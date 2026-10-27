# NapMem product improvement roadmap

Version: 1.0.0
Date: 2026-10-27
Delta: initial product assessment after the repository bootstrap and source audit.
Source baseline: `edd28fbcc2d94c906af701cef4ef330d4d0c94c2`.

## Recommendation

Build NapMem into a private, inspectable memory layer that helps agents recall
the right evidence, understand when it applies, and respect corrections. Its
strongest opportunity is dependable memory across sessions and agent clients.

The current foundation is useful: stable atomic record IDs, duplicate-source
anchors, incremental ingestion, offline substring retrieval, optional local
models, a read-only MCP surface and remote-to-mirror failover. Preserve these.
The next work should establish memory quality and user control before adding
more connectors, larger models or a broad application interface.

This document proposes product changes. It does not implement them. The
previous optimizer result remains `BLIND-AUDIT-DISSENT`; source validation does
not establish production runtime health or retrieval quality.

## What the current code establishes

| Area | Current behavior | Product implication |
|---|---|---|
| Retrieval | Substring matching across layers, or top-k cosine search over Layer 1 | No combined exact/semantic ranking, cross-layer retrieval plan or general response budget |
| Profiles | Every high-salience fact/action becomes a trait; confidence is always 0.95 | A temporary task can look like a durable preference; contradictory traits coexist |
| Time and scope | Records have creation timestamps and source anchors | No explicit subject/project scope, valid-time interval, supersession or expiry policy |
| Provenance | File, heading, line reference and duplicate anchors | A pointer to a mutable file is weaker than a verified quotation from a source revision |
| Persistence | Whole-store JSON replacement; single-writer convention | Atomic replacement avoids partial files but does not prevent lost updates between writers |
| Ingestion | Basename-derived session IDs, mtime gate and blocking batch polling | Renames, preserved timestamps, deletion and interrupted jobs need explicit lifecycle behavior |
| Operations | Four MCP tools, separate global hooks and mirror fallback | Useful infrastructure exists, but setup, health and feedback span several components |
| Measurement | Offline behavioral tests and estimated compression statistics | No checked-in task-quality benchmark; compression is not measured per-query savings |

Source anchors:

- [/Users/mitch/dev/llm-memory-pyramid/napmem_retrieval_agent.py:35](/Users/mitch/dev/llm-memory-pyramid/napmem_retrieval_agent.py:35): substring search; semantic search at line 75; estimated savings at line 157.
- [/Users/mitch/dev/llm-memory-pyramid/memory_pyramid_distiller.py:369](/Users/mitch/dev/llm-memory-pyramid/memory_pyramid_distiller.py:369): tracks and profiles; `PROFILE_CONFIDENCE = 0.95` at line 29.
- [/Users/mitch/dev/llm-memory-pyramid/memory_pyramid_schema.json](/Users/mitch/dev/llm-memory-pyramid/memory_pyramid_schema.json): current persisted fields.
- [/Users/mitch/dev/llm-memory-pyramid/memory_pyramid_distiller.py:73](/Users/mitch/dev/llm-memory-pyramid/memory_pyramid_distiller.py:73): atomic save; ingestion at line 419.
- [/Users/mitch/dev/llm-memory-pyramid/naptime_consolidator.py:218](/Users/mitch/dev/llm-memory-pyramid/naptime_consolidator.py:218): source change collection; basename session identity at line 49.
- [/Users/mitch/dev/llm-memory-pyramid/llm_extractor.py:173](/Users/mitch/dev/llm-memory-pyramid/llm_extractor.py:173): submit-and-poll batch lifecycle.
- [/Users/mitch/dev/llm-memory-pyramid/napmem_mcp_server.py:39](/Users/mitch/dev/llm-memory-pyramid/napmem_mcp_server.py:39): tool definitions; JSON serialized into text results at line 201.
- [/Users/mitch/dev/llm-memory-pyramid/napmem_mcp_failover.py:148](/Users/mitch/dev/llm-memory-pyramid/napmem_mcp_failover.py:148): separate snapshot file transfers.
- [/Users/mitch/dev/llm-memory-pyramid/docs/known-issues.md](/Users/mitch/dev/llm-memory-pyramid/docs/known-issues.md): accepted limits.

An in-memory probe against the current profile builder used two conflicting
editor preferences and `Deploy the temporary test build.`. All three became
profile traits with confidence 0.95. A substring query for `which editor`
returned no records. This demonstrates those specific behaviors; it is not a
representative accuracy benchmark and did not exercise semantic retrieval.

## Ranked improvements

Sizes describe relative engineering scope, not delivery promises: S is a
contained feature; M crosses components; L needs a data migration or several
coordinated behaviors. A complete item can contain smaller independently
useful increments.

| Rank | Improvement | Value | Size |
|---|---|---|---|
| 1 | Memory quality benchmark | Prove which changes improve useful recall | M |
| 2 | Scoped, time-aware memory and trustworthy profiles | Prevent wrong or outdated guidance | L |
| 3 | Hybrid retrieval and bounded context assembly | Retrieve useful evidence within an explicit budget | M |
| 4 | Correct, pin, forget and exclude controls | Give the user durable control over memory | L |
| 5 | Verified, versioned provenance | Explain exactly where a remembered claim came from | M |
| 6 | Transactional writes and resumable ingestion | Protect memory and survive interrupted work | L |
| 7 | Portable installation and one configuration surface | Make first use reliable on a clean machine | M |
| 8 | Memory inspector and review queue | Make memory understandable and correctable | M |
| 9 | Quality, freshness and cost observability | Detect degraded memory before it affects work | M |
| 10 | Consistent client API and optional source adapters | Extend reach without coupling the core to one harness | M |

### 1. Establish a memory quality benchmark

Build a small, sanitized golden corpus of roughly 200 realistic questions and
expected evidence IDs. Include exact errors and symbols, paraphrases,
cross-session questions, conflicting updates, project boundaries, missing
answers, renamed/deleted sources, misleading source instructions and stale
mirrors. Split development cases from a held-out set before tuning.

Compare substring, hashed-TF, real embeddings and proposed hybrid retrieval
against the same corpus. Record Recall@5, ranking quality, unsupported memory
injection, current-fact selection, abstention, latency and returned context
size. Keep retrieval scoring separate from extraction accuracy and downstream
agent answer quality. An LLM judge must not be the sole correctness oracle.

Keep deterministic fixture evaluation in CI. Run model-dependent evaluation
as a separate explicitly enabled job. Existing tests remain the correctness
gate; evaluation supplies the product-quality gate. LongMemEval provides a
useful external model for extraction, updates, temporal reasoning,
cross-session reasoning and abstention [R1].

**Acceptance:** publish reproducible baseline results and per-category scores.
Every retrieval change reports an ablation against the strongest baseline.
Protected scope and explicit-correction fixtures must all pass. Set broader
accuracy and latency release thresholds after measuring the baseline; no
benchmark score is claimed by this assessment.

### 2. Add scope, time and memory lifecycle semantics

Give each assertion an explicit subject, scope, evidence source and lifecycle.
Distinguish user preferences, project decisions, constraints, observations,
temporary tasks and proposed ideas. Extend the existing taxonomy compatibly
rather than silently relabeling old records.

Record when a fact was observed separately from when it applies. Support
`valid_from`, `valid_to`, `supersedes` and `last_verified_at`, with an unknown
state when the source does not establish them. Do not infer real-world event
time from ingestion time. A newer timestamp alone does not settle a conflict.

Example: “Use Vim for Alpha” followed by “Use VS Code for Alpha now” should
produce a current preference and an inspectable historical assertion. A
preference for Beta should not override Alpha. Conflicting evidence without
an explicit correction should remain visibly unresolved.

Require explicit or sufficiently corroborated evidence before promoting a
record to a durable profile. Remove the appearance of calibrated certainty
from the constant 0.95 score. Derive topic summaries from supported current
facts; retain uncertainty and source citations. Give derived tracks/profiles
stable content identities where clients need durable links.

**Acceptance:** current/as-of queries behave correctly on update fixtures;
temporary tasks do not become permanent preferences; out-of-scope records
never enter ranking candidates. Duplicate anchors retain their own scope and
authority, even if canonical storage is shared. Existing record and duplicate
IDs remain resolvable after migration.

### 3. Combine exact and semantic retrieval, then pack context

Replace the either/or search choice with a shared retrieval pipeline: apply
scope/lifecycle filters, collect lexical and semantic candidates, fuse ranks,
remove redundant evidence, then assemble a bounded response. Preserve an
exact-identifier lane for paths, error messages and symbols. Benchmark a
reranker only after the simpler hybrid baseline works [R2].

Use the pyramid actively: a concise profile or track can orient the agent,
then linked atomic records provide evidence. A summary must not replace the
supporting record when the question asks why a decision was made. Add
query-specific expansion into nearby source context when needed.

Apply result limits and byte limits to every mode, including topic expansion.
Offer an estimated token budget and disclose the estimator until a client
provides actual token counts. Return truncation, omitted-result counts,
backend, snapshot age and relevance status. A top-k result is not proof that
anything relevant was found. Calibrate abstention separately for each backend.

**Acceptance:** hybrid retrieval improves held-out results without breaking
identifier cases; responses honor declared limits; irrelevant queries can
return no useful evidence; lexical retrieval remains useful without a model
server. Measure gains rather than importing another system's percentages.

### 4. Let the user correct, pin, forget and exclude memory

Add explicit controls to correct a claim, pin an instruction within a scope,
expire temporary context, exclude a source and forget a record or session.
Store corrections and exclusions outside derived layers so re-ingestion
cannot silently undo them. Keep mutation capabilities separate from the
default read-only retrieval MCP surface.

Use a previewable change set and an auditable mutation journal. Normal
supersession preserves history. Explicit forgetting has a separate retention
policy covering canonical data, duplicate anchors, embeddings, derived
layers, mirrors, exports and backups. A tombstone alone does not erase stored
text. Report pending deletion acknowledgments from offline mirrors; define
when stale mirrors must stop serving rather than promise immediate deletion
from an unreachable machine.

**Acceptance:** a corrected fact stays corrected after re-ingestion; a
forgotten item cannot reappear through duplicate promotion or source replay;
the user can see the scope and completion state of each operation.

### 5. Make provenance verifiable and versioned

Store the source content hash, an exact supporting quotation and its range,
the extraction method/model/prompt version, and a source revision identifier.
Verify that quoted evidence occurs in that revision before admitting a
high-trust assertion. Treat paraphrased assertions and their literal evidence
as different fields. Mark unsupported or unverifiable assertions clearly.

Expose “why this memory?” with the evidence, its age, the scope, any conflict
and the ranking signals. Do not treat a file path or a schema-valid model
response as proof of factual support. Raw snapshots should be opt-in under
the same retention/privacy controls as other memory.

**Acceptance:** every high-trust profile claim resolves to verified evidence
or an explicit unverified state. Moving or editing a file does not make an old
line reference appear verified against new content.

### 6. Protect writes and resume interrupted ingestion

First enforce one writer across the entire load/reconcile/save operation and
add a store generation check. Locking only `save()` still permits two writers
to commit different stale snapshots. Exercise concurrent writers and crash
recovery before changing storage.

Evaluate a stdlib `sqlite3` backend when measured scale or writer requirements
justify it. Transactions, explicit migrations, JSON import/export and
optional FTS5 lexical indexing fit the current lightweight architecture
[R3, R4]. SQLite still serializes writers; handle busy/retry behavior and do
not place a live database on a shared filesystem as a multi-host design.
Probe FTS5 availability and retain a supported fallback.

Give sources stable identities independent of basenames. Define rename,
missing-source, explicit deletion and reappearance policies. Periodic content
verification should catch same-mtime edits. Preserve existing record IDs via
an explicit compatibility mapping.

Persist extraction jobs with source hash, job ID, status, extractor version,
attempt count and result hash. Separate submit, collect and commit so a
one-hour batch cannot occupy the whole sweep process. Revalidate the source
revision before committing delayed output. Make replay idempotent.

Publish mirrors with a generation manifest and checksums. A generation must
bind store data, optional vector cache and embedding configuration. Disclose
an omitted cache and use lexical retrieval while it is unavailable.

**Acceptance:** concurrent writers cannot silently lose updates; a killed job
resumes without duplicate ingestion; stale batch output cannot replace newer
source content; restore preserves all record IDs; mirror generation and age
are visible and validated.

### 7. Make installation and configuration predictable

Expose one `napmem` CLI with coherent `init`, `ingest`, `query`, `inspect` and
`doctor` subcommands. Use one documented config file, explicit environment/CLI
precedence, and named offline/local/remote modes. This consolidates existing
capabilities rather than adding a second implementation.

The default doctor should inspect local configuration without probing
services or creating stores. Explicit probe options can test authorized
endpoints and installed client wiring. Show the selected store, source roots,
actual backend and mirror state in plain language. Prevent accidental writes
to the checked-in example when a user expects the canonical store.

For distribution beyond the current operator, remove the mandatory private
Git dependency barrier. Either publish the shared client as a separately
versioned accessible package or isolate it as an optional integration. Do not
copy its implementation into NapMem. Retain the current dependency contract
until that packaging decision is made.

**Acceptance:** a fresh supported machine can install and run an offline demo
without private repository access, API credentials or a model server. Online
setup remains explicit and its diagnostics state exactly what was tested.

### 8. Add a focused memory inspector

Provide a terminal-first inspector with current preferences, recent changes,
unresolved conflicts, stale evidence and an extraction review queue. Each
item should answer: “What does it remember?”, “Why?”, “Where does it apply?”
and “How do I correct it?”. Prototype with existing CLI output before adding
a UI dependency or dashboard framework.

Useful views include a decision timeline, a diff between source revisions,
and a compact project handoff brief with evidence links. Approve a proposed
profile only when its source, scope and current status are visible. Keep
review state distinct from model confidence.

**Acceptance:** a user can find an incorrect preference, inspect its evidence
and make a persistent correction through one coherent workflow. The inspector
does not edit derived records directly.

### 9. Observe memory quality, freshness and real cost

Add local structured metrics for ingest lag, rejected units, extraction
fallback rates, backend mode, mirror age, retrieval latency, empty-result
rate and returned context size. Connect opt-in “useful / wrong / outdated”
feedback to ranked candidates without treating a click as ground truth.

Existing global auto-recall hooks and a threshold-replay monitor are already
documented in
[/Users/mitch/dev/llm-memory-pyramid/docs/semantic-indexing-and-hooks-reference.md](/Users/mitch/dev/llm-memory-pyramid/docs/semantic-indexing-and-hooks-reference.md).
Integrate their observable outcomes rather than build a competing hook suite.
Their live installation and effectiveness were not verified in this review.

Report actual context delivered per request and extraction/embedding usage
where available. Keep the existing word-based compression estimate labeled
as an estimate. Actual savings require a stated baseline and observed usage.
Metrics should omit raw personal content by default and have retention limits.

**Acceptance:** an operator can distinguish ingestion failure, stale mirror,
lexical fallback and low-quality retrieval from one status report. Threshold
changes use held-out evaluation or explicit review rather than automatic
optimization of noisy feedback.

### 10. Offer a consistent interface across clients

Return typed MCP `structuredContent` with output schemas and compatible text
representations [R5]. Standardize scope, limits, status and provenance fields
across CLI and MCP. Add client contract tests and a documented capability
matrix before claiming compatibility with a client.

Then add bounded source adapters for actual workflows: Markdown, conversation
exports, Git decision notes and explicit imports from other memory stores.
Give adapters a shared source identity/evidence contract and respect source
exclusions. In the current environment, NapMem can supply evidence recall
while Stele retains task and decision authority; avoid two conflicting task
systems. A brief/export integration is more useful initially than another
generic graph interface.

**Acceptance:** the same scoped request has equivalent results through CLI
and MCP; imports are idempotent; clients can detect stale, truncated or
unverified evidence without parsing human prose.

## Practical implementation sequence

1. **Measure and contain:** build the golden corpus; stop presenting fixed
   profile confidence as calibrated; bound all result modes; enforce one
   writer over the full transaction. These are independently useful changes.
2. **Improve memory correctness:** design the versioned scope/lifecycle schema
   and migration; add evidence verification, corrections and exclusions;
   introduce hybrid retrieval and a budgeted evidence response. Evaluate each
   change separately, then test their combined behavior.
3. **Make it operable:** unify CLI/config/doctor; ship the inspector, durable
   jobs and generation-aware mirrors. Add measured quality/freshness reports.
4. **Broaden adoption:** resolve package distribution, test client contracts
   and add requested adapters. Consider SQLite/FTS5 or a richer UI when the
   measurements and supported workflows justify the migration cost.

The first feature release should demonstrate a complete loop: ingest two
sessions, answer a paraphrased question with evidence, respect a changed
project preference, accept a correction, retain it after re-ingestion, and
serve a clearly dated offline result. A release that proves this loop is more
valuable than several disconnected connectors.

Defer multimodal capture, mobile clients, an autonomous memory-rewriting
agent, a hosted multi-tenant service, a new graph database and a model-size
upgrade until a specific measured failure justifies them. The current
requirements do not establish a need for those changes.

## Evidence and limits

This assessment read current code and audit artifacts, consulted primary
sources and ran a small in-memory probe. It did not inspect production data,
run inference, create embeddings, restart indexing or exercise deployed MCP
clients. No recommendation is a measured NapMem quality or speed gain.

Primary references checked on 2026-10-27:

- **R1:** LongMemEval authors' benchmark and ability categories.
  https://github.com/xiaowu0162/LongMemEval
- **R2:** Anthropic contextual retrieval experiments: lexical/semantic
  combination, added context and reranking. Their reported gains are
  dataset-specific and are not NapMem forecasts.
  https://www.anthropic.com/research/contextual-retrieval
- **R3:** SQLite transaction behavior, including one simultaneous writer.
  https://www.sqlite.org/lang_transaction.html
- **R4:** SQLite FTS5 full-text indexing and BM25; availability depends on the
  SQLite build.
  https://www.sqlite.org/fts5.html
- **R5:** MCP tools specification for the version NapMem currently declares;
  structured results and output schemas already exist in that version.
  https://modelcontextprotocol.io/specification/2025-06-18/server/tools

Assessment tracking: capability review TASK-230; roadmap TASK-231; validation
and publication TASK-232. The profile-promotion risk is recorded as KNOW-234.
