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
python3 -m venv .venv
.venv/bin/python -m pip install -e .
.venv/bin/napmem --pyramid /tmp/napmem-demo/store.json demo
.venv/bin/napmem --pyramid /tmp/napmem-demo/store.json query "preferred editor" --scope project:napmem-demo-alpha
.venv/bin/napmem --pyramid /tmp/napmem-demo/store.json doctor
NAPMEM_EMBED_BACKEND=hashed .venv/bin/python -m unittest discover -s . -p "test_*.py"
```

Python 3.11+ is required. The default installation has no runtime dependencies
and runs offline. Install `.[llm]` for Anthropic or `.[ollama]` for the pinned
shared Ollama client (the latter requires private repository access). Online
extraction and embeddings require explicit configuration. The shared transport
remains in that optional client. See [the CLI guide](docs/CLI.md).

Named project scopes, historical queries, persistent corrections, explicit
forgetting and source exclusions govern recall. Profiles require reviewed
persistent claims with supporting evidence. The local inspector explains each
claim's scope, source and review state. Snapshot restores preserve newer privacy
controls; deletion receipts disclose replica and backup limits.

## MCP server

`napmem_mcp_server.py` exposes the retrieval tools to Claude Code / Claude
Desktop over MCP stdio (registered in `.mcp.json`) — agents probe memory with
targeted queries instead of loading raw logs. See [docs/MCP.md](docs/MCP.md).
`.mcp.json` runs the server locally on `~/.napmem/napmem_pyramid.json` with
embeddings from local Ollama (`127.0.0.1:11434`); no remote host is used. The
example store checked into this repo is separate; see `CLAUDE.md`.

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
| `napmem_mcp_failover.py` | Legacy MCP proxy (remote SSH server, local-mirror fallback); no longer registered in `.mcp.json` |
| `memory_pyramid_schema.json` | JSON Schema for the pyramid store |
| `napmem_pyramid.json` | Local dev/test example pyramid store — not used by `.mcp.json`, which targets `~/.napmem/napmem_pyramid.json` |
| `test_napmem_pipeline.py` | Core unittest suite; run discovery for every suite |

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
