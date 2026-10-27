"""Offline core acceptance with the optional Ollama package made unimportable."""

import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import textwrap
import tomllib
import unittest


ROOT = Path(__file__).resolve().parent


class TestOptionalOllamaClient(unittest.TestCase):
    def run_without_client(self, body):
        # -I excludes the caller's Python path. The module sentinel also blocks a shared
        # client installed in the project venv, making this a true absence test.
        script = textwrap.dedent("""\
            import json
            import os
            from pathlib import Path
            import socket
            import sys
            import tempfile
            import urllib.request

            def forbidden_network(*args, **kwargs):
                raise AssertionError("offline core attempted a network request")

            sys.modules["ollama_client"] = None
            socket.socket.connect = forbidden_network
            socket.create_connection = forbidden_network
            urllib.request.urlopen = forbidden_network
            """)
        script += f"\nsys.path.insert(0, {str(ROOT)!r})\n"
        script += textwrap.dedent(body)
        with tempfile.TemporaryDirectory(prefix="napmem_optional_cwd_") as directory:
            completed = subprocess.run(
                [sys.executable, "-I", "-c", script], cwd=directory,
                env={**os.environ, "NAPMEM_EMBED_BACKEND": "hashed"},
                capture_output=True, text=True, timeout=30,
            )
        self.assertEqual(completed.returncode, 0, completed.stdout + completed.stderr)
        return json.loads(completed.stdout)

    def test_auto_backend_uses_stdlib_vectors_without_optional_client(self):
        result = self.run_without_client("""\
            import semantic_index
            os.environ.pop("NAPMEM_EMBED_BACKEND", None)
            backend = semantic_index.select_backend()
            assert isinstance(backend, semantic_index.HashedTfBackend)
            vectors = backend.embed(["offline memory", "offline memory", "unrelated"])
            assert abs(semantic_index.cosine(vectors[0], vectors[1]) - 1.0) < 1e-9
            assert semantic_index.cosine(vectors[0], vectors[2]) < 0.5
            assert semantic_index.cosine([0.0], [0.0]) == 0.0
            assert semantic_index.OllamaBackend.probe() is None
            print(json.dumps({"backend": backend.name}))
            """)
        self.assertEqual(result["backend"], "hashed-tf")

    def test_explicit_ollama_paths_explain_optional_installation(self):
        result = self.run_without_client("""\
            import ollama_extractor
            import semantic_index
            os.environ["NAPMEM_EMBED_BACKEND"] = "ollama"
            errors = []
            for operation in (
                semantic_index.select_backend,
                lambda: semantic_index.OllamaBackend("http://unused.invalid"),
                lambda: ollama_extractor.extract_ollama({"session": "prompt"}),
            ):
                try:
                    operation()
                except (RuntimeError, ollama_extractor.OllamaExtractionError) as error:
                    assert "llm-memory-pyramid[ollama]" in str(error), str(error)
                    errors.append(str(error))
                else:
                    raise AssertionError("explicit Ollama request silently succeeded")
            assert ollama_extractor.ollama_available() is False
            print(json.dumps({"errors": len(errors)}))
            """)
        self.assertEqual(result["errors"], 3)

    def test_heuristic_ingestion_and_query_need_no_optional_client(self):
        result = self.run_without_client("""\
            from memory_pyramid_distiller import MemoryPyramidDistiller
            from napmem_retrieval_agent import NapMemRetrievalAgent
            with tempfile.TemporaryDirectory(prefix="napmem_optional_core_") as directory:
                source = Path(directory) / "source.md"
                content = "# Offline preference\\n- User prefers cobalt editor themes.\\n"
                source.write_text(content, encoding="utf-8")
                store = Path(directory) / "store.json"
                distiller = MemoryPyramidDistiller(str(store))
                count = distiller.ingest_session("offline", "Offline fixture", str(source),
                                                content, scope="offline-fixture")
                assert count > 0
                response = NapMemRetrievalAgent(str(store)).query(
                    "cobalt editor themes", scope="offline-fixture")
                assert response["matches"], response
                assert all(record["scope"] == "offline-fixture" for record in response["matches"])
                assert sys.modules.get("ollama_client") is None
                print(json.dumps({"matches": len(response["matches"])}))
            """)
        self.assertGreater(result["matches"], 0)

    def test_cli_init_ingest_query_and_doctor_work_without_optional_client(self):
        result = self.run_without_client("""\
            import contextlib
            import io
            import napmem_cli
            with tempfile.TemporaryDirectory(prefix="napmem_optional_cli_") as directory:
                store = Path(directory) / "store.json"
                source = Path(directory) / "source.md"
                source.write_text("# Offline preference\\n- User prefers cobalt editor themes.\\n",
                                  encoding="utf-8")
                def invoke(*arguments):
                    output = io.StringIO()
                    with contextlib.redirect_stdout(output):
                        status = napmem_cli.main(["--pyramid", str(store), *arguments])
                    assert status == 0, (status, output.getvalue())
                    return json.loads(output.getvalue())
                invoke("init")
                invoke("ingest", str(source), "--scope", "offline-fixture")
                response = invoke("query", "cobalt editor themes", "--scope", "offline-fixture")
                assert response["matches"], response
                doctor = invoke("doctor")
                assert isinstance(doctor, dict)
                assert sys.modules.get("ollama_client") is None
                print(json.dumps({"matches": len(response["matches"]), "doctor": True}))
            """)
        self.assertGreater(result["matches"], 0)
        self.assertTrue(result["doctor"])

    def test_distribution_declares_offline_core_and_canonical_fixture(self):
        config = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
        self.assertEqual(config["project"]["dependencies"], [])
        ollama = config["project"]["optional-dependencies"]["ollama"]
        self.assertEqual(len(ollama), 1)
        self.assertIn("ollama-client @ git+https://github.com/mithudso/ollama-client@", ollama[0])
        self.assertEqual(config["project"]["scripts"]["napmem"], "napmem_cli:main")
        runtime = set(config["tool"]["setuptools"]["py-modules"])
        self.assertTrue({"napmem_storage", "napmem_jobs", "napmem_sources", "napmem_snapshots",
                         "napmem_config", "napmem_cli"} <= runtime)
        self.assertIn("evaluations/memory_quality_v1.json",
                      config["tool"]["setuptools"]["data-files"]["share/napmem/evaluations"])


if __name__ == "__main__":
    unittest.main()
