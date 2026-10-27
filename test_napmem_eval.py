"""Deterministic, network-free evidence scorer and benchmark contract tests."""

from copy import deepcopy
import hashlib
import json
import math
from pathlib import Path
import tempfile
import unittest
from unittest import mock

import napmem_eval as evaluation


AS_OF = "2026-09-01T00:00:00Z"


def record(rid, **changes):
    value = {"id": rid, "text": f"Synthetic {rid}", "type": "fact", "scope": "project:a",
             "memory_kind": "decision", "valid_from": "2026-01-01T00:00:00Z",
             "valid_to": None, "status": "active", "supersedes": []}
    value.update(changes)
    return value


def case(expected=None, **changes):
    value = {"id": "q1", "query": "Synthetic question", "scenario": "one", "split": "dev",
             "category": "paraphrase", "scope": "project:a", "expected_ids": expected or []}
    value.update(changes)
    return value


class TestEvidenceScoring(unittest.TestCase):
    def setUp(self):
        self.records = {rid: record(rid) for rid in ("a", "b", "noise")}

    def test_recall_mrr_and_graded_ndcg_have_known_values(self):
        scores = evaluation.score_query(case(["a", "b"], relevance={"a": 2, "b": 1}),
                                        ["noise", "b", "a"], self.records, as_of=AS_OF)
        self.assertEqual(scores["recall_at_5"], 1)
        self.assertEqual(scores["mrr_at_5"], .5)
        expected_ndcg = (1 / math.log2(3) + 3 / math.log2(4)) / (3 + 1 / math.log2(3))
        self.assertAlmostEqual(scores["ndcg_at_5"], expected_ndcg)
        self.assertEqual(scores["unsupported_results"], 1)

    def test_recall_uses_all_gold_and_cutoff_ignores_sixth_hit(self):
        scores = evaluation.score_query(case(["a", "b"]),
                                        ["a", "noise", "noise", "noise", "noise", "b"],
                                        self.records, as_of=AS_OF)
        self.assertEqual(scores["recall_at_5"], .5)
        self.assertEqual(scores["mrr_at_5"], 1)
        self.assertEqual(scores["returned_count"], 6)
        self.assertEqual(scores["unsupported_results"], 4)

    def test_duplicates_occupy_ranks_and_cannot_inflate_gain(self):
        scores = evaluation.score_query(case(["a", "b"]), ["a", "a", "b"], self.records, as_of=AS_OF)
        self.assertEqual(scores["recall_at_5"], 1)
        self.assertEqual(scores["duplicate_results"], 1)
        self.assertAlmostEqual(scores["ndcg_at_5"], (1 + 1 / math.log2(4)) / (1 + 1 / math.log2(3)))
        self.assertLess(scores["ndcg_at_5"], 1)

    def test_no_answer_requires_empty_result_and_excludes_rank_denominator(self):
        empty = evaluation.score_query(case(), [], self.records, as_of=AS_OF)
        self.assertTrue(empty["abstention_correct"])
        for metric in ("recall_at_5", "mrr_at_5", "ndcg_at_5"):
            self.assertIsNone(empty[metric])
        wrong = evaluation.score_query(case(), ["unknown"], self.records, as_of=AS_OF)
        self.assertFalse(wrong["abstention_correct"])
        self.assertEqual(wrong["unknown_ids"], 1)
        self.assertTrue(wrong["unsupported_injection"])
        missed = evaluation.score_query(case(["a"]), [], self.records, as_of=AS_OF)
        self.assertEqual(missed["recall_at_5"], 0)
        self.assertIsNone(missed["abstention_correct"])

    def test_scope_errors_include_every_return_even_past_five(self):
        self.records["other"] = record("other", scope="project:b")
        self.records["global"] = record("global", scope="global")
        self.records["legacy"] = record("legacy", scope="legacy")
        scores = evaluation.score_query(case(["a"]), ["a"] * 5 + ["other", "global", "legacy"],
                                        self.records, as_of=AS_OF)
        self.assertEqual(scores["scope_violations"], 2)
        unspecified = evaluation.score_query(case(scope=None), ["a", "global", "legacy"], self.records, as_of=AS_OF)
        self.assertEqual(unspecified["scope_violations"], 1)
        all_scopes = evaluation.score_query(case(scope="*"), ["a", "other", "global", "legacy"], self.records, as_of=AS_OF)
        self.assertEqual(all_scopes["scope_violations"], 0)

    def test_validity_is_start_inclusive_end_exclusive_and_deletion_is_absolute(self):
        old = record("old", status="superseded", valid_to="2026-06-01T00:00:00Z")
        new = record("new", valid_from="2026-06-01T00:00:00Z", supersedes=["old"])
        deleted = record("deleted", status="deleted")
        records = {r["id"]: r for r in (old, new, deleted)}
        before = evaluation.score_query(case(["old"], as_of="2026-05-31T23:59:59Z"), ["old", "new", "deleted"], records, as_of=AS_OF)
        boundary = evaluation.score_query(case(["new"], as_of="2026-06-01T00:00:00Z"), ["old", "new"], records, as_of=AS_OF)
        self.assertEqual(before["lifecycle_violations"], 2)
        self.assertEqual(boundary["lifecycle_violations"], 1)

    def test_protected_and_current_fact_require_complete_clean_evidence(self):
        query = case(["a", "b"], category="update", protected=True)
        good = evaluation.score_query(query, ["b", "a"], self.records, as_of=AS_OF)
        noisy = evaluation.score_query(query, ["a", "b", "noise"], self.records, as_of=AS_OF)
        for key in ("protected_pass", "current_fact_correct"):
            self.assertTrue(good[key])
            self.assertFalse(noisy[key])

    def test_aggregation_excludes_unanswerable_cases_from_recall(self):
        rows = [{"scores": evaluation.score_query(query, ids, self.records, as_of=AS_OF)}
                for query, ids in ((case(["a"]), ["a"]), (case(), []))]
        metrics = evaluation._aggregate(rows)
        self.assertEqual(metrics["recall_at_5"], 1)
        self.assertEqual(metrics["recall_at_5_cases"], 1)
        self.assertEqual(metrics["abstention_correct_rate"], 1)
        self.assertEqual(metrics["abstention_correct_cases"], 1)


class TestBenchmarkContract(unittest.TestCase):
    def test_fixture_is_complete_and_whole_scenarios_do_not_cross_splits(self):
        fixture = evaluation.load_fixture()
        self.assertEqual(len(fixture["queries"]), 200)
        self.assertEqual(len(fixture["records"]), 83)
        dev = {q["scenario"] for q in fixture["queries"] if q["split"] == "dev"}
        heldout = {q["scenario"] for q in fixture["queries"] if q["split"] == "heldout"}
        self.assertFalse(dev & heldout)
        self.assertEqual((len(dev), len(heldout)), (10, 10))
        for split in ("dev", "heldout"):
            self.assertEqual(sum(q["split"] == split for q in fixture["queries"]), 100)
        self.assertTrue(all("synthetic/" in r["source_anchor"]["file_path"] for r in fixture["records"]))

    def test_fixture_rejects_gold_scope_error_and_split_leakage(self):
        fixture = {"synthetic": True, "as_of": AS_OF, "records": [record("a")],
                   "queries": [case(["a"], scope="project:b")]}
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "fixture.json"
            path.write_text(json.dumps(fixture))
            with self.assertRaisesRegex(ValueError, "scope"):
                evaluation.load_fixture(path)
            fixture["queries"] = [case(["a"]), case(["a"], id="q2", split="heldout")]
            path.write_text(json.dumps(fixture))
            with self.assertRaisesRegex(ValueError, "scenario"):
                evaluation.load_fixture(path)

    def test_normalizes_legacy_and_unified_evidence(self):
        for response in ({"matches": {"memory_records": [{"id": "a"}]}},
                         {"matches": [{"id": "a", "score": .5}]},
                         {"evidence": [{"record_id": "a"}]},
                         {"evidence": [{"record": {"id": "a"}}]}):
            self.assertEqual(evaluation.extract_result_ids(response), ["a"])
        with self.assertRaisesRegex(ValueError, "ID"):
            evaluation.extract_result_ids({"evidence": [{"text": "no id"}]})

    def test_hashed_and_substring_are_reproducible_and_never_probe_network(self):
        with mock.patch("semantic_index.OllamaBackend.probe", side_effect=AssertionError("Unexpected model probe")):
            for mode in ("substring", "hashed"):
                with self.subTest(mode=mode):
                    first = evaluation.evaluate(mode, "dev")
                    second = evaluation.evaluate(mode, "dev")
                    self.assertEqual(first["metrics"], second["metrics"])
                    self.assertEqual(first["by_category"], second["by_category"])
                    self.assertEqual([r["result_ids"] for r in first["results"]],
                                     [r["result_ids"] for r in second["results"]])
                    self.assertEqual(first["fixture_sha256"], second["fixture_sha256"])
                    self.assertGreater(first["result_bytes"]["max"], 0)
                    self.assertEqual(evaluation.compare_baseline(second, first), [])

    def test_hashed_mode_refuses_disguised_substring_fallback(self):
        class FallbackAgent:
            def __init__(self, path):
                pass

            def semantic_search(self, query, top_k):
                return {"mode": "substring-fallback", "matches": []}

        with self.assertRaisesRegex(RuntimeError, "hashed-TF"):
            evaluation.evaluate("hashed", "dev", agent_class=FallbackAgent)

    def test_hybrid_adapter_passes_scope_time_and_budgets(self):
        calls = []

        class FutureAgent:
            def __init__(self, path):
                self.data = json.loads(Path(path).read_text())

            def query(self, text, **kwargs):
                calls.append((text, kwargs))
                return {"evidence": [], "mode": "hybrid"}

        report = evaluation.evaluate("hybrid", "heldout", agent_class=FutureAgent,
                                     max_bytes=2048, max_tokens=300)
        self.assertEqual(len(calls), 100)
        self.assertEqual(calls[0][1], {"scope": "project:estuary", "as_of": AS_OF,
                                      "top_k": 5, "mode": "hybrid", "max_bytes": 2048, "max_tokens": 300})
        self.assertTrue(any(kwargs["as_of"] != AS_OF for _, kwargs in calls))
        self.assertEqual(report["budgets"], {"max_bytes": 2048, "max_tokens": 300})

    def test_hybrid_requires_unified_api(self):
        class OldAgent:
            def __init__(self, path):
                pass

        with self.assertRaisesRegex(ValueError, "unified query API"):
            evaluation.evaluate("hybrid", "dev", agent_class=OldAgent)

    def test_baseline_gate_catches_category_regressions_and_incompatible_fixture(self):
        baseline = evaluation.evaluate("substring", "heldout")
        changed = deepcopy(baseline)
        category = next(c for c, v in changed["by_category"].items() if v["recall_at_5"] is not None)
        changed["by_category"][category]["recall_at_5"] -= .01
        self.assertTrue(any(category + ".recall_at_5" in error for error in evaluation.compare_baseline(changed, baseline)))
        changed = deepcopy(baseline)
        changed["latency_ms"]["max"] = 1e9
        self.assertEqual(evaluation.compare_baseline(changed, baseline), [])
        changed["fixture_sha256"] = "other"
        self.assertEqual(evaluation.compare_baseline(changed, baseline), ["Incompatible baseline: fixture_sha256 differs"])

    def test_saved_baselines_bind_current_fixture_and_scored_ids(self):
        digest = hashlib.sha256(evaluation.DEFAULT_FIXTURE.read_bytes()).hexdigest()
        fixture = evaluation.load_fixture()
        queries = {q["id"]: q for q in fixture["queries"]}
        records = {r["id"]: r for r in fixture["records"]}
        for mode in ("substring", "hashed"):
            path = evaluation.ROOT / "evaluations" / f"baseline_{mode}_heldout_v1.json"
            saved = json.loads(path.read_text())
            self.assertEqual(saved["fixture_sha256"], digest)
            self.assertEqual(saved["metrics"]["query_count"], 100)
            self.assertEqual(saved["mode"], mode)
            for row in saved["results"]:
                self.assertEqual(row["scores"], evaluation.score_query(queries[row["query_id"]],
                                 row["result_ids"], records, as_of=fixture["as_of"]))
            self.assertEqual(saved["metrics"], evaluation._aggregate(saved["results"]))


if __name__ == "__main__":
    unittest.main()
