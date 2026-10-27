"""Public retrieval adapters preserve scope, offline defaults and budgets."""
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from memory_pyramid_distiller import MemoryPyramidDistiller
from napmem_retrieval_agent import NapMemRetrievalAgent


class RetrievalContractTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.path = str(Path(self.tmp.name) / "store.json")
        distiller = MemoryPyramidDistiller(self.path)
        for session, scope, text in (("a", "project:a", "Editor preference is Vim."),
                                     ("b", "project:b", "Editor preference is Emacs.")):
            distiller.ingest_session(session, session, f"{session}.md", "# Editors\n" + text, scope=scope)
        self.agent = NapMemRetrievalAgent(self.path)

    def test_query_and_legacy_views_do_not_disclose_other_project(self):
        for result in (self.agent.query("editor", scope="project:a"),
                       self.agent.search_memory_pyramid("editor", scope="project:a"),
                       self.agent.get_topic_track("editors", scope="project:a")):
            self.assertIn("Vim", json.dumps(result))
            self.assertNotIn("Emacs", json.dumps(result))
            self.assertNotIn("project:b", json.dumps(result))
        self.assertIn("error", self.agent.inspect_provenance("rec_b_001", scope="project:a"))

    def test_default_hybrid_never_selects_or_probes_an_online_backend(self):
        with patch.dict("os.environ", {"NAPMEM_EMBED_BACKEND": "ollama"}), patch(
                "socket.create_connection", side_effect=AssertionError("network forbidden")), patch(
                "semantic_index.OllamaBackend.probe", side_effect=AssertionError("probe forbidden")):
            result = self.agent.query("editor", scope="project:a")
        self.assertEqual(len(result["matches"]), 1)
        self.assertIn("sparse", result["mode"])

    def test_topic_limit_accepts_a_real_long_heading_advertised_by_mcp(self):
        slug = "a" * 300
        MemoryPyramidDistiller(self.path).ingest_session("long", "Long", "long.md", "# " + slug + "\nA long heading fact.")
        result = NapMemRetrievalAgent(self.path).get_topic_track(slug)
        self.assertEqual(result["track"]["topic_slug"], slug)
        self.assertEqual(len(result["records"]), 1)

    def test_legacy_semantic_constructor_failure_stays_offline(self):
        with patch("semantic_index.SemanticIndex", side_effect=RuntimeError("offline")), patch(
                "semantic_index.OllamaBackend.probe", side_effect=AssertionError("probe forbidden")):
            result = self.agent.semantic_search("Editor", scope="project:a", top_k=1)
        self.assertEqual(result["mode"], "substring-fallback")
        self.assertEqual(len(result["matches"]), 1)

    def test_wire_accounting_and_small_budget_errors_are_explicit(self):
        result = self.agent.query("editor", scope="project:a", max_bytes=2048, max_tokens=512)
        encoded = json.dumps(result, sort_keys=True, ensure_ascii=False, separators=(",", ":")).encode()
        self.assertLessEqual(len(encoded), 2048)
        self.assertEqual(result["returned_bytes"], len(encoded))
        with self.assertRaises(ValueError):
            self.agent.query("editor", scope="project:a", max_bytes=12)

    def test_invalid_query_and_counts_never_reach_a_backend(self):
        for value in (True, False, 0, -1, 101, "4"):
            with self.subTest(value=value), self.assertRaises(ValueError):
                self.agent.query("editor", top_k=value)
        for query in (None, "", " " * 3, "x" * 2049):
            with self.subTest(query=repr(query)[:20]), self.assertRaises(ValueError):
                self.agent.query(query)

    def test_short_query_keeps_its_distinguishing_qualifier(self):
        result = self.agent.query("editor Sublime", scope="project:a")
        self.assertTrue(result["abstention"])
        self.assertEqual(result["matches"], [])

    def test_preference_word_forms_match_without_relaxing_short_query_coverage(self):
        for query in ("preferred editor", "favorite editor", "editor preference"):
            with self.subTest(query=query):
                result = self.agent.query(query, scope="project:a")
                self.assertEqual([r["text"] for r in result["matches"]], ["Editor preference is Vim."])
