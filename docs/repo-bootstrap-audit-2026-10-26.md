# Repository bootstrap audit — 2026-10-26

## Scope and provenance

The user requested repo-bootstrapper and deep-code-optimizer. This pass adapts
repo-bootstrapper 5.4.1 to the existing Python CLI/MCP repository. It does not
invent a Node service, dashboard, duplicate file-embedding pipeline or new
runtime dependencies. Baseline: clean main at 1f3d21d, no unfinished Git
operations and no open PRs. All original runtime/source files received the
optimizer's per-file diagnostic pass. No earlier repo-bootstrap audit existed. The static-map generator also received an idempotence repair after its first generate/check exposed a self-description dependency; immediate regeneration/check now passes.

## Manifest audit

| Manifest area | Observed state and action | Result |
|---|---|---|
| CLAUDE/AGENTS/GEMINI/Copilot | Existing files; corrected Python/dependency/test rules, architecture shape and workflow version scope | Updated |
| README/contributor/PR guidance | Fixed obsolete counts, install path, CI matrix and lint status | Updated |
| Versioned request/work logs | Saved exact request, v1.7.0 delta, package 0.1.1 delta and continuation state | Updated |
| Log rotation/archive tooling | Both logs below 12 KB; no rotation threshold reached, no Node dependency added for an inactive need | Adapted |
| .editorconfig/.gitattributes | Existing UTF-8/LF/indent/final-newline rules and text normalization inspected | Retained |
| .gitignore/.env.example | Added safe env template, secret/build/cache/state exclusions | Updated |
| Node version pins | No Node runtime/package | N/A |
| VS Code settings/extensions/launch | Existing Python editor/test/debug setup inspected | Retained |
| VS Code MCP duplicate | Root .mcp.json is the established client entry; no editor-specific runtime installation performed | Adapted; no VS Code acceptance claim |
| Root MCP config | Existing proxy command retained; actual protocol tools checked through offline subprocess tests | Retained |
| CI/dependabot | Explicit Ruff rules/version, SHA-pinned Actions, pinned shared library, doc-map and shell checks, pip update policy | Updated |
| CODEOWNERS/issue templates/license/conduct | Existing owner/templates/Apache license/conduct inspected; no fabricated ownership or response SLA | Retained |
| Architecture/components/requirements | Corrected optional semantic dedup, installed dependency, extraction/failover and test coverage | Updated |
| Development/testing/install/onboarding | Replaced obsolete stdlib-only installation and stale suite/version counts | Updated |
| Security/logging/external calls | Documented actual HTTP/SDK/SSH/subprocess boundaries and privacy rules; removed false no-network/no-subprocess claims | Updated |
| Runbooks/integrations/known issues | Corrected extraction chain, persistent watermark, SDK credential boundary and current limits | Updated |
| Deployment/global hook references | Preserved historical fleet/hook evidence; this run did not verify or change deployed systems | Retained with scope limits |
| Retrieval maps/llms family | Added deterministic stdlib-only generator/checker and CI drift gate | Generated and exact-content checked |
| semantic_indexer/watch scripts | Existing embedding module and external hub own indexing; no duplicate ChromaDB/Ollama infrastructure or indexing run | Adapted |
| Generic operations registry/dashboard/JSONL error service | Absent from established CLI/MCP architecture; current triggers/logging/fallback/validation documented honestly | Accepted architecture exceptions; full mdb-tam parity not claimed |
| Concept tree/new skill scaffolding | No local concept tree or repo-local agents; Python/security/tooling skills cover this stack | N/A |
| Hub registry | Existing project purpose/path/remote and stale MCP activation description refreshed; existing scheduler issue #29 preserved | Updated |

## Verified setup repair

The checkout had no installed ollama-client and the default Python could not
import the extension suite. Installed only the declared package/dependency in
an ignored local Python 3.12 virtual environment. This ran no model, embedding,
indexer, consolidator wrapper, scheduler or production store operation.

Previous GitHub CI failed private dependency authentication and an existing
Ruff UTC-alias check. The repo had no Actions secrets. Created a dedicated
read-only dependency deploy key (id 167768571), verified its SSH read access,
stored it as OLLAMA_CLIENT_DEPLOY_KEY on this repo, and removed local private
key copies. The workflow pins the library revision and verifies GitHub host
keys obtained from the official GitHub metadata API. No personal token was
copied. The code review report contains revocation commands.

## Validation and remaining scope

First complete baseline: 66 tests pass. After fixes: 111 tests pass on Python
3.12; compile, Ruff and shell syntax pass. Python 3.14 also passes the 110-test candidate; the final additional decoder regression is covered locally on 3.12 and in the CI matrix. Generated maps pass exact-content checks. Two independent code reviews ran; the second dissented on one remaining parser boundary. Its fix and a two-file regression are verified, while the optimizer retains BLIND-AUDIT-DISSENT as its bounded exit status. The external dossier verified 77/77 source hashes, 77 cards and 11 outputs at
source commit 9d23b3b. PR #15 merged as ee2170da1eff9effea62e47621257a298f299a16
with all 111 tests green on Python 3.11/3.12/3.14 plus Ruff, static maps and
shell syntax. Main was synced and the task branch deleted:
https://github.com/mithudso/llm-memory-pyramid/pull/15
https://github.com/mithudso/llm-memory-pyramid/actions/runs/40413224889

The post-commit hook starts automatic indexing. Per-command hook overrides
preserved the indexing pause during commit and sync; persistent Git config
was unchanged. Registry metadata was updated explicitly. TASK-220 records
final delivery of these receipts.

No live runtime acceptance, production deployment, global hook reload,
embedding generation, indexing, model quality qualification or scheduler
restart was performed. Optional Anthropic dependency/advisory scanning was
not a full vulnerability audit. The existing scheduler registration question
#29 remains an external operational item, not an unverified production outage.

## Durable lessons

Preserve operator files when revoking mirror links. Validate disposable cache
structure before reuse and bind watermarks to sessions present in the store.
Keep validation logs free of memory payloads. Bound child pipe reads/writes
and parser failures. Keep every duplicate occurrence ID stable. Treat raw
source paths as changeable objects when computing read-only statistics.
