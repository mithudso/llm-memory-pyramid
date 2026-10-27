"""Offline regression checks for store reconciliation and disposable caches."""

import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from memory_pyramid_distiller import MemoryPyramidDistiller
from napmem_retrieval_agent import NapMemRetrievalAgent
from semantic_index import HashedTfBackend, SemanticIndex, _text_key


class RecordingBackend:
    name = "recording"
    model = "recording-v1"

    def __init__(self):
        self.calls = []

    def embed(self, texts):
        self.calls.append(list(texts))
        return [[1.0, 0.0] if text == "US" else [0.0, 1.0] for text in texts]


class TestReconciliationRegressions(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="napmem_reconcile_")
        self.addCleanup(self.temp.cleanup)
        self.pyramid = str(Path(self.temp.name) / "p.json")

    def test_reasserted_record_refreshes_payload_without_changing_identity(self):
        distiller = MemoryPyramidDistiller(self.pyramid)
        distiller.ingest_session("s", "S", "s.md", "# Old\n- Original statement\n")
        original = dict(distiller.data["memory_records"][0])
        updated = distiller.extract_atomic_units(
            "# New\n- original statement\n", "s", "s.md")
        updated[0].update(type="fact", salience="high", topic_slug="new")
        distiller.ingest_session_records("s", "S", "s.md", updated)

        record = MemoryPyramidDistiller(self.pyramid).data["memory_records"][0]
        self.assertEqual(record["id"], original["id"])
        self.assertEqual(record["canonical"], original["canonical"])
        self.assertEqual(record["created_at"], original["created_at"])
        self.assertEqual(record["text"], "original statement")
        self.assertEqual((record["type"], record["salience"], record["topic_slug"]),
                         ("fact", "high", "new"))
        self.assertEqual(distiller.data["topic_tracks"][0]["topic_slug"], "new")
        # Salience and classification alone do not establish a durable trait.
        self.assertEqual(distiller.data["user_profiles"], [])

    def test_wording_refresh_preserves_foreign_duplicate_promotion(self):
        distiller = MemoryPyramidDistiller(self.pyramid)
        distiller.ingest_session("a", "A", "a.md", "# Old\n- Uses PostgreSQL.\n")
        distiller.ingest_session("b", "B", "b.md", "# Other\n- Uses PostgreSQL.\n")
        duplicate_id = distiller.data["memory_records"][0]["duplicates"][0]

        distiller.ingest_session("a", "A", "a.md", "# New\n- uses postgresql.\n")
        current = distiller.data["memory_records"][0]
        self.assertEqual(current["text"], "uses postgresql.")
        self.assertEqual(current["duplicate_anchors"][duplicate_id]["paraphrase_text"],
                         "Uses PostgreSQL.")
        distiller.ingest_session("a", "A", "a.md", "# New\n")
        promoted = distiller.data["memory_records"][0]
        self.assertEqual(promoted["id"], duplicate_id)
        self.assertEqual(promoted["text"], "Uses PostgreSQL.")
        self.assertEqual(promoted["source_anchor"]["session_id"], "b")

    def test_repeated_own_occurrences_keep_ids_and_ordinal_anchors(self):
        distiller = MemoryPyramidDistiller(self.pyramid)
        content = "# Notes\n- alpha\n- alpha\n- beta\n- alpha\n"
        distiller.ingest_session("s", "S", "s.md", content)
        original = json.loads(json.dumps(distiller.data["memory_records"]))
        for record in original:
            record.setdefault("duplicate_anchors", {})
        distiller.ingest_session("s", "S", "s.md", content)
        self.assertEqual(distiller.data["memory_records"], original)
        agent = NapMemRetrievalAgent(self.pyramid)
        self.assertEqual(agent.inspect_provenance("rec_s_002")["source_anchor"]["line_range"], "L3")
        self.assertEqual(agent.inspect_provenance("rec_s_004")["source_anchor"]["line_range"], "L5")
        distiller.ingest_session("s", "S", "s.md", "# Notes\n- beta\n- alpha\n- alpha\n")
        agent = NapMemRetrievalAgent(self.pyramid)
        self.assertEqual(agent.inspect_provenance("rec_s_001")["source_anchor"]["line_range"], "L3")
        self.assertEqual(agent.inspect_provenance("rec_s_002")["source_anchor"]["line_range"], "L4")
        self.assertIn("error", agent.inspect_provenance("rec_s_004"))

    def test_repeated_foreign_occurrences_reclaim_every_duplicate(self):
        distiller = MemoryPyramidDistiller(self.pyramid)
        distiller.ingest_session("a", "A", "a.md", "# Notes\n- alpha\n")
        content = "# Notes\n- alpha\n- alpha\n- beta\n- alpha\n"
        distiller.ingest_session("s", "S", "s.md", content)
        original = json.loads(json.dumps(distiller.data["memory_records"]))
        for record in original:
            record.setdefault("duplicate_anchors", {})
        distiller.ingest_session("s", "S", "s.md", content)
        self.assertEqual(distiller.data["memory_records"], original)
        agent = NapMemRetrievalAgent(self.pyramid)
        for suffix, line in [(1, 2), (2, 3), (4, 5)]:
            self.assertEqual(agent.inspect_provenance(f"rec_s_{suffix:03d}")["source_anchor"]["line_range"],
                             f"L{line}")

    def test_semantic_index_initialization_failure_degrades_to_exact(self):
        for error in [RuntimeError, ImportError, OSError, ValueError]:
            with self.subTest(error=error.__name__):
                path = str(Path(self.temp.name) / (error.__name__ + ".json"))
                distiller = MemoryPyramidDistiller(path, semantic_dedup=True)
                with mock.patch.object(distiller, "_get_semantic_index",
                                       side_effect=error("SENSITIVE_MODEL_PAYLOAD")):
                    with self.assertLogs("memory_pyramid_distiller", level="WARNING") as logs:
                        distiller.ingest_session("s", "S", "s.md", "# Notes\n- alpha\n- alpha\n")
                stored = MemoryPyramidDistiller(path).data["memory_records"]
                self.assertEqual(len(stored), 1)
                self.assertEqual(stored[0]["duplicates"], ["rec_s_002"])
                self.assertIn("exact-only", " ".join(logs.output))
                self.assertNotIn("SENSITIVE_MODEL_PAYLOAD", " ".join(logs.output))

    def test_exact_only_merge_does_not_initialize_semantic_index(self):
        distiller = MemoryPyramidDistiller(self.pyramid)
        distiller.ingest_session("a", "A", "a.md", "# Notes\n- alpha\n")
        distiller.semantic_dedup = True
        with mock.patch.object(distiller, "_get_semantic_index") as factory:
            distiller.ingest_session("s", "S", "s.md", "# Notes\n- alpha\n")
            factory.assert_not_called()


class TestSemanticCacheRegressions(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="napmem_cache_")
        self.addCleanup(self.temp.cleanup)
        self.pyramid = str(Path(self.temp.name) / "p.json")
        self.cache_path = Path(self.pyramid + ".embindex.json")
        self.backend = RecordingBackend()
        self.record = {"id": "r", "text": "US"}

    def write_cache(self, entry):
        self.cache_path.write_text(json.dumps({
            "model": self.backend.model, "vectors": {"r": entry}}), encoding="utf-8")

    def test_invalid_entries_recover_with_safe_warning(self):
        malformed = [None, {}, {"key": _text_key("US")},
                     {"key": _text_key("US"), "vec": None},
                     {"key": _text_key("US"), "vec": [True, False]},
                     {"key": _text_key("US"), "vec": [float("nan"), 0.0]},
                     {"key": _text_key("US"), "vec": [float("inf"), 0.0]},
                     {"key": _text_key("US"), "vec": []},
                     {"key": _text_key("US"), "vec": [0.0] * 8193}]
        for entry in malformed:
            with self.subTest(entry_type=type(entry).__name__):
                self.write_cache(entry)
                with self.assertLogs("semantic_index", level="WARNING") as logs:
                    hits = SemanticIndex(self.pyramid, self.backend).search("US", [self.record])
                self.assertEqual(hits[0]["score"], 1.0)
                self.assertIn("Discarding", " ".join(logs.output))
                self.assertNotIn("'US'", " ".join(logs.output))
                persisted = json.loads(self.cache_path.read_text(encoding="utf-8"))
                self.assertEqual(persisted["vectors"]["r"]["vec"], [1.0, 0.0])

    def test_wrong_cached_dimension_reembeds_before_scoring(self):
        self.write_cache({"key": _text_key("US"), "vec": [1.0, 0.0, 0.0]})
        with self.assertLogs("semantic_index", level="WARNING"):
            hits = SemanticIndex(self.pyramid, self.backend).search("US", [self.record])
        self.assertEqual(hits[0]["score"], 1.0)
        self.assertEqual(json.loads(self.cache_path.read_text())["vectors"]["r"]["vec"],
                         [1.0, 0.0])

    def test_exact_input_changes_invalidate_cached_vector(self):
        index = SemanticIndex(self.pyramid, self.backend)
        index._vectors_for([self.record])
        vectors = index._vectors_for([{"id": "r", "text": "us"}])
        self.assertEqual(vectors["r"], [0.0, 1.0])
        self.assertEqual(self.backend.calls, [["US"], ["us"]])

    def test_deletion_only_refresh_prunes_persisted_cache(self):
        index = SemanticIndex(self.pyramid, self.backend)
        index.rebuild([self.record, {"id": "removed", "text": "other"}])
        self.backend.calls.clear()
        self.assertEqual(index._vectors_for([self.record]), {"r": [1.0, 0.0]})
        self.assertEqual(self.backend.calls, [])
        self.assertEqual(set(json.loads(self.cache_path.read_text())["vectors"]), {"r"})

    def test_empty_rebuild_persists_empty_cache(self):
        index = SemanticIndex(self.pyramid, self.backend)
        index.rebuild([self.record])
        index.rebuild([])
        self.assertEqual(json.loads(self.cache_path.read_text())["vectors"], {})

    def test_search_after_last_record_deletion_clears_disk_without_embedding(self):
        index = SemanticIndex(self.pyramid, self.backend)
        index.rebuild([self.record])
        self.backend.calls.clear()
        self.assertEqual(index.search("query", []), [])
        self.assertEqual(self.backend.calls, [])
        self.assertEqual(json.loads(self.cache_path.read_text())["vectors"], {})

    def test_invalid_backend_vectors_do_not_replace_good_cache(self):
        index = SemanticIndex(self.pyramid, self.backend)
        index.rebuild([self.record])
        before = self.cache_path.read_bytes()
        with mock.patch.object(self.backend, "embed", return_value=[[float("nan"), 0.0]]):
            with self.assertRaises(ValueError):
                index.search("query", [self.record])
        self.assertEqual(self.cache_path.read_bytes(), before)

    def test_overflow_similarity_fails_search_and_dedup_without_nan(self):
        index = SemanticIndex(self.pyramid, self.backend)
        with mock.patch.object(self.backend, "embed", side_effect=lambda texts: [[1e308, 0.0] for _ in texts]):
            with self.assertRaisesRegex(ValueError, "similarity"):
                index.search("query", [self.record])
            with self.assertRaisesRegex(ValueError, "similarity"):
                index.nearest_many(["query"], [self.record], threshold=0.9)


class TestRetrievalCountRegressions(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="napmem_count_")
        self.addCleanup(self.temp.cleanup)
        self.pyramid = str(Path(self.temp.name) / "p.json")
        MemoryPyramidDistiller(self.pyramid).save()

    def test_invalid_counts_fail_before_backend_or_fallback(self):
        agent = NapMemRetrievalAgent(self.pyramid)
        index = SemanticIndex(self.pyramid, HashedTfBackend())
        with mock.patch("semantic_index.SemanticIndex") as factory:
            for value in [-1, 0, True, False, 1.5, "2", None]:
                with self.subTest(value=value):
                    with self.assertRaisesRegex(ValueError, "positive integer"):
                        agent.semantic_search("query", top_k=value)
                    with self.assertRaisesRegex(ValueError, "positive integer"):
                        index.search("query", [], top_k=value)
            factory.assert_not_called()

    def test_valid_count_is_respected_by_disclosed_fallback(self):
        distiller = MemoryPyramidDistiller(self.pyramid)
        distiller.ingest_session("s", "S", "s.md", "# T\n- apple one\n- apple two\n")
        agent = NapMemRetrievalAgent(self.pyramid)
        with mock.patch("semantic_index.SemanticIndex", side_effect=RuntimeError("offline")):
            result = agent.semantic_search("apple", top_k=1)
        self.assertEqual(result["mode"], "substring-fallback")
        self.assertEqual(len(result["matches"]), 1)


if __name__ == "__main__":
    unittest.main()
