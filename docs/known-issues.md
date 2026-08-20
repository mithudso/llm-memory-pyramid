# Known issues

Active limitations and accepted trade-offs. No open defects; the test suite is
green (9/9).

## Limitations (by design, candidates for enhancement)

- **Exact-text dedup only.** Paraphrases of the same fact create separate
  records; semantic/embedding dedup is the planned complement (ADR-3).
- **Heuristic extractor in the loop.** `extract_atomic_units()` is a
  deterministic keyword-rule stand-in; the production LLM extraction path
  (`llm_extraction_prompts.py`) is defined but not wired.
- **Heuristic profile categories are a subset.** The stand-in emits only
  `preference`/`constraint`/`workflow`; `identity` and `goal` from the schema
  enum are reserved for the LLM extractor.
- **Single writer.** No lock file; running two consolidators against one store
  can lose updates (last atomic write wins).
- **In-memory mtime cache.** The consolidator re-ingests every file on
  restart (correct, just redundant work); no persisted watermark.
- **Layer 2/3 summaries are naive.** Track summary = first three high-salience
  texts; profile per high-salience fact/actionable record (no cross-record
  synthesis).

## TODO tracking

Code carries no TODO/FIXME markers; enhancements above are tracked here and in
`memory.md` next-steps.
