# Implementation plan: trusted NapMem memory

Version: 1.1.0
Date: 2026-10-27
Delta: all ten source stages implemented and verified; delivery receipt added.
Baseline: 0790dc7f31faca1118f961f533199275b93fc73f.

## Scope and architecture

Implement all ten priorities from /Users/mitch/dev/llm-memory-pyramid/docs/product-roadmap-2026-10-27.md in order. Tasks live in Stele project dev-y3seh under EPIC-235. The user's request authorizes execution of the reviewed roadmap; no additional planning approval is needed. This plan supplements that specification.

Keep the canonical store inspectable JSON. Add a compatible versioned model, whole-transaction writer serialization, generation checks and explicit migrations. A storage-engine migration is conditional in the roadmap and is not required to add safe writes; use stdlib SQLite only where durable jobs/metrics benefit from transactions. Keep stable existing canonical and duplicate record IDs. Never rewrite the checked-in example or production stores as part of implementation.

New model fields use string scope, memory_kind, subject, valid_from/valid_to, observed_at, last_verified_at, supersedes and explicit review/evidence state. Legacy facts migrate with unknown scope ('legacy'), no invented validity/evidence and no calibrated confidence. Named project queries include only that scope and explicitly global memory. Filter before ranking. Derived profiles require approved or corroborated evidence and never promote temporary tasks merely from salience.

Provide one shared bounded retrieval contract: query(query, scope=None, as_of=None, top_k=5, mode='hybrid', max_bytes=16384, max_tokens=2048). Canonical matches are a list. Responses disclose mode, snapshot/generation, scope, estimated tokens, truncation, omitted counts and abstention. Preserve legacy wrappers while applying safe defaults. Separate local mutation commands from read-only MCP.

Controls persist in canonical state and are applied on re-ingestion. Explicit forgetting removes associated text/caches and records content-free replay suppression; normal supersession preserves history. Evidence binds quotations to source revisions. No source or retrieved text becomes an instruction to execute.

No new runtime dependencies. Make the shared Ollama integration optional without copying its transport. Offline operation must work in a fresh installation without the private client. Do not run model inference, embeddings, indexing, services, scheduler setup or production deployment. Git commits use per-command hook suppression to preserve the paused indexing boundary; do not change persistent Git configuration.

## Ordered task index

1. TASK-236 — quality benchmark
2. TASK-237 — scoped temporal model and profiles
3. TASK-238 — hybrid bounded retrieval
4. TASK-239 — durable user controls
5. TASK-240 — verified source evidence
6. TASK-241 — transactional/resumable ingestion and mirrors
7. TASK-242 — portable CLI/configuration/doctor
8. TASK-243 — inspector and review
9. TASK-244 — quality/freshness observability
10. TASK-245 — MCP contracts and source adapters

Each task has acceptance and verification criteria in Stele. Keep exactly one implementation stage in progress. Independent analysis and tests can run in parallel under the dispatching-parallel-agents skill; dependent feature integration follows the order above.

## Checkpoints

- Stage 1: capture the old-runtime benchmark before modifying retrieval/model behavior; test metric correctness and fixed splits.
- Stages 2–3: preserve ID/dedup/reconciliation tests; verify scope/time filtering, conflict/profile rules, hybrid ranking, abstention and response limits.
- Stages 4–5: exercise correction replay, duplicate forgetting, source exclusion and evidence verification against changed/missing sources.
- Stage 6: exercise overlapping processes, stale object save, failed commit/retry, interrupted job recovery, source rename/delete and stale batch outputs, mirror generation mismatch.
- Stages 7–8: build/install the package in an isolated environment; run offline init/demo/doctor/query/inspect/review without the optional client or network.
- Stages 9–10: content-free metric retention, CLI/MCP parity, schemas, source adapter replay and full end-to-end trusted-memory loop.
- Final: all discovered unittest tests, Ruff, compile check, shell syntax and generated-map checks; quality comparison and high-risk fixture gates; independent code/acceptance review; CI, merge and clean synced main.

## Risks and continuation

Implementation is complete. Local discovery passes 486 tests; static checks and
independent adversarial fix verification pass. A fresh wheel without optional
clients passes 61 console invocations and 15 MCP responses. Exact receipts are
in docs/acceptance-offline-2026-10-27.md and docs/IMPLEMENTATION.md.

Delivery is PR 18: https://github.com/mithudso/llm-memory-pyramid/pull/18
Feature-head CI passed Python 3.11/3.12/3.14, lint and offline installation.
The final documentation receipt must pass CI before squash merge and main sync.
If resuming after the PR is merged, no product work remains; verify clean main.

- Schema changes must not silently grant legacy records global authority. Preserve unknown values and require explicit scope/review for durable profiles.
- Correction/forget state must survive re-extraction, duplicate promotion and cache regeneration. Report unreachable replicas and backup retention limits honestly.
- Lock the entire read/modify/write transaction, reload long-lived objects and use generation checks for direct stale saves.
- Golden fixtures are sanitized synthetic cases, not measured production performance. Keep held-out queries fixed and report limitations.
- Existing global hooks remain separate. Integrate observable outcomes via portable APIs; do not restart or overwrite their loaded state.
- Follow progress and remaining steps in /Users/mitch/dev/llm-memory-pyramid/memory.md and Stele EPIC-235. No completed stage means the entire request is complete until all ten stages and delivery checks pass.
