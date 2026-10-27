#!/usr/bin/env python3
"""
NapMem MCP failover proxy (stdio)

Sits between an MCP client and the NapMem MCP server. The primary backend is
the canonical server on the remote box over SSH; the fallback is a local
`napmem_mcp_server.py` reading a mirrored snapshot of the canonical pyramid.

  - Startup: probe SSH. If the remote is unreachable, start on the local
    mirror immediately. If it is reachable, relay to it and refresh the
    local mirror in the background (when older than NAPMEM_MIRROR_MAX_AGE).
  - Mid-session: if the SSH backend dies, spawn the local server, replay the
    client's `initialize` handshake into it, and resend every in-flight
    request. The client sees no disconnect.
  - While on the mirror, every tools/call result gets one extra text item
    saying the answer came from a local snapshot and how old it is.

The server is read-only, so the mirror can be stale but never divergent.
Pure stdlib.

Config (env):
  NAPMEM_REMOTE_HOST      ssh target (user@host). Unset -> first line of
                          ~/.napmem/remote_host. Neither -> local only.
  NAPMEM_REMOTE_PYRAMID   canonical store on the remote
                          (default $HOME/.napmem/napmem_pyramid.json)
  NAPMEM_REMOTE_REPO      repo checkout on the remote
                          (default $HOME/dev/llm-memory-pyramid)
  NAPMEM_MIRROR_DIR       local mirror dir (default ~/.napmem/mirror)
  NAPMEM_MIRROR_MAX_AGE   seconds before a background refresh (default 3600)
  NAPMEM_SSH_TIMEOUT      ssh ConnectTimeout seconds (default 5)
  NAPMEM_REMOTE_REQUEST_TIMEOUT  seconds a remote request may stay
                          unanswered before the remote counts as hung and
                          the proxy fails over (default 60)
  NAPMEM_FALLBACK_OLLAMA  embedding host for the local server
                          (default http://127.0.0.1:11434)

Usage:
  python3 napmem_mcp_failover.py               # run as the MCP server
  python3 napmem_mcp_failover.py --sync-mirror # refresh the mirror and exit
  python3 napmem_mcp_failover.py --status      # print remote/mirror status
"""

import argparse
import json
import logging
import os
import queue
import select
import selectors
import shlex
import subprocess
import sys
import tarfile
import tempfile
import threading
import time
from pathlib import Path
from typing import Any, Callable

from napmem_mcp_server import (
    MAX_LINE_BYTES, bounded_lines, bounded_tool_result, limit_wire_response,
    budget_request_error, response_budget_fits_id, tool_budgets, valid_request_id, wire_json,
)
from napmem_snapshots import (
    MAX_ARCHIVE_BYTES, STORE_FILE, load_snapshot, publish_snapshot,
    resolve_snapshot_directory, unpack_snapshot,
)

logger = logging.getLogger("napmem_failover")

HERE = Path(__file__).resolve().parent
LOCAL_SERVER = HERE / "napmem_mcp_server.py"
HOST_FILE = Path.home() / ".napmem" / "remote_host"

REPLAY_INIT_ID = "__napmem_failover_init__"
MAX_LOCAL_RESTARTS = 2
WATCHDOG_TICK_S = 1.0
MIRROR_FILES = ("napmem_pyramid.json", "napmem_pyramid.json.embindex.json")


def remote_host() -> str | None:
    host = os.environ.get("NAPMEM_REMOTE_HOST", "").strip()
    if host:
        return host
    try:
        first = HOST_FILE.read_text(encoding="utf-8").strip().splitlines()
    except OSError:
        return None
    return first[0].strip() if first and first[0].strip() else None


def remote_pyramid() -> str:
    return os.environ.get("NAPMEM_REMOTE_PYRAMID", "$HOME/.napmem/napmem_pyramid.json")


def mirror_dir() -> Path:
    return Path(os.environ.get("NAPMEM_MIRROR_DIR", str(Path.home() / ".napmem" / "mirror")))


def mirror_pyramid() -> Path:
    return resolve_snapshot_directory(mirror_dir()) / STORE_FILE


def ssh_base(host: str) -> list[str]:
    timeout = os.environ.get("NAPMEM_SSH_TIMEOUT", "5")
    return ["ssh", "-o", "BatchMode=yes", "-o", f"ConnectTimeout={timeout}",
            # Detect a vanished box in ~30s instead of hanging on TCP.
            "-o", "ServerAliveInterval=15", "-o", "ServerAliveCountMax=2", host]


def primary_cmd(host: str) -> list[str]:
    repo = os.environ.get("NAPMEM_REMOTE_REPO", "$HOME/dev/llm-memory-pyramid")
    pyr = remote_pyramid()
    return ssh_base(host) + [
        f'cd "{repo}" && NAPMEM_PYRAMID="{pyr}" python3 napmem_mcp_server.py --pyramid "{pyr}"'
    ]


def fallback_cmd() -> list[str]:
    path = mirror_pyramid()
    if path.exists():
        load_snapshot(path.parent)
    return [sys.executable, str(LOCAL_SERVER), "--pyramid", str(path)]


def fallback_env() -> dict[str, str]:
    env = dict(os.environ)
    # Remote fleet hosts are likely down too when we are on the fallback;
    # embed on this box only. Same model as remote keeps the mirrored cache valid.
    env["NAPMEM_OLLAMA_URL"] = os.environ.get("NAPMEM_FALLBACK_OLLAMA", "http://127.0.0.1:11434")
    env["NAPMEM_CACHE_READ_ONLY"] = "1"
    return env


def probe_remote(host: str) -> bool:
    timeout = float(os.environ.get("NAPMEM_SSH_TIMEOUT", "5"))
    try:
        proc = subprocess.run(ssh_base(host) + ["true"], stdin=subprocess.DEVNULL,
                              capture_output=True, timeout=timeout + 5, check=False)
    except (OSError, subprocess.TimeoutExpired):
        return False
    return proc.returncode == 0


def mirror_age_s(pyramid: Path | None = None) -> float | None:
    try:
        return time.time() - (pyramid or mirror_pyramid()).stat().st_mtime
    except (OSError, ValueError):
        return None


def describe_age(age: float | None) -> str:
    if age is None:
        return "no mirror snapshot exists yet"
    if age < 3600:
        return f"snapshot is {int(age // 60)} min old"
    if age < 86400:
        return f"snapshot is {age / 3600:.1f} h old"
    return f"snapshot is {age / 86400:.1f} days old"


def describe_mirror_snapshot(pyramid: Path | None = None) -> str:
    age = describe_age(mirror_age_s(pyramid))
    try:
        checked = load_snapshot(pyramid.parent if pyramid else mirror_dir())
    except FileNotFoundError:
        return age + "; generation unavailable; verification unavailable"
    except (OSError, ValueError, TypeError):
        return age + "; generation unavailable; verification failed"
    verification = checked["verification"]
    return (f"{age}; generation {checked['manifest']['generation']} "
            f"({verification['generation']}); verification {verification['status']}; "
            f"cache {verification['cache']}")


def remote_snapshot_cmd(host: str) -> list[str]:
    """Ask the remote exporter to hold its canonical lock while binding a snapshot."""
    repo = os.environ.get("NAPMEM_REMOTE_REPO", "$HOME/dev/llm-memory-pyramid")
    runner = ("import os,runpy,sys; "
              "sys.path.insert(0,os.path.expanduser(os.path.expandvars(sys.argv.pop(1)))); "
              "runpy.run_module('napmem_snapshots',run_name='__main__')")
    command = shlex.join(["python3", "-c", runner, repo, "export-archive", "--pyramid", remote_pyramid()])
    base = ssh_base(host)
    return base[:-1] + ["-C", base[-1], command]


def _receive_snapshot(host: str, destination: Path, *, timeout: float = 300) -> None:
    """Stream bounded stdout/stderr without letting a stalled child hold the proxy."""
    proc = subprocess.Popen(remote_snapshot_cmd(host), stdin=subprocess.DEVNULL,
                            stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    assert proc.stdout is not None and proc.stderr is not None
    deadline, total, errors = time.monotonic() + timeout, 0, bytearray()
    try:
        with destination.open("xb") as output, selectors.DefaultSelector() as selector:
            for stream in (proc.stdout, proc.stderr):
                os.set_blocking(stream.fileno(), False)
                selector.register(stream, selectors.EVENT_READ)
            while selector.get_map():
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise TimeoutError("Snapshot transfer timed out")
                for key, _ in selector.select(min(.2, remaining)):
                    chunk = os.read(key.fileobj.fileno(), 65536)
                    if not chunk:
                        selector.unregister(key.fileobj)
                    elif key.fileobj is proc.stdout:
                        total += len(chunk)
                        if total > MAX_ARCHIVE_BYTES:
                            raise ValueError("Snapshot transfer exceeds size limit")
                        output.write(chunk)
                    elif len(errors) < 16384:
                        errors.extend(chunk[:16384 - len(errors)])
            output.flush()
            os.fsync(output.fileno())
        if proc.wait(timeout=max(.1, deadline - time.monotonic())) != 0:
            raise RuntimeError(errors.decode("utf-8", "replace").strip() or "Remote snapshot export failed")
    finally:
        if proc.poll() is None:
            proc.kill()
            proc.wait(timeout=5)
        proc.stdout.close()
        proc.stderr.close()


def sync_mirror(host: str) -> bool:
    """Transfer one locked export, validate it, then publish one generation pointer.

    Concurrent transfers use separate private directories. Only publication is
    serialized; a failed refresh leaves the previous complete generation active.
    """
    dest_dir = mirror_dir()
    dest_dir.mkdir(parents=True, exist_ok=True)
    try:
        with tempfile.TemporaryDirectory(dir=dest_dir, prefix=".refresh-") as temporary:
            archive = Path(temporary) / "snapshot.tar"
            _receive_snapshot(host, archive)
            staging = Path(temporary) / "snapshot"
            unpack_snapshot(archive, staging)
            manifest = publish_snapshot(staging, dest_dir)
        logger.info("Mirrored complete generation %s", manifest["generation"])
        return True
    except (OSError, RuntimeError, ValueError, TypeError, tarfile.TarError, subprocess.TimeoutExpired) as exc:
        logger.warning("Mirror snapshot refresh failed: %s", exc)
        return False


class Backend:
    """Owned child with bounded queued writes and interruptible pipe workers.

    send() only queues bytes; it never blocks while the proxy's state lock is
    held. The reader owns the one exit callback, including decode/I/O failure.
    """

    def __init__(self, cmd: list[str], env: dict[str, str] | None, gen: int, proxy: "FailoverProxy"):
        self.gen = gen
        self._proxy = proxy
        self._stop = threading.Event()
        self._close_lock = threading.Lock()
        self._queue_lock = threading.Lock()
        self._queued_bytes = 0
        self._writes = queue.Queue(maxsize=64)
        self.proc = subprocess.Popen(cmd, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                     env=env, bufsize=0)
        assert self.proc.stdin is not None and self.proc.stdout is not None
        os.set_blocking(self.proc.stdin.fileno(), False)
        os.set_blocking(self.proc.stdout.fileno(), False)
        self._writer = threading.Thread(target=self._write, daemon=True)
        self._reader = threading.Thread(target=self._read, daemon=True)
        self._writer.start()
        self._reader.start()

    def _read(self):
        pending = bytearray()
        try:
            fd = self.proc.stdout.fileno()
            while not self._stop.is_set():
                readable, _, _ = select.select([fd], [], [], 0.1)
                if not readable:
                    continue
                chunk = os.read(fd, 65536)
                if not chunk:
                    if pending:
                        self._proxy.on_backend_line(self.gen, pending.decode("utf-8"))
                    break
                pending.extend(chunk)
                while True:
                    end = pending.find(b"\n")
                    if end < 0:
                        break
                    if end + 1 > MAX_LINE_BYTES:
                        raise ValueError("Backend line exceeds input limit")
                    line = bytes(pending[:end + 1]).decode("utf-8")
                    del pending[:end + 1]
                    self._proxy.on_backend_line(self.gen, line)
                if len(pending) > MAX_LINE_BYTES:
                    raise ValueError("Backend line exceeds input limit")
        except (OSError, ValueError, RecursionError) as exc:
            if not self._stop.is_set():
                logger.warning("Backend read failed (%s)", type(exc).__name__)
        finally:
            self._shutdown()
            self._proxy.on_backend_exit(self.gen)

    def _write(self):
        try:
            fd = self.proc.stdin.fileno()
            while not self._stop.is_set():
                try:
                    payload = self._writes.get(timeout=0.1)
                except queue.Empty:
                    continue
                with self._queue_lock:
                    self._queued_bytes -= len(payload)
                remaining = memoryview(payload)
                deadline = time.monotonic() + max(0.1, self._proxy.request_timeout)
                while remaining and not self._stop.is_set():
                    if time.monotonic() >= deadline:
                        raise TimeoutError("Backend pipe write timed out")
                    _, writable, _ = select.select([], [fd], [], 0.1)
                    if not writable:
                        continue
                    try:
                        written = os.write(fd, remaining)
                    except BlockingIOError:
                        continue
                    remaining = remaining[written:]
        except (OSError, ValueError) as exc:
            if not self._stop.is_set():
                logger.warning("Backend write failed (%s)", type(exc).__name__)
                try:
                    self.proc.kill()
                except OSError:
                    pass

    def send(self, line: str) -> bool:
        if self._stop.is_set():
            return False
        payload = (line if line.endswith("\n") else line + "\n").encode("utf-8")
        with self._queue_lock:
            if len(payload) > MAX_LINE_BYTES or self._queued_bytes + len(payload) > 2 * MAX_LINE_BYTES:
                return False
            try:
                self._writes.put_nowait(payload)
            except queue.Full:
                return False
            self._queued_bytes += len(payload)
        return True

    def _shutdown(self):
        with self._close_lock:
            self._stop.set()
            if threading.current_thread() is not self._writer:
                self._writer.join(timeout=0.5)
            if self.proc.stdin and not self.proc.stdin.closed:
                self.proc.stdin.close()
            try:
                self.proc.wait(timeout=1)
            except subprocess.TimeoutExpired:
                self.proc.kill()
                self.proc.wait(timeout=1)
            if self.proc.stdout and not self.proc.stdout.closed:
                self.proc.stdout.close()

    def close(self):
        self._shutdown()
        if threading.current_thread() is not self._reader:
            self._reader.join(timeout=1)


def _id_key(msg_id: Any) -> str:
    return json.dumps(msg_id, sort_keys=True)


class FailoverProxy:
    def __init__(self, primary: list[str] | None, fallback: list[str] | Callable[[], list[str]],
                 fallback_env: dict[str, str] | None = None, stdout=None,
                 note_fn=None):
        self.primary = primary
        self.fallback = fallback
        self.fallback_env = fallback_env
        self.stdout = stdout or sys.stdout
        self._local_pyramid: Path | None = None
        self.note_fn = note_fn or (lambda: describe_mirror_snapshot(self._local_pyramid))
        self.lock = threading.RLock()
        self.out_lock = threading.Lock()
        self.pending: dict[str, tuple[str, str, float]] = {}  # id -> (line, method, sent_at)
        self.replay_ids: set[str] = set()
        self.init_line: str | None = None
        self.init_key: str | None = None
        self.initialized_seen = False
        self.gen = 0
        self.mode = "none"
        self.local_restarts = 0
        self.backend: Backend | None = None
        self.closing = False
        self.request_timeout = float(os.environ.get("NAPMEM_REMOTE_REQUEST_TIMEOUT", "60"))

    # --- lifecycle ---------------------------------------------------------

    def start(self, use_primary: bool):
        with self.lock:
            if use_primary and self.primary:
                self._spawn("remote")
            else:
                self._spawn("local")
            if self.backend is None:
                self._failover()
        threading.Thread(target=self._watchdog, daemon=True).start()

    def _watchdog(self):
        """A remote that is alive but silent (hung server, wedged ssh) never
        hits EOF. Kill it once a request waits past request_timeout; the
        reader thread then sees EOF and triggers the normal failover."""
        while not self.closing:
            time.sleep(WATCHDOG_TICK_S)
            with self.lock:
                if self.mode != "remote" or not self.pending or self.backend is None:
                    continue
                oldest = min(sent for _l, _m, sent in self.pending.values())
                if time.monotonic() - oldest < self.request_timeout:
                    continue
                logger.warning("Remote request unanswered for %.0fs; treating remote as hung",
                               self.request_timeout)
                proc = self.backend.proc
            try:
                proc.kill()
            except OSError:
                pass  # Reader may have already reaped this generation.

    def _spawn(self, mode: str):
        self.gen += 1
        self.mode = mode
        cmd, env = (self.primary, None) if mode == "remote" else (self.fallback, self.fallback_env)
        try:
            cmd = cmd() if callable(cmd) else cmd
        except (OSError, ValueError) as exc:
            logger.error("Cannot resolve %s backend snapshot: %s", mode, exc)
            self.backend = None
            return
        if mode == "local" and "--pyramid" in cmd:
            self._local_pyramid = Path(cmd[cmd.index("--pyramid") + 1])
        logger.info("Starting %s backend: %s", mode, " ".join(cmd[:2]) + " ...")
        try:
            self.backend = Backend(cmd, env, self.gen, self)
        except OSError as exc:
            logger.error("Cannot start %s backend: %s", mode, exc)
            self.backend = None

    def _failover(self):
        """Called with self.lock held after the current backend died."""
        if self.closing:
            return
        if self.mode == "remote":
            logger.warning("Remote napmem backend lost; failing over to local mirror")
        elif self.local_restarts < MAX_LOCAL_RESTARTS:
            self.local_restarts += 1
            logger.warning("Local backend died; restart %d/%d",
                           self.local_restarts, MAX_LOCAL_RESTARTS)
        else:
            logger.error("Local backend keeps dying; answering with errors")
            self.backend = None
            self.mode = "dead"
            self._fail_pending("napmem backend unavailable (remote and local both failed)")
            return
        self._spawn("local")
        if self.backend is None:
            self.mode = "dead"
            self._fail_pending("napmem local fallback could not start")
            return
        # Replay the handshake unless the client's own initialize is still in
        # flight (it gets resent with the rest of pending below).
        if self.init_line and self.init_key not in self.pending:
            msg = json.loads(self.init_line)
            msg["id"] = REPLAY_INIT_ID
            self.replay_ids.add(_id_key(REPLAY_INIT_ID))
            self.backend.send(json.dumps(msg))
            if self.initialized_seen:
                self.backend.send(json.dumps({"jsonrpc": "2.0",
                                              "method": "notifications/initialized"}))
        for line, _method, _sent in list(self.pending.values()):
            if not self.backend.send(line):
                # Let the reader report one exit and retry/fail the pending set.
                self.backend.proc.kill()
                break

    def on_backend_exit(self, gen: int):
        with self.lock:
            if gen == self.gen:
                self._failover()

    def close(self):
        with self.lock:
            self.closing = True
            backend = self.backend
        if backend:
            backend.close()

    # --- relay -------------------------------------------------------------

    def _emit(self, obj_or_line):
        obj = json.loads(obj_or_line) if isinstance(obj_or_line, str) else obj_or_line
        line = wire_json(limit_wire_response(obj))
        with self.out_lock:
            binary = getattr(self.stdout, "buffer", None)
            if binary is not None:
                binary.write(line.encode("utf-8"))
                binary.flush()
            else:
                self.stdout.write(line)
                self.stdout.flush()

    def _fail_pending(self, message: str):
        for key, (line, _m, _s) in list(self.pending.items()):
            self.pending.pop(key, None)
            try:
                msg_id = json.loads(line).get("id")
            except (json.JSONDecodeError, AttributeError):
                msg_id = None
            self._emit({"jsonrpc": "2.0", "id": msg_id,
                        "error": {"code": -32603, "message": message}})

    def on_client_line(self, line: str):
        stripped = line.strip()
        if not stripped:
            return
        try:
            msg = json.loads(stripped)
        except (ValueError, RecursionError):
            msg = None
        if isinstance(msg, dict) and "id" in msg:
            msg_id = msg["id"]
            if not valid_request_id(msg_id):
                # The backend answers invalid IDs with null, which cannot
                # clear a pending entry keyed by the original invalid value.
                self._emit({"jsonrpc": "2.0", "id": None,
                            "error": {"code": -32600, "message": "Invalid Request"}})
                return
            if msg.get("method") == "tools/call":
                params = msg.get("params", {})
                arguments = params.get("arguments", {}) if isinstance(params, dict) else {}
                maximum, tokens = tool_budgets(arguments if isinstance(arguments, dict) else {})
                if not response_budget_fits_id(msg_id, maximum, tokens):
                    self._emit(budget_request_error(msg_id))
                    return
        dead = None
        with self.lock:
            if isinstance(msg, dict):
                method = msg.get("method")
                if "id" in msg and isinstance(method, str):
                    key = _id_key(msg["id"])
                    self.pending[key] = (stripped, method, time.monotonic())
                    if method == "initialize":
                        self.init_line, self.init_key = stripped, key
                elif method == "notifications/initialized":
                    self.initialized_seen = True
            if self.backend is None:
                if isinstance(msg, dict) and "id" in msg:
                    self._fail_pending("napmem backend unavailable")
                return
            if not self.backend.send(stripped):
                # Reader thread will also see EOF; bump gen so it no-ops.
                dead = self.backend
                self.gen += 1
                self._failover()
        if dead is not None:
            dead.close()

    def on_backend_line(self, gen: int, line: str):
        stripped = line.strip()
        if not stripped:
            return
        with self.lock:
            if gen != self.gen:
                return
            try:
                msg = json.loads(stripped)
            except (ValueError, RecursionError) as exc:
                raise ValueError("Invalid backend JSON") from exc
            method = None
            request = None
            if isinstance(msg, dict) and "id" in msg and "method" not in msg:
                key = _id_key(msg["id"])
                if key in self.replay_ids:
                    self.replay_ids.discard(key)
                    return
                entry = self.pending.pop(key, None)
                method = entry[1] if entry else None
                request = json.loads(entry[0]) if entry else None
            if method == "tools/call" and isinstance(msg, dict):
                params = request.get("params", {}) if isinstance(request, dict) else {}
                arguments = params.get("arguments", {}) if isinstance(params, dict) else {}
                maximum, tokens = tool_budgets(arguments if isinstance(arguments, dict) else {})
                result = msg.get("result")
                if isinstance(result, dict) and isinstance(result.get("content"), list):
                    payload = result.get("structuredContent")
                    if not isinstance(payload, dict):
                        first = result["content"][0] if result["content"] else {}
                        text = first.get("text", "") if isinstance(first, dict) else ""
                        try:
                            payload = json.loads(text)
                        except (ValueError, TypeError):
                            payload = {"legacy_text": text}
                        if not isinstance(payload, dict):
                            payload = {"legacy_value": payload}
                    extras = result["content"][1:]
                    failed = result.get("isError") is True or "error" in payload
                    if failed:
                        # Older backends may expose exception text in content.
                        # The proxy preserves failure status, never that body.
                        supplied = payload.get("error", {})
                        code = supplied.get("code") if isinstance(supplied, dict) else None
                        messages = {"INVALID_TOOL_ARGUMENTS": "Unknown tool or invalid tool arguments",
                                    "MEMORY_UNAVAILABLE": "Requested memory is unavailable"}
                        code = code if code in messages else "TOOL_FAILED"
                        payload = {"error": {"code": code, "message": messages.get(code, "Memory tool could not complete")}}
                        extras = []
                    if self.mode == "local":
                        payload = dict(payload)
                        age = mirror_age_s(self._local_pyramid) if self._local_pyramid else None
                        metadata = {"mode": "local_mirror", "snapshot_age_seconds": age,
                                    "generation": None, "verification": "unavailable"}
                        try:
                            if self._local_pyramid is None:
                                raise ValueError("Custom backend has no mirror snapshot path")
                            snapshot = load_snapshot(self._local_pyramid.parent)
                            metadata.update(generation=snapshot["manifest"]["generation"],
                                            verification=snapshot["verification"]["status"],
                                            generation_verification=snapshot["verification"]["generation"])
                        except (OSError, ValueError, TypeError):
                            pass
                        payload["fallback"] = metadata
                        note = str(self.note_fn())[:1024]
                        extras = [*extras, {"type": "text", "text": (
                            "[napmem fallback] Remote napmem server is unreachable; this "
                            f"answer came from the local mirror ({note}).")}]
                    msg = bounded_tool_result(msg["id"], payload, max_bytes=maximum, max_tokens=tokens,
                                              extra_content=extras, is_error=failed)
                else:
                    if isinstance(msg.get("error"), dict):
                        code = msg["error"].get("code")
                        if isinstance(code, bool) or not isinstance(code, int) or not -(2**31) <= code < 2**31:
                            code = -32603
                        messages = {-32700: "Parse error", -32600: "Invalid Request", -32601: "Method not found",
                                    -32602: "Invalid params", -32603: "Internal error",
                                    -32001: "Response budget too small for metadata"}
                        msg = {"jsonrpc": "2.0", "id": msg.get("id"), "error": {
                            "code": code, "message": messages.get(code, "Backend request failed")}}
                    msg = limit_wire_response(msg, max_bytes=maximum, max_tokens=tokens)
                self._emit(msg)
                return
        self._emit(msg)

    def serve(self, stdin=None):
        stdin = stdin or sys.stdin
        try:
            for line in bounded_lines(stdin):
                if line is None:
                    self._emit({"jsonrpc": "2.0", "id": None,
                                "error": {"code": -32700, "message": "Invalid input line"}})
                else:
                    self.on_client_line(line)
        finally:
            self.close()


def status() -> int:
    host = remote_host()
    print(f"remote host : {host or '(not configured -> local only)'}")
    if host:
        print(f"reachable   : {probe_remote(host)}")
    print(f"mirror      : {mirror_pyramid()} ({describe_mirror_snapshot()})")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="NapMem MCP proxy: remote SSH with local-mirror fallback.")
    parser.add_argument("--sync-mirror", action="store_true", help="refresh the local mirror and exit")
    parser.add_argument("--status", action="store_true", help="print remote/mirror status and exit")
    args = parser.parse_args()

    logging.basicConfig(stream=sys.stderr, level=logging.INFO,
                        format="%(asctime)s [%(name)s] %(levelname)s: %(message)s")
    if args.status:
        return status()
    host = remote_host()
    if args.sync_mirror:
        if not host:
            logger.error("No remote host configured (NAPMEM_REMOTE_HOST or %s)", HOST_FILE)
            return 2
        return 0 if sync_mirror(host) else 1

    reachable = bool(host) and probe_remote(host)
    if host and not reachable:
        logger.warning("Remote %s unreachable; serving local mirror (%s)",
                       host, describe_age(mirror_age_s()))
    if reachable:
        age = mirror_age_s()
        if age is None or age > float(os.environ.get("NAPMEM_MIRROR_MAX_AGE", "3600")):
            threading.Thread(target=sync_mirror, args=(host,), daemon=True).start()

    proxy = FailoverProxy(primary_cmd(host) if host else None, fallback_cmd, fallback_env())
    proxy.start(use_primary=reachable)
    proxy.serve()
    return 0


if __name__ == "__main__":
    sys.exit(main())
