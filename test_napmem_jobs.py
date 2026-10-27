"""Offline durable queue, lease, cloud-resume and atomic-commit tests."""

from concurrent.futures import ThreadPoolExecutor
import json
import os
from pathlib import Path
import sqlite3
import tempfile
import time
from types import SimpleNamespace as NS
import unittest
from unittest import mock

from memory_pyramid_distiller import MemoryPyramidDistiller
from napmem_jobs import JobQueue
from napmem_sources import SourceRegistry, read_source


class TestDurableJobs(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.source = self.root / "notes.md"
        self.content = "# Notes\n- User prefers quiet prompts.\n"
        self.source.write_text(self.content)
        self.pyramid = str(self.root / "store.json")
        self.queue = JobQueue(self.pyramid)

    def enqueue(self, **kwargs):
        values = {"session_id": "sess_notes", "source_path": str(self.source), "source_content": self.content}
        values.update(kwargs)
        return self.queue.enqueue(**values)

    def distiller(self):
        return MemoryPyramidDistiller(self.pyramid)

    def test_status_and_privacy_purge_of_absent_queue_create_nothing(self):
        self.assertEqual(self.queue.list(), [])
        self.assertIsNone(self.queue.get("missing"))
        self.assertEqual(self.queue.purge(session_ids=["sess_notes"])["matched"], 0)
        self.assertFalse(Path(self.queue.path).exists())

    def test_enqueue_idempotency_private_permissions_and_content_free_receipt(self):
        first, second = self.enqueue(), self.enqueue()
        self.assertEqual(first["id"], second["id"])
        self.assertTrue(first["enqueued"])
        self.assertFalse(second["enqueued"])
        self.assertEqual(os.stat(self.queue.path).st_mode & 0o777, 0o600)
        self.assertNotIn("quiet prompts", json.dumps(self.queue.receipt(first["id"])))
        with sqlite3.connect(self.queue.path) as db:
            self.assertEqual(db.execute("PRAGMA journal_mode").fetchone()[0], "delete")

    def test_expired_lease_can_resume_on_restart_and_retry_limit_clears_payload(self):
        job = self.enqueue(max_attempts=2)
        self.assertEqual(self.queue.claim("first", now=100, lease_seconds=10)["id"], job["id"])
        restarted = JobQueue(self.pyramid)
        self.assertIsNone(restarted.claim("second", now=105))
        self.assertEqual(restarted.claim("second", now=111, lease_seconds=10)["id"], job["id"])
        self.assertIsNone(restarted.claim("third", now=122))
        failed = restarted.get(job["id"], include_payload=True)
        self.assertEqual(failed["state"], "failed")
        self.assertEqual(failed["error_code"], "RetryLimitExceeded")
        self.assertIsNone(failed["source_text"])

    def test_concurrent_claims_are_unique(self):
        jobs = [self.enqueue(session_id=f"session_{index}") for index in range(8)]
        def claim(index):
            result = JobQueue(self.pyramid).claim(f"worker_{index}")
            return result["id"] if result else None
        with ThreadPoolExecutor(max_workers=8) as pool:
            ids = list(pool.map(claim, range(8)))
        self.assertEqual(set(ids), {job["id"] for job in jobs})

    def test_failed_extraction_requires_original_payload_for_retry_and_then_commits(self):
        job = self.enqueue()
        broken = mock.Mock()
        broken.extract_atomic_units.side_effect = ValueError("PRIVATE source error")
        self.queue.run(broken)
        failed = self.queue.get(job["id"], include_payload=True)
        self.assertEqual(failed["state"], "failed")
        self.assertEqual(failed["error_code"], "ValueError")
        self.assertIsNone(failed["source_text"])
        self.assertNotIn("PRIVATE", json.dumps(self.queue.receipt(job["id"])))
        self.queue.retry(job["id"], source_content=self.content)
        distiller = self.distiller()
        self.queue.run(distiller)
        receipt = self.queue.commit(job["id"], distiller)
        self.assertEqual(receipt["state"], "committed")
        self.assertEqual(len(distiller.data["memory_records"]), 1)
        completed = self.queue.get(job["id"], include_payload=True)
        self.assertIsNone(completed["source_text"])
        self.assertIsNone(completed["result_text"])

    def test_changed_or_missing_source_result_is_stale_and_cannot_overwrite_current_memory(self):
        for missing in (False, True):
            with self.subTest(missing=missing):
                self.source.write_text(self.content)
                queue = JobQueue(self.pyramid, str(self.root / f"queue{missing}.sqlite3"))
                job = queue.enqueue(session_id="sess_notes", source_path=str(self.source), source_content=self.content)
                distiller = self.distiller()
                queue.run(distiller)
                if missing:
                    self.source.unlink()
                else:
                    self.source.write_text("# Notes\n- Newer fact.\n")
                result = queue.commit(job["id"], distiller)
                self.assertEqual(result["state"], "stale")
                self.assertEqual(distiller.data["memory_records"], [])
                self.assertIsNone(queue.get(job["id"], include_payload=True)["result_text"])

    def test_commit_replay_after_canonical_save_before_queue_ack_is_idempotent(self):
        job = self.enqueue()
        distiller = self.distiller()
        self.queue.run(distiller)
        finish = self.queue._finish
        def crash_after_save(job_id, state, **kwargs):
            if state == "committed":
                raise OSError("simulated process loss before acknowledgment")
            return finish(job_id, state, **kwargs)
        with mock.patch.object(self.queue, "_finish", side_effect=crash_after_save), self.assertRaises(OSError):
            self.queue.commit(job["id"], distiller)
        before = self.distiller().data
        self.source.write_text("Changed after the canonical commit")
        restarted = JobQueue(self.pyramid)
        self.assertEqual(restarted.commit(job["id"], self.distiller())["state"], "committed")
        after = self.distiller().data
        self.assertEqual(after["generation"], before["generation"])
        self.assertEqual(after["memory_records"], before["memory_records"])
        self.assertEqual(after["applied_jobs"].count(job["id"]), 1)

    def test_source_rename_can_commit_with_registry_identity_and_current_anchor(self):
        registry = SourceRegistry(self.pyramid)
        entry = registry.observe(read_source(str(self.source)))
        job = self.enqueue(session_id=entry["session_id"])
        distiller = self.distiller()
        self.queue.run(distiller)
        moved = self.root / "moved.md"
        self.source.rename(moved)
        registry.observe(read_source(str(moved)), live_paths=[str(moved)])
        self.queue.commit(job["id"], distiller, source_reader=lambda row: registry.read_current(row["session_id"]))
        self.assertEqual(distiller.data["memory_records"][0]["source_anchor"]["file_path"], str(moved))
        self.assertEqual(distiller.data["memory_records"][0]["source_anchor"]["session_id"], entry["session_id"])

    def test_fresh_permanent_source_controls_block_ready_job_commit(self):
        job = self.enqueue()
        distiller = self.distiller()
        self.queue.run(distiller)
        distiller.control("forget_session", source="session:sess_notes")
        self.assertIn(self.queue.commit(job["id"], distiller)["state"], ("stale", "cancelled"))
        self.assertEqual(distiller.data["memory_records"], [])

    def test_privacy_purge_clears_matching_payloads_without_touching_unrelated_jobs(self):
        private = "UNIQUE_PRIVATE_PAYLOAD_" + "x" * 10000
        first = self.enqueue(source_content=private)
        other = self.enqueue(session_id="unrelated")
        result = self.queue.purge(session_ids=["sess_notes"])
        self.assertEqual(result["matched"], 1)
        row = self.queue.get(first["id"], include_payload=True)
        self.assertEqual(row["state"], "cancelled")
        self.assertIsNone(row["source_text"])
        self.assertEqual(self.queue.get(other["id"])["state"], "queued")
        self.assertNotIn(private.encode(), Path(self.queue.path).read_bytes())
        self.assertFalse(Path(self.queue.path + "-wal").exists())
        self.assertEqual(self.source.read_text(), self.content)

    def test_purge_by_source_hash_and_terminal_receipt_pruning(self):
        job = self.enqueue()
        self.assertEqual(self.queue.purge(source_hashes=[job["source_hash"]])["matched"], 1)
        self.assertEqual(self.queue.prune(older_than_seconds=-1)["removed"], 1)
        self.assertEqual(self.queue.list(), [])

    def test_privacy_purge_cannot_retry_but_reversible_include_allows_fresh_job(self):
        job = self.enqueue()
        distiller = self.distiller()
        distiller.control("exclude", source=str(self.source))
        self.queue.purge(session_ids=["sess_notes"])
        with self.assertRaises(ValueError):
            self.queue.retry(job["id"], source_content=self.content)
        with self.assertRaisesRegex(ValueError, "excluded"):
            self.enqueue()
        distiller.control("include", source=str(self.source))
        fresh = self.enqueue()
        self.assertNotEqual(fresh["id"], job["id"])
        self.assertTrue(fresh["enqueued"])

    def test_permanent_source_suppression_refuses_raw_payload_at_enqueue(self):
        distiller = self.distiller()
        distiller.control("forget_session", source="session:sess_notes")
        with self.assertRaisesRegex(ValueError, "forgotten"):
            self.enqueue()
        self.assertFalse(Path(self.queue.path).exists())

    def test_unsupported_backend_is_explicit_and_does_not_create_queue(self):
        with self.assertRaises(ValueError):
            self.enqueue(backend="unknown")
        self.assertFalse(Path(self.queue.path).exists())

    def test_cloud_batch_submit_and_collect_resume_across_instances_without_polling(self):
        job = self.enqueue(backend="anthropic", model="synthetic-model")
        client = mock.Mock()
        client.messages.batches.create.return_value = NS(id="batch_fixture", processing_status="in_progress")
        client.messages.batches.retrieve.side_effect = [NS(processing_status="in_progress"), NS(processing_status="ended")]
        unit = {"type": "fact", "text": "User prefers quiet prompts.", "salience": "high",
                "source_anchor": {"heading": "Notes", "line_range": "L2"}, "source_quote": "User prefers quiet prompts."}
        client.messages.batches.results.return_value = [
            NS(custom_id="req_00000", result=NS(type="succeeded", message=NS(content=[NS(type="text", text=json.dumps([unit]))])))]
        self.assertEqual(self.queue.submit(client)[0]["state"], "submitted")
        restarted = JobQueue(self.pyramid)
        self.assertEqual(restarted.collect(client)[0]["state"], "submitted")
        self.assertEqual(restarted.get(job["id"])["lease_owner"], None)
        self.assertEqual(restarted.collect(client)[0]["state"], "ready")
        distiller = self.distiller()
        self.assertEqual(restarted.commit(job["id"], distiller)["state"], "committed")
        self.assertEqual(distiller.data["memory_records"][0]["evidence"]["extraction"]["model"], "synthetic-model")
        self.assertEqual(client.messages.batches.create.call_count, 1)
        self.assertEqual(client.messages.batches.retrieve.call_count, 2)

    def test_crash_in_cloud_submission_gap_does_not_silently_submit_again(self):
        job = self.enqueue(backend="anthropic", model="synthetic-model")
        client = mock.Mock()
        client.messages.batches.create.return_value = NS(id="accepted_remotely", processing_status="in_progress")
        finish = self.queue._finish
        def crash_after_provider(job_id, state, **kwargs):
            if kwargs.get("batch", {}).get("batch_id") == "accepted_remotely":
                raise KeyboardInterrupt("simulated process loss")
            return finish(job_id, state, **kwargs)
        with mock.patch.object(self.queue, "_finish", side_effect=crash_after_provider), self.assertRaises(KeyboardInterrupt):
            self.queue.submit(client)
        with sqlite3.connect(self.queue.path) as db:
            db.execute("UPDATE jobs SET lease_until=? WHERE id=?", (time.time() - 1, job["id"]))
        restarted = JobQueue(self.pyramid)
        self.assertEqual(restarted.submit(client), [])
        receipt = restarted.collect(client)[0]
        self.assertEqual(receipt["state"], "failed")
        self.assertEqual(receipt["error_code"], "SubmissionOutcomeUnknown")
        self.assertEqual(client.messages.batches.create.call_count, 1)
        client.messages.batches.retrieve.assert_not_called()


if __name__ == "__main__":
    unittest.main()
