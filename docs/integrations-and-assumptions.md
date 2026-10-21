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
  → silent fallback to the stdlib hashed-TF backend. Note: a host is only
  poolable if its Ollama listens on the LAN (`OLLAMA_HOST=0.0.0.0`).

## Environment variables

| Var | Used by | Meaning |
|---|---|---|
| `NAPMEM_EMBED_BACKEND` | `semantic_index.py` | Force `ollama` or `hashed` (default: auto-probe) |
| `NAPMEM_OLLAMA_URLS` | `semantic_index.py` | Comma-separated `url=weight` pool (no built-in default: unset falls back to the ollama-client env `OLLAMA_URLS`, then `OLLAMA_HOST`, then `http://127.0.0.1:11434`) |
| `NAPMEM_OLLAMA_URL` / `NAPMEM_OLLAMA_MODEL` | `semantic_index.py` | Single-host override of the chain / embedding model (default `mxbai-embed-large`) |
| `NAPMEM_PYRAMID` | `napmem_mcp_server.py` | Default pyramid store path |
| `ANTHROPIC_API_KEY` (et al.) | `anthropic` SDK | Standard SDK credential resolution; never read directly by repo code |

## Hardcoded assumptions

- Store path defaults to `napmem_pyramid.json` in CWD (override: `--pyramid`).
- Watch dir defaults to `./memory_logs`; only `*.md` files are consolidated.
- Session IDs derive from file basenames (`sess_<basename>`); renaming a file
  creates a new session rather than replacing the old one.
- Token estimates use a fixed ~0.75 words/token ratio (`* 1.33`).
- Single-writer: exactly one consolidator/distiller process per store at a
  time; atomicity protects against crashes, not concurrent writers.
- Record ID format `rec_<session>_<NNN>` with 3-digit zero padding (grows past
  999 without collision — `isdigit()` parse, not fixed-width).

## Environment differences

None known — pure-stdlib code, exercised on macOS (dev) and ubuntu-latest
(CI), Python 3.10–3.14.
