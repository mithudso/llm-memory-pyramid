# Scoped evidence retrieval

`NapMemRetrievalAgent.query()` is the shared version 2 evidence API. It accepts
`scope`, `as_of`, `top_k`, `mode`, `max_bytes`, `max_tokens` and an optional
explicit embedding backend. Its default hybrid uses BM25 and sparse TF-IDF
rank fusion without importing a model client, contacting a host or writing a
cache. A caller can inject a real embedding backend. Failed embeddings produce
a disclosed lexical fallback. Sparse retrieval is not a substitute for a
qualified semantic model.

Named scopes include only that scope and explicitly global assertions.
Unscoped calls include legacy/global assertions. An explicit `*` includes all
scopes. Scope, validity, review rejection, quarantine, exclusions and known
unsafe-source markers apply before ranking. Explicit forgetting is different
from a missing raw source: retained evidence remains recallable when a source
file moves or disappears, with its provenance state disclosed.

Results contain a ranked `matches` list, ranking signals, source context,
generation/snapshot metadata, abstention, truncation and omission counts.
The agent can attach supported profiles and topic briefs linked to those
matches. Scores order evidence; they are not truth probabilities. Source text
is untrusted data and never an instruction to execute.

Budgets count the complete compact UTF-8 JSON payload, including accounting
fields. `returned_bytes` is exact for `ensure_ascii=False`, sorted keys and
compact separators. `estimated_tokens` uses UTF-8 bytes divided by four,
rounded up; it is an explicitly approximate estimator. Oversized responses
drop complete tail items rather than cutting JSON. If metadata alone cannot
fit, the call raises a clear budget error. MCP must also budget its protocol
envelope and duplicate text representation before writing to the wire.

Legacy substring, semantic, provenance and topic methods remain available
with scope/time/budget options. Legacy `semantic_search` remains an explicit
embedding/cache path; the new default `query()` stays offline. The original
SemanticIndex constructor seam remains injectable for safe tests.

## Evaluation receipts

The immutable original reports live in the `evaluations/` directory. The
initial hybrid held-out run is `hybrid_initial_heldout_v2.json`. It exposed
short queries that discarded their distinguishing qualifier. A generic
short-query coverage fix has a regression test; the subsequent report is
`hybrid_regression_v2.json`. That report reuses the inspected split and is not
a fresh blind estimate.

On the 100-query regression split, Recall@5 is 0.86, MRR@5 is 0.8733 and
abstention accuracy is 0.76. All 13 protected cases pass, all 11 current-fact
cases pass, and scope/lifecycle/marked-instruction leakage counts are zero.
The original hashed baseline recalled more evidence (0.92) but returned 297
out-of-scope records, failed every abstention case and had MRR@5 0.7069.
These are synthetic fixture measurements. They do not establish production
accuracy, extraction quality, multilingual coverage or real-model quality.
