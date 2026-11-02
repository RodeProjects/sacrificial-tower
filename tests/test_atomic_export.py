from pathlib import Path
import hashlib
import os
import sys
import subprocess
import tempfile
import unittest
from types import SimpleNamespace
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'src'))
from cooling_tower.export_io import atomic_export, export_directory, generated_file
from cooling_tower.write_policy import ProtectedWritePathError
from cooling_tower.protected_io import UnsafeWorkspaceError, OwnedWorkspace, require_owned_workspace

@unittest.skipUnless(os.name=='nt','Windows handle-based export')
class AtomicExportTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name);self.source=self.root/'checked.3mf';self.source.write_bytes(b'new verified export')
        self.digest=hashlib.sha256(self.source.read_bytes()).hexdigest();self.target=self.root/'published.3mf'
    def export(self,**kw):return atomic_export(self.source,self.target,expected_sha256=self.digest,**kw)
    def test_success_and_explicit_atomic_replacement(self):
        self.export();self.assertEqual(self.target.read_bytes(),self.source.read_bytes())
        self.target.write_bytes(b'old export');self.export(overwrite=True)
        self.assertEqual(self.target.read_bytes(),self.source.read_bytes())
    def test_existing_export_survives_wrong_source_identity_and_default_no_overwrite(self):
        self.target.write_bytes(b'valid old export')
        with self.assertRaises(FileExistsError):self.export()
        self.source.write_bytes(b'changed')
        with self.assertRaises(UnsafeWorkspaceError):self.export(overwrite=True)
        self.assertEqual(self.target.read_bytes(),b'valid old export')
        self.assertFalse(tuple(self.root.glob('.st-export-*')))
    def test_original_and_installation_paths_rejected(self):
        self.target.write_bytes(b'original')
        with self.assertRaises(ProtectedWritePathError):self.export(overwrite=True,protected_files=(self.target,))
        with self.assertRaises(ProtectedWritePathError):self.export(overwrite=True,protected_roots=(self.root,))
        self.assertEqual(self.target.read_bytes(),b'original')
    def test_hardlink_to_original_rejected_without_modifying_original(self):
        original=self.root/'original.3mf';original.write_bytes(b'protected original')
        os.link(original,self.target)
        with self.assertRaises(ProtectedWritePathError):self.export(overwrite=True,protected_files=(original,))
        self.assertEqual(original.read_bytes(),b'protected original')
    def test_source_cannot_be_its_own_export(self):
        with self.assertRaises(ProtectedWritePathError):atomic_export(self.source,self.source,expected_sha256=self.digest,overwrite=True)

    def test_cancelled_copy_keeps_previous_export_and_removes_partial_by_handle(self):
        self.target.write_bytes(b'valid old export')
        checks=[]
        def cancelled():
            checks.append(1)
            return len(checks)>1
        with self.assertRaises(InterruptedError):
            self.export(overwrite=True,cancellation_callback=cancelled)
        self.assertEqual(self.target.read_bytes(),b'valid old export')
        self.assertFalse(tuple(self.root.glob('.st-export-*')))

    def test_export_folder_retains_completed_files_and_exclusively_avoids_old_runs(self):
        original=self.root/'exports'/'neutral';original.mkdir(parents=True)
        (original/'kept.txt').write_bytes(b'old export')
        with export_directory(self.root/'exports','neutral',protected_files=(self.source,)) as directory:
            self.assertEqual(directory.name,'neutral_2')
            (directory/'new.txt').write_bytes(b'complete')
        self.assertEqual((directory/'new.txt').read_bytes(),b'complete')
        self.assertEqual((original/'kept.txt').read_bytes(),b'old export')
        with self.assertRaises(UnsafeWorkspaceError):require_owned_workspace(directory)

    def test_failed_export_folder_removes_only_its_own_new_run(self):
        with self.assertRaisesRegex(RuntimeError,'interrupted'):
            with export_directory(self.root/'exports','neutral') as directory:
                (directory/'partial.txt').write_bytes(b'partial')
                raise RuntimeError('interrupted')
        self.assertFalse(directory.exists())

    def test_native_directory_pins_readable_original_root_and_all_output_ancestors(self):
        original_root = self.root/'neutral-installation'
        original_root.mkdir()
        original = original_root/'engine.exe'
        original.write_bytes(b'protected neutral engine')
        output = self.root/'native-exports'
        with export_directory(output,'neutral',protected_files=(original,),
                protected_roots=(original_root,),pin_protected_roots_only=True) as directory:
            with self.assertRaises(PermissionError):
                original_root.rename(self.root/'moved-installation')
            with self.assertRaises(PermissionError):
                original.unlink()
            with self.assertRaises(PermissionError):
                output.rename(self.root/'moved-output')
            atomic_export(self.source,directory/'complete.3mf',expected_sha256=self.digest,
                protected_files=(original,),protected_roots=(original_root,))
        self.assertEqual(original.read_bytes(),b'protected neutral engine')
        self.assertEqual((directory/'complete.3mf').read_bytes(),self.source.read_bytes())

    def test_nested_export_can_pin_owned_originals_without_releasing_their_lease(self):
        with OwnedWorkspace(parent=self.root) as work:
            original=work.child('source.txt');original.write_bytes(b'original')
            with export_directory(self.root/'exports','neutral',protected_files=(original,)) as directory:
                atomic_export(self.source,directory/'export.3mf',expected_sha256=self.digest,protected_files=(original,))
            self.assertEqual(original.read_bytes(),b'original')
            self.assertIs(require_owned_workspace(work.path),work)

    def test_external_change_of_previous_export_is_not_overwritten_during_copy(self):
        self.target.write_bytes(b'previous export')
        checks=[]
        def changed():
            checks.append(1)
            if len(checks)==2:self.target.write_bytes(b'external edit')
            return False
        with self.assertRaisesRegex(UnsafeWorkspaceError,'zwischenzeitlich'):
            self.export(overwrite=True,cancellation_callback=changed)
        self.assertEqual(self.target.read_bytes(),b'external edit')
        self.assertFalse(tuple(self.root.glob('.st-export-*')))

    def test_generation_failure_preserves_previous_artifact(self):
        self.target.write_bytes(b'previous complete artifact')
        with self.assertRaisesRegex(RuntimeError, 'generation failed'):
            with generated_file(self.target) as staging:
                staging.write_bytes(b'partial')
                raise RuntimeError('generation failed')
        self.assertEqual(self.target.read_bytes(), b'previous complete artifact')

    def test_legacy_reports_and_mesh_writer_refuse_hardlinked_originals(self):
        from cooling_tower.models import GenerationSettings
        from cooling_tower.services.output_service import OutputService
        from cooling_tower.tower.mesh_generator import TriangleMesh, write_binary_stl
        service = OutputService(self.root / 'output')
        paths = service.create_run_directories(self.source)
        mesh = TriangleMesh(((0,0,0),(1,0,0),(0,1,0),(0,0,1)),
                            ((0,2,1),(0,1,3),(1,2,3),(2,0,3)), 0, 0)
        for target, writer in (
            (paths.log_path, lambda: service.write_log(paths, ['new log'])),
            (paths.settings_path, lambda: service.write_settings(paths, GenerationSettings())),
            (paths.stl_path, lambda: write_binary_stl(mesh, paths.stl_path)),
        ):
            with self.subTest(target=target.name):
                os.link(self.source, target)
                with self.assertRaises(ProtectedWritePathError): writer()
                self.assertEqual(self.source.read_bytes(), b'new verified export')
                target.unlink()

    def test_generation_run_pins_source_and_destination_through_all_writers(self):
        from cooling_tower.services.output_service import OutputService
        with OutputService(self.root / 'output').run_directory(self.source) as paths:
            with self.assertRaises(PermissionError):
                self.source.replace(self.root / 'moved-original.3mf')
            with self.assertRaises(PermissionError):
                paths.run_directory.replace(paths.run_directory.with_name('moved'))
            require_owned_workspace(paths.run_directory)
        self.assertTrue(self.source.exists())

    def test_legacy_writers_reject_directory_junction_before_touching_originals(self):
        from cooling_tower.config import save_generation_settings
        from cooling_tower.models import GenerationSettings
        from cooling_tower.tower.mesh_generator import TriangleMesh, write_binary_stl
        originals = self.root / 'neutral-source'
        originals.mkdir()
        stl, settings = originals / 'tower.stl', originals / 'settings.json'
        stl.write_bytes(b'original mesh')
        settings.write_bytes(b'original settings')
        junction = self.root / 'alias'
        result = subprocess.run(('cmd.exe', '/d', '/c', 'mklink', '/J', str(junction), str(originals)),
                                capture_output=True, text=True, timeout=10)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        try:
            mesh = TriangleMesh(((0,0,0),(1,0,0),(0,1,0),(0,0,1)),
                                ((0,2,1),(0,1,3),(1,2,3),(2,0,3)), 0, 0)
            with self.assertRaises(ProtectedWritePathError):
                write_binary_stl(mesh, junction / 'tower.stl')
            with self.assertRaises(ProtectedWritePathError):
                save_generation_settings(GenerationSettings(), junction / 'settings.json')
            self.assertEqual(stl.read_bytes(), b'original mesh')
            self.assertEqual(settings.read_bytes(), b'original settings')
        finally:
            junction.rmdir()

    def test_calibration_export_refuses_hardlinked_original_outside_selected_source(self):
        from cooling_tower.calibration.calibration_service import CalibrationService
        from cooling_tower.models import CalibrationConfig, CalibrationState
        install = self.root / 'neutral-installation'
        install.mkdir()
        executable = install / 'slicer.exe'
        executable.write_bytes(b'neutral placeholder')
        profile = SimpleNamespace(installation=SimpleNamespace(executable_path=executable, profile_roots=()))
        original = self.root / 'another-original.stl'
        original.write_bytes(b'protected original mesh')
        candidate = self.root / 'candidate.stl'
        candidate.write_bytes(b'own generated mesh')
        output = self.root / 'exports'
        output.mkdir()
        os.link(original, output / 'cooling_tower_slicer_evaluated.stl')
        with self.assertRaises(ProtectedWritePathError):
            CalibrationService._export_candidate(state=CalibrationState.CONVERGED,
                config=CalibrationConfig(), iterations=[], profile=profile,
                candidate_stl=candidate, candidate_gcode=None, candidate_project=None,
                deferred_project=None, placement=None, failures=(), warnings=[],
                source=self.source, source_hash=self.digest, protected_roots=(install,), output_directory=output,
                best_iteration_number=1, improved_over_initial_candidate=False)
        self.assertEqual(original.read_bytes(), b'protected original mesh')

if __name__=='__main__':unittest.main()
