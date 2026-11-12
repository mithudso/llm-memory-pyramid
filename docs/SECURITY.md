# Security

## Threat model

The failover proxy starts SSH and local MCP server subprocesses. SSH uses the
operator's configuration; Anthropic credentials use the SDK's standard
resolution. Memory sources, model output, persisted caches and protocol
messages cross trust boundaries. Principal attack surfaces:

1. **Untrusted file content** — memory files are arbitrary text flowing into
   the heuristic parser and LLM extraction prompts.
2. **Data egress** — memory text *leaves the machine* on the optional paths:
   full file content goes to the **Anthropic API** (TLS) in LLM extraction
   mode, and record/query text goes to the configured **Ollama host** for
   embeddings — the hosts in `NAPMEM_OLLAMA_URLS` (a remote LAN server in the deployed fleet) over
   **plain HTTP**. Treat the watch directory as the consent boundary: do not
   point the consolidator at files that must never leave the machine, or run
   `--extraction heuristic` with `NAPMEM_EMBED_BACKEND=hashed`. Cached
   embedding vectors (`*.embindex.json`) are themselves partially invertible
   and should be treated as sensitive as the text they encode.

## STRIDE summary

| Threat | Exposure | Mitigation |
|---|---|---|
| Spoofing | Ollama traffic is unauthenticated plain HTTP on the LAN — a spoofed/compromised host could serve crafted embeddings | Strict response validation in `OllamaBackend.embed` (numeric-only vectors, consistent dimension) blocks structural poisoning of the vector cache; semantically crafted vectors remain possible — put the Ollama hosts on a trusted network segment, or force `NAPMEM_EMBED_BACKEND=hashed` |
| Tampering | Pyramid store and embedding cache are plain JSON on disk | Atomic writes (`.tmp` + `os.replace`) prevent corruption; filesystem permissions are the trust boundary |
| Repudiation | Low | Every record carries a source anchor (session, file, heading, line) |
| Information disclosure | Memory files may hold sensitive user data; text egresses to the Anthropic API (LLM mode) and the Ollama host (embeddings, plain HTTP); embedding vectors are partially invertible | See "Data egress" in the threat model. Do not commit real pyramid stores/memory logs or embedding caches (`.gitignore` excludes `memory_logs/` and `*.embindex.json`) |
| Denial of service | Malformed/huge files | Consolidator skips unreadable/non-UTF-8 files per-file; no recursion on input |
| Elevation of privilege | Prompt injection via memory-file content | See below |

## Prompt-injection defenses (`llm_extraction_prompts.py`)

- **Untrusted-content guard**: system prompt instructs the model to treat all
  document text as data, never instructions.
- **Sentinel delimiter, not markdown fence**: a ``` in hostile text would
  close a fence early; the sentinel `<<<RAW_MEMORY_SOURCE>>>` bounds the data
  region instead.
- **Loop neutralization**: occurrences of the sentinel inside source text are
  replaced *until none survive* — a single replace is bypassable because
  stripping one bracket from a nested form reconstitutes the delimiter.
- **Metadata hardening**: session ids and file names are interpolated outside
  the delimited region, so they are stripped of newlines and sentinels — a
  hostile filename cannot smuggle instruction lines.

Instruction-following by the downstream LLM remains probabilistic; treat
extractor output as untrusted data and validate against
`memory_pyramid_schema.json` before ingestion.

## Reporting

See [.github/SECURITY.md](../.github/SECURITY.md) — private advisories only.

## Current runtime and filesystem boundaries

The project MCP configuration selects local stdio and loopback Ollama. Optional
legacy CLI configurations can still target remote services. The fleet examples
above are historical; configuration determines actual egress. Source labels now
share the prompt's untrusted-data region. Sentinel redaction is conservative:
a redacted marker cannot prove an original literal quotation, and the binder
leaves mismatching evidence unverified. Prompt guards do not prove model obedience.

Job SQLite paths must be regular singly-linked files inside a user-owned directory
that other users cannot write. The opener retains its checked descriptor through
SQLite open and checks path identity before SQL. Same-user writers and arbitrary
operator changes to the directory remain inside the filesystem trust boundary.
Raw source reads compare size, mtime and ctime. Rename inference requires matching
creation identity; unknown or reused identity never inherits another source's scope.

Proxy request count, pending bytes, local/remote response time and real output-pipe
writes are bounded. Provider/SSH error bodies do not enter the new failure logs.
No new reporting deadline, legal assurance, license or compliance claim is made.
