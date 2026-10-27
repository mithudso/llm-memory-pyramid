"""Single-host writer isolation, commit boundaries and stale-reader privacy."""
from concurrent.futures import ThreadPoolExecutor
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from memory_pyramid_distiller import MemoryPyramidDistiller
from napmem_retrieval_agent import NapMemRetrievalAgent
from napmem_storage import StoreConflict, StoreLockTimeout, atomic_write, read_snapshot, store_lock


class TransactionTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.path = str(Path(self.tmp.name) / "store.json")

    def test_missing_snapshot_does_not_create_a_directory(self):
        path = Path(self.tmp.name) / "absent" / "store.json"
        self.assertEqual(read_snapshot(path), (None, None))
        self.assertFalse(path.parent.exists())

    def test_implicit_scope_queue_is_visible_in_the_projects_status(self):
        from napmem_jobs import JobQueue
        from napmem_metrics import status_report
        store = MemoryPyramidDistiller(self.path)
        store.ingest_session("a", "A", "a.md", "Project preference", scope="project:a")
        job = JobQueue(self.path).enqueue(session_id="a", source_path="a.md", source_content="Project preference")
        self.assertEqual(job["scope"], "project:a")
        self.assertEqual(status_report(self.path, scope="project:a")["jobs"]["states"]["queued"], 1)

    def test_restore_preserves_current_forget_and_creates_a_new_generation(self):
        from napmem_snapshots import export_snapshot
        store = MemoryPyramidDistiller(self.path)
        store.ingest_session("a", "A", "a.md", "Secret preference", scope="project:a")
        identity = store.data["memory_records"][0]["id"]
        backup = str(Path(self.tmp.name) / "backup")
        export_snapshot(self.path, backup)
        store.control("forget", record_id=identity)
        generation = store.data["generation"]
        receipt = store.restore_snapshot(backup)
        self.assertEqual(receipt["generation"], generation + 1)
        self.assertEqual(store.data["memory_records"], [])
        store.ingest_session("a", "A", "a.md", "Secret preference", scope="project:a")
        self.assertEqual(store.data["memory_records"], [])

    def test_restore_retains_ids_and_newer_correction(self):
        from napmem_snapshots import export_snapshot
        store = MemoryPyramidDistiller(self.path)
        store.ingest_session("a", "A", "a.md", "Use Vim", scope="project:a")
        identity = store.data["memory_records"][0]["id"]
        backup = str(Path(self.tmp.name) / "backup")
        export_snapshot(self.path, backup)
        store.control("correct", record_id=identity, value="Use Emacs")
        store.restore_snapshot(backup)
        texts = {r["text"] for r in NapMemRetrievalAgent(self.path).query("Emacs", scope="project:a")["matches"]}
        self.assertEqual(texts, {"Use Emacs"})
        self.assertIn(identity, {r["id"] for r in store.data["memory_records"]})

    def test_restore_does_not_rescope_and_resurrect_forgotten_claim(self):
        from napmem_snapshots import export_snapshot
        store = MemoryPyramidDistiller(self.path)
        store.ingest_session("a", "A", "a.md", "Secret preference", scope="project:a")
        backup = str(Path(self.tmp.name) / "backup")
        export_snapshot(self.path, backup)
        store.control("forget", record_id=store.data["memory_records"][0]["id"])
        store.ingest_session("a", "A", "a.md", "Public preference", scope="project:b")
        store.restore_snapshot(backup)
        self.assertNotIn("Secret preference", str(store.data["memory_records"]))

    def test_missing_manifest_cannot_downgrade_a_verified_reader(self):
        from napmem_snapshots import export_snapshot
        store = MemoryPyramidDistiller(self.path)
        store.ingest_session("a", "A", "a.md", "Preference")
        backup = Path(self.tmp.name) / "backup"
        export_snapshot(self.path, backup)
        agent = NapMemRetrievalAgent(str(backup / "napmem_pyramid.json"))
        (backup / "manifest.json").unlink()
        with self.assertRaisesRegex(ValueError, "lost its manifest"):
            agent.query("Preference")

    def test_restore_retains_independent_same_text_in_another_project(self):
        from napmem_snapshots import export_snapshot
        store = MemoryPyramidDistiller(self.path)
        for session in ("a", "b"):
            store.ingest_session(session, session, session + ".md", "Same preference", scope="project:" + session)
        target = next(r["id"] for r in store.data["memory_records"] if r["scope"] == "project:a")
        backup = str(Path(self.tmp.name) / "backup")
        export_snapshot(self.path, backup)
        store.control("forget", record_id=target)
        store.restore_snapshot(backup)
        self.assertEqual([r["scope"] for r in store.data["memory_records"]], ["project:b"])

    def test_new_managed_snapshot_reader_requires_manifest(self):
        directory = Path(self.tmp.name) / "generations" / ("gen-1-" + "a" * 32)
        directory.mkdir(parents=True)
        path = directory / "napmem_pyramid.json"
        MemoryPyramidDistiller(str(path)).ingest_session("a", "A", "a.md", "Preference")
        with self.assertRaisesRegex(ValueError, "lost its manifest"):
            NapMemRetrievalAgent(str(path))

    def test_retry_purge_interleaving_cannot_restore_payload(self):
        from contextlib import contextmanager
        from napmem_jobs import JobQueue
        queue = JobQueue(self.path)
        job = queue.enqueue(session_id="a", source_path="a.md", source_content="Private source")
        queue.cancel(job["id"])
        original = queue._db
        injected = False
        @contextmanager
        def interleaved(**kwargs):
            nonlocal injected
            with original(**kwargs) as db:
                yield db
            if not injected:
                injected = True
                queue.purge(session_ids=["a"])
        with patch.object(queue, "_db", interleaved):
            queue.retry(job["id"], source_content="Private source")
        self.assertEqual(queue.get(job["id"])["state"], "cancelled")
        self.assertIsNone(queue.get(job["id"], include_payload=True)["source_text"])

    def test_forget_purges_only_affected_jobs_and_blocks_stale_cache_writer(self):
        from napmem_jobs import JobQueue
        from semantic_index import SemanticIndex, HashedTfBackend
        store = MemoryPyramidDistiller(self.path)
        store.ingest_session("a", "A", "a.md", "Secret preference")
        queue = JobQueue(self.path)
        job = queue.enqueue(session_id="a", source_path="a.md", source_content="Secret preference")
        other = queue.enqueue(session_id="b", source_path="b.md", source_content="Independent preference")
        index = SemanticIndex(self.path, backend=HashedTfBackend())
        receipt = store.control("forget", record_id=store.data["memory_records"][0]["id"])
        self.assertEqual(receipt["jobs"]["payloads_cleared"], 1)
        self.assertIsNone(queue.get(job["id"], include_payload=True)["source_text"])
        self.assertEqual(queue.get(other["id"])["state"], "queued")
        with self.assertRaisesRegex(ValueError, "forgotten claim"):
            queue.enqueue(session_id="a", source_path="a.md", source_content="- Secret preference")
        with self.assertRaises(StoreConflict):
            index.save()

    def test_semantic_snapshot_query_does_not_change_manifest_bytes(self):
        from napmem_snapshots import export_snapshot, load_snapshot
        store = MemoryPyramidDistiller(self.path)
        store.ingest_session("a", "A", "a.md", "Secret preference")
        backup = Path(self.tmp.name) / "backup"
        export_snapshot(self.path, backup)
        before = {p.name: p.read_bytes() for p in backup.iterdir()}
        NapMemRetrievalAgent(str(backup / "napmem_pyramid.json")).semantic_search("preference")
        self.assertEqual(before, {p.name: p.read_bytes() for p in backup.iterdir()})
        self.assertEqual(load_snapshot(backup)["verification"]["status"], "verified")

    def test_stale_instances_reload_for_ingestion_and_reject_direct_save(self):
        a, b = MemoryPyramidDistiller(self.path), MemoryPyramidDistiller(self.path)
        a.ingest_session("a", "A", "a.md", "Alpha record")
        with self.assertRaises(StoreConflict):
            b.save()
        b.ingest_session("b", "B", "b.md", "Beta record")
        loaded = MemoryPyramidDistiller(self.path)
        self.assertEqual({r["text"] for r in loaded.data["memory_records"]}, {"Alpha record", "Beta record"})
        self.assertEqual(loaded.data["generation"], 2)

    def test_external_change_does_not_discard_uncommitted_caller_edits(self):
        a, b = MemoryPyramidDistiller(self.path), MemoryPyramidDistiller(self.path)
        b.data["operator_note"] = "pending local edit"
        a.ingest_session("a", "A", "a.md", "Alpha")
        with self.assertRaises(StoreConflict):
            b.ingest_session("b", "B", "b.md", "Beta")
        self.assertEqual(b.data["operator_note"], "pending local edit")

    def test_failed_replace_keeps_disk_and_memory_at_prior_generation(self):
        store = MemoryPyramidDistiller(self.path)
        store.ingest_session("a", "A", "a.md", "Alpha")
        before = Path(self.path).read_bytes()
        memory = json.dumps(store.data, sort_keys=True)
        with patch("napmem_storage.os.replace", side_effect=OSError("synthetic replace failure")), self.assertRaises(OSError):
            store.ingest_session("b", "B", "b.md", "Beta")
        self.assertEqual(Path(self.path).read_bytes(), before)
        self.assertEqual(json.dumps(store.data, sort_keys=True), memory)
        self.assertEqual(list(Path(self.tmp.name).glob("*.tmp")), [])

    def test_nested_commit_is_not_undone_by_later_ack_failure(self):
        store = MemoryPyramidDistiller(self.path)
        with self.assertRaises(RuntimeError):
            with store.transaction():
                store.data["applied_jobs"] = {"job": {"source_sha256": "test"}}
                store.ingest_session("a", "A", "a.md", "Alpha")
                raise RuntimeError("queue acknowledgment failed after commit")
        self.assertIn("job", store.data["applied_jobs"])
        self.assertEqual(store.data, MemoryPyramidDistiller(self.path).data)

    def test_mocked_save_keeps_sequential_in_memory_ingests(self):
        store = MemoryPyramidDistiller(self.path)
        with patch.object(store, "save"):
            store.ingest_session("a", "A", "a.md", "Alpha")
            store.ingest_session("b", "B", "b.md", "Beta")
        self.assertEqual(len(store.data["memory_records"]), 2)

    def test_threads_and_processes_do_not_lose_updates(self):
        def write(number):
            MemoryPyramidDistiller(self.path).ingest_session(
                f"t{number}", "Thread", f"t{number}.md", f"Thread fact {number}")
        with ThreadPoolExecutor(max_workers=4) as pool:
            list(pool.map(write, range(8)))
        script = ("import sys; from memory_pyramid_distiller import MemoryPyramidDistiller; "
                  "n=sys.argv[2]; MemoryPyramidDistiller(sys.argv[1]).ingest_session('p'+n,'Process','p'+n+'.md','Process fact '+n)")
        env = {**os.environ, "NAPMEM_EMBED_BACKEND": "hashed"}
        children = [subprocess.Popen([sys.executable, "-c", script, self.path, str(n)],
                                     env=env, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
                    for n in range(4)]
        for child in children:
            _, error = child.communicate(timeout=15)
            self.assertEqual(child.returncode, 0, error.decode())
        loaded = MemoryPyramidDistiller(self.path)
        self.assertEqual(len(loaded.data["memory_records"]), 12)
        self.assertEqual(loaded.data["generation"], 12)

    def test_lock_is_reentrant_and_has_a_deadline_for_other_threads(self):
        with store_lock(self.path), store_lock(self.path):
            with ThreadPoolExecutor(max_workers=1) as pool:
                future = pool.submit(self._try_lock)
                with self.assertRaises(StoreLockTimeout):
                    future.result(timeout=2)
        self.assertTrue(Path(self.path + ".lock").exists())

    def _try_lock(self):
        with store_lock(self.path, timeout=.05):
            pass

    def test_invalid_generation_and_nonfinite_json_cannot_commit(self):
        store = MemoryPyramidDistiller(self.path)
        store.save()
        before = Path(self.path).read_bytes()
        store.data["generation"] = True
        with self.assertRaises(StoreConflict):
            store.save()
        with self.assertRaises(ValueError):
            atomic_write(self.path, {"value": float("nan")}, expected_fingerprint=read_snapshot(self.path)[1])
        self.assertEqual(Path(self.path).read_bytes(), before)

    def test_long_lived_reader_refreshes_after_forgetting(self):
        store = MemoryPyramidDistiller(self.path)
        store.ingest_session("a", "A", "a.md", "Remember blue widgets")
        agent = NapMemRetrievalAgent(self.path)
        self.assertTrue(agent.query("blue widgets")["matches"])
        store.control("forget", record_id=store.data["memory_records"][0]["id"])
        self.assertEqual(agent.query("blue widgets")["matches"], [])

    def test_removed_ids_are_never_reused_for_new_text(self):
        store = MemoryPyramidDistiller(self.path)
        store.ingest_session("a", "A", "a.md", "Original")
        rid = store.data["memory_records"][0]["id"]
        store.ingest_session("a", "A", "a.md", "# Empty")
        store.ingest_session("a", "A", "a.md", "Replacement")
        self.assertNotEqual(store.data["memory_records"][0]["id"], rid)
