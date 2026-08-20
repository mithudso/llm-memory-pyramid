# Installation

## Prerequisites

- Python 3.10 or newer (CI tests 3.10, 3.12, 3.14). No other dependencies.

## Install

```bash
git clone https://github.com/mithudso/llm-memory-pyramid.git
cd llm-memory-pyramid
```

There is no package to install — the tools run directly from the checkout.

## Verify

```bash
python3 test_napmem_pipeline.py
# Expected: "Ran 9 tests ... OK"

python3 memory_pyramid_distiller.py --input sample_agent_memory.md --pyramid /tmp/verify_pyramid.json
# Expected: "Successfully distilled N atomic units ..." plus a markdown summary
```

## Upgrade

```bash
git pull
python3 test_napmem_pipeline.py
```

The store format carries a `version` field; current stores are `1.0.0`. Format
migrations, if ever needed, will be documented here.

## Uninstall

Delete the checkout. The only state outside it is any pyramid store JSON you
created at custom `--pyramid` paths.
