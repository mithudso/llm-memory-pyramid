# External calls

## Inventory

Every transport below is optional at runtime. Core heuristic distillation and
default offline hybrid retrieval use no external services. File/line locations move; symbol
names below are stable lookup anchors.

| Source and trigger | Target/transport | Outcome logging and failure policy | Offline tests / persisted verification |
|---|---|---|---|
| `llm_extractor.py:extract_direct`; CLI `--no-batch` | Anthropic Messages API through SDK, HTTPS | Request/usage/error logs; SDK retry policy, errors become `ExtractionError` | Extension parsing/SDK fakes; validated units enter atomic ingest |
| `llm_extractor.py:extract_batch`; extraction CLI/consolidator | SDK batches create/retrieve/results/cancel, HTTPS | Batch/item logs; SDK retries and bounded polling; per-item extraction failures skip/fallback | Extension batch mocks; output validation before atomic ingest |
| `semantic_index.py:OllamaBackend.probe/embed`; semantic query/dedup CLI | Configured Ollama tags/embed through `ollama-client`, HTTP or configured HTTPS | Host selection/cache warnings; shared pool failover; auto backend may fall back to hashed, retrieval may fall back to substring | Extension host mocks and cache regressions; validated vectors saved atomically |
| `ollama_extractor.py:ollama_available/extract_ollama`; consolidator `--extraction ollama`/`auto` | Configured Ollama tags/chat through shared client | Model/host failure logs; dead hosts benched, missing model permits next model; heuristic fallback per file | Extension HTTP/chat fakes; same validated ingest path |
| `napmem_mcp_failover.py:probe_remote/primary_cmd`; proxy startup/status | SSH probe and remote MCP subprocess | Probe timeout and lifecycle logs; remote loss/request timeout triggers local mirror | Fake child processes; no persisted data from probe/relay |
| `napmem_mcp_failover.py:sync_mirror`; `--sync-mirror`/background refresh | One quoted SSH snapshot export/archive command | Bounded transfer; validated store/cache manifest and atomic generation publication; failed refresh preserves active generation | Fake transfers/concurrent refresh tests; no production SSH exercised |
| `napmem_mcp_failover.py:Backend`; local fallback | Local Python MCP subprocess and stdio pipes | Reader/writer/exit logs; bounded restart count and pending-request errors | Local strict fake servers and temporary mirrors; no store writes |
| `scripts/run-naptime.sh:mirror`; sweep wrapper | Local `readlink`, `ln`, filesystem discovery, Python consolidator child | Refused/colliding path warnings; preserves plain operator files and avoids destination-link traversal | Extracted-function temporary fixtures; guarded read validates opened source before extraction |

Runtime text egress depends on selected modes. Full source text may go to
Anthropic or Ollama chat. Record/query text may go to Ollama embeddings. SSH
copies memory snapshots and relays tool responses. See [Security](SECURITY.md).

## Standard adaptation and remaining gaps

The project uses existing CLI/MCP triggers, stdlib logging, shared-client
retries/fallback and schema/atomic-write checks. It has no generic operation
registry, persisted attempt-history API, central structured JSONL error sink,
or dashboard cards. These mdb-tam standards remain unimplemented; the audit
does not mark them passed. Adding a server or dashboard only to satisfy a
checklist would change the established architecture.

## Credentials

The optional Anthropic SDK resolves its own supported credentials. This repo
constructs its client without an `ant auth login` profile adapter. SSH uses the
operator's SSH configuration. Ollama endpoints can be remote and may use
plain HTTP; trust and protect that network or select the hashed backend.
Never commit credentials or memory payloads to the environment template.

## Complete maintained transport families (2026-11-12)

| Family / exact anchors | Egress and bounds | Failure / retry / tests |
|---|---|---|
| `llm_extractor.extract_direct`, `extract_batch`, `napmem_jobs.submit/collect` | Explicit Anthropic source prompts, SDK HTTPS;2MiB source, bounded batch result/polling | Unknown post-intent submission stays `SubmissionOutcomeUnknown`, no automatic resubmit; mocked SDK tests and lease-fenced atomic commit |
| `napmem_cli._ingest` / `naptime_consolidator._make_client`, `_durable_sweep` | Explicit cloud mode only; heuristic async never collects cloud work;256 files/64MiB sweep cap | Safe exception classes; stale/failed CLI exits nonzero; source-revision recheck; fake SDK tests |
| `ollama_extractor._client_for`, `ollama_available`, `extract_ollama` | Explicit extraction mode, shared HTTP client; exact model tag, per-call timeout | Host failover and heuristic fallback; model-list/chat fakes; no local inference in tests |
| `semantic_index.OllamaBackend`, `select_backend`; explicit semantic CLI/dedup | Query/record embedding HTTP only in selected legacy/semantic path | Shared client and hashed fallback; strict vector validation/cache generation/hash checks; mocked backends |
| `napmem_mcp_failover.primary_cmd`, `remote_snapshot_cmd`, `probe_remote`, `_receive_snapshot` | SSH remote Python and snapshot stdout; shell-quoted argv, finite timeouts, bounded archive/stderr | Sanitized warning text; failed transfer preserves active snapshot; fake children/valid oversized archive tests |
| `napmem_mcp_failover.Backend`, `Proxy` | Local/remote subprocess stdio, no shell in local spawn;64 pending/32MiB, local+remote deadlines,1s binary-output stall limit | Unique internal replay IDs; bounded restarts/errors; malformed response cannot silently lose pending request; fixture subprocess tests |
| `napmem_adapters._git` / Git source ingestion | Git subprocess local object database, bounded stdout/stderr/deadline; no shell/filter/textconv execution | Pinned immutable commit/blob provenance; activated malicious-driver fixture proves no execution |
| `scripts/run-naptime.sh` | POSIX local discovery/mirror + Python child; inherited whole-run lock, root validation and collision suffixes | Only extracted mirror function tested on synthetic trees; entire scheduled wrapper never executed in maintenance |
| `scripts/repo_docs.census` | Read-only `git ls-files` subprocess; no runtime imports or corpus parsing | Static maps, binary descriptions, contained atomic UTF-8 output; check mode writes nothing |
| Test subprocess families | Python fake MCP/CLI/Git/lock/FIFO fixtures and extracted mirror shell | All descendants OS-isolated; scratch data/config/cache/auth/models; hard timeouts and process cleanup |
| CI dependency installation | GitHub Actions/PyPI and pinned private shared library before test isolation | Exact Actions SHAs and private-client SHA; fork PR cannot consume deploy-key secret; package metadata queries only |

See [tool inventory](tool-inventory.json). No generic runtime execution registry,
dashboard, central error service or new MCP administration tools were added.
These remain architecture exceptions, not claims of full mdb-tam parity.
