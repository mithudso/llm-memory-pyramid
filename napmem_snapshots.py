"""Checksummed store exports and atomic publication of complete mirror generations.

Export reads the canonical store under its writer lock. Cache provenance is
separate: old caches have per-record text keys but no generation commitment.
No function here contacts a host, runs inference, or overwrites a live store.
"""

from __future__ import annotations

import argparse
from copy import deepcopy
from datetime import UTC, datetime
import hashlib
import json
import math
import os
from pathlib import Path
import re
import shutil
import stat
import sys
import tarfile
import tempfile
from typing import Any
from uuid import uuid4

from napmem_model import migrate_store, parse_time


STORE_FILE = "napmem_pyramid.json"
CACHE_FILE = STORE_FILE + ".embindex.json"
MANIFEST_FILE = "manifest.json"
CURRENT_FILE = "current.json"
SNAPSHOT_VERSION = "1.0.0"
MAX_FILE_BYTES = 64 * 1024 * 1024
MAX_MANIFEST_BYTES = 65536
MAX_ARCHIVE_BYTES = 2 * MAX_FILE_BYTES + 1024 * 1024
SNAPSHOT_FILES = (STORE_FILE, CACHE_FILE, MANIFEST_FILE)


def _sha(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _json(raw: bytes, label: str) -> dict[str, Any]:
    def reject_constant(value):
        raise ValueError(f"Nonfinite JSON constant in {label}: {value}")
    value = json.loads(raw, parse_constant=reject_constant)
    if not isinstance(value, dict):
        raise ValueError(f"{label} must contain a JSON object")
    return value


def _read(path: Path, limit: int = MAX_FILE_BYTES) -> bytes:
    flags = os.O_RDONLY | getattr(os, "O_NONBLOCK", 0) | getattr(os, "O_NOFOLLOW", 0)
    fd = os.open(path, flags)
    try:
        details = os.fstat(fd)
        if not stat.S_ISREG(details.st_mode) or details.st_nlink != 1:
            raise ValueError(f"Snapshot member must be a regular, singly linked file: {path.name}")
        if details.st_size > limit:
            raise ValueError(f"Snapshot member exceeds size limit: {path.name}")
        with os.fdopen(fd, "rb", closefd=False) as stream:
            raw = stream.read(limit + 1)
        if len(raw) > limit:
            raise ValueError(f"Snapshot member exceeds size limit: {path.name}")
        return raw
    finally:
        os.close(fd)


def _write(path: Path, raw: bytes) -> None:
    with path.open("xb") as stream:
        os.chmod(path, 0o600)
        stream.write(raw)
        stream.flush()
        os.fsync(stream.fileno())


def _encoded(value: dict[str, Any]) -> bytes:
    return (json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2, allow_nan=False) + "\n").encode("utf-8")


def _cache_info(cache: dict[str, Any], data: dict[str, Any]) -> tuple[str, dict[str, Any]]:
    generation = cache.get("generation")
    if generation is not None and (isinstance(generation, bool) or not isinstance(generation, int)
                                   or generation != data["generation"]):
        raise ValueError("Cache generation does not match the store")
    model, vectors = cache.get("model"), cache.get("vectors")
    if not isinstance(model, str) or not model or not isinstance(vectors, dict):
        raise ValueError("Cache must identify its model and vectors")
    keys = {item["id"]: _sha(item["text"].encode("utf-8"))[:16] for item in data["memory_records"]}
    dimensions = set()
    for rid, entry in vectors.items():
        if (rid not in keys or not isinstance(entry, dict) or entry.get("key") != keys[rid]
                or not isinstance(entry.get("vec"), list) or not 1 <= len(entry["vec"]) <= 8192):
            raise ValueError("Cache record text hashes do not match the store")
        try:
            finite = all(not isinstance(value, bool) and isinstance(value, (int, float)) and math.isfinite(value)
                         for value in entry["vec"])
        except OverflowError:
            finite = False
        if not finite:
            raise ValueError("Cache vector coordinates must be finite numbers")
        dimensions.add(len(entry["vec"]))
    if len(dimensions) > 1:
        raise ValueError("Cache vectors have inconsistent dimensions")
    embedding = {"model": model, "backend": cache.get("backend"),
                 "dimensions": next(iter(dimensions)) if len(dimensions) == 1 else None,
                 "config": deepcopy(cache.get("embedding_config"))}
    provenance = "generation-bound" if generation is not None else "record-text-hashes-only"
    return provenance, embedding


def export_snapshot(pyramid_path: str | os.PathLike, destination: str | os.PathLike,
                    *, include_cache: bool = True) -> dict[str, Any]:
    """Export exact canonical bytes to a new or empty directory without changing them.

    An absent, invalid or explicitly stale cache is omitted. Old caches with
    matching record text hashes remain labeled generation-unverified.
    """
    from napmem_storage import read_snapshot, store_lock
    source, destination = Path(pyramid_path), Path(destination)
    if destination.exists() and (not destination.is_dir() or any(destination.iterdir())):
        raise FileExistsError("Snapshot destination must be new or empty")
    destination.parent.mkdir(parents=True, exist_ok=True)
    stage = Path(tempfile.mkdtemp(prefix=".snapshot-", dir=destination.parent))
    try:
        with store_lock(source):
            original, fingerprint = read_snapshot(source)
            if original is None:
                raise FileNotFoundError(source)
            data = migrate_store(deepcopy(original))
            raw = _read(source)
            if _sha(raw) != fingerprint:
                raise ValueError("Canonical store changed while exporting")
            cache_raw, cache, provenance, embedding = None, None, "absent", None
            absence_reason = "disabled" if not include_cache else "missing"
            if include_cache:
                try:
                    cache_raw = _read(Path(str(source) + ".embindex.json"))
                    cache = _json(cache_raw, "cache")
                    provenance, embedding = _cache_info(cache, data)
                except FileNotFoundError:
                    pass
                except (OSError, ValueError, TypeError, RecursionError):
                    cache_raw, cache, provenance, embedding = None, None, "absent", None
                    absence_reason = "invalid_or_stale_cache"
            manifest = {
                "snapshot_version": SNAPSHOT_VERSION, "generation": data["generation"],
                "schema": original.get("version", "1.0.0"), "created_at": datetime.now(UTC).isoformat(),
                "source_updated_at": original.get("updated_at"),
                "store": {"filename": STORE_FILE, "sha256": _sha(raw), "bytes": len(raw)},
                "cache": {"status": "included" if cache_raw is not None else "absent",
                          "filename": CACHE_FILE if cache_raw is not None else None,
                          "sha256": _sha(cache_raw) if cache_raw is not None else None,
                          "bytes": len(cache_raw) if cache_raw is not None else None,
                          "generation": cache.get("generation") if cache is not None else None,
                          "provenance": provenance,
                          "absence_reason": None if cache_raw is not None else absence_reason},
                "embedding": embedding,
            }
            _write(stage / STORE_FILE, raw)
            if cache_raw is not None:
                _write(stage / CACHE_FILE, cache_raw)
            manifest_raw = _encoded(manifest)
            if len(manifest_raw) > MAX_MANIFEST_BYTES:
                raise ValueError("Snapshot manifest exceeds size limit")
            _write(stage / MANIFEST_FILE, manifest_raw)
        load_snapshot(stage)
        os.replace(stage, destination)
        return manifest
    finally:
        if stage.exists():
            shutil.rmtree(stage)


def resolve_snapshot_directory(directory: str | os.PathLike) -> Path:
    """Resolve one atomic generation pointer, or return the legacy flat directory."""
    root = Path(directory)
    try:
        pointer = _json(_read(root / CURRENT_FILE, MAX_MANIFEST_BYTES), "snapshot pointer")
    except FileNotFoundError:
        return root
    relative = pointer.get("directory")
    if (set(pointer) != {"directory", "generation", "manifest_sha256"}
            or not isinstance(relative, str) or re.fullmatch(r"generations/gen-[0-9]+-[0-9a-f]{32}", relative) is None):
        raise ValueError("Invalid snapshot generation pointer")
    target = root / relative
    if target.is_symlink() or target.parent.is_symlink():
        raise ValueError("Snapshot generation pointer must not follow directory links")
    raw = _read(target / MANIFEST_FILE, MAX_MANIFEST_BYTES)
    if _sha(raw) != pointer["manifest_sha256"]:
        raise ValueError("Snapshot pointer manifest checksum mismatch")
    manifest = _json(raw, "snapshot manifest")
    if (isinstance(pointer["generation"], bool) or not isinstance(pointer["generation"], int)
            or manifest.get("generation") != pointer["generation"]):
        raise ValueError("Snapshot pointer generation mismatch")
    return target


def load_snapshot(directory: str | os.PathLike) -> dict[str, Any]:
    """Validate checksums, generation, schema and cache provenance; return copied data.

    Manifest-free flat mirrors remain readable with explicit unverified
    provenance. They never acquire a validated generation merely by loading.
    """
    directory = resolve_snapshot_directory(directory)
    raw = _read(directory / STORE_FILE)
    original = _json(raw, "snapshot store")
    data = migrate_store(deepcopy(original))
    try:
        manifest = _json(_read(directory / MANIFEST_FILE, MAX_MANIFEST_BYTES), "snapshot manifest")
    except FileNotFoundError:
        cache = None
        try:
            cache = _json(_read(directory / CACHE_FILE), "legacy cache")
        except (FileNotFoundError, ValueError):
            pass
        return {"data": data, "manifest": {"snapshot_version": None, "generation": data["generation"],
                                              "schema": original.get("version", "1.0.0")},
                "cache": cache, "verification": {"status": "legacy-unverified", "generation": "unverified",
                                                   "store": "checksum-unavailable", "cache": "legacy-unverified" if cache else "absent"}}
    if (manifest.get("snapshot_version") != SNAPSHOT_VERSION
            or isinstance(manifest.get("generation"), bool) or not isinstance(manifest.get("generation"), int)
            or manifest.get("generation") != data["generation"]
            or manifest.get("schema") != original.get("version", "1.0.0")):
        raise ValueError("Snapshot generation or schema mismatch")
    parse_time(manifest.get("created_at"), "snapshot created_at")
    store_info = manifest.get("store")
    if (not isinstance(store_info, dict) or store_info.get("filename") != STORE_FILE
            or store_info.get("sha256") != _sha(raw) or store_info.get("bytes") != len(raw)):
        raise ValueError("Snapshot store checksum mismatch")
    cache_info = manifest.get("cache")
    if not isinstance(cache_info, dict):
        raise ValueError("Snapshot cache declaration is missing")
    cache = None
    if cache_info.get("status") == "included":
        cache_raw = _read(directory / CACHE_FILE)
        if (cache_info.get("filename") != CACHE_FILE or cache_info.get("sha256") != _sha(cache_raw)
                or cache_info.get("bytes") != len(cache_raw)):
            raise ValueError("Snapshot cache checksum mismatch")
        cache = _json(cache_raw, "snapshot cache")
        provenance, embedding = _cache_info(cache, data)
        if (cache_info.get("generation") != cache.get("generation") or cache_info.get("provenance") != provenance
                or manifest.get("embedding") != embedding):
            raise ValueError("Snapshot cache provenance mismatch")
    elif cache_info.get("status") == "absent":
        if ((directory / CACHE_FILE).exists() or cache_info.get("sha256") is not None
                or cache_info.get("filename") is not None or cache_info.get("bytes") is not None
                or cache_info.get("generation") is not None or cache_info.get("provenance") != "absent"
                or manifest.get("embedding") is not None):
            raise ValueError("Snapshot declares an absent cache but includes cache state")
        provenance = "absent"
    else:
        raise ValueError("Invalid snapshot cache status")
    return {"data": data, "manifest": manifest, "cache": cache,
            "verification": {"status": "verified", "generation": "verified", "store": "sha256",
                             "cache": provenance}}


def unpack_snapshot(archive: str | os.PathLike, destination: str | os.PathLike) -> dict[str, Any]:
    """Unpack only the three fixed regular-file members from a bounded plain tar."""
    destination = Path(destination)
    destination.mkdir(parents=True, exist_ok=True)
    if any(destination.iterdir()):
        raise FileExistsError("Snapshot extraction destination must be empty")
    if Path(archive).stat().st_size > MAX_ARCHIVE_BYTES:
        raise ValueError("Snapshot archive exceeds size limit")
    seen = set()
    try:
        with tarfile.open(archive, "r:") as stream:
            for member in stream:
                if (not member.isfile() or member.name not in SNAPSHOT_FILES or member.name in seen
                        or member.size > (MAX_MANIFEST_BYTES if member.name == MANIFEST_FILE else MAX_FILE_BYTES)):
                    raise ValueError("Invalid snapshot archive member")
                seen.add(member.name)
                source = stream.extractfile(member)
                if source is None:
                    raise ValueError("Snapshot archive member has no data")
                with source:
                    raw = source.read(member.size + 1)
                if len(raw) != member.size:
                    raise ValueError("Snapshot archive member size mismatch")
                _write(destination / member.name, raw)
        if not {STORE_FILE, MANIFEST_FILE} <= seen:
            raise ValueError("Snapshot archive is incomplete")
        result = load_snapshot(destination)
        return result["manifest"]
    except BaseException:
        for name in seen:
            (destination / name).unlink(missing_ok=True)
        raise


def publish_snapshot(staging: str | os.PathLike, mirror_root: str | os.PathLike) -> dict[str, Any]:
    """Validate and publish one immutable directory with one serialized pointer change."""
    from napmem_storage import atomic_write, read_snapshot, store_lock
    staging, root = Path(staging), Path(mirror_root)
    checked = load_snapshot(staging)
    if checked["verification"]["status"] != "verified":
        raise ValueError("Cannot publish a manifest-free snapshot")
    manifest = checked["manifest"]
    generations = root / "generations"
    generations.mkdir(parents=True, exist_ok=True)
    name = f"gen-{manifest['generation']}-{uuid4().hex}"
    copied = generations / name
    try:
        copied.mkdir(mode=0o700)
        for filename in SNAPSHOT_FILES:
            source = staging / filename
            if source.exists():
                _write(copied / filename, _read(source, MAX_MANIFEST_BYTES if filename == MANIFEST_FILE else MAX_FILE_BYTES))
        load_snapshot(copied)
        if os.name != "nt":
            for directory in (copied, generations, root):
                fd = os.open(directory, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
                try:
                    os.fsync(fd)
                finally:
                    os.close(fd)
        pointer = root / CURRENT_FILE
        with store_lock(pointer):
            current, fingerprint = read_snapshot(pointer)
            if current is not None:
                previous = load_snapshot(root)["manifest"]
                if previous["generation"] > manifest["generation"]:
                    shutil.rmtree(copied)
                    return previous
                if (previous["generation"] == manifest["generation"]
                        and previous["store"]["sha256"] != manifest["store"]["sha256"]):
                    raise ValueError("Snapshot generation conflicts with the published store")
            atomic_write(pointer, {"directory": "generations/" + name, "generation": manifest["generation"],
                                   "manifest_sha256": _sha(_read(copied / MANIFEST_FILE, MAX_MANIFEST_BYTES))},
                         expected_fingerprint=fingerprint)
        return manifest
    except BaseException:
        shutil.rmtree(copied, ignore_errors=True)
        raise


def main() -> int:
    parser = argparse.ArgumentParser(description="Export a locked NapMem snapshot without changing the store.")
    commands = parser.add_subparsers(dest="command", required=True)
    for name in ("export", "export-archive"):
        command = commands.add_parser(name)
        command.add_argument("--pyramid", required=True)
        command.add_argument("--without-cache", action="store_true")
        if name == "export":
            command.add_argument("--destination", required=True)
    args = parser.parse_args()
    source = os.path.expanduser(os.path.expandvars(args.pyramid))
    if args.command == "export":
        manifest = export_snapshot(source, args.destination, include_cache=not args.without_cache)
        print(json.dumps(manifest))
    else:
        with tempfile.TemporaryDirectory(prefix="napmem-export-") as temp:
            destination = Path(temp) / "snapshot"
            export_snapshot(source, destination, include_cache=not args.without_cache)
            with tarfile.open(fileobj=sys.stdout.buffer, mode="w|") as archive:
                for filename in SNAPSHOT_FILES:
                    path = destination / filename
                    if path.exists():
                        archive.add(path, arcname=filename, recursive=False)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
