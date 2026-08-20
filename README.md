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

Core pipeline is Python 3.10+ standard library only. Optional extras:
`anthropic` (LLM extraction path) and a local [Ollama](https://ollama.com)
server (real embeddings — otherwise a stdlib hashed-TF backend is used).

## MCP server

`napmem_mcp_server.py` exposes the retrieval tools to Claude Code / Claude
Desktop over MCP stdio (registered in `.mcp.json`) — agents probe memory with
targeted queries instead of loading raw logs. See [docs/MCP.md](docs/MCP.md).

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
| `memory_pyramid_schema.json` | JSON Schema for the pyramid store |
| `napmem_pyramid.json` | Example pyramid store |
| `test_napmem_pipeline.py` | Test suite (unittest, 9 tests) |

## Documentation

- [Architecture](docs/ARCHITECTURE.md) · [Components](docs/COMPONENTS.md) · [Development](docs/DEVELOPMENT.md)
- [Installation](docs/INSTALLATION.md) · [Testing](docs/TESTING.md) · [Security](docs/SECURITY.md)
- [Codebase overview](docs/codebase-overview.md) · [Known issues](docs/known-issues.md) · [Onboarding](docs/onboarding.md)

## License

[Apache 2.0](LICENSE)
