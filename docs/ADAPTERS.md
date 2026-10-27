# Source adapters and portable export

Version: 1.0.0. Delta: bounded source interoperability.

`napmem ingest` supports four explicit formats, stable source identity,
revision checks and durable exclusions. Structured/Git adapters run offline;
queued or model extraction currently accepts Markdown only.

| Format | Input | Evidence |
|---|---|---|
| markdown | UTF-8 file | Registry identity survives recognized rename and same-inode edits; literal quotation/hash |
| conversation | User/assistant `{role,content}` array, or `{messages:[...]}` | Original JSON revision; decoded text absent literally from JSON stays unverified |
| portable | `{records:[{text,...}]}` or NapMem portable export | Caller scope; imported IDs, approval, authority, evidence and supersession discarded |
| git | Repository with --git-path and --revision | Stable repository/path identity; resolved commit/blob and bounded committed text |

```sh
napmem --pyramid /tmp/napmem-demo/store.json ingest /tmp/napmem-demo/notes.md --scope project:example
napmem --pyramid /tmp/napmem-demo/store.json ingest /tmp/napmem-demo/messages.json --format conversation --scope project:example
napmem --pyramid /tmp/napmem-demo/store.json ingest /tmp/napmem-demo/repository --format git --git-path docs/decisions.md --revision HEAD --scope project:example
napmem --pyramid /tmp/napmem-demo/store.json export --scope project:example
```

Portable exports group scoped records, evidence and citations under a versioned
snapshot envelope. Budgets retain complete groups. Imports do not restore
operator approval, read imported paths or execute source instructions. System
conversation roles and malformed/oversized inputs are rejected.

Git uses fixed builtin commands, bounded time/stdout, no shell, hooks, pagers,
replace objects or textconv. Source roots constrain files and repositories.
Explicit session IDs cannot take over another source or impersonate operator
correction identities. Each adapter rechecks source bytes and exclusions under
the canonical transaction; stale capture is not committed. Re-ingestion keeps
IDs and controls. A nonliteral requested quotation remains empty/unverified
rather than retaining an unrelated source passage.

Adapters provide evidence recall. Stele retains authoritative task and decision
state; the handoff brief/export avoids a competing task-management interface.
