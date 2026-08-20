# AGENTS.md

Guidance for coding agents working in this repository. No repo-local subagents
are defined; this file carries the shared agent contract.

## Contract

- Run `python3 test_napmem_pipeline.py` before claiming any change works; all 9
  tests must pass.
- Standard library only — do not add dependencies without operator approval.
- Respect the invariants in [CLAUDE.md](CLAUDE.md): stable record IDs across
  re-ingestion, atomic store writes, exact-text dedup with resolvable duplicate
  anchors, derived Layers 2–3, sentinel-guarded prompt interpolation.
- Log completed work in `memory.md`; log the triggering request in `prompts.md`.

## Repo-local agents

None. If one is added, catalog it here with: name, scope, when-to-use, tools.
