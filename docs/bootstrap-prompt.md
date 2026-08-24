# Bootstrap prompt: recreate the NapMem memory pyramid + semantic indexing

Copy-paste prompt for another user to hand to a fresh Claude Code session
(base install, no prior context) to implement the same system documented in
`docs/ARCHITECTURE.md`, `docs/deployment-topology.md`, and
`docs/semantic-indexing-and-hooks-reference.md`. Phases are independently
useful — stop after any phase and use what exists.

---

```
Task: Implement a portable, zero-API-cost-capable LLM memory system —
"NapMem" — from a base Claude Code install. Work through the phases below
in order; each is independently useful, so it's fine to stop after any
phase and use what exists. Use your worktree-isolation mechanism before
any code/config edit if you have one.

=====================================================================
PHASE 1 (required) — Core memory pyramid
=====================================================================
This already exists as a public, tested reference implementation. Don't
reimplement it from scratch — clone and verify it:

  git clone https://github.com/mithudso/llm-memory-pyramid.git
  cd llm-memory-pyramid
  python3 -m unittest discover -s . -p "test_*.py"
    # expect "Ran 38 tests ... OK"
  python3 memory_pyramid_distiller.py --input sample_agent_memory.md \
      --pyramid /tmp/verify_pyramid.json
    # expect "Successfully distilled N atomic units ..."

Read, in this order, to understand what you now have: README.md,
docs/onboarding.md, docs/ARCHITECTURE.md, docs/COMPONENTS.md, CLAUDE.md
(especially its "Invariants — do not break" section — the 4-layer model,
stable record IDs across re-ingestion, exact-text dedup, atomic store
writes, and the untrusted-content sentinel-delimiter rule all matter and
are already implemented; don't relax them).

The four layers: raw session logs -> atomic memory records (Layer 1) ->
topic tracks (Layer 2, derived) -> user profile traits (Layer 3, derived).
Layers 2-3 are always rebuilt from Layer 1, never hand-edited. Extraction
has three interchangeable backends selectable per-run
(`--extraction auto|llm|ollama|heuristic`): Anthropic Batches API
(cheapest per-token, needs API credits), local Ollama chat models (zero
API spend), and a network-free heuristic fallback. Pick based on whether
the receiving user has Anthropic API access.

=====================================================================
PHASE 2 (required for zero-cost operation) — Ollama setup
=====================================================================
  1. Install/confirm Ollama is running: `ollama --version`,
     `pgrep -fl "ollama serve"` (or start it).
  2. Check what models this repo's scripts actually default to before
     pulling anything — grep `DEFAULT_CHAT_HOSTS` in ollama_extractor.py
     and `OLLAMA_MODEL` in semantic_index.py (defaults may drift; read the
     current values, don't assume they match what's below).
     As of this writing: chat `qwen3.5:35b` (needs ~23GB disk, a large
     download — confirm with the user before pulling if disk/bandwidth is
     a concern), embed `mxbai-embed-large` (~670MB).
  3. `ollama pull <chat-model>` and `ollama pull <embed-model>` for
     whatever's missing from `ollama list`.
  4. Verify each actually works — don't trust the pull exit code alone:
     - embed: POST a test string to `http://localhost:11434/api/embeddings`
     - chat: run it through the repo's own code path, e.g.
       `python3 -c "import ollama_extractor as oe; h=oe.parse_chat_hosts(); \
        print(oe._chat_once(h[0][0], h[0][1], 'reply OK'))"`
  5. Run a real sweep to confirm end-to-end: `python3 naptime_consolidator.py
     --watch-dir ./memory_logs --once --extraction ollama` (guarantees zero
     Anthropic API spend).

=====================================================================
PHASE 3 (required) — Wire up the MCP server for Claude Code
=====================================================================
The repo ships `napmem_mcp_server.py`, a stdlib MCP stdio server exposing
retrieval tools (search_memory, get_topic_track, inspect_provenance,
memory_stats). It reads its store path from `--pyramid` or the
`NAPMEM_PYRAMID` env var (check napmem_mcp_server.py's argparse to
confirm this is still true).

Decide up front: single-machine (store stays local to this checkout) or
multi-machine (one canonical store on a host, other machines/sessions
reach it remotely)? For single-machine, `.mcp.json` can point straight at
the local file:

  {
    "mcpServers": {
      "napmem": {
        "command": "python3",
        "args": ["napmem_mcp_server.py"],
        "env": { "NAPMEM_PYRAMID": "napmem_pyramid.json" }
      }
    }
  }

For multi-machine, proxy over SSH instead (adjust host/paths/model to the
actual deployment — do not hardcode someone else's IP or username):

  {
    "mcpServers": {
      "napmem": {
        "command": "ssh",
        "args": [
          "-o", "ControlMaster=auto",
          "-o", "ControlPath=/tmp/napmem-ssh-ctrl-%C",
          "-o", "ControlPersist=10m",
          "<user>@<canonical-host>",
          "cd <remote-repo-path> && NAPMEM_PYRAMID=<remote-pyramid-path> python3 napmem_mcp_server.py"
        ]
      }
    }
  }

Smoke-test before trusting it: pipe a raw MCP `initialize` JSON-RPC
request (protocolVersion "2025-06-18") into the exact command from
`.mcp.json` via stdin, capture stdout, confirm a valid JSON-RPC result and
a server log line naming the pyramid path you expected — not a fallback
default.

=====================================================================
PHASE 4 (optional, advanced) — Claude Code auto-retrieval hook suite
=====================================================================
This makes memory retrieval automatic instead of relying on the model to
call the MCP tools. It's a separate concern from Phases 1-3 — build it
only if the receiving user wants every Claude Code session/prompt to
auto-pull relevant memory without being asked. Functional spec (design
proven in production; keep these properties, adapt paths/hosts to the new
environment):

Shared module (e.g. `napmem_hook_lib.py`, imported by every hook below):
  - Tunable constants, all named, all in one place: a cosine-similarity
    "strong" threshold above which a candidate is kept regardless of
    keyword overlap (~0.75), a lower "floor" threshold that additionally
    requires >=1 shared content word with the query (~0.65), a minimum
    text length to reject one-word fragments (~15 chars), a max-injected
    count per event (~3), and a larger fetch count (~8) so near-misses
    below the floor get logged for later threshold tuning.
  - A `keep_candidate(feat)` function implementing that rule exactly once,
    imported by both the live hooks AND an offline analysis tool — the
    two must never drift apart.
  - Every hook logs its full candidate list (not just what it kept) to a
    JSONL file, size-rotated, so thresholds can be re-tuned by replaying
    old traffic without re-querying anything live.
  - A local query-embedding cache (cosine similarity against recent
    queries, TTL matching your ingestion cadence) so near-duplicate
    prompts skip the remote round-trip.
  - A single kill-switch env var that disables the entire suite.
  - Every hook wrapped in bare try/except at the top level: a broken hook
    must degrade to silence, never to a visible error on every prompt.

Hooks to build (Claude Code hook events in parens):
  1. Session-brief (SessionStart) — one pull per session of the pyramid's
     coarse standing picture (top topic tracks, all profile traits),
     cached with a TTL matching your ingestion cadence so short sessions
     benefit even if no individual prompt trips the semantic floor.
  2. Per-prompt context (UserPromptSubmit) — embed the prompt, check the
     cache, semantic-search the store on miss, apply the keep rule, print
     up to N lines as injected context. Also worth layering in: a
     keyword match against any per-repo "high signal file index" and the
     current repo's CLAUDE.md commands block, so script/invocation
     pointers surface alongside memory.
  3. Pre-tool decision surfacing (PreToolUse on Edit/Write/Bash) — on the
     FIRST touch of a given file per session, or the first
     commit/push/merge/rebase/revert per (repo, verb) per session, query
     for past decisions/gotchas about that file or that repo+verb. Use a
     per-session dedup cache so repeat touches are free. Emit as
     `hookSpecificOutput.additionalContext`, never as a permission
     decision — this hook must not affect the permission flow.
  4. Offline tuning monitor (a plain CLI, not a hook) — replays the exact
     `keep_candidate` rule over the logged candidate history under a grid
     of threshold values, reports trivial-prompt firing rate (target
     ~0%), substantive-prompt firing rate (target 25-75%), and a junk
     rate among injected candidates, then recommends constant edits.

Register hooks in the Claude Code settings that apply at whatever scope
you want (user-level for "every repo, every session" — verify against
current Claude Code hook documentation, since matcher syntax and
settings file location can change between versions).

=====================================================================
PHASE 5 (optional, advanced) — Separate codebase-content indexer
=====================================================================
Distinct system from Phases 1-4: indexes raw file *contents* across repos
(not memory records) for semantic file search, so hooks like the
pretool/per-prompt ones above can also surface "files related to this
prompt," not just memory records. Build only if wanted; keep it
architecturally separate from the memory pyramid (different store,
can be a different embedding model, no shared code).

  - A small local HTTP daemon (e.g. FastAPI on 127.0.0.1) with endpoints:
    `POST /index {path}` (index one file, background task), `POST
    /index-tree {root, max_files?}` (walk a dir, freshest-first, hard cap
    per call so one huge repo can't monopolize it), `POST /search {query,
    prefix?, top?}` (embed + cosine, optionally bounded to a path prefix
    so per-repo hooks stay fast against a large global store), `GET
    /health`.
  - A background idle-indexer thread: only walks watched directories when
    system load is below a threshold, sleeps otherwise, periodically
    garbage-collects stale entries.
  - A hard path guard on every write path: only index files under the
    user's home directory, explicitly excluding system/vendor/cache
    trees — an earlier version of this pattern once indexed all of
    /Applications by accident; don't repeat that.
  - A watch-list file the idle loop reads, auto-appended to by session
    hooks (index whatever repo the user is currently working in) and by
    a lightweight usage predictor (frequency-recency scoring over a file
    access log, so "hot" files/repos stay freshly indexed without a full
    re-walk).
  - If you build this, verify at the end that the daemon is actually
    running (`curl` its health endpoint) — hooks that depend on it are
    typically designed to fail silently, so a stopped daemon produces no
    visible error, only silently-missing context.

=====================================================================
PHASE 6 (required if you want ongoing ingestion, not just one-off) —
Automate the consolidator
=====================================================================
`naptime_consolidator.py --watch-dir <dir> --once` does one sweep; for
continuous operation, schedule it (launchd on macOS / systemd --user
timer on Linux / cron as a fallback) at whatever interval matches your
memory-log write frequency (hourly is a reasonable default). Confirm the
persistent sweep-state file (`<pyramid>.sweepstate.json`) is doing its job
by touching-but-not-changing a watched file and confirming a re-run
skips re-extraction.

=====================================================================
Final report
=====================================================================
State: which phases you completed, which models you pulled (name + size),
what the MCP server's `.mcp.json` actually points at (local file or
remote host — name it), test suite pass count, and — if you built Phase
4/5 — confirmation the hooks fire (show one real log line from each) and
whether Phase 5's daemon is actually running right now, not just
configured to run.
```
