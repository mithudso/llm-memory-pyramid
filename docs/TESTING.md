# Testing

## Setup and running

Install the package in a project virtual environment as described in
[Installation](INSTALLATION.md). The full compatibility suite exercises the
sanctioned shared `ollama-client` integration and requires the `ollama` extra.
Anthropic is mocked. Fresh offline acceptance runs without either optional
client; `test_napmem_optional_client.py` also blocks private-client imports.

```bash
source .venv/bin/activate
# Full integration-contract suite only (requires private client access):
python -m pip install -e '.[ollama]'
NAPMEM_EMBED_BACKEND=hashed python3 -m unittest discover -s . -p "test_*.py"
python3 -m compileall -q .
ruff check .
python3 scripts/repo_docs.py --check
bash -n scripts/run-naptime.sh
```

All discovered tests must pass. There is no fixed test-count or numeric line
coverage gate. Ruff is a development/CI tool, pinned in the workflow; it is
not a runtime dependency.

## Suites and risky paths

| Suite | Cases | Observable behavior |
|---|---:|---|
| `test_napmem_adapters.py` | 16 | Synthetic, offline source interoperability and control-replay acceptance. |
| `test_napmem_cli.py` | 25 | Portable configuration and CLI behavior against synthetic temporary stores. |
| `test_napmem_controls.py` | 21 | Pure replay, deletion-family and operator-preview tests. |
| `test_napmem_controls_integration.py` | 9 | Operator controls remain effective across ingestion, cache and reload boundaries. |
| `test_napmem_eval.py` | 17 | Deterministic, network-free evidence scorer and benchmark contract tests. |
| `test_napmem_evidence.py` | 26 | Offline tests for literal source binding and explicitly allowed file checks. |
| `test_napmem_evidence_extraction.py` | 16 | Offline checks for exact extraction inputs and untrusted model quotations. |
| `test_napmem_evidence_forget.py` | 13 | Forgetting erases literal source evidence without deleting unrelated facts. |
| `test_napmem_extensions.py` | 58 | Tests for the production-path extensions: LLM extractor parsing/validation, |
| `test_napmem_failover.py` | 22 | Tests for napmem_mcp_failover.py — the remote-SSH / local-mirror MCP proxy. |
| `test_napmem_inspector.py` | 31 | Offline operator inspection, provenance boundaries and exact budgets. |
| `test_napmem_jobs.py` | 16 | Offline durable queue, lease, cloud-resume and atomic-commit tests. |
| `test_napmem_lifecycle.py` | 7 | Integration gates for compatible scoped assertion ingestion. |
| `test_napmem_maintenance.py` | 34 | Synthetic adversarial maintenance regressions; no providers or live stores. |
| `test_napmem_mcp_contract.py` | 22 | Typed MCP contracts, strict pre-load validation and complete wire budgets. |
| `test_napmem_metrics.py` | 30 | Content-free local metrics, retention and strictly read-only status tests. |
| `test_napmem_model.py` | 24 | Pure scoped assertion, migration and derived-view tests. |
| `test_napmem_optional_client.py` | 5 | Offline core acceptance with the optional Ollama package made unimportable. |
| `test_napmem_pipeline.py` | 9 | Integration test for NapMem + Document Distiller Memory Pipeline |
| `test_napmem_protocol.py` | 9 | Offline regressions for the stdlib MCP protocol boundary. |
| `test_napmem_provenance.py` | 6 | Source proof, profile admission and explicit re-verification at public boundaries. |
| `test_napmem_regressions.py` | 16 | Offline regression checks for store reconciliation and disposable caches. |
| `test_napmem_retrieval_contract.py` | 8 | Public retrieval adapters preserve scope, offline defaults and budgets. |
| `test_napmem_safety.py` | 4 | Offline regressions for prompt CPU bounds and wrapper filesystem safety. |
| `test_napmem_search.py` | 24 | Offline search safety, ranking and exact serialized-budget tests. |
| `test_napmem_snapshots.py` | 19 | Offline snapshot, checksum and atomic mirror generation tests. |
| `test_napmem_sources.py` | 16 | Offline stable identity, guarded collection and source lifecycle tests. |
| `test_napmem_transactions.py` | 21 | Single-host writer isolation, commit boundaries and stale-reader privacy. |
| `test_napmem_trusted_loop.py` | 2 | Actual offline CLI/MCP loop from scoped sources through correction and restore. |

Tests use temporary stores, hashed vectors, mocked HTTP/SDK calls and local
fake child processes. The wrapper test extracts `mirror()` without running
its scheduling or source-discovery path. No test needs production data, SSH,
a model server, embeddings or an API credential. Tests that alter the
environment must restore the prior values. Do not parallelize these suites
inside one process: mocks and environment overrides are process-global.

## Coverage target

Meaningful coverage of important and changed/risky paths with assertions on
results, filesystem effects, protocol responses and safe logs. A regression
must fail before its fix. Tests must preserve each store invariant; avoid
assertion-free coverage work or a blanket 100% line mandate. The prompt CPU
test runs its adversarial case in a child with a generous deadline so the
old quadratic implementation cannot wedge the runner.

## CI gates

`.github/workflows/ci.yml` runs compilation, unittest discovery, generated-map
checks and shell syntax on Python 3.11, 3.12 and 3.14. A separate Ruff job
checks configured syntax/correctness rules. All five trusted-PR jobs must pass. Fork PRs run lint and the core-only install/test job; private-client integration is explicitly skipped. CI reads the
shared library with the repository's `OLLAMA_CLIENT_DEPLOY_KEY` secret, at the same
Git revision pinned in `pyproject.toml`.

The separate offline-install job installs the core wheel without extras and
runs real console commands outside the checkout. No private deploy key is
available to that job. Local acceptance receipts record its equivalent checks.

Local tests prove source behavior. They do not prove production deployment,
scheduler health, remote authentication, live Ollama quality or hook loading.

## Whole-process isolation

CI installs declared dependencies before executing tests. Ubuntu test/evaluation
and installed-CLI steps use `sudo unshare --net` with no interfaces enabled,
including loopback. `env -i` supplies only PATH and fresh HOME, TMPDIR,
XDG config/cache/data, auth and model roots, with offline/hashed mode. A proof
checks parent and spawned-child loopback/external denial before the full suite.
No cached model computation is an acceptable substitute for a provider mock.

The 2026-11-12 macOS maintenance run used `sandbox-exec` network denial for
all descendants and proved parent/child denial plus a separate proof-only owned
fixture exception. The actual suite allowed no endpoints. Baseline:486 tests,
one reproducible failover timing failure. Final counts and commands are in the
[optimizer report](code-deep-optimizer-2026-11-12.md). This verifies fixtures,
protocols, local subprocesses and installed packaging, not production services.

## Offline evaluation eligibility

`memory_quality_v1.json` has100 dev and100 heldout synthetic cases. The
must-pass surface is the normal suite, compilation, Ruff, maps, shell syntax
and frozen `hybrid_regression_v2.json` gate. Run development evaluation with
`python napmem_eval.py --mode hybrid --split dev`; the heldout regression
command is `python napmem_eval.py --mode hybrid --split heldout --check-baseline evaluations/hybrid_regression_v2.json`.
No tests/evals invoke real SDK, model, embedding, SSH or external APIs. The
historically reused heldout set is regression evidence, not a fresh blind
quality estimate. This run preserves the fixture and threshold bytes, performs
no model benchmark or global champion promotion, and makes no quality-gain claim.
