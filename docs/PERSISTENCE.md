# Persistence, jobs and snapshots

Version: 1.0.0. Delta: transactional JSON and resumable extraction.

Canonical JSON remains the source of truth. Writers lock the complete
read/reconcile/save operation with a stable adjacent lock file. Atomic commits
increment generation and compare the exact snapshot fingerprint. A stale
direct save fails with StoreConflict. Locks coordinate processes on one host;
do not use a shared filesystem as a distributed database.

The source registry preserves source identity across renames, checks content
even when modification time is unchanged, and retains missing-source metadata.
Missing files do not implicitly delete memory. Explicit source exclusions and
forgetting determine deletion. Retired record IDs are never reused.

The optional adjacent jobs database uses SQLite transactions, bounded leases,
retry limits and content-free status receipts. Submit, collect and commit are
separate operations. Commit rechecks the source revision and current controls.
A canonical applied-job marker makes replay safe after a queue acknowledgment
crash. Unknown cloud submission outcomes require operator investigation before
retry; they are never automatically resubmitted. Local privacy purges cancel
matching jobs and clear their source/result payloads. Remote providers, exports
and backups remain operator managed; deletion receipts disclose this boundary.

Snapshots bind canonical bytes, generation, schema and optional embedding-cache
checksums in a manifest. An invalid or incompatible cache is omitted. A legacy
cache with matching text hashes is labeled as such, without an invented store
generation. Mirrors publish an immutable generation through one atomic pointer.
Older or failed refreshes preserve the active generation. Snapshot searches
cannot write caches. Restores validate the manifest, retain newer local privacy
controls and corrections, and create a new generation without changing IDs.
Restored assertions retain their original scopes. Content-free record-family
IDs suppress older copies made before a scope change, while independent copies
in other scopes retain their own lifecycle. A reader that
opened a verified snapshot refuses a later manifest-free downgrade.

All persisted JSON and queue files use private permissions. Atomic replacement
includes file fsync; a directory-sync failure after replacement is reported as
a durability limitation because the commit is already visible. Original raw
files are never deleted by memory controls.

## Maintenance boundaries

Correction text cannot form a fingerprint cycle (A→B→A). Preview IDs include every
occurrence affected by a scoped text override. Deleting one source preserves
unrelated raw-session metadata, including sessions with no extracted records.

Source rename recognition now also requires creation identity: native birth time
on macOS, or Linux statx `STATX_BTIME` where available. Existing registries gain this
metadata when a known path is observed. If it is unknown, a renamed file gets a new
identity; use explicit session mapping where continuity is required. Device/inode
alone cannot distinguish a recycled inode. Creation time is metadata evidence,
not a cryptographic guarantee against a privileged filesystem adversary.

An expired or replaced job lease cannot mutate canonical memory. Commit holds the
queue write fence during the canonical write, following store→queue lock order.
`SubmissionOutcomeUnknown` cannot retry automatically. Queue parents must be owned
by the current user and not writable by others. Operator/provider reconciliation
remains necessary after an ambiguous paid submission.
