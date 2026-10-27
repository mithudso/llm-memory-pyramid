"""Operator controls remain effective across ingestion, cache and reload boundaries."""
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from memory_pyramid_distiller import MemoryPyramidDistiller
from napmem_model import effective_records
from napmem_retrieval_agent import NapMemRetrievalAgent


class ControlIntegrationTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.path = str(Path(self.tmp.name) / "store.json")
        self.store = MemoryPyramidDistiller(self.path)
        self.text = "I prefer the blue editor."
        self.store.ingest_session("a", "A", "a.md", self.text, scope="project:a")
        self.rid = self.store.data["memory_records"][0]["id"]

    def test_preview_is_read_only_and_commit_detects_stale_preview(self):
        before = Path(self.path).read_bytes()
        preview = self.store.control("pin", record_id=self.rid, dry_run=True)
        self.assertEqual(Path(self.path).read_bytes(), before)
        self.store.control("approve", record_id=self.rid)
        with self.assertRaises(ValueError):
            self.store.control("pin", record_id=self.rid, preview_token=preview["preview_token"])

    def test_correction_survives_source_replay_and_reloading(self):
        corrected = "I prefer the green editor."
        self.store.control("correct", record_id=self.rid, value=corrected)
        self.store.ingest_session("a", "A", "a.md", self.text)
        loaded = MemoryPyramidDistiller(self.path)
        visible = effective_records(loaded.data, "project:a")
        self.assertEqual([r["text"] for r in visible], [corrected])
        self.assertEqual(visible[0]["evidence"]["source_kind"], "operator")
        self.assertEqual(len(loaded.data["memory_records"]), 2)

    def test_forget_removes_corrected_family_cache_and_replay(self):
        corrected = "I prefer the green editor."
        self.store.control("correct", record_id=self.rid, value=corrected)
        cache = Path(self.path + ".embindex.json")
        cache.write_text(json.dumps({"vectors": {self.rid: [1.0, 2.0]}}))
        receipt = self.store.control("forget", record_id=self.rid)
        self.assertFalse(cache.exists())
        self.assertTrue(receipt["canonical_deletion_complete"])
        self.store.ingest_session("a", "A", "a.md", self.text)
        self.assertEqual(effective_records(self.store.data, "project:a"), [])
        serialized = Path(self.path).read_text()
        self.assertNotIn(self.text, serialized)
        self.assertNotIn(corrected, serialized)

    def test_forget_seeds_scope_for_a_store_without_source_registry(self):
        self.store.data.pop("source_scopes", None)
        self.store.data["raw_conversations"] = []
        self.store.save()
        self.store.control("forget", record_id=self.rid)
        self.store.ingest_session("a", "A", "a.md", self.text)
        self.assertEqual(self.store.data["memory_records"], [])
        self.assertNotIn(self.text, Path(self.path).read_text())

    def test_source_exclusion_promotes_other_occurrence_and_blocks_replay(self):
        self.store.ingest_session("b", "B", "b.md", self.text, scope="project:a")
        self.store.control("exclude", source="session:a")
        rows = effective_records(self.store.data, "project:a")
        self.assertEqual([r["source_anchor"]["session_id"] for r in rows], ["b"])
        self.store.ingest_session("a", "A", "a.md", self.text, scope="project:a")
        self.assertEqual(len(self.store.data["memory_records"]), 1)
        self.assertEqual(self.store.data["memory_records"][0]["duplicates"], [])

    def test_expiry_keeps_history_but_removes_current_context(self):
        self.store.control("expire", record_id=self.rid, value="2026-02-01T00:00:00Z")
        self.assertEqual(effective_records(self.store.data, "project:a", "2026-03-01T00:00:00Z"), [])
        self.assertEqual(len(effective_records(self.store.data, "project:a", "2026-01-15T00:00:00Z")), 1)

    def test_save_failure_rolls_back_operator_state(self):
        before = json.dumps(self.store.data, sort_keys=True)
        with patch.object(self.store, "save", side_effect=OSError("disk unavailable")), self.assertRaises(OSError):
            self.store.control("pin", record_id=self.rid)
        self.assertEqual(json.dumps(self.store.data, sort_keys=True), before)

    def test_cache_purge_failure_is_a_persisted_partial_receipt(self):
        with patch("memory_pyramid_distiller.os.unlink", side_effect=PermissionError("not writable")):
            receipt = self.store.control("forget", record_id=self.rid)
        self.assertFalse(receipt["canonical_deletion_complete"])
        self.assertEqual(receipt["cache"], "pending:PermissionError")
        loaded = MemoryPyramidDistiller(self.path)
        self.assertEqual(loaded.data["memory_records"], [])
        self.assertEqual(loaded.data["deletion_receipts"][-1]["cache"], "pending:PermissionError")

    def test_retrieval_is_read_only_after_a_control_commit(self):
        self.store.control("pin", record_id=self.rid)
        before = Path(self.path).read_bytes()
        result = NapMemRetrievalAgent(self.path).query("editor", scope="project:a")
        self.assertTrue(result["matches"][0]["pinned"])
        self.assertEqual(Path(self.path).read_bytes(), before)
