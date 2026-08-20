# Security Policy

## Reporting a vulnerability

Open a [private security advisory](https://github.com/mithudso/llm-memory-pyramid/security/advisories/new)
on GitHub. Do not open public issues for security problems.

## Scope notes

This project makes no network calls and reads no credentials. The main
security surface is prompt-injection resistance in `llm_extraction_prompts.py`
(untrusted memory-file content interpolated into LLM prompts) — reports in that
area are especially welcome. See `docs/SECURITY.md` for the threat model.
