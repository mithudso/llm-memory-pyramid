#!/usr/bin/env python3
"""
Tests for the production-path extensions: LLM extractor parsing/validation,
semantic index + semantic dedup, and the MCP stdio server.

Network-free by design: the extractor tests exercise parsing and record
conversion (not the API), semantic tests force the stdlib hashed backend, and
the MCP test drives the real server binary over a subprocess pipe.
"""

import json
import os
import shutil
import subprocess
import sys
import tempfile
import types
import unittest
from unittest import mock

import llm_extractor
from llm_extractor import ExtractionError, parse_extraction_output, units_to_records
from memory_pyramid_distiller import MemoryPyramidDistiller
from naptime_consolidator import NaptimeConsolidator
from semantic_index import HashedTfBackend, OllamaBackend, SemanticIndex, cosine

BASE_DIR = os.path.dirname(os.path.abspath(__file__))


class TestLLMExtractorParsing(unittest.TestCase):
    def _unit(self, **overrides):
        unit = {
            "type": "fact",
            "text": "User prefers tabs over spaces.",
            "salience": "high",
            "topic_slug": "editor-config",
            "source_anchor": {"heading": "Preferences", "line_range": "L3"},
        }
        unit.update(overrides)
        return unit

    def test_parses_bare_and_fenced_json(self):
        units = [self._unit()]
        raw = json.dumps(units)
        self.assertEqual(parse_extraction_output(raw), units)
        fenced = f"```json\n{raw}\n```"
        self.assertEqual(parse_extraction_output(fenced), units)

    def test_rejects_non_json_and_non_array(self):
        with self.assertRaises(ExtractionError):
            parse_extraction_output("I could not extract anything, sorry!")
        with self.assertRaises(ExtractionError):
            parse_extraction_output(json.dumps({"type": "fact"}))

    def test_units_to_records_validates_and_converts(self):
        good = self._unit()
        bad_type = self._unit(type="opinion")
        bad_anchor = self._unit(source_anchor={"heading": "X"})
        records, rejections = units_to_records(
            [good, bad_type, bad_anchor], "sess_x", "x.md"
        )
        self.assertEqual(len(records), 1)
        self.assertEqual(len(rejections), 2)
        rec = records[0]
        self.assertEqual(rec["id"], "rec_sess_x_001")
        self.assertEqual(rec["canonical"], rec["id"])
        self.assertEqual(rec["source_anchor"]["session_id"], "sess_x")
        self.assertEqual(rec["source_anchor"]["file_path"], "x.md")
        self.assertEqual(rec["topic_slug"], "editor-config")

    def test_batch_custom_ids_stay_short_and_map_back(self):
        """The Batches API caps custom_id at 64 chars; long mirrored-file
        session ids must never leak into custom_id, and results must map back
        to their sessions."""
        long_session = "sess_-Users-mitch-hudson-Documents-dashboard-mdb-tam__MEMORY-and-then-some"
        self.assertGreater(len(long_session), 64)

        captured = {}

        class FakeBatches:
            def create(self, requests):
                captured["requests"] = requests
                return types.SimpleNamespace(id="b1", processing_status="ended")

            def retrieve(self, bid):
                return types.SimpleNamespace(id=bid, processing_status="ended")

            def results(self, bid):
                for req in captured["requests"]:
                    yield types.SimpleNamespace(
                        custom_id=req["custom_id"],
                        result=types.SimpleNamespace(
                            type="succeeded",
                            message=types.SimpleNamespace(
                                content=[types.SimpleNamespace(type="text", text="[]")],
                                usage=types.SimpleNamespace(input_tokens=1, output_tokens=1),
                            ),
                        ),
                    )

        client = types.SimpleNamespace(
            messages=types.SimpleNamespace(batches=FakeBatches()))
        outputs = llm_extractor.extract_batch(client, {long_session: "prompt"}, "m")
        for req in captured["requests"]:
            self.assertLessEqual(len(req["custom_id"]), 64)
        self.assertEqual(set(outputs), {long_session})

    def test_extracted_records_flow_through_reingest(self):
        """LLM-extracted records must honor the same stable-ID re-ingest
        semantics as heuristic ones."""
        tmp = tempfile.mkdtemp(prefix="napmem_ext_")
        self.addCleanup(shutil.rmtree, tmp, ignore_errors=True)
        pyramid = os.path.join(tmp, "p.json")
        distiller = MemoryPyramidDistiller(pyramid_path=pyramid)

        v1, _ = units_to_records([self._unit()], "sess_llm", "m.md")
        distiller.ingest_session_records("sess_llm", "V1", "m.md", v1)
        kept_id = distiller.data["memory_records"][0]["id"]

        v2, _ = units_to_records(
            [self._unit(), self._unit(text="Uses MongoDB for storage.")],
            "sess_llm", "m.md",
        )
        distiller.ingest_session_records("sess_llm", "V2", "m.md", v2)
        records = distiller.data["memory_records"]
        ids = [r["id"] for r in records]
        self.assertEqual(len(ids), len(set(ids)))
        self.assertIn(kept_id, ids)
        self.assertCountEqual(
            [r["text"] for r in records],
            ["User prefers tabs over spaces.", "Uses MongoDB for storage."],
        )


class TestSemanticIndex(unittest.TestCase):
    def setUp(self):
        os.environ["NAPMEM_EMBED_BACKEND"] = "hashed"
        self.addCleanup(os.environ.pop, "NAPMEM_EMBED_BACKEND", None)
        self.tmp = tempfile.mkdtemp(prefix="napmem_sem_")
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        self.pyramid = os.path.join(self.tmp, "p.json")

    def _record(self, rid, text):
        return {"id": rid, "type": "fact", "text": text, "salience": "high",
                "canonical": rid, "duplicates": [], "topic_slug": "general",
                "source_anchor": {"session_id": "s", "file_path": "f.md",
                                  "heading": "H", "line_range": "L1"}}

    def test_hashed_backend_cosine_properties(self):
        backend = HashedTfBackend()
        [a, b, c] = backend.embed([
            "user prefers tabs over spaces",
            "user prefers tabs over spaces",
            "completely unrelated quantum entanglement",
        ])
        self.assertAlmostEqual(cosine(a, b), 1.0, places=6)
        self.assertLess(cosine(a, c), 0.5)

    def test_search_ranks_related_text_first(self):
        records = [
            self._record("r1", "User prefers tabs over spaces in the editor."),
            self._record("r2", "The deployment pipeline uses GitHub Actions."),
        ]
        index = SemanticIndex(self.pyramid)
        hits = index.search("tabs versus spaces preference", records, top_k=2)
        self.assertEqual(hits[0]["record"]["id"], "r1")
        self.assertGreater(hits[0]["score"], hits[1]["score"])
        self.assertTrue(os.path.exists(index.index_path))

    def test_semantic_dedup_folds_near_duplicate(self):
        distiller = MemoryPyramidDistiller(
            pyramid_path=self.pyramid, semantic_dedup=True, semantic_threshold=0.8
        )
        distiller.ingest_session(
            "sess_a", "A", "a.md", "# N\n- User prefers tabs over spaces always.\n"
        )
        # Same tokens, different punctuation/case: exact dedup misses, semantic folds.
        distiller.ingest_session(
            "sess_b", "B", "b.md", "# N\n- user Prefers TABS over spaces always\n"
        )
        records = distiller.data["memory_records"]
        self.assertEqual(len(records), 1)
        canonical = records[0]
        self.assertEqual(len(canonical["duplicates"]), 1)
        dup_id = canonical["duplicates"][0]
        anchor = canonical["duplicate_anchors"][dup_id]
        self.assertEqual(anchor["session_id"], "sess_b")
        self.assertIn("paraphrase_text", anchor)

    def test_semantic_dedup_off_by_default(self):
        distiller = MemoryPyramidDistiller(pyramid_path=self.pyramid)
        distiller.ingest_session("sess_a", "A", "a.md", "# N\n- alpha beta gamma one.\n")
        distiller.ingest_session("sess_b", "B", "b.md", "# N\n- Alpha beta gamma one!\n")
        self.assertEqual(len(distiller.data["memory_records"]), 2)


def _fake_anthropic_module():
    """Minimal stand-in for the anthropic package (never touches the network)."""
    module = types.ModuleType("anthropic")
    module.AnthropicError = type("AnthropicError", (Exception,), {})
    module.APIError = type("APIError", (module.AnthropicError,), {})
    module.Anthropic = lambda: object()
    return module


class TestConsolidatorLLMWiring(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="napmem_llm_")
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        self.watch = os.path.join(self.tmp, "logs")
        os.makedirs(self.watch)
        self.pyramid = os.path.join(self.tmp, "p.json")
        with open(os.path.join(self.watch, "notes.md"), "w", encoding="utf-8") as f:
            f.write("# Prefs\n- User prefers tabs over spaces.\n")
        # `anthropic` is faked in sys.modules so auto mode selects the LLM
        # path without the real dependency or network.
        patcher = mock.patch.dict(sys.modules, {"anthropic": _fake_anthropic_module()})
        patcher.start()
        self.addCleanup(patcher.stop)

    def _llm_output(self):
        return json.dumps([{
            "type": "fact", "text": "LLM says: tabs preferred.",
            "salience": "high", "topic_slug": "prefs",
            "source_anchor": {"heading": "Prefs", "line_range": "L2"},
        }])

    def test_auto_mode_uses_llm_batch(self):
        with mock.patch.object(llm_extractor, "extract_batch",
                               return_value={"sess_notes": self._llm_output()}) as mocked:
            consolidator = NaptimeConsolidator(self.watch, self.pyramid, extraction="auto")
            self.assertTrue(consolidator.use_llm)
            processed = consolidator.scan_and_consolidate()
        self.assertEqual(processed, 1)
        mocked.assert_called_once()
        texts = [r["text"] for r in consolidator.distiller.data["memory_records"]]
        self.assertEqual(texts, ["LLM says: tabs preferred."])  # LLM path, not heuristic

    def test_llm_failure_falls_back_to_heuristic(self):
        with mock.patch.object(llm_extractor, "extract_batch",
                               side_effect=ExtractionError("batch timed out")):
            consolidator = NaptimeConsolidator(self.watch, self.pyramid, extraction="auto")
            processed = consolidator.scan_and_consolidate()
        self.assertEqual(processed, 1)
        texts = [r["text"] for r in consolidator.distiller.data["memory_records"]]
        self.assertIn("User prefers tabs over spaces.", texts)  # heuristic extracted

    def test_missing_credential_falls_back_to_heuristic(self):
        """The SDK raises TypeError at call time when no credential resolves;
        the sweep must degrade to the heuristic, not crash."""
        with mock.patch.object(llm_extractor, "extract_batch",
                               side_effect=TypeError("Could not resolve authentication method")):
            consolidator = NaptimeConsolidator(self.watch, self.pyramid, extraction="auto")
            processed = consolidator.scan_and_consolidate()
        self.assertEqual(processed, 1)
        texts = [r["text"] for r in consolidator.distiller.data["memory_records"]]
        self.assertIn("User prefers tabs over spaces.", texts)

    def test_invalid_llm_output_falls_back_per_file(self):
        with mock.patch.object(llm_extractor, "extract_batch",
                               return_value={"sess_notes": "not json at all"}):
            consolidator = NaptimeConsolidator(self.watch, self.pyramid, extraction="auto")
            consolidator.scan_and_consolidate()
        texts = [r["text"] for r in consolidator.distiller.data["memory_records"]]
        self.assertIn("User prefers tabs over spaces.", texts)

    def test_heuristic_mode_never_imports_llm_path(self):
        with mock.patch.object(llm_extractor, "extract_batch") as mocked:
            consolidator = NaptimeConsolidator(self.watch, self.pyramid,
                                               extraction="heuristic")
            self.assertFalse(consolidator.use_llm)
            consolidator.scan_and_consolidate()
        mocked.assert_not_called()

    def test_extraction_mode_validation(self):
        with self.assertRaises(ValueError):
            NaptimeConsolidator(self.watch, self.pyramid, extraction="magic")


class TestGuardedRead(unittest.TestCase):
    """Race-free read guard: validation happens on the open fd, so a watched
    entry swapped into a symlink cannot leak an out-of-root file."""

    def setUp(self):
        self.tmp = os.path.realpath(tempfile.mkdtemp(prefix="napmem_guard_"))
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        self.root = os.path.join(self.tmp, "vetted")
        self.watch = os.path.join(self.tmp, "watch")
        self.outside = os.path.join(self.tmp, "outside")
        for d in (self.root, self.watch, self.outside):
            os.makedirs(d)

    def test_legit_symlink_chain_reads(self):
        from naptime_consolidator import _read_file_guarded
        src = os.path.join(self.root, "notes.md")
        with open(src, "w", encoding="utf-8") as f:
            f.write("safe content")
        link = os.path.join(self.watch, "proj__notes.md")
        os.symlink(src, link)
        self.assertEqual(_read_file_guarded(link, [self.root]), "safe content")

    def test_unverifiable_fd_path_fails_closed(self):
        """No kernel-reported fd path -> refuse; a realpath fallback would
        reintroduce the TOCTOU race."""
        import naptime_consolidator as nc
        src = os.path.join(self.root, "notes.md")
        with open(src, "w", encoding="utf-8") as f:
            f.write("content")
        with mock.patch.object(nc, "_fd_true_path", return_value=None), \
             self.assertRaises(PermissionError):
            nc._read_file_guarded(src, [self.root])

    def test_out_of_root_symlink_refused(self):
        from naptime_consolidator import _read_file_guarded
        secret = os.path.join(self.outside, "id_ed25519")
        with open(secret, "w", encoding="utf-8") as f:
            f.write("PRIVATE KEY MATERIAL")
        link = os.path.join(self.watch, "proj__notes.md")
        os.symlink(secret, link)
        with self.assertRaises(PermissionError):
            _read_file_guarded(link, [self.root])

    def test_consolidator_skips_refused_file(self):
        from naptime_consolidator import ALLOWED_ROOTS_ENV
        secret = os.path.join(self.outside, "secret.txt")
        with open(secret, "w", encoding="utf-8") as f:
            f.write("PRIVATE")
        good = os.path.join(self.root, "good.md")
        with open(good, "w", encoding="utf-8") as f:
            f.write("# N\n- good fact stays here.\n")
        os.symlink(secret, os.path.join(self.watch, "evil.md"))
        os.symlink(good, os.path.join(self.watch, "good.md"))

        pyramid = os.path.join(self.tmp, "p.json")
        with mock.patch.dict(os.environ, {ALLOWED_ROOTS_ENV: self.root}):
            consolidator = NaptimeConsolidator(self.watch, pyramid,
                                               extraction="heuristic")
            processed = consolidator.scan_and_consolidate()
        self.assertEqual(processed, 1)
        texts = " ".join(r["text"] for r in consolidator.distiller.data["memory_records"])
        self.assertNotIn("PRIVATE", texts)
        self.assertIn("good fact", texts)

    def test_guard_fails_closed_without_env(self):
        """Unset env defaults to the watch dir as sole root (fail-closed);
        only an explicit 'off' disables the guard."""
        from naptime_consolidator import _resolve_allowed_roots
        with mock.patch.dict(os.environ, {}, clear=False):
            os.environ.pop("NAPMEM_ALLOWED_ROOTS", None)
            self.assertEqual(_resolve_allowed_roots(self.watch),
                             [os.path.realpath(self.watch)])
        with mock.patch.dict(os.environ, {"NAPMEM_ALLOWED_ROOTS": "off"}):
            self.assertEqual(_resolve_allowed_roots(self.watch), [])

    def test_default_guard_blocks_escaping_symlink(self):
        """Manual invocation with no env: mirrored-style symlink escaping the
        watch dir must be refused — the fail-open manual path is closed."""
        secret = os.path.join(self.outside, "secret.txt")
        with open(secret, "w", encoding="utf-8") as f:
            f.write("PRIVATE")
        os.symlink(secret, os.path.join(self.watch, "evil.md"))
        with open(os.path.join(self.watch, "plain.md"), "w", encoding="utf-8") as f:
            f.write("# N\n- plain fact stays here.\n")

        pyramid = os.path.join(self.tmp, "p2.json")
        with mock.patch.dict(os.environ, {}, clear=False):
            os.environ.pop("NAPMEM_ALLOWED_ROOTS", None)
            consolidator = NaptimeConsolidator(self.watch, pyramid,
                                               extraction="heuristic")
            processed = consolidator.scan_and_consolidate()
        self.assertEqual(processed, 1)
        texts = " ".join(r["text"] for r in consolidator.distiller.data["memory_records"])
        self.assertNotIn("PRIVATE", texts)
        self.assertIn("plain fact", texts)


class TestOllamaFailover(unittest.TestCase):
    def test_probe_returns_none_when_all_hosts_dead(self):
        # Ports 1 and 2 refuse connections immediately on loopback.
        self.assertIsNone(OllamaBackend.probe(
            urls=["http://127.0.0.1:1", "http://127.0.0.1:2"]))

    def test_embed_rejects_malformed_vectors(self):
        """Crafted responses (non-numeric or ragged vectors) must never reach
        the persistent vector cache."""
        backend = OllamaBackend("http://127.0.0.1:9999")
        for bad in (
            {"embeddings": [["a", "b"]]},                 # non-numeric
            {"embeddings": [[0.1, 0.2], [0.3]]},          # inconsistent dims
            {"embeddings": [[True, False]]},              # bools masquerading
            {"embeddings": [[]]},                         # empty vector
            {"embeddings": [{"v": 1}]},                   # wrong structure
        ):
            resp = mock.MagicMock()
            resp.__enter__ = lambda s: s
            resp.__exit__ = lambda s, *a: False
            with mock.patch("semantic_index.urllib.request.urlopen", return_value=resp), \
                 mock.patch("semantic_index.json.load", return_value=bad):
                texts = ["x", "y"] if len(bad["embeddings"]) == 2 else ["x"]
                with self.assertRaises(RuntimeError, msg=f"accepted {bad}"):
                    backend.embed(texts)

    def test_corrupt_cache_discarded_not_fatal(self):
        os.environ["NAPMEM_EMBED_BACKEND"] = "hashed"
        self.addCleanup(os.environ.pop, "NAPMEM_EMBED_BACKEND", None)
        tmp = tempfile.mkdtemp(prefix="napmem_cc_")
        self.addCleanup(shutil.rmtree, tmp, ignore_errors=True)
        pyramid = os.path.join(tmp, "p.json")
        with open(f"{pyramid}.embindex.json", "w", encoding="utf-8") as f:
            f.write('{"model": "x", "vectors": {}}GARBAGE-TRAILER')
        index = SemanticIndex(pyramid)  # must not raise
        self.assertEqual(index._cache["vectors"], {})

    def test_weighted_url_parsing_and_split(self):
        from semantic_index import _parse_weighted_urls
        hosts = _parse_weighted_urls(
            "http://a:1/=4, http://b:2=2 ,http://c:3,bad=weight=x")
        self.assertEqual(hosts[:3], [("http://a:1", 4), ("http://b:2", 2), ("http://c:3", 1)])
        pool = OllamaBackend(hosts=[("http://a:1", 3), ("http://b:2", 1)])
        chunks = pool._split_by_weight(list(range(8)))
        self.assertEqual(chunks, [("http://a:1", 0, 6), ("http://b:2", 6, 8)])
        self.assertEqual(pool.name, "ollama-pool[2]")

    def test_nearest_many_matches_singles(self):
        os.environ["NAPMEM_EMBED_BACKEND"] = "hashed"
        self.addCleanup(os.environ.pop, "NAPMEM_EMBED_BACKEND", None)
        tmp = tempfile.mkdtemp(prefix="napmem_nm_")
        self.addCleanup(shutil.rmtree, tmp, ignore_errors=True)
        index = SemanticIndex(os.path.join(tmp, "p.json"))
        records = [
            {"id": "r1", "text": "user prefers tabs over spaces always"},
            {"id": "r2", "text": "deployment pipeline uses github actions"},
        ]
        queries = ["User Prefers TABS over spaces always!",
                   "something entirely unrelated to anything"]
        batched = index.nearest_many(queries, records, threshold=0.8)
        singles = [index.nearest_record_id(q, records, 0.8) for q in queries]
        self.assertEqual(batched, singles)
        self.assertEqual(batched[0], "r1")
        self.assertIsNone(batched[1])

    def test_probe_order_prefers_first_responding_host(self):
        alive = "http://127.0.0.1:9999"

        def fake_urlopen(req, timeout=0):
            if alive in req.full_url:
                resp = mock.MagicMock()
                resp.status = 200
                resp.__enter__ = lambda s: resp
                resp.__exit__ = lambda s, *a: False
                return resp
            raise OSError("refused")

        with mock.patch("semantic_index.urllib.request.urlopen", side_effect=fake_urlopen):
            backend = OllamaBackend.probe(urls=["http://127.0.0.1:1", alive])
        self.assertIsNotNone(backend)
        self.assertEqual(backend.base_url, alive)


class TestMCPServer(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.mkdtemp(prefix="napmem_mcp_")
        cls.pyramid = os.path.join(cls.tmp, "p.json")
        distiller = MemoryPyramidDistiller(pyramid_path=cls.pyramid)
        with open(os.path.join(BASE_DIR, "sample_agent_memory.md"), encoding="utf-8") as f:
            distiller.ingest_session("sess_sample", "Sample",
                                     os.path.join(BASE_DIR, "sample_agent_memory.md"),
                                     f.read())

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.tmp, ignore_errors=True)

    def _rpc_session(self, messages):
        """Runs the server binary, sends JSON-RPC lines, returns responses."""
        env = dict(os.environ, NAPMEM_EMBED_BACKEND="hashed")
        proc = subprocess.run(
            [sys.executable, os.path.join(BASE_DIR, "napmem_mcp_server.py"),
             "--pyramid", self.pyramid],
            input="".join(json.dumps(m) + "\n" for m in messages),
            capture_output=True, text=True, timeout=60, env=env, check=False,
        )
        self.assertEqual(proc.returncode, 0, proc.stderr)
        return [json.loads(line) for line in proc.stdout.splitlines() if line.strip()]

    def test_full_handshake_list_and_call(self):
        responses = self._rpc_session([
            {"jsonrpc": "2.0", "id": 1, "method": "initialize",
             "params": {"protocolVersion": "2025-06-18", "capabilities": {},
                        "clientInfo": {"name": "test", "version": "0"}}},
            {"jsonrpc": "2.0", "method": "notifications/initialized"},
            {"jsonrpc": "2.0", "id": 2, "method": "tools/list"},
            {"jsonrpc": "2.0", "id": 3, "method": "tools/call",
             "params": {"name": "search_memory", "arguments": {"query": "NapMem"}}},
            {"jsonrpc": "2.0", "id": 4, "method": "tools/call",
             "params": {"name": "memory_stats", "arguments": {}}},
            {"jsonrpc": "2.0", "id": 5, "method": "tools/call",
             "params": {"name": "search_memory",
                        "arguments": {"query": "napmem pyramid", "semantic": True}}},
        ])
        by_id = {r["id"]: r for r in responses}
        # Notification produced no response.
        self.assertEqual(len(responses), 5)

        self.assertEqual(by_id[1]["result"]["serverInfo"]["name"], "napmem")
        tool_names = {t["name"] for t in by_id[2]["result"]["tools"]}
        self.assertEqual(tool_names, {"search_memory", "inspect_provenance",
                                      "get_topic_track", "memory_stats"})
        search_payload = json.loads(by_id[3]["result"]["content"][0]["text"])
        self.assertIn("matches", search_payload)
        self.assertFalse(by_id[3]["result"]["isError"])
        stats_payload = json.loads(by_id[4]["result"]["content"][0]["text"])
        self.assertIn("token_compression_ratio", stats_payload)
        semantic_payload = json.loads(by_id[5]["result"]["content"][0]["text"])
        self.assertTrue(semantic_payload["mode"].startswith("semantic:")
                        or semantic_payload["mode"] == "substring-fallback")

    def test_unknown_tool_and_method(self):
        responses = self._rpc_session([
            {"jsonrpc": "2.0", "id": 1, "method": "tools/call",
             "params": {"name": "not_a_tool", "arguments": {}}},
            {"jsonrpc": "2.0", "id": 2, "method": "resources/list"},
        ])
        by_id = {r["id"]: r for r in responses}
        self.assertTrue(by_id[1]["result"]["isError"])
        self.assertEqual(by_id[2]["error"]["code"], -32601)


if __name__ == "__main__":
    unittest.main(verbosity=1)
