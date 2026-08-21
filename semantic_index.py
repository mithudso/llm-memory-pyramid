#!/usr/bin/env python3
"""
Semantic Embedding Index for the NapMem Pyramid

Provides cosine-similarity retrieval and near-duplicate detection over Layer 1
memory records. Two embedding backends:

  - OllamaBackend: real embeddings from an Ollama server. Probes each host in
    NAPMEM_OLLAMA_URLS in order (default: the remote server at
    http://192.168.4.75:11434, then http://localhost:11434 as the local
    backup) and uses the first that responds. Zero API cost, no cloud
    dependency.
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
import http.client
import json
import logging
import math
import os
import re
import urllib.error
import urllib.request
from typing import Any

logger = logging.getLogger(__name__)

# Capacity-weighted Ollama pool. Comma-separated `url=weight` entries (weight
# optional, default 1); embedding batches are split across the LIVE hosts in
# proportion to weight, and a host failing mid-batch has its chunk retried on
# the remaining hosts. Fleet: the RTX 5080 Linux box (heaviest), the M5 Max
# MacBook Pro, and this box's local daemon. A single NAPMEM_OLLAMA_URL
# overrides the whole list.
DEFAULT_OLLAMA_URLS = (
    "http://192.168.4.75:11434=4,"    # linux / RTX 5080
    "http://192.168.4.1:11434=2,"     # M5 Max MBP 64GB
    "http://localhost:11434=1"        # this box
)


def _parse_weighted_urls(raw: str) -> list[tuple[str, int]]:
    hosts: list[tuple[str, int]] = []
    for part in raw.split(","):
        part = part.strip()
        if not part:
            continue
        url, _, weight = part.partition("=")
        try:
            w = max(1, int(weight)) if weight else 1
        except ValueError:
            w = 1
        hosts.append((url.strip().rstrip("/"), w))
    return hosts


OLLAMA_HOSTS = _parse_weighted_urls(
    os.environ.get("NAPMEM_OLLAMA_URL")
    or os.environ.get("NAPMEM_OLLAMA_URLS", DEFAULT_OLLAMA_URLS)
)
OLLAMA_URLS = [u for u, _ in OLLAMA_HOSTS]  # back-compat (probe order)
# mxbai-embed-large: strongest embedding model served by both hosts; keeping
# remote and local on the SAME model preserves the vector cache across
# failover (a model switch invalidates every cached vector).
OLLAMA_MODEL = os.environ.get("NAPMEM_OLLAMA_MODEL", "mxbai-embed-large")
BACKEND_ENV = "NAPMEM_EMBED_BACKEND"  # "ollama" | "hashed" | unset (auto)

TOKEN_RE = re.compile(r"[a-z0-9]+")
HASHED_DIM = 512
MAX_EMBED_DIM = 8192  # reject absurd vector dims (cache-bloat DoS guard)


def _reject_nonfinite_token(token: str):
    raise ValueError(f"non-finite JSON token rejected: {token}")


def _text_key(text: str) -> str:
    return hashlib.sha256(text.strip().lower().encode("utf-8")).hexdigest()[:16]


def cosine(a: list[float], b: list[float]) -> float:
    if len(a) != len(b):
        return 0.0
    dot = sum(x * y for x, y in zip(a, b))
    na = math.sqrt(sum(x * x for x in a))
    nb = math.sqrt(sum(x * x for x in b))
    if na == 0.0 or nb == 0.0:
        return 0.0
    return dot / (na * nb)


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
    Capacity-weighted embedding pool over one or more Ollama hosts.

    Every live host must serve the SAME model (cache validity). Batches are
    split across live hosts proportionally to their weights and dispatched in
    parallel; a host failing mid-batch has its chunk retried on the remaining
    hosts and is dropped from the pool for this process's lifetime. All hosts
    failing raises RuntimeError (callers degrade to hashed/substring paths).
    """

    def __init__(self, base_url: str | None = None, model: str = OLLAMA_MODEL,
                 hosts: list[tuple[str, int]] | None = None):
        if hosts is None:
            hosts = [(base_url.rstrip("/"), 1)] if base_url else []
        self.hosts: list[tuple[str, int]] = [(u.rstrip("/"), w) for u, w in hosts]
        self.model = model

    @property
    def base_url(self) -> str:
        return self.hosts[0][0] if self.hosts else ""

    @property
    def name(self) -> str:
        return "ollama" if len(self.hosts) <= 1 else f"ollama-pool[{len(self.hosts)}]"

    @staticmethod
    def _host_alive(url: str) -> bool:
        try:
            req = urllib.request.Request(f"{url}/api/tags", method="GET")
            with urllib.request.urlopen(req, timeout=1.5) as resp:
                return resp.status == 200
        except (urllib.error.URLError, OSError, TimeoutError) as exc:
            logger.debug("Ollama probe failed for %s: %s", url, exc)
            return False

    @classmethod
    def probe(cls, urls: list[str] | None = None) -> "OllamaBackend | None":
        """Probes every configured host; returns a pool of the live ones
        (weighted per NAPMEM_OLLAMA_URLS), or None when none respond."""
        configured = ([(u, 1) for u in urls] if urls is not None else OLLAMA_HOSTS)
        live = [(u.rstrip("/"), w) for u, w in configured if cls._host_alive(u)]
        if not live:
            return None
        backend = cls(hosts=live)
        logger.info("Ollama backend: %s -> %s (%s)", backend.name,
                    [f"{u}(w={w})" for u, w in live], backend.model)
        return backend

    def _embed_on(self, url: str, texts: list[str]) -> list[list[float]]:
        payload = json.dumps({"model": self.model, "input": texts}).encode("utf-8")
        req = urllib.request.Request(
            f"{url}/api/embed", data=payload,
            headers={"Content-Type": "application/json"}, method="POST",
        )
        # Any transport-or-parse failure must surface as RuntimeError — the
        # failover loops key on it; a bare JSONDecodeError/HTTPException from a
        # misbehaving host would otherwise escape embed() and defeat the pool.
        try:
            with urllib.request.urlopen(req, timeout=300) as resp:
                # parse_constant: stdlib json accepts NaN/Infinity tokens by
                # default — reject them so they never reach the cache.
                body = json.load(resp, parse_constant=_reject_nonfinite_token)
        except (urllib.error.URLError, OSError, TimeoutError, ValueError,
                http.client.HTTPException) as exc:
            raise RuntimeError(f"Ollama embedding request failed ({url}): {exc}") from exc
        embeddings = body.get("embeddings") if isinstance(body, dict) else None
        if not isinstance(embeddings, list) or len(embeddings) != len(texts):
            raise RuntimeError(f"Ollama returned a malformed embeddings response ({url})")
        # The response travels plain HTTP from a LAN host and lands in the
        # persistent vector cache — validate strictly (finite-numeric-only
        # vectors, one consistent bounded dimension) so a compromised or
        # spoofed server cannot poison the cache: NaN silently disables
        # cosine dedup, and unbounded dims are a disk/CPU DoS.
        dim = None
        for vec in embeddings:
            if (not isinstance(vec, list) or not vec or len(vec) > MAX_EMBED_DIM
                    or not all(isinstance(v, (int, float)) and not isinstance(v, bool)
                               and math.isfinite(v) for v in vec)):
                raise RuntimeError(f"Ollama returned an invalid embedding vector ({url})")
            if dim is None:
                dim = len(vec)
            elif len(vec) != dim:
                raise RuntimeError(f"Ollama returned inconsistent embedding dimensions ({url})")
        return embeddings

    def _split_by_weight(self, texts: list[str]) -> list[tuple[str, int, int]]:
        """Contiguous (url, start, end) chunks proportional to host weight."""
        total_w = sum(w for _, w in self.hosts)
        chunks = []
        start = 0
        for i, (url, w) in enumerate(self.hosts):
            if i == len(self.hosts) - 1:
                end = len(texts)
            else:
                end = start + max(1, round(len(texts) * w / total_w))
                end = min(end, len(texts))
            if start < end:
                chunks.append((url, start, end))
            start = end
        return chunks

    def embed(self, texts: list[str]) -> list[list[float]]:
        if not self.hosts:
            raise RuntimeError("Ollama pool has no live hosts")
        # Small batches: single request to the highest-weight host, walking
        # down the pool on failure.
        if len(self.hosts) == 1 or len(texts) < 4:
            last_exc: Exception | None = None
            for url, _ in self.hosts:
                try:
                    return self._embed_on(url, texts)
                except RuntimeError as exc:
                    last_exc = exc
                    logger.warning("Embed failed on %s; trying next host", url)
            raise RuntimeError(f"All Ollama hosts failed: {last_exc}")

        # Large batches: weighted parallel dispatch with per-chunk failover.
        from concurrent.futures import ThreadPoolExecutor
        results: list[list[list[float]] | None] = [None] * len(self.hosts)
        chunks = self._split_by_weight(texts)
        with ThreadPoolExecutor(max_workers=len(chunks)) as pool:
            futures = {pool.submit(self._embed_on, url, texts[s:e]): (i, url, s, e)
                       for i, (url, s, e) in enumerate(chunks)}
            failed: list[tuple[int, str, int, int]] = []
            for fut, (i, url, s, e) in futures.items():
                try:
                    results[i] = fut.result()
                except RuntimeError as exc:
                    logger.warning("Embed chunk failed on %s (%s); will retry elsewhere", url, exc)
                    failed.append((i, url, s, e))
        for i, dead_url, s, e in failed:
            self.hosts = [(u, w) for u, w in self.hosts if u != dead_url] or self.hosts
            retried = False
            for url, _ in self.hosts:
                if url == dead_url:
                    continue
                try:
                    results[i] = self._embed_on(url, texts[s:e])
                    retried = True
                    break
                except RuntimeError:
                    continue
            if not retried:
                raise RuntimeError("All Ollama hosts failed while retrying a chunk")
        out: list[list[float]] = []
        for i, (_, s, e) in enumerate(chunks):
            out.extend(results[i])
        # Cross-chunk consistency: two hosts serving different builds under
        # one model tag could return different dims; mixed dims make cosine
        # silently return 0.0 downstream. Refuse the whole batch instead.
        dims = {len(v) for v in out}
        if len(dims) > 1:
            raise RuntimeError(f"Ollama hosts returned mixed embedding dimensions: {sorted(dims)}")
        return out


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
