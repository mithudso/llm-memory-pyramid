"""Portable NapMem commands. Default operation is local, offline and explicit."""

from __future__ import annotations

import argparse
import importlib.util
import json
from pathlib import Path
import sys
from typing import Any

from napmem_config import NapMemConfig, resolve_config, runtime_environment


def _common(parser):
    for flag, choices in (("mode", ("offline", "local", "remote")),
                           ("embedding-backend", ("hashed", "ollama")),
                           ("extraction", ("heuristic", "ollama", "anthropic"))):
        parser.add_argument("--" + flag, choices=choices, default=argparse.SUPPRESS)
    for field in ("pyramid", "config", "scope", "ollama-url", "ollama-model", "chat-model", "anthropic-model"):
        parser.add_argument("--" + field, default=argparse.SUPPRESS)
    parser.add_argument("--source-root", dest="source_roots", action="append", default=argparse.SUPPRESS)


def build_parser():
    parser = argparse.ArgumentParser(description="NapMem: inspectable agent memory, offline by default.")
    from importlib.metadata import PackageNotFoundError, version
    try:
        installed_version = version("llm-memory-pyramid")
    except PackageNotFoundError:
        installed_version = "0.2.0"
    parser.add_argument("--version", action="version", version=installed_version)
    _common(parser)
    commands = parser.add_subparsers(dest="command", required=True)

    def command(name, parent=commands, **kwargs):
        result = parent.add_parser(name, **kwargs)
        _common(result)
        return result

    command("init", help="create a new store, preserving an existing store")
    command("demo", help="ingest two synthetic, separately scoped demo sessions")
    ingest = command("ingest", help="ingest one explicit Markdown/text source")
    ingest.add_argument("input")
    ingest.add_argument("--session-id")
    ingest.add_argument("--title")
    ingest.add_argument("--enqueue", action="store_true", help="capture a durable job without running extraction")
    query = command("query", help="retrieve bounded, scoped evidence")
    query.add_argument("query")
    query.add_argument("--retrieval-mode", choices=("hybrid", "lexical", "semantic"), default="hybrid")
    query.add_argument("--top-k", type=int, default=5)
    inspect = command("inspect", help="inspect a record or a memory view")
    inspect.add_argument("record_id", nargs="?")
    inspect.add_argument("--view", choices=("overview", "current", "profiles", "conflicts", "stale", "review", "timeline", "handoff"))
    inspect.add_argument("--verify", action="store_true")
    inspect.add_argument("--offset", type=int, default=0)
    inspect.add_argument("--limit", type=int, default=20)
    inspect.add_argument("--stale-days", type=float, default=30)
    for item in (query, inspect):
        item.add_argument("--as-of")
        item.add_argument("--max-bytes", type=int, default=16384)
        item.add_argument("--max-tokens", type=int, default=2048)
    doctor = command("doctor", help="read-only diagnostics; no default probes or initialization")
    doctor.add_argument("--probe", action="store_true", help="explicitly probe the configured Ollama endpoint")
    diff = command("diff", help="compare two explicit source revisions without changing memory")
    diff.add_argument("before")
    diff.add_argument("after")
    diff.add_argument("--max-bytes", type=int, default=8192)
    control = command("control", help="apply or preview a durable local control")
    from napmem_controls import ACTIONS
    control.add_argument("action", choices=ACTIONS)
    control.add_argument("--record-id")
    control.add_argument("--value")
    control.add_argument("--source")
    control.add_argument("--at")
    control.add_argument("--dry-run", "--preview", dest="dry_run", action="store_true")
    control.add_argument("--expected-generation", type=int)
    control.add_argument("--preview-token")
    jobs = command("jobs", help="inspect and resume durable extraction jobs")
    job_commands = jobs.add_subparsers(dest="job_action", required=True)
    for name in ("list", "get", "enqueue", "run", "commit", "retry", "cancel", "submit", "collect", "prune"):
        item = command(name, job_commands)
        if name in ("get", "retry", "cancel"):
            item.add_argument("job_id")
        if name == "commit":
            item.add_argument("job_id", nargs="?")
        if name in ("enqueue", "retry"):
            item.add_argument("input")
        if name == "enqueue":
            item.add_argument("--session-id")
        if name in ("list", "run", "commit", "submit", "collect"):
            item.add_argument("--limit", type=int, default=100 if name == "list" else 20)
        if name == "list":
            item.add_argument("--state")
        if name == "run":
            item.add_argument("--commit", action="store_true")
        if name == "prune":
            item.add_argument("--older-than-seconds", type=float, default=7 * 86400)
    snapshot = command("snapshot", help="export or restore a verified snapshot")
    snapshot_commands = snapshot.add_subparsers(dest="snapshot_action", required=True)
    export = command("export", snapshot_commands)
    export.add_argument("destination")
    export.add_argument("--without-cache", action="store_true")
    restore = command("restore", snapshot_commands)
    restore.add_argument("source")
    evaluation = command("eval", help="run the synthetic offline retrieval benchmark")
    evaluation.add_argument("--eval-mode", choices=("substring", "hashed", "hybrid"), default="hybrid")
    evaluation.add_argument("--split", choices=("dev", "heldout", "all"), default="heldout")
    evaluation.add_argument("--fixture")
    evaluation.add_argument("--output")
    evaluation.add_argument("--check-baseline")
    return parser


def _distiller(config):
    from memory_pyramid_distiller import MemoryPyramidDistiller
    return MemoryPyramidDistiller(config.pyramid)


def _initialize(config):
    from napmem_storage import read_snapshot, store_lock
    with store_lock(config.pyramid):
        existing, _ = read_snapshot(config.pyramid)
        distiller = _distiller(config)
        if existing is None:
            distiller.save()
        return {"pyramid": config.pyramid, "created": existing is None, "generation": distiller.data["generation"]}


def _online(config):
    if config.mode == "offline":
        raise ValueError("This operation requires explicit local or remote mode")


def _anthropic_client(config):
    _online(config)
    try:
        import anthropic
    except ImportError as exc:
        raise ValueError("Anthropic extraction requires the optional llm extra") from exc
    return anthropic.Anthropic()


def _capture(config, args, distiller):
    from napmem_controls import source_is_excluded
    from napmem_sources import SourceRegistry, normalized_path, read_source
    path = normalized_path(args.input)
    registry = SourceRegistry(config.pyramid)
    session = getattr(args, "session_id", None) or registry.resolve_session_id(
        path, legacy_sources=distiller.data["raw_conversations"])
    if source_is_excluded(distiller.data, path, session_id=session):
        return None, session, registry
    source = read_source(path, list(config.source_roots) or None)
    if not getattr(args, "session_id", None):
        entry = registry.observe(source, scope=config.scope, legacy_sources=distiller.data["raw_conversations"])
        session = entry["session_id"]
    return source, session, registry


def _enqueue(config, args):
    from napmem_jobs import JobQueue
    source, session, _ = _capture(config, args, _distiller(config))
    if source is None:
        return {"status": "excluded", "session_id": session}
    if config.extraction == "ollama":
        raise ValueError("Durable jobs support heuristic or Anthropic extraction; use direct Ollama ingest")
    return JobQueue(config.pyramid).enqueue(
        session_id=session, source_path=source["path"], source_content=source["content"],
        scope=config.scope, backend=config.extraction, model=config.anthropic_model,
        allowed_roots=list(config.source_roots) or None)


def _ingest(config, args):
    if args.enqueue:
        return _enqueue(config, args)
    distiller = _distiller(config)
    source, session, registry = _capture(config, args, distiller)
    if source is None:
        return {"status": "excluded", "session_id": session, "ingested": 0}
    title = args.title or Path(source["path"]).name
    if config.extraction == "heuristic":
        records = distiller.extract_atomic_units(source["content"], session, source["path"])
        info = {"method": "heuristic"}
    else:
        _online(config)
        from llm_extraction_prompts import PROMPT_VERSION, get_extraction_prompt
        from llm_extractor import parse_extraction_output, units_to_records
        prompt = get_extraction_prompt(source["content"], session, Path(source["path"]).name)
        if config.extraction == "anthropic":
            if not config.anthropic_model:
                raise ValueError("Anthropic extraction requires an explicit anthropic_model")
            from llm_extractor import extract_direct
            raw = extract_direct(_anthropic_client(config), prompt, config.anthropic_model)
            info = {"method": "anthropic", "model": config.anthropic_model, "prompt_version": PROMPT_VERSION}
        else:
            if not config.ollama_url or not config.chat_model:
                raise ValueError("Ollama extraction requires explicit ollama_url and chat_model")
            from ollama_extractor import extract_ollama
            infos = {}
            output = extract_ollama({session: prompt}, [(config.ollama_url, config.chat_model)], extraction_info=infos)
            if session not in output:
                raise RuntimeError("Ollama extraction did not return valid output")
            raw, info = output[session], infos[session]
        records, rejected = units_to_records(parse_extraction_output(raw), session, source["path"])
        if not records:
            raise ValueError("Extraction returned no valid records")
    # Extraction can outlive both the file revision and an operator exclusion.
    # Reload canonical controls and recheck the source at the commit boundary.
    from napmem_controls import source_is_excluded
    from napmem_sources import read_source
    with distiller.transaction():
        stale = None
        if source_is_excluded(distiller.data, source["path"], session_id=session):
            stale = "source_excluded"
        else:
            try:
                current = read_source(source["path"], list(config.source_roots) or None)
                if current["sha256"] != source["sha256"]:
                    stale = "source_revision_changed"
            except (OSError, ValueError):
                stale = "source_missing_or_unreadable"
        if stale:
            return {"status": "stale", "reason": stale, "session_id": session, "ingested": 0}
        count = distiller.ingest_session_records(session, title, source["path"], records,
                                                  scope=config.scope, source_content=source["content"], extraction_info=info)
    if not getattr(args, "session_id", None):
        registry.mark_committed(session, source["sha256"])
    return {"pyramid": config.pyramid, "session_id": session, "ingested": count,
            "generation": distiller.data["generation"], "extraction": config.extraction}


def _doctor(config, args):
    from napmem_storage import read_snapshot
    def available(name):
        try:
            return importlib.util.find_spec(name) is not None
        except (ImportError, ValueError):
            return False
    result: dict[str, Any] = {"ok": True, "config": config.as_dict(), "probed": False,
                              "python": sys.version.split()[0], "store": {"exists": Path(config.pyramid).exists()},
                              "optional_dependencies": {name: available(name)
                                                         for name in ("anthropic", "ollama_client")},
                              "source_roots": [{"path": path, "exists": Path(path).is_dir()} for path in config.source_roots]}
    if result["store"]["exists"]:
        try:
            from napmem_controls import apply_controls
            from napmem_model import migrate_store
            raw, digest = read_snapshot(config.pyramid)
            data = migrate_store(raw)
            apply_controls(data)
            result["store"].update(valid=True, generation=data["generation"], schema=data["version"], sha256=digest,
                                    records=len(data["memory_records"]))
        except (OSError, ValueError, TypeError) as exc:
            result.update(ok=False)
            result["store"].update(valid=False, error=type(exc).__name__)
    if args.probe:
        _online(config)
        if not config.ollama_url:
            raise ValueError("Explicit probing requires an ollama_url")
        import urllib.request
        with urllib.request.urlopen(config.ollama_url.rstrip("/") + "/api/tags", timeout=2) as response:
            result["probe"] = {"endpoint": config.ollama_url, "status": response.status}
        result["probed"] = True
    return result


def _jobs(config, args):
    from napmem_jobs import JobQueue
    queue = JobQueue(config.pyramid)
    action = args.job_action
    if action == "list":
        return {"jobs": queue.list(args.state, limit=args.limit)}
    if action == "get":
        return {"job": queue.get(args.job_id)}
    if action == "enqueue":
        return _enqueue(config, args)
    if action == "cancel":
        return queue.cancel(args.job_id)
    if action == "retry":
        from napmem_sources import read_source
        source = read_source(args.input, list(config.source_roots) or None)
        return queue.retry(args.job_id, source_content=source["content"], source_path=source["path"])
    if action == "prune":
        return queue.prune(older_than_seconds=args.older_than_seconds)
    if action in ("submit", "collect"):
        client = _anthropic_client(config)
        return {"jobs": getattr(queue, action)(client, limit=args.limit)}
    distiller = _distiller(config)
    if action == "run":
        result = {"jobs": queue.run(distiller, limit=args.limit)}
        if args.commit:
            result["commits"] = queue.commit_ready(distiller, limit=args.limit)
        return result
    return {"jobs": [queue.commit(args.job_id, distiller)] if args.job_id else queue.commit_ready(distiller, limit=args.limit)}


def execute(config: NapMemConfig, args) -> dict[str, Any]:
    if args.command == "diff":
        from napmem_inspector import source_diff
        from napmem_sources import read_source
        roots = list(config.source_roots) or None
        old = read_source(args.before, roots, max_bytes=2 * 1024 * 1024)
        new = read_source(args.after, roots, max_bytes=2 * 1024 * 1024)
        return source_diff(old["content"], new["content"], max_bytes=args.max_bytes)
    if args.command == "doctor":
        return _doctor(config, args)
    if args.command == "init":
        return _initialize(config)
    if args.command == "demo":
        distiller = _distiller(config)
        for session, scope, text in (
            ("sess_napmem_demo_alpha", "project:napmem-demo-alpha", "I prefer Vim as my editor for Alpha.\n"),
            ("sess_napmem_demo_beta", "project:napmem-demo-beta", "I prefer VS Code as my editor for Beta.\n"),
        ):
            distiller.ingest_session(session, "Synthetic NapMem demo", "napmem:demo/" + session, text, scope=scope)
        from napmem_retrieval_agent import NapMemRetrievalAgent
        return {"pyramid": config.pyramid, "synthetic": True,
                "query": NapMemRetrievalAgent(config.pyramid).query("preferred editor", scope="project:napmem-demo-alpha")}
    if args.command == "ingest":
        return _ingest(config, args)
    if args.command in ("query", "inspect"):
        from napmem_retrieval_agent import NapMemRetrievalAgent
        if args.command == "inspect" and (args.view or not args.record_id):
            from napmem_inspector import inspect_store
            return inspect_store(config.pyramid, view=args.view or "overview", scope=config.scope,
                                 as_of=args.as_of, offset=args.offset, limit=args.limit, max_bytes=args.max_bytes,
                                 max_tokens=args.max_tokens, stale_days=args.stale_days)
        agent = NapMemRetrievalAgent(config.pyramid)
        common = {"scope": config.scope, "as_of": args.as_of, "max_bytes": args.max_bytes, "max_tokens": args.max_tokens}
        if args.command == "inspect":
            return agent.inspect_provenance(args.record_id, verify=args.verify,
                                             allowed_roots=list(config.source_roots) or None, **common)
        backend = None
        if config.embedding_backend == "ollama":
            _online(config)
            if not config.ollama_url or not config.ollama_model:
                raise ValueError("Ollama query requires explicit ollama_url and ollama_model")
            from semantic_index import OllamaBackend
            backend = OllamaBackend(config.ollama_url, model=config.ollama_model)
        return agent.query(args.query, top_k=args.top_k, mode=args.retrieval_mode, backend=backend, **common)
    if args.command == "control":
        return _distiller(config).control(args.action, record_id=args.record_id, value=args.value, source=args.source,
                                          at=args.at, dry_run=args.dry_run, expected_generation=args.expected_generation,
                                          preview_token=args.preview_token)
    if args.command == "jobs":
        return _jobs(config, args)
    if args.command == "snapshot":
        if args.snapshot_action == "restore":
            return _distiller(config).restore_snapshot(args.source)
        from napmem_snapshots import export_snapshot
        return export_snapshot(config.pyramid, args.destination, include_cache=not args.without_cache)
    from napmem_eval import DEFAULT_FIXTURE, compare_baseline, evaluate
    report = evaluate(args.eval_mode, args.split, fixture_path=args.fixture or DEFAULT_FIXTURE)
    issues = compare_baseline(report, json.loads(Path(args.check_baseline).read_text(encoding="utf-8"))) if args.check_baseline else []
    if args.output:
        output = Path(args.output)
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(json.dumps(report, ensure_ascii=False, allow_nan=False) + "\n", encoding="utf-8")
    return {"mode": report["mode"], "split": report["split"], "metrics": report["metrics"], "baseline_regressions": issues}


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        config = resolve_config(vars(args))
        with runtime_environment(config):
            result = execute(config, args)
        print(json.dumps(result, ensure_ascii=False, separators=(",", ":"), allow_nan=False))
        return 1 if result.get("ok") is False or result.get("baseline_regressions") else 0
    except Exception as exc:
        print(json.dumps({"error": {"type": type(exc).__name__, "message": str(exc)}}, separators=(",", ":")))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
