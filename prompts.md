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
