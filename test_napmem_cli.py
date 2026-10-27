"""Portable configuration and CLI behavior against synthetic temporary stores."""

from contextlib import redirect_stdout
from copy import deepcopy
import io
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import napmem_cli
from napmem_config import default_config_path, resolve_config, runtime_environment, user_data_dir


class IsolatedEnvironment(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.env = {"HOME": str(self.root), "NAPMEM_DATA_DIR": str(self.root / "data"),
                    "XDG_CONFIG_HOME": str(self.root / "config"), "NAPMEM_EMBED_BACKEND": "hashed"}
        self.environment = patch.dict(os.environ, self.env, clear=True)
        self.environment.start()
        self.addCleanup(self.environment.stop)
        for name in ("socket.create_connection", "urllib.request.urlopen"):
            blocker = patch(name, side_effect=AssertionError("CLI offline test attempted network access"))
            blocker.start()
            self.addCleanup(blocker.stop)


class TestConfiguration(IsolatedEnvironment):
    def test_offline_defaults_use_user_data_and_do_not_create_anything(self):
        config = resolve_config()
        self.assertEqual(config.pyramid, str(self.root / "data" / "napmem_pyramid.json"))
        self.assertEqual(config.mode, "offline")
        self.assertEqual(config.embedding_backend, "hashed")
        self.assertEqual(config.extraction, "heuristic")
        self.assertEqual(list(self.root.iterdir()), [])
        self.assertNotEqual(Path(config.pyramid).parent, Path(__file__).parent)

    def test_precedence_is_cli_then_environment_then_file_then_defaults(self):
        file = self.root / "config.toml"
        file.write_text('[napmem]\npyramid="file.json"\nscope="project:file"\nsource_roots=["sources"]\n', encoding="utf-8")
        env = {**self.env, "NAPMEM_CONFIG": str(file), "NAPMEM_PYRAMID": str(self.root / "env.json")}
        configured = resolve_config(environ=env)
        self.assertEqual(configured.pyramid, str(self.root / "env.json"))
        self.assertEqual(configured.scope, "project:file")
        self.assertEqual(configured.source_roots, (str(self.root / "sources"),))
        cli = resolve_config({"pyramid": str(self.root / "cli.json"), "scope": "project:cli"}, environ=env)
        self.assertEqual(cli.pyramid, str(self.root / "cli.json"))
        self.assertEqual(cli.scope, "project:cli")
        self.assertEqual(cli.origins["pyramid"], "cli")
        self.assertEqual(cli.origins["source_roots"], "file")

    def test_environment_source_roots_and_explicit_all_scope_are_supported(self):
        config = resolve_config(environ={**self.env, "NAPMEM_SOURCE_ROOTS": os.pathsep.join((str(self.root), str(self.root / "other"))),
                                         "NAPMEM_SCOPE": "*"})
        self.assertEqual(config.scope, "*")
        self.assertEqual(len(config.source_roots), 2)

    def test_runtime_environment_is_reversible(self):
        config = resolve_config({"mode": "local", "ollama_url": "http://offline.invalid:11434", "ollama_model": "fixture"})
        before = dict(os.environ)
        with runtime_environment(config):
            self.assertEqual(os.environ["NAPMEM_OLLAMA_URL"], config.ollama_url)
            self.assertEqual(os.environ["NAPMEM_OLLAMA_MODEL"], "fixture")
        self.assertEqual(dict(os.environ), before)

    def test_invalid_config_and_accidental_online_selection_fail_before_runtime(self):
        for fields in ({"mode": "invalid"}, {"embedding_backend": "ollama"}, {"extraction": "anthropic"},
                       {"source_roots": "not-an-array"}, {"scope": "project:a\nsecret"},
                       {"ollama_url": "https://user:secret@example.invalid"}):
            with self.subTest(fields=fields), self.assertRaises(ValueError):
                resolve_config(fields)
        file = self.root / "invalid.toml"
        file.write_text('unknown_setting="value"\n', encoding="utf-8")
        with self.assertRaises(ValueError):
            resolve_config({"config": str(file)})
        with self.assertRaisesRegex(ValueError, "does not exist"):
            resolve_config({"config": str(self.root / "absent.toml")})

    def test_portable_xdg_paths_are_absolute(self):
        env = {"HOME": str(self.root), "XDG_DATA_HOME": str(self.root / "xdg-data"),
               "XDG_CONFIG_HOME": str(self.root / "xdg-config")}
        self.assertEqual(user_data_dir(env), self.root / "xdg-data" / "napmem")
        self.assertEqual(default_config_path(env), self.root / "xdg-config" / "napmem" / "config.toml")


class TestCli(IsolatedEnvironment):
    def setUp(self):
        super().setUp()
        self.store = self.root / "store.json"
        self.source = self.root / "notes.md"
        self.source.write_text("# Editor\nI prefer Vim as my editor for Alpha.\n", encoding="utf-8")

    def run_cli(self, *arguments, code=0):
        output = io.StringIO()
        with redirect_stdout(output):
            actual = napmem_cli.main(["--pyramid", str(self.store), *map(str, arguments)])
        self.assertEqual(actual, code, output.getvalue())
        lines = output.getvalue().splitlines()
        self.assertEqual(len(lines), 1, output.getvalue())
        return json.loads(lines[0])

    def ingest(self):
        return self.run_cli("ingest", self.source, "--scope", "project:a")

    def query(self):
        return self.run_cli("query", "Vim editor", "--scope", "project:a")

    def test_init_is_idempotent_and_common_flags_work_after_command(self):
        result = self.run_cli("init")
        self.assertTrue(result["created"])
        before = self.store.read_bytes()
        self.assertFalse(self.run_cli("init")["created"])
        self.assertEqual(self.store.read_bytes(), before)
        output = io.StringIO()
        with redirect_stdout(output):
            code = napmem_cli.main(["init", "--pyramid", str(self.root / "second.json")])
        self.assertEqual(code, 0)
        self.assertTrue((self.root / "second.json").is_file())

    def test_version_uses_installed_metadata_with_source_fallback(self):
        from importlib.metadata import PackageNotFoundError
        for result, error, expected in (("9.8.7", None, "9.8.7"), (None, PackageNotFoundError(), "0.2.0")):
            output = io.StringIO()
            with patch("importlib.metadata.version", return_value=result, side_effect=error), redirect_stdout(output):
                with self.assertRaises(SystemExit) as exit_result:
                    napmem_cli.main(["--version"])
            self.assertEqual(exit_result.exception.code, 0)
            self.assertEqual(output.getvalue().strip(), expected)

    def test_ingest_query_and_inspect_share_scope_and_evidence_contract(self):
        receipt = self.ingest()
        self.assertGreater(receipt["ingested"], 0)
        result = self.query()
        self.assertTrue(result["matches"])
        row = result["matches"][0]
        self.assertEqual(row["scope"], "project:a")
        inspected = self.run_cli("inspect", row["id"], "--scope", "project:a")
        self.assertEqual(inspected["record_id"], row["id"])
        self.assertEqual(inspected["evidence"]["status"], "verified")
        self.assertEqual(inspected["verification"]["status"], "not_rechecked")
        other = self.run_cli("query", "Vim editor", "--scope", "project:b")
        self.assertEqual(other["matches"], [])

    def test_query_honors_explicit_byte_budget(self):
        self.ingest()
        result = self.run_cli("query", "Vim editor", "--scope", "project:a", "--max-bytes", "1024")
        self.assertLessEqual(len(json.dumps(result, ensure_ascii=False, separators=(",", ":")).encode()), 1024)

    def test_default_doctor_creates_no_store_lock_queue_or_directory_and_does_not_probe(self):
        before = set(self.root.rglob("*"))
        result = self.run_cli("doctor")
        self.assertTrue(result["ok"])
        self.assertFalse(result["probed"])
        self.assertFalse(result["store"]["exists"])
        self.assertEqual(set(self.root.rglob("*")), before)
        self.assertFalse(self.store.exists())
        self.run_cli("doctor", "--probe", code=2)

    def test_doctor_handles_an_unavailable_optional_client_without_importing_it(self):
        with patch("napmem_cli.importlib.util.find_spec", side_effect=ModuleNotFoundError("optional package absent")):
            result = self.run_cli("doctor")
        self.assertEqual(result["optional_dependencies"], {"anthropic": False, "ollama_client": False})

    def test_doctor_reads_existing_store_without_changing_canonical_bytes(self):
        self.ingest()
        before = self.store.read_bytes()
        result = self.run_cli("doctor")
        self.assertTrue(result["store"]["valid"])
        self.assertEqual(self.store.read_bytes(), before)

    def test_demo_is_synthetic_scoped_and_preserves_an_existing_other_session(self):
        self.ingest()
        result = self.run_cli("demo")
        self.assertTrue(result["synthetic"])
        self.assertEqual(result["query"]["scope"], "project:napmem-demo-alpha")
        self.assertFalse(result["query"]["abstention"])
        self.assertEqual(len(result["query"]["matches"]), 1)
        self.assertTrue(self.query()["matches"])

    def test_inspector_and_explicit_diff_share_the_cli_without_mutating_store(self):
        self.run_cli("demo")
        before = self.store.read_bytes()
        result = self.run_cli("inspect", "--view", "review", "--scope", "project:napmem-demo-alpha")
        self.assertEqual(result["view"], "review")
        self.assertTrue(result["records"])
        old, new = self.root / "before.md", self.root / "after.md"
        old.write_text("Use Vim\n")
        new.write_text("Use Emacs\n")
        diff = self.run_cli("diff", str(old), str(new))
        self.assertIn("-Use Vim", diff["records"][0]["diff"])
        self.assertEqual(self.store.read_bytes(), before)

    def test_control_preview_is_read_only_and_apply_persists(self):
        self.ingest()
        rid = self.query()["matches"][0]["id"]
        before = self.store.read_bytes()
        preview = self.run_cli("control", "pin", "--record-id", rid, "--dry-run")
        self.assertEqual(self.store.read_bytes(), before)
        result = self.run_cli("control", "pin", "--record-id", rid, "--preview-token", preview["preview_token"])
        self.assertIn(rid, result["affected_ids"])
        self.assertTrue(self.query()["matches"][0]["pinned"])

    def test_opt_in_metrics_feedback_status_and_forget_do_not_store_personal_text(self):
        from napmem_metrics import MetricsStore
        self.ingest()
        self.assertFalse(Path(str(self.store) + ".metrics.json").exists())
        result = self.run_cli("query", "Vim editor", "--scope", "project:a", "--metrics")
        rid = result["matches"][0]["id"]
        metrics = MetricsStore(str(self.store))
        self.assertEqual(metrics.summarize()["event_counts"]["retrieval"], 1)
        self.run_cli("feedback", rid, "useful", "--scope", "project:a")
        encoded = Path(metrics.path).read_text()
        self.assertNotIn("Vim", encoded)
        self.assertNotIn(rid, encoded)
        before = Path(metrics.path).read_bytes()
        report = self.run_cli("status", "--scope", "project:a")
        self.assertIn("metrics", report)
        self.assertEqual(Path(metrics.path).read_bytes(), before)
        self.run_cli("control", "forget", "--record-id", rid)
        self.assertEqual(metrics.summarize()["feedback"]["count"], 0)

    def test_portable_adapter_export_and_import_use_the_same_cli(self):
        self.ingest()
        exported = self.run_cli("export", "--scope", "project:a")
        self.assertEqual(exported["format"], "napmem-portable")
        source = self.root / "exported.json"
        source.write_text(json.dumps(exported))
        receipt = self.run_cli("ingest", str(source), "--format", "portable", "--scope", "project:b")
        self.assertEqual(receipt["status"], "ingested")
        matches = self.run_cli("query", "Vim editor", "--scope", "project:b")["matches"]
        self.assertTrue(matches)
        self.assertTrue(all(row["review_status"] == "unreviewed" for row in matches))

    def test_excluded_source_is_not_opened_again(self):
        self.run_cli("init")
        self.run_cli("control", "exclude", "--source", self.source)
        with patch("napmem_sources.read_source", side_effect=AssertionError("excluded source opened")):
            result = self.run_cli("ingest", self.source)
        self.assertEqual(result["status"], "excluded")

    def test_ingest_rechecks_source_revision_after_extraction_before_commit(self):
        from memory_pyramid_distiller import MemoryPyramidDistiller
        extract = MemoryPyramidDistiller.extract_atomic_units

        def extract_then_change(distiller, *arguments):
            records = extract(distiller, *arguments)
            self.source.write_text("I prefer a changed editor.\n", encoding="utf-8")
            return records

        with patch.object(MemoryPyramidDistiller, "extract_atomic_units", extract_then_change):
            result = self.ingest()
        self.assertEqual(result["status"], "stale")
        self.assertEqual(result["reason"], "source_changed_or_unavailable")
        self.assertFalse(self.store.exists())

    def test_ingest_reloads_operator_exclusions_after_extraction(self):
        from memory_pyramid_distiller import MemoryPyramidDistiller
        extract = MemoryPyramidDistiller.extract_atomic_units

        def extract_then_exclude(distiller, *arguments):
            records = extract(distiller, *arguments)
            MemoryPyramidDistiller(str(self.store)).control("exclude", source=str(self.source))
            return records

        with patch.object(MemoryPyramidDistiller, "extract_atomic_units", extract_then_exclude):
            result = self.ingest()
        self.assertEqual(result["status"], "excluded")
        self.assertEqual(json.loads(self.store.read_text())["memory_records"], [])

    def test_durable_job_enqueue_run_commit_and_inspection(self):
        job = self.run_cli("jobs", "enqueue", self.source, "--scope", "project:a")
        listed = self.run_cli("jobs", "list")["jobs"]
        self.assertEqual(listed[0]["id"], job["id"])
        self.assertNotIn("source_text", listed[0])
        ready = self.run_cli("jobs", "run")
        self.assertEqual(ready["jobs"][0]["state"], "ready")
        committed = self.run_cli("jobs", "commit", job["id"])
        self.assertEqual(committed["jobs"][0]["state"], "committed")
        self.assertTrue(self.query()["matches"])
        self.assertEqual(self.run_cli("jobs", "get", job["id"])["job"]["state"], "committed")

    def test_job_cancel_retry_and_offline_submit_guard(self):
        job = self.run_cli("jobs", "enqueue", self.source)
        self.assertEqual(self.run_cli("jobs", "cancel", job["id"])["state"], "cancelled")
        self.assertEqual(self.run_cli("jobs", "retry", job["id"], self.source)["state"], "queued")
        self.run_cli("jobs", "submit", code=2)

    def test_snapshot_export_and_restore_use_verified_api(self):
        self.ingest()
        destination = self.root / "snapshot"
        manifest = self.run_cli("snapshot", "export", destination, "--without-cache")
        self.assertEqual(manifest["cache"]["status"], "absent")
        self.source.write_text("# Editor\nI prefer Emacs as my editor for Alpha.\n", encoding="utf-8")
        self.ingest()
        restored = self.run_cli("snapshot", "restore", destination)
        self.assertIsInstance(restored, dict)
        self.assertTrue(self.query()["matches"])

    def test_eval_dispatch_is_offline_and_outputs_summary_without_touching_store(self):
        report = {"mode": "hybrid", "split": "heldout", "metrics": {"protected_pass_rate": 1}}
        with patch("napmem_eval.evaluate", return_value=deepcopy(report)) as evaluate:
            result = self.run_cli("eval")
        self.assertEqual(result["metrics"], report["metrics"])
        self.assertEqual(evaluate.call_args.args, ("hybrid", "heldout"))
        self.assertFalse(self.store.exists())


if __name__ == "__main__":
    unittest.main()
