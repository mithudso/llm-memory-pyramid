# MCP and client contracts

Server version: 1.2.0. Protocol: 2025-06-18. Transport: UTF-8 newline-delimited
JSON-RPC over stdio, implemented with the standard library.

Use `napmem --pyramid /absolute/store.json mcp` for the configured portable
entrypoint. Legacy modules and the proxy remain available with explicit stores.
This release does not modify installed client configurations or services.

## Tools

Four read-only tools accept scope, as_of, max_bytes and max_tokens:

| Tool | Selection | Result |
|---|---|---|
| search_memory | Required query; explicit mode hybrid/lexical/semantic, top_k | Shared CLI query contract, matches list |
| search_memory legacy | Default layer all, or semantic=true | Compatible nested substring matches or semantic list |
| inspect_provenance | Required record_id | Scoped occurrence evidence/source metadata; no implicit source reread |
| get_topic_track | Required topic_slug, top_k | Scoped eligible records, bounded as complete entries |
| memory_stats | Scope/time | Metadata-only counts; no raw source reads |

Explicit mode cannot combine with legacy layer/semantic selection. Top-k is
1–100. Queries have at most 2,048 characters; IDs/topic slugs at most 512.
Times must be timezone-aware. Unknown fields, invalid Unicode, booleans used as
integers and invalid scopes are rejected before store loading.

Input/output schemas are published through tools/list. Tool results return
structuredContent and equivalent JSON in content[0].text. Errors contain no
private exception bodies. Invalid tool arguments/unknown tools remain in-band
isError results; malformed RPC params return -32602. Notifications execute no
tools and receive no reply.

## Complete response budgets

Tool max_bytes is 128–1,048,576. Max_tokens is a byte-based estimate with minimum
32, or null to disable that cap. Defaults: 16,384 bytes/2,048 estimated tokens.
Both JSON copies, escaped text, UTF-8, metadata, newline and fallback note count.
`_meta.napmem` discloses wire_bytes, estimator, truncation and omitted entries.
Complete values are removed to fit; JSON is never cut. Tiny metadata budgets
return a correlated -32001 error.

A requested budget unable to hold a minimal response with its original valid
ID is rejected before dispatch with -32602 under the global output cap. This
invalid combination does not receive its requested smaller cap; the rejection
explains why. Accepted requests retain their correlation IDs. IDs are bounded
strings or signed 64-bit integers. Inbound lines have a 16 MiB hard limit.

CLI budgets cover one JSON payload; MCP budgets cover its larger wire envelope.
Equivalent scoped requests return the same candidates when both budgets fit.
Smaller MCP budgets can omit more evidence; clients must inspect truncation.

## Mirrors and fallback

Mirrors publish immutable generations through an atomic pointer. The manifest
binds store and optional cache checksums/configuration. Failed/older refreshes
preserve the active generation. Managed generations require manifests even in
new readers. Legacy flat mirrors disclose unverified generation provenance.
Snapshot searches cannot write caches.

On remote failure/timeout, the proxy starts the local backend, replays
initialization and resends pending requests. Its final text block is the
fallback note. Structured metadata reports the actual spawned snapshot's
generation, age and verification. Both count toward the final wire budget.
Deletion receipts disclose pending replicas and operator-managed originals,
exports and backups; forgetting does not silently erase unreachable mirrors.

## Verified capability matrix

| Surface | Evidence | Limits |
|---|---|---|
| Python query | Scoped/time/budget fixtures | Real embedding quality unmeasured |
| Installed CLI | Fresh wheel, absent optional clients, actual commands outside checkout | Receipt names tested interpreter/platform |
| Local MCP stdio | Actual subprocess handshake, tools/call and CLI parity | No deployed client installation claim |
| Proxy | Fake backend lifecycle and validated local snapshots | Production SSH/authentication unverified |
| Claude Code/Desktop and other external clients | Schema/text protocol interface | Actual installed configurations unverified |

Protocol reference:
https://modelcontextprotocol.io/specification/2025-06-18/server/tools
