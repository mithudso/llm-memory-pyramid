"""Durable extraction jobs with leases and idempotent canonical commits.

Source and result payloads exist only while work is pending. Committed, stale,
cancelled and failed work clears them. Failed work needs a fresh source snapshot
for retry. SQLite uses secure_delete and DELETE journaling; backups, remote
provider retention and storage-device forensic erasure remain operator-owned.
"""

from __future__ import annotations

from contextlib import contextmanager
import hashlib
import json
import os
from pathlib import Path
import sqlite3
import stat
import time
import uuid
from typing import Any, Callable

from llm_extraction_prompts import PROMPT_VERSION, get_extraction_prompt
from napmem_sources import MAX_SOURCE_BYTES, read_source


STATES = ("queued", "submitted", "ready", "committed", "stale", "failed", "cancelled")
TERMINAL = ("committed", "stale", "failed", "cancelled")
BACKENDS = ("heuristic", "anthropic")
MAX_RESULT_BYTES = 4 * 1024 * 1024


def _json(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)


def _sha(value):
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


class JobQueue:
    def __init__(self, pyramid_path: str, path: str | None = None):
        self.pyramid_path = os.fspath(pyramid_path)
        self.path = path or self.pyramid_path + ".jobs.sqlite3"

    @contextmanager
    def _db(self, *, create=True):
        if not create and not os.path.exists(self.path):
            yield None
            return
        if create:
            Path(self.path).parent.mkdir(parents=True, exist_ok=True)
        fd = os.open(self.path, os.O_RDWR | (os.O_CREAT if create else 0) |
                     getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_NONBLOCK", 0), 0o600)
        try:
            details = os.fstat(fd)
            if not stat.S_ISREG(details.st_mode) or details.st_nlink != 1:
                raise ValueError("Job queue must be a private regular, singly-linked file")
            os.fchmod(fd, 0o600)
        finally:
            os.close(fd)
        db = sqlite3.connect(self.path, timeout=10, isolation_level=None)
        db.row_factory = sqlite3.Row
        try:
            db.execute("PRAGMA busy_timeout=10000")
            db.execute("PRAGMA journal_mode=DELETE")
            db.execute("PRAGMA secure_delete=ON")
            db.execute("PRAGMA synchronous=FULL")
            if create:
                db.execute("""CREATE TABLE IF NOT EXISTS jobs (
                    id TEXT PRIMARY KEY, idempotency_key TEXT NOT NULL,
                    session_id TEXT NOT NULL, source_path TEXT NOT NULL, source_hash TEXT NOT NULL,
                    scope TEXT, backend TEXT NOT NULL, model TEXT, prompt_version TEXT,
                    state TEXT NOT NULL, source_text TEXT, result_text TEXT, result_kind TEXT,
                    allowed_roots TEXT, batch_handle TEXT, error_code TEXT,
                    lease_owner TEXT, lease_until REAL, attempts INTEGER NOT NULL DEFAULT 0,
                    max_attempts INTEGER NOT NULL DEFAULT 3, created_at REAL NOT NULL, updated_at REAL NOT NULL
                )""")
                db.execute("CREATE INDEX IF NOT EXISTS jobs_state ON jobs(state, created_at)")
                if "result_hash" not in {row[1] for row in db.execute("PRAGMA table_info(jobs)")}:
                    db.execute("ALTER TABLE jobs ADD COLUMN result_hash TEXT")
                db.execute("""CREATE UNIQUE INDEX IF NOT EXISTS jobs_active_key ON jobs(idempotency_key)
                           WHERE state IN ('queued','submitted','ready')""")
            yield db
        finally:
            db.close()

    @staticmethod
    def _public(row):
        if row is None:
            return None
        return {key: row[key] for key in (
            "id", "idempotency_key", "session_id", "source_path", "source_hash", "scope",
            "backend", "model", "prompt_version", "state", "error_code", "lease_owner",
            "lease_until", "attempts", "max_attempts", "created_at", "updated_at", "result_hash")}

    def list(self, state: str | None = None, *, limit: int = 100) -> list[dict[str, Any]]:
        if state is not None and state not in STATES:
            raise ValueError("Unknown job state")
        if isinstance(limit, bool) or not isinstance(limit, int) or not 1 <= limit <= 10000:
            raise ValueError("limit must be between 1 and 10000")
        with self._db(create=False) as db:
            if db is None:
                return []
            rows = db.execute("SELECT * FROM jobs" + (" WHERE state=?" if state else "") +
                              " ORDER BY created_at,id LIMIT ?", (state, limit) if state else (limit,))
            return [self._public(row) for row in rows]

    def get(self, job_id: str, *, include_payload=False) -> dict[str, Any] | None:
        with self._db(create=False) as db:
            if db is None:
                return None
            row = db.execute("SELECT * FROM jobs WHERE id=?", (job_id,)).fetchone()
            return dict(row) if row is not None and include_payload else self._public(row)

    def enqueue(self, *, session_id: str, source_path: str, source_content: str,
                scope: str | None = None, backend: str = "heuristic", model: str | None = None,
                prompt_version: str | None = PROMPT_VERSION,
                allowed_roots: list[str] | None = None, max_attempts: int = 3) -> dict[str, Any]:
        from napmem_controls import source_is_excluded
        from napmem_storage import read_snapshot, store_lock
        # Use the canonical lock order (store, then queue) so a privacy control
        # cannot race a new raw source payload into this database after purge.
        with store_lock(self.pyramid_path):
            snapshot, _ = read_snapshot(self.pyramid_path)
            if snapshot is not None and (
                    source_is_excluded(snapshot, source_path, session_id=session_id)
                    or source_is_excluded(snapshot, os.path.abspath(source_path), session_id=session_id)):
                raise ValueError("Source is excluded or permanently forgotten")
            if snapshot is not None:
                from napmem_controls import _quote_line_hashes
                routed_scope = scope or snapshot.get("source_scopes", {}).get(_sha(session_id), "legacy")
                forbidden = {item["text_sha256"] for item in snapshot.get("controls", {}).get("tombstones", [])
                             if item["scope"] == routed_scope}
                if forbidden.intersection(_quote_line_hashes(source_content)):
                    raise ValueError("Source body contains a forgotten claim; redact it before queueing")
            return self._enqueue(session_id=session_id, source_path=source_path, source_content=source_content,
                                 scope=scope, backend=backend, model=model, prompt_version=prompt_version,
                                 allowed_roots=allowed_roots, max_attempts=max_attempts)

    def _enqueue(self, *, session_id, source_path, source_content, scope, backend, model,
                 prompt_version, allowed_roots, max_attempts):
        if backend not in BACKENDS:
            raise ValueError("Unsupported durable extraction backend")
        if not isinstance(session_id, str) or not session_id or not isinstance(source_content, str):
            raise ValueError("Job needs a stable session ID and original source text")
        if len(source_content.encode("utf-8")) > MAX_SOURCE_BYTES:
            raise ValueError("Source exceeds durable job payload limit")
        if isinstance(max_attempts, bool) or not isinstance(max_attempts, int) or not 1 <= max_attempts <= 100:
            raise ValueError("max_attempts must be between 1 and 100")
        if backend == "anthropic" and (not isinstance(model, str) or not model.strip()):
            raise ValueError("Anthropic jobs require an explicit model")
        source_path = os.path.abspath(os.fspath(source_path))
        digest = _sha(source_content)
        key = _sha(_json([session_id, digest, scope, backend, model, prompt_version]))
        now = time.time()
        with self._db() as db:
            db.execute("BEGIN IMMEDIATE")
            existing = db.execute("SELECT * FROM jobs WHERE idempotency_key=? AND state IN ('queued','submitted','ready')",
                                  (key,)).fetchone()
            if existing is None:
                latest = db.execute("""SELECT * FROM jobs WHERE session_id=? AND backend=?
                    AND model IS ? AND prompt_version IS ? ORDER BY created_at DESC,rowid DESC LIMIT 1""",
                                    (session_id, backend, model, prompt_version)).fetchone()
                if (latest is not None and latest["idempotency_key"] == key
                        and latest["state"] != "stale" and latest["error_code"] != "PrivacyPurge"):
                    existing = latest
            if existing is not None:
                db.execute("COMMIT")
                return {**self._public(existing), "enqueued": False}
            job_id = "job_" + uuid.uuid4().hex
            db.execute("""INSERT INTO jobs
                (id,idempotency_key,session_id,source_path,source_hash,scope,backend,model,prompt_version,
                 state,source_text,allowed_roots,max_attempts,created_at,updated_at)
                VALUES (?,?,?,?,?,?,?,?,?,'queued',?,?,?,?,?)""",
                       (job_id, key, session_id, source_path, digest, scope, backend, model, prompt_version,
                        source_content, _json(allowed_roots), max_attempts, now, now))
            db.execute("COMMIT")
        return {**self.get(job_id), "enqueued": True}

    def claim(self, worker: str, *, states=("queued",), backend: str | None = None,
              lease_seconds: float = 60, now: float | None = None,
              exclude_ids=()) -> dict[str, Any] | None:
        if not worker or not states or any(state not in ("queued", "submitted", "ready") for state in states):
            raise ValueError("A worker and claimable states are required")
        if not isinstance(lease_seconds, (int, float)) or isinstance(lease_seconds, bool) or not 0 < lease_seconds <= 86400:
            raise ValueError("lease_seconds must be positive and at most one day")
        moment = time.time() if now is None else now
        with self._db(create=False) as db:
            if db is None:
                return None
            db.execute("BEGIN IMMEDIATE")
            db.execute("""UPDATE jobs SET state='failed',source_text=NULL,result_text=NULL,result_kind=NULL,
                       batch_handle=NULL,error_code='RetryLimitExceeded',lease_owner=NULL,lease_until=NULL,updated_at=?
                       WHERE state='queued' AND attempts>=max_attempts AND (lease_until IS NULL OR lease_until<=?)""",
                       (moment, moment))
            placeholders = ",".join("?" for _ in states)
            sql = f"SELECT * FROM jobs WHERE state IN ({placeholders}) AND (lease_until IS NULL OR lease_until<=?)"
            values = [*states, moment]
            if backend:
                sql += " AND backend=?"
                values.append(backend)
            if exclude_ids:
                sql += " AND id NOT IN (" + ",".join("?" for _ in exclude_ids) + ")"
                values.extend(exclude_ids)
            sql += " AND (state!='queued' OR attempts<max_attempts) ORDER BY created_at,id LIMIT 1"
            row = db.execute(sql, values).fetchone()
            if row is None:
                db.execute("COMMIT")
                return None
            db.execute("""UPDATE jobs SET lease_owner=?,lease_until=?,updated_at=?,
                       attempts=attempts+CASE WHEN state='queued' THEN 1 ELSE 0 END WHERE id=?""",
                       (worker, moment + lease_seconds, moment, row["id"]))
            db.execute("COMMIT")
        return self.get(row["id"], include_payload=True)

    def renew(self, job_id: str, worker: str, *, lease_seconds: float = 60) -> bool:
        now = time.time()
        with self._db(create=False) as db:
            if db is None:
                return False
            changed = db.execute("UPDATE jobs SET lease_until=?,updated_at=? WHERE id=? AND lease_owner=? AND lease_until>?",
                                 (now + lease_seconds, now, job_id, worker, now)).rowcount
            return bool(changed)

    def _finish(self, job_id, state, *, worker=None, error=None, result=None, result_kind=None, batch=None,
                keep_lease=False):
        if state not in STATES:
            raise ValueError("Unknown job state")
        if result is not None and len(result.encode("utf-8")) > MAX_RESULT_BYTES:
            raise ValueError("Result exceeds durable job payload limit")
        clear = state in TERMINAL
        with self._db(create=False) as db:
            if db is None:
                raise ValueError("Job does not exist")
            db.execute("BEGIN IMMEDIATE")
            row = db.execute("SELECT * FROM jobs WHERE id=?", (job_id,)).fetchone()
            if row is None or (worker is not None and row["lease_owner"] != worker):
                db.execute("ROLLBACK")
                raise ValueError("Job lease was lost or job does not exist")
            # A privacy cancellation wins over a concurrent extraction result.
            if row["state"] in TERMINAL and row["state"] != state:
                db.execute("ROLLBACK")
                raise ValueError("Job is already terminal")
            db.execute("""UPDATE jobs SET state=?,source_text=?,result_text=?,result_kind=?,batch_handle=?,
                       error_code=?,lease_owner=?,lease_until=?,updated_at=?,result_hash=? WHERE id=?""",
                       (state, None if clear else row["source_text"],
                        None if clear else result if result is not None else row["result_text"],
                        None if clear else result_kind or row["result_kind"],
                        None if clear else _json(batch) if batch is not None else row["batch_handle"],
                        error, row["lease_owner"] if keep_lease else None,
                        row["lease_until"] if keep_lease else None, time.time(),
                        _sha(result) if result is not None else row["result_hash"], job_id))
            db.execute("COMMIT")
        return self.receipt(job_id)

    def receipt(self, job_id):
        row = self.get(job_id)
        return {"job_id": job_id, "state": row["state"], "session_id": row["session_id"],
                "source_hash": row["source_hash"], "result_hash": row["result_hash"], "error_code": row["error_code"],
                "payload_retained": row["state"] not in TERMINAL}

    def submit(self, client, *, limit: int = 20, worker: str | None = None) -> list[dict[str, Any]]:
        from llm_extractor import submit_batch
        worker = worker or "submit_" + uuid.uuid4().hex
        receipts = []
        for _ in range(limit):
            job = self.claim(worker, backend="anthropic")
            if job is None:
                break
            try:
                prompt = get_extraction_prompt(job["source_text"], job["session_id"], os.path.basename(job["source_path"]))
                # Persist the outbound intent before calling a provider. A crash
                # in the unavoidable API/SQLite gap must not silently resubmit
                # and bill twice when the outcome is unknown.
                self._finish(job["id"], "submitted", worker=worker, keep_lease=True,
                             batch={"batch_id": None, "phase": "submission_started"})
                handle = submit_batch(client, {job["session_id"]: prompt}, job["model"])
                receipts.append(self._finish(job["id"], "submitted", worker=worker, batch=handle))
            except Exception as exc:
                receipts.append(self._finish(job["id"], "failed", worker=worker, error=type(exc).__name__))
        return receipts

    def collect(self, client, *, limit: int = 20, worker: str | None = None) -> list[dict[str, Any]]:
        from llm_extractor import collect_batch
        worker = worker or "collect_" + uuid.uuid4().hex
        receipts, visited = [], set()
        for _ in range(limit):
            job = self.claim(worker, states=("submitted",), backend="anthropic", exclude_ids=visited)
            if job is None:
                break
            visited.add(job["id"])
            try:
                handle = json.loads(job["batch_handle"])
                if not handle.get("batch_id"):
                    receipts.append(self._finish(job["id"], "failed", worker=worker,
                                                 error="SubmissionOutcomeUnknown"))
                    continue
                collected = collect_batch(client, handle)
                if not collected["ready"]:
                    receipts.append(self._finish(job["id"], "submitted", worker=worker))
                elif job["session_id"] in collected["outputs"]:
                    receipts.append(self._finish(job["id"], "ready", worker=worker,
                                                 result=collected["outputs"][job["session_id"]], result_kind="units"))
                else:
                    receipts.append(self._finish(job["id"], "failed", worker=worker, error="RemoteExtractionFailed"))
            except Exception as exc:
                receipts.append(self._finish(job["id"], "failed", worker=worker, error=type(exc).__name__))
        return receipts

    def run(self, distiller, *, limit: int = 20, worker: str | None = None) -> list[dict[str, Any]]:
        """Run pending heuristic extraction only; no network backend is selected."""
        worker = worker or "run_" + uuid.uuid4().hex
        receipts = []
        for _ in range(limit):
            job = self.claim(worker, backend="heuristic")
            if job is None:
                break
            try:
                records = distiller.extract_atomic_units(job["source_text"], job["session_id"], job["source_path"])
                receipts.append(self._finish(job["id"], "ready", worker=worker, result=_json(records), result_kind="records"))
            except Exception as exc:
                receipts.append(self._finish(job["id"], "failed", worker=worker, error=type(exc).__name__))
        return receipts

    def commit(self, job_id: str, distiller, *, source_reader: Callable | None = None,
               worker: str | None = None) -> dict[str, Any]:
        """Commit exactly once after checking current source and fresh control state."""
        from napmem_controls import source_is_excluded
        from llm_extractor import parse_extraction_output, units_to_records
        job = self.get(job_id, include_payload=True)
        if job is None:
            raise ValueError("Job does not exist")
        if job["state"] in TERMINAL:
            return self.receipt(job_id)
        if job["state"] != "ready":
            raise ValueError("Only ready jobs can commit")
        with distiller.transaction():
            refreshed = self.get(job_id)
            if refreshed["state"] in TERMINAL:
                return self.receipt(job_id)
            if job_id in distiller.data.get("applied_jobs", []):
                return self._finish(job_id, "committed", worker=worker)
            try:
                current = (source_reader(job) if source_reader is not None else
                           read_source(job["source_path"], json.loads(job["allowed_roots"])))
            except (OSError, ValueError) as exc:
                return self._finish(job_id, "stale", worker=worker, error=type(exc).__name__)
            if (current is None or _sha(current["content"]) != job["source_hash"]
                    or source_is_excluded(distiller.data, current["path"], session_id=job["session_id"])):
                return self._finish(job_id, "stale", worker=worker, error="SourceChangedMissingOrExcluded")
            try:
                if job["result_kind"] == "records":
                    records = json.loads(job["result_text"])
                elif job["result_kind"] == "units":
                    records, rejected = units_to_records(parse_extraction_output(job["result_text"]), job["session_id"], current["path"])
                    if not records:
                        return self._finish(job_id, "failed", worker=worker, error="NoValidUnits")
                else:
                    return self._finish(job_id, "failed", worker=worker, error="UnsupportedResultKind")
            except Exception as exc:
                return self._finish(job_id, "failed", worker=worker, error=type(exc).__name__)
            # A rename changes anchors, not the captured extraction input.
            for record in records:
                record["source_anchor"]["file_path"] = current["path"]
            distiller.data.setdefault("applied_jobs", []).append(job_id)
            distiller.ingest_session_records(
                job["session_id"], "Durable memory extraction", current["path"], records,
                scope=job["scope"], source_content=job["source_text"],
                extraction_info={"method": job["backend"], "model": job["model"], "prompt_version": job["prompt_version"]})
        # If the process dies before this acknowledgment, applied_jobs makes the
        # ready queue row safe to replay after restarting.
        return self._finish(job_id, "committed", worker=worker)

    def commit_ready(self, distiller, *, source_reader=None, limit=20, worker=None):
        worker = worker or "commit_" + uuid.uuid4().hex
        receipts = []
        for _ in range(limit):
            job = self.claim(worker, states=("ready",))
            if job is None:
                break
            try:
                receipts.append(self.commit(job["id"], distiller, source_reader=source_reader, worker=worker))
            except (FileNotFoundError, PermissionError, UnicodeDecodeError) as exc:
                receipts.append(self._finish(job["id"], "stale", worker=worker, error=type(exc).__name__))
        return receipts

    def retry(self, job_id: str, *, source_content: str, source_path: str | None = None) -> dict[str, Any]:
        from napmem_controls import source_is_excluded, _quote_line_hashes
        from napmem_storage import read_snapshot, store_lock
        with store_lock(self.pyramid_path):
            snapshot, _ = read_snapshot(self.pyramid_path)
            with self._db(create=False) as db:
                if db is None:
                    raise ValueError("Job does not exist")
                db.execute("BEGIN IMMEDIATE")
                row = db.execute("SELECT * FROM jobs WHERE id=?", (job_id,)).fetchone()
                job = dict(row) if row is not None else None
                if job is None or job["state"] not in ("failed", "stale", "cancelled"):
                    raise ValueError("Only failed, stale or cancelled jobs can retry")
                if job["error_code"] == "PrivacyPurge":
                    raise ValueError("Privacy-purged jobs cannot retry; an allowed source needs a fresh enqueue")
                if job["attempts"] >= job["max_attempts"]:
                    raise ValueError("Job retry limit reached")
                if _sha(source_content) != job["source_hash"]:
                    raise ValueError("Retry needs the same source revision; enqueue a changed source")
                path = os.path.abspath(source_path or job["source_path"])
                if snapshot is not None:
                    if source_is_excluded(snapshot, path, session_id=job["session_id"]):
                        raise ValueError("Source is excluded or permanently forgotten")
                    scope = job["scope"] or snapshot.get("source_scopes", {}).get(_sha(job["session_id"]), "legacy")
                    forbidden = {item["text_sha256"] for item in snapshot.get("controls", {}).get("tombstones", [])
                                 if item["scope"] == scope}
                    if forbidden.intersection(_quote_line_hashes(source_content)):
                        raise ValueError("Source body contains a forgotten claim")
                db.execute("""UPDATE jobs SET state='queued',source_text=?,result_text=NULL,result_kind=NULL,
                           batch_handle=NULL,error_code=NULL,lease_owner=NULL,lease_until=NULL,source_path=?,updated_at=? WHERE id=?""",
                           (source_content, path, time.time(), job_id))
                db.execute("COMMIT")
        return self.receipt(job_id)

    def cancel(self, job_id: str) -> dict[str, Any]:
        return self._finish(job_id, "cancelled", error="OperatorCancelled")

    def purge(self, *, session_ids=(), source_hashes=(), source_paths=()) -> dict[str, Any]:
        """Cancel and clear matching local payloads; never touch unrelated jobs or source files."""
        clauses, values = [], []
        for field, selected in (("session_id", session_ids), ("source_hash", source_hashes), ("source_path", source_paths)):
            selected = list(selected)
            if selected:
                clauses.append(field + " IN (" + ",".join("?" for _ in selected) + ")")
                values.extend(os.path.abspath(item) if field == "source_path" else item for item in selected)
        if not clauses:
            return {"matched": 0, "payloads_cleared": 0, "coverage": "local_queue_only"}
        with self._db(create=False) as db:
            if db is None:
                return {"matched": 0, "payloads_cleared": 0, "coverage": "queue_absent"}
            db.execute("BEGIN IMMEDIATE")
            rows = db.execute("SELECT id FROM jobs WHERE " + " OR ".join(clauses), values).fetchall()
            db.execute("""UPDATE jobs SET state='cancelled',source_text=NULL,result_text=NULL,result_kind=NULL,
                       batch_handle=NULL,lease_owner=NULL,lease_until=NULL,error_code='PrivacyPurge',updated_at=?
                       WHERE """ + " OR ".join(clauses), [time.time(), *values])
            db.execute("COMMIT")
        return {"matched": len(rows), "payloads_cleared": len(rows), "coverage": "local_queue_only",
                "remote_provider": "operator_managed", "backups": "operator_managed"}

    def prune(self, *, older_than_seconds: float = 7 * 86400) -> dict[str, Any]:
        """Remove terminal receipts after retention; pending payloads are never age-pruned."""
        with self._db(create=False) as db:
            if db is None:
                return {"removed": 0}
            count = db.execute("DELETE FROM jobs WHERE state IN ('committed','stale','failed','cancelled') AND updated_at<?",
                               (time.time() - older_than_seconds,)).rowcount
        return {"removed": count}
