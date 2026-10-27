"""Offline search safety, ranking and exact serialized-budget tests."""

from copy import deepcopy
import json
import math
import os
import unittest
from unittest import mock

from napmem_model import CONTEXT_FIELDS, normalize_record
from napmem_search import bounded_response, compact_json, eligible_records, search


JAN = "2026-01-01T00:00:00Z"
JUN = "2026-06-01T00:00:00Z"
JUL = "2026-07-01T00:00:00Z"


def record(rid="r1", text="Editor preference: use Vim.", **fields):
    value = {"id": rid, "text": text, "type": "fact", "scope": "project:a",
             "source_anchor": {"session_id": rid, "file_path": rid + ".md"},
             "created_at": JAN}
    value.update(fields)
    return normalize_record(value)


def store(*records, **changes):
    result = {"memory_records": list(records), "generation": 7, "version": "2.0.0", "updated_at": JAN}
    result.update(changes)
    return result


def run(data, query, **kwargs):
    return search(data, query, scope="project:a", as_of=JUL, **kwargs)


class TestScopedSearch(unittest.TestCase):
    def test_default_is_offline_even_when_model_endpoints_are_configured(self):
        with mock.patch.dict(os.environ, {"NAPMEM_EMBED_BACKEND": "ollama", "OLLAMA_HOST": "http://unreachable.invalid"}), \
                mock.patch("urllib.request.urlopen", side_effect=AssertionError("Unexpected network")), \
                mock.patch("socket.create_connection", side_effect=AssertionError("Unexpected network")):
            result = run(store(record()), "editor")
        self.assertEqual(result["mode"], "hybrid:sparse-tfidf")
        self.assertEqual([r["id"] for r in result["matches"]], ["r1"])

    def test_exact_id_and_error_symbol_rank_without_substituting_similar_ids(self):
        data = store(record("rec_api_17", "The server reports RevisionMismatchError on conflict."),
                     record("rec_api_18", "The server reports another revision error."))
        for query in ("rec_api_17", "Find rec_api_17", "RevisionMismatchError"):
            with self.subTest(query=query):
                result = run(data, query)
                self.assertEqual([r["id"] for r in result["matches"]], ["rec_api_17"])
        self.assertTrue(run(data, "rec_api_19")["abstention"])

    def test_generic_paraphrase_ranks_relevant_evidence_first(self):
        data = store(record("images", "Save a backup of each image in the archive directory."),
                     record("release", "Release notes describe the navigation menu."))
        result = run(data, "Where should I preserve copies of pictures in a folder?")
        self.assertEqual(result["matches"][0]["id"], "images")
        self.assertGreater(result["matches"][0]["ranking"]["bm25"], 0)
        self.assertGreater(result["matches"][0]["ranking"]["cosine"], 0)

    def test_irrelevant_or_only_stop_words_abstain_without_top_k_padding(self):
        data = store(record(), record("other", "Backup retention is seven days."))
        for query in ("unicorn metallurgy", "the and is", "project:a"):
            with self.subTest(query=query):
                result = run(data, query)
                self.assertEqual(result["matches"], [])
                self.assertTrue(result["abstention"])
                self.assertEqual(result["status"], "no_match")

    def test_scope_filters_before_ranking_and_embedding(self):
        calls = []

        class Backend:
            def embed(self, texts):
                calls.append(texts)
                return [[1., 0.] for _ in texts]

        data = store(record("allowed"), record("hidden", "PRIVATE editor evidence", scope="project:b"),
                     record("deleted", "DELETED editor evidence", status="deleted"),
                     record("unsafe", "UNTRUSTED editor instructions", instruction_bearing=True))
        result = run(data, "editor", backend=Backend())
        self.assertEqual([r["id"] for r in result["matches"]], ["allowed"])
        self.assertEqual(calls, [["editor", "Editor preference: use Vim."]])
        self.assertNotIn("PRIVATE", json.dumps(result))
        self.assertNotIn("UNTRUSTED", json.dumps(result))

    def test_alias_evidence_keeps_own_anchor_and_cannot_expose_other_scope(self):
        own = record("alias", "Public editor wording", scope="project:a")
        context = {field: own[field] for field in (*CONTEXT_FIELDS, "created_at")}
        canonical = record("owner", "PRIVATE editor wording", scope="project:b", duplicates=["alias"], duplicate_anchors={
            "alias": {"session_id": "public", "file_path": "public.md", "paraphrase_text": own["text"], "assertion": context}})
        result = run(store(canonical), "editor")
        evidence = result["matches"][0]
        self.assertEqual((evidence["id"], evidence["canonical"]), ("alias", "owner"))
        self.assertEqual(evidence["source_anchor"]["file_path"], "public.md")
        self.assertEqual(evidence["duplicate_anchors"], {})
        self.assertNotIn("PRIVATE", json.dumps(result))

    def test_historical_supersession_and_expiry_filter_before_ranking(self):
        data = store(record("old", "Editor preference: Vim.", status="superseded", valid_from=JAN, valid_to=JUN),
                     record("new", "Editor preference: Code.", valid_from=JUN, supersedes=["old"]),
                     record("expired", "Editor experiment: Emacs.", valid_to=JAN))
        old = search(data, "editor", scope="project:a", as_of=JAN)
        new = run(data, "editor")
        self.assertEqual([r["id"] for r in old["matches"]], ["old"])
        self.assertEqual([r["id"] for r in new["matches"]], ["new"])

    def test_literal_numbers_and_weekdays_do_not_match_different_current_values(self):
        data = store(record("limit", "Queue capacity is 20 jobs."), record("day", "Publish the report every Thursday."))
        self.assertEqual(run(data, "90 jobs")["matches"], [])
        self.assertEqual(run(data, "Publish every Monday")["matches"], [])
        self.assertEqual([r["id"] for r in run(data, "20 jobs")["matches"]], ["limit"])

    def test_rejected_quarantined_source_excluded_and_instruction_records_are_removed(self):
        data = store(record("good"), record("q", status="quarantined"), record("rejected", review_status="rejected"),
                     record("excluded", source_excluded=True), record("source_deleted", source_status="deleted"),
                     record("hostile", instruction_bearing=True), record("controlled"),
                     controls={"excluded_sources": ["controlled.md"]})
        result = run(data, "editor")
        self.assertEqual([r["id"] for r in result["matches"]], ["good"])
        self.assertEqual([r["id"] for r in eligible_records(data, "project:a", JUL)], ["good"])

    def test_missing_raw_source_is_disclosed_and_retained_without_fabricating_verification(self):
        result = run(store(record(source_state="deleted")), "editor")
        self.assertEqual(result["matches"][0]["source_state"], "deleted")
        self.assertEqual(result["matches"][0]["provenance_status"], "unverified")

    def test_out_of_scope_aliases_and_source_excluded_alias_anchors_are_not_returned(self):
        own = record("excluded_alias")
        context = {field: own[field] for field in (*CONTEXT_FIELDS, "created_at")}
        canonical = record("owner", duplicates=["excluded_alias"], duplicate_anchors={
            "excluded_alias": {"session_id": "excluded", "file_path": "excluded.md", "excluded": True, "assertion": context}})
        result = run(store(canonical), "editor")
        self.assertEqual(result["matches"][0]["duplicates"], [])
        self.assertEqual(result["matches"][0]["duplicate_anchors"], {})
        self.assertNotIn("excluded.md", json.dumps(result))

    def test_search_does_not_mutate_input_and_is_repeatable_at_fixed_reference_time(self):
        data = store(record(), record("another", "Unrelated notes"))
        original = deepcopy(data)
        first, second = run(data, "editor"), run(data, "editor")
        self.assertEqual(first, second)
        self.assertEqual(data, original)

    def test_top_k_discloses_omission_without_reordering_ties(self):
        data = store(*[record(f"r{i}") for i in range(4)])
        response = run(data, "editor", top_k=2)
        self.assertEqual([r["id"] for r in response["matches"]], ["r0", "r1"])
        self.assertEqual(response["omitted_count"], 2)
        self.assertTrue(response["truncated"])


class TestInjectedEmbeddingBackend(unittest.TestCase):
    def test_explicit_backend_can_recover_a_nonlexical_paraphrase(self):
        class Backend:
            def embed(self, texts):
                return [[1., 0.], [1., 0.], [0., 1.]]

        data = store(record("match", "Persist the archive."), record("noise", "Rotate the signing key."))
        result = run(data, "early recollections", backend=Backend())
        self.assertEqual(result["mode"], "hybrid:injected-embeddings")
        self.assertEqual(result["matches"][0]["id"], "match")
        self.assertEqual(result["matches"][0]["ranking"]["bm25"], 0)

    def test_backend_failure_discloses_class_and_falls_back_without_sensitive_message(self):
        class Backend:
            def embed(self, texts):
                raise RuntimeError("PRIVATE_TOKEN failed at internal endpoint")

        response = run(store(record()), "editor", backend=Backend())
        self.assertEqual(response["mode"], "lexical:fallback")
        self.assertEqual(response["fallback_reason"], "RuntimeError")
        self.assertEqual([r["id"] for r in response["matches"]], ["r1"])
        self.assertNotIn("PRIVATE_TOKEN", json.dumps(response))

    def test_invalid_or_nonfinite_vectors_degrade_to_lexical(self):
        for vectors in ([], [[1.], [1., 2.]], [[True], [1.]], [[math.nan], [1.]], [[math.inf], [1.]]):
            backend = mock.Mock()
            backend.embed.return_value = vectors
            with self.subTest(vectors=vectors):
                response = run(store(record()), "editor", backend=backend)
                self.assertEqual(response["mode"], "lexical:fallback")
                self.assertEqual(response["fallback_reason"], "ValueError")

    def test_semantic_without_explicit_backend_discloses_offline_fallback(self):
        result = run(store(record()), "editor", mode="semantic")
        self.assertEqual(result["mode"], "lexical:fallback")
        self.assertEqual(result["fallback_reason"], "NoInjectedBackend")


class TestCompleteResponseBudgets(unittest.TestCase):
    def assert_accounted(self, response):
        encoded = compact_json(response)
        self.assertEqual(response["returned_bytes"], len(encoded))
        self.assertEqual(response["estimated_tokens"], math.ceil(len(encoded) / 4))
        self.assertEqual(json.loads(encoded), response)

    def test_exact_bytes_cover_metadata_unicode_and_accounting_fields(self):
        payload = {"matches": [{"id": "large", "text": "雪🙂" * 1500}], "query": "雪", "abstention": False}
        original = deepcopy(payload)
        response = bounded_response(payload, max_bytes=600, max_tokens=None)
        self.assertLessEqual(len(compact_json(response)), 600)
        self.assertEqual(response["matches"], [])
        self.assertEqual(response["omitted_count"], 1)
        self.assertTrue(response["abstention"])
        self.assertEqual(response["status"], "budget_exhausted")
        self.assertEqual(payload, original)
        self.assert_accounted(response)

    def test_token_cap_covers_entire_envelope_and_drops_only_complete_entries(self):
        payload = {"matches": [{"id": str(i), "text": "content " * 80} for i in range(5)], "query": "notes"}
        response = bounded_response(payload, max_bytes=10000, max_tokens=230)
        self.assertLessEqual(response["estimated_tokens"], 230)
        self.assertLess(len(response["matches"]), 5)
        for entry in response["matches"]:
            self.assertEqual(entry["text"], "content " * 80)
        self.assert_accounted(response)

    def test_accounting_respects_an_exact_boundary_and_includes_its_own_digits(self):
        payload = {"matches": [{"id": "one", "text": "Complete evidence text."}]}
        original = bounded_response(payload, max_bytes=10000, max_tokens=None)
        exact = bounded_response(payload, max_bytes=original["returned_bytes"], max_tokens=None)
        self.assertEqual(exact, original)
        smaller = bounded_response(payload, max_bytes=original["returned_bytes"] - 1, max_tokens=None)
        self.assertEqual(smaller["matches"], [])
        self.assertLessEqual(smaller["returned_bytes"], original["returned_bytes"] - 1)
        self.assert_accounted(smaller)

    def test_generic_legacy_collections_drop_lowest_scored_tails(self):
        payload = {"matches": {"memory_records": [{"id": "best", "score": 9, "text": "a" * 400}],
                               "topic_tracks": [{"id": "weak", "score": 1, "text": "b" * 400}]},
                   "records": [], "profiles": [], "tracks": []}
        response = bounded_response(payload, max_bytes=850, max_tokens=None)
        self.assertEqual([r["id"] for r in response["matches"]["memory_records"]], ["best"])
        self.assertEqual(response["matches"]["topic_tracks"], [])
        self.assertEqual(response["omitted_count"], 1)
        self.assert_accounted(response)

    def test_search_budget_drops_full_huge_evidence_without_changing_source_text(self):
        huge = "Editor observation: " + "長い原文🙂" * 5000
        data = store(record(text=huge))
        response = run(data, "editor", max_bytes=1000, max_tokens=200)
        self.assertEqual(response["matches"], [])
        self.assertTrue(response["abstention"])
        self.assertEqual(response["status"], "budget_exhausted")
        self.assertEqual(data["memory_records"][0]["text"], huge)
        self.assert_accounted(response)

    def test_metadata_that_cannot_fit_fails_clearly(self):
        with self.assertRaisesRegex(ValueError, "metadata"):
            bounded_response({"query": "雪" * 3000, "matches": []}, max_bytes=500)
        with self.assertRaisesRegex(ValueError, "metadata"):
            run(store(record(), updated_at="x" * 10000), "editor", max_bytes=500)

    def test_arguments_are_validated_even_for_empty_store(self):
        for fields in ({"top_k": True}, {"top_k": 0}, {"top_k": 101}, {"max_bytes": True},
                       {"max_bytes": 0}, {"max_tokens": False}, {"max_tokens": -1}, {"mode": "other"}):
            with self.subTest(fields=fields), self.assertRaises(ValueError):
                run(store(), "editor", **fields)
        for query in ("", " " * 3, 2, "x" * 2049):
            with self.subTest(query=query), self.assertRaises(ValueError):
                run(store(), query)
        for scope in (False, "", "x" * 257, "project:a\nprivate"):
            with self.subTest(scope=scope), self.assertRaises(ValueError):
                search(store(), "editor", scope=scope, as_of=JUL)


if __name__ == "__main__":
    unittest.main()
