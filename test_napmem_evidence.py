"""Offline tests for literal source binding and explicitly allowed file checks."""

from copy import deepcopy
import hashlib
import json
import os
from pathlib import Path
import tempfile
import time
import unittest
from unittest.mock import patch

from napmem_evidence import (
    MAX_QUOTE_BYTES, QUOTE_TRUNCATION_MARKER, bind_evidence, verify_evidence,
)


CONTENT = "# Editor\n- Use Vim for Alpha.\nKeep Beta separate.\n"
CREATED = "2026-10-27T12:00:00Z"


def sha(text):
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def record(**fields):
    result = {"id": "rec_s_001", "text": "Use Vim for Alpha.", "created_at": CREATED,
              "source_anchor": {"file_path": "/unused/source.md", "line_range": "L2"}}
    result.update(fields)
    return result


class TestEvidenceBinding(unittest.TestCase):
    def test_exact_quote_range_revision_and_extraction_are_separate_from_assertion(self):
        original = record(source_quote="Use Vim for Alpha.")
        before = deepcopy(original)
        bound = bind_evidence(original, CONTENT, method="heuristic", model=None,
                              prompt_version="heuristic-v2", source_revision="git:abc123")
        proof = bound["evidence"]
        self.assertEqual(proof["status"], "verified")
        self.assertEqual(proof["source_kind"], "document")
        self.assertEqual(proof["source_sha256"], sha(CONTENT))
        self.assertEqual(proof["source_revision"], "git:abc123")
        self.assertEqual(proof["revision"], "git:abc123")
        self.assertEqual(proof["line_range"], "L2")
        self.assertEqual(proof["quote"], "Use Vim for Alpha.")
        self.assertEqual(proof["quote_sha256"], sha(proof["quote"]))
        self.assertEqual(proof["extraction"], {"method": "heuristic", "model": None,
                                                "prompt_version": "heuristic-v2"})
        self.assertEqual(proof["assertion_support"], "verbatim")
        self.assertEqual(bound["last_verified_at"], CREATED)
        self.assertEqual(original, before)
        bound["source_anchor"]["file_path"] = "another.md"
        self.assertEqual(original, before)

    def test_supported_line_range_formats_normalize_and_keep_literal_line_endings(self):
        for supplied in ("L2-L3", "2-3", " L02-L03 "):
            with self.subTest(supplied=supplied):
                bound = bind_evidence(record(source_anchor={"line_range": supplied}), CONTENT)
                self.assertEqual(bound["evidence"]["line_range"], "L2-L3")
                self.assertEqual(bound["evidence"]["quote"], "- Use Vim for Alpha.\nKeep Beta separate.\n")
                self.assertEqual(bound["evidence"]["source_revision"], sha(CONTENT))
        bound = bind_evidence(record(source_anchor={"line_range": "2-2"}), CONTENT)
        self.assertEqual(bound["evidence"]["line_range"], "L2")

    def test_quote_in_source_anchor_is_used_only_inside_its_cited_range(self):
        bound = bind_evidence(record(source_anchor={"line_range": "L2", "source_quote": "Use Vim"}), CONTENT)
        self.assertEqual(bound["evidence"]["quote"], "Use Vim")
        self.assertEqual(bound["evidence"]["assertion_support"], "unverified")
        for supplied in ("Keep Beta separate.", "Invented wording.", "", 13):
            with self.subTest(supplied=supplied):
                bound = bind_evidence(record(source_quote=supplied), CONTENT)
                self.assertEqual(bound["evidence"]["quote"], "")
                self.assertEqual(bound["evidence"]["status"], "unverified")
                self.assertEqual(bound["evidence"]["reason"], "source_quote_not_in_cited_range")
                self.assertEqual(bound["evidence"]["assertion_support"], "unverified")
                self.assertEqual(verify_evidence(bound, source_content=CONTENT)["status"], "unverified")

    def test_invalid_ranges_and_out_of_bounds_ranges_cannot_verify(self):
        for supplied in (None, "", "all", "L0", "L2-L1", "L-2", "L2-L3 extra", "L2.5", 2, "L" + "9" * 10000):
            with self.subTest(supplied=supplied):
                bound = bind_evidence(record(source_anchor={"line_range": supplied}), CONTENT)
                self.assertEqual(bound["evidence"]["status"], "unverified")
                self.assertEqual(bound["evidence"]["reason"], "invalid_line_range")
                self.assertEqual(bound["evidence"]["quote"], "")
        bound = bind_evidence(record(source_anchor={"line_range": "L2-L4"}), CONTENT)
        self.assertEqual(bound["evidence"]["reason"], "line_range_out_of_bounds")
        self.assertEqual(bind_evidence(record(), "")["evidence"]["status"], "unverified")

    def test_paraphrase_has_verified_quotation_but_unverified_assertion_support(self):
        bound = bind_evidence(record(text="Alpha's preferred editor is Vim."), CONTENT, method="llm",
                              model="fixture-model", prompt_version="extract-v3")
        self.assertEqual(bound["evidence"]["status"], "verified")
        self.assertEqual(bound["evidence"]["assertion_support"], "unverified")
        self.assertNotEqual(bound["text"], bound["evidence"]["quote"])
        checked = verify_evidence(bound, source_content=CONTENT)
        self.assertEqual(checked["status"], "verified")
        self.assertEqual(checked["assertion_support"], "unverified")

    def test_stripped_bullet_assertion_can_be_verbatim_but_case_changes_cannot(self):
        for assertion in ("- Use Vim for Alpha.", "* [x] Use Vim for Alpha.", "1. Use Vim for Alpha."):
            with self.subTest(assertion=assertion):
                bound = bind_evidence(record(text=assertion), CONTENT)
                self.assertEqual(bound["evidence"]["assertion_support"], "verbatim")
        bound = bind_evidence(record(text="use vim for alpha."), CONTENT)
        self.assertEqual(bound["evidence"]["assertion_support"], "unverified")

    def test_quote_is_bounded_with_marker_without_supporting_an_omitted_assertion(self):
        content = "é" * MAX_QUOTE_BYTES + "Use Vim for Alpha."
        bound = bind_evidence(record(source_anchor={"line_range": "L1"}), content)
        proof = bound["evidence"]
        self.assertLessEqual(len(proof["quote"].encode("utf-8")), MAX_QUOTE_BYTES)
        self.assertTrue(proof["quote"].endswith(QUOTE_TRUNCATION_MARKER))
        self.assertTrue(proof["quote_truncated"])
        self.assertEqual(proof["assertion_support"], "unverified")
        self.assertEqual(verify_evidence(bound, source_content=content)["status"], "verified")
        proof["quote"] = proof["quote"].replace(QUOTE_TRUNCATION_MARKER, "")
        proof["quote_sha256"] = sha(proof["quote"])
        self.assertEqual(verify_evidence(bound, source_content=content)["status"], "unverified")

    def test_binding_and_noop_replay_are_deterministic(self):
        bound = bind_evidence(record(), CONTENT)
        self.assertEqual(bind_evidence(record(), CONTENT), bound)
        self.assertEqual(bind_evidence(bound, CONTENT), bound)
        self.assertFalse(any("at" == key[-2:] for key in bound["evidence"]))
        self.assertNotIn("last_verified_at", bind_evidence(record(created_at="2026-10-27T12:00:00"), CONTENT))

    def test_binding_never_reads_the_stored_path_even_when_content_is_missing(self):
        with patch("builtins.open", side_effect=AssertionError("implicit file read")), \
                patch("os.open", side_effect=AssertionError("implicit descriptor read")):
            bound = bind_evidence(record(), None)
            self.assertEqual(bound["evidence"]["status"], "unverified")
            self.assertIsNone(bound["evidence"]["source_sha256"])
            self.assertNotIn("last_verified_at", bound)
            self.assertEqual(bind_evidence(record(), CONTENT)["evidence"]["status"], "verified")

    def test_invalid_metadata_types_are_rejected(self):
        for fields in ({"method": ""}, {"method": 5}, {"model": "m" * 257},
                       {"prompt_version": []}, {"source_revision": ""}):
            with self.subTest(fields=fields), self.assertRaises(ValueError):
                bind_evidence(record(), CONTENT, **fields)
        with self.assertRaises(ValueError):
            bind_evidence(record(), b"not text")


class TestEvidenceVerification(unittest.TestCase):
    def setUp(self):
        self.bound = bind_evidence(record(), CONTENT)

    def test_supplied_source_checks_hash_and_quote_without_filesystem_io(self):
        before = deepcopy(self.bound)
        with patch("os.open", side_effect=AssertionError("unexpected file read")):
            checked = verify_evidence(self.bound, source_content=CONTENT)
            self.assertEqual(checked["status"], "verified")
            changed = verify_evidence(self.bound, source_content=CONTENT + "new line\n")
        self.assertEqual(changed["status"], "changed")
        self.assertEqual(changed["current_source_sha256"], sha(CONTENT + "new line\n"))
        self.assertNotIn("quote", checked)
        self.assertNotIn("new line", json.dumps(changed))
        self.assertEqual(self.bound, before)

    def test_missing_roots_cannot_open_a_source(self):
        with patch("os.open", side_effect=AssertionError("unexpected file read")):
            for roots in (None, []):
                checked = verify_evidence(self.bound, allowed_roots=roots)
                self.assertEqual(checked["status"], "unverified")
                self.assertEqual(checked["reason"], "allowed_roots_required")

    def test_path_or_claimed_verified_status_without_literal_proof_cannot_upgrade(self):
        missing = record(evidence={"status": "verified", "source_sha256": sha(CONTENT)})
        with patch("os.open", side_effect=AssertionError("unexpected file read")):
            for supplied in (None, CONTENT):
                checked = verify_evidence(missing, source_content=supplied, allowed_roots=["/unused"])
                self.assertEqual(checked["status"], "unverified")
                self.assertEqual(checked["reason"], "literal_proof_unavailable")

    def test_tampered_quote_digest_revision_and_anchor_cannot_verify(self):
        for mutate in (
            lambda value: value["evidence"].update(quote="Invented quotation"),
            lambda value: value["evidence"].update(source_sha256="invalid"),
            lambda value: value["evidence"].update(revision="another"),
            lambda value: value["source_anchor"].update(line_range="L3"),
        ):
            with self.subTest(mutate=mutate):
                value = deepcopy(self.bound)
                mutate(value)
                self.assertEqual(verify_evidence(value, source_content=CONTENT)["status"], "unverified")
        self.bound["evidence"].update(quote="Keep Beta separate.", quote_sha256=sha("Keep Beta separate."))
        checked = verify_evidence(self.bound, source_content=CONTENT)
        self.assertEqual(checked["status"], "unverified")
        self.assertEqual(checked["reason"], "quote_not_in_cited_range")

    def test_unverified_metadata_is_bounded_and_returns_no_source_content(self):
        checked = verify_evidence(record(evidence={"source_revision": "x" * 10000,
                                                   "quote": "SECRET" * 10000}))
        self.assertLess(len(json.dumps(checked)), 1000)
        self.assertNotIn("SECRET", json.dumps(checked))

    def test_operator_correction_verifies_without_opening_virtual_anchor(self):
        change = "a" * 24
        value = record(id="rec_control_" + change, text="Use VS Code for Alpha.",
                       source_anchor={"session_id": "session_control_" + change,
                                      "file_path": "napmem:control/" + change},
                       evidence={"status": "verified", "source_kind": "operator",
                                 "quote": "Use VS Code for Alpha.",
                                 "source_sha256": sha("Use VS Code for Alpha."), "revision": change})
        with patch("os.open", side_effect=AssertionError("virtual anchor opened")):
            checked = verify_evidence(value)
            self.assertEqual(checked["status"], "verified")
            self.assertEqual(checked["assertion_support"], "verbatim")
            for field, replacement in (("revision", "b" * 24), ("quote", "invented"),
                                       ("source_sha256", "0" * 64)):
                damaged = deepcopy(value)
                damaged["evidence"][field] = replacement
                self.assertEqual(verify_evidence(damaged)["status"], "unverified")
            damaged = deepcopy(value)
            damaged["source_anchor"]["file_path"] = "/private/source.md"
            self.assertEqual(verify_evidence(damaged)["status"], "unverified")

    def test_invalid_limits_and_input_types_fail_clearly(self):
        for limit in (0, -1, True, 1.5):
            with self.subTest(limit=limit), self.assertRaises(ValueError):
                verify_evidence(self.bound, max_source_bytes=limit)
        with self.assertRaises(ValueError):
            verify_evidence(self.bound, source_content=b"not text")
        with self.assertRaises(ValueError):
            verify_evidence(self.bound, allowed_roots="/unused")


class TestExplicitSourceVerification(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name) / "allowed"
        self.root.mkdir()
        self.path = self.root / "source.md"
        self.path.write_text(CONTENT, encoding="utf-8")
        self.bound = bind_evidence(record(source_anchor={"file_path": str(self.path), "line_range": "L2"}), CONTENT)

    def check(self, **fields):
        return verify_evidence(self.bound, allowed_roots=[str(self.root)], **fields)

    def test_allowed_regular_file_changed_file_and_missing_file(self):
        self.assertEqual(self.check()["status"], "verified")
        self.path.write_text("SECRET NEW SOURCE\n", encoding="utf-8")
        checked = self.check()
        self.assertEqual(checked["status"], "changed")
        self.assertNotIn("SECRET", json.dumps(checked))
        self.path.unlink()
        checked = self.check()
        self.assertEqual(checked["status"], "missing")
        self.assertEqual(checked["reason"], "source_missing")

    def test_outside_root_is_refused_before_read(self):
        with patch("napmem_evidence.os.read", side_effect=AssertionError("out-of-root bytes read")):
            checked = verify_evidence(self.bound, allowed_roots=[str(self.root / "other")])
        self.assertEqual(checked["status"], "unverified")
        self.assertEqual(checked["reason"], "source_outside_allowed_roots")

    def test_open_descriptor_path_controls_containment(self):
        with patch("napmem_evidence._fd_true_path", return_value="/private/outside.md"), \
                patch("napmem_evidence.os.read", side_effect=AssertionError("outside descriptor read")):
            self.assertEqual(self.check()["reason"], "source_outside_allowed_roots")
        with patch("napmem_evidence._fd_true_path", return_value=None):
            self.assertEqual(self.check()["reason"], "source_path_unverifiable")

    def test_final_symlink_and_symlinked_directory_escape_are_refused(self):
        outside = Path(self.temp.name) / "outside"
        outside.mkdir()
        secret = outside / "secret.md"
        secret.write_text("PRIVATE", encoding="utf-8")
        self.path.unlink()
        self.path.symlink_to(secret)
        with patch("napmem_evidence.os.read", side_effect=AssertionError("symlink source read")):
            self.assertEqual(self.check()["status"], "unverified")
        directory_link = self.root / "linked"
        directory_link.symlink_to(outside, target_is_directory=True)
        self.bound["source_anchor"]["file_path"] = str(directory_link / "secret.md")
        self.assertEqual(self.check()["reason"], "source_outside_allowed_roots")

    def test_hardlink_is_refused_before_read(self):
        os.link(self.path, self.root / "alias.md")
        with patch("napmem_evidence.os.read", side_effect=AssertionError("hardlink source read")):
            checked = self.check()
        self.assertEqual(checked["reason"], "source_multi_linked")

    @unittest.skipUnless(hasattr(os, "mkfifo"), "requires FIFO support")
    def test_fifo_is_opened_nonblocking_and_refused(self):
        self.path.unlink()
        os.mkfifo(self.path)
        started = time.monotonic()
        checked = self.check()
        self.assertLess(time.monotonic() - started, 1)
        self.assertEqual(checked["reason"], "source_not_regular")

    def test_directory_and_oversized_source_are_refused(self):
        self.path.unlink()
        self.path.mkdir()
        self.assertEqual(self.check()["reason"], "source_not_regular")
        self.path.rmdir()
        self.path.write_text("PRIVATE" * 100, encoding="utf-8")
        with patch("napmem_evidence.os.read", side_effect=AssertionError("oversize source read")):
            checked = self.check(max_source_bytes=50)
        self.assertEqual(checked["reason"], "source_too_large")
        self.assertNotIn("PRIVATE", json.dumps(checked))

    def test_source_growth_read_is_bounded_to_limit_plus_one(self):
        real_fstat = os.fstat
        real_read = os.read
        read_sizes = []

        def changed_size(fd):
            details = list(real_fstat(fd))
            details[6] = 1
            return os.stat_result(details)

        def tracked_read(fd, count):
            read_sizes.append(count)
            return real_read(fd, count)

        with patch("napmem_evidence.os.fstat", side_effect=changed_size), \
                patch("napmem_evidence.os.read", side_effect=tracked_read):
            checked = self.check(max_source_bytes=10)
        self.assertEqual(checked["reason"], "source_too_large")
        self.assertEqual(sum(read_sizes), 11)

    def test_invalid_utf8_source_is_refused_without_decoding_output(self):
        self.path.write_bytes(b"\xff\xfePRIVATE")
        checked = self.check()
        self.assertEqual(checked["reason"], "source_not_utf8")
        self.assertNotIn("PRIVATE", json.dumps(checked))


if __name__ == "__main__":
    unittest.main()
