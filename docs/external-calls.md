# External calls

## Inventory

Every transport below is optional at runtime. Core heuristic distillation and
substring retrieval use no external services. File/line locations move; symbol
names below are stable lookup anchors.

| Source and trigger | Target/transport | Outcome logging and failure policy | Offline tests / persisted verification |
|---|---|---|---|
| `llm_extractor.py:extract_direct`; CLI `--no-batch` | Anthropic Messages API through SDK, HTTPS | Request/usage/error logs; SDK retry policy, errors become `ExtractionError` | Extension parsing/SDK fakes; validated units enter atomic ingest |
| `llm_extractor.py:extract_batch`; extraction CLI/consolidator | SDK batches create/retrieve/results/cancel, HTTPS | Batch/item logs; SDK retries and bounded polling; per-item extraction failures skip/fallback | Extension batch mocks; output validation before atomic ingest |
| `semantic_index.py:OllamaBackend.probe/embed`; semantic query/dedup CLI | Configured Ollama tags/embed through `ollama-client`, HTTP or configured HTTPS | Host selection/cache warnings; shared pool failover; auto backend may fall back to hashed, retrieval may fall back to substring | Extension host mocks and cache regressions; validated vectors saved atomically |
| `ollama_extractor.py:ollama_available/extract_ollama`; consolidator `--extraction ollama`/`auto` | Configured Ollama tags/chat through shared client | Model/host failure logs; dead hosts benched, missing model permits next model; heuristic fallback per file | Extension HTTP/chat fakes; same validated ingest path |
| `napmem_mcp_failover.py:probe_remote/primary_cmd`; proxy startup/status | SSH probe and remote MCP subprocess | Probe timeout and lifecycle logs; remote loss/request timeout triggers local mirror | Fake child processes; no persisted data from probe/relay |
| `napmem_mcp_failover.py:sync_mirror`; `--sync-mirror`/background refresh | SSH `cat` of configured pyramid/cache | Transfer outcome/warning; bounded transfer, private temp files and atomic replace; optional cache copy may fail separately | Mocked SSH copy/concurrent-writer tests; pyramid JSON validated before replacement |
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
