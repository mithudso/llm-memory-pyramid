# Known issues

Active limitations and accepted trade-offs. No open defects; the test suite is
green (9/9).

## Limitations (by design, candidates for enhancement)

- **Semantic dedup is opt-in and threshold-based.** Default pipeline remains
  exact-text (deterministic). The hashed-TF fallback backend detects
  token-overlap near-duplicates, not true paraphrase — real paraphrase folding
  needs the Ollama backend.
- **Semantic folds keep the canonical's text.** The paraphrase is preserved in
  the duplicate anchor (`paraphrase_text`); a promoted duplicate therefore
  carries the old canonical's wording with its own anchor disclosing the
  original phrasing.
- **Heuristic extractor is still the default.** `llm_extractor.py` is the
  production path but requires the `anthropic` package and an API key; the
  consolidator daemon still uses the heuristic extractor.
- **Heuristic profile categories are a subset.** The stand-in emits only
  `preference`/`constraint`/`workflow`; `identity` and `goal` from the schema
  enum arrive via the LLM extraction path.
- **Batch extraction polls synchronously.** `extract_batch` blocks up to 1h;
  a submit-now/collect-later mode would suit cron-driven naptime better.
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
