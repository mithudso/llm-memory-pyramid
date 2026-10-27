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
from copy import deepcopy
import json
import logging
import math
import os
import sys
import time
from typing import Any

from napmem_retrieval_agent import VALID_LAYERS, NapMemRetrievalAgent

logger = logging.getLogger(__name__)

SERVER_INFO = {"name": "napmem", "version": "1.2.0"}
PROTOCOL_VERSION = "2025-06-18"
SUPPORTED_PROTOCOL_VERSIONS = ("2025-06-18", "2025-03-26", "2024-11-05")
MAX_LINE_BYTES = 16 * 1024 * 1024  # cap inbound request lines (OOM guard)
MAX_TOOL_BYTES = 1024 * 1024
DEFAULT_TOOL_BYTES = 16384
DEFAULT_TOOL_TOKENS = 2048
TOKEN_ESTIMATOR = "ceil(complete_jsonrpc_utf8_bytes_including_newline/4)"

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
                "top_k": {"type": "integer", "minimum": 1, "description": "Result count (semantic mode)."},
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

# Both the advertised schema and the runtime validator use these constraints.
COMMON_INPUT = {
    "scope": {"type": ["string", "null"], "minLength": 1, "maxLength": 256},
    "as_of": {"type": ["string", "null"], "format": "date-time", "maxLength": 128},
    "max_bytes": {"type": "integer", "minimum": 128, "maximum": MAX_TOOL_BYTES},
    "max_tokens": {"type": ["integer", "null"], "minimum": 32, "maximum": MAX_TOOL_BYTES},
}
ERROR_SCHEMA = {"type": "object", "properties": {"error": {
    "type": "object", "properties": {"code": {"type": "string"}, "message": {"type": "string"}},
    "required": ["code", "message"], "additionalProperties": False}}, "required": ["error"]}
RECORD_SCHEMA = {"type": "object", "properties": {"id": {"type": "string"}, "text": {"type": "string"},
    "scope": {"type": "string"}, "evidence": {"type": "object"}}, "required": ["id", "text"]}
OUTPUT_SCHEMAS = {
    "search_memory": {"type": "object", "properties": {
        "query": {"type": "string"}, "mode": {"type": "string"},
        "matches": {"anyOf": [{"type": "array", "items": RECORD_SCHEMA},
                               {"type": "object", "properties": {
                                   key: {"type": "array", "items": {"type": "object"}}
                                   for key in ("memory_records", "topic_tracks", "user_profiles")}, "additionalProperties": False}]},
        "truncated": {"type": "boolean"}, "omitted_count": {"type": "integer", "minimum": 0}},
        "required": ["query", "mode", "matches"]},
    "inspect_provenance": {"type": "object", "properties": {
        "record_id": {"type": "string"}, "text": {"type": "string"}, "scope": {"type": "string"},
        "source_anchor": {"type": "object"}, "evidence": {"type": "object"}, "verification": {"type": "object"}},
        "required": ["record_id", "text", "source_anchor", "evidence"]},
    "get_topic_track": {"type": "object", "properties": {
        "track": {"type": "object", "properties": {"topic_slug": {"type": "string"}}, "required": ["topic_slug"]},
        "records": {"type": "array", "items": RECORD_SCHEMA}, "truncated": {"type": "boolean"}},
        "required": ["track", "records"]},
    "memory_stats": {"type": "object", "properties": {
        "scope": {"type": ["string", "null"]}, "generation": {"type": "integer"},
        "current_records": {"type": "integer"}, "token_compression_ratio": {"type": "string"},
        "comparison": {"type": "string"}, "raw_memory_estimated_tokens": {"type": "integer"}},
        "required": ["generation", "current_records", "comparison", "token_compression_ratio"]},
}
for _tool in TOOLS:
    _properties = _tool["inputSchema"]["properties"]
    _properties.update(deepcopy(COMMON_INPUT))
    if _tool["name"] == "search_memory":
        _properties["query"].update(minLength=1, maxLength=2048)
        _properties["mode"] = {"type": "string", "enum": ["hybrid", "lexical", "semantic"]}
    if _tool["name"] in ("search_memory", "get_topic_track"):
        _properties["top_k"] = {"type": "integer", "minimum": 1, "maximum": 100}
    for _field in ("record_id", "topic_slug"):
        if _field in _properties:
            _properties[_field].update(minLength=1, maxLength=512)
    _tool["outputSchema"] = {"type": "object", "anyOf": [OUTPUT_SCHEMAS[_tool["name"]], ERROR_SCHEMA]}
    _tool["annotations"] = {"readOnlyHint": True, "destructiveHint": False, "openWorldHint": False}
TOOLS[0]["description"] += " An explicit mode uses the shared scoped query API. Budgets cover the entire JSON-RPC response."


class ToolInputError(ValueError):
    """A schema-invalid tool request; no store has been loaded."""


def valid_request_id(value: Any) -> bool:
    return ((isinstance(value, str) and len(value) <= 512 and _utf8_text(value))
            or (isinstance(value, int) and not isinstance(value, bool) and -(2**63) <= value < 2**63))


def _utf8_text(value: str) -> bool:
    try:
        value.encode("utf-8")
        return True
    except UnicodeError:
        return False


def wire_json(response: dict[str, Any]) -> str:
    return json.dumps(response, ensure_ascii=False, separators=(",", ":"), allow_nan=False) + "\n"


def _budget_error(msg_id):
    return {"jsonrpc": "2.0", "id": msg_id, "error": {
        "code": -32001, "message": "Response budget too small for metadata"}}


def response_budget_fits_id(msg_id: Any, max_bytes: int, max_tokens: int | None) -> bool:
    size = len(wire_json(_budget_error(msg_id)).encode("utf-8"))
    return size <= max_bytes and (max_tokens is None or math.ceil(size / 4) <= max_tokens)


def budget_request_error(msg_id):
    # This is a rejected parameter combination, bounded by the global transport
    # cap. It does not claim to honor an impossible per-request response limit.
    return {"jsonrpc": "2.0", "id": msg_id, "error": {
        "code": -32602, "message": "Requested budget cannot hold response ID"}}


def limit_wire_response(response: dict[str, Any], *, max_bytes: int = MAX_TOOL_BYTES,
                        max_tokens: int | None = None) -> dict[str, Any]:
    """Final transport guard; never cut serialized JSON or reflect an invalid ID."""
    if not isinstance(response, dict):
        response = {"jsonrpc": "2.0", "id": None, "error": {"code": -32603, "message": "Invalid backend response"}}
    msg_id = response.get("id")
    if msg_id is not None and not valid_request_id(msg_id):
        return {"jsonrpc": "2.0", "id": None, "error": {"code": -32600, "message": "Invalid response ID"}}
    size = len(wire_json(response).encode("utf-8"))
    if size <= max_bytes and (max_tokens is None or math.ceil(size / 4) <= max_tokens):
        return response
    return _budget_error(msg_id) if response_budget_fits_id(msg_id, max_bytes, max_tokens) else budget_request_error(msg_id)


def tool_budgets(arguments: dict[str, Any]) -> tuple[int, int | None]:
    maximum = arguments.get("max_bytes", DEFAULT_TOOL_BYTES)
    tokens = arguments.get("max_tokens", DEFAULT_TOOL_TOKENS)
    if isinstance(maximum, bool) or not isinstance(maximum, int) or not 128 <= maximum <= MAX_TOOL_BYTES:
        maximum = DEFAULT_TOOL_BYTES
    if tokens is not None and (isinstance(tokens, bool) or not isinstance(tokens, int) or not 32 <= tokens <= MAX_TOOL_BYTES):
        tokens = DEFAULT_TOOL_TOKENS
    return maximum, tokens


def validate_tool_arguments(name: str, arguments: dict[str, Any]) -> dict[str, Any]:
    tool = next((item for item in TOOLS if item["name"] == name), None)
    if tool is None or not isinstance(arguments, dict):
        raise ToolInputError("Unknown tool or invalid arguments")
    schema = tool["inputSchema"]
    if set(arguments) - set(schema["properties"]) or set(schema.get("required", [])) - set(arguments):
        raise ToolInputError("Unknown or missing tool argument")
    for key, value in arguments.items():
        spec = schema["properties"][key]
        types = spec["type"] if isinstance(spec["type"], list) else [spec["type"]]
        if value is None and "null" in types:
            continue
        if "boolean" in types:
            valid = isinstance(value, bool)
        elif "integer" in types:
            valid = isinstance(value, int) and not isinstance(value, bool) and spec.get("minimum", 0) <= value <= spec.get("maximum", MAX_TOOL_BYTES)
        else:
            valid = (isinstance(value, str) and spec.get("minLength", 0) <= len(value) <= spec.get("maxLength", 4096)
                     and bool(value.strip()) and _utf8_text(value))
        if not valid or ("enum" in spec and value not in spec["enum"]):
            raise ToolInputError("Invalid tool argument type or bounds")
    if arguments.get("scope") is not None and arguments["scope"] != "*":
        from napmem_model import normalize_record
        try:
            normalize_record({"id": "mcp_validation", "text": "", "scope": arguments["scope"]})
        except ValueError as exc:
            raise ToolInputError("Invalid scope") from exc
    if arguments.get("as_of") is not None:
        from napmem_model import parse_time
        try:
            parse_time(arguments["as_of"])
        except ValueError as exc:
            raise ToolInputError("Invalid as_of") from exc
    if "mode" in arguments and (arguments.get("semantic") is True or "layer" in arguments):
        raise ToolInputError("Explicit mode cannot combine with legacy layer or semantic selection")
    return deepcopy(arguments)


def _payload_json(payload):
    return json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)


def _prune_payload(payload):
    # Derived prose loses its evidence when a record is omitted; discard it first.
    collections = []
    for key in ("profiles", "tracks", "matches", "records", "sessions_missing", "sessions_compared"):
        value = payload.get(key)
        if isinstance(value, list) and value:
            collections.append(value)
        elif key == "matches" and isinstance(value, dict):
            collections.extend(items for _, items in sorted(value.items()) if isinstance(items, list) and items)
    if not collections:
        return False
    collections[0].pop()
    payload["truncated"] = True
    omitted = payload.get("omitted_count", 0)
    payload["omitted_count"] = (omitted if isinstance(omitted, int) and not isinstance(omitted, bool) and omitted >= 0 else 0) + 1
    if isinstance(payload.get("matches"), list) and not payload["matches"] and "abstention" in payload:
        payload.update(abstention=True, status="budget_exhausted")
    if "returned_bytes" in payload or "estimated_tokens" in payload:
        for _ in range(16):
            size = len(_payload_json(payload).encode("utf-8"))
            if payload.get("returned_bytes") == size and payload.get("estimated_tokens") == math.ceil(size / 4):
                break
            payload.update(returned_bytes=size, estimated_tokens=math.ceil(size / 4))
    return True


def bounded_tool_result(msg_id: Any, payload: dict[str, Any], *, max_bytes: int = DEFAULT_TOOL_BYTES,
                        max_tokens: int | None = DEFAULT_TOOL_TOKENS,
                        extra_content: list[dict[str, Any]] | None = None, is_error: bool = False) -> dict[str, Any]:
    """Fit complete JSON values into the UTF-8 JSON-RPC envelope, including newline.

    Both structured and textual copies, escaping, metadata and optional final
    fallback notes count. Tiny budgets return a bounded protocol error rather
    than emitting partial JSON or pretending the requested limit was honored.
    """
    if (isinstance(max_bytes, bool) or not isinstance(max_bytes, int) or not 128 <= max_bytes <= MAX_TOOL_BYTES
            or (max_tokens is not None and (isinstance(max_tokens, bool) or not isinstance(max_tokens, int)
                                           or not 32 <= max_tokens <= MAX_TOOL_BYTES))):
        raise ValueError("Invalid whole-wire budget")
    msg_id = msg_id if valid_request_id(msg_id) else None
    if not response_budget_fits_id(msg_id, max_bytes, max_tokens):
        raise ValueError("Requested budget cannot hold response ID")
    payload = deepcopy(payload)
    extra = deepcopy(extra_content or [])
    omitted = payload.get("omitted_count", 0)
    omitted = omitted if isinstance(omitted, int) and not isinstance(omitted, bool) and omitted >= 0 else 0
    metadata = {"scope": "complete_jsonrpc_utf8_including_newline", "max_bytes": max_bytes,
                "max_tokens": max_tokens, "wire_bytes": 0, "estimated_tokens": 0,
                "token_estimator": TOKEN_ESTIMATOR, "truncated": payload.get("truncated") is True,
                "omitted_count": omitted}

    def build():
        result = {"jsonrpc": "2.0", "id": msg_id, "result": {
            "content": [{"type": "text", "text": _payload_json(payload)}, *extra],
            "structuredContent": payload, "isError": is_error, "_meta": {"napmem": metadata}}}
        for _ in range(16):
            count = len(wire_json(result).encode("utf-8"))
            estimate = math.ceil(count / 4)
            if metadata["wire_bytes"] == count and metadata["estimated_tokens"] == estimate:
                return result
            metadata.update(wire_bytes=count, estimated_tokens=estimate)
        raise ValueError("Cannot account for response metadata")

    while True:
        result = build()
        if metadata["wire_bytes"] <= max_bytes and (max_tokens is None or metadata["estimated_tokens"] <= max_tokens):
            return result
        if not _prune_payload(payload):
            break
        metadata.update(truncated=True, omitted_count=metadata["omitted_count"] + 1)
    # Evidence-free metadata can itself exceed a requested budget. A compact
    # RPC error remains valid JSON even when no tool envelope can fit.
    return _budget_error(msg_id)


def bounded_lines(stdin):
    """Yield bounded UTF-8 lines, or None after draining an invalid line.

    Native text streams expose their byte buffer, so limits apply before
    UTF-8 decoding. StringIO fixtures remain bounded by character count too.
    """
    stream = getattr(stdin, "buffer", stdin)
    while True:
        chunk = stream.readline(MAX_LINE_BYTES + 1)
        if not chunk:
            return
        newline = b"\n" if isinstance(chunk, bytes) else "\n"
        oversized = len(chunk) > MAX_LINE_BYTES
        if oversized:
            while not chunk.endswith(newline):
                chunk = stream.readline(MAX_LINE_BYTES + 1)
                if not chunk:
                    break
            logger.warning("Dropping oversized request line")
            yield None
            continue
        try:
            line = chunk.decode("utf-8") if isinstance(chunk, bytes) else chunk
            if len(line.encode("utf-8")) > MAX_LINE_BYTES:
                logger.warning("Dropping oversized UTF-8 request line")
                yield None
                continue
        except UnicodeError:
            logger.warning("Dropping invalid UTF-8 request line")
            yield None
            continue
        yield line


class NapMemMCPServer:
    def __init__(self, pyramid_path: str):
        self.pyramid_path = pyramid_path

    def _agent(self) -> NapMemRetrievalAgent:
        # Fresh load per call: the consolidator may have rewritten the store.
        return NapMemRetrievalAgent(pyramid_path=self.pyramid_path)

    def call_tool(self, name: str, arguments: dict[str, Any]) -> Any:
        arguments = validate_tool_arguments(name, arguments)
        agent = self._agent()
        common = {key: arguments[key] for key in COMMON_INPUT if key in arguments}
        if name == "search_memory":
            if "mode" in arguments:
                return agent.query(arguments["query"], mode=arguments["mode"],
                                   top_k=arguments.get("top_k", 5), **common)
            if arguments.get("semantic"):
                return agent.semantic_search(arguments["query"], top_k=arguments.get("top_k", 5), **common)
            return agent.search_memory_pyramid(arguments["query"],
                                               arguments.get("layer", "all"),
                                               top_k=arguments.get("top_k", 20), **common)
        if name == "inspect_provenance":
            return agent.inspect_provenance(arguments["record_id"], **common)
        if name == "get_topic_track":
            return agent.get_topic_track(arguments["topic_slug"], top_k=arguments.get("top_k", 20), **common)
        if name == "memory_stats":
            return agent.compute_context_budget_savings(include_source_estimate=False, **common)
        raise KeyError(f"Unknown tool: {name}")

    def _tool_response(self, msg_id, name, arguments, payload, started, *, is_error=False):
        maximum, tokens = tool_budgets(arguments)
        response = bounded_tool_result(msg_id, payload, max_bytes=maximum, max_tokens=tokens, is_error=is_error)
        # These bytes stop at this server. A failover proxy accounts separately
        # for the snapshot metadata and note it appends before client delivery.
        if name == "search_memory" and os.environ.get("NAPMEM_METRICS", "").lower() in ("1", "true"):
            try:
                from napmem_metrics import hash_scope, record_if_enabled
                result = response.get("result", {})
                content = result.get("structuredContent", {})
                matches = content.get("matches", [])
                count = (sum(len(items) for items in matches.values() if isinstance(items, list))
                         if isinstance(matches, dict) else len(matches) if isinstance(matches, list) else 0)
                mode = str(content.get("mode", ""))
                success = "error" not in response and result.get("isError") is False
                backend = ("hashed" if "hashed" in mode else "ollama" if "ollama" in mode else
                           "hybrid" if "hybrid" in mode else "lexical" if mode in ("substring", "lexical") or "fallback" in mode else "unavailable")
                record_if_enabled(self.pyramid_path, "retrieval", stage="retrieval",
                                  latency_ms=(time.perf_counter() - started) * 1000,
                                  returned_bytes=len(wire_json(response).encode("utf-8")),
                                  result_count=count, empty=count == 0, success=success,
                                  fallback="fallback" in mode, backend=backend,
                                  scope_hash=hash_scope(arguments.get("scope")))
            except Exception:
                # Optional telemetry must not change a successful retrieval.
                logger.debug("Optional retrieval metrics were unavailable")
        return response

    # --- JSON-RPC plumbing -------------------------------------------------

    def handle(self, message: dict[str, Any]) -> dict[str, Any] | None:
        """Returns a JSON-RPC response dict, or None for notifications."""
        started = time.perf_counter()
        method = message.get("method")
        msg_id = message.get("id")
        is_notification = "id" not in message

        valid_id = valid_request_id(msg_id)
        safe_id = msg_id if valid_id else None
        if (message.get("jsonrpc") != "2.0" or not isinstance(method, str)
                or (not is_notification and not valid_id)):
            return self._error(safe_id, -32600, "Invalid Request")
        # Notifications are one-way. Never dispatch request-only methods as
        # notifications: they must not execute tools or emit unmatched replies.
        if is_notification:
            return None
        params = message.get("params", {})
        if not isinstance(params, dict):
            return self._error(msg_id, -32602, "Invalid params")

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
            arguments = params.get("arguments", {})
            if ("name" not in params or not isinstance(name, str) or not name.strip() or not isinstance(arguments, dict)
                    or set(params) - {"name", "arguments", "_meta"}
                    or ("_meta" in params and not isinstance(params["_meta"], dict))):
                return self._error(msg_id, -32602, "Invalid params")
            maximum, tokens = tool_budgets(arguments)
            if not response_budget_fits_id(msg_id, maximum, tokens):
                return budget_request_error(msg_id)
            try:
                payload = self.call_tool(name, arguments)
                failed = isinstance(payload, dict) and "error" in payload
                if failed:
                    payload = {"error": {"code": "MEMORY_UNAVAILABLE", "message": "Requested memory is unavailable"}}
                return self._tool_response(msg_id, name, arguments, payload, started, is_error=failed)
            except ToolInputError as exc:
                logger.error("Tool arguments rejected (%s)", type(exc).__name__)
                payload = {"error": {"code": "INVALID_TOOL_ARGUMENTS", "message": "Unknown tool or invalid tool arguments"}}
                return self._tool_response(msg_id, name, arguments, payload, started, is_error=True)
            except Exception as exc:
                logger.error("Tool execution failed (%s)", type(exc).__name__)
                payload = {"error": {"code": "TOOL_FAILED", "message": "Memory tool could not complete"}}
                return self._tool_response(msg_id, name, arguments, payload, started, is_error=True)
        if is_notification:
            return None
        return self._error(msg_id, -32601, "Method not found")

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
        try:
            for line in bounded_lines(stdin):
                if line is None:
                    self._write(stdout, self._error(None, -32700, "Parse error: invalid line"))
                    continue
                line = line.strip()
                if not line:
                    continue
                try:
                    message = json.loads(line)
                except (ValueError, RecursionError) as exc:
                    logger.warning("Request JSON decoding failed (%s)", type(exc).__name__)
                    self._write(stdout, self._error(None, -32700, "Parse error"))
                    continue
                if not isinstance(message, dict):
                    self._write(stdout, self._error(None, -32600, "Invalid Request"))
                    continue
                try:
                    response = self.handle(message)
                except Exception:
                    logger.exception("Internal error handling request")
                    msg_id = message.get("id")
                    valid_id = valid_request_id(msg_id)
                    response = self._error(msg_id if valid_id else None, -32603, "Internal error")
                if response is not None:
                    self._write(stdout, response)
        except (BrokenPipeError, OSError):
            logger.info("Client closed the pipe; shutting down")

    @staticmethod
    def _write(stdout, response: dict[str, Any]):
        line = wire_json(limit_wire_response(response))
        binary = getattr(stdout, "buffer", None)
        if binary is not None:
            binary.write(line.encode("utf-8"))
            binary.flush()
        else:
            stdout.write(line)
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
