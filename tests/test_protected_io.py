from __future__ import annotations

import hashlib
import gc
import os
from pathlib import Path
import sys
import tempfile
import subprocess
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from cooling_tower.protected_io import InputChangedError, OwnedWorkspace, OwnedTemporaryDirectory, UnsafeWorkspaceError, read_locked


class InputSnapshotTests(unittest.TestCase):
    def test_legacy_temporary_owner_cleans_up_on_last_reference(self):
        with tempfile.TemporaryDirectory() as directory:
            owner = OwnedTemporaryDirectory(parent=directory, prefix='neutral_owner_')
            root = Path(owner.name)
            (root / 'own.txt').write_bytes(b'own scratch')
            del owner
            gc.collect()
            self.assertFalse(root.exists())

    def test_consistent_copy_remains_identified_after_external_source_change(self):
        with tempfile.TemporaryDirectory() as directory:
            original = Path(directory) / "original.stl"
            original.write_bytes(b"independent neutral test content")
            before = original.stat()
            with OwnedWorkspace(parent=directory) as workspace:
                snapshot = workspace.capture(original)
                self.assertEqual(snapshot.sha256, hashlib.sha256(original.read_bytes()).hexdigest())
                self.assertTrue(snapshot.original_is_unchanged())
                self.assertEqual(original.stat().st_mtime_ns, before.st_mtime_ns)
                original.write_bytes(b"external change")
                self.assertFalse(snapshot.original_is_unchanged())
                snapshot.verify()
                self.assertEqual(snapshot.path.read_bytes(), b"independent neutral test content")

    def test_snapshot_tampering_is_detected_and_original_is_not_restored(self):
        with tempfile.TemporaryDirectory() as directory:
            original = Path(directory) / "original.stl"
            original.write_bytes(b"original")
            with OwnedWorkspace(parent=directory) as workspace:
                snapshot = workspace.capture(original)
                snapshot.path.write_bytes(b"tampered")
                with self.assertRaises(InputChangedError):
                    snapshot.verify()
                self.assertEqual(original.read_bytes(), b"original")

    def test_exclusive_capture_does_not_replace_existing_copy(self):
        with tempfile.TemporaryDirectory() as directory:
            original = Path(directory) / "original.stl"
            original.write_bytes(b"original")
            with OwnedWorkspace(parent=directory) as workspace:
                snapshot = workspace.capture(original)
                with self.assertRaises(FileExistsError):
                    workspace.capture(original)
                snapshot.verify()

    @unittest.skipUnless(os.name == "nt", "Windows sharing semantics")
    def test_capture_handle_actually_denies_source_write_and_delete(self):
        with tempfile.TemporaryDirectory() as directory:
            original = Path(directory) / "neutral-original.stl"
            original.write_bytes(b"original")
            with read_locked(original) as stream:
                with self.assertRaises(PermissionError):
                    original.write_bytes(b"forbidden")
                with self.assertRaises(PermissionError):
                    original.unlink()
                self.assertEqual(stream.read(), b"original")
            self.assertEqual(original.read_bytes(), b"original")


class OwnedWorkspaceTests(unittest.TestCase):
    @unittest.skipUnless(os.name == 'nt', 'Windows creation boundary')
    def test_parent_is_pinned_before_the_first_workspace_write(self):
        with tempfile.TemporaryDirectory() as directory:
            parent = Path(directory) / 'parent'
            parent.mkdir()
            original = tempfile.mkdtemp
            attempted = []
            def create(*args, **kwargs):
                attempted.append(True)
                replacement = parent.with_name('replaced')
                try:
                    parent.rename(replacement)
                except PermissionError:
                    pass
                else:
                    replacement.rename(parent)
                    self.fail('The parent was replaceable before workspace creation.')
                return original(*args,**kwargs)
            with patch('cooling_tower.protected_io.tempfile.mkdtemp',side_effect=create):
                with OwnedWorkspace(parent=parent) as workspace:
                    self.assertTrue(workspace.path.is_dir())
            self.assertEqual(attempted,[True])

    def test_rejects_escape_ambiguous_paths_and_hardlinks(self):
        with tempfile.TemporaryDirectory() as directory:
            original = Path(directory) / "neutral-original.txt"
            original.write_bytes(b"original")
            with OwnedWorkspace(parent=directory) as workspace:
                for path in ("../escape", "C:/escape", "x:stream", "trailing.", "x/../../escape"):
                    with self.subTest(path=path), self.assertRaises(UnsafeWorkspaceError):
                        workspace.child(path)
                os.link(original, workspace.path / "alias")
                with self.assertRaises(UnsafeWorkspaceError):
                    workspace.child("alias")
            self.assertEqual(original.read_bytes(), b"original")

    @unittest.skipUnless(os.name == "nt", "Windows directory pinning")
    def test_live_lease_denies_directory_replacement(self):
        with tempfile.TemporaryDirectory() as directory:
            with OwnedWorkspace(parent=directory) as workspace:
                with self.assertRaises(PermissionError):
                    workspace.path.rename(workspace.path.with_name("replacement"))
            self.assertFalse(workspace.path.exists())

    @unittest.skipUnless(os.name == "nt", "Windows ancestor pinning")
    def test_live_lease_denies_ancestor_replacement(self):
        with tempfile.TemporaryDirectory() as directory:
            container = Path(directory) / "container"
            container.mkdir()
            with OwnedWorkspace(parent=container) as workspace:
                with self.assertRaises(PermissionError):
                    container.rename(container.with_name("replacement"))
                self.assertTrue(workspace.path.is_dir())

    def test_closed_workspace_cannot_be_reused(self):
        with tempfile.TemporaryDirectory() as directory:
            workspace = OwnedWorkspace(parent=directory)
            workspace.close()
            workspace.close()
            with self.assertRaises(UnsafeWorkspaceError):
                workspace.child("late-file")

    @unittest.skipUnless(os.name == "nt", "Windows junction semantics")
    def test_junction_is_rejected_and_cleanup_preserves_its_target(self):
        with tempfile.TemporaryDirectory() as directory:
            outside = Path(directory) / "neutral-originals"
            outside.mkdir()
            original = outside / "neutral.txt"
            original.write_bytes(b"original")
            with OwnedWorkspace(parent=directory) as workspace:
                alias = workspace.path / "alias"
                result = subprocess.run(["cmd.exe", "/d", "/c", "mklink", "/J", str(alias), str(outside)],
                    capture_output=True, timeout=10, creationflags=subprocess.CREATE_NO_WINDOW)
                self.assertEqual(result.returncode, 0, result.stderr)
                with self.assertRaises(UnsafeWorkspaceError):
                    workspace.child("alias/neutral.txt")
            self.assertEqual(original.read_bytes(), b"original")
            self.assertTrue(outside.is_dir())


if __name__ == "__main__":
    unittest.main()
