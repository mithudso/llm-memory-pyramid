# Testing

## Strategy

Plain `unittest`, two suites (`test_napmem_pipeline.py`,
`test_napmem_extensions.py`), 38 tests, no test dependencies, network-free:
extractor tests exercise parsing/validation offline, semantic tests force
`NAPMEM_EMBED_BACKEND=hashed`, and the MCP test drives the real server binary
over a subprocess pipe. Tests assert observable behavior on real pyramid
stores written to temp paths.

## Running

```bash
python3 -m unittest discover -s . -p "test_*.py"   # everything (CI command)
python3 test_napmem_pipeline.py                    # core suite only
python3 test_napmem_extensions.py                  # extensions suite only
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
- Extractor gate (`validate_unit`/`units_to_records`): invalid units rejected;
  LLM-extracted records honor stable-ID re-ingest semantics.
- Semantic dedup: fold with `paraphrase_text` anchor; off by default.
- MCP protocol: handshake, tool list, in-band tool errors, -32601 on unknown
  methods.
- Consolidator LLM wiring: auto-mode batch use, per-file heuristic fallback on
  batch error or invalid output, heuristic mode isolation (via a faked
  `anthropic` module — no network).
- Ollama failover: probe order prefers the first responding host; all-dead
  chain returns None.

## CI gate

`.github/workflows/ci.yml` runs compile check + the suite on Python 3.10,
3.12, and 3.14 for every push to `main` and every PR. The test job is the
merge gate; the ruff lint job is advisory.

Any behavior change ships with a test. Bug fixes ship with a regression test
that fails before the fix.
