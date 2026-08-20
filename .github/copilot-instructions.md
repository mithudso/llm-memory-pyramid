## Default Execution Strategy

Work directly and verify with the test suite. This is a pure-stdlib Python
project with no build step: edit, then run `python3 test_napmem_pipeline.py`
(all 9 tests must pass) before reporting success.

## Project rules

- Python 3.10+ standard library only; never add dependencies unprompted.
- Core invariants (see CLAUDE.md for detail): record IDs are stable across
  session re-ingestion; store writes are atomic via `save()`; dedup is
  exact-text with resolvable `duplicate_anchors`; Layers 2–3 are derived from
  Layer 1 and never edited directly; untrusted text stays inside the sentinel
  delimiter in extraction prompts.
- Add or extend `unittest` tests in `test_napmem_pipeline.py` for any behavior
  change.
- Log completed work in `memory.md` and the triggering request in `prompts.md`.
