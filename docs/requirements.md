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

- **NFR-1** Python 3.10+ standard library only.
- **NFR-2** Store writes are crash-safe (atomic replace).
- **NFR-3** Single-writer model; retrieval is read-only.
- **NFR-4** Deterministic heuristic extraction (same input → same pyramid,
  timestamps aside).

## Dependencies

None at runtime. CI-only: `ruff` (advisory lint), GitHub Actions
`setup-python`/`checkout`.
