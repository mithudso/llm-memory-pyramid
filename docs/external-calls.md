# External calls

## Inventory

**None.** Verified by inspection: no `urllib`/`http`/`socket` usage, no
`subprocess`, no SDK clients, no env-var reads. All I/O is local filesystem
(store JSON, watched memory files).

Consequently the 5-standard auto-remediation contract (CLI trigger,
centralized error log, auto-remediation map, dashboard card, datastore
verification) has an empty scope, and the operations-registry infrastructure
is intentionally not present.

## Watchlist

The first external call will be the LLM extraction backend for
`llm_extraction_prompts.py` (currently unwired). When added, register it here
with: file:line, target, transport, error handling, retry policy, logging, and
a test — and stand up the operations registry at that point.
