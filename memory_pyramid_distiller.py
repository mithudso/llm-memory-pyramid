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
import copy
import hashlib
import json
import os
import re
import sys
from collections import deque
from datetime import UTC, datetime
from typing import Any

from napmem_model import (
    CONTEXT_FIELDS, apply_supersession, build_derived, migrate_store, normalize_record,
)

UNIT_TYPES = ["concept", "fact", "actionable", "question", "problem", "statement", "quote", "idea"]
SALIENCE_LEVELS = ["high", "medium", "low"]

CHECKBOX_RE = re.compile(r"^-\s*\[[ xX]\]\s*")
BULLET_RE = re.compile(r"^-\s+")


def _utcnow() -> str:
    return datetime.now(UTC).isoformat()


def _slugify(heading: str) -> str:
    return heading.lower().replace(" ", "-")


def _assertion_key(record):
    """Never fold a claim across scope, subject or explicit validity boundaries."""
    return tuple(record.get(field) for field in
                 ("scope", "subject", "memory_kind", "valid_from", "valid_to", "status"))


def _text_identity(record):
    return (_assertion_key(record), record["text"].lower().strip())

class MemoryPyramidDistiller:
    def __init__(self, pyramid_path: str = "napmem_pyramid.json",
                 semantic_dedup: bool = False, semantic_threshold: float = 0.92):
        self.pyramid_path = pyramid_path
        self.data = self._load_pyramid()
        # Semantic dedup is opt-in: it folds near-duplicate paraphrases into
        # canonicals using the embedding index (see semantic_index.py). Off by
        # default so the exact-text pipeline stays deterministic.
        self.semantic_dedup = semantic_dedup
        self.semantic_threshold = semantic_threshold
        self._semantic_index = None

    def _get_semantic_index(self):
        if self._semantic_index is None and self.semantic_dedup:
            from semantic_index import SemanticIndex  # lazy: optional feature
            self._semantic_index = SemanticIndex(self.pyramid_path)
        return self._semantic_index

    def _load_pyramid(self) -> dict[str, Any]:
        from napmem_controls import apply_controls
        if os.path.exists(self.pyramid_path):
            with open(self.pyramid_path, "r", encoding="utf-8") as f:
                data = migrate_store(json.load(f))
                apply_controls(data)
                build_derived(data)
                return data
        return migrate_store({
            "version": "1.0.0",
            "updated_at": _utcnow(),
            "user_profiles": [],
            "topic_tracks": [],
            "memory_records": [],
            "raw_conversations": []
        })

    def save(self):
        previous_generation = self.data.get("generation", 0)
        self.data["generation"] = previous_generation + 1
        self.data["updated_at"] = _utcnow()
        # Atomic + durable write: per-PID tmp so a concurrent CLI run cannot
        # interleave into the daemon's tmp file (whichever replace runs last
        # wins wholesale, never a corrupt mix); fsync before replace so a
        # power loss cannot make the rename durable ahead of the data.
        tmp_path = f"{self.pyramid_path}.{os.getpid()}.tmp"
        try:
            with open(tmp_path, "w", encoding="utf-8") as f:
                json.dump(self.data, f, indent=2)
                f.flush()
                os.fsync(f.fileno())
            os.replace(tmp_path, self.pyramid_path)
        except OSError:
            self.data["generation"] = previous_generation
            try:
                os.unlink(tmp_path)
            except OSError:
                pass
            raise

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
        existing_texts = {_text_identity(r): r for r in self.data["memory_records"]}
        merged_records = []

        def fold(rec, canonical_rec):
            if rec["id"] != canonical_rec["id"] and rec["id"] not in canonical_rec["duplicates"]:
                canonical_rec["duplicates"].append(rec["id"])
                anchor = dict(rec["source_anchor"])
                anchor["assertion"] = {
                    field: copy.deepcopy(rec[field]) for field in
                    (*CONTEXT_FIELDS, "created_at") if field in rec
                }
                if rec["text"] != canonical_rec["text"]:
                    anchor["paraphrase_text"] = rec["text"]
                canonical_rec.setdefault("duplicate_anchors", {})[rec["id"]] = anchor

        # Pass 1: exact-text folds; collect the misses for a single batched
        # semantic pass (one embed round-trip per merge, not per record).
        exact_misses: list[dict[str, Any]] = []
        for rec in new_records:
            canonical_rec = existing_texts.get(_text_identity(rec))
            if canonical_rec is not None:
                fold(rec, canonical_rec)
            else:
                exact_misses.append(rec)

        # Pass 2: semantic near-duplicate folds against the EXISTING store.
        # The promotion machinery requires identical text between canonical
        # and duplicates, so semantic folds keep the CANONICAL's text and
        # record the paraphrase in the duplicate anchor. Best-effort: any
        # index failure (backend outage, cache-write race) degrades to
        # exact-only dedup for this merge instead of aborting the ingest.
        near_ids: list[str | None] = [None] * len(exact_misses)
        if self.semantic_dedup and exact_misses:
            try:
                index = self._get_semantic_index()
                if index is not None:
                    groups = {}
                    for pos, rec in enumerate(exact_misses):
                        # Similarity alone cannot establish equivalence between
                        # preferences, constraints or decisions with different values.
                        signature = None
                        if rec.get("memory_kind") in ("preference", "constraint", "decision", "goal"):
                            signature = tuple(re.findall(r"\w+", rec["text"].casefold()))
                        groups.setdefault((_assertion_key(rec), signature), []).append(pos)
                    for (key, signature), positions in groups.items():
                        candidates = [r for r in self.data["memory_records"]
                                      if _assertion_key(r) == key and
                                      (signature is None or tuple(re.findall(
                                          r"\w+", r["text"].casefold())) == signature)]
                        found = index.nearest_many(
                            [exact_misses[p]["text"] for p in positions],
                            candidates, self.semantic_threshold)
                        for pos, found_id in zip(positions, found):
                            near_ids[pos] = found_id
            except (ImportError, RuntimeError, OSError, ValueError) as exc:
                import logging
                logging.getLogger(__name__).warning(
                    "Semantic dedup unavailable (%s); exact-only for this merge",
                    type(exc).__name__)

        by_id = {r["id"]: r for r in self.data["memory_records"]}
        for rec, near_id in zip(exact_misses, near_ids):
            clean_text = _text_identity(rec)
            canonical_rec = existing_texts.get(clean_text) or by_id.get(near_id or "")
            if canonical_rec is not None:
                fold(rec, canonical_rec)
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
        it; that duplicate is promoted to canonical, adopting its own wording
        (the anchor's `paraphrase_text`, recorded at fold time for semantic and
        case-variant folds) so record text always matches text the anchoring
        file actually contained. Duplicate references from the re-ingested
        session are stripped, and a re-asserted unit reclaims its previous
        duplicate ID on merge so external references survive no-op re-ingests.
        Legacy duplicate IDs with no recorded anchor are unresolvable dangling
        references and are dropped wherever found.
        """
        new_by_text: dict[str, dict[str, Any]] = {}
        for unit in new_records:
            new_by_text.setdefault(unit["text"].lower().strip(), unit)
        consumed_ids = set()
        # Same-session duplicate IDs stripped from ANY session's canonical:
        # if the re-ingested content re-asserts that text, the unit must
        # reclaim its previous duplicate ID (it will re-fold on merge) instead
        # of being renumbered — external provenance references stay valid
        # across a no-op re-ingest.
        # Keep one ordered slot per occurrence, not just one ID per text.
        reclaimable: dict[str, deque] = {}

        kept: list[dict[str, Any]] = []
        referenced = {rid for record in self.data["memory_records"]
                      for rid in record.get("supersedes", [])}
        for correction in self.data.get("controls", {}).get("corrections", {}).values():
            referenced.update(correction.get("original_ids", []))
        for rec in self.data["memory_records"]:
            anchors = rec.get("duplicate_anchors", {})
            for duplicate_id in rec.get("duplicates", []):
                anchor = anchors.get(duplicate_id, {})
                if anchor.get("session_id") == session_id:
                    duplicate_text = anchor.get("paraphrase_text", rec["text"])
                    reclaimable.setdefault(duplicate_text.lower().strip(), deque()).append(
                        (duplicate_id, copy.deepcopy(anchor.get("assertion", {}))))
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
                old_text = rec["text"]
                kept_anchors = {d: dict(anchors[d]) for d in foreign}
                if match["text"] != old_text:
                    for anchor in kept_anchors.values():
                        anchor.setdefault("paraphrase_text", old_text)
                # Stable identity does not freeze extracted metadata. A heading
                # move, classification change, or case-only edit must reach the
                # derived layers and remain faithful to the current source.
                for field in ("text", "type", "salience"):
                    rec[field] = match[field]
                rec["topic_slug"] = match.get(
                    "topic_slug", _slugify(match["source_anchor"].get("heading", "General")))
                rec["source_anchor"] = match["source_anchor"]
                for field in CONTEXT_FIELDS:
                    if field == "observed_at" and rec.get(field) is not None:
                        continue
                    if (field in ("subject", "valid_from", "valid_to", "status", "supersedes",
                                  "review_status", "authority", "pinned", "last_verified_at")
                            and field not in match.get("_context_updates", [])):
                        continue
                    if field in match:
                        rec[field] = copy.deepcopy(match[field])
                rec["duplicates"] = foreign
                rec["duplicate_anchors"] = kept_anchors
                consumed_ids.add(match["id"])
                kept.append(rec)
                continue
            if not foreign:
                # Explicitly superseded evidence remains historical even if
                # its original mutable source is later edited or removed.
                if rec["id"] in referenced and rec.get("status") == "superseded":
                    kept.append(rec)
                continue
            promoted_id = foreign[0]
            old_text = rec["text"]
            promoted_anchor = dict(anchors[promoted_id])
            promoted_context = promoted_anchor.pop("assertion", {})
            for field in (*CONTEXT_FIELDS, "created_at"):
                if field in promoted_context:
                    rec[field] = copy.deepcopy(promoted_context[field])
            rec["id"] = promoted_id
            rec["canonical"] = promoted_id
            # Provenance invariant: a record's text must be text its anchor's
            # file actually contained. A duplicate folded SEMANTICALLY carries
            # its own wording in the anchor's `paraphrase_text`; on promotion
            # that wording becomes the record text (and the key is dropped).
            # Exact-text duplicates that remain under the new canonical then
            # get `paraphrase_text` = the old canonical text, since their
            # files contained THAT wording, not the promoted one.
            if "paraphrase_text" in promoted_anchor:
                rec["text"] = promoted_anchor.pop("paraphrase_text")
            rec["source_anchor"] = promoted_anchor
            # The record's topic must follow its new anchor, not the removed
            # session's heading.
            rec["topic_slug"] = _slugify(promoted_anchor.get("heading", "General"))
            rec["duplicates"] = foreign[1:]
            remaining_anchors = {}
            for d in foreign[1:]:
                a = dict(anchors[d])
                if rec["text"] != old_text and "paraphrase_text" not in a:
                    a["paraphrase_text"] = old_text
                remaining_anchors[d] = a
            rec["duplicate_anchors"] = remaining_anchors
            kept.append(rec)
        self.data["memory_records"] = kept

        # Re-issue IDs for the units still to merge: kept/promoted records retain
        # IDs from earlier generations, so a fresh rec_<session>_NNN numbered from
        # 1 can collide with a surviving record (e.g. a line inserted above a kept
        # line, or re-ingesting a session whose duplicate was promoted). Number
        # strictly after the session's highest surviving suffix.
        remaining = [u for u in new_records if u["id"] not in consumed_ids]
        # Reclaim first, then number fresh units past BOTH the surviving and
        # the just-reclaimed suffixes so the two ranges cannot collide.
        fresh: list[dict[str, Any]] = []
        max_reclaimed = 0
        prefix = f"rec_{session_id}_"
        for unit in remaining:
            prior_ids = reclaimable.get(unit["text"].lower().strip())
            prior = prior_ids.popleft() if prior_ids else None
            if prior is not None:
                reclaimed, prior_context = prior
                unit["id"] = reclaimed
                unit["canonical"] = reclaimed
                for field in ("observed_at", "created_at"):
                    if field in prior_context:
                        unit[field] = prior_context[field]
                if reclaimed.startswith(prefix) and reclaimed[len(prefix):].isdigit():
                    max_reclaimed = max(max_reclaimed, int(reclaimed[len(prefix):]))
            else:
                fresh.append(unit)
        next_n = max(self._next_unit_number(session_id), max_reclaimed + 1)
        for offset, unit in enumerate(fresh):
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
        """Rebuild only supported, scoped and current derived assertions."""
        apply_supersession(self.data)
        build_derived(self.data)

    def ingest_session(self, session_id: str, title: str, file_path: str, content: str,
                       *, scope: str | None = None, metadata: dict | None = None):
        """
        Ingests a raw session log into Layer 0 and triggers distillation using
        the built-in heuristic extractor.
        """
        new_records = self.extract_atomic_units(content, session_id, file_path)
        return self.ingest_session_records(session_id, title, file_path, new_records,
                                           scope=scope, metadata=metadata)

    def ingest_session_records(self, session_id: str, title: str, file_path: str,
                               new_records: list[dict[str, Any]], *,
                               scope: str | None = None,
                               metadata: dict | None = None) -> int:
        """
        Ingests pre-extracted Layer 1 records for a session (e.g. from the LLM
        extractor in llm_extractor.py) and runs the reconcile -> dedup ->
        rebuild -> save pipeline. Records must already carry
        rec_<session_id>_NNN ids and complete source anchors.
        """
        from napmem_controls import apply_controls, filter_incoming
        apply_controls(self.data)
        prior_source = next((s for s in self.data["raw_conversations"]
                             if s["session_id"] == session_id), {})
        source_scopes = self.data.setdefault("source_scopes", {})
        if not isinstance(source_scopes, dict):
            raise ValueError("source_scopes must be an object")
        source_key = hashlib.sha256(session_id.encode("utf-8")).hexdigest()
        if (scope is None and "scope" not in (metadata or {})
                and not any("scope" in record for record in new_records)):
            scope = prior_source.get("scope") or source_scopes.get(source_key)
        normalized = []
        for record in new_records:
            item = normalize_record(record, scope=scope, metadata=metadata)
            provided = set(record).intersection(CONTEXT_FIELDS)
            provided.update(set(metadata or {}).intersection(CONTEXT_FIELDS))
            if scope is not None:
                provided.add("scope")
            item["_context_updates"] = sorted(provided)
            normalized.append(item)
        new_records = filter_incoming(self.data, normalized)
        resolved_scopes = {record["scope"] for record in normalized}
        resolved_scope = (next(iter(resolved_scopes)) if len(resolved_scopes) == 1
                          else scope or (metadata or {}).get("scope", "legacy"))
        source_scopes[source_key] = resolved_scope
        # Register Layer 0 raw conversation
        raw_entry = {
            "session_id": session_id,
            "title": title,
            "timestamp": _utcnow(),
            "file_path": file_path,
            "scope": resolved_scope,
        }
        # Re-ingest semantics: replace the Layer 0 entry and reconcile the
        # session's previously distilled Layer 1 records against the fresh
        # extraction — re-asserted text keeps its stable record ID, stale text is
        # removed (or its canonical handed to another session's duplicate), and
        # only genuinely new units flow into the merge. Without this, re-issued
        # rec_<session>_NNN IDs collide with the stale generation.
        self.data["raw_conversations"] = [s for s in self.data["raw_conversations"] if s["session_id"] != session_id]
        self.data["raw_conversations"].append(raw_entry)

        # Phase 3: Reconcile prior generation, then deduplicate the remainder
        remaining_records = self._reconcile_session_records(session_id, new_records)
        for record in remaining_records:
            record.pop("_context_updates", None)
        self.deduplicate_and_merge(remaining_records)
        apply_controls(self.data)

        # Phase 4: Rebuild Pyramid Layers 2 and 3
        self.rebuild_higher_layers()

        self.save()
        return len(new_records)

    def control(self, action: str, *, record_id: str | None = None, value=None,
                source: str | None = None, at: str | None = None, dry_run: bool = False,
                expected_generation: int | None = None,
                preview_token: str | None = None) -> dict[str, Any]:
        """Apply an operator action; retrieval MCP never exposes this mutation API."""
        from napmem_controls import apply_action, preview_action
        arguments = dict(record_id=record_id, value=value, source=source, at=at)
        if dry_run:
            return preview_action(self.data, action, **arguments)
        previous = copy.deepcopy(self.data)
        cache_state = "retained"
        try:
            receipt = apply_action(self.data, action, **arguments,
                                   expected_generation=expected_generation,
                                   preview_token=preview_token)
            source_scopes = self.data.setdefault("source_scopes", {})
            if not isinstance(source_scopes, dict):
                raise ValueError("source_scopes must be an object")
            # Hash-only routing survives removal of raw source metadata, so
            # implicit replay cannot evade a scope-specific content tombstone.
            for record in previous["memory_records"]:
                anchors = [(record["source_anchor"], record.get("scope", "legacy"))]
                anchors.extend((anchor, anchor.get("assertion", {}).get("scope", "legacy"))
                               for anchor in record.get("duplicate_anchors", {}).values())
                for anchor, item_scope in anchors:
                    session = anchor.get("session_id")
                    if session:
                        key = hashlib.sha256(session.encode("utf-8")).hexdigest()
                        source_scopes.setdefault(key, item_scope)
            self.rebuild_higher_layers()
            if action in ("correct", "reject", "exclude", "forget", "forget_session"):
                self._semantic_index = None
                cache_state = "absent"
                try:
                    os.unlink(self.pyramid_path + ".embindex.json")
                    cache_state = "removed"
                except FileNotFoundError:
                    pass
                except OSError as exc:
                    cache_state = "pending:" + type(exc).__name__
            if action in ("forget", "forget_session", "exclude"):
                receipts = self.data.setdefault("deletion_receipts", [])
                if not isinstance(receipts, list):
                    raise ValueError("deletion_receipts must be a list")
                receipts.append({"change_id": receipt["change_id"], "action": action,
                                 "cache": cache_state, "mirrors": "pending_acknowledgment",
                                 "originals_exports_backups": "operator_managed"})
                self.data["deletion_receipts"] = receipts[-1000:]
            self.save()
        except Exception:
            self.data = previous
            raise
        self._semantic_index = None
        receipt.update(generation=self.data["generation"], persistence="committed",
                       cache=cache_state, embedding_cache=cache_state,
                       canonical_deletion_complete=(action in ("forget", "forget_session")
                                                    and not cache_state.startswith("pending:")),
                       completion_scope="canonical_store_and_adjacent_embedding_cache")
        if action in ("forget", "forget_session", "exclude"):
            receipt["target_scope"] = {"forget": "claim_and_correction_family",
                                       "forget_session": "selected_session_occurrences",
                                       "exclude": "selected_source_occurrences"}[action]
        return receipt

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
        # Derive the default session ID from the input BASENAME (mirroring the
        # consolidator). Caveat: two different files sharing a basename map to
        # the same session and replace each other's records — warn when the
        # stored Layer 0 entry points at a different path.
        session_id = args.session_id or f"sess_{os.path.splitext(os.path.basename(args.input))[0]}"
        prior = next((s for s in distiller.data["raw_conversations"]
                      if s["session_id"] == session_id), None)
        if prior and os.path.abspath(prior.get("file_path", "")) != os.path.abspath(args.input):
            print(f"Warning: session {session_id!r} previously ingested from "
                  f"{prior.get('file_path')!r}; this run REPLACES those records "
                  f"(pass --session-id to keep them separate)", file=sys.stderr)
        num_extracted = distiller.ingest_session(session_id, args.title, args.input, content)
        print(f"Successfully distilled {num_extracted} atomic units from {args.input} into {args.pyramid}")
        print("\n" + distiller.render_markdown_summary())
    else:
        print("No input provided. Rendering current pyramid:")
        print(distiller.render_markdown_summary())

if __name__ == "__main__":
    main()
