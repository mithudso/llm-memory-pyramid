# llm-memory-pyramid

NapMem: a 4-layer multi-granularity memory pyramid for LLM agents. Distills raw
session logs and memory files into deduplicated atomic records, thematic topic
tracks, and high-level user/system profiles — with full provenance back to the
raw source — then serves them through active, tool-driven retrieval instead of
passive context dumping.

## The pyramid

| Layer | Contents | Built by |
|---|---|---|
| 3 | User & system profiles (traits, constraints, goals) | `rebuild_higher_layers()` |
| 2 | Topic tracks (thematic clusters with summaries) | `rebuild_higher_layers()` |
| 1 | Atomic memory records (document-distiller taxonomy, deduped) | `extract_atomic_units()` |
| 0 | Raw conversations & source anchors | `ingest_session()` |

Re-ingesting a session (same `session_id`) replaces that session's Layer 1
records with stable record IDs, then rebuilds Layers 2–3 from the survivors.

## Quick start

```bash
# Distill one memory file into the pyramid store
python3 memory_pyramid_distiller.py --input sample_agent_memory.md

# Watch a directory and consolidate in the background ("naptime")
python3 naptime_consolidator.py --watch-dir ./memory_logs --once

# Query the pyramid
python3 napmem_retrieval_agent.py --query "architecture" --layer all
python3 napmem_retrieval_agent.py --query "editor prefs" --semantic --top-k 5
python3 napmem_retrieval_agent.py --provenance rec_sess_sample_agent_memory_001
python3 napmem_retrieval_agent.py --stats

# Production extraction via the Anthropic Batches API (needs `pip install anthropic`)
python3 llm_extractor.py --input memory_logs/notes.md --semantic-dedup

# Run the test suite
python3 -m unittest discover -s . -p "test_*.py"
```

The package requires Python 3.11+ and the shared `ollama-client` library.
Install into a virtual environment before running the full suite:

```bash
python3 -m venv .venv
.venv/bin/python -m pip install -e .
source .venv/bin/activate
```

Git access to `mithudso/ollama-client` is required. The heuristic distiller
and substring retrieval use only the standard library. Install `.[llm]` to
use Anthropic extraction. Ollama extraction and real embeddings need a
configured Ollama server; the hashed-TF embedding backend runs offline.

## MCP server

`napmem_mcp_server.py` exposes the retrieval tools to Claude Code / Claude
Desktop over MCP stdio (registered in `.mcp.json`) — agents probe memory with
targeted queries instead of loading raw logs. See [docs/MCP.md](docs/MCP.md).
`.mcp.json` runs the failover proxy: remote SSH is primary and a local mirror
is the fallback. The local example store is separate; see `CLAUDE.md`.

## Components

| File | Purpose |
|---|---|
| `memory_pyramid_distiller.py` | Core distiller: extraction, dedup, session reconciliation, layer rebuild |
| `naptime_consolidator.py` | Background watcher that incrementally re-ingests changed `.md` files |
| `napmem_retrieval_agent.py` | Active retrieval tools: search, provenance, topic tracks, token-savings stats |
| `llm_extraction_prompts.py` | Zero-fabrication LLM extraction prompt templates with injection guards |
| `llm_extractor.py` | Production extraction: Haiku via Anthropic Batches API, schema-validated ingest |
| `semantic_index.py` | Embedding index: Ollama or stdlib hashed-TF backend, cosine search + semantic dedup |
| `napmem_mcp_server.py` | Stdlib MCP stdio server exposing the retrieval tools |
| `napmem_mcp_failover.py` | MCP proxy registered in `.mcp.json`: remote SSH server, local-mirror fallback when it is offline |
| `memory_pyramid_schema.json` | JSON Schema for the pyramid store |
| `napmem_pyramid.json` | Local dev/test example pyramid store — orphaned from `.mcp.json`, which targets the remote production store |
| `test_napmem_pipeline.py` | Core unittest suite; run discovery for all three suites |

## Documentation

- [Architecture](docs/ARCHITECTURE.md) · [Components](docs/COMPONENTS.md) · [Development](docs/DEVELOPMENT.md)
- [Installation](docs/INSTALLATION.md) · [Testing](docs/TESTING.md) · [Security](docs/SECURITY.md)
- [Deployment topology](docs/deployment-topology.md) · [Deploy units](deploy/README.md) · [Security ledger](docs/security-review-ledger.md)
- [External calls](docs/external-calls.md) · [Logging](docs/logging.md) · [Requirements](docs/requirements.md)
- [Integrations](docs/integrations-and-assumptions.md) · [Contributing](CONTRIBUTING.md)
- [Codebase overview](docs/codebase-overview.md) · [Known issues](docs/known-issues.md) · [Onboarding](docs/onboarding.md)
- [Product improvement roadmap](docs/product-roadmap-2026-10-27.md): ranked proposals and acceptance criteria

## License

[Apache 2.0](LICENSE)
