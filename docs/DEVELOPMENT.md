# Development

## Setup

None. Clone and run — Python 3.10+ standard library only, no virtualenv, no
install step.

```bash
git clone https://github.com/mithudso/llm-memory-pyramid.git
cd llm-memory-pyramid
python3 -m unittest discover -s . -p "test_*.py"   # verify: 38 tests, OK
```

## Commands

| Command | Purpose |
|---|---|
| `python3 -m unittest discover -s . -p "test_*.py"` | Run all tests |
| `python3 llm_extractor.py --input <f.md> [--no-batch\|--dry-run\|--semantic-dedup]` | LLM extraction (Batches API; needs `anthropic`) |
| `python3 semantic_index.py --rebuild` / `--query <q>` | Manage/query the embedding index |
| `python3 napmem_retrieval_agent.py --query <q> --semantic --top-k 5` | Embedding cosine search |
| `python3 napmem_mcp_server.py --pyramid <p.json>` | Run the MCP stdio server |
| `python3 memory_pyramid_distiller.py --input <file.md>` | Distill one file into the pyramid |
| `python3 memory_pyramid_distiller.py` | Render current pyramid summary |
| `python3 naptime_consolidator.py --watch-dir ./memory_logs --once` | One consolidation sweep |
| `python3 naptime_consolidator.py --interval 5 --max-ticks 10` | Polling loop |
| `python3 napmem_retrieval_agent.py --query <q> [--layer profiles\|tracks\|records\|all]` | Search |
| `python3 napmem_retrieval_agent.py --provenance <record_id>` | Provenance lookup |
| `python3 napmem_retrieval_agent.py --stats` | Token-savings stats |
| `python -m compileall -q .` | Compile check (CI runs this) |

All tools accept `--pyramid <path>` to target a non-default store.

## Environment variables

All optional — table in `docs/integrations-and-assumptions.md`
(`NAPMEM_EMBED_BACKEND`, `NAPMEM_OLLAMA_URL`, `NAPMEM_OLLAMA_MODEL`,
`NAPMEM_PYRAMID`; `ANTHROPIC_API_KEY` resolved by the SDK, never read
directly). Core pipeline needs none.

## Workflow

1. Branch from `main`.
2. Make the change; add/extend a `unittest` test in `test_napmem_pipeline.py`.
3. Run the suite; keep it green.
4. Update `docs/` if architecture, commands, or components changed.
5. PR with the template; CI (tests on 3.10/3.12/3.14 + advisory ruff) must pass.

## Troubleshooting

- **`FileNotFoundError: Pyramid file ... not found`** — retrieval agent needs
  an existing store; run the distiller first.
- **Records seem duplicated after editing a memory file** — check the session
  id: re-ingest replacement only happens for the *same* `session_id`
  (`sess_<basename>` by default). Renamed files create new sessions.
- **Consolidator skips a file** — non-`.md` extensions are ignored; unreadable
  or non-UTF-8 files are logged and skipped.
