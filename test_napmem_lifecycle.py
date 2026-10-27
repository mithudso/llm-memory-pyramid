"""Integration gates for compatible scoped assertion ingestion."""
import json
from pathlib import Path
import tempfile
import unittest

from memory_pyramid_distiller import MemoryPyramidDistiller
from napmem_model import effective_records
from semantic_index import SemanticIndex


class ConstantBackend:
    name = "constant"
    model = "constant-test"

    def embed(self, texts):
        return [[1.0, 0.0] for _ in texts]


class LifecycleIntegrationTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.path = str(Path(self.tmp.name) / "store.json")
        self.store = MemoryPyramidDistiller(self.path)

    def test_same_text_in_two_projects_keeps_separate_assertions(self):
        for session, scope in (("a", "project:a"), ("b", "project:b")):
            self.store.ingest_session(session, session, f"{session}.md",
                                      "# Editor\nI prefer Vim.\n", scope=scope)
        self.assertEqual(len(self.store.data["memory_records"]), 2)
        chosen = effective_records(self.store.data, scope="project:a")
        self.assertEqual([r["source_anchor"]["session_id"] for r in chosen], ["a"])
        self.assertEqual(self.store.data["user_profiles"], [])

    def test_temporary_task_never_becomes_an_approved_profile(self):
        self.store.ingest_session("a", "A", "a.md", "Deploy the temporary test build.",
                                  metadata={"memory_kind": "task", "review_status": "approved"})
        self.assertEqual(self.store.data["user_profiles"], [])

    def test_similarity_cannot_fold_conflicting_preference_values(self):
        self.store.semantic_dedup = True
        self.store._semantic_index = SemanticIndex(self.path, backend=ConstantBackend())
        for session, text in (("a", "I prefer Vim."), ("b", "I prefer VS Code.")):
            self.store.ingest_session(session, session, f"{session}.md", text,
                                      scope="project:a", metadata={"subject": "editor"})
        self.assertEqual(len(self.store.data["memory_records"]), 2)
        self.assertEqual(len(self.store.data["conflicts"]), 1)

    def test_explicit_update_retains_history_and_ids(self):
        self.store.ingest_session("a", "A", "a.md", "I prefer Vim.", scope="project:a",
                                  metadata={"subject": "editor", "valid_from": "2026-01-01T00:00:00Z"})
        old = self.store.data["memory_records"][0]["id"]
        self.store.ingest_session("b", "B", "b.md", "I prefer VS Code.", scope="project:a",
                                  metadata={"subject": "editor", "valid_from": "2026-02-01T00:00:00Z",
                                            "supersedes": [old]})
        before = effective_records(self.store.data, scope="project:a", as_of="2026-01-15T00:00:00Z")
        after = effective_records(self.store.data, scope="project:a", as_of="2026-02-15T00:00:00Z")
        self.assertEqual([r["id"] for r in before], [old])
        self.assertEqual([r["text"] for r in after], ["I prefer VS Code."])
        self.assertEqual(len(self.store.data["memory_records"]), 2)

    def test_scope_change_does_not_reclassify_a_foreign_duplicate(self):
        text = "# Editor\nI prefer Vim.\n"
        self.store.ingest_session("a", "A", "a.md", text)
        self.store.ingest_session("b", "B", "b.md", text)
        self.store.ingest_session("a", "A", "a.md", text, scope="project:a")
        legacy = effective_records(self.store.data)
        scoped = effective_records(self.store.data, scope="project:a")
        self.assertEqual([r["source_anchor"]["session_id"] for r in legacy], ["b"])
        self.assertEqual([r["source_anchor"]["session_id"] for r in scoped], ["a"])

    def test_reingest_and_migration_do_not_churn_metadata(self):
        text = "# Notes\n- alpha\n- alpha\n"
        self.store.ingest_session("a", "A", "a.md", text, scope="project:a")
        original = json.loads(json.dumps(self.store.data["memory_records"]))
        self.store.ingest_session("a", "A", "a.md", text, scope="project:a")
        self.assertEqual(self.store.data["memory_records"], original)
        fresh = MemoryPyramidDistiller(self.path)
        self.assertEqual(fresh.data["memory_records"], original)
        self.assertEqual(fresh.data["version"], "2.0.0")

    def test_source_replay_retains_scope_and_explicit_lifecycle(self):
        text = "I prefer Vim."
        metadata = {"subject": "editor", "valid_from": "2026-01-01T00:00:00Z"}
        self.store.ingest_session("a", "A", "a.md", text, scope="project:a", metadata=metadata)
        first = json.loads(json.dumps(self.store.data["memory_records"][0]))
        self.store.ingest_session("a", "A", "a.md", text)
        self.assertEqual(self.store.data["memory_records"][0], first)
        self.store.ingest_session("b", "B", "b.md", "I prefer VS Code.", scope="project:a",
                                  metadata={"subject": "editor", "supersedes": [first["id"]],
                                            "valid_from": "2026-02-01T00:00:00Z"})
        self.store.ingest_session("a", "A", "a.md", "# Removed from mutable file")
        loaded = MemoryPyramidDistiller(self.path)
        self.assertEqual(len(loaded.data["memory_records"]), 2)
        self.assertEqual(effective_records(loaded.data, "project:a", "2026-01-15T00:00:00Z")[0]["id"], first["id"])
