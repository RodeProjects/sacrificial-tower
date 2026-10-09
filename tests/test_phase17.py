from __future__ import annotations

import json
import os
import sys
import tempfile
import time
import unittest
from pathlib import Path
from threading import Event
from types import SimpleNamespace
from unittest.mock import patch


PROJECT_ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = PROJECT_ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("COOLING_TOWER_DISABLE_SLICER_DISCOVERY", "1")

from PySide6.QtCore import QCoreApplication, QPoint, QPointF, Qt
from PySide6.QtGui import QWheelEvent
from PySide6.QtWidgets import QApplication, QMessageBox
from PySide6.QtTest import QTest

from cooling_tower.config import SETTINGS_SCHEMA_VERSION
from cooling_tower.gui.background_jobs import JobKind
from cooling_tower.gui.main_window import MainWindow
from cooling_tower.gui.settings_store import UserSettingsStore
from cooling_tower.gui.preview_dialog import PreviewDialog
from cooling_tower.gui.widgets import PreviewCanvas, WheelSafeComboBox
from cooling_tower.models import (
    BedBounds,
    CalibrationConfig,
    CalibrationFailureCode,
    CalibrationMode,
    CalibrationState,
    GenerationSettings,
    ProfileFeasibilityAssessment,
    SourceArtifact,
    TowerPlacement,
)
from cooling_tower.preview import (
    LineSegment3D,
    OutputMode,
    Point3D,
    PreviewCancelled,
    PreviewExportService,
    PreviewRequest,
    PreviewResult,
    PreviewScene,
    PreviewService,
    PreviewState,
    StalePreviewError,
    extract_deposition_toolpaths,
)
from cooling_tower.services import GCodeAnalysisService, assess_tower_need
from cooling_tower.slicers import (
    SlicerCapability,
    SlicerDiscoveryResult,
    SlicerDiscoverySource,
    SlicerGuiState,
    SlicerInstallation,
    SlicerSupportLevel,
)
from cooling_tower.slicers.profile_models import ProfileMatchState
from cooling_tower.tower.mesh_generator import automatic_mesh_segments


def source_gcode(layer_count: int = 4, moves_per_layer: int = 4) -> str:
    lines = ["; phase17", "G90", "M83", "M204 S1000"]
    for layer in range(1, layer_count + 1):
        z = layer * 0.2
        lines.append(f"G1 Z{z:.2f} F600")
        x = 10.0 + layer
        y = 10.0
        for move in range(moves_per_layer):
            x += 1.0
            y += 0.5 if move % 2 else 1.0
            lines.append(f"G1 X{x:.3f} Y{y:.3f} E0.4 F900")
    return "\n".join(lines) + "\n"


def preview_scene() -> PreviewScene:
    segment = LineSegment3D(Point3D(0, 0, 0.2), Point3D(10, 10, 0.2))
    tower = LineSegment3D(Point3D(20, 20, 0), Point3D(20, 20, 5))
    return PreviewScene(
        (segment,),
        (tower,),
        BedBounds(0, 100, 0, 100),
        (20, 20),
        1,
        1,
        5,
    )


class SyntheticSuccessfulCalibrator:
    """Small deterministic slicer stand-in for preview/export UI tests."""

    def calibrate(self, _snapshot, _settings, **kwargs):
        root = Path(kwargs["output_directory"])
        root.mkdir(parents=True, exist_ok=True)
        artifact = root / "tower.stl"
        artifact.write_text("solid tower\nendsolid tower\n", encoding="utf-8")
        profile = SimpleNamespace(
            points=(
                SimpleNamespace(outer_radius_mm=5.0, z_mm=0.2),
                SimpleNamespace(outer_radius_mm=6.0, z_mm=5.0),
            ),
            layers=(),
        )
        return SimpleNamespace(
            state=CalibrationState.CONVERGED,
            success=True,
            has_usable_improvement=True,
            profile=profile,
            placement=TowerPlacement(
                80.0,
                20.0,
                6.0,
                BedBounds(0.0, 100.0, 0.0, 100.0),
                25.0,
            ),
            warnings=(),
            failures=(),
            gcode_path=None,
            stl_path=artifact,
            project_path=None,
            iterations=(),
            best_iteration=None,
            configured_iteration_count=kwargs["config"].maximum_iterations,
        )


class Phase17Tests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.source = self.root / "object.gcode"
        self.source.write_text(source_gcode(), encoding="utf-8")
        self.snapshot = GCodeAnalysisService().analyze(self.source)

    def tearDown(self) -> None:
        self.app.processEvents()
        self.temporary.cleanup()

    def request(self, **changes) -> PreviewRequest:
        values = {
            "snapshot": self.snapshot,
            "settings": GenerationSettings(),
            "output_mode": OutputMode.STL,
            "calibration_config": CalibrationConfig(mode=CalibrationMode.STL),
            "slicer_identity_key": "synthetic-slicer",
            "profile_fingerprint": "synthetic-profile",
            "effective_profile": SimpleNamespace(
                effective_values={
                    "printable_area": [
                        [0, 0],
                        [100, 0],
                        [100, 100],
                        [0, 100],
                    ]
                }
            ),
            "adapter": object(),
            "maximum_object_segments": 200,
        }
        values.update(changes)
        return PreviewRequest(**values)

    def window(self, **kwargs) -> MainWindow:
        return MainWindow(
            user_settings_path=self.root / "user_settings.json",
            **kwargs,
        )

    def complete_source_step(self, window: MainWindow) -> None:
        window.workflow.set_slicer_step_visible(True)
        window.workflow.source_validation_succeeded(
            "referenz.stl geprüft",
            analysis_complete=True,
        )

    @staticmethod
    def installation(root: Path, name: str, *, verified: bool = True):
        executable = root / f"{name}.exe"
        executable.write_bytes(b"MZ")
        return SlicerInstallation(
            adapter_id="synthetic",
            product_name=name,
            version="1.0",
            executable_path=executable,
            verified=verified,
            capabilities=frozenset({SlicerCapability.CLI_SLICE}),
            discovery_source=SlicerDiscoverySource.MANUAL,
            support_level=SlicerSupportLevel.FULL,
        )

    def ready_window(self, **kwargs) -> MainWindow:
        kwargs.setdefault(
            "preview_service",
            PreviewService(SyntheticSuccessfulCalibrator()),
        )
        window = self.window(**kwargs)
        original_stl = self.root / "object.stl"
        original_stl.write_text(
            "solid object\nendsolid object\n",
            encoding="utf-8",
        )
        window.current_source_path = original_stl.resolve()
        window.source_artifact = SourceArtifact.capture(original_stl)
        window.current_gcode_path = self.source
        window.analysis_snapshot = self.snapshot
        installation = self.installation(self.root, "ReadySlicer")
        window.slicer_discovery_result = SlicerDiscoveryResult(
            (installation,),
            installation.identity_key,
            SlicerGuiState.AVAILABLE,
            "Slicer verfügbar",
        )
        window.slicer_combo.addItem(
            installation.display_name,
            installation.identity_key,
        )
        effective_profile = SimpleNamespace(
            effective_values={
                "printable_area": [
                    [0, 0],
                    [100, 0],
                    [100, 100],
                    [0, 100],
                ]
            }
        )
        window.profile_match_result = SimpleNamespace(
            selected=SimpleNamespace(
                effective_profile=effective_profile,
                bundle_id="ready-bundle",
            ),
            can_use_stl_mode=True,
            execution_slicer=installation,
            inventory_fingerprint="ready-inventory",
            user_confirmed=True,
        )
        window.slicer_service = SimpleNamespace(
            adapter_for=lambda _installation: object()
        )
        settings = window.collect_settings()
        window.tower_assessment = assess_tower_need(self.snapshot, settings)
        window.profile_feasibility = ProfileFeasibilityAssessment(True, True)
        window.validate_form()
        return window

    def test_01_only_verified_slicers_appear(self) -> None:
        window = self.window()
        verified = self.installation(self.root, "Verified")
        unverified = self.installation(self.root, "Unverified", verified=False)
        result = SlicerDiscoveryResult(
            (unverified, verified), verified.identity_key,
            SlicerGuiState.AVAILABLE_AND_RECOMMENDED, "Erkennung abgeschlossen",
        )
        window._slicer_request_id = 7
        window._on_slicer_discovery_succeeded(7, result)
        self.assertEqual(window.slicer_combo.count(), 1)
        self.assertEqual(window.slicer_combo.currentData(), verified.identity_key)
        window.close()

    def test_02_last_used_slicer_is_preselected_and_labelled(self) -> None:
        window = self.window()
        first = self.installation(self.root, "First")
        second = self.installation(self.root, "Second")
        result = SlicerDiscoveryResult(
            (first, second), second.identity_key,
            SlicerGuiState.AVAILABLE_AND_RECOMMENDED, "Erkennung abgeschlossen",
            last_used_key=second.identity_key,
        )
        window._slicer_request_id = 1
        window._on_slicer_discovery_succeeded(1, result)
        self.assertEqual(window.slicer_combo.currentData(), second.identity_key)
        self.assertIn("zuletzt verwendet", window.slicer_combo.currentText())
        self.assertNotIn("empfohlen", window.slicer_combo.currentText())
        window.close()

    def test_02b_single_slicer_has_no_last_used_suffix(self) -> None:
        window = self.window()
        installation = self.installation(self.root, "Only")
        result = SlicerDiscoveryResult(
            (installation,),
            installation.identity_key,
            SlicerGuiState.AVAILABLE,
            "Erkennung abgeschlossen",
            last_used_key=installation.identity_key,
        )
        window._slicer_request_id = 1
        window._on_slicer_discovery_succeeded(1, result)
        self.assertEqual(
            window.slicer_combo.currentText(),
            installation.display_name,
        )
        window.close()

    def test_02c_refresh_switches_to_newly_last_used_slicer(self) -> None:
        window = self.window()
        first = self.installation(self.root, "First")
        second = self.installation(self.root, "Second")
        window._slicer_request_id = 1
        window._on_slicer_discovery_succeeded(
            1,
            SlicerDiscoveryResult(
                (first, second),
                first.identity_key,
                SlicerGuiState.AVAILABLE_AND_RECOMMENDED,
                "Erkennung abgeschlossen",
                last_used_key=first.identity_key,
            ),
        )
        self.assertEqual(window.slicer_combo.currentData(), first.identity_key)

        window._slicer_request_id = 2
        window._on_slicer_discovery_succeeded(
            2,
            SlicerDiscoveryResult(
                (first, second),
                second.identity_key,
                SlicerGuiState.AVAILABLE_AND_RECOMMENDED,
                "Erkennung aktualisiert",
                last_used_key=second.identity_key,
            ),
        )

        self.assertEqual(window.slicer_combo.currentData(), second.identity_key)
        self.assertIn("zuletzt verwendet", window.slicer_combo.currentText())
        window.close()

    def test_03_user_can_select_another_slicer(self) -> None:
        window = self.window()
        first = self.installation(self.root, "First")
        second = self.installation(self.root, "Second")
        result = SlicerDiscoveryResult(
            (first, second), first.identity_key,
            SlicerGuiState.AVAILABLE_AND_RECOMMENDED, "Erkennung abgeschlossen",
        )
        window._slicer_request_id = 1
        window._on_slicer_discovery_succeeded(1, result)
        window.slicer_combo.setCurrentIndex(1)
        self.assertEqual(window.selected_slicer_installation, second)
        window.close()

    def test_04_slicer_change_discards_profiles_and_preview(self) -> None:
        window = self.window()
        first = self.installation(self.root, "First")
        second = self.installation(self.root, "Second")
        result = SlicerDiscoveryResult(
            (first, second), first.identity_key,
            SlicerGuiState.AVAILABLE_AND_RECOMMENDED, "Erkennung abgeschlossen",
        )
        window._slicer_request_id = 1
        window._on_slicer_discovery_succeeded(1, result)
        window.current_preview = SimpleNamespace()
        window.preview_state = PreviewState.CURRENT
        window.profile_match_result = SimpleNamespace(selected=object())
        window.slicer_combo.setCurrentIndex(1)
        self.assertIsNone(window.profile_match_result)
        self.assertEqual(window.preview_state, PreviewState.EMPTY)
        self.assertIsNone(window.current_preview)
        window.close()

    def test_05_main_status_remains_evidence_neutral(self) -> None:
        window = self.window()
        text = " ".join(
            (window.slicer_status_label.text(), window.slicer_detail_label.text())
        ).casefold()
        self.assertNotIn("definitiv", text)
        self.assertNotIn("garantiert", text)
        self.assertIn("nicht", text)
        window.close()

    def test_06_reconstructed_origin_is_labelled(self) -> None:
        window = self.window()
        result = SimpleNamespace(state=ProfileMatchState.RECONSTRUCTED)
        self.assertIn("rekonstruiert", window._profile_origin_text(result))
        window.close()

    def test_07_ambiguous_origin_requests_confirmation(self) -> None:
        window = self.window()
        result = SimpleNamespace(state=ProfileMatchState.AMBIGUOUS)
        self.assertIn("Bestätigung", window._profile_origin_text(result))
        window.close()

    def test_08_gui_offers_only_stl_export(self) -> None:
        window = self.window()
        self.assertEqual(
            window.stl_mode_description.text(),
            "STL-Dateien bleiben allgemein anpassbar.",
        )
        self.assertIs(window.output_mode, OutputMode.STL)
        self.assertFalse(hasattr(window, "stl_mode_radio"))
        self.assertFalse(hasattr(window, "gcode_mode_radio"))
        self.assertFalse(hasattr(window, "gcode_mode_description"))
        window.close()

    def test_09_legacy_gcode_gui_setting_is_ignored(self) -> None:
        (self.root / "user_settings.json").write_text(
            json.dumps({"output_mode": "gcode"}),
            encoding="utf-8",
        )
        window = self.window()
        self.assertIs(window.output_mode, OutputMode.STL)
        self.assertFalse(hasattr(window, "gcode_mode_radio"))
        window.close()

    def test_10_stl_processing_requires_a_confirmed_slicer(self) -> None:
        window = self.window()
        window._refresh_stl_availability()
        self.assertIn("Slicer ist erforderlich", window.stl_mode_status.text())
        self.assertNotIn("Fallback", window.stl_mode_status.text())
        window.close()

    def test_11_preview_is_not_computed_until_requested(self) -> None:
        class CountingService:
            calls = 0

            def prepare(self, *_args, **_kwargs):
                self.calls += 1

        service = CountingService()
        window = self.ready_window(preview_service=service)
        QCoreApplication.processEvents()
        self.assertEqual(service.calls, 0)
        self.assertEqual(window.preview_state, PreviewState.EMPTY)
        window.close()

    def test_12_preview_contains_object_and_tower(self) -> None:
        result = PreviewService(SyntheticSuccessfulCalibrator()).prepare(
            self.request()
        )
        self.assertTrue(result.scene.object_segments)
        self.assertTrue(result.scene.tower_segments)
        self.assertGreater(result.scene.tower_height_mm, 0)
        self.assertEqual(
            result.scene.object_height_mm,
            self.snapshot.maximum_print_z_mm,
        )
        self.assertEqual(
            result.scene.object_layer_count,
            self.snapshot.layer_count,
        )
        self.assertEqual(
            result.scene.tower_layer_count,
            len(result.calibration.profile.layers),
        )
        self.assertEqual(
            result.scene.tower_circle_segments,
            automatic_mesh_segments(result.calibration.profile),
        )
        result.dispose()

    def test_joint_slice_preview_reuses_object_lines_and_builds_current_tower(self) -> None:
        class ReportingCalibrator(SyntheticSuccessfulCalibrator):
            def calibrate(self, snapshot, settings, **kwargs):
                result = super().calibrate(snapshot, settings, **kwargs)
                kwargs["joint_progress_callback"](SimpleNamespace(
                    current_profile=result.profile,
                    placement=result.placement,
                ))
                return result

        scenes = []
        result = PreviewService(ReportingCalibrator()).prepare(
            self.request(), joint_scene_callback=scenes.append
        )
        self.assertEqual(len(scenes), 1)
        self.assertIs(scenes[0].object_segments, result.scene.object_segments)
        self.assertTrue(scenes[0].tower_segments)
        self.assertEqual(scenes[0].tower_center_xy_mm, (80.0, 20.0))
        self.assertEqual(scenes[0].tower_layer_count, result.scene.tower_layer_count)
        self.assertEqual(
            scenes[0].tower_circle_segments,
            automatic_mesh_segments(result.calibration.profile),
        )
        result.dispose()

    def test_13_large_toolpath_is_strictly_bounded(self) -> None:
        large = self.root / "large.gcode"
        large.write_text(source_gcode(80, 80), encoding="utf-8")
        segments, source_count = extract_deposition_toolpaths(
            large, expected_layer_count=80, maximum_segments=350
        )
        self.assertGreater(source_count, 6_000)
        self.assertLessEqual(len(segments), 350)

    def test_14_camera_rotate_pan_zoom_and_reset(self) -> None:
        canvas = PreviewCanvas()
        canvas.set_scene(preview_scene())
        canvas.apply_camera_state(
            {"yaw_deg": 42, "pitch_deg": 18, "zoom": 2, "pan_x": 30, "pan_y": -9}
        )
        self.assertEqual(canvas.camera_state()["yaw_deg"], 42)
        self.assertEqual(canvas.camera_state()["pan_x"], 30)
        canvas.reset_camera()
        state = canvas.camera_state()
        self.assertEqual(state["yaw_deg"], -38)
        self.assertEqual(state["pan_x"], 0)

    def test_15_setting_change_marks_preview_stale(self) -> None:
        window = self.ready_window()
        window.preview_dialog.canvas.set_scene(preview_scene())
        original_value = window.target_time_spin.value()
        original_signature = window._current_preview_request().signature()
        window.current_preview = SimpleNamespace(
            request_signature=original_signature,
            minimum_verified_layer_time_s=None,
        )
        window.preview_state = PreviewState.CURRENT
        window.target_time_spin.setValue(original_value + 1)
        self.assertEqual(window.preview_state, PreviewState.STALE)
        self.assertEqual(
            window.status_label.text(),
            "Einstellungen geändert",
        )
        self.assertTrue(window.preview_hint_label.isHidden())
        self.assertIn("Veraltet", window.preview_dialog.state_label.text())
        window.profile_feasibility = ProfileFeasibilityAssessment(True, True)
        window.validate_form()
        self.assertFalse(window.export_button.isEnabled())
        self.assertTrue(window.preview_button.isEnabled())
        self.assertEqual(window.preview_button.text(), "Kühlturm aktualisieren")

        window.target_time_spin.setValue(original_value)
        window.profile_feasibility = ProfileFeasibilityAssessment(True, True)
        window.validate_form()
        self.assertEqual(window.preview_state, PreviewState.CURRENT)
        self.assertEqual(window.preview_dialog.state, PreviewState.CURRENT)
        self.assertIn("Aktuell", window.preview_dialog.state_label.text())
        self.assertTrue(window.preview_hint_label.isHidden())
        self.assertTrue(window.export_button.isEnabled())
        window.current_preview = None
        window.close()

    def test_16_camera_change_does_not_mark_preview_stale(self) -> None:
        window = self.window()
        window.current_preview = SimpleNamespace()
        window.preview_state = PreviewState.CURRENT
        window.preview_dialog.canvas.front_view()
        self.assertEqual(window.preview_state, PreviewState.CURRENT)
        window.current_preview = None
        window.close()

    def test_17_service_rejects_stale_preview(self) -> None:
        request = self.request()
        result = PreviewService(SyntheticSuccessfulCalibrator()).prepare(request)
        changed = self.request(
            settings=GenerationSettings(target_layer_time_s=23.0)
        )
        with self.assertRaises(StalePreviewError):
            PreviewExportService().export(result, changed, self.root / "out")
        result.dispose()

    def test_18_current_preview_exports_and_writes_integrity_report(self) -> None:
        request = self.request()
        preview = PreviewService(SyntheticSuccessfulCalibrator()).prepare(request)
        result = PreviewExportService().export(preview, request, self.root / "out")
        self.assertTrue(result.output_path.is_file())
        report = json.loads(result.report_path.read_text(encoding="utf-8"))
        self.assertEqual(report["preview_signature"], request.signature())
        self.assertEqual(report["output_sha256"], result.output_sha256)
        self.assertEqual(report["technical_report_schema_version"], 2)
        self.assertIn("calibration", report)
        self.assertIn("source", report)
        self.assertIn("request", report)
        protection = report["request"]["slicer_file_protection"]
        self.assertEqual(protection["source_profiles_access"], "read_only")
        self.assertTrue(protection["calibration_uses_temporary_profile_copies"])
        self.assertEqual(
            protection["slicer_user_data_environment"],
            "isolated_temporary_directory",
        )
        self.assertTrue(result.user_report_path.is_file())
        self.assertIn(
            "Kurzbericht",
            result.user_report_path.read_text(encoding="utf-8"),
        )
        preview.dispose()

    def test_export_rechecks_copied_artifact_and_removes_partial_run(self) -> None:
        request = self.request()
        preview = PreviewService(SyntheticSuccessfulCalibrator()).prepare(request)
        output_root = self.root / "out"

        def replace_during_copy(_source: Path, destination: Path) -> None:
            Path(destination).write_bytes(b"changed during copy")

        with patch(
            "cooling_tower.preview.export_service.shutil.copy2",
            side_effect=replace_during_copy,
        ):
            with self.assertRaisesRegex(StalePreviewError, "während des Exports"):
                PreviewExportService().export(preview, request, output_root)

        self.assertTrue(output_root.is_dir())
        self.assertEqual(list(output_root.iterdir()), [])
        preview.dispose()

    def test_19_obsolete_background_result_cannot_replace_current(self) -> None:
        window = self.window()
        window._preview_request_id = 4
        artifact = self.root / "old.stl"
        artifact.write_bytes(b"old")
        old = PreviewResult(
            "old", OutputMode.STL, preview_scene(), artifact, "s", "a", False, "test"
        )
        current = SimpleNamespace(request_signature="current")
        window.current_preview = current
        window._on_preview_succeeded(3, old)
        self.assertIs(window.current_preview, current)
        window.current_preview = None
        window.close()

    def test_20_preview_cancellation_reaches_background_service(self) -> None:
        event = Event()
        event.set()
        with self.assertRaises(PreviewCancelled):
            extract_deposition_toolpaths(
                self.source,
                expected_layer_count=self.snapshot.layer_count,
                cancellation_event=event,
            )

    def test_21_settings_persist_camera_and_migrate_old_files(self) -> None:
        defaults = self.root / "defaults.json"
        defaults.write_text(
            json.dumps({"settings_schema_version": 2, **GenerationSettings().to_dict()}),
            encoding="utf-8",
        )
        user = self.root / "settings.json"
        user.write_text(
            json.dumps({"generation": {"minimum_radius_mm": 7.0}}),
            encoding="utf-8",
        )
        store = UserSettingsStore(user, defaults)
        migrated, _state = store.load()
        self.assertEqual(migrated.minimum_outer_radius_mm, 7.0)
        store.save(
            migrated,
            output_root="output",
            window_width=900,
            window_height=700,
            preview_iterations=8,
            preview_camera={"yaw_deg": 12.0},
        )
        payload = json.loads(user.read_text(encoding="utf-8"))
        self.assertEqual(
            payload["settings_schema_version"],
            SETTINGS_SCHEMA_VERSION,
        )
        self.assertNotIn("output_mode", payload)
        self.assertEqual(payload["preview_iterations"], 8)
        self.assertNotIn("preview_quality", payload)
        self.assertNotIn("slicer_iterations", payload)
        self.assertEqual(payload["preview_camera"]["yaw_deg"], 12.0)
        self.assertNotIn("preview_signature", payload)

    def test_22_gui_remains_laid_out_at_compact_and_large_sizes(self) -> None:
        window = self.window()
        window.show()
        self.app.processEvents()
        self.assertTrue(window.preview_button.isHidden())
        self.complete_source_step(window)
        window.workflow.slicer_succeeded("Testslicer")
        window.workflow.complete_preparation()
        window.automatic_generation_card.click()
        for width, height in ((720, 640), (1400, 1000)):
            window.resize(width, height)
            self.app.processEvents()
            self.assertGreaterEqual(window.settings_scroll.viewport().width(), 600)
            self.assertTrue(window.preview_button.isVisible())
        window.close()

    def test_23_spinboxes_and_reset_buttons_do_not_overlap(self) -> None:
        window = self.window()
        window.resize(900, 900)
        for group in (
            window.geometry_group,
            window.stability_group,
            window.geometry_settings_group,
        ):
            group.setChecked(True)
        window.show()
        self.app.processEvents()
        for item in window._setting_widgets.values():
            # Conditional rows (for example the manual stand-base width while
            # automatic calculation is active) intentionally stay hidden even
            # when their surrounding section is expanded.
            if not item.isVisible():
                continue
            editor_right = item.editor.mapToGlobal(item.editor.rect().topRight()).x()
            reset_left = item.reset_button.mapToGlobal(
                item.reset_button.rect().topLeft()
            ).x()
            self.assertLess(editor_right, reset_left)
            self.assertGreaterEqual(item.editor.width(), 68)
            self.assertGreaterEqual(item.reset_button.width(), 32)
        window.close()

    def test_24_gcode_preview_and_export_use_calibrated_artifact(self) -> None:
        class Calibrator:
            def calibrate(self, snapshot, _settings, **kwargs):
                root = Path(kwargs["output_directory"])
                root.mkdir(parents=True, exist_ok=True)
                artifact = root / "combined.gcode"
                artifact.write_bytes(snapshot.gcode_path.read_bytes())
                profile = SimpleNamespace(
                    points=(
                        SimpleNamespace(outer_radius_mm=5.0, z_mm=0.2),
                        SimpleNamespace(outer_radius_mm=7.0, z_mm=0.8),
                    )
                )
                bed = BedBounds(0, 100, 0, 100)
                return SimpleNamespace(
                    state=CalibrationState.CONVERGED,
                    success=True,
                    profile=profile,
                    placement=TowerPlacement(80, 20, 7, bed, 5),
                    warnings=(),
                    failures=(),
                    gcode_path=artifact,
                    stl_path=None,
                    iterations=(),
                )

        effective_profile = SimpleNamespace(
            effective_values={
                "printable_area": [[0, 0], [100, 0], [100, 100], [0, 100]]
            }
        )
        request = self.request(
            output_mode=OutputMode.GCODE,
            calibration_config=CalibrationConfig(mode=CalibrationMode.GCODE),
            adapter=object(),
            effective_profile=effective_profile,
            slicer_identity_key="verified",
            profile_fingerprint="profile",
        )
        preview = PreviewService(Calibrator()).prepare(request)
        self.assertTrue(preview.calibrated)
        self.assertEqual(preview.artifact_path.suffix, ".gcode")
        exported = PreviewExportService().export(
            preview, request, self.root / "gcode_output"
        )
        self.assertTrue(exported.output_path.name.endswith("_mit_kuehlturm.gcode"))
        preview.dispose()

    def test_25_export_requires_a_current_generation(self) -> None:
        window = self.ready_window()
        output = self.root / "direct_output"
        window.output_root_edit.setText(str(output))
        window.validate_form()
        self.assertIsNone(window.current_preview)
        self.assertFalse(window.export_button.isEnabled())
        self.assertTrue(window.preview_button.isEnabled())
        self.assertEqual(window.preview_button.text(), "Kühlturm generieren")
        window.start_export()
        self.assertFalse(
            window.background_job_manager.has_active(JobKind.EXPORT)
        )
        self.assertIsNone(window.last_export_result)
        self.assertIsNone(window.current_preview)
        self.assertTrue(window.open_run_button.isHidden())
        self.assertFalse(hasattr(window, "open_technical_report_button"))
        window.close()

    def test_25a_generation_is_exported_without_a_second_calibration(self) -> None:
        window = self.ready_window()
        window.warning_text.setPlainText("• Hinweis des vorherigen Kühlturms")
        window.result_label.setText("Veraltetes technisches Ergebnis")
        window.result_label.setToolTip("C:/old/result.stl")
        window._refresh_issue_panels()
        window.start_preview()
        self.assertFalse(window.warning_text.toPlainText())
        self.assertTrue(window.notice_panel.isHidden())
        self.assertFalse(window.result_label.text())
        self.assertFalse(window.result_label.toolTip())
        deadline = time.monotonic() + 10.0
        while (
            window.background_job_manager.has_active(JobKind.PREVIEW)
            and time.monotonic() < deadline
        ):
            self.app.processEvents()
            time.sleep(0.01)
        self.assertIsNotNone(window.current_preview)
        self.assertFalse(window.warning_text.toPlainText())
        self.assertTrue(window.notice_panel.isHidden())
        self.assertFalse(window.result_label.text())
        self.assertFalse(window.result_label.toolTip())
        self.assertEqual(window._calibration_config().maximum_iterations, 18)
        self.assertEqual(window._calibration_config().minimum_joint_slices, 3)
        self.assertEqual(window._calibration_config().maximum_joint_slices, 12)

        window.output_root_edit.setText(str(self.root / "exact_output"))
        window.validate_form()
        window.start_export()
        deadline = time.monotonic() + 10.0
        while (
            window.background_job_manager.has_active(JobKind.EXPORT)
            and time.monotonic() < deadline
        ):
            self.app.processEvents()
            time.sleep(0.01)

        self.assertIsNotNone(window.last_export_result)
        report = json.loads(
            window.last_export_result.report_path.read_text(encoding="utf-8")
        )
        self.assertEqual(
            report["calibration"]["configured_iteration_count"],
            18,
        )
        self.assertFalse(window.warning_text.toPlainText())
        self.assertTrue(window.notice_panel.isHidden())
        self.assertFalse(window.result_label.text())
        self.assertFalse(window.result_label.toolTip())
        window.close()

    def test_26_stale_preview_blocks_export_and_offers_update(self) -> None:
        window = self.ready_window()
        window.output_root_edit.setText(str(self.root / "confirmed_output"))
        window.current_preview = SimpleNamespace(request_signature="outdated")
        window.preview_state = PreviewState.STALE
        window.validate_form()
        self.assertFalse(window.export_button.isEnabled())
        self.assertTrue(window.preview_button.isEnabled())
        self.assertEqual(window.preview_button.text(), "Kühlturm aktualisieren")
        window.start_export()
        self.assertFalse(
            window.background_job_manager.has_active(JobKind.EXPORT)
        )
        self.assertIsNone(window.last_export_result)
        window.current_preview = None
        window.close()

    def test_27_reports_explain_failed_calibration_in_both_detail_levels(self) -> None:
        request = self.request()
        preview = PreviewService(SyntheticSuccessfulCalibrator()).prepare(request)
        preview.calibration = SimpleNamespace(
            state=CalibrationState.LIMIT_REACHED,
            mode=CalibrationMode.STL,
            failures=(
                SimpleNamespace(
                    code=CalibrationFailureCode.ITERATION_LIMIT,
                    message="Maximum iteration count reached with deficit.",
                    layer_index=12,
                    related_setting_names=("maximum_iterations",),
                ),
            ),
            iterations=(SimpleNamespace(), SimpleNamespace()),
            warnings=("Kalibrierungsgrenze erreicht.",),
        )
        preview.calibrated = False
        preview.slicer_optimized = False
        preview.generation_kind = "Slicer-Kalibrierung fehlgeschlagen"
        preview.warnings = (
            "Die Slicer-Kalibrierung erreichte kein verwendbares Ergebnis.",
        )
        result = PreviewExportService().export(
            preview, request, self.root / "failed_calibration_report"
        )
        technical = json.loads(result.report_path.read_text(encoding="utf-8"))
        calibration = technical["calibration"]
        self.assertTrue(calibration["attempted"])
        self.assertFalse(calibration["succeeded"])
        self.assertEqual(calibration["state"], "limit_reached")
        self.assertEqual(calibration["iteration_count"], 2)
        self.assertEqual(calibration["failures"][0]["code"], "iteration_limit")
        self.assertEqual(calibration["failures"][0]["layer_index"], 12)
        summary = result.user_report_path.read_text(encoding="utf-8")
        self.assertIn("Kein belastbares slicerbasiertes Resultat", summary)
        self.assertIn("erfolgreichen Slicerlauf", summary)
        self.assertIn("maximale Anzahl", summary)
        self.assertIn("Layer 12", summary)
        self.assertNotIn("Vorschau verwendet", summary)
        preview.dispose()

    def test_28_short_report_names_unknown_filament_profile_type(self) -> None:
        request = self.request()
        preview = PreviewService(SyntheticSuccessfulCalibrator()).prepare(request)
        preview.calibration = SimpleNamespace(
            state=CalibrationState.SLICER_FAILED,
            mode=CalibrationMode.STL,
            failures=(
                SimpleNamespace(
                    code=CalibrationFailureCode.SLICER_FAILURE,
                    message=(
                        "Der Slicer wurde mit Fehlercode 5 beendet. Slicer output: "
                        "unknown config type of file C:\\Profiles\\PLA User.json "
                        "in load-settings"
                    ),
                    layer_index=None,
                    related_setting_names=(),
                ),
            ),
            iterations=(),
            warnings=(),
        )
        preview.calibrated = False
        preview.slicer_optimized = False
        preview.generation_kind = "Slicer-Kalibrierung fehlgeschlagen"
        result = PreviewExportService().export(
            preview, request, self.root / "filament_failure_report"
        )
        summary = result.user_report_path.read_text(encoding="utf-8")
        self.assertIn("PLA User.json", summary)
        self.assertIn("keinen erkennbaren Profiltyp", summary)
        preview.dispose()

    def test_29_generation_has_one_fixed_quality_budget(self) -> None:
        window = self.window()
        self.assertEqual(
            Path(window.output_root_edit.text()),
            (PROJECT_ROOT / "output").resolve(),
        )
        self.assertNotIn("slicer_iterations", window._setting_widgets)
        self.assertFalse(hasattr(window, "preview_iteration_slider"))
        self.assertFalse(hasattr(window, "preview_fast_button"))
        self.assertFalse(hasattr(window, "preview_precise_button"))
        self.assertFalse(hasattr(window, "preview_quality_panel"))
        self.assertEqual(window.preview_iterations, 18)
        self.assertEqual(window._calibration_config().maximum_iterations, 18)
        self.assertEqual(window._calibration_config().minimum_joint_slices, 3)
        self.assertEqual(window._calibration_config().maximum_joint_slices, 12)
        self.assertFalse(
            window._calibration_config().perform_joint_final_slice
        )
        window.source_artifact = SimpleNamespace(
            source_kind=SimpleNamespace(value="stl")
        )
        self.assertTrue(
            window._calibration_config().perform_joint_final_slice
        )
        window.close()

    def test_joint_export_signature_accepts_matching_fast_preview_seed(self) -> None:
        fast = self.request(
            calibration_config=CalibrationConfig(
                maximum_iterations=4,
                perform_joint_final_slice=True,
                maximum_joint_slices=1,
            )
        )
        exact = self.request(
            calibration_config=CalibrationConfig(
                maximum_iterations=8,
                perform_joint_final_slice=True,
                maximum_joint_slices=5,
            )
        )
        resumed = self.request(
            calibration_config=CalibrationConfig(
                maximum_iterations=3,
                perform_joint_final_slice=True,
                maximum_joint_slices=3,
                completed_joint_slices_before_run=5,
            )
        )

        self.assertNotEqual(fast.signature(), exact.signature())
        self.assertNotEqual(exact.signature(), resumed.signature())
        self.assertEqual(
            fast.refinement_seed_signature(),
            exact.refinement_seed_signature(),
        )
        self.assertEqual(
            exact.refinement_seed_signature(),
            resumed.refinement_seed_signature(),
        )

    def test_exact_preview_build_reuses_matching_fast_preview_artifact(self) -> None:
        class SeedAwareCalibrator:
            def __init__(self) -> None:
                self.calls = []

            def calibrate(self, _snapshot, _settings, **kwargs):
                self.calls.append(kwargs)
                root = Path(kwargs["output_directory"])
                root.mkdir(parents=True, exist_ok=True)
                artifact = root / "tower.stl"
                artifact.write_bytes(b"synthetic tower")
                project = None
                if kwargs["config"].perform_joint_final_slice:
                    project = root / "joint.3mf"
                    project.write_bytes(b"synthetic project")
                profile = SimpleNamespace(
                    points=(
                        SimpleNamespace(outer_radius_mm=5.0, z_mm=0.0),
                        SimpleNamespace(outer_radius_mm=5.0, z_mm=0.8),
                    ),
                    layers=(),
                )
                return SimpleNamespace(
                    state=CalibrationState.CONVERGED,
                    success=True,
                    has_usable_improvement=True,
                    profile=profile,
                    placement=TowerPlacement(
                        80.0,
                        20.0,
                        5.0,
                        BedBounds(0.0, 100.0, 0.0, 100.0),
                        25.0,
                    ),
                    warnings=(),
                    failures=(),
                    gcode_path=None,
                    stl_path=artifact,
                    project_path=project,
                    iterations=(),
                    best_iteration=None,
                )

        original_stl = self.root / "original.stl"
        original_stl.write_bytes(b"synthetic source")
        artifact = SourceArtifact.capture(original_stl)
        profile = SimpleNamespace(
            effective_values={
                "printable_area": [[0, 0], [100, 0], [100, 100], [0, 100]]
            }
        )
        calibrator = SeedAwareCalibrator()
        service = PreviewService(calibrator)
        fast_request = self.request(
            calibration_config=CalibrationConfig(
                maximum_iterations=4,
                perform_joint_final_slice=True,
                maximum_joint_slices=1,
            ),
            adapter=object(),
            effective_profile=profile,
            source_artifact=artifact,
        )
        fast_preview = service.prepare(fast_request)
        exact_request = self.request(
            calibration_config=CalibrationConfig(
                maximum_iterations=8,
                perform_joint_final_slice=True,
                maximum_joint_slices=5,
            ),
            adapter=object(),
            effective_profile=profile,
            source_artifact=artifact,
        )

        exact_preview = service.prepare(
            exact_request,
            seed_preview=fast_preview,
        )

        self.assertEqual(len(calibrator.calls), 2)
        self.assertIs(
            calibrator.calls[1]["seed_profile"],
            fast_preview.calibration.profile,
        )
        self.assertEqual(
            calibrator.calls[1]["seed_stl_path"],
            fast_preview.artifact_path,
        )
        self.assertTrue(exact_preview.joint_sliced)
        resumed_request = self.request(
            calibration_config=CalibrationConfig(
                maximum_iterations=3,
                perform_joint_final_slice=True,
                maximum_joint_slices=3,
                completed_joint_slices_before_run=5,
            ),
            adapter=object(),
            effective_profile=profile,
            source_artifact=artifact,
        )
        resumed_preview = service.prepare(
            resumed_request,
            seed_preview=exact_preview,
        )
        self.assertEqual(len(calibrator.calls), 3)
        self.assertIs(
            calibrator.calls[2]["seed_profile"],
            exact_preview.calibration.profile,
        )
        self.assertEqual(
            calibrator.calls[2]["seed_stl_path"],
            exact_preview.artifact_path,
        )
        self.assertTrue(resumed_preview.joint_sliced)
        resumed_preview.dispose()
        exact_preview.dispose()
        fast_preview.dispose()

    def test_30_zero_slicer_iterations_are_rejected(self) -> None:
        with self.assertRaisesRegex(ValueError, "mindestens einen Slicer-Durchlauf"):
            self.request(
                settings=GenerationSettings(target_layer_time_s=13.0),
                calibration_config=CalibrationConfig(
                    mode=CalibrationMode.STL,
                    maximum_iterations=0,
                ),
            )

    def test_31_partial_slicer_improvement_is_explained_and_exported(self) -> None:
        request = self.request(
            settings=GenerationSettings(target_layer_time_s=15.0),
            calibration_config=CalibrationConfig(
                mode=CalibrationMode.STL,
                maximum_iterations=5,
            ),
        )
        preview = PreviewService(SyntheticSuccessfulCalibrator()).prepare(request)
        best = SimpleNamespace(
            number=2,
            maximum_remaining_deficit_s=0.537,
            deficient_layer_count=4,
            total_remaining_deficit_s=1.1,
        )
        preview.calibration = SimpleNamespace(
            state=CalibrationState.LIMIT_REACHED,
            mode=CalibrationMode.STL,
            failures=(
                SimpleNamespace(
                    code=CalibrationFailureCode.STALLED,
                    message="Repeated identical candidates cannot close the deficit.",
                    layer_index=None,
                    related_setting_names=(),
                ),
            ),
            iterations=(SimpleNamespace(number=1), best),
            warnings=(),
            configured_iteration_count=5,
            best_iteration_number=2,
            best_iteration=best,
            improved_over_initial_candidate=True,
        )
        preview.calibrated = False
        preview.slicer_optimized = True
        preview.generation_kind = "sliceroptimierter bester Zwischenstand"
        preview.minimum_verified_layer_time_s = 14.463
        preview.warnings = (
            "The calibrated STL is a timing prognosis; verify it.",
            "Temporary cooling overrides: slow_down_layer_time=0",
            "Calibration did not fully converge; candidate from iteration 2 retained.",
        )
        exported = PreviewExportService().export(
            preview,
            request,
            self.root / "partial_improvement",
        )
        summary = exported.user_report_path.read_text(encoding="utf-8")
        self.assertIn("bester Zwischenstand", summary)
        self.assertIn("Durchgeführt: 2 von maximal 5", summary)
        self.assertIn("Exportierter bester Durchlauf: 2", summary)
        self.assertIn("-0.537 s", summary)
        self.assertIn("Noch betroffene Layer: 4", summary)
        self.assertNotIn("Temporary cooling overrides", summary)
        self.assertNotIn("Calibration did not", summary)
        read_only_hint = (
            "Das Programm liest Slicer- und Profilinformationen ausschließlich "
            "zur Kühlturmerzeugung aus. Slicerdateien und Slicerprofile werden "
            "niemals verändert."
        )
        self.assertEqual(summary.count(read_only_hint), 1)
        self.assertLess(summary.index("Hinweise:"), summary.index(read_only_hint))
        technical = json.loads(exported.report_path.read_text(encoding="utf-8"))
        self.assertEqual(
            technical["summary"]["status"],
            "success_slicer_optimized_partial",
        )
        self.assertTrue(
            technical["diagnostic_guidance"]["uses_slicer_evaluated_candidate"]
        )
        preview.dispose()

    def test_32_gcode_mode_rejects_zero_slicer_iterations(self) -> None:
        with self.assertRaisesRegex(ValueError, "mindestens einen Slicer-Durchlauf"):
            self.request(
                output_mode=OutputMode.GCODE,
                calibration_config=CalibrationConfig(
                    mode=CalibrationMode.GCODE,
                    maximum_iterations=0,
                ),
                adapter=object(),
                effective_profile=object(),
            )

    def test_33_main_actions_fit_in_the_bottom_bar(self) -> None:
        window = self.window()
        window.resize(1100, 800)
        window.show()
        self.app.processEvents()
        for button in (
            window.open_stl_button,
            window.reset_button,
            window.preview_button,
            window.export_button,
        ):
            self.assertFalse(window.settings_scroll.isAncestorOf(button))
        for button in (
            window.open_stl_button,
            window.reset_button,
            window.preview_button,
            window.export_button,
        ):
            self.assertTrue(button.isHidden())
        self.complete_source_step(window)
        window.workflow.slicer_unavailable("Kein Slicer verfügbar")
        self.app.processEvents()
        self.assertTrue(window.reset_button.isHidden())
        window.workflow.slicer_succeeded("Testslicer")
        window.workflow.complete_preparation()
        window.automatic_generation_card.click()
        self.app.processEvents()
        for button in (
            window.open_stl_button,
            window.reset_button,
            window.preview_button,
        ):
            self.assertTrue(button.isVisible())
        self.assertTrue(window.export_button.isHidden())
        self.assertTrue(window.open_run_button.isHidden())
        self.assertFalse(hasattr(window, "open_technical_report_button"))
        self.assertEqual(
            window.reset_button.text(),
            "Standardwerte wiederherstellen",
        )
        self.assertEqual(window.export_button.text(), "Kühlturm exportieren")
        action_x = {
            button: button.mapTo(window, button.rect().topLeft()).x()
            for button in (
                window.open_output_button,
                window.open_stl_button,
                window.preview_action_control,
            )
        }
        self.assertLess(
            action_x[window.open_output_button],
            action_x[window.open_stl_button],
        )
        self.assertLess(
            action_x[window.open_stl_button],
            action_x[window.preview_action_control],
        )
        self.assertEqual(window.reset_button.parent().objectName(), "footerMessageArea")
        self.assertEqual(
            window.reset_button.height(),
            window.options_button.height(),
        )
        self.assertFalse(hasattr(window, "stl_info_button"))
        button_bottoms = {
            button.mapTo(window, button.rect().bottomLeft()).y()
            for button in (
                window.open_output_button,
                window.open_stl_button,
                window.preview_action_control,
            )
        }
        self.assertIn(len(button_bottoms), (1, 2))
        self.assertFalse(
            window.open_stl_button.geometry().intersects(
                window.preview_action_control.geometry()
            )
        )
        window.close()

    def test_34_output_folder_button_uses_compact_label_when_needed(self) -> None:
        window = self.window()
        self.complete_source_step(window)
        window.workflow.slicer_succeeded("Testslicer")
        window.workflow.complete_preparation()
        window.automatic_generation_card.click()
        window.show()
        window.resize(1000, 700)
        self.app.processEvents()
        self.assertEqual(window.open_stl_button.text(), "Letzten Export öffnen")
        window.resize(720, 640)
        self.app.processEvents()
        self.assertEqual(window.open_stl_button.text(), "Letzter Export")
        window.close()

    def test_35_preview_progress_step_is_below_progress_bar(self) -> None:
        dialog = PreviewDialog()
        dialog.set_building("Geometrie wird berechnet …")
        dialog.set_progress(25, "Werkzeugwege werden ausgewertet …")
        dialog.show()
        self.app.processEvents()
        self.assertTrue(dialog.progress.isVisible())
        self.assertTrue(dialog.progress_status_label.isVisible())
        self.assertEqual(
            dialog.progress_status_label.text(),
            "Werkzeugwege werden ausgewertet …",
        )
        self.assertGreater(
            dialog.progress_status_label.mapTo(dialog, QPoint(0, 0)).y(),
            dialog.progress.mapTo(dialog, QPoint(0, 0)).y(),
        )
        dialog.close()

    def test_42_preview_quality_failures_are_bounded_and_deduplicated(self) -> None:
        repeated = tuple(
            SimpleNamespace(message="Die benötigte Layertime ist nicht erreichbar.")
            for _index in range(80)
        )
        additional = tuple(
            SimpleNamespace(message=f"Zusätzlicher Grund {index}")
            for index in range(5)
        )

        lines = PreviewDialog._summarized_failures(repeated + additional)

        self.assertLessEqual(len(lines), 4)
        self.assertEqual(
            sum("Die benötigte Layertime" in line for line in lines),
            1,
        )
        self.assertIn("(80×)", lines[0])
        self.assertIn("Weitere", lines[-1])
        dialog = PreviewDialog()
        self.assertLessEqual(dialog.quality_label.maximumHeight(), 260)
        dialog.close()

    def test_36_mouse_wheel_does_not_change_values_or_closed_dropdowns(self) -> None:
        window = self.window()
        window.target_time_spin.setValue(11.0)
        window.slicer_combo.addItem("Zweite Auswahl", "second")
        window.slicer_combo.setCurrentIndex(0)

        def wheel_event(delta: int) -> QWheelEvent:
            return QWheelEvent(
                QPointF(5, 5),
                QPointF(5, 5),
                QPoint(0, 0),
                QPoint(0, delta),
                Qt.MouseButton.NoButton,
                Qt.KeyboardModifier.NoModifier,
                Qt.ScrollPhase.ScrollUpdate,
                False,
            )

        QApplication.sendEvent(window.target_time_spin, wheel_event(120))
        QApplication.sendEvent(window.slicer_combo, wheel_event(-120))
        self.assertEqual(window.target_time_spin.value(), 11.0)
        self.assertEqual(window.slicer_combo.currentIndex(), 0)

        combo = WheelSafeComboBox()
        combo.addItems([f"Eintrag {number}" for number in range(100)])
        combo.setMaxVisibleItems(5)
        combo.resize(180, 32)
        combo.show()
        combo.showPopup()
        self.app.processEvents()
        scrollbar = combo.view().verticalScrollBar()
        before_scroll = scrollbar.value()
        QApplication.sendEvent(combo.view().viewport(), wheel_event(-120))
        self.app.processEvents()
        self.assertGreater(scrollbar.value(), before_scroll)
        self.assertEqual(combo.currentIndex(), 0)
        combo.hidePopup()
        combo.setCurrentIndex(combo.count() - 1)
        combo.showPopup()
        QTest.qWait(10)
        self.app.processEvents()
        self.assertEqual(scrollbar.value(), scrollbar.minimum())
        self.assertEqual(combo.currentIndex(), combo.count() - 1)
        combo.hidePopup()
        combo.close()
        window.close()

    def test_37_default_maximum_outer_diameter_is_forty_mm(self) -> None:
        self.assertEqual(GenerationSettings().maximum_outer_diameter_mm, 40.0)
        window = self.window()
        window.reset_defaults()
        self.assertEqual(window.maximum_outer_spin.value(), 40.0)
        window.close()

    def test_38_disabled_export_always_shows_a_reason(self) -> None:
        window = self.window()
        window.show()
        self.app.processEvents()
        self.assertFalse(window.export_button.isEnabled())
        self.assertFalse(window.action_availability_widget.isVisible())
        self.assertFalse(window.export_availability_label.text())
        window.close()

        ready = self.ready_window()
        self.complete_source_step(ready)
        ready.workflow.slicer_succeeded("Testslicer")
        ready.workflow.complete_preparation()
        ready.automatic_generation_card.click()
        ready.show()
        self.app.processEvents()
        self.assertFalse(ready.export_button.isEnabled())
        self.assertTrue(ready.preview_button.isEnabled())
        self.assertFalse(ready.action_availability_widget.isVisible())
        ready.maximum_outer_spin.setValue(1.0)
        ready.validate_form()
        self.app.processEvents()
        self.assertFalse(ready.export_button.isEnabled())
        self.assertTrue(ready.action_availability_widget.isVisible())
        self.assertIn("korrigieren", ready.export_availability_label.text())
        ready.close()

    def test_39_invalid_input_cannot_bypass_validation(self) -> None:
        window = self.ready_window()
        self.complete_source_step(window)
        window.workflow.slicer_succeeded("Testslicer")
        window.workflow.complete_preparation()
        window.automatic_generation_card.click()
        window.show()
        self.app.processEvents()

        self.assertFalse(hasattr(window, "validation_bypass_checkbox"))

        window.maximum_outer_spin.setValue(1001.0)
        window.validate_form()
        self.app.processEvents()
        maximum_outer_setting = window._setting_widgets[
            "maximum_outer_diameter_mm"
        ]
        self.assertTrue(maximum_outer_setting.editor.property("invalid"))
        self.assertTrue(window.validation_label.text().strip())
        self.assertFalse(window.export_button.isEnabled())

        window.close()

    def test_41_preview_quality_summary_explains_selected_passes_and_refreshes(self) -> None:
        dialog = PreviewDialog()
        unstable_iteration = SimpleNamespace(
            maximum_remaining_deficit_s=0.42,
            deficient_layer_count=2,
            maximum_slicer_result_change_s=0.31,
            maximum_profile_change_mm=0.06,
            evaluation=SimpleNamespace(maximum_metadata_difference_s=0.9),
        )
        unstable_calibration = SimpleNamespace(
            configured_iteration_count=5,
            iterations=(
                SimpleNamespace(),
                SimpleNamespace(),
                SimpleNamespace(),
                SimpleNamespace(),
                unstable_iteration,
            ),
            failures=(SimpleNamespace(message="Ergebnisse blieben instabil."),),
        )
        first = SimpleNamespace(
            scene=preview_scene(),
            calibrated=False,
            slicer_optimized=True,
            output_mode=OutputMode.STL,
            calibration=unstable_calibration,
            minimum_verified_layer_time_s=11.58,
            target_layer_time_s=12.0,
            calibration_time_tolerance_s=0.2,
            calibration_slicer_result_tolerance_s=0.25,
            calibration_profile_tolerance_mm=0.1,
            calibration_metadata_tolerance_s=0.75,
        )

        dialog.set_preview(first)
        summary = dialog.quality_label.text()
        self.assertIn("Prognose noch nicht bestätigt", summary)
        self.assertIn("Prüfdurchläufe: 5 von maximal 5", summary)
        self.assertNotIn("Messwerte des letzten Durchlaufs", summary)
        self.assertNotIn("Ergebnisse blieben instabil", summary)
        self.assertNotIn("Grund", summary)
        self.assertEqual(dialog.quality_label.property("state"), "warning")
        self.assertFalse(dialog.quality_details_toggle.isHidden())
        self.assertFalse(dialog.quality_details_toggle.isChecked())
        self.assertTrue(dialog.quality_details_label.isHidden())
        details = dialog.quality_details_label.text()
        self.assertIn("0.420 s > 0.200 s", details)
        self.assertIn("0.310 s > 0.250 s", details)
        self.assertNotIn("0.060 mm", details)
        self.assertIn("0.900 s > 0.750 s", details)
        self.assertIn("Ergebnisse blieben instabil", details)
        dialog.quality_details_toggle.click()
        self.assertFalse(dialog.quality_details_label.isHidden())

        tolerated = SimpleNamespace(
            **{
                **first.__dict__,
                "minimum_verified_layer_time_s": 11.82,
            }
        )
        dialog.set_preview(tolerated)
        tolerated_summary = dialog.quality_label.text()
        self.assertIn("Mindest-Layerzeit erreicht", tolerated_summary)
        self.assertIn("-0.180 s", tolerated_summary)
        self.assertNotIn("Ergebnisse blieben instabil", tolerated_summary)
        self.assertEqual(dialog.quality_label.property("state"), "warning")
        self.assertIn(
            "Ergebnisse blieben instabil",
            dialog.quality_details_label.text(),
        )

        stable_iteration = SimpleNamespace(
            maximum_remaining_deficit_s=0.05,
            deficient_layer_count=0,
            maximum_slicer_result_change_s=0.04,
            maximum_profile_change_mm=0.01,
            evaluation=SimpleNamespace(maximum_metadata_difference_s=0.1),
        )
        second = SimpleNamespace(
            scene=preview_scene(),
            calibrated=True,
            slicer_optimized=False,
            output_mode=OutputMode.STL,
            calibration=SimpleNamespace(
                configured_iteration_count=2,
                iterations=(SimpleNamespace(), stable_iteration),
                failures=(),
            ),
            minimum_verified_layer_time_s=11.95,
            target_layer_time_s=12.0,
            calibration_time_tolerance_s=0.2,
            calibration_slicer_result_tolerance_s=0.25,
            calibration_profile_tolerance_mm=0.1,
            calibration_metadata_tolerance_s=0.75,
        )

        dialog.set_preview(second)
        refreshed = dialog.quality_label.text()
        self.assertIn("Prognose bestätigt", refreshed)
        self.assertIn("Prüfdurchläufe: 2 von maximal 2", refreshed)
        self.assertNotIn("0.040 s ≤ 0.150 s", refreshed)
        self.assertNotIn("0.310 s", refreshed)
        self.assertNotIn("Ergebnisse blieben instabil", refreshed)
        self.assertEqual(dialog.quality_label.property("state"), "success")
        self.assertEqual(dialog.quality_details_label.text(), "")
        self.assertNotIn("0.310 s", dialog.quality_details_label.text())
        self.assertFalse(dialog.quality_details_toggle.isChecked())
        self.assertTrue(dialog.quality_details_label.isHidden())

        dialog.set_building("Neue Vorschau wird erstellt")
        self.assertIn("mit der neuen Vorschau aktualisiert", dialog.quality_label.text())
        self.assertNotIn("Prognose bestätigt", dialog.quality_label.text())
        self.assertTrue(dialog.quality_details_toggle.isHidden())
        dialog.close()

    def test_41a_joint_quality_summary_excludes_isolated_slices(self) -> None:
        isolated = tuple(
            SimpleNamespace(joint_slice=False) for _index in range(6)
        )
        joint = tuple(
            SimpleNamespace(joint_slice=True) for _index in range(8)
        )
        result = SimpleNamespace(
            calibration=SimpleNamespace(
                configured_iteration_count=21,
                iterations=isolated + joint,
            ),
            calibrated=True,
            joint_sliced=True,
            slicer_optimized=True,
            completed_joint_slice_count=8,
            configured_joint_slice_count=15,
            minimum_verified_layer_time_s=11.05,
            target_layer_time_s=11.0,
            calibration_time_tolerance_s=0.25,
        )

        summary, state = PreviewDialog._quality_summary(
            result,
            compact=True,
        )

        self.assertEqual(state, "success")
        self.assertIn("Gemeinsame Slices: 8 von maximal 15", summary)
        self.assertNotIn("14 von maximal 21", summary)


if __name__ == "__main__":
    unittest.main()
