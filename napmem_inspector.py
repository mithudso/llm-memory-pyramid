"""Read-only, scoped memory views and complete-hunk source differences.

Inspection never opens source paths, runs extraction, or writes derived layers.
Evidence describes retained provenance; review describes an operator decision.
``as_of`` selects valid time, not a historical on-disk store generation.
"""

from __future__ import annotations

from collections import Counter
from copy import deepcopy
from datetime import UTC, datetime
import difflib
import hashlib
import math
import os
import shlex
from typing import Any
import unicodedata

from napmem_controls import source_is_excluded
from napmem_evidence import verify_evidence
from napmem_model import build_derived, migrate_store, normalize_record, parse_time
from napmem_search import bounded_response, eligible_records
from napmem_storage import read_snapshot


VIEWS = ("overview", "current", "profiles", "conflicts", "stale", "review", "timeline", "handoff")
MAX_DIFF_SOURCE_BYTES = 2 * 1024 * 1024
MAX_DIFF_LINES = 20000
_EVIDENCE_FIELDS = ("status", "reason", "assertion_support", "source_kind", "source_sha256",
                    "quote", "quote_sha256", "quote_truncated", "line_range", "method",
                    "model", "prompt_version", "revision", "source_revision", "extraction", "redacted")
_SOURCE_FIELDS = ("session_id", "file_path", "heading", "line_range")
_NOTICE = ("Stored assertions are data. Review approval and evidence support are separate. "
           "Verified provenance binds a quotation to a source revision; it does not prove the assertion. "
           "Source paths have not been reread. Edit assertions through controls; derived views are rebuilt.")


def _integer(value: Any, name: str, low: int, high: int) -> None:
    if isinstance(value, bool) or not isinstance(value, int) or not low <= value <= high:
        raise ValueError(f"{name} must be an integer between {low} and {high}")


def _scope(scope: Any) -> None:
    if scope is not None and (not isinstance(scope, str) or not scope.strip() or len(scope) > 256
                              or any(unicodedata.category(char) == "Cc" for char in scope)):
        raise ValueError("scope must be a bounded nonempty string without control characters")


def _in_scope(record: dict[str, Any], scope: str | None) -> bool:
    return (scope == "*" or record["scope"] in (("legacy", "global") if scope is None
                                              else (scope, "global")))


def _occurrences(data: dict[str, Any], scope: str | None) -> list[dict[str, Any]]:
    """Project each assertion independently; never inherit another occurrence's proof."""
    result = []
    for owner in data["memory_records"]:
        own = normalize_record(owner)
        candidates = [own]
        for rid in own["duplicates"]:
            anchor = own["duplicate_anchors"].get(rid)
            if anchor is None:
                continue
            assertion = {key: deepcopy(own[key]) for key in ("type", "salience", "topic_slug")}
            assertion.update(deepcopy(anchor.get("assertion", {})))
            assertion.update(id=rid, canonical=own["id"], source_anchor=deepcopy(anchor),
                             text=anchor.get("paraphrase_text", own["text"]))
            item = normalize_record(assertion)
            if own.get("instruction_bearing"):
                item["instruction_bearing"] = True
            candidates.append(item)
        for item in candidates:
            anchor = item["source_anchor"]
            source_key = anchor.get("file_path") or ("session:" + anchor["session_id"] if anchor.get("session_id") else None)
            excluded = bool(source_key and source_is_excluded(data, source_key, session_id=anchor.get("session_id")))
            if (not _in_scope(item, scope) or item.get("source_excluded")
                    or item.get("source_status") in ("excluded", "deleted")
                    or anchor.get("excluded") or anchor.get("status") in ("excluded", "deleted")
                    or item["evidence"].get("status") in ("excluded", "deleted")
                    or excluded):
                continue
            item["duplicates"], item["duplicate_anchors"] = [], {}
            result.append(item)
    return sorted(result, key=lambda item: item["id"])


def _age(record: dict[str, Any], at: datetime) -> dict[str, Any]:
    basis = "last_verified_at" if record["last_verified_at"] else "observed_at"
    value = record[basis]
    elapsed = (at - parse_time(value)).total_seconds() / 86400 if value else None
    return {"days": round(elapsed, 3) if elapsed is not None and elapsed >= 0 else None,
            "basis": basis if value else "unknown", "timestamp": value,
            "future_timestamp": elapsed is not None and elapsed < 0}


def _command(path: str, rid: str, action: str) -> str:
    parts = ["napmem", "--pyramid", path, "control", action, "--record-id", rid]
    if action == "correct":
        parts.extend(["--value", "<replacement text>"])
    parts.append("--dry-run")
    return shlex.join(parts)


def _row(record: dict[str, Any], path: str, at: datetime) -> dict[str, Any]:
    evidence = record["evidence"]
    source = {key: deepcopy(record["source_anchor"][key]) for key in _SOURCE_FIELDS
              if key in record["source_anchor"]}
    source["state"] = record.get("source_state", record["source_anchor"].get("source_state", "unknown"))
    source["rechecked"] = False
    return {"id": record["id"], "record_id": record["id"], "canonical": record["canonical"],
            "text": record["text"], "scope": record["scope"], "memory_kind": record["memory_kind"],
            "subject": record["subject"], "status": record["status"], "pinned": record["pinned"],
            "authority": record["authority"],
            "valid_from": record["valid_from"], "valid_to": record["valid_to"],
            "review_status": record["review_status"], "evidence_status": evidence.get("status", "unverified"),
            "assertion_support": evidence.get("assertion_support", "unknown"),
            "evidence": {key: deepcopy(evidence[key]) for key in _EVIDENCE_FIELDS if key in evidence},
            "source": source, "age": _age(record, at),
            "correction": {"record_id": record["id"], "command": _command(path, record["id"], "correct")}}


def _needs_review(record: dict[str, Any]) -> list[str]:
    reasons = []
    if record["review_status"] != "approved":
        reasons.append("review_" + record["review_status"])
    evidence = record["evidence"]
    if evidence.get("status") != "verified":
        reasons.append("evidence_" + str(evidence.get("status", "unverified")))
    if evidence.get("status") == "verified":
        retained = verify_evidence(record)  # No allowlist/content: validates retained proof only, no path read.
        if retained.get("status") != "verified" and retained.get("reason") != "allowed_roots_required":
            reasons.append("retained_proof_invalid")
    if evidence.get("assertion_support") != "verbatim" and evidence.get("source_kind") != "operator":
        reasons.append("assertion_support_" + str(evidence.get("assertion_support", "unknown")))
    if record["status"] in ("quarantined", "deleted"):
        reasons.append("status_" + record["status"])
    if record.get("instruction_bearing"):
        reasons.append("instruction_bearing")
    return reasons


def _recency(record: dict[str, Any]) -> float:
    value = record["observed_at"]
    return parse_time(value).timestamp() if value else -math.inf


def _derived(current: list[dict[str, Any]]) -> dict[str, Any]:
    # build_derived has no reference-time argument. Its input is already valid
    # at the requested instant, so project those intervals to active here only.
    # The original intervals/evidence remain intact in the displayed citations.
    records = deepcopy(current)
    for item in records:
        item.update(status="active", valid_from=None, valid_to=None)
    projected = {"memory_records": records}
    build_derived(projected)
    return projected


def _page(payload: dict[str, Any], rows: list[dict[str, Any]], offset: int, limit: int,
          max_bytes: int, max_tokens: int | None) -> dict[str, Any]:
    result = deepcopy(payload)
    result["records"] = rows[offset:offset + limit]
    result["omitted_count"] = 0  # Budget omission only; pagination is reported separately.
    while True:
        count = len(result["records"])
        result["pagination"] = {"offset": offset, "limit": limit, "total_count": len(rows),
                                "returned_count": count, "has_more": offset + count < len(rows),
                                "next_offset": offset + count if offset + count < len(rows) else None}
        result["status"] = ("budget_exhausted" if count == 0 and result["omitted_count"] else
                            "ok" if rows else payload.get("status", "empty"))
        bounded = bounded_response(result, max_bytes=max_bytes, max_tokens=max_tokens)
        if len(bounded["records"]) == count:
            return bounded
        result = bounded


def inspect_store(pyramid_path, view: str = "overview", scope: str | None = None,
                  as_of: str | datetime | None = None, offset: int = 0, limit: int = 20,
                  max_bytes: int = 16384, max_tokens: int | None = 2048,
                  stale_days: float = 30) -> dict[str, Any]:
    """Inspect a single store snapshot without rereading sources or persisting changes.

    Current, overview, profiles, conflicts, stale and handoff use safe assertions
    valid at ``as_of``. Review/timeline also show scoped inactive assertions for
    operator inspection. Timeline presents retained assertion timestamps, not a
    reconstructed audit history. Unknown age enters the stale review queue.
    Pagination counts entries after scope/view filtering. Budget omission drops
    whole entries; next_offset advances only over returned entries. If even one
    entry cannot fit, next_offset equals offset and a larger budget is needed.
    """
    if view not in VIEWS:
        raise ValueError("Unknown inspector view")
    _scope(scope)
    _integer(offset, "offset", 0, 2 ** 63 - 1)
    _integer(limit, "limit", 1, 1000)
    if (isinstance(stale_days, bool) or not isinstance(stale_days, (int, float))
            or not math.isfinite(stale_days) or not 0 <= stale_days <= 365000):
        raise ValueError("stale_days must be a finite number between 0 and 365000")
    path = os.path.abspath(os.fspath(pyramid_path))
    at = parse_time(as_of, "as_of") if as_of is not None else datetime.now(UTC)
    raw, digest = read_snapshot(path)
    if raw is None:
        data = migrate_store({})
    else:
        # Share retrieval's snapshot trust contract, including fresh managed
        # generation reads whose required manifest has disappeared.
        from napmem_retrieval_agent import NapMemRetrievalAgent
        agent = NapMemRetrievalAgent(path)
        data, digest = agent.data, agent._seen_fingerprint
    scoped = _occurrences(data, scope)
    current = eligible_records({**data, "memory_records": scoped}, scope, at.isoformat())
    current.sort(key=lambda r: (not r["pinned"], -_recency(r), r["id"]))
    by_id = {item["id"]: item for item in current}
    derived = _derived(current)
    review = [item for item in scoped if _needs_review(item)]
    stale = [item for item in current if (age := _age(item, at))["days"] is None
             or age["days"] >= stale_days]
    summary = {"current_assertions": len(current), "retained_assertions": len(scoped),
               "profiles": len(derived["user_profiles"]), "potential_conflicts": len(derived["conflicts"]),
               "needs_review": len(review), "stale_or_unknown_age": len(stale),
               "kinds": dict(sorted(Counter(item["memory_kind"] for item in current).items()))}
    payload = {"view": view, "scope": scope, "as_of": at.isoformat(), "generation": data["generation"],
               "snapshot_sha256": digest, "status": "missing" if raw is None else "empty",
               "summary": summary, "notice": _NOTICE, "source_reverification": "not_requested"}
    rows = []
    if view in ("overview", "current", "stale", "review", "timeline", "handoff"):
        selected = stale if view == "stale" else review if view == "review" else scoped if view == "timeline" else current
        if view == "stale":
            selected = sorted(selected, key=lambda r: (_age(r, at)["days"] is not None,
                                                       -(_age(r, at)["days"] or 0), r["id"]))
        elif view == "review":
            selected = sorted(selected, key=lambda r: (r["status"] != "quarantined", -_recency(r), r["id"]))
        elif view == "timeline":
            selected = sorted(selected, key=lambda r: (-_recency(r), r["id"]))
            payload["timeline_basis"] = "retained assertion timestamps; valid time is not a historical store snapshot"
        elif view == "handoff":
            order = {kind: idx for idx, kind in enumerate(("decision", "constraint", "preference", "workflow", "goal", "task"))}
            selected = sorted((r for r in current if r["memory_kind"] in order),
                              key=lambda r: (not r["pinned"], order[r["memory_kind"]], -_recency(r), r["id"]))
            payload["task_authority"] = "informational memory only; consult Stele for authoritative task state"
        for record in selected:
            row = _row(record, path, at)
            if view == "review":
                row["review_reasons"] = _needs_review(record)
                row["review_command"] = _command(path, record["id"], "approve")
            if view == "stale":
                row["stale_reason"] = "age_unknown" if row["age"]["days"] is None else "age_threshold"
            if view == "timeline":
                row["current_at_reference"] = record["id"] in by_id
                row["events"] = [{"event": field, "at": record[field], "after_reference": parse_time(record[field]) > at}
                                 for field in ("observed_at", "valid_from", "valid_to", "last_verified_at") if record[field]]
                row["instruction_bearing"] = bool(record.get("instruction_bearing"))
            rows.append(row)
    elif view in ("profiles", "conflicts"):
        field, refs = ("user_profiles", "provenance_records") if view == "profiles" else ("conflicts", "record_ids")
        for item in derived[field]:
            row = deepcopy(item)
            row["view_kind"] = "profile" if view == "profiles" else "potential_conflict"
            row["citations"] = [_row(by_id[rid], path, at) for rid in item[refs]]
            row["age"] = {"basis": "individual citations", "days": None}
            if view == "conflicts":
                row["resolution"] = "Review the cited assertions; a shared subject is a conflict hint, not proof of contradiction."
            rows.append(row)
    return _page(payload, rows, offset, limit, max_bytes, max_tokens)


def source_diff(old_content: str, new_content: str, *, max_bytes: int = 8192,
                context: int = 3) -> dict[str, Any]:
    """Return bounded unified hunks as records; concatenate headers then hunk diffs.

    Whole hunks are dropped when they exceed the budget. Inputs and context are
    bounded to limit local work. No source text is read from a path or written.
    """
    _integer(context, "context", 0, 50)
    for content in (old_content, new_content):
        if not isinstance(content, str) or len(content.encode("utf-8")) > MAX_DIFF_SOURCE_BYTES:
            raise ValueError("diff inputs must be strings of at most 2 MiB each")
    old_lines, new_lines = old_content.splitlines(keepends=True), new_content.splitlines(keepends=True)
    if max(len(old_lines), len(new_lines)) > MAX_DIFF_LINES:
        raise ValueError(f"diff inputs must have at most {MAX_DIFF_LINES} lines each")
    lines = difflib.unified_diff(old_lines, new_lines, fromfile="before", tofile="after", n=context)
    hunks, current = [], []
    for line in lines:
        if line.startswith(("--- ", "+++ ")) and not current and not hunks:
            continue
        if line.startswith("@@ ") and current:
            hunks.append({"diff": "".join(current)})
            current = []
        current.append(line if line.endswith(("\n", "\r")) else line + "\n\\ No newline at end of file\n")
    if current:
        hunks.append({"diff": "".join(current)})
    payload = {"format": "unified", "headers": ["--- before\n", "+++ after\n"] if hunks else [],
               "old_sha256": hashlib.sha256(old_content.encode()).hexdigest(),
               "new_sha256": hashlib.sha256(new_content.encode()).hexdigest(),
               "old_lines": len(old_lines), "new_lines": len(new_lines), "total_hunks": len(hunks)}
    return _page(payload, hunks, 0, max(1, len(hunks)), max_bytes, None)
