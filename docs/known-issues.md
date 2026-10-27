# Known issues

Current limits and accepted trade-offs. Local tests do not prove deployed
fleet health; installed acceptance records its exact runtime separately.

- **Single-host persistence.** Whole-operation locks and generation/CAS checks
  serialize local writers. They are not a distributed database protocol for a
  network filesystem. Missing sources retain memory until explicit controls
  remove it. Same-inode rename/edit and unchanged-mtime edits are recognized;
  cross-device moves can require an explicit identity mapping.
- **Retrieval quality is measured on synthetic cases.** Sparse hybrid and hashed
  retrieval are conservative lexical approximations. Real embeddings remain
  explicit; production accuracy and monetary savings are unmeasured.
- **Mirrors can be stale.** Immutable generations bind store/cache checksums,
  but an unreachable old mirror cannot acknowledge deletion. Receipts disclose
  replica gaps and operator-managed originals/exports/backups.
- **Legacy batch calls can block.** The old extraction helper still polls when
  explicitly selected. Durable jobs and --async-batches separate submit,
  collect and commit; ambiguous provider submission needs operator resolution.
- **Derived summaries remain simple.** Tracks use selected assertion text;
  reviewed supported persistent claims form profiles. Conflict groups are hints,
  not an automatic contradiction or entailment model.
- **Optional infrastructure is separate.** Installed hooks, hub indexing,
  schedulers, remote credentials and external clients were not deployed or
  restarted. Runtime integrations require separate acceptance.
- **No speculative dashboard or service migration.** This release keeps JSON
  canonical and adds stdlib SQLite for jobs. It does not add a hosted service,
  graph database or competing Stele task interface.
