#!/usr/bin/env python3
"""
Semantic Embedding Index for the NapMem Pyramid

Provides cosine-similarity retrieval and near-duplicate detection over Layer 1
memory records. Two embedding backends:

  - OllamaBackend: real embeddings from a local Ollama server
    (http://localhost:11434, model nomic-embed-text by default). Zero API
    cost, no cloud dependency. Selected automatically when the server responds.
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
import urllib.error
import urllib.request
from typing import Any

logger = logging.getLogger(__name__)

OLLAMA_URL = os.environ.get("NAPMEM_OLLAMA_URL", "http://localhost:11434")
OLLAMA_MODEL = os.environ.get("NAPMEM_OLLAMA_MODEL", "nomic-embed-text")
BACKEND_ENV = "NAPMEM_EMBED_BACKEND"  # "ollama" | "hashed" | unset (auto)

TOKEN_RE = re.compile(r"[a-z0-9]+")
HASHED_DIM = 512


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
    """Embeddings from a local Ollama server via its /api/embed endpoint."""

    name = "ollama"

    def __init__(self, base_url: str = OLLAMA_URL, model: str = OLLAMA_MODEL):
        self.base_url = base_url.rstrip("/")
        self.model = model

    @classmethod
    def probe(cls) -> "OllamaBackend | None":
        """Returns a backend if the Ollama server answers quickly, else None."""
        backend = cls()
        try:
            req = urllib.request.Request(f"{backend.base_url}/api/tags", method="GET")
            with urllib.request.urlopen(req, timeout=1.5) as resp:
                if resp.status == 200:
                    return backend
        except (urllib.error.URLError, OSError, TimeoutError) as exc:
            logger.debug("Ollama probe failed: %s", exc)
        return None

    def embed(self, texts: list[str]) -> list[list[float]]:
        payload = json.dumps({"model": self.model, "input": texts}).encode("utf-8")
        req = urllib.request.Request(
            f"{self.base_url}/api/embed", data=payload,
            headers={"Content-Type": "application/json"}, method="POST",
        )
        try:
            with urllib.request.urlopen(req, timeout=120) as resp:
                body = json.load(resp)
        except (urllib.error.URLError, OSError, TimeoutError) as exc:
            raise RuntimeError(f"Ollama embedding request failed: {exc}") from exc
        embeddings = body.get("embeddings")
        if not isinstance(embeddings, list) or len(embeddings) != len(texts):
            raise RuntimeError("Ollama returned a malformed embeddings response")
        return embeddings


def select_backend():
    forced = os.environ.get(BACKEND_ENV, "").lower()
    if forced == "hashed":
        return HashedTfBackend()
    if forced == "ollama":
        backend = OllamaBackend.probe()
        if backend is None:
            raise RuntimeError(
                f"{BACKEND_ENV}=ollama but no Ollama server at {OLLAMA_URL}"
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
            with open(self.index_path, "r", encoding="utf-8") as f:
                cache = json.load(f)
            # A backend/model switch invalidates every cached vector.
            if cache.get("model") == self.backend.model:
                return cache
        return {"model": self.backend.model, "vectors": {}}

    def save(self):
        tmp_path = f"{self.index_path}.tmp"
        with open(tmp_path, "w", encoding="utf-8") as f:
            json.dump(self._cache, f)
        os.replace(tmp_path, self.index_path)

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
        """Id of the most similar record at or above threshold, else None."""
        results = self.search(text, records, top_k=1)
        if results and results[0]["score"] >= threshold:
            return results[0]["record"]["id"]
        return None


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
