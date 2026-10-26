# Requirements

## Functional

- **FR-1** Distill raw markdown memory files into typed atomic units
  (concept / fact / actionable / question / problem / statement / quote /
  idea) with salience and per-line source anchors.
- **FR-2** Deduplicate units by exact text; fold duplicates into canonical
  records keeping every duplicate's anchor resolvable.
- **FR-3** Re-ingesting a session replaces its records while keeping record
  IDs stable for re-asserted text; canonicals still substantiated by another
  session survive via duplicate promotion.
- **FR-4** Derive topic tracks (Layer 2) and user/system profiles (Layer 3)
  from Layer 1; rebuild on every ingest.
- **FR-5** Background consolidation: watch a directory, re-ingest on any
  mtime change, survive bad files.
- **FR-6** Active retrieval: layer-scoped search, provenance resolution
  (canonical and duplicate IDs), full-track fetch, token-savings stats.
- **FR-7** Provide zero-fabrication LLM extraction prompts hardened against
  prompt injection.

## Non-functional

- **NFR-1** Python 3.11+; core code uses the standard library.
- **NFR-2** Store writes are crash-safe (atomic replace).
- **NFR-3** Single-writer model; retrieval is read-only.
- **NFR-4** Deterministic heuristic extraction (same input → same pyramid,
  timestamps aside).

## Dependencies

Core distillation and substring retrieval: standard library. Package install:
shared `ollama-client` library, pinned to a reviewed Git revision. Optional:
`anthropic` SDK (`.[llm]`) for API extraction; configured Ollama hosts for
chat extraction and real embeddings. Hashed-TF embeddings run offline.
Development/CI: Ruff and GitHub Actions. No numeric coverage gate is configured.
