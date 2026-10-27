# Integrations and assumptions

## External services

All optional — the core pipeline runs with zero external calls. Full
inventory with error/retry/logging status: `docs/external-calls.md`.

- **Anthropic API** (`llm_extractor.py`): Messages + Message Batches for LLM
  extraction. Credential via the SDK's standard resolution; `anthropic`
  package lazy-imported.
- **Ollama** (`semantic_index.py`): `/api/embed` via a capacity-weighted pool.
  Transport is the shared `ollama-client` library. No fleet is hardcoded:
  set `NAPMEM_OLLAMA_URLS` (see `deploy/napmem-consolidator.service`); unset
  falls back to `OLLAMA_URLS`/`OLLAMA_HOST`, then `http://127.0.0.1:11434`.
  Live hosts share batches proportionally to weight; a host failing
  mid-batch has its chunk retried elsewhere and cools down for 30 s
  (`OLLAMA_COOLDOWN`). Every host must serve `mxbai-embed-large` — same model
  everywhere keeps the vector cache valid across failover. No host responding
  → fallback to the stdlib hashed-TF backend. Note: a host is only
  poolable if its Ollama listens on the LAN (`OLLAMA_HOST=0.0.0.0`).

- **Ollama chat** (`ollama_extractor.py`): `NAPMEM_OLLAMA_CHAT` is a
  comma-separated `url=model` chain. `--extraction auto` tries it after
  Anthropic; `--extraction ollama` never calls Anthropic.
- **SSH and local subprocesses** (`napmem_mcp_failover.py`): the proxy reads
  remote configuration, relays MCP and refreshes a local mirror. It uses
  fixed local filenames even when the configured remote store has another
  basename. Offline tests substitute fake local children and mocked copies.

## Environment variables

| Var | Used by | Meaning |
|---|---|---|
| `NAPMEM_EMBED_BACKEND` | `semantic_index.py` | Force `ollama` or `hashed` (default: auto-probe) |
| `NAPMEM_OLLAMA_URLS` | `semantic_index.py` | Comma-separated `url=weight` pool (no built-in default: unset falls back to the ollama-client env `OLLAMA_URLS`, then `OLLAMA_HOST`, then `http://127.0.0.1:11434`) |
| `NAPMEM_OLLAMA_URL` / `NAPMEM_OLLAMA_MODEL` | `semantic_index.py` | Single-host override of the chain / embedding model (default `mxbai-embed-large`) |
| `NAPMEM_PYRAMID` | `napmem_mcp_server.py` | Default pyramid store path |
| `ANTHROPIC_API_KEY` (et al.) | `anthropic` SDK | Standard SDK credential resolution; never read directly by repo code |

## Hardcoded assumptions

- Portable CLI defaults to the platform user data directory. Legacy direct
  modules retain CWD defaults; use explicit `--pyramid` for those entrypoints.
- Watch dir defaults to `./memory_logs`; only `*.md` files are consolidated.
- Registry identity preserves recognized renames. First IDs remain basename
  compatible; collisions get a hash. Missing sources do not imply deletion.
- Retrieval token estimates use ceil(UTF-8 bytes/4). Legacy word-compression
  estimates use words * 1.33; neither is a measured monetary saving.
- Complete transactions serialize same-host writers. Atomic commits compare
  generation/fingerprint; stale direct saves fail closed.
- Record ID format `rec_<session>_<NNN>` with 3-digit zero padding (grows past
  999 without collision — `isdigit()` parse, not fixed-width).

## Environment differences

Package support starts at Python 3.11; CI covers 3.11, 3.12 and 3.14 on
Ubuntu. Guarded reads use macOS F_GETPATH or Linux procfs and fail closed
where neither is available. The proxy uses POSIX nonblocking pipe I/O.
Windows runtime acceptance is not claimed.

## Complete configuration reference

`.env.example` documents all variables read directly by repository programs,
the wrapper, and CI. It contains placeholders and is not loaded automatically.
Additional proxy controls are `NAPMEM_REMOTE_HOST`, `NAPMEM_REMOTE_PYRAMID`,
`NAPMEM_REMOTE_REPO`, `NAPMEM_MIRROR_DIR`, `NAPMEM_MIRROR_MAX_AGE`,
`NAPMEM_SSH_TIMEOUT`, `NAPMEM_REMOTE_REQUEST_TIMEOUT` and
`NAPMEM_FALLBACK_OLLAMA`. Wrapper controls are `NAPMEM_HOME`, `NAPMEM_REPO`,
`NAPMEM_EXTRACTION` and `NAPMEM_ALLOWED_ROOTS`. Never export the entire example
as a production configuration; choose settings for the operation being run.
