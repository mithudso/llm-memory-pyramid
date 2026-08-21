# prompts.md — request log

Versioned record of user requests, in order. Newest last.

## v1.0.0 — 2026-08-20

1. "This is the github repo for this folder: llm-memory-pyramid, implement it
   and add all the files to github and run the repo bootstrapper skill on it"
   — verified implementation (9/9 tests), initialized git, published to
   https://github.com/mithudso/llm-memory-pyramid, ran repo-bootstrapper.
2. "Evaluate how you would implement this memory pyramid infrastructure, if it
   would be effective, and estimate cost savings." — delivered analysis:
   architecture sound, retrieval quality the gate; ~10–25x compression on
   transcripts, ~50–90% memory-cost reduction depending on baseline.
3. "Implement all 3" — shipped llm_extractor.py (Haiku Batches API),
   semantic_index.py (+semantic dedup, --semantic search), napmem_mcp_server.py
   (+.mcp.json); tests 9 → 19; docs + external-calls registry updated.
4. "Wire the naptime consolidator to use llm_extractor. Also download whatever
   ollama model would be most effective ... local backup if the remote ollama
   server at 192.168.4.75 isn't responding" — consolidator --extraction
   auto|llm|heuristic with per-file fallback; NAPMEM_OLLAMA_URLS failover
   chain (remote first, localhost backup); pulled mxbai-embed-large locally
   to match the remote's model; tests 19 → 26.
5. "Install anthropic into this machine's python" — user-site install;
   hardened credential-missing fallback; security findings fixed; tests → 28.
6. "Set it up with launchd, use my ant auth login profile" — hourly agent,
   ant CLI, OAuth (org-credits detour), end-to-end batch extraction verified.
7. "Point it at my real Claude Code memory files" / "also antigravity + the
   volume copies" — multi-source mirror; custom_id fix; exfiltration guards
   (mirror-time, TOCTOU fd-guard, fail-closed default); tests → 35.
8. "Ollama on 3 machines ... used according to their capacity" — weighted
   pool, batched dedup, cache race + corruption fixes; tests → 38.
9. "Migrate the consolidator to the linux box; initialize global-ai-hub repo"
   — portable bash wrapper, systemd units, canonical on 192.168.4.75, M3
   ssh-MCP cutover, hub pushed with skills submodule.
10. "Document everything, run full /cdo, rerun bootstrapper" — this commit.
11. "Is the pyramid running and are you using it?" → infra verified healthy
    but retrieval was pull-only and unused; "auto-call search_memory per
    prompt / semantic instead of grep / index the scripts" + "how would I
    know the thresholds are right — build an offline monitor; add the
    PreToolUse and SessionStart hooks; push semantic indexing further" —
    global hook suite (per-prompt semantic pull with local-embed query cache,
    first-touch PreToolUse decision surfacing, SessionStart bulk brief) +
    candidate-logging monitor with threshold-sweep recommendations; orphan
    memorydistiller launchd job killed.
12. "Push it / PR, commit, make it happen / check the .env files / clarify the
    agbrain fallbacks / build a constant ML feedback loop of my usage that
    auto-indexes whatever is most likely, always the cwd repo, hook on
    unindexed file opens, zero maintenance, wired into pipeline_manager" —
    skills main pushed (env templates verified + committed), log PR merged,
    fallback root-caused to the exhausted org API spend cap, and the
    usage-learning auto-index loop shipped against the global-ai-hub daemon
    (access sensor → predictor → /index|/index-tree; /search into the
    per-prompt hook; pipeline_manager repo-status/index-repo/watch-repo),
    fixing the daemon's dead interpreter, the /-walking indexer loop, and an
    fd-leak crash along the way.
13. "What's the API usage rate? Make it not use API spend — ollama, or a task
    on the normal budget?" — measured: one successful batch sweep ever
    (~$0.30–0.50); cap was killed by other month usage; projected burn came
    from state-less hourly full re-extraction. Shipped: persistent sha256
    sweep state (delta-only sweeps) + ollama_extractor.py zero-API backend
    (qwen3.5:35b on the 5080) with --extraction ollama / auto chain;
    subscription-budget headless-claude option assessed and declined (burns
    the Max allowance the whole project exists to conserve).
