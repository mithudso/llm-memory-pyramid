"""Source proof, profile admission and explicit re-verification at public boundaries."""
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from memory_pyramid_distiller import MemoryPyramidDistiller
from napmem_retrieval_agent import NapMemRetrievalAgent


class ProvenanceIntegrationTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.path = str(self.root / "store.json")
        self.source = self.root / "notes.md"
        self.text = "# Editor\nI prefer Vim.\n"
        self.source.write_text(self.text)
        self.store = MemoryPyramidDistiller(self.path)

    def ingest(self, **kwargs):
        self.store.ingest_session("a", "A", str(self.source), self.text,
                                  scope="project:a", **kwargs)
        return self.store.data["memory_records"][0]

    def test_approved_verbatim_evidence_can_form_a_profile(self):
        row = self.ingest(metadata={"review_status": "approved"})
        self.assertEqual(row["evidence"]["status"], "verified")
        self.assertEqual(row["evidence"]["assertion_support"], "verbatim")
        self.assertEqual(len(self.store.data["user_profiles"]), 1)
        self.assertNotIn("confidence", self.store.data["user_profiles"][0])

    def test_fabricated_evidence_cannot_be_admitted_without_original_content(self):
        unit = self.store.extract_atomic_units(self.text, "a", str(self.source))[0]
        unit.update(review_status="approved", evidence={"status": "verified"})
        self.store.ingest_session_records("a", "A", str(self.source), [unit], scope="project:a")
        self.assertEqual(self.store.data["memory_records"][0]["evidence"]["status"], "unverified")
        self.assertEqual(self.store.data["user_profiles"], [])

    def test_quote_binding_does_not_prove_a_paraphrased_assertion(self):
        unit = self.store.extract_atomic_units(self.text, "a", str(self.source))[0]
        unit.update(text="I prefer Emacs.", review_status="approved")
        self.store.ingest_session_records("a", "A", str(self.source), [unit],
                                          scope="project:a", source_content=self.text)
        proof = self.store.data["memory_records"][0]["evidence"]
        self.assertEqual(proof["status"], "verified")
        self.assertEqual(proof["assertion_support"], "unverified")
        self.assertEqual(self.store.data["user_profiles"], [])

    def test_inspection_does_not_reopen_a_stored_path_without_explicit_verification(self):
        row = self.ingest()
        agent = NapMemRetrievalAgent(self.path)
        import os
        original = os.open
        def canonical_only(path, *args, **kwargs):
            self.assertEqual(os.fspath(path), self.path)
            return original(path, *args, **kwargs)
        with patch("napmem_evidence.os.open", side_effect=canonical_only):
            result = agent.inspect_provenance(row["id"], scope="project:a")
        self.assertEqual(result["verification"]["status"], "not_rechecked")
        self.assertEqual(result["verification"]["binding_status"], "verified")

    def test_reverification_discloses_changed_or_missing_source_without_new_text(self):
        row = self.ingest()
        self.source.write_text("new private text must never enter the response")
        agent = NapMemRetrievalAgent(self.path)
        changed = agent.inspect_provenance(row["id"], scope="project:a", verify=True,
                                           allowed_roots=[str(self.root)])
        self.assertEqual(changed["verification"]["status"], "changed")
        self.assertNotIn("new private text", str(changed))
        self.source.unlink()
        missing = agent.inspect_provenance(row["id"], scope="project:a", verify=True,
                                           allowed_roots=[str(self.root)])
        self.assertEqual(missing["verification"]["status"], "missing")

    def test_verified_timestamp_is_stable_until_the_source_revision_changes(self):
        with patch("memory_pyramid_distiller._utcnow", return_value="2026-01-01T00:00:00Z"):
            original = dict(self.ingest())
        with patch("memory_pyramid_distiller._utcnow", return_value="2026-02-01T00:00:00Z"):
            same = self.ingest()
        self.assertEqual(same["last_verified_at"], original["last_verified_at"])
        self.text = self.text.replace("# Editor", "# Current editor")
        with patch("memory_pyramid_distiller._utcnow", return_value="2026-03-01T00:00:00Z"):
            changed = self.ingest()
        self.assertEqual(changed["last_verified_at"], "2026-03-01T00:00:00Z")
        self.assertEqual(changed["created_at"], original["created_at"])
