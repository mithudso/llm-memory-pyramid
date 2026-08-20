# Security

## Threat model

No subprocess execution; credentials only via the `anthropic` SDK's standard
resolution (never read directly). Two attack surfaces:

1. **Untrusted file content** — memory files are arbitrary text flowing into
   the heuristic parser and LLM extraction prompts.
2. **Data egress** — memory text *leaves the machine* on the optional paths:
   full file content goes to the **Anthropic API** (TLS) in LLM extraction
   mode, and record/query text goes to the configured **Ollama host** for
   embeddings — by default the remote LAN server `192.168.4.75:11434` over
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
