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
python3 napmem_retrieval_agent.py --provenance rec_sess_sample_agent_memory_001
python3 napmem_retrieval_agent.py --stats

# Run the test suite
python3 test_napmem_pipeline.py
```

No dependencies — Python 3.10+ standard library only.

## Components

| File | Purpose |
|---|---|
| `memory_pyramid_distiller.py` | Core distiller: extraction, dedup, session reconciliation, layer rebuild |
| `naptime_consolidator.py` | Background watcher that incrementally re-ingests changed `.md` files |
| `napmem_retrieval_agent.py` | Active retrieval tools: search, provenance, topic tracks, token-savings stats |
| `llm_extraction_prompts.py` | Zero-fabrication LLM extraction prompt templates with injection guards |
| `memory_pyramid_schema.json` | JSON Schema for the pyramid store |
| `napmem_pyramid.json` | Example pyramid store |
| `test_napmem_pipeline.py` | Test suite (unittest, 9 tests) |

## Documentation

- [Architecture](docs/ARCHITECTURE.md) · [Components](docs/COMPONENTS.md) · [Development](docs/DEVELOPMENT.md)
- [Installation](docs/INSTALLATION.md) · [Testing](docs/TESTING.md) · [Security](docs/SECURITY.md)
- [Codebase overview](docs/codebase-overview.md) · [Known issues](docs/known-issues.md) · [Onboarding](docs/onboarding.md)

## License

[Apache 2.0](LICENSE)
