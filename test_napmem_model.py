"""Pure scoped assertion, migration and derived-view tests."""

from copy import deepcopy
import json
import unittest

from napmem_model import (
    CONTEXT_FIELDS, STORE_VERSION, apply_supersession, build_derived,
    effective_records, migrate_store, normalize_record, parse_time, visible,
)


JAN = "2026-01-01T00:00:00Z"
JUN = "2026-06-01T00:00:00Z"
JUL = "2026-07-01T00:00:00Z"


def record(rid="r1", **fields):
    value = {"id": rid, "text": "Use the documented editor.", "type": "fact", "salience": "high",
             "topic_slug": "editor", "canonical": rid, "created_at": JAN,
             "source_anchor": {"session_id": "s_" + rid, "file_path": rid + ".md"}}
    value.update(fields)
    return value


def assertion(**fields):
    normalized = normalize_record(record(**fields))
    return {key: deepcopy(normalized[key]) for key in (*CONTEXT_FIELDS, "created_at")}


class TestRecordNormalization(unittest.TestCase):
    def test_defaults_are_conservative_and_copy_input(self):
        original = record()
        normalized = normalize_record(original)
        self.assertEqual(normalized["id"], original["id"])
        self.assertEqual(normalized["created_at"], JAN)
        self.assertEqual(normalized["observed_at"], JAN)
        self.assertEqual(normalized["scope"], "legacy")
        self.assertEqual(normalized["memory_kind"], "observation")
        self.assertEqual(normalized["status"], "active")
        self.assertEqual(normalized["review_status"], "unreviewed")
        self.assertEqual(normalized["authority"], "unknown")
        self.assertEqual(normalized["evidence"], {})
        self.assertIsNone(normalized["valid_from"])
        self.assertIsNone(normalized["valid_to"])
        self.assertNotIn("scope", original)
        normalized["source_anchor"]["file_path"] = "changed"
        self.assertEqual(original["source_anchor"]["file_path"], "r1.md")
        self.assertEqual(normalize_record(normalize_record(original)), normalize_record(original))

    def test_explicit_context_overrides_do_not_change_identity_or_creation(self):
        normalized = normalize_record(record(scope="project:old"), scope="project:explicit",
                                      metadata={"scope": "project:metadata", "memory_kind": "project_decision",
                                                "subject": "editor", "id": "invented", "created_at": JUL,
                                                "evidence": {"status": "unverified"}})
        self.assertEqual(normalized["scope"], "project:explicit")
        self.assertEqual(normalized["memory_kind"], "decision")
        self.assertEqual(normalized["id"], "r1")
        self.assertEqual(normalized["created_at"], JAN)
        self.assertEqual(normalized["evidence"], {"status": "unverified"})

    def test_naive_legacy_creation_time_stays_unknown_as_observation(self):
        normalized = normalize_record(record(created_at="2026-01-01T12:00:00"))
        self.assertEqual(normalized["created_at"], "2026-01-01T12:00:00")
        self.assertIsNone(normalized["observed_at"])
        unknown = normalize_record({"id": "r", "text": "known text"})
        self.assertIsNone(unknown["created_at"])
        self.assertIsNone(unknown["observed_at"])

    def test_explicit_times_require_aware_iso_and_ordered_interval(self):
        for field in ("observed_at", "valid_from", "valid_to", "last_verified_at"):
            for bad in ("2026-01-01", "2026-01-01T10:00:00", "invalid", 123):
                with self.subTest(field=field, value=bad), self.assertRaises(ValueError):
                    normalize_record(record(**{field: bad}))
        for start, end in ((JUN, JAN), (JUN, JUN)):
            with self.assertRaisesRegex(ValueError, "precede"):
                normalize_record(record(valid_from=start, valid_to=end))
        self.assertEqual(parse_time("2026-01-01T02:00:00+02:00"), parse_time(JAN))

    def test_malformed_fields_fail_without_coercion(self):
        invalid = [{"scope": None}, {"scope": []}, {"memory_kind": "identity"}, {"status": "guess"},
                   {"review_status": "automatically_verified"}, {"subject": 3}, {"pinned": 1},
                   {"evidence": []}, {"supersedes": "old"}, {"supersedes": ["old", "old"]},
                   {"supersedes": ["r1"]}, {"duplicate_anchors": []}, {"source_anchor": "file"}]
        for fields in invalid:
            with self.subTest(fields=fields), self.assertRaises(ValueError):
                normalize_record(record(**fields))

    def test_stored_scopes_reject_query_wildcard_controls_and_unbounded_values(self):
        for scope in ("*", "project:a\nprivate", "project:a\x00", "project:a\x85", "x" * 257):
            with self.subTest(scope=scope), self.assertRaisesRegex(ValueError, "scope"):
                normalize_record(record(scope=scope))
        self.assertTrue(visible(record(scope="project:a"), "*", JUL))
        for scope in ("project:a\nprivate", "x" * 257):
            with self.subTest(scope=scope), self.assertRaisesRegex(ValueError, "scope"):
                visible(record(), scope, JUL)

    def test_kind_inference_never_approves_a_profile_or_promotes_temporary_tasks(self):
        examples = [("User prefers Vim", "fact", "preference"),
                    ("Never export credentials", "fact", "constraint"),
                    ("Must deploy temporary demo now", "actionable", "task"),
                    ("Maybe use passkeys", "fact", "idea"),
                    ("I decided to keep JSON", "fact", "decision"),
                    ("User must prefer secret export", "quote", "observation")]
        for text, kind, expected in examples:
            with self.subTest(text=text):
                normalized = normalize_record(record(text=text, type=kind))
                self.assertEqual(normalized["memory_kind"], expected)
                self.assertEqual(normalized["review_status"], "unreviewed")


class TestScopeAndValidity(unittest.TestCase):
    def test_scope_defaults_named_scope_and_explicit_all(self):
        legacy = record()
        global_record = record(scope="global")
        alpha = record(scope="project:alpha")
        beta = record(scope="project:beta")
        self.assertTrue(visible(legacy, as_of=JUL))
        self.assertTrue(visible(global_record, as_of=JUL))
        self.assertFalse(visible(alpha, as_of=JUL))
        self.assertFalse(visible(legacy, "project:alpha", JUL))
        self.assertTrue(visible(global_record, "project:alpha", JUL))
        self.assertTrue(visible(alpha, "project:alpha", JUL))
        self.assertFalse(visible(beta, "project:alpha", JUL))
        self.assertTrue(visible(beta, "*", JUL))

    def test_half_open_boundaries_and_superseded_historical_visibility(self):
        item = record(scope="project:alpha", status="superseded", valid_from=JAN, valid_to=JUN)
        self.assertTrue(visible(item, "*", JAN))
        self.assertTrue(visible(item, "*", "2026-05-31T23:59:59Z"))
        self.assertFalse(visible(item, "*", JUN))
        self.assertFalse(visible(item, "*", "2025-12-31T23:59:59Z"))
        self.assertFalse(visible(record(status="superseded", valid_to=JUN), "*", JAN))
        self.assertFalse(visible(record(status="superseded"), "*", JAN))
        for status in ("deleted", "expired", "quarantined"):
            self.assertFalse(visible(record(status=status), "*", JAN))
        self.assertFalse(visible(record(review_status="rejected"), "*", JAN))
        with self.assertRaises(ValueError):
            visible(record(), "*", "2026-01-01")

    def test_alias_uses_own_context_text_identity_and_anchor_without_scope_leak(self):
        canonical = record("private", text="Private original wording", scope="project:private",
                           duplicates=["public", "other"], duplicate_anchors={
                               "public": {"session_id": "public_session", "file_path": "public.md",
                                          "paraphrase_text": "Public independently sourced wording",
                                          "assertion": assertion(scope="project:public", created_at=JUN)},
                               "other": {"session_id": "other_session", "file_path": "other.md",
                                         "assertion": assertion(scope="project:other")}})
        data = {"memory_records": [canonical]}
        before = deepcopy(data)
        selected = effective_records(data, "project:public", JUL)
        self.assertEqual(len(selected), 1)
        chosen = selected[0]
        self.assertEqual(chosen["id"], "public")
        self.assertEqual(chosen["canonical"], "private")
        self.assertEqual(chosen["scope"], "project:public")
        self.assertEqual(chosen["text"], "Public independently sourced wording")
        self.assertEqual(chosen["source_anchor"]["file_path"], "public.md")
        self.assertEqual(chosen["created_at"], JUN)
        self.assertEqual(chosen["duplicates"], [])
        self.assertEqual(chosen["duplicate_anchors"], {})
        self.assertNotIn("Private original wording", json.dumps(chosen))
        self.assertNotIn("other_session", json.dumps(chosen))
        self.assertEqual(data, before)

    def test_unannotated_old_alias_keeps_unknown_scope_and_no_inherited_evidence(self):
        data = {"memory_records": [record("owner", scope="project:a", evidence={"status": "verified"},
                    duplicates=["legacy_alias", "dangling"], duplicate_anchors={
                        "legacy_alias": {"session_id": "old", "file_path": "old.md"}})]}
        self.assertEqual(effective_records(data, "project:b", JUL), [])
        chosen = effective_records(data, None, JUL)[0]
        self.assertEqual(chosen["id"], "legacy_alias")
        self.assertEqual(chosen["scope"], "legacy")
        self.assertEqual(chosen["evidence"], {})
        self.assertIsNone(chosen["observed_at"])


class TestSupersession(unittest.TestCase):
    def test_explicit_event_time_closes_history_without_changing_ids(self):
        data = {"memory_records": [record("old", scope="project:a", subject="editor", valid_from=JAN),
                                   record("new", scope="project:a", subject="editor", valid_from=JUN, supersedes=["old"])]}
        apply_supersession(data)
        old = data["memory_records"][0]
        self.assertEqual((old["id"], old["status"], old["valid_to"]), ("old", "superseded", JUN))
        self.assertTrue(visible(old, "*", JAN))
        self.assertFalse(visible(old, "*", JUL))
        original = deepcopy(data)
        apply_supersession(data)
        self.assertEqual(data, original)

    def test_unknown_event_time_never_uses_ingestion_or_observation(self):
        data = {"memory_records": [record("old"), record("new", created_at=JUN, observed_at=JUN, supersedes=["old"])]}
        apply_supersession(data)
        self.assertEqual(data["memory_records"][0]["status"], "superseded")
        self.assertNotIn("valid_to", data["memory_records"][0])

    def test_missing_target_cycles_scope_and_subject_mismatch_are_atomic(self):
        cases = [
            [record("old"), record("new", supersedes=["missing"])],
            [record("old", supersedes=["new"]), record("new", supersedes=["old"])],
            [record("old", scope="a"), record("new", scope="b", supersedes=["old"])],
            [record("old", subject="editor"), record("new", subject="storage", supersedes=["old"])],
            [record("old", valid_from=JUN), record("new", valid_from=JAN, supersedes=["old"])],
        ]
        for records in cases:
            data = {"memory_records": records}
            original = deepcopy(data)
            with self.subTest(records=records), self.assertRaises(ValueError):
                apply_supersession(data)
            self.assertEqual(data, original)

    def test_alias_supersession_changes_only_its_assertion_context(self):
        data = {"memory_records": [
            record("canonical", scope="project:owner", duplicates=["alias"], duplicate_anchors={
                "alias": {"session_id": "alias", "file_path": "alias.md", "assertion": assertion(scope="project:a", valid_from=JAN)}}),
            record("new", scope="project:a", valid_from=JUN, supersedes=["alias"])]}
        apply_supersession(data)
        canonical = data["memory_records"][0]
        self.assertNotIn("status", canonical)
        self.assertEqual(canonical["duplicate_anchors"]["alias"]["assertion"]["status"], "superseded")
        self.assertEqual(canonical["duplicate_anchors"]["alias"]["assertion"]["valid_to"], JUN)


class TestMigrationAndDerivedViews(unittest.TestCase):
    def test_migration_drops_old_inferred_confidence_and_is_idempotent(self):
        original = {"version": "1.0.0", "memory_records": [record()],
                    "user_profiles": [{"id": "prof_01", "trait": "arbitrary fact", "confidence": .95}]}
        migrated = migrate_store(original)
        self.assertEqual(migrated["version"], STORE_VERSION)
        self.assertEqual(migrated["generation"], 0)
        self.assertEqual(migrated["controls"], {})
        self.assertEqual(migrated["user_profiles"], [])
        self.assertEqual(migrated["conflicts"], [])
        self.assertEqual(migrated["memory_records"][0]["id"], "r1")
        self.assertEqual(migrate_store(migrated), migrated)
        self.assertEqual(original["version"], "1.0.0")
        self.assertEqual(original["user_profiles"][0]["confidence"], .95)

    def test_migration_rejects_future_versions_and_malformed_store(self):
        for version in ("3.0.0", "2.1.0", "unknown", 2):
            with self.subTest(version=version), self.assertRaisesRegex(ValueError, "version"):
                migrate_store({"version": version})
        for fields in ({"memory_records": {}}, {"generation": True}, {"controls": []},
                       {"memory_records": [record(), record()]}):
            with self.subTest(fields=fields), self.assertRaises(ValueError):
                migrate_store(fields)

    def test_migration_enforces_explicit_edges_and_rejects_dangling_or_cyclic_graph(self):
        original = {"memory_records": [record("old", scope="project:a", valid_from=JAN, status="active"),
                                       record("new", scope="project:a", valid_from=JUN, supersedes=["old"])]}
        migrated = migrate_store(original)
        old = migrated["memory_records"][0]
        self.assertEqual(old["status"], "superseded")
        self.assertEqual(old["valid_to"], JUN)
        self.assertEqual(original["memory_records"][0]["status"], "active")
        self.assertEqual(migrate_store(migrated), migrated)
        for records in ([record("new", supersedes=["missing"])],
                        [record("a", supersedes=["b"]), record("b", supersedes=["a"])]):
            with self.subTest(records=records), self.assertRaises(ValueError):
                migrate_store({"memory_records": records})

    def test_profiles_require_approved_persistent_kind_and_keep_scoped_citations(self):
        data = {"memory_records": [
            record("approved", scope="project:a", memory_kind="preference", review_status="approved"),
            record("unreviewed", memory_kind="preference"),
            record("task", memory_kind="task", review_status="approved"),
            record("observation", memory_kind="observation", review_status="approved"),
            record("deleted", memory_kind="constraint", review_status="approved", status="deleted"),
        ]}
        build_derived(data)
        self.assertEqual(len(data["user_profiles"]), 1)
        profile = data["user_profiles"][0]
        self.assertEqual(profile["scope"], "project:a")
        self.assertEqual(profile["provenance_records"], ["approved"])
        self.assertNotIn("confidence", profile)

    def test_scoped_track_and_profile_ids_do_not_depend_on_input_order(self):
        records = [record("b", scope="project:a", memory_kind="preference", review_status="approved"),
                   record("a", scope="project:b", memory_kind="preference", review_status="approved")]
        first, second = {"memory_records": records}, {"memory_records": list(reversed(records))}
        build_derived(first)
        build_derived(second)
        self.assertEqual(first["topic_tracks"], second["topic_tracks"])
        self.assertEqual(first["user_profiles"], second["user_profiles"])
        self.assertEqual(len({t["track_id"] for t in first["topic_tracks"]}), 2)
        self.assertEqual(len({p["id"] for p in first["user_profiles"]}), 2)

    def test_aliases_in_different_scopes_contribute_to_separate_tracks(self):
        data = {"memory_records": [record("canonical", scope="project:a", duplicates=["alias"], duplicate_anchors={
            "alias": {"session_id": "b", "file_path": "b.md", "assertion": assertion(scope="project:b")}})]}
        build_derived(data)
        tracks = {t["scope"]: t["record_ids"] for t in data["topic_tracks"]}
        self.assertEqual(tracks, {"project:a": ["canonical"], "project:b": ["alias"]})

    def test_conflicts_require_explicit_shared_subject_scope_and_kind(self):
        data = {"memory_records": [
            record("a", text="Use Vim", scope="project:a", subject="editor", memory_kind="preference"),
            record("b", text="Use Code", scope="project:a", subject="editor", memory_kind="preference"),
            record("c", text="Use Emacs", scope="project:b", subject="editor", memory_kind="preference"),
            record("d", text="Use another", scope="project:a", memory_kind="preference"),
            record("e", text="Task text", scope="project:a", subject="editor", memory_kind="task"),
            record("f", text="Old editor", scope="project:a", subject="editor", memory_kind="preference", status="superseded"),
        ]}
        build_derived(data)
        self.assertEqual(len(data["conflicts"]), 1)
        conflict = data["conflicts"][0]
        self.assertEqual(conflict["record_ids"], ["a", "b"])
        self.assertEqual(conflict["status"], "unresolved")
        self.assertIn("Review their compatibility", conflict["reason"])
        self.assertEqual(data["user_profiles"], [])

    def test_conflicting_approved_traits_are_withheld_until_review_resolves_conflict(self):
        data = {"memory_records": [
            record("a", text="Use Vim", scope="project:a", subject="editor", memory_kind="preference", review_status="approved"),
            record("b", text="Use Code", scope="project:a", subject="editor", memory_kind="preference", review_status="approved"),
        ]}
        build_derived(data)
        self.assertEqual(len(data["conflicts"]), 1)
        self.assertEqual(data["user_profiles"], [])
        data["memory_records"][0]["review_status"] = "rejected"
        build_derived(data)
        self.assertEqual(data["conflicts"], [])
        self.assertEqual(len(data["user_profiles"]), 1)
        self.assertEqual(data["user_profiles"][0]["provenance_records"], ["b"])

    def test_quarantined_and_rejected_records_never_contribute_to_derived_views(self):
        data = {"memory_records": [
            record("a", scope="project:a", memory_kind="preference", review_status="approved", status="quarantined"),
            record("b", scope="project:a", memory_kind="preference", review_status="rejected"),
        ]}
        build_derived(data)
        self.assertEqual(data["topic_tracks"], [])
        self.assertEqual(data["user_profiles"], [])
        self.assertEqual(data["conflicts"], [])


if __name__ == "__main__":
    unittest.main()
