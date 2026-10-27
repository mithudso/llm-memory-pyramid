"""
Tests for napmem_mcp_failover.py — the remote-SSH / local-mirror MCP proxy.

The "remote" backend is a tiny fake MCP server run as a subprocess, so no
SSH or network is involved. The local fallback is the real
napmem_mcp_server.py reading a throwaway pyramid.
"""

import json
import os
import shutil
import sys
import tempfile
import threading
import unittest
from unittest import mock

import napmem_mcp_failover as fo
from memory_pyramid_distiller import MemoryPyramidDistiller

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
SERVER = os.path.join(BASE_DIR, "napmem_mcp_server.py")

# Fake remote: answers initialize, then dies on the first tools/call without
# answering it (a dropped SSH link mid-request).
FAKE_REMOTE_DIES_ON_CALL = r"""
import json, sys
for line in sys.stdin:
    msg = json.loads(line)
    if msg.get("method") == "initialize":
        print(json.dumps({"jsonrpc": "2.0", "id": msg["id"], "result": {
            "protocolVersion": "2025-06-18", "capabilities": {"tools": {}},
            "serverInfo": {"name": "fake-remote", "version": "0"}}}), flush=True)
    elif msg.get("method") == "tools/call":
        sys.exit(1)
"""

# Fake remote that stays alive but never answers tools/call (hung server).
FAKE_REMOTE_HANGS_ON_CALL = FAKE_REMOTE_DIES_ON_CALL.replace(
    "sys.exit(1)", "import time; time.sleep(600)")

# The production server is deliberately permissive about lifecycle ordering.
# This backend makes the proxy's handshake replay observable to the test.
STRICT_FALLBACK = r"""
import json, sys
initialized = False
initializing = False
for line in sys.stdin:
    msg = json.loads(line)
    method = msg.get("method")
    if method == "initialize":
        initializing = True
        print(json.dumps({"jsonrpc":"2.0", "id":msg["id"], "result":{
            "protocolVersion":"2025-06-18", "capabilities":{},
            "serverInfo":{"name":"strict-fallback", "version":"0"}}}), flush=True)
    elif method == "notifications/initialized":
        initialized = initializing
    elif method == "tools/call":
        print(json.dumps({"jsonrpc":"2.0", "id":msg["id"], "result":{
            "isError": not initialized,
            "content":[{"type":"text", "text":"ready" if initialized else "missing handshake"}]}}), flush=True)
"""


class CaptureOut:
    """Thread-safe stdout stand-in; wait_for() blocks until N messages arrive."""

    def __init__(self):
        self.buf = ""
        self.cond = threading.Condition()

    def write(self, s):
        with self.cond:
            self.buf += s
            self.cond.notify_all()

    def flush(self):
        pass

    def messages(self):
        return [json.loads(line) for line in self.buf.splitlines() if line.strip()]

    def wait_for(self, n, timeout=15):
        with self.cond:
            self.cond.wait_for(lambda: len(self.messages()) >= n, timeout=timeout)
        return self.messages()


class TestFailoverProxy(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.pyramid = os.path.join(self.tmp, "napmem_pyramid.json")
        MemoryPyramidDistiller(pyramid_path=self.pyramid).ingest_session(
            "sess_a", "A", "a.md", "# Notes\n- The failover proxy serves the local mirror.\n")
        self.fallback = [sys.executable, SERVER, "--pyramid", self.pyramid]
        self.env = dict(os.environ, NAPMEM_EMBED_BACKEND="hashed")

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _proxy(self, primary):
        out = CaptureOut()
        proxy = fo.FailoverProxy(primary, self.fallback, self.env, stdout=out,
                                 note_fn=lambda: "test snapshot")
        return proxy, out

    @staticmethod
    def _req(msg_id, method, params=None):
        return json.dumps({"jsonrpc": "2.0", "id": msg_id, "method": method,
                           "params": params or {}})

    def test_mid_session_failover_replays_handshake_and_pending_call(self):
        proxy, out = self._proxy([sys.executable, "-c", FAKE_REMOTE_DIES_ON_CALL])
        proxy.fallback = [sys.executable, "-c", STRICT_FALLBACK]
        proxy.start(use_primary=True)
        try:
            proxy.on_client_line(self._req(1, "initialize", {"protocolVersion": "2025-06-18"}))
            msgs = out.wait_for(1)
            self.assertEqual(msgs[0]["result"]["serverInfo"]["name"], "fake-remote")
            proxy.on_client_line(json.dumps({"jsonrpc": "2.0",
                                             "method": "notifications/initialized"}))
            proxy.on_client_line(self._req(2, "tools/call",
                                           {"name": "memory_stats", "arguments": {}}))
            msgs = out.wait_for(2)
        finally:
            proxy.close()
        # Exactly one initialize response reached the client: the replayed
        # handshake's response is swallowed.
        self.assertEqual([m["id"] for m in msgs], [1, 2])
        self.assertEqual(proxy.mode, "local")
        content = msgs[1]["result"]["content"]
        self.assertFalse(msgs[1]["result"]["isError"])
        self.assertIn("[napmem fallback]", content[-1]["text"])
        self.assertIn("test snapshot", content[-1]["text"])
        self.assertEqual(json.loads(content[0]["text"])["legacy_text"], "ready")
        self.assertEqual(json.loads(content[0]["text"]), msgs[1]["result"]["structuredContent"])

    def test_invalid_utf8_backend_fails_over_and_logs(self):
        remote = "import sys,os; sys.stdin.readline(); os.write(1,b'\\xff\\n')"
        proxy, out = self._proxy([sys.executable, "-c", remote])
        proxy.start(use_primary=True)
        try:
            with self.assertLogs(fo.logger, level="WARNING") as logs:
                proxy.on_client_line(self._req(1, "initialize"))
                messages = out.wait_for(1, timeout=3)
            self.assertEqual(messages[0]["result"]["serverInfo"]["name"], "napmem")
            self.assertEqual(proxy.mode, "local")
            self.assertTrue(any("read failed" in message for message in logs.output))
        finally:
            proxy.close()

    def test_nonreading_backend_cannot_block_relay_or_watchdog(self):
        proxy, out = self._proxy([sys.executable, "-c", "import time; time.sleep(600)"])
        proxy.request_timeout = 0.1
        with mock.patch.object(fo, "WATCHDOG_TICK_S", 0.02):
            proxy.start(use_primary=True)
            remote = proxy.backend.proc
            sender = threading.Thread(target=proxy.on_client_line, args=(
                self._req(1, "initialize", {"padding": "x" * 200000}),), daemon=True)
            try:
                sender.start()
                sender.join(timeout=1)
                self.assertFalse(sender.is_alive(), "Pipe writes blocked the state lock")
                messages = out.wait_for(1, timeout=3)
                self.assertEqual(messages[0]["id"], 1)
                self.assertIn("result", messages[0])
                self.assertEqual(proxy.mode, "local")
            finally:
                # Kill only this test's child, including on an unfixed baseline
                # where close() would otherwise wait on the sender's state lock.
                if remote.poll() is None:
                    remote.kill()
                sender.join(timeout=3)
                proxy.close()

    def test_close_reaps_child_and_closes_both_pipes(self):
        proxy, out = self._proxy(None)
        proxy.start(use_primary=False)
        backend = proxy.backend
        try:
            proxy.on_client_line(self._req(1, "initialize"))
            self.assertEqual(out.wait_for(1, timeout=3)[0]["id"], 1)
        finally:
            proxy.close()
        self.assertIsNotNone(backend.proc.poll())
        self.assertTrue(backend.proc.stdin.closed)
        self.assertTrue(backend.proc.stdout.closed)

    def test_failed_remote_spawn_uses_local_fallback(self):
        proxy, out = self._proxy([os.path.join(self.tmp, "nonexistent-executable")])
        proxy.start(use_primary=True)
        try:
            proxy.on_client_line(self._req(1, "initialize"))
            messages = out.wait_for(1, timeout=3)
            self.assertEqual(messages[0]["result"]["serverInfo"]["name"], "napmem")
        finally:
            proxy.close()

    def test_hung_remote_is_killed_and_request_served_locally(self):
        proxy, out = self._proxy([sys.executable, "-c", FAKE_REMOTE_HANGS_ON_CALL])
        proxy.request_timeout = 1.0
        proxy.start(use_primary=True)
        try:
            proxy.on_client_line(self._req(1, "initialize"))
            out.wait_for(1)
            proxy.on_client_line(self._req(2, "tools/call",
                                           {"name": "memory_stats", "arguments": {}}))
            msgs = out.wait_for(2)
        finally:
            proxy.close()
        self.assertEqual([m["id"] for m in msgs], [1, 2])
        self.assertEqual(proxy.mode, "local")
        self.assertIn("[napmem fallback]", msgs[1]["result"]["content"][-1]["text"])

    def test_remote_dead_before_initialize_answer_resends_client_initialize(self):
        proxy, out = self._proxy([sys.executable, "-c", "import sys; sys.exit(3)"])
        proxy.start(use_primary=True)
        try:
            proxy.on_client_line(self._req(7, "initialize", {"protocolVersion": "2025-06-18"}))
            msgs = out.wait_for(1)
            proxy.on_client_line(self._req(8, "tools/list"))
            msgs = out.wait_for(2)
        finally:
            proxy.close()
        self.assertEqual([m["id"] for m in msgs], [7, 8])
        self.assertEqual(msgs[0]["result"]["serverInfo"]["name"], "napmem")
        names = {t["name"] for t in msgs[1]["result"]["tools"]}
        self.assertIn("search_memory", names)

    def test_start_local_when_remote_unreachable(self):
        proxy, out = self._proxy(None)
        proxy.start(use_primary=False)
        try:
            proxy.on_client_line(self._req(1, "initialize"))
            proxy.on_client_line(self._req(2, "tools/call", {
                "name": "search_memory", "arguments": {"query": "failover"}}))
            msgs = out.wait_for(2)
        finally:
            proxy.close()
        self.assertEqual(proxy.mode, "local")
        self.assertIn("failover proxy", msgs[1]["result"]["content"][0]["text"])
        self.assertIn("[napmem fallback]", msgs[1]["result"]["content"][-1]["text"])

    def test_both_backends_dead_answers_errors_not_hang(self):
        proxy, out = self._proxy([sys.executable, "-c", "import sys; sys.exit(1)"])
        proxy.fallback = [sys.executable, "-c", "import sys; sys.exit(1)"]
        proxy.start(use_primary=True)
        try:
            proxy.on_client_line(self._req(1, "initialize"))
            msgs = out.wait_for(1)
        finally:
            proxy.close()
        self.assertEqual(msgs[0]["id"], 1)
        self.assertIn("unavailable", msgs[0]["error"]["message"])


class TestMirrorSync(unittest.TestCase):
    """Run the real exporter through a local subprocess, without any host contact."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.remote = os.path.join(self.tmp, "remote")
        self.mirror = os.path.join(self.tmp, "mirror")
        os.makedirs(self.remote)
        self.env = mock.patch.dict(os.environ, {
            "NAPMEM_REMOTE_PYRAMID": os.path.join(self.remote, "napmem_pyramid.json"),
            "NAPMEM_MIRROR_DIR": self.mirror,
        })
        self.env.start()
        self.ssh = mock.patch.object(fo, "remote_snapshot_cmd", lambda host: [
            sys.executable, str(fo.HERE / "napmem_snapshots.py"), "export-archive",
            "--pyramid", fo.remote_pyramid()])
        self.ssh.start()

    def tearDown(self):
        self.ssh.stop()
        self.env.stop()
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _write_remote(self, name, text):
        with open(os.path.join(self.remote, name), "w", encoding="utf-8") as fh:
            fh.write(text)

    def test_sync_copies_pyramid_and_embindex(self):
        self._write_remote("napmem_pyramid.json", json.dumps({"memory_records": [], "generation": 5}))
        self._write_remote("napmem_pyramid.json.embindex.json", json.dumps({"model": "m", "vectors": {}}))
        self.assertTrue(fo.sync_mirror("fake"))
        with open(fo.mirror_pyramid(), encoding="utf-8") as fh:
            self.assertEqual(json.load(fh), {"memory_records": [], "generation": 5})
        self.assertTrue(fo.mirror_pyramid().with_name(fo.MIRROR_FILES[1]).exists())
        self.assertIn(str(fo.mirror_pyramid()), fo.fallback_cmd())
        description = fo.describe_mirror_snapshot()
        self.assertIn("generation 5 (verified)", description)
        self.assertIn("record-text-hashes-only", description)

    def test_corrupt_remote_pyramid_keeps_old_mirror(self):
        os.makedirs(self.mirror)
        good = os.path.join(self.mirror, "napmem_pyramid.json")
        with open(good, "w", encoding="utf-8") as fh:
            json.dump({"layer_1": ["old"]}, fh)
        self._write_remote("napmem_pyramid.json", '{"layer_1": [')  # truncated
        self.assertFalse(fo.sync_mirror("fake"))
        with open(good, encoding="utf-8") as fh:
            self.assertEqual(json.load(fh), {"layer_1": ["old"]})
        self.assertFalse([n for n in os.listdir(self.mirror) if n.startswith(".refresh-")])

    def test_missing_embindex_is_not_fatal(self):
        self._write_remote("napmem_pyramid.json", json.dumps({}))
        self.assertTrue(fo.sync_mirror("fake"))
        self.assertFalse(fo.mirror_pyramid().with_name(fo.MIRROR_FILES[1]).exists())
        self.assertIn("cache absent", fo.describe_mirror_snapshot())

    def test_new_generation_without_cache_cannot_retain_previous_cache(self):
        self._write_remote("napmem_pyramid.json", json.dumps({"generation": 1}))
        self._write_remote("napmem_pyramid.json.embindex.json", json.dumps({"model": "m", "vectors": {}}))
        self.assertTrue(fo.sync_mirror("fake"))
        old_path = fo.mirror_pyramid()
        os.unlink(os.path.join(self.remote, fo.MIRROR_FILES[1]))
        self._write_remote("napmem_pyramid.json", json.dumps({"generation": 2}))
        self.assertTrue(fo.sync_mirror("fake"))
        self.assertNotEqual(fo.mirror_pyramid(), old_path)
        self.assertTrue(old_path.with_name(fo.MIRROR_FILES[1]).exists())
        self.assertFalse(fo.mirror_pyramid().with_name(fo.MIRROR_FILES[1]).exists())

    def test_configured_remote_basename_is_used_for_store_and_cache(self):
        self._write_remote("custom.json", json.dumps({"memory_records": [], "generation": 3}))
        self._write_remote("custom.json.embindex.json", json.dumps({"model": "custom", "vectors": {}}))
        with mock.patch.dict(os.environ, {
            "NAPMEM_REMOTE_PYRAMID": os.path.join(self.remote, "custom.json"),
        }):
            self.assertTrue(fo.sync_mirror("fake"))
        with open(fo.mirror_pyramid(), encoding="utf-8") as fh:
            self.assertEqual(json.load(fh), {"memory_records": [], "generation": 3})
        with open(fo.mirror_pyramid().with_name(fo.MIRROR_FILES[1]), encoding="utf-8") as fh:
            self.assertEqual(json.load(fh), {"model": "custom", "vectors": {}})

    def test_concurrent_sync_never_publishes_another_writers_open_file(self):
        # A publishes while B has an open, incomplete transfer. Each transfer
        # must own its staging directory, and the pointer must select only A.
        self._write_remote("napmem_pyramid.json", json.dumps({"memory_records": []}))
        validated = threading.Event()
        second_open = threading.Event()
        published = threading.Event()
        release_second = threading.Event()
        publish = fo.publish_snapshot
        path_open = fo.Path.open
        results = {}
        failures = []

        def open_transfer(path, *args, **kwargs):
            stream = path_open(path, *args, **kwargs)
            if (threading.current_thread().name == "mirror-B" and path.name == "snapshot.tar"
                    and args and args[0] == "xb"):
                second_open.set()
                if not release_second.wait(timeout=3):
                    stream.close()
                    raise RuntimeError("test did not release second transfer")
            return stream

        def publish_after_second_open(src, dest):
            if threading.current_thread().name == "mirror-A":
                validated.set()
                if not second_open.wait(timeout=3):
                    raise RuntimeError("second test transfer did not start")
                result = publish(src, dest)
                published.set()
                return result
            return publish(src, dest)

        def run_sync():
            try:
                results[threading.current_thread().name] = fo.sync_mirror("fake")
            except Exception as exc:
                failures.append(exc)

        with mock.patch.object(fo.Path, "open", open_transfer), \
                mock.patch.object(fo, "publish_snapshot", side_effect=publish_after_second_open):
            first = threading.Thread(target=run_sync, name="mirror-A")
            second = threading.Thread(target=run_sync, name="mirror-B")
            try:
                first.start()
                self.assertTrue(validated.wait(timeout=3))
                second.start()
                self.assertTrue(published.wait(timeout=3))
                with open(fo.mirror_pyramid(), encoding="utf-8") as fh:
                    self.assertEqual(json.load(fh), {"memory_records": []})
            finally:
                release_second.set()
                first.join(timeout=3)
                if second.ident is not None:
                    second.join(timeout=3)
        self.assertFalse(first.is_alive())
        self.assertFalse(second.is_alive())
        self.assertEqual(failures, [])
        self.assertEqual(results, {"mirror-A": True, "mirror-B": True})

    def test_failed_publication_preserves_previous_active_generation(self):
        self._write_remote("napmem_pyramid.json", json.dumps({"generation": 1}))
        self.assertTrue(fo.sync_mirror("fake"))
        previous = fo.mirror_pyramid()
        with mock.patch("napmem_storage.atomic_write", side_effect=OSError("synthetic pointer failure")):
            self.assertFalse(fo.sync_mirror("fake"))
        self.assertEqual(fo.mirror_pyramid(), previous)
        self.assertFalse(list(fo.Path(self.mirror).glob(".refresh-*")))

    def test_bounded_transfer_and_invalid_archive_keep_previous_generation(self):
        self._write_remote("napmem_pyramid.json", json.dumps({"generation": 1}))
        self.assertTrue(fo.sync_mirror("fake"))
        previous = fo.mirror_pyramid()
        command = [sys.executable, "-c", "import sys;sys.stdout.buffer.write(b'x'*10000)"]
        with mock.patch.object(fo, "remote_snapshot_cmd", return_value=command), \
                mock.patch.object(fo, "MAX_ARCHIVE_BYTES", 32):
            self.assertFalse(fo.sync_mirror("fake"))
        command = [sys.executable, "-c", "print('invalid tar')"]
        with mock.patch.object(fo, "remote_snapshot_cmd", return_value=command):
            self.assertFalse(fo.sync_mirror("fake"))
        self.assertEqual(fo.mirror_pyramid(), previous)

    def test_transfer_timeout_and_bounded_error_output(self):
        destination = fo.Path(self.tmp) / "received.tar"
        command = [sys.executable, "-c", "import time;time.sleep(10)"]
        with mock.patch.object(fo, "remote_snapshot_cmd", return_value=command):
            with self.assertRaises(TimeoutError):
                fo._receive_snapshot("fake", destination, timeout=.05)
        destination.unlink()
        command = [sys.executable, "-c", "import sys;sys.stderr.write('x'*100000);sys.exit(1)"]
        with mock.patch.object(fo, "remote_snapshot_cmd", return_value=command):
            with self.assertRaises(RuntimeError) as failure:
                fo._receive_snapshot("fake", destination)
        self.assertLessEqual(len(str(failure.exception)), 16384)

    def test_legacy_flat_mirror_notes_generation_is_unverified(self):
        os.makedirs(self.mirror)
        with open(os.path.join(self.mirror, fo.MIRROR_FILES[0]), "w", encoding="utf-8") as stream:
            json.dump({"memory_records": []}, stream)
        self.assertEqual(fo.mirror_pyramid(), fo.Path(self.mirror) / fo.MIRROR_FILES[0])
        self.assertIn("generation 0 (unverified)", fo.describe_mirror_snapshot())
        self.assertIn("legacy-unverified", fo.describe_mirror_snapshot())


class TestRemoteHostConfig(unittest.TestCase):
    def test_fallback_environment_keeps_snapshot_cache_read_only(self):
        with mock.patch.dict(os.environ, {"NAPMEM_CACHE_READ_ONLY": "0", "NAPMEM_FALLBACK_OLLAMA": "http://offline.invalid"}):
            env = fo.fallback_env()
        self.assertEqual(env["NAPMEM_CACHE_READ_ONLY"], "1")
        self.assertEqual(env["NAPMEM_OLLAMA_URL"], "http://offline.invalid")

    def test_refresh_requests_one_authoritative_export_with_quoted_paths(self):
        with mock.patch.object(fo, "ssh_base", return_value=["fake-ssh", "fake-host"]), \
                mock.patch.dict(os.environ, {"NAPMEM_REMOTE_REPO": "$HOME/a repo", "NAPMEM_REMOTE_PYRAMID": "$HOME/a store.json"}):
            command = fo.remote_snapshot_cmd("fake-host")
        self.assertEqual(command[:3], ["fake-ssh", "-C", "fake-host"])
        self.assertIn("export-archive", command[-1])
        self.assertIn("napmem_snapshots", command[-1])
        self.assertIn("'$HOME/a store.json'", command[-1])
        self.assertNotIn("cat ", command[-1])

    def test_env_wins_then_host_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            host_file = os.path.join(tmp, "remote_host")
            with open(host_file, "w", encoding="utf-8") as fh:
                fh.write("me@filehost\n")
            with mock.patch.object(fo, "HOST_FILE", fo.Path(host_file)):
                with mock.patch.dict(os.environ, {"NAPMEM_REMOTE_HOST": "me@envhost"}):
                    self.assertEqual(fo.remote_host(), "me@envhost")
                with mock.patch.dict(os.environ, {"NAPMEM_REMOTE_HOST": ""}):
                    self.assertEqual(fo.remote_host(), "me@filehost")
            with mock.patch.object(fo, "HOST_FILE", fo.Path(tmp, "absent")), \
                    mock.patch.dict(os.environ, {"NAPMEM_REMOTE_HOST": ""}):
                self.assertIsNone(fo.remote_host())


if __name__ == "__main__":
    unittest.main()
