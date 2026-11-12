"""Synthetic adversarial maintenance regressions; no providers or live stores."""

import copy
import json
import os
from pathlib import Path
import tempfile
import tracemalloc
import unittest
from unittest import mock

from memory_pyramid_distiller import MemoryPyramidDistiller
from napmem_config import resolve_config
from napmem_jobs import JobQueue
import napmem_controls as controls
import napmem_eval as evaluation
from napmem_inspector import source_diff
from napmem_evidence import verify_evidence


class MaintenanceRegressions(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.path = str(self.root / "store.json")
        self.store = MemoryPyramidDistiller(self.path)
        self.text = "I prefer Vim."

    def units(self, session="a", **fields):
        unit = self.store.extract_atomic_units(
            self.text, session, str(self.root / "notes.md")
        )[0]
        unit.update(fields)
        return unit

    def test_same_text_different_contexts_keep_ids_after_reordered_reingest(self):
        for field, values in [
            ("scope", ["project:a", "project:b"]),
            ("subject", ["editor:a", "editor:b"]),
        ]:
            with self.subTest(field=field):
                self.store = MemoryPyramidDistiller(str(self.root / (field + ".json")))
                units = [
                    self.units(
                        **{
                            field: v,
                            "id": f"rec_a_{n:03d}",
                            "canonical": f"rec_a_{n:03d}",
                        }
                    )
                    for n, v in enumerate(values, 1)
                ]
                self.store.ingest_session_records(
                    "a", "A", "notes.md", copy.deepcopy(units), source_content=self.text
                )
                before = {r[field]: r["id"] for r in self.store.data["memory_records"]}
                self.store.ingest_session_records(
                    "a",
                    "A",
                    "notes.md",
                    copy.deepcopy(units[::-1]),
                    source_content=self.text,
                )
                self.assertEqual(
                    {r[field]: r["id"] for r in self.store.data["memory_records"]},
                    before,
                )

    def test_unrelated_empty_source_survives_noop_exclusion(self):
        self.store.ingest_session("empty", "Empty", str(self.root / "empty.md"), "")
        before = copy.deepcopy(self.store.data["raw_conversations"])
        self.store.control("exclude", source=str(self.root / "absent.md"))
        self.assertEqual(self.store.data["raw_conversations"], before)

    def test_correction_cannot_close_a_text_fingerprint_cycle(self):
        self.store.ingest_session("a", "A", "notes.md", self.text, scope="project:a")
        rid = self.store.data["memory_records"][0]["id"]
        first = self.store.control("correct", record_id=rid, value="I prefer Emacs.")
        replacement = next(
            r
            for r in self.store.data["memory_records"]
            if r.get("authority") == "operator"
        )
        before = copy.deepcopy(self.store.data)
        with self.assertRaisesRegex(ValueError, "cycle|previously corrected"):
            self.store.control("correct", record_id=replacement["id"], value=self.text)
        self.assertEqual(self.store.data, before)
        self.assertTrue(first["affected_ids"])

    def test_preview_includes_all_fingerprint_overrides(self):
        units = [
            self.units(
                scope="project:a",
                subject=s,
                id=f"rec_a_{n:03d}",
                canonical=f"rec_a_{n:03d}",
            )
            for n, s in enumerate(["one", "two"], 1)
        ]
        self.store.ingest_session_records(
            "a", "A", "notes.md", units, source_content=self.text
        )
        preview = self.store.control("pin", record_id="rec_a_001", dry_run=True)
        self.assertEqual(set(preview["affected_ids"]), {"rec_a_001", "rec_a_002"})
        self.store.control(
            "pin", record_id="rec_a_001", preview_token=preview["preview_token"]
        )
        self.assertTrue(all(r["pinned"] for r in self.store.data["memory_records"]))

    def test_alias_family_connectivity_uses_linear_memory(self):
        aliases = [f"alias_{n}" for n in range(1000)]
        data = {"memory_records": [{"id": "root", "duplicates": aliases}]}
        control = {"assertions": [], "corrections": {}, "overrides": {}}
        tracemalloc.start()
        try:
            self.assertEqual(
                controls._family(data, control, "root"), {"root", *aliases}
            )
            _, peak = tracemalloc.get_traced_memory()
        finally:
            tracemalloc.stop()
        self.assertLess(peak, 10 * 1024 * 1024)

    def test_configuration_overrides_invalid_lower_priority_paths(self):
        file = self.root / "config.toml"
        file.write_text(
            '[napmem]\nsource_roots = 42\npyramid = 12\nmetrics_enabled = "bad"\n'
        )
        config = resolve_config(
            {
                "config": str(file),
                "pyramid": self.path,
                "source_roots": [str(self.root)],
                "metrics_enabled": False,
            },
            environ={},
        )
        self.assertEqual(config.source_roots, (str(self.root),))
        self.assertEqual(config.pyramid, self.path)

    def test_eval_rejects_nonfinite_gate_values(self):
        report = {
            "fixture_sha256": "x",
            "split": "heldout",
            "top_k": 5,
            "as_of": "2026-01-01T00:00:00Z",
            "metrics": {"recall_at_5": 0.0},
            "by_category": {},
        }
        for value in (float("nan"), float("inf"), float("-inf")):
            with self.subTest(value=value):
                baseline = copy.deepcopy(report)
                baseline["metrics"]["recall_at_5"] = value
                with self.assertRaises(ValueError):
                    evaluation.compare_baseline(report, baseline)
                with self.assertRaises(ValueError):
                    evaluation.compare_baseline(report, report, tolerance=value)

    def test_eval_rejects_invalid_nested_record_and_metric_cutoff(self):
        with self.assertRaises(ValueError):
            evaluation.extract_result_ids({"evidence": [{"record": None}]})
        with self.assertRaises(ValueError):
            evaluation.score_query(
                {"expected_ids": [], "category": "fact"},
                [],
                {},
                as_of="2026-01-01T00:00:00Z",
                k=6,
            )

    def test_unverified_surrogate_quote_fails_closed(self):
        result = verify_evidence(
            {"evidence": {"status": "unverified", "quote": "\ud800"}}
        )
        self.assertEqual(result["status"], "unverified")

    def test_diff_preserves_non_lf_characters_as_source_bytes(self):
        diff = source_diff("a\vb\n", "a\vc\n")
        self.assertEqual(diff["old_lines"], 1)
        self.assertEqual(diff["new_lines"], 1)
        self.assertIn("-a\vb\n", diff["records"][0]["diff"])
        self.assertNotIn("No newline", diff["records"][0]["diff"])

    def queue_job(self, **kwargs):
        self.source = self.root / "notes.md"
        self.source.write_text(self.text)
        self.queue = JobQueue(self.path)
        return self.queue.enqueue(
            session_id="a",
            source_path=str(self.source),
            source_content=self.text,
            **kwargs,
        )

    def test_ambiguous_submission_cannot_be_retried(self):
        job = self.queue_job(backend="anthropic", model="fixture-model")
        client = mock.Mock()
        client.messages.batches.create.side_effect = OSError(
            "response lost after acceptance"
        )
        receipt = self.queue.submit(client)[0]
        self.assertEqual(receipt["error_code"], "SubmissionOutcomeUnknown")
        with self.assertRaisesRegex(ValueError, "Unknown|unknown|ambiguous"):
            self.queue.retry(job["id"], source_content=self.text)
        self.assertEqual(self.queue.submit(client), [])
        self.assertEqual(client.messages.batches.create.call_count, 1)

    def test_expired_worker_cannot_mutate_canonical_store(self):
        job = self.queue_job()
        self.queue.run(self.store)
        claimed = self.queue.claim(
            "worker-a", states=("ready",), now=1, lease_seconds=1
        )
        self.assertIsNotNone(claimed)
        before = copy.deepcopy(self.store.data)
        with self.assertRaisesRegex(ValueError, "lease|Lease"):
            self.queue.commit(job["id"], self.store, worker="worker-a")
        self.assertEqual(self.store.data, before)
        self.assertNotIn(job["id"], self.store.data.get("applied_jobs", []))

    def test_collection_error_retains_provider_handle_and_resumes_without_resubmit(self):
        job = self.queue_job(backend="anthropic", model="fixture")
        client = mock.Mock()
        handle = {"batch_id": "batch-existing", "id_to_session": {"req_00000": "a"}}
        with mock.patch("llm_extractor.submit_batch", return_value=handle):
            self.queue.submit(client)
        with mock.patch("llm_extractor.collect_batch", side_effect=OSError("transient fixture failure")):
            self.queue.collect(client)
        retained = self.queue.get(job["id"], include_payload=True)
        self.assertEqual(retained["state"], "submitted")
        self.assertEqual(json.loads(retained["batch_handle"]), handle)
        with self.assertRaises(ValueError):
            self.queue.retry(job["id"], source_content=self.text)
        with mock.patch("llm_extractor.submit_batch") as submit:
            self.assertEqual(self.queue.submit(client), [])
            submit.assert_not_called()
        output = {"ready": True, "outputs": {"a": "[]"}}
        with mock.patch("llm_extractor.collect_batch", return_value=output) as collect:
            self.queue.collect(client)
            self.assertEqual(collect.call_args.args[1], handle)
        self.assertEqual(self.queue.get(job["id"])["state"], "ready")

    def test_model_cli_refuses_conflicting_session_before_provider_calls(self):
        import napmem_cli as cli
        from types import SimpleNamespace
        self.store.ingest_session("a", "Original", str(self.root / "original.md"), "I prefer Vim.")
        source = self.root / "other.md"
        source.write_text("I prefer Emacs.")
        before = Path(self.path).read_bytes()
        args = SimpleNamespace(format="markdown", enqueue=False, input=str(source), session_id="a", title=None)
        config = resolve_config({"pyramid": self.path, "mode": "remote", "extraction": "anthropic", "anthropic_model": "fixture"}, environ={})
        with mock.patch.object(cli, "_anthropic_client", side_effect=AssertionError("provider reached before ownership check")) as provider:
            with self.assertRaisesRegex(ValueError, "belongs to another source"):
                cli._ingest(config, args)
            provider.assert_not_called()
        self.assertEqual(Path(self.path).read_bytes(), before)

    def test_durable_job_cannot_replace_another_source_session(self):
        self.store.ingest_session("a", "Original", str(self.root / "original.md"), "I prefer Vim.")
        job = self.queue_job()
        self.queue.run(self.store)
        before = Path(self.path).read_bytes()
        with self.assertRaisesRegex(ValueError, "belongs to another source"):
            self.queue.commit(job["id"], self.store)
        self.assertEqual(Path(self.path).read_bytes(), before)

    def test_expired_extraction_worker_cannot_publish_ready_result(self):
        job = self.queue_job()
        clock = [1000.0]
        extract = self.store.extract_atomic_units
        def late_result(*args):
            result = extract(*args)
            clock[0] += 61
            return result
        with mock.patch("napmem_jobs.time.time", side_effect=lambda: clock[0]), \
                mock.patch.object(self.store, "extract_atomic_units", side_effect=late_result):
            with self.assertRaisesRegex(ValueError, "lease|Lease"):
                self.queue.run(self.store, worker="expired-worker")
        retained = self.queue.get(job["id"])
        self.assertEqual(retained["state"], "queued")
        self.assertEqual(self.queue.claim("replacement", now=1062)["id"], job["id"])
        self.assertEqual(self.store.data["memory_records"], [])

    def test_provenance_honors_source_safety_for_records_and_aliases(self):
        from napmem_retrieval_agent import NapMemRetrievalAgent
        self.store.ingest_session("a", "A", "notes.md", self.text, scope="project:a")
        original = copy.deepcopy(self.store.data)
        rid = original["memory_records"][0]["id"]
        # Establish the permitted positive control before applying each marker.
        self.assertEqual(NapMemRetrievalAgent(self.path).inspect_provenance(rid, scope="project:a")["text"], self.text)
        for marker in ("deleted", "anchor", "alias"):
            with self.subTest(marker=marker):
                self.store.data = copy.deepcopy(original)
                row = self.store.data["memory_records"][0]
                selected = rid
                if marker == "deleted":
                    row["source_status"] = "deleted"
                elif marker == "anchor":
                    row["source_anchor"]["excluded"] = True
                else:
                    selected = "unsafe_alias"
                    row["duplicates"] = [selected]
                    row["duplicate_anchors"] = {selected: {
                        **copy.deepcopy(row["source_anchor"]), "excluded": True,
                        "assertion": {key: copy.deepcopy(row[key]) for key in ("scope", "memory_kind", "status", "review_status", "authority", "created_at")}}}
                fixture = self.root / (marker + ".json")
                fixture.write_text(json.dumps(self.store.data))
                result = NapMemRetrievalAgent(str(fixture)).inspect_provenance(selected, scope="project:a")
                self.assertIn("error", result)
                self.assertNotIn(self.text, json.dumps(result))

    def test_renew_rejects_invalid_duration(self):
        job = self.queue_job()
        self.assertEqual(self.queue.claim("worker")["id"], job["id"])
        self.assertTrue(self.queue.renew(job["id"], "worker", lease_seconds=30))
        for duration in [True, 0, -1, float("nan"), float("inf"), 86401]:
            with self.subTest(duration=duration), self.assertRaises(ValueError):
                self.queue.renew(job["id"], "worker", lease_seconds=duration)

    def test_unrelated_quote_cannot_support_a_profile(self):
        import hashlib
        from napmem_model import normalize_record, build_derived

        row = normalize_record(
            {
                "id": "r",
                "text": "I prefer Vim.",
                "memory_kind": "preference",
                "review_status": "approved",
                "evidence": {
                    "status": "verified",
                    "assertion_support": "verbatim",
                    "quote": "I prefer Emacs.",
                    "quote_sha256": hashlib.sha256(b"I prefer Emacs.").hexdigest(),
                    "source_sha256": "a" * 64,
                },
            }
        )
        for proof in (row["evidence"], {}, {"status": "unverified", "reason": "unsupported"}):
            with self.subTest(proof=proof):
                candidate = copy.deepcopy(row)
                candidate["evidence"] = proof
                data = {"memory_records": [candidate]}
                build_derived(data)
                self.assertEqual(data["user_profiles"], [])

    def test_rejected_successor_does_not_retire_an_active_assertion(self):
        from napmem_model import normalize_record, apply_supersession

        data = {
            "memory_records": [
                normalize_record({"id": "old", "text": "Original"}),
                normalize_record(
                    {
                        "id": "new",
                        "text": "Rejected",
                        "review_status": "rejected",
                        "supersedes": ["old"],
                    }
                ),
            ]
        }
        apply_supersession(data)
        self.assertEqual(data["memory_records"][0]["status"], "active")

    def test_utc_overflow_is_a_validation_error(self):
        from napmem_model import parse_time

        with self.assertRaises(ValueError):
            parse_time("0001-01-01T00:00:00+14:00")

    def test_store_rejects_numeric_overflow_in_json(self):
        from napmem_storage import read_snapshot

        Path(self.path).write_text('{"x":1e999}')
        with self.assertRaises(ValueError):
            read_snapshot(self.path)

    def test_backend_error_code_is_sanitized_without_losing_request(self):
        import io
        import time
        import napmem_mcp_failover as proxy_module

        output = io.StringIO()
        proxy = proxy_module.FailoverProxy(None, [], stdout=output)
        proxy.gen = 1
        proxy.mode = "remote"
        request = {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "tools/call",
            "params": {"name": "memory_stats"},
        }
        proxy.pending[proxy_module._id_key(1)] = (
            json.dumps(request),
            "tools/call",
            time.monotonic(),
        )
        response = {
            "jsonrpc": "2.0",
            "id": 1,
            "result": {"content": [], "structuredContent": {"error": {"code": []}}},
        }
        proxy.on_backend_line(1, json.dumps(response))
        result = json.loads(output.getvalue())
        self.assertEqual(result["id"], 1)
        self.assertEqual(
            result["result"]["structuredContent"]["error"]["code"], "TOOL_FAILED"
        )
        self.assertEqual(proxy.pending, {})

    def test_proxy_bounds_pending_local_requests(self):
        import io
        from types import SimpleNamespace
        import napmem_mcp_failover as proxy_module

        output = io.StringIO()
        proxy = proxy_module.FailoverProxy(None, [], stdout=output)
        proxy.mode = "local"
        proxy.backend = SimpleNamespace(send=lambda line: True)
        with mock.patch.object(proxy_module, "MAX_PENDING_REQUESTS", 2, create=True):
            for n in range(3):
                proxy.on_client_line(
                    json.dumps({"jsonrpc": "2.0", "id": n, "method": "initialize"})
                )
        self.assertLessEqual(len(proxy.pending), 2)
        self.assertEqual(json.loads(output.getvalue())["id"], 2)

    def test_primary_command_preserves_shell_metacharacters(self):
        import shlex
        import napmem_mcp_failover as proxy_module

        path = "/srv/$(printf UNEXPECTED)/a repo"
        with mock.patch.dict(
            os.environ,
            {"NAPMEM_REMOTE_REPO": path, "NAPMEM_REMOTE_PYRAMID": "$HOME/a store.json"},
        ):
            command = proxy_module.primary_cmd("fixture.invalid")[-1]
        words = shlex.split(command)
        self.assertEqual(words[-2:], [path, "$HOME/a store.json"])
        self.assertEqual(words[0], "python3")
        self.assertEqual(command, shlex.join(words))

    def test_mcp_prunes_derived_prose_before_atomic_evidence(self):
        import napmem_mcp_server as mcp

        payload = {
            "matches": {
                "memory_records": [{"id": "r", "text": "evidence"}],
                "topic_tracks": [{"summary": "derived"}],
                "user_profiles": [{"trait": "derived"}],
            }
        }
        self.assertTrue(mcp._prune_payload(payload))
        self.assertEqual(
            payload["matches"]["memory_records"], [{"id": "r", "text": "evidence"}]
        )
        self.assertEqual(payload["matches"]["user_profiles"], [])
        payload = {"track": {"summary": "derived"}, "records": [{"id": "r"}]}
        self.assertTrue(mcp._prune_payload(payload))
        self.assertTrue(payload["records"])
        self.assertFalse(payload.get("track"))

    def test_search_requires_complete_numeric_literals(self):
        from napmem_model import normalize_record
        from napmem_search import search

        data = {
            "generation": 0,
            "memory_records": [
                normalize_record({"id": "r", "text": "The limit is 100."})
            ],
        }
        self.assertEqual(search(data, "What is limit 10?")["matches"], [])

    def test_injected_embeddings_support_semantic_fragments(self):
        from napmem_model import normalize_record
        from napmem_search import search

        backend = mock.Mock()
        backend.embed.return_value = [[1.0], [1.0]]
        data = {
            "generation": 0,
            "memory_records": [
                normalize_record({"id": "r", "text": "red car maintenance"})
            ],
        }
        self.assertEqual(
            [
                r["id"]
                for r in search(data, "crimson automobile repair", backend=backend)[
                    "matches"
                ]
            ],
            ["r"],
        )

    def test_dense_similarity_is_scale_invariant(self):
        from napmem_search import _cosine

        for value in [1e200, 1e-200]:
            with self.subTest(value=value):
                self.assertAlmostEqual(_cosine([value], [value]), 1.0)

    def test_snapshot_refresh_requires_new_manifest_verification(self):
        from napmem_retrieval_agent import NapMemRetrievalAgent
        from napmem_snapshots import export_snapshot, STORE_FILE

        self.store.ingest_session("a", "A", "a.md", self.text)
        directory = self.root / "flat"
        directory.mkdir()
        import shutil

        shutil.copy2(self.path, directory / STORE_FILE)
        agent = NapMemRetrievalAgent(str(directory / STORE_FILE))
        export = self.root / "export"
        export_snapshot(self.path, export, include_cache=False)
        shutil.copy2(export / "manifest.json", directory / "manifest.json")
        (directory / STORE_FILE).write_text("{}")
        with self.assertRaises(ValueError):
            agent.query("editor")

    def test_cache_decoder_depth_is_disposable(self):
        from semantic_index import SemanticIndex, HashedTfBackend

        cache = Path(self.path + ".embindex.json")
        cache.write_text("{}")
        with (
            mock.patch("semantic_index.json.load", side_effect=RecursionError),
            self.assertLogs("semantic_index", level="WARNING"),
        ):
            index = SemanticIndex(self.path, HashedTfBackend())
        self.assertEqual(index._cache["vectors"], {})

    def test_ollama_model_tags_are_exact(self):
        import ollama_extractor as extractor

        client = mock.Mock()
        client.list_models.return_value = ["qwen:7b"]
        # Actual client contract is inspected by the test's explicit fixture below.
        with mock.patch.object(extractor, "_client_for", return_value=client), \
                mock.patch.object(extractor, "OllamaClient", object()), \
                mock.patch.object(extractor, "OllamaPool", object()):
            self.assertTrue(extractor.ollama_available([("http://fixture.invalid", "qwen:7b")]))
            self.assertFalse(
                extractor.ollama_available([("http://fixture.invalid", "qwen:32b")])
            )



class StaticMapSafetyTests(unittest.TestCase):
    def setUp(self):
        import importlib.util
        spec = importlib.util.spec_from_file_location("repo_docs_fixture", Path(__file__).parent / "scripts/repo_docs.py")
        self.module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(self.module)
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.module.ROOT = self.root

    def test_binary_asset_description_does_not_decode_as_prose(self):
        (self.root / "image.png").write_bytes(b"\x89PNG\xff")
        self.assertEqual(self.module.describe("image.png"), "Binary repository asset")

    def test_output_symlink_cannot_overwrite_an_external_file(self):
        outside = self.root / "outside.txt"
        outside.write_text("preserve")
        (self.root / "llms.txt").symlink_to(outside)
        self.module.OUTPUTS = ("llms.txt",)
        with mock.patch("sys.argv", ["repo_docs.py"]), mock.patch.object(self.module, "render") as render:
            with self.assertRaises(ValueError):
                self.module.main()
            render.assert_not_called()
        self.assertEqual(outside.read_text(), "preserve")


if __name__ == "__main__":
    unittest.main()
