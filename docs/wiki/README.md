# NapMem project wiki

Use Python 3.11+ and the default dependency-free offline CLI. Start with
[Installation](../INSTALLATION.md), [CLI](../CLI.md) and [Development](../DEVELOPMENT.md).

| Question | Maintained reference |
|---|---|
| What are the processes, stores and invariants? | [Architecture](../ARCHITECTURE.md), [Components](../COMPONENTS.md), [file map](../codebase-overview.md) |
| Which assertions can be recalled or approved? | [Retrieval](../RETRIEVAL.md), [Provenance](../PROVENANCE.md), [Controls](../CONTROLS.md) |
| How do jobs, snapshots and source identity work? | [Persistence](../PERSISTENCE.md), [Adapters](../ADAPTERS.md) |
| How do clients and the inspector behave? | [MCP](../MCP.md), [Inspector](../INSPECTOR.md) |
| Which commands verify a change? | [Testing](../TESTING.md), [Contributing](../../CONTRIBUTING.md) |
| What can leave the machine? | [Security](../SECURITY.md), [external calls](../external-calls.md), [integrations](../integrations-and-assumptions.md) |
| Where are logs, cache and status? | [Logging](../logging.md), [Observability](../OBSERVABILITY.md), [Caching](../caching-and-optimization.md) |
| How is a sweep operated or recovered? | [Runbook](../runbooks/run-naptime-consolidator.md), [deployment reference](../../deploy/README.md) |
| What is verified and what remains limited? | [Known issues](../known-issues.md), [bootstrap audit](../repo-bootstrap-audit-2026-11-12.md), [optimizer report](../code-deep-optimizer-2026-11-12.md) |
| What is the product direction? | [Roadmap](../product-roadmap-2026-10-27.md), [requirements](../requirements.md) |

Verified source commands: `python -m unittest discover -s . -p "test_*.py"`
(with the optional Ollama test extra), `ruff check .`,
`python -m compileall -q .`, `python scripts/repo_docs.py --check`,
`bash -n scripts/run-naptime.sh`, and the offline regression gate in Testing.
Refresh static maps with `python scripts/repo_docs.py`. Semantic generation,
service activation and private data imports require their own explicit scope.
