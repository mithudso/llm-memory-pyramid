# Deployment topology and build history

The live NapMem deployment across the three-machine fleet, and the full build
log of how it got here (all on 2026-08-20).

## Fleet

| Machine | Role | Details |
|---|---|---|
| **Linux 5080 box** (`mithudso@192.168.4.75`, NUC15) | **Canonical consolidator + heavy embedding** | systemd user units `napmem-consolidator.{service,timer}` (hourly, `Persistent`, linger enabled — survives logout/reboot); repo at `~/dev/llm-memory-pyramid`; store at `~/.napmem/napmem_pyramid.json`; `anthropic` 1.0.0; `ant` via linuxbrew, OAuth profile active. Syncthing hub — sees both laptops' memory files. Ollama weight 4. |
| **M5 Max MBP** (`mitch@192.168.4.1`, 64 GB) | Embedding pool member | Ollama exposed on the LAN (app setting `settings.expose=1` in its sqlite — the app ignores `OLLAMA_HOST`); serves `mxbai-embed-large`. Weight 2. |
| **M3 work laptop** (this repo's original home) | Client + light embedding | launchd consolidator retired; user-scope MCP server `napmem` reaches the canonical store over ssh-stdio (deploy key `~/.napmem/keys/linux_deploy`; pubkey installed on the box). Local Ollama loopback-only, weight 1 for locally-initiated queries. |

Every pool host serves the same embedding model (`mxbai-embed-large`,
1024-dim) — a model switch invalidates the vector cache, so failover between
hosts is cache-free only because the model matches everywhere.

## Data flow

```
~/.claude/projects/*/memory/*.md ┐  (Syncthing, all machines)
~/.gemini/antigravity/brain/*/*.md ┤
/Volumes/mitch twins (keep-existing) ┘
        │  scripts/run-naptime.sh mirror (symlinks, sync-conflict skip,
        │  out-of-root refusal + revocation, NAPMEM_ALLOWED_ROOTS export)
        ▼
~/.napmem/memory_logs/ ──▶ naptime_consolidator.py (hourly systemd sweep)
        │   LLM mode: one Message Batches request per sweep (claude-haiku-4-5,
        │   50% batch pricing); per-file heuristic fallback on ANY failure
        ▼
~/.napmem/napmem_pyramid.json (single-writer, atomic replace)
        │                                   ▲
        │ semantic dedup (batched embeds    │ ssh-stdio MCP from other
        │ via the Ollama pool, opt-in)      │ machines (napmem server)
        ▼                                   │
<store>.embindex.json (per-PID tmp writes, disposable/corrupt-tolerant)
```

## Security model (see also docs/SECURITY.md, docs/security-review-ledger.md)

- **Consent boundary** = the mirror. Everything swept egresses to the
  Anthropic API (LLM extraction, TLS) and the Ollama hosts (embeddings, plain
  LAN HTTP).
- **Exfiltration guards**, three layers: mirror-time root resolution with
  link revocation → **race-free fd-based read guard** in the consolidator
  (kernel-reported fd path via `F_GETPATH`/procfs; fail-closed default — the
  watch dir is the sole root when `NAPMEM_ALLOWED_ROOTS` is unset; explicit
  `off` to disable; unverifiable fd paths refuse) → schema validation before
  any store write.
- **Cache poisoning**: Ollama embed responses strictly validated
  (numeric-only, consistent dimension) before entering the persistent cache.
- **Credentials**: `ant auth login` OAuth profiles per machine; no keys in
  any repo, plist, or unit file. The M3→Linux deploy key is a dedicated
  ed25519 keypair outside `~/.ssh`.

## Canonical store contents (as of the migration sweep)

143 sessions (142 LLM-extracted, 1 heuristic fallback on an invalid-JSON
model output) → 2,043 atomic records, 1,523 topic tracks, 702 profile traits.
The M3's earlier store (157 sessions / 2,442 records — it included that box's
`/Volumes/mitch` mounts) remains on the M3 as a stale read replica; the Linux
store is canonical.

## Build history (2026-08-20, chronological)

1. **Bootstrap** — repo verified (9 tests), published to
   github.com/mithudso/llm-memory-pyramid, brought to mdb-tam standard.
2. **Production path** — `llm_extractor.py` (Batches API + schema gate),
   `semantic_index.py` (embeddings + semantic dedup), `napmem_mcp_server.py`
   (stdlib MCP stdio). Tests 9 → 19.
3. **Consolidator wiring + failover** — `--extraction auto|llm|heuristic`,
   sweep-level batching, Ollama host failover, `mxbai-embed-large` pulled
   locally for model parity. Tests → 26.
4. **`anthropic` installed** — exposed a latent bug (missing credential
   raises `TypeError` at call time); fallback hardened. Security review:
   data-egress threat model rewritten, embed-response validation added.
   Tests → 28.
5. **launchd deployment** — `ant` CLI + OAuth login, hourly agent, real
   Batches extraction verified end-to-end (after an org-credits detour).
6. **Real memory ingestion** — project-prefixed symlink mirror; batch
   `custom_id` 64-char cap fixed (index-mapped ids). Security findings fixed
   as they were raised: `--` end-of-options, symlink exfiltration guard,
   TOCTOU fd-guard, fail-closed default, fd-path-unverifiable refusal;
   `docs/security-review-ledger.md` records all dispositions. Tests → 35.
7. **Fleet pool** — capacity-weighted multi-host Ollama pool (parallel
   chunk dispatch, per-chunk failover); batched semantic dedup (one embed
   round-trip per merge, ~10x sweep speedup); index cache made concurrent-
   writer-safe (per-PID tmps) and corrupt-tolerant after a live two-writer
   race corrupted it. Tests → 38.
8. **Antigravity + volume sources** — brain artifacts mirrored
   (uuid-prefixed), mounted twins in keep-existing mode, sync-conflict
   copies skipped.
9. **Migration** — wrapper ported to portable bash, systemd units added,
   canonical consolidator moved to the Linux box, M3 cut over to ssh-stdio
   MCP, M5 Max added to the pool, `global-ai-hub` pushed to GitHub
   (skills/ as submodule).

## Operational commands

| Where | Command |
|---|---|
| Linux | `systemctl --user start napmem-consolidator.service` — sweep now |
| Linux | `journalctl --user -u napmem-consolidator.service -f` — watch |
| Linux | `systemctl --user list-timers napmem-consolidator.timer` — next run |
| M3 | MCP `napmem` (user scope) — query canonical store from any session |
| Any | `python3 napmem_retrieval_agent.py --pyramid <store> --query <q> --semantic` |

## Known deltas / future work

- M3 and M5 local Ollama daemons are loopback-only from the LAN's
  perspective (M5 was exposed via the app toggle; M3 remains loopback — only
  its own queries use it, weight 1).
- The M3's stale local store could be deleted or refreshed by pointing its
  retrieval at the canonical box (already the default via MCP).
- Submit-now/collect-later batch mode (`memory.md` next-steps) would let
  sweeps return immediately instead of polling.
