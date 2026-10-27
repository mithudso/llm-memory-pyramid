# Trusted-memory implementation receipt

Version: 1.0.0. Date: 2026-10-27. Delta: implementation of all ten ordered
priorities from the product roadmap. Package 0.2.0; store 2.0.0; MCP server
1.2.0, protocol 2025-06-18.

| Priority | Delivered capability | Acceptance evidence |
|---|---|---|
| 1 | 200-query synthetic benchmark, fixed splits, frozen old-runtime baselines | Scorer tests and explicit regression comparison |
| 2 | Scoped/temporal assertions, unknown legacy scope, reviewed evidence-based profiles | Migration, alias isolation, validity, conflicts and profile tests |
| 3 | Offline lexical/sparse hybrid recall, injected optional embeddings, bounded context | Ranking, abstention, scope/lifecycle and exact byte-accounting tests |
| 4 | Durable correction, pin, review, expiry, exclusions and forgetting | Replay, aliases, redaction and deletion coverage tests |
| 5 | Exact revision/quotation binding, explicit safe source verification | Changed/missing/unsupported evidence and quotation privacy tests |
| 6 | Complete writer transactions, durable jobs/source identity, generation snapshots | Process/thread concurrency, CAS, crash replay, rename, restore and mirror tests |
| 7 | Portable offline CLI/TOML/doctor; optional private integration | Actual fresh wheel outside checkout without model clients |
| 8 | Scoped review/current/profiles/conflicts/stale/timeline/handoff inspector and diff | Read-only, pagination, historical and complete-hunk tests |
| 9 | Content-free metrics/feedback, freshness/fallback/deletion status | Retention, privacy, read-only status and actual returned-byte observations |
| 10 | Typed MCP plus text compatibility and bounded source adapters/export | Actual CLI/MCP roundtrip and trusted-memory end-to-end loop |

The final local discovery passes 486 tests. Ruff, compilation, shell syntax and
independent adversarial fix verification pass. The independent reviewer
reproduced privacy and protocol failures; fixes now have regression tests.
Fresh-install evidence and exact wheel/module hashes live in
[the acceptance receipt](acceptance-offline-2026-10-27.md). CI/merge receipts
are recorded in the work log after delivery.

## Measured quality and limits

The final fixed-corpus regression has Recall@5 0.86, MRR@5 0.8733 and correct
abstention rate 0.76. Its scope and lifecycle violation counts are zero;
protected-fragment and current-fact cases pass. These are sanitized synthetic
fixtures. They do not establish production accuracy, answer-generation quality,
real embedding quality or a speed gain. The held-out cases informed earlier
fixes; the final report is a regression gate, not a fresh blind evaluation.
Initial and final reports remain separate rather than overwriting history.

Offline sparse retrieval remains intentionally conservative. Unsupported
results/abstentions still exist in the broad fixture. No user traffic was
collected and no noisy feedback was used to tune thresholds. Byte-based token
counts and word-based compression are estimates; real monetary savings need
provider usage and a stated comparison baseline.

Canonical JSON remains inspectable; whole-operation locks solve the observed
single-host writer problem without a speculative storage-engine migration.
SQLite serves durable jobs only. Multi-host writes on shared filesystems, a
hosted service, multimodal capture and a new dashboard remain outside the
roadmap's justified first release.

## Operational boundary

Production stores, installed hooks, schedulers and service configuration were
not migrated or restarted. Commit hooks were suppressed per command to preserve
paused indexing. One stage-3 test-seam mistake contacted a configured embedding
backend with synthetic fixture text; it is recorded in the work log and
KNOW-250. Subsequent tests force hashed mode and offline acceptance guards
record no runtime network attempts. This receipt does not claim the entire
implementation session performed zero inference calls.

Deletion receipts distinguish local canonical/cache/job/feedback handling from
unreachable replicas and operator-managed originals/exports/backups. Restores
preserve current scoped controls and forgotten record families without deleting
independent claims in another project. External clients and production SSH/model
integrations still require separate deployed acceptance.
