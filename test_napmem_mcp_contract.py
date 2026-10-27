"""Typed MCP contracts, strict pre-load validation and complete wire budgets."""

import io
import json
import math
import os
from pathlib import Path
import tempfile
import time
from types import ModuleType
import unittest
from unittest.mock import Mock, patch

from memory_pyramid_distiller import MemoryPyramidDistiller
import napmem_mcp_failover as failover
import napmem_mcp_server as mcp
from napmem_retrieval_agent import NapMemRetrievalAgent


AS_OF = "2026-10-27T12:00:00Z"


def request(name, arguments=None, msg_id=1):
    return {"jsonrpc": "2.0", "id": msg_id, "method": "tools/call",
            "params": {"name": name, "arguments": arguments or {}}}


class TestInputContracts(unittest.TestCase):
    def setUp(self):
        self.server = mcp.NapMemMCPServer("/unused-contract-test-store")

    def test_four_read_only_tools_have_typed_input_and_output_schemas(self):
        self.assertEqual({item["name"] for item in mcp.TOOLS}, {
            "search_memory", "inspect_provenance", "get_topic_track", "memory_stats"})
        for tool in mcp.TOOLS:
            with self.subTest(tool=tool["name"]):
                self.assertTrue(tool["annotations"]["readOnlyHint"])
                self.assertFalse(tool["inputSchema"]["additionalProperties"])
                self.assertEqual(tool["outputSchema"]["type"], "object")
                success, failure = tool["outputSchema"]["anyOf"]
                self.assertTrue(success["properties"])
                self.assertTrue(success["required"])
                self.assertEqual(failure["required"], ["error"])
                self.assertTrue(set(mcp.COMMON_INPUT) <= tool["inputSchema"]["properties"].keys())
        self.assertEqual(mcp.SERVER_INFO["version"], "1.2.0")

    def test_invalid_tool_arguments_never_load_store_and_remain_in_band_errors(self):
        cases = [("search_memory", value) for value in (
            {}, {"query": ""}, {"query": 4}, {"query": "\ud800"}, {"query": "q" * 2049}, {"query": "q", "unknown": True},
            {"query": "q", "semantic": "true"}, {"query": "q", "top_k": True},
            {"query": "q", "top_k": 101}, {"query": "q", "top_k": None},
            {"query": "q", "layer": "invalid"}, {"query": "q", "mode": "invalid"},
            {"query": "q", "mode": "hybrid", "semantic": True}, {"query": "q", "mode": "lexical", "layer": "all"},
            {"query": "q", "scope": "project:a\nprivate"}, {"query": "q", "scope": 3},
            {"query": "q", "as_of": "2026-10-27"}, {"query": "q", "as_of": []},
            {"query": "q", "max_bytes": True}, {"query": "q", "max_bytes": 0},
            {"query": "q", "max_tokens": False}, {"query": "q", "max_tokens": "2048"},
        )]
        cases.extend(("inspect_provenance", value) for value in (
            {}, {"record_id": []}, {"record_id": "r" * 513}, {"record_id": "r", "verify": True}))
        cases.extend((("get_topic_track", {"topic_slug": "x", "top_k": False}),
                      ("get_topic_track", {"topic_slug": None}), ("memory_stats", {"extra": "secret"}),
                      ("not_a_tool", {})))
        with patch.object(self.server, "_agent") as agent, self.assertLogs(mcp.logger, level="ERROR"):
            for name, arguments in cases:
                with self.subTest(name=name, arguments=arguments):
                    response = self.server.handle(request(name, arguments))
                    result = response["result"]
                    self.assertTrue(result["isError"])
                    self.assertEqual(json.loads(result["content"][0]["text"]), result["structuredContent"])
                    self.assertEqual(result["structuredContent"]["error"]["code"], "INVALID_TOOL_ARGUMENTS")
            agent.assert_not_called()

    def test_malformed_tool_wrapper_is_rpc_invalid_params(self):
        for params in (None, [], {"arguments": {}}, {"name": 4}, {"name": ""},
                       {"name": "memory_stats", "arguments": None},
                       {"name": "memory_stats", "extra": 1}):
            with self.subTest(params=params), patch.object(self.server, "_agent") as agent:
                response = self.server.handle({"jsonrpc": "2.0", "id": 1, "method": "tools/call", "params": params})
                self.assertEqual(response["error"]["code"], -32602)
                agent.assert_not_called()

    def test_boundary_values_and_nullable_time_scope_budget_are_valid(self):
        parsed = mcp.validate_tool_arguments("search_memory", {"query": "q" * 2048, "top_k": 100,
            "mode": "hybrid", "scope": "*", "as_of": None, "max_bytes": 128, "max_tokens": None})
        self.assertEqual(parsed["top_k"], 100)
        self.assertEqual(mcp.validate_tool_arguments("inspect_provenance", {"record_id": "r" * 512})["record_id"], "r" * 512)

    def test_oversized_or_invalid_request_ids_are_not_reflected_by_server_or_proxy(self):
        for value in ("PRIVATE" * 100, "\ud800", 2**100, True):
            with self.subTest(value_type=type(value).__name__):
                message = request("memory_stats", msg_id=value)
                with patch.object(self.server, "_agent") as agent:
                    response = self.server.handle(message)
                    self.assertIsNone(response["id"])
                    self.assertEqual(response["error"]["code"], -32600)
                    agent.assert_not_called()
                output = io.StringIO()
                proxy = failover.FailoverProxy(None, [], stdout=output)
                proxy.backend = Mock()
                proxy.on_client_line(json.dumps(message))
                proxy.backend.send.assert_not_called()
                self.assertEqual(proxy.pending, {})
                self.assertIsNone(json.loads(output.getvalue())["id"])
        self.assertEqual(self.server.handle({"jsonrpc": "2.0", "id": "x" * 512, "method": "ping"})["id"], "x" * 512)

    def test_execution_errors_do_not_expose_private_exception_or_missing_record_bodies(self):
        private = "/private/source.md RAW_SECRET_SOURCE"
        with patch.object(self.server, "_agent", side_effect=RuntimeError(private)), self.assertLogs(mcp.logger, level="ERROR") as logs:
            response = self.server.handle(request("memory_stats"))
        self.assertTrue(response["result"]["isError"])
        self.assertNotIn(private, mcp.wire_json(response))
        self.assertNotIn(private, " ".join(logs.output))
        agent = Mock()
        agent.inspect_provenance.return_value = {"error": private}
        with patch.object(self.server, "_agent", return_value=agent):
            response = self.server.handle(request("inspect_provenance", {"record_id": "r"}))
        self.assertTrue(response["result"]["isError"])
        self.assertNotIn(private, mcp.wire_json(response))

    def test_opted_in_metrics_count_final_wire_without_query_or_record_ids(self):
        import sys
        fake = ModuleType("napmem_metrics")
        fake.hash_scope = Mock(return_value="scoped-digest")
        fake.record_if_enabled = Mock()
        agent = Mock()
        agent.query.return_value = {"query": "PRIVATE_QUERY", "mode": "hybrid:sparse-tfidf", "matches": [{"id": "PRIVATE_RECORD_ID", "text": "safe"}]}
        with patch.dict(sys.modules, {"napmem_metrics": fake}), patch.dict(os.environ, {"NAPMEM_METRICS": "1"}), \
                patch.object(self.server, "_agent", return_value=agent):
            response = self.server.handle(request("search_memory", {"query": "PRIVATE_QUERY", "mode": "hybrid", "scope": "project:a"}))
        fields = fake.record_if_enabled.call_args.kwargs
        self.assertEqual(fields["returned_bytes"], len(mcp.wire_json(response).encode()))
        self.assertEqual(fields["result_count"], 1)
        self.assertEqual(fields["backend"], "hybrid")
        self.assertTrue(fields["success"])
        self.assertEqual(fields["scope_hash"], "scoped-digest")
        self.assertNotIn("PRIVATE_QUERY", repr(fake.record_if_enabled.call_args))
        self.assertNotIn("PRIVATE_RECORD_ID", repr(fake.record_if_enabled.call_args))

    def test_optional_metrics_failure_does_not_change_tool_success(self):
        import sys
        fake = ModuleType("napmem_metrics")
        fake.hash_scope = lambda scope: "digest"
        fake.record_if_enabled = Mock(side_effect=OSError("synthetic metrics failure"))
        agent = Mock()
        agent.query.return_value = {"query": "q", "mode": "hybrid", "matches": []}
        with patch.dict(sys.modules, {"napmem_metrics": fake}), patch.dict(os.environ, {"NAPMEM_METRICS": "true"}), \
                patch.object(self.server, "_agent", return_value=agent):
            response = self.server.handle(request("search_memory", {"query": "q", "mode": "hybrid"}))
        self.assertFalse(response["result"]["isError"])


class TestWholeWireBudgets(unittest.TestCase):
    def test_server_and_proxy_write_actual_utf8_bytes_through_binary_stdio(self):
        class BinaryOutput:
            def __init__(self):
                self.buffer = io.BytesIO()

            def write(self, _text):
                raise AssertionError("Native protocol output must use UTF-8 bytes")

        response = {"jsonrpc": "2.0", "id": "é", "result": {"text": "😀"}}
        for emit in (lambda output: mcp.NapMemMCPServer._write(output, response),
                     lambda output: failover.FailoverProxy(None, [], stdout=output)._emit(response)):
            output = BinaryOutput()
            emit(output)
            self.assertEqual(output.buffer.getvalue(), mcp.wire_json(response).encode("utf-8"))

    @staticmethod
    def payload():
        return {"query": "escaped Unicode", "mode": "hybrid", "matches": [
            {"id": str(index), "text": ('é😀 "quoted" \\ slash\n' * 40), "scope": "project:a"}
            for index in range(20)], "profiles": [], "tracks": [], "truncated": False,
            "omitted_count": 0, "abstention": False}

    def assert_accounted(self, response, maximum, tokens=None):
        wire = mcp.wire_json(response)
        size = len(wire.encode("utf-8"))
        self.assertLessEqual(size, maximum)
        self.assertEqual(json.loads(wire), response)
        if tokens is not None:
            self.assertLessEqual(math.ceil(size / 4), tokens)
        if "result" in response:
            result = response["result"]
            self.assertEqual(json.loads(result["content"][0]["text"]), result["structuredContent"])
            self.assertEqual(result["_meta"]["napmem"]["wire_bytes"], size)
            self.assertEqual(result["_meta"]["napmem"]["estimated_tokens"], math.ceil(size / 4))

    def test_budget_counts_escaped_text_copy_unicode_id_metadata_and_newline(self):
        response = mcp.bounded_tool_result('"' * 512, self.payload(), max_bytes=5000, max_tokens=None)
        self.assert_accounted(response, 5000)
        result = response["result"]
        self.assertTrue(result["_meta"]["napmem"]["truncated"])
        self.assertLess(len(result["structuredContent"]["matches"]), 20)
        self.assertGreater(result["structuredContent"]["omitted_count"], 0)

    def test_token_budget_applies_to_whole_envelope(self):
        response = mcp.bounded_tool_result(1, self.payload(), max_bytes=10000, max_tokens=700)
        self.assert_accounted(response, 10000, 700)

    def test_tiny_metadata_budget_returns_disclosed_bounded_error_with_original_id(self):
        response = mcp.bounded_tool_result(1, self.payload(), max_bytes=128, max_tokens=32)
        self.assert_accounted(response, 128, 32)
        self.assertEqual(response["id"], 1)
        self.assertEqual(response["error"]["code"], -32001)
        self.assertIn("budget", response["error"]["message"])

    def test_impossible_budget_id_combination_is_rejected_before_dispatch_without_pending_request(self):
        rid = "x" * 512
        incoming = request("search_memory", {"query": "q", "max_bytes": 128, "max_tokens": None}, msg_id=rid)
        server = mcp.NapMemMCPServer("/unused-budget-test")
        with patch.object(server, "_agent") as agent:
            response = server.handle(incoming)
        self.assertEqual(response["id"], rid)
        self.assertEqual(response["error"]["code"], -32602)
        self.assertIn("budget", response["error"]["message"])
        agent.assert_not_called()
        output = io.StringIO()
        proxy = failover.FailoverProxy(None, [], stdout=output)
        proxy.backend = Mock()
        proxy.on_client_line(json.dumps(incoming))
        proxy.backend.send.assert_not_called()
        self.assertEqual(proxy.pending, {})
        self.assertEqual(json.loads(output.getvalue())["id"], rid)
        self.assertLess(len(output.getvalue().encode()), mcp.MAX_TOOL_BYTES)
        with self.assertRaisesRegex(ValueError, "budget"):
            mcp.bounded_tool_result(rid, self.payload(), max_bytes=128, max_tokens=None)

    def test_accepted_tiny_budget_response_clears_proxy_pending_with_same_id(self):
        incoming = request("search_memory", {"query": "q", "max_bytes": 128, "max_tokens": 32}, msg_id=7)
        output = io.StringIO()
        proxy = failover.FailoverProxy(None, [], stdout=output)
        proxy.mode, proxy.gen, proxy.backend = "remote", 1, Mock()
        proxy.on_client_line(json.dumps(incoming))
        self.assertIn(failover._id_key(7), proxy.pending)
        response = mcp.bounded_tool_result(7, self.payload(), max_bytes=128, max_tokens=32)
        proxy.on_backend_line(1, json.dumps(response))
        self.assertEqual(proxy.pending, {})
        emitted = json.loads(output.getvalue())
        self.assertEqual(emitted["id"], 7)
        self.assert_accounted(emitted, 128, 32)

    def test_invalid_direct_helper_budget_fails_clearly(self):
        for kwargs in ({"max_bytes": 1}, {"max_bytes": True}, {"max_tokens": 1}, {"max_tokens": True}):
            with self.subTest(kwargs=kwargs), self.assertRaises(ValueError):
                mcp.bounded_tool_result(1, {}, **kwargs)

    def test_fallback_note_is_last_structured_metadata_agrees_and_whole_wire_fits(self):
        output = io.StringIO()
        proxy = failover.FailoverProxy(None, [], stdout=output, note_fn=lambda: "synthetic snapshot")
        proxy.mode, proxy.gen = "local", 1
        incoming = request("search_memory", {"query": "q", "max_bytes": 3500, "max_tokens": 875}, msg_id=9)
        proxy.pending[failover._id_key(9)] = (json.dumps(incoming), "tools/call", time.monotonic())
        backend = {"jsonrpc": "2.0", "id": 9, "result": {"content": [{"type": "text", "text": "legacy"}],
                   "structuredContent": self.payload(), "isError": False}}
        with patch.object(failover, "load_snapshot", side_effect=AssertionError("custom backend must not read a mirror")):
            proxy.on_backend_line(1, json.dumps(backend))
        response = json.loads(output.getvalue())
        self.assert_accounted(response, 3500, 875)
        result = response["result"]
        self.assertEqual(result["structuredContent"]["fallback"]["mode"], "local_mirror")
        self.assertIn("[napmem fallback]", result["content"][-1]["text"])
        self.assertIn("synthetic snapshot", result["content"][-1]["text"])

    def test_proxy_enforces_budget_on_remote_result_and_rpc_error_too(self):
        for backend in (
            {"result": {"content": [{"type": "text", "text": json.dumps(self.payload())}], "isError": False}},
            {"error": {"code": -32000, "message": "x" * 10000}},
        ):
            output = io.StringIO()
            proxy = failover.FailoverProxy(None, [], stdout=output)
            proxy.mode, proxy.gen = "remote", 1
            incoming = request("search_memory", {"query": "q", "max_bytes": 1600}, msg_id=3)
            proxy.pending[failover._id_key(3)] = (json.dumps(incoming), "tools/call", time.monotonic())
            proxy.on_backend_line(1, json.dumps({"jsonrpc": "2.0", "id": 3, **backend}))
            self.assert_accounted(json.loads(output.getvalue()), 1600)

    def test_legacy_backend_private_error_bodies_are_not_forwarded(self):
        for mode in ("remote", "local"):
            for body in ({"result": {"content": [{"type": "text", "text": "Error: RAW_PRIVATE_SOURCE"}], "isError": True}},
                         {"error": {"code": -32603, "message": "RAW_PRIVATE_SOURCE"}}):
                output = io.StringIO()
                proxy = failover.FailoverProxy(None, [], stdout=output, note_fn=lambda: "synthetic snapshot")
                proxy.mode, proxy.gen = mode, 1
                incoming = request("memory_stats", msg_id=3)
                proxy.pending[failover._id_key(3)] = (json.dumps(incoming), "tools/call", time.monotonic())
                proxy.on_backend_line(1, json.dumps({"jsonrpc": "2.0", "id": 3, **body}))
                self.assertNotIn("RAW_PRIVATE_SOURCE", output.getvalue())


class TestReadOnlyToolParity(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.path = self.root / "napmem_pyramid.json"
        self.source = self.root / "source.md"
        self.source.write_text("# Editor\nI prefer Vim as my editor.\n", encoding="utf-8")
        distiller = MemoryPyramidDistiller(str(self.path))
        distiller.ingest_session("s_alpha", "Synthetic Alpha", str(self.source), self.source.read_text(), scope="project:a")
        distiller.ingest_session("s_beta", "Synthetic Beta", "napmem:test/beta", "# Editor\nI prefer Emacs as my editor.\n", scope="project:b")
        self.rid = distiller.data["memory_records"][0]["id"]
        self.server = mcp.NapMemMCPServer(str(self.path))

    def test_explicit_query_modes_match_shared_cli_api_without_wire_pruning(self):
        agent = NapMemRetrievalAgent(str(self.path))
        for mode in ("hybrid", "lexical", "semantic"):
            arguments = {"query": "preferred editor", "mode": mode, "scope": "project:a", "as_of": AS_OF,
                         "top_k": 5, "max_bytes": 65536, "max_tokens": None}
            expected = agent.query(arguments["query"], mode=mode, scope="project:a", as_of=AS_OF,
                                   top_k=5, max_bytes=65536, max_tokens=None)
            with self.subTest(mode=mode):
                response = self.server.handle(request("search_memory", arguments))
                self.assertFalse(response["result"]["isError"])
                self.assertEqual(response["result"]["structuredContent"], expected)
                self.assertEqual(json.loads(response["result"]["content"][0]["text"]), expected)

    def test_legacy_search_retains_match_map_and_semantic_flag_retains_list(self):
        plain = self.server.handle(request("search_memory", {"query": "Vim", "scope": "project:a"}))
        self.assertIsInstance(plain["result"]["structuredContent"]["matches"], dict)
        semantic = self.server.handle(request("search_memory", {"query": "Vim", "scope": "project:a", "semantic": True}))
        self.assertIsInstance(semantic["result"]["structuredContent"]["matches"], list)
        self.assertEqual(semantic["result"]["structuredContent"]["mode"], "semantic:hashed-tf")

    def test_stats_and_inspection_never_open_raw_sources_and_scope_is_safe(self):
        original_open = os.open

        def guard(path, *args, **kwargs):
            if os.fspath(path) == str(self.source):
                raise AssertionError("MCP opened a raw source")
            return original_open(path, *args, **kwargs)

        with patch("napmem_retrieval_agent.os.open", side_effect=guard):
            stats = self.server.handle(request("memory_stats", {"scope": "project:a", "as_of": AS_OF}))
            inspected = self.server.handle(request("inspect_provenance", {"record_id": self.rid, "scope": "project:a"}))
        self.assertFalse(stats["result"]["isError"])
        self.assertEqual(stats["result"]["structuredContent"]["current_records"], 1)
        self.assertEqual(stats["result"]["structuredContent"]["comparison"], "not_requested")
        self.assertFalse(inspected["result"]["isError"])
        denied = self.server.handle(request("inspect_provenance", {"record_id": self.rid, "scope": "project:b"}))
        self.assertTrue(denied["result"]["isError"])

    def test_topic_and_all_tool_success_payloads_match_text_and_required_schema_fields(self):
        calls = (("search_memory", {"query": "Vim", "scope": "project:a"}),
                 ("inspect_provenance", {"record_id": self.rid, "scope": "project:a"}),
                 ("get_topic_track", {"topic_slug": "editor", "scope": "project:a", "top_k": 1}),
                 ("memory_stats", {"scope": "project:a"}))
        for name, arguments in calls:
            with self.subTest(name=name):
                response = self.server.handle(request(name, arguments))
                result = response["result"]
                self.assertFalse(result["isError"])
                structured = result["structuredContent"]
                self.assertEqual(json.loads(result["content"][0]["text"]), structured)
                self.assertTrue(set(mcp.OUTPUT_SCHEMAS[name]["required"]) <= structured.keys())


if __name__ == "__main__":
    unittest.main()
