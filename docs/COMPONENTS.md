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

**Extraction modes** (`extraction=` / `--extraction`): `auto` tries Anthropic
when installed, then Ollama, then a per-file heuristic fallback. `llm`
requires the SDK; `ollama` skips Anthropic entirely; `heuristic` uses no
model. A persisted mtime/sha256 state file avoids re-extracting unchanged
sources across `--once` restarts. Invalid state entries are ignored; absent
source sessions invalidate their watermark. A fatal store-write failure
propagates from batch ingest so later writes cannot hide a partial commit.

**CLI:** `--watch-dir` (default `./memory_logs`), `--pyramid`, `--interval`,
`--max-ticks`, `--once`, `--extraction`, `--semantic-dedup`.

**Depends on:** `memory_pyramid_distiller`; lazy Anthropic and Ollama extractors
when selected. Ollama paths use the shared `ollama-client` library.

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
backend/model switch invalidates the cache. Backends: `OllamaBackend` with a
weighted host pool via the shared `ollama-client` library (`NAPMEM_OLLAMA_URLS`;
unset falls back to `OLLAMA_URLS`/`OLLAMA_HOST`/`localhost:11434`; all hosts serving
`mxbai-embed-large` so failover preserves the cache) and `HashedTfBackend`
(stdlib hashed term-frequency, deterministic fallback). Force with
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

## `ollama_extractor.py` — local chat extraction

Uses a configured `url=model` chain through `ollama-client`. It shares the
sentinel prompt and schema validation with the Anthropic extractor. Leading
reasoning preambles are removed; JSON string content remains intact. Failed
models can fall through to another model on the same live host.

## `napmem_mcp_failover.py` — stdio proxy

Relays requests over SSH and replays initialization and pending requests to
the local mirror after remote failure. Mirror refresh copies the configured
remote snapshot into a validated immutable generation with fixed member names
and one atomic publication pointer. Backend
read/write errors trigger controlled cleanup and failover. Tool results from
the mirror disclose snapshot age. Configuration and CLI flags are documented
in the module header and [MCP reference](MCP.md).

## Trusted-memory modules

`napmem_model`, `napmem_search`, `napmem_controls` and `napmem_evidence` define
scoped temporal assertions, bounded retrieval, persistent operator controls and
literal source binding. `napmem_storage` owns complete writer locks/CAS commits;
`napmem_sources`, `napmem_jobs` and `napmem_snapshots` own source identity,
resumable extraction and verified mirror generations. `napmem_cli` and
`napmem_config` provide the offline entrypoint. `napmem_inspector`,
`napmem_metrics`, `napmem_adapters` and `napmem_eval` add review, measured status,
bounded import/export and synthetic quality regression. Dedicated guides explain
each contract; the generated source index catalogs every public module.

## Maintenance and tests

`test_napmem_*.py` files use `unittest`, temporary stores and mocked transports.
See [Testing](TESTING.md) for every suite and its coverage. `scripts/repo_docs.py`
generates the static file map, high-signal index and root llms files. Its
`--check` mode verifies exact generated content without importing runtime
modules or making network calls.
