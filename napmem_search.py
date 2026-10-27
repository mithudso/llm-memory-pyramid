"""Offline scoped retrieval with complete-entry JSON budgets.

BM25 and sparse TF-IDF use only the already eligible records. A supplied
embedding backend may add semantic candidates. No backend is selected, no
network is probed, and no cache or store is written by this module.
"""

from __future__ import annotations

from collections import Counter
from copy import deepcopy
from datetime import UTC, datetime
import hashlib
import json
import math
import re
from typing import Any
import unicodedata

from napmem_model import effective_records, parse_time


MAX_QUERY_CHARS = 2048
MAX_BUDGET_BYTES = 16 * 1024 * 1024
TOKEN_ESTIMATOR = "ceil(compact_utf8_bytes/4); estimate, not a model tokenizer"
MODES = ("hybrid", "lexical", "substring", "hashed", "semantic")
_WORD = re.compile(r"\w+(?:[./:-]\w+)*", re.UNICODE)
_STOP = frozenset("""a an the and or but if then than of for from to into in on at by with
    as is are was were be been being it its their this that these those what which
    who whom whose how when where why does do did can could may might should would
    will shall have has had not no yes now today currently current during before
    after every all some any each other same both our your my we i they he she you
    there here about through under over between onward use used using apply applies
    applicable govern governs known know tell please question ask project team
""".split())
# Small general-language normalizations, independent of fixture/project names.
_SYNONYMS = (
    ("prefer", "preference", "preferred", "favorite", "favourite"),
    ("save", "store", "persist", "preserve"),
    ("folder", "directory"), ("delete", "remove", "erase"),
    ("config", "configuration", "setting"), ("picture", "image", "photo"),
    ("backup", "copy"), ("error", "failure", "exception"),
    ("limit", "maximum", "capacity"), ("duration", "time", "period"),
    ("finish", "complete", "done"), ("send", "transmit"),
    ("credential", "authentication", "auth"), ("signout", "logout"),
    ("display", "show"), ("return", "restore"), ("require", "mandatory"),
    ("begin", "start", "initial"), ("value", "amount"),
    ("retention", "retain", "keep"), ("language", "locale"),
    ("store", "storage"), ("owner", "own", "owns", "ownership", "responsible"),
    ("audience", "reader", "read"), ("document", "documentation", "guide", "manual"),
    ("rule", "policy"), ("format", "style"), ("directory", "destination"),
    ("overflow", "exceed", "full", "fill"), ("pending", "waiting", "wait"),
    ("job", "work"), ("delay", "backoff"), ("write", "post"), ("get", "fetch"),
    ("temporary", "transient"), ("idea", "tentative", "proposal"),
    ("launch", "ship", "delivery"), ("label", "text"),
)


def compact_json(payload: Any) -> bytes:
    """Canonical transport representation used for byte and token accounting."""
    return json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"),
                      allow_nan=False).encode("utf-8")


def _positive(value: Any, field: str, maximum: int) -> None:
    if isinstance(value, bool) or not isinstance(value, int) or not 1 <= value <= maximum:
        raise ValueError(f"{field} must be an integer between 1 and {maximum}")


def _collections(payload: dict[str, Any]) -> list[list[Any]]:
    result = []
    for field in ("matches", "records", "profiles", "tracks"):
        collection = payload.get(field)
        if isinstance(collection, list):
            result.append(collection)
        elif field == "matches" and isinstance(collection, dict):
            result.extend(value for _, value in sorted(collection.items()) if isinstance(value, list))
    return result


def _account(payload: dict[str, Any]) -> bytes:
    # Both accounting fields contribute to the size. Iterate to a fixed point
    # rather than omitting their own digits from the declared budget.
    payload.setdefault("estimated_tokens", 0)
    payload.setdefault("returned_bytes", 0)
    for _ in range(16):
        encoded = compact_json(payload)
        size = len(encoded)
        tokens = math.ceil(size / 4)
        if payload["returned_bytes"] == size and payload["estimated_tokens"] == tokens:
            return encoded
        payload["returned_bytes"], payload["estimated_tokens"] = size, tokens
    raise ValueError("Unable to account for response metadata")


def bounded_response(payload: dict[str, Any], *, max_bytes: int = 16384,
                     max_tokens: int | None = 2048) -> dict[str, Any]:
    """Copy a JSON response and drop complete lowest-ranked tail entries until it fits.

    Supports matches lists, legacy nested match lists, records, profiles and
    tracks. Within each collection the existing order is authoritative. Across
    collections numeric tail scores decide first, with stable collection order
    breaking ties. Unscored collections use that stable order alone.
    """
    _positive(max_bytes, "max_bytes", MAX_BUDGET_BYTES)
    if max_tokens is not None:
        _positive(max_tokens, "max_tokens", MAX_BUDGET_BYTES)
    if not isinstance(payload, dict):
        raise ValueError("Response must be an object")
    result = deepcopy(payload)
    result.setdefault("truncated", False)
    result.setdefault("omitted_count", 0)
    if (not isinstance(result["omitted_count"], int) or isinstance(result["omitted_count"], bool)
            or result["omitted_count"] < 0):
        raise ValueError("omitted_count must be a nonnegative integer")
    result["token_estimator"] = TOKEN_ESTIMATOR
    collections = _collections(result)
    while True:
        encoded = _account(result)
        if len(encoded) <= max_bytes and (max_tokens is None or result["estimated_tokens"] <= max_tokens):
            return result
        nonempty = [(idx, items) for idx, items in enumerate(collections) if items]
        if not nonempty:
            raise ValueError("Response budget is too small for metadata")

        def tail_rank(pair):
            idx, items = pair
            tail = items[-1]
            score = tail.get("score") if isinstance(tail, dict) else None
            if isinstance(score, (int, float)) and not isinstance(score, bool) and math.isfinite(score):
                return score, -idx
            return -math.inf, -idx

        _, items = min(nonempty, key=tail_rank)
        items.pop()
        result["truncated"] = True
        result["omitted_count"] += 1
        if "abstention" in result and not any(collections):
            result["abstention"] = True
            result["status"] = "budget_exhausted"


def _stem(token: str) -> str:
    if len(token) > 5 and token.endswith("ies"):
        return token[:-3] + "y"
    for suffix in ("ing", "ed"):
        if len(token) > len(suffix) + 3 and token.endswith(suffix):
            return token[:-len(suffix)]
    if len(token) > 4 and token.endswith(("sses", "xes", "zes", "ches", "shes")):
        return token[:-2]
    if len(token) > 3 and token.endswith("s") and not token.endswith("ss"):
        return token[:-1]
    return token


def _synonym_map() -> dict[str, str]:
    parents: dict[str, str] = {}

    def root(word):
        while parents[word] != word:
            word = parents[word]
        return word

    for group in _SYNONYMS:
        words = [_stem(word) for word in group]
        for word in words:
            parents.setdefault(word, word)
        for word in words[1:]:
            parents[root(word)] = root(words[0])
    return {word: root(word) for word in parents}


_ALIAS = _synonym_map()


def _tokens(text: str) -> list[str]:
    result = []
    for original in _WORD.findall(text):
        # Keep exact symbols while also exposing components to natural queries.
        separated = re.sub(r"([a-z])([A-Z])", r"\1 \2", original)
        components = re.split(r"[\W_]+", separated)
        for word in dict.fromkeys([original.casefold(), *[part.casefold() for part in components if part]]):
            if word in _STOP:
                continue
            stem = _stem(word)
            if stem in _STOP:
                continue
            result.append(_ALIAS.get(stem, stem))
    return result


def _safe_source(record: dict[str, Any], excluded: set[str]) -> bool:
    anchor = record.get("source_anchor", {})
    evidence = record.get("evidence", {})
    return not (record.get("source_excluded") or record.get("instruction_bearing")
                or record.get("source_status") in ("excluded", "deleted")
                or anchor.get("excluded") or anchor.get("status") in ("excluded", "deleted")
                or anchor.get("file_path") in excluded
                or evidence.get("status") in ("excluded", "deleted", "rejected"))


def eligible_records(data: dict[str, Any], scope: str | None, at: str) -> list[dict[str, Any]]:
    """Shared scope, validity and source-safety filter used before any ranking."""
    if scope is not None and (not isinstance(scope, str) or not scope.strip() or len(scope) > 256
                              or any(unicodedata.category(char) == "Cc" for char in scope)):
        raise ValueError("scope must be a bounded nonempty string without control characters")
    controls = data.get("controls", {})
    excluded_raw = controls.get("excluded_sources", []) if isinstance(controls, dict) else []
    excluded = set(excluded_raw) if isinstance(excluded_raw, (list, dict)) else set()
    known_unsafe = {r["id"] for r in data.get("memory_records", []) if r.get("instruction_bearing")}
    result = []
    for record in effective_records(data, scope, at):
        if record.get("canonical", record["id"]) in known_unsafe or not _safe_source(record, excluded):
            continue
        aliases = {}
        for rid, anchor in record.get("duplicate_anchors", {}).items():
            occurrence = {**anchor.get("assertion", {}), "source_anchor": anchor}
            if _safe_source(occurrence, excluded):
                aliases[rid] = anchor
        record["duplicate_anchors"] = aliases
        record["duplicates"] = [rid for rid in record.get("duplicates", []) if rid in aliases]
        result.append(record)
    return result


def _cosine(left: list[float], right: list[float]) -> float:
    denominator = math.sqrt(sum(x * x for x in left)) * math.sqrt(sum(x * x for x in right))
    return sum(a * b for a, b in zip(left, right)) / denominator if denominator else 0.0


def _backend_scores(backend: Any, query: str, records: list[dict[str, Any]]) -> list[float]:
    vectors = backend.embed([query, *[r["text"] for r in records]])
    if (not isinstance(vectors, list) or len(vectors) != len(records) + 1
            or not all(isinstance(vec, list) and 1 <= len(vec) <= 8192 for vec in vectors)
            or len({len(vec) for vec in vectors}) != 1
            or any(isinstance(n, bool) or not isinstance(n, (int, float)) or not math.isfinite(n)
                   for vec in vectors for n in vec)):
        raise ValueError("Embedding backend returned invalid vectors")
    scores = [_cosine(vectors[0], vec) for vec in vectors[1:]]
    if not all(math.isfinite(score) for score in scores):
        raise ValueError("Embedding backend returned unusable vectors")
    return scores


def search(data: dict[str, Any], query: str, *, scope: str | None = None,
           as_of: str | datetime | None = None, top_k: int = 5, mode: str = "hybrid",
           max_bytes: int = 16384, max_tokens: int | None = 2048,
           backend: Any = None) -> dict[str, Any]:
    """Retrieve scoped evidence, preserving source text as untrusted data.

    Default hybrid fuses BM25 with deterministic sparse TF-IDF cosine ranks.
    Scores are ranking signals, not calibrated truth or answer confidence.
    Explicit embedding failures fall back to lexical results and disclose the
    exception class, excluding potentially sensitive exception text.
    """
    if not isinstance(data, dict):
        raise ValueError("Store must be an object")
    if not isinstance(query, str) or not query.strip() or len(query) > MAX_QUERY_CHARS:
        raise ValueError(f"query must be a nonempty string of at most {MAX_QUERY_CHARS} characters")
    _positive(top_k, "top_k", 100)
    _positive(max_bytes, "max_bytes", MAX_BUDGET_BYTES)
    if max_tokens is not None:
        _positive(max_tokens, "max_tokens", MAX_BUDGET_BYTES)
    if mode not in MODES:
        raise ValueError("Unknown retrieval mode")
    generation = data.get("generation", 0)
    if isinstance(generation, bool) or not isinstance(generation, int) or generation < 0:
        raise ValueError("generation must be a nonnegative integer")
    at = parse_time(as_of).isoformat() if as_of is not None else datetime.now(UTC).isoformat()
    records = eligible_records(data, scope, at)
    # Scope names identify the corpus, rather than the information being asked
    # for. Excluding them prevents every project record from being a match.
    context_terms = set(_tokens(scope.split(":", 1)[-1])) if scope and scope != "*" else set()
    terms = [term for term in _tokens(query) if term not in context_terms]
    query_terms = set(terms)
    # Literal codes, paths and numeric limits cannot be approximated by a
    # semantically similar but different identifier or number.
    date_parts = {str(value) for value in (parse_time(at).year, parse_time(at).month, parse_time(at).day)}
    month_in_query = re.search(r"\b(?:jan(?:uary)?|feb(?:ruary)?|mar(?:ch)?|apr(?:il)?|may|jun(?:e)?|jul(?:y)?|aug(?:ust)?|sep(?:tember)?|oct(?:ober)?|nov(?:ember)?|dec(?:ember)?)\b", query, re.IGNORECASE)
    required_literals = [word.casefold() for word in _WORD.findall(query)
                         if any(char.isdigit() for char in word) or "_" in word
                         or "/" in word or re.search(r"[a-z][A-Z]", word)
                         or (word.isupper() and len(word) >= 2)]
    if month_in_query:
        required_literals = [word for word in required_literals if word not in date_parts]
    required_literals.extend(word.casefold() for word in re.findall(
        r"\b(?:Monday|Tuesday|Wednesday|Thursday|Friday|Saturday|Sunday)\b", query, re.IGNORECASE))
    fragment = ("?" not in query and not re.match(r"\s*(?:what|which|who|when|where|why|how|does|do|did|can|is|are|was|were|may|should)\b", query, re.IGNORECASE))
    doc_tokens = [_tokens(r["text"]) for r in records]
    counts = [Counter(tokens) for tokens in doc_tokens]
    frequency = Counter(term for bag in counts for term in bag)
    size = len(records)
    idf = {term: math.log(1 + (size - count + .5) / (count + .5)) for term, count in frequency.items()}
    average = sum(map(len, doc_tokens)) / size if size else 1
    lexical, sparse, matched, exact_ids, exact_texts = [], [], [], [], []
    for record, tokens, bag in zip(records, doc_tokens, counts):
        overlap = query_terms.intersection(bag)
        bm25 = sum(idf[term] * (bag[term] * 2.2) / (bag[term] + 1.2 * (.25 + .75 * len(tokens) / max(average, 1)))
                   for term in overlap)
        qweights = {term: idf.get(term, math.log(2 + size)) for term in query_terms}
        dweights = {term: count * idf[term] for term, count in bag.items()}
        norm = math.sqrt(sum(value * value for value in qweights.values())) * math.sqrt(sum(value * value for value in dweights.values()))
        cosine = sum(qweights[term] * dweights.get(term, 0) for term in query_terms) / norm if norm else 0
        identifiers = [record["id"], *record.get("duplicates", [])]
        exact_id = any(identifier.casefold() == query.strip().casefold()
                       or (len(identifier) >= 3 and re.search(r"(?<!\w)" + re.escape(identifier) + r"(?!\w)", query, re.IGNORECASE))
                       for identifier in identifiers)
        exact_text = query.strip().casefold() in record["text"].casefold()
        lexical.append(bm25)
        sparse.append(cosine)
        matched.append(sorted(overlap))
        exact_ids.append(exact_id)
        exact_texts.append(exact_text)
    vector = sparse
    actual_mode = "hybrid:sparse-tfidf" if mode == "hybrid" else mode
    fallback = None
    if backend is not None and records and query_terms and mode in ("hybrid", "semantic"):
        try:
            vector = _backend_scores(backend, query, records)
            actual_mode = mode + ":injected-embeddings"
        except Exception as exc:
            vector = [0.0] * size
            actual_mode = "lexical:fallback"
            fallback = type(exc).__name__
    elif mode == "semantic":
        actual_mode = "lexical:fallback"
        fallback = "NoInjectedBackend"
    if mode == "hashed":
        def hashed(words):
            vec = [0.0] * 512
            for term in words:
                vec[int(hashlib.sha256(term.encode("utf-8")).hexdigest(), 16) % 512] += 1
            return vec
        query_vec = hashed(terms)
        vector = [_cosine(query_vec, hashed(tokens)) for tokens in doc_tokens]
        actual_mode = "hashed:stdlib-tf"
    lexical_order = sorted(range(size), key=lambda idx: (-lexical[idx], records[idx]["id"]))
    vector_order = sorted(range(size), key=lambda idx: (-vector[idx], records[idx]["id"]))
    lexical_rank = {idx: rank for rank, idx in enumerate(lexical_order, 1)}
    vector_rank = {idx: rank for rank, idx in enumerate(vector_order, 1)}
    ranked = []
    for idx, record in enumerate(records):
        coverage = len(matched[idx]) / len(query_terms) if query_terms else 0
        # A short lookup must not silently discard its distinguishing term
        # (for example a color, environment or feature name). Dense evidence
        # can still support a paraphrase when explicitly configured below.
        required_coverage = 1.0 if len(query_terms) <= 2 else .25
        meaningful = bool(matched[idx]) and coverage >= required_coverage
        if backend is not None and actual_mode.endswith(":injected-embeddings"):
            meaningful = meaningful or vector[idx] >= .65
        if mode == "substring":
            meaningful = exact_texts[idx]
        searchable = (record["text"] + " " + " ".join([record["id"], *record.get("duplicates", [])])).casefold()
        if required_literals and not all(literal in searchable for literal in required_literals):
            continue
        if fragment and len(query_terms) >= 3 and not query_terms.issubset(set(doc_tokens[idx])) and not exact_ids[idx]:
            continue
        if not (meaningful or exact_ids[idx]):
            continue
        if mode in ("lexical", "substring") or actual_mode == "lexical:fallback":
            score = lexical[idx]
        elif mode in ("hashed", "semantic"):
            score = vector[idx]
        else:
            score = (1 / (60 + lexical_rank[idx]) if lexical[idx] > 0 else 0) + (1 / (60 + vector_rank[idx]) if vector[idx] > 0 else 0)
        score += 2 * exact_ids[idx] + .05 * exact_texts[idx] + .01 * bool(record.get("pinned"))
        match = deepcopy(record)
        match.update(score=round(score, 8),
                     ranking={"bm25": round(lexical[idx], 6), "cosine": round(vector[idx], 6),
                              "exact_id": exact_ids[idx], "exact_text": exact_texts[idx],
                              "pinned": bool(record.get("pinned")), "matched_terms": matched[idx]},
                     provenance_status=record.get("evidence", {}).get("status", "unverified"))
        ranked.append(match)
    ranked.sort(key=lambda item: (-item["score"], item["id"]))
    if ranked and mode != "substring":
        best_bm25 = max(item["ranking"]["bm25"] for item in ranked)
        ranked = [item for item in ranked if item["ranking"]["exact_id"] or item["ranking"]["exact_text"]
                  or item["ranking"]["bm25"] >= .4 * best_bm25
                  or (actual_mode.endswith(":injected-embeddings") and item["ranking"]["cosine"] >= .65)]
    chosen = ranked[:top_k]
    response = {"query": query, "scope": scope, "as_of": at, "mode": actual_mode,
                "generation": generation, "snapshot": {"version": data.get("version"), "updated_at": data.get("updated_at")},
                "matches": chosen, "abstention": not chosen, "status": "ok" if chosen else "no_match",
                "truncated": len(ranked) > len(chosen), "omitted_count": len(ranked) - len(chosen),
                "content_role": "untrusted_evidence"}
    if fallback:
        response["fallback_reason"] = fallback
    return bounded_response(response, max_bytes=max_bytes, max_tokens=max_tokens)
