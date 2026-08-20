# Security

## Threat model

No network calls, no credentials, no env vars, no subprocess execution. Attack
surface is **untrusted file content**: memory files are arbitrary text that
flows into (a) the heuristic parser and (b) LLM extraction prompts.

## STRIDE summary

| Threat | Exposure | Mitigation |
|---|---|---|
| Spoofing | N/A — no auth surface | — |
| Tampering | Pyramid store is plain JSON on disk | Atomic writes (`.tmp` + `os.replace`) prevent corruption; filesystem permissions are the trust boundary |
| Repudiation | Low | Every record carries a source anchor (session, file, heading, line) |
| Information disclosure | Memory files may hold sensitive user data | Store stays local; nothing is transmitted. Do not commit real pyramid stores/memory logs (`.gitignore` excludes `memory_logs/`) |
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
