# External calls

## Inventory

| # | Call | File | Transport | Error handling | Retry | Logged | Tested |
|---|---|---|---|---|---|---|---|
| 1 | Anthropic Messages API (`messages.create`) | `llm_extractor.py` (`extract_direct`) | HTTPS via `anthropic` SDK | Typed exception chain (RateLimit → APIStatus → APIConnection) → `ExtractionError`, session skipped | SDK default (2 retries, backoff on 429/5xx) | request outcome + token usage at INFO, failures at ERROR | Parsing/validation layer tested offline; live call not tested in CI (no network) |
| 2 | Anthropic Message Batches API (`batches.create/retrieve/results`) | `llm_extractor.py` (`extract_batch`) | HTTPS via `anthropic` SDK | Per-item failures logged and omitted; poll timeout raises `ExtractionError` | SDK default + 1h poll deadline | batch id, per-item usage, failures | Same as above |
| 3 | Ollama local embeddings (`/api/embed`, `/api/tags` probe) | `semantic_index.py` (`OllamaBackend`) | HTTP (localhost) via `urllib` | Probe failure → silent fallback to stdlib hashed backend; embed failure → `RuntimeError` → substring fallback in retrieval agent | None (fallback instead) | probe failures at DEBUG, embed failures at ERROR via caller | Fallback path tested; live Ollama not tested in CI |

All calls are optional: the core pipeline (heuristic extractor, substring
search) runs with zero external calls and zero dependencies.

## 5-standard contract status

- **CLI trigger** — ✅ all three reachable via `llm_extractor.py` / `semantic_index.py` CLIs.
- **Centralized error log** — ✅ stdlib `logging`, per `docs/logging.md`.
- **Auto-remediation map** — ✅ SDK retries + poll deadline (Anthropic); backend fallback chain ollama → hashed → substring (embeddings).
- **Dashboard card** — ❌ N/A: no dashboard exists in this repo. TODO if one is added.
- **Datastore verification** — ✅ extractor output schema-validated (`validate_unit`) before any store write; invalid units rejected and logged.

## Credentials

`llm_extractor.py` uses the `anthropic` SDK's standard resolution
(`ANTHROPIC_API_KEY` or an `ant auth login` profile). No credential is read or
stored by this repo's code directly. Ollama is unauthenticated localhost.
