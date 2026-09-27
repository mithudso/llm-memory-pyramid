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
import subprocess
import sys
import threading
import time
from pathlib import Path
from typing import Any

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
    return mirror_dir() / MIRROR_FILES[0]


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
    return [sys.executable, str(LOCAL_SERVER), "--pyramid", str(mirror_pyramid())]


def fallback_env() -> dict[str, str]:
    env = dict(os.environ)
    # Remote fleet hosts are likely down too when we are on the fallback;
    # embed on this box only. Same model as remote keeps the mirrored cache valid.
    env["NAPMEM_OLLAMA_URL"] = os.environ.get("NAPMEM_FALLBACK_OLLAMA", "http://127.0.0.1:11434")
    return env


def probe_remote(host: str) -> bool:
    timeout = float(os.environ.get("NAPMEM_SSH_TIMEOUT", "5"))
    try:
        proc = subprocess.run(ssh_base(host) + ["true"], stdin=subprocess.DEVNULL,
                              capture_output=True, timeout=timeout + 5, check=False)
    except (OSError, subprocess.TimeoutExpired):
        return False
    return proc.returncode == 0


def mirror_age_s() -> float | None:
    try:
        return time.time() - mirror_pyramid().stat().st_mtime
    except OSError:
        return None


def describe_age(age: float | None) -> str:
    if age is None:
        return "no mirror snapshot exists yet"
    if age < 3600:
        return f"snapshot is {int(age // 60)} min old"
    if age < 86400:
        return f"snapshot is {age / 3600:.1f} h old"
    return f"snapshot is {age / 86400:.1f} days old"


def sync_mirror(host: str) -> bool:
    """Copy the canonical pyramid (+ embedding cache) to the mirror dir.
    Each file lands via tmp + os.replace, so a reader never sees a torn file.
    The pyramid must parse as a JSON object before it replaces the old one."""
    dest_dir = mirror_dir()
    dest_dir.mkdir(parents=True, exist_ok=True)
    remote_dir = os.path.dirname(remote_pyramid()) or "."
    ok = True
    for name in MIRROR_FILES:
        dest = dest_dir / name
        tmp = dest_dir / f".{name}.tmp"
        src = f"{remote_dir}/{name}"
        try:
            with open(tmp, "wb") as out:
                proc = subprocess.run(ssh_base(host) + ["-C", f'cat "{src}"'],
                                      stdin=subprocess.DEVNULL, stdout=out,
                                      stderr=subprocess.PIPE, timeout=300, check=False)
            if proc.returncode != 0:
                raise RuntimeError(proc.stderr.decode("utf-8", "replace").strip()
                                   or f"ssh exit {proc.returncode}")
            if name == MIRROR_FILES[0]:
                with open(tmp, encoding="utf-8") as fh:
                    if not isinstance(json.load(fh), dict):
                        raise TypeError("pyramid is not a JSON object")
            os.replace(tmp, dest)
            logger.info("Mirrored %s (%d bytes)", name, dest.stat().st_size)
        except (OSError, RuntimeError, ValueError, TypeError, subprocess.TimeoutExpired) as exc:
            logger.warning("Mirror of %s failed: %s", name, exc)
            ok = ok and name != MIRROR_FILES[0]  # embindex is optional
            try:
                tmp.unlink()
            except OSError:
                pass
    return ok


class Backend:
    """One child MCP server process. A reader thread forwards each stdout line
    to the proxy and reports EOF exactly once."""

    def __init__(self, cmd: list[str], env: dict[str, str] | None, gen: int, proxy: "FailoverProxy"):
        self.gen = gen
        self.proc = subprocess.Popen(cmd, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                     env=env, text=True, encoding="utf-8", bufsize=1)
        self._proxy = proxy
        threading.Thread(target=self._read, daemon=True).start()

    def _read(self):
        assert self.proc.stdout is not None
        for line in self.proc.stdout:
            self._proxy.on_backend_line(self.gen, line)
        self.proc.wait()
        self._proxy.on_backend_exit(self.gen)

    def send(self, line: str) -> bool:
        try:
            assert self.proc.stdin is not None
            self.proc.stdin.write(line if line.endswith("\n") else line + "\n")
            self.proc.stdin.flush()
            return True
        except (BrokenPipeError, OSError, ValueError):
            return False

    def close(self):
        try:
            if self.proc.stdin:
                self.proc.stdin.close()
        except OSError:
            pass
        try:
            self.proc.wait(timeout=3)
        except subprocess.TimeoutExpired:
            self.proc.kill()


def _id_key(msg_id: Any) -> str:
    return json.dumps(msg_id, sort_keys=True)


class FailoverProxy:
    def __init__(self, primary: list[str] | None, fallback: list[str],
                 fallback_env: dict[str, str] | None = None, stdout=None,
                 note_fn=None):
        self.primary = primary
        self.fallback = fallback
        self.fallback_env = fallback_env
        self.stdout = stdout or sys.stdout
        self.note_fn = note_fn or (lambda: describe_age(mirror_age_s()))
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
            proc.kill()

    def _spawn(self, mode: str):
        self.gen += 1
        self.mode = mode
        cmd, env = (self.primary, None) if mode == "remote" else (self.fallback, self.fallback_env)
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
            self.backend.send(line)

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
        line = obj_or_line if isinstance(obj_or_line, str) else json.dumps(obj_or_line)
        with self.out_lock:
            self.stdout.write(line if line.endswith("\n") else line + "\n")
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
        except json.JSONDecodeError:
            msg = None
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
            except json.JSONDecodeError:
                msg = None
            method = None
            if isinstance(msg, dict) and "id" in msg and "method" not in msg:
                key = _id_key(msg["id"])
                if key in self.replay_ids:
                    self.replay_ids.discard(key)
                    return
                entry = self.pending.pop(key, None)
                method = entry[1] if entry else None
            if (self.mode == "local" and method == "tools/call" and isinstance(msg, dict)
                    and isinstance(msg.get("result"), dict)
                    and isinstance(msg["result"].get("content"), list)):
                msg["result"]["content"].append({
                    "type": "text",
                    "text": ("[napmem fallback] Remote napmem server is unreachable; this "
                             f"answer came from the local mirror ({self.note_fn()})."),
                })
                self._emit(msg)
                return
        self._emit(stripped)

    def serve(self, stdin=None):
        stdin = stdin or sys.stdin
        try:
            for line in stdin:
                self.on_client_line(line)
        finally:
            self.close()


def status() -> int:
    host = remote_host()
    print(f"remote host : {host or '(not configured -> local only)'}")
    if host:
        print(f"reachable   : {probe_remote(host)}")
    print(f"mirror      : {mirror_pyramid()} ({describe_age(mirror_age_s())})")
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

    proxy = FailoverProxy(primary_cmd(host) if host else None, fallback_cmd(), fallback_env())
    proxy.start(use_primary=reachable)
    proxy.serve()
    return 0


if __name__ == "__main__":
    sys.exit(main())
