# Logging

## Runtime sinks

Runtime modules use stdlib `logging` and module-level loggers. CLI tools print
results to stdout. MCP reserves stdout for protocol messages and logs to
stderr. The consolidator configures INFO logs as
`%(asctime)s [%(name)s] %(levelname)s: %(message)s`. Scheduler redirection is
in [the runbook](runbooks/run-naptime-consolidator.md).

| Path | Events |
|---|---|
| Consolidator | Selected extraction chain, guarded-read rejection, unreadable file, cache rejection, per-file fallback and sweep counts |
| Anthropic extractor | Request/batch outcome and usage, fixed validation rejection categories, successful ingest counts |
| Ollama extractor | Configured model attempt, model/down-host failure, selected fallback |
| Embedding index | Backend selection, cache discard, embedding failures through caller |
| MCP server | Startup, malformed request/input-bound warnings, tool failures and pipe closure |
| Failover proxy | Backend spawn/exit, timeout, local restart, mirror success/failure |

## Sensitive data policy

Log paths, unit positions, counts, error categories and state transitions.
Never include memory text, prompt payloads, rejected units, model responses,
credentials or authentication headers. Rejection reasons use fixed categories
rather than arbitrary invalid field values. Treat host/path metadata as private
when sharing logs. Configure external SDK logging with the same care.

Regression tests capture safe rejection/cache/fallback events and assert that
synthetic sensitive markers stay absent. Transport mocks prevent tests from
sending memory to configured operator services.

## Limits

This repository does not implement a centralized JSONL error service, dashboard
or automatic remediator. Logs describe the local process; deployed systemd or
launchd log collection is a separate operator concern. Fatal store-write
failures can propagate from batch ingestion: continuing without rolling back
mutated in-memory state could hide a failed commit.
