from pathlib import Path
import hashlib
import json
import os
import sys
import tempfile
from threading import Event
from types import SimpleNamespace
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]/'src'))

from cooling_tower.native_project.export import NativeExportReport, export_project_run
from cooling_tower.native_project.session import NativeOperationCancelled, NativeSliceError
from cooling_tower.write_policy import ProtectedWritePathError


class NativeProjectExportTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.source = self.root/'private-source.3mf'
        self.source.write_bytes(b'unchanged original')
        installation = self.root/'slicer'
        installation.mkdir()
        executable = installation/'engine.exe'
        executable.write_bytes(b'neutral executable')
        self.project = self.root/'verified.3mf'
        self.project.write_bytes(b'complete verified project')
        prepared = SimpleNamespace(project_path=self.project,
            project_sha256=hashlib.sha256(self.project.read_bytes()).hexdigest(),
            installation=SimpleNamespace(executable_path=executable, profile_roots=()),
            context=SimpleNamespace(adapter_id='bambu_studio'), plate_id='1', verify=lambda:None,
            analysis=SimpleNamespace(layer_count=2, layers=(SimpleNamespace(total_time_s=10.),)*2))
        self.generated = SimpleNamespace(prepared=prepared,
            state=SimpleNamespace(value='converged'), settings=SimpleNamespace(target_layer_time_s=9.),
            tower_center_mm=(25.,30.), tower_radius_mm=15., iterations=(1,2))
        self.session = SimpleNamespace(source_snapshot=SimpleNamespace(original_path=self.source))
        self.output = self.root/'exports'

    def export(self, **options):
        return export_project_run(self.session,self.generated,self.output,**options)

    def test_separate_runs_preserve_complete_artifacts_and_only_technical_report_fields(self):
        first, second = self.export(), self.export()
        self.assertNotEqual(first.path.parent,second.path.parent)
        for result in (first,second):
            self.assertEqual(result.path.read_bytes(),self.project.read_bytes())
            report = json.loads(result.report_path.read_text(encoding='utf-8'))
            self.assertEqual(report['native_project_report_version'],1)
            self.assertIs(report['tower_brim_enabled'],False)
            self.assertIn('Iterativ',result.user_report_path.read_text(encoding='utf-8'))
            self.assertNotIn(str(self.root),result.report_path.read_text(encoding='utf-8'))
            self.assertNotIn(self.source.name,result.user_report_path.read_text(encoding='utf-8'))
        self.assertEqual(self.source.read_bytes(),b'unchanged original')

    def test_report_failure_removes_incomplete_run_and_retains_previous_export(self):
        previous = self.export()
        before = previous.path.read_bytes()
        with patch('cooling_tower.native_project.export.atomic_export_data',side_effect=OSError('locked report')):
            with self.assertRaisesRegex(OSError,'locked report'):
                self.export()
        self.assertEqual(list(self.output.iterdir()),[previous.path.parent])
        self.assertEqual(previous.path.read_bytes(),before)

    def test_preliminary_report_uses_the_exported_candidate_instead_of_the_last_slice(self):
        self.generated.state.value = 'paused'
        self.generated.settings.target_layer_time_s = 11.
        self.generated.minimum_layer_time_s = 10.96
        self.generated.best_iteration = 1
        exported = self.export()
        report = json.loads(exported.report_path.read_text(encoding='utf-8'))
        self.assertEqual(report['state'], 'paused')
        self.assertEqual(report['iterations'], 2)
        self.assertEqual(report['best_iteration'], 1)
        self.assertEqual(NativeExportReport.read(exported.path).minimum_verified_layer_time_s, 10.96)
        self.assertEqual(exported.path.read_bytes(), self.project.read_bytes())
        summary = exported.user_report_path.read_text(encoding='utf-8')
        self.assertIn('Vorläufig übernommen', summary)
        self.assertIn('Exportierter Kandidat: Durchlauf 1', summary)

    def test_report_excludes_only_the_additional_layer_from_the_minimum(self):
        self.generated.prepared.analysis.layers = (
            SimpleNamespace(z_mm=.2, total_time_s=11.), SimpleNamespace(z_mm=.4, total_time_s=10.),
            SimpleNamespace(z_mm=.6, total_time_s=.5))
        self.generated.extra_layer_z_mm = .6
        self.generated.settings.extra_top_layer = True
        self.generated.prepared.composed = SimpleNamespace(extra_layer_base_z=None)
        with self.assertRaisesRegex(NativeSliceError, 'zusätzliche Turmlayer'):
            self.export()
        self.assertFalse(self.output.exists())
        self.generated.prepared.composed.extra_layer_base_z = .4
        exported = self.export()
        report = NativeExportReport.read(exported.path)
        self.assertEqual(report.minimum_verified_layer_time_s, 10.)
        self.assertTrue(report.extra_layer)
        self.assertIn('unberücksichtigt', exported.user_report_path.read_text(encoding='utf-8'))

    def test_cancellation_during_report_cleans_only_incomplete_run(self):
        from cooling_tower.native_project import export
        cancelled = Event()
        real = export.atomic_export_data
        def write_and_cancel(*args,**options):
            result = real(*args,**options)
            cancelled.set()
            return result
        with patch.object(export,'atomic_export_data',side_effect=write_and_cancel):
            with self.assertRaises(NativeOperationCancelled):
                self.export(cancellation_event=cancelled)
        self.assertEqual(list(self.output.iterdir()),[])
        self.assertEqual(self.source.read_bytes(),b'unchanged original')

    def test_slicer_directory_is_rejected_without_creating_export(self):
        self.output = self.generated.prepared.installation.executable_path.parent/'exports'
        with self.assertRaises(ProtectedWritePathError):
            self.export()
        self.assertFalse(self.output.exists())


if __name__ == '__main__':
    unittest.main()
