"""Offline snapshot, checksum and atomic mirror generation tests."""

from contextlib import contextmanager
from copy import deepcopy
import hashlib
import io
import json
from pathlib import Path
import tarfile
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

import napmem_snapshots as snapshots
from napmem_storage import store_lock


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def data(generation=4):
    return {"version": "2.0.0", "generation": generation, "memory_records": [
        {"id": "rec_one", "text": "A synthetic snapshot fact.", "scope": "project:test"}]}


def cache(generation=None):
    result = {"model": "fixture-2d", "vectors": {
        "rec_one": {"key": sha(b"A synthetic snapshot fact.")[:16], "vec": [1.0, 0.0]}}}
    if generation is not None:
        result["generation"] = generation
    return result


class TestSnapshots(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.source = self.root / "custom.json"
        self.source.write_text(json.dumps(data(), indent=3) + "\n", encoding="utf-8")
        self.destination = self.root / "snapshot"

    def write_cache(self, value):
        Path(str(self.source) + ".embindex.json").write_text(json.dumps(value), encoding="utf-8")

    def export(self, **kwargs):
        return snapshots.export_snapshot(self.source, self.destination, **kwargs)

    def change_manifest(self, change):
        path = self.destination / snapshots.MANIFEST_FILE
        manifest = json.loads(path.read_text(encoding="utf-8"))
        change(manifest)
        path.write_text(json.dumps(manifest), encoding="utf-8")

    def test_export_preserves_exact_canonical_bytes_and_normalizes_only_returned_copy(self):
        before = self.source.read_bytes()
        stamp = self.source.stat().st_mtime_ns
        manifest = self.export()
        self.assertEqual(self.source.read_bytes(), before)
        self.assertEqual(self.source.stat().st_mtime_ns, stamp)
        self.assertEqual((self.destination / snapshots.STORE_FILE).read_bytes(), before)
        self.assertEqual(manifest["store"]["sha256"], sha(before))
        self.assertEqual(manifest["generation"], 4)
        checked = snapshots.load_snapshot(self.destination)
        self.assertEqual(checked["data"]["version"], "2.0.0")
        self.assertEqual(checked["verification"], {"status": "verified", "generation": "verified",
                                                    "store": "sha256", "cache": "absent"})
        checked["data"]["memory_records"][0]["text"] = "local edit"
        self.assertEqual(self.source.read_bytes(), before)

    def test_export_reads_store_and_cache_under_one_reentrant_canonical_lock(self):
        self.write_cache(cache())
        active, reads = [], []
        real_read = snapshots._read

        @contextmanager
        def tracked_lock(path, **kwargs):
            with store_lock(path, **kwargs):
                active.append(str(path))
                try:
                    yield
                finally:
                    active.pop()

        def tracked_read(path, *args):
            if str(path).startswith(str(self.source)):
                reads.append(str(path))
                self.assertIn(str(self.source), active)
            return real_read(path, *args)

        with patch("napmem_storage.store_lock", side_effect=tracked_lock), \
                patch.object(snapshots, "_read", side_effect=tracked_read), store_lock(self.source):
            self.export()
        self.assertEqual(len(reads), 2)

    def test_legacy_cache_discloses_record_hash_provenance_without_generation_claim(self):
        self.write_cache(cache())
        manifest = self.export()
        self.assertEqual(manifest["cache"]["provenance"], "record-text-hashes-only")
        self.assertIsNone(manifest["cache"]["generation"])
        self.assertEqual(manifest["embedding"]["model"], "fixture-2d")
        checked = snapshots.load_snapshot(self.destination)
        self.assertEqual(checked["cache"], cache())
        self.assertEqual(checked["verification"]["cache"], "record-text-hashes-only")

    def test_explicit_cache_generation_is_bound_and_mismatch_is_omitted(self):
        self.write_cache(cache(4))
        self.assertEqual(self.export()["cache"]["provenance"], "generation-bound")
        self.destination = self.root / "without-stale-cache"
        self.write_cache(cache(3))
        manifest = self.export()
        self.assertEqual(manifest["cache"]["status"], "absent")
        self.assertEqual(manifest["cache"]["absence_reason"], "invalid_or_stale_cache")
        self.assertFalse((self.destination / snapshots.CACHE_FILE).exists())

    def test_disabled_and_invalid_cache_are_absent(self):
        self.write_cache(cache())
        self.assertEqual(self.export(include_cache=False)["cache"]["absence_reason"], "disabled")
        self.destination = self.root / "invalid-cache"
        invalid = cache()
        invalid["vectors"]["rec_one"]["key"] = "wrong"
        self.write_cache(invalid)
        self.assertEqual(self.export()["cache"]["status"], "absent")

    def test_changed_store_bytes_and_manifest_generation_are_rejected(self):
        self.export()
        (self.destination / snapshots.STORE_FILE).write_text(json.dumps(data(5)), encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "generation"):
            snapshots.load_snapshot(self.destination)
        (self.destination / snapshots.STORE_FILE).write_bytes(self.source.read_bytes() + b" ")
        with self.assertRaisesRegex(ValueError, "checksum"):
            snapshots.load_snapshot(self.destination)
        (self.destination / snapshots.STORE_FILE).write_bytes(self.source.read_bytes())
        self.change_manifest(lambda manifest: manifest.update(generation=True))
        with self.assertRaisesRegex(ValueError, "generation"):
            snapshots.load_snapshot(self.destination)

    def test_changed_cache_bytes_and_forged_cache_provenance_are_rejected(self):
        self.write_cache(cache())
        self.export()
        path = self.destination / snapshots.CACHE_FILE
        before = path.read_bytes()
        path.write_bytes(before + b" ")
        with self.assertRaisesRegex(ValueError, "checksum"):
            snapshots.load_snapshot(self.destination)
        path.write_bytes(before)
        self.change_manifest(lambda manifest: manifest["cache"].update(provenance="generation-bound"))
        with self.assertRaisesRegex(ValueError, "provenance"):
            snapshots.load_snapshot(self.destination)

    def test_absent_cache_declaration_refuses_leftover_cache(self):
        self.export()
        (self.destination / snapshots.CACHE_FILE).write_text(json.dumps(cache()), encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "absent cache"):
            snapshots.load_snapshot(self.destination)

    def test_invalid_store_or_nonempty_destination_cannot_publish_partial_export(self):
        self.source.write_text('{"memory_records": ["invalid"]}', encoding="utf-8")
        with self.assertRaises(ValueError):
            self.export()
        self.assertFalse(self.destination.exists())
        self.assertFalse(list(self.root.glob(".snapshot-*")))
        self.destination.mkdir()
        (self.destination / "keep").write_text("user data", encoding="utf-8")
        with self.assertRaises(FileExistsError):
            self.export()
        self.assertEqual((self.destination / "keep").read_text(), "user data")

    def test_publication_switches_one_pointer_and_missing_cache_does_not_retain_old_cache(self):
        self.write_cache(cache())
        self.export()
        mirror = self.root / "mirror"
        snapshots.publish_snapshot(self.destination, mirror)
        old = snapshots.resolve_snapshot_directory(mirror)
        self.assertTrue((old / snapshots.CACHE_FILE).exists())
        self.source.write_text(json.dumps(data(5)), encoding="utf-8")
        self.destination = self.root / "next"
        self.export(include_cache=False)
        snapshots.publish_snapshot(self.destination, mirror)
        current = snapshots.resolve_snapshot_directory(mirror)
        self.assertNotEqual(current, old)
        self.assertTrue((old / snapshots.CACHE_FILE).exists())
        self.assertFalse((current / snapshots.CACHE_FILE).exists())
        self.assertIsNone(snapshots.load_snapshot(mirror)["cache"])
        self.assertEqual(snapshots.load_snapshot(mirror)["manifest"]["generation"], 5)

    def test_pointer_publication_failure_keeps_old_complete_generation(self):
        self.export()
        mirror = self.root / "mirror"
        snapshots.publish_snapshot(self.destination, mirror)
        before = (mirror / snapshots.CURRENT_FILE).read_bytes()
        directories = set((mirror / "generations").iterdir())
        with patch("napmem_storage.atomic_write", side_effect=OSError("synthetic publication failure")):
            with self.assertRaises(OSError):
                snapshots.publish_snapshot(self.destination, mirror)
        self.assertEqual((mirror / snapshots.CURRENT_FILE).read_bytes(), before)
        self.assertEqual(set((mirror / "generations").iterdir()), directories)
        self.assertEqual(snapshots.load_snapshot(mirror)["manifest"]["generation"], 4)

    def test_older_transfer_cannot_replace_newer_generation_or_conflict_at_same_generation(self):
        self.export()
        older = self.destination
        self.source.write_text(json.dumps(data(5)), encoding="utf-8")
        self.destination = self.root / "newer"
        self.export()
        mirror = self.root / "mirror"
        snapshots.publish_snapshot(self.destination, mirror)
        current = snapshots.resolve_snapshot_directory(mirror)
        result = snapshots.publish_snapshot(older, mirror)
        self.assertEqual(result["generation"], 5)
        self.assertEqual(snapshots.resolve_snapshot_directory(mirror), current)
        self.assertEqual(len(list((mirror / "generations").iterdir())), 1)
        changed = data(5)
        changed["memory_records"][0]["text"] = "Conflicting store at the same generation."
        self.source.write_text(json.dumps(changed), encoding="utf-8")
        self.destination = self.root / "conflicting"
        self.export()
        with self.assertRaisesRegex(ValueError, "conflicts"):
            snapshots.publish_snapshot(self.destination, mirror)
        self.assertEqual(snapshots.resolve_snapshot_directory(mirror), current)

    def test_concurrent_publications_each_leave_a_complete_generation(self):
        self.export()
        mirror = self.root / "mirror"
        failures = []

        def publish():
            try:
                snapshots.publish_snapshot(self.destination, mirror)
            except Exception as exc:
                failures.append(exc)

        code = ("from concurrent.futures import ThreadPoolExecutor; import sys; "
                "from napmem_snapshots import publish_snapshot; "
                "pool=ThreadPoolExecutor(max_workers=3); "
                "list(pool.map(lambda _:publish_snapshot(sys.argv[1],sys.argv[2]),range(3))); pool.shutdown()")
        subprocess.run([sys.executable, "-c", code, str(self.destination), str(mirror)],
                       timeout=8, check=True, capture_output=True)
        self.assertEqual(snapshots.load_snapshot(mirror)["manifest"]["generation"], 4)
        self.assertEqual(len(list((mirror / "generations").iterdir())), 3)

    def test_legacy_flat_mirror_is_readable_and_explicitly_unverified(self):
        self.destination.mkdir()
        (self.destination / snapshots.STORE_FILE).write_bytes(self.source.read_bytes())
        checked = snapshots.load_snapshot(self.destination)
        self.assertEqual(checked["verification"]["status"], "legacy-unverified")
        self.assertEqual(checked["verification"]["generation"], "unverified")
        with self.assertRaisesRegex(ValueError, "manifest-free"):
            snapshots.publish_snapshot(self.destination, self.root / "mirror")

    def test_archive_unpack_rejects_traversal_links_duplicates_and_missing_manifest(self):
        self.export()
        required = (snapshots.STORE_FILE, snapshots.MANIFEST_FILE)
        for invalid in ("../escape", snapshots.STORE_FILE, "symlink", "missing"):
            archive = self.root / "bad.tar"
            with tarfile.open(archive, "w") as stream:
                for name in required:
                    if invalid == "missing" and name == snapshots.MANIFEST_FILE:
                        continue
                    stream.add(self.destination / name, arcname=name)
                if invalid != "missing":
                    item = tarfile.TarInfo(invalid if invalid != "symlink" else snapshots.CACHE_FILE)
                    if invalid == "symlink":
                        item.type, item.linkname = tarfile.SYMTYPE, "/private/synthetic"
                        stream.addfile(item)
                    else:
                        item.size = 2
                        stream.addfile(item, io.BytesIO(b"{}"))
            target = self.root / "unpacked"
            with self.subTest(invalid=invalid), self.assertRaisesRegex(ValueError, "member|incomplete"):
                snapshots.unpack_snapshot(archive, target)
            self.assertEqual(list(target.iterdir()), [])

    def test_copied_generation_is_authoritative_if_valid_staging_changes(self):
        self.export()
        newer = self.root / "newer"
        self.source.write_text(json.dumps(data(5)))
        snapshots.export_snapshot(self.source, newer)
        original_read = snapshots._read
        switched = False

        def changing_read(path, *args):
            nonlocal switched
            if path == self.destination / snapshots.STORE_FILE and not switched:
                switched = True
                for name in snapshots.SNAPSHOT_FILES:
                    if (newer / name).exists():
                        (self.destination / name).write_bytes((newer / name).read_bytes())
            return original_read(path, *args)

        mirror = self.root / "mirror"
        with patch.object(snapshots, "_read", side_effect=changing_read):
            result = snapshots.publish_snapshot(self.destination, mirror)
        self.assertEqual(result["generation"], 5)
        self.assertEqual(snapshots.load_snapshot(mirror)["data"]["generation"], 5)
        self.assertIn("gen-5-", snapshots.resolve_snapshot_directory(mirror).name)

    def test_unpack_does_not_delete_a_foreign_file_created_during_extraction(self):
        self.export()
        archive = self.root / "snapshot.tar"
        with tarfile.open(archive, "w") as stream:
            for name in (snapshots.STORE_FILE, snapshots.MANIFEST_FILE):
                stream.add(self.destination / name, arcname=name)
        target = self.root / "unpacked"
        original_write = snapshots._write

        def collision(path, raw):
            if path.name == snapshots.MANIFEST_FILE:
                path.write_bytes(b"foreign bytes")
            return original_write(path, raw)

        with patch.object(snapshots, "_write", side_effect=collision):
            with self.assertRaises(FileExistsError):
                snapshots.unpack_snapshot(archive, target)
        self.assertEqual((target / snapshots.MANIFEST_FILE).read_bytes(), b"foreign bytes")
        self.assertFalse((target / snapshots.STORE_FILE).exists())

    def test_large_optional_cache_metadata_is_omitted_without_losing_store(self):
        value = cache()
        value["model"] = "m" * snapshots.MAX_MANIFEST_BYTES
        self.write_cache(value)
        result = self.export()
        self.assertEqual(result["cache"]["status"], "absent")
        self.assertEqual(snapshots.load_snapshot(self.destination)["data"]["generation"], 4)

    def test_pointer_checksum_tampering_and_traversal_are_rejected(self):
        self.export()
        mirror = self.root / "mirror"
        snapshots.publish_snapshot(self.destination, mirror)
        pointer = mirror / snapshots.CURRENT_FILE
        original = json.loads(pointer.read_text())
        for change in ({"directory": "../outside"}, {"manifest_sha256": "0" * 64}, {"generation": 8}):
            pointer.write_text(json.dumps({**deepcopy(original), **change}), encoding="utf-8")
            with self.subTest(change=change), self.assertRaises(ValueError):
                snapshots.load_snapshot(mirror)


if __name__ == "__main__":
    unittest.main()
