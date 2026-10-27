"""Content-free local metrics, retention and strictly read-only status tests."""

from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from datetime import UTC, datetime
import hashlib
import json
import os
from pathlib import Path
import sqlite3
import stat
import tempfile
import unittest
from unittest import mock

from napmem_metrics import (
    MetricsStore, candidate_hash, hash_scope, record_hook_outcome,
    record_if_enabled, status_report,
)
from napmem_model import CONTEXT_FIELDS, normalize_record
from napmem_search import compact_json


JAN = "2026-01-01T00:00:00Z"
JUN = "2026-06-01T00:00:00Z"
JUL = "2026-07-01T00:00:00Z"
NOW = datetime(2026, 7, 1, tzinfo=UTC)


def record(rid="r1", text="PRIVATE memory wording", **changes):
    value = {"id": rid, "text": text, "scope": "project:PRIVATE", "created_at": JAN,
             "source_anchor": {"session_id": "PRIVATEsession", "file_path": "/PRIVATE/source.md"}}
    value.update(changes)
    return normalize_record(value)


class MetricsCase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.path = Path(self.tmp.name) / "PRIVATE pyramid.json"
        self.clock = mock.patch("napmem_metrics._now", return_value=NOW)
        self.clock.start()
        self.addCleanup(self.clock.stop)
        self.metrics = MetricsStore(self.path)
        self.metric_path = Path(self.metrics.path)

    def write_store(self, *records, **changes):
        data = {"version": "2.0.0", "generation": 7, "updated_at": JUN, "memory_records": list(records)}
        data.update(changes)
        self.path.write_text(json.dumps(data), encoding="utf-8")

    def assert_no_private(self, result):
        self.assertNotIn("PRIVATE", json.dumps(result))
        self.assertNotIn(str(self.path), json.dumps(result))


class MetricsTests(MetricsCase):
    def test_constructor_summary_and_purge_missing_never_create_files(self):
        self.assertEqual(self.metrics.summarize()["status"], "missing")
        self.assertIsNone(self.metrics.summarize()["retrieval"]["empty_rate"])
        self.assertEqual(self.metrics.purge(["r1"])["metrics"], "absent")
        self.assertEqual(list(self.path.parent.iterdir()), [])

    def test_private_atomic_events_and_feedback_retain_no_raw_identifiers_or_scope(self):
        self.metrics.record("retrieval", latency_ms=12.5, returned_bytes=512, result_count=1,
                            empty=False, fallback=False, backend="hybrid", success=True,
                            scope_hash=hash_scope("project:PRIVATE"))
        receipt = self.metrics.feedback("PRIVATE-record-id", "useful", "project:PRIVATE")
        serialized = self.metric_path.read_text()
        self.assertNotIn("PRIVATE", serialized)
        data = json.loads(serialized)
        feedback = data["events"][1]["fields"]
        self.assertEqual(feedback["record_hash"], hashlib.sha256(b"PRIVATE-record-id").hexdigest())
        self.assertEqual(feedback["candidate_hash"], candidate_hash("PRIVATE-record-id", "project:PRIVATE"))
        self.assertEqual(stat.S_IMODE(self.metric_path.stat().st_mode), 0o600)
        self.assertEqual(stat.S_IMODE(Path(self.metrics.path + ".lock").stat().st_mode), 0o600)
        self.assertEqual(receipt["metrics"], "recorded")
        self.assert_no_private(self.metrics.summarize())

    def test_unknown_or_sensitive_event_fields_fail_before_any_write(self):
        invalid = (("query", {}), ("feedback", {"rating": "useful"}),
                   ("retrieval", {"query": "PRIVATE query"}), ("ingest", {"text": "PRIVATE source"}),
                   ("extraction", {"model": "PRIVATE model secret"}), ("hook_recall", {"path": "/PRIVATE/path"}),
                   ("retrieval", {"scope": "project:PRIVATE"}), ("ingest", {"error": "PRIVATE failure"}),
                   ("extraction", {"backend": "https://PRIVATE:secret@host"}),
                   ("extraction", {"stage": "PRIVATE stage"}))
        for event, fields in invalid:
            with self.subTest(event=event, fields=fields), self.assertRaises(ValueError):
                self.metrics.record(event, **fields)
        self.assertEqual(list(self.path.parent.iterdir()), [])

    def test_numbers_types_enums_and_internal_consistency_are_strict(self):
        bad = ({"latency_ms": -1}, {"latency_ms": float("nan")}, {"lag_seconds": float("inf")},
               {"latency_ms": True}, {"returned_bytes": 1.2}, {"result_count": True},
               {"input_bytes": 2 ** 64}, {"success": 1}, {"fallback": "true"},
               {"scope_hash": "rawscope"}, {"scope_hash": "A" * 64},
               {"empty": True, "result_count": 1}, {"empty": False, "result_count": 0})
        for fields in bad:
            with self.subTest(fields=fields), self.assertRaises(ValueError):
                self.metrics.record("retrieval", **fields)
        self.assertEqual(list(self.path.parent.iterdir()), [])

    def test_summary_reports_exact_rate_denominators_and_measured_byte_latency_distributions(self):
        for fields in ({"latency_ms": 10, "returned_bytes": 100, "empty": True, "fallback": False, "success": True},
                       {"latency_ms": 20, "returned_bytes": 200, "empty": False, "fallback": True, "success": True},
                       {"latency_ms": 50, "returned_bytes": 0, "empty": True, "fallback": False, "success": False},
                       {"result_count": 1}):
            self.metrics.record("retrieval", **fields)
        before = self.metric_path.read_bytes()
        summary = self.metrics.summarize()
        result = summary["retrieval"]
        self.assertEqual((result["count"], result["empty_count"], result["empty_observations"]), (4, 1, 2))
        self.assertEqual(result["empty_rate"], .5)
        self.assertEqual((result["fallback_count"], result["fallback_observations"]), (1, 3))
        self.assertEqual(result["fallback_rate"], 1 / 3)
        self.assertEqual(result["failure_rate"], 1 / 3)
        self.assertEqual(result["latency_ms"], {"count": 3, "min": 10, "p50": 20, "p95": 50, "max": 50, "mean": 80 / 3})
        self.assertEqual(result["returned_bytes"]["mean"], 100)
        self.assertEqual(self.metric_path.read_bytes(), before)

    def test_extraction_stages_do_not_dilute_fallback_denominator_or_invent_validation_latency(self):
        self.metrics.record("extraction", stage="request", latency_ms=30, backend="anthropic", success=False)
        self.metrics.record("extraction", stage="fallback", latency_ms=2, backend="heuristic", fallback=True, success=True)
        self.metrics.record("extraction", stage="validation", rejected_units=4, success=False)
        self.metrics.record("extraction", stage="request", latency_ms=10, backend="anthropic", success=True)
        self.metrics.record("extraction", stage="validation", rejected_units=0, success=True)
        result = self.metrics.summarize()
        extraction = result["extraction"]
        self.assertEqual(extraction["fallback_per_request"], {"numerator": 1, "denominator": 2, "rate": .5})
        self.assertEqual(extraction["fallback_observations"], 1)
        self.assertEqual(extraction["fallback_rate_basis"], "stage:fallback")
        stages = result["by_stage"]["extraction"]
        self.assertEqual(stages["request"]["latency_ms"]["p50"], 20)
        self.assertEqual(stages["validation"]["latency_ms"]["count"], 0)
        self.assertEqual(stages["validation"]["rejected_units"], 4)
        self.assertEqual(stages["validation"]["success_observations"], 2)

    def test_feedback_is_latest_per_scoped_candidate_and_purge_removes_all_scopes_for_record(self):
        self.metrics.feedback("one", "wrong", "project:a")
        self.metrics.feedback("one", "useful", "project:a")
        self.metrics.feedback("one", "outdated", "project:b")
        self.metrics.feedback("other", "wrong", "project:a")
        self.metrics.record("retrieval", success=True)
        self.assertEqual(self.metrics.summarize()["feedback"]["ratings"], {"useful": 1, "wrong": 1, "outdated": 1})
        result = self.metrics.purge(["one"])
        self.assertEqual(result["removed"], 2)
        summary = self.metrics.summarize()
        self.assertEqual(summary["feedback"]["ratings"], {"useful": 0, "wrong": 1, "outdated": 0})
        self.assertEqual(summary["retrieval"]["count"], 1)
        raw = self.metric_path.read_text()
        self.assertNotIn(hashlib.sha256(b"one").hexdigest(), raw)
        self.assertNotIn(candidate_hash("one", "project:a"), raw)

    def test_candidate_hash_purge_only_removes_the_selected_scope_and_noop_does_not_rewrite(self):
        self.metrics.feedback("one", "useful", "project:a")
        self.metrics.feedback("one", "outdated", "project:b")
        self.assertEqual(self.metrics.purge([candidate_hash("one", "project:a")])["removed"], 1)
        before = self.metric_path.read_bytes()
        self.assertEqual(self.metrics.purge(["unrelated"])["removed"], 0)
        self.assertEqual(self.metric_path.read_bytes(), before)
        self.assertEqual(self.metrics.summarize()["feedback"]["ratings"]["outdated"], 1)

    def test_feedback_validation_and_scope_hash_contexts_are_distinct(self):
        self.assertEqual(len({hash_scope(None), hash_scope("global"), hash_scope("*")}), 3)
        self.assertNotEqual(candidate_hash("r", "project:a"), candidate_hash("r", "project:b"))
        for rid, rating, scope in (("", "useful", None), (1, "wrong", None), ("r", "PRIVATE", None),
                                    ("r", "useful", "bad\x00scope"), ("r", True, None)):
            with self.subTest(rid=rid, rating=rating), self.assertRaises(ValueError):
                self.metrics.feedback(rid, rating, scope)
        for ids in (None, "record", [1], [""], ["x" * 4097]):
            with self.subTest(ids=ids), self.assertRaises(ValueError):
                self.metrics.purge(ids)
        self.assertEqual(list(self.path.parent.iterdir()), [])

    def test_event_count_retention_is_bounded_and_persisted_policy_is_reported(self):
        metrics = MetricsStore(self.path, max_events=3, retention_days=2)
        for count in range(5):
            metrics.record("ingest", result_count=count)
        data = json.loads(self.metric_path.read_text())
        self.assertEqual([r["fields"]["result_count"] for r in data["events"]], [2, 3, 4])
        self.assertEqual(self.metrics.summarize()["retention"]["max_events"], 3)
        self.assertEqual(self.metrics.summarize()["retention"]["retention_days"], 2)

    def test_expired_events_are_excluded_read_only_and_physically_pruned_on_write(self):
        with mock.patch("napmem_metrics._now", return_value=datetime(2026, 1, 1, tzinfo=UTC)):
            self.metrics.feedback("old", "wrong")
        before = self.metric_path.read_bytes()
        self.assertEqual(self.metrics.summarize()["retained_events"], 0)
        self.assertEqual(self.metrics.summarize()["excluded_by_retention"], 1)
        self.assertEqual(self.metric_path.read_bytes(), before)
        self.metrics.record("ingest", success=True)
        self.assertNotIn(hashlib.sha256(b"old").hexdigest(), self.metric_path.read_text())
        self.assertEqual(self.metrics.summarize()["retained_events"], 1)

    def test_file_cap_can_prune_more_than_event_cap_without_partial_events(self):
        with mock.patch("napmem_metrics.MAX_METRICS_BYTES", 1200):
            for count in range(12):
                self.metrics.record("retrieval", result_count=count, latency_ms=count, returned_bytes=count * 10, success=True)
            self.assertLessEqual(self.metric_path.stat().st_size, 1200)
            self.assertEqual(self.metrics.summarize()["status"], "ok")
        self.assertEqual(json.loads(self.metric_path.read_text())["events"][-1]["fields"]["result_count"], 11)

    def test_concurrent_writers_do_not_lose_events_and_generation_counts_commits(self):
        with ThreadPoolExecutor(max_workers=4) as workers:
            results = list(workers.map(lambda i: MetricsStore(self.path).record("ingest", result_count=i), range(20)))
        self.assertTrue(all(result["metrics"] == "recorded" for result in results))
        summary = self.metrics.summarize()
        self.assertEqual(summary["generation"], 20)
        self.assertEqual(summary["ingest"]["count"], 20)
        self.assertEqual(len(list(self.path.parent.glob("*.tmp"))), 0)

    def test_optional_runtime_instrumentation_is_best_effort_without_sensitive_errors(self):
        with mock.patch.dict(os.environ, {}, clear=True):
            self.assertIsNone(record_if_enabled(self.path, "retrieval", success=True))
        self.assertEqual(list(self.path.parent.iterdir()), [])
        with mock.patch.dict(os.environ, {"NAPMEM_METRICS": "TRUE"}):
            self.assertEqual(record_if_enabled(self.path, "retrieval", success=True)["metrics"], "recorded")
            with mock.patch("napmem_metrics.MetricsStore.record", side_effect=OSError("PRIVATE filesystem secret")):
                self.assertEqual(record_if_enabled(self.path, "ingest"), {"metrics": "unavailable"})
            self.assertEqual(record_if_enabled(self.path, "ingest", query="PRIVATE"), {"metrics": "unavailable"})

    def test_explicit_hook_outcome_measures_outcome_without_env_optin_or_hook_changes(self):
        with mock.patch.dict(os.environ, {"NAPMEM_METRICS": "0"}):
            receipt = record_hook_outcome(self.path, success=False, latency_ms=11, result_count=0,
                                           returned_bytes=0, empty=True, fallback=True, lag_seconds=20,
                                           scope="project:PRIVATE")
        self.assertEqual(receipt["event"], "hook_recall")
        result = self.metrics.summarize()["hook_recall"]
        self.assertEqual(result["failure_count"], 1)
        self.assertEqual(result["empty_observations"], 0)
        self.assert_no_private(self.metrics.summarize())

    def test_bad_persistent_state_is_rejected_without_rewrite_and_status_stays_content_free(self):
        self.metrics.record("ingest", success=True)
        valid = json.loads(self.metric_path.read_text())
        cases = [dict(valid, version="9.0.0"), dict(valid, events=[{"event": "ingest", "at": JUL, "fields": {"query": "PRIVATE"}}]),
                 dict(valid, generation=True), dict(valid, events="bad"), dict(valid, private="PRIVATE")]
        for data in cases:
            self.metric_path.write_text(json.dumps(data), encoding="utf-8")
            before = self.metric_path.read_bytes()
            with self.subTest(data=data), self.assertRaises(ValueError):
                self.metrics.summarize()
            with self.assertRaises(ValueError):
                self.metrics.record("ingest", success=True)
            self.assertEqual(self.metric_path.read_bytes(), before)
            self.assertEqual(status_report(self.path)["metrics"]["status"], "invalid")
            self.assert_no_private(status_report(self.path))

    def test_symlink_insecure_permissions_and_oversized_metric_files_are_rejected(self):
        target = Path(self.tmp.name) / "target.json"
        target.write_text("{}")
        self.metric_path.symlink_to(target)
        with self.assertRaises(ValueError):
            self.metrics.summarize()
        self.metric_path.unlink()
        self.metrics.record("ingest", success=True)
        self.metric_path.chmod(0o644)
        with self.assertRaises(ValueError):
            self.metrics.summarize()
        self.assertEqual(stat.S_IMODE(self.metric_path.stat().st_mode), 0o644)
        self.metric_path.chmod(0o600)
        with mock.patch("napmem_metrics.MAX_METRICS_BYTES", 1), self.assertRaises(ValueError):
            self.metrics.summarize()

    def test_constructor_policy_validation_does_not_create_files(self):
        for kwargs in ({"max_events": 0}, {"max_events": True}, {"max_events": 10001},
                       {"retention_days": 0}, {"retention_days": float("nan")}, {"retention_days": -1}):
            with self.subTest(kwargs=kwargs), self.assertRaises(ValueError):
                MetricsStore(self.path, **kwargs)
        self.assertEqual(list(self.path.parent.iterdir()), [])


class StatusTests(MetricsCase):
    def test_missing_status_is_honest_read_only_and_never_initializes_sidecars(self):
        result = status_report(self.path)
        self.assertEqual(result["status"], "missing")
        self.assertEqual(result["store"]["status"], "missing")
        self.assertEqual(result["sources"]["status"], "missing")
        self.assertEqual(result["jobs"]["status"], "missing")
        self.assertEqual(result["metrics"]["status"], "missing")
        self.assertEqual(result["mirror"]["status"], "not_requested")
        self.assertEqual(list(self.path.parent.iterdir()), [])
        self.assert_no_private(result)

    def test_current_counts_are_scoped_and_aliases_use_own_scope_without_returning_text(self):
        alias = record("alias", "PRIVATE alias", scope="project:allowed")
        anchor = {**alias["source_anchor"], "paraphrase_text": alias["text"],
                  "assertion": {field: deepcopy(alias[field]) for field in (*CONTEXT_FIELDS, "created_at")}}
        self.write_store(record("owner", duplicates=["alias"], duplicate_anchors={"alias": anchor}),
                         record("global", scope="global"), record("deleted", scope="global", status="deleted"))
        result = status_report(self.path, scope="project:allowed", as_of=JUL)
        self.assertEqual(result["store"]["counts"]["current_records"], 2)
        self.assertEqual(result["store"]["counts"]["current_assertions"], 2)
        self.assertEqual(result["store"]["generation"], 7)
        self.assertEqual(result["store"]["schema"], "2.0.0")
        self.assertEqual(result["store"]["age_seconds"], 30 * 86400)
        self.assert_no_private(result)

    def test_status_valid_time_counts_and_unknown_update_timestamp_are_explicit(self):
        self.write_store(record("old", scope="legacy", status="superseded", valid_from=JAN, valid_to=JUN),
                         record("new", scope="legacy", valid_from=JUN, supersedes=["old"]), updated_at="naive bad timestamp")
        historic = status_report(self.path, as_of=JAN)
        current = status_report(self.path, as_of=JUL)
        self.assertEqual(historic["store"]["counts"]["current_records"], 1)
        self.assertEqual(current["store"]["counts"]["current_records"], 1)
        self.assertEqual(current["store"]["updated_time_status"], "unknown")
        self.assertIsNone(current["store"]["updated_at"])

    def test_source_registry_pending_lag_missing_and_exclusions_are_metadata_only(self):
        from napmem_sources import SourceRegistry
        self.write_store()
        registry = SourceRegistry(str(self.path))
        for name, scope in (("pending", "project:allowed"), ("committed", "project:allowed"),
                            ("missing", "project:allowed"), ("excluded", "project:allowed"), ("hidden", "project:PRIVATE")):
            registry.observe({"path": "/PRIVATE/" + name + ".md", "sha256": "a" * 64, "device": 1,
                              "inode": len(registry.list()) + 1, "mtime": NOW.timestamp() - 100, "size": 12}, scope=scope)
        registry.mark_committed("sess_committed", "a" * 64)
        registry.mark_missing(["/PRIVATE/pending.md", "/PRIVATE/committed.md", "/PRIVATE/excluded.md", "/PRIVATE/hidden.md"])
        self.write_store(controls={"excluded_sources": {"session:sess_excluded": True}})
        before = {p.name: (p.read_bytes(), p.stat().st_mode) for p in self.path.parent.iterdir()}
        with mock.patch("napmem_sources.read_source", side_effect=AssertionError("source read")), \
                mock.patch("socket.create_connection", side_effect=AssertionError("network")):
            result = status_report(self.path, scope="project:allowed")
        sources = result["sources"]
        self.assertEqual((sources["count"], sources["pending"], sources["missing"], sources["suppressed"]), (4, 1, 1, 1))
        self.assertEqual(sources["oldest_lag_seconds"], 100)
        self.assertEqual({p.name: (p.read_bytes(), p.stat().st_mode) for p in self.path.parent.iterdir()}, before)
        self.assert_no_private(result)

    def make_jobs(self, rows):
        queue = Path(str(self.path) + ".jobs.sqlite3")
        with sqlite3.connect(queue) as db:
            db.execute("CREATE TABLE jobs(id TEXT,state TEXT,created_at REAL,scope TEXT,source_text TEXT)")
            for idx, (state, scope) in enumerate(rows):
                db.execute("INSERT INTO jobs VALUES(?,?,?,?,?)", (str(idx), state, NOW.timestamp() - 100 + idx, scope, "PRIVATE raw source"))
        queue.chmod(0o600)
        return queue

    def test_jobs_status_uses_readonly_metadata_sql_and_preserves_payloads_bytes_and_permissions(self):
        self.write_store()
        queue = self.make_jobs([("queued", None), ("submitted", "global"), ("failed", None), ("stale", None), ("queued", "project:PRIVATE")])
        before = queue.read_bytes(), queue.stat().st_mode, sorted(p.name for p in self.path.parent.iterdir())
        result = status_report(self.path)
        jobs = result["jobs"]
        self.assertEqual(jobs["states"]["queued"], 1)
        self.assertEqual(jobs["states"]["failed"], 1)
        self.assertEqual(jobs["states"]["stale"], 1)
        self.assertEqual(jobs["oldest_pending_lag_seconds"], 100)
        self.assertTrue(jobs["counts_complete"])
        self.assertFalse(jobs["payloads_read"])
        self.assertEqual(result["status"], "degraded")
        self.assertEqual((queue.read_bytes(), queue.stat().st_mode, sorted(p.name for p in self.path.parent.iterdir())), before)
        self.assert_no_private(result)

    def test_jobs_sampling_cap_is_disclosed_and_never_claims_full_counts(self):
        self.write_store()
        self.make_jobs([("queued", None)] * 5)
        with mock.patch("napmem_metrics.JOB_STATUS_CAP", 3):
            result = status_report(self.path)
        self.assertFalse(result["jobs"]["counts_complete"])
        self.assertEqual(result["jobs"]["row_cap"], 3)
        self.assertEqual(result["jobs"]["states"]["queued"], 3)
        self.assertEqual(result["jobs"]["rows_examined"], 3)

    def test_bad_sidecar_is_reported_as_invalid_without_private_exception_strings(self):
        self.write_store()
        Path(str(self.path) + ".sources.json").write_text("{PRIVATE broken")
        Path(str(self.path) + ".jobs.sqlite3").write_text("PRIVATE not sqlite")
        result = status_report(self.path)
        self.assertEqual(result["status"], "degraded")
        self.assertEqual(result["sources"]["status"], "invalid")
        self.assertEqual(result["jobs"]["status"], "invalid")
        self.assert_no_private(result)

    def test_feedback_is_quality_opinion_and_runtime_failure_is_distinct_from_empty_result(self):
        self.write_store()
        self.metrics.feedback("PRIVATE id", "wrong")
        self.metrics.record("retrieval", success=True, result_count=0, empty=True, fallback=False, returned_bytes=123, latency_ms=5)
        self.metrics.record("retrieval", success=False, result_count=0, empty=True, fallback=True, returned_bytes=60, latency_ms=10)
        result = status_report(self.path)
        self.assertEqual(result["metrics"]["retrieval"]["empty_rate"], 1)
        self.assertEqual(result["metrics"]["retrieval"]["empty_observations"], 1)
        self.assertEqual(result["metrics"]["retrieval"]["failure_count"], 1)
        self.assertIn("unmeasured", result["interpretation"]["quality"])
        self.assertIn("observed", result["interpretation"]["failures"])
        self.assertEqual(result["metrics"]["feedback"]["ratings"]["wrong"], 1)
        self.assert_no_private(result)

    def test_store_validation_including_managed_missing_manifest_never_downgrades_trust(self):
        self.path.write_text('{"version":"99.0.0","memory_records":[]}')
        self.assertEqual(status_report(self.path)["store"]["status"], "invalid")
        generation = self.path.parent / "generations" / ("gen-1-" + "a" * 32)
        generation.mkdir(parents=True)
        pyramid = generation / "napmem_pyramid.json"
        pyramid.write_text('{"version":"2.0.0","memory_records":[],"generation":1}')
        self.assertEqual(status_report(pyramid)["store"]["status"], "invalid")
        self.assertFalse((generation / "manifest.json").exists())

    def test_deletion_coverage_reports_local_partial_work_and_unacknowledged_mirrors(self):
        self.write_store(deletion_receipts=[{"change_id": "PRIVATEid", "cache": "pending:OSError",
                                            "jobs": {"coverage": "pending:OSError"},
                                            "metrics": {"metrics": "unavailable"}, "mirrors": "pending_acknowledgment"}])
        result = status_report(self.path)
        self.assertEqual(result["deletion"]["status"], "pending")
        self.assertEqual(result["deletion"]["pending_cache"], 1)
        self.assertEqual(result["deletion"]["pending_jobs"], 1)
        self.assertEqual(result["deletion"]["pending_metrics"], 1)
        self.assertEqual(result["deletion"]["pending_mirrors"], 1)
        self.assertEqual(result["deletion"]["originals_exports_backups"], "operator_managed")
        self.assert_no_private(result)

    def test_explicit_mirror_verifies_generation_age_and_legacy_generation_stays_unverified(self):
        from napmem_snapshots import export_snapshot
        self.write_store()
        mirror = self.path.parent / "mirror"
        export_snapshot(self.path, mirror, include_cache=False)
        result = status_report(self.path, mirror_dir=mirror)
        self.assertEqual(result["mirror"]["status"], "verified")
        self.assertEqual(result["mirror"]["generation"], 7)
        self.assertEqual(result["mirror"]["generation_relation"], "same")
        (mirror / "manifest.json").unlink()
        legacy = status_report(self.path, mirror_dir=mirror)
        self.assertEqual(legacy["mirror"]["status"], "unverified")
        self.assertIsNone(legacy["mirror"]["generation"])
        self.assert_no_private(result)

    def test_status_budget_accounting_and_argument_validation(self):
        self.write_store()
        result = status_report(self.path)
        self.assertEqual(result["returned_bytes"], len(compact_json(result)))
        self.assertLessEqual(len(compact_json(result)), 16384)
        self.assertLessEqual(result["estimated_tokens"], 2048)
        for kwargs in ({"scope": "bad\x00scope"}, {"as_of": "2026-01-01"}, {"max_bytes": 10}, {"max_tokens": 2}):
            with self.subTest(kwargs=kwargs), self.assertRaises(ValueError):
                status_report(self.path, **kwargs)


if __name__ == "__main__":
    unittest.main()
