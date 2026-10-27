#!/usr/bin/env python3
"""
Semantic Embedding Index for the NapMem Pyramid

Provides cosine-similarity retrieval and near-duplicate detection over Layer 1
memory records. Two embedding backends:

  - OllamaBackend: real embeddings from an Ollama fleet via the shared
    `ollama-client` library (weighted pool, per-host failover, retry,
    response validation). Probes every host in NAPMEM_OLLAMA_URLS and pools
    the live ones. With no NAPMEM_OLLAMA_URL(S) set, the library defaults
    apply: OLLAMA_URLS / OLLAMA_HOST, else http://127.0.0.1:11434. Zero API
    cost, no cloud dependency.
  - HashedTfBackend: pure-stdlib fallback — hashed bag-of-words term-frequency
    vectors. Deterministic, dependency-free, adequate for near-duplicate
    detection and keyword-ish search; weaker on true paraphrase.

Vectors are cached in <pyramid>.embindex.json keyed by record id + text hash,
so unchanged records are never re-embedded.

Usage:
    python3 semantic_index.py --pyramid napmem_pyramid.json --rebuild
    python3 semantic_index.py --query "storage engine preferences" --top-k 5
"""

from __future__ import annotations

import argparse
import hashlib
import json
import logging
import math
import os
import re
from typing import Any

try:
    from ollama_client import (
        OllamaClient, OllamaPool, cosine as _shared_cosine, parse_urls, urls_from_env,
    )
except ImportError:
    # Offline retrieval uses only stdlib math. Ollama transport and URL parsing
    # remain owned by the optional shared client, with no local replacement.
    OllamaClient = OllamaPool = _shared_cosine = parse_urls = urls_from_env = None

from napmem_storage import StoreConflict, atomic_write, file_fingerprint, store_lock

logger = logging.getLogger(__name__)

# Capacity-weighted Ollama pool. Comma-separated `url=weight` entries (weight
# optional, default 1) in NAPMEM_OLLAMA_URLS; embedding batches are spread over
# the LIVE hosts in proportion to weight and a failing host's batch is retried
# on the others (ollama-client pool). A single NAPMEM_OLLAMA_URL overrides the
# list. Nothing is hardcoded: with neither set, the ollama-client environment
# applies (OLLAMA_URLS, then OLLAMA_HOST, then http://127.0.0.1:11434). Put the
# fleet in the environment, e.g. deploy/napmem-consolidator.service.

OLLAMA_INSTALL_MESSAGE = (
    "Ollama embeddings require the optional shared ollama-client package. "
    "Install it with: python -m pip install 'llm-memory-pyramid[ollama]'"
)


def _require_ollama_client():
    if OllamaClient is None or OllamaPool is None:
        raise RuntimeError(OLLAMA_INSTALL_MESSAGE)


def cosine(left: list[float], right: list[float]) -> float:
    """Use shared cosine when installed, otherwise stdlib vector arithmetic."""
    if _shared_cosine is not None:
        return _shared_cosine(left, right)
    if len(left) != len(right):
        raise ValueError("Vectors must have matching dimensions")
    left_norm = math.sqrt(sum(value * value for value in left))
    right_norm = math.sqrt(sum(value * value for value in right))
    if not left_norm or not right_norm:
        return 0.0
    return sum(a * b for a, b in zip(left, right)) / (left_norm * right_norm)


def _parse_weighted_urls(raw: str) -> list[tuple[str, int]]:
    _require_ollama_client()
    return parse_urls(raw)


def _configured_hosts() -> list[tuple[str, int]]:
    if OllamaClient is None or OllamaPool is None:
        return []
    raw = os.environ.get("NAPMEM_OLLAMA_URL") or os.environ.get("NAPMEM_OLLAMA_URLS", "")
    return _parse_weighted_urls(raw) or urls_from_env()


OLLAMA_HOSTS = _configured_hosts()
OLLAMA_URLS = [u for u, _ in OLLAMA_HOSTS]  # back-compat (probe order)
# mxbai-embed-large: strongest embedding model served by every host; keeping
# remote and local on the SAME model preserves the vector cache across
# failover (a model switch invalidates every cached vector).
OLLAMA_MODEL = os.environ.get("NAPMEM_OLLAMA_MODEL", "mxbai-embed-large")
BACKEND_ENV = "NAPMEM_EMBED_BACKEND"  # "ollama" | "hashed" | unset (auto)
EMBED_TIMEOUT_S = 300
PROBE_TIMEOUT_S = 1.5

TOKEN_RE = re.compile(r"[a-z0-9]+")
HASHED_DIM = 512
MAX_CACHE_DIMENSIONS = 8192


def _text_key(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:16]


def _valid_cached_vector(vector: Any, dimensions: int | None = None) -> bool:
    """Validate disposable cache data before it reaches cosine scoring."""
    if (not isinstance(vector, list) or not 1 <= len(vector) <= MAX_CACHE_DIMENSIONS
            or (dimensions is not None and len(vector) != dimensions)):
        return False
    try:
        return all(isinstance(value, (int, float)) and not isinstance(value, bool)
                   and math.isfinite(value) for value in vector)
    except OverflowError:
        return False


def _checked_cosine(left: list[float], right: list[float]) -> float:
    # Finite coordinates can still overflow the shared helper's arithmetic.
    # Reject an unusable score so callers take their disclosed fallback rather
    # than emitting NaN JSON or making a semantic-dedup decision from it.
    score = cosine(left, right)
    if not math.isfinite(score):
        raise ValueError("Embedding similarity is not finite")
    return score


class HashedTfBackend:
    """Stdlib-only hashed term-frequency vectors (l2-normalized)."""

    name = "hashed-tf"
    model = f"hashed-tf-{HASHED_DIM}"

    def embed(self, texts: list[str]) -> list[list[float]]:
        vectors = []
        for text in texts:
            vec = [0.0] * HASHED_DIM
            for token in TOKEN_RE.findall(text.lower()):
                bucket = int(hashlib.md5(token.encode("utf-8")).hexdigest(), 16) % HASHED_DIM
                vec[bucket] += 1.0
            norm = math.sqrt(sum(v * v for v in vec))
            if norm > 0:
                vec = [v / norm for v in vec]
            vectors.append(vec)
        return vectors


class OllamaBackend:
    """
    Capacity-weighted embedding pool over one or more Ollama hosts, backed by
    ollama_client.OllamaClient.

    Every live host must serve the SAME model (cache validity). A batch is cut
    into ~sum(weights) pieces dispatched in parallel (one worker per host); the
    pool picks hosts by weight, fails a piece over to the other hosts and
    cools a failing host down. Responses are validated by the library (finite
    numbers, one bounded dimension, matching count). All hosts failing raises
    OllamaUnavailable (a RuntimeError; callers degrade to hashed/substring paths).
    """

    def __init__(self, base_url: str | None = None, model: str = OLLAMA_MODEL,
                 hosts: list[tuple[str, int]] | None = None):
        _require_ollama_client()
        if hosts is None:
            hosts = [(base_url.rstrip("/"), 1)] if base_url else []
        self.hosts: list[tuple[str, int]] = [(u.rstrip("/"), w) for u, w in hosts]
        self.model = model
        self._pool: OllamaPool | None = None
        self._pool_hosts: list[tuple[str, int]] = []

    @property
    def base_url(self) -> str:
        return self.hosts[0][0] if self.hosts else ""

    @property
    def name(self) -> str:
        return "ollama" if len(self.hosts) <= 1 else f"ollama-pool[{len(self.hosts)}]"

    @property
    def pool(self) -> OllamaPool:
        """The library pool for the current host list (health state survives calls)."""
        if self._pool is None or self._pool_hosts != self.hosts:
            self._pool = OllamaPool(list(self.hosts))
            self._pool_hosts = list(self.hosts)
        return self._pool

    @staticmethod
    def _host_alive(url: str) -> bool:
        if OllamaClient is None or OllamaPool is None:
            return False
        client = OllamaClient(OllamaPool([url], retries=0), embed_model=OLLAMA_MODEL)
        return client.available(url, timeout=PROBE_TIMEOUT_S)

    @classmethod
    def probe(cls, urls: list[str] | None = None) -> "OllamaBackend | None":
        """Probes every configured host; returns a pool of the live ones
        (weighted per NAPMEM_OLLAMA_URLS), or None when none respond."""
        if OllamaClient is None or OllamaPool is None:
            return None
        configured = ([(u, 1) for u in urls] if urls is not None else OLLAMA_HOSTS)
        if not configured:
            return None
        pool = OllamaPool(configured, retries=0)
        states = OllamaClient(pool, embed_model=OLLAMA_MODEL).health(timeout=PROBE_TIMEOUT_S)
        live = [(h.url, h.weight) for h in pool.hosts if states.get(h.url)]
        if not live:
            return None
        backend = cls(hosts=live)
        logger.info("Ollama backend: %s -> %s (%s)", backend.name,
                    [f"{u}(w={w})" for u, w in live], backend.model)
        return backend

    def embed(self, texts: list[str]) -> list[list[float]]:
        if not self.hosts:
            raise RuntimeError("Ollama pool has no live hosts")
        if not texts:
            return []
        # Small batches (or one host): a single request. Large batches: cut into
        # ~sum(weights) pieces so the weighted pool spreads them across hosts.
        total_w = sum(w for _, w in self.hosts)
        if len(self.hosts) == 1 or len(texts) < 4:
            batch = len(texts)
        else:
            batch = max(1, math.ceil(len(texts) / total_w))
        client = OllamaClient(self.pool, embed_model=self.model, batch_size=batch,
                              workers=len(self.hosts))
        return client.embed(texts, timeout=EMBED_TIMEOUT_S)


def select_backend():
    forced = os.environ.get(BACKEND_ENV, "").lower()
    if forced == "hashed":
        return HashedTfBackend()
    if forced == "ollama":
        _require_ollama_client()
        backend = OllamaBackend.probe()
        if backend is None:
            raise RuntimeError(
                f"{BACKEND_ENV}=ollama but no Ollama server responded at any of {OLLAMA_URLS}"
            )
        return backend
    return OllamaBackend.probe() or HashedTfBackend()


class SemanticIndex:
    """Persistent embedding index over a pyramid store's Layer 1 records."""

    def __init__(self, pyramid_path: str, backend=None, *, cache_writable=True):
        self.pyramid_path = pyramid_path
        self.index_path = f"{pyramid_path}.embindex.json"
        self._store_fingerprint = file_fingerprint(pyramid_path)
        self.cache_writable = (cache_writable and os.environ.get("NAPMEM_CACHE_READ_ONLY") != "1"
                               and not os.path.isfile(os.path.join(os.path.dirname(os.path.abspath(pyramid_path)), "manifest.json")))
        self.backend = backend or select_backend()
        self._cache_dirty = False
        self._cache = self._load()

    def _load(self) -> dict[str, Any]:
        if os.path.exists(self.index_path):
            # The cache is disposable: a corrupt or unreadable file (e.g. left
            # behind by a crashed writer) must never take down a sweep — start
            # fresh and re-embed instead.
            try:
                with open(self.index_path, "r", encoding="utf-8") as f:
                    cache = json.load(f)
            except (OSError, ValueError) as exc:
                logger.warning("Discarding unreadable embedding cache %s: %s",
                               self.index_path, exc)
                cache = {}
            # A backend/model switch invalidates every cached vector.
            if (isinstance(cache, dict) and cache.get("model") == self.backend.model
                    and isinstance(cache.get("vectors"), dict)):
                vectors = cache["vectors"]
                valid = {rid: entry for rid, entry in vectors.items()
                         if isinstance(entry, dict) and isinstance(entry.get("key"), str)
                         and _valid_cached_vector(entry.get("vec"))}
                discarded = len(vectors) - len(valid)
                if discarded:
                    logger.warning("Discarding %d invalid embedding cache entries from %s",
                                   discarded, self.index_path)
                    self._cache_dirty = True
                return {"model": self.backend.model, "vectors": valid}
        return {"model": self.backend.model, "vectors": {}}

    def save(self):
        if not self.cache_writable:
            return
        with store_lock(self.pyramid_path):
            if file_fingerprint(self.pyramid_path) != self._store_fingerprint:
                raise StoreConflict("Canonical store changed; discard the stale embedding index")
            atomic_write(self.index_path, self._cache,
                         expected_fingerprint=file_fingerprint(self.index_path))

    def _embed_checked(self, texts: list[str], dimensions: int | None = None):
        embedded = self.backend.embed(texts)
        if (not isinstance(embedded, list) or len(embedded) != len(texts)
                or not all(_valid_cached_vector(vec, dimensions) for vec in embedded)
                or len({len(vec) for vec in embedded}) != 1):
            raise ValueError("Embedding backend returned invalid or inconsistent vectors")
        return embedded

    def _vectors_for(self, records: list[dict[str, Any]],
                     dimensions: int | None = None) -> dict[str, list[float]]:
        """Returns {record_id: vector}, embedding only cache misses."""
        wanted: dict[str, str] = {r["id"]: _text_key(r["text"]) for r in records}
        cached = self._cache["vectors"]
        vectors = {rid: entry for rid, entry in cached.items() if rid in wanted}
        if dimensions is None and isinstance(self.backend, HashedTfBackend):
            dimensions = HASHED_DIM
        if dimensions is None and len({len(entry["vec"]) for entry in vectors.values()}) > 1:
            logger.warning("Discarding embedding cache entries with mixed dimensions from %s",
                           self.index_path)
            vectors = {}
        invalid = [rid for rid, entry in vectors.items()
                   if not _valid_cached_vector(entry["vec"], dimensions)]
        if invalid:
            logger.warning("Discarding %d embedding cache entries with invalid dimensions from %s",
                           len(invalid), self.index_path)
            for rid in invalid:
                del vectors[rid]
        missing = [r for r in records if vectors.get(r["id"], {}).get("key") != wanted[r["id"]]]
        if missing:
            embedded = self._embed_checked([r["text"] for r in missing], dimensions)
            for rec, vec in zip(missing, embedded):
                vectors[rec["id"]] = {"key": wanted[rec["id"]], "vec": vec}
            # A fresh vector also establishes the dimension for cache-only
            # callers such as rebuild(), which do not have a query vector.
            fresh_dimensions = len(embedded[0])
            stale = [r for r in records
                     if len(vectors[r["id"]]["vec"]) != fresh_dimensions]
            if stale:
                logger.warning("Discarding %d stale-dimension embedding cache entries from %s",
                               len(stale), self.index_path)
                refreshed = self._embed_checked([r["text"] for r in stale], fresh_dimensions)
                for rec, vec in zip(stale, refreshed):
                    vectors[rec["id"]] = {"key": wanted[rec["id"]], "vec": vec}
        # Persist deletion-only changes too; an empty rebuild must clear disk.
        if self._cache_dirty or vectors != cached:
            self._cache["vectors"] = vectors
            self.save()
            self._cache_dirty = False
        return {rid: vectors[rid]["vec"] for rid in wanted}

    def rebuild(self, records: list[dict[str, Any]]):
        self._cache = {"model": self.backend.model, "vectors": {}}
        self._cache_dirty = True
        self._vectors_for(records)

    def search(self, query: str, records: list[dict[str, Any]],
               top_k: int = 5) -> list[dict[str, Any]]:
        """Top-k records by cosine similarity to the query."""
        if isinstance(top_k, bool) or not isinstance(top_k, int) or top_k <= 0:
            raise ValueError("top_k must be a positive integer")
        if not records:
            self._vectors_for([])
            return []
        query_vec = self._embed_checked([query])[0]
        vectors = self._vectors_for(records, len(query_vec))
        scored = sorted(
            ({"score": round(_checked_cosine(query_vec, vectors[r["id"]]), 4), "record": r}
             for r in records),
            key=lambda s: s["score"], reverse=True,
        )
        return scored[:top_k]

    def nearest_record_id(self, text: str, records: list[dict[str, Any]],
                          threshold: float) -> str | None:
        """Id of the most similar record at or above threshold, else None.
        Delegates to nearest_many so single and batched calls can never
        disagree at threshold boundaries (search() rounds for display; the
        dedup decision must not)."""
        return self.nearest_many([text], records, threshold)[0]

    def nearest_many(self, texts: list[str], records: list[dict[str, Any]],
                     threshold: float) -> list[str | None]:
        """
        Batched nearest_record_id: ONE embed round-trip for all query texts
        (plus cache misses among records) instead of one per query — the
        difference between minutes and hours on a large merge.
        """
        if not texts:
            return []
        if not records:
            self._vectors_for([])
            return [None] * len(texts)
        query_vecs = self._embed_checked(texts)
        vectors = self._vectors_for(records, len(query_vecs[0]))
        out: list[str | None] = []
        for qv in query_vecs:
            best_id, best_score = None, -math.inf
            for r in records:
                score = _checked_cosine(qv, vectors[r["id"]])
                if score > best_score:
                    best_id, best_score = r["id"], score
            out.append(best_id if best_score >= threshold else None)
        return out


def main():
    parser = argparse.ArgumentParser(description="NapMem semantic embedding index.")
    parser.add_argument("--pyramid", type=str, default="napmem_pyramid.json")
    parser.add_argument("--rebuild", action="store_true", help="Re-embed every record.")
    parser.add_argument("--query", type=str, help="Semantic search query.")
    parser.add_argument("--top-k", type=int, default=5)
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO,
                        format="%(asctime)s [%(name)s] %(levelname)s: %(message)s")

    with open(args.pyramid, "r", encoding="utf-8") as f:
        records = json.load(f)["memory_records"]

    index = SemanticIndex(args.pyramid)
    print(f"Backend: {index.backend.name} ({index.backend.model})")

    if args.rebuild:
        index.rebuild(records)
        print(f"Rebuilt index for {len(records)} record(s) -> {index.index_path}")
    if args.query:
        for hit in index.search(args.query, records, top_k=args.top_k):
            rec = hit["record"]
            print(f"{hit['score']:.4f}  [{rec['type']}] {rec['text']}  ({rec['id']})")
    if not args.rebuild and not args.query:
        parser.print_help()


if __name__ == "__main__":
    main()
