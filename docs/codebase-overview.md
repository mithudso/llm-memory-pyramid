# Codebase overview

Single-component repository — one flat Python package-less module set at the
repo root. Every file accounted for below.

## Root — core pipeline

| File | Role |
|---|---|
| `memory_pyramid_distiller.py` | Core distiller: store ownership, extraction, dedup, session reconciliation, layer rebuild, markdown rendering, CLI |
| `naptime_consolidator.py` | Background watcher: mtime-change detection, per-file error isolation, polling loop, CLI |
| `napmem_retrieval_agent.py` | Read-only retrieval tools: search, provenance, topic tracks, token-savings stats, CLI |
| `llm_extraction_prompts.py` | LLM extraction prompt templates + injection-guard helpers (sentinel/metadata neutralization) |
| `llm_extractor.py` | Production extraction via Anthropic Batches API: parse, validate, ingest |
| `semantic_index.py` | Embedding index (Ollama / stdlib hashed-TF), cosine search, semantic dedup |
| `napmem_mcp_server.py` | Stdlib MCP stdio server (JSON-RPC) exposing retrieval tools |
| `test_napmem_pipeline.py` | 9-test `unittest` suite for the core pipeline |
| `test_napmem_extensions.py` | 10-test suite: extractor, semantic index/dedup, MCP server |

## Root — data & schema

| File | Role |
|---|---|
| `memory_pyramid_schema.json` | JSON Schema for the pyramid store |
| `napmem_pyramid.json` | Example/demo pyramid store |
| `sample_agent_memory.md` | Sample input memory file |

## Meta

| Path | Role |
|---|---|
| `README.md`, `CLAUDE.md`, `AGENTS.md`, `GEMINI.md` | Entry points for humans and coding agents |
| `memory.md`, `prompts.md` | Operator work log / request log |
| `CONTRIBUTING.md`, `CODE_OF_CONDUCT.md`, `LICENSE` | Contribution meta (Apache 2.0) |
| `docs/` | Full documentation suite (architecture, components, development, testing, security, installation, requirements, logging, caching, runbooks, indexes) |
| `.mcp.json` | Registers the napmem MCP server for MCP clients |
| `scripts/run-naptime.sh` | Portable bash sweep wrapper (launchd + systemd): multi-source mirror, guards, one sweep |
| `deploy/` | systemd user units + deployment README (Linux canonical consolidator) |
| `.github/` | CI workflow, dependabot, CODEOWNERS, templates, security policy, copilot instructions |
| `.vscode/`, `.editorconfig`, `.gitattributes`, `.gitignore` | Editor/toolchain meta |
