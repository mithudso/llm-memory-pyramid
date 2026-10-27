"""Pure, versioned assertion context and derived views for NapMem stores.

These functions never read files, contact a model, or manufacture source
evidence. Observation time and valid time have distinct meanings. Legacy
assertions retain unknown scope and unknown valid time after migration.
"""

from __future__ import annotations

from collections import defaultdict, deque
from copy import deepcopy
from datetime import UTC, datetime
import hashlib
import json
import re
from typing import Any
import unicodedata


STORE_VERSION = "2.0.0"
CONTEXT_FIELDS = (
    "scope", "memory_kind", "subject", "observed_at", "valid_from", "valid_to",
    "last_verified_at", "status", "supersedes", "review_status", "authority",
    "evidence", "pinned",
)
MEMORY_KINDS = ("preference", "constraint", "decision", "observation", "task",
                "idea", "lesson", "goal", "workflow")
PERSISTENT_KINDS = ("preference", "constraint", "workflow", "goal")
STATUSES = ("active", "superseded", "deleted", "expired", "quarantined")
REVIEW_STATUSES = ("unreviewed", "pending", "approved", "rejected")
MAX_SCOPE_LENGTH = 256
_TIME_FIELDS = ("observed_at", "valid_from", "valid_to", "last_verified_at")


def parse_time(value: str | datetime, field: str = "timestamp") -> datetime:
    """Parse an explicit timezone-aware instant without assigning a timezone."""
    if not isinstance(value, (str, datetime)):
        raise ValueError(f"{field} must be a timezone-aware ISO timestamp")
    try:
        result = datetime.fromisoformat(value.replace("Z", "+00:00")) if isinstance(value, str) else value
    except ValueError as exc:
        raise ValueError(f"{field} must be a timezone-aware ISO timestamp") from exc
    if result.tzinfo is None or result.utcoffset() is None:
        raise ValueError(f"{field} must include a timezone")
    return result.astimezone(UTC)


def _inferred_kind(record: dict[str, Any]) -> str:
    # Classification does not approve a profile or establish persistent truth.
    text = record.get("text", "").lower()
    kind = record.get("type", "statement")
    if kind == "quote" or kind == "question":
        return "observation"
    if kind == "idea" or re.search(r"\b(proposal|propose|maybe|could|hypothesis)\b", text):
        return "idea"
    if kind == "actionable":
        return "task"
    if re.search(r"\b(prefer|prefers|preference)\b", text):
        return "preference"
    if re.search(r"\b(must|never|prohibited|required)\b", text):
        return "constraint"
    if re.search(r"\b(decided|decision|approved)\b", text):
        return "decision"
    if re.search(r"\b(lesson|root cause)\b", text):
        return "lesson"
    return "observation"


def _id_list(value: Any, field: str) -> list[str]:
    if (not isinstance(value, list) or any(not isinstance(item, str) or not item.strip() for item in value)
            or len(value) != len(set(value))):
        raise ValueError(f"{field} must be a list of unique nonempty record IDs")
    return value


def _validate_scope(scope: Any, *, query: bool = False) -> None:
    if (not isinstance(scope, str) or not scope.strip() or len(scope) > MAX_SCOPE_LENGTH
            or any(unicodedata.category(char) == "Cc" for char in scope)
            or (scope == "*" and not query)):
        raise ValueError("scope must be a bounded nonempty string without control characters; '*' is query-only")


def normalize_record(record: dict[str, Any], *, scope: str | None = None,
                     metadata: dict[str, Any] | None = None) -> dict[str, Any]:
    """Return a validated deep copy; metadata overrides context and explicit scope wins.

    Legacy naive creation timestamps stay unchanged. They cannot establish an
    aware observed_at, so that default remains null. No validity is inferred
    from creation, observation, ingestion or verification timestamps.
    """
    if not isinstance(record, dict) or (metadata is not None and not isinstance(metadata, dict)):
        raise ValueError("record and metadata must be objects")
    result = deepcopy(record)
    if metadata:
        for field in CONTEXT_FIELDS:
            if field in metadata:
                result[field] = deepcopy(metadata[field])
    if scope is not None:
        result["scope"] = scope
    if not isinstance(result.get("id"), str) or not result["id"].strip():
        raise ValueError("record.id must be a nonempty string")
    if not isinstance(result.get("text"), str):
        raise ValueError("record.text must be a string")
    defaults = {"type": "statement", "salience": "medium", "canonical": result["id"],
                "topic_slug": "general", "source_anchor": {}, "duplicates": [], "duplicate_anchors": {},
                "created_at": None, "scope": "legacy", "subject": None, "valid_from": None,
                "valid_to": None, "last_verified_at": None, "status": "active", "supersedes": [],
                "review_status": "unreviewed", "authority": "unknown", "evidence": {}, "pinned": False}
    for field, default in defaults.items():
        result.setdefault(field, default)
    if result["created_at"] is not None and not isinstance(result["created_at"], str):
        raise ValueError("created_at must be a string or null")
    if "observed_at" not in result:
        try:
            parse_time(result["created_at"], "created_at")
        except ValueError:
            result["observed_at"] = None
        else:
            result["observed_at"] = result["created_at"]
    result.setdefault("memory_kind", _inferred_kind(result))
    if result["memory_kind"] == "project_decision":
        result["memory_kind"] = "decision"
    if result["memory_kind"] not in MEMORY_KINDS:
        raise ValueError("Unknown memory_kind")
    if result["status"] not in STATUSES:
        raise ValueError("Unknown record status")
    if result["review_status"] not in REVIEW_STATUSES:
        raise ValueError("Unknown review_status")
    for field in ("scope", "canonical", "type", "salience", "topic_slug", "authority"):
        if not isinstance(result[field], str) or not result[field].strip():
            raise ValueError(f"{field} must be a nonempty string")
    _validate_scope(result["scope"])
    if result["subject"] is not None and not isinstance(result["subject"], str):
        raise ValueError("subject must be a string or null")
    if not isinstance(result["pinned"], bool):
        raise ValueError("pinned must be a boolean")
    if not isinstance(result["evidence"], dict):
        raise ValueError("evidence must be an object")
    for field in _TIME_FIELDS:
        if result[field] is not None:
            if not isinstance(result[field], str):
                raise ValueError(f"{field} must be an ISO timestamp string or null")
            parse_time(result[field], field)
    if (result["valid_from"] and result["valid_to"]
            and parse_time(result["valid_from"]) >= parse_time(result["valid_to"])):
        raise ValueError("valid_from must precede valid_to")
    for field in ("duplicates", "supersedes"):
        _id_list(result[field], field)
        if result["id"] in result[field]:
            raise ValueError(f"record cannot include its own ID in {field}")
    if not isinstance(result["source_anchor"], dict) or not isinstance(result["duplicate_anchors"], dict):
        raise ValueError("source_anchor and duplicate_anchors must be objects")
    for anchor in [result["source_anchor"], *result["duplicate_anchors"].values()]:
        if not isinstance(anchor, dict):
            raise ValueError("source anchors must be objects")
        for field in ("session_id", "file_path", "heading", "line_range", "paraphrase_text"):
            if field in anchor and not isinstance(anchor[field], str):
                raise ValueError(f"source anchor {field} must be a string")
        if "assertion" in anchor and not isinstance(anchor["assertion"], dict):
            raise ValueError("source anchor assertion must be an object")
    return result


def _occurrences(record: dict[str, Any]) -> list[dict[str, Any]]:
    canonical = normalize_record(record)
    occurrences = [canonical]
    for rid in canonical["duplicates"]:
        anchor = canonical["duplicate_anchors"].get(rid)
        if anchor is None:
            # Old dangling aliases do not establish an occurrence or scope.
            continue
        assertion = deepcopy(anchor.get("assertion", {}))
        own = {field: deepcopy(canonical[field]) for field in ("type", "salience", "topic_slug")}
        own.update(assertion)
        own.update(id=rid, canonical=canonical["id"],
                   text=anchor.get("paraphrase_text", canonical["text"]), source_anchor=deepcopy(anchor))
        own = normalize_record(own)
        occurrences.append(own)
    return occurrences


def visible(record: dict[str, Any], scope: str | None = None,
            as_of: str | datetime | None = None) -> bool:
    """Check scope then half-open valid time; deleted assertions never appear."""
    if scope is not None:
        _validate_scope(scope, query=True)
    at = parse_time(as_of, "as_of") if as_of is not None else datetime.now(UTC)
    item = normalize_record(record)
    if scope is None:
        allowed = item["scope"] in ("global", "legacy")
    else:
        allowed = scope == "*" or item["scope"] in (scope, "global")
    if (not allowed or item["status"] in ("deleted", "expired", "quarantined")
            or item["review_status"] == "rejected"):
        return False
    if item["status"] == "superseded" and not (item["valid_from"] and item["valid_to"]):
        return False
    return ((item["valid_from"] is None or parse_time(item["valid_from"]) <= at)
            and (item["valid_to"] is None or at < parse_time(item["valid_to"])))


def effective_records(data: dict[str, Any], scope: str | None = None,
                      as_of: str | datetime | None = None) -> list[dict[str, Any]]:
    """Select one eligible occurrence per canonical and remove hidden alias metadata."""
    at = parse_time(as_of, "as_of") if as_of is not None else datetime.now(UTC)
    result = []
    for record in data.get("memory_records", []):
        eligible = [item for item in _occurrences(record) if visible(item, scope, at)]
        if not eligible:
            continue
        chosen = deepcopy(eligible[0])
        chosen["duplicates"] = [item["id"] for item in eligible[1:]]
        chosen["duplicate_anchors"] = {item["id"]: deepcopy(item["source_anchor"]) for item in eligible[1:]}
        result.append(chosen)
    return result


def _stable_id(prefix: str, *parts: Any) -> str:
    payload = json.dumps(parts, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return prefix + hashlib.sha256(payload.encode("utf-8")).hexdigest()[:20]


def _profile_evidence_supported(record: dict[str, Any]) -> bool:
    evidence = record["evidence"]
    if evidence.get("status") != "verified":
        return False
    if evidence.get("source_kind") == "operator":
        from napmem_evidence import verify_evidence
        return verify_evidence(record).get("status") == "verified"
    quote = evidence.get("quote")
    return (evidence.get("assertion_support") == "verbatim" and isinstance(quote, str)
            and bool(quote) and evidence.get("quote_sha256") == hashlib.sha256(quote.encode()).hexdigest()
            and isinstance(evidence.get("source_sha256"), str)
            and bool(re.fullmatch(r"[0-9a-f]{64}", evidence["source_sha256"])))


def build_derived(data: dict[str, Any]) -> None:
    """Rebuild scoped tracks, explicitly approved persistent profiles and conflict hints."""
    at = datetime.now(UTC)
    current = []
    for record in data.get("memory_records", []):
        current.extend(item for item in _occurrences(record) if visible(item, "*", at))
    current.sort(key=lambda item: item["id"])
    tracks: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
    profile_groups: dict[tuple[str, str, str], list[dict[str, Any]]] = defaultdict(list)
    subjects: dict[tuple[str, str, str], list[dict[str, Any]]] = defaultdict(list)
    for record in current:
        tracks[record["scope"], record["topic_slug"]].append(record)
        if record["subject"] and record["subject"].strip():
            subjects[record["scope"], record["subject"], record["memory_kind"]].append(record)
    conflict_groups = {key: members for key, members in subjects.items()
                       if len({r["text"].lower().strip() for r in members}) > 1}
    conflict_ids = {r["id"] for members in conflict_groups.values() for r in members}
    for record in current:
        if (record["memory_kind"] in PERSISTENT_KINDS and record["review_status"] == "approved"
                and record["id"] not in conflict_ids and _profile_evidence_supported(record)):
            profile_groups[record["scope"], record["memory_kind"], record["text"]].append(record)
    data["topic_tracks"] = []
    for (scope, slug), members in sorted(tracks.items()):
        texts = list(dict.fromkeys(r["text"] for r in members))
        observed = [r["observed_at"] for r in members if r["observed_at"]]
        data["topic_tracks"].append({
            "track_id": _stable_id("track_", scope, slug), "scope": scope, "topic_slug": slug,
            "title": slug.replace("-", " ").title(), "summary": "; ".join(texts[:3]),
            "record_ids": [r["id"] for r in members],
            "last_updated": max(observed, key=parse_time) if observed else None,
        })
    data["user_profiles"] = [
        {"id": _stable_id("prof_", scope, kind, text), "scope": scope,
         "category": kind, "trait": text, "review_status": "approved",
         "evidence_status": "verified", "confidence_status": "not_calibrated",
         "provenance_records": [r["id"] for r in members]}
        for (scope, kind, text), members in sorted(profile_groups.items())
    ]
    data["conflicts"] = [
        {"id": _stable_id("conflict_", scope, subject, kind, sorted(r["id"] for r in members)),
         "scope": scope, "subject": subject, "memory_kind": kind, "status": "unresolved",
         "reason": "Distinct current assertions share the same explicit subject, scope and memory kind. Review their compatibility.",
         "record_ids": [r["id"] for r in members]}
        for (scope, subject, kind), members in sorted(conflict_groups.items())
    ]


def apply_supersession(data: dict[str, Any]) -> None:
    """Validate explicit supersession edges, then close known old validity intervals.

    All validation precedes mutation. Unknown event time stays unknown; an
    ingestion or creation timestamp never closes an old validity interval.
    Alias targets update their own assertion metadata, not the canonical's.
    """
    occurrences: dict[str, dict[str, Any]] = {}
    targets: dict[str, tuple[dict[str, Any], str | None]] = {}
    for record in data.get("memory_records", []):
        for item in _occurrences(record):
            rid = item["id"]
            if rid in occurrences:
                raise ValueError(f"Duplicate record ID {rid}")
            occurrences[rid] = item
            targets[rid] = (record, None if rid == record["id"] else rid)
    incoming = {rid: 0 for rid in occurrences}
    successors: dict[str, list[str]] = defaultdict(list)
    changes: dict[str, dict[str, Any]] = {}
    for rid, new in occurrences.items():
        for old_id in new["supersedes"]:
            if old_id not in occurrences:
                raise ValueError(f"Superseded record does not exist: {old_id}")
            old = occurrences[old_id]
            if old["scope"] != new["scope"]:
                raise ValueError("Supersession cannot cross scopes")
            if old["subject"] and new["subject"] and old["subject"] != new["subject"]:
                raise ValueError("Supersession cannot cross explicit subjects")
            incoming[old_id] += 1
            successors[rid].append(old_id)
            change = changes.setdefault(old_id, {"status": old["status"]
                                       if old["status"] in ("deleted", "expired", "quarantined") else "superseded"})
            if new["valid_from"]:
                end = new["valid_from"]
                existing_end = change.get("valid_to") or old["valid_to"]
                if existing_end and parse_time(existing_end) < parse_time(end):
                    end = existing_end
                if old["valid_from"] and parse_time(end) <= parse_time(old["valid_from"]):
                    raise ValueError("Supersession would create an empty or reversed validity interval")
                change["valid_to"] = end
    ready = deque(rid for rid, count in incoming.items() if count == 0)
    visited = 0
    while ready:
        rid = ready.popleft()
        visited += 1
        for old_id in successors[rid]:
            incoming[old_id] -= 1
            if incoming[old_id] == 0:
                ready.append(old_id)
    if visited != len(occurrences):
        raise ValueError("Supersession cycle detected")
    for rid, change in changes.items():
        owner, alias = targets[rid]
        target = owner if alias is None else owner["duplicate_anchors"][alias].setdefault("assertion", {})
        target.update(change)


def migrate_store(data: dict[str, Any]) -> dict[str, Any]:
    """Copy a supported legacy/current store, normalize assertions and rebuild views."""
    if not isinstance(data, dict):
        raise ValueError("Store must be an object")
    version = data.get("version", "1.0.0")
    match = re.fullmatch(r"(\d+)\.(\d+)\.(\d+)", version) if isinstance(version, str) else None
    if not match or int(match.group(1)) not in (1, 2):
        raise ValueError(f"Unsupported store version: {version}")
    if tuple(map(int, match.groups())) > (2, 0, 0):
        raise ValueError(f"Unsupported future store version: {version}")
    result = deepcopy(data)
    for field in ("raw_conversations", "memory_records", "topic_tracks", "user_profiles", "conflicts"):
        result.setdefault(field, [])
        if not isinstance(result[field], list) or any(not isinstance(item, dict) for item in result[field]):
            raise ValueError(f"{field} must be a list of objects")
    result.setdefault("generation", 0)
    if isinstance(result["generation"], bool) or not isinstance(result["generation"], int) or result["generation"] < 0:
        raise ValueError("generation must be a nonnegative integer")
    result.setdefault("controls", {})
    if not isinstance(result["controls"], dict):
        raise ValueError("controls must be an object")
    result["memory_records"] = [normalize_record(r) for r in result["memory_records"]]
    ids = [rid for r in result["memory_records"] for rid in [r["id"], *r["duplicates"]]]
    if len(ids) != len(set(ids)):
        raise ValueError("Duplicate record IDs in store")
    # Normalize stored occurrence metadata without inheriting canonical scope.
    for record in result["memory_records"]:
        for occurrence in _occurrences(record)[1:]:
            anchor = record["duplicate_anchors"][occurrence["id"]]
            anchor["assertion"] = {field: deepcopy(occurrence[field]) for field in (*CONTEXT_FIELDS, "created_at")}
    result["version"] = STORE_VERSION
    apply_supersession(result)
    build_derived(result)
    return result
