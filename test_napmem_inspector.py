"""Offline operator inspection, provenance boundaries and exact budgets."""

from copy import deepcopy
import hashlib
import json
from pathlib import Path
import shlex
import tempfile
import unittest
from unittest import mock

from napmem_controls import apply_action
from napmem_evidence import bind_evidence
from napmem_inspector import VIEWS, inspect_store, source_diff
from napmem_model import CONTEXT_FIELDS, migrate_store, normalize_record
from napmem_search import compact_json


JAN = "2026-01-01T00:00:00Z"
JUN = "2026-06-01T00:00:00Z"
JUL = "2026-07-01T00:00:00Z"


def record(rid="r1", text="Use the documented editor.", *, verified=False, **changes):
    result = {"id": rid, "text": text, "scope": "project:a", "created_at": JAN,
              "source_anchor": {"session_id": "session_" + rid, "file_path": "/synthetic/" + rid + ".md", "line_range": "L1"}}
    result.update(changes)
    if verified:
        result = bind_evidence(result, text, method="synthetic")
    return normalize_record(result)


def store(*records, **changes):
    result = {"version": "2.0.0", "generation": 7, "memory_records": list(records)}
    result.update(changes)
    return result


class InspectorTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name) / "test pyramid.json"

    def write(self, data):
        self.path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")

    def inspect(self, view="current", **kwargs):
        return inspect_store(self.path, view=view, scope="project:a", as_of=JUL, **kwargs)

    def assertBudget(self, result, maximum, tokens=None):
        encoded = compact_json(result)
        self.assertLessEqual(len(encoded), maximum)
        self.assertEqual(result["returned_bytes"], len(encoded))
        self.assertEqual(result["estimated_tokens"], (len(encoded) + 3) // 4)
        if tokens is not None:
            self.assertLessEqual(result["estimated_tokens"], tokens)

    def test_every_view_is_offline_read_only_and_uses_one_store_generation(self):
        self.write(store(record(memory_kind="decision")))
        before = self.path.read_bytes()
        with mock.patch("socket.create_connection", side_effect=AssertionError("network")), \
                mock.patch("urllib.request.urlopen", side_effect=AssertionError("network")), \
                mock.patch("napmem_sources.read_source", side_effect=AssertionError("source read")):
            for view in VIEWS:
                with self.subTest(view=view):
                    result = self.inspect(view)
                    self.assertEqual(result["generation"], 7)
                    self.assertEqual(result["snapshot_sha256"], hashlib.sha256(before).hexdigest())
                    self.assertBudget(result, 16384, 2048)
        self.assertEqual(self.path.read_bytes(), before)
        self.assertEqual(sorted(p.name for p in self.path.parent.iterdir()), [self.path.name])

    def test_missing_store_does_not_create_a_store_lock_or_sidecar(self):
        result = self.inspect("overview")
        self.assertEqual(result["status"], "missing")
        self.assertEqual(result["records"], [])
        self.assertEqual(list(self.path.parent.iterdir()), [])

    def test_scope_filters_counts_and_every_view_before_derived_views(self):
        self.write(store(record("a"), record("b", "SECRET foreign memory", scope="project:b"),
                         record("global", "Shared policy", scope="global"), record("legacy", scope="legacy")))
        for view in VIEWS:
            with self.subTest(view=view):
                result = self.inspect(view, max_tokens=None)
                serialized = json.dumps(result)
                self.assertNotIn("SECRET", serialized)
                self.assertNotIn("/synthetic/b.md", serialized)
                self.assertEqual(result["summary"]["retained_assertions"], 2)
        unscoped = inspect_store(self.path, as_of=JUL)
        self.assertEqual({r["record_id"] for r in unscoped["records"]}, {"legacy", "global"})
        explicit = inspect_store(self.path, scope="*", as_of=JUL, max_tokens=None)
        self.assertEqual(explicit["summary"]["current_assertions"], 4)

    def test_foreign_canonical_alias_uses_only_own_scope_text_and_proof(self):
        own = record("alias", "Allowed wording", memory_kind="preference", review_status="approved", verified=True)
        anchor = {**own["source_anchor"], "paraphrase_text": own["text"],
                  "assertion": {field: deepcopy(own[field]) for field in (*CONTEXT_FIELDS, "created_at")}}
        foreign = record("owner", "SECRET original wording", scope="project:b", duplicates=["alias"],
                         duplicate_anchors={"alias": anchor})
        self.write(store(foreign))
        for view in VIEWS:
            result = self.inspect(view, max_tokens=None)
            self.assertNotIn("SECRET", json.dumps(result))
            self.assertNotIn("/synthetic/owner.md", json.dumps(result))
        row = self.inspect()["records"][0]
        self.assertEqual((row["record_id"], row["canonical"], row["source"]["session_id"]), ("alias", "owner", "session_alias"))
        self.assertEqual(row["evidence"]["quote"], own["text"])

    def test_current_uses_half_open_validity_while_timeline_labels_retained_history(self):
        self.write(store(record("old", status="superseded", valid_from=JAN, valid_to=JUN),
                         record("new", valid_from=JUN, supersedes=["old"]),
                         record("deleted", status="deleted")))
        self.assertEqual([r["record_id"] for r in self.inspect()["records"]], ["new"])
        historic = inspect_store(self.path, view="current", scope="project:a", as_of=JAN)
        self.assertEqual([r["record_id"] for r in historic["records"]], ["old"])
        timeline = self.inspect("timeline", max_tokens=None)["records"]
        self.assertEqual({r["record_id"] for r in timeline}, {"old", "new", "deleted"})
        old = next(r for r in timeline if r["record_id"] == "old")
        self.assertFalse(old["current_at_reference"])
        self.assertIn({"event": "valid_to", "at": JUN, "after_reference": False}, old["events"])

    def test_historical_profiles_use_historical_eligibility_and_verified_citations(self):
        self.write(store(record("old", "Prefer Vim", memory_kind="preference", review_status="approved", verified=True,
                                status="superseded", valid_from=JAN, valid_to=JUN, subject="editor"),
                         record("new", "Prefer Code", memory_kind="preference", review_status="approved", verified=True,
                                valid_from=JUN, supersedes=["old"], subject="editor")))
        old = inspect_store(self.path, view="profiles", scope="project:a", as_of=JAN)
        new = self.inspect("profiles")
        self.assertEqual(old["records"][0]["provenance_records"], ["old"])
        self.assertEqual(new["records"][0]["provenance_records"], ["new"])
        citation = old["records"][0]["citations"][0]
        self.assertEqual(citation["valid_to"], JUN)
        self.assertEqual(citation["evidence_status"], "verified")
        self.assertEqual(citation["review_status"], "approved")
        self.assertNotIn("confidence", new["records"][0])

    def test_stored_derived_traits_are_ignored_and_temporary_tasks_do_not_become_profiles(self):
        self.write(store(record("task", memory_kind="task", review_status="approved", verified=True),
                         record("unverified", memory_kind="preference", review_status="approved"),
                         user_profiles=[{"trait": "INVENTED old confident trait", "confidence": 0.95}]))
        result = self.inspect("profiles")
        self.assertEqual(result["records"], [])
        self.assertEqual(result["summary"]["profiles"], 0)
        self.assertNotIn("INVENTED", json.dumps(result))

    def test_conflict_hint_has_scoped_citations_and_withholds_conflicting_profiles(self):
        self.write(store(record("a", "Use Vim", subject="editor", memory_kind="preference", review_status="approved", verified=True),
                         record("b", "Use Code", subject="editor", memory_kind="preference", review_status="approved", verified=True),
                         record("foreign", "SECRET foreign preference", subject="editor", scope="project:b")))
        self.assertEqual(self.inspect("profiles")["records"], [])
        result = self.inspect("conflicts", max_tokens=None)
        row = result["records"][0]
        self.assertEqual(row["status"], "unresolved")
        self.assertEqual({r["record_id"] for r in row["citations"]}, {"a", "b"})
        self.assertIn("not proof of contradiction", row["resolution"])
        self.assertNotIn("SECRET", json.dumps(result))

    def test_review_distinguishes_approval_from_quote_provenance_and_support(self):
        approved = record("approved", review_status="approved", memory_kind="preference")
        unreviewed = record("unreviewed", verified=True)
        paraphrase = record("paraphrase", review_status="approved", verified=True)
        paraphrase["evidence"]["assertion_support"] = "paraphrase"
        self.write(store(approved, unreviewed, paraphrase))
        rows = {r["record_id"]: r for r in self.inspect("review", max_tokens=None)["records"]}
        self.assertEqual(rows["approved"]["review_status"], "approved")
        self.assertEqual(rows["approved"]["evidence_status"], "unverified")
        self.assertEqual(rows["unreviewed"]["evidence_status"], "verified")
        self.assertEqual(rows["unreviewed"]["review_reasons"], ["review_unreviewed"])
        self.assertIn("assertion_support_paraphrase", rows["paraphrase"]["review_reasons"])

    def test_claimed_verification_with_broken_retained_proof_remains_in_review(self):
        broken = record("broken", verified=True, review_status="approved", memory_kind="preference")
        broken["evidence"]["quote_sha256"] = "0" * 64
        self.write(store(broken))
        result = self.inspect("review")
        self.assertIn("retained_proof_invalid", result["records"][0]["review_reasons"])
        self.assertEqual(self.inspect("profiles")["records"], [])

    def test_cli_view_routes_to_inspector_and_preserves_extraction_provenance(self):
        from contextlib import redirect_stdout
        import io
        import napmem_cli
        self.write(store(record(verified=True)))
        output = io.StringIO()
        with redirect_stdout(output):
            code = napmem_cli.main(["--pyramid", str(self.path), "--scope", "project:a", "inspect",
                                    "--view", "current", "--as-of", JUL])
        self.assertEqual(code, 0)
        result = json.loads(output.getvalue())
        self.assertEqual(result["records"][0]["evidence"]["extraction"]["method"], "synthetic")
        self.assertBudget(result, 16384, 2048)

    def test_quarantine_rejection_and_instructions_are_operator_review_data_only(self):
        self.write(store(record("quarantine", status="quarantined"), record("rejected", review_status="rejected"),
                         record("unsafe", instruction_bearing=True), record("good")))
        self.assertEqual([r["record_id"] for r in self.inspect()["records"]], ["good"])
        self.assertEqual([r["record_id"] for r in self.inspect("handoff")["records"]], [])
        rows = {r["record_id"]: r for r in self.inspect("review", max_tokens=None)["records"]}
        self.assertIn("instruction_bearing", rows["unsafe"]["review_reasons"])
        self.assertIn("status_quarantined", rows["quarantine"]["review_reasons"])
        self.assertIn("review_rejected", rows["rejected"]["review_reasons"])

    def test_staleness_uses_verification_then_observation_never_guesses_naive_time(self):
        self.write(store(record("old"), record("verified", last_verified_at="2026-06-30T00:00:00Z"),
                         record("unknown", created_at="2026-01-01T00:00:00", observed_at=None),
                         record("future", observed_at="2027-01-01T00:00:00Z")))
        rows = {r["record_id"]: r for r in self.inspect("stale", max_tokens=None)["records"]}
        self.assertEqual(set(rows), {"old", "unknown", "future"})
        self.assertEqual(rows["old"]["age"]["days"], 181.0)
        self.assertEqual(rows["unknown"]["age"]["basis"], "unknown")
        self.assertTrue(rows["future"]["age"]["future_timestamp"])
        self.assertEqual(rows["unknown"]["stale_reason"], "age_unknown")
        current = {r["record_id"]: r for r in self.inspect(max_tokens=None)["records"]}
        self.assertEqual(current["verified"]["age"], {"days": 1.0, "basis": "last_verified_at",
                                                    "timestamp": "2026-06-30T00:00:00Z", "future_timestamp": False})

    def test_exact_stale_threshold_and_fractional_cli_days_are_supported(self):
        self.write(store(record(last_verified_at="2026-06-30T12:00:00Z")))
        self.assertEqual(self.inspect("stale", stale_days=0.5)["pagination"]["total_count"], 1)
        self.assertEqual(self.inspect("stale", stale_days=0.501)["records"], [])

    def test_handoff_contains_actionable_context_and_cites_task_authority_limit(self):
        self.write(store(record("decision", memory_kind="decision"), record("preference", memory_kind="preference"),
                         record("task", memory_kind="task"), record("idea", memory_kind="idea"),
                         record("fact", memory_kind="observation")))
        result = self.inspect("handoff", max_tokens=None)
        self.assertEqual([r["record_id"] for r in result["records"]], ["decision", "preference", "task"])
        self.assertIn("Stele", result["task_authority"])
        for row in result["records"]:
            self.assertTrue(row["source"]["session_id"])
            self.assertIn("evidence_status", row)
            self.assertIn("age", row)

    def test_source_exclusion_is_applied_but_missing_source_memory_is_retained(self):
        self.write(store(record("excluded"), record("missing", source_state="missing"),
                         controls={"excluded_sources": {"session:session_excluded": True}}))
        for view in VIEWS:
            result = self.inspect(view, max_tokens=None)
            self.assertNotIn("/synthetic/excluded.md", json.dumps(result))
        row = self.inspect()["records"][0]
        self.assertEqual(row["record_id"], "missing")
        self.assertEqual(row["source"]["state"], "missing")
        self.assertFalse(row["source"]["rechecked"])

    def test_minimal_legacy_record_with_no_anchor_is_still_inspectable(self):
        self.write({"memory_records": [{"id": "minimal", "text": "Legacy observation"}]})
        result = inspect_store(self.path, scope=None, as_of=JUL)
        self.assertEqual(result["records"][0]["scope"], "legacy")
        self.assertEqual(result["records"][0]["source"], {"state": "unknown", "rechecked": False})

    def test_correction_controls_and_forgetting_are_reflected_without_store_writes(self):
        data = migrate_store(store(record("original", "Original editor rule")))
        apply_action(data, "correct", record_id="original", value="Corrected editor rule", at=JUN)
        self.write(data)
        before = self.path.read_bytes()
        current = self.inspect()["records"]
        self.assertEqual([r["text"] for r in current], ["Corrected editor rule"])
        self.assertEqual(current[0]["evidence"]["source_kind"], "operator")
        self.assertEqual(self.path.read_bytes(), before)
        apply_action(data, "forget", record_id="original", at=JUL)
        self.write(data)
        for view in VIEWS:
            self.assertEqual(self.inspect(view)["records"], [])

    def test_correction_hints_quote_paths_ids_and_only_preview_operator_controls(self):
        rid = "record id; $(private)"
        self.write(store(record(rid)))
        row = self.inspect()["records"][0]
        argv = shlex.split(row["correction"]["command"])
        self.assertEqual(argv, ["napmem", "--pyramid", str(self.path), "control", "correct", "--record-id", rid,
                                "--value", "<replacement text>", "--dry-run"])
        from napmem_cli import build_parser
        parsed = build_parser().parse_args(argv[1:])
        self.assertEqual(parsed.record_id, rid)
        self.assertTrue(parsed.dry_run)

    def test_pagination_is_truthful_after_view_filter_and_complete_entry_budget_drops(self):
        self.write(store(*[record(f"r{i:02}", "量子記憶😀" * 20) for i in range(8)]))
        first = self.inspect(offset=2, limit=4, max_tokens=None, max_bytes=4000)
        self.assertTrue(first["truncated"])
        self.assertGreater(len(first["records"]), 0)
        page = first["pagination"]
        self.assertEqual(page["total_count"], 8)
        self.assertEqual(page["returned_count"], len(first["records"]))
        self.assertEqual(page["next_offset"], 2 + len(first["records"]))
        self.assertEqual(first["omitted_count"], 4 - len(first["records"]))
        following = self.inspect(offset=page["next_offset"], limit=4, max_tokens=None)
        self.assertNotEqual(first["records"][-1]["record_id"], following["records"][0]["record_id"])
        self.assertBudget(first, 4000)

    def test_large_unicode_evidence_drops_whole_record_and_reports_blocked_page(self):
        data = record(verified=True)
        data["evidence"]["quote"] = "秘密😀" * 20000
        self.write(store(data))
        result = self.inspect(max_bytes=2000, max_tokens=500)
        self.assertEqual(result["records"], [])
        self.assertEqual(result["status"], "budget_exhausted")
        self.assertEqual(result["omitted_count"], 1)
        self.assertEqual(result["pagination"]["next_offset"], 0)
        self.assertTrue(result["pagination"]["has_more"])
        self.assertBudget(result, 2000, 500)

    def test_offset_beyond_end_is_empty_and_does_not_hide_total_count(self):
        self.write(store(record()))
        result = self.inspect(offset=20)
        self.assertEqual(result["records"], [])
        self.assertEqual(result["pagination"]["total_count"], 1)
        self.assertFalse(result["pagination"]["has_more"])
        self.assertIsNone(result["pagination"]["next_offset"])
        self.assertFalse(result["truncated"])

    def test_fixed_reference_is_repeatable_and_invalid_parameters_fail(self):
        self.write(store(record()))
        self.assertEqual(self.inspect(), self.inspect())
        invalid = ({"view": "unknown"}, {"offset": -1}, {"offset": True}, {"limit": 0}, {"limit": 1001},
                   {"stale_days": float("nan")}, {"stale_days": -1}, {"stale_days": True}, {"as_of": "2026-01-01"},
                   {"scope": "bad\x00scope"}, {"scope": "x" * 257}, {"max_bytes": 10}, {"max_tokens": 1})
        for kwargs in invalid:
            with self.subTest(kwargs=kwargs), self.assertRaises(ValueError):
                inspect_store(self.path, **kwargs)

    def test_exported_snapshot_is_inspectable_but_manifest_mismatch_is_rejected(self):
        from napmem_snapshots import export_snapshot
        self.write(store(record()))
        snapshot = Path(self.temp.name) / "export"
        export_snapshot(self.path, snapshot, include_cache=False)
        exported_store = snapshot / "napmem_pyramid.json"
        result = inspect_store(exported_store, scope="project:a", as_of=JUL)
        self.assertEqual(result["records"][0]["record_id"], "r1")
        exported_store.write_text(json.dumps(store(record(text="Tampered"))), encoding="utf-8")
        with self.assertRaises(ValueError):
            inspect_store(exported_store, scope="project:a", as_of=JUL)

    def test_managed_generation_cannot_downgrade_to_unverified_when_manifest_is_missing(self):
        generation = Path(self.temp.name) / "generations" / ("gen-7-" + "a" * 32)
        generation.mkdir(parents=True)
        pyramid = generation / "napmem_pyramid.json"
        pyramid.write_text(json.dumps(store(record())), encoding="utf-8")
        before = pyramid.read_bytes()
        with self.assertRaisesRegex(ValueError, "lost its manifest"):
            inspect_store(pyramid, scope="project:a", as_of=JUL)
        self.assertEqual(pyramid.read_bytes(), before)
        self.assertEqual([p.name for p in generation.iterdir()], ["napmem_pyramid.json"])

    def test_malformed_persistent_controls_or_store_is_not_silently_ignored(self):
        for data in (store(record(), controls={"unknown": []}), {"memory_records": "bad"},
                     {"version": "99.0.0"}):
            self.write(data)
            before = self.path.read_bytes()
            with self.subTest(data=data), self.assertRaises(ValueError):
                self.inspect()
            self.assertEqual(self.path.read_bytes(), before)


class SourceDiffTests(unittest.TestCase):
    def test_unified_hunks_are_literal_and_deterministic_including_no_final_newline(self):
        result = source_diff("first\nold", "first\nnew")
        self.assertEqual(result, source_diff("first\nold", "first\nnew"))
        self.assertEqual(result["records"], [{"diff": "@@ -1,2 +1,2 @@\n first\n-old\n\\ No newline at end of file\n+new\n\\ No newline at end of file\n"}])
        self.assertEqual(result["total_hunks"], 1)
        self.assertEqual(result["pagination"]["returned_count"], 1)

    def test_identical_content_has_no_change_or_headers(self):
        result = source_diff("same\n", "same\n")
        self.assertEqual(result["records"], [])
        self.assertEqual(result["headers"], [])
        self.assertEqual(result["old_sha256"], result["new_sha256"])

    def test_budget_drops_complete_hunks_with_exact_unicode_accounting(self):
        old = "old\n" + "same\n" * 20 + "last\n"
        new = "first\n" + "same\n" * 20 + "新😀" * 2000 + "\n"
        result = source_diff(old, new, context=1, max_bytes=1000)
        self.assertEqual(result["total_hunks"], 2)
        self.assertEqual(len(result["records"]), 1)
        self.assertEqual(result["omitted_count"], 1)
        self.assertTrue(result["truncated"])
        self.assertLessEqual(len(compact_json(result)), 1000)
        self.assertEqual(result["returned_bytes"], len(compact_json(result)))
        self.assertIn("-old\n+first\n", result["records"][0]["diff"])

    def test_diff_header_like_source_lines_are_not_discarded(self):
        result = source_diff("-- before\n", "++ after\n")
        self.assertIn("--- before\n+++ after\n", result["records"][0]["diff"])

    def test_inputs_context_and_metadata_budget_are_bounded(self):
        for old, new, kwargs in ((None, "", {}), ("", 1, {}), ("x" * (2 * 1024 * 1024 + 1), "", {}),
                                 ("a\n" * 20001, "", {}), ("", "", {"context": True}),
                                 ("", "", {"context": -1}), ("", "", {"max_bytes": 10})):
            with self.subTest(kwargs=kwargs), self.assertRaises(ValueError):
                source_diff(old, new, **kwargs)


if __name__ == "__main__":
    unittest.main()
