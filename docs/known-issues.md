# Known issues

Current limits and accepted trade-offs. Test results and the dated review
report describe validation; they do not prove the deployed fleet is healthy.

- **Single writer per pyramid.** Atomic replacement protects readers from
  partial JSON. It does not serialize two consolidators or distillers; the
  last writer can lose another writer's changes.
- **Same-mtime changes can be missed.** The persistent sweep cache checks
  mtime before hashing. Editing content while preserving its mtime can skip
  extraction. Touch the source to force a content check. Renaming a file
  creates a new session; deleting a source does not delete its stored session.
- **Semantic behavior depends on the backend.** Hashed-TF detects token
  overlap, not paraphrase meaning. Semantic dedup stays opt-in. Folds preserve
  canonical wording and duplicate anchors disclose original paraphrase text.
- **Mirrors can be stale.** Failover marks tool results with snapshot age.
  The pyramid and embedding cache are copied separately; cache misses can
  be recomputed. Substring retrieval needs no embedding service.
- **Batch extraction blocks.** Anthropic batch polling can run for up to one
  hour. Configure the scheduler for one writer; do not overlap sweeps.
- **Derived summaries are simple.** Tracks take the first three high-salience
  texts; profiles derive from individual facts and actionable records.
- **Optional infrastructure is separate.** Global hooks, hub indexing and
  deployed scheduler state are outside this repo. This review did not restart,
  deploy, re-embed or verify those systems.
- **Generic server standards are not implemented.** This Python CLI/MCP
  project has no dashboard, operation registry or shared JSONL error service.
  [External calls](external-calls.md) records actual triggers, logs, retries
  and validation. This adaptation does not establish full mdb-tam parity.
