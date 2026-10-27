#!/usr/bin/env python3
"""
Tests for the production-path extensions: LLM extractor parsing/validation,
semantic index + semantic dedup, and the MCP stdio server.

Network-free by design: the extractor tests exercise parsing and record
conversion (not the API), semantic tests force the stdlib hashed backend, and
the MCP test drives the real server binary over a subprocess pipe.
"""

import json
import io
import os
import shutil
import subprocess
import sys
import tempfile
import time
import types
import unittest
from unittest import mock

import llm_extractor
import ollama_extractor
from llm_extractor import ExtractionError, parse_extraction_output, units_to_records
from memory_pyramid_distiller import MemoryPyramidDistiller
from naptime_consolidator import NaptimeConsolidator
from ollama_extractor import _coerce_array_text, extract_ollama, parse_chat_hosts
from semantic_index import HashedTfBackend, OllamaBackend, SemanticIndex, cosine

BASE_DIR = os.path.dirname(os.path.abspath(__file__))

def setUpModule():
    # Every transport exercise installs its own fake. Unexpected requests must
    # fail here, regardless of the operator's configured Ollama endpoints.
    global _network_guard
    _network_guard = mock.patch(
        "urllib.request.urlopen",
        side_effect=AssertionError("Unexpected network request in extension tests"),
    )
    _network_guard.start()


def tearDownModule():
    _network_guard.stop()


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

    def test_decoder_limits_reject_one_session_without_abandoning_later_sessions(self):
        tmp = tempfile.mkdtemp(prefix="napmem_decode_limits_")
        self.addCleanup(shutil.rmtree, tmp, ignore_errors=True)
        hostile_outputs = ["[" + "9" * 5000 + "]", "[" * 20000 + "]" * 20000]
        for hostile in hostile_outputs:
            with self.subTest(size=len(hostile)):
                distiller = MemoryPyramidDistiller(os.path.join(tmp, "p.json"))
                with self.assertLogs("llm_extractor", level="ERROR"):
                    count, ingested = llm_extractor.ingest_extractions(
                        distiller,
                        {"bad": hostile, "good": json.dumps([self._unit()])},
                        {"bad": "bad.md", "good": "good.md"},
                    )
                self.assertEqual(count, 1)
                self.assertEqual(ingested, {"good"})
                self.assertEqual(
                    [record["source_anchor"]["session_id"]
                     for record in distiller.data["memory_records"]],
                    ["good"],
                )

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

    def test_rejection_logs_exclude_unit_content_and_invalid_values(self):
        marker = "SYNTHETIC_PRIVATE_MEMORY"
        units = [
            self._unit(type=marker, text=marker),
            self._unit(salience=marker, text=marker),
            self._unit(topic_slug={marker: marker}, text=marker),
        ]
        records, rejections = units_to_records(units, "s", "sample.md")
        self.assertEqual(records, [])
        self.assertEqual(len(rejections), 3)
        self.assertNotIn(marker, " ".join(rejections))
        with self.assertLogs("llm_extractor", level="WARNING") as logs:
            llm_extractor.ingest_extractions(
                mock.Mock(), {"s": json.dumps(units)}, {"s": "sample.md"}
            )
        self.assertNotIn(marker, " ".join(logs.output))
        self.assertIn("rejected unit", " ".join(logs.output))

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
        patcher = mock.patch.dict(os.environ, {"NAPMEM_EMBED_BACKEND": "hashed"})
        patcher.start()
        self.addCleanup(patcher.stop)
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

    def test_promotion_adopts_paraphrase_text(self):
        """F1 regression: a semantically-folded duplicate promoted to
        canonical must adopt its own wording — record text must be text its
        anchoring file actually contained — and stay stable on re-ingest."""
        distiller = MemoryPyramidDistiller(
            pyramid_path=self.pyramid, semantic_dedup=True, semantic_threshold=0.8
        )
        distiller.ingest_session("sess_a", "A", "a.md",
                                 "# N\n- User prefers tabs over spaces always.\n")
        b_text = "user Prefers TABS over spaces always"
        distiller.ingest_session("sess_b", "B", "b.md", f"# N\n- {b_text}\n")
        distiller.ingest_session("sess_a", "A2", "a.md",
                                 "# N\n- Something else entirely here.\n")
        promoted = next(r for r in distiller.data["memory_records"]
                        if r["source_anchor"]["session_id"] == "sess_b")
        self.assertEqual(promoted["text"], b_text)
        self.assertNotIn("paraphrase_text", promoted["source_anchor"])
        promoted_id = promoted["id"]
        # No-op re-ingest of sess_b keeps the promoted record's ID.
        distiller.ingest_session("sess_b", "B2", "b.md", f"# N\n- {b_text}\n")
        ids = [r["id"] for r in distiller.data["memory_records"]
               if r["source_anchor"]["session_id"] == "sess_b"]
        self.assertIn(promoted_id, ids)

    def test_noop_reingest_reclaims_duplicate_ids(self):
        """A session whose line folded into ANOTHER session's canonical must
        keep its duplicate ID across a no-op re-ingest (no churn to _NNN+1)."""
        shared = "- Uses PostgreSQL for storage.\n"
        distiller = MemoryPyramidDistiller(pyramid_path=self.pyramid)
        distiller.ingest_session("sess_a", "A", "a.md", "# N\n" + shared)
        distiller.ingest_session("sess_b", "B", "b.md", "# N\n" + shared + "- Second line here.\n")
        canonical = next(r for r in distiller.data["memory_records"]
                         if r["text"] == "Uses PostgreSQL for storage.")
        dup_id = canonical["duplicates"][0]
        distiller.ingest_session("sess_b", "B2", "b.md", "# N\n" + shared + "- Second line here.\n")
        canonical = next(r for r in distiller.data["memory_records"]
                         if r["text"] == "Uses PostgreSQL for storage.")
        self.assertEqual(canonical["duplicates"], [dup_id])

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
        # These cases test the Anthropic -> heuristic branch. Ollama transport
        # is exercised separately with mocked HTTP responses below.
        ollama_patcher = mock.patch.object(ollama_extractor, "ollama_available", return_value=False)
        ollama_patcher.start()
        self.addCleanup(ollama_patcher.stop)

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

    def test_client_constructor_failure_falls_back_to_heuristic(self):
        module = _fake_anthropic_module()
        module.Anthropic = mock.Mock(side_effect=module.AnthropicError("missing credentials"))
        with mock.patch.dict(sys.modules, {"anthropic": module}), \
             self.assertLogs("naptime_consolidator", level="ERROR") as logs:
            consolidator = NaptimeConsolidator(self.watch, self.pyramid, extraction="auto")
            self.assertEqual(consolidator.scan_and_consolidate(), 1)
        self.assertIn("LLM batch extraction failed", " ".join(logs.output))
        self.assertEqual(
            [r["text"] for r in consolidator.distiller.data["memory_records"]],
            ["User prefers tabs over spaces."],
        )

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

    def test_sibling_prefix_root_refused(self):
        """`/x/vetted-evil` must not satisfy root `/x/vetted` — the check is
        prefix-boundary-exact, and a regression to bare startswith must fail."""
        from naptime_consolidator import _read_file_guarded
        evil_dir = self.root + "-evil"
        os.makedirs(evil_dir)
        secret = os.path.join(evil_dir, "leak.md")
        with open(secret, "w", encoding="utf-8") as f:
            f.write("SIBLING SECRET")
        link = os.path.join(self.watch, "proj__leak.md")
        os.symlink(secret, link)
        with self.assertRaises(PermissionError):
            _read_file_guarded(link, [self.root])

    def test_fifo_refused_not_hung(self):
        """A FIFO planted in the watch dir must be refused, not block the
        daemon forever at open()."""
        from naptime_consolidator import _read_file_guarded
        fifo = os.path.join(self.watch, "hang.md")
        os.mkfifo(fifo)
        with self.assertRaises(PermissionError):
            _read_file_guarded(fifo, [self.root])

    def test_degenerate_roots_env_refused(self):
        """':::' must not silently equal 'off' (fail-open on a typo)."""
        from naptime_consolidator import _resolve_allowed_roots
        with mock.patch.dict(os.environ, {"NAPMEM_ALLOWED_ROOTS": ":::"}), \
             self.assertRaises(ValueError):
            _resolve_allowed_roots(self.watch)

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
        with mock.patch("urllib.request.urlopen", side_effect=OSError("refused")):
            self.assertIsNone(OllamaBackend.probe(
                urls=["http://127.0.0.1:1", "http://127.0.0.1:2"]))

    def test_embed_rejects_malformed_vectors(self):
        """Crafted responses (non-numeric or ragged vectors) must never reach
        the persistent vector cache."""
        backend = OllamaBackend("http://127.0.0.1:9999")
        backend.pool.retries = 0  # no backoff sleeps in the test
        for bad in (
            {"embeddings": [["a", "b"]]},                 # non-numeric
            {"embeddings": [[0.1, 0.2], [0.3]]},          # inconsistent dims
            {"embeddings": [[True, False]]},              # bools masquerading
            {"embeddings": [[]]},                         # empty vector
            {"embeddings": [{"v": 1}]},                   # wrong structure
            {"embeddings": [[float("nan"), 0.1]]},        # NaN poisoning
            {"embeddings": [[float("inf"), 0.1]]},        # Infinity poisoning
        ):
            resp = mock.MagicMock()
            resp.read.return_value = json.dumps(bad).encode()  # NaN/Infinity serialise as tokens
            resp.__enter__ = lambda s: s
            resp.__exit__ = lambda s, *a: False
            with mock.patch("urllib.request.urlopen", return_value=resp):
                texts = ["x", "y"] if len(bad["embeddings"]) == 2 else ["x"]
                with self.assertRaises(RuntimeError, msg=f"accepted {bad}"):
                    backend.embed(texts)

    def test_corrupt_cache_discarded_not_fatal(self):
        patcher = mock.patch.dict(os.environ, {"NAPMEM_EMBED_BACKEND": "hashed"})
        patcher.start()
        self.addCleanup(patcher.stop)
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
        self.assertEqual(pool.name, "ollama-pool[2]")
        self.assertEqual([(h.url, h.weight) for h in pool.pool.hosts],
                         [("http://a:1", 3), ("http://b:2", 1)])

    def test_embed_cuts_batch_by_total_weight_and_keeps_order(self):
        """8 texts over weights 3+1 -> 4 requests of 2; results stay in input order."""
        pool = OllamaBackend(hosts=[("http://a:1", 3), ("http://b:2", 1)])
        sizes = []

        def fake_urlopen(req, timeout=0):
            texts = json.loads(req.data)["input"]
            sizes.append(len(texts))
            resp = mock.MagicMock()
            resp.read.return_value = json.dumps(
                {"embeddings": [[float(t), 1.0] for t in texts]}).encode()
            resp.__enter__ = lambda s: s
            resp.__exit__ = lambda s, *a: False
            return resp

        with mock.patch("urllib.request.urlopen", side_effect=fake_urlopen):
            out = pool.embed([str(i) for i in range(8)])
        self.assertEqual(sorted(sizes), [2, 2, 2, 2])
        self.assertEqual([v[0] for v in out], [float(i) for i in range(8)])

    def test_nearest_many_matches_singles(self):
        patcher = mock.patch.dict(os.environ, {"NAPMEM_EMBED_BACKEND": "hashed"})
        patcher.start()
        self.addCleanup(patcher.stop)
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
                resp.read.return_value = b'{"models": []}'
                resp.__enter__ = lambda s: resp
                resp.__exit__ = lambda s, *a: False
                return resp
            raise OSError("refused")

        with mock.patch("urllib.request.urlopen", side_effect=fake_urlopen):
            backend = OllamaBackend.probe(urls=["http://127.0.0.1:1", alive])
        self.assertIsNotNone(backend)
        self.assertEqual(backend.base_url, alive)


class TestRetrievalSourceFiles(unittest.TestCase):
    @unittest.skipUnless(hasattr(os, "mkfifo"), "requires POSIX named pipes")
    def test_stats_skip_fifo_and_other_unreadable_sources_without_blocking(self):
        tmp = tempfile.mkdtemp(prefix="napmem_stats_sources_")
        self.addCleanup(shutil.rmtree, tmp, ignore_errors=True)
        fifo = os.path.join(tmp, "source.fifo")
        os.mkfifo(fifo)
        invalid_utf8 = os.path.join(tmp, "invalid.md")
        with open(invalid_utf8, "wb") as f:
            f.write(b"\xff")
        valid = os.path.join(tmp, "valid.md")
        with open(valid, "w", encoding="utf-8") as f:
            f.write("Readable source words.")
        pyramid = os.path.join(tmp, "p.json")
        distiller = MemoryPyramidDistiller(pyramid)
        distiller.data["raw_conversations"] = [
            {"session_id": "fifo", "file_path": fifo},
            {"session_id": "directory", "file_path": tmp},
            {"session_id": "invalid_utf8", "file_path": invalid_utf8},
            {"session_id": "missing", "file_path": os.path.join(tmp, "absent.md")},
            {"session_id": "valid", "file_path": valid},
        ]
        distiller.save()
        code = (
            "import json, sys; from napmem_retrieval_agent import NapMemRetrievalAgent; "
            "print(json.dumps(NapMemRetrievalAgent(sys.argv[1]).compute_context_budget_savings()))"
        )
        try:
            result = subprocess.run(
                [sys.executable, "-c", code, pyramid], cwd=BASE_DIR,
                capture_output=True, text=True, timeout=3, check=False,
            )
        except subprocess.TimeoutExpired:
            self.fail("Memory statistics blocked on a FIFO source")
        self.assertEqual(result.returncode, 0, result.stderr)
        stats = json.loads(result.stdout)
        self.assertEqual(stats["sessions_compared"], ["valid"])
        self.assertCountEqual(
            stats["sessions_missing_raw_file"], ["fifo", "directory", "invalid_utf8", "missing"]
        )
        self.assertGreater(stats["raw_memory_estimated_tokens"], 0)


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
        # Env pins the hashed backend, so the mode is deterministic — a
        # disjunction here would pass even with the semantic path broken.
        self.assertEqual(semantic_payload["mode"], "semantic:hashed-tf")

    def test_malformed_input_never_kills_server(self):
        """Crash-class regression: batch arrays, non-dict params, wrong-typed
        arguments, missing method — server must answer every one and keep
        serving (final ping proves the loop survived)."""
        responses = self._rpc_session([
            [{"jsonrpc": "2.0", "id": 1, "method": "ping"}],          # batch array
            {"jsonrpc": "2.0", "id": 2, "method": "initialize", "params": []},
            {"jsonrpc": "2.0", "id": 3, "method": "tools/call",
             "params": {"name": "search_memory", "arguments": "notadict"}},
            {"jsonrpc": "2.0", "id": 4, "method": "tools/call",
             "params": {"name": "search_memory", "arguments": {"query": 123}}},
            {"jsonrpc": "2.0", "id": 5},                               # no method
            {"jsonrpc": "2.0", "id": 6, "method": "initialize",
             "params": {"protocolVersion": "9999-12-31"}},
            {"jsonrpc": "2.0", "id": 7, "method": "ping"},
        ])
        by_id = {r.get("id"): r for r in responses}
        self.assertEqual(by_id[None]["error"]["code"], -32600)         # batch rejected
        self.assertEqual(by_id[2]["error"]["code"], -32602)              # invalid params
        self.assertEqual(by_id[3]["error"]["code"], -32602)
        self.assertTrue(by_id[4]["result"]["isError"])                 # in-band tool error
        self.assertEqual(by_id[5]["error"]["code"], -32600)
        self.assertEqual(by_id[6]["result"]["protocolVersion"], "2025-06-18")  # negotiated down
        self.assertIn("result", by_id[7])                              # loop survived

    def test_unknown_tool_and_method(self):
        responses = self._rpc_session([
            {"jsonrpc": "2.0", "id": 1, "method": "tools/call",
             "params": {"name": "not_a_tool", "arguments": {}}},
            {"jsonrpc": "2.0", "id": 2, "method": "resources/list"},
        ])
        by_id = {r["id"]: r for r in responses}
        self.assertTrue(by_id[1]["result"]["isError"])
        self.assertEqual(by_id[2]["error"]["code"], -32601)


class TestOllamaExtraction(unittest.TestCase):
    def _chat_response(self, content):
        body = json.dumps({"message": {"role": "assistant", "content": content}})
        resp = mock.MagicMock()
        resp.read.return_value = body.encode()
        resp.__enter__ = lambda s: s
        resp.__exit__ = lambda s, *a: False
        return resp

    def _unit_array_text(self, text="Ollama says: tabs preferred."):
        return json.dumps([{
            "type": "fact", "text": text,
            "salience": "high", "topic_slug": "prefs",
            "source_anchor": {"heading": "Prefs", "line_range": "L2"},
        }])

    def test_parse_chat_hosts_orders_and_validates(self):
        hosts = parse_chat_hosts("http://a:1=m1, http://b:2=m2:7b")
        self.assertEqual(hosts, [("http://a:1", "m1"), ("http://b:2", "m2:7b")])
        with self.assertRaises(ValueError):
            parse_chat_hosts("http://a:1")  # no model
        with self.assertRaises(ValueError):
            parse_chat_hosts(",")  # no hosts at all

    def test_coerce_array_text_unwraps_single_list_object(self):
        arr = self._unit_array_text()
        wrapped = json.dumps({"units": json.loads(arr)})
        self.assertEqual(json.loads(_coerce_array_text(wrapped)), json.loads(arr))
        # A lone bare unit object (json-mode grammars force a top-level
        # object) is wrapped into a one-element array.
        lone = json.loads(arr)[0]
        self.assertEqual(json.loads(_coerce_array_text(json.dumps(lone))), [lone])
        # Bare arrays and non-JSON pass through untouched.
        self.assertEqual(_coerce_array_text(arr), arr)
        self.assertEqual(_coerce_array_text("not json"), "not json")
        # Ambiguous objects (two lists) are left for the strict parser to
        # reject rather than guessed at.
        ambiguous = json.dumps({"a": [], "b": []})
        self.assertEqual(_coerce_array_text(ambiguous), ambiguous)

    def test_extract_ollama_fails_over_and_benches_dead_host(self):
        import urllib.error
        hosts = [("http://dead:1", "m"), ("http://live:2", "m")]
        calls = []

        def fake_urlopen(req, timeout=None):
            calls.append(req.full_url)
            if "dead" in req.full_url:
                raise urllib.error.URLError("refused")
            return self._chat_response(self._unit_array_text())

        with mock.patch("urllib.request.urlopen",
                               side_effect=fake_urlopen):
            outputs = extract_ollama(
                {"sess_a": "prompt a", "sess_b": "prompt b"}, hosts)
        self.assertEqual(set(outputs), {"sess_a", "sess_b"})
        # The dead host is benched after its first failure: exactly one
        # attempt against it, both extractions served by the live host.
        self.assertEqual([u for u in calls if "dead" in u],
                         ["http://dead:1/api/chat"])
        self.assertEqual([u for u in calls if "live" in u],
                         ["http://live:2/api/chat"] * 2)

    def test_chat_strips_think_block(self):
        content = "<think>reasoning here</think>\n" + self._unit_array_text()

        def fake_urlopen(req, timeout=None):
            return self._chat_response(content)

        with mock.patch("urllib.request.urlopen",
                               side_effect=fake_urlopen):
            outputs = extract_ollama({"s": "p"}, [("http://h:1", "m")])
        self.assertEqual(json.loads(outputs["s"]), json.loads(self._unit_array_text()))

    def test_chat_preserves_think_tags_inside_json_strings(self):
        content = self._unit_array_text("User stores <think>literal XML content</think> in notes.")
        with mock.patch("urllib.request.urlopen", return_value=self._chat_response(content)):
            outputs = extract_ollama({"s": "p"}, [("http://h:1", "m")])
        self.assertEqual(json.loads(outputs["s"]), json.loads(content))

    def test_missing_model_does_not_bench_other_models_on_same_host(self):
        import urllib.error
        models = []

        def fake_urlopen(req, timeout=None):
            model = json.loads(req.data)["model"]
            models.append(model)
            if model == "missing":
                raise urllib.error.HTTPError(
                    req.full_url, 404, "model absent", {},
                    io.BytesIO(b'{"error":"model missing"}'),
                )
            return self._chat_response(self._unit_array_text())

        with mock.patch("urllib.request.urlopen", side_effect=fake_urlopen):
            outputs = extract_ollama(
                {"s1": "p", "s2": "p"},
                [("http://same:1", "missing"), ("http://same:1", "available")],
            )
        self.assertEqual(set(outputs), {"s1", "s2"})
        self.assertEqual(models, ["missing", "available", "available"])

    def test_extract_ollama_omits_sessions_all_hosts_failed(self):
        import urllib.error
        with mock.patch("urllib.request.urlopen",
                               side_effect=urllib.error.URLError("refused")):
            outputs = extract_ollama({"sess_a": "p"}, [("http://dead:1", "m")])
        self.assertEqual(outputs, {})


class TestConsolidatorOllamaWiring(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="napmem_ollama_")
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        self.watch = os.path.join(self.tmp, "logs")
        os.makedirs(self.watch)
        self.pyramid = os.path.join(self.tmp, "p.json")
        with open(os.path.join(self.watch, "notes.md"), "w", encoding="utf-8") as f:
            f.write("# Prefs\n- User prefers tabs over spaces.\n")

    def _ollama_output(self):
        return json.dumps([{
            "type": "fact", "text": "Ollama says: tabs preferred.",
            "salience": "high", "topic_slug": "prefs",
            "source_anchor": {"heading": "Prefs", "line_range": "L2"},
        }])

    def test_ollama_mode_ingests_without_anthropic(self):
        with mock.patch.object(ollama_extractor, "ollama_available", return_value=True), \
             mock.patch.object(ollama_extractor, "extract_ollama",
                               return_value={"sess_notes": self._ollama_output()}) as mocked:
            consolidator = NaptimeConsolidator(self.watch, self.pyramid,
                                               extraction="ollama")
            self.assertFalse(consolidator.use_llm)
            self.assertTrue(consolidator.use_ollama)
            processed = consolidator.scan_and_consolidate()
        self.assertEqual(processed, 1)
        mocked.assert_called_once()
        texts = [r["text"] for r in consolidator.distiller.data["memory_records"]]
        self.assertEqual(texts, ["Ollama says: tabs preferred."])

    def test_deep_ollama_json_falls_back_and_preserves_later_file(self):
        with open(os.path.join(self.watch, "second.md"), "w", encoding="utf-8") as source:
            source.write("# Second\n- A second source.\n")
        client = mock.Mock()
        client.chat.side_effect = ["[" * 20000 + "]" * 20000, self._ollama_output()]
        with mock.patch.object(ollama_extractor, "ollama_available", return_value=True), \
                mock.patch.object(ollama_extractor, "parse_chat_hosts",
                                  return_value=[("http://offline.invalid:1", "fake")]), \
                mock.patch.object(ollama_extractor, "_client_for", return_value=client), \
                self.assertLogs(llm_extractor.logger, level="ERROR"):
            consolidator = NaptimeConsolidator(self.watch, self.pyramid, extraction="ollama")
            self.assertEqual(consolidator.scan_and_consolidate(), 2)
        self.assertEqual(client.chat.call_count, 2)
        records = consolidator.distiller.data["memory_records"]
        by_session = {record["source_anchor"]["session_id"]: record["text"] for record in records}
        self.assertEqual(by_session["sess_notes"], "User prefers tabs over spaces.")
        self.assertEqual(by_session["sess_second"], "Ollama says: tabs preferred.")

    def test_ollama_unreachable_falls_back_to_heuristic(self):
        with mock.patch.object(ollama_extractor, "ollama_available", return_value=False):
            consolidator = NaptimeConsolidator(self.watch, self.pyramid,
                                               extraction="ollama")
            processed = consolidator.scan_and_consolidate()
        self.assertEqual(processed, 1)
        texts = [r["text"] for r in consolidator.distiller.data["memory_records"]]
        self.assertIn("User prefers tabs over spaces.", texts)

    def test_auto_mode_skips_ollama_when_anthropic_succeeds(self):
        llm_output = json.dumps([{
            "type": "fact", "text": "LLM says: tabs preferred.",
            "salience": "high", "topic_slug": "prefs",
            "source_anchor": {"heading": "Prefs", "line_range": "L2"},
        }])
        with mock.patch.dict(sys.modules, {"anthropic": _fake_anthropic_module()}), \
             mock.patch.object(llm_extractor, "extract_batch",
                               return_value={"sess_notes": llm_output}), \
             mock.patch.object(ollama_extractor, "extract_ollama") as ollama_mock:
            consolidator = NaptimeConsolidator(self.watch, self.pyramid,
                                               extraction="auto")
            consolidator.scan_and_consolidate()
        ollama_mock.assert_not_called()


class TestSweepStatePersistence(unittest.TestCase):
    """The persistent hash gate: touched-but-unchanged files must not
    re-extract across PROCESS restarts (systemd --once mode), in either
    timestamp direction; changed content must."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="napmem_state_")
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        self.watch = os.path.join(self.tmp, "logs")
        os.makedirs(self.watch)
        self.pyramid = os.path.join(self.tmp, "p.json")
        self.state = os.path.join(self.tmp, "state.json")
        self.fpath = os.path.join(self.watch, "notes.md")
        with open(self.fpath, "w", encoding="utf-8") as f:
            f.write("# Prefs\n- User prefers tabs over spaces.\n")

    def _fresh(self):
        return NaptimeConsolidator(self.watch, self.pyramid,
                                   extraction="heuristic",
                                   state_path=self.state)

    def test_touched_but_unchanged_skips_across_restarts(self):
        self.assertEqual(self._fresh().scan_and_consolidate(), 1)
        os.utime(self.fpath, (time.time() + 60, time.time() + 60))
        self.assertEqual(self._fresh().scan_and_consolidate(), 0)
        # Older-timestamp restore must also skip (hash, not mtime ordering).
        os.utime(self.fpath, (1000, 1000))
        self.assertEqual(self._fresh().scan_and_consolidate(), 0)

    def test_changed_content_still_extracts(self):
        self.assertEqual(self._fresh().scan_and_consolidate(), 1)
        with open(self.fpath, "a", encoding="utf-8") as f:
            f.write("- Also: never use sudo in scripts.\n")
        self.assertEqual(self._fresh().scan_and_consolidate(), 1)

    def test_corrupt_state_file_is_tolerated(self):
        with open(self.state, "w", encoding="utf-8") as f:
            f.write("{corrupt")
        self.assertEqual(self._fresh().scan_and_consolidate(), 1)

    def test_invalid_state_shapes_are_ignored_with_safe_warning(self):
        marker = "SYNTHETIC_PRIVATE_STATE"
        for index, state in enumerate((
            [], {"files": []}, {"files": {self.fpath: marker}},
            {"files": {self.fpath: {"mtime": marker, "sha256": marker}}},
        )):
            with self.subTest(state=type(state).__name__):
                with open(self.state, "w", encoding="utf-8") as f:
                    json.dump(state, f)
                with self.assertLogs("naptime_consolidator", level="WARNING") as logs:
                    consolidator = self._fresh()
                self.assertEqual(consolidator.file_hashes, {})
                self.assertNotIn(marker, " ".join(logs.output))
                # The durable registry, unlike the legacy sweep cache, remains valid.
                self.assertEqual(consolidator.scan_and_consolidate(), int(index == 0))

    def test_missing_store_is_rebuilt_despite_persisted_sweep_state(self):
        self.assertEqual(self._fresh().scan_and_consolidate(), 1)
        os.remove(self.pyramid)
        restored = self._fresh()
        self.assertEqual(restored.scan_and_consolidate(), 1)
        self.assertEqual(len(restored.distiller.data["memory_records"]), 1)
        self.assertTrue(os.path.exists(self.pyramid))

    def test_replaced_empty_store_is_rebuilt_despite_sweep_state(self):
        self.assertEqual(self._fresh().scan_and_consolidate(), 1)
        empty = MemoryPyramidDistiller(self.pyramid)
        empty.data["memory_records"] = []
        empty.data["raw_conversations"] = []
        empty.rebuild_higher_layers()
        empty.save()
        restored = self._fresh()
        self.assertEqual(restored.scan_and_consolidate(), 1)
        self.assertEqual(len(restored.distiller.data["memory_records"]), 1)

    def test_state_prunes_deleted_files(self):
        self._fresh().scan_and_consolidate()
        os.remove(self.fpath)
        c = self._fresh()
        c.scan_and_consolidate()
        with open(self.state, encoding="utf-8") as f:
            self.assertEqual(json.load(f)["files"], {})


if __name__ == "__main__":
    unittest.main(verbosity=1)
