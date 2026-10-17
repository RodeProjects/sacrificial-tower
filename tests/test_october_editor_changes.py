"""Regression cases for profile restoration, simulations and preview editing."""
import os
import sys
import tempfile
import time
import unittest
import zipfile
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch, PropertyMock
from xml.etree import ElementTree

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("COOLING_TOWER_DISABLE_SLICER_DISCOVERY", "1")
from PySide6.QtCore import Qt, QSignalBlocker
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QStyle, QStyleOptionSlider
from cooling_tower.gui.main_window import MainWindow, _PROFILE_CONTENT_ROLE
from cooling_tower.gui.manual_panel import ManualGenerationPanel
from cooling_tower.gui.layer_range_dialog import LayerRangeDialog
from cooling_tower.gui.background_jobs import BackgroundJobManager
from cooling_tower.gui.generation_panel import GenerationPanel
from cooling_tower.gui.widgets.object_resolution_control import ObjectResolutionControl
from cooling_tower.models import GenerationSettings
from cooling_tower.preview import PreviewState
from cooling_tower.slicers.support_simulation import global_supports_disabled
from cooling_tower.slicers import ProfileCatalog, ProfileRecord, ProfileKind, ProfileSelectionReference
from cooling_tower.calibration.joint_project import MODEL_SETTINGS_PATH, validate_joint_project
from cooling_tower.manual.service import ManualExportService
from test_manual_generation import create_fixture
from gui_lifecycle import dispose_test_widget


class EditorChangesTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def panel(self):
        f, service, ref, request, adapter = create_fixture(self, joint=True, count=100)
        panel = ManualGenerationPanel()
        panel.initialize(ref)
        panel.set_busy(False)
        panel.show()
        self.app.processEvents()
        self.addCleanup(dispose_test_widget, panel)
        return panel, (f, service, ref, request, adapter)

    def test_history_coalesces_drag_redoes_and_clears_redo_on_branch(self):
        p, _ = self.panel()
        original = p.draft
        p._begin_interaction()
        p.move("base", 12, 8)
        p.move("base", 15, 8)
        p._end_interaction()
        edited = p.draft
        self.assertEqual(len(p._undo_stack), 1)
        p.canvas.undo_button.click()
        self.assertEqual(p.draft, original)
        self.assertTrue(p.canvas.redo_button.isEnabled())
        p.canvas.redo_button.click()
        self.assertEqual(p.draft, edited)
        p.canvas.setFocus()
        QTest.keyClick(p.canvas, Qt.Key.Key_Z, Qt.KeyboardModifier.ControlModifier)
        self.assertEqual(p.draft, original)
        QTest.keyClick(p.canvas, Qt.Key.Key_Y, Qt.KeyboardModifier.ControlModifier)
        self.assertEqual(p.draft, edited)
        p.undo()
        p.insert(12)
        self.assertFalse(p.canvas.redo_button.isEnabled())
        p.undo()
        self.assertEqual(p.draft, original)
        p.set_busy(True)
        self.assertFalse(p.canvas.undo_button.isEnabled())

    def test_undo_removed_point_restores_curve_reset_defaults(self):
        p, _ = self.panel()
        p.insert(12)
        identity = p.selected
        expected = dict(p._control_defaults)
        inserted = p.draft
        p.remove(identity)
        self.assertNotIn(identity, {point.identity for point in p.draft.points})
        p.undo()
        self.assertEqual(p.draft, inserted)
        self.assertEqual(p._control_defaults, expected)
        p.redo()
        self.assertNotIn(identity, {point.identity for point in p.draft.points})

    def test_history_buttons_do_not_overlap_view_controls_at_narrow_widths(self):
        p, _ = self.panel()
        for width in (300, 500, 850, 1500):
            p.canvas.resize(width, 600)
            p.canvas.view_controls.relayout()
            self.assertFalse(p.canvas.history_controls.geometry().intersects(p.canvas.view_controls.geometry()))

    def test_paused_update_waits_for_worker_release_before_restarting(self):
        from cooling_tower.gui.background_jobs import JobKind
        w = self.window()
        w._joint_generation_paused = True
        w.preview_state = PreviewState.STALE
        with patch.object(w.background_job_manager, "has_active", return_value=True), \
             patch.object(w.background_job_manager, "cancel_jobs") as cancel, \
             patch.object(w, "start_preview") as start:
            w._on_generation_button_clicked()
            cancel.assert_called_once()
            start.assert_not_called()
        self.assertTrue(w._restart_preview_after_release)
        with patch.object(w, "_finish_generation_cancelled") as discard, \
             patch.object(w, "start_preview") as start:
            w._on_background_job_released(SimpleNamespace(kind=JobKind.PREVIEW))
            self.app.processEvents()
            discard.assert_called_once()
            start.assert_called_once()

    def test_joint_simulations_preserve_global_profile_and_export_overrides(self):
        p, (f, service, ref, request, adapter) = self.panel()
        original_values = dict(request.effective_profile.effective_values)
        adapter.gcode = "; printing object cooling_tower\n" + adapter.gcode + "; stop printing object\n"
        changed = replace(request, settings=GenerationSettings(simulate_full_tower_infill=True, simulate_source_supports=True))
        self.assertNotEqual(request.signature(), changed.signature())
        result = service.prepare(changed)
        self.addCleanup(result.dispose)
        exported = ManualExportService().export(result, changed, f.root / "exports")
        source, tower = validate_joint_project(exported.project_path, tower_full_infill=True, source_supports_enabled=True)
        with zipfile.ZipFile(exported.project_path) as archive:
            root = ElementTree.fromstring(archive.read(MODEL_SETTINGS_PATH))
        values = {int(obj.get("id")): {item.get("key"): item.get("value") for item in obj.findall("metadata")}
                  for obj in root.findall("object")}
        self.assertEqual(values[source]["enable_support"], "1")
        self.assertNotIn("enable_support", values[tower])
        self.assertEqual(values[tower]["sparse_infill_density"], "100%")
        self.assertNotIn("sparse_infill_density", values[source])
        self.assertEqual(dict(request.effective_profile.effective_values), original_values)
        self.assertTrue(request.profiles_are_current())
        self.assertTrue(exported.source_supports_simulated)
        self.assertTrue(exported.full_tower_infill_simulated)
        self.assertFalse(p.full_infill_checkbox.isChecked())
        self.assertFalse(p.source_supports_checkbox.isChecked())

    def test_support_offer_requires_explicit_disabled_global_setting(self):
        _, (_, _, _, request, _) = self.panel()
        for value, expected in (("0", True), (["0"], True), (False, True), ("1", False), (None, False), ("unknown", False)):
            profile = replace(request.effective_profile, effective_values={"enable_support": value})
            self.assertEqual(global_supports_disabled(profile), expected)
        settings = GenerationSettings(simulate_source_supports=True)
        self.assertNotIn("simulate_source_supports", settings.to_dict())
        self.assertTrue(settings.to_dict(include_object_settings=True)["simulate_source_supports"])

    def test_object_option_replaces_legacy_global_support_retry_in_both_requests(self):
        _, (f, _, ref, request, adapter) = self.panel()
        w = self.window()
        profile = replace(request.effective_profile, effective_values={**request.effective_profile.effective_values,
                                                                     "enable_support": "0"})
        w.profile_match_result = SimpleNamespace(selected=SimpleNamespace(effective_profile=profile, bundle_id="bundle"),
                                                inventory_fingerprint="profiles", user_confirmed=True, can_use_stl_mode=True,
                                                execution_slicer=profile.installation)
        w.analysis_snapshot = f.snapshot
        w.source_preslice_result = SimpleNamespace(supports_simulated=True, draft_shield_simulated=False,
                                                   preview_source_data=ref.source_data, cleanup=lambda: None)
        with patch.object(w.slicer_service, "adapter_for", return_value=adapter):
            automatic = w._current_preview_request()
            self.assertTrue(automatic.effective_profile.supports_simulated)
            for checkbox in (w.simulate_source_supports_checkbox, w.manual_generation_panel.source_supports_checkbox):
                with QSignalBlocker(checkbox):
                    checkbox.setChecked(True)
            automatic = w._current_preview_request()
            manual = w.manual_controller.build_request(request.draft)
        for prepared in (automatic, manual):
            self.assertEqual(prepared.effective_profile.effective_values["enable_support"], "0")
            self.assertFalse(prepared.effective_profile.supports_simulated)
            self.assertTrue(prepared.settings.simulate_source_supports)

    def test_range_mesh_quality_uses_shared_control_and_cached_render(self):
        _, (f, service, ref, request, adapter) = self.panel()
        manager = BackgroundJobManager()
        self.addCleanup(manager.shutdown, 5000)
        dialog = LayerRangeDialog(ref.context.layers, ref.source_data.object_segments,
                                  target_time_s=10, target_minimum=5, target_maximum=30,
                                  silhouette=ref.silhouette, source_artifact=request.source_artifact,
                                  render_manager=manager)
        self.addCleanup(dispose_test_widget, dialog)
        dialog.show()
        self.assertIsInstance(dialog.resolution_control, ObjectResolutionControl)
        self.assertEqual(dialog.canvas.object_resolution_percent, 75)
        view = dialog.canvas.object_view
        deadline = time.monotonic() + 15
        while view.key() not in view.cache and time.monotonic() < deadline:
            self.app.processEvents()
            QTest.qWait(15)
        self.assertIn(view.key(), view.cache, dialog.canvas.accessibleDescription())
        count = view.request_id
        material=view.cache[view.key()].material
        with patch.object(view,"_start_render",side_effect=AssertionError("color edit started a worker")):
            previous_key = view.key()
            dialog.color_enabled_checkbox.setChecked(True)
            for red in (8, 10):
                dialog.color_gradient.request_value("red", red)
                dialog.canvas.grab()
                self.assertNotEqual(view.key(), previous_key)
                self.assertIs(view.cache[view.key()].material,material)
                self.assertEqual(view.request_id,count)
                previous_key = view.key()
            dialog.target_spin.setValue(12)
            self.assertEqual(view.key(), previous_key)
        dialog.canvas.zoom = 2
        dialog.canvas.pan = 15
        dialog.canvas._background = None
        dialog.canvas.grab()
        self.assertEqual(view.request_id, count)
        dialog.resolution_slider.setValue(1)
        self.assertEqual(dialog.canvas.object_resolution_percent, 0)
        self.assertIsNone(dialog.resolution_control.resolution_reset)
        slider = dialog.resolution_slider
        option = QStyleOptionSlider()
        slider.initStyleOption(option)
        handle = slider.style().subControlRect(
            QStyle.ComplexControl.CC_Slider, option,
            QStyle.SubControl.SC_SliderHandle, slider)
        QTest.mouseClick(slider, Qt.MouseButton.LeftButton, pos=handle.center())
        QTest.mouseDClick(slider, Qt.MouseButton.LeftButton, pos=handle.center())
        self.assertEqual(dialog.canvas.object_resolution_percent, 75)
        self.assertTrue(request.original_source_is_current())
        dialog.reject()

    def test_idle_tower_artwork_preserves_progress_and_displays_complete(self):
        image = Path(__file__).resolve().parents[1] / "src/cooling_tower/gui/assets/tower_gen_finished.webp"
        panel = GenerationPanel(image)
        self.addCleanup(dispose_test_widget, panel)
        panel.begin(10, .25, 0, 12)
        panel.image_progress.set_fill(.35)
        panel.mark_finished(paused=True, can_continue=True)
        self.assertTrue(panel.image_progress._display_complete)
        self.assertEqual(panel.image_progress._fill, .35)
        panel.resume_waiting()
        self.assertFalse(panel.image_progress._display_complete)
        self.assertEqual(panel.image_progress._fill, .35)

    def test_automatic_joint_candidates_and_deferred_export_keep_source_supports(self):
        import test_phase16 as fixture
        from cooling_tower.calibration import CalibrationService
        from cooling_tower.models import CalibrationConfig
        f, _, _, request, _ = create_fixture(self, joint=True, count=3)
        profile = replace(request.effective_profile, installation=replace(request.effective_profile.installation,
                          adapter_id="bambu_studio", product_name="Synthetic Bambu Studio"))
        base = fixture.DeferredBambuAdapter
        calls = []
        class Adapter(base):
            def prepare_joint_slice_input(self, *args, **kwargs):
                calls.append(("slice", kwargs.get("source_supports_enabled")))
                return super().prepare_joint_slice_input(*args, **kwargs)
            def create_joint_project(self, *args, **kwargs):
                calls.append(("export", kwargs.get("source_supports_enabled")))
                return super().create_joint_project(*args, **kwargs)
        adapter = Adapter(fixture.tower_gcode(layer_count=3, path_size=3, feed=30))
        result = CalibrationService().calibrate(
            f.snapshot, GenerationSettings(target_layer_time_s=30, simulate_source_supports=True), force_tower=True,
            adapter=adapter, profile=profile, output_directory=f.root / "auto_simulation",
            config=CalibrationConfig(maximum_iterations=3, minimum_joint_slices=2, perform_joint_final_slice=True,
                                     maximum_joint_slices=3, time_tolerance_s=1000),
            source_artifact=request.source_artifact)
        self.assertTrue(result.success, result.failures)
        self.assertGreaterEqual(len([kind for kind, _ in calls if kind == "slice"]), 2)
        self.assertEqual(len([kind for kind, _ in calls if kind == "export"]), 1)
        self.assertTrue(all(enabled is True for _, enabled in calls))

    def window(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        window = MainWindow(user_settings_path=Path(temporary.name) / "settings.json",
                            enable_update_check=False, enable_startup_slicer_discovery=False)
        self.addCleanup(dispose_test_widget, window)
        return window

    def test_paused_settings_restore_abort_and_restart_disposes_old_result(self):
        w = self.window()
        retained = SimpleNamespace(dispose=lambda: None)
        w.current_preview = retained
        w._joint_generation_paused = True
        w.resize(2600, 900)
        with patch.object(w, "_export_block_reason", return_value=None), \
             patch.object(w, "_current_preview_was_exported", return_value=False):
            w.preview_state = PreviewState.STALE
            w._refresh_phase17_actions()
            self.assertEqual(w.preview_button.text(), "Kühlturm aktualisieren")
            self.assertFalse(w.joint_generation_dialog.continue_button.isEnabled())
            self.assertFalse(w.joint_generation_dialog.export_button.isEnabled())
            w.preview_state = PreviewState.CURRENT
            w._refresh_phase17_actions()
            self.assertEqual(w.preview_button.text(), "Generierung abbrechen")
            self.assertTrue(w.joint_generation_dialog.continue_button.isEnabled())
            self.assertTrue(w.joint_generation_dialog.export_button.isEnabled())
            w.preview_state = PreviewState.STALE
            with patch.object(w, "_finish_generation_cancelled") as discard, patch.object(w, "start_preview") as start:
                w._on_generation_button_clicked()
                discard.assert_called_once()
                start.assert_called_once()

    def test_new_joint_scene_replaces_stale_label_during_rebuild(self):
        from PySide6.QtGui import QColor, QPalette
        from cooling_tower.preview import PreviewScene, LineSegment3D, Point3D
        from cooling_tower.models import BedBounds
        w = self.window()
        preview = w.preview_dialog
        old_scene = PreviewScene((), (LineSegment3D(Point3D(0, 0, 0), Point3D(0, 0, 10)),),
                                 BedBounds(0, 200, 0, 200), (100, 100), 0, 0, 10)
        preview.canvas.set_scene(old_scene)
        preview.mark_stale()
        preview.set_building("Wird aktualisiert")
        self.assertIn("Veraltet", preview.state_label.text())
        scene = PreviewScene((), (), BedBounds(0, 200, 0, 200), (100, 100), 0, 0, 10)
        preview.set_intermediate_scene(scene)
        self.assertIs(preview.canvas.scene, scene)
        self.assertNotIn("veraltet", preview.state_label.text())
        self.assertEqual("✓ Aktuell", preview.state_label.text())
        self.assertEqual(preview.state_label.property("state"), "current")
        self.assertEqual(preview.state_label.palette().color(QPalette.ColorRole.WindowText), QColor("#176b45"))
        self.assertEqual(preview.state, PreviewState.BUILDING)
        self.assertFalse(preview.side_button.isEnabled())

    def test_rescan_restores_only_unchanged_profiles_per_role(self):
        w = self.window()
        root = w.settings_store.user_path.parent
        executable = root / "slicer.exe"
        executable.write_bytes(b"MZ")
        installation = SimpleNamespace(identity_key="test-slicer", display_name="Testslicer", can_slice=True,
                                       verified=True, executable_path=executable)
        records = {}
        for role, kind in (("machine", ProfileKind.MACHINE), ("process", ProfileKind.PROCESS), ("filament", ProfileKind.FILAMENT)):
            records[role] = tuple(ProfileRecord("test", f"{role}-{i}", f"{role}-{i}", kind,
                                               root / f"{role}-{i}.json", "user") for i in (1, 2))
            for record in records[role]:
                record.path.write_text("{}")
        fingerprints = {str(record.path): record.profile_id for group in records.values() for record in group}
        catalog = ProfileCatalog(installation, "old", records["machine"], records["process"], records["filament"],
                                 content_fingerprints=fingerprints,
                                 **{"selected_" + role: ProfileSelectionReference(group[1].profile_id, group[1].path)
                                    for role, group in records.items()})
        with patch.object(type(w), "selected_slicer_installation", new_callable=PropertyMock, return_value=installation):
            w.profile_catalog = catalog
            w._populate_profile_combos(catalog)
            original_refs = {role: w._profile_combo_reference(combo) for role, combo in
                             (("machine", w.machine_profile_combo), ("process", w.process_profile_combo),
                              ("filament", w.filament_profile_combo))}
            w._profile_rescan_slicer_key = installation.identity_key
            w._profile_rescan_selections = {role: (ref, fingerprints[str(ref.path)]) for role, ref in original_refs.items()}
            changed = dict(fingerprints)
            changed[str(records["process"][1].path)] = "changed-process"
            refreshed = replace(catalog, inventory_fingerprint="new", content_fingerprints=changed)
            w._profile_request_id = 42
            w._profile_catalog_preserve_selection_requests[42] = False
            w._on_profile_catalog_succeeded(42, refreshed)
            self.assertEqual(w._profile_combo_reference(w.machine_profile_combo), original_refs["machine"])
            self.assertEqual(w._profile_combo_reference(w.filament_profile_combo), original_refs["filament"])
            self.assertEqual(w.process_profile_combo.currentData(), str(records["process"][0].path))
            self.assertFalse(w._profile_rescan_selections)
            w._profile_rescan_selections = {role: (ref, fingerprints[str(ref.path)]) for role, ref in original_refs.items()}
            changed_machine = dict(fingerprints)
            changed_machine[str(records["machine"][1].path)] = "changed-machine"
            with patch.object(w, "start_profile_catalog_loading") as reload_catalog:
                w._on_profile_catalog_succeeded(42, replace(catalog, content_fingerprints=changed_machine))
                self.assertEqual(reload_catalog.call_args.kwargs["selected_machine"].path, records["machine"][0].path)
                self.assertEqual(reload_catalog.call_args.kwargs["selected_profile_ids"]["filament"], original_refs["filament"])
                self.assertFalse(reload_catalog.call_args.kwargs["restore_remembered_profiles"])
            w._profile_rescan_selections = {}
