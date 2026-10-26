# Installation

## Prerequisites

Python 3.11+ and Git access to the shared `mithudso/ollama-client` repository.
CI tests Python 3.11, 3.12 and 3.14. Core distillation and substring retrieval
use the standard library. The package includes `ollama-client` for Ollama paths.

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
embeddings; installation and offline tests do not start or query one.

## Verify

```bash
NAPMEM_EMBED_BACKEND=hashed python3 -m unittest discover -s . -p "test_*.py"
python3 memory_pyramid_distiller.py --input sample_agent_memory.md --pyramid /tmp/verify_pyramid.json
python3 napmem_retrieval_agent.py --pyramid /tmp/verify_pyramid.json --stats
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
format (`1.0.0`), MCP server version and workflow-log version. Store migrations,
if needed, will be documented here.

## Uninstall

Remove the virtual environment and checkout. Custom pyramid stores, their
`.embindex.json` and `.sweepstate.json` siblings, and any local mirror remain
until explicitly removed. Stop any separately installed scheduler first;
see [deployment](../deploy/README.md).
