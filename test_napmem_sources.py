"""Offline stable identity, guarded collection and source lifecycle tests."""

import hashlib
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest import mock
from types import SimpleNamespace as NS

from memory_pyramid_distiller import MemoryPyramidDistiller
from napmem_sources import SourceRegistry, read_source
from naptime_consolidator import NaptimeConsolidator


class TestSourceRegistry(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.pyramid = str(self.root / "store.json")
        self.registry = SourceRegistry(self.pyramid)

    def test_status_on_missing_registry_creates_nothing(self):
        self.assertEqual(self.registry.list(), [])
        self.assertIsNone(self.registry.lookup(session_id="missing"))
        self.assertFalse(Path(self.registry.path).exists())
        self.assertFalse(Path(self.registry.path + ".lock").exists())

    def test_first_legacy_basename_and_independent_same_basename_have_distinct_ids(self):
        left, right = self.root / "left" / "notes.md", self.root / "right" / "notes.md"
        left.parent.mkdir()
        right.parent.mkdir()
        left.write_text("left source")
        right.write_text("right source")
        a = self.registry.observe(read_source(str(left)), live_paths=[str(left), str(right)])
        b = self.registry.observe(read_source(str(right)), live_paths=[str(left), str(right)])
        self.assertEqual(a["session_id"], "sess_notes")
        self.assertNotEqual(a["session_id"], b["session_id"])
        self.assertEqual(self.registry.lookup(path=str(left))["session_id"], a["session_id"])
        self.assertEqual(os.stat(self.registry.path).st_mode & 0o777, 0o600)

    def test_rename_preserves_identity_and_committed_digest(self):
        old, new = self.root / "before.md", self.root / "after.md"
        old.write_text("same immutable snapshot")
        first = self.registry.observe(read_source(str(old)), scope="project:a")
        self.registry.mark_committed(first["session_id"], first["sha256"])
        old.rename(new)
        new.write_text("updated immutable snapshot")
        renamed = self.registry.observe(read_source(str(new)), live_paths=[str(new)])
        self.assertEqual(renamed["session_id"], first["session_id"])
        self.assertEqual(renamed["committed_sha256"], first["sha256"])
        self.assertEqual(renamed["scope"], "project:a")

    def test_missing_is_metadata_only_and_does_not_delete_registry_identity(self):
        path = self.root / "notes.md"
        path.write_text("retained knowledge")
        entry = self.registry.observe(read_source(str(path)))
        path.unlink()
        missing = self.registry.mark_missing([])
        self.assertEqual(missing[0]["session_id"], entry["session_id"])
        self.assertEqual(self.registry.list()[0]["status"], "missing")
        self.assertIsNone(self.registry.read_current(entry["session_id"]))

    def test_root_limited_missing_scan_does_not_mark_other_watch_tree_missing(self):
        for name in ("left", "right"):
            directory = self.root / name
            directory.mkdir()
            path = directory / "notes.md"
            path.write_text(name)
            self.registry.observe(read_source(str(path)), live_paths=[str(path)])
        self.registry.mark_missing([], root=str(self.root / "left"))
        states = {Path(entry["path"]).parent.name: entry["status"] for entry in self.registry.list()}
        self.assertEqual(states, {"left": "missing", "right": "present"})

    def test_bounded_reader_hashes_actual_bytes_and_refuses_oversized_or_unverifiable_source(self):
        path = self.root / "unicode.md"
        path.write_bytes("雪\r\nliteral".encode())
        snapshot = read_source(str(path))
        self.assertEqual(snapshot["content"], "雪\r\nliteral")
        self.assertEqual(snapshot["sha256"], hashlib.sha256(path.read_bytes()).hexdigest())
        with self.assertRaises(ValueError):
            read_source(str(path), max_bytes=2)
        with self.assertRaises(PermissionError):
            read_source(str(path), fd_path_resolver=lambda fd: None)


class TestConsolidatorSourceLifecycle(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.watch = self.root / "logs"
        self.watch.mkdir()
        self.path = self.watch / "notes.md"
        self.path.write_text("# Preferences\n- User prefers quiet prompts.\n")
        self.pyramid = str(self.root / "store.json")

    def fresh(self, **kwargs):
        return NaptimeConsolidator(str(self.watch), self.pyramid, extraction="heuristic", **kwargs)

    def test_same_mtime_edit_is_detected_and_touched_identical_content_skips(self):
        self.assertEqual(self.fresh().scan_and_consolidate(), 1)
        stamp = self.path.stat().st_mtime_ns
        self.path.write_text("# Preferences\n- User prefers brief prompts.\n")
        os.utime(self.path, ns=(stamp, stamp))
        self.assertEqual(self.fresh().scan_and_consolidate(), 1)
        os.utime(self.path, ns=(stamp + 1000000, stamp + 1000000))
        self.assertEqual(self.fresh().scan_and_consolidate(), 0)
        data = MemoryPyramidDistiller(self.pyramid).data
        self.assertEqual([r["text"] for r in data["memory_records"]], ["User prefers brief prompts."])

    def test_rename_preserves_session_and_record_ids_and_updates_path(self):
        self.fresh().scan_and_consolidate()
        before = MemoryPyramidDistiller(self.pyramid).data["memory_records"][0]
        new_path = self.watch / "renamed.md"
        self.path.rename(new_path)
        self.assertEqual(self.fresh().scan_and_consolidate(), 0)
        after = MemoryPyramidDistiller(self.pyramid).data["memory_records"][0]
        self.assertEqual(after["id"], before["id"])
        self.assertEqual(after["source_anchor"]["session_id"], before["source_anchor"]["session_id"])
        self.assertEqual(after["source_anchor"]["file_path"], str(new_path))

    def test_deleted_source_retains_records_with_explicit_missing_status(self):
        self.fresh().scan_and_consolidate()
        before = MemoryPyramidDistiller(self.pyramid).data["memory_records"][0]["id"]
        self.path.unlink()
        self.assertEqual(self.fresh().scan_and_consolidate(), 0)
        data = MemoryPyramidDistiller(self.pyramid).data
        self.assertEqual(data["memory_records"][0]["id"], before)
        self.assertEqual(data["memory_records"][0]["source_state"], "missing")
        self.assertEqual(data["raw_conversations"][0]["source_state"], "missing")

    def test_permanently_forgotten_source_is_skipped_before_guarded_read(self):
        self.fresh().scan_and_consolidate()
        distiller = MemoryPyramidDistiller(self.pyramid)
        distiller.control("forget_session", source="session:sess_notes")
        with mock.patch("naptime_consolidator.read_source", side_effect=AssertionError("Excluded source was read")):
            self.assertEqual(self.fresh().scan_and_consolidate(), 0)

    def test_async_heuristic_path_commits_and_restarts_without_duplicate_jobs(self):
        self.assertEqual(self.fresh(async_batches=True).scan_and_consolidate(), 1)
        self.assertEqual(self.fresh(async_batches=True).scan_and_consolidate(), 0)
        from napmem_jobs import JobQueue
        queue = JobQueue(self.pyramid)
        self.assertEqual(len(queue.list()), 1)
        self.assertEqual(queue.list()[0]["state"], "committed")
        self.assertEqual(len(MemoryPyramidDistiller(self.pyramid).data["memory_records"]), 1)

    def test_async_cloud_batch_submits_once_then_collects_in_later_sweep(self):
        client = mock.Mock()
        client.messages.batches.create.return_value = NS(id="batch_fixture", processing_status="in_progress")
        client.messages.batches.retrieve.return_value = NS(processing_status="ended")
        unit = {"type": "fact", "text": "User prefers quiet prompts.", "salience": "high",
                "source_quote": "User prefers quiet prompts.",
                "source_anchor": {"heading": "Preferences", "line_range": "L2"}}
        client.messages.batches.results.return_value = [
            NS(custom_id="req_00000", result=NS(type="succeeded", message=NS(content=[NS(type="text", text=json.dumps([unit]))])))]
        def fresh():
            with mock.patch("naptime_consolidator._anthropic_available", return_value=True):
                instance = NaptimeConsolidator(str(self.watch), self.pyramid, extraction="llm", async_batches=True)
            instance._client = client
            return instance
        self.assertEqual(fresh().scan_and_consolidate(), 1)
        client.messages.batches.retrieve.assert_not_called()
        self.assertEqual(fresh().scan_and_consolidate(), 1)
        self.assertEqual(fresh().scan_and_consolidate(), 0)
        self.assertEqual(client.messages.batches.create.call_count, 1)
        self.assertEqual(client.messages.batches.retrieve.call_count, 1)
        self.assertEqual(len(MemoryPyramidDistiller(self.pyramid).data["memory_records"]), 1)

    def test_sync_model_output_for_changed_source_is_not_committed_or_heuristically_replayed(self):
        def stale_batch(client, prompts, model):
            self.path.write_text("# Preferences\n- Newer source content.\n")
            return {"sess_notes": json.dumps([{
                "type": "fact", "text": "User prefers quiet prompts.", "salience": "high",
                "source_anchor": {"heading": "Preferences", "line_range": "L2"}}])}
        with mock.patch("naptime_consolidator._anthropic_available", return_value=True):
            instance = NaptimeConsolidator(str(self.watch), self.pyramid, extraction="llm")
        instance._client = object()
        with mock.patch("llm_extractor.extract_batch", side_effect=stale_batch), \
                mock.patch.dict("sys.modules", {"anthropic": NS(AnthropicError=RuntimeError)}):
            self.assertEqual(instance.scan_and_consolidate(), 0)
        self.assertEqual(MemoryPyramidDistiller(self.pyramid).data["memory_records"], [])


if __name__ == "__main__":
    unittest.main()
