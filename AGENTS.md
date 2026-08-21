# AGENTS.md

Guidance for coding agents working in this repository. No repo-local subagents
are defined; this file carries the shared agent contract.

## Contract

- Run `python3 -m unittest discover -s . -p "test_*.py"` before claiming any change works; all 38
  tests must pass.
- Core is stdlib-only; sanctioned optional extras are `anthropic` (lazy) and Ollama over HTTP. Further dependencies need operator approval.
- Respect the invariants in [CLAUDE.md](CLAUDE.md): stable record IDs across
  re-ingestion, atomic store writes, exact-text dedup with resolvable duplicate
  anchors, derived Layers 2–3, sentinel-guarded prompt interpolation.
- Log completed work in `memory.md`; log the triggering request in `prompts.md`.

## Repo-local agents

None. If one is added, catalog it here with: name, scope, when-to-use, tools.
