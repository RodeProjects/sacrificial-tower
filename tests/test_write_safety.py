from __future__ import annotations

import json
import os
import sys
import tempfile
import threading
import subprocess
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from cooling_tower.persistence.versioned_json import (
    ConcurrentDocumentChangeError, VersionedJsonStore, atomic_write_json,
)
from cooling_tower.persistence.document_lock import document_lock
from cooling_tower.write_policy import ProtectedWritePathError, ensure_writable_output
from cooling_tower.services.output_service import OutputService


class WriteSafetyTests(unittest.TestCase):
    def test_export_rejects_vendor_directory_before_creating_anything(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            with patch.dict(os.environ, {"APPDATA": str(root)}):
                destination = root / "BambuStudio" / "user" / "exports"
                with self.assertRaises(ProtectedWritePathError):
                    OutputService(destination).create_run_directories("model.gcode")
                self.assertFalse((root / "BambuStudio").exists())
                self.assertEqual(ensure_writable_output(root / "my-exports"), root / "my-exports")

    def test_explicit_portable_roots_and_original_files_are_protected(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            with self.assertRaises(ProtectedWritePathError):
                ensure_writable_output(root / "portable" / "new", protected_roots=(root / "portable",))
            with self.assertRaises(ProtectedWritePathError):
                ensure_writable_output(root / "profile.json", protected_files=(root / "profile.json",))

    def test_first_creation_never_replaces_a_late_file(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "settings.json"
            original_link = os.link
            def create_competing_file(source, target):
                path.write_text('{"external":true}', encoding="utf-8")
                return original_link(source, target)
            with patch("cooling_tower.persistence.versioned_json.os.link", side_effect=create_competing_file):
                with self.assertRaises(ConcurrentDocumentChangeError):
                    atomic_write_json(path, {"ours": True}, expect_absent=True)
            self.assertEqual(json.loads(path.read_text()), {"external": True})
            self.assertFalse(list(Path(directory).glob(".*.tmp")))

    def test_load_never_labels_external_bytes_as_its_own_snapshot(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "settings.json"
            path.write_text('{"schema":1,"value":1}', encoding="utf-8")
            def normalizer(payload):
                path.write_text('{"schema":1,"value":2}', encoding="utf-8")
                return payload
            store = VersionedJsonStore(path, schema_key="schema", current_version=1, normalizer=normalizer)
            self.assertEqual(store.load().payload["value"], 1)
            store.normalizer = None
            with self.assertRaises(ConcurrentDocumentChangeError):
                store.save({"value": 3})
            self.assertEqual(json.loads(path.read_text())["value"], 2)

    def test_document_lock_is_reentrant_and_excludes_another_thread(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "settings.json"
            acquired = threading.Event()
            started = threading.Event()
            def contender():
                started.set()
                with document_lock(path):
                    acquired.set()
            with document_lock(path):
                with document_lock(path):
                    worker = threading.Thread(target=contender)
                    worker.start()
                    self.assertTrue(started.wait(2))
                    self.assertFalse(acquired.wait(0.05))
            worker.join(2)
            self.assertTrue(acquired.is_set())

    def test_document_lock_excludes_another_process_and_releases(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "settings.json"
            code = """import sys
from cooling_tower.persistence.document_lock import document_lock
try:
    with document_lock(sys.argv[1], timeout_s=0.1):
        pass
except TimeoutError:
    sys.exit(3)
"""
            env = dict(os.environ, PYTHONPATH=str(Path(__file__).resolve().parents[1] / "src"))
            command = [sys.executable, "-c", code, str(path)]
            with document_lock(path):
                result = subprocess.run(command, env=env, capture_output=True, timeout=10)
                self.assertEqual(result.returncode, 3, result.stderr)
            result = subprocess.run(command, env=env, capture_output=True, timeout=10)
            self.assertEqual(result.returncode, 0, result.stderr)

    def test_foreign_backup_created_during_open_is_not_deleted(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "settings.json"
            path.write_text('{"schema":0}', encoding="utf-8")
            backup = path.with_name(path.name + ".schema-0.backup")
            original_open = Path.open

            def competing_open(target, mode="r", *args, **kwargs):
                if target == backup and mode == "xb":
                    with original_open(target, "wb") as stream:
                        stream.write(b"foreign backup")
                    raise FileExistsError("Competing backup")
                return original_open(target, mode, *args, **kwargs)

            store = VersionedJsonStore(path, schema_key="schema", current_version=1, migrations={0: lambda data: dict(data, schema=1)})
            with patch.object(Path, "open", competing_open):
                with self.assertRaises(FileExistsError):
                    store.load()
            self.assertEqual(backup.read_bytes(), b"foreign backup")
            self.assertEqual(json.loads(path.read_text())["schema"], 0)


if __name__ == "__main__":
    unittest.main()
