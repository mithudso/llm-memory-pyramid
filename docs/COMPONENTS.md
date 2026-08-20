# Components

## `memory_pyramid_distiller.py` — core distiller

**Purpose:** owns the pyramid store and the single write path.

**API (`MemoryPyramidDistiller`):**
- `ingest_session(session_id, title, file_path, content) -> int` — full
  pipeline: extract → reconcile → dedup → rebuild → save. Returns unit count.
- `extract_atomic_units(content, session_id, file_path)` — heuristic extractor
  (8-way taxonomy + salience).
- `deduplicate_and_merge(new_records)` — exact-text fold into canonicals.
- `rebuild_higher_layers()` — regenerates topic tracks and profiles.
- `render_markdown_summary() -> str` — human-readable pyramid report.
- `save()` — atomic write.

**CLI:** `--input <file>`, `--session-id` (default `sess_<basename>`),
`--title`, `--pyramid <store.json>`.

**Depends on:** stdlib only.

## `naptime_consolidator.py` — background consolidator

**Purpose:** idle-time ("naptime") incremental re-ingestion of changed memory
files.

**API (`NaptimeConsolidator`):** `scan_and_consolidate() -> int`,
`run_loop(poll_interval_sec, max_ticks)`. Per-file errors (OSError, non-UTF-8)
are logged and skipped — one bad file never kills the loop.

**CLI:** `--watch-dir` (default `./memory_logs`), `--pyramid`, `--interval`,
`--max-ticks`, `--once`.

**Depends on:** `memory_pyramid_distiller`.

## `napmem_retrieval_agent.py` — active retrieval tools

**Purpose:** read-only tool surface for LLM agents.

**API (`NapMemRetrievalAgent`):**
- `search_memory_pyramid(query, layer)` — substring search across profiles /
  tracks / records; raises `ValueError` on unknown layer (typo ≠ "no memory").
- `inspect_provenance(record_id)` — resolves canonical *or duplicate* IDs back
  to Layer 0; duplicates resolve with their own anchor + `canonical_id`.
- `get_topic_track(topic_slug)` — full track with associated records.
- `compute_context_budget_savings()` — token compression stats vs raw logs;
  only counts sessions whose raw file is still readable, disclosing missing
  ones.

**CLI:** `--query`, `--layer`, `--provenance`, `--stats`, `--pyramid`.

**Depends on:** stdlib only; requires an existing pyramid store.

## `llm_extraction_prompts.py` — production extraction prompts

**Purpose:** zero-fabrication LLM extraction prompt templates with injection
guards. `get_extraction_prompt(raw_text, session_id, file_name)` wraps
untrusted text in a loop-neutralized sentinel delimiter and strips
newlines/sentinels from metadata. Consumed by `llm_extractor.py`.

## `llm_extractor.py` — LLM extraction pipeline

**Purpose:** production extraction path replacing the heuristic extractor.

**API:** `parse_extraction_output(raw)` (tolerates one JSON code fence),
`validate_unit(unit)`, `units_to_records(units, session_id, file_path)`,
`extract_direct(client, prompt, model)`, `extract_batch(client, prompts, model)`
(Message Batches API — 50% cost, polls to completion),
`ingest_extractions(distiller, outputs, file_paths)`. Invalid units are
rejected and logged, never repaired.

**CLI:** `--input <files>`, `--model` (default `claude-haiku-4-5`),
`--no-batch`, `--semantic-dedup`, `--dry-run`, `--pyramid`.

**Depends on:** `anthropic` (lazy import; clear error if missing).

## `semantic_index.py` — embedding index

**Purpose:** cosine retrieval + near-duplicate detection over Layer 1.

**API (`SemanticIndex`):** `search(query, records, top_k)`,
`nearest_record_id(text, records, threshold)`, `rebuild(records)`. Vectors
cached in `<pyramid>.embindex.json` keyed by record id + text hash; a
backend/model switch invalidates the cache. Backends: `OllamaBackend`
(localhost `/api/embed`, auto-probed) and `HashedTfBackend` (stdlib hashed
term-frequency, deterministic fallback). Force with
`NAPMEM_EMBED_BACKEND=ollama|hashed`.

**CLI:** `--rebuild`, `--query`, `--top-k`, `--pyramid`.

## `napmem_mcp_server.py` — MCP stdio server

**Purpose:** exposes retrieval tools to MCP clients (registered in
`.mcp.json`). Pure-stdlib newline-delimited JSON-RPC 2.0; protocol
`2025-06-18`. Tools: `search_memory` (substring or semantic),
`inspect_provenance`, `get_topic_track`, `memory_stats`. Store re-read per
call so consolidator updates are visible; tool failures return in-band
`isError` results.

## `memory_pyramid_schema.json` — store schema

JSON Schema describing the pyramid store shape (layers 0–3, record fields,
profile category enum).

## `test_napmem_pipeline.py` / `test_napmem_extensions.py` — test suites

19 `unittest` tests total. Pipeline suite (9): extraction, dedup/duplicate
anchors, re-ingestion ID stability, duplicate promotion, layer rebuild,
provenance resolution, prompt-guard neutralization. Extensions suite (10):
extractor parsing/validation/record conversion, LLM-record re-ingest
stability, hashed-backend cosine properties, semantic search ranking,
semantic dedup fold (and off-by-default), MCP handshake/tools/errors via
subprocess. Network-free by design.
