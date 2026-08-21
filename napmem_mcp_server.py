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

SERVER_INFO = {"name": "napmem", "version": "1.1.0"}
PROTOCOL_VERSION = "2025-06-18"
SUPPORTED_PROTOCOL_VERSIONS = ("2025-06-18", "2025-03-26", "2024-11-05")
MAX_LINE_BYTES = 16 * 1024 * 1024  # cap inbound request lines (OOM guard)

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

        # Structural validation first: a request whose method is not a string
        # (or whose params is not an object) is Invalid Request per JSON-RPC,
        # never a crash and never -32601.
        if not isinstance(method, str):
            return None if is_notification else self._error(msg_id, -32600, "Invalid Request")
        params = message.get("params")
        if not isinstance(params, dict):
            params = {}

        if method == "initialize":
            # Version negotiation: echo the client's version only when we
            # actually speak it; otherwise answer with ours.
            client_version = params.get("protocolVersion")
            version = client_version if client_version in SUPPORTED_PROTOCOL_VERSIONS \
                else PROTOCOL_VERSION
            return self._result(msg_id, {
                "protocolVersion": version,
                "capabilities": {"tools": {}},
                "serverInfo": SERVER_INFO,
            })
        if method in ("notifications/initialized", "notifications/cancelled"):
            # A request (id present) using a notification method is malformed;
            # answer it so the client doesn't hang to timeout.
            return None if is_notification else self._error(msg_id, -32600, "Invalid Request")
        if method == "ping":
            return self._result(msg_id, {})
        if method == "tools/list":
            return self._result(msg_id, {"tools": TOOLS})
        if method == "tools/call":
            name = params.get("name", "")
            arguments = params.get("arguments")
            if arguments is None:
                arguments = {}
            if not isinstance(name, str) or not isinstance(arguments, dict):
                return self._error(msg_id, -32602, "Invalid params")
            try:
                payload = self.call_tool(name, arguments)
                return self._result(msg_id, {
                    "content": [{"type": "text", "text": json.dumps(payload, indent=2)}],
                    "isError": False,
                })
            except Exception as exc:
                # whatever their type (wrong-typed arguments raise AttributeError,
                # a missing optional module ImportError, malformed stores anything).
                logger.exception("Tool %s failed", name)
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
        """Newline-delimited JSON-RPC loop until EOF. No client input — valid,
        malformed, or hostile — may kill the loop; the only exits are EOF and
        a broken outbound pipe."""
        stdin = stdin or sys.stdin
        stdout = stdout or sys.stdout
        for line in stdin:
            if len(line) > MAX_LINE_BYTES:
                logger.warning("Dropping oversized request line (%d bytes)", len(line))
                self._write(stdout, self._error(None, -32700, "Parse error: line too large"))
                continue
            line = line.strip()
            if not line:
                continue
            try:
                message = json.loads(line)
            except json.JSONDecodeError as exc:
                self._write(stdout, self._error(None, -32700, f"Parse error: {exc}"))
                continue
            if not isinstance(message, dict):
                # Includes JSON-RPC batch arrays — valid JSON-RPC 2.0, but the
                # MCP stdio transport forbids them: reject, don't crash.
                self._write(stdout, self._error(None, -32600, "Invalid Request"))
                continue
            try:
                response = self.handle(message)
            except Exception:
                logger.exception("Internal error handling request")
                msg_id = message.get("id")
                response = self._error(msg_id if not isinstance(msg_id, (dict, list)) else None,
                                       -32603, "Internal error")
            if response is not None:
                try:
                    self._write(stdout, response)
                except (BrokenPipeError, OSError):
                    logger.info("Client closed the pipe; shutting down")
                    return

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
