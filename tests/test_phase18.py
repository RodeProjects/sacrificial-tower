from __future__ import annotations

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

from PySide6.QtCore import QEvent, QPoint, QPointF, Qt
from PySide6.QtTest import QSignalSpy, QTest
from PySide6.QtWidgets import (
    QApplication,
    QLabel,
    QVBoxLayout,
    QWidget,
)

from cooling_tower.gui.design_tokens import METRICS
from cooling_tower.gui.main_window import MainWindow
from cooling_tower.gui.user_messages import german_user_message
from cooling_tower.gui.workflow_controller import WorkflowController
from cooling_tower.gui.widgets import PreviewCanvas, SectionCard, SectionState
from cooling_tower.models import (
    BedBounds,
    FeasibilityIssue,
    GenerationSettings,
    ProfileFeasibilityAssessment,
)
from cooling_tower.preview import (
    LineSegment3D,
    Point3D,
    PreviewScene,
    PreviewState,
)
from cooling_tower.slicers import (
    SlicerCapability,
    SlicerDiscoveryResult,
    SlicerDiscoverySource,
    SlicerGuiState,
    SlicerInstallation,
    SlicerSupportLevel,
)
from cooling_tower.tower.hollow_profile import validate_hollow_settings


class Phase18UiTests(unittest.TestCase):
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

    def test_section_and_workflow_state_changes_are_immediate(self) -> None:
        host = QWidget()
        layout = QVBoxLayout(host)
        source = SectionCard("G-Code", collapsible=True)
        slicer = SectionCard("Slicer", collapsible=True)
        downstream = QLabel("Einstellungen")
        for widget in (source, slicer, downstream):
            layout.addWidget(widget)
        controller = WorkflowController(
            source_card=source,
            slicer_card=slicer,
            downstream_widgets=(downstream,),
            parent=host,
        )
        controller.reset()
        host.show()
        self.app.processEvents()

        controller.begin_analysis()
        controller.analysis_succeeded("datei.gcode · 12 Layer")
        self.assertEqual(controller.first_success_duration_ms, 0)
        self.assertFalse(source.isChecked())
        self.assertTrue(slicer.isVisible())
        self.assertIsNone(source._transition)
        self.assertIsNone(source._state_transition)
        self.assertIsNone(source.graphicsEffect())
        self.assertIsNone(source.content_widget.graphicsEffect())
        source.set_expanded(True, animated=True)
        self.assertTrue(source.isChecked())
        self.assertIsNone(source._transition)

        controller.begin_analysis()
        controller.analysis_succeeded("erneut gelesen")
        self.assertTrue(source.isChecked())
        self.assertIsNone(source._transition)
        host.close()

    def test_downstream_reveal_has_no_delay_or_fade(self) -> None:
        host = QWidget()
        layout = QVBoxLayout(host)
        source = SectionCard("G-Code", collapsible=True)
        slicer = SectionCard("Slicer", collapsible=True)
        downstream = QLabel("Einstellungen")
        for widget in (source, slicer, downstream):
            layout.addWidget(widget)
        controller = WorkflowController(
            source_card=source,
            slicer_card=slicer,
            downstream_widgets=(downstream,),
            parent=host,
        )
        controller.reset()
        host.show()
        self.app.processEvents()

        slicer.setCheckable(True)
        slicer.setChecked(False)
        controller.slicer_succeeded("Testslicer")
        self.app.processEvents()
        self.assertTrue(downstream.isVisible())
        self.assertIsNone(downstream.graphicsEffect())
        self.assertIsNone(slicer._transition)
        self.assertIsNone(slicer._state_transition)
        host.close()

    def test_form_rows_are_left_right_aligned_and_editors_equal_sized(self) -> None:
        window = self.window()
        editors = (
            window.target_time_spin,
            window.safety_factor_spin,
            window.maximum_outer_spin,
        )
        self.assertEqual(
            {(editor.width(), editor.height()) for editor in editors},
            {
                (
                    METRICS.form_editor_width_px,
                    METRICS.form_control_height_px,
                )
            },
        )
        row = window._setting_widgets["safety_factor"]
        grid = row.layout()
        self.assertEqual(grid.getItemPosition(grid.indexOf(row.label))[:2], (0, 0))
        self.assertEqual(grid.columnStretch(0), 1)
        self.assertEqual(grid.columnStretch(1), 0)
        self.assertEqual(grid.getItemPosition(grid.indexOf(row.editor))[:2], (0, 2))
        self.assertEqual(
            grid.getItemPosition(grid.indexOf(row.reset_button))[:2],
            (0, 3),
        )
        self.assertEqual(window.timing_group.state(), SectionState.NEUTRAL)
        window.close()

    def test_two_column_rows_keep_collapsible_cards_independently_sized(self) -> None:
        window = self.window()
        window.resize(1400, 1000)
        window.show()
        window.ready_grid.show()
        self.app.processEvents()
        self.assertTrue(window.ready_grid.is_two_column())
        self.assertTrue(window.geometry_split.is_two_column())
        self.assertEqual(
            window.geometry_group.height(),
            window.geometry_right_column.height(),
        )
        for card in (window.timing_group, window.prediction_frame):
            self.assertTrue(card.isCheckable())
            self.assertTrue(card.isChecked())
            self.assertTrue(card.toggle_button.isVisible())
        self.assertTrue(bool(window.timing_group.property("outerDropdown")))
        self.assertEqual(window.prediction_frame.property("cardTone"), "preview")
        expanded_prediction_height = window.prediction_frame.height()
        window.timing_group.setChecked(False)
        self.app.processEvents()
        self.assertTrue(window.timing_group.content_widget.isHidden())
        self.assertTrue(window.prediction_frame.content_widget.isVisible())
        self.assertLess(
            window.timing_group.height(),
            expanded_prediction_height,
        )
        self.assertLessEqual(
            window.timing_group.height(),
            window.timing_group.header.height() + 2,
        )
        self.assertEqual(
            window.geometry_settings_group.title_label.text(),
            "Turmgeometrie",
        )
        self.assertFalse(bool(window.geometry_group.property("collapsible")))
        self.assertFalse(bool(window.stability_group.property("collapsible")))
        for card in (
            window.timing_group,
            window.prediction_frame,
            window.geometry_settings_group,
            window.geometry_group,
            window.stability_group,
            window.overhang_group,
        ):
            self.assertTrue(card.content_layout.alignment() & Qt.AlignmentFlag.AlignTop)
        window.close()

    def test_embedded_slicer_configuration_is_integrated_without_old_submenu(self) -> None:
        window = self.window()
        self.assertTrue(window.geometry_settings_group.isChecked())
        self.assertFalse(hasattr(window, "output_group"))
        self.assertFalse(hasattr(window, "profile_group"))
        self.assertTrue(window.slicer_group.isAncestorOf(window.reconstructed_config_toggle))
        items = (SimpleNamespace(key="printer", raw_value="Kobra"),)
        snapshot = SimpleNamespace(metadata=SimpleNamespace(typed_config=items))
        window._show_reconstructed_configuration(snapshot)
        self.assertFalse(window.reconstructed_config_toggle.isChecked())
        self.assertTrue(window.reconstructed_config_text.isHidden())
        window.close()

    def test_reload_action_reanalyses_the_same_gcode(self) -> None:
        source = self.root / "referenz.gcode"
        source.write_text(";LAYER:0\nG1 X1 Y1\n", encoding="utf-8")
        window = self.window()
        window.current_gcode_path = source
        with patch.object(window, "_on_file_selected") as selected:
            window.reload_gcode()
        selected.assert_called_once_with(str(source.resolve()))
        self.assertEqual(window.drop_zone.reload_button.text(), "G-Code neu einlesen")
        window.close()

    def test_automatic_slicer_detection_is_visible_in_header(self) -> None:
        window = self.window()
        automatic = SlicerInstallation(
            adapter_id="test",
            product_name="Testslicer",
            version="1.0",
            executable_path=self.root / "slicer.exe",
            verified=True,
            capabilities=frozenset(),
            discovery_source=SlicerDiscoverySource.KNOWN_PATH,
        )
        window._set_slicer_header_summary(automatic)
        self.assertEqual(window.slicer_group.summary(), automatic.display_name)
        self.assertEqual(
            window.slicer_group.title_note_label.text(),
            "(automatisch erkannt)",
        )
        self.assertEqual(
            window.slicer_group.title_note_label.property("severity"),
            "success",
        )
        self.assertTrue(window.slicer_group.summary_note_label.isHidden())
        window._set_slicer_header_summary(
            replace(automatic, discovery_source=SlicerDiscoverySource.MANUAL)
        )
        self.assertTrue(window.slicer_group.title_note_label.isHidden())
        window.close()

    def test_header_space_hover_chevrons_footer_and_prediction_padding(self) -> None:
        window = self.window()
        window.resize(1100, 900)
        window.show()
        window.ready_grid.show()
        self.app.processEvents()
        header_layout = window.geometry_group.header.layout()
        self.assertEqual(header_layout.stretch(0), 0)
        self.assertEqual(header_layout.stretch(2), 1)
        summary_right = (
            window.geometry_group.summary_label.x()
            + window.geometry_group.summary_label.width()
        )
        self.assertLessEqual(
            window.geometry_group.toggle_button.x() - summary_right,
            METRICS.card_header_summary_gap_px,
        )
        stylesheet = window.styleSheet()
        self.assertIn('QFrame#sectionCard[collapsible="true"]', stylesheet)
        self.assertIn("QComboBox:hover", stylesheet)
        self.assertIn("QComboBox::down-arrow", stylesheet)
        self.assertNotIn("__COMBO_DOWN_ICON__", stylesheet)
        self.assertIn("QWidget#mainFooter", stylesheet)
        self.assertIn("QLabel#predictionValue", stylesheet)
        self.assertIn("padding: 5px", stylesheet)
        window.close()

    def test_info_icon_is_circular_and_shows_hint_only_while_hovered(self) -> None:
        window = self.window()
        window.show()
        self.app.processEvents()
        button = window.stl_info_button
        self.assertEqual(
            (button.width(), button.height()),
            (
                METRICS.info_button_diameter_px,
                METRICS.info_button_diameter_px,
            ),
        )
        self.assertTrue(button.toolTip())
        self.assertIn("border-radius: 16px", window.styleSheet())

        shown = QSignalSpy(button.hint_shown)
        QApplication.sendEvent(button, QEvent(QEvent.Type.Enter))
        self.app.processEvents()
        self.assertGreaterEqual(shown.count(), 1)
        popover = window._bounded_hint_popover
        self.assertTrue(popover.isVisible())
        self.assertEqual(popover.label.text(), button.toolTip())
        self.assertTrue(window.rect().contains(popover.geometry()))

        QApplication.sendEvent(button, QEvent(QEvent.Type.Leave))
        self.app.processEvents()
        self.assertFalse(popover.isVisible())
        previous_count = shown.count()
        button.click()
        self.app.processEvents()
        self.assertEqual(shown.count(), previous_count)
        self.assertFalse(popover.isVisible())
        window.close()

    def test_calculation_settings_belong_to_the_geometry_card(self) -> None:
        window = self.window()
        geometry = window.geometry_settings_group
        self.assertTrue(geometry.isChecked())
        self.assertEqual(geometry.title(), "Turmgeometrie")
        for obsolete_alias in (
            "calculation_group",
            "advanced_group",
            "output_group",
        ):
            self.assertFalse(hasattr(window, obsolete_alias))
        self.assertNotIn(
            "Berechnungsdetails",
            [card.title() for card in window.findChildren(SectionCard)],
        )
        self.assertTrue(
            geometry.content_widget.isAncestorOf(window.mesh_segments_spin)
        )
        self.assertTrue(
            geometry.content_widget.isAncestorOf(window.local_window_spin)
        )
        self.assertTrue(
            window.geometry_calculation_section.isAncestorOf(
                window.mesh_segments_spin
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
        self.assertEqual(
            window._setting_widgets["mesh_segments"].label.text(),
            "Kreissegmente",
        )
        self.assertEqual(
            window._setting_widgets["local_reference_window"].label.text(),
            "Layer im lokalen Zeitfenster",
        )
        self.assertEqual(
            window.geometry_calculation_title.text(),
            "Auflösung und Zeitfenster",
        )
        self.assertEqual(
            window.geometry_calculation_title.objectName(),
            "sectionCardTitle",
        )
        self.assertFalse(hasattr(window, "geometry_calculation_grid"))
        self.assertFalse(hasattr(window, "geometry_calculation_divider"))
        self.assertFalse(
            geometry.isAncestorOf(window.output_root_edit)
        )
        self.assertTrue(
            window.additional_options_dialog.isAncestorOf(
                window.output_root_edit
            )
        )

        window.resize(1200, 900)
        window.show()
        window.ready_grid.show()
        self.app.processEvents()
        self.assertFalse(geometry.content_widget.isHidden())
        self.assertFalse(window.mesh_segments_spin.isHidden())
        self.assertFalse(window.local_window_spin.isHidden())
        self.assertGreater(geometry.content_widget.height(), 0)
        self.assertEqual(
            window.geometry_calculation_title.font().pointSizeF(),
            window.geometry_group.title_label.font().pointSizeF(),
        )
        self.assertEqual(
            window.geometry_calculation_title.font().weight(),
            window.geometry_group.title_label.font().weight(),
        )
        calculation_title_image = (
            window.geometry_calculation_header.grab().toImage()
        )
        self.assertEqual(
            calculation_title_image.pixelColor(
                calculation_title_image.width() // 2,
                5,
            ).name(),
            "#f5f7f9",
        )
        calculation_divider_image = (
            window.geometry_calculation_header_divider.grab().toImage()
        )
        self.assertEqual(
            calculation_divider_image.pixelColor(
                calculation_divider_image.width() // 2,
                0,
            ).name(),
            "#e0e5ea",
        )
        self.assertLessEqual(
            window.geometry_calculation_section.geometry().bottom(),
            window.geometry_right_column.contentsRect().bottom(),
        )
        stylesheet = window.styleSheet()
        geometry_subsection_selector = (
            'QWidget#geometrySettingsSplit '
            'QFrame#sectionCard[subsection="left"]'
        )
        self.assertIn(geometry_subsection_selector, stylesheet)
        self.assertIn(
            "background: #ffffff;",
            stylesheet[stylesheet.index(geometry_subsection_selector):],
        )
        for subsection in (
            window.geometry_group,
            window.stability_group,
            window.overhang_group,
        ):
            header_image = subsection.header.grab().toImage()
            body_image = subsection.content_widget.grab().toImage()
            self.assertEqual(
                header_image.pixelColor(
                    header_image.width() // 2,
                    5,
                ).name(),
                "#f5f7f9",
            )
            self.assertEqual(
                body_image.pixelColor(
                    body_image.width() // 2,
                    body_image.height() // 2,
                ).name(),
                "#ffffff",
            )
            subsection_image = subsection.grab().toImage()
            self.assertEqual(
                subsection_image.pixelColor(
                    1,
                    subsection_image.height() // 2,
                ).name(),
                "#ffffff",
            )
        outer_geometry_image = geometry.grab().toImage()
        self.assertEqual(
            outer_geometry_image.pixelColor(
                1,
                outer_geometry_image.height() // 2,
            ).name(),
            "#1769aa",
        )
        window._refresh_collapsible_error_badges(
            {"mesh_segments": ["Ungültige Segmentanzahl"]}
        )
        self.assertEqual(geometry.badge_label.text(), "1 Fehler")
        self.assertEqual(geometry.state(), SectionState.ERROR)
        window._refresh_collapsible_error_badges({})

        window.options_button.click()
        self.app.processEvents()
        self.assertTrue(window.additional_options_dialog.isVisible())
        self.assertEqual(window.options_button.text(), "")
        self.assertFalse(window.options_button.icon().isNull())
        self.assertEqual(window.options_button.iconSize().width(), 18)
        self.assertLess(
            window.stl_info_button.geometry().left(),
            window.options_button.geometry().left(),
        )
        window.close()

    def test_additional_options_dialog_is_content_high_and_centred(self) -> None:
        window = self.window()
        window.resize(720, 800)
        window.move(40, 0)
        window.show()
        self.app.processEvents()
        window.options_button.click()
        QTest.qWait(30)
        self.app.processEvents()
        dialog = window.additional_options_dialog
        expected_width = int(round((window.width() * 0.8) / 20.0) * 20)
        self.assertEqual(dialog.width(), expected_width)
        self.assertEqual(dialog.height(), dialog.layout().sizeHint().height())
        self.assertLess(dialog.height(), window.height() // 2)
        self.assertLessEqual(
            abs(
                dialog.frameGeometry().center().y()
                - window.frameGeometry().center().y()
            ),
            2,
        )
        window.close()

    def test_initial_gcode_card_keeps_its_previous_natural_height(self) -> None:
        window = self.window()
        window.resize(1205, 1393)
        window.show()
        self.app.processEvents()
        viewport_height = window.settings_scroll.viewport().height()
        self.assertLess(window.source_group.height(), viewport_height // 2)
        self.assertLessEqual(
            window.source_group.height(),
            window.source_group.sizeHint().height() + 2,
        )
        self.assertGreaterEqual(window.drop_zone.height(), 180)
        window.close()

    def test_outer_dropdowns_use_matching_header_and_left_accent_colours(self) -> None:
        window = self.window()
        window.resize(1200, 900)
        window.show()
        self.app.processEvents()
        outer_groups = (
            window.source_group,
            window.slicer_group,
            window.timing_group,
            window.geometry_settings_group,
            window.prediction_frame,
        )
        for group in outer_groups:
            self.assertTrue(group.property("outerDropdown"))
        self.assertFalse(bool(window.geometry_group.property("outerDropdown")))
        self.assertEqual(window.prediction_frame.property("cardTone"), "preview")
        self.assertIn(
            'QFrame#sectionCard[outerDropdown="true"] > QFrame#sectionCardHeader',
            window.styleSheet(),
        )
        initial_header = window.source_group.header.grab().toImage()
        self.assertEqual(
            initial_header.pixelColor(initial_header.width() // 2, 5).name(),
            "#f0f6fb",
        )
        timing_header = window.timing_group.header.grab().toImage()
        self.assertEqual(
            timing_header.pixelColor(timing_header.width() // 2, 5).name(),
            "#f0f6fb",
        )
        prediction_header = window.prediction_frame.header.grab().toImage()
        self.assertEqual(
            prediction_header.pixelColor(
                prediction_header.width() // 2,
                5,
            ).name(),
            "#f3f0ff",
        )
        expected_accents = {
            window.source_group: "#1769aa",
            window.slicer_group: "#1769aa",
            window.timing_group: "#1769aa",
            window.geometry_settings_group: "#1769aa",
            window.prediction_frame: "#6f52c9",
        }
        for group, colour in expected_accents.items():
            image = group.grab().toImage()
            self.assertEqual(
                image.pixelColor(1, image.height() // 2).name(),
                colour,
            )
        stylesheet = window.styleSheet()
        generic_hover = (
            'QFrame#sectionCard[collapsible="true"] '
            'QFrame#sectionCardHeader:hover'
        )
        blue_hover = (
            'QFrame#sectionCard[outerDropdown="true"]'
            '[collapsible="true"] > QFrame#sectionCardHeader:hover'
        )
        green_hover = (
            'QFrame#sectionCard[outerDropdown="true"]'
            '[collapsible="true"][state="success"] > '
            'QFrame#sectionCardHeader:hover'
        )
        self.assertGreater(
            stylesheet.index(blue_hover),
            stylesheet.index(generic_hover),
        )
        self.assertGreater(
            stylesheet.index(green_hover),
            stylesheet.index(generic_hover),
        )
        self.assertIn(
            "background: #e5f0f8;",
            stylesheet[stylesheet.index(blue_hover):],
        )
        self.assertIn(
            "background: #e2f2e8;",
            stylesheet[stylesheet.index(green_hover):],
        )

        window.workflow.analysis_succeeded("test.gcode")
        window.workflow.slicer_succeeded("Testslicer")
        window.prediction_frame.set_state(SectionState.SUCCESS)
        QTest.qWait(METRICS.first_success_animation_duration_ms + 100)
        for group in (window.source_group, window.slicer_group):
            image = group.header.grab().toImage()
            self.assertEqual(
                image.pixelColor(image.width() // 2, 5).name(),
                "#eef8f2",
            )
        prediction_image = window.prediction_frame.grab().toImage()
        self.assertEqual(
            prediction_image.pixelColor(
                5,
                window.prediction_frame.header.height() + 5,
            ).name(),
            "#fbfaff",
        )
        self.assertEqual(
            prediction_image.pixelColor(
                1,
                prediction_image.height() // 2,
            ).name(),
            "#6f52c9",
        )
        icon_colours = {
            group.status_icon.palette().color(
                group.status_icon.foregroundRole()
            ).name()
            for group in (
                window.source_group,
                window.slicer_group,
                window.prediction_frame,
            )
        }
        self.assertEqual(icon_colours, {"#176b45"})
        self.assertFalse(hasattr(window, "profile_group"))
        window.close()

    def test_preview_opening_clears_a_maximized_window_state(self) -> None:
        window = self.window()
        window.resize(900, 700)
        window.show()
        window.preview_dialog.setWindowState(Qt.WindowState.WindowMaximized)
        window._show_preview_dialog()
        QTest.qWait(220)
        self.app.processEvents()
        self.assertTrue(window.preview_dialog.isVisible())
        self.assertFalse(window.preview_dialog.isMaximized())
        self.assertFalse(window.preview_dialog.isFullScreen())
        self.assertEqual(
            window.preview_dialog.geometry(),
            window._preview_target_geometry,
        )
        self.assertLessEqual(
            abs(
                window.preview_dialog.frameGeometry().top()
                - window.frameGeometry().top()
            ),
            1,
        )
        window.close()

    def test_prediction_method_colours_and_short_two_line_action(self) -> None:
        window = self.window()
        window.resize(1200, 900)
        window.show()
        window.workflow.analysis_succeeded("test.gcode")
        window.workflow.slicer_succeeded("Testslicer")
        QTest.qWait(METRICS.first_success_animation_duration_ms + 100)
        self.app.processEvents()
        self.assertEqual(
            window.slicer_prediction_button.text(),
            "Slicer-Schätzung\ndurchführen",
        )
        window.prediction_method_label.setText("Analytische Schätzung")
        window.prediction_method_label.setProperty("mode", "analytical")
        window._refresh_widget_style(window.prediction_method_label)
        self.assertEqual(
            window.prediction_method_label.property("mode"),
            "analytical",
        )
        self.assertIn(
            'QLabel#predictionMethodBadge[mode="analytical"]',
            window.styleSheet(),
        )
        self.assertIn(
            'QLabel#predictionMethodBadge[mode="slicer"]',
            window.styleSheet(),
        )
        primary_position_before = window.prediction_primary_widget.mapTo(
            window.prediction_frame,
            QPoint(0, 0),
        )
        with (
            patch.object(
                window,
                "_slicer_prediction_is_offered",
                return_value=True,
            ),
            patch.object(
                window,
                "_slicer_prediction_can_start",
                return_value=True,
            ),
        ):
            window._refresh_prediction_advice("Analytische Schätzung")
            self.app.processEvents()
            self.app.processEvents()
        self.assertEqual(
            window.prediction_advice_label.text(),
            "Die analytische Schätzung ist relativ ungenau.\n"
            "Eine Slicer-gestützte Schätzung wird empfohlen.",
        )
        self.assertEqual(
            window.prediction_primary_widget.mapTo(
                window.prediction_frame,
                QPoint(0, 0),
            ),
            primary_position_before,
        )
        self.assertEqual(
            window.prediction_advice_frame.y(),
            window.prediction_primary_widget.y(),
        )
        self.assertEqual(
            window.prediction_advice_frame.height(),
            window.prediction_advice_frame.layout().sizeHint().height(),
        )
        self.assertLess(
            window.prediction_advice_frame.height(),
            window.prediction_primary_widget.height(),
        )
        self.assertTrue(window.slicer_prediction_button.isVisible())
        self.assertEqual(
            window.prediction_advice_frame.layout().contentsMargins().left(),
            0,
        )
        self.assertEqual(
            window.prediction_advice_content.layout().contentsMargins().left(),
            8,
        )
        self.assertTrue(
            window.prediction_advice_label.alignment()
            & Qt.AlignmentFlag.AlignHCenter
        )
        self.assertEqual(window.slicer_prediction_button.x(), 0)
        self.assertEqual(
            window.slicer_prediction_button.width(),
            window.prediction_advice_frame.width(),
        )
        self.assertEqual(
            window.prediction_advice_content.geometry().bottom() + 1,
            window.slicer_prediction_button.geometry().top(),
        )
        self.assertEqual(
            window.slicer_prediction_button.geometry().bottom(),
            window.prediction_advice_frame.rect().bottom(),
        )
        stylesheet = window.styleSheet()
        button_selector = "QPushButton#slicerPredictionButton {"
        button_rule = stylesheet[
            stylesheet.index(button_selector):
            stylesheet.index(
                "QPushButton#slicerPredictionButton:hover",
            )
        ]
        self.assertIn("border: 1px solid #b9aae9;", button_rule)
        self.assertIn("background: #f3f0ff;", button_rule)
        window.close()

    def test_followup_copy_headers_dropdown_widths_and_prediction_columns(self) -> None:
        window = self.window()
        window.resize(1200, 900)
        window.show()
        window.slicer_group.show()
        self.app.processEvents()
        self.assertEqual(window.status_label.text(), "Bitte G-Code auswählen")
        self.assertEqual(window.source_group.status_icon.text(), "⇧")
        self.assertIn("Objekt im Slicer", window.gcode_import_guide.text())
        self.assertIn("G-Code exportieren", window.gcode_import_guide.text())
        self.assertEqual(window.geometry_group.title(), "Abmessungen")
        self.assertEqual(window.stability_group.title(), "Standfuß")
        self.assertEqual(window.overhang_group.title(), "Überhänge")
        self.assertEqual(window.subtitle_label.text(), "Kühlturm aus einem G-Code erzeugen")
        self.assertEqual(window.prediction_frame.title(), "Prognose")
        self.assertTrue(window.slicer_columns.is_two_column())
        self.assertTrue(window.slicer_columns_divider.isVisible())
        self.assertEqual(
            [label.text() for label in window._slicer_width_labels],
            ["Slicer", "Maschinenprofil", "Prozessprofil", "Filamentprofil"],
        )
        slicer_layout = window.slicer_group.content_layout
        self.assertLess(
            slicer_layout.indexOf(window.slicer_progress_bar),
            slicer_layout.indexOf(window.slicer_progress_status_widget),
        )
        self.assertLess(
            slicer_layout.indexOf(window.slicer_progress_status_widget),
            slicer_layout.indexOf(window.slicer_columns),
        )
        self.assertLess(
            slicer_layout.indexOf(window.slicer_columns),
            slicer_layout.indexOf(window.slicer_details_divider),
        )
        self.assertLess(
            slicer_layout.indexOf(window.slicer_details_divider),
            slicer_layout.indexOf(window.profile_status_label),
        )
        self.assertFalse(hasattr(window, "profile_group"))

        item = window.prediction_content_grid.indexOf(
            window.prediction_advice_frame
        )
        self.assertEqual(
            window.prediction_content_grid.getItemPosition(item)[1],
            1,
        )
        primary_item = window.prediction_content_grid.indexOf(
            window.prediction_primary_widget
        )
        self.assertEqual(
            window.prediction_content_grid.getItemPosition(primary_item)[1],
            0,
        )
        widths = {combo.width() for combo in window._slicer_width_combos}
        self.assertEqual(len(widths), 1)
        self.assertLessEqual(
            abs(
                next(iter(widths))
                - window.slicer_selector_column.contentsRect().width()
            ),
            1,
        )
        self.assertFalse(hasattr(window, "slicer_profile_divider"))
        self.assertLessEqual(
            window.filament_profile_combo.geometry().bottom(),
            window.slicer_selector_column.contentsRect().bottom(),
        )

        window.resize(760, 900)
        self.app.processEvents()
        self.app.processEvents()
        self.assertFalse(window.slicer_columns.is_two_column())
        for combo in window._slicer_width_combos:
            self.assertLessEqual(
                abs(
                    combo.width()
                    - window.slicer_selector_column.contentsRect().width()
                ),
                1,
            )
        self.assertGreaterEqual(
            window.slicer_group.content_widget.height(),
            window.slicer_group.content_widget.sizeHint().height() - 2,
        )
        self.assertLessEqual(
            window.filament_profile_combo.geometry().bottom(),
            window.slicer_selector_column.contentsRect().bottom(),
        )
        window.slicer_combo.addItem("Ein sehr langer Slicername für die Popup-Breitenprüfung")
        window.slicer_combo.showPopup()
        self.assertGreaterEqual(
            window.slicer_combo.view().minimumWidth(),
            window.slicer_combo.width(),
        )
        window.slicer_combo.hidePopup()
        window.close()

    def test_slicer_information_does_not_repeat_discovery_facts(self) -> None:
        window = self.window()
        installation = SlicerInstallation(
            adapter_id="test",
            product_name="Testslicer",
            version="1.0",
            executable_path=self.root / "slicer.exe",
            verified=True,
            capabilities=frozenset({SlicerCapability.CLI_SLICE}),
            discovery_source=SlicerDiscoverySource.KNOWN_PATH,
            support_level=SlicerSupportLevel.FULL,
        )
        result = SlicerDiscoveryResult(
            installations=(installation,),
            recommended_key=installation.identity_key,
            gui_state=SlicerGuiState.AVAILABLE_AND_RECOMMENDED,
            message=(
                "Automatische Slicer-Verarbeitung verfügbar; passendster "
                "erkannter Slicer ist vorausgewählt."
            ),
        )
        window._slicer_request_id = 1
        window._on_slicer_discovery_succeeded(1, result)
        status = window.slicer_status_label.text().casefold()
        self.assertEqual(status.count("automatische slicer-verarbeitung"), 1)
        self.assertEqual(status.count("passendster erkannter slicer"), 1)
        window.close()

    def test_preview_starts_in_zoomed_out_side_view_and_exports_from_dialog(self) -> None:
        window = self.window()
        scene = PreviewScene(
            object_segments=(
                LineSegment3D(Point3D(0, 0, 0), Point3D(1, 1, 1)),
            ),
            tower_segments=(
                LineSegment3D(Point3D(2, 2, 0), Point3D(2, 2, 10)),
            ),
            bed_bounds=BedBounds(0, 100, 0, 100),
            tower_center_xy_mm=(2, 2),
            source_segment_count=1,
            displayed_segment_count=1,
            tower_height_mm=10,
        )
        result = SimpleNamespace(
            scene=scene,
            calibrated=False,
            slicer_optimized=False,
            output_mode=SimpleNamespace(value="stl"),
        )
        window.preview_dialog.set_preview(result)
        self.assertEqual(window.preview_dialog.canvas.yaw_deg, 90.0)
        self.assertAlmostEqual(
            window.preview_dialog.canvas.zoom,
            PreviewCanvas.SIDE_VIEW_ZOOM,
        )
        window.preview_dialog.canvas.zoom = 2.0
        window.preview_dialog.side_button.click()
        self.assertAlmostEqual(
            window.preview_dialog.canvas.zoom,
            PreviewCanvas.SIDE_VIEW_ZOOM,
        )
        exported = QSignalSpy(window.preview_dialog.export_requested)
        window.preview_dialog.export_button.setEnabled(True)
        window.preview_dialog.export_button.click()
        self.assertEqual(exported.count(), 1)
        self.assertEqual(
            window.preview_dialog.export_button.text(),
            "Kühlturm exportieren",
        )
        window.close()

    def test_side_view_uses_exactly_one_wheel_step_of_zoom_out(self) -> None:
        self.assertAlmostEqual(PreviewCanvas.SIDE_VIEW_ZOOM, 1.0 / 1.15)

    def test_preview_has_a_top_view_button_with_a_vertical_camera(self) -> None:
        window = self.window()
        dialog = window.preview_dialog
        dialog.canvas.yaw_deg = 42.0
        dialog.canvas.pitch_deg = 12.0
        dialog.canvas.zoom = 2.0
        dialog.canvas.pan_x = 25.0
        dialog.canvas.pan_y = -15.0
        changed = QSignalSpy(dialog.canvas.camera_changed)

        self.assertEqual(dialog.top_button.text(), "Draufsicht")
        dialog.top_button.click()

        self.assertEqual(dialog.canvas.yaw_deg, 0.0)
        self.assertEqual(dialog.canvas.pitch_deg, 89.0)
        self.assertEqual(dialog.canvas.zoom, 1.0)
        self.assertEqual(dialog.canvas.pan_x, 0.0)
        self.assertEqual(dialog.canvas.pan_y, 0.0)
        self.assertEqual(changed.count(), 1)
        self.assertEqual(
            dialog.canvas.camera_state()["pitch_deg"],
            89.0,
        )
        window.close()

    def test_user_facing_validation_messages_are_german(self) -> None:
        self.assertEqual(
            german_user_message("Target layer time must be greater than zero."),
            "Die Ziel-Layerzeit muss größer als 0 sein.",
        )
        generic = german_user_message("Unexpected profile validation failed.")
        self.assertNotIn("validation failed", generic.casefold())
        self.assertNotIn("fehlerprotokoll", generic.casefold())
        self.assertIn("nicht vollständig geprüft", generic.casefold())

        window = self.window()
        window.workflow.analysis_succeeded("referenz.gcode")
        window.workflow.slicer_succeeded("Testslicer")
        window.target_time_spin.setValue(0.0)
        self.app.processEvents()
        inline = window._setting_widgets["target_layer_time_s"].message_label.text()
        self.assertNotIn("Gewünschte Mindest-Layerzeit: 0,00 s", inline)
        self.assertIn("Mindestwert 0,01 s", inline)
        self.assertIn("Gewünschte Mindest-Layerzeit: 0,00 s", window.validation_label.text())
        self.assertIn("Mindestwert 0,01 s", window.validation_label.text())
        self.assertNotIn("must be", window.validation_label.text().casefold())
        window.close()

    def test_hint_styles_and_inline_messages_use_their_natural_height(self) -> None:
        window = self.window()
        stylesheet = window.styleSheet()
        for selector in (
            "QLabel#settingMessage",
            "QFrame#issuePanel",
            "QFrame#hintPopover",
        ):
            self.assertIn(selector, stylesheet)
        setting = window._setting_widgets["target_layer_time_s"]
        setting.set_error(
            "Kurze Zusammenfassung des Fehlers, die auch bei schmaler "
            "Fensterbreite vollständig lesbar bleiben muss."
        )
        window.resize(760, 700)
        window.show()
        self.app.processEvents()
        self.assertFalse(hasattr(setting, "message_scroll"))
        self.assertTrue(setting.message_label.wordWrap())
        self.assertEqual(
            setting.message_label.maximumHeight(),
            16_777_215,
        )
        self.assertGreaterEqual(
            setting.message_label.height(),
            setting.message_label.sizeHint().height(),
        )
        window.close()

    def test_expanded_cards_have_a_subtle_header_body_divider(self) -> None:
        card = SectionCard("Testbereich", collapsible=True, expanded=True)
        card.show()
        self.app.processEvents()
        self.assertTrue(card.body_divider.isVisible())
        self.assertEqual(card.body_divider.height(), 1)
        card.setChecked(False)
        self.assertTrue(card.body_divider.isHidden())

        window = self.window()
        stylesheet = window.styleSheet()
        self.assertIn("QFrame#sectionCardBodyDivider", stylesheet)
        self.assertIn("background: #e7ecf1", stylesheet)
        self.assertIn("border: 1px solid #d6dee8", stylesheet)
        window.close()
        card.close()

    def test_automatic_base_checkbox_geometry_does_not_change_on_hover(self) -> None:
        window = self.window()
        window.resize(1200, 900)
        window.show()
        window.ready_grid.show()
        self.app.processEvents()
        checkbox = window.automatic_base_checkbox
        before = checkbox.geometry()
        QApplication.sendEvent(checkbox, QEvent(QEvent.Type.Enter))
        self.app.processEvents()
        hovered = checkbox.geometry()
        QApplication.sendEvent(checkbox, QEvent(QEvent.Type.Leave))
        self.app.processEvents()
        self.assertEqual(hovered, before)
        self.assertEqual(checkbox.geometry(), before)
        window.close()

    def test_status_icons_and_text_are_vertically_centred(self) -> None:
        window = self.window()
        self.assertTrue(
            window.gcode_progress_status_label.alignment()
            & Qt.AlignmentFlag.AlignVCenter
        )
        self.assertTrue(
            window.slicer_progress_status_label.alignment()
            & Qt.AlignmentFlag.AlignVCenter
        )
        self.assertTrue(
            window.status_label.alignment() & Qt.AlignmentFlag.AlignVCenter
        )
        preview_layout = window.preview_dialog.progress_status_widget.layout()
        for widget in (
            window.preview_dialog.progress_status_icon,
            window.preview_dialog.progress_status_label,
        ):
            item = preview_layout.itemAt(preview_layout.indexOf(widget))
            self.assertTrue(item.alignment() & Qt.AlignmentFlag.AlignVCenter)
        window.close()

    def test_gcode_prompt_icon_stays_prominent_during_analysis(self) -> None:
        window = self.window()
        window.show()
        self.app.processEvents()
        icon = window.source_group.status_icon
        title = window.source_group.title_label
        self.assertTrue(bool(icon.property("prominent")))
        self.assertEqual(icon.width(), 28)
        self.assertGreaterEqual(
            icon.font().pointSizeF(),
            title.font().pointSizeF() + 6.0,
        )
        self.assertGreater(
            icon.fontMetrics().height(),
            title.fontMetrics().height(),
        )
        window.workflow.begin_analysis()
        self.assertTrue(bool(icon.property("prominent")))
        self.assertEqual(icon.width(), 28)
        self.assertGreater(
            icon.fontMetrics().height(),
            title.fontMetrics().height(),
        )
        window.workflow.analysis_succeeded("test.gcode")
        self.assertFalse(bool(icon.property("prominent")))
        self.assertEqual(icon.width(), 18)
        window.close()

    def test_geometry_dropdown_never_hides_timing_or_prediction_cards(self) -> None:
        window = self.window()
        window.resize(1205, 1393)
        window.show()
        window.workflow.analysis_succeeded("test.gcode")
        window.workflow.slicer_succeeded("Testslicer")
        QTest.qWait(METRICS.first_success_animation_duration_ms + 100)
        self.app.processEvents()
        timing_height = window.timing_group.height()
        prediction_height = window.prediction_frame.height()
        timing_geometry = window.timing_group.geometry()
        prediction_geometry = window.prediction_frame.geometry()
        timing_image = window.timing_group.grab().toImage()
        prediction_image = window.prediction_frame.grab().toImage()
        ready_origin = window.ready_grid.mapTo(
            window.settings_content, QPoint(0, 0)
        )
        ready_width = window.ready_grid.width()
        viewport_width = window.settings_scroll.viewport().width()
        self.assertTrue(window.settings_scroll.verticalScrollBar().isVisible())

        window.geometry_settings_group.toggle()
        QTest.qWait(METRICS.animation_duration_ms // 2)
        self.app.processEvents()
        for card in (window.timing_group, window.prediction_frame):
            self.assertTrue(card.isVisible())
            self.assertFalse(card.isHidden())
            self.assertTrue(card.content_widget.isVisible())
        self.assertEqual(window.timing_group.height(), timing_height)
        self.assertEqual(window.prediction_frame.height(), prediction_height)
        self.assertEqual(window.timing_group.geometry(), timing_geometry)
        self.assertEqual(window.prediction_frame.geometry(), prediction_geometry)
        self.assertEqual(
            window.ready_grid.mapTo(window.settings_content, QPoint(0, 0)),
            ready_origin,
        )
        self.assertEqual(window.ready_grid.width(), ready_width)
        self.assertEqual(window.settings_scroll.viewport().width(), viewport_width)
        self.assertIsNone(window.timing_group.graphicsEffect())
        self.assertIsNone(window.prediction_frame.graphicsEffect())
        self.assertEqual(window.timing_group.grab().toImage(), timing_image)
        self.assertEqual(
            window.prediction_frame.grab().toImage(), prediction_image
        )

        QTest.qWait(METRICS.animation_duration_ms)
        self.app.processEvents()
        self.assertTrue(window.geometry_settings_group.content_widget.isHidden())
        self.assertTrue(window.timing_group.content_widget.isVisible())
        self.assertTrue(window.prediction_frame.content_widget.isVisible())
        self.assertEqual(window.timing_group.geometry(), timing_geometry)
        self.assertEqual(window.prediction_frame.geometry(), prediction_geometry)
        self.assertEqual(
            window.ready_grid.mapTo(window.settings_content, QPoint(0, 0)),
            ready_origin,
        )
        self.assertEqual(window.ready_grid.width(), ready_width)
        self.assertEqual(window.settings_scroll.viewport().width(), viewport_width)
        self.assertTrue(window.settings_scroll.verticalScrollBar().isVisible())

        window.geometry_settings_group.toggle()
        QTest.qWait(METRICS.animation_duration_ms // 2)
        self.app.processEvents()
        self.assertEqual(window.timing_group.geometry(), timing_geometry)
        self.assertEqual(window.prediction_frame.geometry(), prediction_geometry)
        self.assertIsNone(window.timing_group.graphicsEffect())
        self.assertIsNone(window.prediction_frame.graphicsEffect())
        self.assertIsNone(window.timing_group.content_widget.graphicsEffect())
        self.assertIsNone(window.prediction_frame.content_widget.graphicsEffect())
        QTest.qWait(METRICS.animation_duration_ms)
        self.app.processEvents()
        self.assertFalse(window.geometry_settings_group.content_widget.isHidden())
        window.close()

    def test_geometry_dropdown_first_open_from_restored_collapsed_state(self) -> None:
        window = self.window()
        geometry = window.geometry_settings_group
        body = geometry.content_widget
        geometry.setChecked(False)
        window.resize(1205, 1393)
        window.show()
        window.workflow.analysis_succeeded("test.gcode")
        window.workflow.slicer_succeeded("Testslicer")
        QTest.qWait(METRICS.first_success_animation_duration_ms + 100)
        self.app.processEvents()

        self.assertFalse(geometry.isChecked())
        self.assertTrue(body.isHidden())
        timing_y = window.timing_group.y()
        timing_height = window.timing_group.height()
        prediction_y = window.prediction_frame.y()
        prediction_height = window.prediction_frame.height()

        geometry.toggle()
        QTest.qWait(METRICS.animation_duration_ms // 2)
        self.app.processEvents()
        self.assertTrue(geometry.isChecked())
        self.assertFalse(body.isHidden())
        self.assertGreater(body.height(), 1)
        self.assertGreater(geometry.height(), geometry.header.height() + 1)
        self.assertEqual(window.timing_group.y(), timing_y)
        self.assertEqual(window.timing_group.height(), timing_height)
        self.assertEqual(window.prediction_frame.y(), prediction_y)
        self.assertEqual(window.prediction_frame.height(), prediction_height)
        self.assertIsNone(window.timing_group.graphicsEffect())
        self.assertIsNone(window.prediction_frame.graphicsEffect())

        QTest.qWait(METRICS.animation_duration_ms + 50)
        self.app.processEvents()
        self.assertIsNone(geometry._transition)
        self.assertFalse(body.isHidden())
        self.assertGreaterEqual(body.height(), body.sizeHint().height() - 2)
        self.assertGreaterEqual(
            geometry.height(),
            geometry.header.height() + body.sizeHint().height(),
        )
        self.assertTrue(window.minimum_outer_spin.isVisible())
        self.assertTrue(window.maximum_expansion_angle_spin.isVisible())
        self.assertTrue(window.mesh_segments_spin.isVisible())
        self.assertTrue(window.local_window_spin.isVisible())
        self.assertTrue(window.geometry_calculation_section.isVisible())
        window.close()

    def test_geometry_dropdown_first_open_is_complete_when_stacked(self) -> None:
        window = self.window()
        geometry = window.geometry_settings_group
        body = geometry.content_widget
        geometry.setChecked(False)
        window.resize(760, 1000)
        window.show()
        window.workflow.analysis_succeeded("test.gcode")
        window.workflow.slicer_succeeded("Testslicer")
        QTest.qWait(METRICS.first_success_animation_duration_ms + 100)
        self.app.processEvents()

        geometry.toggle()
        QTest.qWait(METRICS.animation_duration_ms + 50)
        self.app.processEvents()
        self.assertFalse(window.geometry_split.is_two_column())
        self.assertFalse(body.isHidden())
        self.assertGreaterEqual(body.height(), body.sizeHint().height() - 2)
        self.assertTrue(window.mesh_segments_spin.isVisible())
        self.assertTrue(window.local_window_spin.isVisible())
        self.assertTrue(window.geometry_calculation_section.isVisible())
        window.close()

    def test_reset_action_is_hidden_until_settings_are_editable(self) -> None:
        window = self.window()
        window.show()
        self.app.processEvents()
        self.assertTrue(window.reset_button.isHidden())

        window.workflow.begin_analysis()
        self.assertTrue(window.reset_button.isHidden())
        window.workflow.analysis_succeeded("test.gcode")
        self.assertTrue(window.reset_button.isHidden())
        window.workflow.begin_slicer_search()
        self.assertTrue(window.reset_button.isHidden())

        window.workflow.slicer_succeeded("Testslicer")
        self.assertTrue(window.reset_button.isVisible())
        window.workflow.reset()
        self.assertTrue(window.reset_button.isHidden())
        window.workflow.slicer_unavailable("Kein Slicer verfügbar")
        self.assertTrue(window.reset_button.isHidden())
        window.close()

    def test_gui_sources_do_not_use_visual_animation_classes(self) -> None:
        gui_root = SRC_ROOT / "cooling_tower" / "gui"
        forbidden = (
            "QPropertyAnimation",
            "QVariantAnimation",
            "QParallelAnimationGroup",
            "QGraphicsOpacityEffect",
        )
        source_text = "\n".join(
            path.read_text(encoding="utf-8")
            for path in gui_root.rglob("*.py")
        )
        for class_name in forbidden:
            self.assertNotIn(class_name, source_text)

    def test_invalid_domain_limits_preserve_the_entered_value(self) -> None:
        window = self.window()
        window.workflow.analysis_succeeded("referenz.gcode")
        window.workflow.slicer_succeeded("Testslicer")
        setting = window._setting_widgets["maximum_expansion_angle_deg"]
        line_edit = window.maximum_expansion_angle_spin.lineEdit()
        line_edit.setText(
            window.maximum_expansion_angle_spin.textFromValue(71.0)
        )
        self.app.processEvents()
        self.assertTrue(bool(window.maximum_expansion_angle_spin.property("invalid")))
        self.assertEqual(window.maximum_expansion_angle_spin.value(), 71.0)
        self.assertIn("Maximalwert 70,0 °", setting.message_label.text())
        self.assertIn("Vorsicht", setting.secondary_message_label.text())
        self.assertIn("Maximalwert 70,0 °", window.validation_label.text())

        integer_setting = window._setting_widgets["mesh_segments"]
        window.mesh_segments_spin.lineEdit().setText("2")
        self.app.processEvents()
        self.assertEqual(window.mesh_segments_spin.value(), 2)
        self.assertIn("Mindestwert 3", integer_setting.message_label.text())
        window.mesh_segments_spin.lineEdit().setText("513")
        self.app.processEvents()
        self.assertEqual(window.mesh_segments_spin.value(), 513)
        self.assertIn("Maximalwert 512", integer_setting.message_label.text())
        window.close()

    def test_footer_explains_causes_without_solution_suggestions(self) -> None:
        window = self.window()
        window.workflow.analysis_succeeded("referenz.gcode")
        window.workflow.slicer_succeeded("Testslicer")
        window.minimum_outer_spin.setValue(30.0)
        window.maximum_outer_spin.setValue(20.0)
        window.minimum_wall_spin.setValue(5.0)
        window.maximum_wall_spin.setValue(4.0)
        window._last_changed_setting_name = "maximum_wall_thickness_mm"
        window.validate_form()
        self.assertTrue(window.validation_label.text().strip())
        self.assertNotIn("Mögliche Lösungen", window.validation_label.text())
        self.assertFalse(hasattr(window, "error_solutions_toggle"))
        self.assertFalse(hasattr(window, "error_solutions_label"))
        window.close()

    def test_expansion_angle_above_70_is_preserved_but_invalid(self) -> None:
        window = self.window()
        window.workflow.analysis_succeeded("referenz.gcode")
        window.workflow.slicer_succeeded("Testslicer")
        self.assertEqual(
            window.maximum_expansion_angle_spin.property("validationMaximum"),
            70.0,
        )
        window.maximum_expansion_angle_spin.setValue(85.0)
        self.assertEqual(window.maximum_expansion_angle_spin.value(), 85.0)
        self.assertTrue(window.maximum_expansion_angle_spin.property("invalid"))

        invalid = replace(
            GenerationSettings(),
            maximum_expansion_angle_deg=70.1,
        )
        with self.assertRaisesRegex(ValueError, "at most 70 degrees"):
            validate_hollow_settings(invalid)

        issue = FeasibilityIssue(
            code="EXPANSION_ANGLE_TOO_SMALL",
            message="Expansion angle is too small.",
            affected_layer_index=50,
            affected_z_mm=10.0,
            related_setting_names=("maximum_expansion_angle_deg",),
            required_value=89.5,
            achievable_value=70.0,
        )
        window._last_changed_setting_name = "maximum_expansion_angle_deg"
        group = window._group_feasibility_issues((issue,))[0]
        solutions = group["solutions"]
        self.assertIn("zuletzt geänderten Aufweitungswinkel", solutions[0])
        self.assertIn("70°", solutions[0])
        self.assertFalse(any("89,5° erhöhen" in item for item in solutions))
        self.assertNotIn("Layer", group["inline"])
        self.assertNotIn("Lösungen", group["inline"])
        self.assertIn("Betroffen ist 1 Layer", group["summary"])
        self.assertIn(
            "Erforderlich sind bis zu 89,50°. Zulässig sind höchstens 70,00°.",
            group["summary"],
        )
        window.close()

    def test_error_badge_stays_within_fixed_header_height(self) -> None:
        card = SectionCard("Testbereich", collapsible=True)
        card.show()
        self.app.processEvents()
        before = card.header.height()
        card.set_summary_badge("3 Fehler")
        self.app.processEvents()
        self.assertEqual(before, METRICS.card_header_height_px)
        self.assertEqual(card.header.height(), before)
        self.assertLessEqual(card.badge_label.height(), card.header.height())
        card.close()

    def test_footer_never_displays_solution_suggestions(self) -> None:
        window = self.window()
        self.assertFalse(hasattr(window, "error_solutions_toggle"))
        self.assertFalse(hasattr(window, "error_solutions_label"))
        self.assertNotIn("Mögliche Lösungen", window.validation_label.text())
        window.close()

    def test_preview_actions_are_disabled_while_a_preview_job_exists(self) -> None:
        window = self.window()
        window.preview_button.setEnabled(True)
        window.preview_dialog.update_button.setEnabled(True)
        window.prediction_method_label.setText("Analytische Schätzung")
        window._slicer_prediction_is_offered = lambda: True
        window.slicer_prediction_button.setVisible(True)
        window.slicer_prediction_button.setEnabled(True)
        window.preview_state = PreviewState.BUILDING
        window._preview_jobs[99] = (SimpleNamespace(), SimpleNamespace())
        window._refresh_phase17_actions()
        window._update_responsive_action_labels()
        self.assertFalse(window.preview_button.isEnabled())
        self.assertFalse(window.preview_dialog.update_button.isEnabled())
        self.assertFalse(window.slicer_prediction_button.isEnabled())
        self.assertEqual(
            window.slicer_prediction_button.text(),
            "Schätzung wird durchgeführt...",
        )
        self.assertIn(
            "Während die Vorschau erstellt wird",
            window.slicer_prediction_button.toolTip(),
        )
        self.assertEqual(window.preview_button.text(), "Vorschau wird erstellt...")
        self.assertEqual(
            window.preview_dialog.update_button.text(),
            "Vorschau wird erstellt...",
        )
        window._preview_jobs.clear()
        window.close()

    def test_calculation_settings_follow_only_the_geometry_dropdown(self) -> None:
        window = self.window()
        window.resize(1205, 1393)
        window.show()
        window.workflow.analysis_succeeded("test.gcode")
        window.workflow.slicer_succeeded("Testslicer")
        QTest.qWait(METRICS.first_success_animation_duration_ms + 100)
        self.app.processEvents()
        geometry = window.geometry_settings_group
        self.assertTrue(geometry.isChecked())
        self.assertFalse(window.mesh_segments_spin.isHidden())
        self.assertFalse(window.local_window_spin.isHidden())
        geometry.set_expanded(False, animated=True)
        QTest.qWait(METRICS.animation_duration_ms + 40)
        self.app.processEvents()
        self.assertTrue(geometry.content_widget.isHidden())
        self.assertFalse(window.mesh_segments_spin.isVisible())
        self.assertFalse(window.local_window_spin.isVisible())
        geometry.set_expanded(True, animated=True)
        QTest.qWait(METRICS.animation_duration_ms + 40)
        self.app.processEvents()
        self.assertFalse(geometry.content_widget.isHidden())
        self.assertFalse(window.mesh_segments_spin.isHidden())
        self.assertFalse(window.local_window_spin.isHidden())
        window.close()

    def test_export_notice_uses_content_height(self) -> None:
        window = self.window()
        window.resize(1300, 900)
        window.show()
        self.app.processEvents()
        self.app.processEvents()
        self.assertEqual(window.footer.maximumHeight(), 350)
        self.assertLess(window.footer.height(), 350)
        window.warning_text.setPlainText(
            "Die Sliceroptimierung hat die Zielzeit noch nicht vollständig "
            "erreicht. Bitte die tatsächliche Layerzeit kontrollieren."
        )
        window._refresh_issue_panels()
        self.app.processEvents()
        window.warning_text.fit_to_document()
        self.app.processEvents()
        self.assertLessEqual(window.warning_text.height(), 60)
        self.assertLess(window.notice_panel.height(), 100)

        window.workflow.slicer_succeeded("Layoutprüfung")
        long_message = "Ausführlicher prüfbarer Hinweis. " * 80
        window.validation_label.setText(long_message)
        window._static_error_causes = ["Fehler"] * 4
        window._refresh_issue_panels()
        window.error_panel.set_expanded(True)
        self.app.processEvents()
        self.app.processEvents()
        self.assertEqual(window.footer.height(), 350)
        self.assertGreater(
            window.footer_messages_scroll.verticalScrollBar().maximum(),
            0,
        )
        for button in (
            window.open_output_button,
            window.open_stl_button,
            window.preview_action_control,
            window.export_button,
        ):
            self.assertTrue(button.isVisible())
            self.assertTrue(window.footer.isAncestorOf(button))
            self.assertTrue(
                window.footer.rect().contains(
                    button.mapTo(
                        window.footer,
                        button.rect().bottomLeft(),
                    )
                )
            )
        self.assertEqual(window.reset_button.parent().objectName(), "mainHeader")
        window.close()

    def test_one_off_slicer_prediction_always_uses_five_iterations(self) -> None:
        class FakePreviewService:
            def __init__(self) -> None:
                self.iterations: list[int] = []

            def prepare(self, request, *, cancellation_event, progress_callback):
                self.iterations.append(request.calibration_config.maximum_iterations)
                progress_callback(50, "Slicer wird ausgewertet")
                return SimpleNamespace(
                    minimum_verified_layer_time_s=12.5,
                    dispose=lambda: None,
                )

        service = FakePreviewService()
        window = MainWindow(
            user_settings_path=self.root / "settings.json",
            preview_service=service,
        )
        window.preview_quality_buttons["balanced"].click()
        installation = SlicerInstallation(
            adapter_id="test",
            product_name="Testslicer",
            version="1.0",
            executable_path=self.root / "slicer.exe",
            verified=True,
            capabilities=frozenset({SlicerCapability.CLI_SLICE}),
            discovery_source=SlicerDiscoverySource.KNOWN_PATH,
            support_level=SlicerSupportLevel.FULL,
        )
        window.slicer_discovery_result = SlicerDiscoveryResult(
            installations=(installation,),
            recommended_key=installation.identity_key,
            gui_state=SlicerGuiState.AVAILABLE,
            message="verfügbar",
        )
        window.slicer_combo.addItem("Testslicer", installation.identity_key)
        selected = SimpleNamespace(
            effective_profile=object(),
            bundle_id="bundle",
        )
        window.profile_match_result = SimpleNamespace(
            selected=selected,
            can_use_stl_mode=True,
            execution_slicer=installation,
            inventory_fingerprint="inventory",
            user_confirmed=True,
        )
        window.analysis_snapshot = SimpleNamespace(maximum_print_z_mm=20.0)
        window.tower_assessment = SimpleNamespace(
            tower_required=True,
            target_layer_time_s=15.0,
            deficit_layer_count=4,
            tower_end_z_mm=20.0,
        )
        window.profile_feasibility = ProfileFeasibilityAssessment(
            tower_required=True,
            feasible=True,
            estimated_minimum_combined_layer_time_s=9.0,
        )
        with patch.object(window.slicer_service, "adapter_for", return_value=object()):
            window.start_slicer_prediction()
        for _ in range(100):
            self.app.processEvents()
            if not window._slicer_prediction_jobs:
                break
            QTest.qWait(10)
        self.assertEqual(service.iterations, [5])
        self.assertEqual(window.preview_quality, "balanced")
        self.assertEqual(
            window.prediction_method_label.text(),
            "Slicer-gestützte Annäherung",
        )
        self.assertEqual(window.prediction_value_labels["minimum"].text(), "12,50 s")
        window.close()

    def test_left_drag_rotation_directions_are_inverted(self) -> None:
        canvas = PreviewCanvas()
        canvas._last_mouse = QPoint(100, 100)
        canvas._drag_button = Qt.MouseButton.LeftButton
        yaw = canvas.yaw_deg
        pitch = canvas.pitch_deg
        event = SimpleNamespace(
            position=lambda: QPointF(120.0, 115.0),
            accept=lambda: None,
        )
        canvas.mouseMoveEvent(event)
        self.assertLess(canvas.yaw_deg, yaw)
        self.assertGreater(canvas.pitch_deg, pitch)
        canvas.close()


if __name__ == "__main__":
    unittest.main()
