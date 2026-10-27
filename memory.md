# memory.md — operator work log

Versioned log of active task, completed work, and next steps. Newest first.

## v2.0.0 — 2026-10-27

**Active task:** implement all ten roadmap improvements in order, EPIC-235.
TASK-236–TASK-245 track the ten stages. Stages 1–8 passed; next is TASK-244,
observability, followed by consistent MCP contracts and source adapters.

**Delta:** workflow v1.8.0 → v2.0.0; implementation request and ordered plan
added. Package 0.1.1 → 0.2.0 for this feature release; schema/MCP versions
will change with the corresponding implemented features.

**Completed:** read current source, instructions and prior assessment; checked
clean main 0790dc7 with no open owned PRs; created the tracked stages and
tasks/plan.md; captured implementation constraints in KNOW-246. Started an
offline benchmark author and independent read-only compatibility review.
- Stage 8: eight scoped terminal inspector views, evidence/age/review state,
  durable correction previews, historical timeline and project handoff added.
  Bounded pagination retains complete assertions and source diffs retain whole
  hunks. Inspection is read-only and shares managed snapshot validation.
  All 31 inspector tests and 54 focused inspector/CLI tests pass; full suite
  411 passed before one final CLI workflow test. Stele remains task authority.
- Stage 7 implementation: portable `napmem` command and TOML/env/CLI precedence;
  offline defaults, read-only doctor, explicit online integrations and source
  boundaries. Private shared client moved to optional `ollama` extra without
  copying its transport. Packaged synthetic evaluation fixture. CLI/config 22
  focused tests and complete 375-test suite passed. Independent fresh wheel
  acceptance passed outside the checkout without either optional client: 20
  console invocations plus identity/guard checks, zero runtime network attempts.
  The demo revealed a preference word-form mismatch; generic normalization and
  regression tests fix it without relaxing short-query qualifier coverage.
  A final wheel will be checked again after stages 8–10 add their modules.
- Stage 6: whole-operation single-host locks, atomic generation/fingerprint
  commits, stale-save rejection and long-lived reader refresh implemented.
  Stable source registry handles rename, missing files and same-mtime edits.
  Leased durable extraction jobs separate submit/collect/commit and reject stale
  results; canonical applied-job markers survive acknowledgment crashes.
  Forget/exclude purges matching local job payloads and discloses remote gaps.
  Checksummed immutable mirror generations and privacy-preserving restore
  implemented. Stale cache writers cannot recreate deleted vectors. Full suite
  341 passed, then 15 focused transaction/privacy tests passed (four added).
  No production stores, services, indexing or snapshot transfers were changed.
- Independent review follow-up: an older backup plus a later session scope
  could revive forgotten text; restore now retains historical scopes and also
  suppresses older copies of the forgotten record family. Independently scoped
  copies retain their own lifecycle. Retry validation
  and payload update now share one SQLite transaction, so PrivacyPurge wins.
  Rename identity survives edits on the same inode. A verified reader refuses
  to downgrade when its manifest disappears. All 47 focused persistence tests
  pass, including deterministic purge/retry interleaving.
- Stage 1: 200 synthetic queries, 83 records and 20 scenario families with
  fixed 100/100 dev/held-out split. Original substring and hashed-TF reports
  captured before runtime changes. Held-out Recall@5: 0.3067 / 0.9200;
  hashed-TF has 297 scope violations and zero correct abstentions. These are
  fixture results, not production accuracy. Scorer tests 17/17 and full
  suite 128/128 pass. Reproduction gates report no baseline regressions.
- Stage 2: store v2 migration and scoped temporal assertions implemented.
  Legacy scope remains unknown; metadata/IDs survive no-op replay and alias
  promotion. Explicit updates retain history; approval gates persistent
  profiles and unresolved conflicts withhold traits. Removed constant 0.95
  confidence. All 159 tests, Ruff and compile checks pass. The prior profile
  risk KNOW-234 is now an implemented fix; production stores remain untouched.
- Stage 3: offline BM25/sparse hybrid and optional injected embeddings,
  pre-ranking scope/time/safety filters, abstention and compact payload budgets
  implemented with scoped legacy adapters. All 189 tests/Ruff/compile pass.
  Initial held-out result retained; a short-query qualifier-loss bug was
  fixed generically. Regression report has Recall@5 0.86, MRR 0.8733,
  abstention 0.76, all 13 protected/all 11 current-fact cases passing and zero
  scope/lifecycle/marked-instruction leakage. It reuses an inspected split,
  so it is a regression receipt, not a fresh blind qualification.
- Validation incident: a focused test bypassed its SemanticIndex constructor
  mock and contacted the configured embedding backend with synthetic fixture
  text. Restored the seam and added no-network regression tests; all later
  test commands force NAPMEM_EMBED_BACKEND=hashed. No production data was
  accessed or service configuration changed. Concrete lesson: KNOW-250.
- Stage 4: concrete generation/snapshot-bound previews, correction/pin/expiry/
  review/exclusion/forget controls, source replay suppression, content-free
  bounded journal and persistent deletion receipts implemented. Forgetting
  purges the local embedding cache; failures remain explicitly pending.
  Permanent session suppression differs from reversible exclusion; whole
  claim forgetting removes correction/alias families. Fixed implicit replay
  scope loss with pseudonymous routing (KNOW-251). All 219 tests/Ruff/compile
  pass. Canonical receipts do not claim external original/backup/mirror deletion.
- Stage 5: exact source revision/quotation binding and explicit bounded
  re-verification implemented. Anthropic/Ollama ingestion carries original
  input and actual extractor/model/prompt provenance. Quotes and paraphrase
  support remain distinct; mismatching supplied quotes stay unverified.
  Profiles now require reviewed supported evidence. Shared evidence quotes
  are redacted through persistent hash/range policies when forgetting a claim;
  replay cannot restore those literal passages. All 280 tests and Ruff pass.

**Continuation:** branch feat/napmem-trusted-memory. Implement stage 1 before
altering runtime behavior. Then proceed through scoped time-aware model,
hybrid retrieval, controls, evidence, safe persistence/jobs, CLI/config,
inspector, metrics and typed MCP/adapters. Each stage must pass focused tests;
full integration gates and publication remain required. Do not stop after an
early stage merely because its work is tracked. Use the installed .venv.
Production stores, inference, embeddings, indexing, hooks and schedulers stay
untouched. Git commit hooks start indexing; suppress them per command only.

## v1.8.0 — 2026-10-27

**Active task:** none — product assessment complete. TASK-230 covers evidence,
TASK-231 the roadmap, and TASK-232 the final validation/publication receipt.

**Delta:** workflow v1.7.0 → v1.8.0. Added one product assessment and one
triggering request. Package 0.1.1, MCP server 1.1.1 and store 1.0.0 unchanged.

**Completed on this checkout:**
- Revalidated current main edd28fb against source, schema, operational limits,
  previous audit and existing global hook documentation. Consulted primary
  LongMemEval, contextual retrieval, MCP and SQLite documentation.
- Ran an in-memory profile probe: contradictory preferences and a temporary
  task all become traits at constant confidence 0.95. A paraphrased substring
  query returns no match. This is a narrow behavior probe, not a benchmark.
- Prepared docs/product-roadmap-2026-10-27.md with ten ranked improvements,
  source anchors, acceptance criteria, dependencies and implementation phases.
- Proposed evaluation, scoped/time-aware memory, hybrid bounded retrieval,
  user corrections/forgetting, versioned evidence, transactional/resumable
  ingestion, portable setup, an inspector, observability and client adapters.
  No proposed feature is implemented or implicitly approved by this record.
- Preserved the prior BLIND-AUDIT-DISSENT result. No production data, model,
  embeddings, indexing, hooks, scheduler or deployed client operation ran.

**Validation:** all 111 tests pass in the installed Python 3.12 environment.
Ruff, static-map check, shell syntax and whitespace checks pass. Ten local
source links resolve; the exact triggering prompt is recorded. No runtime
source or package/protocol/schema version changed.

**Delivery and remaining scope:** TASK-232 records the commit, PR, CI and
final main synchronization. The assessment branch is
docs/napmem-product-roadmap-20261027. Assessment commit f3ac607 is published
through https://github.com/mithudso/llm-memory-pyramid/pull/17; its CI passed
on Python 3.11/3.12/3.14 and Ruff. TASK-232 holds the final receipt after this
continuation-record update. No assessment content remains to write.
The proposed product features require a subsequent implementation request;
this record does not claim they exist or that production behavior improved.

## v1.7.0 — 2026-10-26

**Active task:** none — requested source and bootstrap work published.
TASK-218 covers standards, TASK-219 the code review, and TASK-220 delivery.

**Delta:** workflow v1.6.0 → v1.7.0; package 0.1.0 → 0.1.1; MCP server
1.1.0 → 1.1.1. Store schema remains 1.0.0. Added three regression suites.

**Completed on this checkout:**
- Ran repo-bootstrapper 5.4.1 and code-deep-optimizer 1.16.0 against clean
  main at 1f3d21d. Reviewed every original Python/shell source; no file cap.
- Fixed 35 corroborated runtime/test findings: operator-file preservation,
  prompt CPU/metadata boundaries, stable repeated IDs and refreshed payloads,
  cache validation/persistence/result bounds, extractor privacy/fallbacks,
  safe raw-source statistics, mirror atomicity and subprocess/protocol safety.
- Final local Python 3.12 gate: 111 tests pass. Python 3.14 passed the
  110-test candidate; the last decoder fix gets the full CI matrix too.
  Compilation, Ruff, shell syntax and exact static-map checks pass.
- Two fresh-context audits ran. The second found an Ollama decoder-depth
  gap. Fixed it and added a red/green two-file fallback regression. CDO exits
  BLIND-AUDIT-DISSENT under its review cap; do not relabel it CLEAN. No
  corroborated finding is left unfixed; no third independent gate ran.
- Updated stale Python/dependency/test/security/operations guidance. Added
  deterministic static doc generation/checking, safe env template and CI
  drift gates. Generic dashboard/Node/central error-service standards remain
  explicit architecture exceptions, not fabricated implementations.
- Installed only the declared package and pinned ollama-client in an ignored
  Python 3.12 venv. No inference, embeddings, indexing, live SSH MCP,
  production store, hook, scheduler or deployment operation ran.
- Repaired pre-existing CI private-library authentication with a dedicated
  read-only deploy key id 167768571 on mithudso/ollama-client. Its private key
  is only in this repo Actions secret OLLAMA_CLIENT_DEPLOY_KEY; local private
  copies were removed. Pinned dependency, Actions and Ruff revisions.
- Refreshed the existing hub project metadata and MCP activation. Preserved
  scheduler issue #29; no scheduler health conclusion was inferred.

**Artifacts and continuation:**
- Audit: docs/repo-bootstrap-audit-2026-10-26.md.
- Findings, gate limits and rollback: docs/code-deep-optimizer-2026-10-26.md.
- Original/per-iteration snapshots and CI access receipt:
  /Users/mitch/.claude/skill-consolidation/backups/llm-memory-pyramid-20261026T2155/.
- External static dossier:
  /Users/mitch/.global-ai-hub/skills.llms/mithudso-llm-memory-pyramid.repo/.
- Delivery: source commit 9d23b3b published through PR #15 and squash-merged
  as ee2170da1eff9effea62e47621257a298f299a16. CI passed all 111 tests on
  Python 3.11/3.12/3.14, Ruff, static maps and shell syntax:
  https://github.com/mithudso/llm-memory-pyramid/pull/15
  https://github.com/mithudso/llm-memory-pyramid/actions/runs/40413224889
- Main was fast-forwarded to the merged tree and the task branch removed.
  Commit/sync commands suppressed the automatic indexing hook for this run
  only; persistent Git config was not changed. Registry metadata was recorded
  explicitly. The external dossier verified 77/77 source hashes at 9d23b3b.
- Remaining product steps: none. Optimizer exit remains BLIND-AUDIT-DISSENT;
  no independent CLEAN claim or production runtime acceptance is implied.
  Production runtime work remains outside scope. TASK-220 holds the final
  receipt for this documentation closeout too.

## v1.6.0 — 2026-09-26

**Active task:** none — local MCP fallback shipped.

**Completed:**
- Root cause of `napmem (CONNECTION_CLOSED)`: PR #12 replaced the real ssh
  target in the project `.mcp.json` with the placeholder `user@box.example`;
  project scope overrides the working user-scope entry, so every session in
  this repo failed to connect. The remote box itself was up.
- `napmem_mcp_failover.py`: stdlib MCP proxy. Relays to the remote server
  over SSH; falls back to a local `napmem_mcp_server.py` on
  `~/.napmem/mirror/` when the remote is down at startup or dies
  mid-session (replays `initialize` + in-flight requests). Tool results on
  the mirror carry a `[napmem fallback]` snapshot-age note.
- Mirror: pyramid (3.5 MB) + embindex (38 MB) copied over ssh in ~2 s,
  tmp + `os.replace`, JSON-validated. Local Ollama serves the same
  `mxbai-embed-large`, so semantic scores match the remote exactly (0.8415
  on the same query both ways).
- Host is read from `NAPMEM_REMOTE_HOST` / `~/.napmem/remote_host` (not
  committed). Project `.mcp.json` and user-scope `~/.claude.json` both run
  the proxy now. A watchdog kills a hung remote after 60 s unanswered.
  Tests 56 → 65 (+9 in `test_napmem_failover.py`).

**Next steps:**
- Done same day: the global napmem hooks now fall back to the mirror too
  (github.com/mithudso/skills PR #37), with a 120 s remote-down marker and
  a background mirror refresh from the session brief.

## v1.5.0 — 2026-08-21 (later still)

**Active task:** none — zero-API-spend extraction shipped.

**Completed:**
- Spend post-mortem: NapMem itself spent well under $1 (exactly one
  successful 142-file batch sweep before the org cap hit — the cap was
  already near-exhausted by 20 days of other API usage). But the projected
  rate was ~$5–10/day because the sweep state was in-memory only: every
  systemd `--once` run re-extracted all 143 files.
- Persistent sweep state: `<pyramid>.sweepstate.json` (mtime fast-path +
  sha256 content gate, atomic writes, prunes deleted files) — touched-but-
  unchanged files now skip extraction across process restarts, in both
  timestamp directions.
- `ollama_extractor.py`: zero-API-cost extraction via local Ollama chat
  models (`NAPMEM_OLLAMA_CHAT` url=model chain, json-mode, per-sweep
  dead-host benching, wrapped-object coercion). Same sentinel prompt, same
  untrusted-output validation gauntlet as the Anthropic path.
- Consolidator chain: `--extraction auto` = anthropic → ollama → heuristic;
  `--extraction ollama` guarantees no API spend; wrapper honors
  `NAPMEM_EXTRACTION`. Tests 44 → 55, all green; docs + file index updated.

**Next steps:**
- Deploy: box drop-in `NAPMEM_EXTRACTION=ollama` (qwen3.5:35b on the 5080),
  one-shot backfill re-extracting all files at LLM quality, then hourly
  delta sweeps.
- After 2026-09-01 (cap reset): optionally flip to `auto` — with the hash
  gate the Anthropic cost would be pennies/day for delta-only sweeps.

## v1.4.1 — 2026-08-21 (later)

**Active task:** none — usage-learning auto-index loop live.

**Completed (deployment-side + global-ai-hub; no code changes in this repo):**
- Diagnosed the sweep-wide heuristic fallbacks: the Anthropic org's monthly
  API spend cap is exhausted (400 "reached your specified API usage limits",
  reset 2026-09-01) — every consolidator sweep since Aug 20 23:21 falls back
  to heuristic extraction. Graceful degradation worked; extraction quality
  is capped until the limit resets or is raised.
- Wired retrieval into the global-ai-hub file index and built the usage
  feedback loop: PostToolUse access sensor → frequency+recency predictor →
  hub-daemon /index + /index-tree; SessionStart always indexes the cwd repo;
  per-prompt hook adds "related file" hits from hub /search. Managed via
  `pipeline_manager.py repo-status|index-repo|watch-repo` (hub PRs #1–#3).
- Fixed three latent hub outages while integrating: daemon launchd
  interpreter lacked fastapi (dead since Aug 18); gen-universal-index walked
  / under launchd on a self-retriggering WatchPaths loop (hub.db bloated to
  268MB — purged to 89MB); hub_sqlite leaked one fd per call and crashed the
  daemon under indexing load.

**Next steps:**
- Raise the org API limit (or wait for 2026-09-01) to restore LLM extraction.
- Watch `pipeline_manager.py repo-status` and the retrieval monitor after a
  few days of organic use; retune floors from data.

## v1.4.0 — 2026-08-21

**Active task:** none — auto-retrieval hook suite live.

**Completed (deployment-side; hook code lives in `~/.claude/hooks/`, not this
repo):**
- Push-based retrieval: the pyramid was pull-only (MCP tools never invoked),
  so a global hook suite now auto-injects memory — per-prompt semantic pull
  (UserPromptSubmit), first-touch file/commit decision surfacing (PreToolUse),
  once-per-session bulk brief of profiles + largest tracks (SessionStart).
- Semantic query cache on the M3: prompts embedded locally (Ollama
  mxbai-embed-large), remote results reused when query-cosine >= 0.90 within
  the hourly consolidation TTL — paraphrased repeats skip ssh (~130ms).
- Noise control: cosine >= 0.75 passes alone; 0.65–0.75 needs content-word
  overlap with the prompt; < 15 chars always dropped (pure cosine floors let
  filler match filler at 0.6–0.7).
- Offline tuning loop: every event logs its full top-8 candidate set with
  features; `napmem-retrieval-monitor.py` replays the keep rule across a
  (floor × overlap) grid and prints recommended constants; `--tail` for
  eyeball audits.
- Killed orphan launchd job `com.mitchhudson.memorydistiller` (unrelated
  `.gemini` aider nightly, failing on `tput: no $TERM` since creation).

**Next steps:**
- Re-run the monitor after ~20+ organic prompts; apply its recommendation.
- Investigate per-file heuristic fallbacks for `agbrain_*` walkthrough files
  in the 03:03 sweep (LLM extraction otherwise active).
- Candidate next layers: track-summary substitution when hits cluster on one
  topic, per-type floors, code/docs chunk index fed by file-access frequency.

## v1.3.0 — 2026-08-20 (late)

**Active task:** none — fleet deployment complete.

**Completed:**
- Real memory ingestion: symlink mirror over Claude Code projects,
  Antigravity brain, and mounted twins; batch custom_id cap fixed;
  five security-review findings fixed as raised (ledger:
  docs/security-review-ledger.md).
- Capacity-weighted Ollama pool (5080 w=4, M5 Max w=2, local w=1; M5
  exposed via app sqlite settings.expose=1); batched semantic dedup
  (~10x sweep speedup); index cache made concurrent-writer-safe and
  corrupt-tolerant.
- Wrapper ported to portable bash; systemd units in deploy/; canonical
  consolidator MIGRATED to the Linux 5080 box (hourly Persistent timer,
  linger on, ant OAuth active). First canonical sweep: 143 sessions,
  142 LLM-extracted, 2,043 records / 1,523 tracks / 702 profiles.
- M3 launchd retired; M3 queries canonical store via user-scope
  ssh-stdio MCP. global-ai-hub pushed to github.com/mithudso/global-ai-hub
  (skills/ as submodule).
- Full-repo CDO audit pass + doc refresh (this entry's commit).

**Next steps:**
- Submit-now/collect-later batch mode for non-blocking sweeps.
- skills repo (mithudso/skills) has ~687 uncommitted local changes.

## v1.2.0 — 2026-08-20

**Active task:** none.

**Completed:**
- Naptime consolidator wired to `llm_extractor` (`--extraction auto|llm|heuristic`;
  one Batches API batch per sweep, per-file heuristic fallback on any failure).
- `ingest_extractions` now returns the ingested session set so callers can
  route failed sessions to the fallback extractor.
- Ollama host failover: `NAPMEM_OLLAMA_URLS` chain, remote
  `http://192.168.4.75:11434` first, `http://localhost:11434` backup; default
  model switched to `mxbai-embed-large` (pulled locally, 669 MB) so both
  hosts serve the same model and the vector cache survives failover.
  Verified live: remote picked by default; simulated outage fails over to
  local, 1024-dim embeddings on both.
- Tests 19 → 26 (consolidator wiring with faked anthropic module, probe-order
  failover); dependabot PR #2 (checkout v7) merged by operator.

**Next steps:**
- `pip install anthropic` + credential on the naptime host to activate LLM mode.

## v1.1.0 — 2026-08-20

**Active task:** none — production path shipped.

**Completed:**
- `llm_extractor.py`: LLM extraction via Anthropic Message Batches API
  (claude-haiku-4-5 default), schema-validated ingest through new
  `ingest_session_records` distiller entry point.
- `semantic_index.py`: embedding index (Ollama backend with stdlib hashed-TF
  fallback), cosine search, opt-in semantic dedup in the distiller,
  `--semantic` retrieval CLI.
- `napmem_mcp_server.py` + `.mcp.json`: pure-stdlib MCP stdio server exposing
  search_memory / inspect_provenance / get_topic_track / memory_stats.
- Test suite grown 9 → 19 (all network-free); CI now runs unittest discovery.
- `docs/external-calls.md` populated with the repo's first external calls.

**Next steps:**
- Submit-now/collect-later batch mode for cron-driven naptime.
- Optional: point the naptime consolidator at the LLM extractor.

## v1.0.0 — 2026-08-20

**Active task:** none — bootstrap complete.

**Completed:**
- NapMem pipeline implemented: distiller (extraction, dedup, session
  reconciliation with stable IDs, layer rebuild), naptime consolidator
  (mtime-based incremental re-ingest), retrieval agent (search, provenance,
  topic tracks, token-savings stats), zero-fabrication extraction prompts with
  sentinel injection guards.
- Test suite: 9/9 passing (`python3 test_napmem_pipeline.py`).
- Repo bootstrapped to mdb-tam standard (docs suite, CI, meta files) and
  published to https://github.com/mithudso/llm-memory-pyramid.

**Next steps:**
- Wire `llm_extraction_prompts.py` into a real LLM extraction path (the
  distiller currently uses the heuristic stand-in extractor).
- Consider embedding-based (semantic) dedup to complement exact-text matching.
