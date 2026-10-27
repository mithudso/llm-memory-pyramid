#!/usr/bin/env python3
"""Offline evidence-retrieval evaluation, independent of answer generation.

The public helpers ``load_fixture``, ``score_query``, ``evaluate`` and
``compare_baseline`` are usable from CI. Only synthetic fixture data is loaded.
Hashed retrieval uses the existing agent with the backend forced to hashed-TF;
its disposable cache lives in a temporary directory. No model or service runs.
"""

from __future__ import annotations

import argparse
from collections import Counter
from contextlib import ExitStack
from datetime import datetime
import hashlib
import json
import math
import os
from pathlib import Path
import statistics
import sys
import tempfile
import time
from typing import Any
from unittest.mock import patch

from napmem_retrieval_agent import NapMemRetrievalAgent

ROOT = Path(__file__).resolve().parent
DEFAULT_FIXTURE = ROOT / "evaluations" / "memory_quality_v1.json"
if not DEFAULT_FIXTURE.is_file():
    DEFAULT_FIXTURE = Path(sys.prefix) / "share" / "napmem" / "evaluations" / "memory_quality_v1.json"
REPORT_VERSION = "1.0.0"
MODES = ("substring", "hashed", "hybrid")
SPLITS = ("dev", "heldout", "all")


def _encoded(value: Any) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True,
                      separators=(",", ":"), allow_nan=False).encode("utf-8")


def _date(value: str) -> datetime:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        raise ValueError("Fixture timestamps must include a timezone")
    return parsed


def load_fixture(path: str | Path = DEFAULT_FIXTURE) -> dict[str, Any]:
    """Load and validate a versioned, explicitly split fixture without I/O side effects."""
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    if data.get("synthetic") is not True:
        raise ValueError("Evaluation requires an explicitly synthetic fixture")
    _date(data["as_of"])
    records = {record["id"]: record for record in data["records"]}
    if len(records) != len(data["records"]):
        raise ValueError("Duplicate record ID")
    for record in records.values():
        for field in ("scope", "memory_kind", "status", "supersedes", "text"):
            if field not in record:
                raise ValueError(f"Record {record['id']} lacks {field}")
        if not isinstance(record["scope"], str) or not isinstance(record["supersedes"], list):
            raise ValueError("Record scope must be a string and supersedes must be a list")
        if not set(record["supersedes"]) <= records.keys():
            raise ValueError("Unknown superseded record ID")
        for field in ("valid_from", "valid_to"):
            if record.get(field):
                _date(record[field])
        if (record.get("valid_from") and record.get("valid_to")
                and _date(record["valid_from"]) >= _date(record["valid_to"])):
            raise ValueError("Invalid validity interval")
    seen: set[str] = set()
    scenario_splits: dict[str, str] = {}
    for case in data["queries"]:
        if case["id"] in seen:
            raise ValueError("Duplicate query ID")
        seen.add(case["id"])
        if case["split"] not in ("dev", "heldout"):
            raise ValueError("Every query must have a fixed dev or heldout split")
        scenario = case["scenario"]
        if scenario_splits.setdefault(scenario, case["split"]) != case["split"]:
            raise ValueError("A scenario cannot cross development and held-out splits")
        expected = case["expected_ids"]
        if len(expected) != len(set(expected)) or not set(expected) <= records.keys():
            raise ValueError("Invalid expected evidence IDs")
        if set(case.get("relevance", {})) - set(expected):
            raise ValueError("Relevance grades must refer to expected IDs")
        if any(not isinstance(grade, int) or isinstance(grade, bool) or grade < 1
               for grade in case.get("relevance", {}).values()):
            raise ValueError("Relevance grades must be positive integers")
        _date(case.get("as_of") or data["as_of"])
        for rid in expected:
            if not _scope_allowed(records[rid], case.get("scope")):
                raise ValueError(f"Gold evidence violates query scope: {case['id']} / {rid}")
            if not _time_allowed(records[rid], case.get("as_of") or data["as_of"]):
                raise ValueError(f"Gold evidence violates validity: {case['id']} / {rid}")
    return data


def _scope_allowed(record: dict[str, Any], scope: str | None) -> bool:
    record_scope = record.get("scope", "legacy")
    if scope == "*":
        return True
    if scope is None:
        return record_scope in ("global", "legacy")
    return record_scope in (scope, "global")


def _time_allowed(record: dict[str, Any], as_of: str) -> bool:
    if record.get("status") in ("deleted", "expired"):
        return False
    at = _date(as_of)
    start, end = record.get("valid_from"), record.get("valid_to")
    # An explicitly superseded assertion with unknown end time is not current.
    if record.get("status") == "superseded" and not end:
        return False
    return (not start or _date(start) <= at) and (not end or at < _date(end))


def score_query(case: dict[str, Any], result_ids: list[str],
                records: dict[str, dict[str, Any]], *, as_of: str,
                k: int = 5) -> dict[str, Any]:
    """Score evidence IDs; no-answer cases have null ranking scores, not perfect recall.

    Recall uses all gold evidence as the denominator. MRR uses the first gold
    hit. nDCG uses gain ``2**grade - 1`` and log2 rank discount. Duplicate hits
    occupy ranks but receive gain only once. Unsupported injection means a
    returned ID outside this query's labels; it does not measure generated text.
    Safety counts cover the complete returned list, even beyond rank five.
    """
    if isinstance(k, bool) or not isinstance(k, int) or k < 1:
        raise ValueError("k must be a positive integer")
    expected = set(case["expected_ids"])
    grades = {rid: case.get("relevance", {}).get(rid, 1) for rid in expected}
    ranked = result_ids[:k]
    seen: set[str] = set()
    gains = []
    first = None
    for rank, rid in enumerate(ranked, 1):
        grade = grades.get(rid, 0) if rid not in seen else 0
        seen.add(rid)
        if grade and first is None:
            first = rank
        gains.append((2 ** grade - 1) / math.log2(rank + 1))
    ideal = sum((2 ** grade - 1) / math.log2(rank + 1)
                for rank, grade in enumerate(sorted(grades.values(), reverse=True)[:k], 1))
    unsupported = sum(rid not in expected for rid in result_ids)
    known = [records[rid] for rid in result_ids if rid in records]
    return {
        "recall_at_5": len(expected.intersection(ranked)) / len(expected) if expected else None,
        "mrr_at_5": (1 / first if first else 0.0) if expected else None,
        "ndcg_at_5": sum(gains) / ideal if ideal else None,
        "unsupported_results": unsupported,
        "unsupported_injection": bool(unsupported),
        "unknown_ids": sum(rid not in records for rid in result_ids),
        "duplicate_results": len(result_ids) - len(set(result_ids)),
        "scope_violations": sum(not _scope_allowed(r, case.get("scope")) for r in known),
        "lifecycle_violations": sum(not _time_allowed(r, case.get("as_of") or as_of) for r in known),
        "instruction_bearing_results": sum(bool(r.get("instruction_bearing")) for r in known),
        "abstention_correct": not result_ids if not expected else None,
        "current_fact_correct": expected.issubset(ranked) and not unsupported
            if case["category"] in ("update", "temporal") else None,
        "protected_pass": expected.issubset(ranked) and not unsupported
            if case.get("protected", False) else None,
        "returned_count": len(result_ids),
    }


def extract_result_ids(response: dict[str, Any]) -> list[str]:
    """Normalize the legacy record response or the unified query evidence envelope."""
    hits = response.get("evidence", response.get("matches", []))
    if isinstance(hits, dict):
        hits = hits.get("memory_records", [])
    if not isinstance(hits, list):
        raise ValueError("Retrieval response must contain a list of evidence records")
    ids = []
    for hit in hits:
        if not isinstance(hit, dict):
            raise ValueError("Evidence must contain record objects")
        record = hit.get("record", hit)
        rid = record.get("id", record.get("record_id"))
        if not isinstance(rid, str):
            raise ValueError("Evidence record lacks an ID")
        ids.append(rid)
    return ids


def _distribution(values: list[float | int]) -> dict[str, float | int | None]:
    if not values:
        return {"min": None, "median": None, "p95": None, "max": None, "mean": None}
    ordered = sorted(values)
    return {"min": ordered[0], "median": statistics.median(ordered),
            "p95": ordered[max(0, math.ceil(len(ordered) * .95) - 1)],
            "max": ordered[-1], "mean": statistics.mean(ordered)}


def _aggregate(rows: list[dict[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {"query_count": len(rows)}
    for field in ("recall_at_5", "mrr_at_5", "ndcg_at_5", "abstention_correct",
                  "current_fact_correct", "protected_pass"):
        values = [r["scores"][field] for r in rows if r["scores"][field] is not None]
        result[field + ("_rate" if field.endswith(("correct", "pass")) else "")] = (
            statistics.mean(values) if values else None)
        result[field + "_cases"] = len(values)
    returned = sum(r["scores"]["returned_count"] for r in rows)
    unsupported = sum(r["scores"]["unsupported_results"] for r in rows)
    result["unsupported_result_rate"] = unsupported / returned if returned else 0.0
    result["unsupported_injection_query_rate"] = (
        sum(r["scores"]["unsupported_injection"] for r in rows) / len(rows) if rows else 0.0)
    for field in ("scope_violations", "lifecycle_violations", "unknown_ids",
                  "instruction_bearing_results", "duplicate_results", "returned_count"):
        result[field] = sum(r["scores"][field] for r in rows)
    return result


def evaluate(mode: str = "substring", split: str = "heldout", *,
             fixture_path: str | Path = DEFAULT_FIXTURE, max_bytes: int = 8192,
             max_tokens: int | None = None, agent_class: type | None = None) -> dict[str, Any]:
    """Run fixed queries against a disposable store, with network access blocked.

    Legacy adapters receive query text without per-case scope or time options;
    their current runtime defaults apply. Frozen v1 reports capture the original
    unfiltered behavior before scope/lifecycle implementation.
    The optional hybrid adapter calls ``agent.query`` with explicit scope,
    as_of, top_k=5 and budgets. It fails clearly if that API is unavailable.
    Latencies cover the retrieval call including any temporary cache work;
    store loading and serialization are excluded. All response bytes count.
    """
    if mode not in MODES or split not in SPLITS:
        raise ValueError("Unknown evaluation mode or split")
    fixture = load_fixture(fixture_path)
    records = {r["id"]: r for r in fixture["records"]}
    cases = [q for q in fixture["queries"] if split == "all" or q["split"] == split]
    rows = []
    with tempfile.TemporaryDirectory(prefix="napmem-eval-") as temporary, ExitStack() as stack:
        # Existing semantic_search honors this setting before selecting a backend.
        stack.enter_context(patch.dict(os.environ, {"NAPMEM_EMBED_BACKEND": "hashed"}))
        stack.enter_context(patch("socket.create_connection", side_effect=RuntimeError("Offline evaluation forbids network access")))
        stack.enter_context(patch("urllib.request.urlopen", side_effect=RuntimeError("Offline evaluation forbids network access")))
        pyramid = Path(temporary) / "synthetic.json"
        pyramid.write_bytes(_encoded({"memory_records": fixture["records"],
                                      "raw_conversations": [], "topic_tracks": [], "user_profiles": []}))
        agent = (agent_class or NapMemRetrievalAgent)(str(pyramid))
        if mode == "hybrid" and not callable(getattr(agent, "query", None)):
            raise ValueError("Hybrid mode requires NapMemRetrievalAgent.query; this runtime has no unified query API")
        for case in cases:
            start = time.perf_counter_ns()
            if mode == "substring":
                response = agent.search_memory_pyramid(case["query"], layer="records")
            elif mode == "hashed":
                response = agent.semantic_search(case["query"], top_k=5)
                if response.get("mode") != "semantic:hashed-tf":
                    raise RuntimeError("Hashed baseline did not use the required hashed-TF backend")
            else:
                response = agent.query(case["query"], scope=case.get("scope"),
                                       as_of=case.get("as_of") or fixture["as_of"], top_k=5,
                                       mode="hybrid", max_bytes=max_bytes, max_tokens=max_tokens)
            latency = (time.perf_counter_ns() - start) / 1_000_000
            result_ids = extract_result_ids(response)
            rows.append({"query_id": case["id"], "scenario": case["scenario"],
                         "category": case["category"], "expected_ids": case["expected_ids"],
                         "result_ids": result_ids, "scores": score_query(case, result_ids, records, as_of=fixture["as_of"]),
                         "latency_ms": latency, "result_bytes": len(_encoded(response))})
    runtime_files = tuple(name for name in ("napmem_retrieval_agent.py", "semantic_index.py",
                                            "napmem_model.py", "napmem_search.py")
                          if (ROOT / name).exists())
    return {
        "report_version": REPORT_VERSION, "fixture_version": fixture["version"],
        "fixture_sha256": hashlib.sha256(Path(fixture_path).read_bytes()).hexdigest(),
        "runtime_sha256": {name: hashlib.sha256((ROOT / name).read_bytes()).hexdigest() for name in runtime_files},
        "mode": mode, "split": split, "top_k": 5, "as_of": fixture["as_of"],
        "budgets": {"max_bytes": max_bytes, "max_tokens": max_tokens} if mode == "hybrid" else None,
        "coverage": {"total_queries": len(fixture["queries"]), "total_records": len(records),
                     "scenarios_in_split": len({q["scenario"] for q in cases}),
                     "categories_in_split": dict(sorted(Counter(q["category"] for q in cases).items()))},
        "limitations": fixture["limitations"] + [
            "Evidence retrieval only: this does not score extraction, generated answers, production traffic, or real embeddings.",
            "Unsupported injection counts IDs outside the query labels; incomplete labels can overstate it.",
            "Legacy modes use their runtime defaults; frozen v1 reports document the original unfiltered behavior.",
            "Latency is a single local pass with cold first-query cache cost; it is machine dependent and excluded from quality gates.",
            "Result bytes count canonical compact UTF-8 JSON of the complete response, before metric top-five truncation.",
        ],
        "metrics": _aggregate(rows),
        "by_category": {category: _aggregate([r for r in rows if r["category"] == category])
                        for category in sorted({r["category"] for r in rows})},
        "latency_ms": _distribution([r["latency_ms"] for r in rows]),
        "result_bytes": _distribution([r["result_bytes"] for r in rows]),
        "results": rows,
    }


def compare_baseline(report: dict[str, Any], baseline: dict[str, Any], *, tolerance: float = 1e-12) -> list[str]:
    """Return quality regressions against a compatible report; ignore timing and byte variation."""
    for field in ("fixture_sha256", "split", "top_k", "as_of"):
        if report.get(field) != baseline.get(field):
            return [f"Incompatible baseline: {field} differs"]
    issues = []
    higher = ("recall_at_5", "mrr_at_5", "ndcg_at_5", "abstention_correct_rate",
              "current_fact_correct_rate", "protected_pass_rate")
    lower = ("unsupported_result_rate", "unsupported_injection_query_rate", "scope_violations",
             "lifecycle_violations", "unknown_ids", "instruction_bearing_results", "duplicate_results")
    groups = [("all", report["metrics"], baseline["metrics"])]
    for category, old in baseline["by_category"].items():
        if category not in report["by_category"]:
            issues.append(f"Missing category: {category}")
        else:
            groups.append((category, report["by_category"][category], old))
    for name, new, old in groups:
        for field in higher + lower:
            if old.get(field) is None:
                continue
            if new.get(field) is None:
                issues.append(f"{name}.{field}: missing measurement")
            elif ((field in higher and new[field] + tolerance < old[field])
                  or (field in lower and new[field] > old[field] + tolerance)):
                issues.append(f"{name}.{field}: {new[field]} regressed from {old[field]}")
    return issues


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--mode", choices=MODES, default="substring")
    parser.add_argument("--split", choices=SPLITS, default="heldout")
    parser.add_argument("--fixture", type=Path, default=DEFAULT_FIXTURE)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--check-baseline", type=Path, help="Fail on quality regressions against this report")
    parser.add_argument("--max-bytes", type=int, default=8192, help="Budget passed only to the hybrid adapter")
    parser.add_argument("--max-tokens", type=int, help="Budget passed only to the hybrid adapter")
    args = parser.parse_args(argv)
    try:
        report = evaluate(args.mode, args.split, fixture_path=args.fixture,
                          max_bytes=args.max_bytes, max_tokens=args.max_tokens)
        issues = compare_baseline(report, json.loads(args.check_baseline.read_text(encoding="utf-8"))) if args.check_baseline else []
    except (ValueError, OSError, RuntimeError) as exc:
        parser.exit(2, f"Evaluation failed: {exc}\n")
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True, allow_nan=False) + "\n", encoding="utf-8")
    print(json.dumps({"mode": report["mode"], "split": report["split"], "metrics": report["metrics"],
                      "baseline_regressions": issues}, indent=2, sort_keys=True))
    return 1 if issues else 0


if __name__ == "__main__":
    raise SystemExit(main())
