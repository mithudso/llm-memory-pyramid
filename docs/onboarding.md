# Onboarding

New-contributor walkthrough — 15 minutes to productive.

## 1. Run it (2 min)

```bash
git clone https://github.com/mithudso/llm-memory-pyramid.git
cd llm-memory-pyramid
python3 -m unittest discover -s . -p "test_*.py"       # 38 tests, OK
python3 memory_pyramid_distiller.py --input sample_agent_memory.md --pyramid /tmp/onboard.json
python3 napmem_retrieval_agent.py --pyramid /tmp/onboard.json --stats
```

## 2. Read in this order (10 min)

1. `README.md` — what the pyramid is.
2. `docs/ARCHITECTURE.md` — data flow of `ingest_session()` and the 5 ADRs.
3. `memory_pyramid_distiller.py` — the whole system is ~380 lines; read
   `ingest_session()` top-down, then `_reconcile_session_records()` (the
   subtle part: stable IDs + duplicate promotion).
4. `test_napmem_pipeline.py` — the tests are executable documentation of the
   reconciliation edge cases.

## 3. Rules of the road

- Stdlib only; tests green before any claim of "works"; invariants in
  `CLAUDE.md` are load-bearing.
- Good first contributions: semantic dedup experiments, wiring the LLM
  extractor, persisted consolidator watermark (see `docs/known-issues.md`).

## 4. Where things live

`docs/codebase-overview.md` maps every file;
`docs/high_signal_file_index.json` is the machine-readable version.
