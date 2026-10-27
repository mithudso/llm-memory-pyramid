"""Bind literal source passages to the exact text supplied to extraction.

Verified evidence establishes a quotation's provenance, not the truth of an
assertion. This module does not open source paths during binding. Rechecking a
stored path requires an explicit allowlist and never returns newly read text.
"""

from __future__ import annotations

from copy import deepcopy
from datetime import datetime
import errno
import hashlib
import os
import re
import stat
from typing import Any


MAX_QUOTE_BYTES = 4096
MAX_METADATA_CHARS = 256
DEFAULT_MAX_SOURCE_BYTES = 2 * 1024 * 1024
QUOTE_TRUNCATION_MARKER = "\n[napmem quotation truncated]"
_LINE_RANGE = re.compile(r"L?([0-9]+)(?:-L?([0-9]+))?", re.IGNORECASE)
_DIGEST = re.compile(r"[0-9a-f]{64}")
_BULLET = re.compile(r"^\s*(?:(?:[-*+]|\d+[.)])\s+)?(?:\[[ xX]\]\s+)?")


def _sha(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _line_range(value: Any) -> tuple[int, int] | None:
    if not isinstance(value, str) or len(value) > 64:
        return None
    match = _LINE_RANGE.fullmatch(value.strip())
    if match is None:
        return None
    start = int(match[1])
    end = int(match[2] or match[1])
    return (start, end) if 0 < start <= end else None


def _range_label(bounds: tuple[int, int]) -> str:
    start, end = bounds
    return f"L{start}" if start == end else f"L{start}-L{end}"


def _passage(content: str, bounds: tuple[int, int]) -> str | None:
    # Keep line endings: a quotation must remain an exact source substring.
    lines = content.splitlines(keepends=True)
    start, end = bounds
    if end > len(lines):
        return None
    return "".join(lines[start - 1:end])


def _bounded_quote(quote: str) -> tuple[str, bool]:
    encoded = quote.encode("utf-8")
    if len(encoded) <= MAX_QUOTE_BYTES:
        return quote, False
    room = MAX_QUOTE_BYTES - len(QUOTE_TRUNCATION_MARKER.encode("utf-8"))
    return encoded[:room].decode("utf-8", errors="ignore") + QUOTE_TRUNCATION_MARKER, True


def _literal_quote(evidence: dict[str, Any]) -> str | None:
    quote = evidence.get("quote")
    if not isinstance(quote, str) or not quote or len(quote.encode("utf-8")) > MAX_QUOTE_BYTES:
        return None
    if evidence.get("quote_sha256") != _sha(quote):
        return None
    if evidence.get("quote_truncated") is True:
        if not quote.endswith(QUOTE_TRUNCATION_MARKER):
            return None
        quote = quote[:-len(QUOTE_TRUNCATION_MARKER)]
    elif evidence.get("quote_truncated") not in (False, None):
        return None
    return quote or None


def _support(record: dict[str, Any], quote: str) -> str:
    assertion = record.get("text")
    if isinstance(assertion, str):
        assertion = _BULLET.sub("", assertion, count=1).strip()
        if assertion and assertion in quote:
            return "verbatim"
    return "unverified"


def _metadata(value: Any, name: str, *, optional: bool = True) -> str | None:
    if value is None and optional:
        return None
    if not isinstance(value, str) or not value.strip() or len(value) > MAX_METADATA_CHARS:
        raise ValueError(f"{name} must be a nonempty string of at most {MAX_METADATA_CHARS} characters")
    return value


def bind_evidence(record: dict[str, Any], content: str | None, *, method: str = "provided",
                  model: str | None = None, prompt_version: str | None = None,
                  source_revision: str | None = None) -> dict[str, Any]:
    """Return a copied record whose evidence binds to the extraction input.

    A supplied ``source_quote`` is used only if it literally occurs in the
    cited line range. A mismatching quote leaves the assertion unverified.
    If no quote is supplied, the range itself supplies the quotation.
    Missing content or invalid ranges cannot establish evidence. No file or
    network I/O occurs here, and repeated calls introduce no new timestamps.
    """
    if not isinstance(record, dict) or (content is not None and not isinstance(content, str)):
        raise ValueError("record must be an object and content must be a string or null")
    result = deepcopy(record)
    extraction = {"method": _metadata(method, "method", optional=False),
                  "model": _metadata(model, "model"),
                  "prompt_version": _metadata(prompt_version, "prompt_version")}
    revision = _metadata(source_revision, "source_revision")
    anchor = result.get("source_anchor", {})
    if not isinstance(anchor, dict):
        anchor = {}
    supplied_quote = result.pop("source_quote", anchor.get("source_quote"))
    anchor = {key: value for key, value in anchor.items() if key != "source_quote"}
    result["source_anchor"] = anchor
    bounds = _line_range(anchor.get("line_range"))
    digest = _sha(content) if content is not None else None
    revision = revision or digest
    evidence = {"status": "unverified", "reason": "source_content_unavailable",
                "source_kind": "document", "source_sha256": digest,
                "source_revision": revision, "revision": revision,
                "line_range": _range_label(bounds) if bounds else None,
                "quote": "", "quote_sha256": None, "quote_truncated": False,
                "extraction": extraction, "assertion_support": "unverified"}
    result["evidence"] = evidence
    if content is None:
        return result
    if bounds is None:
        evidence["reason"] = "invalid_line_range"
        return result
    passage = _passage(content, bounds)
    if passage is None:
        evidence["reason"] = "line_range_out_of_bounds"
        return result
    if not passage:
        evidence["reason"] = "empty_source_passage"
        return result
    supplied = supplied_quote
    supplied_matches = isinstance(supplied, str) and bool(supplied) and supplied in passage
    mismatch = supplied is not None and not supplied_matches
    if mismatch:
        # A broad source range can contain unrelated/private assertions. Never
        # retain that passage as a replacement for a nonliteral requested quote.
        evidence["reason"] = "source_quote_not_in_cited_range"
        return result
    quote = supplied if supplied_matches else passage
    quote, truncated = _bounded_quote(quote)
    evidence.update(status="unverified" if mismatch else "verified",
                    reason="source_quote_not_in_cited_range" if mismatch else "source_revision_and_quote_checked", quote=quote,
                    quote_sha256=_sha(quote), quote_truncated=truncated)
    if mismatch:
        return result
    literal = _literal_quote(evidence)
    evidence["assertion_support"] = _support(result, literal or "")
    # Creation time is stable across re-ingestion; the clock would break no-op replay.
    if not result.get("last_verified_at"):
        created = result.get("created_at")
        try:
            moment = datetime.fromisoformat(created.replace("Z", "+00:00"))
        except (AttributeError, TypeError, ValueError):
            pass
        else:
            if moment.tzinfo is not None and moment.utcoffset() is not None:
                result["last_verified_at"] = created
    return result


def _status(evidence: dict[str, Any], status: str, reason: str,
            **fields: Any) -> dict[str, Any]:
    # Return metadata only. In particular, do not expose text read from a mutable path.
    result: dict[str, Any] = {"status": status, "reason": reason}
    for key in ("source_kind", "source_sha256", "source_revision", "revision", "line_range",
                "assertion_support", "quote_truncated"):
        value = evidence.get(key)
        if value is None or isinstance(value, bool):
            result[key] = value
        elif isinstance(value, str):
            result[key] = value[:MAX_METADATA_CHARS]
    result.update(fields)
    return result


def _operator_evidence(record: dict[str, Any], evidence: dict[str, Any]) -> dict[str, Any]:
    revision = evidence.get("revision")
    anchor = record.get("source_anchor", {})
    valid = (isinstance(revision, str) and re.fullmatch(r"[0-9a-f]{24}", revision)
             and isinstance(anchor, dict) and evidence.get("status") == "verified"
             and evidence.get("quote") == record.get("text")
             and isinstance(record.get("text"), str)
             and evidence.get("source_sha256") == _sha(record["text"])
             and record.get("id") == "rec_control_" + revision
             and anchor.get("session_id") == "session_control_" + revision
             and anchor.get("file_path") == "napmem:control/" + revision)
    if (not valid or evidence.get("source_revision", revision) != revision
            or evidence.get("quote_sha256", evidence.get("source_sha256")) != evidence.get("source_sha256")):
        return _status(evidence, "unverified", "invalid_operator_evidence")
    return _status(evidence, "verified", "operator_revision_and_quote_checked",
                   assertion_support="verbatim")


def _proof(record: dict[str, Any], evidence: dict[str, Any]) -> tuple[str, tuple[int, int]] | None:
    digest = evidence.get("source_sha256")
    revision = evidence.get("source_revision", evidence.get("revision"))
    bounds = _line_range(evidence.get("line_range"))
    anchor = record.get("source_anchor", {})
    literal = _literal_quote(evidence)
    if (evidence.get("status") != "verified" or evidence.get("source_kind") != "document" or not isinstance(digest, str)
            or _DIGEST.fullmatch(digest) is None or not isinstance(revision, str)
            or not revision.strip() or len(revision) > MAX_METADATA_CHARS
            or evidence.get("revision", revision) != revision or bounds is None or literal is None
            or not isinstance(anchor, dict) or _line_range(anchor.get("line_range")) != bounds):
        return None
    return literal, bounds


def _check_content(record: dict[str, Any], evidence: dict[str, Any], content: str,
                   proof: tuple[str, tuple[int, int]]) -> dict[str, Any]:
    digest = _sha(content)
    if digest != evidence["source_sha256"]:
        return _status(evidence, "changed", "source_revision_changed", current_source_sha256=digest)
    literal, bounds = proof
    passage = _passage(content, bounds)
    if passage is None or literal not in passage:
        return _status(evidence, "unverified", "quote_not_in_cited_range")
    return _status(evidence, "verified", "source_revision_and_quote_checked",
                   assertion_support=_support(record, literal))


def _fd_true_path(fd: int) -> str | None:
    """Ask the kernel for the opened object's path; never fall back to realpath."""
    try:
        import fcntl
        if hasattr(fcntl, "F_GETPATH"):
            raw = fcntl.fcntl(fd, fcntl.F_GETPATH, bytes(1024))
            return raw.split(b"\x00", 1)[0].decode("utf-8")
    except (ImportError, OSError, ValueError, UnicodeDecodeError):
        pass
    try:
        return os.readlink(f"/proc/self/fd/{fd}")
    except OSError:
        return None


def _read_source(path: str, roots: list[str], limit: int) -> tuple[str | None, str | None]:
    if not hasattr(os, "O_NONBLOCK"):
        return None, "nonblocking_source_open_unavailable"
    flags = os.O_RDONLY | os.O_NONBLOCK | getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_NOFOLLOW", 0)
    try:
        fd = os.open(path, flags)
    except FileNotFoundError:
        return None, "source_missing"
    except OSError as exc:
        return None, "source_link_refused" if exc.errno == errno.ELOOP else "source_open_failed"
    try:
        details = os.fstat(fd)
        if not stat.S_ISREG(details.st_mode):
            return None, "source_not_regular"
        if details.st_nlink != 1:
            return None, "source_multi_linked"
        real = _fd_true_path(fd)
        if real is None or not os.path.isabs(real):
            return None, "source_path_unverifiable"
        if not any(os.path.commonpath((real, root)) == root for root in roots):
            return None, "source_outside_allowed_roots"
        if details.st_size > limit:
            return None, "source_too_large"
        chunks: list[bytes] = []
        remaining = limit + 1
        while remaining:
            chunk = os.read(fd, min(65536, remaining))
            if not chunk:
                break
            chunks.append(chunk)
            remaining -= len(chunk)
        raw = b"".join(chunks)
        if len(raw) > limit:
            return None, "source_too_large"
        try:
            return raw.decode("utf-8"), None
        except UnicodeDecodeError:
            return None, "source_not_utf8"
    except OSError:
        return None, "source_read_failed"
    finally:
        os.close(fd)


def verify_evidence(record: dict[str, Any], *, source_content: str | None = None,
                    allowed_roots: list[str] | None = None,
                    max_source_bytes: int = DEFAULT_MAX_SOURCE_BYTES) -> dict[str, Any]:
    """Recheck stored literal proof against supplied text or an allowed source.

    ``verified`` means the source revision and retained quotation match. It
    does not establish factual entailment. A path alone cannot upgrade an old
    record with no literal proof. Operator corrections use their journal
    identity and never open their ``napmem:control`` anchors.
    """
    if not isinstance(record, dict) or (source_content is not None and not isinstance(source_content, str)):
        raise ValueError("record must be an object and source_content must be a string or null")
    if not isinstance(max_source_bytes, int) or isinstance(max_source_bytes, bool) or max_source_bytes < 1:
        raise ValueError("max_source_bytes must be a positive integer")
    evidence = record.get("evidence", {})
    if not isinstance(evidence, dict):
        evidence = {}
    if evidence.get("source_kind") == "operator":
        return _operator_evidence(record, evidence)
    proof = _proof(record, evidence)
    if proof is None:
        return _status(evidence, "unverified", "literal_proof_unavailable")
    if source_content is not None:
        return _check_content(record, evidence, source_content, proof)
    if not allowed_roots:
        return _status(evidence, "unverified", "allowed_roots_required")
    if not isinstance(allowed_roots, (list, tuple)) or not all(
            isinstance(root, (str, os.PathLike)) and isinstance(os.fspath(root), str)
            and os.fspath(root) for root in allowed_roots):
        raise ValueError("allowed_roots must be a list of nonempty paths")
    roots = [os.path.realpath(root) for root in allowed_roots]
    anchor = record.get("source_anchor", {})
    path = anchor.get("file_path")
    if not isinstance(path, str) or not path or path.startswith("napmem:") or "\x00" in path:
        return _status(evidence, "unverified", "source_path_unavailable")
    content, reason = _read_source(path, roots, max_source_bytes)
    if reason is not None:
        return _status(evidence, "missing" if reason == "source_missing" else "unverified", reason)
    return _check_content(record, evidence, content, proof)
