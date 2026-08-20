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
from typing import Any

VALID_LAYERS = ("all", "profiles", "tracks", "records")

class NapMemRetrievalAgent:
    def __init__(self, pyramid_path: str = "napmem_pyramid.json"):
        self.pyramid_path = pyramid_path
        self.data = self._load_pyramid()

    def _load_pyramid(self) -> dict[str, Any]:
        if os.path.exists(self.pyramid_path):
            with open(self.pyramid_path, "r", encoding="utf-8") as f:
                return json.load(f)
        raise FileNotFoundError(f"Pyramid file {self.pyramid_path} not found. Please run memory_pyramid_distiller.py first.")

    def search_memory_pyramid(self, query: str, layer: str = "all") -> dict[str, Any]:
        """
        Active memory search tool.
        layer can be 'profiles', 'tracks', 'records', or 'all'.

        Raises ValueError on an unknown layer rather than silently returning no
        matches — this is a tool surface for LLM agents, where a typo'd layer
        would otherwise masquerade as "no memory found".
        """
        if layer not in VALID_LAYERS:
            raise ValueError(f"Unknown layer '{layer}'; expected one of {VALID_LAYERS}")
        query_lower = query.lower()
        results = {"query": query, "layer": layer, "matches": {}}

        # Layer 3: Profiles
        if layer in ["profiles", "all"]:
            profile_matches = [
                p for p in self.data.get("user_profiles", [])
                if query_lower in p["trait"].lower() or query_lower in p["category"].lower()
            ]
            results["matches"]["user_profiles"] = profile_matches

        # Layer 2: Topic Tracks
        if layer in ["tracks", "all"]:
            track_matches = [
                t for t in self.data.get("topic_tracks", [])
                if query_lower in t["title"].lower() or query_lower in t["topic_slug"].lower() or query_lower in t["summary"].lower()
            ]
            results["matches"]["topic_tracks"] = track_matches

        # Layer 1: Atomic Memory Records
        if layer in ["records", "all"]:
            record_matches = [
                r for r in self.data.get("memory_records", [])
                if query_lower in r["text"].lower() or query_lower in r["type"].lower()
            ]
            results["matches"]["memory_records"] = record_matches

        return results

    def semantic_search(self, query: str, top_k: int = 5) -> dict[str, Any]:
        """
        Embedding cosine search over Layer 1 records via semantic_index.py.
        Falls back to substring search when no embedding backend is usable, and
        discloses which path answered in the result's `mode` field.
        """
        records = self.data.get("memory_records", [])
        try:
            from semantic_index import SemanticIndex  # lazy: optional feature
            index = SemanticIndex(self.pyramid_path)
            hits = index.search(query, records, top_k=top_k)
            return {
                "query": query,
                "mode": f"semantic:{index.backend.name}",
                "matches": [{"score": h["score"], **h["record"]} for h in hits],
            }
        except (RuntimeError, OSError) as exc:
            fallback = self.search_memory_pyramid(query, layer="records")
            return {
                "query": query,
                "mode": "substring-fallback",
                "fallback_reason": str(exc),
                "matches": fallback["matches"]["memory_records"][:top_k],
            }

    def inspect_provenance(self, record_id: str) -> dict[str, Any]:
        """
        Resolves an atomic record back to its Layer 0 source anchor and raw conversation metadata.

        Duplicate IDs (units folded into a canonical record at dedup time) resolve to
        their canonical record, with the duplicate's own anchor when it was recorded;
        the result then carries a `canonical_id` key.
        """
        record = next((r for r in self.data.get("memory_records", []) if r["id"] == record_id), None)
        canonical_id = None
        anchor = None
        if not record:
            for r in self.data.get("memory_records", []):
                if record_id in r.get("duplicates", []):
                    record = r
                    canonical_id = r["id"]
                    anchor = r.get("duplicate_anchors", {}).get(record_id)
                    break
        if not record:
            return {"error": f"Record ID {record_id} not found."}

        anchor = anchor or record["source_anchor"]
        raw_session = next((s for s in self.data.get("raw_conversations", []) if s["session_id"] == anchor["session_id"]), None)

        result = {
            "record_id": record_id,
            "text": record["text"],
            "type": record["type"],
            "salience": record["salience"],
            "duplicates": record.get("duplicates", []),
            "source_anchor": anchor,
            "raw_session": raw_session
        }
        if canonical_id:
            result["canonical_id"] = canonical_id
        return result

    def get_topic_track(self, topic_slug: str) -> dict[str, Any]:
        """
        Retrieves a full topic track with all associated atomic records.
        """
        track = next((t for t in self.data.get("topic_tracks", []) if t["topic_slug"] == topic_slug), None)
        if not track:
            return {"error": f"Topic slug '{topic_slug}' not found."}

        associated_records = [
            r for r in self.data.get("memory_records", [])
            if r["id"] in track["record_ids"]
        ]

        return {
            "track": track,
            "records": associated_records
        }

    def compute_context_budget_savings(self) -> dict[str, Any]:
        """
        Calculates token savings of using active NapMem retrieval vs dumping raw memory logs.

        The comparison only covers sessions whose raw file is still readable:
        counting every distilled record against a partial raw baseline would
        report distillation as *expanding* memory once source files are moved or
        deleted. Missing sessions are disclosed in the result.
        """
        raw_text_len = 0
        available_sessions = set()
        missing_sessions = []
        for session in self.data.get("raw_conversations", []):
            try:
                with open(session["file_path"], "r", encoding="utf-8") as f:
                    raw_text_len += len(f.read().split())
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
