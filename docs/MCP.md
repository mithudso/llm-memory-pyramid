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

## Failover proxy (`napmem_mcp_failover.py`)

`.mcp.json` registers the proxy, not the server directly:

```json
{"mcpServers": {"napmem": {"command": "python3", "args": ["napmem_mcp_failover.py"]}}}
```

| Situation | Behavior |
|---|---|
| Remote reachable at startup | Relays to the canonical server over SSH; refreshes `~/.napmem/mirror/` in the background when older than `NAPMEM_MIRROR_MAX_AGE` (3600 s) |
| Remote unreachable at startup | Serves local `napmem_mcp_server.py --pyramid ~/.napmem/mirror/napmem_pyramid.json` |
| SSH dies mid-session | Spawns the local server, replays `initialize` + `notifications/initialized` (response swallowed), resends in-flight requests |
| Remote alive but a request unanswered for `NAPMEM_REMOTE_REQUEST_TIMEOUT` (60 s) | Kills the SSH backend and fails over as above |
| Local server dies | Restarts up to 2 times, then answers requests with JSON-RPC `-32603` errors instead of hanging |

While on the mirror, each `tools/call` result gets an extra text item:
`[napmem fallback] Remote napmem server is unreachable; this answer came from the local mirror (snapshot is N min old).`

Config: `NAPMEM_REMOTE_HOST` (else first line of `~/.napmem/remote_host`;
neither means local only), `NAPMEM_REMOTE_PYRAMID`, `NAPMEM_REMOTE_REPO`,
`NAPMEM_MIRROR_DIR`, `NAPMEM_MIRROR_MAX_AGE`, `NAPMEM_SSH_TIMEOUT` (5 s),
`NAPMEM_FALLBACK_OLLAMA` (`http://127.0.0.1:11434`; keep it on the same
embedding model as the remote so the mirrored `.embindex.json` stays valid).

```bash
python3 napmem_mcp_failover.py --status       # host, reachability, mirror age
python3 napmem_mcp_failover.py --sync-mirror  # refresh the mirror now
```

Mirror writes go through tmp + `os.replace`; a pyramid that fails to parse
as a JSON object never replaces the previous snapshot.

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
subprocess) in `test_napmem_extensions.py`; the proxy in `test_napmem_failover.py`.
