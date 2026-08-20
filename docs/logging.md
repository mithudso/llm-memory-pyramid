# Logging

## Approach

Stdlib `logging`, module-level loggers. The long-running component
(`naptime_consolidator.py`) logs; short-lived CLI tools (distiller, retrieval
agent) print results to stdout and errors to stderr with non-zero exit.

Format (set in `naptime_consolidator.main()`):
`%(asctime)s [%(name)s] %(levelname)s: %(message)s`, level INFO.

## What gets logged (audit)

| Path | Level | Event |
|---|---|---|
| Consolidator loop start | INFO | watch dir, interval, tick count |
| File picked up | INFO | filename + mtime |
| Sweep summary | INFO | processed count + store path |
| Unreadable file (`OSError`) | ERROR | path + exception — loop continues |
| Non-UTF-8 file (`UnicodeDecodeError`) | ERROR | path + exception — loop continues |
| Distiller missing input | stderr + exit 1 | path |

No silent failure paths: every `except` branch logs before continuing. Error
logging is exercised by the test suite (bad-file isolation test).

## Sensitive data rules

- Log **paths and metadata only** — never memory-file *content* (memory files
  may contain personal/user data).
- No secrets exist in this codebase (no credentials, tokens, or env vars).

## Future

When the LLM extraction path is wired, the request/outcome of each LLM call
must be logged (without prompt content above DEBUG) and added to
`docs/external-calls.md`.
