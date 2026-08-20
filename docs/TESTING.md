# Testing

## Strategy

Plain `unittest`, single suite in `test_napmem_pipeline.py`, no test
dependencies. Tests assert observable behavior on real pyramid stores written
to temp paths — extraction output, dedup folds, ID stability across
re-ingestion, duplicate promotion, provenance resolution, prompt-guard
neutralization.

## Running

```bash
python3 test_napmem_pipeline.py        # direct
python3 -m unittest -v                 # discovery, verbose
```

## Coverage target

Meaningful coverage of important and changed/risky paths with real assertions
on behavior — explicitly **not** a blanket 100%-line mandate. The risky paths
in this codebase, all covered and to stay covered:

- Session reconciliation (`_reconcile_session_records`): re-asserted text
  keeps IDs; stale canonical dropped; duplicate promoted to canonical;
  renumbering after highest surviving suffix.
- Dedup (`deduplicate_and_merge`): fold + `duplicate_anchors` preservation.
- Provenance (`inspect_provenance`): canonical and duplicate-ID resolution.
- Prompt guards (`_neutralize_sentinel`): nested-sentinel reconstitution.

## CI gate

`.github/workflows/ci.yml` runs compile check + the suite on Python 3.10,
3.12, and 3.14 for every push to `main` and every PR. The test job is the
merge gate; the ruff lint job is advisory.

Any behavior change ships with a test. Bug fixes ship with a regression test
that fails before the fix.
