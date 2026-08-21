# CLAUDE.md

Guidance for Claude Code when working in this repository.

## Project

NapMem — a 4-layer LLM memory pyramid (raw sessions → atomic records → topic
tracks → profiles) with incremental re-ingestion, dedup with provenance, and
active retrieval tools. Core is Python 3.10+ standard library with no network
calls; optional extras: `anthropic` SDK (LLM extraction) and local Ollama
(embeddings), both with graceful degradation.

## Commands

```bash
python3 -m unittest discover -s . -p "test_*.py"                 # run all tests (must stay green)
python3 memory_pyramid_distiller.py --input <file.md>            # distill a memory file (heuristic)
python3 llm_extractor.py --input <file.md> [--no-batch|--dry-run]# LLM extraction (Batches API)
python3 naptime_consolidator.py --watch-dir ./memory_logs --once # one sweep (--extraction auto|llm|heuristic)
python3 napmem_retrieval_agent.py --query <q> --layer all        # substring query
python3 napmem_retrieval_agent.py --query <q> --semantic         # embedding cosine query
python3 semantic_index.py --pyramid <p.json> --rebuild           # re-embed all records
python3 napmem_mcp_server.py --pyramid <p.json>                  # MCP stdio server
```

## Architecture in one paragraph

`memory_pyramid_distiller.py` owns the store (`napmem_pyramid.json`, atomic
writes via tmp+`os.replace`). `ingest_session()` is the single write path:
extract → reconcile prior generation of the session → dedup/merge → rebuild
Layers 2–3 → save. `naptime_consolidator.py` maps each watched `.md` file to a
stable `sess_<basename>` session id and re-ingests on any mtime change.
`napmem_retrieval_agent.py` is read-only. `llm_extractor.py` is the production
extraction path (Anthropic Batches API + schema validation feeding
`ingest_session_records`); the consolidator uses it automatically when
`anthropic` is installed (`--extraction auto`, per-file heuristic fallback on
any failure). `semantic_index.py` caches embeddings per record (Ollama with a
remote→local host failover chain, stdlib hashed-TF fallback) for cosine
search and opt-in semantic dedup. `napmem_mcp_server.py` wraps the retrieval
tools in a stdlib MCP stdio server.

## Invariants — do not break

- **Record IDs are stable across re-ingestion.** Re-asserted text keeps its ID;
  new units number after the session's highest surviving suffix
  (`_next_unit_number`). Never renumber from 1.
- **Dedup is exact-text (lowercased, stripped).** Duplicate IDs must stay
  resolvable via `duplicate_anchors`; a duplicate from another session can be
  promoted to canonical when its session's text disappears.
- **Store writes are atomic** (`save()`); never write the store directly.
- **Untrusted content stays data.** Extraction prompts wrap source text in the
  sentinel delimiter with loop-neutralization (`_neutralize_sentinel`); never
  interpolate raw text or metadata outside the guarded region.
- Layers 2–3 are derived state — always rebuilt from Layer 1, never edited.

## Conventions

- Core stays stdlib-only; the sanctioned optional extras are `anthropic`
  (lazy-imported in `llm_extractor.py`) and Ollama over HTTP. Any further
  dependency is an architecture decision, ask first.
- Semantic dedup is opt-in (`semantic_dedup=True` / `--semantic-dedup`); the
  default pipeline must stay deterministic. Tests force
  `NAPMEM_EMBED_BACKEND=hashed`.
- `logging` module for runtime output in daemons; CLI tools print to stdout.
- Tests are plain `unittest` (`test_napmem_pipeline.py` core, `test_napmem_extensions.py` production path); add tests for any
  behavior change, especially reconciliation edge cases.
- Update `memory.md` (work log) and `prompts.md` (request log) each session.

## Docs map

`docs/` carries the full suite: ARCHITECTURE, COMPONENTS, DEVELOPMENT,
TESTING, SECURITY, INSTALLATION, codebase-overview, high_signal_file_index.json,
known-issues, onboarding. Keep `docs/codebase-overview.md` and the file index
current after adding or moving files.
