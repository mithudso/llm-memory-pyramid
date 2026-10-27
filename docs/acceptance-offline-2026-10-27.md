# Fresh-install offline acceptance — 2026-10-27

Version: 1.0.0. Delta: initial Stage 7 installed-behavior receipt.

Stage 7 result: **complete**. A frozen-source wheel installed into a fresh virtual environment with no runtime dependencies. Twenty actual console invocations and two identity/guard processes all exited 0. Every CLI invocation ran outside the checkout, using hashed embeddings, explicit offline mode, an isolated configuration file and temporary stores.

## Identity

Source checkout: /Users/mitch/dev/llm-memory-pyramid
Source base revision: cb5ccee638f975d1a5cf56bc14df73bdde4e7101 on feat/napmem-trusted-memory, plus the implementation bytes identified by the hashes below. The base commit alone does not identify the uncommitted implementation.
Frozen source: /var/folders/hz/s7btlxx54c32yt375m03q0h40000gn/T/napmem-install-acceptance-final-r3jaajle/source
Wheel: /var/folders/hz/s7btlxx54c32yt375m03q0h40000gn/T/napmem-install-acceptance-final-r3jaajle/wheel/llm_memory_pyramid-0.2.0-py3-none-any.whl
Wheel SHA-256: 937224a5a6c0621a62b897a140c06d2bdfc33e5b61046cc665a3632bfc76531e
Installed console: /var/folders/hz/s7btlxx54c32yt375m03q0h40000gn/T/napmem-install-acceptance-final-r3jaajle/venv/bin/napmem
Console SHA-256: 3cacdd6ae8a7ac65f9592bf3cb16820a2a4ed182f5dcbc7b06395cd070965e7b
Interpreter: /private/var/folders/hz/s7btlxx54c32yt375m03q0h40000gn/T/napmem-install-acceptance-final-r3jaajle/venv/bin/python
Working directory: /private/var/folders/hz/s7btlxx54c32yt375m03q0h40000gn/T/napmem-install-acceptance-final-r3jaajle/run
Configuration: /var/folders/hz/s7btlxx54c32yt375m03q0h40000gn/T/napmem-install-acceptance-final-r3jaajle/config.toml — empty [napmem] table.
Python: 3.15.1 (main, Oct 21 2026, 05:55:12) [Clang 21.0.0 (clang-2100.3.34.2)]
Distribution and napmem --version: 0.2.0; entry point napmem = napmem_cli:main.
Installed CLI: /private/var/folders/hz/s7btlxx54c32yt375m03q0h40000gn/T/napmem-install-acceptance-final-r3jaajle/venv/lib/python3.15/site-packages/napmem_cli.py
Installed configuration: /private/var/folders/hz/s7btlxx54c32yt375m03q0h40000gn/T/napmem-install-acceptance-final-r3jaajle/venv/lib/python3.15/site-packages/napmem_config.py
Installed evaluation: /private/var/folders/hz/s7btlxx54c32yt375m03q0h40000gn/T/napmem-install-acceptance-final-r3jaajle/venv/lib/python3.15/site-packages/napmem_eval.py
Installed fixture: /private/var/folders/hz/s7btlxx54c32yt375m03q0h40000gn/T/napmem-install-acceptance-final-r3jaajle/venv/share/napmem/evaluations/memory_quality_v1.json
Fixture SHA-256: 7c6c09508902842e61c204bde5257d780b01bf7af1e18d050c13b47b27c76b8e

The wheel has no unconditional Requires-Dist entries. importlib.util.find_spec returned None for both ollama_client and anthropic. Doctor independently reported both optional clients absent. All 20 installed Python runtime module hashes and the installed fixture hash matched the frozen build inputs. None of the captured source files changed during the final run.

Build, virtual-environment creation and installation each exited 0. The isolated build used setuptools 84.2.1; its wheel tag is py3-none-any. Build isolation could retrieve setuptools. Installation used --no-deps --no-index. No optional extra or private Git dependency was installed.

## Observed behavior

| Action | Observed result | Exit |
| --- | --- | --- |
| Version and help | Version 0.2.0 and available commands. | 0 |
| Doctor on a nonexistent store | No probe; store parent remained nonexistent; optional clients absent. | 0 |
| Init twice | First created generation 1; second preserved generation 1. | 0 |
| Demo | Ingested two synthetic scopes; built-in Alpha query returned Vim. | 0 |
| Alpha/Beta query | Alpha returned only Vim; Beta returned only VS Code. | 0 |
| Unrelated project:demo query | Abstained. Actual demo scopes are project:napmem-demo-alpha and project:napmem-demo-beta. | 0 |
| Inspect Alpha | Stored hash, quotation and extractor visible; verification.status=not_rechecked distinguished stored binding from a fresh reread. | 0 |
| Doctor on existing store | probed=false; store-directory file hashes, byte counts and mtimes were identical before and after. | 0 |
| Preview and apply correction | Applied Emacs correction with preview token and expected generation. | 0 |
| Replay demo | Alpha still returned only Emacs. Original Vim text did not return to active results. | 0 |
| Snapshot export and restore | New store reported privacy_controls=preserved and returned corrected Emacs. | 0 |
| Installed evaluation | Loaded fixture from virtual environment and completed 100 held-out queries. | 0 |

Installed evaluation: Recall@5 0.86; MRR@5 0.8733333333333333; correct abstention 0.76; current-fact cases 11/11; protected cases 13/13; scope violations 0; lifecycle violations 0; marked-instruction results 0. Unsupported-result rate remained 0.21978021978021978. These are retrieval regression-fixture results, not production accuracy or a new blind benchmark.

## Offline evidence

A unique guard module loaded through a .pth file in the temporary virtual environment. It blocked Python socket connection/DNS entry points, urllib requests, subprocess creation, os.system and POSIX spawn. Positive probes raised the expected guard exceptions before a connection or process launch. The final log recorded all 22 processes and zero runtime network or subprocess attempts. Its only two blocked calls were labeled positive probes. This is Python-level evidence, not an operating-system packet capture.

The first harness put its guard in sitecustomize.py; Homebrew Python loaded its own standard-library sitecustomize.py first. That preliminary run is not used as no-network proof. The final run used a verified .pth import and repeated the entire required flow.

## Failure resolved

The first installed wheel, SHA-256 c873b27a94e600096f190800866585c925b2bcb4a8327cf0bcd459534e1087bd, ingested demo records but its preferred editor query abstained. The phrases editor and prefer editor retrieved the same records. The implementation agent added general preference word forms to lexical normalization and made demo fail if its query returns no evidence. The second wheel above passed the original phrase, both scopes, correction replay and restored query.

## Commands executed

Every console command inherited the following isolated environment. PYTHONPATH and PYTHONHOME were removed. Temporary paths here identify evidence; they are not suggested installation locations.

```text
NAPMEM_EMBED_BACKEND=hashed
NAPMEM_MODE=offline
NAPMEM_CONFIG=/var/folders/hz/s7btlxx54c32yt375m03q0h40000gn/T/napmem-install-acceptance-final-r3jaajle/config.toml
NAPMEM_DATA_DIR=/var/folders/hz/s7btlxx54c32yt375m03q0h40000gn/T/napmem-install-acceptance-final-r3jaajle/unused-data
PYTHONNOUSERSITE=1
```

```sh
NAPMEM_EMBED_BACKEND=hashed /Users/mitch/dev/llm-memory-pyramid/.venv/bin/python -m pip wheel --no-deps --wheel-dir /var/folders/hz/s7btlxx54c32yt375m03q0h40000gn/T/napmem-install-acceptance-final-r3jaajle/wheel /var/folders/hz/s7btlxx54c32yt375m03q0h40000gn/T/napmem-install-acceptance-final-r3jaajle/source
NAPMEM_EMBED_BACKEND=hashed python3 -m venv /var/folders/hz/s7btlxx54c32yt375m03q0h40000gn/T/napmem-install-acceptance-final-r3jaajle/venv
NAPMEM_EMBED_BACKEND=hashed /var/folders/hz/s7btlxx54c32yt375m03q0h40000gn/T/napmem-install-acceptance-final-r3jaajle/venv/bin/python -m pip install --no-deps --no-index /var/folders/hz/s7btlxx54c32yt375m03q0h40000gn/T/napmem-install-acceptance-final-r3jaajle/wheel/llm_memory_pyramid-0.2.0-py3-none-any.whl
NAPMEM_EMBED_BACKEND=hashed NAPMEM_MODE=offline /var/folders/hz/s7btlxx54c32yt375m03q0h40000gn/T/napmem-install-acceptance-final-r3jaajle/venv/bin/napmem --version
NAPMEM_EMBED_BACKEND=hashed NAPMEM_MODE=offline /var/folders/hz/s7btlxx54c32yt375m03q0h40000gn/T/napmem-install-acceptance-final-r3jaajle/venv/bin/napmem --help
NAPMEM_EMBED_BACKEND=hashed NAPMEM_MODE=offline /var/folders/hz/s7btlxx54c32yt375m03q0h40000gn/T/napmem-install-acceptance-final-r3jaajle/venv/bin/napmem --pyramid /var/folders/hz/s7btlxx54c32yt375m03q0h40000gn/T/napmem-install-acceptance-final-r3jaajle/missing/store.json doctor
NAPMEM_EMBED_BACKEND=hashed NAPMEM_MODE=offline /var/folders/hz/s7btlxx54c32yt375m03q0h40000gn/T/napmem-install-acceptance-final-r3jaajle/venv/bin/napmem --pyramid /var/folders/hz/s7btlxx54c32yt375m03q0h40000gn/T/napmem-install-acceptance-final-r3jaajle/stores/main.json init
NAPMEM_EMBED_BACKEND=hashed NAPMEM_MODE=offline /var/folders/hz/s7btlxx54c32yt375m03q0h40000gn/T/napmem-install-acceptance-final-r3jaajle/venv/bin/napmem --pyramid /var/folders/hz/s7btlxx54c32yt375m03q0h40000gn/T/napmem-install-acceptance-final-r3jaajle/stores/main.json init
NAPMEM_EMBED_BACKEND=hashed NAPMEM_MODE=offline /var/folders/hz/s7btlxx54c32yt375m03q0h40000gn/T/napmem-install-acceptance-final-r3jaajle/venv/bin/napmem --pyramid /var/folders/hz/s7btlxx54c32yt375m03q0h40000gn/T/napmem-install-acceptance-final-r3jaajle/stores/main.json demo
NAPMEM_EMBED_BACKEND=hashed NAPMEM_MODE=offline /var/folders/hz/s7btlxx54c32yt375m03q0h40000gn/T/napmem-install-acceptance-final-r3jaajle/venv/bin/napmem --pyramid /var/folders/hz/s7btlxx54c32yt375m03q0h40000gn/T/napmem-install-acceptance-final-r3jaajle/stores/main.json query 'preferred editor' --scope project:napmem-demo-alpha
NAPMEM_EMBED_BACKEND=hashed NAPMEM_MODE=offline /var/folders/hz/s7btlxx54c32yt375m03q0h40000gn/T/napmem-install-acceptance-final-r3jaajle/venv/bin/napmem --pyramid /var/folders/hz/s7btlxx54c32yt375m03q0h40000gn/T/napmem-install-acceptance-final-r3jaajle/stores/main.json query 'preferred editor' --scope project:napmem-demo-beta
NAPMEM_EMBED_BACKEND=hashed NAPMEM_MODE=offline /var/folders/hz/s7btlxx54c32yt375m03q0h40000gn/T/napmem-install-acceptance-final-r3jaajle/venv/bin/napmem --pyramid /var/folders/hz/s7btlxx54c32yt375m03q0h40000gn/T/napmem-install-acceptance-final-r3jaajle/stores/main.json query 'preferred editor' --scope project:demo
NAPMEM_EMBED_BACKEND=hashed NAPMEM_MODE=offline /var/folders/hz/s7btlxx54c32yt375m03q0h40000gn/T/napmem-install-acceptance-final-r3jaajle/venv/bin/napmem --pyramid /var/folders/hz/s7btlxx54c32yt375m03q0h40000gn/T/napmem-install-acceptance-final-r3jaajle/stores/main.json inspect rec_sess_napmem_demo_alpha_001 --scope project:napmem-demo-alpha
NAPMEM_EMBED_BACKEND=hashed NAPMEM_MODE=offline /var/folders/hz/s7btlxx54c32yt375m03q0h40000gn/T/napmem-install-acceptance-final-r3jaajle/venv/bin/napmem --pyramid /var/folders/hz/s7btlxx54c32yt375m03q0h40000gn/T/napmem-install-acceptance-final-r3jaajle/stores/main.json doctor
NAPMEM_EMBED_BACKEND=hashed NAPMEM_MODE=offline /var/folders/hz/s7btlxx54c32yt375m03q0h40000gn/T/napmem-install-acceptance-final-r3jaajle/venv/bin/napmem --pyramid /var/folders/hz/s7btlxx54c32yt375m03q0h40000gn/T/napmem-install-acceptance-final-r3jaajle/stores/main.json control correct --record-id rec_sess_napmem_demo_alpha_001 --value 'I prefer Emacs as my editor for Alpha.' --at 2026-10-27T12:46:20.961818+00:00 --dry-run
NAPMEM_EMBED_BACKEND=hashed NAPMEM_MODE=offline /var/folders/hz/s7btlxx54c32yt375m03q0h40000gn/T/napmem-install-acceptance-final-r3jaajle/venv/bin/napmem --pyramid /var/folders/hz/s7btlxx54c32yt375m03q0h40000gn/T/napmem-install-acceptance-final-r3jaajle/stores/main.json control correct --record-id rec_sess_napmem_demo_alpha_001 --value 'I prefer Emacs as my editor for Alpha.' --at 2026-10-27T12:46:20.961818+00:00 --expected-generation 3 --preview-token eyJhdCI6IjIwMjYtMTAtMjdUMTI6NDY6MjAuOTYxODE4KzAwOjAwIiwiZ2VuZXJhdGlvbiI6MywicmVxdWVzdF9zaGEyNTYiOiIzNDljZDNlZmViZjRkM2UyMTMzNzQ3YjA0ODhjZmMxN2M3OGM3N2U5NGM2M2NhNjNiNWRkNTg1ZmFkZGZlOTY1Iiwic25hcHNob3Rfc2hhMjU2IjoiZjdmMDRhMjM2MGEzNDAyMGEyN2ZjYzE0ZmE0YjJjNTE5ODgwYWQ0OGEyYTY0Y2M3MWFjMTY0NmNiMWQ3Y2E2ZiJ9.74178e97c49263a9dbf4dc0d523d2e5894046189939ce0e783db4bd939967835
NAPMEM_EMBED_BACKEND=hashed NAPMEM_MODE=offline /var/folders/hz/s7btlxx54c32yt375m03q0h40000gn/T/napmem-install-acceptance-final-r3jaajle/venv/bin/napmem --pyramid /var/folders/hz/s7btlxx54c32yt375m03q0h40000gn/T/napmem-install-acceptance-final-r3jaajle/stores/main.json query 'preferred editor' --scope project:napmem-demo-alpha
NAPMEM_EMBED_BACKEND=hashed NAPMEM_MODE=offline /var/folders/hz/s7btlxx54c32yt375m03q0h40000gn/T/napmem-install-acceptance-final-r3jaajle/venv/bin/napmem --pyramid /var/folders/hz/s7btlxx54c32yt375m03q0h40000gn/T/napmem-install-acceptance-final-r3jaajle/stores/main.json demo
NAPMEM_EMBED_BACKEND=hashed NAPMEM_MODE=offline /var/folders/hz/s7btlxx54c32yt375m03q0h40000gn/T/napmem-install-acceptance-final-r3jaajle/venv/bin/napmem --pyramid /var/folders/hz/s7btlxx54c32yt375m03q0h40000gn/T/napmem-install-acceptance-final-r3jaajle/stores/main.json query 'preferred editor' --scope project:napmem-demo-alpha
NAPMEM_EMBED_BACKEND=hashed NAPMEM_MODE=offline /var/folders/hz/s7btlxx54c32yt375m03q0h40000gn/T/napmem-install-acceptance-final-r3jaajle/venv/bin/napmem --pyramid /var/folders/hz/s7btlxx54c32yt375m03q0h40000gn/T/napmem-install-acceptance-final-r3jaajle/stores/main.json snapshot export /var/folders/hz/s7btlxx54c32yt375m03q0h40000gn/T/napmem-install-acceptance-final-r3jaajle/snapshot
NAPMEM_EMBED_BACKEND=hashed NAPMEM_MODE=offline /var/folders/hz/s7btlxx54c32yt375m03q0h40000gn/T/napmem-install-acceptance-final-r3jaajle/venv/bin/napmem --pyramid /var/folders/hz/s7btlxx54c32yt375m03q0h40000gn/T/napmem-install-acceptance-final-r3jaajle/stores/restored.json snapshot restore /var/folders/hz/s7btlxx54c32yt375m03q0h40000gn/T/napmem-install-acceptance-final-r3jaajle/snapshot
NAPMEM_EMBED_BACKEND=hashed NAPMEM_MODE=offline /var/folders/hz/s7btlxx54c32yt375m03q0h40000gn/T/napmem-install-acceptance-final-r3jaajle/venv/bin/napmem --pyramid /var/folders/hz/s7btlxx54c32yt375m03q0h40000gn/T/napmem-install-acceptance-final-r3jaajle/stores/restored.json query 'preferred editor' --scope project:napmem-demo-alpha
NAPMEM_EMBED_BACKEND=hashed NAPMEM_MODE=offline /var/folders/hz/s7btlxx54c32yt375m03q0h40000gn/T/napmem-install-acceptance-final-r3jaajle/venv/bin/napmem --pyramid /var/folders/hz/s7btlxx54c32yt375m03q0h40000gn/T/napmem-install-acceptance-final-r3jaajle/stores/main.json eval --eval-mode hybrid --split heldout --output /var/folders/hz/s7btlxx54c32yt375m03q0h40000gn/T/napmem-install-acceptance-final-r3jaajle/eval-installed.json
```

## Exact source bindings

All installed runtime Python files matched the corresponding frozen source hash.

| Build input | SHA-256 |
| --- | --- |
| /Users/mitch/dev/llm-memory-pyramid/pyproject.toml | e46bfa0f441a121d52992cde52f3c420b761d762a919f00e6e140b43a5c8af09 |
| /Users/mitch/dev/llm-memory-pyramid/napmem_model.py | 47893d7e337604f0656d182c1880fadc0547b255702f2f524378e1ddcfb432ae |
| /Users/mitch/dev/llm-memory-pyramid/napmem_search.py | 15f2d3b7db6b1c4e1029e61f770cda9b6252c23d6659b86d7d1aa1c07badd0e7 |
| /Users/mitch/dev/llm-memory-pyramid/napmem_controls.py | 59d0e02bdc2f89b6a9bb9a8b635d1a94d8f39942287a0e4b032e443032c006d5 |
| /Users/mitch/dev/llm-memory-pyramid/napmem_evidence.py | 60c39cb9cb7dd465c1454e363357c822a489b7dca16cbd4528a36af95af10ea9 |
| /Users/mitch/dev/llm-memory-pyramid/napmem_eval.py | abd7b0fc26f63175f8f72256668c4123bc8147257d38127b4da24af1a182b2e0 |
| /Users/mitch/dev/llm-memory-pyramid/napmem_storage.py | 2816aa4d86d3f803cc582f478f5100c8159809ca548bf498459b955b68128e8b |
| /Users/mitch/dev/llm-memory-pyramid/napmem_jobs.py | 90250959cbcec6e52da98ddbcf015f4b7cb712e9a1b2ecd80183a2dc04301317 |
| /Users/mitch/dev/llm-memory-pyramid/napmem_sources.py | 5b1d219b8c1bfeae57e056d676febab1ff17264559c9d2e3740156e51c18dc94 |
| /Users/mitch/dev/llm-memory-pyramid/napmem_snapshots.py | 54d3fb3c62bf85997e3bca931acc9798e8601a35a9f2c829e07bf73a0db3c582 |
| /Users/mitch/dev/llm-memory-pyramid/napmem_config.py | 1bc76880adbf43d1720502648768b705b522ba08ecad9319465fcd6fe3afb116 |
| /Users/mitch/dev/llm-memory-pyramid/napmem_cli.py | 8ee882a76931aef7a36cb3d0d9bd897f6abf8baa26b8c50567831eeb76f7cff2 |
| /Users/mitch/dev/llm-memory-pyramid/semantic_index.py | 8a4f7851fbcbcfe6b87d47a9f3163cae2331e378487a4c8859abd52f06be9b88 |
| /Users/mitch/dev/llm-memory-pyramid/ollama_extractor.py | 768f963c9f586892a0bd2c7307841a9cf9aff845232643d31fdb937f430fb4e1 |
| /Users/mitch/dev/llm-memory-pyramid/llm_extractor.py | 396c8a0d4ec2d0302b1464e48d091226002d31abdc29ea8b22ffd684625cf13d |
| /Users/mitch/dev/llm-memory-pyramid/llm_extraction_prompts.py | 2361b192b404c731bc11689cd9b0e25be941f2410bff35c731cb0cb86db0ab88 |
| /Users/mitch/dev/llm-memory-pyramid/memory_pyramid_distiller.py | 2e6623f706bbf0131f85a9b9a9c44e7fb607013fce1e2bb0e61678d99f59a0ca |
| /Users/mitch/dev/llm-memory-pyramid/naptime_consolidator.py | fdd2d9eb6d373b225df88efca28c366a392554b05de3f4d4cb17cb91118ab53b |
| /Users/mitch/dev/llm-memory-pyramid/napmem_retrieval_agent.py | 26372d69bab43309134ef61c820bd00f48f4a169289317084577bab7e877f280 |
| /Users/mitch/dev/llm-memory-pyramid/napmem_mcp_server.py | cf09d30ff16944da6aac4ff3fe68c8bc4d3ccdf7c9e0a222453da6cdee26ec1c |
| /Users/mitch/dev/llm-memory-pyramid/napmem_mcp_failover.py | abeb18c09a6700e4c2743a49c94e8618065e247f008c7a1670de259b5b4dd46c |
| /Users/mitch/dev/llm-memory-pyramid/evaluations/memory_quality_v1.json | 7c6c09508902842e61c204bde5257d780b01bf7af1e18d050c13b47b27c76b8e |
| /Users/mitch/dev/llm-memory-pyramid/LICENSE | c71d239df91726fc519c6eb72d318ec65820627232b2f796219e87dcf35d0ab4 |
| /Users/mitch/dev/llm-memory-pyramid/README.md | cd74aeb93f0b76a13d9e1543ec6cfb43ce833784c90e73b03b0082583305279f |

## Limits

This receipt covers the Stage 7 offline console flow. It does not establish a production installation, remote-host behavior, real embeddings, online extraction, Windows/Linux operation, or Python 3.11–3.14 compatibility. No production/default store, model server, indexer, SSH connection or deployment was used.

Inspector views advertised by help, operational metrics and typed client adapters belong to later stages and were not in this frozen wheel acceptance. Repeat installed acceptance after those modules and their packaging entries are finalized. The parent workflow owns full repository tests, generated documentation checks, prompt/memory/task updates and Git delivery. This verifier changed only this report and did not commit or publish.

## Raw evidence

Temporary evidence is retained locally and may disappear when the operating system cleans its temporary directory.

- /var/folders/hz/s7btlxx54c32yt375m03q0h40000gn/T/napmem-install-acceptance-final-r3jaajle/receipt.json
- /var/folders/hz/s7btlxx54c32yt375m03q0h40000gn/T/napmem-install-acceptance-final-r3jaajle/commands.json
- /var/folders/hz/s7btlxx54c32yt375m03q0h40000gn/T/napmem-install-acceptance-final-r3jaajle/identity.json
- /var/folders/hz/s7btlxx54c32yt375m03q0h40000gn/T/napmem-install-acceptance-final-r3jaajle/source-manifest.json
- /var/folders/hz/s7btlxx54c32yt375m03q0h40000gn/T/napmem-install-acceptance-final-r3jaajle/doctor-no-write.json
- /var/folders/hz/s7btlxx54c32yt375m03q0h40000gn/T/napmem-install-acceptance-final-r3jaajle/guard-processes.jsonl
- /var/folders/hz/s7btlxx54c32yt375m03q0h40000gn/T/napmem-install-acceptance-final-r3jaajle/guard-attempts.jsonl
- /var/folders/hz/s7btlxx54c32yt375m03q0h40000gn/T/napmem-install-acceptance-final-r3jaajle/eval-installed.json

## Machine-readable receipt

```json
{
  "agent": "live-acceptance-verifier",
  "definition_version": "1.0.0",
  "status": "complete",
  "evidence": [
    {
      "source": "/var/folders/hz/s7btlxx54c32yt375m03q0h40000gn/T/napmem-install-acceptance-final-r3jaajle/receipt.json",
      "observed_at": "2026-10-27T12:46:21.779213+00:00",
      "supported_claim": "All Stage 7 installed acceptance assertions and actual command exit codes passed."
    },
    {
      "source": "/var/folders/hz/s7btlxx54c32yt375m03q0h40000gn/T/napmem-install-acceptance-final-r3jaajle/identity.json",
      "observed_at": "2026-10-27T12:46:21.779213+00:00",
      "supported_claim": "Fresh-venv imports matched frozen source bytes; optional clients were absent."
    },
    {
      "source": "/var/folders/hz/s7btlxx54c32yt375m03q0h40000gn/T/napmem-install-acceptance-final-r3jaajle/guard-processes.jsonl",
      "observed_at": "2026-10-27T12:46:21.779213+00:00",
      "supported_claim": "All 22 final acceptance processes loaded the guard."
    },
    {
      "source": "/var/folders/hz/s7btlxx54c32yt375m03q0h40000gn/T/napmem-install-acceptance-final-r3jaajle/guard-attempts.jsonl",
      "observed_at": "2026-10-27T12:46:21.779213+00:00",
      "supported_claim": "Only two labeled positive probes attempted blocked operations."
    },
    {
      "source": "/var/folders/hz/s7btlxx54c32yt375m03q0h40000gn/T/napmem-install-acceptance-final-r3jaajle/eval-installed.json",
      "observed_at": "2026-10-27T12:46:21.779213+00:00",
      "supported_claim": "Installed fixture completed 100 held-out queries."
    }
  ],
  "changes": [
    "/Users/mitch/dev/llm-memory-pyramid/docs/acceptance-offline-2026-10-27.md"
  ],
  "remaining": [],
  "details": {
    "surface": "Freshly installed napmem console script, Stage 7 offline subset",
    "acceptance_condition": "Core wheel installs without extras; init/demo/scoped query/record inspect/doctor/correction replay/snapshot round-trip/bundled evaluation work outside checkout with hashed embeddings and no runtime Python network or subprocess attempt.",
    "source_revision": "cb5ccee638f975d1a5cf56bc14df73bdde4e7101 plus source hashes recorded above",
    "loaded_revision": "937224a5a6c0621a62b897a140c06d2bdfc33e5b61046cc665a3632bfc76531e",
    "process_or_origin": "/var/folders/hz/s7btlxx54c32yt375m03q0h40000gn/T/napmem-install-acceptance-final-r3jaajle/venv/bin/napmem",
    "configuration_identity": "/var/folders/hz/s7btlxx54c32yt375m03q0h40000gn/T/napmem-install-acceptance-final-r3jaajle/config.toml; NAPMEM_EMBED_BACKEND=hashed; NAPMEM_MODE=offline; explicit temporary pyramid on every command",
    "observations": {
      "console_commands": 20,
      "total_guarded_processes": 22,
      "runtime_guard_attempts": 0,
      "optional_clients_absent": [
        "ollama_client",
        "anthropic"
      ],
      "installed_hash_mismatches": 0
    },
    "mismatches": [],
    "unverified_checks": [
      "Later-stage inspector views, metrics and client adapters are outside this Stage 7 receipt.",
      "Other platforms and Python versions are outside this run.",
      "Online integrations and production deployment are outside this run."
    ]
  }
}
```

---

# Final installed acceptance — v1.1.0

Delta: preserved the Stage 7 receipt above and added fresh installation and actual behavior evidence for the completed offline inspector, metrics, adapters, MCP and trusted-memory flow. The final acceptance below supersedes the earlier receipt’s later-stage exclusions.

Final result: **complete for the requested offline acceptance scope**. The final wheel installed without runtime dependencies into another fresh virtual environment. All 61 actual console invocations and three Python identity/guard/snapshot-verification processes exited 0. All 64 processes loaded the guard, and no runtime network or subprocess attempt was recorded.

## Final identity

Observed at: 2026-10-27T13:13:14.649083+00:00
Source checkout: /Users/mitch/dev/llm-memory-pyramid
Source base revision: c3905b5891aac52131a2ccb25f457d6155427144 on feat/napmem-trusted-memory, plus the exact source hashes below.
Frozen source tree: /private/var/folders/hz/s7btlxx54c32yt375m03q0h40000gn/T/napmem-all-stages-acceptance-leeu455d/source
Wheel: /private/var/folders/hz/s7btlxx54c32yt375m03q0h40000gn/T/napmem-all-stages-acceptance-leeu455d/wheel/llm_memory_pyramid-0.2.0-py3-none-any.whl
Wheel SHA-256: 2cdf30a87ace7f25d079fab439255810e5d2c02b58b2ce79d9fc048ee38fdd35
Console executable: /private/var/folders/hz/s7btlxx54c32yt375m03q0h40000gn/T/napmem-all-stages-acceptance-leeu455d/venv/bin/napmem
Console SHA-256: d231b34413188fda123372366ebe18e2b7fad63824aec0932ae2e2147f2f23b8
Console interpreter: /private/var/folders/hz/s7btlxx54c32yt375m03q0h40000gn/T/napmem-all-stages-acceptance-leeu455d/venv/bin/python
Working directory of actual commands: /private/var/folders/hz/s7btlxx54c32yt375m03q0h40000gn/T/napmem-all-stages-acceptance-leeu455d/run
Installed CLI: /private/var/folders/hz/s7btlxx54c32yt375m03q0h40000gn/T/napmem-all-stages-acceptance-leeu455d/venv/lib/python3.15/site-packages/napmem_cli.py
Installed inspector: /private/var/folders/hz/s7btlxx54c32yt375m03q0h40000gn/T/napmem-all-stages-acceptance-leeu455d/venv/lib/python3.15/site-packages/napmem_inspector.py
Installed metrics: /private/var/folders/hz/s7btlxx54c32yt375m03q0h40000gn/T/napmem-all-stages-acceptance-leeu455d/venv/lib/python3.15/site-packages/napmem_metrics.py
Installed adapters: /private/var/folders/hz/s7btlxx54c32yt375m03q0h40000gn/T/napmem-all-stages-acceptance-leeu455d/venv/lib/python3.15/site-packages/napmem_adapters.py
Installed MCP server: /private/var/folders/hz/s7btlxx54c32yt375m03q0h40000gn/T/napmem-all-stages-acceptance-leeu455d/venv/lib/python3.15/site-packages/napmem_mcp_server.py
Installed fixture: /private/var/folders/hz/s7btlxx54c32yt375m03q0h40000gn/T/napmem-all-stages-acceptance-leeu455d/venv/share/napmem/evaluations/memory_quality_v1.json
Configuration: /private/var/folders/hz/s7btlxx54c32yt375m03q0h40000gn/T/napmem-all-stages-acceptance-leeu455d/config.toml
Temporary stores: /private/var/folders/hz/s7btlxx54c32yt375m03q0h40000gn/T/napmem-all-stages-acceptance-leeu455d/stores
Python: 3.15.1 (main, Oct 21 2026, 05:55:12) [Clang 21.0.0 (clang-2100.3.34.2)]

CLI/distribution version is 0.2.0; MCP server version is 1.2.0. The wheel advertises no unconditional runtime dependencies. Both ollama_client and anthropic were absent. All 23 installed Python module hashes matched both their wheel members and the frozen source bytes. The fixture hash also matched. Build and fresh installation each exited 0; installation used --no-deps --no-index. Build isolation used only the declared setuptools backend dependency.

The acceptance environment removed PYTHONPATH/PYTHONHOME and inherited NAPMEM_EMBED_BACKEND=hashed, NAPMEM_MODE=offline, PYTHONNOUSERSITE=1, the explicit temporary configuration and an unused temporary NAPMEM_DATA_DIR. Every operational console invocation specified its pyramid path. The new MCP command ran in the same installed process and honored an explicit CLI pyramid over a conflicting NAPMEM_PYRAMID environment value.

## Final behavior

| Surface | Actual result |
| --- | --- |
| Demo and scoped queries | Alpha returned Vim; Beta returned VS Code; unrelated scope abstained. |
| Inspector overview/current/review/stale/timeline/handoff/profiles/conflicts | All eight installed views executed. Current/review/timeline/handoff showed the scoped assertion. Profiles stayed empty until explicit approval, then showed one cited profile. |
| Conflict and stale fixtures | A portable source produced one conflict with two citations. At an explicit 2027-01-01 reference, the stale view returned both assertions using last_verified_at as its age basis. |
| Inspector read-only behavior | Store-directory file contents, byte counts and mtimes were unchanged across the eight views. |
| Source diff | The installed command returned the change from Vim to Helix within the requested 4096-byte JSON budget. |
| Metrics and feedback | An opt-in query recorded one retrieval; feedback/status showed one opinion. Forget removed that record’s local feedback; status then showed zero opinions. Stored metrics contained no raw query, scope or record ID. |
| Conversation adapter | Imported two user/assistant messages and retrieved the selected editor in the explicit conversation scope. |
| Portable export/import | Exported two scoped records and imported them into a new caller-selected scope. Imported records remained source-authority and unreviewed. The old scope returned no imported result. |
| Global scope and precedence | Explicit global import ignored a forged input scope; its global assertion appeared in the permitted project context. A subcommand scope overrode both a root CLI scope and an environment scope. |
| Trusted source/update/correction loop | Scoped Markdown ingest retrieved Vim; source update retrieved Nano; a generation/token-bound operator correction retrieved Helix after replay. |
| Forget and older-backup restore | Forget removed the correction family. Restoring the older backup and replaying the source did not restore Nano or Helix. The other project still returned Emacs. Forgotten literal text remained absent from the canonical store. |
| Verified snapshot | A final snapshot returned Emacs through the installed offline CLI. Installed load_snapshot reported verified; snapshot file hashes and mtimes were unchanged. |
| Doctor | No probe and no store-directory content or mtime change; a missing store was not initialized. |
| Bundled evaluations | Both installed dev and held-out 100-query fixtures completed with zero scope/lifecycle/marked-instruction leakage. |

Stale-view semantics were checked without changing the 30-day threshold. A freshly verified imported source correctly stayed fresh even when its observed_at value was old. The later explicit reference time made the last_verified_at age exceed the threshold. The initial harness assumption about observed_at was corrected; runtime code and thresholds were unchanged.

Forgetting here means canonical-store and adjacent local state behavior. Original source files and the explicitly retained older backup remain operator-managed. This run does not claim deletion from external originals, backups, mirrors or replicas.

## MCP wire acceptance

The actual installed napmem mcp process negotiated protocol 2025-06-18, returned server version 1.2.0, answered ping, and listed four read-only tools with input/output schemas. Its initialized notification emitted no response. Explicit hybrid/lexical searches, provenance inspection, topic-track retrieval and memory statistics succeeded. Fifteen responses included twelve budgeted tool responses. Successful result payloads were exactly equal after parsing structuredContent and the text JSON copy. Store-directory contents and mtimes stayed unchanged.

Byte measurements include the full UTF-8 JSON-RPC response and its newline. Token counts use the advertised ceil(bytes/4) estimate. Tiny budgets returned a complete bounded JSON-RPC error instead of partial JSON.

| Request | Requested bytes | Requested tokens | Actual wire bytes | Estimated tokens | Result |
| --- | --- | --- | --- | --- | --- |
| 4 | 16384 | 4096 | 4987 | 1247 | complete result |
| 5 | 16384 | 4096 | 4963 | 1241 | complete result |
| 6 | 16384 | 4096 | 4255 | 1064 | complete result |
| 7 | 16384 | 4096 | 3812 | 953 | complete result |
| 8 | 16384 | 4096 | 1463 | 366 | complete result |
| b128 | 128 | 32 | 105 | 27 | bounded protocol error |
| b512 | 512 | 128 | 105 | 27 | bounded protocol error |
| b1024 | 1024 | 256 | 106 | 27 | bounded protocol error |
| b2048 | 2048 | 512 | 1436 | 359 | truncated whole groups |
| b4096 | 4096 | 1024 | 1437 | 360 | truncated whole groups |
| b8192 | 8192 | 2048 | 4992 | 1248 | complete result |
| token | 65536 | 128 | 106 | 27 | bounded protocol error |

## Installed evaluation results

| Metric | Dev, 100 queries | Held-out, 100 queries |
| --- | --- | --- |
| Recall@5 | 0.879746835443038 | 0.86 |
| MRR@5 | 0.8924050632911392 | 0.8733333333333333 |
| Correct abstention | 0.7619047619047619 | 0.76 |
| Current-fact correct rate | 0.9166666666666666 | 1 |
| Protected-case pass rate | 1 | 1 |
| Unsupported-result rate | 0.20202020202020202 | 0.21978021978021978 |
| Scope violations | 0 | 0 |
| Lifecycle violations | 0 | 0 |
| Marked-instruction results | 0 | 0 |

These are synthetic retrieval regression measurements. The held-out split has previously been inspected, so this is not a new blind evaluation. The dev current-fact rate remains 11/12; the held-out rate remains 11/11. No claim of perfect recall, calibrated confidence, production accuracy or real-model performance follows.

## Final source bindings

Every runtime module, package metadata input, fixture and license below remained unchanged during acceptance. The README changed concurrently from its historical frozen-copy hash to de88ef7b26b1745b9c7e8ca9ba3109cf406a34088efabca1c05a0d3aba6ab23f. It is absent from the wheel, and package metadata declares no README input. That documentation change does not alter the tested installed runtime. The raw source manifest retains the frozen README context; the raw receipt records the observed drift.

| Build input | SHA-256 |
| --- | --- |
| /Users/mitch/dev/llm-memory-pyramid/pyproject.toml | 7ac646c32811b95647ecafd666bca3bf00fc940207b1352eaafb4b3b8292aafb |
| /Users/mitch/dev/llm-memory-pyramid/napmem_model.py | a3742acbd0d1b4c9d55a4a74bce09e389d79e2f9caba9496062c490aba85289f |
| /Users/mitch/dev/llm-memory-pyramid/napmem_search.py | 15f2d3b7db6b1c4e1029e61f770cda9b6252c23d6659b86d7d1aa1c07badd0e7 |
| /Users/mitch/dev/llm-memory-pyramid/napmem_controls.py | 59d0e02bdc2f89b6a9bb9a8b635d1a94d8f39942287a0e4b032e443032c006d5 |
| /Users/mitch/dev/llm-memory-pyramid/napmem_evidence.py | 85b09592a5091793fb2c768370274420e4789be128ff246b54963f413bcfe7cb |
| /Users/mitch/dev/llm-memory-pyramid/napmem_eval.py | abd7b0fc26f63175f8f72256668c4123bc8147257d38127b4da24af1a182b2e0 |
| /Users/mitch/dev/llm-memory-pyramid/napmem_storage.py | 2816aa4d86d3f803cc582f478f5100c8159809ca548bf498459b955b68128e8b |
| /Users/mitch/dev/llm-memory-pyramid/napmem_jobs.py | a38f8d4e047b2b7e6cc5ce4e1af20c00e0b46587496489175dfb88f42d972fd7 |
| /Users/mitch/dev/llm-memory-pyramid/napmem_sources.py | 8213bee307e78f66fc4e60f889969ea4c3039c4165d8ab9f9468cda5815e11a3 |
| /Users/mitch/dev/llm-memory-pyramid/napmem_snapshots.py | 54d3fb3c62bf85997e3bca931acc9798e8601a35a9f2c829e07bf73a0db3c582 |
| /Users/mitch/dev/llm-memory-pyramid/napmem_config.py | 65094f365ea63821460bddbba32fe6bff515aa20656420bc93082f36fa5f92f2 |
| /Users/mitch/dev/llm-memory-pyramid/napmem_cli.py | fa34b4a9e7817e65cc7837bc85466ee636d0e2f185656b189bfaa28046944ba1 |
| /Users/mitch/dev/llm-memory-pyramid/napmem_inspector.py | d28ef183768fb94b08251d8cebc8e9872388a5fca7d3180a341ce2cf234d2038 |
| /Users/mitch/dev/llm-memory-pyramid/napmem_metrics.py | 8cb726b4682a0a4e734a7e493d6a08300862c9ddadd52fa4e43214134736223e |
| /Users/mitch/dev/llm-memory-pyramid/napmem_adapters.py | 4943094cafe9daaccff9f04db7dde0fef6c135895f1283e0b81e125b2b6db798 |
| /Users/mitch/dev/llm-memory-pyramid/semantic_index.py | 8a4f7851fbcbcfe6b87d47a9f3163cae2331e378487a4c8859abd52f06be9b88 |
| /Users/mitch/dev/llm-memory-pyramid/ollama_extractor.py | 768f963c9f586892a0bd2c7307841a9cf9aff845232643d31fdb937f430fb4e1 |
| /Users/mitch/dev/llm-memory-pyramid/llm_extractor.py | 3e555f7caa80f2ee6bcd1cbf9461e45f2037f7b4962f56b9979cf1a8be28b8dd |
| /Users/mitch/dev/llm-memory-pyramid/llm_extraction_prompts.py | 2361b192b404c731bc11689cd9b0e25be941f2410bff35c731cb0cb86db0ab88 |
| /Users/mitch/dev/llm-memory-pyramid/memory_pyramid_distiller.py | c61a7db717f9a3d500e8c61480c6d8e421aeee1121448a9a64bb29f27ce40048 |
| /Users/mitch/dev/llm-memory-pyramid/naptime_consolidator.py | 21dd15f6244d387b0864408661547c1b40c8871df7a16e1ea7e3f22fc380f598 |
| /Users/mitch/dev/llm-memory-pyramid/napmem_retrieval_agent.py | 120fa81b137ad568e49906bf63c427c3d7c410ca19d5fe76c8eb02610d16bc99 |
| /Users/mitch/dev/llm-memory-pyramid/napmem_mcp_server.py | 11f9ba05adc11370c77bfbdcd632807d75970b86d4364bc7f52370c5e225043f |
| /Users/mitch/dev/llm-memory-pyramid/napmem_mcp_failover.py | 449371665a3db46b62a7a0cc27697967c4544ae8d4f2a5138ef14037f63a1c26 |
| /Users/mitch/dev/llm-memory-pyramid/evaluations/memory_quality_v1.json | 7c6c09508902842e61c204bde5257d780b01bf7af1e18d050c13b47b27c76b8e |
| /Users/mitch/dev/llm-memory-pyramid/LICENSE | c71d239df91726fc519c6eb72d318ec65820627232b2f796219e87dcf35d0ab4 |

## Final limits

This run covers the requested local offline behavior on macOS with Python 3.15.1. It does not establish Windows/Linux behavior, other Python versions, production deployment, online extraction, real embeddings, remote failover, editor-hook installation or external-replica deletion. Fresh-installed Git ingestion was intentionally omitted so the subprocess guard could remain strict. Git fixture tests belong to the parent workflow and were not independently rerun by this verifier.

The Python guard positively blocked a socket attempt and a process-launch attempt, then recorded zero runtime attempts. It is Python-level instrumentation, not OS network isolation or packet capture. No production/default store, service, SSH connection, inference, real embedding, indexing, deployment or publication was used. Full repository tests, documentation generation, task/prompt/memory updates and Git delivery remain the parent workflow’s responsibility.

## Final evidence artifacts

The following are local temporary evidence, not example installation locations. The operating system may eventually remove them.

- /private/var/folders/hz/s7btlxx54c32yt375m03q0h40000gn/T/napmem-all-stages-acceptance-leeu455d/receipt.json
- /private/var/folders/hz/s7btlxx54c32yt375m03q0h40000gn/T/napmem-all-stages-acceptance-leeu455d/commands.json
- /private/var/folders/hz/s7btlxx54c32yt375m03q0h40000gn/T/napmem-all-stages-acceptance-leeu455d/checks.json
- /private/var/folders/hz/s7btlxx54c32yt375m03q0h40000gn/T/napmem-all-stages-acceptance-leeu455d/identity.json
- /private/var/folders/hz/s7btlxx54c32yt375m03q0h40000gn/T/napmem-all-stages-acceptance-leeu455d/source-manifest.json
- /private/var/folders/hz/s7btlxx54c32yt375m03q0h40000gn/T/napmem-all-stages-acceptance-leeu455d/mcp-wire.jsonl
- /private/var/folders/hz/s7btlxx54c32yt375m03q0h40000gn/T/napmem-all-stages-acceptance-leeu455d/mcp-budgets.json
- /private/var/folders/hz/s7btlxx54c32yt375m03q0h40000gn/T/napmem-all-stages-acceptance-leeu455d/guard-processes.jsonl
- /private/var/folders/hz/s7btlxx54c32yt375m03q0h40000gn/T/napmem-all-stages-acceptance-leeu455d/guard-attempts.jsonl
- /private/var/folders/hz/s7btlxx54c32yt375m03q0h40000gn/T/napmem-all-stages-acceptance-leeu455d/eval-dev.json
- /private/var/folders/hz/s7btlxx54c32yt375m03q0h40000gn/T/napmem-all-stages-acceptance-leeu455d/eval-heldout.json

## Final machine-readable receipt

```json
{
  "agent": "live-acceptance-verifier",
  "definition_version": "1.0.0",
  "status": "complete",
  "evidence": [
    {
      "source": "/private/var/folders/hz/s7btlxx54c32yt375m03q0h40000gn/T/napmem-all-stages-acceptance-leeu455d/commands.json",
      "observed_at": "2026-10-27T13:13:14.649083+00:00",
      "supported_claim": "All 61 actual console invocations and three Python verification/probe processes exited 0."
    },
    {
      "source": "/private/var/folders/hz/s7btlxx54c32yt375m03q0h40000gn/T/napmem-all-stages-acceptance-leeu455d/identity.json",
      "observed_at": "2026-10-27T13:13:14.649083+00:00",
      "supported_claim": "Installed CLI 0.2.0 and MCP 1.2.0 loaded frozen wheel modules; optional clients were absent."
    },
    {
      "source": "/private/var/folders/hz/s7btlxx54c32yt375m03q0h40000gn/T/napmem-all-stages-acceptance-leeu455d/mcp-budgets.json",
      "observed_at": "2026-10-27T13:13:14.649083+00:00",
      "supported_claim": "All twelve measured tool responses fit complete UTF-8 wire and estimated-token budgets; successful text/structured payloads matched."
    },
    {
      "source": "/private/var/folders/hz/s7btlxx54c32yt375m03q0h40000gn/T/napmem-all-stages-acceptance-leeu455d/checks.json",
      "observed_at": "2026-10-27T13:13:14.649083+00:00",
      "supported_claim": "Inspector, metrics feedback purge, scoped adapters, source/correction replay, forget/older-backup restore and verified snapshots passed."
    },
    {
      "source": "/private/var/folders/hz/s7btlxx54c32yt375m03q0h40000gn/T/napmem-all-stages-acceptance-leeu455d/guard-attempts.jsonl",
      "observed_at": "2026-10-27T13:13:14.649083+00:00",
      "supported_claim": "Only two labeled positive probes attempted guarded operations; runtime attempts were zero."
    },
    {
      "source": "/private/var/folders/hz/s7btlxx54c32yt375m03q0h40000gn/T/napmem-all-stages-acceptance-leeu455d/eval-dev.json",
      "observed_at": "2026-10-27T13:13:14.649083+00:00",
      "supported_claim": "Installed bundled dev fixture completed 100 synthetic queries."
    },
    {
      "source": "/private/var/folders/hz/s7btlxx54c32yt375m03q0h40000gn/T/napmem-all-stages-acceptance-leeu455d/eval-heldout.json",
      "observed_at": "2026-10-27T13:13:14.649083+00:00",
      "supported_claim": "Installed bundled held-out fixture completed 100 synthetic queries."
    }
  ],
  "changes": [
    "/Users/mitch/dev/llm-memory-pyramid/docs/acceptance-offline-2026-10-27.md"
  ],
  "remaining": [],
  "details": {
    "surface": "Fresh wheel installed outside checkout: CLI, inspector, metrics, adapters and MCP stdio",
    "acceptance_condition": "Requested local offline final installed flow passes with hashed embeddings, no optional clients and no runtime network/subprocess attempt.",
    "source_revision": "c3905b5891aac52131a2ccb25f457d6155427144 plus exact source hashes recorded above; concurrent nonpackaged README change disclosed",
    "loaded_revision": "2cdf30a87ace7f25d079fab439255810e5d2c02b58b2ce79d9fc048ee38fdd35",
    "process_or_origin": "/private/var/folders/hz/s7btlxx54c32yt375m03q0h40000gn/T/napmem-all-stages-acceptance-leeu455d/venv/bin/napmem",
    "configuration_identity": "/private/var/folders/hz/s7btlxx54c32yt375m03q0h40000gn/T/napmem-all-stages-acceptance-leeu455d/config.toml; NAPMEM_EMBED_BACKEND=hashed; NAPMEM_MODE=offline; explicit temporary pyramid paths",
    "observations": {
      "console_commands": 61,
      "guarded_processes": 64,
      "runtime_guard_attempts": 0,
      "installed_module_hash_matches": 23,
      "mcp_responses": 15,
      "budgeted_tool_responses": 12,
      "metrics_feedback_before_after": [
        1,
        0
      ],
      "forgotten_after_old_backup_restore": true,
      "dev_queries": 100,
      "heldout_queries": 100
    },
    "mismatches": [],
    "unverified_checks": [
      "Fresh-installed Git CLI omitted under strict subprocess guard.",
      "Other platforms/Python versions, online integrations, production services and external replicas are outside this run."
    ]
  }
}
```

---

# Developer environment parity — v1.2.0

Delta: preserved both earlier receipts and verified the existing developer virtual environment after the parent upgraded only the project package. This closes the local stale-metadata discrepancy; it does not repeat the fresh-install acceptance.

Observed at: 2026-10-27T13:25:27.926218+00:00
Merged source: be84a2341a4b4780eda53d7600bafeff80e4c80e
Actual console: /Users/mitch/dev/llm-memory-pyramid/.venv/bin/napmem
Console SHA-256: a89a1fbcb73d4655de19d0bbcd603ad0824d8e7ac3985bfbffbfc50b3879e029
Interpreter: /Users/mitch/dev/llm-memory-pyramid/.venv/bin/python
Installed modules: /Users/mitch/dev/llm-memory-pyramid/.venv/lib/python3.12/site-packages
Installed metadata: /Users/mitch/dev/llm-memory-pyramid/.venv/lib/python3.12/site-packages/llm_memory_pyramid-0.2.0.dist-info/METADATA
Metadata SHA-256: 44c16ac97956d06a2311ed916ea0df5235578d0e7fa360367915ed9869743253
Working directory: /private/var/folders/hz/s7btlxx54c32yt375m03q0h40000gn/T/napmem-developer-venv-parity-ihtvf65t/run

The actual console and installed distribution metadata both report 0.2.0. All 23 installed runtime module hashes exactly match the committed merged source and the v1.1 source-binding table above. The console imports from the developer virtual environment, with the checkout source directory absent from sys.path. Ollama client 0.1.0 is present; Anthropic is absent.

Five actual console invocations exited 0: version, temporary demo, Alpha query, Beta query and doctor. Alpha returned only Vim; Beta returned only VS Code. Doctor reported offline/hashed operation, probed=false and unchanged store-directory file hashes, byte counts and mtimes. Seven processes loaded a temporary PYTHONPATH startup guard. Its two positive probes were blocked; runtime network/process attempts were zero. No installed startup file, .pth file, hook, dependency or service was modified by this verifier.

Temporary configuration: /var/folders/hz/s7btlxx54c32yt375m03q0h40000gn/T/napmem-developer-venv-parity-ihtvf65t/config.toml
Temporary pyramid: /var/folders/hz/s7btlxx54c32yt375m03q0h40000gn/T/napmem-developer-venv-parity-ihtvf65t/stores/main.json
Temporary startup guard: /var/folders/hz/s7btlxx54c32yt375m03q0h40000gn/T/napmem-developer-venv-parity-ihtvf65t/guard/sitecustomize.py

The following commands inherited NAPMEM_MODE=offline, NAPMEM_EMBED_BACKEND=hashed, NAPMEM_METRICS=0 and the explicit temporary configuration. PYTHONPATH contained only the temporary guard directory.

```sh
NAPMEM_EMBED_BACKEND=hashed NAPMEM_MODE=offline /Users/mitch/dev/llm-memory-pyramid/.venv/bin/napmem --version
NAPMEM_EMBED_BACKEND=hashed NAPMEM_MODE=offline /Users/mitch/dev/llm-memory-pyramid/.venv/bin/napmem --pyramid /var/folders/hz/s7btlxx54c32yt375m03q0h40000gn/T/napmem-developer-venv-parity-ihtvf65t/stores/main.json demo
NAPMEM_EMBED_BACKEND=hashed NAPMEM_MODE=offline /Users/mitch/dev/llm-memory-pyramid/.venv/bin/napmem --pyramid /var/folders/hz/s7btlxx54c32yt375m03q0h40000gn/T/napmem-developer-venv-parity-ihtvf65t/stores/main.json query 'favorite editor' --scope project:napmem-demo-alpha
NAPMEM_EMBED_BACKEND=hashed NAPMEM_MODE=offline /Users/mitch/dev/llm-memory-pyramid/.venv/bin/napmem --pyramid /var/folders/hz/s7btlxx54c32yt375m03q0h40000gn/T/napmem-developer-venv-parity-ihtvf65t/stores/main.json query 'favorite editor' --scope project:napmem-demo-beta
NAPMEM_EMBED_BACKEND=hashed NAPMEM_MODE=offline /Users/mitch/dev/llm-memory-pyramid/.venv/bin/napmem --pyramid /var/folders/hz/s7btlxx54c32yt375m03q0h40000gn/T/napmem-developer-venv-parity-ihtvf65t/stores/main.json doctor
```

Evidence artifacts:

- /var/folders/hz/s7btlxx54c32yt375m03q0h40000gn/T/napmem-developer-venv-parity-ihtvf65t/receipt.json
- /var/folders/hz/s7btlxx54c32yt375m03q0h40000gn/T/napmem-developer-venv-parity-ihtvf65t/identity.json
- /var/folders/hz/s7btlxx54c32yt375m03q0h40000gn/T/napmem-developer-venv-parity-ihtvf65t/source-manifest.json
- /var/folders/hz/s7btlxx54c32yt375m03q0h40000gn/T/napmem-developer-venv-parity-ihtvf65t/commands.json
- /var/folders/hz/s7btlxx54c32yt375m03q0h40000gn/T/napmem-developer-venv-parity-ihtvf65t/guard-processes.jsonl
- /var/folders/hz/s7btlxx54c32yt375m03q0h40000gn/T/napmem-developer-venv-parity-ihtvf65t/guard-attempts.jsonl

Limit: this is an existing developer environment with an installed optional client. It verifies offline loaded-state parity, not production services or online integrations. No production/default data, model, embedding server, indexer, SSH connection or deployment was used.

## Developer environment machine-readable receipt

```json
{
  "agent": "live-acceptance-verifier",
  "definition_version": "1.0.0",
  "status": "complete",
  "evidence": [
    {
      "source": "/var/folders/hz/s7btlxx54c32yt375m03q0h40000gn/T/napmem-developer-venv-parity-ihtvf65t/receipt.json",
      "observed_at": "2026-10-27T13:25:27.926218+00:00",
      "supported_claim": "Actual developer console version, temporary demo/scoped queries/doctor and runtime guards passed."
    },
    {
      "source": "/var/folders/hz/s7btlxx54c32yt375m03q0h40000gn/T/napmem-developer-venv-parity-ihtvf65t/identity.json",
      "observed_at": "2026-10-27T13:25:27.926218+00:00",
      "supported_claim": "Installed package metadata is 0.2.0 and all 23 installed modules match merged main."
    }
  ],
  "changes": [
    "/Users/mitch/dev/llm-memory-pyramid/docs/acceptance-offline-2026-10-27.md"
  ],
  "remaining": [],
  "details": {
    "surface": "Existing developer virtual environment console outside checkout",
    "acceptance_condition": "Actual installed napmem reports 0.2.0, matches merged runtime bytes and passes temporary offline demo/query/doctor without probes or runtime network/process attempts.",
    "source_revision": "be84a2341a4b4780eda53d7600bafeff80e4c80e",
    "loaded_revision": "llm-memory-pyramid 0.2.0; installed METADATA SHA256 44c16ac97956d06a2311ed916ea0df5235578d0e7fa360367915ed9869743253",
    "process_or_origin": "/Users/mitch/dev/llm-memory-pyramid/.venv/bin/napmem",
    "configuration_identity": "/var/folders/hz/s7btlxx54c32yt375m03q0h40000gn/T/napmem-developer-venv-parity-ihtvf65t/config.toml; explicit temporary pyramid; offline/hashed; temporary PYTHONPATH guard only",
    "observations": {
      "installed_modules_match_merged_main": 23,
      "console_commands_exit_zero": 5,
      "guarded_processes": 7,
      "positive_guard_probes": 2,
      "runtime_guard_attempts": 0,
      "demo_alpha": "Vim",
      "demo_beta": "VS Code",
      "doctor_probed": false,
      "doctor_store_tree_unchanged": true,
      "persistent_environment_or_hooks_modified": false
    },
    "mismatches": [],
    "unverified_checks": [
      "Online integrations and production services are outside this focused parity check."
    ]
  }
}
```
