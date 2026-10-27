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
