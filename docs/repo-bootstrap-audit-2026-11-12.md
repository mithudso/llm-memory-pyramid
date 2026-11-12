# Repository bootstrap audit — 2026-11-12

Full repo-bootstrapper and full code-deep-optimizer maintenance of owned
`mithudso/llm-memory-pyramid`, base `7367fa42056a360df653b3480f3c6a582318c0f3`.
The original clean main and pre-existing locked worktree remain preserved.
This task owns only its isolated worktree and external artifacts. Historical
2026-10-26 audits remain intact; their statuses are not reused as current proof.

## Manifest and component audit

| Family | Evidence/action | Outcome |
|---|---|---|
| AGENTS/CLAUDE/GEMINI/Copilot instructions | Existing invariants and request/work-log contract retained; optional dependency and minimum runtime guidance corrected | Audited; no new local agents |
| README/contributing/PR templates | Existing package shape, source installation and wiki navigation checked; full suite extra clarified | Updated factual guidance |
| memory.md/prompts.md | v2.3.0 records scoped request, package/MCP/prompt patches and actual continuation/delivery limits | Updated; no copied private prompt body |
| Log rotation/archive tooling | Logs are small tracked prose; no always-running logger or Node tool added | Existing convention retained |
| pyproject/build | Python3.11+, stdlib core, setuptools build,23 top-level runtime modules and declared evaluation data | Patch0.2.1; wheel tested; no package publish |
| All runtime/source/config/tests |70 maintained paths; no silent cap; initial69 plus new synthetic regression suite | Individual source-hash diagnostics and two blind gates; see coverage JSON |
| .editorconfig/.gitattributes/.gitignore | UTF-8/LF/editor defaults; runtime stores/caches/build artifacts excluded | Retained; source corpus excluded individually |
| .env.example | Placeholder-only documented optional endpoints/modes, no secret values read | Retained |
| VS Code settings/extensions/launch | Python editor/debug/test config; no extension/service activation | Audited; no UI acceptance claim |
| Root .mcp.json | Established stdio proxy entry; no new editor-specific or admin MCP surface | Retained; fixture protocol tests |
| CI | SHA-pinned Actions,3.11/3.12/3.14 integration, core-only fork-safe job, Ruff, maps/eval/shell checks | All runtime test descendants network-isolated with scratch homes |
| Dependabot | Monthly pip and Actions manifests | Retained |
| Funding | Unsupported keys/reserved YAML fixed with GitHub-supported existing destinations | No payment or funding-policy change |
| CODEOWNERS/issue templates/license/conduct/security policy | Existing maintainer evidence inspected | No new license, legal promise or response SLA |
| Architecture/components/requirements | Current offline core/optional clients/atomic stores, historical topology clearly labeled | Factual docs updated; valid docs preserved |
| Installation/development/onboarding/testing | Optional full integration extra, exact commands and complete suite table | Updated; no fixed inflated coverage claim |
| Persistence/controls/retrieval/evidence | Stable context IDs, correction safety, source creation identity, provider/lease recovery and snapshot publication | Repaired established contracts |
| MCP/CLI | Version/exit/resource/budget behavior documented | No new server architecture |
| Security/logging/external calls | Every maintained transport family, egress, failure/retry and fixture boundaries enumerated | Complete static inventory; generic5-standard parity not claimed |
| Caching/observability | Actual persistent metadata/cache layers and no-payload status documented | Removed obsolete no-cache claim |
| Runbooks/deploy/systemd | Historical fleet facts retained with date/verification limits; operator-only procedures | No scheduler/service/deployment operation |
| Maintained wiki | docs/wiki/README.md links actual architecture, operations, tests, audits and limits | KNOW-1255 fulfilled |
| Retrieval indexes/llms family | Deterministic static generator handles binary assets and refuses output symlinks; all current paths indexed | Refreshed/check gate; no semantic generation |
| Semantic pipeline/watchers | Existing opt-in module retained; frozen/live vectors untouched | No indexing, model inference or new watcher |
| Runtime operation registry/dashboard/JSONL sink | Existing CLI/MCP/logging/atomic checks documented in external calls/tool inventory | Accepted architecture exceptions; not falsely passed |
| Context skill scaffolding/global installation | Existing Python/security/tooling guidance fits repo; no new context service/concept tree | Inapplicable; no global skill writes |
| Hub registry | Existing mixed Git hook registry block retained by exact command-scoped filter | Registration delegated to parent coordinator |

## Verification and delivery boundaries

See the [optimizer report](code-deep-optimizer-2026-11-12.md) for baseline,
regressions, two-gate dissent and focused repairs. Final526-test suite,
compilation, Ruff, exact generated-map check, shell syntax, frozen100-case
heldout gate, wheel/core acceptance and actual final PR CI govern delivery.
All source tests use process-tree OS network denial including loopback, scratch
provider/data/model/auth homes, synthetic stores, fake SDKs and owned children.
CI dependency installation occurs before isolation, with the existing pinned
private client and deploy-key handling. No real model/API benchmarks ran.

Before every task commit, inspect the effective post-commit hook hash. The
approved exact mixed-hook filter suppresses only the semantic indexer block
and retains registry/validation behavior. Use command-scoped core.hooksPath;
never --no-verify or persistent/global hook changes. The FILTER-RECEIPT remains
in task artifacts. Unknown hook changes block commits until understood.

No current research/customer bodies, live stores, embeddings, caches, services,
trade operations, new licenses or policy commitments were changed. Original
checkout synchronization is conditional on cleanliness, divergence and absence
of runtime activation risk. Only this task's clean merged worktree/branch may
be removed. Exact PR, merge, remote-tree verification, sync/cleanup and Stele
completion are recorded by the external machine receipt after delivery.

## Explicit residuals and maintainer choices

- Optimizer remains BLIND-AUDIT-DISSENT. Both gate2 defects received focused
  repairs and normal-suite verification, without a third blind gate.
- Source rename identity requires available creation-time evidence. macOS uses
  its native birth timestamp; Linux uses statx STATX_BTIME. An unsupported
  filesystem cannot prove a rename from inode alone. Use an explicit mapping
  or ingest as a new source; unknown legacy birth metadata is conservative.
- Queue safety trusts the current user's non-shared directory. Same-user
  directory replacement is within that filesystem boundary.
- Public SDK versions are optional and unbounded; sampled official PyPI/OSV
  metadata is not a full advisory/attestation promise for every installation.
  The private client remains pinned; no dependency or secret was upgraded.
- Generic operation dashboard/registry, central structured error sink, ant-login
  profile adapter and Windows pipe portability remain architecture choices.
- Historical deployment/fleet and production model quality were not reverified.
- Synthetic retrieval retains known unsupported-result/abstention limitations;
  a frozen regression pass does not establish universal factual support.
- Semantic generation stays paused. Hub registration is delegated, not an
  unresolved product defect. No GitHub wiki publication was requested; the
  maintained project wiki lives in the repository.

## Primary references checked

[GitHub funding syntax](https://docs.github.com/en/repositories/managing-your-repositorys-settings-and-features/customizing-your-repository/displaying-a-sponsor-button-in-your-repository),
[Linux statx UAPI](https://github.com/torvalds/linux/blob/master/include/uapi/linux/stat.h),
[statx manual](https://man7.org/linux/man-pages/man2/statx.2.html),
[SQLite open boundary](https://www.sqlite.org/c3ref/open.html), and official
PyPI/OSV version metadata. No customer data or credentials were used for research.
