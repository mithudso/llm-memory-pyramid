#!/usr/bin/env python3
"""
Naptime Async Memory Consolidator

Implements background ("naptime") offline processing for LLM memory files.
Monitors memory files or session logs and incrementally re-ingests changed files
(each file maps to a stable session_id, so updates replace that session's records)
to keep the NapMem Pyramid updated without impacting active agent context or
response latency.
"""

import os
import time
import logging
import argparse
from typing import Dict
from memory_pyramid_distiller import MemoryPyramidDistiller

logger = logging.getLogger(__name__)

class NaptimeConsolidator:
    def __init__(self, watch_dir: str, pyramid_path: str = "napmem_pyramid.json"):
        self.watch_dir = watch_dir
        self.pyramid_path = pyramid_path
        self.distiller = MemoryPyramidDistiller(pyramid_path=pyramid_path)
        self.file_timestamps: Dict[str, float] = {}

    def scan_and_consolidate(self) -> int:
        """
        Scans watch_dir for new or updated .md memory files and incrementally distills them.
        Returns count of processed files.
        """
        processed_count = 0
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

                logger.info("Processing updated memory file: %s (mtime: %s)", fname, mtime)
                with open(fpath, "r", encoding="utf-8") as f:
                    content = f.read()

                self.distiller.ingest_session(
                    session_id=f"sess_{os.path.splitext(fname)[0]}",
                    title=f"Memory File {fname}",
                    file_path=fpath,
                    content=content
                )
                self.file_timestamps[fpath] = mtime
                processed_count += 1
            except OSError as exc:
                logger.error("Skipping memory file %s: %s", fpath, exc)
            except UnicodeDecodeError as exc:
                logger.error("Skipping non-UTF-8 memory file %s: %s", fpath, exc)

        if processed_count > 0:
            logger.info("Consolidated %d memory file(s) into %s", processed_count, self.pyramid_path)

        return processed_count

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
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(name)s] %(levelname)s: %(message)s")
    consolidator = NaptimeConsolidator(watch_dir=args.watch_dir, pyramid_path=args.pyramid)
    max_ticks = 1 if args.once else args.max_ticks
    consolidator.run_loop(poll_interval_sec=args.interval, max_ticks=max_ticks)

if __name__ == "__main__":
    main()
