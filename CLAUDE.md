# CLAUDE.md

Guidance for Claude Code when working in this repository.

## Project

NapMem — a 4-layer LLM memory pyramid (raw sessions → atomic records → topic
tracks → profiles) with incremental re-ingestion, dedup with provenance, and
active retrieval tools. Pure Python 3.10+ standard library; no dependencies, no
network calls, no build step.

## Commands

```bash
python3 test_napmem_pipeline.py                                  # run tests (must stay green)
python3 memory_pyramid_distiller.py --input <file.md>            # distill a memory file
python3 naptime_consolidator.py --watch-dir ./memory_logs --once # one consolidation sweep
python3 napmem_retrieval_agent.py --query <q> --layer all        # query the pyramid
```

## Architecture in one paragraph

`memory_pyramid_distiller.py` owns the store (`napmem_pyramid.json`, atomic
writes via tmp+`os.replace`). `ingest_session()` is the single write path:
extract → reconcile prior generation of the session → dedup/merge → rebuild
Layers 2–3 → save. `naptime_consolidator.py` maps each watched `.md` file to a
stable `sess_<basename>` session id and re-ingests on any mtime change.
`napmem_retrieval_agent.py` is read-only. `llm_extraction_prompts.py` holds the
production LLM extraction prompt (the distiller's heuristic extractor is its
deterministic stand-in).

## Invariants — do not break

- **Record IDs are stable across re-ingestion.** Re-asserted text keeps its ID;
  new units number after the session's highest surviving suffix
  (`_next_unit_number`). Never renumber from 1.
- **Dedup is exact-text (lowercased, stripped).** Duplicate IDs must stay
  resolvable via `duplicate_anchors`; a duplicate from another session can be
  promoted to canonical when its session's text disappears.
- **Store writes are atomic** (`save()`); never write the store directly.
- **Untrusted content stays data.** Extraction prompts wrap source text in the
  sentinel delimiter with loop-neutralization (`_neutralize_sentinel`); never
  interpolate raw text or metadata outside the guarded region.
- Layers 2–3 are derived state — always rebuilt from Layer 1, never edited.

## Conventions

- stdlib only; adding a dependency is an architecture decision, ask first.
- `logging` module for runtime output in daemons; CLI tools print to stdout.
- Tests are plain `unittest` in `test_napmem_pipeline.py`; add tests for any
  behavior change, especially reconciliation edge cases.
- Update `memory.md` (work log) and `prompts.md` (request log) each session.

## Docs map

`docs/` carries the full suite: ARCHITECTURE, COMPONENTS, DEVELOPMENT,
TESTING, SECURITY, INSTALLATION, codebase-overview, high_signal_file_index.json,
known-issues, onboarding. Keep `docs/codebase-overview.md` and the file index
current after adding or moving files.
