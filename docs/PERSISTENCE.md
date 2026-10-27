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

All persisted JSON and queue files use private permissions. Atomic replacement
includes file fsync; a directory-sync failure after replacement is reported as
a durability limitation because the commit is already visible. Original raw
files are never deleted by memory controls.
