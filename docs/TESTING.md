# Testing

## Setup and running

Install the package in a project virtual environment as described in
[Installation](INSTALLATION.md). The sanctioned shared `ollama-client`
dependency is required to import the extension suite. Anthropic is mocked.

```bash
source .venv/bin/activate
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

| Suite | Observable behavior |
|---|---|
| `test_napmem_pipeline.py` | Heuristic taxonomy, exact dedup, stable IDs, duplicate promotion, provenance, derived layers, sentinel neutralization |
| `test_napmem_extensions.py` | Schema gates and safe rejection logs, mocked extraction chains, sweep-state recovery, hashed embeddings, host failover, MCP subprocess integration |
| `test_napmem_failover.py` | Remote/local lifecycle with fake children, strict handshake replay, timeout and malformed-output recovery, mirror refresh configuration and atomicity |
| `test_napmem_regressions.py` | Reasserted metadata/wording, disposable cache validation, dimension changes, deletion/empty persistence, exact text hashes, result-count bounds |
| `test_napmem_protocol.py` | Protocol envelopes, silent notifications, bounded input reads, decoder failures and continued serving |
| `test_napmem_safety.py` | Prompt CPU deadline and extracted shell mirror function on isolated filesystem fixtures |

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
checks configured syntax/correctness rules. Both jobs must pass. CI reads the
shared library with the repository's `OLLAMA_CLIENT_DEPLOY_KEY` secret, at the same
Git revision pinned in `pyproject.toml`.

Local tests prove source behavior. They do not prove production deployment,
scheduler health, remote authentication, live Ollama quality or hook loading.
