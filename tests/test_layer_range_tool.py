from __future__ import annotations

import os
import random
import sys
import tempfile
import unittest
import numpy as np
import trimesh
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QEvent, QPoint, QPointF, QSize, QSignalBlocker, Qt
from PySide6.QtGui import QFontDatabase, QWheelEvent
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QLabel, QPushButton, QStyle, QStyleOptionFrame, QWidget
from cooling_tower.gui.layer_range_dialog import LayerRangeDialog
from cooling_tower.gui.main_window import MainWindow
from cooling_tower.gui.settings_store import UserSettingsStore
from cooling_tower.gui.widgets.layer_range_canvas import LayerRangeCanvas
from cooling_tower.models import CalibrationConfig, GenerationSettings, OccupiedBounds
from cooling_tower.models.layer_ranges import excluded_layer_indices, normalize_layer_ranges
from cooling_tower.preview.models import LineSegment3D, OutputMode, Point3D, PreviewRequest
from cooling_tower.preview.service import PreviewService
from cooling_tower.preview.layer_silhouette import load_layer_silhouette
from cooling_tower.models import SourceArtifact, SourceKind, SourceChangedError
from cooling_tower.calibration import CalibrationService, adjust_radius_profile
from cooling_tower.services import GenerationService
from cooling_tower.services import GCodeAnalysisService
from cooling_tower.services.tower_need_service import assess_tower_need
from cooling_tower.tower.profile import TowerProfileConfig, TowerRadiusProfile, build_tower_radius_profile
from cooling_tower.tower.diameter_transitions import plan_diameter_transitions
from cooling_tower.tower.solid_profile import build_solid_tower_profile, ProfileFeasibilityError
from cooling_tower.tower.mesh_generator import TowerMeshConfig, generate_solid_tower_mesh, validate_triangle_mesh
from test_phase9 import make_snapshot, make_layer
from test_solid_tower_changes import radius_layer
import test_phase16 as calibration_fixture


def object_segments(layers):
    return tuple(LineSegment3D(Point3D(90, 98, layer.z_mm), Point3D(110, 102, layer.z_mm)) for layer in layers)


class LayerRangeDomainTests(unittest.TestCase):
    def test_range_union_and_invalid_values(self):
        self.assertEqual(normalize_layer_ranges(((8, 10), (1, 4), (3, 7), (15, 15))), ((1, 10), (15, 15)))
        for spans in (((0, 2),), ((3, 2),), ((True, 5),), ((1, 2.5),), ((1, 11),)):
            with self.assertRaises(ValueError):
                normalize_layer_ranges(spans, layer_count=10)

    def test_exclusions_use_positions_and_preserve_original_indices(self):
        layers = tuple(make_layer(i, (i - 6) * .2, .2, 1) for i in (7, 8, 9))
        self.assertEqual(excluded_layer_indices(layers, ((1, 2),)), frozenset({7, 8}))

    def test_excluded_top_deficits_do_not_extend_tower(self):
        with tempfile.TemporaryDirectory() as temporary:
            snapshot = make_snapshot(Path(temporary) / "source.gcode", (1, 20, 1, 1, 1), layer_heights=(.2, .3, .1, .4, .2))
            settings = GenerationSettings(excluded_layer_ranges=((3, 5),))
            result = assess_tower_need(snapshot, settings)
            self.assertEqual(result.deficit_layer_count, 1)
            self.assertEqual(result.layer_time_deficits_s[2:], (0, 0, 0))
            self.assertAlmostEqual(result.tower_end_z_mm, .2)
            self.assertEqual(snapshot.layers[-1].total_time_s, 1)

    def test_all_excluded_creates_no_output(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            snapshot = make_snapshot(root / "source.gcode", (1, 1, 1))
            result = GenerationService(root / "output").generate_from_analysis(snapshot, GenerationSettings(excluded_layer_ranges=((1, 3),)))
            self.assertFalse(result.assessment.tower_required)
            self.assertFalse((root / "output").exists())

    def _solid(self, *, full=True, ranges=((25, 30),), peak=False):
        settings = GenerationSettings(minimum_outer_diameter_mm=4, maximum_outer_diameter_mm=40,
            automatic_base_width=False, manual_base_width_mm=20, simulate_full_tower_infill=full,
            maximum_expansion_angle_deg=45, maximum_contraction_angle_deg=45,
            excluded_layer_ranges=ranges)
        source = TowerRadiusProfile(TowerProfileConfig(11), .1, tuple(
            radius_layer(index=i, z=i, radius=8 if not peak or i == 31 else 6,
                         calculated_radius=8 if not peak or i == 31 else 6)
            for i in range(1, 35)))
        return build_solid_tower_profile(source, settings)

    def test_full_infill_step_is_at_excluded_boundary_and_mesh_is_closed(self):
        # The excluded boundary is above the structural foot transition.
        profile = self._solid(ranges=((31, 34),))
        step = next(p for p in profile.points if p.source == "inward_step" and p.z_mm == 30)
        self.assertAlmostEqual(step.outer_radius_mm, 2)
        self.assertAlmostEqual(profile.layers[30].outer_radius_mm, 2)
        self.assertEqual(profile.layers[30].time_deficit_s, 0)
        mesh = generate_solid_tower_mesh(profile, TowerMeshConfig(32))
        validate_triangle_mesh(mesh)

    def test_future_peak_remains_reachable_and_angles_are_preserved(self):
        profile = self._solid(ranges=((25, 30),), peak=True)
        self.assertAlmostEqual(profile.layers[30].outer_radius_mm, 8)
        self.assertGreaterEqual(profile.layers[29].outer_radius_mm, 7)
        for a, b in zip(profile.layers[24:31], profile.layers[25:32]):
            self.assertLessEqual(b.outer_radius_mm - a.outer_radius_mm, b.z - a.z + 1e-8)

    def test_normal_infill_tapers_and_full_infill_start_keeps_the_foot(self):
        profile = self._solid(full=False)
        self.assertLess(profile.layers[25].outer_radius_mm, profile.layers[23].outer_radius_mm)
        self.assertFalse(any(p.source == "inward_step" and 24 <= p.z_mm <= 30 for p in profile.points))
        start = self._solid(ranges=((1, 20),))
        self.assertAlmostEqual(start.points[0].outer_radius_mm, 10)
        self.assertAlmostEqual(start.layers[0].outer_radius_mm, 10)
        self.assertGreaterEqual(start.layers[20].outer_radius_mm, 8)

    def test_excluded_full_infill_start_validates_the_foot_width(self):
        settings = GenerationSettings(minimum_outer_diameter_mm=30, maximum_outer_diameter_mm=40,
            automatic_base_width=False, manual_base_width_mm=20,
            simulate_full_tower_infill=True, excluded_layer_ranges=((1, 5),))
        source = TowerRadiusProfile(TowerProfileConfig(11), .1, tuple(
            radius_layer(index=i, z=i, radius=15, calculated_radius=15) for i in range(1, 8)))
        with self.assertRaises(ProfileFeasibilityError) as error:
            build_solid_tower_profile(source, settings)
        self.assertEqual(error.exception.issues[0].code, "BASE_WIDTH_TOO_SMALL")
        with self.assertRaises(ProfileFeasibilityError) as error:
            build_solid_tower_profile(source, replace(settings, manual_base_width_mm=50))
        self.assertEqual(error.exception.issues[0].code, "BASE_WIDTH_TOO_LARGE")

    def test_excluded_foot_matches_adequate_layers_and_has_a_minimum_trunk(self):
        # Reproduce the screenshot's 990 layers, 178.22 mm and excluded 1–951.
        height = 178.22 / 990
        source = TowerRadiusProfile(TowerProfileConfig(11), .1, tuple(
            radius_layer(index=i, z=i * height, radius=18 if i <= 951 else 10,
                         calculated_radius=18 if i <= 951 else 10)
            for i in range(1, 991)))
        adequate = replace(source, layers=tuple(
            replace(layer, radius_mm=2.5, calculated_radius_mm=2.5,
                    time_deficit_s=0, additional_path_mm=0, safety_adjusted_path_mm=0)
            if layer.layer_index <= 951 else layer for layer in source.layers))
        for full in (False, True):
            for automatic in (False, True):
                with self.subTest(full=full, automatic=automatic):
                    settings = GenerationSettings(minimum_outer_diameter_mm=5,
                        maximum_outer_diameter_mm=40, simulate_full_tower_infill=full,
                        automatic_base_width=automatic, manual_base_width_mm=37.43,
                        maximum_expansion_angle_deg=50, maximum_contraction_angle_deg=55,
                        excluded_layer_ranges=((1, 951),))
                    actual = build_solid_tower_profile(source, settings)
                    reference = build_solid_tower_profile(adequate,
                        replace(settings, excluded_layer_ranges=()))
                    self.assertEqual(actual.points, reference.points)
                    self.assertAlmostEqual(actual.base_outer_radius_mm, 37.43 / 2,
                                           delta=.002)
                    self.assertAlmostEqual(actual.layers[0].outer_radius_mm, actual.base_outer_radius_mm)
                    self.assertTrue(any(point.outer_radius_mm > 2.5
                                        for point in actual.points if 0 < point.z_mm < 5))
                    for layer in actual.layers[200:800]:
                        self.assertAlmostEqual(layer.outer_radius_mm, 2.5)
                    for layer in actual.layers[951:]:
                        self.assertGreaterEqual(layer.outer_radius_mm, 10 - 1e-8)
                    mesh = generate_solid_tower_mesh(actual, TowerMeshConfig(32))
                    validate_triangle_mesh(mesh)

    def test_regular_taper_does_not_extend_through_minimum_radius_layers(self):
        radii, unreachable, segments = plan_diameter_transitions(
            tuple(float(i) for i in range(101)), (10.,) + (2.,) * 100,
            base_index=0, base_radius=10, minimum_radius=2,
            expansion_slope=1, contraction_slope=1, allow_steps=False)
        self.assertFalse(unreachable)
        self.assertEqual(segments[0].taper.duration, 16)
        self.assertTrue(all(value == 2 for value in radii[16:]))

    def test_variable_layer_ranges_preserve_all_future_demands_and_valid_meshes(self):
        randomizer = random.Random(841)
        for full in (False, True):
            for ranges in (((1, 12), (30, 40)), ((20, 25), (50, 55)), ((1, 5), (15, 25), (40, 50))):
                z = 0.0
                layers = []
                for index in range(1, 61):
                    height = randomizer.choice((.1, .2, .35))
                    z += height
                    radius = randomizer.uniform(2, 9)
                    layers.append(replace(radius_layer(index=index, z=z, radius=radius, calculated_radius=radius), height_mm=height))
                settings = GenerationSettings(minimum_outer_diameter_mm=4, maximum_outer_diameter_mm=40,
                    automatic_base_width=False, manual_base_width_mm=20, simulate_full_tower_infill=full,
                    maximum_expansion_angle_deg=45, maximum_contraction_angle_deg=45,
                    excluded_layer_ranges=ranges)
                source = TowerRadiusProfile(TowerProfileConfig(11), .1, tuple(layers))
                profile = build_solid_tower_profile(source, settings)
                for original, actual in zip(layers, profile.layers):
                    if not any(a <= original.layer_index <= b for a, b in ranges):
                        self.assertGreaterEqual(actual.outer_radius_mm + 1e-7, original.radius_mm)
                for previous, current in zip(profile.layers, profile.layers[1:]):
                    self.assertLessEqual(current.outer_radius_mm - previous.outer_radius_mm, current.z - previous.z + 1e-7)
                    if not full:
                        self.assertLessEqual(previous.outer_radius_mm - current.outer_radius_mm, current.z - previous.z + 1e-7)
                validate_triangle_mesh(generate_solid_tower_mesh(profile, TowerMeshConfig(32)))

    def test_calibration_does_not_regrow_an_excluded_layer(self):
        layers = tuple(make_layer(i, i * .2, .2, 1) for i in (1, 2, 3))
        profile = build_tower_radius_profile(layers, TowerProfileConfig(11, minimum_radius_mm=2, excluded_layer_indices=frozenset({2})))
        adjusted, _ = adjust_radius_profile(profile, layers, {1: 10, 2: .01, 3: 10},
            target_time_s=11, combined_layer_times_s={1: 11, 2: .1, 3: 11},
            coupled_radius_scale=1.3, config=CalibrationConfig())
        self.assertEqual(adjusted.layers[1].radius_mm, 2)
        self.assertEqual(adjusted.layers[1].time_deficit_s, 0)
        self.assertEqual(adjusted.layers[1].additional_path_mm, 0)

    def test_calibration_ignores_excluded_objective_but_reports_complete_project(self):
        fixture = calibration_fixture.Phase16Tests("test_01_config_rejects_unbounded_values")
        fixture.setUp()
        try:
            snapshot = make_snapshot(fixture.source, (1, 1, 1))
            sliced = calibration_fixture.tower_gcode() + "G4 S6\n"
            fixture.tower.write_text(sliced, encoding="utf-8")
            target = 1 + GCodeAnalysisService().analyze(fixture.tower).layers[-1].total_time_s
            settings = GenerationSettings(target_layer_time_s=target, excluded_layer_ranges=((1, 2),))
            originals = {path: path.read_bytes() for path in (fixture.source, fixture.machine, fixture.process, fixture.filament)}
            result = CalibrationService().calibrate(snapshot, settings,
                adapter=calibration_fixture.FakeAdapter(sliced),
                profile=fixture.profile, output_directory=fixture.root / "ranges", config=CalibrationConfig(maximum_iterations=1))
            self.assertTrue(result.success, result.failures)
            self.assertEqual(result.iterations[-1].deficient_layer_count, 0)
            request = SimpleNamespace(snapshot=snapshot, settings=settings)
            expected_minimum = min(
                layer.total_time_s + result.best_iteration.evaluation.added_time_by_layer[layer.index]
                for layer in snapshot.layers
            )
            self.assertAlmostEqual(PreviewService._minimum_verified_time(request, result), expected_minimum)
            self.assertLess(expected_minimum, target)
            for path, data in originals.items():
                self.assertEqual(path.read_bytes(), data)
        finally:
            fixture.tearDown()

    def test_explicitly_forced_tower_with_all_layers_excluded_has_no_time_objective(self):
        fixture = calibration_fixture.Phase16Tests("test_01_config_rejects_unbounded_values")
        fixture.setUp()
        try:
            settings = GenerationSettings(excluded_layer_ranges=((1, 3),))
            result = CalibrationService().calibrate(fixture.snapshot, settings,
                adapter=calibration_fixture.FakeAdapter(calibration_fixture.tower_gcode()),
                profile=fixture.profile, output_directory=fixture.root / "forced-ranges",
                config=CalibrationConfig(maximum_iterations=1), force_tower=True)
            self.assertTrue(result.success, result.failures)
            self.assertEqual(result.iterations[-1].deficient_layer_count, 0)
        finally:
            fixture.tearDown()

    def test_object_ranges_change_preview_identity_but_not_global_settings(self):
        settings = GenerationSettings(excluded_layer_ranges=((1, 3),))
        self.assertNotIn("excluded_layer_ranges", settings.to_dict())
        self.assertEqual(settings.to_dict(include_object_settings=True)["excluded_layer_ranges"], ((1, 3),))
        self.assertEqual(replace(settings, target_layer_time_s=20).excluded_layer_ranges, ((1, 3),))
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "settings.json"
            snapshot = make_snapshot(Path(temporary) / "source.gcode", (1, 1, 1))
            request = PreviewRequest(snapshot=snapshot, settings=GenerationSettings(),
                output_mode=OutputMode.STL, calibration_config=CalibrationConfig(),
                effective_profile=SimpleNamespace(), adapter=SimpleNamespace())
            self.assertNotEqual(request.signature(), replace(request, settings=settings).signature())
            store = UserSettingsStore(path, ROOT / "config/default_settings.json")
            store.save(settings, output_root=temporary, window_width=1000, window_height=800)
            restored, _ = store.load()
            self.assertEqual(restored.excluded_layer_ranges, ())


class LayerRangeUiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.layers = tuple(make_layer(i, i * .2, .2, 9.7) for i in range(1, 101))
        self.dialog = LayerRangeDialog(self.layers, object_segments(self.layers), target_time_s=10,
            target_minimum=5, target_maximum=120)
        self.dialog.show()
        self.app.processEvents()
        self.addCleanup(self.dialog.close)

    def test_heatmap_exact_endpoints_and_one_second_threshold(self):
        self.assertEqual(LayerRangeCanvas.layer_color(10, 10).name(), LayerRangeCanvas.OBJECT_COLOR)
        self.assertEqual(LayerRangeCanvas.layer_color(10, 9).name(), LayerRangeCanvas.CRITICAL_COLOR)
        self.assertEqual(LayerRangeCanvas.layer_color(10, 5).name(), LayerRangeCanvas.CRITICAL_COLOR)
        self.assertNotEqual(LayerRangeCanvas.layer_color(10, 9.75).name(), LayerRangeCanvas.CRITICAL_COLOR)
        self.assertEqual(LayerRangeCanvas.layer_color(10, 20).name(), LayerRangeCanvas.OBJECT_COLOR)

    def _styled_dialog(self):
        # Windows' offscreen backend does not enumerate installed fonts.
        font_path = Path("C:/Windows/Fonts/segoeui.ttf")
        if not QFontDatabase.families() and font_path.exists():
            font_id = QFontDatabase.addApplicationFont(str(font_path))
            self.addCleanup(lambda: QFontDatabase.removeApplicationFont(font_id))
        # Keep the styling local: changing QApplication's stylesheet also
        # repolishes every widget retained by earlier GUI tests in the suite.
        # A styled parent supplies the font and metrics during construction.
        style_host = QWidget()
        style_host.setStyleSheet((ROOT / "src/cooling_tower/gui/styles.qss").read_text(encoding="utf-8"))
        self.addCleanup(style_host.deleteLater)
        dialog = LayerRangeDialog(self.layers, object_segments(self.layers), target_time_s=10,
            target_minimum=5, target_maximum=120, ranges=((1, 20), (50, 100)), parent=style_host)
        dialog.show()
        self.addCleanup(dialog.close)
        return dialog

    def _settle_layout(self):
        for _ in range(10):
            self.app.processEvents()

    @staticmethod
    def _usable_editor_width(spin):
        editor = spin.lineEdit()
        option = QStyleOptionFrame()
        editor.initStyleOption(option)
        contents = editor.style().subElementRect(QStyle.SubElement.SE_LineEditContents, option, editor)
        margins = editor.textMargins()
        return contents.width() - margins.left() - margins.right() - 4

    def test_left_pane_stays_unwrapped_while_preview_shrinks_proportionally(self):
        dialog = self._styled_dialog()
        dialog.resize(dialog.sizeHint())
        self._settle_layout()
        preferred = dialog._preferred_pane_widths[0]

        def assert_unwrapped():
            self.assertEqual(dialog.target_spin.y(), dialog.target_info_button.parentWidget().y()
                             + (dialog.target_info_button.parentWidget().height() - dialog.target_spin.height()) // 2)
            self.assertLessEqual(dialog.color_info_button.parentWidget().height(), dialog.settings_panel.height())
            color_label = next(label for label in dialog.settings_panel.findChildren(QLabel)
                               if label.text() == "Defizit-Einfärbung nach Mindest-Layerzeit")
            self.assertLessEqual(color_label.height(), color_label.fontMetrics().height() + 2)
            self.assertEqual(dialog.new_start_spin.parentWidget().y(), dialog.new_end_spin.parentWidget().y())
            for row, first, last, select in dialog.range_rows:
                remove = next(button for button in row.findChildren(QPushButton) if button.text() == "Entfernen")
                self.assertEqual(remove.y(), select.y())
                self.assertEqual(first.parentWidget().y(), last.parentWidget().y())

        self.assertEqual(dialog.splitter.sizes()[0], preferred)
        self.assertEqual(dialog.settings_panel.minimumWidth(), preferred)
        initial_canvas_width = dialog.canvas.width()
        initial_scale = dialog.canvas._scale()
        assert_unwrapped()
        right_minimum = dialog.splitter.widget(1).minimumSizeHint().width()
        chrome = dialog.width() - sum(dialog.splitter.sizes())
        dialog.resize(preferred + right_minimum + chrome + 20, dialog.height())
        self._settle_layout()
        self.assertEqual(dialog.splitter.sizes()[0], preferred)
        assert_unwrapped()
        dialog.resize(dialog.minimumSizeHint().width(), dialog.height())
        self._settle_layout()
        self.assertEqual(dialog.splitter.sizes()[0], preferred)
        self.assertLess(dialog.canvas.width(), 500)
        self.assertLess(dialog.canvas.width(), initial_canvas_width)
        self.assertLess(dialog.canvas._scale(), initial_scale)
        canvas = dialog.canvas
        horizontal_scale = canvas.x_for_position(1) - canvas.x_for_position(0)
        vertical_scale = canvas.y_for_z(0) - canvas.y_for_z(1)
        self.assertAlmostEqual(horizontal_scale, vertical_scale)
        self.assertGreaterEqual(canvas.y_for_z(canvas.tops[-1]), canvas.plot_rect().top() - 1)
        self.assertGreaterEqual(canvas.x_for_position(canvas._minimum_x), canvas.plot_rect().left() - 1)
        self.assertLessEqual(canvas.x_for_position(canvas._maximum_x), canvas.plot_rect().right() + 1)
        self.assertEqual(dialog.fit_button.text(), "Objekt einpassen")
        self.assertGreater(dialog.fit_button.y(), dialog.rotation_slider.y())
        for label in dialog.preview_notes.findChildren(QLabel):
            if label.wordWrap():
                self.assertGreaterEqual(label.height(), label.heightForWidth(label.width()))
        assert_unwrapped()
        dialog.splitter.setSizes([0, 10000])
        self._settle_layout()
        self.assertEqual(dialog.splitter.sizes()[0], preferred)
        assert_unwrapped()
        dialog.resize(dialog.sizeHint())
        self._settle_layout()
        self.assertEqual(dialog.splitter.sizes()[0], preferred)
        assert_unwrapped()

    def test_initial_size_fits_preferred_preview_and_uses_smaller_available_space(self):
        dialog = self._styled_dialog()
        preferred = dialog.initial_size(QSize(2400, 1600))
        dialog.resize(preferred)
        self._settle_layout()
        self.assertFalse(dialog.isMaximized())
        self.assertEqual(dialog.canvas.size(), QSize(650, 550))
        self.assertEqual(dialog.size(), preferred)
        self.assertLess(dialog.width(), 2400)
        self.assertLess(dialog.height(), 1600)
        fallback_limit = preferred - QSize(150, 50)
        dialog.resize(dialog.initial_size(fallback_limit))
        self._settle_layout()
        self.assertEqual(dialog.canvas.size(), QSize(500, 500))
        self.assertEqual(dialog.size(), fallback_limit)
        small_limit = fallback_limit - QSize(100, 100)
        dialog.resize(dialog.initial_size(small_limit))
        self._settle_layout()
        self.assertLessEqual(dialog.width(), small_limit.width())
        self.assertLessEqual(dialog.height(), small_limit.height())
        self.assertEqual(dialog.splitter.sizes()[0], dialog.settings_panel.minimumWidth())
        dialog.resize(dialog.initial_size(QSize(2400, 1600)))
        self._settle_layout()
        self.assertEqual(dialog.canvas.size(), QSize(650, 550))

    def test_narrow_preview_reclaims_outer_margins_and_keeps_controls_reachable(self):
        self._styled_dialog()
        canvas = LayerRangeCanvas(self.layers, object_segments(self.layers))
        canvas.setMinimumWidth(240)
        canvas.set_ranges(((20, 50),), selected=0)
        canvas.show()
        self.addCleanup(canvas.close)
        previous = None
        for width in (650, 500, 400, 280, 240):
            canvas.resize(width, 500)
            self._settle_layout()
            plot = canvas.plot_rect()
            heading = canvas.layer_title_rect()
            grips = canvas.handle_rects((20, 50))
            remove = canvas.delete_rect((20, 50))
            left, right, axis_gap, _, _ = canvas._horizontal_spacing()
            self.assertGreaterEqual(left - axis_gap, canvas.fontMetrics().horizontalAdvance("100") + 6)
            self.assertEqual(heading.y(), 5)
            self.assertLess(grips[0].right(), remove.left())
            self.assertLessEqual(remove.right(), canvas.width() - 4)
            for grip, action in zip(grips, ("end", "start")):
                self.assertEqual(grip.size().width(), 30)
                self.assertEqual(canvas._hit(grip.center()), (0, action))
            self.assertEqual(canvas._hit(remove.center()), (0, "delete"))
            if width >= 500:
                self.assertEqual((left, right, heading.x()), (58, 108, 6))
            else:
                self.assertLess(left, previous[0])
                self.assertLess(right, previous[1])
                self.assertGreater(heading.x(), previous[2])
                self.assertGreater(plot.width(), width - 166)
            previous = left, right, heading.x()
        deleted, committed = [], []
        canvas.remove_requested.connect(deleted.append)
        canvas.range_committed.connect(lambda *values: committed.append(values))
        upper = canvas.handle_rects((20, 50))[0].center().toPoint()
        end = QPoint(upper.x(), round(canvas.y_for_z((canvas.bottoms[54] + canvas.tops[54]) / 2)))
        QTest.mousePress(canvas, Qt.MouseButton.LeftButton, pos=upper)
        QTest.mouseMove(canvas, end)
        QTest.mouseRelease(canvas, Qt.MouseButton.LeftButton, pos=end)
        self.assertEqual(committed[-1], (0, 20, 55))
        QTest.mouseClick(canvas, Qt.MouseButton.LeftButton,
                         pos=canvas.delete_rect((20, 50)).center().toPoint())
        self.assertEqual(deleted, [0])

    def test_left_minimum_tracks_wider_values_and_added_range_rows(self):
        dialog = self._styled_dialog()
        self._settle_layout()
        original_width = dialog.settings_panel.minimumWidth()
        dialog.target_spin.setMaximum(1e12)
        with QSignalBlocker(dialog.target_spin):
            dialog.target_spin.setValue(1e12)
        self._settle_layout()
        self.assertGreater(dialog.settings_panel.minimumWidth(), original_width)
        self.assertEqual(dialog.settings_panel.minimumWidth(), dialog._unwrapped_settings_width())
        self.assertEqual(dialog.target_spin.y(), dialog.target_info_button.parentWidget().y()
                         + (dialog.target_info_button.parentWidget().height() - dialog.target_spin.height()) // 2)
        dialog.set_ranges(tuple((layer, layer) for layer in range(1, 21, 2)))
        self._settle_layout()
        self.assertEqual(len(dialog.range_rows), 10)
        self.assertEqual(dialog.settings_panel.minimumWidth(), dialog._unwrapped_settings_width())
        for row, first, last, select in dialog.range_rows:
            remove = next(button for button in row.findChildren(QPushButton) if button.text() == "Entfernen")
            self.assertEqual(select.y(), remove.y())
            self.assertEqual(first.parentWidget().y(), last.parentWidget().y())

    def test_legend_shows_gradient_and_caption_without_numeric_labels(self):
        texts = [label.text() for label in self.dialog.legend.findChildren(QLabel)]
        self.assertEqual(texts, ["Layerzeit-Defizit",
            "Ausschlussbereiche: Enthaltene Layerzeit-Defizite werden ignoriert"])

    def test_empty_list_hint_wraps_without_affecting_preferred_width(self):
        self._styled_dialog()
        dialog = LayerRangeDialog(self.layers, object_segments(self.layers), target_time_s=10,
            target_minimum=5, target_maximum=120)
        self.addCleanup(dialog.close)
        dialog.show()
        self._settle_layout()
        hint = dialog.rows_host.findChild(QLabel, "layerRangeEmptyHint")
        self.assertEqual(hint.text(), "Es wurden noch keine Bereiche definiert.\n\n"
            "Füge einen festen Bereich hinzu oder zeichne einen direkt in die Vorschau ein.")
        self.assertTrue(hint.wordWrap())
        self.assertEqual(dialog.add_button.text(), "Bereich hinzufügen")
        preferred = dialog._preferred_pane_widths[0]
        self.assertEqual(dialog._unwrapped_settings_width(), preferred)
        self.assertGreaterEqual(hint.height(), hint.heightForWidth(hint.width()))
        hint.setText("Ein viel längerer frei umbrechender Hinweis. " * 50)
        self._settle_layout()
        self.assertEqual(dialog._unwrapped_settings_width(), preferred)
        self.assertTrue(hint.wordWrap())

    def test_deficit_reset_and_labels_align_with_full_width_slider(self):
        dialog = self._styled_dialog()
        self._settle_layout()
        reset, start, full = dialog.color_reset_button, dialog.color_start_spin, dialog.color_full_spin
        self.assertEqual(reset.height(), full.height())
        self.assertEqual(reset.y(), full.y())
        self.assertEqual(start.y(), full.y())
        self.assertLess(dialog.color_gradient.y(), start.y())
        self.assertLess(dialog.color_start_label.geometry().right(), dialog.color_gradient.x())
        self.assertLess(dialog.color_gradient.geometry().right(), dialog.color_full_label.x())
        self.assertEqual(dialog.color_full_label.geometry().right(), reset.geometry().right())
        self.assertEqual((dialog.color_start_label.text(), dialog.color_full_label.text()), ("0,0 s", "1,0 s"))
        full.setValue(1.25)
        start.setValue(.15)
        self._settle_layout()
        self.assertEqual((dialog.color_start_label.text(), dialog.color_full_label.text()), ("0,2 s", "1,3 s"))

    def test_target_label_and_reset_height_and_standard_value(self):
        dialog = self._styled_dialog()
        self._settle_layout()
        self.assertIn("Gew. Min-Layerzeit", [label.text() for label in dialog.settings_panel.findChildren(QLabel)])
        reset, spin = dialog.target_reset_button, dialog.target_spin
        self.assertEqual(reset.height(), spin.height())
        self.assertEqual(reset.y(), spin.y())
        self.assertGreater(reset.x(), spin.geometry().right())
        self.assertFalse(reset.isEnabled())
        changed = []
        dialog.target_time_changed.connect(changed.append)
        spin.setValue(15)
        self.assertTrue(reset.isEnabled())
        reset.click()
        self.assertEqual(spin.value(), 10)
        self.assertEqual(dialog.canvas.target_time_s, 10)
        self.assertEqual(changed, [15, 10])
        self.assertFalse(reset.isEnabled())
        dialog.set_target_time(12)
        self.assertTrue(reset.isEnabled())
        dialog.set_target_time(10)
        self.assertFalse(reset.isEnabled())
        custom = LayerRangeDialog(self.layers, object_segments(self.layers), target_time_s=15,
            target_minimum=5, target_maximum=120, target_default=12)
        self.addCleanup(custom.close)
        custom.target_reset_button.click()
        self.assertEqual(custom.target_spin.value(), 12)

    def test_deficit_input_rounds_half_up_and_blocked_or_typed_values_are_not_clipped(self):
        dialog = self._styled_dialog()
        self._settle_layout()
        for value, expected in ((.05, .1), (.15, .2), (1.25, 1.3), (1.55, 1.6), (1.95, 2.0), (5, 2)):
            dialog.color_full_spin.setValue(value)
            self.assertEqual(dialog.color_full_spin.value(), expected)
            self.assertEqual(dialog.color_full_spin.text(), f"≥ {expected:.1f} s".replace(".", ","))
        editor = dialog.color_full_spin.lineEdit()
        editor.setFocus()
        dialog.color_full_spin.selectAll()
        QTest.keyClicks(editor, "1,25")
        self._settle_layout()
        self.assertGreaterEqual(self._usable_editor_width(dialog.color_full_spin),
                                editor.fontMetrics().horizontalAdvance(editor.text()))
        dialog.color_full_spin.interpretText()
        self.assertEqual(dialog.color_full_spin.value(), 1.3)
        self.assertEqual(dialog.color_gradient.full_handle.value(), 13)
        for spin in (dialog.target_spin, dialog.new_start_spin, dialog.new_end_spin):
            with QSignalBlocker(spin):
                spin.setValue(spin.maximum())
            self._settle_layout()
            self.assertGreaterEqual(self._usable_editor_width(spin),
                                    spin.lineEdit().fontMetrics().horizontalAdvance(spin.text()))

    def test_compact_fields_expand_without_wrapping_left_pane(self):
        dialog = self._styled_dialog()
        dialog.resize(1200, 800)
        self._settle_layout()
        dialog.splitter.setSizes([0, 10000])
        self._settle_layout()
        self.assertLessEqual(dialog.settings_panel.width(), dialog._preferred_pane_widths[0] + 4)
        self.assertEqual(dialog.color_start_spin.prefix(), "≤ ")
        self.assertEqual(dialog.color_full_spin.prefix(), "≥ ")
        for spin in (dialog.target_spin, dialog.color_start_spin, dialog.color_full_spin, dialog.new_start_spin):
            metrics = spin.lineEdit().fontMetrics()
            spare = self._usable_editor_width(spin) - metrics.horizontalAdvance(spin.text())
            self.assertGreaterEqual(spare, metrics.horizontalAdvance("0") - 1)
            self.assertLessEqual(spare, metrics.horizontalAdvance("0") + 2)
        self.assertEqual(dialog.target_spin.y(), dialog.target_info_button.parentWidget().y()
                         + (dialog.target_info_button.parentWidget().height() - dialog.target_spin.height()) // 2)
        row, first, last, select = dialog.range_rows[0]
        remove = next(button for button in row.findChildren(QPushButton) if button.text() == "Entfernen")
        self.assertEqual(remove.y(), select.y())
        self.assertEqual(last.parentWidget().y(), first.parentWidget().y())
        old_width = dialog.new_start_spin.width()
        dialog.new_start_spin.setValue(100)
        self._settle_layout()
        self.assertGreater(dialog.new_start_spin.width(), old_width)
        self.assertEqual(dialog.new_end_spin.parentWidget().y(), dialog.new_start_spin.parentWidget().y())
        dialog.splitter.setSizes([650, 500])
        self._settle_layout()
        self.assertEqual(dialog.target_spin.y(), dialog.target_info_button.parentWidget().y()
                         + (dialog.target_info_button.parentWidget().height() - dialog.target_spin.height()) // 2)
        self.assertEqual(remove.y(), select.y())
        self.assertEqual(last.parentWidget().y(), first.parentWidget().y())

    def test_rotation_fit_shortens_then_wraps_and_preview_notes_scroll(self):
        dialog = self._styled_dialog()
        dialog.resize(1200, 800)
        controls = dialog.rotation_controls
        # Exercise each responsive stage at its exact width independently.
        stylesheet = dialog.parentWidget().styleSheet()
        controls.setParent(None)
        controls.setStyleSheet(stylesheet)
        controls.show()
        self.addCleanup(controls.close)
        self._settle_layout()
        widths = controls._widths()
        base = sum(widths[:4]) + 4 * 6
        for width, text, wrapped in ((base + widths[4] + 8, "Objekt einpassen", False),
                                     (base + widths[5] + 2, "Einpassen", False),
                                     (max(240, base - 6), "Objekt einpassen", True)):
            controls.resize(width, controls.heightForWidth(width))
            self._settle_layout()
            self.assertEqual(dialog.fit_button.text(), text)
            self.assertEqual(dialog.fit_button.y() > dialog.rotation_slider.y(), wrapped)
            self.assertGreaterEqual(controls.height(), controls.heightForWidth(controls.width()))
            self.assertLessEqual(dialog.fit_button.geometry().right(), controls.width())
        dialog.preview_notes.setMaximumHeight(64)
        dialog.color_full_spin.setValue(2)
        dialog.color_start_spin.setValue(1.9)
        self._settle_layout()
        self.assertGreater(dialog.preview_notes.verticalScrollBar().maximum(), 0)
        for label in dialog.preview_notes.findChildren(QLabel):
            if label.wordWrap():
                self.assertGreaterEqual(label.height(), label.heightForWidth(label.width()))
        dialog.preview_notes.verticalScrollBar().setValue(dialog.preview_notes.verticalScrollBar().maximum())
        self._settle_layout()
        self.assertLessEqual(dialog.legend.mapTo(dialog.preview_notes.viewport(), dialog.legend.rect().bottomRight()).y(),
                             dialog.preview_notes.viewport().height())

    def test_configurable_color_limits_update_canvas_and_legend_without_changing_ranges(self):
        self.dialog.commit_range(-1, 10, 20)
        changes = []
        self.dialog.ranges_changed.connect(changes.append)
        self.dialog.color_start_spin.setValue(.2)
        self.dialog.color_full_spin.setValue(.8)
        canvas = self.dialog.canvas
        self.assertEqual((canvas.gradient_start_deficit_s, canvas.gradient_full_deficit_s), (.2, .8))
        self.assertEqual((self.dialog.legend.start_deficit_s, self.dialog.legend.full_deficit_s), (.2, .8))
        self.assertEqual(canvas.layer_color(10, 9.9, .2, .8).name(), canvas.OBJECT_COLOR)
        self.assertEqual(canvas.layer_color(10, 9.2, .2, .8).name(), canvas.CRITICAL_COLOR)
        self.assertNotEqual(canvas.layer_color(10, 9.5, .2, .8).name(), canvas.OBJECT_COLOR)
        self.assertNotEqual(canvas.layer_color(10, 9.5, .2, .8).name(), canvas.CRITICAL_COLOR)
        self.assertEqual(self.dialog.ranges, ((10, 20),))
        self.assertEqual(changes, [])
        self.dialog.color_start_spin.setValue(1)
        self.assertGreater(self.dialog.color_full_spin.value(), self.dialog.color_start_spin.value())
        self.dialog.color_full_spin.setValue(.1)
        self.assertLess(self.dialog.color_start_spin.value(), self.dialog.color_full_spin.value())
        self.assertEqual(canvas.gradient_start_deficit_s, self.dialog.legend.start_deficit_s)
        self.assertEqual(canvas.gradient_full_deficit_s, self.dialog.legend.full_deficit_s)

    def test_dual_deficit_slider_drag_fields_and_keyboard_stay_synchronized(self):
        dialog = self._styled_dialog()
        self._settle_layout()
        slider = dialog.color_gradient
        self.assertEqual(slider.MAXIMUM_SECONDS, 2)
        self.assertEqual((dialog.color_start_spin.value(), dialog.color_full_spin.value()), (0, 1))
        self.assertEqual((slider.start_handle.value(), slider.full_handle.value()), (0, 10))

        def drag(handle, value):
            point = QPoint(round(slider.x_for_value(value)), handle.geometry().center().y())
            QTest.mousePress(handle, Qt.MouseButton.LeftButton,
                             pos=QPoint(handle.width() // 2, handle.height() // 2))
            QTest.mouseMove(handle, handle.mapFrom(slider, point))
            QTest.mouseRelease(handle, Qt.MouseButton.LeftButton, pos=handle.mapFrom(slider, point))
            self._settle_layout()
            return slider.value_at(point.x()) / 10

        expected = drag(slider.start_handle, 5)
        self.assertAlmostEqual(dialog.color_start_spin.value(), expected, delta=.03)
        self.assertEqual(slider.start_handle.value(), round(dialog.color_start_spin.value() * 10))
        expected = drag(slider.full_handle, 15)
        self.assertAlmostEqual(dialog.color_full_spin.value(), expected, delta=.03)
        drag(slider.full_handle, 20)
        self.assertEqual(dialog.color_full_spin.value(), 2)
        dialog.color_start_spin.setValue(1.8)
        self._settle_layout()
        self.assertEqual(slider.start_handle.value(), 18)
        dialog.color_full_spin.setValue(.2)
        self._settle_layout()
        self.assertEqual((slider.start_handle.value(), slider.full_handle.value()), (1, 2))
        self.assertFalse(slider.start_handle.geometry().intersects(slider.full_handle.geometry()))
        slider.start_handle.setFocus()
        QTest.keyClick(slider.start_handle, Qt.Key.Key_Right)
        self.assertEqual((dialog.color_start_spin.value(), dialog.color_full_spin.value()), (.2, .3))
        QTest.keyClick(slider.full_handle, Qt.Key.Key_End)
        self.assertEqual(dialog.color_full_spin.value(), 2)
        QTest.keyClick(slider.full_handle, Qt.Key.Key_Home)
        self.assertEqual((dialog.color_start_spin.value(), dialog.color_full_spin.value()), (0, .1))
        self.assertEqual((dialog.canvas.gradient_start_deficit_s, dialog.canvas.gradient_full_deficit_s), (0, .1))
        self.assertEqual((dialog.legend.start_deficit_s, dialog.legend.full_deficit_s), (0, .1))
        dialog.color_reset_button.click()
        self.assertEqual((slider.start_handle.value(), slider.full_handle.value()), (0, 10))

    def test_closing_tool_cancels_pending_rebuild_and_scroll_callbacks(self):
        dialog = LayerRangeDialog(self.layers, object_segments(self.layers),
            target_time_s=10, target_minimum=5, target_maximum=120)
        dialog.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)
        dialog.show()
        self.app.processEvents()
        with patch("sys.excepthook") as errors:
            dialog.commit_range(-1, 10, 20)
            dialog.close()
            self.app.sendPostedEvents(None, QEvent.Type.DeferredDelete)
            QTest.qWait(20)
            errors.assert_not_called()

    def test_precision_inputs_add_edit_union_and_remove(self):
        self.dialog.new_start_spin.setValue(10)
        self.dialog.new_end_spin.setValue(20)
        self.dialog.add_button.click()
        self.app.processEvents()
        self.dialog.commit_range(-1, 30, 40)
        self.app.processEvents()
        row, first, last, _ = self.dialog.range_rows[1]
        last.setValue(35)
        last.editingFinished.emit()
        self.app.processEvents()
        self.assertEqual(self.dialog.ranges, ((10, 40),))
        self.assertEqual(self.dialog.canvas.ranges, self.dialog.ranges)
        self.assertEqual(len(self.dialog.range_rows), 1)
        self.dialog.range_rows[0][0].findChildren(QPushButton)[1].click()
        self.app.processEvents()
        self.assertEqual(self.dialog.ranges, ())
        self.assertEqual(len(self.dialog.range_rows), 0)

    def _point(self, layer, x=None):
        canvas = self.dialog.canvas
        y = canvas.y_for_z((canvas.tops[layer - 1] + canvas.bottoms[layer - 1]) / 2)
        return QPoint(round(canvas.plot_rect().center().x() if x is None else x), round(y))

    def test_drag_merge_is_committed_only_on_release(self):
        # Isolate join highlighting from changes to the default heatmap scale.
        self.dialog.color_full_spin.setValue(.5)
        self.dialog.commit_range(-1, 10, 20)
        self.dialog.commit_range(-1, 30, 40)
        self.app.processEvents()
        canvas = self.dialog.canvas
        QTest.mousePress(canvas, Qt.MouseButton.LeftButton, pos=self._point(15))
        QTest.mouseMove(canvas, self._point(30))
        self.assertEqual(self.dialog.ranges, ((30, 40), (10, 20)))
        self.assertEqual(len(self.dialog.range_rows), 2)
        self.assertFalse(canvas.join_hint.isHidden())
        self.assertEqual(canvas._joining_indices, frozenset({0, 1}))
        QTest.mouseMove(canvas, self._point(15))
        self.assertTrue(canvas.join_hint.isHidden())
        self.assertEqual(canvas._joining_indices, frozenset())
        QTest.mouseMove(canvas, self._point(30))
        self.assertFalse(canvas.join_hint.isHidden())
        region = canvas.range_rect((30, 40))
        color = canvas.grab().toImage().pixelColor(round(region.left() + 4), round(region.center().y()))
        self.assertGreater(color.red(), 190)
        self.assertGreater(color.green(), 190)
        QTest.mouseRelease(canvas, Qt.MouseButton.LeftButton, pos=self._point(30))
        self.app.processEvents()
        self.assertTrue(canvas.join_hint.isHidden())
        self.assertEqual(self.dialog.ranges, ((25, 40),))
        self.assertEqual(self.dialog.range_rows[0][1].value(), 25)
        self.assertEqual(self.dialog.range_rows[0][2].value(), 40)

    def test_overlap_hint_for_boundary_grip_disappears_on_escape(self):
        self.dialog.commit_range(-1, 10, 20)
        self.dialog.commit_range(-1, 30, 40)
        self.app.processEvents()
        canvas = self.dialog.canvas
        upper, _ = canvas.handle_rects((10, 20))
        QTest.mousePress(canvas, Qt.MouseButton.LeftButton, pos=upper.center().toPoint())
        QTest.mouseMove(canvas, self._point(35, upper.center().x()))
        self.assertFalse(canvas.join_hint.isHidden())
        self.assertEqual(self.dialog.ranges, ((30, 40), (10, 20)))
        QTest.keyClick(canvas, Qt.Key.Key_Escape)
        self.assertTrue(canvas.join_hint.isHidden())
        self.assertEqual(canvas._joining_indices, frozenset())
        QTest.mouseRelease(canvas, Qt.MouseButton.LeftButton, pos=self._point(35, upper.center().x()))
        self.assertEqual(self.dialog.ranges, ((30, 40), (10, 20)))

    def test_draw_resize_and_preview_delete(self):
        canvas = self.dialog.canvas
        QTest.mousePress(canvas, Qt.MouseButton.LeftButton, pos=self._point(50))
        QTest.mouseRelease(canvas, Qt.MouseButton.LeftButton, pos=self._point(60))
        self.app.processEvents()
        self.assertEqual(self.dialog.ranges, ((50, 60),))
        upper, _ = canvas.handle_rects((50, 60))
        QTest.mousePress(canvas, Qt.MouseButton.LeftButton, pos=upper.center().toPoint())
        QTest.mouseRelease(canvas, Qt.MouseButton.LeftButton, pos=self._point(70, upper.center().x()))
        self.app.processEvents()
        self.assertEqual(self.dialog.ranges, ((50, 70),))
        QTest.mouseClick(canvas, Qt.MouseButton.LeftButton, pos=canvas.delete_rect((50, 70)).center().toPoint())
        self.app.processEvents()
        self.assertEqual(self.dialog.ranges, ())

    def test_rotation_changes_geometry_but_keeps_ranges_and_layers(self):
        self.dialog.commit_range(-1, 10, 20)
        original_width = self.dialog.canvas._maximum_x - self.dialog.canvas._minimum_x
        self.dialog.rotation_slider.setValue(90)
        self.assertLess(self.dialog.canvas._maximum_x - self.dialog.canvas._minimum_x, original_width)
        self.assertEqual(self.dialog.ranges, ((10, 20),))
        self.assertEqual(self.dialog.canvas.tops, tuple(layer.z_mm for layer in self.layers))
        canvas = self.dialog.canvas
        QTest.mousePress(canvas, Qt.MouseButton.RightButton, pos=self._point(50))
        QTest.mouseMove(canvas, self._point(50) + QPoint(40, 0))
        QTest.mouseRelease(canvas, Qt.MouseButton.RightButton, pos=self._point(50) + QPoint(40, 0))
        self.assertNotEqual(canvas.yaw_deg, 90)
        self.assertEqual(self.dialog.rotation_slider.value(), canvas.yaw_deg)

    def test_wheel_zoom_keeps_proportions_cursor_anchor_and_layer_selection(self):
        canvas = self.dialog.canvas
        self.assertFalse(self.dialog.fit_button.isEnabled())
        canvas.set_rotation(90)
        self.assertFalse(self.dialog.fit_button.isEnabled())
        cursor = self._point(50) + QPoint(5, 0)
        z = (canvas.plot_rect().bottom() + canvas.pan - cursor.y()) / canvas._scale()
        model_x = (cursor.x() - canvas.plot_rect().center().x() - canvas.pan_x) / canvas._scale()
        model_x += (canvas._minimum_x + canvas._maximum_x) / 2
        before_width = canvas.x_for_position(canvas._maximum_x) - canvas.x_for_position(canvas._minimum_x)
        before_height = canvas.y_for_z(5) - canvas.y_for_z(15)
        before_layer = canvas.layer_at_y(cursor.y())

        def rendered_width():
            image = canvas.grab().toImage()
            color = canvas.layer_color(canvas.target_time_s, self.layers[49].total_time_s)
            return sum(image.pixelColor(x, cursor.y()) == color for x in range(image.width()))

        before_pixels = rendered_width()
        event = QWheelEvent(QPointF(cursor), QPointF(canvas.mapToGlobal(cursor)), QPoint(), QPoint(0, 120),
                            Qt.MouseButton.NoButton, Qt.KeyboardModifier.NoModifier, Qt.ScrollPhase.NoScrollPhase, False)
        self.app.sendEvent(canvas, event)
        self.assertTrue(self.dialog.fit_button.isEnabled())
        after_width = canvas.x_for_position(canvas._maximum_x) - canvas.x_for_position(canvas._minimum_x)
        after_height = canvas.y_for_z(5) - canvas.y_for_z(15)
        self.assertAlmostEqual(after_width / before_width, 1.2)
        self.assertAlmostEqual(after_height / before_height, 1.2)
        self.assertAlmostEqual(canvas.x_for_position(model_x), cursor.x())
        self.assertAlmostEqual(canvas.y_for_z(z), cursor.y())
        self.assertEqual(canvas.layer_at_y(cursor.y()), before_layer)
        self.assertAlmostEqual(rendered_width() / before_pixels, 1.2, delta=.03)
        QTest.mousePress(canvas, Qt.MouseButton.MiddleButton, pos=cursor)
        QTest.mouseMove(canvas, cursor + QPoint(12, 18))
        QTest.mouseRelease(canvas, Qt.MouseButton.MiddleButton, pos=cursor + QPoint(12, 18))
        self.assertAlmostEqual(canvas.x_for_position(model_x), cursor.x() + 12)
        self.assertAlmostEqual(canvas.y_for_z(z), cursor.y() + 18)
        self.dialog.fit_button.click()
        self.assertEqual((canvas.zoom, canvas.pan, canvas.pan_x), (1, 0, 0))
        self.assertFalse(self.dialog.fit_button.isEnabled())
        QTest.mousePress(canvas, Qt.MouseButton.MiddleButton, pos=cursor)
        QTest.mouseMove(canvas, cursor + QPoint(12, 18))
        QTest.mouseRelease(canvas, Qt.MouseButton.MiddleButton, pos=cursor + QPoint(12, 18))
        self.assertTrue(self.dialog.fit_button.isEnabled())
        self.dialog.fit_button.click()
        self.assertFalse(self.dialog.fit_button.isEnabled())
        self.app.sendEvent(canvas, event)
        down = QWheelEvent(QPointF(cursor), QPointF(canvas.mapToGlobal(cursor)), QPoint(), QPoint(0, -120),
                          Qt.MouseButton.NoButton, Qt.KeyboardModifier.NoModifier, Qt.ScrollPhase.NoScrollPhase, False)
        self.app.sendEvent(canvas, down)
        self.assertFalse(self.dialog.fit_button.isEnabled())

    def test_main_window_apply_cancel_reset_and_center(self):
        with tempfile.TemporaryDirectory() as temporary:
            window = MainWindow(user_settings_path=Path(temporary) / "settings.json",
                enable_update_check=False, enable_startup_slicer_discovery=False)
            window.show()
            self.app.processEvents()
            self.assertFalse(window.layer_range_button.isEnabled())
            self.assertEqual(window.layer_range_button.text(), "Bereichseditor öffnen")
            window.layer_range_button_row.layout().activate()
            self.assertEqual(window.layer_range_button.width(), window.layer_range_button.sizeHint().width())
            self.assertEqual(window.layer_range_button.height(), window.reset_button.height())
            geometry_layout = window.geometry_fields_layout
            self.assertIs(geometry_layout.itemAt(geometry_layout.count() - 1).widget(), window.layer_range_button_row)
            self.assertIs(window.layer_range_button_row.layout().itemAt(0).widget(), window.layer_range_info_button)
            self.assertIs(window.layer_range_button_row.layout().itemAt(1).widget(), window.layer_range_button)
            self.assertIs(window.layer_range_button_row.layout().itemAt(2).widget(), window.layer_range_summary)
            self.assertEqual(window.layer_range_summary.text(), "")
            self.assertFalse(window.layer_range_summary.wordWrap())
            self.assertTrue(window.layer_range_summary.isHidden())
            def assert_left_aligned():
                row = window.layer_range_button_row
                row.resize(max(900, row.width()), row.height())
                row.layout().activate()
                self._settle_layout()
                info = window.layer_range_info_button
                reference = window._setting_widgets["maximum_contraction_angle_deg"].info_button
                self.assertEqual(info.mapTo(window, QPoint()).x(), reference.mapTo(window, QPoint()).x())
                gap = window.layer_range_button_row.layout().spacing()
                self.assertEqual(window.layer_range_button.x(), info.x() + info.width() + gap)
                if not window.layer_range_summary.isHidden():
                    self.assertEqual(window.layer_range_summary.x(),
                                     window.layer_range_button.x() + window.layer_range_button.width() + gap)
            assert_left_aligned()
            for ranges, expected in (
                (((2, 3),), "1 Ausschlussbereich"),
                (((2, 3), (5, 6)), "2 Ausschlussbereiche"),
            ):
                window._excluded_layer_ranges = ranges
                window._refresh_layer_range_tool()
                self.assertEqual(window.layer_range_summary.text(), expected)
                self.assertFalse(window.layer_range_summary.isHidden())
                assert_left_aligned()
            window._excluded_layer_ranges = ()
            window._refresh_layer_range_tool()
            self.assertIn("<b>Was macht dieses Werkzeug?</b>", window.layer_range_info_button.toolTip())
            self.assertIn("&#8226; Der minimale Turmdurchmesser kann dadurch nicht unterschritten werden</p>",
                          window.layer_range_info_button.toolTip())
            snapshot = make_snapshot(Path(temporary) / "source.gcode", (1,) * 100)
            window.analysis_snapshot = snapshot
            window.source_preslice_result = SimpleNamespace(preview_source_data=SimpleNamespace(object_segments=object_segments(snapshot.layers)), cleanup=lambda: None)
            with patch.object(window, "_schedule_feasibility_validation"):
                original = window.collect_settings()
                window.show_layer_range_tool()
                dialog = window._layer_range_dialog
                self.assertIsNotNone(dialog)
                self.assertEqual(dialog.windowTitle(), "Bereichseditor · Aufweitung ausschließen")
                self.app.processEvents()
                self.assertFalse(dialog.isMaximized())
                expected = dialog.frameGeometry()
                expected.moveCenter(window.frameGeometry().center())
                available = window.screen().availableGeometry()
                expected.moveTopLeft(QPoint(
                    max(available.left(), min(expected.left(), available.right() - expected.width() + 1)),
                    max(available.top(), min(expected.top(), available.bottom() - expected.height() + 1))))
                self.assertLess((dialog.frameGeometry().topLeft() - expected.topLeft()).manhattanLength(), 10)
                self.assertGreater(dialog.apply_button.x(), dialog.cancel_button.x())
                self.assertEqual(dialog.windowModality(), Qt.WindowModality.WindowModal)
                self.assertEqual(dialog.target_info_button.toolTip(), window._setting_widgets["target_layer_time_s"].info_button.toolTip())
                self.assertEqual(dialog.add_button.height(), window.reset_button.height())
                dialog.target_spin.setValue(15)
                dialog.target_spin.stepUp()
                self.assertAlmostEqual(dialog.target_spin.value(), 15.1)
                dialog.commit_range(-1, 10, 20)
                dialog.color_start_spin.setValue(.1)
                dialog.color_full_spin.setValue(.7)
                self.assertEqual(window.collect_settings(), original)
                self.assertEqual(window._range_color_thresholds, (0, 1))
                dialog.apply_button.click()
                self.app.processEvents()
                self.assertIsNone(window._layer_range_dialog)
                self.assertEqual(window.collect_settings().excluded_layer_ranges, ((10, 20),))
                self.assertAlmostEqual(window.target_time_spin.value(), 15.1)
                self.assertEqual(window._range_color_thresholds, (.1, .7))
                window.target_time_spin.stepDown()
                self.assertAlmostEqual(window.target_time_spin.value(), 15)
                accepted = window.collect_settings()
                for action in ("button", "escape", "close"):
                    window.show_layer_range_tool()
                    dialog = window._layer_range_dialog
                    self.app.processEvents()
                    self.assertEqual(dialog.ranges, ((10, 20),))
                    self.assertEqual(dialog.target_spin.value(), 15)
                    self.assertEqual(dialog.color_start_spin.value(), .1)
                    self.assertEqual(dialog.color_full_spin.value(), .7)
                    dialog.target_spin.setValue(30)
                    dialog.commit_range(-1, 35, 45)
                    dialog.color_start_spin.setValue(.2)
                    dialog.color_full_spin.setValue(.8)
                    self.assertEqual(window.collect_settings(), accepted)
                    if action == "button":
                        dialog.cancel_button.click()
                    elif action == "escape":
                        dialog.canvas.setFocus()
                        QTest.keyClick(dialog.canvas, Qt.Key.Key_Escape)
                    else:
                        dialog.close()
                    self.app.processEvents()
                    self.assertIsNone(window._layer_range_dialog)
                    self.assertEqual(window.collect_settings(), accepted)
                    self.assertEqual(window._range_color_thresholds, (.1, .7))
                window.show_layer_range_tool()
                self.assertEqual(window._layer_range_dialog.ranges, ((10, 20),))
                self.assertEqual(window._layer_range_dialog.color_start_spin.value(), .1)
                self.assertEqual(window._layer_range_dialog.color_full_spin.value(), .7)
                window._discard_source_preslice("source_replaced")
                self.assertEqual(window.collect_settings().excluded_layer_ranges, ())
                self.assertIsNone(window._layer_range_dialog)
                self.assertFalse(window.layer_range_button.isEnabled())
            window.close()
            self.app.processEvents()

    def test_apply_commits_focused_layer_editor_and_disabled_tool_cannot_apply(self):
        self.dialog.commit_range(-1, 10, 20)
        self.app.processEvents()
        last = self.dialog.range_rows[0][2]
        last.setFocus()
        last.selectAll()
        QTest.keyClicks(last, "25")
        self.assertEqual(self.dialog.ranges, ((10, 20),))
        self.dialog.set_editing_enabled(False)
        self.dialog.apply_button.click()
        self.assertTrue(self.dialog.isVisible())
        self.assertTrue(self.dialog.cancel_button.isEnabled())
        self.dialog.set_editing_enabled(True)
        self.dialog.apply_button.click()
        self.assertEqual(self.dialog.ranges, ((10, 25),))
        self.assertEqual(self.dialog.result(), self.dialog.DialogCode.Accepted)

    def test_automatic_drawing_top_down_names_and_rotation_reset(self):
        canvas = self.dialog.canvas
        self.assertFalse(any(button.text() in ("+ Bereich zeichnen", "Bereich entfernen")
                             for button in self.dialog.findChildren(QPushButton)))
        for first, last in ((10, 20), (30, 40)):
            QTest.mousePress(canvas, Qt.MouseButton.LeftButton, pos=self._point(first))
            QTest.mouseRelease(canvas, Qt.MouseButton.LeftButton, pos=self._point(last))
            self.app.processEvents()
        self.assertEqual(self.dialog.ranges, ((30, 40), (10, 20)))
        self.assertEqual(canvas.ranges, self.dialog.ranges)
        self.assertEqual([(a.value(), b.value(), button.text()) for _, a, b, button in self.dialog.range_rows],
                         [(30, 40, "Ausschlussbereich 1"), (10, 20, "Ausschlussbereich 2")])
        self.dialog.rotation_slider.setValue(45)
        self.assertTrue(self.dialog.rotation_reset_button.isEnabled())
        self.dialog.rotation_reset_button.click()
        self.assertEqual(canvas.yaw_deg, 0)
        self.assertFalse(self.dialog.rotation_reset_button.isEnabled())
        self.assertEqual(self.dialog.ranges, ((30, 40), (10, 20)))
        # Escape cancels one drawing gesture; the next is immediately possible.
        QTest.mousePress(canvas, Qt.MouseButton.LeftButton, pos=self._point(60))
        QTest.mouseMove(canvas, self._point(70))
        QTest.keyClick(canvas, Qt.Key.Key_Escape)
        QTest.mouseRelease(canvas, Qt.MouseButton.LeftButton, pos=self._point(70))
        self.assertTrue(self.dialog.isVisible())
        self.assertEqual(self.dialog.ranges, ((30, 40), (10, 20)))
        QTest.mousePress(canvas, Qt.MouseButton.LeftButton, pos=self._point(60))
        QTest.mouseRelease(canvas, Qt.MouseButton.LeftButton, pos=self._point(70))
        self.app.processEvents()
        self.assertEqual(self.dialog.ranges, ((60, 70), (30, 40), (10, 20)))

    def test_slider_snaps_near_quarter_turns_but_keeps_fine_control(self):
        slider = self.dialog.rotation_slider
        slider.setSliderDown(True)
        for requested, expected in ((-179, -180), (-87, -90), (-3, 0),
                                    (81, 90), (99, 90), (177, 180), (171, 180),
                                    (-81, -90), (-99, -90), (-171, -180),
                                    (76, 76), (80, 80), (100, 100),
                                    (-80, -80), (-100, -100)):
            slider.setValue(requested)
            self.assertEqual(slider.value(), expected)
            self.assertEqual(self.dialog.canvas.yaw_deg, expected)
        slider.setSliderDown(False)
        slider.setValue(87)
        self.assertEqual(self.dialog.canvas.yaw_deg, 87)
        self.assertEqual(slider.tickInterval(), 90)

    def test_color_reset_updates_both_limits_atomically_in_the_draft(self):
        dialog = self.dialog
        self.assertFalse(dialog.color_reset_button.isEnabled())
        dialog.commit_range(-1, 10, 20)
        dialog.color_start_spin.setValue(.8)
        dialog.color_full_spin.setValue(1.2)
        self.assertTrue(dialog.color_reset_button.isEnabled())
        received = []
        dialog.color_thresholds_changed.connect(lambda a, b: received.append((a, b)))
        dialog.color_reset_button.click()
        self.assertEqual(received, [(0., 1.)])
        self.assertEqual((dialog.color_start_spin.value(), dialog.color_full_spin.value()), (0., 1.))
        self.assertEqual((dialog.canvas.gradient_start_deficit_s, dialog.canvas.gradient_full_deficit_s), (0., 1.))
        self.assertEqual((dialog.legend.start_deficit_s, dialog.legend.full_deficit_s), (0., 1.))
        self.assertEqual(dialog.color_gradient.full_handle.value(), 10)
        self.assertFalse(dialog.color_reset_button.isEnabled())
        self.assertEqual(dialog.ranges, ((10, 20),))
        self.assertEqual(dialog.result(), dialog.DialogCode.Rejected)
        self.assertTrue(dialog.isVisible())

    def test_preview_selection_keeps_scroll_after_mouse_release_and_rebuild(self):
        # Styling and real press/release expose Qt's queued content resize.
        previous_style = self.dialog.styleSheet()
        self.dialog.setStyleSheet((ROOT / 'src/cooling_tower/gui/styles.qss').read_text(encoding='utf-8'))
        self.addCleanup(lambda: self.dialog.setStyleSheet(previous_style))
        self.dialog.resize(1000, 760)
        for start in range(1, 92, 10):
            self.dialog.commit_range(-1, start, start + 2)
            self.app.processEvents()
        QTest.qWait(40)
        bar = self.dialog.scroll.verticalScrollBar()
        self.dialog.select_range(0)
        QTest.qWait(20)
        bar.setValue(0)
        row_before = self.dialog.range_rows[-1][0]
        QTest.mouseClick(self.dialog.canvas, Qt.MouseButton.LeftButton, pos=self._point(2))
        QTest.qWait(60)
        self.assertIs(self.dialog.range_rows[-1][0], row_before)
        self.assertEqual(self.dialog.selected, 9)
        for change in (False, True):
            if change:
                self.dialog.commit_range(9, 1, 4)
            # Rebuilding and QScrollArea's extent update are queued. Wait for
            # the observable result instead of a fixed 60 ms under CPU load.
            settled_turns = 0
            for _ in range(40):
                QTest.qWait(25)
                row = self.dialog.range_rows[-1][0]
                top = row.mapTo(self.dialog.scroll.viewport(), QPoint()).y()
                settled = (
                    0 <= top
                    and top + row.height() <= self.dialog.scroll.viewport().height()
                    and not self.dialog._rows_pending
                    and not self.dialog._selection_scroll_timer.isActive()
                    and not self.dialog._pane_resize_timer.isActive()
                )
                settled_turns = settled_turns + 1 if settled else 0
                if settled_turns >= 2:
                    break
            self.assertGreaterEqual(top, 0)
            self.assertLessEqual(top + row.height(), self.dialog.scroll.viewport().height())
        # The automatic selection scroll must not lock out manual navigation.
        bar.setValue(0)
        QTest.qWait(40)
        self.assertEqual(bar.value(), 0)

    def test_selected_row_scrolls_into_view_and_footer_spans_window(self):
        for start in range(1, 92, 10):
            self.dialog.commit_range(-1, start, start + 2)
        QTest.qWait(20)
        for index in (9, 0, 5):
            self.dialog.select_range(index)
            QTest.qWait(20)
            row = self.dialog.range_rows[index][0]
            top = row.mapTo(self.dialog.scroll.viewport(), QPoint(0, 0)).y()
            self.assertGreaterEqual(top, 0)
            self.assertLessEqual(top + row.height(), self.dialog.scroll.viewport().height())
        self.assertEqual(self.dialog.footer_divider.x(), 0)
        self.assertEqual(self.dialog.footer_divider.width(), self.dialog.width())
        self.assertEqual(self.dialog.splitter.handleWidth(), 1)
        self.assertGreaterEqual(self.dialog.splitter.mapTo(self.dialog, QPoint()).y(), 18)

    def test_exact_silhouette_preserves_islands_and_rotation(self):
        with tempfile.TemporaryDirectory() as temporary:
            left = trimesh.creation.box(extents=(2, 4, 20))
            left.apply_translation((-4, 0, 10))
            right = left.copy()
            right.apply_translation((8, 0, 0))
            path = Path(temporary) / "islands.stl"
            trimesh.util.concatenate((left, right)).export(path)
            source = SourceArtifact.capture(path, source_kind=SourceKind.STL)
            sections = load_layer_silhouette(source, self.layers)
            canvas = LayerRangeCanvas(self.layers, object_segments(self.layers), silhouette=sections)
            self.assertTrue(all(len(row) == 2 for row in canvas._intervals))
            self.assertEqual(canvas._intervals[0], ((-5, -3), (3, 5)))
            canvas.set_rotation(90)
            self.assertTrue(all(len(row) == 1 for row in canvas._intervals))
            self.assertAlmostEqual(canvas._intervals[0][0][0], -2)
            self.assertAlmostEqual(canvas._intervals[0][0][1], 2)
            self.assertTrue(source.matches_current_file(verify_content=True))
            with patch("cooling_tower.preview.layer_silhouette.MAXIMUM_SILHOUETTE_SEGMENTS", 1):
                with self.assertRaisesRegex(ValueError, "Speicherlimit"):
                    load_layer_silhouette(source, self.layers)
            self.assertTrue(source.matches_current_file(verify_content=True))
            path.write_bytes(b"changed")
            with self.assertRaises(SourceChangedError):
                load_layer_silhouette(source, self.layers)

    def test_real_manifold_model_has_complete_silhouette_in_every_layer(self):
        source = SourceArtifact.capture(ROOT / "input/Test-STL (manifold).stl", source_kind=SourceKind.STL)
        layers = tuple(make_layer(i, i * 178.22 / 990, 178.22 / 990, 10) for i in range(1, 991))
        sections = load_layer_silhouette(source, layers)
        self.assertEqual(len(sections.segments_xy), 990)
        self.assertTrue(all(len(row) for row in sections.segments_xy))
        self.assertTrue(all(not row.flags.writeable for row in sections.segments_xy))
        canvas = LayerRangeCanvas(layers, object_segments(layers), silhouette=sections)
        for angle in (0, 45, 90, -135):
            canvas.set_rotation(angle)
            self.assertTrue(all(row and all(b >= a for a, b in row) for row in canvas._intervals))
        self.assertTrue(source.matches_current_file(verify_content=True))

    def test_dense_layers_do_not_cancel_each_other_in_heatmap(self):
        layers = tuple(make_layer(i, i * .1, .1, 10) for i in range(1, 1001))
        canvas = LayerRangeCanvas(layers, object_segments(layers))
        canvas.resize(360, 360)
        canvas.show()
        self.addCleanup(canvas.close)
        image = canvas.grab().toImage()
        x = round(canvas.plot_rect().center().x())
        top, bottom = round(canvas.y_for_z(layers[-1].z_mm)), round(canvas.y_for_z(0))
        for y in range(top + 1, bottom - 1):
            self.assertEqual(image.pixelColor(x, y).name(), canvas.OBJECT_COLOR, f"Ungefüllte Bildzeile {y}")

    def test_main_window_uses_and_discards_cached_original_silhouette(self):
        with tempfile.TemporaryDirectory() as temporary:
            window = MainWindow(user_settings_path=Path(temporary) / "settings.json",
                enable_update_check=False, enable_startup_slicer_discovery=False)
            self.addCleanup(window.close)
            window.source_artifact = SourceArtifact.capture(ROOT / "input/Test-STL (manifold).stl", source_kind=SourceKind.STL)
            snapshot = make_snapshot(Path(temporary) / "source.gcode", (1,) * 100)
            window.analysis_snapshot = snapshot
            window.source_preslice_result = SimpleNamespace(
                preview_source_data=SimpleNamespace(object_segments=object_segments(snapshot.layers)), cleanup=lambda: None)
            with patch("cooling_tower.preview.layer_silhouette.load_layer_silhouette", wraps=load_layer_silhouette) as loader:
                window.show_layer_range_tool()
                original_shape = window._layer_range_silhouette
                self.assertIsNotNone(original_shape)
                self.assertIs(window._layer_range_dialog.canvas._silhouette, original_shape)
                window._layer_range_dialog.reject()
                window.show_layer_range_tool()
                self.assertIs(window._layer_range_dialog.canvas._silhouette, original_shape)
                self.assertEqual(loader.call_count, 1)
                window._discard_source_preslice("source_replaced")
                self.assertIsNone(window._layer_range_silhouette)
                self.assertIsNone(window._layer_range_dialog)
            self.assertTrue(window.source_artifact.matches_current_file(verify_content=True))


if __name__ == "__main__":
    unittest.main()
