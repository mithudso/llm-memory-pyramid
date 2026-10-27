# Installation

## Prerequisites

Python 3.11+. CI tests Python 3.11, 3.12 and 3.14. The default installation has
no runtime dependencies. Offline ingestion, retrieval, diagnostics, jobs and
snapshots require no private Git access, API credentials or model server.

## Install

```bash
git clone https://github.com/mithudso/llm-memory-pyramid.git
cd llm-memory-pyramid
python3 -m venv .venv
.venv/bin/python -m pip install -e .
source .venv/bin/activate
```

For Anthropic extraction, install the optional SDK with
`.venv/bin/python -m pip install -e '.[llm]'`. Configure credentials supported
by that SDK. This repo constructs its client without a custom login-profile
adapter. An Ollama server is needed only for chat extraction or real
embeddings. Install `.[ollama]` to enable the pinned shared client; that optional
extra requires access to its private repository. Installation and offline tests
do not start or query a model server. See [CLI configuration](CLI.md).

## Verify

```bash
NAPMEM_EMBED_BACKEND=hashed python3 -m unittest discover -s . -p "test_*.py"
napmem --pyramid /tmp/napmem-verification/store.json demo
napmem --pyramid /tmp/napmem-verification/store.json doctor
```

Expect all discovered tests to pass, then a summary of the temporary store.
The tests mock remote transports and use temporary stores. The checked-in
example store is separate from production.

## Upgrade

```bash
git pull --ff-only
.venv/bin/python -m pip install -e .
NAPMEM_EMBED_BACKEND=hashed .venv/bin/python -m unittest discover -s . -p "test_*.py"
```

The package version lives in `pyproject.toml`. It is separate from the store
format (`2.0.0`), MCP server version and workflow-log version. Existing stores
migrate in memory on load; the next authorized write persists v2. IDs remain
stable, unknown scope stays `legacy`, and missing evidence stays unverified.
Migration does not start a service or modify a production store by itself.

## Uninstall

Remove the virtual environment and checkout. Custom pyramid stores, their
`.embindex.json` and `.sweepstate.json` siblings, and any local mirror remain
until explicitly removed. Stop any separately installed scheduler first;
see [deployment](../deploy/README.md).
