#!/usr/bin/env python3
"""
Naptime Async Memory Consolidator

Implements background ("naptime") offline processing for LLM memory files.
Monitors memory files or session logs and incrementally re-ingests changed files
(each file maps to a stable session_id, so updates replace that session's records)
to keep the NapMem Pyramid updated without impacting active agent context or
response latency.

Extraction modes (--extraction):
  auto      (default) Anthropic when importable, then Ollama, then heuristic.
  llm       Require LLM extraction; startup fails without `anthropic`.
  ollama    Local Ollama extraction, then heuristic; no Anthropic API calls.
  heuristic Always use the built-in keyword-rule extractor.

In LLM mode each sweep's changed files go out as ONE Message Batches API batch
(50% cost — naptime is idle-time work, latency is irrelevant). Any file whose
LLM extraction fails tries the remaining configured extractors for that file.
Store write failures remain fatal to batch ingestion: continuing without a
transaction rollback could persist a partially mutated in-memory store.
"""

import argparse
import hashlib
import json
import logging
import math
import os
import time

from memory_pyramid_distiller import MemoryPyramidDistiller
from napmem_sources import MAX_SOURCE_BYTES, SourceRegistry, read_source

logger = logging.getLogger(__name__)

EXTRACTION_MODES = ("auto", "llm", "ollama", "heuristic")

# Colon-separated list of directories memory files must RESOLVE into; every
# file read is verified race-free (see _read_file_guarded) so a watched entry
# swapped into a symlink between scan and read cannot leak an out-of-root
# file's content into the extraction/embedding egress paths. FAIL-CLOSED:
# when unset, the watch dir itself is the sole allowed root — plain files
# ingest, symlinks escaping it are refused. Set to "off" to disable (only for
# a watch dir you deliberately populate with out-of-tree symlinks and trust).
ALLOWED_ROOTS_ENV = "NAPMEM_ALLOWED_ROOTS"


def _session_id_for(fname: str) -> str:
    """Stable session id for a watched file — the replace-by-session key.
    Shared definition; llm_extractor's CLI derives ids the same way."""
    return f"sess_{os.path.splitext(os.path.basename(fname))[0]}"


def _anthropic_available() -> bool:
    try:
        import anthropic  # noqa: F401
        return True
    except ImportError:
        return False


def _fd_true_path(fd: int) -> str | None:
    """Kernel-reported path of an open fd (macOS F_GETPATH / Linux procfs)."""
    try:
        import fcntl
        if hasattr(fcntl, "F_GETPATH"):
            raw = fcntl.fcntl(fd, fcntl.F_GETPATH, bytes(1024))
            return raw.split(b"\x00", 1)[0].decode()
    except (OSError, ValueError, UnicodeDecodeError):
        pass
    try:
        return os.readlink(f"/proc/self/fd/{fd}")
    except OSError:
        return None


def _read_file_guarded(path: str, allowed_roots: list[str]) -> str:
    """
    Reads a file, enforcing that the object actually opened is a regular file
    inside allowed_roots. The check runs on the OPEN fd (kernel-reported path
    + fstat), not on the pre-open path, so it cannot be raced by swapping the
    file into a symlink between validation and read (TOCTOU).
    """
    return read_source(path, allowed_roots, fd_path_resolver=_fd_true_path)["content"]


def _resolve_allowed_roots(watch_dir: str) -> list[str]:
    raw = os.environ.get(ALLOWED_ROOTS_ENV)
    if raw is None or not raw.strip():
        return [os.path.realpath(watch_dir)]  # fail-closed default
    if raw.strip().lower() == "off":
        return []
    roots = [os.path.realpath(p) for p in raw.split(":") if p.strip()]
    if not roots:
        # Degenerate values like ":::" must not silently equal "off" —
        # that would fail open on a config typo. Refuse to start instead.
        raise ValueError(
            f"{ALLOWED_ROOTS_ENV}={raw!r} yields no roots; use 'off' to disable the guard")
    return roots


class NaptimeConsolidator:
    def __init__(self, watch_dir: str, pyramid_path: str = "napmem_pyramid.json",
                 extraction: str = "auto", semantic_dedup: bool = False,
                 state_path: str | None = None, async_batches: bool = False):
        if extraction not in EXTRACTION_MODES:
            raise ValueError(f"extraction must be one of {EXTRACTION_MODES}")
        self.watch_dir = watch_dir
        self.pyramid_path = pyramid_path
        if async_batches and extraction == "ollama":
            raise ValueError("Durable async jobs currently support Anthropic and heuristic extraction")
        self.async_batches = async_batches
        self.source_registry = SourceRegistry(pyramid_path)
        self.distiller = MemoryPyramidDistiller(pyramid_path=pyramid_path,
                                                semantic_dedup=semantic_dedup)
        self.file_timestamps: dict[str, float] = {}
        # Persistent change state: under systemd/launchd --once mode every
        # sweep is a fresh process, so in-memory mtimes alone re-extract the
        # ENTIRE watch dir every hour — that is what burned the API budget.
        # {fpath: {"mtime": float, "sha256": hex}}; mtime is the cheap
        # fast-path, the hash catches touched-but-unchanged files (Syncthing,
        # mirror relinks) in both timestamp directions.
        self.state_path = state_path or (pyramid_path + ".sweepstate.json")
        self.file_hashes: dict[str, dict] = self._load_state()
        # (path -> mtime) of files refused/unreadable at that mtime: log the
        # refusal ONCE per change instead of flooding ERROR every sweep (a
        # parked hostile symlink would otherwise emit ~17k lines/day).
        self._refused: dict[str, float] = {}

        if extraction == "llm" and not _anthropic_available():
            raise RuntimeError(
                "--extraction llm requires the `anthropic` package: pip install anthropic"
            )
        self.use_llm = (extraction == "llm"
                        or (extraction == "auto" and _anthropic_available()))
        # ollama mode never touches the Anthropic API (zero API spend); auto
        # tries anthropic first, then ollama, then heuristic — reachability
        # is probed per sweep so an offline daemon costs one 3s check.
        self.use_ollama = extraction in ("ollama", "auto")
        self._client = None
        self.allowed_roots = _resolve_allowed_roots(watch_dir)
        mode = ("llm" if self.use_llm else
                "ollama" if self.use_ollama else "heuristic")
        logger.info("Extraction mode: %s (chain: %s)", mode, extraction)
        if self.allowed_roots:
            logger.info("Read guard active; allowed roots: %s", self.allowed_roots)
        else:
            logger.warning("Read guard DISABLED (%s=%r)", ALLOWED_ROOTS_ENV,
                           os.environ.get(ALLOWED_ROOTS_ENV))

    def _load_state(self) -> dict[str, dict]:
        try:
            with open(self.state_path, "r", encoding="utf-8") as f:
                data = json.load(f)
        except FileNotFoundError:
            return {}
        except (OSError, ValueError) as exc:
            logger.warning("Discarding unreadable sweep state %s (%s)",
                           self.state_path, type(exc).__name__)
            return {}
        if not isinstance(data, dict) or not isinstance(data.get("files"), dict):
            logger.warning("Discarding invalid sweep state structure in %s", self.state_path)
            return {}
        valid = {}
        for path, entry in data["files"].items():
            if not isinstance(entry, dict):
                continue
            mtime, digest = entry.get("mtime"), entry.get("sha256")
            if (isinstance(mtime, (int, float)) and not isinstance(mtime, bool)
                    and (not isinstance(mtime, float) or math.isfinite(mtime))
                    and isinstance(digest, str) and len(digest) == 64
                    and all(char in "0123456789abcdef" for char in digest)):
                valid[path] = {"mtime": mtime, "sha256": digest}
        invalid_count = len(data["files"]) - len(valid)
        if invalid_count:
            logger.warning("Discarding %d invalid sweep state entries in %s",
                           invalid_count, self.state_path)
        return valid

    def _save_state(self) -> None:
        # Prune entries for files gone from the watch dir so the state file
        # cannot grow without bound; write atomically like the store itself.
        try:
            live = {fp: st for fp, st in self.file_hashes.items()
                    if os.path.exists(fp)}
            from napmem_storage import atomic_write, read_snapshot, store_lock
            with store_lock(self.state_path):
                previous, expected = read_snapshot(self.state_path)
                merged = previous.get("files", {}) if isinstance(previous, dict) else {}
                if not isinstance(merged, dict):
                    merged = {}
                merged.update(live)
                merged = {path: entry for path, entry in merged.items() if os.path.exists(path)}
                atomic_write(self.state_path, {"files": merged}, expected_fingerprint=expected)
            self.file_hashes = live
        except (OSError, ValueError) as exc:
            logger.warning("Could not persist disposable sweep state to %s (%s)",
                           self.state_path, type(exc).__name__)

    def _collect_changed(self) -> list[tuple[str, str, str, float]]:
        """Returns (session_id, fpath, content, mtime) for changed .md files."""
        changed = []
        os.makedirs(self.watch_dir, exist_ok=True)
        with self.distiller.transaction():
            sources = list(self.distiller.data["raw_conversations"])
        stored_sources = {(session["session_id"], os.path.abspath(session["file_path"])) for session in sources}
        store_exists = os.path.exists(self.pyramid_path)
        paths = sorted(os.path.abspath(os.path.join(root, name))
                       for root, _, names in os.walk(self.watch_dir) for name in names if name.endswith(".md"))
        metadata = []
        for fpath in paths:
            known = self.source_registry.lookup(path=fpath)
            session_id = known["session_id"] if known else self.source_registry.resolve_session_id(
                fpath, legacy_sources=sources)
            from napmem_controls import source_is_excluded
            if source_is_excluded(self.distiller.data, fpath, session_id=session_id):
                continue
            mtime = None
            try:
                mtime = os.path.getmtime(fpath)
                snapshot = read_source(fpath, self.allowed_roots, max_bytes=MAX_SOURCE_BYTES,
                                       fd_path_resolver=_fd_true_path)
                content, digest = snapshot["content"], snapshot["sha256"]
                entry = self.source_registry.observe(snapshot, live_paths=paths, legacy_sources=sources)
                session_id = entry["session_id"]
                retained_scope = self.distiller.data.get("source_scopes", {}).get(
                    hashlib.sha256(session_id.encode("utf-8")).hexdigest())
                if retained_scope and entry.get("scope") != retained_scope:
                    entry = self.source_registry.observe(snapshot, scope=retained_scope,
                                                         live_paths=paths, legacy_sources=sources)
                if source_is_excluded(self.distiller.data, fpath, session_id=session_id):
                    continue
                metadata.append(entry)
                self._refused.pop(fpath, None)
                prior = self.file_hashes.get(fpath)
                source_present = any(session["session_id"] == session_id for session in sources)
                if store_exists and source_present and (entry.get("committed_sha256") == digest
                        or ((session_id, fpath) in stored_sources and prior and prior.get("sha256") == digest)):
                    self.file_hashes[fpath] = {"mtime": mtime, "sha256": digest}
                    self.source_registry.mark_committed(session_id, digest)
                    continue
                changed.append((session_id, fpath, content, mtime))
            except (OSError, ValueError) as exc:
                if self._refused.get(fpath) != mtime:
                    logger.error("Skipping memory file %s: %s", fpath, exc)
                if mtime is not None:
                    self._refused[fpath] = mtime
            except UnicodeDecodeError as exc:
                logger.error("Skipping non-UTF-8 memory file %s: %s", fpath, exc)
                if mtime is not None:
                    self._refused[fpath] = mtime
        metadata.extend(self.source_registry.mark_missing(paths, root=self.watch_dir))
        self._sync_source_metadata(metadata)
        return changed

    def _sync_source_metadata(self, entries):
        if not entries:
            return
        with self.distiller.transaction():
            changed = False
            for entry in entries:
                session_id = entry["session_id"]
                for raw in self.distiller.data["raw_conversations"]:
                    if raw["session_id"] == session_id:
                        for field, value in (("file_path", entry["path"]), ("source_state", entry["status"])):
                            if raw.get(field) != value:
                                raw[field] = value
                                changed = True
                for record in self.distiller.data["memory_records"]:
                    anchors = [record["source_anchor"], *record.get("duplicate_anchors", {}).values()]
                    for anchor in anchors:
                        if anchor.get("session_id") == session_id and anchor.get("file_path") != entry["path"]:
                            anchor["file_path"] = entry["path"]
                            changed = True
                    if record["source_anchor"].get("session_id") == session_id and record.get("source_state") != entry["status"]:
                        record["source_state"] = entry["status"]
                        changed = True
            if changed:
                self.distiller.save()

    def _current_outputs(self, outputs, changed):
        """Fence asynchronous model output against current source and controls."""
        from napmem_controls import source_is_excluded
        captured = {sid: hashlib.sha256(content.encode("utf-8")).hexdigest()
                    for sid, _, content, _ in changed}
        current = {}
        for session_id in outputs:
            try:
                snapshot = self.source_registry.read_current(session_id, allowed_roots=self.allowed_roots)
                if (snapshot is not None and snapshot["sha256"] == captured.get(session_id)
                        and not source_is_excluded(self.distiller.data, snapshot["path"], session_id=session_id)):
                    current[session_id] = snapshot
            except (OSError, ValueError):
                pass
        return current

    def _extract_llm(self, changed: list[tuple[str, str, str, float]]) -> set[str]:
        """
        Extracts the sweep's changed files as one batch via llm_extractor.
        Returns the session_ids successfully ingested; callers run the
        heuristic path for the rest.
        """
        import anthropic

        from llm_extractor import (
            DEFAULT_MODEL,
            ExtractionError,
            extract_batch,
            get_extraction_prompt,
            ingest_extractions,
        )
        prompts = {
            session_id: get_extraction_prompt(content, session_id, os.path.basename(fpath))
            for session_id, fpath, content, _ in changed
        }
        try:
            if self._client is None:
                self._client = anthropic.Anthropic()
            outputs = extract_batch(self._client, prompts, DEFAULT_MODEL)
        # TypeError included deliberately: the SDK raises it at call time when
        # no credential resolves (missing ANTHROPIC_API_KEY and no `ant auth`
        # profile) — that must degrade to the heuristic, not kill the sweep.
        except (ExtractionError, anthropic.AnthropicError, TypeError, OSError) as exc:
            logger.error("LLM batch extraction failed (%s); falling back to heuristic", exc)
            return set()
        from llm_extraction_prompts import PROMPT_VERSION
        source_contents = {sid: content for sid, _, content, _ in changed}
        with self.distiller.transaction():
            current = self._current_outputs(outputs, changed)
            _, ingested = ingest_extractions(
                self.distiller, {sid: output for sid, output in outputs.items() if sid in current},
                {sid: snapshot["path"] for sid, snapshot in current.items()}, source_contents=source_contents,
                extraction_info={"method": "anthropic_batch", "model": DEFAULT_MODEL,
                                 "prompt_version": PROMPT_VERSION})
        return ingested

    def _extract_ollama(self, changed: list[tuple[str, str, str, float]]) -> set[str]:
        """
        Extracts the given files via local Ollama chat models (zero API
        spend). Same contract as _extract_llm: returns the session_ids
        successfully ingested; callers run the heuristic path for the rest.
        """
        from llm_extractor import get_extraction_prompt, ingest_extractions
        try:
            from ollama_extractor import (
                extract_ollama,
                ollama_available,
                parse_chat_hosts,
            )
        except ImportError as exc:  # ollama-client not installed in this interpreter
            logger.error("Ollama extraction unavailable (%s); pip install ollama-client", exc)
            return set()
        try:
            hosts = parse_chat_hosts()
        except ValueError as exc:
            logger.error("Ollama extraction misconfigured (%s); skipping", exc)
            return set()
        if not ollama_available(hosts):
            logger.warning("No Ollama chat host reachable; skipping Ollama extraction")
            return set()

        prompts = {
            session_id: get_extraction_prompt(content, session_id, os.path.basename(fpath))
            for session_id, fpath, content, _ in changed
        }
        extraction_info = {}
        try:
            outputs = extract_ollama(prompts, hosts, extraction_info=extraction_info)
        except OSError as exc:
            logger.error("Ollama extraction failed (%s); falling back to heuristic", exc)
            return set()
        source_contents = {sid: content for sid, _, content, _ in changed}
        with self.distiller.transaction():
            current = self._current_outputs(outputs, changed)
            _, ingested = ingest_extractions(
                self.distiller, {sid: output for sid, output in outputs.items() if sid in current},
                {sid: snapshot["path"] for sid, snapshot in current.items()},
                source_contents=source_contents, extraction_info=extraction_info)
        return ingested

    def scan_and_consolidate(self) -> int:
        """
        Scans watch_dir for new or updated .md memory files and incrementally
        distills them (LLM batch first when enabled, heuristic fallback).
        Returns count of processed files.
        """
        changed = self._collect_changed()
        if self.async_batches:
            return self._durable_sweep(changed)
        if not changed:
            self._save_state()  # touched-but-unchanged mtimes still need persisting
            return 0

        llm_done: set[str] = set()
        if self.use_llm:
            llm_done = self._extract_llm(changed)
        if self.use_ollama:
            remaining = [c for c in changed if c[0] not in llm_done]
            if remaining:
                llm_done |= self._extract_ollama(remaining)

        processed = 0
        for session_id, fpath, content, mtime in changed:
            # Per-file guard: one failing ingest (store write error, malformed
            # content) must not kill the daemon or abandon the rest of the
            # sweep — same contract as the collect phase.
            try:
                if session_id in llm_done:
                    logger.info("LLM-extracted %s", os.path.basename(fpath))
                else:
                    if self.use_llm or self.use_ollama:
                        logger.warning("Heuristic fallback for %s", os.path.basename(fpath))
                    with self.distiller.transaction():
                        current = self._current_outputs({session_id: None}, [(session_id, fpath, content, mtime)])
                        if session_id not in current:
                            logger.warning("Source changed, disappeared or was excluded; deferring %s", session_id)
                            continue
                        self.distiller.ingest_session(
                            session_id=session_id,
                            title=f"Memory File {os.path.basename(fpath)}",
                            file_path=current[session_id]["path"],
                            content=content,
                        )
                self.file_timestamps[fpath] = mtime
                self.file_hashes[fpath] = {
                    "mtime": mtime,
                    "sha256": hashlib.sha256(content.encode("utf-8")).hexdigest(),
                }
                self.source_registry.mark_committed(session_id, self.file_hashes[fpath]["sha256"])
                processed += 1
            except Exception:
                logger.exception("Ingest failed for %s; will retry next sweep", fpath)

        self._save_state()
        logger.info("Consolidated %d memory file(s) into %s", processed, self.pyramid_path)
        return processed

    def _durable_sweep(self, changed):
        from napmem_jobs import JobQueue
        from llm_extractor import DEFAULT_MODEL
        from llm_extraction_prompts import PROMPT_VERSION
        queue = JobQueue(self.pyramid_path)
        backend = "anthropic" if self.use_llm else "heuristic"
        if queue.list("submitted"):
            if self._client is None:
                from llm_extractor import _make_client
                self._client = _make_client()
            queue.collect(self._client)
        receipts = queue.commit_ready(
            self.distiller, source_reader=lambda job: self.source_registry.read_current(
                job["session_id"], allowed_roots=self.allowed_roots))
        for receipt in receipts:
            if receipt["state"] == "committed":
                self.source_registry.mark_committed(receipt["session_id"], receipt["source_hash"])
        touched = {receipt["session_id"] for receipt in receipts if receipt["state"] == "committed"}
        for session_id, path, content, _ in changed:
            entry = self.source_registry.lookup(session_id=session_id)
            job = queue.enqueue(session_id=session_id, source_path=path, source_content=content,
                                scope=entry.get("scope"), backend=backend,
                                model=DEFAULT_MODEL if backend == "anthropic" else None,
                                prompt_version=PROMPT_VERSION, allowed_roots=self.allowed_roots)
            if job["enqueued"]:
                touched.add(session_id)
        if backend == "heuristic":
            queue.run(self.distiller)
            receipts = queue.commit_ready(self.distiller, source_reader=lambda job: self.source_registry.read_current(
                job["session_id"], allowed_roots=self.allowed_roots))
            for receipt in receipts:
                if receipt["state"] == "committed":
                    touched.add(receipt["session_id"])
                    self.source_registry.mark_committed(receipt["session_id"], receipt["source_hash"])
        elif queue.list("queued"):
            if self._client is None:
                from llm_extractor import _make_client
                self._client = _make_client()
            queue.submit(self._client)
        self._save_state()
        return len(touched)

    def run_loop(self, poll_interval_sec: int = 5, max_ticks: int = 1):
        """
        Runs the periodic scanning loop during agent idle states for max_ticks sweeps.
        """
        logger.info("Starting monitoring loop on '%s' every %ss for %s tick(s)...",
                    self.watch_dir, poll_interval_sec, max_ticks)
        ticks = 0
        while ticks < max_ticks:
            try:
                self.scan_and_consolidate()
            except Exception:
                logger.exception("Sweep failed; continuing on next tick")
            ticks += 1
            if ticks < max_ticks:
                time.sleep(poll_interval_sec)

def main():
    parser = argparse.ArgumentParser(description="Naptime Background Memory Consolidator.")
    parser.add_argument("--watch-dir", type=str, default="./memory_logs", help="Directory containing memory files.")
    parser.add_argument("--pyramid", type=str, default="napmem_pyramid.json", help="Path to pyramid JSON store.")
    parser.add_argument("--interval", type=int, default=5, help="Polling interval in seconds.")
    parser.add_argument("--max-ticks", type=int, default=10, help="Number of scan sweeps before exiting.")
    parser.add_argument("--once", action="store_true", help="Run single consolidation sweep and exit.")
    parser.add_argument("--extraction", choices=list(EXTRACTION_MODES), default="auto",
                        help="Extractor: llm (Batches API), ollama (local chat model, zero API "
                             "spend), heuristic, or auto (llm -> ollama -> heuristic).")
    parser.add_argument("--semantic-dedup", action="store_true",
                        help="Fold semantic near-duplicates via the embedding index.")
    parser.add_argument("--async-batches", action="store_true",
                        help="Persist jobs; submit cloud batches now and collect/commit in later sweeps.")
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(name)s] %(levelname)s: %(message)s")
    consolidator = NaptimeConsolidator(watch_dir=args.watch_dir, pyramid_path=args.pyramid,
                                       extraction=args.extraction,
                                       semantic_dedup=args.semantic_dedup,
                                       async_batches=args.async_batches)
    max_ticks = 1 if args.once else args.max_ticks
    consolidator.run_loop(poll_interval_sec=args.interval, max_ticks=max_ticks)

if __name__ == "__main__":
    main()
