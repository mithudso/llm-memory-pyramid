#!/usr/bin/env python3
"""
Naptime Async Memory Consolidator

Implements background ("naptime") offline processing for LLM memory files.
Monitors memory files or session logs and incrementally re-ingests changed files
(each file maps to a stable session_id, so updates replace that session's records)
to keep the NapMem Pyramid updated without impacting active agent context or
response latency.

Extraction modes (--extraction):
  auto      (default) LLM extraction when the `anthropic` package is
            importable, heuristic otherwise — decided once at startup.
  llm       Require LLM extraction; startup fails without `anthropic`.
  heuristic Always use the built-in keyword-rule extractor.

In LLM mode each sweep's changed files go out as ONE Message Batches API batch
(50% cost — naptime is idle-time work, latency is irrelevant). Any file whose
LLM extraction fails falls back to the heuristic extractor for that file, so
the pyramid never silently misses an update.
"""

import argparse
import logging
import os
import stat
import time

from memory_pyramid_distiller import MemoryPyramidDistiller

logger = logging.getLogger(__name__)

EXTRACTION_MODES = ("auto", "llm", "heuristic")

# Colon-separated list of directories memory files must RESOLVE into. When
# set, every file read is verified race-free (see _read_file_guarded) so a
# watched entry swapped into a symlink between scan and read cannot leak an
# out-of-root file's content into the extraction/embedding egress paths.
ALLOWED_ROOTS_ENV = "NAPMEM_ALLOWED_ROOTS"


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
    fd = os.open(path, os.O_RDONLY)
    try:
        if not stat.S_ISREG(os.fstat(fd).st_mode):
            raise PermissionError(f"{path}: not a regular file")
        real = _fd_true_path(fd) or os.path.realpath(path)
        if not any(real == root or real.startswith(root + os.sep)
                   for root in allowed_roots):
            raise PermissionError(f"{path}: resolves outside allowed roots ({real})")
        with os.fdopen(fd, "r", encoding="utf-8") as f:
            fd = -1  # ownership transferred to the file object
            return f.read()
    finally:
        if fd >= 0:
            os.close(fd)


def _allowed_roots_from_env() -> list[str]:
    raw = os.environ.get(ALLOWED_ROOTS_ENV, "")
    return [os.path.realpath(p) for p in raw.split(":") if p.strip()]


class NaptimeConsolidator:
    def __init__(self, watch_dir: str, pyramid_path: str = "napmem_pyramid.json",
                 extraction: str = "auto", semantic_dedup: bool = False):
        if extraction not in EXTRACTION_MODES:
            raise ValueError(f"extraction must be one of {EXTRACTION_MODES}")
        self.watch_dir = watch_dir
        self.pyramid_path = pyramid_path
        self.distiller = MemoryPyramidDistiller(pyramid_path=pyramid_path,
                                                semantic_dedup=semantic_dedup)
        self.file_timestamps: dict[str, float] = {}

        if extraction == "llm" and not _anthropic_available():
            raise RuntimeError(
                "--extraction llm requires the `anthropic` package: pip install anthropic"
            )
        self.use_llm = (extraction == "llm"
                        or (extraction == "auto" and _anthropic_available()))
        self._client = None
        self.allowed_roots = _allowed_roots_from_env()
        logger.info("Extraction mode: %s", "llm" if self.use_llm else "heuristic")
        if self.allowed_roots:
            logger.info("Read guard active; allowed roots: %s", self.allowed_roots)

    def _collect_changed(self) -> list[tuple[str, str, str, float]]:
        """Returns (session_id, fpath, content, mtime) for changed .md files."""
        changed = []
        os.makedirs(self.watch_dir, exist_ok=True)
        for fname in sorted(os.listdir(self.watch_dir)):
            if not fname.endswith(".md"):
                continue
            fpath = os.path.join(self.watch_dir, fname)
            # One bad file (deleted mid-scan, unreadable, undecodable) must not
            # kill the background loop; log it and keep consolidating the rest.
            try:
                mtime = os.path.getmtime(fpath)
                # Any mtime CHANGE counts as modified: a strictly-newer check
                # silently skips files restored with an older timestamp
                # (backup restore, rsync -t, git checkout).
                if fpath in self.file_timestamps and mtime == self.file_timestamps[fpath]:
                    continue
                if self.allowed_roots:
                    content = _read_file_guarded(fpath, self.allowed_roots)
                else:
                    with open(fpath, "r", encoding="utf-8") as f:
                        content = f.read()
                session_id = f"sess_{os.path.splitext(fname)[0]}"
                changed.append((session_id, fpath, content, mtime))
            except OSError as exc:  # includes PermissionError from the read guard
                logger.error("Skipping memory file %s: %s", fpath, exc)
            except UnicodeDecodeError as exc:
                logger.error("Skipping non-UTF-8 memory file %s: %s", fpath, exc)
        return changed

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
        if self._client is None:
            self._client = anthropic.Anthropic()

        prompts = {
            session_id: get_extraction_prompt(content, session_id, os.path.basename(fpath))
            for session_id, fpath, content, _ in changed
        }
        file_paths = {session_id: fpath for session_id, fpath, _, _ in changed}
        try:
            outputs = extract_batch(self._client, prompts, DEFAULT_MODEL)
        # TypeError included deliberately: the SDK raises it at call time when
        # no credential resolves (missing ANTHROPIC_API_KEY and no `ant auth`
        # profile) — that must degrade to the heuristic, not kill the sweep.
        except (ExtractionError, anthropic.AnthropicError, TypeError, OSError) as exc:
            logger.error("LLM batch extraction failed (%s); falling back to heuristic", exc)
            return set()
        _, ingested = ingest_extractions(self.distiller, outputs, file_paths)
        return ingested

    def scan_and_consolidate(self) -> int:
        """
        Scans watch_dir for new or updated .md memory files and incrementally
        distills them (LLM batch first when enabled, heuristic fallback).
        Returns count of processed files.
        """
        changed = self._collect_changed()
        if not changed:
            return 0

        llm_done: set[str] = set()
        if self.use_llm:
            llm_done = self._extract_llm(changed)

        for session_id, fpath, content, mtime in changed:
            if session_id in llm_done:
                logger.info("LLM-extracted %s", os.path.basename(fpath))
            else:
                if self.use_llm:
                    logger.warning("Heuristic fallback for %s", os.path.basename(fpath))
                self.distiller.ingest_session(
                    session_id=session_id,
                    title=f"Memory File {os.path.basename(fpath)}",
                    file_path=fpath,
                    content=content,
                )
            self.file_timestamps[fpath] = mtime

        logger.info("Consolidated %d memory file(s) into %s", len(changed), self.pyramid_path)
        return len(changed)

    def run_loop(self, poll_interval_sec: int = 5, max_ticks: int = 1):
        """
        Runs the periodic scanning loop during agent idle states for max_ticks sweeps.
        """
        logger.info("Starting monitoring loop on '%s' every %ss for %s tick(s)...",
                    self.watch_dir, poll_interval_sec, max_ticks)
        ticks = 0
        while ticks < max_ticks:
            self.scan_and_consolidate()
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
                        help="Extractor: llm (Batches API), heuristic, or auto (llm when available).")
    parser.add_argument("--semantic-dedup", action="store_true",
                        help="Fold semantic near-duplicates via the embedding index.")
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(name)s] %(levelname)s: %(message)s")
    consolidator = NaptimeConsolidator(watch_dir=args.watch_dir, pyramid_path=args.pyramid,
                                       extraction=args.extraction,
                                       semantic_dedup=args.semantic_dedup)
    max_ticks = 1 if args.once else args.max_ticks
    consolidator.run_loop(poll_interval_sec=args.interval, max_ticks=max_ticks)

if __name__ == "__main__":
    main()
