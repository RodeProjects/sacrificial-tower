from __future__ import annotations

import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch


PROJECT_ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = PROJECT_ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("COOLING_TOWER_DISABLE_SLICER_DISCOVERY", "1")

from PySide6.QtCore import QPoint, Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QDialog, QLabel, QPushButton

from cooling_tower.gui.main_window import (
    ABOUT_DIALOG_MINIMUM_WIDTH_PX,
    ABOUT_DIALOG_MAXIMUM_NATURAL_HEIGHT_PX,
    ABOUT_DIALOG_PREFERRED_WIDTH_PX,
    CURRENT_LICENSE_STATUS,
    INTERNAL_DIALOG_REVEAL_DELAY_MS,
    LICENSE_STATUS_DEFINITIONS,
    MAIN_FOOTER_MAX_HEIGHT_PX,
    MAIN_FOOTER_NARROW_MAX_HEIGHT_PX,
    MainWindow,
)
from cooling_tower.gui.design_tokens import METRICS
from cooling_tower.gui.user_messages import german_user_message
from cooling_tower.models.feasibility import (
    FeasibilityIssue,
    ProfileFeasibilityAssessment,
)
from cooling_tower.slicers.base import BaseSlicerAdapter
from cooling_tower.slicers.models import (
    SlicerCandidate,
    SlicerDiscoverySource,
)
from cooling_tower.slicers.process import ProcessOutcome
from cooling_tower.version import APP_NAME, APP_SUBTITLE
from gui_lifecycle import dispose_test_widget


class RecordingProbeRunner:
    def __init__(self) -> None:
        self.commands: list[tuple[str, ...]] = []

    def run(
        self,
        executable,
        arguments,
        *,
        working_directory,
        timeout_s,
        cancellation_event=None,
    ) -> ProcessOutcome:
        command = (str(executable), *(str(value) for value in arguments))
        self.commands.append(command)
        return ProcessOutcome(
            command=command,
            return_code=0,
            stdout="Flash Safe Slicer 1.2.3",
            stderr="",
            duration_s=0.01,
        )


class FlashSafeAdapter(BaseSlicerAdapter):
    adapter_id = "flash_safe"
    product_name = "Flash Safe Slicer"
    executable_names = ("FlashSafe.exe",)
    product_markers = ("Flash Safe Slicer",)


class LatestGuiRequirementsTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)

    def tearDown(self) -> None:
        self.app.processEvents()

    def window(self) -> MainWindow:
        window = MainWindow(user_settings_path=self.root / "settings.json")
        self.addCleanup(dispose_test_widget, window)
        return window

    def complete_source_step(self, window: MainWindow) -> None:
        window.workflow.set_slicer_step_visible(True)
        window.workflow.source_validation_succeeded(
            "referenz.stl geprüft",
            analysis_complete=True,
        )

    def test_wide_geometry_is_remeasured_when_workflow_becomes_visible(self) -> None:
        window = self.window()
        window.resize(1400, 900)
        window.show()
        self.complete_source_step(window)
        window.workflow.slicer_succeeded("Testslicer")
        window.workflow.complete_preparation()
        window.automatic_generation_card.click()
        QTest.qWait(100)
        self.app.processEvents()

        self.assertEqual(
            window.geometry_split.height(),
            window.geometry_split_layout.sizeHint().height(),
        )
        sections = (
            window.timing_group,
            window.geometry_group,
        )
        for previous, following in zip(sections, sections[1:]):
            self.assertEqual(
                following.geometry().top(),
                previous.geometry().bottom() + 1,
            )
        window.close()

    def test_out_of_range_values_remain_visible_with_priority_feedback(self) -> None:
        window = self.window()
        self.complete_source_step(window)
        window.workflow.slicer_succeeded("Testslicer")
        window.workflow.complete_preparation()
        window.automatic_generation_card.click()
        setting = window.maximum_expansion_angle_setting
        window.maximum_expansion_angle_spin.setValue(90.0)
        self.app.processEvents()

        self.assertEqual(window.maximum_expansion_angle_spin.value(), 90.0)
        self.assertTrue(setting.editor.property("invalid"))
        self.assertFalse(setting.editor.property("warning"))
        self.assertIn("Maximalwert 89,0 °", setting.message_label.text())
        self.assertTrue(setting.secondary_message_label.isHidden())
        self.assertIn("Maximalwert 89,0 °", window.validation_label.text())

        window.maximum_expansion_angle_spin.setValue(28.0)
        self.app.processEvents()
        self.assertFalse(setting.editor.property("invalid"))
        self.assertTrue(setting.editor.property("warning"))
        self.assertIn("Vorsicht", setting.message_label.text())
        window.close()

    def test_footer_is_responsive_prioritized_and_bounded(self) -> None:
        window = self.window()
        self.complete_source_step(window)
        window.workflow.slicer_succeeded("Testslicer")
        window.workflow.complete_preparation()
        window.automatic_generation_card.click()
        window.resize(2000, 900)
        window.show()
        window.warning_text.setPlainText("Ein Warnhinweis")
        window._refresh_issue_panels()
        self.app.processEvents()

        self.assertFalse(window._footer_narrow_layout)
        self.assertLessEqual(window.footer.height(), MAIN_FOOTER_MAX_HEIGHT_PX)
        self.assertEqual(window.footer.maximumHeight(), window.footer.height())
        self.assertTrue(window.notice_panel.is_expanded())
        self.assertEqual(
            window.footer_notice_layout.indexOf(window.notice_panel), 0
        )
        self.assertIs(window.reset_button.parentWidget(), window.footer_reset_host)
        self.assertTrue(window.footer_message_area.isAncestorOf(window.reset_button))

        window.validation_label.setText("Ein kritischer Fehler")
        window.error_panel.show()
        window._refresh_footer_notice_layout()
        self.assertFalse(window.error_panel.is_expanded())
        self.assertFalse(window.notice_panel.is_expanded())
        self.assertLess(
            window.footer_notice_layout.indexOf(window.error_panel),
            window.footer_notice_layout.indexOf(window.notice_panel),
        )

        window.resize(900, 800)
        QTest.qWait(40)
        self.app.processEvents()
        self.assertTrue(window._footer_narrow_layout)
        self.assertEqual(MAIN_FOOTER_NARROW_MAX_HEIGHT_PX, 400)
        self.assertLessEqual(window.footer.height(), MAIN_FOOTER_NARROW_MAX_HEIGHT_PX)
        self.assertEqual(window.footer.maximumHeight(), window.footer.height())
        positions = [
            window.footer_content_grid.getItemPosition(
                window.footer_content_grid.indexOf(widget)
            )[0]
            for widget in (
                window.footer_message_area,
                window.footer_horizontal_divider,
                window.footer_action_area,
            )
        ]
        self.assertEqual(positions, [0, 1, 2])
        self.assertGreaterEqual(
            window.error_panel.chevron_button.geometry().left(),
            window.error_panel.header_button.geometry().right(),
        )
        self.assertFalse(hasattr(window, "error_solutions_toggle"))
        self.assertFalse(hasattr(window, "error_solutions_label"))
        window.close()

    def test_setting_feedback_waits_for_both_workflow_prerequisites(self) -> None:
        window = self.window()
        window._apply_show_setting_limits(True)
        window.target_time_spin.setValue(0.0)
        window.maximum_expansion_angle_spin.setValue(28.0)
        self.complete_source_step(window)
        window.workflow.slicer_unavailable("Kein Slicer verfügbar")
        self.app.processEvents()

        target = window._setting_widgets["target_layer_time_s"]
        expansion = window.maximum_expansion_angle_setting
        self.assertTrue(target.message_container.isHidden())
        self.assertTrue(target.range_label.isHidden())
        self.assertFalse(bool(target.editor.property("invalid")))
        self.assertFalse(bool(expansion.editor.property("warning")))
        self.assertFalse(window.validation_label.text().strip())
        self.assertTrue(window.error_panel.isHidden())

        window.workflow.slicer_succeeded("Testslicer")
        window.workflow.complete_preparation()
        window.automatic_generation_card.click()
        self.app.processEvents()
        self.assertFalse(target.message_container.isHidden())
        self.assertFalse(target.range_label.isHidden())
        self.assertTrue(bool(target.editor.property("invalid")))
        self.assertTrue(bool(expansion.editor.property("warning")))
        window.close()

    def test_ranges_are_visible_and_layer_time_is_limited_to_30_seconds(self) -> None:
        window = self.window()
        window._apply_show_setting_limits(True)
        self.complete_source_step(window)
        window.workflow.slicer_succeeded("Testslicer")
        window.workflow.complete_preparation()
        window.automatic_generation_card.click()
        self.app.processEvents()

        for setting in window._setting_widgets.values():
            self.assertTrue(setting.range_label.text().strip())
            self.assertFalse(setting.range_label.isHidden())
        self.assertIn("5,0 - 30,0 Sek.", window._setting_widgets[
            "target_layer_time_s"
        ].range_label.text())
        window.target_time_spin.setValue(121.0)
        self.app.processEvents()
        self.assertEqual(window.target_time_spin.value(), 121.0)
        self.assertTrue(window.target_time_spin.property("invalid"))
        self.assertIn(
            "30,0",
            window.validation_label.text(),
        )
        self.assertIn("Gewünschte Mindest-Layerzeit: 121,0 Sek.", window.validation_label.text())
        window.close()

    def test_retired_controls_are_absent(self) -> None:
        window = self.window()
        for name in ("safety_factor", "mesh_segments", "minimum_object_tower_distance_mm"):
            self.assertNotIn(name, window._setting_widgets)
        window.close()

    def test_diameter_relationship_errors_mark_both_inputs_and_clear(self) -> None:
        window = self.window()
        self.complete_source_step(window)
        window.workflow.slicer_succeeded("Testslicer")
        window.workflow.complete_preparation()
        window.automatic_generation_card.click()
        window.minimum_outer_spin.setValue(30.0)
        window.maximum_outer_spin.setValue(20.0)
        window._last_changed_setting_name = "minimum_outer_diameter_mm"
        window.validate_form()

        self.assertTrue(window._static_error_causes)
        minimum_setting = window._setting_widgets["minimum_outer_diameter_mm"]
        maximum_setting = window._setting_widgets["maximum_outer_diameter_mm"]
        self.assertTrue(minimum_setting.editor.property("invalid"))
        self.assertTrue(maximum_setting.editor.property("invalid"))
        self.assertIn(
            "Min. Turmdurchmesser muss kleiner als Max. Turmdurchmesser sein",
            minimum_setting.message_label.text(),
        )
        self.assertIn(
            "Max. Turmdurchmesser muss größer als Min. Turmdurchmesser sein",
            maximum_setting.message_label.text(),
        )
        self.assertTrue(window.validation_label.text())

        window.maximum_outer_spin.setValue(31.0)
        self.app.processEvents()
        self.assertFalse(minimum_setting.editor.property("invalid"))
        self.assertFalse(maximum_setting.editor.property("invalid"))
        self.assertTrue(minimum_setting.message_container.isHidden())
        self.assertTrue(maximum_setting.message_container.isHidden())
        window.minimum_outer_spin.setValue(31.0)
        self.app.processEvents()
        self.assertIn("muss kleiner als", minimum_setting.message_label.text())
        self.assertIn("muss größer als", maximum_setting.message_label.text())
        window.maximum_outer_spin.setValue(32.0)
        self.app.processEvents()
        self.assertTrue(minimum_setting.message_container.isHidden())
        self.assertTrue(maximum_setting.message_container.isHidden())
        self.assertIn(
            'QDoubleSpinBox[invalid="true"]:focus',
            window.styleSheet(),
        )
        window.validate_form()
        self.assertFalse(minimum_setting.editor.property("invalid"))
        window.close()

    def test_optional_dialogs_are_not_created_during_startup(self) -> None:
        dialogs_before = {
            id(widget)
            for widget in self.app.topLevelWidgets()
            if isinstance(widget, QDialog)
        }
        window = self.window()
        self.assertIsNotNone(window._preview_dialog)
        self.assertFalse(window.preview_dialog.isWindow())
        self.assertEqual(
            window.preview_dialog.state_label.text(),
            "Vorschau wurde noch nicht erstellt.",
        )
        self.assertTrue(window.preview_dialog.state_label.isHidden())
        self.assertTrue(window.preview_dialog.three_quarter_button.isHidden())
        self.assertIsNone(window._additional_options_dialog)
        self.assertIsNone(window._about_dialog)
        self.assertIsNone(window._support_report_dialog)
        dialogs_after = {
            id(widget)
            for widget in self.app.topLevelWidgets()
            if isinstance(widget, QDialog)
        }
        self.assertEqual(
            dialogs_after,
            dialogs_before,
        )

        self.assertIsNotNone(window.preview_dialog)
        self.assertIsNotNone(window.additional_options_dialog)
        self.assertIsNotNone(window.about_dialog)
        self.assertIsNotNone(window.support_report_dialog)
        window.close()

    def test_header_menu_and_subtitle_expose_the_requested_actions(self) -> None:
        window = self.window()
        window.resize(760, 700)
        window.move(20, 20)
        window.show()
        self.app.processEvents()

        self.assertEqual(
            window.subtitle_label.text(),
            "Erzeugt Opferobjekte passend zur gewünschten Layerzeit",
        )
        self.assertEqual(window.windowTitle(), APP_NAME)
        self.assertEqual(window.title_label.text().replace("\n", ""), APP_NAME)
        self.assertEqual(window.subtitle_label.text(), APP_SUBTITLE)
        self.assertEqual(window.options_button.toolTip(), "")
        self.assertEqual(window.options_button.accessibleName(), "Menü öffnen")
        self.assertEqual(window.version_label.toolTip(), "")
        self.assertNotEqual(window.version_label.accessibleName(), "")
        self.assertEqual(
            [action.text() for action in window.options_menu.actions()],
            [
                "Allgemeine Einstellungen …",
                "Support Diagnose …",
                "Buy me a coffee …",
                "Über Kühlturm-Generator",
            ],
        )
        self.assertTrue(
            all(
                not action.icon().isNull()
                for action in window.options_menu.actions()
            )
        )
        window.options_menu.ensurePolished()
        menu_size = window.options_menu.sizeHint()
        popup_position = window._options_menu_popup_position(menu_size)
        window_top_left = window.mapToGlobal(QPoint(0, 0))
        button_top_left = window.options_button.mapToGlobal(QPoint(0, 0))
        self.assertGreaterEqual(popup_position.x(), window_top_left.x())
        self.assertLessEqual(
            popup_position.x() + menu_size.width(),
            window_top_left.x() + window.width(),
        )
        self.assertEqual(
            popup_position.y(),
            button_top_left.y() + window.options_button.height(),
        )
        window.close()

    def test_output_folder_is_in_general_settings(self) -> None:
        window = self.window()
        self.addCleanup(window.close)
        window.joint_slice_settings_action.trigger()
        dialog = window._joint_slice_settings_dialog
        self.assertEqual(dialog.output_root_edit.text(), window.output_root_edit.text())
        dialog.output_root_edit.setText(str(self.root / "custom-output"))
        dialog.accept()
        self.assertEqual(window.output_root_edit.text(), str(self.root / "custom-output"))
        window._reset_output_root()
        self.assertEqual(Path(window.output_root_edit.text()), window.settings_store.load_default_output_root())

    def test_program_information_contains_requested_icons_and_scrolling(self) -> None:
        window = self.window()
        window.resize(900, 900)
        window.show()
        self.app.processEvents()
        window.about_action.trigger()
        self.app.processEvents()

        dialog = window.about_dialog
        self.assertTrue(dialog.isVisible())
        self.assertEqual(dialog.windowTitle(), "Über Kühlturm-Generator")
        self.assertEqual(window.about_product_title.text(), APP_NAME)
        self.assertEqual(
            window.about_product_description.text(),
            APP_SUBTITLE,
        )
        self.assertEqual(
            dialog.minimumWidth(), ABOUT_DIALOG_MINIMUM_WIDTH_PX
        )
        self.assertEqual(dialog.width(), ABOUT_DIALOG_PREFERRED_WIDTH_PX)
        self.assertLessEqual(
            dialog.height(), ABOUT_DIALOG_MAXIMUM_NATURAL_HEIGHT_PX
        )
        self.assertLess(dialog.width(), window.width())
        self.assertLess(dialog.height(), window.height())
        self.assertFalse(window.about_program_icon.pixmap().isNull())
        self.assertEqual(
            window.about_scroll.horizontalScrollBarPolicy(),
            Qt.ScrollBarPolicy.ScrollBarAsNeeded,
        )
        self.assertEqual(
            window.about_scroll.verticalScrollBarPolicy(),
            Qt.ScrollBarPolicy.ScrollBarAsNeeded,
        )
        labels = "\n".join(
            label.text() for label in dialog.findChildren(QLabel)
        )
        for expected in (
            "Kühlturm-Generator",
            "Wolfgang Florian Rode",
            "Entwicklungsversion",
            "Apache-2.0",
            "auch kommerziell",
            "GitHub Issues",
        ):
            self.assertIn(expected, labels)
        self.assertNotIn("© 2026 Florian Rode", labels)
        self.assertNotIn("Weiterverbreitung ist untersagt", labels)
        self.assertEqual(
            window.about_developer_row.itemAt(1).widget().text(),
            "Entwickelt von:",
        )
        self.assertIs(
            window.about_developer_row.itemAt(2).widget(),
            window.about_developer_name,
        )
        self.assertEqual(
            window.about_license_status_row.itemAt(1).widget().text(),
            "Veröffentlichungsstatus:",
        )
        self.assertIs(
            window.about_license_status_row.itemAt(2).widget(),
            window.about_license_status_label,
        )
        self.assertEqual(window.about_copyright_symbol.text(), "©")
        self.assertEqual(
            window.about_copyright_symbol.font().pointSizeF(),
            window.about_copyright_text.font().pointSizeF(),
        )
        self.assertEqual(
            window.about_copyright_text.text(),
            "2026 Wolfgang Florian Rode · Apache-2.0",
        )
        self.assertTrue(window.about_copyright_symbol.pixmap().isNull())
        stylesheet = window.styleSheet()
        for status, definition in LICENSE_STATUS_DEFINITIONS.items():
            window._set_about_license_status(status)
            self.assertEqual(
                window.about_license_status_label.text(),
                definition["label"],
            )
            self.assertEqual(
                window.about_license_status_label.property("licenseStatus"),
                status,
            )
            self.assertEqual(
                window.about_license_status_description.text(),
                definition["description"],
            )
            for color in (
                definition["foreground"],
                definition["background"],
                definition["border"],
            ):
                self.assertIn(color, stylesheet)
        window._set_about_license_status(CURRENT_LICENSE_STATUS)
        self.assertIn("#123c63", window.about_support_link.text())
        self.assertIn("issues/new/choose", window.about_support_link.text())
        self.assertNotIn("mailto:", window.about_support_link.text())
        self.assertEqual(
            [button.text() for button in window.about_legal_buttons],
            [
                "Lizenzbedingungen",
                "Datenschutzerklärung",
                "Drittanbieter-Lizenzen",
            ],
        )
        self.assertTrue(
            all(
                not button.icon().isNull()
                for button in window.about_legal_buttons
            )
        )
        button_widths = [
            window.about_legal_grid._columns_for_width(width)
            for width in range(1, 2000)
        ]
        one_column_width = button_widths.index(2) + 1
        three_column_width = button_widths.index(3) + 1
        for width, expected_columns in (
            (three_column_width, 3),
            (one_column_width, 2),
            (one_column_width - 1, 1),
        ):
            window.about_legal_grid._relayout(width)
            self.assertEqual(
                window.about_legal_grid.column_count,
                expected_columns,
            )
        window.resize(720, 640)
        QTest.qWait(20)
        self.app.processEvents()
        self.assertEqual(dialog.width(), 640)
        self.assertLessEqual(dialog.height(), 560)
        self.assertLess(dialog.width(), window.width())
        self.assertLess(dialog.height(), window.height())
        dialog.resize(300, dialog.height())
        self.app.processEvents()
        self.assertEqual(dialog.width(), ABOUT_DIALOG_MINIMUM_WIDTH_PX)
        window.close()

    def test_internal_dialogs_stay_transparent_until_final_placement(self) -> None:
        window = self.window()
        reveal_delay_ms = 250
        window.resize(900, 900)
        window.show()
        self.app.processEvents()

        with patch(
            "cooling_tower.gui.main_window.INTERNAL_DIALOG_REVEAL_DELAY_MS",
            reveal_delay_ms,
        ):
            for opener, dialog_getter in (
                (window.show_about_dialog, lambda: window.about_dialog),
                (
                    window.show_additional_options,
                    lambda: window._joint_slice_settings_dialog,
                ),
            ):
                opener()
                dialog = dialog_getter()
                self.app.processEvents()
                self.assertTrue(dialog.isVisible())
                self.assertEqual(dialog.windowOpacity(), 0.0)

                QTest.qWait(reveal_delay_ms + 20)
                self.app.processEvents()
                self.assertEqual(dialog.windowOpacity(), 1.0)
                dialog.close()
                self.app.processEvents()

            # New dialogs are protected automatically even if their implementer
            # accidentally omits the preferred main-window parent.
            future_dialog = QDialog()
            future_dialog.setWindowTitle("Zukünftiger Dialog")
            future_dialog.show()
            self.app.processEvents()
            self.assertEqual(future_dialog.windowOpacity(), 0.0)
            QTest.qWait(reveal_delay_ms + 20)
            self.app.processEvents()
            self.assertEqual(future_dialog.windowOpacity(), 1.0)
            future_dialog.close()
            future_dialog.setParent(window)
        window.close()

    def test_file_status_precedes_guide_and_keeps_body_gap_below(self) -> None:
        window = self.window()
        window.resize(900, 900)
        window.show()
        self.app.processEvents()

        guide_top = window.source_guide.mapTo(
            window.source_group.content_widget,
            QPoint(0, 0),
        ).y()
        guide_bottom = guide_top + window.source_guide.height()
        drop_zone_top = window.drop_zone.mapTo(
            window.source_group.content_widget,
            QPoint(0, 0),
        ).y()
        lower_gap = drop_zone_top - guide_bottom

        self.assertTrue(window.source_progress_status_widget.isHidden())
        self.assertEqual(
            window.preparation_source_requirements.geometry().top(),
            window.source_group.content_layout.contentsMargins().top(),
        )
        self.assertLess(
            window.preparation_source_divider.geometry().bottom(),
            guide_top,
        )
        self.assertEqual(lower_gap, METRICS.card_body_vertical_padding_px)
        window.close()

    def test_program_legal_placeholder_expands_down_before_scrolling(self) -> None:
        window = self.window()
        window.resize(900, 900)
        window.show()
        window.show_about_dialog()
        QTest.qWait(INTERNAL_DIALOG_REVEAL_DELAY_MS + 20)
        self.app.processEvents()

        dialog = window.about_dialog
        available = dialog.screen().availableGeometry()
        dialog.move(available.left() + 20, available.top() + 80)
        dialog.resize(dialog.width(), 400)
        self.app.processEvents()
        initial_frame_top = dialog.frameGeometry().top()
        initial_height = dialog.height()

        window.about_legal_buttons[0].click()
        QTest.qWait(20)
        self.app.processEvents()

        self.assertFalse(window.about_placeholder_label.isHidden())
        self.assertGreater(dialog.height(), initial_height)
        self.assertEqual(dialog.frameGeometry().top(), initial_frame_top)
        self.assertLessEqual(
            dialog.frameGeometry().bottom(), available.bottom()
        )
        natural_height = (
            window._about_natural_content_height(dialog.width()) + 2
        )
        if natural_height > dialog.height():
            self.assertGreater(
                window.about_scroll.verticalScrollBar().maximum(), 0
            )
        window.close()

    def test_about_document_collapse_restores_full_width_without_a_sticky_scrollbar(self):
        from test_manual_gui import preview_test_application, restore_preview_test_application

        app, previous_font, font_id = preview_test_application()
        self.addCleanup(restore_preview_test_application, app, previous_font, font_id)
        window = self.window()
        window.resize(1400, 1390)
        window.show()
        window.show_about_dialog()
        QTest.qWait(INTERNAL_DIALOG_REVEAL_DELAY_MS + 20)
        dialog = window.about_dialog
        initial = (dialog.size(), dialog.about_content.width(), dialog.about_license_status_description.height())
        self.assertEqual(dialog.about_scroll.verticalScrollBar().maximum(), 0)
        for _ in range(2):
            for button in dialog.about_legal_buttons:
                button.click()
                QTest.qWait(20)
                button.click()
                QTest.qWait(20)
                self.assertEqual(dialog.about_scroll.verticalScrollBar().maximum(), 0)
                self.assertEqual((dialog.size(), dialog.about_content.width(), dialog.about_license_status_description.height()), initial)
        dialog.about_legal_buttons[0].click()
        dialog.close()
        window.show_about_dialog()
        QTest.qWait(INTERNAL_DIALOG_REVEAL_DELAY_MS + 20)
        self.assertEqual(dialog.about_scroll.verticalScrollBar().maximum(), 0)
        self.assertEqual(dialog.about_scroll.verticalScrollBarPolicy(), Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self.assertEqual(dialog.size(), initial[0])

    def test_startup_exposes_only_the_main_window(self) -> None:
        window = self.window()
        window.show()
        self.app.processEvents()

        visible_top_levels = [
            widget
            for widget in self.app.topLevelWidgets()
            if widget.isVisible()
        ]
        self.assertEqual(visible_top_levels, [window])
        window.close()

    def test_initial_footer_has_no_duplicate_right_notice_or_separator(self) -> None:
        window = self.window()
        window.resize(1300, 800)
        window.show()
        self.app.processEvents()

        self.assertTrue(window.footer.isHidden())
        self.assertTrue(window.action_availability_widget.isHidden())
        self.assertTrue(window.footer_action_area.isHidden())
        self.assertTrue(window.footer_vertical_divider.isHidden())
        self.assertTrue(window.footer_horizontal_divider.isHidden())
        self.assertTrue(window.status_icon_label.property("prominent"))
        window.close()

    def test_footer_notice_header_uses_expected_arrow_directions(self) -> None:
        window = self.window()
        self.complete_source_step(window)
        window.workflow.slicer_succeeded("Testslicer")
        window.workflow.complete_preparation()
        window.automatic_generation_card.click()
        panel = window.error_panel
        panel.show()
        window.show()
        self.app.processEvents()
        panel.set_expanded(False)

        self.assertEqual(panel.chevron_button.arrowType(), Qt.ArrowType.DownArrow)
        self.assertIsInstance(panel.header_button, QPushButton)
        self.assertIn(
            "QPushButton#footerNoticeHeader",
            window.styleSheet(),
        )
        self.assertIn("text-align: left", window.styleSheet())
        self.assertGreaterEqual(
            panel.chevron_button.geometry().left(),
            panel.header_button.geometry().right(),
        )
        panel.set_expanded(True)
        self.assertEqual(panel.chevron_button.arrowType(), Qt.ArrowType.UpArrow)
        window.close()

    def test_multiline_angle_fields_keep_the_standard_range_gap(self) -> None:
        window = self.window()
        self.complete_source_step(window)
        window.workflow.slicer_succeeded("Testslicer")
        window.workflow.complete_preparation()
        window.automatic_generation_card.click()
        window.resize(1300, 900)
        window.show()
        self.app.processEvents()

        def range_gap(setting_name: str) -> int:
            setting = window._setting_widgets[setting_name]
            editor_bottom = setting.editor.mapTo(
                setting,
                setting.editor.rect().bottomLeft(),
            ).y()
            range_top = setting.range_label.mapTo(
                setting,
                setting.range_label.rect().topLeft(),
            ).y()
            return range_top - editor_bottom - 1

        reference_gap = range_gap("maximum_outer_diameter_mm")
        self.assertEqual(range_gap("maximum_expansion_angle_deg"), reference_gap)
        self.assertEqual(range_gap("maximum_contraction_angle_deg"), reference_gap)
        window.close()

    def test_setting_info_buttons_are_centered_and_labels_use_available_width(self) -> None:
        window = self.window()
        self.complete_source_step(window)
        window.workflow.slicer_succeeded("Testslicer")
        window.workflow.complete_preparation()
        window.automatic_generation_card.click()
        window.resize(1500, 900)
        window.show()
        self.app.processEvents()

        for setting in window._setting_widgets.values():
            if not setting.isVisible() or setting.info_button.isHidden():
                continue
            editor_center = setting.editor.mapTo(
                setting,
                setting.editor.rect().center(),
            )
            info_center = setting.info_button.mapTo(
                setting,
                setting.info_button.rect().center(),
            )
            self.assertLessEqual(abs(editor_center.y() - info_center.y()), 1)
            text_control = (
                window.automatic_base_checkbox
                if setting.setting_name == "manual_base_width_mm"
                else setting.label
            )
            label_right = text_control.mapTo(
                setting,
                text_control.rect().topRight(),
            ).x()
            info_left = setting.info_button.mapTo(
                setting,
                setting.info_button.rect().topLeft(),
            ).x()
            self.assertLess(info_left + setting.info_button.width(), label_right)
            self.assertLess(
                info_left + setting.info_button.width(),
                text_control.mapTo(setting, text_control.rect().topLeft()).x(),
                setting.setting_name,
            )
        self.assertGreater(
            window._setting_widgets["minimum_outer_diameter_mm"].label.width(),
            320,
        )
        window.close()

    def test_multiple_inline_messages_are_bulleted(self) -> None:
        window = self.window()
        self.complete_source_step(window)
        window.workflow.slicer_succeeded("Testslicer")
        window.workflow.complete_preparation()
        window.automatic_generation_card.click()
        setting = window._setting_widgets["maximum_outer_diameter_mm"]
        setting.set_error(
            "Erste kurze Fehlermeldung.\nZweite kurze Fehlermeldung."
        )
        self.assertEqual(
            setting.message_label.text().splitlines(),
            [
                "• Erste kurze Fehlermeldung.",
                "• Zweite kurze Fehlermeldung.",
            ],
        )
        self.assertNotIn(";", setting.message_label.text())
        window.close()

    def test_unchanged_inline_error_skips_redundant_repolishing(self) -> None:
        window = self.window()
        setting = window._setting_widgets["maximum_outer_diameter_mm"]
        setting.set_error("Unveränderte Testmeldung")

        with (
            patch.object(setting, "_sync_editor_feedback_properties") as sync,
            patch.object(setting, "_render_messages") as render,
        ):
            setting.set_error("Unveränderte Testmeldung")

        sync.assert_not_called()
        render.assert_not_called()
        window.close()

    def test_unchanged_form_errors_skip_global_repolishing(self) -> None:
        window = self.window()
        window._apply_inline_errors({})

        with patch.object(MainWindow, "_refresh_widget_style") as refresh:
            window._apply_inline_errors({})

        refresh.assert_not_called()
        window.close()

    def test_automatic_slicer_verification_never_starts_the_gui_executable(self) -> None:
        executable = self.root / "FlashSafe.exe"
        executable.write_bytes(b"synthetic executable")
        runner = RecordingProbeRunner()
        adapter = FlashSafeAdapter(runner=runner)

        automatic = adapter.verify_installation(
            SlicerCandidate(
                executable,
                SlicerDiscoverySource.KNOWN_PATH,
                adapter_hint=adapter.adapter_id,
            )
        )
        self.assertTrue(automatic.verified)
        self.assertEqual(runner.commands, [])

        manual = adapter.verify_installation(
            SlicerCandidate(
                executable,
                SlicerDiscoverySource.MANUAL,
            )
        )
        self.assertTrue(manual.verified)
        self.assertEqual(len(runner.commands), 1)

    def test_unknown_english_gui_messages_are_replaced_by_german_text(self) -> None:
        for message in (
            "Profile adapter unavailable.",
            "Scanning profile directories.",
            "Something went wrong while reading the selected file.",
        ):
            rendered = german_user_message(message)
            self.assertNotEqual(rendered, message)
            self.assertIn("Die ", rendered)
        self.assertEqual(
            german_user_message("Die Profilzuordnung ist abgeschlossen."),
            "Die Profilzuordnung ist abgeschlossen.",
        )

    def test_multiple_errors_use_bullets_and_field_specific_inline_text(self) -> None:
        window = self.window()
        self.complete_source_step(window)
        window.workflow.slicer_succeeded("Testslicer")
        window.workflow.complete_preparation()
        window.automatic_generation_card.click()
        window.minimum_outer_spin.setValue(30.0)
        window.maximum_outer_spin.setValue(20.0)
        window.local_window_spin.setValue(4)
        window.validate_form()

        lines = window.validation_label.text().splitlines()
        self.assertGreaterEqual(len(lines), 2)
        headings = [line for line in lines if not line.startswith("• ")]
        bullets = [line for line in lines if line.startswith("• ")]
        self.assertGreaterEqual(len(headings), 1)
        self.assertGreaterEqual(len(bullets), 1)
        self.assertNotIn(";", window.validation_label.text())
        diameter_setting = window._setting_widgets[
            "maximum_outer_diameter_mm"
        ]
        self.assertFalse(diameter_setting.message_container.isHidden())
        self.assertIn(
            "Max. Turmdurchmesser muss größer als Min. Turmdurchmesser sein",
            diameter_setting.message_label.text(),
        )
        window.close()

    def test_footer_groups_feasibility_issues_below_the_changed_setting(self) -> None:
        window = self.window()
        self.complete_source_step(window)
        window.workflow.slicer_succeeded("Testslicer")
        window.workflow.complete_preparation()
        window.automatic_generation_card.click()
        window.target_time_spin.setValue(29.0)
        window._last_changed_setting_name = "target_layer_time_s"
        issues = (
            FeasibilityIssue(
                code="EXPANSION_ANGLE_TOO_SMALL",
                message="Expansion angle is too small.",
                affected_layer_index=10,
                related_setting_names=("maximum_expansion_angle_deg",),
                required_value=89.0,
            ),
            FeasibilityIssue(
                code="BASE_WIDTH_TOO_SMALL",
                message="Base width is too small.",
                affected_layer_index=11,
                related_setting_names=("manual_base_width_mm",),
                required_value=45.0,
            ),
            FeasibilityIssue(
                code="MAXIMUM_OUTER_DIAMETER_REACHED",
                message="Maximum outer diameter reached.",
                affected_layer_index=12,
                related_setting_names=("maximum_outer_diameter_mm",),
                required_value=44.0,
            ),
        )
        window._on_feasibility_succeeded(
            window._feasibility_request_id,
            ProfileFeasibilityAssessment(
                tower_required=True,
                feasible=False,
                issues=issues,
            ),
        )

        self.assertEqual(
            window.validation_label.text().splitlines(),
            [
                "• Maximaler Aufweitungswinkel reicht nicht aus.",
                "• Standfußbreite reicht nicht aus.",
                "• Eingestellter größter Außendurchmesser von 40,00 mm reicht nicht aus.",
            ],
        )
        self.assertNotIn(";", window.validation_label.text())
        self.assertNotIn("Betroffen", window.validation_label.text())
        self.assertNotIn("Erforderlich", window.validation_label.text())
        self.assertEqual(
            window.validation_label.textFormat(),
            Qt.TextFormat.RichText,
        )
        self.assertNotIn(
            "<b>Gewünschte Mindest-Layerzeit: 29,0 Sek.</b>",
            window.validation_label._rendered_html,
        )
        self.assertIn(
            "Maximaler Aufweitungswinkel",
            window.validation_label._rendered_html,
        )
        inline = window._setting_widgets["target_layer_time_s"].message_label.text()
        self.assertNotIn("Gewünschte Mindest-Layerzeit", inline)
        self.assertNotIn(";", inline)
        window.close()

    def test_capacity_path_length_is_not_presented_as_a_required_radius(self) -> None:
        window = self.window()
        issue = FeasibilityIssue(
            code="MAXIMUM_OUTER_DIAMETER_REACHED",
            message="Maximum outer diameter reached.",
            related_setting_names=("maximum_outer_diameter_mm",),
            required_value=5789.65,
            achievable_value=180.0,
        )

        group = window._group_feasibility_issues((issue,))[0]

        self.assertNotIn("Erforderlich", group["summary"])
        self.assertFalse(
            any("5789" in solution for solution in group["solutions"])
        )
        self.assertIn("Außendurchmesser erhöhen", group["solutions"][0])
        window.close()

    def test_error_cards_keep_normal_background_and_footer_keeps_error_tone(self) -> None:
        window = self.window()
        stylesheet = window.styleSheet()
        self.assertIn(
            'QFrame#sectionCard[state="error"] {\n    background: #ffffff;',
            stylesheet,
        )
        self.assertIn(
            'QFrame#issuePanel[severity="error"] {\n    background: #fff1f0;',
            stylesheet,
        )
        self.assertIn(
            "QLabel#errorLabel {\n    color: #152536;",
            stylesheet,
        )
        window.close()

    def test_inline_hint_backgrounds_are_transparent(self) -> None:
        window = self.window()
        stylesheet = window.styleSheet()
        for selector in (
            'QLabel#settingMessage[error="true"]',
            'QLabel#settingMessage[warning="true"]',
            "QLabel#settingMessageDetails",
            'QLabel#towerNeedLabel[state="notRequired"]',
            'QLabel#towerNeedLabel[state="error"]',
        ):
            start = stylesheet.index(selector)
            end = stylesheet.index("}", start)
            rule = stylesheet[start:end]
            self.assertIn("background: transparent;", rule, selector)
            self.assertNotIn("background: #fff", rule, selector)
        window.close()

    def test_static_error_survives_an_action_in_another_section(self) -> None:
        window = self.window()
        self.complete_source_step(window)
        window.workflow.slicer_succeeded("Testslicer")
        window.workflow.complete_preparation()
        window.automatic_generation_card.click()
        window.target_time_spin.setValue(0.0)
        self.app.processEvents()

        timing_message = window._setting_widgets[
            "target_layer_time_s"
        ].message_label.text()
        self.assertTrue(timing_message)
        self.assertEqual(window.timing_group.badge_label.text(), "1 Fehler")
        self.assertEqual(window.timing_group.state().value, "error")

        window.maximum_outer_spin.setValue(
            window.maximum_outer_spin.value() + 1.0
        )
        self.app.processEvents()

        self.assertEqual(
            window._setting_widgets[
                "target_layer_time_s"
            ].message_label.text(),
            timing_message,
        )
        self.assertEqual(window.timing_group.badge_label.text(), "1 Fehler")
        self.assertEqual(window.timing_group.state().value, "error")
        window.close()

    def test_feasibility_error_keeps_its_origin_until_resolved(self) -> None:
        window = self.window()
        self.complete_source_step(window)
        window.workflow.slicer_succeeded("Testslicer")
        window.workflow.complete_preparation()
        window.automatic_generation_card.click()
        window.target_time_spin.setValue(29.0)
        window._last_changed_setting_name = "target_layer_time_s"
        issue = FeasibilityIssue(
            code="EXPANSION_ANGLE_TOO_SMALL",
            message="Expansion angle is too small.",
            affected_layer_index=10,
            related_setting_names=("maximum_expansion_angle_deg",),
            required_value=89.0,
        )
        unresolved = ProfileFeasibilityAssessment(
            tower_required=True,
            feasible=False,
            issues=(issue,),
        )
        window._on_feasibility_succeeded(
            window._feasibility_request_id,
            unresolved,
        )
        original_message = window.validation_label.text()
        self.assertFalse(window._setting_widgets["target_layer_time_s"].message_label.text())
        self.assertFalse(window.timing_group.badge_label.text())

        window.maximum_outer_spin.setValue(
            window.maximum_outer_spin.value() + 1.0
        )
        self.app.processEvents()
        self.assertEqual(window.validation_label.text(), original_message)
        self.assertFalse(window.timing_group.badge_label.text())

        window._on_feasibility_succeeded(
            window._feasibility_request_id,
            unresolved,
        )
        self.assertEqual(window.validation_label.text(), original_message)
        self.assertFalse(
            window._setting_widgets[
                "maximum_outer_diameter_mm"
            ].message_label.text()
        )

        window._last_changed_setting_name = "target_layer_time_s"
        window._on_feasibility_succeeded(
            window._feasibility_request_id,
            ProfileFeasibilityAssessment(
                tower_required=True,
                feasible=True,
            ),
        )
        self.assertFalse(
            window._setting_widgets[
                "target_layer_time_s"
            ].message_label.text()
        )
        self.assertFalse(window.timing_group.badge_label.text())
        window.close()

    def test_fixing_one_feasibility_error_keeps_unrelated_errors(self) -> None:
        window = self.window()
        self.complete_source_step(window)
        window.workflow.slicer_succeeded("Testslicer")
        window.workflow.complete_preparation()
        window.automatic_generation_card.click()
        window._last_changed_setting_name = "target_layer_time_s"
        expansion_issue = FeasibilityIssue(
            code="EXPANSION_ANGLE_TOO_SMALL",
            message="Expansion angle is too small.",
            related_setting_names=("maximum_expansion_angle_deg",),
        )
        diameter_issue = FeasibilityIssue(
            code="MAXIMUM_OUTER_DIAMETER_REACHED",
            message="Maximum outer diameter reached.",
            related_setting_names=("maximum_outer_diameter_mm",),
        )
        window._on_feasibility_succeeded(
            window._feasibility_request_id,
            ProfileFeasibilityAssessment(
                tower_required=True,
                feasible=False,
                issues=(expansion_issue, diameter_issue),
            ),
        )
        self.assertEqual(len(window._feasibility_issue_summaries), 2)

        window.maximum_expansion_angle_spin.setValue(
            window.maximum_expansion_angle_spin.value() + 1.0
        )
        window._on_feasibility_succeeded(
            window._feasibility_request_id,
            ProfileFeasibilityAssessment(
                tower_required=True,
                feasible=False,
                issues=(diameter_issue,),
            ),
        )
        self.assertEqual(
            window._feasibility_issue_summaries,
            [
                "Eingestellter größter Außendurchmesser von 40,00 mm reicht "
                "nicht aus."
            ],
        )
        self.assertFalse(window._setting_widgets["target_layer_time_s"].message_label.text())
        self.assertIn("größter Außendurchmesser", window.validation_label.text())
        self.assertFalse(window.timing_group.badge_label.text())
        self.assertFalse(window.preview_button.isEnabled())

        window.maximum_outer_spin.setValue(
            window.maximum_outer_spin.value() + 1.0
        )
        window._on_feasibility_succeeded(
            window._feasibility_request_id,
            ProfileFeasibilityAssessment(
                tower_required=True,
                feasible=True,
            ),
        )
        self.assertFalse(window._feasibility_issue_summaries)
        self.assertFalse(
            window._setting_widgets[
                "target_layer_time_s"
            ].message_label.text()
        )
        window.close()

    def test_reset_rehomes_a_persistent_limit_issue_from_the_reset_field(self) -> None:
        window = self.window()
        self.complete_source_step(window)
        window.workflow.slicer_succeeded("Testslicer")
        window.workflow.complete_preparation()
        window.automatic_generation_card.click()
        issue = FeasibilityIssue(
            code="MAXIMUM_OUTER_DIAMETER_REACHED",
            message="Maximum outer diameter reached.",
            related_setting_names=("maximum_outer_diameter_mm",),
            required_value=44.0,
        )
        issue_key = (
            issue.code,
            tuple(sorted(issue.related_setting_names)),
        )
        window._feasibility_issue_targets[issue_key] = (
            "maximum_outer_diameter_mm"
        )
        window._feasibility_request_source = (
            window._feasibility_request_id,
            "maximum_outer_diameter_mm",
            "maximum_outer_diameter_mm",
        )

        window._on_feasibility_succeeded(
            window._feasibility_request_id,
            ProfileFeasibilityAssessment(
                tower_required=True,
                feasible=False,
                issues=(issue,),
            ),
        )

        self.assertFalse(
            window._setting_widgets[
                "maximum_outer_diameter_mm"
            ].message_label.text()
        )
        self.assertFalse(window._setting_widgets["target_layer_time_s"].message_label.text())
        self.assertIn("größter Außendurchmesser", window.validation_label.text())
        self.assertIn("40,00 mm", window.validation_label.text())
        self.assertIn("6,0 - 100,0 mm", window._setting_widgets[
            "maximum_outer_diameter_mm"
        ].range_label.text())
        window.close()

    def test_latest_feasibility_result_is_the_only_issue_source(self) -> None:
        window = self.window()
        self.complete_source_step(window)
        window.workflow.slicer_succeeded("Testslicer")
        window.workflow.complete_preparation()
        window.automatic_generation_card.click()
        window._last_changed_setting_name = "target_layer_time_s"
        issue = FeasibilityIssue(
            code="MAXIMUM_OUTER_DIAMETER_REACHED",
            message="Maximum outer diameter reached.",
            related_setting_names=("maximum_outer_diameter_mm",),
        )
        window._on_feasibility_succeeded(
            window._feasibility_request_id,
            ProfileFeasibilityAssessment(True, False, (issue,)),
        )
        self.assertTrue(window._feasibility_issue_summaries)

        window._on_feasibility_succeeded(
            window._feasibility_request_id,
            ProfileFeasibilityAssessment(True, True),
        )

        self.assertFalse(window._feasibility_issue_summaries)
        self.assertFalse(window._feasibility_field_errors)
        self.assertFalse(window._feasibility_issue_targets)
        self.assertFalse(window.validation_label.text())
        window.close()

    def test_changed_dependency_drops_only_its_stale_feasibility_issue(self) -> None:
        window = self.window()
        self.complete_source_step(window)
        window.workflow.slicer_succeeded("Testslicer")
        window.workflow.complete_preparation()
        window.automatic_generation_card.click()
        window._last_changed_setting_name = "target_layer_time_s"
        issues = (
            FeasibilityIssue(
                code="EXPANSION_ANGLE_TOO_SMALL",
                message="Expansion angle is too small.",
                related_setting_names=("maximum_expansion_angle_deg",),
            ),
            FeasibilityIssue(
                code="BASE_WIDTH_TOO_SMALL",
                message="Base width is too small.",
                related_setting_names=("manual_base_width_mm",),
            ),
            FeasibilityIssue(
                code="MAXIMUM_OUTER_DIAMETER_REACHED",
                message="Maximum outer diameter reached.",
                related_setting_names=("maximum_outer_diameter_mm",),
            ),
        )
        window._on_feasibility_succeeded(
            window._feasibility_request_id,
            ProfileFeasibilityAssessment(True, False, issues),
        )
        self.assertIn("40,00 mm", window.validation_label.text())

        window.maximum_outer_spin.setValue(1001.0)
        self.app.processEvents()

        target_message = window._setting_widgets["target_layer_time_s"].message_label.text()
        self.assertFalse(target_message)
        self.assertIn("Aufweitungswinkel", window.validation_label.text())
        self.assertIn("Standfußbreite", window.validation_label.text())
        self.assertNotIn("40,00 mm", window.validation_label.text())
        self.assertIn(
            "Überschreitet den Maximalwert 100,0 mm",
            window._setting_widgets[
                "maximum_outer_diameter_mm"
            ].message_label.text(),
        )
        self.assertEqual(len(window._feasibility_issues), 2)
        self.assertEqual(len(window._feasibility_issue_summaries), 2)
        window.close()

    def test_recalculated_dependency_notice_uses_its_current_value(self) -> None:
        window = self.window()
        self.complete_source_step(window)
        window.workflow.slicer_succeeded("Testslicer")
        window.workflow.complete_preparation()
        window.automatic_generation_card.click()
        window.maximum_outer_spin.setValue(500.0)
        issue = FeasibilityIssue(
            code="MAXIMUM_OUTER_DIAMETER_REACHED",
            message="Maximum outer diameter reached.",
            related_setting_names=("maximum_outer_diameter_mm",),
        )

        window._on_feasibility_succeeded(
            window._feasibility_request_id,
            ProfileFeasibilityAssessment(True, False, (issue,)),
        )

        self.assertIn("500,00 mm", window.validation_label.text())
        self.assertNotIn("40,00 mm", window.validation_label.text())
        window.close()

    def test_initial_generation_area_has_no_prediction_footnote(self) -> None:
        window = self.window()
        self.addCleanup(window.close)
        self.assertTrue(window.tower_need_label.isHidden())
        self.assertTrue(window.prediction_primary_widget.isHidden())
        self.assertTrue(window.joint_generation_dialog.isHidden())
        self.assertTrue(window.prediction_frame.isAncestorOf(window.preview_dialog))

    def test_failed_feasibility_check_replaces_old_calculated_errors(self) -> None:
        window = self.window()
        self.complete_source_step(window)
        window.workflow.slicer_succeeded("Testslicer")
        window.workflow.complete_preparation()
        window.automatic_generation_card.click()
        window._last_changed_setting_name = "target_layer_time_s"
        issue = FeasibilityIssue(
            code="EXPANSION_ANGLE_TOO_SMALL",
            message="Expansion angle is too small.",
            related_setting_names=("maximum_expansion_angle_deg",),
        )
        window._on_feasibility_succeeded(
            window._feasibility_request_id,
            ProfileFeasibilityAssessment(True, False, (issue,)),
        )

        window._on_feasibility_failed(
            window._feasibility_request_id,
            "unexpected worker failure",
            "details",
        )

        self.assertFalse(window._feasibility_field_errors)
        self.assertFalse(window._feasibility_issue_targets)
        self.assertEqual(
            window._feasibility_issue_summaries,
            ["Die Turmgeometrie konnte nicht vollständig geprüft werden."],
        )
        self.assertIn(
            "Turmgeometrie konnte nicht vollständig geprüft werden",
            window.validation_label.text(),
        )
        window.close()

    def test_infeasible_result_without_details_still_shows_a_problem(self) -> None:
        window = self.window()
        self.complete_source_step(window)
        window.workflow.slicer_succeeded("Testslicer")
        window.workflow.complete_preparation()
        window.automatic_generation_card.click()

        window._on_feasibility_succeeded(
            window._feasibility_request_id,
            ProfileFeasibilityAssessment(True, False),
        )

        self.assertEqual(
            window._feasibility_issue_summaries,
            [
                "Die Turmgeometrie ist mit den aktuellen Einstellungen "
                "nicht möglich."
            ],
        )
        self.assertIn("nicht möglich", window.validation_label.text())
        self.assertFalse(window.preview_button.isEnabled())
        window.close()

    def test_external_input_error_survives_central_form_validation(self) -> None:
        window = self.window()

        window._show_input_error("Die gewählte Datei ist nicht verfügbar.")
        window.validate_form()

        self.assertIn("nicht verfügbar", window.validation_label.text())
        self.assertFalse(window.error_panel.isHidden())
        self.assertIn("1 Problem", window.error_panel.title())
        window.close()

    def test_fixing_one_static_error_keeps_an_independent_static_error(self) -> None:
        window = self.window()
        self.complete_source_step(window)
        window.workflow.slicer_succeeded("Testslicer")
        window.workflow.complete_preparation()
        window.automatic_generation_card.click()
        window.target_time_spin.setValue(121.0)
        window.maximum_expansion_angle_spin.setValue(90.0)
        self.app.processEvents()
        self.assertEqual(window.timing_group.badge_label.text(), "1 Fehler")
        self.assertEqual(
            window.geometry_settings_group.badge_label.text(),
            "2 Fehler",
        )

        window.target_time_spin.setValue(11.0)
        self.app.processEvents()
        self.assertFalse(window.timing_group.badge_label.text())
        self.assertEqual(
            window.geometry_settings_group.badge_label.text(),
            "1 Fehler",
        )
        self.assertIn(
            "Maximalwert 89,0 °",
            window.maximum_expansion_angle_setting.message_label.text(),
        )
        window.close()

    def test_clean_footer_status_starts_at_the_action_controls_top_edge(self) -> None:
        window = self.window()
        window.resize(1400, 900)
        window.show()
        self.complete_source_step(window)
        window.workflow.slicer_succeeded("Testslicer")
        window.workflow.complete_preparation()
        window.automatic_generation_card.click()
        window.error_panel.hide()
        window.notice_panel.hide()
        window.action_availability_widget.hide()
        window.footer_action_area.show()
        window._refresh_footer_notice_layout()
        window._fit_footer_height()
        self.app.processEvents()

        status_top = window.status_label.mapTo(window.footer, window.status_label.rect().topLeft()).y()
        action_top = window.preview_action_control.mapTo(
            window.footer,
            window.preview_action_control.rect().topLeft(),
        ).y()
        self.assertFalse(window.footer.isHidden())
        self.assertLessEqual(status_top, action_top)
        self.assertLessEqual(
            action_top + window.preview_action_control.height(),
            window.footer.height(),
        )
        window.close()

    def test_full_infill_hint_is_bundled_in_an_info_button(self) -> None:
        window = self.window()
        self.assertEqual(
            window.full_infill_info_button.objectName(),
            "settingInfoButton",
        )
        self.assertFalse(hasattr(window, "full_infill_hint"))
        window.close()

    def test_non_export_validation_does_not_write_a_gui_error_log(self) -> None:
        window = self.window()
        with patch.object(window, "_write_gui_error_log") as write_log:
            window._on_feasibility_failed(
                window._feasibility_request_id,
                "Unexpected validation failed.",
                "technical details",
            )
        write_log.assert_not_called()
        window.close()

    def test_range_lines_and_dynamic_layer_limit_are_compact(self) -> None:
        window = self.window()
        self.complete_source_step(window)
        window.workflow.slicer_succeeded("Testslicer")
        window.workflow.complete_preparation()
        window.automatic_generation_card.click()
        window._update_local_window_layer_limit(891)

        dual_bounds = {
            "target_layer_time_s",
            "minimum_outer_diameter_mm",
            "maximum_outer_diameter_mm",
            "manual_base_width_mm",
            "maximum_expansion_angle_deg",
            "maximum_contraction_angle_deg",
        }
        for name, setting in window._setting_widgets.items():
            if name in dual_bounds:
                self.assertIn("-", setting.range_label.text())
                self.assertLessEqual(
                    setting.range_label.fontMetrics().horizontalAdvance(
                        setting.range_label.text()
                    ),
                    setting.range_label.width(),
                )
            else:
                self.assertTrue(setting.range_label.text().startswith("Max. "))
        maximum_diameter = window._setting_widgets[
            "maximum_outer_diameter_mm"
        ]
        self.assertEqual(maximum_diameter.unit_label.text(), "mm")
        self.assertEqual(
            maximum_diameter.range_label.text(), "6,0 - 100,0 mm"
        )
        self.assertEqual(
            window._setting_widgets["minimum_outer_diameter_mm"].range_label.text(),
            "3,0 - 40,0 mm",
        )
        self.assertEqual(
            window._setting_widgets["manual_base_width_mm"].range_label.text(),
            "20 - 80 mm",
        )
        window.show_joint_slice_settings()
        tolerance = window._joint_slice_settings_dialog.tolerance_spin_box
        self.assertEqual((tolerance.minimum(), tolerance.maximum()), (0.1, 3.0))
        window._joint_slice_settings_dialog.reject()
        self.assertEqual(
            window._setting_widgets["maximum_expansion_angle_deg"].range_label.text(),
            "20,0 - 89,0 °",
        )
        self.assertEqual(
            window._setting_widgets[
                "local_reference_window"
            ].range_label.text(),
            "Max. 891 Layer",
        )
        self.assertEqual(
            window.local_window_spin.property("validationMaximum"),
            891,
        )
        window.close()

    def test_folder_and_generation_actions_form_two_aligned_groups(self) -> None:
        window = self.window()
        window.resize(1400, 900)
        window.show()
        self.app.processEvents()
        positions = {
            widget: window.main_actions_layout.getItemPosition(
                window.main_actions_layout.indexOf(widget)
            )[1]
            for widget in (
                window.open_output_button,
                window.open_stl_button,
                window.last_export_report_button,
                window.preview_action_control,
                window.export_button,
            )
        }
        self.assertEqual(positions[window.open_output_button], 0)
        self.assertEqual(positions[window.open_stl_button], 1)
        self.assertEqual(positions[window.last_export_report_button], 2)
        self.assertEqual(positions[window.preview_action_control], 4)
        self.assertEqual(positions[window.export_button], 5)
        self.assertEqual(window.main_actions_layout.columnStretch(3), 1)
        window.last_export_report_button.show()
        window.resize(760, 900)
        self.app.processEvents()
        window._update_responsive_action_labels()
        for widget in (window.preview_action_control, window.export_button):
            row, _column, _row_span, _column_span = (
                window.main_actions_layout.getItemPosition(
                    window.main_actions_layout.indexOf(widget)
                )
            )
            self.assertIn(row, (0, 1))
        self.assertNotIn("\n", window.last_export_report_button.text())
        window.close()


if __name__ == "__main__":
    unittest.main()
