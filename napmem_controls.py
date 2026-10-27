"""Pure operator controls that persist across extraction replay and alias promotion.

The caller owns file transactions, generation increments, cache purges and
replica acknowledgments. This module mutates only an explicitly passed store.
"""

from __future__ import annotations

import base64
from collections import defaultdict, deque
from copy import deepcopy
from datetime import UTC, datetime
import hashlib
import json
import os
import re
from typing import Any
import unicodedata

from napmem_model import CONTEXT_FIELDS, migrate_store, normalize_record, parse_time


ACTIONS = ("correct", "pin", "unpin", "expire", "approve", "reject",
           "exclude", "include", "forget", "forget_session")
JOURNAL_LIMIT = 1000
_CONTROL_KEYS = {"overrides", "corrections", "assertions", "tombstones", "excluded_sources", "journal"}
_OVERRIDE_FIELDS = {"pinned", "review_status", "valid_to"}
_IDENTITY_FIELDS = {"record_ids", "scope", "text_sha256"}
_CORRECTION_FIELDS = {"original_ids", "assertion_id", "scope", "text_sha256"}
_REDACTION_FIELDS = {"scope", "source_sha256", "quote_sha256", "line_range"}
_LINE_RANGE = re.compile(r"L?([0-9]+)(?:-L?([0-9]+))?", re.IGNORECASE)
_MARKDOWN_PREFIX = re.compile(r"^(?:>\s*|(?:[-*+]|[0-9]+[.)])\s+|\[[ xX]\]\s+)")


def _json(value: Any) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"),
                      allow_nan=False).encode("utf-8")


def _sha(value: str | bytes) -> str:
    return hashlib.sha256(value.encode("utf-8") if isinstance(value, str) else value).hexdigest()


def _text_hash(record: dict[str, Any]) -> str:
    return _sha(record["text"].lower().strip())


def fingerprint(record: dict[str, Any]) -> str:
    """Bind replay controls to exact-dedup text and its scope, never an ID alone."""
    normalized = normalize_record(record)
    return _sha(_json([normalized["scope"], normalized["text"].lower().strip()]))


def _ids(value: Any, field: str, *, nonempty: bool = False) -> None:
    if (not isinstance(value, list) or (nonempty and not value)
            or any(not isinstance(item, str) or not item.strip() for item in value)
            or len(value) != len(set(value))):
        raise ValueError(f"{field} must contain unique nonempty IDs")


def _digest(value: Any) -> bool:
    return isinstance(value, str) and len(value) == 64 and all(char in "0123456789abcdef" for char in value)


def _source(source: Any) -> str:
    if (not isinstance(source, str) or not source.strip() or len(source) > 4096
            or any(unicodedata.category(char) == "Cc" for char in source)):
        raise ValueError("source must be a nonempty path or session:<id>")
    if source.startswith("session:"):
        if not source[len("session:"):]:
            raise ValueError("source session ID cannot be empty")
        return source
    return os.path.normpath(source)


def _identity(scope: Any, text_hash: Any) -> None:
    # Reuse the model's scope validation without manufacturing a fact.
    normalize_record({"id": "control_validation", "text": "", "scope": scope})
    if not _digest(text_hash):
        raise ValueError("text_sha256 must be a SHA-256 digest")


def _line_bounds(value: Any) -> tuple[int, int] | None:
    if not isinstance(value, str) or len(value) > 64:
        return None
    match = _LINE_RANGE.fullmatch(value.strip())
    if match is None:
        return None
    start, end = int(match[1]), int(match[2] or match[1])
    return (start, end) if 0 < start <= end else None


def _range_label(bounds: tuple[int, int]) -> str:
    start, end = bounds
    return f"L{start}" if start == end else f"L{start}-L{end}"


def _redactions(data: dict[str, Any]) -> list[dict[str, Any]]:
    raw = data.get("evidence_redactions", [])
    if not isinstance(raw, list):
        raise ValueError("evidence_redactions must be a list")
    seen = set()
    for policy in raw:
        if not isinstance(policy, dict) or set(policy) != _REDACTION_FIELDS:
            raise ValueError("Malformed content-free evidence redaction")
        normalize_record({"id": "redaction_validation", "text": "", "scope": policy["scope"]})
        for field in ("source_sha256", "quote_sha256"):
            if policy[field] is not None and not _digest(policy[field]):
                raise ValueError(f"evidence redaction {field} must be a SHA-256 digest or null")
        bounds = _line_bounds(policy["line_range"])
        if policy["line_range"] is not None and (bounds is None or policy["line_range"] != _range_label(bounds)):
            raise ValueError("evidence redaction line_range must be normalized or null")
        if policy["quote_sha256"] is None and (policy["source_sha256"] is None or bounds is None):
            raise ValueError("evidence redaction must bind a quote or a source range")
        identity = _json(policy)
        if identity in seen:
            raise ValueError("Duplicate evidence redaction")
        seen.add(identity)
    return deepcopy(raw)


def _capture_redactions(data: dict[str, Any], records: list[dict[str, Any]]) -> None:
    policies = {_json(policy): policy for policy in _redactions(data)}
    for record in records:
        evidence = record["evidence"]
        quotes = [evidence.get("quote"), record.get("source_quote"), record["source_anchor"].get("source_quote")]
        quote_hashes = {_sha(quote) for quote in quotes if isinstance(quote, str) and quote}
        source_hash = evidence.get("source_sha256")
        source_hash = source_hash if _digest(source_hash) else None
        bounds = _line_bounds(evidence.get("line_range", record["source_anchor"].get("line_range")))
        if not quote_hashes and (source_hash is None or bounds is None):
            continue
        for quote_hash in quote_hashes or {None}:
            policy = {"scope": record["scope"], "source_sha256": source_hash,
                      "quote_sha256": quote_hash, "line_range": _range_label(bounds) if bounds else None}
            policies[_json(policy)] = policy
    if policies or "evidence_redactions" in data:
        data["evidence_redactions"] = [policies[key] for key in sorted(policies)]


def _quote_line_hashes(quote: str) -> set[str]:
    hashes = set()
    for line in quote.splitlines():
        text = line.strip()
        while text:
            hashes.add(_sha(text.lower().strip()))
            stripped = _MARKDOWN_PREFIX.sub("", text, count=1).strip()
            if stripped == text:
                break
            text = stripped
    return hashes


def _redact_evidence(record: dict[str, Any], policies: list[dict[str, Any]],
                     controls: dict[str, Any]) -> bool:
    evidence = record["evidence"]
    quote = evidence.get("quote")
    quotes = [quote, record.get("source_quote"), record["source_anchor"].get("source_quote")]
    quote_hashes = {_sha(value) for value in quotes if isinstance(value, str) and value}
    if _digest(evidence.get("quote_sha256")) and not quote:
        quote_hashes.add(evidence["quote_sha256"])
    bounds = _line_bounds(evidence.get("line_range", record["source_anchor"].get("line_range")))
    matched = False
    for policy in policies:
        if policy["scope"] != record["scope"]:
            continue
        if policy["quote_sha256"] is not None and policy["quote_sha256"] in quote_hashes:
            matched = True
            break
        forbidden_bounds = _line_bounds(policy["line_range"])
        if (bounds and forbidden_bounds and policy["source_sha256"] is not None
                and policy["source_sha256"] == evidence.get("source_sha256")
                and bounds[0] <= forbidden_bounds[1] and forbidden_bounds[0] <= bounds[1]):
            matched = True
            break
    if not matched:
        forbidden = {item["text_sha256"] for item in controls["tombstones"] if item["scope"] == record["scope"]}
        matched = any(forbidden.intersection(_quote_line_hashes(value))
                      for value in quotes if isinstance(value, str) and value)
    if not matched:
        return False
    changed = bool(quote or evidence.get("quote_sha256") or "source_quote" in record
                   or "source_quote" in record["source_anchor"])
    evidence.update(quote="", quote_sha256=None, status="unverified",
                    assertion_support="unverified", reason="redacted_by_forget")
    record.pop("source_quote", None)
    record["source_anchor"].pop("source_quote", None)
    assertion = record["source_anchor"].get("assertion")
    if isinstance(assertion, dict):
        assertion.pop("source_quote", None)
    return changed


def _controls(data: dict[str, Any]) -> dict[str, Any]:
    _redactions(data)
    raw = data.get("controls", {})
    if not isinstance(raw, dict) or set(raw) - _CONTROL_KEYS:
        raise ValueError("Malformed persistent controls: unknown fields or non-object")
    result = deepcopy(raw)
    for field in ("overrides", "corrections", "excluded_sources"):
        result.setdefault(field, {})
        if not isinstance(result[field], dict):
            raise ValueError(f"controls.{field} must be an object")
    for field in ("assertions", "tombstones", "journal"):
        result.setdefault(field, [])
        if not isinstance(result[field], list):
            raise ValueError(f"controls.{field} must be a list")
    for fp, override in result["overrides"].items():
        if (not _digest(fp) or not isinstance(override, dict)
                or set(override) - (_OVERRIDE_FIELDS | _IDENTITY_FIELDS)
                or not _IDENTITY_FIELDS <= override.keys()):
            raise ValueError("Malformed persistent override")
        _identity(override["scope"], override["text_sha256"])
        _ids(override["record_ids"], "override.record_ids", nonempty=True)
        if "pinned" in override and not isinstance(override["pinned"], bool):
            raise ValueError("Override pinned must be a boolean")
        if "review_status" in override and override["review_status"] not in ("approved", "rejected"):
            raise ValueError("Override review_status must be approved or rejected")
        if "valid_to" in override:
            parse_time(override["valid_to"], "override.valid_to")
    assertion_ids = set()
    assertion_parents = {}
    for assertion in result["assertions"]:
        normalized = normalize_record(assertion)
        rid = normalized["id"]
        if (not re.fullmatch(r"rec_control_[0-9a-f]{24}", rid) or rid in assertion_ids
                or not isinstance(normalized.get("corrects"), str)
                or not normalized["corrects"].strip() or normalized["corrects"] == rid
                or normalized["supersedes"]):
            raise ValueError("Malformed operator assertion identity")
        change_id = rid[len("rec_control_"):]
        evidence = normalized["evidence"]
        redacted = (evidence.get("status") == "unverified" and evidence.get("reason") == "redacted_by_forget"
                    and evidence.get("quote") == "" and evidence.get("quote_sha256") is None
                    and evidence.get("assertion_support") == "unverified")
        if ((not redacted and (evidence.get("status") != "verified" or evidence.get("quote") != normalized["text"]))
                or evidence.get("source_kind") != "operator"
                or evidence.get("source_sha256") != _sha(normalized["text"])
                or evidence.get("revision") != change_id
                or normalized["source_anchor"].get("session_id") != "session_control_" + change_id
                or normalized["source_anchor"].get("file_path") != "napmem:control/" + change_id):
            raise ValueError("Malformed operator assertion evidence")
        assertion_ids.add(rid)
        assertion_parents[rid] = normalized["corrects"]
    for rid in assertion_parents:
        seen = set()
        while rid in assertion_parents:
            if rid in seen:
                raise ValueError("Correction cycle detected")
            seen.add(rid)
            rid = assertion_parents[rid]
    for fp, correction in result["corrections"].items():
        if (not _digest(fp) or not isinstance(correction, dict) or set(correction) != _CORRECTION_FIELDS
                or not isinstance(correction["assertion_id"], str)
                or correction["assertion_id"] not in assertion_ids):
            raise ValueError("Malformed persistent correction")
        _ids(correction["original_ids"], "correction.original_ids", nonempty=True)
        _identity(correction["scope"], correction["text_sha256"])
        if assertion_parents[correction["assertion_id"]] not in correction["original_ids"]:
            raise ValueError("Correction assertion must identify its original evidence")
    for tombstone in result["tombstones"]:
        if not isinstance(tombstone, dict) or set(tombstone) != {"scope", "text_sha256"}:
            raise ValueError("Malformed content-free tombstone")
        _identity(tombstone["scope"], tombstone["text_sha256"])
    for source, enabled in result["excluded_sources"].items():
        if _source(source) != source or not (enabled is True or enabled == "forgotten"):
            raise ValueError("Excluded source keys must be normalized and values must be true or 'forgotten'")
    journal_fields = {"action", "id", "at", "affected_ids", "hashes", "fields"}
    journal_changes = _OVERRIDE_FIELDS | {"excluded_sources", "tombstones", "assertions", "corrections", "overrides", "status", "evidence_redactions"}
    if len(result["journal"]) > JOURNAL_LIMIT:
        raise ValueError("Control journal exceeds bounded retention")
    for entry in result["journal"]:
        if (not isinstance(entry, dict) or set(entry) != journal_fields or entry["action"] not in ACTIONS
                or not isinstance(entry["id"], str) or not re.fullmatch(r"[0-9a-f]{24}", entry["id"])):
            raise ValueError("Malformed content-free control journal")
        parse_time(entry["at"], "journal.at")
        _ids(entry["affected_ids"], "journal.affected_ids")
        _ids(entry["fields"], "journal.fields")
        if not set(entry["fields"]) <= journal_changes:
            raise ValueError("Control journal fields must name known changed fields")
        if not isinstance(entry["hashes"], list) or not all(_digest(value) for value in entry["hashes"]):
            raise ValueError("Malformed journal hashes")
    return result


def source_is_excluded(data: dict[str, Any], source: str,
                       session_id: str | None = None) -> bool:
    """Check a normalized exact path and optional session before extraction."""
    excluded = _controls(data)["excluded_sources"]
    return _source(source) in excluded or bool(session_id and "session:" + session_id in excluded)


def _excluded(controls: dict[str, Any], record: dict[str, Any]) -> bool:
    anchor = record.get("source_anchor", {})
    excluded = controls["excluded_sources"]
    path = anchor.get("file_path")
    return bool((path and _source(path) in excluded)
                or (anchor.get("session_id") and "session:" + anchor["session_id"] in excluded))


def _tombstoned(controls: dict[str, Any], record: dict[str, Any]) -> bool:
    identity = {"scope": record["scope"], "text_sha256": _text_hash(record)}
    return identity in controls["tombstones"]


def filter_incoming(data: dict[str, Any], records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Return normalized copies after durable replay and source suppression."""
    controls = _controls(data)
    policies = _redactions(data)
    result = []
    for record in records:
        record = normalize_record(record)
        if (_tombstoned(controls, record) or fingerprint(record) in controls["corrections"]
                or _excluded(controls, record)):
            continue
        _redact_evidence(record, policies, controls)
        result.append(record)
    return result


def _occurrences(record: dict[str, Any]) -> list[dict[str, Any]]:
    canonical = normalize_record(record)
    result = [canonical]
    for rid in canonical["duplicates"]:
        anchor = canonical["duplicate_anchors"].get(rid)
        if anchor is None:
            continue
        own = {field: deepcopy(canonical[field]) for field in ("type", "salience", "topic_slug")}
        own.update(deepcopy(anchor.get("assertion", {})))
        own.update(id=rid, canonical=canonical["id"], source_anchor=deepcopy(anchor),
                   text=anchor.get("paraphrase_text", canonical["text"]))
        result.append(normalize_record(own))
    return result


def _all(data: dict[str, Any], controls: dict[str, Any]) -> dict[str, dict[str, Any]]:
    result = {item["id"]: item for record in data.get("memory_records", []) for item in _occurrences(record)}
    for assertion in controls["assertions"]:
        result.setdefault(assertion["id"], normalize_record(assertion))
    return result


def _family(data: dict[str, Any], controls: dict[str, Any], record_id: str) -> set[str]:
    graph: dict[str, set[str]] = defaultdict(set)

    def connect(ids):
        for rid in ids:
            graph[rid].update(ids)

    for record in data.get("memory_records", []):
        connect([record["id"], *record.get("duplicates", [])])
    for record in controls["assertions"]:
        connect([record["id"], record["corrects"]])
    for correction in controls["corrections"].values():
        connect([*correction["original_ids"], correction["assertion_id"]])
    for override in controls["overrides"].values():
        connect(override["record_ids"])
    if record_id not in graph:
        raise ValueError(f"Record ID does not exist: {record_id}")
    found, pending = set(), deque([record_id])
    while pending:
        rid = pending.popleft()
        if rid not in found:
            found.add(rid)
            pending.extend(graph[rid] - found)
    return found


def _repack(occurrences: list[dict[str, Any]]) -> dict[str, Any] | None:
    if not occurrences:
        return None
    canonical = deepcopy(occurrences[0])
    canonical["canonical"] = canonical["id"]
    canonical["duplicates"] = [item["id"] for item in occurrences[1:]]
    canonical["duplicate_anchors"] = {}
    for item in occurrences[1:]:
        anchor = deepcopy(item["source_anchor"])
        anchor["assertion"] = {field: deepcopy(item[field]) for field in (*CONTEXT_FIELDS, "created_at")}
        if item["text"] != canonical["text"]:
            anchor["paraphrase_text"] = item["text"]
        else:
            anchor.pop("paraphrase_text", None)
        canonical["duplicate_anchors"][item["id"]] = anchor
    # A promoted anchor must describe the promoted occurrence, not another
    # assertion that previously occupied the canonical slot.
    if "assertion" in canonical["source_anchor"]:
        canonical["source_anchor"]["assertion"] = {
            field: deepcopy(canonical[field]) for field in (*CONTEXT_FIELDS, "created_at")}
    return canonical


def _apply(data: dict[str, Any], controls: dict[str, Any]) -> set[str]:
    policies = _redactions(data)
    redacted = set()
    records = deepcopy(data.get("memory_records", []))
    present = {rid for record in records for rid in [record["id"], *record.get("duplicates", [])]}
    controls["assertions"] = [a for a in controls["assertions"] if not _tombstoned(controls, normalize_record(a))]
    records.extend(deepcopy(a) for a in controls["assertions"] if a["id"] not in present)
    result = []
    removed = set()
    for record in records:
        kept = []
        for item in _occurrences(record):
            if _tombstoned(controls, item) or _excluded(controls, item):
                removed.add(item["id"])
                continue
            fp = fingerprint(item)
            override = controls["overrides"].get(fp)
            if override:
                item.update({field: deepcopy(value) for field, value in override.items() if field in _OVERRIDE_FIELDS})
                override["record_ids"] = sorted(set(override["record_ids"]) | {item["id"]})
            if fp in controls["corrections"]:
                correction = controls["corrections"][fp]
                correction["original_ids"] = sorted(set(correction["original_ids"]) | {item["id"]})
                item.update(status="superseded", review_status="rejected")
            if _redact_evidence(item, policies, controls):
                redacted.add(item["id"])
            kept.append(item)
        rebuilt = _repack(kept)
        if rebuilt:
            result.append(rebuilt)
    # A removal must not leave an invalid supersession edge on a survivor.
    present = {rid for record in result for rid in [record["id"], *record.get("duplicates", [])]}
    for record in result:
        record["supersedes"] = [rid for rid in record["supersedes"] if rid not in removed or rid in present]
        for anchor in record.get("duplicate_anchors", {}).values():
            assertion = anchor.get("assertion", {})
            assertion["supersedes"] = [rid for rid in assertion.get("supersedes", []) if rid not in removed or rid in present]
    data["memory_records"] = result
    retained = {item["id"]: item for record in result for item in _occurrences(record)}
    controls["assertions"] = [deepcopy(retained.get(item["id"], item)) for item in controls["assertions"]]
    data["controls"] = controls
    return redacted


def apply_controls(data: dict[str, Any]) -> None:
    """Atomically reapply replay controls and restore retained operator assertions."""
    working = deepcopy(data)
    _apply(working, _controls(working))
    working["controls"] = _controls(working)
    working = migrate_store(working)
    data.clear()
    data.update(working)


def _generation(data: dict[str, Any]) -> int:
    value = data.get("generation", 0)
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise ValueError("generation must be a nonnegative integer")
    return value


def _request(action, record_id, value, source, at) -> str:
    return _sha(_json({"action": action, "record_id": record_id, "value": value, "source": source, "at": at}))


def _token(data, request_hash, at) -> str:
    body = _json({"generation": _generation(data), "snapshot_sha256": _sha(_json(data)),
                  "request_sha256": request_hash, "at": at})
    return base64.urlsafe_b64encode(body).decode("ascii").rstrip("=") + "." + _sha(body)


def _read_token(token, data, request_hash) -> str:
    try:
        if not isinstance(token, str) or len(token) > 4096:
            raise ValueError("invalid token")
        encoded, digest = token.split(".")
        body = base64.urlsafe_b64decode(encoded + "=" * (-len(encoded) % 4))
        payload = json.loads(body)
        if (_sha(body) != digest or payload["generation"] != _generation(data)
                or payload["snapshot_sha256"] != _sha(_json(data)) or payload["request_sha256"] != request_hash):
            raise ValueError("stale")
        return parse_time(payload["at"]).isoformat()
    except (AttributeError, KeyError, TypeError, ValueError, json.JSONDecodeError) as exc:
        raise ValueError("Preview token is invalid or the store/request changed") from exc


def _context(data, action, record_id, value, source, at):
    if action not in ACTIONS:
        raise ValueError("Unknown control action")
    controls = _controls(data)
    moment = parse_time(at).isoformat() if at is not None else datetime.now(UTC).isoformat()
    records = _all(data, controls)
    if action in ("exclude", "include", "forget_session"):
        if action == "forget_session":
            source = source or ("session:" + value if isinstance(value, str) else None)
            if source and not source.startswith("session:"):
                source = "session:" + source
        source = _source(source)
        if action == "include" and controls["excluded_sources"].get(source) == "forgotten":
            raise ValueError("A forgotten session cannot be included; source exclusion and session forgetting are distinct")
        affected = [rid for rid, item in records.items() if _excluded({"excluded_sources": {source: True}}, item)]
        return controls, records, moment, source, sorted(affected)
    if not isinstance(record_id, str):
        raise ValueError("record_id is required")
    family = _family(data, controls, record_id)
    if action == "forget":
        return controls, records, moment, source, sorted(family)
    if record_id not in records:
        raise ValueError("Record is retained only as control history; use forget to erase that history")
    if action == "correct":
        if not isinstance(value, str) or not value.strip() or len(value) > 1024 * 1024:
            raise ValueError("Correction must be nonempty text of at most 1 MiB")
        visited = set()
        while fingerprint(records[record_id]) in controls["corrections"]:
            if record_id in visited:
                raise ValueError("Correction cycle detected")
            visited.add(record_id)
            record_id = controls["corrections"][fingerprint(records[record_id])]["assertion_id"]
        target = records[record_id]
        if target["text"].lower().strip() == value.lower().strip():
            raise ValueError("Correction must change the normalized assertion text")
        affected = sorted(family | {record_id})
    else:
        affected = [record_id]
    if action == "expire":
        expiry = parse_time(value if value is not None else moment, "expiry").isoformat()
        normalize_record({**records[record_id], "valid_to": expiry})
    return controls, records, moment, source, affected


def preview_action(data: dict[str, Any], action: str, *, record_id: str | None = None,
                   value: Any = None, source: str | None = None, at: str | None = None) -> dict[str, Any]:
    """Describe concrete effects without writing; bind the preview to this snapshot."""
    _, records, moment, normalized_source, affected = _context(data, action, record_id, value, source, at)
    new_value = value
    if action in ("pin", "unpin"):
        new_value = action == "pin"
    elif action in ("approve", "reject"):
        new_value = "approved" if action == "approve" else "rejected"
    elif action == "expire":
        new_value = parse_time(value if value is not None else moment).isoformat()
    preview = {"action": action, "record_id": record_id, "source": normalized_source,
               "generation": _generation(data), "at": moment, "affected_ids": affected,
               "new_value": new_value, "canonical_scope": records.get(record_id, {}).get("scope")}
    request_hash = _request(action, record_id, value, source, at)
    if action == "correct":
        change_id = _sha(_json([request_hash, _generation(data), moment]))[:24]
        preview["affected_ids"] = sorted(set(affected) | {"rec_control_" + change_id})
    if action == "forget":
        simulated = deepcopy(data)
        preview["redacted_evidence_ids"] = apply_action(
            simulated, action, record_id=record_id, value=value, source=source, at=moment)["redacted_evidence_ids"]
    preview["preview_token"] = _token(data, request_hash, moment)
    return preview


def _prune_raw(data):
    sessions = {item["source_anchor"].get("session_id")
                for record in data.get("memory_records", []) for item in _occurrences(record)}
    data["raw_conversations"] = [raw for raw in data.get("raw_conversations", []) if raw.get("session_id") in sessions]


def apply_action(data: dict[str, Any], action: str, *, record_id: str | None = None,
                 value: Any = None, source: str | None = None, at: str | None = None,
                 expected_generation: int | None = None, preview_token: str | None = None) -> dict[str, Any]:
    """Validate a copy, apply an operator action, then atomically replace input state.

    Persistence owns generation increments. This function leaves generation
    unchanged and returns the proposed next generation for the caller's commit.
    """
    generation = _generation(data)
    if expected_generation is not None and (isinstance(expected_generation, bool)
                                             or not isinstance(expected_generation, int)
                                             or expected_generation != generation):
        raise ValueError("Generation conflict")
    request_hash = _request(action, record_id, value, source, at)
    resolved_at = _read_token(preview_token, data, request_hash) if preview_token is not None else at
    working = deepcopy(data)
    controls, records, moment, normalized_source, affected = _context(working, action, record_id, value, source, resolved_at)
    change_id = _sha(_json([request_hash, generation, moment]))[:24]
    changed_fields, hashes = [], set()
    if action in ("exclude", "forget_session"):
        if action == "forget_session":
            controls["excluded_sources"][normalized_source] = "forgotten"
        else:
            controls["excluded_sources"].setdefault(normalized_source, True)
        hashes.add(_sha(normalized_source))
        changed_fields = ["excluded_sources"]
    elif action == "include":
        controls["excluded_sources"].pop(normalized_source, None)
        hashes.add(_sha(normalized_source))
        changed_fields = ["excluded_sources"]
    elif action == "forget":
        family = set(affected)
        identities = {(item["scope"], _text_hash(item)) for rid, item in records.items() if rid in family}
        for fp, entry in [*controls["corrections"].items(), *controls["overrides"].items()]:
            ids = entry.get("original_ids", entry.get("record_ids", []))
            if family.intersection(ids) or entry.get("assertion_id") in family:
                identities.add((entry["scope"], entry["text_sha256"]))
                hashes.add(fp)
        for item in records.values():
            if (item["scope"], _text_hash(item)) in identities:
                hashes.add(fingerprint(item))
        _capture_redactions(working, [item for rid, item in records.items()
                                     if rid in family or (item["scope"], _text_hash(item)) in identities])
        controls["tombstones"] = [{"scope": scope, "text_sha256": text_hash}
                                  for scope, text_hash in sorted(identities | {
                                      (item["scope"], item["text_sha256"]) for item in controls["tombstones"]})]
        controls["assertions"] = [item for item in controls["assertions"]
                                  if item["id"] not in family and not _tombstoned(controls, normalize_record(item))]
        controls["corrections"] = {fp: item for fp, item in controls["corrections"].items()
                                   if fp not in hashes and not family.intersection(item["original_ids"])
                                   and item["assertion_id"] not in family}
        controls["overrides"] = {fp: item for fp, item in controls["overrides"].items()
                                 if fp not in hashes and not family.intersection(item["record_ids"])}
        changed_fields = ["tombstones", "assertions", "corrections", "overrides", "evidence_redactions"]
    elif action == "correct":
        target_id = record_id
        while fingerprint(records[target_id]) in controls["corrections"]:
            target_id = controls["corrections"][fingerprint(records[target_id])]["assertion_id"]
        target = records[target_id]
        fp = fingerprint(target)
        rid = "rec_control_" + change_id
        assertion = normalize_record({
            "id": rid, "canonical": rid, "text": value, "type": target["type"],
            "salience": target["salience"], "topic_slug": target["topic_slug"], "created_at": moment,
            "scope": target["scope"], "memory_kind": target["memory_kind"], "subject": target["subject"],
            "review_status": "approved", "authority": "operator", "corrects": target_id,
            "evidence": {"status": "verified", "source_kind": "operator", "quote": value,
                         "source_sha256": _sha(value), "revision": change_id},
            "source_anchor": {"session_id": "session_control_" + change_id,
                              "file_path": "napmem:control/" + change_id},
        })
        controls["assertions"].append(assertion)
        # A semantic/case-variant alias still substantiates the corrected claim.
        # Retire each related wording in this scope so promotion cannot revive
        # the claim through a different source. Other scopes remain independent.
        for original_id in affected:
            original = records.get(original_id)
            if original is None or original["scope"] != target["scope"]:
                continue
            original_fp = fingerprint(original)
            if original_fp in controls["corrections"]:
                continue
            controls["corrections"][original_fp] = {
                "original_ids": sorted({original_id, target_id}), "assertion_id": rid,
                "scope": original["scope"], "text_sha256": _text_hash(original)}
            hashes.add(original_fp)
        affected = sorted(set(affected) | {rid})
        changed_fields = ["corrections", "assertions", "review_status", "status"]
    else:
        target = records[record_id]
        fp = fingerprint(target)
        override = controls["overrides"].setdefault(fp, {"record_ids": [], "scope": target["scope"], "text_sha256": _text_hash(target)})
        override["record_ids"] = sorted(set(override["record_ids"]) | {record_id})
        if action in ("pin", "unpin"):
            override["pinned"] = action == "pin"
            changed_fields = ["pinned"]
        elif action in ("approve", "reject"):
            override["review_status"] = "approved" if action == "approve" else "rejected"
            changed_fields = ["review_status"]
        elif action == "expire":
            override["valid_to"] = parse_time(value if value is not None else moment).isoformat()
            changed_fields = ["valid_to"]
        hashes.add(fp)
    redacted = _apply(working, controls)
    if action in ("forget", "forget_session", "exclude"):
        _prune_raw(working)
    controls["journal"].append({"action": action, "id": change_id, "at": moment,
                                "affected_ids": sorted(set(affected)), "hashes": sorted(hashes),
                                "fields": sorted(changed_fields)})
    controls["journal"] = controls["journal"][-JOURNAL_LIMIT:]
    # Persistent controls are authoritative: validate every field and reference,
    # rather than treating malformed state like a disposable cache.
    working["controls"] = _controls(working)
    working = migrate_store(working)
    data.clear()
    data.update(working)
    return {"action": action, "change_id": change_id, "affected_ids": sorted(set(affected)),
            "redacted_evidence_ids": sorted(redacted),
            "generation": generation, "proposed_generation": generation + 1,
            "canonical": "complete", "persistence": "pending_caller_commit",
            "cache": "pending_parent_purge", "mirrors": "pending_acknowledgment",
            "originals": "operator_managed", "exports": "operator_managed", "backups": "operator_managed",
            "completion_scope": "whole_claim_and_correction_family" if action == "forget" else
                "selected_session_occurrences" if action == "forget_session" else
                "selected_source_occurrences" if action in ("exclude", "include") else "selected_scoped_assertion",
            "independent_sources": "retained" if action == "forget_session" else "action_dependent",
            "operator_assertions": "separately_owned_unless_selected" if action == "forget_session" else "action_dependent"}
