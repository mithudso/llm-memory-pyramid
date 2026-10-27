# Inspect and review memory

Version: 1.0.0. Delta: terminal views and source revision differences.

Use `napmem inspect --view review --scope project:example` to see proposed
claims, their exact record IDs, evidence, age and current review state. The
current, profiles, conflicts, stale, timeline and handoff views answer different
questions without changing the store. The overview summarizes the same scoped
snapshot. Project views include explicitly global memory; they never include
another project's claims by default.

Each displayed assertion has its source citation, retained verification state,
scope, validity and a correction preview command. Verification against retained
source bytes does not establish factual entailment. A paraphrased claim can
still require review after its quote has been bound successfully. Unknown age
is shown explicitly and enters stale review.

```sh
napmem --pyramid /tmp/napmem-demo/store.json inspect --view review --scope project:napmem-demo-alpha
napmem --pyramid /tmp/napmem-demo/store.json inspect --view conflicts --scope project:napmem-demo-alpha
napmem --pyramid /tmp/napmem-demo/store.json inspect --view handoff --scope project:napmem-demo-alpha
napmem --pyramid /tmp/napmem-demo/store.json inspect --view timeline --as-of 2026-10-27T00:00:00Z --scope project:napmem-demo-alpha
napmem diff /tmp/napmem-demo/before.md /tmp/napmem-demo/after.md --max-bytes 8192
```

Review and timeline deliberately show retained rejected or inactive assertions
with labels. Other views use the shared retrieval eligibility rules. Timeline
shows retained assertion timestamps, not a reconstructed historical database.
The handoff brief supplies evidence recall; Stele retains authoritative task
state. Conflict groups identify different values sharing an explicit subject;
they are review hints rather than automatic contradiction judgments.

Choose `--offset` and `--limit` to page. Budgets drop complete entries and report
the next offset after entries actually returned. If one entry cannot fit,
increase `--max-bytes` or `--max-tokens`; the reported offset does not skip it.
Diffs operate only on two explicit bounded local inputs and retain complete
unified hunks. Neither inspection nor diff implicitly rereads stored source
paths. Explicit record `inspect ID --verify --source-root ROOT` rechecks an
authorized source under the provenance contract.

Apply approve/reject/correct with the ordinary `napmem control` command and the
displayed record ID. `--dry-run` returns a preview token; passing that token when
applying rejects an intervening store change. Controls persist outside derived
profiles and survive re-ingestion. The inspector never edits derived layers.
