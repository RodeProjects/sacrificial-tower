from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import sys
import subprocess
import tempfile
from threading import Event, Timer, Thread
import time
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from cooling_tower.protected_io import OwnedWorkspace, UnsafeWorkspaceError
from cooling_tower.slicers.protected_process import WindowsProtectedSlicerProcessRunner
from cooling_tower.slicers.qprocess_backend import QProcessSlicerProcessRunner


@unittest.skipUnless(os.name == "nt" and os.environ.get("COOLING_TOWER_RUN_SANDBOX_ACCEPTANCE") == "1",
                     "Windows LPAC acceptance is opt-in and requires a normal desktop user token.")
class WindowsSlicerSandboxTests(unittest.TestCase):
    _probe_path = None

    @classmethod
    def native_probe(cls):
        if cls._probe_path is None:
            directory = tempfile.TemporaryDirectory()
            cls.addClassCleanup(directory.cleanup)
            probe_path = Path(directory.name) / 'neutral-probe.dll'
            root = Path(__file__).resolve().parents[1]
            built = subprocess.run([sys.executable, str(root / 'scripts' / 'build_sandbox_test_probe.py'),
                '--output', str(probe_path)], cwd=root, capture_output=True, text=True,
                errors='replace', timeout=120, check=False)
            if built.returncode:
                raise RuntimeError('Neutral Windows probe build failed:\n' + built.stdout + built.stderr)
            cls._probe_path = probe_path
        return cls._probe_path

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.original = self.root / "neutral-original.txt"
        self.original.write_bytes(b"original")
        self.before = self.original.stat()
        self.runner = WindowsProtectedSlicerProcessRunner(QProcessSlicerProcessRunner(), mirror_runtime=False)
        self.executable = Path(os.environ["SystemRoot"]) / "System32" / "cmd.exe"

    def unchanged(self):
        self.assertEqual(self.original.read_bytes(), b"original")
        self.assertEqual(self.original.stat().st_mtime_ns, self.before.st_mtime_ns)
        self.assertEqual(self.original.stat().st_file_attributes, self.before.st_file_attributes)

    def run_command(self, work, command, **kwargs):
        return self.runner.run(self.executable, ("/d", "/v:off", "/c", command),
            working_directory=work.path, timeout_s=kwargs.pop("timeout_s", 20), **kwargs)

    def grant_shared_test_originals(self, integrity='LW'):
        import ctypes as C
        from ctypes import wintypes as W
        from cooling_tower.slicers.windows_lpac import _Api, _grant_owned
        api = _Api()
        _grant_owned(api, self.root, 'S-1-15-2-2', writable=True, integrity=integrity)
        # Full control deliberately includes FILE_DELETE_CHILD, which ordinary
        # FILE_GENERIC_WRITE omits. Only this neutral test area is provisioned.
        descriptor = W.LPVOID()
        api.check(api.security.ConvertStringSecurityDescriptorToSecurityDescriptorW(
            'D:P(A;OICI;FA;;;OW)(A;OICI;FA;;;SY)(A;OICI;FA;;;S-1-15-2-2)',
            1, C.byref(descriptor), None))
        handle = api.kernel.CreateFileW(str(self.root), 0xE0081, 7, None, 3, 0x02200000, None)
        if handle == C.c_void_p(-1).value:
            raise C.WinError(C.get_last_error())
        try:
            present, defaulted, acl = W.BOOL(), W.BOOL(), W.LPVOID()
            api.check(api.security.GetSecurityDescriptorDacl(descriptor, C.byref(present), C.byref(acl), C.byref(defaulted)))
            error = api.security.SetSecurityInfo(handle, 1, 4 | 0x80000000, None, None, acl, None)
            if error:raise C.WinError(error)
        finally:
            api.kernel.CloseHandle(handle)
            api.kernel.LocalFree(descriptor)

    def security_hash(self, path):
        import ctypes as C
        from ctypes import wintypes as W
        function = C.WinDLL('advapi32', use_last_error=True).GetFileSecurityW
        function.argtypes = (W.LPCWSTR, W.DWORD, W.LPVOID, W.DWORD, C.POINTER(W.DWORD))
        size = W.DWORD()
        function(str(path), 7 | 0x10, None, 0, C.byref(size))
        self.assertGreater(size.value, 0)
        buffer = C.create_string_buffer(size.value)
        if not function(str(path), 7 | 0x10, buffer, len(buffer), C.byref(size)):
            raise C.WinError(C.get_last_error())
        return hashlib.sha256(buffer.raw[:size.value]).hexdigest()

    def assert_bootstrapped_payload_cannot_modify_originals(self, integrity):
        installation = self.root / 'neutral-installation'
        installation.mkdir()
        executable = installation / 'AnycubicSlicerNext.exe'
        executable.write_bytes(b'Own neutral placeholder, never executed')
        (installation / 'AnycubicSlicer.dll').write_bytes(self.native_probe().read_bytes())
        self.grant_shared_test_originals(integrity)
        self.before = self.original.stat()
        security_before = self.security_hash(self.original), self.security_hash(self.root)
        links_before = self.original.stat().st_nlink
        runner = WindowsProtectedSlicerProcessRunner(QProcessSlicerProcessRunner(),
            adapter_id='anycubic_slicer_next')
        with OwnedWorkspace(parent=self.root) as work:
            outcome = runner.run(executable, ('--slice', str(self.root), str(work.path)),
                working_directory=work.path, timeout_s=20)
            self.assertEqual(outcome.return_code, 0, outcome.stdout + outcome.stderr)
            self.assertEqual(work.child('allowed.txt').read_bytes(), b'allowed')
            self.assertEqual(work.child('child.txt').read_text().strip(), 'child')
        self.unchanged()
        self.assertFalse((self.root / 'new.txt').exists())
        self.assertEqual(self.original.stat().st_nlink, links_before)
        self.assertEqual((self.security_hash(self.original), self.security_hash(self.root)), security_before)

    def test_bootstrapped_native_payload_preserves_low_shared_originals(self):
        self.assert_bootstrapped_payload_cannot_modify_originals('LW')

    def test_bootstrapped_native_payload_preserves_untrusted_shared_originals(self):
        self.assert_bootstrapped_payload_cannot_modify_originals('S-1-16-0')

    def assert_hosted_interruption(self, cancel):
        installation = self.root / 'neutral-installation'
        installation.mkdir()
        executable = installation / 'AnycubicSlicerNext.exe'
        executable.write_bytes(b'Own neutral placeholder, never executed')
        (installation / 'AnycubicSlicer.dll').write_bytes(self.native_probe().read_bytes())
        self.grant_shared_test_originals()
        self.before = self.original.stat()
        runner = WindowsProtectedSlicerProcessRunner(QProcessSlicerProcessRunner(),
            adapter_id='anycubic_slicer_next')
        event, ready, finished = Event(), Event(), Event()
        observers = []
        def state_changed(state, details):
            if state != 'slicer_process_started': return
            request = Path(details['command'][-1])
            stage = Path(json.loads(request.read_text(encoding='utf-8'))['root'])
            def observe_child():
                deadline = time.monotonic() + 10
                while time.monotonic() < deadline and not finished.wait(.02):
                    if (stage / 'w' / 'child.txt').is_file():
                        ready.set()
                        if cancel: event.set()
                        return
            observer = Thread(target=observe_child)
            observers.append(observer)
            observer.start()
        with OwnedWorkspace(parent=self.root) as work:
            try:
                outcome = runner.run(executable, ('--slice', '--wait', str(self.root), str(work.path)),
                    working_directory=work.path, timeout_s=15 if cancel else 5.,
                    cancellation_event=event if cancel else None, state_callback=state_changed)
            finally:
                finished.set()
                for observer in observers: observer.join(2.)
            self.assertTrue(ready.is_set(), 'The native payload and its child must actually run before interruption.')
            self.assertTrue(outcome.cancelled if cancel else outcome.timed_out, outcome)
            self.assertFalse(work.child('allowed.txt').exists())
            self.assertFalse(work.child('child.txt').exists())
        self.unchanged()

    def test_timeout_stops_bootstrapped_engine_and_its_child_without_publishing(self):
        self.assert_hosted_interruption(False)

    def test_cancellation_stops_bootstrapped_engine_and_its_child_without_publishing(self):
        self.assert_hosted_interruption(True)

    def test_native_process_can_write_only_to_its_owned_copy(self):
        with OwnedWorkspace(parent=self.root) as work:
            outcome = self.run_command(work,
                f'(echo allowed)>"{work.path / "allowed.txt"}" & (echo forbidden)>"{self.original}" & exit /b 0')
            self.assertEqual(outcome.return_code, 0, outcome.stderr)
            self.assertIsNotNone(outcome.process_id)
            self.assertTrue((work.path / "allowed.txt").is_file(), outcome)
            self.assertEqual((work.path / "allowed.txt").read_text().strip(), "allowed")
            self.assertTrue(outcome.stderr.strip(), "The denied native write must be observable.")
        self.unchanged()

    def test_real_child_process_inherits_the_boundary(self):
        with OwnedWorkspace(parent=self.root) as work:
            # CMD starts a second native CMD, which tries both destinations.
            (work.path / "child.cmd").write_text(
                f'@echo off\necho child>child.txt\n(echo forbidden)>"{self.original}"\nexit /b 0\n', encoding="utf-8")
            outcome = self.run_command(work,
                'cmd.exe /d /c child.cmd & exit /b 0')
            self.assertEqual(outcome.return_code, 0, outcome.stderr)
            self.assertTrue((work.path / "child.txt").is_file(), outcome)
            self.assertEqual((work.path / "child.txt").read_text().strip(), "child")
            self.assertTrue(outcome.stderr.strip())
        self.unchanged()

    def test_low_integrity_shared_package_directory_still_cannot_be_modified(self):
        # Provision only this newly created neutral test area before recording
        # its protected baseline. Never alter a user's original ACL or label.
        self.grant_shared_test_originals()
        self.before = self.original.stat()
        with OwnedWorkspace(parent=self.root) as work:
            outcome = self.run_command(work,
                f'(echo forbidden)>"{self.original}" & (echo forbidden)>"{self.root / "unexpected.txt"}" & exit /b 0')
            self.assertEqual(outcome.return_code, 0, outcome.stderr)
            self.assertTrue(outcome.stderr.strip(), 'Shared-package rights must not grant write access.')
        self.unchanged()
        self.assertFalse((self.root / 'unexpected.txt').exists())

    def test_child_cannot_mutate_low_shared_original_content_attributes_acl_or_catalog(self):
        self.assert_shared_originals_are_protected('LW')

    def test_child_cannot_mutate_untrusted_shared_originals(self):
        self.assert_shared_originals_are_protected('S-1-16-0')

    def assert_shared_originals_are_protected(self, integrity):
        import ctypes as C
        from ctypes import wintypes as W
        catalog = self.root / 'original-catalog'
        catalog.mkdir()
        (catalog / 'kept.txt').write_bytes(b'catalog original')
        self.grant_shared_test_originals(integrity)
        self.before = self.original.stat()
        def security_hash(path):
            function = C.WinDLL('advapi32', use_last_error=True).GetFileSecurityW
            function.argtypes = (W.LPCWSTR, W.DWORD, W.LPVOID, W.DWORD, C.POINTER(W.DWORD))
            size = W.DWORD()
            function(str(path), 7 | 0x10, None, 0, C.byref(size))
            self.assertGreater(size.value, 0)
            buffer = C.create_string_buffer(size.value)
            if not function(str(path), 7 | 0x10, buffer, len(buffer), C.byref(size)):
                raise C.WinError(C.get_last_error())
            return hashlib.sha256(buffer.raw[:size.value]).hexdigest()
        before = security_hash(self.original), security_hash(catalog)
        with OwnedWorkspace(parent=self.root) as work:
            work.child('child.cmd').write_text(
                f'@echo off\n(echo forbidden)>"{self.original}"\n'
                f'attrib +r "{self.original}"\n'
                f'icacls "{self.original}" /grant *S-1-15-2-2:F\n'
                f'del /f /q "{self.original}"\n'
                f'(echo forbidden)>"{catalog / "new.txt"}"\n'
                f'move /y "{catalog}" "{catalog}.moved"\n'
                'echo child>allowed.txt\nexit /b 0\n', encoding='utf-8')
            outcome = self.run_command(work, 'cmd.exe /d /c child.cmd & exit /b 0')
            self.assertEqual(outcome.return_code, 0, outcome.stderr)
            self.assertTrue(work.child('allowed.txt').is_file(), outcome.stderr)
        self.unchanged()
        self.assertEqual((catalog / 'kept.txt').read_bytes(), b'catalog original')
        self.assertEqual(set(path.name for path in catalog.iterdir()), {'kept.txt'})
        self.assertFalse(Path(str(catalog) + '.moved').exists())
        self.assertEqual((security_hash(self.original), security_hash(catalog)), before)

    def test_delete_and_move_are_denied_for_neutral_original(self):
        for operation in (f'del /f /q "{self.original}"', f'move /y "{self.original}" "{self.original}.moved"'):
            with self.subTest(operation=operation), OwnedWorkspace(parent=self.root) as work:
                outcome = self.run_command(work, operation + " & exit /b 0")
                self.assertEqual(outcome.return_code, 0, outcome.stderr)
                self.assertTrue(outcome.stderr.strip() or outcome.stdout.strip())
                self.unchanged()
                self.assertFalse(Path(str(self.original) + ".moved").exists())

    def test_hardlink_alias_does_not_grant_original_write_access(self):
        with OwnedWorkspace(parent=self.root) as work:
            # Native LPAC attempts the link itself: no source ACL propagation.
            outcome = self.run_command(work,
                f'mklink /H alias.txt "{self.original}" & (echo forbidden)>alias.txt & exit /b 0')
            self.assertEqual(outcome.return_code, 0, outcome.stderr)
        self.unchanged()

    def test_unknown_working_directory_is_rejected_before_launch(self):
        with self.assertRaises(UnsafeWorkspaceError):
            self.runner.run(self.executable, ("/d", "/c", "exit 0"), working_directory=self.root, timeout_s=10)
        self.unchanged()

    def test_timeout_stops_native_process_without_publishing_partial_files(self):
        with OwnedWorkspace(parent=self.root) as work:
            outcome = self.run_command(work, "echo partial>partial.txt & for /L %i in (1,1,2147483647) do @rem", timeout_s=2)
            self.assertTrue(outcome.timed_out, outcome)
            self.assertFalse((work.path / "partial.txt").exists())
        self.unchanged()

    def test_cancellation_stops_native_process_without_publishing(self):
        event = Event()
        timer = Timer(1.5, event.set)
        with OwnedWorkspace(parent=self.root) as work:
            timer.start()
            try:
                outcome = self.run_command(work, "echo partial>partial.txt & for /L %i in (1,1,2147483647) do @rem", cancellation_event=event)
            finally:
                timer.cancel()
            self.assertTrue(outcome.cancelled, outcome)
            self.assertFalse((work.path / "partial.txt").exists())
        self.unchanged()


if __name__ == "__main__":
    unittest.main()
