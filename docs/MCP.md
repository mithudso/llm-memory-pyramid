# MCP

## NapMem MCP server

`napmem_mcp_server.py` exposes the pyramid to any MCP client over the stdio
transport (newline-delimited JSON-RPC 2.0, protocol `2025-06-18`). Pure
stdlib — no MCP SDK dependency. Registered for this repo in `.mcp.json`:

```json
{"mcpServers": {"napmem": {"command": "python3", "args": ["napmem_mcp_server.py"]}}}
```

Point it at a different store with `--pyramid <path>` or `NAPMEM_PYRAMID`.
The store is re-read on every tool call, so a concurrently running naptime
consolidator's updates are always visible.

## Tools

| Tool | Arguments | Returns |
|---|---|---|
| `search_memory` | `query` (req), `layer`, `semantic`, `top_k` | Substring matches across profiles/tracks/records, or embedding cosine top-k when `semantic: true` |
| `inspect_provenance` | `record_id` (req) | Record + source anchor + raw session metadata; duplicate ids resolve via their canonical |
| `get_topic_track` | `topic_slug` (req) | Full Layer 2 track with associated records |
| `memory_stats` | — | Token compression / context-budget savings stats |

Tool failures (unknown record, bad layer, missing store) return in-band MCP
errors (`isError: true`), not JSON-RPC protocol errors.

## Manual smoke test

```bash
printf '%s\n' \
  '{"jsonrpc":"2.0","id":1,"method":"initialize","params":{"protocolVersion":"2025-06-18","capabilities":{},"clientInfo":{"name":"smoke","version":"0"}}}' \
  '{"jsonrpc":"2.0","id":2,"method":"tools/list"}' \
  | python3 napmem_mcp_server.py --pyramid napmem_pyramid.json
```

The handshake, tool list, and tool calls are covered end-to-end (via
subprocess) in `test_napmem_extensions.py`.
