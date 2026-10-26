# Security Policy

## Reporting a vulnerability

Open a [private security advisory](https://github.com/mithudso/llm-memory-pyramid/security/advisories/new)
on GitHub. Do not open public issues for security problems.

## Scope notes

Optional extractors and embeddings send memory text to Anthropic or configured
Ollama hosts. The failover proxy starts SSH and local server subprocesses.
Credentials resolve through the Anthropic SDK or operator SSH configuration.
Prompt boundaries, read guards, cache validation and subprocess handling are
security surfaces. See `docs/SECURITY.md` for the threat model.
