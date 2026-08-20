# Caching and optimization

## Cache layers

- **Consolidator mtime cache** (`file_timestamps`, in-memory): skips
  unchanged files within a process lifetime. Invalidation: *any* mtime change
  (not strictly-newer — see ADR-5). Cold start re-ingests everything; this is
  correct because re-ingestion is idempotent (stable IDs).
- **Dedup index** (`existing_texts` dict, per-merge): O(1) exact-text lookup
  built per `deduplicate_and_merge` call.

There is no persistent cache; the pyramid store itself is the durable artifact.

## Performance characteristics

- Extraction is single-pass line-oriented — O(lines).
- Reconciliation and rebuild are O(records) per ingest; the whole store is
  rewritten each save (atomic replace). Fine for the intended scale
  (thousands of records); a store measured in hundreds of MB would need an
  incremental backend.
- Retrieval search is linear substring scan over records/tracks/profiles — no
  index. Acceptable at current scale; an inverted index or embeddings are the
  upgrade path.

## The optimization that matters

The system's purpose *is* an optimization: `compute_context_budget_savings()`
measures token compression of distilled layers vs raw logs, honestly scoped to
sessions whose raw files are still readable.
