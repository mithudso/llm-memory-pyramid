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

Core distillation and substring retrieval: standard library. Default package installation has no runtime dependencies. Optional:
`ollama-client` (`.[ollama]`), pinned to a Git revision;
`anthropic` SDK (`.[llm]`) for API extraction; configured Ollama hosts for
chat extraction and real embeddings. Hashed-TF embeddings run offline.
Development/CI: Ruff and GitHub Actions. No numeric coverage gate is configured.

## Trusted-memory requirements

- **FR-8** Filter scope, validity, review and source exclusions before ranking.
- **FR-9** Preserve operator corrections, replay suppression, preview coverage and deletion receipts.
- **FR-10** Keep durable source identity and extraction jobs; fence leases during canonical commits and report unknown provider outcomes without automatic resubmission.
- **FR-11** Publish checksummed immutable snapshots; preserve newer privacy controls during restore.
- **FR-12** Provide bounded CLI/MCP, inspector, structured/Git adapters and portable export.
- **FR-13** Gate retrieval changes with the fixed synthetic offline regression set.

Configuration files are bounded to 64 KiB; individual sources default to 2 MiB.
Sweeps defer work after 256 changed files or 64 MiB instead of retaining unbounded
source text. These are implementation resource bounds, not performance SLAs.
Queue directories must belong to the current user and must not be writable by
other users. POSIX/macOS and Linux are validated; Windows acceptance is not claimed.
