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
| 10 | MCP server crash class — malformed/hostile input killed the serve loop (batch arrays, non-dict params, wrong-typed args, oversized lines) | `napmem_mcp_server.py` | ADDRESSED | full-repo CDO commit — structural validation, catch-all dispatch, version negotiation, 16MB line cap, BrokenPipe shutdown |
| 11 | FIFO planted in watch dir hung the daemon forever at open() | `naptime_consolidator.py` | ADDRESSED | same commit — `O_NONBLOCK` open before the regular-file check |
| 12 | Degenerate `NAPMEM_ALLOWED_ROOTS=":::"` silently disabled the guard (fail-open) | `naptime_consolidator.py` | ADDRESSED | same commit — non-off values yielding zero roots refuse startup |
| 13 | Hard-link alias could pass the fd-path check with an in-root name | `naptime_consolidator.py` | ADDRESSED | same commit — refuse `st_nlink > 1` files |
| 14 | NaN/Infinity vectors passed the "strict" embed validation (stdlib json parses those tokens) and poisoned cosine math persistently | `semantic_index.py` | ADDRESSED | same commit — `math.isfinite` per component, `parse_constant` rejection, `allow_nan=False` on save, dim cap 8192 |
| 15 | Non-RuntimeError transport/parse failures escaped the pool's failover (one bad host defeated redundancy) | `semantic_index.py` | ADDRESSED | same commit — all transport/parse errors wrapped as RuntimeError |
| 16 | O(n²) sentinel neutralization — measured CPU DoS on hostile bracket runs | `llm_extraction_prompts.py` | ADDRESSED | same commit — single-pass regex neutralization with non-reconstitutable token |
| 17 | Refused-file ERROR log flooding (~17k lines/day per parked hostile symlink) | `naptime_consolidator.py` | ADDRESSED | same commit — refusals logged once per mtime change |
