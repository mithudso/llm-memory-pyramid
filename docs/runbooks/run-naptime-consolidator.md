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

## Scheduled operation (launchd — the production setup)

`scripts/run-naptime.sh` is the launchd entry point: one sweep per firing
over `~/.napmem/memory_logs` into `~/.napmem/napmem_pyramid.json`
(`NAPMEM_HOME` overrides the data dir), `--semantic-dedup` enabled.
Credentials resolve from the operator's `ant auth login` OAuth profile — no
key in the plist or script; without a profile the sweep degrades to the
heuristic extractor.

Agent plist: `~/Library/LaunchAgents/com.mithudso.napmem-consolidator.plist`
(hourly `StartInterval`, `RunAtLoad`, logs to `~/.napmem/naptime.{log,err}`).
launchd never starts a second instance of the same label, so overlapping
sweeps — the one-writer-per-store hazard — cannot occur.

```bash
launchctl bootstrap "gui/$(id -u)" ~/Library/LaunchAgents/com.mithudso.napmem-consolidator.plist   # install
launchctl kickstart "gui/$(id -u)/com.mithudso.napmem-consolidator"                                 # run now
launchctl print "gui/$(id -u)/com.mithudso.napmem-consolidator" | head -20                          # inspect
launchctl bootout "gui/$(id -u)/com.mithudso.napmem-consolidator"                                   # uninstall
tail ~/.napmem/naptime.log                                                                          # verify
```

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
