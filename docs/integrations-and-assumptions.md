# Integrations and assumptions

## External services

None. No network calls, no SDKs, no subprocesses, no env vars.

The one *intended* integration point is an LLM extraction backend for
`llm_extraction_prompts.py` — not yet wired; the distiller uses its heuristic
extractor. When wired, that call becomes the repo's first external call and
must be added to `docs/external-calls.md` with logging, retry policy, and a
test.

## Hardcoded assumptions

- Store path defaults to `napmem_pyramid.json` in CWD (override: `--pyramid`).
- Watch dir defaults to `./memory_logs`; only `*.md` files are consolidated.
- Session IDs derive from file basenames (`sess_<basename>`); renaming a file
  creates a new session rather than replacing the old one.
- Token estimates use a fixed ~0.75 words/token ratio (`* 1.33`).
- Single-writer: exactly one consolidator/distiller process per store at a
  time; atomicity protects against crashes, not concurrent writers.
- Record ID format `rec_<session>_<NNN>` with 3-digit zero padding (grows past
  999 without collision — `isdigit()` parse, not fixed-width).

## Environment differences

None known — pure-stdlib code, exercised on macOS (dev) and ubuntu-latest
(CI), Python 3.10–3.14.
