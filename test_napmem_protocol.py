"""Offline regressions for the stdlib MCP protocol boundary."""

import io
import json
import sys
import unittest
from unittest import mock

import napmem_mcp_server as mcp
import napmem_mcp_failover as failover


class TestProtocolBoundary(unittest.TestCase):
    def setUp(self):
        # Protocol tests must not touch a store or select an embedding backend.
        self.server = mcp.NapMemMCPServer("/unused-protocol-test-store")

    def _serve(self, text):
        out = io.StringIO()
        self.server.serve(io.StringIO(text), out)
        return [json.loads(line) for line in out.getvalue().splitlines()]

    def test_decoder_failures_do_not_drop_following_requests(self):
        previous = sys.get_int_max_str_digits()
        self.addCleanup(sys.set_int_max_str_digits, previous)
        sys.set_int_max_str_digits(4300)
        invalid = '{"jsonrpc":"2.0","id":' + "9" * 5000 + ',"method":"ping"}\n'
        nested = "[" * 20000 + "]" * 20000 + "\n"
        ping = json.dumps({"jsonrpc": "2.0", "id": 7, "method": "ping"}) + "\n"
        with self.assertLogs(mcp.logger, level="WARNING"):
            messages = self._serve(invalid + nested + ping)
        self.assertEqual(messages[0]["error"]["code"], -32700)
        # Decoder depth limits differ across supported Python versions. A
        # decoded array is Invalid Request; a decoder refusal is Parse error.
        self.assertIn(messages[1]["error"]["code"], (-32700, -32600))
        self.assertEqual(messages[2], {"jsonrpc": "2.0", "id": 7, "result": {}})

    def test_notifications_never_call_tools_or_produce_responses(self):
        with mock.patch.object(self.server, "call_tool") as call:
            for method in ("initialize", "ping", "tools/list", "tools/call",
                           "notifications/initialized", "unknown"):
                with self.subTest(method=method):
                    response = self.server.handle({"jsonrpc": "2.0", "method": method,
                                                   "params": {"name": "memory_stats"}})
                    self.assertIsNone(response)
            call.assert_not_called()

    def test_invalid_envelopes_return_valid_error_ids(self):
        for message in (
            {"id": 1, "method": "ping"},
            {"jsonrpc": "1.0", "id": 1, "method": "ping"},
            {"jsonrpc": "2.0", "id": {}, "method": "ping"},
            {"jsonrpc": "2.0", "id": [], "method": "ping"},
            {"jsonrpc": "2.0", "id": True, "method": "ping"},
            {"jsonrpc": "2.0", "id": 1.5, "method": "ping"},
            {"jsonrpc": "2.0", "id": None, "method": "ping"},
        ):
            with self.subTest(message=message):
                response = self.server.handle(message)
                self.assertEqual(response["error"]["code"], -32600)
                self.assertIn(type(response["id"]), (str, int, type(None)))

    def test_invalid_params_are_rejected(self):
        for params in ([], "bad", 4, None):
            with self.subTest(params=params):
                response = self.server.handle({"jsonrpc": "2.0", "id": 1,
                                               "method": "ping", "params": params})
                self.assertEqual(response["error"]["code"], -32602)

    def test_oversized_lines_are_read_in_bounded_chunks_and_drained(self):
        class BoundedInput(io.StringIO):
            def __iter__(self):
                raise AssertionError("Iteration reads an unbounded line")

            def readline(self, size=-1):
                if not 0 < size <= 129:
                    raise AssertionError(f"Unbounded readline: {size}")
                return super().readline(size)

        out = io.StringIO()
        text = "x" * 1024 + "\n" + '{"jsonrpc":"2.0","id":2,"method":"ping"}\n'
        with mock.patch.object(mcp, "MAX_LINE_BYTES", 128), \
                self.assertLogs(mcp.logger, level="WARNING"):
            self.server.serve(BoundedInput(text), out)
        messages = [json.loads(line) for line in out.getvalue().splitlines()]
        self.assertEqual(len(messages), 2)
        self.assertEqual(messages[0]["error"]["code"], -32700)
        self.assertEqual(messages[1]["id"], 2)

    def test_line_limit_counts_utf8_bytes_and_invalid_utf8_survives(self):
        out = io.StringIO()
        oversized = json.dumps({"jsonrpc": "2.0", "id": 1, "method": "ping",
                                "params": {"text": "é" * 50}}, ensure_ascii=False)
        self.assertLess(len(oversized), 160)
        raw = oversized.encode() + b'\n\xff\n{"jsonrpc":"2.0","id":2,"method":"ping"}\n'
        with mock.patch.object(mcp, "MAX_LINE_BYTES", 160), \
                self.assertLogs(mcp.logger, level="WARNING"):
            self.server.serve(io.BytesIO(raw), out)
        messages = [json.loads(line) for line in out.getvalue().splitlines()]
        self.assertEqual([message.get("id") for message in messages], [None, None, 2])
        self.assertEqual([message["error"]["code"] for message in messages[:2]],
                         [-32700, -32700])

    def test_bad_top_k_never_loads_a_store(self):
        with mock.patch.object(self.server, "_agent") as agent:
            for top_k in (0, -1, True, False, "2", 2.5, None):
                with self.subTest(top_k=top_k):
                    with self.assertLogs(mcp.logger, level="ERROR"):
                        response = self.server.handle({
                            "jsonrpc": "2.0", "id": 1, "method": "tools/call",
                            "params": {"name": "search_memory", "arguments": {
                                "query": "test", "semantic": True, "top_k": top_k}},
                        })
                    self.assertTrue(response["result"]["isError"])
            agent.assert_not_called()
        schema = mcp.TOOLS[0]["inputSchema"]["properties"]["top_k"]
        self.assertEqual(schema["minimum"], 1)

    def test_proxy_rejects_invalid_ids_without_pending_or_forwarding(self):
        for invalid_id in (False, True, None, 1.5, [], {}, {"key": "value"}):
            with self.subTest(id_type=type(invalid_id).__name__):
                out = io.StringIO()
                proxy = failover.FailoverProxy(None, [], stdout=out)
                proxy.backend = mock.Mock()
                proxy.on_client_line(json.dumps({"jsonrpc": "2.0", "id": invalid_id,
                                                 "method": "ping"}))
                self.assertEqual(proxy.pending, {})
                proxy.backend.send.assert_not_called()
                response = json.loads(out.getvalue())
                self.assertIsNone(response["id"])
                self.assertEqual(response["error"]["code"], -32600)

    def test_broken_output_pipe_on_parse_error_shuts_down(self):
        class BrokenOutput:
            def write(self, _text):
                raise BrokenPipeError("closed test client")

        with self.assertLogs(mcp.logger, level="INFO"):
            self.server.serve(io.StringIO("invalid\n"), BrokenOutput())


if __name__ == "__main__":
    unittest.main()
