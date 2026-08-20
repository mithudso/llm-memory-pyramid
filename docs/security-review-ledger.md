# Security review ledger

Findings from automated commit reviews, their disposition, and rationale.
Reviewers: consult this before re-raising — do not re-open an ADDRESSED or
ACCEPTED entry without new evidence.

| # | Finding | Where | Disposition | Commit / rationale |
|---|---|---|---|---|
| 1 | Information disclosure — stale "nothing is transmitted" claim | `docs/SECURITY.md` | ADDRESSED | `b7e1946` — data-egress threat model added |
| 2 | Cache poisoning — unvalidated Ollama embed responses | `semantic_index.py` | ADDRESSED | `b7e1946` — strict numeric/consistent-dim validation before caching |
| 3 | Under-validated sink arg — glob-derived paths to ln/rm | `scripts/run-naptime.sh` | ADDRESSED | `30551c9` — `--` end-of-options everywhere |
| 4 | Symlink-following exfiltration via synced sources | `scripts/run-naptime.sh` | ADDRESSED | `3c34bdc` — mirror-time root resolution + link revocation |
| 5 | TOCTOU on the mirror-time check | `naptime_consolidator.py` | ADDRESSED | `5316f46` — race-free fd-based read guard (F_GETPATH / procfs) |
| 6 | Fail-open state drift — guard existed only under the wrapper env | `scripts/run-naptime.sh` / consolidator | ADDRESSED | `fc9c980` — fail-closed default (watch dir as sole root); explicit `off` opt-out, logged |
| 7 | Fail-open residual — realpath fallback when fd path unavailable | `naptime_consolidator.py` | ADDRESSED | this commit — no-kernel-path now raises instead of degrading to race-able realpath |
| 8 | Unguarded reads via explicit CLI `--input` args | `llm_extractor.py`, `memory_pyramid_distiller.py` | ACCEPTED | Explicit operator-chosen file arguments are operator consent (same trust model as `curl <file>`); the guard exists for *swept directories* whose entries an attacker can influence. Not a drift. |
| 9 | `compute_context_budget_savings` reads raw session files | `napmem_retrieval_agent.py` | ACCEPTED | Local word-count only; content never egresses. Paths come from the local trusted store. |
