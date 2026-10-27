"""Actual offline CLI/MCP loop from scoped sources through correction and restore."""
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest


class TrustedLoopTests(unittest.TestCase):
    def test_changed_json_revision_cannot_reintroduce_forgotten_text_in_an_unverified_quote(self):
        from memory_pyramid_distiller import MemoryPyramidDistiller
        from napmem_adapters import ingest_source
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "source.json"
            store = MemoryPyramidDistiller(str(Path(directory) / "store.json"))
            secret = "PRIVATE_ASSERTION_TO_FORGET"
            data = {"records": [{"text": secret}, {"text": "Public text\nwith an escaped newline"}]}
            source.write_text(json.dumps(data))
            ingest_source(store, source, format="portable")
            identity = next(row["id"] for row in store.data["memory_records"] if row["text"] == secret)
            store.control("forget", record_id=identity)
            data["format"] = "napmem-portable"
            source.write_text(json.dumps(data))
            ingest_source(store, source, format="portable")
            self.assertNotIn(secret, json.dumps(store.data))

    def test_installed_surface_contract_from_ingest_to_forget_and_restore(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            store, config = root / "store.json", root / "config.toml"
            config.write_text("[napmem]\nmode='offline'\n")
            env = {**os.environ, "NAPMEM_EMBED_BACKEND": "hashed", "NAPMEM_METRICS": "0"}
            base = [sys.executable, "-m", "napmem_cli", "--config", str(config), "--pyramid", str(store)]

            def cli(*arguments):
                result = subprocess.run([*base, *arguments], env=env, capture_output=True, text=True, timeout=10)
                self.assertEqual(result.returncode, 0, result.stderr + result.stdout)
                return json.loads(result.stdout)

            def rpc(query, scope):
                message = {"jsonrpc": "2.0", "id": "contract", "method": "tools/call", "params": {
                    "name": "search_memory", "arguments": {"query": query, "mode": "hybrid", "scope": scope,
                                                             "max_bytes": 16384, "max_tokens": 4096}}}
                result = subprocess.run([*base, "mcp"], input=json.dumps(message) + "\n", env=env,
                                        capture_output=True, text=True, timeout=10)
                self.assertEqual(result.returncode, 0, result.stderr)
                wire = json.loads(result.stdout)
                self.assertFalse(wire["result"]["isError"])
                data = wire["result"]["structuredContent"]
                self.assertEqual(data, json.loads(wire["result"]["content"][0]["text"]))
                return data

            for name, editor in (("a", "Vim"), ("b", "Emacs")):
                source = root / (name + ".md")
                source.write_text(f"# Editor\nI prefer {editor} as my editor.\n")
                cli("ingest", str(source), "--scope", "project:" + name)
            initial = cli("query", "favorite editor", "--scope", "project:a")
            self.assertEqual(len(initial["matches"]), 1)
            self.assertIn("Vim", initial["matches"][0]["text"])
            (root / "a.md").write_text("# Editor\nI prefer Nano as my editor.\n")
            cli("ingest", str(root / "a.md"), "--scope", "project:a")
            updated = cli("query", "favorite editor", "--scope", "project:a")
            self.assertIn("Nano", updated["matches"][0]["text"])
            cli("control", "correct", "--record-id", updated["matches"][0]["id"],
                "--value", "I prefer Helix as my editor.")
            cli("ingest", str(root / "a.md"), "--scope", "project:a")
            corrected = cli("query", "favorite editor", "--scope", "project:a")
            self.assertEqual([row["id"] for row in corrected["matches"]],
                             [row["id"] for row in rpc("favorite editor", "project:a")["matches"]])
            self.assertIn("Helix", corrected["matches"][0]["text"])
            old_snapshot = root / "before-forget"
            cli("snapshot", "export", str(old_snapshot))
            cli("control", "forget", "--record-id", corrected["matches"][0]["id"])
            cli("snapshot", "restore", str(old_snapshot))
            cli("ingest", str(root / "a.md"), "--scope", "project:a")
            self.assertEqual(rpc("favorite editor", "project:a")["matches"], [])
            self.assertIn("Emacs", rpc("favorite editor", "project:b")["matches"][0]["text"])
            snapshot = root / "after-forget"
            cli("snapshot", "export", str(snapshot))
            from napmem_retrieval_agent import NapMemRetrievalAgent
            from napmem_snapshots import load_snapshot
            before = {p.name: p.read_bytes() for p in snapshot.iterdir()}
            agent = NapMemRetrievalAgent(str(snapshot / "napmem_pyramid.json"))
            self.assertEqual(agent.query("favorite editor", scope="project:a")["matches"], [])
            self.assertEqual(load_snapshot(snapshot)["verification"]["status"], "verified")
            self.assertEqual(before, {p.name: p.read_bytes() for p in snapshot.iterdir()})


if __name__ == "__main__":
    unittest.main()
