#!/usr/bin/env python3
"""
NapMem MCP Server (stdio)

Exposes the pyramid's retrieval tools to any MCP client (Claude Code, Claude
Desktop, ...) over the Model Context Protocol stdio transport — newline-
delimited JSON-RPC 2.0 on stdin/stdout. Pure stdlib; no MCP SDK dependency.

Tools:
  - search_memory: substring or semantic search across pyramid layers
  - inspect_provenance: resolve a record id back to its Layer 0 source
  - get_topic_track: fetch a full topic track with its records
  - memory_stats: token-savings stats for the pyramid

The pyramid store is re-read on every tool call so a concurrently running
naptime consolidator's updates are always visible.

Register in .mcp.json:
    {"mcpServers": {"napmem": {"command": "python3",
                               "args": ["napmem_mcp_server.py"]}}}
"""

import argparse
import json
import logging
import os
import sys
from typing import Any

from napmem_retrieval_agent import VALID_LAYERS, NapMemRetrievalAgent

logger = logging.getLogger(__name__)

SERVER_INFO = {"name": "napmem", "version": "1.0.0"}
PROTOCOL_VERSION = "2025-06-18"

TOOLS: list[dict[str, Any]] = [
    {
        "name": "search_memory",
        "description": (
            "Search the NapMem memory pyramid. Use semantic=true for embedding "
            "cosine search over atomic records (best for paraphrased queries); "
            "default substring search covers profiles, topic tracks, and records."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "Search query."},
                "layer": {"type": "string", "enum": list(VALID_LAYERS),
                          "description": "Pyramid layer scope (substring mode only)."},
                "semantic": {"type": "boolean",
                             "description": "Embedding cosine search over records."},
                "top_k": {"type": "integer", "description": "Result count (semantic mode)."},
            },
            "required": ["query"],
            "additionalProperties": False,
        },
    },
    {
        "name": "inspect_provenance",
        "description": ("Resolve a memory record id (canonical or duplicate) back to its "
                        "source anchor and raw session metadata."),
        "inputSchema": {
            "type": "object",
            "properties": {"record_id": {"type": "string"}},
            "required": ["record_id"],
            "additionalProperties": False,
        },
    },
    {
        "name": "get_topic_track",
        "description": "Fetch a full topic track (Layer 2 cluster) with its atomic records.",
        "inputSchema": {
            "type": "object",
            "properties": {"topic_slug": {"type": "string"}},
            "required": ["topic_slug"],
            "additionalProperties": False,
        },
    },
    {
        "name": "memory_stats",
        "description": "Token compression / context-budget savings stats for the pyramid.",
        "inputSchema": {"type": "object", "properties": {}, "additionalProperties": False},
    },
]


class NapMemMCPServer:
    def __init__(self, pyramid_path: str):
        self.pyramid_path = pyramid_path

    def _agent(self) -> NapMemRetrievalAgent:
        # Fresh load per call: the consolidator may have rewritten the store.
        return NapMemRetrievalAgent(pyramid_path=self.pyramid_path)

    def call_tool(self, name: str, arguments: dict[str, Any]) -> Any:
        agent = self._agent()
        if name == "search_memory":
            if arguments.get("semantic"):
                return agent.semantic_search(arguments["query"],
                                             top_k=int(arguments.get("top_k", 5)))
            return agent.search_memory_pyramid(arguments["query"],
                                               arguments.get("layer", "all"))
        if name == "inspect_provenance":
            return agent.inspect_provenance(arguments["record_id"])
        if name == "get_topic_track":
            return agent.get_topic_track(arguments["topic_slug"])
        if name == "memory_stats":
            return agent.compute_context_budget_savings()
        raise KeyError(f"Unknown tool: {name}")

    # --- JSON-RPC plumbing -------------------------------------------------

    def handle(self, message: dict[str, Any]) -> dict[str, Any] | None:
        """Returns a JSON-RPC response dict, or None for notifications."""
        method = message.get("method")
        msg_id = message.get("id")
        is_notification = "id" not in message

        if method == "initialize":
            client_version = message.get("params", {}).get("protocolVersion", PROTOCOL_VERSION)
            return self._result(msg_id, {
                "protocolVersion": client_version,
                "capabilities": {"tools": {}},
                "serverInfo": SERVER_INFO,
            })
        if method in ("notifications/initialized", "notifications/cancelled"):
            return None
        if method == "ping":
            return self._result(msg_id, {})
        if method == "tools/list":
            return self._result(msg_id, {"tools": TOOLS})
        if method == "tools/call":
            params = message.get("params", {})
            name = params.get("name", "")
            arguments = params.get("arguments") or {}
            try:
                payload = self.call_tool(name, arguments)
                return self._result(msg_id, {
                    "content": [{"type": "text", "text": json.dumps(payload, indent=2)}],
                    "isError": False,
                })
            except (KeyError, ValueError, TypeError, FileNotFoundError) as exc:
                # Tool-level failure: MCP reports it in-band, not as JSON-RPC error.
                logger.error("Tool %s failed: %s", name, exc)
                return self._result(msg_id, {
                    "content": [{"type": "text", "text": f"Error: {exc}"}],
                    "isError": True,
                })
        if is_notification:
            return None
        return self._error(msg_id, -32601, f"Method not found: {method}")

    @staticmethod
    def _result(msg_id: Any, result: dict[str, Any]) -> dict[str, Any]:
        return {"jsonrpc": "2.0", "id": msg_id, "result": result}

    @staticmethod
    def _error(msg_id: Any, code: int, message: str) -> dict[str, Any]:
        return {"jsonrpc": "2.0", "id": msg_id, "error": {"code": code, "message": message}}

    def serve(self, stdin=None, stdout=None):
        """Newline-delimited JSON-RPC loop until EOF."""
        stdin = stdin or sys.stdin
        stdout = stdout or sys.stdout
        for line in stdin:
            line = line.strip()
            if not line:
                continue
            try:
                message = json.loads(line)
            except json.JSONDecodeError as exc:
                self._write(stdout, self._error(None, -32700, f"Parse error: {exc}"))
                continue
            response = self.handle(message)
            if response is not None:
                self._write(stdout, response)

    @staticmethod
    def _write(stdout, response: dict[str, Any]):
        stdout.write(json.dumps(response) + "\n")
        stdout.flush()


def main():
    parser = argparse.ArgumentParser(description="NapMem MCP stdio server.")
    parser.add_argument("--pyramid", type=str,
                        default=os.environ.get("NAPMEM_PYRAMID", "napmem_pyramid.json"))
    args = parser.parse_args()

    # Logs go to stderr — stdout is the protocol channel.
    logging.basicConfig(stream=sys.stderr, level=logging.INFO,
                        format="%(asctime)s [%(name)s] %(levelname)s: %(message)s")
    logger.info("NapMem MCP server starting (pyramid: %s)", args.pyramid)
    NapMemMCPServer(args.pyramid).serve()


if __name__ == "__main__":
    main()
