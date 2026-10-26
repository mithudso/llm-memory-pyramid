## Default Execution Strategy

Read relevant source and repository guidance before editing. Run the required
tests after each change set. Use commands and paths established in the repo.
Record requests in `prompts.md`, outcomes and remaining work in `memory.md`,
and increment applicable version and delta fields.

## Build, Test, and Validation Commands

Use the installed virtual environment; setup is in `docs/INSTALLATION.md`.

```bash
python3 -m unittest discover -s . -p "test_*.py"
python3 -m compileall -q .
ruff check .
python3 scripts/repo_docs.py --check
```

## High-level Architecture

`memory_pyramid_distiller.py` owns the store. Extractors feed its ingest API;
reconciliation and dedup preserve identities and provenance before derived
layers rebuild and the store saves atomically. The consolidator tracks source
changes. Retrieval and MCP read the pyramid; semantic retrieval also writes a
disposable embedding cache. The proxy serves a local mirror when SSH fails.

## Key Conventions

- Package support starts at Python 3.11; core code stays stdlib-only.
- Sanctioned integrations are `ollama-client` and the optional `anthropic` SDK.
- Preserve stable record IDs and resolvable duplicate anchors.
- Save stores atomically through the distiller API.
- Rebuild Layers 2–3 from Layer 1; never edit derived state directly.
- Keep untrusted content inside sentinel-guarded prompts.
- Test behavior changes offline with temporary stores and mocked transports.
- Use metadata-only runtime logs; never log memory content or credentials.
- Preserve unrelated work and stage explicit paths.
- Refresh generated maps with `python3 scripts/repo_docs.py` after file changes.
