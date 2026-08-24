# Semantic indexing, hooks, and scripts — full reference

There are **two independent semantic-index systems** running on this machine.
They share nothing except the embedding backend (Ollama) and the fact both
were built by this project's author. Don't conflate them.

| | NapMem memory pyramid | global-ai-hub codebase index |
|---|---|---|
| Indexes | Memory *records* (atomic facts extracted from session logs) | Raw *file contents* of any repo under `$HOME` |
| Canonical store | `/home/mithudso/.napmem/napmem_pyramid.json` (remote, Linux 5080 box) | `~/.global-ai-hub/hub.db` (local SQLite, per-machine, not synced) |
| Embedding model | `mxbai-embed-large` (1024-dim) | `nomic-embed-text` |
| Query transport | SSH to the canonical host, or the `napmem` MCP server | HTTP to `127.0.0.1:8000` (local daemon) |
| Scripts live in | this repo (`llm-memory-pyramid`) | `~/.global-ai-hub/scripts/` |
| Detailed doc | `docs/deployment-topology.md` (this repo) | none — this file |

For the memory-pyramid side's fleet topology, data flow, and security model,
**`docs/deployment-topology.md` in this repo is already the canonical
reference** — read that first. This file adds what that one doesn't cover:
the full `~/.claude/hooks/napmem-*.py` auto-retrieval suite (global, fires in
every Claude Code session on this machine) and the global-ai-hub codebase
indexer it talks to.

## Part 1 — NapMem auto-retrieval hook suite (`~/.claude/hooks/`)

Registered in `~/.claude/settings.json` at **user level** — fires in every
repo, every session, on this machine. Not repo-scoped; nothing to opt into
per-project. Global kill switch: `NAPMEM_HOOK_DISABLE=1`.

| Hook file | Event | Matcher | Does |
|---|---|---|---|
| `napmem-session-brief.py` | `SessionStart` | — | One SSH pull of the canonical pyramid's top layers (biggest topic tracks, all profile traits) per session. Cached 30 min (`BRIEF_TTL_S`); serves stale cache marked as such on SSH failure. |
| `napmem-index-kick.py` | `SessionStart` | — | Adds the session's repo root to the **hub-daemon's** watch list and pings `/index-tree` on it. This is the global-ai-hub *codebase* indexer, not the memory pyramid — see Part 2. Also kicks the usage predictor. |
| `napmem-context-hook.py` | `UserPromptSubmit` | every prompt | The main auto-retrieval hook: embeds the prompt locally, semantic-searches the canonical pyramid over SSH (with a local query cache), filters by the keep-rule below, and also checks the repo's `docs/high_signal_file_index.json` + `CLAUDE.md` commands block, plus the hub-daemon's file-level search. Injects up to 3 lines as `[napmem-auto]` context. |
| `napmem-pretool-hook.py` | `PreToolUse` | `Edit\|Write\|MultiEdit\|NotebookEdit\|Bash` | On the *first* touch of a file this session, or the first `git commit/push/merge/rebase/revert` per (repo, verb), surfaces past decisions/gotchas via the same SSH semantic search, stricter floor (`PRETOOL_FLOOR = 0.68`). Emits `hookSpecificOutput.additionalContext`, never a permission decision. Per-session dedup cache makes repeat touches free. |
| `napmem-access-hook.py` | `PostToolUse` | `Read\|Edit\|Write\|MultiEdit\|NotebookEdit` | Async usage-pattern sensor for the codebase indexer: logs every file access to `~/.napmem/logs/file-access.jsonl`, submits the file to the hub-daemon's `/index`, spools to a spillover queue if the daemon is down, and kicks the usage predictor roughly every 20th event. |
| `napmem-usage-predictor.py` | not a hook — spawned detached by the two hooks above | — | Frequency-recency model (`exp(-age/3d)`) over the access log. Re-submits the top 30 hottest files, adds the top 3 hottest repos to the hub's watch list, and asks the daemon to `/index-tree` the single hottest repo. Lockfile-serialized, ~2 min minimum gap between runs. |
| `napmem-retrieval-monitor.py` | offline CLI, not a hook | — | Replays the context-hook's keep-rule over the logged candidate history (`~/.napmem/logs/auto-retrieval.jsonl`) to recommend threshold changes. `--tail N`, `--sweep`, `--days N`. |

### Shared tuning surface (`napmem_hook_lib.py`)

All hooks import this one module; every constant below is a named tunable the
monitor references directly.

| Constant | Value | Meaning |
|---|---|---|
| `SCORE_FLOOR` | 0.65 | Min cosine for a candidate that also has keyword overlap |
| `STRONG_SCORE` | 0.75 | Cosine above which overlap is no longer required |
| `PRETOOL_FLOOR` | 0.68 | Same as `SCORE_FLOOR` but for the PreToolUse hook |
| `OVERLAP_MIN` | 1 | Content-word overlap required in the mid-band |
| `MIN_TEXT_LEN` | 15 chars | Kills one-word heuristic fragments |
| `INJECT_MAX` | 3 | Max memory lines injected per prompt event |
| `FETCH_TOP_K` | 8 | Fetched from remote (more than `INJECT_MAX` so near-misses get logged) |
| `CACHE_SIM` | 0.90 | Query-embedding cosine to reuse a cached remote result |
| `CACHE_TTL_S` | 3600 | Query cache TTL (matches the hourly consolidation cadence) |
| `SSH_TIMEOUT_S` | 3.5 | Per-hook SSH round-trip budget |
| `EMBED_TIMEOUT_S` | 2.0 | Local Ollama embed cap — abandon rather than block on a cold model load |

**Keep rule** (`keep_candidate`, replayed identically by the offline monitor):
`len >= MIN_TEXT_LEN AND (score >= STRONG_SCORE OR (score >= SCORE_FLOOR AND overlap >= OVERLAP_MIN))`.

Design rules stated in the module docstring: never raise out of a hook (a
broken hook degrades to "no context," never a visible error); every
retrieval decision is logged with the full candidate list so thresholds can
be re-tuned offline without re-querying.

### Transport

Both the session-brief and per-prompt/pretool hooks reach the canonical
pyramid the same way as the `napmem` MCP server does post-this-repo's
`.mcp.json` change (see the commit that retargeted it): SSH to
`mithudso@192.168.4.75` with a persistent `ControlMaster` (`ControlPersist=120`,
socket `/tmp/napmem-ssh-ctrl-%C`), running `napmem_retrieval_agent.py
--semantic` remotely against `/home/mithudso/.napmem/napmem_pyramid.json`.
The session-brief hook's SSH call pre-warms the control socket that the
per-prompt/pretool hooks then reuse for free.

## Part 2 — global-ai-hub codebase indexer (separate system)

Lives in `~/.global-ai-hub/scripts/`, indexes **file contents** (not memory
records) across every repo under `$HOME`, and is talked to over HTTP by three
of the hooks above (`napmem-index-kick.py`, `napmem-access-hook.py`,
`napmem-usage-predictor.py`).

- **`hub-daemon.py`** — FastAPI server on `127.0.0.1:8000` + a background
  idle-indexer thread. Endpoints:
  - `POST /index {path}` — index one file (background task)
  - `POST /index-tree {root, max_files?}` — walk a dir, index freshest-first, capped at 2000 files/call (default 400)
  - `POST /search {query, prefix?, top?}` — embed the query, cosine against stored vectors, optionally bounded to a path `prefix` (repo root)
  - `GET /health` — file/embedding counts, model, uptime
  - Idle loop: every `sleep_idle_check` (default 60s) while load average is
    below `idle_threshold` (default 2.0), walks every dir in
    `~/.global-ai-hub/watch_dirs.txt` and indexes anything stale, GC'ing dead
    entries every 10 passes.
  - Embedding model: `nomic-embed-text` (config default in `hub_lib.py`).
  - Path guard: every path must resolve under `$HOME`, excluding
    `Library/Applications/.Trash` and hidden dirs other than
    `.global-ai-hub/.claude/.gemini/.napmem/.remember` — added after an
    earlier bug indexed all of `/Applications`.
  - Storage: SQLite at `~/.global-ai-hub/hub.db` (per-machine, local only —
    unlike the memory pyramid this is **not** synced to a canonical remote).
- **`pipeline_manager.py`** — reads `~/.global-ai-hub/predictor_state.json`
  (written by the usage predictor) for `repo-status` reporting.
- **`hub_manager`** — interactive TUI for starting/stopping the daemon,
  viewing health.

**Known gap (found while compiling this doc, 2026-08-24):** the daemon is
**not currently running** on this Mac (`curl 127.0.0.1:8000/health` refuses,
no `hub-daemon.py` process, no launchd job registered under any
`com.global-ai*`/`*hub-daemon*` name). Every hook that talks to it
(`napmem-index-kick.py`, `napmem-access-hook.py`, `napmem-usage-predictor.py`)
is silently no-oping by design (all wrapped in bare `try/except`) — codebase
indexing and the file-search line in `[napmem-auto]` context blocks simply
don't fire until the daemon is started manually via `hub_manager` or
`python3 ~/.global-ai-hub/scripts/hub-daemon.py`. The memory-pyramid hooks
(session-brief, context-hook's SSH path, pretool-hook) are unaffected — they
don't depend on this daemon.

## Part 3 — this repo's own semantic-indexing scripts

Documented in `CLAUDE.md`/`README.md`; rules not spelled out there:

| Script | Rule |
|---|---|
| `semantic_index.py` | `SemanticIndex` caches one embedding per record in `<pyramid>.embindex.json`, keyed by id+text hash. Backend: `OllamaBackend.probe()` tries a weighted host list (`NAPMEM_OLLAMA_URL(S)`, default `mxbai-embed-large`) in order, falling back to a stdlib hashed-TF backend (512-dim, `hashed-tf-512`) if every host is unreachable. A backend/model switch invalidates the whole cache (checked via `cache["model"]`). |
| `nearest_record_id` / `nearest_many` | Cosine similarity against all record vectors; returns the best match only if `score >= threshold`. |
| `memory_pyramid_distiller.py` | `semantic_threshold = 0.92` default, `semantic_dedup = False` default — semantic dedup is opt-in and does **not** run in the default pipeline (project invariant: default pipeline must stay deterministic). Exact-text dedup (lowercased, stripped) is what always runs. |
| `naptime_consolidator.py` | `--semantic-dedup` CLI flag, same opt-in default. |

## Where each thing actually points, right now

- **`.mcp.json`** (this repo) → remote canonical pyramid over SSH, since the
  `worktree-napmem-remote-mcp` merge (PR #7, 2026-08-24).
- **Global `~/.claude/hooks/napmem-*.py`** → same remote canonical pyramid,
  already were before this repo's `.mcp.json` was retargeted — these were
  never pointed at this repo's local file.
- **This repo's local `napmem_pyramid.json`** → orphaned dev/test store, used
  by nothing above. See the note in `CLAUDE.md`'s architecture section.
- **global-ai-hub codebase index** → separate system, separate store, not
  currently running (see Known gap above).

## Operational commands

| What | Command |
|---|---|
| Tune the auto-retrieval hooks | `python3 ~/.claude/hooks/napmem-retrieval-monitor.py` (add `--sweep` for the full threshold table, `--tail 15` to eyeball recent injections) |
| Disable the whole hook suite | `export NAPMEM_HOOK_DISABLE=1` |
| Start the codebase-index daemon | `python3 ~/.global-ai-hub/scripts/hub-daemon.py` or via `hub_manager`'s Health tab |
| Check codebase-index daemon health | `curl -s http://127.0.0.1:8000/health` |
| Rebuild this repo's local semantic index | `python3 semantic_index.py --pyramid napmem_pyramid.json --rebuild` |
| Query the canonical pyramid directly | `python3 napmem_retrieval_agent.py --pyramid ~/.napmem/napmem_pyramid.json --query <q> --semantic` (works unmodified only on the Linux box or over the SSH transport the hooks use) |
