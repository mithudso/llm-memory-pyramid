# Operator memory controls

`MemoryPyramidDistiller.control()` provides `correct`, `pin`, `unpin`,
`expire`, `approve`, `reject`, `exclude`, `include`, `forget` and
`forget_session`. These are operator mutations. The retrieval MCP exposes no
mutation tools. CLI commands use this same API.

Call with `dry_run=True` for a concrete preview. The preview token binds the
request, timestamp, generation and full snapshot hash. Applying it after an
intervening change fails. `expected_generation` also protects stale callers.
The persistence layer owns generation increments.

Controls live outside derived tracks/profiles. Scoped text fingerprints,
permanent suppression hashes and source exclusions apply before reconciliation
and after extraction. Pin/review/expiry overrides survive fresh extracted IDs.
Pseudonymous source-to-scope routing survives removal of raw source metadata,
so replay cannot evade a project-scoped tombstone by becoming unscoped.

A correction is a new operator assertion with its own stable ID and literal
evidence. It rejects the original claim and its related wording in that
scope. It does not claim the old source contained the corrected text or that
the incorrect old claim was historically true. Ordinary time-based changes
use explicit valid-time/supersession metadata instead.

`expire` sets valid_to and retains historical queries. `pin` boosts already
relevant evidence; it does not bypass scope, time or relevance filtering.
Approving an arbitrary temporary task still does not make it a durable
profile kind.

`exclude` removes the selected source's occurrences and blocks extraction;
`include` can reverse it. `forget_session` permanently suppresses that session
identity and cannot be reversed with include. Independent foreign sources and
separately authored operator assertions remain their own evidence. `forget`
removes the whole selected canonical/alias/correction family, its quotations
and control assertions, and blocks replay of related text in the same scope.

For destructive controls, the writer purges the adjacent embedding cache and
records a bounded, content-free deletion receipt. Cache failures remain
explicitly pending in the store. `canonical_deletion_complete` covers only
the stated canonical store/cache scope; mirrors require acknowledgment.
Raw original files, exports and backups remain operator-managed. Tombstones,
source routing and audit hashes deliberately survive to prevent resurrection;
the control journal retains at most 1000 content-free entries.
