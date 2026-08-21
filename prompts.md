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
