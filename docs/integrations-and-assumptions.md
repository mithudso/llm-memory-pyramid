# Integrations and assumptions

## External services

All optional — the core pipeline runs with zero external calls. Full
inventory with error/retry/logging status: `docs/external-calls.md`.

- **Anthropic API** (`llm_extractor.py`): Messages + Message Batches for LLM
  extraction. Credential via the SDK's standard resolution; `anthropic`
  package lazy-imported.
- **Ollama** (`semantic_index.py`): `/api/embed` for real embeddings with a
  host failover chain — the remote server `http://192.168.4.75:11434` is
  probed first, local `http://localhost:11434` is the backup; both serve
  `mxbai-embed-large` (same model on both keeps the vector cache valid across
  failover). If neither responds, silent fallback to the stdlib hashed-TF
  backend.

## Environment variables

| Var | Used by | Meaning |
|---|---|---|
| `NAPMEM_EMBED_BACKEND` | `semantic_index.py` | Force `ollama` or `hashed` (default: auto-probe) |
| `NAPMEM_OLLAMA_URLS` | `semantic_index.py` | Comma-separated failover chain (default `http://192.168.4.75:11434,http://localhost:11434`) |
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
