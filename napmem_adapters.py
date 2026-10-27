"""Explicit offline source adapters and bounded, portable memory export.

Source documents remain data. Imported IDs, controls, authority, review state,
evidence, scope and supersession never become operator input. Only the caller
selects a source path and scope. Git reads committed blobs with bounded builtin
commands; it never checks out a tree or executes source content.
"""

from __future__ import annotations

from copy import deepcopy
from datetime import UTC, datetime
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import selectors
import subprocess
import time
import unicodedata
from urllib.parse import quote

from napmem_controls import source_is_excluded
from napmem_model import normalize_record
from napmem_search import TOKEN_ESTIMATOR, _account, bounded_response, eligible_records
from napmem_sources import MAX_SOURCE_BYTES, SourceRegistry, normalized_path, read_source


FORMATS = ("markdown", "conversation", "portable", "git")
FORMAT_VERSION = "1.0.0"
MAX_ITEMS = 2000
GIT_TIMEOUT_SECONDS = 15
_OID = re.compile(r"(?:[0-9a-f]{40}|[0-9a-f]{64})")
_TYPES = {"concept", "fact", "actionable", "question", "problem", "statement", "quote", "idea"}
_CONTEXT = ("memory_kind", "subject", "valid_from", "valid_to", "observed_at")


def _bounded_string(value, field, limit=256):
    if (not isinstance(value, str) or not value.strip() or len(value.encode("utf-8")) > limit
            or any(unicodedata.category(char) == "Cc" for char in value)):
        raise ValueError(f"{field} must be a bounded nonempty string without control characters")
    return value


def _session(value):
    _bounded_string(value, "session_id")
    if value == "control" or value.startswith(("control_", "session_control_", "napmem:")):
        raise ValueError("session_id uses a reserved operator identity")
    return value


def _strict_json(content):
    def object_pairs(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise ValueError("Source JSON contains a duplicate object key")
            result[key] = value
        return result

    def invalid_constant(value):
        raise ValueError("Source JSON cannot contain nonfinite numbers")

    try:
        return json.loads(content, object_pairs_hook=object_pairs, parse_constant=invalid_constant)
    except RecursionError as error:
        raise ValueError("Source JSON nesting exceeds the supported limit") from error


def _json_records(content, session, source, kind):
    data = _strict_json(content)
    if kind == "conversation":
        if isinstance(data, dict) and set(data) == {"messages"}:
            items = data["messages"]
        elif isinstance(data, list):
            items = data
        else:
            raise ValueError("Conversation JSON must be a messages array or an object containing only messages")
    else:
        if not isinstance(data, dict) or not isinstance(data.get("records"), list):
            raise ValueError("Portable JSON must contain a records array")
        if "format" in data and data["format"] != "napmem-portable":
            raise ValueError("Unknown portable memory format")
        if "format_version" in data and data["format_version"] != FORMAT_VERSION:
            raise ValueError("Unsupported portable memory format_version")
        items = data["records"]
    if not isinstance(items, list) or len(items) > MAX_ITEMS:
        raise ValueError(f"Source must contain an array of at most {MAX_ITEMS} entries")
    records = []
    last_line = max(1, len(content.splitlines()))
    bounds = "L1" if last_line == 1 else f"L1-L{last_line}"
    for index, item in enumerate(items, 1):
        if not isinstance(item, dict):
            raise ValueError("Each source entry must be an object")
        if kind == "conversation":
            if set(item) != {"role", "content"} or item["role"] not in ("user", "assistant"):
                raise ValueError("Conversation messages require only user/assistant role and string content")
            text, heading = item["content"], "Conversation " + item["role"]
        else:
            text, heading = item.get("text"), "Imported memory"
        if not isinstance(text, str) or not text.strip() or len(text.encode("utf-8")) > MAX_SOURCE_BYTES:
            raise ValueError("Source entry text must be a bounded nonempty string")
        identifier = f"rec_{session}_{index:03d}"
        record = {"id": identifier, "text": text, "type": "statement", "salience": "medium",
                  "topic_slug": "imported-memory", "created_at": datetime.now(UTC).isoformat(),
                  "authority": "source", "review_status": "unreviewed", "supersedes": [],
                  "source_anchor": {"session_id": session, "file_path": source,
                                    "heading": heading, "line_range": bounds},
                  # This is a requested literal quote, not a rendered source.
                  # bind_evidence checks it against the ORIGINAL JSON below.
                  "source_quote": text}
        if kind == "portable":
            for field in _CONTEXT:
                if field in item:
                    record[field] = deepcopy(item[field])
            if not isinstance(item.get("type", "statement"), str) or item.get("type", "statement") not in _TYPES:
                raise ValueError("Unknown imported record type")
            record["type"] = item.get("type", "statement")
            if item.get("salience", "medium") not in ("low", "medium", "high"):
                raise ValueError("Unknown imported salience")
            record["salience"] = item.get("salience", "medium")
            if "topic_slug" in item:
                record["topic_slug"] = _bounded_string(item["topic_slug"], "topic_slug")
            if record.get("subject") is not None:
                _bounded_string(record["subject"], "subject")
        records.append(normalize_record(record))
        # Leave scope absent so the core can retain hash-only source routing
        # after forgetting. Input scope is never copied into this record.
        records[-1].pop("scope", None)
    return records


def _git(repo, *arguments, limit=MAX_SOURCE_BYTES):
    """Run only a literal Git builtin, bounding stdout, stderr and elapsed time."""
    environment = {key: value for key, value in os.environ.items() if not key.startswith("GIT_")}
    environment.update(GIT_CONFIG_NOSYSTEM="1", GIT_CONFIG_GLOBAL=os.devnull,
                       GIT_TERMINAL_PROMPT="0", GIT_NO_REPLACE_OBJECTS="1",
                       GIT_PAGER="cat", GIT_OPTIONAL_LOCKS="0", GIT_NO_LAZY_FETCH="1")
    command = ["git", "--no-pager", "-c", f"core.hooksPath={os.devnull}",
               "-c", "core.fsmonitor=false", "-c", "core.pager=cat", "-c", "protocol.allow=never",
               "-c", "credential.helper=", "-C", repo, *arguments]
    process = subprocess.Popen(command, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                               stderr=subprocess.PIPE, env=environment)
    output, errors = bytearray(), bytearray()
    deadline = time.monotonic() + GIT_TIMEOUT_SECONDS
    try:
        with selectors.DefaultSelector() as selected:
            selected.register(process.stdout, selectors.EVENT_READ, True)
            selected.register(process.stderr, selectors.EVENT_READ, False)
            while selected.get_map():
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise ValueError("Git source command exceeded its time limit")
                for key, _ in selected.select(min(remaining, 0.2)):
                    chunk = os.read(key.fileobj.fileno(), 65536)
                    if not chunk:
                        selected.unregister(key.fileobj)
                    elif key.data:
                        output.extend(chunk)
                        if len(output) > limit:
                            raise ValueError(f"Git source exceeds {limit}-byte limit")
                    elif len(errors) < 4096:
                        errors.extend(chunk[:4096 - len(errors)])
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise ValueError("Git source command exceeded its time limit")
        status = process.wait(timeout=remaining)
        if status:
            raise ValueError("Git source command failed: " + errors.decode("utf-8", errors="replace").strip())
        return bytes(output)
    except subprocess.TimeoutExpired as error:
        raise ValueError("Git source command exceeded its time limit") from error
    finally:
        if process.poll() is None:
            process.kill()
        process.wait()
        process.stdout.close()
        process.stderr.close()


def _repository_allowed(repository, allowed_roots):
    if allowed_roots:
        roots = [os.path.realpath(normalized_path(root)) for root in allowed_roots]
        if not any(os.path.commonpath((repository, root)) == root for root in roots):
            raise PermissionError("Git repository resolves outside allowed roots")


def _git_identity(path, git_path, allowed_roots=None):
    _bounded_string(git_path, "git_path", 4096)
    parsed = PurePosixPath(git_path)
    if (parsed.is_absolute() or ".." in parsed.parts or git_path.startswith("-")
            or parsed.as_posix() != git_path or ":" in git_path or "\\" in git_path):
        raise ValueError("git_path must be a normalized repository-relative path")
    repository = os.path.realpath(normalized_path(path))
    _repository_allowed(repository, allowed_roots)
    root = _git(repository, "rev-parse", "--show-toplevel", limit=8192).decode("utf-8").strip()
    repository = os.path.realpath(root)
    _repository_allowed(repository, allowed_roots)
    identity = hashlib.sha256((repository + "\0" + git_path).encode()).hexdigest()[:24]
    return repository, "napmem:git/" + identity + "/" + quote(git_path, safe="/"), "sess_git_" + identity


def _git_snapshot(repository, revision, git_path):
    _bounded_string(revision, "revision")
    if revision.startswith("-"):
        raise ValueError("revision cannot be an option")
    commit = _git(repository, "rev-parse", "--verify", "--end-of-options",
                  revision + "^{commit}", limit=256).decode("ascii").strip()
    if not _OID.fullmatch(commit):
        raise ValueError("Git revision did not resolve to a commit ID")
    blob = _git(repository, "rev-parse", "--verify", "--end-of-options",
                commit + ":" + git_path, limit=256).decode("ascii").strip()
    if not _OID.fullmatch(blob) or _git(repository, "cat-file", "-t", blob, limit=64).strip() != b"blob":
        raise ValueError("Git source path must identify a committed blob")
    raw = _git(repository, "show", "--no-ext-diff", "--no-textconv", blob)
    return {"content": raw.decode("utf-8"), "sha256": hashlib.sha256(raw).hexdigest(),
            "git_commit": commit, "git_blob": blob, "repository": repository, "git_path": git_path}


def _check_owner(distiller, session, source, previous_path=None):
    prior = next((entry for entry in distiller.data["raw_conversations"]
                  if entry["session_id"] == session), None)
    if prior and prior["file_path"] not in (source, previous_path):
        raise ValueError("session_id already belongs to another source")


def ingest_source(distiller, path, *, format="markdown", scope=None, session_id=None,
                  revision="HEAD", git_path=None, allowed_roots=None, title=None):
    """Capture, sanitize and transactionally ingest an explicitly selected source.

    Receipts have status ingested, excluded or stale. The latter two ingest no
    records. A default import starts in legacy scope. Existing core source
    routing survives replay; an explicit caller scope overrides imported data.
    """
    if format not in FORMATS:
        raise ValueError("format must be one of: " + ", ".join(FORMATS))
    if scope is not None:
        normalize_record({"id": "adapter_scope", "text": "", "scope": scope})
    if session_id is not None:
        _session(session_id)
    distiller.refresh()
    registry, previous_path = None, None
    if format == "git":
        repository, source, default_session = _git_identity(path, git_path, allowed_roots)
        session = session_id or default_session
    else:
        source = normalized_path(path)
        registry = SourceRegistry(distiller.pyramid_path)
        session = session_id or registry.resolve_session_id(source, legacy_sources=distiller.data["raw_conversations"])
    _session(session)

    def excluded():
        return source_is_excluded(distiller.data, source, session_id=session)

    def receipt(status, **fields):
        return {"status": status, "format": format, "source": source, "session_id": session,
                "ingested": 0, "generation": distiller.data["generation"], **fields}

    if excluded():
        return receipt("excluded")
    if format == "git":
        snapshot = _git_snapshot(repository, revision, git_path)
    else:
        snapshot = read_source(source, allowed_roots)
        if session_id is None:
            entry = registry.observe(snapshot, scope=scope, legacy_sources=distiller.data["raw_conversations"])
            session, previous_path = _session(entry["session_id"]), entry.get("previous_path")
    distiller.refresh()
    if excluded():
        return receipt("excluded")
    if format in ("markdown", "git"):
        records = distiller.extract_atomic_units(snapshot["content"], session, source)
        for record in records:
            record.update(authority="source", review_status="unreviewed", supersedes=[])
            if format == "git":
                record["source_anchor"].update({key: snapshot[key] for key in
                                               ("repository", "git_path", "git_commit", "git_blob")})
    else:
        records = _json_records(snapshot["content"], session, source, format)
    if len(records) > MAX_ITEMS:
        raise ValueError(f"Source produces more than {MAX_ITEMS} records")
    with distiller.transaction():
        if excluded():
            return receipt("excluded")
        _check_owner(distiller, session, source, previous_path)
        try:
            current = (_git_snapshot(repository, revision, git_path) if format == "git"
                       else read_source(source, allowed_roots))
        except (OSError, ValueError, UnicodeError):
            return receipt("stale", reason="source_changed_or_unavailable")
        if (current["sha256"] != snapshot["sha256"]
                or (format == "git" and current["git_commit"] != snapshot["git_commit"])):
            return receipt("stale", reason="source_changed_or_unavailable")
        info = {"method": "adapter-" + format, "source_revision": snapshot.get("git_commit", snapshot["sha256"])}
        count = distiller.ingest_session_records(session, title or Path(git_path or source).name, source, records,
                                                scope=scope, source_content=snapshot["content"], extraction_info=info)
    if registry is not None and session_id is None:
        registry.mark_committed(session, snapshot["sha256"])
    return receipt("ingested", ingested=count, source_sha256=snapshot["sha256"],
                   **{key: snapshot[key] for key in ("git_commit", "git_blob") if key in snapshot})


def export_memory(pyramid_path, *, scope=None, as_of=None, max_bytes=16384, max_tokens=2048):
    """Export eligible assertions, stored evidence and citations without source reads.

    The byte/token budget covers the complete compact JSON envelope. Whole
    record/evidence/citation groups are removed together. Importing this data
    never restores its approval or authority as operator input.
    """
    from napmem_retrieval_agent import NapMemRetrievalAgent
    agent = NapMemRetrievalAgent(os.fspath(pyramid_path))
    moment = as_of or datetime.now(UTC).isoformat()
    candidates = sorted(eligible_records(agent.data, scope, moment), key=lambda item: item["id"])
    fields = ("id", "text", "type", "salience", "scope", "memory_kind", "subject", "valid_from",
              "valid_to", "observed_at", "authority", "review_status", "topic_slug")
    anchor_fields = ("file_path", "session_id", "heading", "line_range", "repository", "git_path", "git_commit", "git_blob")

    def envelope(count):
        selected = candidates[:count]
        return {"format": "napmem-portable", "format_version": FORMAT_VERSION, "scope": scope,
                "as_of": moment, "snapshot": {"generation": agent.data["generation"],
                                                "sha256": agent._seen_fingerprint},
                "records": [{key: deepcopy(record.get(key)) for key in fields} for record in selected],
                "evidence": [{**deepcopy(record["evidence"]), "record_id": record["id"]} for record in selected],
                "citations": [{"record_id": record["id"], **{key: deepcopy(record["source_anchor"][key])
                               for key in anchor_fields if key in record["source_anchor"]}} for record in selected],
                "truncated": count < len(candidates), "omitted_count": len(candidates) - count}

    # Validate budgets and establish that metadata alone fits. Search over
    # complete groups rather than leaving evidence for removed assertions.
    bounded_response(envelope(0), max_bytes=max_bytes, max_tokens=max_tokens)
    lower, upper = 0, len(candidates)
    while lower < upper:
        count = (lower + upper + 1) // 2
        candidate = envelope(count)
        candidate["token_estimator"] = TOKEN_ESTIMATOR
        encoded = _account(candidate)
        if len(encoded) <= max_bytes and (max_tokens is None or candidate["estimated_tokens"] <= max_tokens):
            lower = count
        else:
            upper = count - 1
    return bounded_response(envelope(lower), max_bytes=max_bytes, max_tokens=max_tokens)
