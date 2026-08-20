#!/usr/bin/env python3
"""
LLM Extraction Pipeline (production path for the NapMem distiller)

Replaces the heuristic extractor with real LLM extraction using the
zero-fabrication prompts in llm_extraction_prompts.py, submitted through the
Anthropic Message Batches API (50% cost, async — a natural fit for naptime
consolidation). Extracted units are schema-validated before ingestion; invalid
units are rejected and logged, never silently repaired.

Requires the `anthropic` package (the repo's only optional dependency):
    pip install anthropic

Usage:
    python3 llm_extractor.py --input memory_logs/notes.md
    python3 llm_extractor.py --input a.md b.md --model claude-haiku-4-5
    python3 llm_extractor.py --input notes.md --no-batch   # direct call, no batch
    python3 llm_extractor.py --input notes.md --dry-run    # print prompt, no API call
"""

import argparse
import json
import logging
import os
import re
import sys
import time
from typing import Any

from llm_extraction_prompts import get_extraction_prompt
from memory_pyramid_distiller import (
    SALIENCE_LEVELS,
    UNIT_TYPES,
    MemoryPyramidDistiller,
    _slugify,
    _utcnow,
)

logger = logging.getLogger(__name__)

DEFAULT_MODEL = "claude-haiku-4-5"
MAX_OUTPUT_TOKENS = 16000
BATCH_POLL_INTERVAL_SEC = 15
BATCH_TIMEOUT_SEC = 3600

CODE_FENCE_RE = re.compile(r"^```(?:json)?\s*\n(.*)\n```\s*$", re.DOTALL)


class ExtractionError(Exception):
    """Raised when an LLM extraction result cannot be used."""


def parse_extraction_output(raw_text: str) -> list[dict[str, Any]]:
    """
    Parses the model's response into a list of unit dicts. Tolerates a JSON
    code fence around the array (models occasionally add one despite the
    return-only-JSON instruction) but nothing else.
    """
    text = raw_text.strip()
    fence = CODE_FENCE_RE.match(text)
    if fence:
        text = fence.group(1).strip()
    try:
        units = json.loads(text)
    except json.JSONDecodeError as exc:
        raise ExtractionError(f"Extractor did not return valid JSON: {exc}") from exc
    if not isinstance(units, list):
        raise ExtractionError(f"Extractor returned {type(units).__name__}, expected a JSON array")
    return units


def validate_unit(unit: Any) -> str | None:
    """Returns a rejection reason for an invalid unit, or None if valid."""
    if not isinstance(unit, dict):
        return "unit is not an object"
    if unit.get("type") not in UNIT_TYPES:
        return f"invalid type {unit.get('type')!r}"
    text = unit.get("text")
    if not isinstance(text, str) or not text.strip():
        return "missing or empty text"
    if unit.get("salience") not in SALIENCE_LEVELS:
        return f"invalid salience {unit.get('salience')!r}"
    anchor = unit.get("source_anchor")
    if not isinstance(anchor, dict) or not anchor.get("heading") or not anchor.get("line_range"):
        return "missing source_anchor.heading or .line_range"
    return None


def units_to_records(units: list[dict[str, Any]], session_id: str,
                     file_path: str) -> tuple[list[dict[str, Any]], list[str]]:
    """
    Converts validated extractor units into full Layer 1 records with
    rec_<session>_NNN ids. Returns (records, rejection_reasons). The distiller
    renumbers ids past the session's surviving suffix on re-ingest, so
    numbering from 1 here is safe.
    """
    records: list[dict[str, Any]] = []
    rejections: list[str] = []
    for unit in units:
        reason = validate_unit(unit)
        if reason is not None:
            rejections.append(f"{reason}: {json.dumps(unit)[:200]}")
            continue
        anchor = unit["source_anchor"]
        unit_id = f"rec_{session_id}_{len(records) + 1:03d}"
        records.append({
            "id": unit_id,
            "type": unit["type"],
            "text": unit["text"].strip(),
            "salience": unit["salience"],
            "canonical": unit_id,
            "duplicates": [],
            "topic_slug": unit.get("topic_slug") or _slugify(anchor.get("heading", "General")),
            "source_anchor": {
                "session_id": session_id,
                "file_path": file_path,
                "heading": anchor["heading"],
                "line_range": anchor["line_range"],
            },
            "created_at": _utcnow(),
        })
    return records, rejections


def _make_client():
    try:
        import anthropic
    except ImportError as exc:
        raise SystemExit(
            "The LLM extraction path requires the `anthropic` package: pip install anthropic"
        ) from exc
    return anthropic.Anthropic()


def _build_request_params(prompt: str, model: str) -> dict[str, Any]:
    return {
        "model": model,
        "max_tokens": MAX_OUTPUT_TOKENS,
        "messages": [{"role": "user", "content": prompt}],
    }


def extract_direct(client, prompt: str, model: str) -> str:
    """Single synchronous extraction call (small runs / smoke tests)."""
    import anthropic
    try:
        response = client.messages.create(**_build_request_params(prompt, model))
    except anthropic.RateLimitError as exc:
        raise ExtractionError(f"Rate limited: {exc.message}") from exc
    except anthropic.APIStatusError as exc:
        raise ExtractionError(f"API error {exc.status_code}: {exc.message}") from exc
    except anthropic.APIConnectionError as exc:
        raise ExtractionError(f"Network error reaching the API: {exc}") from exc
    logger.info("Extraction usage: input=%s output=%s",
                response.usage.input_tokens, response.usage.output_tokens)
    return "".join(block.text for block in response.content if block.type == "text")


def extract_batch(client, prompts_by_session: dict[str, str], model: str) -> dict[str, str]:
    """
    Submits one extraction request per session via the Message Batches API and
    polls until the batch ends. Returns {session_id: raw_response_text} for
    succeeded requests; failed requests are logged and omitted.
    """
    requests = [
        {"custom_id": session_id,
         "params": _build_request_params(prompt, model)}
        for session_id, prompt in prompts_by_session.items()
    ]
    batch = client.messages.batches.create(requests=requests)
    logger.info("Submitted batch %s with %d request(s)", batch.id, len(requests))

    deadline = time.monotonic() + BATCH_TIMEOUT_SEC
    while batch.processing_status != "ended":
        if time.monotonic() > deadline:
            raise ExtractionError(f"Batch {batch.id} did not end within {BATCH_TIMEOUT_SEC}s")
        time.sleep(BATCH_POLL_INTERVAL_SEC)
        batch = client.messages.batches.retrieve(batch.id)

    outputs: dict[str, str] = {}
    for result in client.messages.batches.results(batch.id):
        if result.result.type == "succeeded":
            message = result.result.message
            outputs[result.custom_id] = "".join(
                block.text for block in message.content if block.type == "text"
            )
            logger.info("Batch item %s: input=%s output=%s tokens", result.custom_id,
                        message.usage.input_tokens, message.usage.output_tokens)
        else:
            logger.error("Batch item %s failed: %s", result.custom_id, result.result.type)
    return outputs


def ingest_extractions(distiller: MemoryPyramidDistiller,
                       outputs_by_session: dict[str, str],
                       file_paths: dict[str, str]) -> tuple[int, set[str]]:
    """
    Parses, validates, and ingests each session's extraction output.
    Returns (total_units_ingested, session_ids_actually_ingested) — sessions
    whose output failed parsing or validation are omitted from the set so
    callers can route them to a fallback extractor.
    """
    total = 0
    ingested: set[str] = set()
    for session_id, raw_text in outputs_by_session.items():
        file_path = file_paths[session_id]
        try:
            units = parse_extraction_output(raw_text)
        except ExtractionError as exc:
            logger.error("Session %s: %s — skipped", session_id, exc)
            continue
        records, rejections = units_to_records(units, session_id, file_path)
        for reason in rejections:
            logger.warning("Session %s: rejected unit (%s)", session_id, reason)
        if not records:
            logger.error("Session %s: no valid units extracted — skipped", session_id)
            continue
        count = distiller.ingest_session_records(
            session_id, f"LLM-extracted {os.path.basename(file_path)}", file_path, records
        )
        logger.info("Session %s: ingested %d unit(s) (%d rejected)",
                    session_id, count, len(rejections))
        total += count
        ingested.add(session_id)
    return total, ingested


def main():
    parser = argparse.ArgumentParser(description="LLM extraction into the NapMem pyramid.")
    parser.add_argument("--input", type=str, nargs="+", required=True,
                        help="Memory file(s) to extract.")
    parser.add_argument("--pyramid", type=str, default="napmem_pyramid.json")
    parser.add_argument("--model", type=str, default=DEFAULT_MODEL,
                        help=f"Model for extraction (default {DEFAULT_MODEL}).")
    parser.add_argument("--no-batch", action="store_true",
                        help="Use direct API calls instead of the Batches API.")
    parser.add_argument("--semantic-dedup", action="store_true",
                        help="Fold semantic near-duplicates via the embedding index.")
    parser.add_argument("--dry-run", action="store_true",
                        help="Print the extraction prompt(s) and exit without calling the API.")
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO,
                        format="%(asctime)s [%(name)s] %(levelname)s: %(message)s")

    prompts: dict[str, str] = {}
    file_paths: dict[str, str] = {}
    for path in args.input:
        if not os.path.exists(path):
            print(f"Error: input file not found: {path}", file=sys.stderr)
            sys.exit(1)
        with open(path, "r", encoding="utf-8") as f:
            content = f.read()
        session_id = f"sess_{os.path.splitext(os.path.basename(path))[0]}"
        prompts[session_id] = get_extraction_prompt(content, session_id, os.path.basename(path))
        file_paths[session_id] = path

    if args.dry_run:
        for session_id, prompt in prompts.items():
            print(f"=== {session_id} ===\n{prompt}\n")
        return

    client = _make_client()
    if args.no_batch:
        outputs = {}
        for session_id, prompt in prompts.items():
            try:
                outputs[session_id] = extract_direct(client, prompt, args.model)
            except ExtractionError as exc:
                logger.error("Session %s: %s — skipped", session_id, exc)
    else:
        outputs = extract_batch(client, prompts, args.model)

    distiller = MemoryPyramidDistiller(pyramid_path=args.pyramid,
                                       semantic_dedup=args.semantic_dedup)
    total, ingested = ingest_extractions(distiller, outputs, file_paths)
    print(f"Ingested {total} LLM-extracted unit(s) from {len(ingested)} session(s) "
          f"into {args.pyramid}")


if __name__ == "__main__":
    main()
