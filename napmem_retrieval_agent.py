#!/usr/bin/env python3
"""
NapMem Active Retrieval Agent

Implements active memory navigation tools for LLM agents, enabling tool-driven
probe queries across the multi-granularity memory pyramid instead of passive context dumping.

Tools provided:
  - search_memory_pyramid(query, layer): Active search across Profiles, Tracks, or Records.
  - semantic_search(query, top_k): Embedding cosine search over Layer 1 records.
  - inspect_provenance(record_id): Bi-directional resolution back to Layer 0 raw logs.
  - get_topic_track(topic_slug): Retrieves entire aggregated thematic track.
  - compute_context_budget_savings(): Demonstrates token cost savings vs passive RAG.
"""

import argparse
import json
import os
import stat
from typing import Any

from napmem_model import migrate_store

VALID_LAYERS = ("all", "profiles", "tracks", "records")

class NapMemRetrievalAgent:
    def __init__(self, pyramid_path: str = "napmem_pyramid.json"):
        self.pyramid_path = pyramid_path
        self.data = self._load_pyramid()

    def _load_pyramid(self) -> dict[str, Any]:
        from napmem_controls import apply_controls
        from napmem_model import build_derived
        if os.path.exists(self.pyramid_path):
            with open(self.pyramid_path, "r", encoding="utf-8") as f:
                data = migrate_store(json.load(f))
                apply_controls(data)
                build_derived(data)
                return data
        raise FileNotFoundError(f"Pyramid file {self.pyramid_path} not found. Please run memory_pyramid_distiller.py first.")

    @staticmethod
    def _bounded(payload, max_bytes=16384, max_tokens=2048):
        from napmem_search import bounded_response
        return bounded_response(payload, max_bytes=max_bytes, max_tokens=max_tokens)

    def query(self, query: str, *, scope: str | None = None, as_of: str | None = None,
              top_k: int = 5, mode: str = "hybrid", max_bytes: int = 16384,
              max_tokens: int | None = 2048, backend=None) -> dict[str, Any]:
        """Shared, scoped evidence contract. Defaults never contact a service."""
        from napmem_search import search
        result = search(self.data, query, scope=scope, as_of=as_of, top_k=top_k,
                        mode=mode, max_bytes=max_bytes, max_tokens=max_tokens,
                        backend=backend)
        selected = {record["id"] for record in result["matches"]}
        result["profiles"] = [profile for profile in self.data.get("user_profiles", [])
                              if profile["provenance_records"] and
                              set(profile["provenance_records"]) <= selected]
        groups = {}
        for record in result["matches"]:
            groups.setdefault((record["scope"], record["topic_slug"]), []).append(record)
        result["tracks"] = [
            {"scope": item_scope, "topic_slug": slug,
             "summary": "; ".join(record["text"] for record in members[:3]),
             "record_ids": [record["id"] for record in members]}
            for (item_scope, slug), members in groups.items()
        ]
        return self._bounded(result, max_bytes, max_tokens)

    def search_memory_pyramid(self, query: str, layer: str = "all", *,
                              scope: str | None = None, as_of: str | None = None,
                              top_k: int = 20, max_bytes: int = 16384,
                              max_tokens: int | None = 2048) -> dict[str, Any]:
        """Bounded legacy layer view; scope and valid time precede matching."""
        from napmem_search import eligible_records
        if layer not in VALID_LAYERS:
            raise ValueError(f"Unknown layer '{layer}'; expected one of {VALID_LAYERS}")
        if not isinstance(query, str) or not query.strip() or len(query) > 2048:
            raise ValueError("query must be a nonempty string of at most 2048 characters")
        if isinstance(top_k, bool) or not isinstance(top_k, int) or not 1 <= top_k <= 100:
            raise ValueError("top_k must be a positive integer no greater than 100")
        records = eligible_records(self.data, scope, as_of)
        eligible_ids = {r["id"] for r in records}
        lower = query.casefold()
        matches = {}
        if layer in ("profiles", "all"):
            matches["user_profiles"] = [
                p for p in self.data.get("user_profiles", [])
                if set(p["provenance_records"]) <= eligible_ids
                and (lower in p["trait"].casefold() or lower in p["category"].casefold())
            ]
        if layer in ("tracks", "all"):
            # Reassemble from eligible evidence; a cached current summary can
            # otherwise disclose a future or differently scoped assertion.
            groups = {}
            for record in records:
                groups.setdefault((record["scope"], record["topic_slug"]), []).append(record)
            tracks = []
            for (record_scope, slug), members in sorted(groups.items()):
                summary = "; ".join(r["text"] for r in members[:3])
                if lower in slug.casefold() or lower in summary.casefold():
                    tracks.append({"scope": record_scope, "topic_slug": slug,
                                   "title": slug.replace("-", " ").title(),
                                   "summary": summary, "record_ids": [r["id"] for r in members]})
            matches["topic_tracks"] = tracks
        if layer in ("records", "all"):
            matches["memory_records"] = [
                r for r in records if lower in r["text"].casefold() or lower in r["type"].casefold()
            ]
        omitted = sum(max(0, len(items) - top_k) for items in matches.values())
        matches = {key: items[:top_k] for key, items in matches.items()}
        return self._bounded({"query": query, "layer": layer, "scope": scope,
                              "as_of": as_of, "mode": "substring", "matches": matches,
                              "omitted_count": omitted, "truncated": omitted > 0,
                              "generation": self.data.get("generation", 0)}, max_bytes, max_tokens)

    def semantic_search(self, query: str, top_k: int = 5, *, scope: str | None = None,
                        as_of: str | None = None, max_bytes: int = 16384,
                        max_tokens: int | None = 2048) -> dict[str, Any]:
        """Explicit legacy embedding path; initialization remains an injectable seam."""
        from napmem_search import eligible_records
        from napmem_model import parse_time
        from datetime import UTC, datetime
        if isinstance(top_k, bool) or not isinstance(top_k, int) or not 1 <= top_k <= 100:
            raise ValueError("top_k must be a positive integer no greater than 100")
        if not isinstance(query, str) or not query.strip() or len(query) > 2048:
            raise ValueError("query must be a nonempty string of at most 2048 characters")
        at = parse_time(as_of).isoformat() if as_of is not None else datetime.now(UTC).isoformat()
        records = eligible_records(self.data, scope, at)
        try:
            from semantic_index import SemanticIndex
            index = SemanticIndex(self.pyramid_path)
            hits = index.search(query, records, top_k=top_k)
            result = {"query": query, "scope": scope, "as_of": at,
                      "mode": f"semantic:{index.backend.name}",
                      "matches": [{"score": h["score"], **h["record"]} for h in hits]}
        except (RuntimeError, OSError, ValueError, ImportError) as exc:
            fallback = self.search_memory_pyramid(query, "records", scope=scope, as_of=as_of,
                                                  top_k=top_k, max_bytes=max_bytes, max_tokens=max_tokens)
            result = {"query": query, "scope": scope, "mode": "substring-fallback",
                      "fallback_reason": type(exc).__name__,
                      "matches": fallback["matches"]["memory_records"]}
        return self._bounded(result, max_bytes, max_tokens)

    def inspect_provenance(self, record_id: str, *, scope: str | None = None,
                           as_of: str | None = None, max_bytes: int = 16384,
                           max_tokens: int | None = 2048) -> dict[str, Any]:
        """Resolve the selected occurrence's own wording, context and source."""
        from copy import deepcopy
        from napmem_model import normalize_record, visible
        if not isinstance(record_id, str) or not record_id or len(record_id) > 512:
            raise ValueError("record_id must be a nonempty string of at most 512 characters")
        record = next((r for r in self.data.get("memory_records", [])
                       if record_id == r["id"] or record_id in r.get("duplicates", [])), None)
        if record is None or record.get("instruction_bearing") or record.get("source_excluded"):
            return {"error": f"Record ID {record_id} not found."}
        selected = deepcopy(record)
        canonical_id = None
        if record_id != record["id"]:
            anchor = record.get("duplicate_anchors", {}).get(record_id)
            if anchor is None:
                return {"error": f"Record ID {record_id} not found."}
            selected = normalize_record({**deepcopy(anchor.get("assertion", {})),
                                         "id": record_id, "text": anchor.get("paraphrase_text", record["text"]),
                                         "type": record["type"], "salience": record["salience"],
                                         "source_anchor": deepcopy(anchor)})
            canonical_id = record["id"]
        check = deepcopy(selected)
        if as_of is None and check.get("status") == "superseded":
            check.update(status="active", valid_from=None, valid_to=None)
        if not visible(check, scope, as_of):
            return {"error": f"Record ID {record_id} not found in the requested scope or time."}
        anchor = selected["source_anchor"]
        session = next((s for s in self.data.get("raw_conversations", [])
                        if s["session_id"] == anchor.get("session_id")), None)
        result = {"record_id": record_id, "text": selected["text"], "type": selected["type"],
                  "salience": selected["salience"], "duplicates": [], "source_anchor": anchor,
                  "raw_session": session, "scope": selected.get("scope", "legacy"),
                  "memory_kind": selected.get("memory_kind"), "status": selected.get("status"),
                  "evidence": selected.get("evidence", {})}
        if canonical_id:
            result["canonical_id"] = canonical_id
        return self._bounded(result, max_bytes, max_tokens)

    def get_topic_track(self, topic_slug: str, *, scope: str | None = None,
                        as_of: str | None = None, top_k: int = 20,
                        max_bytes: int = 16384, max_tokens: int | None = 2048) -> dict[str, Any]:
        """Expand only eligible evidence for a topic, within explicit result budgets."""
        from napmem_search import eligible_records
        if not isinstance(topic_slug, str) or not topic_slug or len(topic_slug) > 256:
            raise ValueError("topic_slug must be a nonempty string of at most 256 characters")
        if isinstance(top_k, bool) or not isinstance(top_k, int) or not 1 <= top_k <= 100:
            raise ValueError("top_k must be a positive integer no greater than 100")
        records = [r for r in eligible_records(self.data, scope, as_of)
                   if r["topic_slug"] == topic_slug]
        if not records:
            return {"error": f"Topic slug '{topic_slug}' not found."}
        return self._bounded({"track": {"topic_slug": topic_slug, "scope": scope,
                                        "title": topic_slug.replace("-", " ").title()},
                              "records": records[:top_k],
                              "omitted_count": max(0, len(records) - top_k),
                              "truncated": len(records) > top_k}, max_bytes, max_tokens)

    def compute_context_budget_savings(self) -> dict[str, Any]:
        """
        Calculates token savings of using active NapMem retrieval vs dumping raw memory logs.

        The comparison only covers readable regular source files:
        counting every distilled record against a partial raw baseline would
        report distillation as *expanding* memory once source files are moved or
        deleted. Missing sessions are disclosed in the result.
        """
        raw_text_len = 0
        available_sessions = set()
        missing_sessions = []
        for session in self.data.get("raw_conversations", []):
            try:
                # A source can be replaced after ingestion. Open without
                # blocking so a FIFO cannot stall the MCP statistics tool,
                # then verify the opened object before reading any bytes.
                fd = os.open(session["file_path"], os.O_RDONLY | os.O_NONBLOCK)
                try:
                    if not stat.S_ISREG(os.fstat(fd).st_mode):
                        raise OSError("Source is not a regular file")
                    with os.fdopen(fd, "r", encoding="utf-8") as f:
                        fd = -1  # the file object owns and closes this descriptor
                        raw_text_len += len(f.read().split())
                finally:
                    if fd >= 0:
                        os.close(fd)
                available_sessions.add(session["session_id"])
            except (OSError, UnicodeDecodeError):
                missing_sessions.append(session["session_id"])

        comparable_records = [
            r for r in self.data.get("memory_records", [])
            if r["source_anchor"]["session_id"] in available_sessions
        ]

        # Estimated token counts (~0.75 words per token)
        raw_tokens = int(raw_text_len * 1.33)
        distilled_records_text = " ".join([r["text"] for r in comparable_records])
        distilled_tokens = int(len(distilled_records_text.split()) * 1.33)
        profiles_text = " ".join([p["trait"] for p in self.data.get("user_profiles", [])])
        profiles_tokens = int(len(profiles_text.split()) * 1.33)

        reduction_pct = ((raw_tokens - distilled_tokens) / max(raw_tokens, 1)) * 100

        return {
            "raw_memory_estimated_tokens": raw_tokens,
            "layer_1_distilled_tokens": distilled_tokens,
            "layer_3_profile_tokens": profiles_tokens,
            "token_compression_ratio": f"{raw_tokens / max(distilled_tokens, 1):.2f}x",
            "context_reduction_percent": f"{reduction_pct:.1f}%",
            "sessions_compared": sorted(available_sessions),
            "sessions_missing_raw_file": missing_sessions
        }

def main():
    parser = argparse.ArgumentParser(description="Active NapMem Memory Retrieval Agent Interface.")
    parser.add_argument("--pyramid", type=str, default="napmem_pyramid.json", help="Path to pyramid JSON store.")
    parser.add_argument("--query", type=str, help="Query string for active navigation.")
    parser.add_argument("--layer", type=str, default="all", choices=list(VALID_LAYERS), help="Pyramid layer.")
    parser.add_argument("--semantic", action="store_true",
                        help="Use embedding cosine search instead of substring matching.")
    parser.add_argument("--top-k", type=int, default=5, help="Result count for --semantic.")
    parser.add_argument("--provenance", type=str, help="Inspect provenance for a specific record ID.")
    parser.add_argument("--stats", action="store_true", help="Display token context budget savings stats.")
    args = parser.parse_args()

    if not (args.stats or args.query or args.provenance):
        parser.print_help()
        parser.exit(1)

    agent = NapMemRetrievalAgent(pyramid_path=args.pyramid)

    if args.stats:
        stats = agent.compute_context_budget_savings()
        print("=== Context Window Budget Savings ===")
        print(json.dumps(stats, indent=2))

    if args.query:
        if args.semantic:
            print(f"\n=== Semantic Search Results for '{args.query}' (top {args.top_k}) ===")
            results = agent.semantic_search(args.query, top_k=args.top_k)
        else:
            print(f"\n=== Active Search Results for '{args.query}' (Layer: {args.layer}) ===")
            results = agent.search_memory_pyramid(args.query, args.layer)
        print(json.dumps(results, indent=2))

    if args.provenance:
        print(f"\n=== Provenance Inspection for Record '{args.provenance}' ===")
        prov = agent.inspect_provenance(args.provenance)
        print(json.dumps(prov, indent=2))

if __name__ == "__main__":
    main()
