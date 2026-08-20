#!/usr/bin/env python3
"""
Memory Pyramid Distiller (NapMem + Document Distiller Integration)

Transforms raw LLM memory files (e.g. session transcripts, MEMORY.md, agent logs)
into a 4-layer NapMem multi-granularity memory pyramid:
  Layer 0: Raw Conversations & Source Anchors
  Layer 1: Memory Records (Atomic units distilled using document-distiller taxonomy)
  Layer 2: Topic Tracks (Aggregated thematic clusters)
  Layer 3: User & System Profiles (High-level traits, constraints, and goals)

Supports incremental distillation: re-ingesting an existing session_id replaces
that session's Layer 1 records (stale units are removed; canonical records that
another session still substantiates are re-anchored to that session) and then
rebuilds Layers 2-3 from the surviving records.
"""

import argparse
import json
import os
import re
import sys
from datetime import datetime, timezone
from typing import Any

UNIT_TYPES = ["concept", "fact", "actionable", "question", "problem", "statement", "quote", "idea"]
SALIENCE_LEVELS = ["high", "medium", "low"]
PROFILE_CONFIDENCE = 0.95

CHECKBOX_RE = re.compile(r"^-\s*\[[ xX]\]\s*")
BULLET_RE = re.compile(r"^-\s+")


def _utcnow() -> str:
    return datetime.now(timezone.utc).isoformat()


def _slugify(heading: str) -> str:
    return heading.lower().replace(" ", "-")

class MemoryPyramidDistiller:
    def __init__(self, pyramid_path: str = "napmem_pyramid.json"):
        self.pyramid_path = pyramid_path
        self.data = self._load_pyramid()

    def _load_pyramid(self) -> dict[str, Any]:
        if os.path.exists(self.pyramid_path):
            with open(self.pyramid_path, "r", encoding="utf-8") as f:
                return json.load(f)
        return {
            "version": "1.0.0",
            "updated_at": _utcnow(),
            "user_profiles": [],
            "topic_tracks": [],
            "memory_records": [],
            "raw_conversations": []
        }

    def save(self):
        self.data["updated_at"] = _utcnow()
        # Atomic write: the consolidator daemon rewrites this store repeatedly;
        # a crash mid-write must not corrupt the only copy.
        tmp_path = f"{self.pyramid_path}.tmp"
        with open(tmp_path, "w", encoding="utf-8") as f:
            json.dump(self.data, f, indent=2)
        os.replace(tmp_path, self.pyramid_path)

    def extract_atomic_units(self, content: str, session_id: str, file_path: str) -> list[dict[str, Any]]:
        """
        Parses raw content into atomic units following document-distiller taxonomy.
        In production, this integrates with LLM zero-fabrication extraction prompts.
        Here we implement a structured heuristic rule engine for demonstration.
        """
        units = []
        lines = content.splitlines()
        current_heading = "General"
        
        for idx, line in enumerate(lines, 1):
            line_str = line.strip()
            if not line_str:
                continue

            if line_str.startswith("#"):
                current_heading = line_str.lstrip("#").strip()
                continue

            # Determine unit type and salience using tight heuristics
            unit_type = "statement"
            salience = "medium"
            text = line_str

            if CHECKBOX_RE.match(line_str) or "should" in line_str.lower() or "must" in line_str.lower():
                unit_type = "actionable"
                salience = "high"
                text = CHECKBOX_RE.sub("", line_str)
            elif "?" in line_str:
                unit_type = "question"
                salience = "high"
            elif line_str.startswith((">", '"')):
                unit_type = "quote"
                salience = "medium"
                text = line_str.lstrip(">").strip().strip('"')
            elif any(kw in line_str.lower() for kw in ["error", "issue", "problem", "bug", "fail", "bottleneck"]):
                unit_type = "problem"
                salience = "high"
            elif any(kw in line_str.lower() for kw in ["prefer", "always", "never", "uses", "config", "framework", "architecture"]):
                unit_type = "fact"
                salience = "high"
            elif any(kw in line_str.lower() for kw in ["pattern", "concept", "model", "algorithm", "paradigm"]):
                unit_type = "concept"
                salience = "high"
            elif any(kw in line_str.lower() for kw in ["maybe", "could", "propose", "idea", "hypothesis"]):
                unit_type = "idea"
                salience = "low"

            # Atomic unit text should not carry markdown list syntax: checkbox and
            # quote branches strip their own markers above; strip the plain
            # bullet prefix for every remaining bulleted line too.
            text = BULLET_RE.sub("", text)

            # Derived topic slug
            topic_slug = _slugify(current_heading)

            unit_id = f"rec_{session_id}_{len(units)+1:03d}"
            record = {
                "id": unit_id,
                "type": unit_type,
                "text": text,
                "salience": salience,
                "canonical": unit_id,
                "duplicates": [],
                "topic_slug": topic_slug,
                "source_anchor": {
                    "session_id": session_id,
                    "file_path": file_path,
                    "heading": current_heading,
                    "line_range": f"L{idx}"
                },
                "created_at": _utcnow()
            }
            units.append(record)

        return units

    def deduplicate_and_merge(self, new_records: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """
        Deduplicates newly extracted atomic units against existing Layer 1 memory records.
        Folds matching units into canonical records; the folded unit's source anchor is
        preserved in the canonical's `duplicate_anchors` map so duplicate IDs stay
        resolvable and removable per session.
        """
        existing_texts = {r["text"].lower().strip(): r for r in self.data["memory_records"]}
        merged_records = []

        for rec in new_records:
            clean_text = rec["text"].lower().strip()
            if clean_text in existing_texts:
                canonical_rec = existing_texts[clean_text]
                if rec["id"] != canonical_rec["id"] and rec["id"] not in canonical_rec["duplicates"]:
                    canonical_rec["duplicates"].append(rec["id"])
                    canonical_rec.setdefault("duplicate_anchors", {})[rec["id"]] = rec["source_anchor"]
            else:
                self.data["memory_records"].append(rec)
                existing_texts[clean_text] = rec
                merged_records.append(rec)

        return merged_records

    def _reconcile_session_records(self, session_id: str, new_records: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """
        Reconciles a session's previously distilled Layer 1 records with a fresh
        extraction ahead of re-ingestion, and returns the new units still to merge.

        Record IDs are stable across re-ingestion: a canonical anchored in this
        session whose text is re-asserted keeps its ID and gets its anchor
        refreshed (the matching new unit is consumed). A canonical whose text is
        gone survives only if a duplicate from another session still substantiates
        it; that duplicate is promoted to canonical (same text by construction of
        the exact-match dedup). Duplicate references from the re-ingested session
        are stripped (re-folded on merge if re-asserted). Legacy duplicate IDs
        with no recorded anchor are unresolvable dangling references and are
        dropped wherever found.
        """
        new_by_text: dict[str, dict[str, Any]] = {}
        for unit in new_records:
            new_by_text.setdefault(unit["text"].lower().strip(), unit)
        consumed_ids = set()

        kept: list[dict[str, Any]] = []
        for rec in self.data["memory_records"]:
            anchors = rec.get("duplicate_anchors", {})
            foreign = [
                d for d in rec.get("duplicates", [])
                if anchors.get(d, {}).get("session_id") not in (session_id, None)
            ]
            if rec["source_anchor"]["session_id"] != session_id:
                if len(foreign) != len(rec.get("duplicates", [])):
                    rec["duplicates"] = foreign
                    rec["duplicate_anchors"] = {d: a for d, a in anchors.items() if d in foreign}
                kept.append(rec)
                continue
            match = new_by_text.get(rec["text"].lower().strip())
            if match is not None and match["id"] not in consumed_ids:
                rec["source_anchor"] = match["source_anchor"]
                rec["duplicates"] = foreign
                rec["duplicate_anchors"] = {d: anchors[d] for d in foreign}
                consumed_ids.add(match["id"])
                kept.append(rec)
                continue
            if not foreign:
                continue
            promoted_id = foreign[0]
            rec["id"] = promoted_id
            rec["canonical"] = promoted_id
            rec["source_anchor"] = anchors[promoted_id]
            # The record's topic must follow its new anchor, not the removed
            # session's heading.
            rec["topic_slug"] = _slugify(anchors[promoted_id].get("heading", "General"))
            rec["duplicates"] = foreign[1:]
            rec["duplicate_anchors"] = {d: anchors[d] for d in foreign[1:]}
            kept.append(rec)
        self.data["memory_records"] = kept

        # Re-issue IDs for the units still to merge: kept/promoted records retain
        # IDs from earlier generations, so a fresh rec_<session>_NNN numbered from
        # 1 can collide with a surviving record (e.g. a line inserted above a kept
        # line, or re-ingesting a session whose duplicate was promoted). Number
        # strictly after the session's highest surviving suffix.
        remaining = [u for u in new_records if u["id"] not in consumed_ids]
        next_n = self._next_unit_number(session_id)
        for offset, unit in enumerate(remaining):
            unit["id"] = f"rec_{session_id}_{next_n + offset:03d}"
            unit["canonical"] = unit["id"]
        return remaining

    def _next_unit_number(self, session_id: str) -> int:
        """Returns the next free rec_<session>_NNN suffix, scanning canonical and
        duplicate IDs alike so no surviving reference can collide."""
        prefix = f"rec_{session_id}_"
        max_n = 0
        for rec in self.data["memory_records"]:
            for rid in [rec["id"], *rec.get("duplicates", [])]:
                if rid.startswith(prefix) and rid[len(prefix):].isdigit():
                    max_n = max(max_n, int(rid[len(prefix):]))
        return max_n + 1

    def rebuild_higher_layers(self):
        """
        Synthesizes Layer 2 (Topic Tracks) and Layer 3 (User Profiles) from Layer 1 records.
        """
        # Group by topic_slug for Layer 2
        topic_groups: dict[str, list[dict[str, Any]]] = {}
        for rec in self.data["memory_records"]:
            slug = rec.get("topic_slug", "general")
            topic_groups.setdefault(slug, []).append(rec)

        self.data["topic_tracks"] = []
        for idx, (slug, recs) in enumerate(topic_groups.items(), 1):
            high_salience_texts = [r["text"] for r in recs if r["salience"] == "high"]
            summary = "; ".join(high_salience_texts[:3]) if high_salience_texts else f"{len(recs)} records under {slug}."
            
            track = {
                "track_id": f"track_{idx:02d}",
                "topic_slug": slug,
                "title": slug.replace("-", " ").title(),
                "summary": summary,
                "record_ids": [r["id"] for r in recs],
                "last_updated": _utcnow()
            }
            self.data["topic_tracks"].append(track)

        # Synthesize Layer 3 User & System Profiles
        fact_records = [r for r in self.data["memory_records"] if r["type"] in ["fact", "actionable"] and r["salience"] == "high"]
        self.data["user_profiles"] = []
        for idx, rec in enumerate(fact_records, 1):
            # Heuristic stand-in emits only a subset of the schema's category enum
            # (preference/constraint/workflow); "identity" and "goal" are reserved
            # for the LLM-based production extractor.
            category = "preference" if "prefer" in rec["text"].lower() else "constraint" if "never" in rec["text"].lower() or "must" in rec["text"].lower() else "workflow"
            profile = {
                "id": f"prof_{idx:02d}",
                "category": category,
                "trait": rec["text"],
                "confidence": PROFILE_CONFIDENCE,
                "provenance_records": [rec["id"]] + rec.get("duplicates", [])
            }
            self.data["user_profiles"].append(profile)

    def ingest_session(self, session_id: str, title: str, file_path: str, content: str):
        """
        Ingests a raw session log into Layer 0 and triggers distillation.
        """
        # Register Layer 0 raw conversation
        raw_entry = {
            "session_id": session_id,
            "title": title,
            "timestamp": _utcnow(),
            "file_path": file_path
        }
        # Re-ingest semantics: replace the Layer 0 entry and reconcile the
        # session's previously distilled Layer 1 records against the fresh
        # extraction — re-asserted text keeps its stable record ID, stale text is
        # removed (or its canonical handed to another session's duplicate), and
        # only genuinely new units flow into the merge. Without this, re-issued
        # rec_<session>_NNN IDs collide with the stale generation.
        self.data["raw_conversations"] = [s for s in self.data["raw_conversations"] if s["session_id"] != session_id]
        self.data["raw_conversations"].append(raw_entry)

        # Phase 1 & 2: Extract Atomic Units
        new_records = self.extract_atomic_units(content, session_id, file_path)

        # Phase 3: Reconcile prior generation, then deduplicate the remainder
        remaining_records = self._reconcile_session_records(session_id, new_records)
        self.deduplicate_and_merge(remaining_records)

        # Phase 4: Rebuild Pyramid Layers 2 and 3
        self.rebuild_higher_layers()

        self.save()
        return len(new_records)

    def render_markdown_summary(self) -> str:
        """
        Generates a human-readable markdown reference representation of the NapMem Pyramid.
        """
        md = ["# NapMem Multi-Granularity Memory Pyramid\n"]
        md.append(f"- **Updated**: {self.data['updated_at']}")
        md.append(f"- **Layer 0 Raw Sessions**: {len(self.data['raw_conversations'])}")
        md.append(f"- **Layer 1 Atomic Records**: {len(self.data['memory_records'])}")
        md.append(f"- **Layer 2 Topic Tracks**: {len(self.data['topic_tracks'])}")
        md.append(f"- **Layer 3 User Profiles**: {len(self.data['user_profiles'])}\n")

        md.append("## Layer 3: User & System Profiles")
        for prof in self.data["user_profiles"]:
            md.append(f"- **[{prof['category'].upper()}]** {prof['trait']} (Provenance: {', '.join(prof['provenance_records'])})")

        md.append("\n## Layer 2: Topic Tracks")
        for track in self.data["topic_tracks"]:
            md.append(f"### {track['title']} (`{track['topic_slug']}`)")
            md.append(f"{track['summary']}")
            md.append(f"*Contains {len(track['record_ids'])} atomic records*\n")

        md.append("## Layer 1: Memory Records (Sample High Salience)")
        for rec in self.data["memory_records"]:
            if rec["salience"] == "high":
                anchor = rec["source_anchor"]
                md.append(f"- **[{rec['type'].upper()}]** {rec['text']} — *{anchor['file_path']} ({anchor['line_range']})*")

        return "\n".join(md)

def main():
    parser = argparse.ArgumentParser(description="Distill raw LLM memory into NapMem Pyramid.")
    parser.add_argument("--input", type=str, help="Path to raw memory file or session log.")
    parser.add_argument("--session-id", type=str, default=None,
                        help="Session ID. Defaults to sess_<input-basename>; re-using a "
                             "session ID replaces that session's records.")
    parser.add_argument("--title", type=str, default="Session Log", help="Session Title.")
    parser.add_argument("--pyramid", type=str, default="napmem_pyramid.json", help="Path to pyramid JSON store.")
    args = parser.parse_args()

    distiller = MemoryPyramidDistiller(pyramid_path=args.pyramid)
    if args.input:
        if not os.path.exists(args.input):
            print(f"Error: input file not found: {args.input}", file=sys.stderr)
            sys.exit(1)
        with open(args.input, "r", encoding="utf-8") as f:
            content = f.read()
        # Derive the default session ID from the input file (mirroring the
        # consolidator): a fixed default would make two runs on DIFFERENT files
        # silently replace each other's records via re-ingest semantics.
        session_id = args.session_id or f"sess_{os.path.splitext(os.path.basename(args.input))[0]}"
        num_extracted = distiller.ingest_session(session_id, args.title, args.input, content)
        print(f"Successfully distilled {num_extracted} atomic units from {args.input} into {args.pyramid}")
        print("\n" + distiller.render_markdown_summary())
    else:
        print("No input provided. Rendering current pyramid:")
        print(distiller.render_markdown_summary())

if __name__ == "__main__":
    main()
