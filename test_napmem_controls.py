"""Pure replay, deletion-family and operator-preview tests."""

from copy import deepcopy
import json
import unittest

from napmem_controls import (
    JOURNAL_LIMIT, apply_action, apply_controls, filter_incoming, fingerprint,
    preview_action, source_is_excluded,
)
from napmem_model import CONTEXT_FIELDS, migrate_store, normalize_record, visible


JAN = "2026-01-01T00:00:00Z"
JUN = "2026-06-01T00:00:00Z"
JUL = "2026-07-01T00:00:00Z"


def record(rid="old", text="Use the first editor.", **fields):
    value = {"id": rid, "text": text, "type": "fact", "salience": "high",
             "scope": "project:a", "memory_kind": "preference", "subject": "editor",
             "created_at": JAN, "source_anchor": {"session_id": "s_" + rid, "file_path": rid + ".md"}}
    value.update(fields)
    return normalize_record(value)


def store(*records, **fields):
    value = {"version": "2.0.0", "generation": 7, "memory_records": list(records), "controls": {},
             "raw_conversations": [{"session_id": "s_" + r["id"], "file_path": r["id"] + ".md"} for r in records]}
    value.update(fields)
    return migrate_store(value)


def aliases():
    alias = record("alias", "Second source wording", scope="project:a", created_at=JUN)
    anchor = deepcopy(alias["source_anchor"])
    anchor["paraphrase_text"] = alias["text"]
    anchor["assertion"] = {field: deepcopy(alias[field]) for field in (*CONTEXT_FIELDS, "created_at")}
    return record("owner", "First source wording", duplicates=["alias"], duplicate_anchors={"alias": anchor})


class TestPersistentReplayControls(unittest.TestCase):
    def test_fingerprint_matches_exact_dedup_and_distinguishes_scope(self):
        first = record(text="  ORIGINAL Wording  ")
        same = record("fresh_id", "original wording")
        other_scope = record("third", "original wording", scope="project:b")
        self.assertEqual(fingerprint(first), fingerprint(same))
        self.assertNotEqual(fingerprint(first), fingerprint(other_scope))
        self.assertEqual(len(fingerprint(first)), 64)

    def test_correction_is_verified_operator_evidence_and_rejects_original_without_false_validity(self):
        data = store(record(text="Original assertion private marker"))
        receipt = apply_action(data, "correct", record_id="old", value="Corrected assertion private marker", at=JUN)
        records = {r["id"]: r for r in data["memory_records"]}
        corrected = next(r for r in records.values() if r["id"].startswith("rec_control_"))
        self.assertEqual(records["old"]["status"], "superseded")
        self.assertEqual(records["old"]["review_status"], "rejected")
        self.assertIsNone(records["old"]["valid_to"])
        self.assertEqual(corrected["corrects"], "old")
        self.assertEqual(corrected["supersedes"], [])
        self.assertEqual(corrected["review_status"], "approved")
        self.assertEqual(corrected["evidence"]["source_kind"], "operator")
        self.assertEqual(corrected["evidence"]["quote"], corrected["text"])
        self.assertTrue(corrected["source_anchor"]["file_path"].startswith("napmem:control/"))
        self.assertEqual(data["generation"], 7)
        self.assertEqual(receipt["proposed_generation"], 8)
        self.assertEqual(receipt["cache"], "pending_parent_purge")
        self.assertEqual(receipt["mirrors"], "pending_acknowledgment")
        self.assertEqual(receipt["backups"], "operator_managed")
        control = next(iter(data["controls"]["corrections"].values()))
        self.assertIn("old", control["original_ids"])
        self.assertNotIn("Original assertion private marker", json.dumps(data["controls"]))

    def test_source_replay_cannot_restore_corrected_original_but_new_scope_is_independent(self):
        original = record()
        data = store(original)
        apply_action(data, "correct", record_id="old", value="Use the corrected editor.", at=JUN)
        replay = record("fresh", original["text"])
        other_scope = record("other", original["text"], scope="project:b")
        self.assertEqual([r["id"] for r in filter_incoming(data, [replay, other_scope])], ["other"])
        corrected_id = data["controls"]["assertions"][0]["id"]
        data["memory_records"] = []
        apply_controls(data)
        self.assertEqual([r["id"] for r in data["memory_records"]], [corrected_id])
        saved = deepcopy(data)
        apply_controls(data)
        self.assertEqual(data, saved)

    def test_correction_retires_semantic_alias_wording_before_promotion_can_revive_it(self):
        data = store(aliases())
        apply_action(data, "correct", record_id="owner", value="Use the corrected setting.", at=JUN)
        owner = data["memory_records"][0]
        self.assertEqual(owner["review_status"], "rejected")
        self.assertEqual(owner["duplicate_anchors"]["alias"]["assertion"]["review_status"], "rejected")
        self.assertEqual(filter_incoming(data, [record("fresh", "Second source wording")]), [])
        apply_action(data, "exclude", source="owner.md", at=JUL)
        promoted = next(r for r in data["memory_records"] if r["id"] == "alias")
        self.assertFalse(visible(promoted, "*", JUL))
        corrected = next(r for r in data["memory_records"] if r["id"].startswith("rec_control_"))
        self.assertTrue(visible(corrected, "*", JUL))

    def test_pin_review_and_expiry_survive_fresh_record_ids_without_mutating_inputs(self):
        original = record()
        data = store(original)
        apply_action(data, "pin", record_id="old", at=JUN)
        apply_action(data, "approve", record_id="old", at=JUN)
        apply_action(data, "expire", record_id="old", value=JUL, at=JUN)
        incoming = record("fresh")
        before = deepcopy(incoming)
        filtered = filter_incoming(data, [incoming])
        self.assertEqual(incoming, before)
        data["memory_records"] = filtered
        apply_controls(data)
        current = data["memory_records"][0]
        self.assertTrue(current["pinned"])
        self.assertEqual(current["review_status"], "approved")
        self.assertEqual(current["valid_to"], "2026-07-01T00:00:00+00:00")
        self.assertEqual(current["status"], "active")
        self.assertTrue(visible(current, "*", JUN))
        self.assertFalse(visible(current, "*", JUL))
        apply_action(data, "unpin", record_id="fresh", at=JUN)
        self.assertFalse(data["memory_records"][0]["pinned"])

    def test_approved_temporary_task_never_becomes_profile(self):
        data = store(record(memory_kind="task", type="actionable", text="Deploy temporary demo build."))
        apply_action(data, "approve", record_id="old", at=JUN)
        self.assertEqual(data["memory_records"][0]["review_status"], "approved")
        self.assertEqual(data["user_profiles"], [])


class TestForgetAndSourceExclusion(unittest.TestCase):
    def test_forgetting_alias_purges_whole_family_and_blocks_each_wording(self):
        original = aliases()
        data = store(original)
        data["raw_conversations"].append({"session_id": "s_alias", "file_path": "alias.md"})
        apply_action(data, "pin", record_id="owner", at=JUN)
        receipt = apply_action(data, "forget", record_id="alias", at=JUN)
        self.assertEqual(set(receipt["affected_ids"]), {"owner", "alias"})
        self.assertEqual(data["memory_records"], [])
        self.assertEqual(data["raw_conversations"], [])
        self.assertEqual(data["controls"]["overrides"], {})
        self.assertEqual(len(data["controls"]["tombstones"]), 2)
        serialized = json.dumps(data)
        self.assertNotIn("First source wording", serialized)
        self.assertNotIn("Second source wording", serialized)
        self.assertEqual(filter_incoming(data, [record("new", "First source wording"),
                                                record("new2", "Second source wording")]), [])
        self.assertEqual(len(filter_incoming(data, [record("other", "First source wording", scope="project:b")])), 1)

    def test_forgetting_correction_descendant_removes_ancestors_and_all_control_text(self):
        data = store(record(text="Original secret content"))
        apply_action(data, "correct", record_id="old", value="First replacement secret", at=JUN)
        first = data["controls"]["assertions"][0]["id"]
        apply_action(data, "correct", record_id=first, value="Final replacement secret", at=JUL)
        final = data["controls"]["assertions"][-1]["id"]
        apply_action(data, "pin", record_id=final, at=JUL)
        apply_action(data, "forget", record_id=final, at=JUL)
        self.assertEqual(data["memory_records"], [])
        self.assertEqual(data["controls"]["assertions"], [])
        self.assertEqual(data["controls"]["corrections"], {})
        self.assertEqual(data["controls"]["overrides"], {})
        for wording in ("Original secret content", "First replacement secret", "Final replacement secret"):
            self.assertNotIn(wording, json.dumps(data))
            self.assertEqual(filter_incoming(data, [record("fresh", wording)]), [])

    def test_forgetting_original_also_removes_retained_correction_when_original_record_is_missing(self):
        data = store(record())
        apply_action(data, "correct", record_id="old", value="Replacement", at=JUN)
        data["memory_records"] = [r for r in data["memory_records"] if r["id"] != "old"]
        apply_action(data, "forget", record_id="old", at=JUL)
        self.assertEqual(data["memory_records"], [])
        self.assertEqual(data["controls"]["assertions"], [])
        self.assertEqual(filter_incoming(data, [record("replay")]), [])

    def test_excluding_source_promotes_remaining_alias_with_own_full_context(self):
        original = aliases()
        data = store(original)
        data["raw_conversations"].append({"session_id": "s_alias", "file_path": "alias.md"})
        apply_action(data, "exclude", source="folder/../owner.md", at=JUN)
        self.assertTrue(source_is_excluded(data, "owner.md"))
        self.assertTrue(source_is_excluded(data, "a/../owner.md"))
        self.assertEqual(len(data["memory_records"]), 1)
        promoted = data["memory_records"][0]
        self.assertEqual((promoted["id"], promoted["canonical"]), ("alias", "alias"))
        self.assertEqual(promoted["text"], "Second source wording")
        self.assertEqual(promoted["created_at"], JUN)
        self.assertEqual(promoted["source_anchor"]["session_id"], "s_alias")
        self.assertEqual(promoted["scope"], "project:a")
        self.assertEqual([r["session_id"] for r in data["raw_conversations"]], ["s_alias"])
        self.assertEqual(filter_incoming(data, [record("replay", source_anchor={"session_id": "another", "file_path": "owner.md"})]), [])
        apply_action(data, "include", source="owner.md", at=JUN)
        self.assertFalse(source_is_excluded(data, "owner.md"))
        self.assertEqual(len(filter_incoming(data, [original])), 1)

    def test_forget_session_removes_only_that_source_and_keeps_shared_claim(self):
        data = store(aliases())
        receipt = apply_action(data, "forget_session", source="session:s_owner", at=JUN)
        self.assertEqual([r["id"] for r in data["memory_records"]], ["alias"])
        self.assertTrue(source_is_excluded(data, "moved.md", session_id="s_owner"))
        self.assertFalse(source_is_excluded(data, "alias.md", session_id="s_alias"))
        self.assertEqual(data["controls"]["tombstones"], [])
        self.assertEqual(receipt["completion_scope"], "selected_session_occurrences")
        self.assertEqual(receipt["independent_sources"], "retained")

    def test_forget_session_cannot_be_undone_by_include_or_downgraded_to_exclusion(self):
        data = store(aliases())
        apply_action(data, "forget_session", source="session:s_owner", at=JUN)
        self.assertEqual(data["controls"]["excluded_sources"]["session:s_owner"], "forgotten")
        apply_action(data, "exclude", source="session:s_owner", at=JUL)
        self.assertEqual(data["controls"]["excluded_sources"]["session:s_owner"], "forgotten")
        original = deepcopy(data)
        with self.assertRaisesRegex(ValueError, "forgotten"):
            preview_action(data, "include", source="session:s_owner", at=JUL)
        with self.assertRaisesRegex(ValueError, "forgotten"):
            apply_action(data, "include", source="session:s_owner", at=JUL)
        self.assertEqual(data, original)
        replay = record("fresh", source_anchor={"session_id": "s_owner", "file_path": "moved.md"})
        self.assertEqual(filter_incoming(data, [replay]), [])

    def test_forgetting_original_session_keeps_independent_operator_correction(self):
        data = store(record())
        apply_action(data, "correct", record_id="old", value="Operator replacement", at=JUN)
        corrected = data["controls"]["assertions"][0]["id"]
        receipt = apply_action(data, "forget_session", source="session:s_old", at=JUL)
        self.assertEqual([r["id"] for r in data["memory_records"]], [corrected])
        self.assertEqual(len(data["controls"]["assertions"]), 1)
        self.assertEqual(receipt["operator_assertions"], "separately_owned_unless_selected")

    def test_missing_raw_source_does_not_implicitly_exclude_or_forget(self):
        data = store(record(source_state="deleted"))
        apply_controls(data)
        self.assertEqual([r["id"] for r in data["memory_records"]], ["old"])
        self.assertFalse(source_is_excluded(data, "old.md"))

    def test_forget_scrubs_surviving_supersession_references(self):
        old = record("old", text="Old fact", subject="old")
        other = record("other", text="Independent fact", subject="old", supersedes=["old"])
        data = store(old, other)
        apply_action(data, "forget", record_id="old", at=JUN)
        self.assertEqual([r["id"] for r in data["memory_records"]], ["other"])
        self.assertEqual(data["memory_records"][0]["supersedes"], [])


class TestPreviewValidationAndPrivacy(unittest.TestCase):
    def test_preview_is_concrete_nonmutating_and_token_reuses_preview_time(self):
        data = store(record())
        original = deepcopy(data)
        preview = preview_action(data, "correct", record_id="old", value="Replacement")
        self.assertEqual(data, original)
        self.assertEqual(preview["new_value"], "Replacement")
        receipt = apply_action(data, "correct", record_id="old", value="Replacement",
                               expected_generation=7, preview_token=preview["preview_token"])
        self.assertEqual(receipt["affected_ids"], preview["affected_ids"])
        self.assertEqual(data["controls"]["assertions"][0]["created_at"], preview["at"])

    def test_snapshot_request_and_generation_conflicts_are_atomic(self):
        for mutation in ("snapshot", "generation", "request", "token"):
            data = store(record())
            preview = preview_action(data, "pin", record_id="old", at=JUN)
            if mutation == "snapshot":
                data["memory_records"][0]["text"] = "Concurrent edit"
            if mutation == "generation":
                data["generation"] += 1
            original = deepcopy(data)
            kwargs = {"record_id": "old", "at": JUN, "preview_token": preview["preview_token"]}
            if mutation == "request":
                kwargs["record_id"] = "different"
            if mutation == "token":
                kwargs["preview_token"] = "invalid"
            with self.subTest(mutation=mutation), self.assertRaises(ValueError):
                apply_action(data, "pin", **kwargs)
            self.assertEqual(data, original)
        for generation in (6, True, 7.0):
            data = store(record())
            with self.assertRaisesRegex(ValueError, "Generation"):
                apply_action(data, "pin", record_id="old", expected_generation=generation, at=JUN)

    def test_invalid_expiry_or_correction_leaves_state_unchanged(self):
        for action, value in (("expire", JAN), ("correct", ""), ("correct", "Use the first editor.")):
            data = store(record(valid_from=JUN))
            before = deepcopy(data)
            with self.subTest(action=action, value=value), self.assertRaises(ValueError):
                apply_action(data, action, record_id="old", value=value, at=JUN)
            self.assertEqual(data, before)
            with self.assertRaises(ValueError):
                preview_action(data, action, record_id="old", value=value, at=JUN)

    def test_malformed_controls_are_never_discarded_as_cache(self):
        invalid = [{"unknown": {}}, {"tombstones": [{"scope": "project:a", "text": "private"}]},
                   {"overrides": {"wrong": {"pinned": True}}}, {"excluded_sources": {"a/../b.md": True}},
                   {"excluded_sources": {"a.md": False}}, {"excluded_sources": {"a.md": "temporary"}},
                   {"excluded_sources": {"session:": "forgotten"}}, {"assertions": [record()]},
                   {"corrections": {"0" * 64: {"assertion_id": "missing", "original_ids": ["old"]}}},
                   {"journal": [{"action": "correct", "text": "private"}]}]
        for controls in invalid:
            data = store(record())
            data["controls"] = controls
            before = deepcopy(data)
            with self.subTest(controls=controls), self.assertRaises(ValueError):
                apply_controls(data)
            self.assertEqual(data, before)

    def test_tampered_operator_anchor_or_correction_graph_fails_closed(self):
        data = store(record())
        apply_action(data, "correct", record_id="old", value="First replacement", at=JUN)
        first = data["controls"]["assertions"][0]["id"]
        apply_action(data, "correct", record_id=first, value="Final replacement", at=JUL)
        for mutation in ("anchor", "revision", "cycle", "unhashable_target", "journal"):
            corrupted = deepcopy(data)
            if mutation == "anchor":
                corrupted["controls"]["assertions"][0]["source_anchor"]["file_path"] = "old.md"
            elif mutation == "revision":
                corrupted["controls"]["assertions"][0]["evidence"]["revision"] = "invented"
            elif mutation == "cycle":
                corrupted["controls"]["assertions"][0]["corrects"] = corrupted["controls"]["assertions"][1]["id"]
            elif mutation == "unhashable_target":
                next(iter(corrupted["controls"]["corrections"].values()))["assertion_id"] = []
            else:
                corrupted["controls"]["journal"][0]["fields"] = ["PRIVATE_TEXT"]
            before = deepcopy(corrupted)
            with self.subTest(mutation=mutation), self.assertRaises(ValueError):
                apply_controls(corrupted)
            self.assertEqual(corrupted, before)

    def test_journal_contains_only_ids_hashes_field_names_and_action_time(self):
        data = store(record(text="PRIVATE_ORIGINAL_TEXT"))
        apply_action(data, "correct", record_id="old", value="PRIVATE_REPLACEMENT_TEXT", at=JUN)
        journal = data["controls"]["journal"]
        self.assertNotIn("PRIVATE_ORIGINAL_TEXT", json.dumps(journal))
        self.assertNotIn("PRIVATE_REPLACEMENT_TEXT", json.dumps(journal))
        self.assertEqual(set(journal[0]), {"action", "id", "at", "affected_ids", "hashes", "fields"})
        event = deepcopy(journal[0])
        data["controls"]["journal"] = [deepcopy(event) for _ in range(JOURNAL_LIMIT)]
        corrected = data["controls"]["assertions"][0]["id"]
        apply_action(data, "pin", record_id=corrected, at=JUN)
        self.assertEqual(len(data["controls"]["journal"]), JOURNAL_LIMIT)


if __name__ == "__main__":
    unittest.main()
