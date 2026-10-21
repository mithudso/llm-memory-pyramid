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

import argparse
import hashlib
import json
import logging
import math
import os
import re
from typing import Any

from ollama_client import OllamaClient, OllamaPool, cosine, parse_urls, urls_from_env

logger = logging.getLogger(__name__)

# Capacity-weighted Ollama pool. Comma-separated `url=weight` entries (weight
# optional, default 1) in NAPMEM_OLLAMA_URLS; embedding batches are spread over
# the LIVE hosts in proportion to weight and a failing host's batch is retried
# on the others (ollama-client pool). A single NAPMEM_OLLAMA_URL overrides the
# list. Nothing is hardcoded: with neither set, the ollama-client environment
# applies (OLLAMA_URLS, then OLLAMA_HOST, then http://127.0.0.1:11434). Put the
# fleet in the environment, e.g. deploy/napmem-consolidator.service.


def _parse_weighted_urls(raw: str) -> list[tuple[str, int]]:
    return parse_urls(raw)


def _configured_hosts() -> list[tuple[str, int]]:
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


def _text_key(text: str) -> str:
    return hashlib.sha256(text.strip().lower().encode("utf-8")).hexdigest()[:16]


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
        client = OllamaClient(OllamaPool([url], retries=0), embed_model=OLLAMA_MODEL)
        return client.available(url, timeout=PROBE_TIMEOUT_S)

    @classmethod
    def probe(cls, urls: list[str] | None = None) -> "OllamaBackend | None":
        """Probes every configured host; returns a pool of the live ones
        (weighted per NAPMEM_OLLAMA_URLS), or None when none respond."""
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
        backend = OllamaBackend.probe()
        if backend is None:
            raise RuntimeError(
                f"{BACKEND_ENV}=ollama but no Ollama server responded at any of {OLLAMA_URLS}"
            )
        return backend
    return OllamaBackend.probe() or HashedTfBackend()


class SemanticIndex:
    """Persistent embedding index over a pyramid store's Layer 1 records."""

    def __init__(self, pyramid_path: str, backend=None):
        self.pyramid_path = pyramid_path
        self.index_path = f"{pyramid_path}.embindex.json"
        self.backend = backend or select_backend()
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
                return cache
        return {"model": self.backend.model, "vectors": {}}

    def save(self):
        # Per-PID tmp name: the index is written by both the consolidator and
        # any concurrent retrieval query; a shared tmp path lets one process's
        # os.replace consume the other's file (observed crash). Last writer
        # wins on the index itself — it is a rebuildable cache.
        tmp_path = f"{self.index_path}.{os.getpid()}.tmp"
        try:
            with open(tmp_path, "w", encoding="utf-8") as f:
                json.dump(self._cache, f, allow_nan=False)
            os.replace(tmp_path, self.index_path)
        except (OSError, ValueError):
            # Never leave a partial tmp behind: PIDs recycle, and a stale
            # partial could later be replaced over a good index.
            try:
                os.unlink(tmp_path)
            except OSError:
                pass
            raise

    def _vectors_for(self, records: list[dict[str, Any]]) -> dict[str, list[float]]:
        """Returns {record_id: vector}, embedding only cache misses."""
        wanted: dict[str, str] = {r["id"]: _text_key(r["text"]) for r in records}
        missing = [r for r in records
                   if self._cache["vectors"].get(r["id"], {}).get("key") != wanted[r["id"]]]
        if missing:
            embedded = self.backend.embed([r["text"] for r in missing])
            for rec, vec in zip(missing, embedded):
                self._cache["vectors"][rec["id"]] = {"key": wanted[rec["id"]], "vec": vec}
            # Drop vectors for records that no longer exist.
            live_ids = set(wanted)
            self._cache["vectors"] = {
                rid: entry for rid, entry in self._cache["vectors"].items() if rid in live_ids
            }
            self.save()
        return {rid: self._cache["vectors"][rid]["vec"] for rid in wanted}

    def rebuild(self, records: list[dict[str, Any]]):
        self._cache = {"model": self.backend.model, "vectors": {}}
        self._vectors_for(records)

    def search(self, query: str, records: list[dict[str, Any]],
               top_k: int = 5) -> list[dict[str, Any]]:
        """Top-k records by cosine similarity to the query."""
        if not records:
            return []
        vectors = self._vectors_for(records)
        query_vec = self.backend.embed([query])[0]
        scored = sorted(
            ({"score": round(cosine(query_vec, vectors[r["id"]]), 4), "record": r}
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
        return self.nearest_many([text], records, threshold)[0] if records else None

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
            return [None] * len(texts)
        vectors = self._vectors_for(records)
        query_vecs = self.backend.embed(texts)
        out: list[str | None] = []
        for qv in query_vecs:
            best_id, best_score = None, -math.inf
            for r in records:
                score = cosine(qv, vectors[r["id"]])
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
