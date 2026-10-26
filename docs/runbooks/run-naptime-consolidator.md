# Runbook: run the naptime consolidator

Recurring procedure for keeping a pyramid store consolidated from a directory
of memory files.

## One-off sweep

```bash
python3 naptime_consolidator.py --watch-dir ./memory_logs --pyramid napmem_pyramid.json --once
```

Activate the installed project virtual environment first. Extraction defaults
to `auto`: Anthropic when installed, then Ollama, then heuristics per file.
Use `--extraction ollama` to avoid Anthropic calls, or `--extraction heuristic`
with `NAPMEM_EMBED_BACKEND=hashed` for an offline sweep. `--semantic-dedup`
enables optional paraphrase folding and may contact embedding hosts.

## Scheduled operation

**The canonical consolidator runs on the Linux box via systemd** — see
[`deploy/README.md`](../../deploy/README.md) and
[deployment-topology.md](../deployment-topology.md). Run exactly one
consolidator per pyramid store fleet-wide. The launchd variant below remains
for macOS-local stores.

### launchd (macOS)

`scripts/run-naptime.sh` is the launchd entry point: one sweep per firing
over `~/.napmem/memory_logs` into `~/.napmem/napmem_pyramid.json`
(`NAPMEM_HOME` overrides the data dir), `--semantic-dedup` enabled.
Configure SDK-supported Anthropic credentials only when that backend is
intended. The wrapper does not load login profiles. Optional scheduler
locations below are deployment references; inspect them on the target host
before starting a job.

Agent plist: `~/Library/LaunchAgents/com.mithudso.napmem-consolidator.plist`
(hourly `StartInterval`, `RunAtLoad`, logs to `~/.napmem/naptime.{log,err}`).
A single launchd label serializes its own runs. Other labels, manual commands
and other hosts can still overlap; enforce one writer fleet-wide.

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
cron/launchd for continuous operation; the loop is safe to restart (persisted
mtime/sha256 state skips unchanged files when their source session still exists).

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

## Recovery and escalation

If extraction fails, inspect the fallback log and confirm the intended mode.
If the store cannot save, repair filesystem permissions or free disk space
before retrying. Keep a backup; do not remove production state to test recovery.
If SSH fails, the MCP proxy can serve a stale local mirror; verify the age note.
Escalate repeated validation or write failures to the operator with metadata
only, never source memory or credentials.
