"""Private atomic JSON snapshots and reentrant, bounded single-host writer locks."""
from __future__ import annotations

from contextlib import contextmanager
import errno
import hashlib
import json
import logging
import os
from pathlib import Path
import stat
import tempfile
import threading
import time

MAX_STORE_BYTES = 128 * 1024 * 1024
_LOCKS: dict[str, threading.RLock] = {}
_LOCKS_GUARD = threading.Lock()
_HELD = threading.local()
logger = logging.getLogger(__name__)


class StoreConflict(ValueError):
    """A caller attempted to commit a snapshot it did not read."""


class StoreLockTimeout(TimeoutError):
    """Another local writer did not release the canonical lock in time."""


def _path(path) -> str:
    return os.path.realpath(os.path.abspath(os.fspath(path)))


@contextmanager
def store_lock(path, timeout: float = 10):
    """Serialize threads and processes using one stable, never-unlinked sidecar.

    Locks are reentrant in the same thread. Lock the entire read/modify/write
    operation, not just the final replace. This is a single-host protocol;
    callers must not use shared/network filesystems as a multi-host database.
    """
    if (isinstance(timeout, bool) or not isinstance(timeout, (int, float))
            or not 0 <= timeout <= 300):
        raise ValueError("lock timeout must be between 0 and 300 seconds")
    canonical = _path(path)
    held = getattr(_HELD, "paths", None)
    if held is None:
        held = _HELD.paths = {}
    if canonical in held:
        yield
        return
    with _LOCKS_GUARD:
        mutex = _LOCKS.setdefault(canonical, threading.RLock())
    started = time.monotonic()
    if not mutex.acquire(timeout=timeout):
        raise StoreLockTimeout("Canonical writer lock timed out")
    fd = None
    locked = False
    try:
        Path(canonical).parent.mkdir(parents=True, exist_ok=True)
        fd = os.open(canonical + ".lock", os.O_CREAT | os.O_RDWR |
                     getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_CLOEXEC", 0), 0o600)
        if not stat.S_ISREG(os.fstat(fd).st_mode):
            raise ValueError("Writer lock must be a regular file")
        if os.name == "nt":
            import msvcrt
            if os.fstat(fd).st_size == 0:
                os.write(fd, b"\0")
            def acquire():
                os.lseek(fd, 0, os.SEEK_SET)
                msvcrt.locking(fd, msvcrt.LK_NBLCK, 1)
            def release():
                os.lseek(fd, 0, os.SEEK_SET)
                msvcrt.locking(fd, msvcrt.LK_UNLCK, 1)
        else:
            import fcntl
            def acquire():
                fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            def release():
                fcntl.flock(fd, fcntl.LOCK_UN)
        while True:
            try:
                acquire()
                locked = True
                break
            except OSError as exc:
                if exc.errno not in (errno.EACCES, errno.EAGAIN, errno.EDEADLK):
                    raise
                if time.monotonic() - started >= timeout:
                    raise StoreLockTimeout("Canonical writer lock timed out") from exc
                time.sleep(min(.01, max(0, timeout - (time.monotonic() - started))))
        held[canonical] = fd
        yield
    finally:
        held.pop(canonical, None)
        if fd is not None:
            try:
                if locked:
                    release()
            finally:
                os.close(fd)
        mutex.release()


def _reject_constant(value):
    raise ValueError("Nonfinite JSON values are not valid store data")


def _read_bytes(path) -> bytes | None:
    try:
        fd = os.open(os.fspath(path), os.O_RDONLY | getattr(os, "O_NONBLOCK", 0))
    except FileNotFoundError:
        return None
    try:
        info = os.fstat(fd)
        # A reader can hold the previous inode after atomic replacement. Its
        # link count is then zero, but the open descriptor is a valid snapshot.
        if not stat.S_ISREG(info.st_mode) or info.st_nlink > 1:
            raise ValueError("Store must be a regular, singly-linked file")
        if info.st_size > MAX_STORE_BYTES:
            raise ValueError("Store exceeds the supported size limit")
        with os.fdopen(fd, "rb") as stream:
            fd = -1
            payload = stream.read(MAX_STORE_BYTES + 1)
        if len(payload) > MAX_STORE_BYTES:
            raise ValueError("Store exceeds the supported size limit")
    finally:
        if fd >= 0:
            os.close(fd)
    return payload


def file_fingerprint(path) -> str | None:
    """Fingerprint raw bytes, including a disposable malformed cache."""
    payload = _read_bytes(path)
    return hashlib.sha256(payload).hexdigest() if payload is not None else None


def read_snapshot(path) -> tuple[dict | None, str | None]:
    """Read one atomic file generation; missing files create nothing."""
    payload = _read_bytes(path)
    if payload is None:
        return None, None
    try:
        data = json.loads(payload.decode("utf-8"), parse_constant=_reject_constant)
    except (UnicodeError, ValueError, RecursionError) as exc:
        raise ValueError("Store is not a valid UTF-8 JSON object") from exc
    if not isinstance(data, dict):
        raise ValueError("Store must contain a JSON object")
    return data, hashlib.sha256(payload).hexdigest()


def _sync_directory(parent: Path) -> None:
    if os.name == "nt":
        return
    fd = os.open(parent, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def atomic_write(path, data: dict, *, expected_fingerprint: str | None) -> str:
    """CAS a private JSON file. A post-replace directory-sync issue is logged.

    After replace the commit is visible. A directory fsync failure cannot be
    reported as an uncommitted mutation; callers must retain the new snapshot.
    """
    if not isinstance(data, dict):
        raise ValueError("Atomic JSON data must be an object")
    payload = (json.dumps(data, ensure_ascii=False, indent=2, allow_nan=False) + "\n").encode("utf-8")
    if len(payload) > MAX_STORE_BYTES:
        raise ValueError("Store exceeds the supported size limit")
    destination = Path(_path(path))
    with store_lock(destination):
        current = file_fingerprint(destination)
        if current != expected_fingerprint:
            raise StoreConflict("Store changed since the caller's snapshot; reload before committing")
        temporary = None
        try:
            with tempfile.NamedTemporaryFile(dir=destination.parent, prefix="." + destination.name + ".",
                                             suffix=".tmp", delete=False) as stream:
                temporary = Path(stream.name)
                stream.write(payload)
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporary, destination)
            temporary = None
            try:
                _sync_directory(destination.parent)
            except OSError as exc:
                logger.warning("JSON commit visible; directory durability sync unavailable (%s)", type(exc).__name__)
        finally:
            if temporary is not None:
                temporary.unlink(missing_ok=True)
    return hashlib.sha256(payload).hexdigest()
