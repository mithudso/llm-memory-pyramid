"""Bounded source snapshots and a persistent, rename-aware source registry."""

from __future__ import annotations

from copy import deepcopy
import hashlib
import os
from pathlib import Path
import stat
from typing import Any, Callable

from napmem_storage import atomic_write, read_snapshot, store_lock


MAX_SOURCE_BYTES = 2 * 1024 * 1024


def normalized_path(path: str) -> str:
    return os.path.abspath(os.path.normpath(os.fspath(path)))


def _fd_path(fd: int) -> str | None:
    try:
        import fcntl
        if hasattr(fcntl, "F_GETPATH"):
            return fcntl.fcntl(fd, fcntl.F_GETPATH, bytes(1024)).split(b"\0", 1)[0].decode("utf-8")
    except (OSError, ValueError, UnicodeDecodeError):
        pass
    try:
        return os.readlink(f"/proc/self/fd/{fd}")
    except OSError:
        return None


def read_source(path: str, allowed_roots: list[str] | None = None, *,
                max_bytes: int = MAX_SOURCE_BYTES,
                fd_path_resolver: Callable[[int], str | None] | None = None) -> dict[str, Any]:
    """Capture one bounded opened file; verify its fd path rather than a pre-open path.

    None defaults to the source directory. An explicit empty root list disables
    the path boundary while retaining regular-file, hard-link and size guards.
    """
    if isinstance(max_bytes, bool) or not isinstance(max_bytes, int) or max_bytes < 1:
        raise ValueError("max_bytes must be a positive integer")
    path = normalized_path(path)
    roots = [os.path.realpath(root) for root in allowed_roots] if allowed_roots is not None else [os.path.realpath(os.path.dirname(path))]
    fd = os.open(path, os.O_RDONLY | os.O_NONBLOCK | getattr(os, "O_CLOEXEC", 0))
    try:
        before = os.fstat(fd)
        if not stat.S_ISREG(before.st_mode):
            raise PermissionError(f"{path}: not a regular file")
        if before.st_nlink > 1:
            raise PermissionError(f"{path}: refusing multi-linked file")
        real = (fd_path_resolver or _fd_path)(fd)
        if real is None:
            raise PermissionError(f"{path}: cannot verify opened file's true path")
        if roots and not any(os.path.commonpath((real, root)) == root for root in roots):
            raise PermissionError(f"{path}: resolves outside allowed roots")
        if before.st_size > max_bytes:
            raise ValueError(f"Source exceeds {max_bytes}-byte limit")
        chunks, remaining = [], max_bytes + 1
        while remaining:
            chunk = os.read(fd, min(65536, remaining))
            if not chunk:
                break
            chunks.append(chunk)
            remaining -= len(chunk)
        raw = b"".join(chunks)
        if len(raw) > max_bytes:
            raise ValueError(f"Source exceeds {max_bytes}-byte limit")
        after = os.fstat(fd)
        if (before.st_mtime_ns, before.st_size) != (after.st_mtime_ns, after.st_size):
            raise ValueError("Source changed during guarded read")
        content = raw.decode("utf-8")
        return {"path": path, "content": content, "sha256": hashlib.sha256(raw).hexdigest(),
                "device": before.st_dev, "inode": before.st_ino, "mtime": before.st_mtime,
                "size": len(raw)}
    finally:
        os.close(fd)


class SourceRegistry:
    """Private metadata-only registry; observing a file never marks it committed."""

    def __init__(self, pyramid_path: str, path: str | None = None):
        self.pyramid_path = os.fspath(pyramid_path)
        self.path = path or self.pyramid_path + ".sources.json"

    def _read(self):
        data, digest = read_snapshot(self.path)
        if data is None:
            return {"version": "1.0.0", "generation": 0, "sources": []}, digest
        if (data.get("version") != "1.0.0" or not isinstance(data.get("sources"), list)
                or not isinstance(data.get("generation"), int)):
            raise ValueError("Malformed persistent source registry")
        ids, paths = set(), set()
        for entry in data["sources"]:
            if (not isinstance(entry, dict) or not isinstance(entry.get("session_id"), str)
                    or not isinstance(entry.get("path"), str) or entry["session_id"] in ids
                    or entry["path"] in paths or entry.get("status") not in ("present", "missing")):
                raise ValueError("Malformed source registry identity")
            ids.add(entry["session_id"])
            paths.add(entry["path"])
        return data, digest

    def list(self) -> list[dict[str, Any]]:
        return deepcopy(self._read()[0]["sources"])

    def lookup(self, *, path: str | None = None, session_id: str | None = None) -> dict[str, Any] | None:
        if (path is None) == (session_id is None):
            raise ValueError("Supply exactly one path or session_id")
        target = normalized_path(path) if path is not None else session_id
        field = "path" if path is not None else "session_id"
        return next((entry for entry in self.list() if entry[field] == target), None)

    def resolve_session_id(self, path: str, *, legacy_sources=None) -> str:
        """Resolve known identities before reading a potentially excluded source."""
        path = normalized_path(path)
        entries = self.list()
        known = next((entry for entry in entries if entry["path"] == path), None)
        if known:
            return known["session_id"]
        legacy = next((entry for entry in legacy_sources or []
                       if normalized_path(entry.get("file_path", "")) == path), None)
        if legacy:
            return legacy["session_id"]
        base = "sess_" + Path(path).stem
        used = {entry["session_id"] for entry in [*entries, *(legacy_sources or [])]}
        return base if base not in used else base + "_" + hashlib.sha256(path.encode()).hexdigest()[:12]

    def _save(self, data, expected):
        data["generation"] += 1
        atomic_write(self.path, data, expected_fingerprint=expected)

    def observe(self, snapshot: dict[str, Any], *, scope: str | None = None,
                live_paths: list[str] | set[str] | None = None,
                legacy_sources: list[dict[str, Any]] | None = None) -> dict[str, Any]:
        path = normalized_path(snapshot["path"])
        live = {normalized_path(item) for item in live_paths} if live_paths is not None else {path}
        with store_lock(self.path):
            data, expected = self._read()
            before = deepcopy(data)
            entry = next((item for item in data["sources"] if item["path"] == path), None)
            if entry is None:
                candidates = [item for item in data["sources"] if item["path"] not in live
                              and not os.path.exists(item["path"])
                              and item.get("device") == snapshot["device"] and item.get("inode") == snapshot["inode"]
                              and item.get("sha256") == snapshot["sha256"]]
                if len(candidates) == 1:
                    entry = candidates[0]
                    entry["previous_path"] = entry["path"]
                    entry["path"] = path
            if entry is None:
                legacy = next((item for item in legacy_sources or []
                               if normalized_path(item.get("file_path", "")) == path), {})
                used = {item["session_id"] for item in data["sources"]}
                used.update(item["session_id"] for item in legacy_sources or [] if "session_id" in item)
                base = "sess_" + Path(path).stem
                session = legacy.get("session_id") or base
                if session in used and not legacy:
                    session = base + "_" + hashlib.sha256(path.encode()).hexdigest()[:12]
                suffix = 1
                while session in {item["session_id"] for item in data["sources"]}:
                    session = base + "_" + hashlib.sha256((path + str(suffix)).encode()).hexdigest()[:12]
                    suffix += 1
                entry = {"session_id": session, "path": path, "committed_sha256": None,
                         "scope": scope or legacy.get("scope", "legacy")}
                data["sources"].append(entry)
            entry.update({field: snapshot[field] for field in ("sha256", "device", "inode", "mtime", "size")})
            entry["status"] = "present"
            if scope is not None:
                entry["scope"] = scope
            if data != before:
                self._save(data, expected)
            return deepcopy(entry)

    def mark_committed(self, session_id: str, digest: str) -> bool:
        with store_lock(self.path):
            data, expected = self._read()
            entry = next((item for item in data["sources"] if item["session_id"] == session_id), None)
            if entry is None or entry.get("sha256") != digest or entry["status"] != "present":
                return False
            if entry.get("committed_sha256") != digest:
                entry["committed_sha256"] = digest
                self._save(data, expected)
            return True

    def mark_missing(self, live_paths: list[str] | set[str], *, root: str | None = None) -> list[dict[str, Any]]:
        live = {normalized_path(path) for path in live_paths}
        with store_lock(self.path):
            data, expected = self._read()
            changed = []
            for entry in data["sources"]:
                if root is not None and os.path.commonpath((entry["path"], normalized_path(root))) != normalized_path(root):
                    continue
                if entry["path"] not in live and entry["status"] != "missing":
                    entry["status"] = "missing"
                    changed.append(deepcopy(entry))
            if changed:
                self._save(data, expected)
            return changed

    def read_current(self, session_id: str, *, allowed_roots: list[str] | None = None) -> dict[str, Any] | None:
        entry = self.lookup(session_id=session_id)
        if entry is None or entry["status"] != "present":
            return None
        try:
            return read_source(entry["path"], allowed_roots)
        except FileNotFoundError:
            return None
