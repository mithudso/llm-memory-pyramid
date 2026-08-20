# memory.md — operator work log

Versioned log of active task, completed work, and next steps. Newest first.

## v1.1.0 — 2026-08-20

**Active task:** none — production path shipped.

**Completed:**
- `llm_extractor.py`: LLM extraction via Anthropic Message Batches API
  (claude-haiku-4-5 default), schema-validated ingest through new
  `ingest_session_records` distiller entry point.
- `semantic_index.py`: embedding index (Ollama backend with stdlib hashed-TF
  fallback), cosine search, opt-in semantic dedup in the distiller,
  `--semantic` retrieval CLI.
- `napmem_mcp_server.py` + `.mcp.json`: pure-stdlib MCP stdio server exposing
  search_memory / inspect_provenance / get_topic_track / memory_stats.
- Test suite grown 9 → 19 (all network-free); CI now runs unittest discovery.
- `docs/external-calls.md` populated with the repo's first external calls.

**Next steps:**
- Submit-now/collect-later batch mode for cron-driven naptime.
- Optional: point the naptime consolidator at the LLM extractor.

## v1.0.0 — 2026-08-20

**Active task:** none — bootstrap complete.

**Completed:**
- NapMem pipeline implemented: distiller (extraction, dedup, session
  reconciliation with stable IDs, layer rebuild), naptime consolidator
  (mtime-based incremental re-ingest), retrieval agent (search, provenance,
  topic tracks, token-savings stats), zero-fabrication extraction prompts with
  sentinel injection guards.
- Test suite: 9/9 passing (`python3 test_napmem_pipeline.py`).
- Repo bootstrapped to mdb-tam standard (docs suite, CI, meta files) and
  published to https://github.com/mithudso/llm-memory-pyramid.

**Next steps:**
- Wire `llm_extraction_prompts.py` into a real LLM extraction path (the
  distiller currently uses the heuristic stand-in extractor).
- Consider embedding-based (semantic) dedup to complement exact-text matching.
