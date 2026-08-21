# memory.md — operator work log

Versioned log of active task, completed work, and next steps. Newest first.

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
