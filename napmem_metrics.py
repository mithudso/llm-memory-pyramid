"""Private, content-free local metrics and read-only operational status.

Metrics are opt-in measurements, not truth labels or automatic tuning inputs.
No event may retain source/query text, paths, raw scopes, model names or secrets.
Writes prune the bounded event window. Reads filter expired events without
rewriting files; idle files are physically pruned on the next explicit write.
"""

from __future__ import annotations

from collections import Counter
from copy import deepcopy
from datetime import UTC, datetime, timedelta
import hashlib
import json
import math
import os
import sqlite3
import stat
from typing import Any
from urllib.parse import quote

from napmem_model import build_derived, normalize_record, parse_time
from napmem_search import bounded_response, compact_json, eligible_records
from napmem_storage import atomic_write, read_snapshot, store_lock


METRICS_VERSION = "1.0.0"
MAX_METRICS_BYTES = 8 * 1024 * 1024
MAX_EVENTS = 10000
JOB_STATUS_CAP = 10000
EVENTS = ("retrieval", "ingest", "extraction", "hook_recall")
BACKENDS = ("hybrid", "lexical", "hashed", "ollama", "anthropic", "heuristic", "unavailable")
STAGES = ("request", "validation", "fallback", "ingestion", "retrieval", "hook")
RATINGS = ("useful", "wrong", "outdated")
_FLOAT_FIELDS = {"latency_ms", "lag_seconds"}
_COUNT_FIELDS = {"returned_bytes", "result_count", "rejected_units", "input_bytes", "output_bytes"}
_BOOL_FIELDS = {"empty", "fallback", "success"}
_RUNTIME_FIELDS = _FLOAT_FIELDS | _COUNT_FIELDS | _BOOL_FIELDS | {"backend", "scope_hash", "stage"}
_FEEDBACK_FIELDS = {"record_hash", "candidate_hash", "scope_hash", "rating"}
_JOB_STATES = ("queued", "submitted", "ready", "committed", "stale", "failed", "cancelled")


def _now() -> datetime:
    return datetime.now(UTC)


def _number(value: Any, field: str, maximum: float = 1e15) -> None:
    if (isinstance(value, bool) or not isinstance(value, (int, float))
            or not 0 <= value <= maximum or not math.isfinite(value)):
        raise ValueError(f"{field} must be a finite nonnegative bounded number")


def _integer(value: Any, field: str, low: int, high: int) -> None:
    if isinstance(value, bool) or not isinstance(value, int) or not low <= value <= high:
        raise ValueError(f"{field} must be an integer between {low} and {high}")


def _scope(scope: Any) -> None:
    if scope is not None:
        # Use the shared query validator without introducing a record or scope.
        import unicodedata
        if (not isinstance(scope, str) or not scope.strip() or len(scope) > 256
                or any(unicodedata.category(char) == "Cc" for char in scope)):
            raise ValueError("scope must be a bounded nonempty string without control characters")


def _digest(value: Any) -> bool:
    return isinstance(value, str) and len(value) == 64 and all(char in "0123456789abcdef" for char in value)


def _record_id(value: Any) -> None:
    if not isinstance(value, str) or not value.strip() or len(value) > 4096:
        raise ValueError("record_id must be a bounded nonempty string")


def hash_scope(scope: str | None) -> str:
    """Hash a query context; None and explicit '*' remain distinct contexts."""
    _scope(scope)
    return hashlib.sha256(compact_json(["scope", scope])).hexdigest()


def candidate_hash(record_id: str, scope: str | None = None) -> str:
    """Hash the candidate identity with its query context; never persist the inputs."""
    _record_id(record_id)
    _scope(scope)
    return hashlib.sha256(compact_json([scope, record_id])).hexdigest()


def _validate_fields(event: str, fields: dict[str, Any], *, feedback: bool = False) -> None:
    allowed = _FEEDBACK_FIELDS if feedback and event == "feedback" else _RUNTIME_FIELDS if event in EVENTS else None
    if allowed is None or not isinstance(fields, dict) or set(fields) - allowed:
        raise ValueError("Unknown metric event or fields")
    if event == "feedback" and set(fields) != _FEEDBACK_FIELDS:
        raise ValueError("Feedback requires only hashed identities and an allowed rating")
    for field, value in fields.items():
        if field in _FLOAT_FIELDS:
            _number(value, field)
        elif field in _COUNT_FIELDS:
            _integer(value, field, 0, 2 ** 63 - 1)
        elif field in _BOOL_FIELDS:
            if not isinstance(value, bool):
                raise ValueError(f"{field} must be a boolean")
        elif field in ("scope_hash", "record_hash", "candidate_hash"):
            if not _digest(value):
                raise ValueError(f"{field} must be a lowercase SHA256 digest")
        elif field == "backend" and value not in BACKENDS:
            raise ValueError("Unknown metric backend")
        elif field == "stage" and value not in STAGES:
            raise ValueError("Unknown metric stage")
        elif field == "rating" and value not in RATINGS:
            raise ValueError("Feedback rating must be useful, wrong or outdated")
    if "empty" in fields and "result_count" in fields and fields["empty"] != (fields["result_count"] == 0):
        raise ValueError("empty and result_count must agree")


def _policy(max_events, retention_days):
    _integer(max_events, "max_events", 1, MAX_EVENTS)
    _number(retention_days, "retention_days", 3650)
    if retention_days == 0:
        raise ValueError("retention_days must be positive")
    return {"max_events": max_events, "retention_days": retention_days}


def _distribution(values: list[int | float]) -> dict[str, Any]:
    if not values:
        return {"count": 0, "min": None, "p50": None, "p95": None, "max": None, "mean": None}
    ordered = sorted(values)
    middle = len(ordered) // 2
    median = ordered[middle] if len(ordered) % 2 else (ordered[middle - 1] + ordered[middle]) / 2
    return {"count": len(ordered), "min": ordered[0], "p50": median,
            "p95": ordered[math.ceil(.95 * len(ordered)) - 1], "max": ordered[-1],
            "mean": sum(ordered) / len(ordered)}


def _rates(rows: list[dict[str, Any]]) -> dict[str, Any]:
    known_success = [row for row in rows if "success" in row]
    # Failures have their own rate; they do not masquerade as successful empty retrievals.
    known_empty = [row for row in rows if "empty" in row and row.get("success") is not False]
    staged_fallback = [row for row in rows if row.get("stage") == "fallback"]
    known_fallback = staged_fallback or [row for row in rows if "fallback" in row]
    failed = sum(not row["success"] for row in known_success)
    empty = sum(row["empty"] for row in known_empty)
    fallback = sum(row.get("fallback", row.get("stage") == "fallback") for row in known_fallback)
    return {"count": len(rows), "success_observations": len(known_success), "failure_count": failed,
            "failure_rate": failed / len(known_success) if known_success else None,
            "empty_observations": len(known_empty), "empty_count": empty,
            "empty_rate": empty / len(known_empty) if known_empty else None,
            "fallback_observations": len(known_fallback), "fallback_count": fallback,
            "fallback_rate": fallback / len(known_fallback) if known_fallback else None,
            "fallback_rate_basis": "stage:fallback" if staged_fallback else "explicit_fallback_field"}


def _aggregate(rows: list[dict[str, Any]]) -> dict[str, Any]:
    result = _rates(rows)
    result.update({"latency_ms": _distribution([row["latency_ms"] for row in rows if "latency_ms" in row]),
                   "returned_bytes": _distribution([row["returned_bytes"] for row in rows if "returned_bytes" in row]),
                   "rejected_units": sum(row.get("rejected_units", 0) for row in rows),
                   "input_bytes": sum(row.get("input_bytes", 0) for row in rows),
                   "output_bytes": sum(row.get("output_bytes", 0) for row in rows)})
    return result


class MetricsStore:
    """An explicit local opt-in sink. Construction and summarize never create files.

    Feedback keeps the latest opinion per scoped candidate. Separate record
    hashes let forgetting purge that record's feedback across every scope.
    Hashes pseudonymize identifiers; they are not protection against guessing.
    """

    def __init__(self, pyramid_path, max_events: int = 1000, retention_days: float = 30):
        self.path = os.fspath(pyramid_path) + ".metrics.json"
        self.policy = _policy(max_events, retention_days)

    def _read(self):
        try:
            details = os.lstat(self.path)
        except FileNotFoundError:
            return {"version": METRICS_VERSION, "generation": 0, "retention": self.policy, "events": []}, None
        if not stat.S_ISREG(details.st_mode) or details.st_nlink != 1 or details.st_size > MAX_METRICS_BYTES or details.st_mode & 0o077:
            raise ValueError("Metrics must be a bounded, singly-linked regular file")
        data, digest = read_snapshot(self.path)
        if data is None:  # An atomic unlink can race this read; it is still an absent snapshot.
            return {"version": METRICS_VERSION, "generation": 0, "retention": self.policy, "events": []}, None
        if (set(data) != {"version", "generation", "retention", "events"}
                or data["version"] != METRICS_VERSION or not isinstance(data["retention"], dict)
                or set(data["retention"]) != {"max_events", "retention_days"}
                or not isinstance(data["events"], list) or len(data["events"]) > MAX_EVENTS):
            raise ValueError("Malformed persistent metrics")
        _integer(data["generation"], "generation", 0, 2 ** 63 - 1)
        _policy(**data["retention"])
        for event in data["events"]:
            if not isinstance(event, dict) or set(event) != {"event", "at", "fields"}:
                raise ValueError("Malformed persistent metric event")
            if not isinstance(event["at"], str) or len(event["at"]) > 64:
                raise ValueError("Metric timestamps must be bounded timezone-aware ISO timestamps")
            parse_time(event["at"], "metric timestamp")
            _validate_fields(event["event"], event["fields"], feedback=True)
        return data, digest

    @staticmethod
    def _retained(data, at, *, policy=None, exclude_future=False):
        policy = policy or data["retention"]
        try:
            cutoff = at - timedelta(days=policy["retention_days"])
        except OverflowError:
            cutoff = datetime.min.replace(tzinfo=UTC)
        rows = [row for row in data["events"] if parse_time(row["at"]) >= cutoff
                and (not exclude_future or parse_time(row["at"]) <= at)]
        rows.sort(key=lambda row: parse_time(row["at"]))
        return rows[-policy["max_events"]:]

    def _write(self, data, digest):
        data["generation"] += 1
        # The event cap and the file cap both apply, even with a larger custom window.
        while True:
            size = len((json.dumps(data, ensure_ascii=False, indent=2, allow_nan=False) + "\n").encode())
            if size <= MAX_METRICS_BYTES:
                break
            if not data["events"]:
                raise ValueError("Metrics metadata exceeds the file cap")
            drop = max(1, math.ceil(len(data["events"]) * (size - MAX_METRICS_BYTES) / size))
            del data["events"][:drop]
        atomic_write(self.path, data, expected_fingerprint=digest)
        return {"metrics": "recorded", "generation": data["generation"], "retained_events": len(data["events"])}

    def _append(self, event, fields, *, replace_candidate=False):
        moment = _now()
        with store_lock(self.path):
            data, digest = self._read()
            data["events"] = self._retained(data, moment, policy=self.policy)
            if replace_candidate:
                data["events"] = [row for row in data["events"] if not (
                    row["event"] == "feedback" and row["fields"]["candidate_hash"] == fields["candidate_hash"])]
            data["events"].append({"event": event, "at": moment.isoformat(), "fields": deepcopy(fields)})
            data["retention"] = deepcopy(self.policy)
            data["events"] = self._retained(data, moment)
            return {**self._write(data, digest), "event": event}

    def record(self, event: str, **fields) -> dict[str, Any]:
        """Record only allowlisted numbers, booleans, enums and scope hashes."""
        _validate_fields(event, fields)
        fields.setdefault("scope_hash", hash_scope(None))
        return self._append(event, fields)

    def feedback(self, record_id: str, rating: str, scope: str | None = None) -> dict[str, Any]:
        """Explicit opinion; neither rating nor repeated feedback establishes truth."""
        fields = {"record_hash": hashlib.sha256(record_id.encode()).hexdigest() if isinstance(record_id, str) else None,
                  "candidate_hash": candidate_hash(record_id, scope), "scope_hash": hash_scope(scope), "rating": rating}
        _validate_fields("feedback", fields, feedback=True)
        return {**self._append("feedback", fields, replace_candidate=True), "candidate_hash": fields["candidate_hash"]}

    def summarize(self, *, scope_hash: str | None = None,
                  as_of: str | datetime | None = None) -> dict[str, Any]:
        """Aggregate the retained window without pruning or rewriting its file.

        Rates disclose their observation denominators. Extraction stage rates
        remain separate. fallback_per_request is null when no request events
        exist; validation events never enter that denominator.
        """
        if scope_hash is not None and not _digest(scope_hash):
            raise ValueError("scope_hash must be a lowercase SHA256 digest")
        at = parse_time(as_of, "as_of") if as_of is not None else _now()
        data, digest = self._read()
        retained = self._retained(data, at, exclude_future=True)
        rows = [row for row in retained if scope_hash is None or row["fields"].get("scope_hash") == scope_hash]
        result = {"status": "missing" if digest is None else "ok", "generation": data["generation"],
                  "scope_hash": scope_hash, "retained_events": len(rows), "stored_events": len(data["events"]),
                  "excluded_by_retention": len(data["events"]) - len(retained),
                  "retention": {**data["retention"], "physical_pruning": "on_explicit_write"},
                  "event_counts": dict(sorted(Counter(row["event"] for row in rows).items())),
                  "by_stage": {}, "feedback": {"count": 0, "ratings": dict.fromkeys(RATINGS, 0),
                                               "interpretation": "latest operator opinion per scoped candidate; not truth"}}
        for kind in EVENTS:
            fields = [row["fields"] for row in rows if row["event"] == kind]
            result[kind] = _aggregate(fields)
            grouped = {}
            for stage in (*STAGES, "unspecified"):
                members = [row for row in fields if row.get("stage", "unspecified") == stage]
                if members:
                    grouped[stage] = _aggregate(members)
            if grouped:
                result["by_stage"][kind] = grouped
            if kind == "extraction":
                requests = sum(row.get("stage") == "request" for row in fields)
                fallbacks = sum(row.get("stage") == "fallback" for row in fields)
                result[kind]["fallback_per_request"] = {"numerator": fallbacks, "denominator": requests,
                                                        "rate": fallbacks / requests if requests else None}
        feedback = [row["fields"] for row in rows if row["event"] == "feedback"]
        result["feedback"]["count"] = len(feedback)
        result["feedback"]["ratings"].update(Counter(row["rating"] for row in feedback))
        return result

    def purge(self, candidate_ids) -> dict[str, Any]:
        """Remove feedback by raw record IDs or by already hashed candidate IDs.

        Raw IDs are hashed in memory only. A record ID removes every scoped
        opinion for that record; a candidate hash removes that candidate alone.
        Missing stores and no-op purges never create or rewrite anything.
        """
        if isinstance(candidate_ids, (str, bytes)):
            raise ValueError("candidate_ids must be a bounded collection of IDs")
        targets = set()
        try:
            candidates = iter(candidate_ids)
        except TypeError as exc:
            raise ValueError("candidate_ids must be a bounded collection of IDs") from exc
        for idx, identity in enumerate(candidates):
            if idx >= MAX_EVENTS:
                raise ValueError("Too many purge candidates")
            _record_id(identity)
            targets.add(hashlib.sha256(identity.encode()).hexdigest())
            if _digest(identity):
                targets.add(identity)
        if not targets:
            return {"metrics": "unchanged", "removed": 0, "coverage": "local_feedback_only"}
        # Check absence before taking a writer lock, which itself creates a sidecar.
        if not os.path.lexists(self.path):
            return {"metrics": "absent", "removed": 0, "coverage": "local_feedback_only"}
        with store_lock(self.path):
            data, digest = self._read()
            kept = [row for row in data["events"] if not (row["event"] == "feedback" and
                    (row["fields"]["record_hash"] in targets or row["fields"]["candidate_hash"] in targets))]
            removed = len(data["events"]) - len(kept)
            if not removed:
                return {"metrics": "unchanged", "removed": 0, "coverage": "local_feedback_only"}
            data["events"] = self._retained({**data, "events": kept}, _now(), policy=self.policy)
            data["retention"] = deepcopy(self.policy)
            self._write(data, digest)
        return {"metrics": "purged", "removed": removed, "coverage": "local_feedback_only",
                "backups": "operator_managed"}


def record_if_enabled(pyramid_path, event: str, **fields) -> dict[str, Any] | None:
    """Best-effort runtime opt-in; measurement failure cannot fail memory work."""
    if os.environ.get("NAPMEM_METRICS", "").lower() not in ("1", "true"):
        return None
    try:
        return MetricsStore(pyramid_path).record(event, **fields)
    except (OSError, ValueError):
        return {"metrics": "unavailable"}


def record_hook_outcome(pyramid_path, *, success: bool, latency_ms=None, result_count=None,
                        returned_bytes=None, empty=None, fallback=None, backend="unavailable",
                        lag_seconds=None, scope=None) -> dict[str, Any]:
    """Record an explicitly measured hook outcome. Calling this API opts in."""
    fields = {"success": success, "backend": backend, "stage": "hook", "scope_hash": hash_scope(scope)}
    fields.update({key: value for key, value in {"latency_ms": latency_ms, "result_count": result_count,
                   "returned_bytes": returned_bytes, "empty": empty, "fallback": fallback,
                   "lag_seconds": lag_seconds}.items() if value is not None})
    return MetricsStore(pyramid_path).record("hook_recall", **fields)


def _allows(scope, actual):
    return scope == "*" or actual in (("legacy", "global") if scope is None else (scope, "global"))


def _age_seconds(value, at):
    if value is None:
        return None
    try:
        elapsed = (at - parse_time(value)).total_seconds()
    except ValueError:
        return None
    return elapsed if elapsed >= 0 else None


def _current_counts(data, scope, at):
    families = eligible_records(data, scope, at.isoformat())
    records = []
    for owner in families:
        own = deepcopy(owner)
        own["duplicates"], own["duplicate_anchors"] = [], {}
        records.append(own)
        for rid, anchor in owner["duplicate_anchors"].items():
            alias = {field: owner[field] for field in ("type", "salience", "topic_slug")}
            alias.update(deepcopy(anchor.get("assertion", {})))
            alias.update(id=rid, canonical=owner["canonical"], source_anchor=deepcopy(anchor),
                         text=anchor.get("paraphrase_text", owner["text"]))
            records.append(normalize_record(alias))
    projected = {"memory_records": deepcopy(records)}
    for record in projected["memory_records"]:
        record.update(status="active", valid_from=None, valid_to=None)
    build_derived(projected)
    return {"current_records": len(families), "current_assertions": len(records),
            "profiles": len(projected["user_profiles"]), "tracks": len(projected["topic_tracks"]),
            "potential_conflicts": len(projected["conflicts"]),
            "unreviewed_current": sum(r["review_status"] != "approved" for r in records),
            "unverified_current": sum(r["evidence"].get("status") != "verified" for r in records)}


def _sources_status(path, data, scope, at):
    from napmem_sources import SourceRegistry
    source_path = path + ".sources.json"
    if not os.path.exists(source_path):
        return {"status": "missing", "count": 0, "pending": 0, "oldest_lag_seconds": None}
    try:
        entries = SourceRegistry(path).list()
        excluded = data.get("controls", {}).get("excluded_sources", {}) if data else {}
        selected = []
        for entry in entries:
            actual = entry.get("scope", "legacy")
            _scope(actual)
            if _allows(scope, actual):
                selected.append(entry)
        present, missing, suppressed, pending, lags, unknown_lag = 0, 0, 0, 0, [], 0
        for entry in selected:
            if os.path.normpath(entry["path"]) in excluded or "session:" + entry["session_id"] in excluded:
                suppressed += 1
                continue
            if entry["status"] == "missing":
                missing += 1
                continue
            present += 1
            if entry.get("sha256") != entry.get("committed_sha256"):
                pending += 1
                mtime = entry.get("mtime")
                if isinstance(mtime, (int, float)) and not isinstance(mtime, bool) and 0 <= mtime <= at.timestamp() and math.isfinite(mtime):
                    lags.append(at.timestamp() - mtime)
                else:
                    unknown_lag += 1
        return {"status": "ok", "count": len(selected), "present": present, "missing": missing,
                "suppressed": suppressed, "pending": pending, "oldest_lag_seconds": max(lags) if lags else None,
                "pending_unknown_lag": unknown_lag, "lag_basis": "registered source mtime; not measured extraction duration"}
    except (OSError, ValueError, TypeError, KeyError):
        return {"status": "invalid", "count": None, "pending": None, "oldest_lag_seconds": None}


def _jobs_status(path, scope, at):
    job_path = path + ".jobs.sqlite3"
    try:
        details = os.lstat(job_path)
    except FileNotFoundError:
        return {"status": "missing", "states": dict.fromkeys(_JOB_STATES, 0), "row_cap": JOB_STATUS_CAP,
                "counts_complete": True, "rows_examined": 0, "oldest_pending_lag_seconds": None}
    try:
        if not stat.S_ISREG(details.st_mode) or details.st_nlink != 1:
            raise ValueError("Unsafe job metadata file")
        condition, parameters = "", []
        if scope is None:
            condition = " WHERE scope IS NULL OR scope IN ('legacy','global')"
        elif scope != "*":
            condition, parameters = " WHERE scope IN (?, 'global')", [scope]
        uri = "file:" + quote(os.path.abspath(job_path), safe="/") + "?mode=ro"
        with sqlite3.connect(uri, uri=True, timeout=1) as db:
            db.execute("PRAGMA query_only=ON")
            db.execute("PRAGMA temp_store=MEMORY")
            rows = db.execute("SELECT state,created_at FROM jobs" + condition + " ORDER BY created_at,id LIMIT ?",
                              [*parameters, JOB_STATUS_CAP + 1]).fetchall()
        complete = len(rows) <= JOB_STATUS_CAP
        rows = rows[:JOB_STATUS_CAP]
        counts, lags = dict.fromkeys(_JOB_STATES, 0), []
        for state, created in rows:
            if state not in counts:
                raise ValueError("Unknown job state")
            counts[state] += 1
            if state in ("queued", "submitted", "ready"):
                _number(created, "job timestamp")
                if created <= at.timestamp():
                    lags.append(at.timestamp() - created)
        return {"status": "ok", "states": counts, "row_cap": JOB_STATUS_CAP, "counts_complete": complete,
                "rows_examined": len(rows), "oldest_pending_lag_seconds": max(lags) if lags else None,
                "lag_basis": "job creation time", "payloads_read": False}
    except (OSError, ValueError, sqlite3.Error):
        return {"status": "invalid", "states": None, "row_cap": JOB_STATUS_CAP, "counts_complete": False}


def _deletion_status(data):
    receipts = data.get("deletion_receipts", []) if data else []
    if not isinstance(receipts, list) or any(not isinstance(r, dict) for r in receipts):
        return {"status": "invalid"}
    pending_cache = sum(isinstance(r.get("cache"), str) and r["cache"].startswith("pending") for r in receipts)
    pending_jobs, pending_metrics, pending_mirrors = 0, 0, 0
    for receipt in receipts:
        for key in ("jobs", "metrics"):
            value = receipt.get(key)
            coverage = value.get("coverage", value.get("metrics")) if isinstance(value, dict) else value
            pending = isinstance(coverage, str) and (coverage.startswith("pending") or coverage == "unavailable")
            if key == "jobs":
                pending_jobs += pending
            else:
                pending_metrics += pending
        pending_mirrors += receipt.get("mirrors") not in (None, "acknowledged", "complete")
    return {"status": "pending" if any((pending_cache, pending_jobs, pending_metrics, pending_mirrors)) else "no_pending_receipts",
            "receipts": len(receipts), "pending_cache": pending_cache, "pending_jobs": pending_jobs,
            "pending_metrics": pending_metrics, "pending_mirrors": pending_mirrors,
            "coverage": "store-wide retained receipts; unreachable replicas are not verified",
            "originals_exports_backups": "operator_managed"}


def _mirror_status(directory, at, generation):
    if directory is None:
        return {"status": "not_requested"}
    from napmem_snapshots import load_snapshot
    try:
        snapshot = load_snapshot(directory)
        if snapshot["verification"]["status"] != "verified":
            return {"status": "unverified", "generation": None, "age_seconds": None}
        manifest = snapshot["manifest"]
        lag = generation - manifest["generation"] if generation is not None else None
        return {"status": "verified", "generation": manifest["generation"],
                "age_seconds": _age_seconds(manifest["created_at"], at),
                "generation_lag": lag, "generation_relation": "unknown" if lag is None else
                "behind" if lag > 0 else "ahead" if lag < 0 else "same",
                "cache": snapshot["verification"]["cache"]}
    except FileNotFoundError:
        return {"status": "missing", "generation": None, "age_seconds": None}
    except (OSError, ValueError, KeyError, TypeError):
        return {"status": "invalid", "generation": None, "age_seconds": None}


def status_report(pyramid_path, scope=None, as_of=None, mirror_dir=None,
                  max_bytes: int = 16384, max_tokens: int | None = 2048) -> dict[str, Any]:
    """Read metadata-only operational status; no initialization, source reads or probes.

    Sidecars are independent snapshots, not an atomic multi-file transaction.
    Missing metrics do not mean zero failures; absent/invalid values stay explicit.
    As-of controls assertion valid time and metric windows, not a past disk snapshot.
    """
    _scope(scope)
    at = parse_time(as_of, "as_of") if as_of is not None else _now()
    path = os.path.abspath(os.fspath(pyramid_path))
    data = None
    try:
        raw, _ = read_snapshot(path)
        if raw is None:
            store = {"status": "missing", "generation": None, "schema": None, "counts": None}
        else:
            from napmem_retrieval_agent import NapMemRetrievalAgent
            agent = NapMemRetrievalAgent(path)
            data = agent.data
            updated = data.get("updated_at")
            try:
                updated = parse_time(updated).isoformat()
            except ValueError:
                updated = None
            store = {"status": "ok", "generation": data["generation"], "schema": data["version"],
                     "snapshot_sha256": agent._seen_fingerprint,
                     "updated_at": updated,
                     "updated_time_status": "unknown" if updated is None else "future" if parse_time(updated) > at else "known",
                     "age_seconds": _age_seconds(updated, at), "counts": _current_counts(data, scope, at)}
    except (OSError, ValueError, KeyError, TypeError):
        store = {"status": "invalid", "generation": None, "schema": None, "counts": None}
    sources = _sources_status(path, data, scope, at)
    jobs = _jobs_status(path, scope, at)
    try:
        full_metrics = MetricsStore(path).summarize(scope_hash=None if scope == "*" else hash_scope(scope), as_of=at)
        metrics = {key: full_metrics[key] for key in ("status", "retained_events", "retention", "event_counts", "feedback", "retrieval", "hook_recall")}
        metrics["failures_by_event"] = {kind: full_metrics[kind]["failure_count"] for kind in EVENTS}
        metrics["extraction_stages"] = {
            stage: {key: values[key] for key in ("count", "failure_count", "rejected_units", "latency_ms")}
            for stage, values in full_metrics["by_stage"].get("extraction", {}).items()}
    except (OSError, ValueError, TypeError, KeyError):
        metrics = {"status": "invalid", "retained_events": None}
    deletion = _deletion_status(data) if data is not None else {"status": "unavailable"}
    mirror = _mirror_status(mirror_dir, at, store.get("generation"))
    failures = bool((jobs.get("states") or {}).get("failed") or any(metrics.get("failures_by_event", {}).values()))
    invalid_sidecar = any(item.get("status") == "invalid" for item in (sources, jobs, metrics, deletion, mirror))
    state = store["status"] if store["status"] != "ok" else "degraded" if invalid_sidecar or failures else "ok"
    payload = {"status": state, "as_of": at.isoformat(), "scope_hash": hash_scope(scope), "store": store,
               "sources": sources, "jobs": jobs, "metrics": metrics, "deletion": deletion, "mirror": mirror,
               "interpretation": {"freshness": "reported ages/backlog; no automatic staleness threshold",
                                  "failures": "observed" if failures else "none_in_available_observations",
                                  "quality": "unmeasured; feedback is opinion and empty retrieval is not a truth verdict"},
               "snapshot_consistency": "independent read-only component snapshots", "records": []}
    return bounded_response(payload, max_bytes=max_bytes, max_tokens=max_tokens)
