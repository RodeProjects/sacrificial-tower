from __future__ import annotations

import json
import os
import sys
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch


PROJECT_ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = PROJECT_ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("COOLING_TOWER_DISABLE_SLICER_DISCOVERY", "1")

from PySide6.QtCore import QPoint, QRect, Qt
from PySide6.QtWidgets import QApplication, QLabel

from cooling_tower.application import append_runtime_diagnostic
from cooling_tower.gui.design_tokens import METRICS
from cooling_tower.gui.main_window import MainWindow
from cooling_tower.gui.widgets import FooterNoticeDropdown
from cooling_tower.models import SlicerFamily
from cooling_tower.preview import OutputMode
from cooling_tower.slicers.base import classify_profile_source
from cooling_tower.slicers import (
    SlicerDiscoveryResult,
    SlicerDiscoverySource,
    SlicerGuiState,
    SlicerInstallation,
)
from cooling_tower.version import APP_VERSION, APP_VERSION_LABEL
from cooling_tower.update import UpdateInfo


class RequestedGuiChangesTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)

    def tearDown(self) -> None:
        self.app.processEvents()
        self.temporary.cleanup()

    def window(self) -> MainWindow:
        return MainWindow(user_settings_path=self.root / "settings.json")

    @staticmethod
    def write_export_folder(
        output_root: Path,
        name: str,
        created_at: str,
    ) -> Path:
        folder = output_root / name
        folder.mkdir(parents=True)
        output_path = folder / "tower.stl"
        output_path.write_text("solid tower\nendsolid tower\n", encoding="utf-8")
        (folder / "export_summary.txt").write_text(
            "Export erfolgreich\n",
            encoding="utf-8",
        )
        (folder / "export_report.json").write_text(
            json.dumps(
                {
                    "report_type": "cooling_tower_export_diagnostics",
                    "created_at": created_at,
                    "summary": {"export_succeeded": True},
                    "output": {"path": str(output_path)},
                }
            ),
            encoding="utf-8",
        )
        return folder

    def test_header_shows_current_version_below_action_icons(self) -> None:
        window = self.window()
        window.show()
        self.app.processEvents()

        self.assertRegex(APP_VERSION, r"^\d+\.\d+\.\d+$")
        self.assertEqual(window.version_label.text(), APP_VERSION_LABEL)
        self.assertEqual(window.version_label.objectName(), "versionLabel")
        self.assertNotIn("alpha", window.version_label.text().casefold())
        self.assertNotIn("alpha", window.version_label.toolTip().casefold())
        self.assertGreater(
            window.version_label.mapTo(window, QPoint(0, 0)).y(),
            window.options_button.mapTo(window, QPoint(0, 0)).y(),
        )
        self.assertEqual(
            window.version_label.mapTo(window, QPoint(0, 0)).x()
            + window.version_label.width(),
            window.options_button.mapTo(window, QPoint(0, 0)).x()
            + window.options_button.width(),
        )
        window.close()

    def test_update_button_appears_right_of_version_only_for_an_update(self) -> None:
        window = self.window()
        window.show()
        self.app.processEvents()
        self.assertTrue(window.update_button.isHidden())

        window._update_check_request_id = 7
        window._on_update_check_succeeded(
            7,
            UpdateInfo(
                version="0.4.2",
                installer_url=(
                    "https://github.com/RodeProjects/"
                    "sacrificial-tower-updates/releases/download/v0.4.2/"
                    "SacrificialTowerSetup-0.4.2.exe"
                ),
                sha256="0" * 64,
                size_bytes=123,
            ),
        )
        self.app.processEvents()
        self.assertFalse(window.update_button.isHidden())
        self.assertGreater(
            window.update_button.mapTo(window, QPoint(0, 0)).x(),
            window.version_label.mapTo(window, QPoint(0, 0)).x(),
        )

        window._on_update_check_succeeded(7, None)
        self.assertTrue(window.update_button.isHidden())
        window.close()

    def test_verified_update_counts_down_before_installer_and_shutdown(self) -> None:
        window = self.window()
        window._update_download_request_id = 9
        installer = self.root / "SacrificialTowerSetup-test.exe"
        events: list[str] = []

        with (
            patch(
                "cooling_tower.gui.main_window.UpdateRestartCountdownDialog"
            ) as dialog_type,
            patch.object(
                window.update_service,
                "launch_installer",
                side_effect=lambda _path: events.append("installer"),
            ),
            patch.object(
                QApplication,
                "quit",
                side_effect=lambda *_args: events.append("beenden"),
            ),
        ):
            dialog_type.return_value.exec_countdown.side_effect = (
                lambda: events.append("countdown")
            )
            window._on_update_download_succeeded(9, installer)

        dialog_type.assert_called_once_with(window, seconds=5)
        self.assertEqual(events, ["countdown", "installer", "beenden"])
        window.close()

    def test_slicer_titles_are_left_aligned(self) -> None:
        window = self.window()
        for label in window._slicer_width_labels:
            self.assertTrue(label.alignment() & Qt.AlignmentFlag.AlignLeft)
            self.assertFalse(label.alignment() & Qt.AlignmentFlag.AlignRight)
        window.close()

    def test_slicer_header_stays_compact_and_profiles_remain_accessible(self) -> None:
        window = self.window()
        window.machine_profile_combo.addItem("Kobra 3 V2")
        window.process_profile_combo.addItem("0,20 mm Standard")
        window.filament_profile_combo.addItem("PLA Schwarz")
        installation = SlicerInstallation(
            adapter_id="requested-ui-test",
            product_name="Testslicer",
            version="1.0",
            executable_path=self.root / "slicer.exe",
            verified=True,
            capabilities=frozenset(),
            discovery_source=SlicerDiscoverySource.KNOWN_PATH,
            family=SlicerFamily.OTHER,
        )

        window.show()
        window.workflow.analysis_succeeded("test.gcode")
        window.workflow.slicer_succeeded("Testslicer")
        window._set_slicer_header_summary(installation)
        self.app.processEvents()

        self.assertEqual(
            window.slicer_group.summary_label.text(),
            installation.display_name,
        )
        self.assertEqual(
            window.slicer_group.title_note_label.text(),
            "(automatisch erkannt)",
        )
        self.assertFalse(window.slicer_group.title_note_label.isHidden())
        self.assertEqual(
            window.slicer_group.title_note_label.palette().color(
                window.slicer_group.title_note_label.foregroundRole()
            ).name(),
            "#176b45",
        )
        self.assertTrue(window.slicer_group.summary_note_label.isHidden())
        self.assertEqual(
            window.slicer_group.header.height(),
            METRICS.card_header_height_px,
        )
        self.assertEqual(
            window.slicer_group.header.height(),
            window.source_group.header.height(),
        )
        accessible = window.slicer_selector_column.accessibleDescription()
        self.assertIn(f"Slicer: {installation.display_name}", accessible)
        self.assertIn("Maschinenprofil: Kobra 3 V2", accessible)
        self.assertIn("Filamentprofil: PLA Schwarz", accessible)
        self.assertIn("Prozessprofil: 0,20 mm Standard", accessible)
        self.assertTrue(
            window.slicer_group.title_label.alignment()
            & Qt.AlignmentFlag.AlignLeft
        )
        left_layout = window.slicer_group.header_left.layout()
        self.assertTrue(left_layout.alignment() & Qt.AlignmentFlag.AlignLeft)
        self.assertEqual(window.slicer_group.title_label.text(), "Slicer")
        self.assertTrue(window.slicer_group.toggle_button.isHidden())
        window.close()

    def test_regular_card_headers_keep_the_standard_height(self) -> None:
        window = self.window()
        window.resize(1200, 1000)
        window.show()
        window.workflow.analysis_succeeded("test.gcode")
        window.workflow.slicer_succeeded("Testslicer")
        self.app.processEvents()

        for card in (
            window.timing_group,
            window.geometry_group,
            window.stability_group,
            window.overhang_group,
        ):
            self.assertEqual(
                card.header.height(),
                METRICS.card_header_height_px,
            )
        window.close()

    def test_profile_dropdowns_show_all_grouped_presets_with_scrollbars(self) -> None:
        window = self.window()
        self.assertIs(
            window.profile_filter_label.parentWidget(),
            window.slicer_information_column,
        )
        selector_layout = window.slicer_selectors_layout
        self.assertLess(
            selector_layout.indexOf(window.machine_profile_label),
            selector_layout.indexOf(window.filament_profile_label),
        )
        self.assertLess(
            selector_layout.indexOf(window.filament_profile_label),
            selector_layout.indexOf(window.process_profile_label),
        )
        records = tuple(
            SimpleNamespace(
                name=f"Profil {index:02d}",
                profile_id=f"profile-{index:02d}",
                path=self.root / f"profile-{index:02d}.json",
                source="user" if index < 7 else "system",
            )
            for index in range(14)
        )
        result = SimpleNamespace(
            selected=None,
            machine_options=records,
            process_options=records,
            filament_options=records,
        )

        window._populate_profile_combos(result)

        for combo in (
            window.machine_profile_combo,
            window.process_profile_combo,
            window.filament_profile_combo,
        ):
            with self.subTest(combo=combo.objectName()):
                profile_paths = tuple(
                    combo.itemData(index)
                    for index in range(combo.count())
                    if isinstance(combo.itemData(index), str)
                )
                self.assertEqual(len(profile_paths), len(records))
                self.assertEqual(combo.itemText(0), "- User presets -")
                self.assertEqual(combo.itemText(8), "- System presets -")
                self.assertEqual(combo.maxVisibleItems(), 10)
                self.assertEqual(
                    combo.view().verticalScrollBarPolicy(),
                    Qt.ScrollBarPolicy.ScrollBarAsNeeded,
                )
                self.assertFalse(combo.model().item(0).isEnabled())
                self.assertFalse(combo.model().item(8).isEnabled())
                self.assertTrue(
                    all(
                        "[" not in combo.itemText(index)
                        for index in range(combo.count())
                        if isinstance(combo.itemData(index), str)
                    )
                )

        requests = []
        window.profile_match_result = result
        window.start_profile_matching = lambda **kwargs: requests.append(kwargs)
        window.machine_profile_combo.setCurrentIndex(2)
        self.assertEqual(requests, [])
        self.assertTrue(window.profile_confirm_button.isEnabled())
        self.assertTrue(window.profile_status_label.isHidden())
        window.filament_profile_combo.setCurrentIndex(2)
        self.assertEqual(requests, [])
        window.close()

    def test_profile_origin_uses_real_storage_location(self) -> None:
        installation = SlicerInstallation(
            adapter_id="origin-test",
            product_name="Testslicer",
            version="1.0",
            executable_path=self.root / "install" / "slicer.exe",
            verified=True,
            capabilities=frozenset(),
            discovery_source=SlicerDiscoverySource.KNOWN_PATH,
            family=SlicerFamily.OTHER,
        )
        bundled = (
            self.root
            / "install"
            / "resources"
            / "profiles"
            / "bundled.json"
        )
        user_created = (
            self.root
            / "appdata"
            / "Testslicer"
            / "user"
            / "default"
            / "custom.json"
        )
        mirrored_system = (
            self.root
            / "appdata"
            / "Testslicer"
            / "system"
            / "mirrored.json"
        )

        self.assertEqual(
            classify_profile_source(installation, bundled, "user"),
            "system",
        )
        self.assertEqual(
            classify_profile_source(installation, user_created, "system"),
            "user",
        )
        self.assertEqual(
            classify_profile_source(installation, mirrored_system, "user"),
            "system",
        )

        anycubic = replace(
            installation,
            adapter_id="anycubic_slicer_next",
        )
        anycubic_system_mirror = (
            self.root
            / "appdata"
            / "AnycubicSlicerNext"
            / "user"
            / "default"
            / "process"
            / "mirrored.json"
        )
        anycubic_account_preset = (
            self.root
            / "appdata"
            / "AnycubicSlicerNext"
            / "user"
            / "489681"
            / "process"
            / "custom.json"
        )
        anycubic_local_preset = anycubic_system_mirror.with_name("local.json")
        anycubic_system_mirror.parent.mkdir(parents=True)
        anycubic_system_mirror.write_text("{}", encoding="utf-8")
        anycubic_system_mirror.with_suffix(".info").write_text(
            "sync_info =\n"
            "user_id =\n"
            "setting_id =\n"
            "base_id = GP004\n",
            encoding="utf-8",
        )
        anycubic_local_preset.write_text("{}", encoding="utf-8")
        anycubic_local_preset.with_suffix(".info").write_text(
            "sync_info = update\n"
            "user_id =\n"
            "setting_id =\n"
            "base_id = GP004\n",
            encoding="utf-8",
        )
        self.assertEqual(
            classify_profile_source(
                anycubic,
                anycubic_system_mirror,
                "user",
            ),
            "system",
        )
        self.assertEqual(
            classify_profile_source(
                anycubic,
                anycubic_account_preset,
                "user",
            ),
            "user",
        )
        self.assertEqual(
            classify_profile_source(
                anycubic,
                anycubic_local_preset,
                "user",
            ),
            "user",
        )
        bambu = replace(installation, adapter_id="bambu_studio")
        self.assertEqual(
            classify_profile_source(
                bambu,
                anycubic_system_mirror,
                "user",
            ),
            "user",
        )

    def test_only_explicit_user_profiles_use_the_user_category(self) -> None:
        records = tuple(
            SimpleNamespace(
                name=source.title(),
                profile_id=source,
                path=self.root / f"{source}.json",
                source=source,
            )
            for source in ("user", "system", "project", "session", "temporary")
        )

        groups = dict(MainWindow._profile_option_groups(records))

        self.assertEqual(
            tuple(record.source for record in groups["- User presets -"]),
            ("user",),
        )
        self.assertEqual(
            tuple(record.source for record in groups["- System presets -"]),
            ("system",),
        )
        self.assertEqual(
            {record.source for record in groups["- Other presets -"]},
            {"project", "session", "temporary"},
        )

    def test_preview_quality_and_expansion_warning_use_fixed_values(self) -> None:
        window = self.window()
        window.show()
        window.workflow.analysis_succeeded("test.gcode")
        window.workflow.slicer_succeeded("Testslicer")
        self.app.processEvents()

        self.assertFalse(hasattr(window, "slicer_iterations_spin"))
        self.assertNotIn("slicer_iterations", window._setting_widgets)
        for quality, iterations in (
            ("fast", 1),
            ("balanced", 3),
            ("exact", 5),
        ):
            window.preview_quality_buttons[quality].click()
            self.assertEqual(window.preview_quality, quality)
            self.assertEqual(
                window._calibration_config().maximum_iterations,
                iterations,
            )
        self.assertEqual(
            window._export_calibration_config().maximum_iterations,
            5,
        )
        self.assertTrue(
            window.preview_action_control.isAncestorOf(
                window.preview_quality_panel
            )
        )
        self.assertTrue(
            window.preview_action_control.isAncestorOf(
                window.preview_button
            )
        )
        self.assertLess(
            window.preview_quality_panel.mapTo(window, window.preview_quality_panel.rect().topLeft()).y(),
            window.preview_button.mapTo(window, window.preview_button.rect().topLeft()).y(),
        )
        panel_left = window.preview_quality_panel.mapTo(
            window,
            window.preview_quality_panel.rect().topLeft(),
        ).x()
        panel_right = window.preview_quality_panel.mapTo(
            window,
            window.preview_quality_panel.rect().topRight(),
        ).x()
        preview_left = window.preview_button.mapTo(
            window,
            window.preview_button.rect().topLeft(),
        ).x()
        preview_right = window.preview_button.mapTo(
            window,
            window.preview_button.rect().topRight(),
        ).x()
        export_left = window.export_button.mapTo(
            window,
            window.export_button.rect().topLeft(),
        ).x()
        self.assertEqual(panel_left, preview_left)
        self.assertLessEqual(panel_right, preview_right)
        self.assertLess(panel_right, export_left)
        self.assertEqual(
            window.preview_quality_panel.geometry().bottom() + 1,
            window.preview_button.geometry().top(),
        )
        self.assertLessEqual(
            window.preview_action_control.width(),
            window.export_button.width(),
        )
        self.assertEqual(
            window.preview_action_control.width(),
            176,
        )
        self.assertEqual(window.preview_quality_panel.height(), 24)
        self.assertTrue(
            all(
                button.height() == 24
                for button in window.preview_quality_buttons.values()
            )
        )
        self.assertFalse(hasattr(window, "preview_quality_label"))
        quality_margins = window.preview_quality_panel.layout().contentsMargins()
        self.assertEqual(
            (
                quality_margins.left(),
                quality_margins.top(),
                quality_margins.right(),
                quality_margins.bottom(),
            ),
            (0, 0, 0, 0),
        )
        for quality, expected_hint in (
            ("fast", "kürzeste Wartezeit"),
            ("balanced", "Kompromiss"),
            ("exact", "höchste Genauigkeit"),
        ):
            self.assertIn(
                expected_hint,
                window.preview_quality_buttons[quality].toolTip(),
            )

        self.assertEqual(
            window.maximum_expansion_angle_spin.property("validationMaximum"),
            70.0,
        )
        window.maximum_expansion_angle_spin.setValue(50.0)
        self.assertTrue(
            window.maximum_expansion_angle_setting.message_label.isHidden()
        )
        window.maximum_expansion_angle_spin.setValue(51.0)
        self.app.processEvents()
        warning = window.maximum_expansion_angle_setting.message_label
        self.assertFalse(warning.isHidden())
        self.assertIn("Vorsicht", warning.text())
        self.assertIn("gut kalibrierten Drucker", warning.text())
        window.maximum_expansion_angle_spin.setValue(70.0)
        self.assertTrue(window.validate_form())
        window.close()

    def test_prediction_and_geometry_headers_use_the_unified_framing(self) -> None:
        window = self.window()
        window.resize(1200, 900)
        window.show()
        window.workflow.analysis_succeeded("test.gcode")
        window.workflow.slicer_succeeded("Testslicer")
        for _ in range(5):
            self.app.processEvents()

        window._refresh_prediction_advice("Analytische Schätzung")
        for _ in range(3):
            self.app.processEvents()
        self.assertEqual(
            window.prediction_advice_label.text(),
            "Die analytische Schätzung ist relativ ungenau.\n"
            "Eine Slicer-gestützte Schätzung wird empfohlen.",
        )

        header = window.geometry_calculation_header
        right_column = window.geometry_right_column
        self.assertEqual(
            header.mapTo(right_column, header.rect().topLeft()).x(),
            0,
        )
        self.assertEqual(header.width(), right_column.width())
        self.assertEqual(
            window.geometry_calculation_title.geometry().bottom() + 1,
            window.geometry_calculation_header_divider.geometry().top(),
        )

        stylesheet = window.styleSheet()
        self.assertIn(
            "QFrame#sectionCard[expanded=\"true\"] > "
            "QFrame#sectionCardHeader",
            stylesheet,
        )
        self.assertIn("border-bottom-left-radius: 0;", stylesheet)
        self.assertIn("border-bottom-right-radius: 0;", stylesheet)
        self.assertIn(
            "QFrame#geometryCalculationHeader {",
            stylesheet,
        )
        window.close()

    def test_main_scroll_range_ends_at_the_standard_bottom_margin(self) -> None:
        window = self.window()
        window.resize(760, 900)
        window.show()
        window.workflow.analysis_succeeded("test.gcode")
        window.workflow.slicer_succeeded("Testslicer")
        for _ in range(8):
            self.app.processEvents()

        window.resize(1700, 900)
        for _ in range(8):
            self.app.processEvents()

        self.assertEqual(
            window.ready_grid.height(),
            window.geometry_settings_group.geometry().bottom() + 1,
        )
        self.assertEqual(
            window.settings_content.height()
            - window.ready_grid.geometry().bottom()
            - 1,
            window.content_layout.contentsMargins().bottom(),
        )
        window.close()

    def test_geometry_card_fits_content_and_headers_meet_the_boundaries(self) -> None:
        window = self.window()
        window.resize(1700, 900)
        window.show()
        window.workflow.analysis_succeeded("test.gcode")
        window.workflow.slicer_succeeded("Testslicer")
        for _ in range(8):
            self.app.processEvents()

        geometry = window.geometry_settings_group
        split = window.geometry_split
        self.assertEqual(
            geometry.content_widget.height(),
            split.height(),
        )
        self.assertLessEqual(
            abs(
                geometry.height()
                - geometry.header.height()
                - geometry.body_divider.height()
                - split.height()
            ),
            2,
        )

        left_header = window.geometry_group.header
        right_header = window.stability_group.header
        divider = window.geometry_vertical_divider
        self.assertEqual(left_header.mapTo(split, left_header.rect().topLeft()).x(), 0)
        self.assertEqual(
            left_header.mapTo(split, left_header.rect().topRight()).x() + 1,
            divider.x(),
        )
        self.assertEqual(
            divider.geometry().right() + 1,
            right_header.mapTo(split, right_header.rect().topLeft()).x(),
        )
        self.assertEqual(
            right_header.mapTo(split, right_header.rect().topRight()).x(),
            split.rect().right(),
        )
        window.close()

    def test_numeric_fields_keep_uniform_units_when_focused_and_edited(self) -> None:
        window = self.window()
        window.show()
        window.workflow.analysis_succeeded("test.gcode")
        window.workflow.slicer_succeeded("Testslicer")
        self.app.processEvents()
        expected_units = {
            "target_layer_time_s": "s",
            "safety_factor": "",
            "minimum_outer_radius_mm": "mm",
            "maximum_outer_radius_mm": "mm",
            "minimum_wall_thickness_mm": "mm",
            "maximum_wall_thickness_mm": "mm",
            "wall_path_width_mm": "mm",
            "minimum_inner_radius_mm": "mm",
            "manual_base_width_mm": "mm",
            "base_height_mm": "mm",
            "maximum_expansion_angle_deg": "°",
            "maximum_contraction_angle_deg": "°",
            "maximum_wall_change_per_mm_z": "mm/mm",
            "mesh_segments": "Segm.",
            "local_reference_window": "Layer",
        }
        self.assertEqual(set(window._setting_widgets), set(expected_units))
        for name, setting in window._setting_widgets.items():
            with self.subTest(setting=name):
                self.assertNotIn("[", setting.label.text())
                self.assertEqual(setting.unit_label.text(), expected_units[name])
                self.assertEqual(setting.unit_label.width(), 44)
                self.assertEqual(
                    setting.unit_label.geometry().right() + 1,
                    setting.editor.width() - 24,
                )

        target = window._setting_widgets["target_layer_time_s"]
        target.editor.setFocus()
        target.editor.selectAll()
        target.editor.lineEdit().setText("23")
        self.app.processEvents()
        self.assertTrue(target.unit_label.isVisible())
        self.assertEqual(target.unit_label.text(), "s")
        self.assertEqual(target.unit_label.width(), 44)
        self.assertGreaterEqual(target.editor.lineEdit().width(), 67)
        self.assertEqual(
            window._setting_widgets[
                "maximum_wall_change_per_mm_z"
            ].label.text(),
            "Max. Wandstärkenänderung",
        )
        window.close()

    def test_footer_actions_require_successful_gcode_and_slicer_stages(self) -> None:
        window = self.window()
        window.show()
        actions = (
            window.open_output_button,
            window.open_stl_button,
            window.reset_button,
            window.preview_action_control,
            window.export_button,
        )
        self.assertTrue(all(action.isHidden() for action in actions))

        window.workflow.analysis_succeeded("test.gcode")
        self.assertTrue(all(action.isHidden() for action in actions))
        window.workflow.slicer_unavailable("Kein Slicer verfügbar")
        self.assertTrue(all(action.isHidden() for action in actions))
        window.workflow.slicer_succeeded("Testslicer")
        self.assertTrue(all(action.isVisible() for action in actions))
        window.close()

    def test_gcode_guide_is_a_two_line_icon_hint_without_a_box(self) -> None:
        window = self.window()
        self.assertTrue(
            window.gcode_import_guide.text().startswith(
                "Noch kein fertiger G-Code?\n"
            )
        )
        self.assertEqual(window.gcode_import_guide_icon.text(), "ℹ")
        self.assertIs(
            window.gcode_import_guide_icon.parentWidget(),
            window.gcode_import_guide_row,
        )
        self.assertEqual(
            window.gcode_import_guide_row.layout().contentsMargins().left(),
            0,
        )
        window.close()

    def test_ready_cards_reopen_while_geometry_stays_collapsed(self) -> None:
        window = self.window()
        window.resize(1300, 900)
        window.show()
        window.workflow.analysis_succeeded("test.gcode")
        window.workflow.slicer_succeeded("Testslicer")
        self.app.processEvents()

        window.geometry_settings_group.setChecked(False)
        window.timing_group.setChecked(False)
        window.prediction_frame.setChecked(False)
        self.app.processEvents()
        collapsed_height = window.ready_grid.height()
        self.assertGreater(
            window.geometry_settings_group.height(),
            window.geometry_settings_group.header.height(),
        )

        window.timing_group.setChecked(True)
        self.app.processEvents()
        self.assertGreater(window.timing_group.height(), 54)
        self.assertGreater(window.ready_grid.height(), collapsed_height)

        timing_open_height = window.ready_grid.height()
        window.prediction_frame.setChecked(True)
        self.app.processEvents()
        self.assertGreater(window.prediction_frame.height(), 54)
        self.assertGreater(window.ready_grid.height(), timing_open_height)
        self.assertFalse(window.geometry_settings_group.isChecked())
        window.close()

    def test_geometry_subsections_are_named_and_owned_by_topic(self) -> None:
        window = self.window()
        self.assertEqual(window.geometry_group.title(), "Abmessungen")
        self.assertEqual(window.stability_group.title(), "Standfuß")
        self.assertEqual(window.overhang_group.title(), "Überhänge")

        for name in ("manual_base_width_mm", "base_height_mm"):
            self.assertTrue(
                window.stability_group.isAncestorOf(
                    window._setting_widgets[name]
                )
            )
            self.assertFalse(
                window.overhang_group.isAncestorOf(
                    window._setting_widgets[name]
                )
            )
        for name in (
            "maximum_expansion_angle_deg",
            "maximum_contraction_angle_deg",
            "maximum_wall_change_per_mm_z",
        ):
            self.assertTrue(
                window.overhang_group.isAncestorOf(
                    window._setting_widgets[name]
                )
            )
            self.assertFalse(
                window.stability_group.isAncestorOf(
                    window._setting_widgets[name]
                )
            )
        self.assertTrue(
            window.geometry_right_column.isAncestorOf(
                window.geometry_calculation_section
            )
        )
        self.assertFalse(
            window.stability_group.isAncestorOf(
                window.geometry_calculation_section
            )
        )
        self.assertFalse(
            window.overhang_group.isAncestorOf(
                window.geometry_calculation_section
            )
        )
        window.close()

    def test_single_column_prediction_order_survives_state_and_width_changes(
        self,
    ) -> None:
        window = self.window()
        window.resize(1400, 900)
        window.show()
        window.workflow.analysis_succeeded("test.gcode")
        window.workflow.slicer_succeeded("Testslicer")
        for _ in range(6):
            self.app.processEvents()

        grid = window.ready_grid
        self.assertTrue(grid.is_two_column())
        self.assertEqual(
            grid.grid.getItemPosition(
                grid.grid.indexOf(window.timing_group)
            )[:2],
            (0, 0),
        )
        self.assertEqual(
            grid.grid.getItemPosition(
                grid.grid.indexOf(window.prediction_frame)
            )[:2],
            (0, 1),
        )
        preserved_target = window.target_time_spin.value()

        window.resize(800, 900)
        for _ in range(8):
            self.app.processEvents()
        self.assertFalse(grid.is_two_column())
        self.assertEqual(
            grid.grid.getItemPosition(
                grid.grid.indexOf(window.prediction_frame)
            )[:2],
            (0, 0),
        )
        self.assertEqual(
            grid.grid.getItemPosition(
                grid.grid.indexOf(window.timing_group)
            )[:2],
            (1, 0),
        )
        self.assertLess(
            window.prediction_frame.y(),
            window.timing_group.y(),
        )
        self.assertGreater(
            grid.mapTo(window.settings_content, QPoint(0, 0)).y(),
            window.workflow_group.geometry().bottom(),
        )

        window.geometry_settings_group.setChecked(False)
        window.prediction_frame.setChecked(False)
        window.timing_group.setChecked(False)
        window.prediction_frame.setChecked(True)
        window.timing_group.setChecked(True)
        for _ in range(5):
            self.app.processEvents()
        self.assertGreater(
            window.prediction_frame.height(),
            window.prediction_frame.header.height(),
        )
        self.assertGreater(
            window.timing_group.height(),
            window.timing_group.header.height(),
        )
        self.assertEqual(
            window.settings_scroll.horizontalScrollBar().maximum(),
            0,
        )

        window.resize(1400, 900)
        for _ in range(8):
            self.app.processEvents()
        self.assertTrue(grid.is_two_column())
        self.assertEqual(
            grid.grid.getItemPosition(
                grid.grid.indexOf(window.timing_group)
            )[:2],
            (0, 0),
        )
        self.assertEqual(
            grid.grid.getItemPosition(
                grid.grid.indexOf(window.prediction_frame)
            )[:2],
            (0, 1),
        )
        self.assertEqual(window.target_time_spin.value(), preserved_target)
        window.close()

    def test_inline_errors_expand_layout_without_overlapping_fields(self) -> None:
        window = self.window()
        window.resize(800, 900)
        window.show()
        window.workflow.analysis_succeeded("test.gcode")
        window.workflow.slicer_succeeded("Testslicer")
        for _ in range(5):
            self.app.processEvents()
        height_before = window.geometry_settings_group.height()

        window.maximum_outer_spin.setValue(1.0)
        window.validate_form()
        for _ in range(6):
            self.app.processEvents()
        self.assertGreater(window.geometry_settings_group.height(), height_before)
        self.assertTrue(
            window._setting_widgets[
                "maximum_outer_radius_mm"
            ].message_label.isVisible()
        )
        self.assertTrue(window.validation_label.text().strip())

        visible_rows: list[tuple[str, QRect]] = []
        for name, setting in window._setting_widgets.items():
            if not setting.isVisible():
                continue
            origin = setting.mapTo(window, QPoint(0, 0))
            visible_rows.append(
                (name, QRect(origin, setting.size()))
            )
        overlaps = [
            (left_name, right_name)
            for index, (left_name, left_rect) in enumerate(visible_rows)
            for right_name, right_rect in visible_rows[index + 1 :]
            if left_rect.intersects(right_rect)
        ]
        self.assertEqual(overlaps, [])
        window.close()

    def test_footer_notices_are_priority_sorted_in_one_scrollable_column(self) -> None:
        window = self.window()
        window.resize(1300, 900)
        window.show()
        window._set_export_button_state(True)
        window.warning_text.setPlainText("Ein Warnhinweis")
        window._refresh_issue_panels()
        for _ in range(5):
            self.app.processEvents()

        self.assertEqual(
            window._active_footer_notice_severities,
            ("warning",),
        )
        self.assertTrue(window.notice_panel.is_expanded())

        window._set_export_button_state(False, "Testvoraussetzung fehlt.")
        for _ in range(5):
            self.app.processEvents()
        self.assertTrue(window.action_availability_widget.isHidden())
        self.assertFalse(window.export_availability_label.text())
        self.assertEqual(
            window._active_footer_notice_severities,
            ("warning",),
        )

        window.validation_label.setText("Fehlerhinweis " * 120)
        window._static_error_causes = ["Fehler"]
        window._refresh_issue_panels()
        for _ in range(5):
            self.app.processEvents()
        self.assertEqual(
            window._active_footer_notice_severities,
            ("error", "warning"),
        )
        for panel in (window.error_panel, window.notice_panel):
            self.assertFalse(panel.is_expanded())
        self.assertLess(
            window.footer_notice_layout.indexOf(window.error_panel),
            window.footer_notice_layout.indexOf(window.notice_panel),
        )

        extra_error = FooterNoticeDropdown(
            "✕  Zusätzliche Fehlergruppe",
            severity="error",
        )
        extra_details = QLabel("Zusätzliche Details " * 80)
        extra_details.setWordWrap(True)
        extra_error.content_layout.addWidget(extra_details)
        window._register_footer_notice("error", extra_error)
        extra_error.show()
        for _ in range(3):
            self.app.processEvents()
        self.assertFalse(extra_error.is_expanded())
        self.assertLess(
            window.error_panel.y(),
            extra_error.y(),
        )

        window.workflow.analysis_succeeded("test.gcode")
        window.workflow.slicer_succeeded("Testslicer")
        window.error_panel.set_expanded(True)
        extra_error.set_expanded(True)
        for _ in range(8):
            self.app.processEvents()
        self.assertEqual(window.footer.height(), 350)
        self.assertEqual(
            window.footer.maximumHeight(),
            350,
        )
        self.assertGreater(
            window.footer_messages_scroll.verticalScrollBar().maximum(), 0
        )
        window.close()

    def test_footer_folder_actions_have_distinct_persistent_targets(self) -> None:
        window = self.window()
        output_root = self.root / "output-root"
        window.output_root_edit.setText(str(output_root))
        with patch(
            "cooling_tower.gui.main_window.open_directory"
        ) as open_directory_mock:
            window.open_output_directory()
            open_directory_mock.assert_called_once_with(output_root.resolve())
        self.assertTrue(output_root.is_dir())

        window._export_request_id = 11
        first_folder = self.write_export_folder(
            output_root,
            "export-1",
            "2026-07-30T10:00:01+02:00",
        )
        second_folder = self.write_export_folder(
            output_root,
            "export-2",
            "2026-07-30T10:00:02+02:00",
        )
        for folder in (first_folder, second_folder):
            result = SimpleNamespace(
                output_mode=OutputMode.STL,
                calibrated=True,
                slicer_optimized=True,
                output_path=folder / "tower.stl",
                user_report_path=folder / "summary.txt",
            )
            window._on_export_succeeded(11, result)
        window.last_export_result = None
        with patch(
            "cooling_tower.gui.main_window.open_directory"
        ) as open_directory_mock:
            window.open_stl_directory()
            open_directory_mock.assert_called_once_with(
                second_folder.resolve()
            )
        self.assertEqual(window.open_output_button.text(), "Alle Exporte öffnen")
        self.assertEqual(window.open_stl_button.text(), "Letzten Export öffnen")
        self.assertTrue(window.open_stl_button.isEnabled())
        window.close()

    def test_latest_export_button_explains_disabled_state_and_rechecks(self) -> None:
        window = self.window()
        output_root = self.root / "exports"
        window.output_root_edit.setText(str(output_root))

        self.assertFalse(window.open_stl_button.isEnabled())
        self.assertEqual(
            window.open_stl_button.toolTip(),
            "Kein Exportordner gefunden.",
        )
        self.assertTrue(
            window.open_stl_button.testAttribute(
                Qt.WidgetAttribute.WA_AlwaysShowToolTips
            )
        )

        latest = self.write_export_folder(
            output_root,
            "20260730_100000_referenz",
            "2026-07-30T10:00:00+02:00",
        )
        window._refresh_folder_action_states(rescan=True)
        self.assertTrue(window.open_stl_button.isEnabled())
        self.assertEqual(
            window.open_stl_button.toolTip(),
            "Den Ordner des zuletzt erstellten Exports öffnen",
        )

        with patch(
            "cooling_tower.gui.main_window.open_directory"
        ) as open_directory_mock:
            window.open_stl_directory()
            open_directory_mock.assert_called_once_with(latest.resolve())

        (latest / "export_report.json").unlink()
        with patch(
            "cooling_tower.gui.main_window.open_directory"
        ) as open_directory_mock:
            window.open_stl_directory()
            open_directory_mock.assert_not_called()
        self.assertFalse(window.open_stl_button.isEnabled())
        self.assertEqual(
            window.open_stl_button.toolTip(),
            "Kein gültiger Exportordner gefunden.",
        )
        window.close()

    def test_slicer_dropdown_keeps_every_verified_installation(self) -> None:
        window = self.window()
        installations = tuple(
            SlicerInstallation(
                adapter_id=f"adapter-{index:02d}",
                product_name=f"Slicer {index:02d}",
                version="1.0",
                executable_path=self.root / f"slicer-{index:02d}.exe",
                verified=True,
                capabilities=frozenset(),
                discovery_source=SlicerDiscoverySource.KNOWN_PATH,
                family=SlicerFamily.OTHER,
            )
            for index in range(14)
        )
        result = SlicerDiscoveryResult(
            installations=installations,
            recommended_key=installations[0].identity_key,
            gui_state=SlicerGuiState.AVAILABLE,
            message="14 Slicer erkannt.",
        )

        window._slicer_request_id = 7
        window._on_slicer_discovery_succeeded(7, result)

        self.assertEqual(window.slicer_combo.count(), len(installations))
        self.assertEqual(window.slicer_combo.maxVisibleItems(), 10)
        self.assertEqual(
            window.slicer_combo.view().verticalScrollBarPolicy(),
            Qt.ScrollBarPolicy.ScrollBarAsNeeded,
        )
        self.assertEqual(
            {
                window.slicer_combo.itemData(index)
                for index in range(window.slicer_combo.count())
            },
            {installation.identity_key for installation in installations},
        )
        window.close()

    def test_every_numeric_setting_has_an_explanatory_info_button(self) -> None:
        window = self.window()
        self.assertTrue(window._setting_widgets)
        for setting_name, setting in window._setting_widgets.items():
            with self.subTest(setting_name=setting_name):
                self.assertFalse(setting.info_button.isHidden())
                self.assertTrue(setting.info_button.toolTip().strip())
                self.assertIn(
                    setting.label.text(),
                    setting.info_button.accessibleName(),
                )
        self.assertTrue(window.automatic_base_info_button.toolTip().strip())
        self.assertTrue(window.output_root_info_button.toolTip().strip())
        window.close()

    def test_manual_base_reset_is_in_the_same_row_as_its_editor(self) -> None:
        window = self.window()
        setting = window._setting_widgets["manual_base_width_mm"]
        layout = setting.layout()
        editor_position = layout.getItemPosition(
            layout.indexOf(window.manual_base_width_spin)
        )
        reset_position = layout.getItemPosition(
            layout.indexOf(window.automatic_base_reset_button)
        )
        self.assertEqual(editor_position[0], reset_position[0])
        self.assertEqual(reset_position[1], editor_position[1] + 1)
        window.automatic_base_checkbox.setChecked(False)
        self.app.processEvents()
        self.assertFalse(window.automatic_base_reset_button.isHidden())
        window.close()

    def test_prediction_rows_expose_visible_value_icons(self) -> None:
        window = self.window()
        self.assertEqual(
            set(window.prediction_value_icons),
            set(window.prediction_value_labels),
        )
        self.assertTrue(
            all(label.text().strip() for label in window.prediction_value_icons.values())
        )
        window.close()

    def test_runtime_diagnostics_are_appended(self) -> None:
        log_path = self.root / "runtime.log"
        append_runtime_diagnostic("first-source", "first detail", log_path)
        append_runtime_diagnostic("second-source", "second detail", log_path)
        content = log_path.read_text(encoding="utf-8")
        self.assertIn("[first-source]", content)
        self.assertIn("first detail", content)
        self.assertIn("[second-source]", content)
        self.assertIn("second detail", content)


if __name__ == "__main__":
    unittest.main()
