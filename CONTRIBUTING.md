# Contributing

Thanks for contributing! The bar is simple:

1. **No new dependencies.** The package targets Python 3.11+. Core code stays stdlib-only;
   sanctioned integrations are `ollama-client` and the optional `anthropic` SDK.
   Proposing a dependency is an architecture discussion — open an issue first.
2. **Tests must pass.** `python3 -m unittest discover -s . -p "test_*.py"` before every PR.
   Add a test for any behavior change; reconciliation and dedup edge cases
   especially.
3. **Preserve the invariants** listed in [CLAUDE.md](CLAUDE.md): stable record
   IDs across re-ingestion, atomic store writes, exact-text dedup with
   resolvable duplicate anchors, derived Layers 2–3, sentinel-guarded prompt
   interpolation.
4. **Update docs** in `docs/` when architecture, commands, or components
   change. Keep `docs/codebase-overview.md` and
   `docs/high_signal_file_index.json` current if files are added or moved.

## Workflow

- Branch from `main`, open a PR using the template.
- CI runs compile check + tests on Python 3.11/3.12/3.14 and Ruff
  lint. Both jobs must be green to merge. See [development](docs/DEVELOPMENT.md).
