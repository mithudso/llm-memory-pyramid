# Runbook: run the naptime consolidator

Recurring procedure for keeping a pyramid store consolidated from a directory
of memory files.

## One-off sweep

```bash
python3 naptime_consolidator.py --watch-dir ./memory_logs --pyramid napmem_pyramid.json --once
```

Extraction is `--extraction auto` by default: LLM extraction (one Batches API
batch per sweep, `claude-haiku-4-5`) when the `anthropic` package is
installed, heuristic otherwise. Force with `--extraction llm|heuristic`; add
`--semantic-dedup` to fold paraphrases via the embedding index. Startup logs
`Extraction mode: llm|heuristic`; any per-file LLM failure logs
`Heuristic fallback for <file>` and is still ingested.

## Background loop (bounded)

```bash
python3 naptime_consolidator.py --watch-dir ./memory_logs --interval 5 --max-ticks 720 \
  >> naptime.log 2>> naptime.err &
```

`--max-ticks 720` at `--interval 5` ≈ 1 hour, then clean exit. Re-launch from
cron/launchd for continuous operation; the loop is safe to restart (restart
re-ingests all files once — idempotent).

## Verify it worked

```bash
tail naptime.log                                    # expect "Consolidated N memory file(s)"
python3 napmem_retrieval_agent.py --stats           # session list should include new files
```

## Failure modes

| Symptom | Cause | Action |
|---|---|---|
| "Skipping memory file ... OSError" | File deleted mid-scan / unreadable | None — by design; fix permissions if persistent |
| "Skipping non-UTF-8 memory file" | Binary or wrongly-encoded file in watch dir | Convert to UTF-8 or remove |
| File never picked up | Not `.md`, or mtime unchanged | Rename to `.md` / `touch` the file |
| Two consolidators on one store | Lost updates (last write wins) | Run exactly one per store |

## Safety

Never run two consolidators against the same `--pyramid` path. Store writes
are crash-safe (atomic replace) — killing the process cannot corrupt the store.
