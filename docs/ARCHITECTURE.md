# Architecture

## System context

NapMem sits beside an LLM agent's raw memory artifacts (session transcripts,
`MEMORY.md`-style files, agent logs). It compresses them into a queryable
4-layer pyramid so the agent retrieves *targeted* memory via tools instead of
dumping raw logs into context.

```
memory files (.md)                     LLM agent
      │                                    ▲
      ▼                                    │ tool calls
naptime_consolidator.py ──▶ memory_pyramid_distiller.py ──▶ napmem_pyramid.json ◀── napmem_retrieval_agent.py
   (watch/poll loop)           (single write path)             (JSON store)            (read-only tools)
```

## Layers

| Layer | Store key | Contents |
|---|---|---|
| 0 | `raw_conversations` | Session metadata + file path (raw text stays on disk) |
| 1 | `memory_records` | Atomic units: type (8-way taxonomy), text, salience, topic slug, source anchor, duplicates |
| 2 | `topic_tracks` | Per-topic clusters with summary and record IDs — derived |
| 3 | `user_profiles` | Preference/constraint/workflow traits with provenance — derived |

Layers 2–3 are always rebuilt from Layer 1 (`rebuild_higher_layers()`); they
are never edited directly.

## Data flow: `ingest_session()`

1. **Extract** — `extract_atomic_units()` parses content into typed units with
   per-line source anchors. (Heuristic stand-in; the production path is the LLM
   extractor prompted by `llm_extraction_prompts.py`.)
2. **Reconcile** — `_reconcile_session_records()` diffs the fresh extraction
   against the session's prior generation: re-asserted text keeps its stable
   record ID; stale canonicals are dropped or handed to a surviving duplicate
   from another session (promotion); remaining new units are renumbered after
   the session's highest surviving suffix to avoid ID collisions.
3. **Dedup/merge** — `deduplicate_and_merge()` folds exact-text matches into
   canonical records, preserving each duplicate's anchor in
   `duplicate_anchors`.
4. **Rebuild** — Layers 2–3 regenerated from surviving records.
5. **Save** — atomic write (`.tmp` + `os.replace`).

## Key decisions (ADRs)

- **ADR-1: JSON file store, atomic replace.** Single-file store keeps the
  system dependency-free and inspectable; `os.replace` guarantees the
  consolidator daemon can't corrupt it mid-write. Trade-off: no concurrent
  writers — one consolidator process at a time.
- **ADR-2: Stable record IDs across re-ingestion.** Downstream consumers
  (profiles' `provenance_records`, tracks' `record_ids`, external references)
  survive re-ingestion. Enforced by reconcile-before-merge and
  `_next_unit_number()` scanning canonical *and* duplicate IDs.
- **ADR-3: Exact-text dedup.** Deterministic and cheap; semantic dedup is a
  known future enhancement (see docs/known-issues.md).
- **ADR-4: Sentinel-delimited prompts, not markdown fences.** A ``` inside
  hostile source text would terminate a fence early; the sentinel is
  loop-neutralized so it cannot be reconstituted by nesting.
- **ADR-5: mtime *change* (not strictly-newer) triggers re-ingest.** Restores
  with older timestamps (rsync -t, git checkout) must not be silently skipped.
