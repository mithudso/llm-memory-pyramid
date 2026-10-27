"""Forgetting erases literal source evidence without deleting unrelated facts."""

from copy import deepcopy
import hashlib
import json
import unittest

from napmem_controls import apply_action, apply_controls, filter_incoming, preview_action
from napmem_evidence import bind_evidence
from napmem_model import CONTEXT_FIELDS, migrate_store, normalize_record


AT = "2026-10-27T12:00:00Z"
SECRET = "Forget this private assertion."
PUBLIC = "Keep this public assertion."
SOURCE = SECRET + "\n" + PUBLIC + "\nUnrelated third assertion.\n"


def sha(text):
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def record(rid, text, *, content=SOURCE, lines="L1-L2", scope="project:a"):
    return normalize_record(bind_evidence({
        "id": rid, "text": text, "scope": scope, "created_at": AT,
        "source_anchor": {"file_path": "/test/source.md", "session_id": "session_" + rid,
                          "line_range": lines},
    }, content))


def store(*records):
    return migrate_store({"version": "2.0.0", "memory_records": list(records), "controls": {},
                          "raw_conversations": [{"session_id": "session_" + item["id"]} for item in records]})


def records_by_id(data):
    return {item["id"]: item for item in data["memory_records"]}


class TestEvidenceForgetting(unittest.TestCase):
    def test_forget_redacts_shared_source_range_without_deleting_other_record(self):
        target = record("private", SECRET, lines="L1")
        survivor = record("public", PUBLIC)
        survivor["source_quote"] = SOURCE
        survivor["source_anchor"]["source_quote"] = SOURCE
        data = store(target, survivor)
        before = deepcopy(data)
        preview = preview_action(data, "forget", record_id="private", at=AT)
        self.assertEqual(data, before)
        self.assertEqual(preview["affected_ids"], ["private"])
        self.assertEqual(preview["redacted_evidence_ids"], ["public"])
        receipt = apply_action(data, "forget", record_id="private", at=AT,
                               preview_token=preview["preview_token"])
        self.assertEqual(receipt["affected_ids"], ["private"])
        self.assertEqual(receipt["redacted_evidence_ids"], ["public"])
        remaining = records_by_id(data)
        self.assertEqual(set(remaining), {"public"})
        proof = remaining["public"]["evidence"]
        self.assertEqual(proof["quote"], "")
        self.assertIsNone(proof["quote_sha256"])
        self.assertEqual(proof["status"], "unverified")
        self.assertEqual(proof["assertion_support"], "unverified")
        self.assertEqual(proof["reason"], "redacted_by_forget")
        self.assertNotIn("source_quote", remaining["public"])
        self.assertNotIn("source_quote", remaining["public"]["source_anchor"])
        self.assertNotIn(SECRET, json.dumps(data))
        self.assertEqual(data["evidence_redactions"], [{
            "scope": "project:a", "source_sha256": sha(SOURCE),
            "quote_sha256": sha(SECRET + "\n"), "line_range": "L1",
        }])
        self.assertEqual(set(data["controls"]), {
            "overrides", "corrections", "assertions", "tombstones", "excluded_sources", "journal"})

    def test_same_quote_hash_redacts_a_different_source_revision(self):
        first_source = SECRET + "\n" + PUBLIC + "\n"
        second_source = "Introduction\n" + first_source
        data = store(record("private", SECRET, content=first_source),
                     record("public", PUBLIC, content=second_source, lines="L2-L3"))
        receipt = apply_action(data, "forget", record_id="private", at=AT)
        self.assertEqual(receipt["redacted_evidence_ids"], ["public"])
        self.assertNotIn(SECRET, json.dumps(data))

    def test_nonoverlapping_range_and_other_scope_keep_their_evidence(self):
        independent = record("independent", "Unrelated third assertion.", lines="L3")
        other = record("other_scope", PUBLIC, scope="project:b")
        data = store(record("private", SECRET, lines="L1"), independent, other)
        apply_action(data, "forget", record_id="private", at=AT)
        remaining = records_by_id(data)
        self.assertEqual(remaining["independent"]["evidence"], independent["evidence"])
        self.assertEqual(remaining["other_scope"]["evidence"], other["evidence"])
        self.assertIn(SECRET, remaining["other_scope"]["evidence"]["quote"])

    def test_alias_occurrence_evidence_redacts_and_its_owner_is_preserved(self):
        owner = record("owner", PUBLIC, content=PUBLIC, lines="L1")
        alias = record("alias", PUBLIC)
        anchor = deepcopy(alias["source_anchor"])
        anchor["source_quote"] = SOURCE
        anchor["assertion"] = {field: deepcopy(alias[field]) for field in (*CONTEXT_FIELDS, "created_at")}
        owner["duplicates"] = ["alias"]
        owner["duplicate_anchors"] = {"alias": anchor}
        data = store(record("private", SECRET, lines="L1"), owner)
        receipt = apply_action(data, "forget", record_id="private", at=AT)
        self.assertEqual(receipt["affected_ids"], ["private"])
        self.assertEqual(receipt["redacted_evidence_ids"], ["alias"])
        remaining = records_by_id(data)["owner"]
        self.assertEqual(remaining["evidence"]["status"], "verified")
        alias_anchor = remaining["duplicate_anchors"]["alias"]
        self.assertEqual(alias_anchor["assertion"]["evidence"]["reason"], "redacted_by_forget")
        self.assertNotIn("source_quote", alias_anchor)
        self.assertNotIn(SECRET, json.dumps(data))

    def test_forgetting_alias_captures_each_source_in_the_family(self):
        owner = record("private", SECRET, lines="L1")
        second_source = "Another header\n" + SOURCE
        alias = record("alias", SECRET, content=second_source, lines="L2")
        anchor = deepcopy(alias["source_anchor"])
        anchor["assertion"] = {field: deepcopy(alias[field]) for field in (*CONTEXT_FIELDS, "created_at")}
        owner["duplicates"] = ["alias"]
        owner["duplicate_anchors"] = {"alias": anchor}
        data = store(owner, record("public", PUBLIC, content=second_source, lines="L2-L3"))
        receipt = apply_action(data, "forget", record_id="alias", at=AT)
        self.assertEqual(receipt["affected_ids"], ["alias", "private"])
        self.assertEqual(receipt["redacted_evidence_ids"], ["public"])
        self.assertEqual(len(data["evidence_redactions"]), 2)
        self.assertNotIn(SECRET, json.dumps(data))

    def test_correction_family_captures_original_and_operator_quotation_hashes(self):
        replacement = "Forget this replacement assertion."
        data = store(record("private", SECRET, lines="L1"), record("public", PUBLIC),
                     record("replacement_witness", PUBLIC, content=replacement + "\n" + PUBLIC, lines="L1"))
        apply_action(data, "correct", record_id="private", value=replacement, at=AT)
        correction = data["controls"]["assertions"][0]["id"]
        receipt = apply_action(data, "forget", record_id=correction, at=AT)
        self.assertIn("public", receipt["redacted_evidence_ids"])
        self.assertIn("replacement_witness", receipt["redacted_evidence_ids"])
        self.assertEqual(data["controls"]["assertions"], [])
        self.assertNotIn(SECRET, json.dumps(data))
        self.assertNotIn(replacement, json.dumps(data))
        operator_policy = next(item for item in data["evidence_redactions"] if item["line_range"] is None)
        self.assertEqual(operator_policy["quote_sha256"], sha(replacement))

    def test_source_replay_same_hash_remains_redacted_after_rebuild(self):
        data = store(record("private", SECRET, lines="L1"), record("public", PUBLIC))
        apply_action(data, "forget", record_id="private", at=AT)
        policy = deepcopy(data["evidence_redactions"])
        fresh = record("fresh_public", PUBLIC)
        incoming = filter_incoming(data, [record("replayed_private", SECRET, lines="L1"), fresh])
        self.assertEqual([item["id"] for item in incoming], ["fresh_public"])
        self.assertEqual(incoming[0]["evidence"]["reason"], "redacted_by_forget")
        self.assertEqual(fresh["evidence"]["status"], "verified")
        data["memory_records"] = [fresh]
        apply_controls(data)
        self.assertEqual(data["evidence_redactions"], policy)
        self.assertNotIn(SECRET, json.dumps(data))
        once = deepcopy(data)
        apply_controls(data)
        self.assertEqual(data, once)

    def test_changed_source_literal_line_matches_scoped_tombstone_after_markdown_stripping(self):
        data = store(record("private", SECRET, lines="L1"))
        apply_action(data, "forget", record_id="private", at=AT)
        for marker in ("", "- ", "* [x] ", "> ", "> - [ ] ", "1. "):
            with self.subTest(marker=marker):
                revised = "New introduction\n" + marker + SECRET + "\n" + PUBLIC + "\n"
                incoming = filter_incoming(data, [record("fresh", PUBLIC, content=revised, lines="L2-L3")])
                self.assertEqual(len(incoming), 1)
                self.assertEqual(incoming[0]["evidence"]["reason"], "redacted_by_forget")
                self.assertNotIn(SECRET, json.dumps(incoming))

    def test_changed_source_unrecognized_paraphrase_is_not_semantically_suppressed(self):
        data = store(record("private", SECRET, lines="L1"))
        apply_action(data, "forget", record_id="private", at=AT)
        changed = "A differently worded private assertion.\n" + PUBLIC
        incoming = filter_incoming(data, [record("fresh", PUBLIC, content=changed)])
        self.assertEqual(incoming[0]["evidence"]["status"], "verified")

    def test_existing_scoped_tombstone_protects_quotes_even_without_revision_policies(self):
        fresh = record("public", PUBLIC)
        data = store(fresh)
        data["controls"]["tombstones"] = [{"scope": "project:a", "text_sha256": sha(SECRET.lower())}]
        apply_controls(data)
        self.assertEqual(records_by_id(data)["public"]["evidence"]["reason"], "redacted_by_forget")
        self.assertNotIn(SECRET, json.dumps(data))

    def test_legacy_redundant_source_quote_is_redacted_without_bound_evidence(self):
        survivor = record("public", PUBLIC)
        survivor["evidence"] = {}
        survivor["source_anchor"]["source_quote"] = SECRET + "\n" + PUBLIC
        data = store(record("private", SECRET, lines="L1"), survivor)
        receipt = apply_action(data, "forget", record_id="private", at=AT)
        self.assertEqual(receipt["redacted_evidence_ids"], ["public"])
        self.assertNotIn(SECRET, json.dumps(data))

    def test_redacted_operator_assertion_keeps_valid_control_identity_on_replay(self):
        data = store(record("private", SECRET, lines="L1"), record("other", "An unrelated starting claim."))
        apply_action(data, "correct", record_id="other", value=SECRET + "\n" + PUBLIC, at=AT)
        correction = data["controls"]["assertions"][0]["id"]
        receipt = apply_action(data, "forget", record_id="private", at=AT)
        self.assertIn(correction, receipt["redacted_evidence_ids"])
        self.assertEqual(data["controls"]["assertions"][0]["evidence"]["reason"], "redacted_by_forget")
        apply_controls(data)
        self.assertIn(correction, records_by_id(data))

    def test_malformed_redaction_policy_is_rejected_atomically_everywhere(self):
        valid = {"scope": "project:a", "source_sha256": sha(SOURCE),
                 "quote_sha256": sha(SECRET), "line_range": "L1"}
        invalid = [None, {}, [None], [{**valid, "text": SECRET}],
                   [{**valid, "scope": "*"}], [{**valid, "source_sha256": "bad"}],
                   [{**valid, "quote_sha256": []}], [{**valid, "line_range": "1-1"}],
                   [{**valid, "line_range": "L2-L1"}],
                   [{**valid, "source_sha256": None, "quote_sha256": None}], [valid, valid]]
        for policy in invalid:
            for operation in (apply_controls,
                              lambda data: apply_action(data, "pin", record_id="public", at=AT),
                              lambda data: preview_action(data, "forget", record_id="public", at=AT),
                              lambda data: filter_incoming(data, [record("incoming", PUBLIC)])):
                data = store(record("public", PUBLIC))
                data["evidence_redactions"] = deepcopy(policy)
                before = deepcopy(data)
                with self.subTest(policy=policy, operation=operation), self.assertRaises(ValueError):
                    operation(data)
                self.assertEqual(data, before)


if __name__ == "__main__":
    unittest.main()
