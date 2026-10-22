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
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from cooling_tower.gui.design_tokens import METRICS
from cooling_tower.gui.background_jobs import JobKind
from cooling_tower.gui.main_window import MainWindow
from cooling_tower.gui.user_messages import german_user_message
from cooling_tower.gui.workflow_controller import WorkflowController
from cooling_tower.gui.widgets import PreviewCanvas, SectionCard, SectionState
from cooling_tower.models import (
    BedBounds,
    FeasibilityIssue,
    GenerationSettings,
    ProfileFeasibilityAssessment,
    SourceKind,
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
from cooling_tower.tower.solid_profile import validate_solid_settings
from gui_lifecycle import dispose_test_widget


class Phase18UiTests(unittest.TestCase):
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

    def unlock_preparation_step(self, window: MainWindow) -> None:
        source = (self.root / "referenz.stl").resolve()
        source.write_text("solid x\nendsolid x\n", encoding="ascii")
        window.current_source_path = source
        window.current_source_kind = SourceKind.STL
        window.source_artifact = SimpleNamespace(
            original_path=source,
            matches_current_file=lambda: True,
        )
        window.stl_validation_result = SimpleNamespace(valid=True)
        window._update_preparation_requirements()

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

        controller.begin_source_validation(is_stl=True)
        controller.source_validation_succeeded("datei.stl geprüft")
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

        controller.begin_source_validation(is_stl=True)
        controller.source_validation_succeeded("erneut geprüft")
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
        row = window._setting_widgets["target_layer_time_s"]
        grid = row.layout()
        self.assertEqual(grid.getItemPosition(grid.indexOf(row.info_button))[:2], (0, 0))
        self.assertEqual(grid.getItemPosition(grid.indexOf(row.label))[:2], (0, 1))
        self.assertEqual(grid.columnStretch(0), 0)
        self.assertEqual(grid.columnStretch(1), 1)
        self.assertEqual(grid.getItemPosition(grid.indexOf(row.editor))[:2], (0, 2))
        self.assertEqual(
            grid.getItemPosition(grid.indexOf(row.reset_button))[:2],
            (0, 3),
        )
        self.assertEqual(window.timing_group.state(), SectionState.NEUTRAL)
        window.close()

    def test_header_divider_stays_visible_across_scroll_range_changes(self) -> None:
        window = self.window()
        window.resize(1400, 1400)
        window.show()
        self.app.processEvents()
        scrollbar = window.settings_scroll.verticalScrollBar()
        self.assertEqual(scrollbar.maximum(), scrollbar.minimum())
        self.assertFalse(window.main_header.property("scrolled"))
        divider_colour = window.workflow_header.separator.grab().toImage().pixelColor(0, 0)

        window.settings_content.setMinimumHeight(
            window.settings_scroll.viewport().height() + 300
        )
        self.app.processEvents()
        self.assertGreater(scrollbar.maximum(), scrollbar.minimum())
        self.assertFalse(window.main_header.property("scrolled"))
        header_pixel = lambda: window.main_header.grab().toImage().pixelColor(
            window.main_header.width() // 2, window.main_header.height() - 1
        )
        self.assertEqual(header_pixel(), divider_colour)

        scrollbar.setValue(scrollbar.minimum() + 1)
        self.app.processEvents()
        self.assertTrue(window.main_header.property("scrolled"))
        self.assertEqual(header_pixel(), divider_colour)

        scrollbar.setValue(scrollbar.minimum())
        self.app.processEvents()
        self.assertFalse(window.main_header.property("scrolled"))
        self.assertEqual(header_pixel(), divider_colour)

        scrollbar.setValue(scrollbar.maximum())
        self.app.processEvents()
        self.assertTrue(window.main_header.property("scrolled"))
        window._refresh_settings_content_minimum_height()
        self.app.processEvents()
        self.assertEqual(scrollbar.maximum(), scrollbar.minimum())
        self.assertFalse(window.main_header.property("scrolled"))
        self.assertEqual(header_pixel(), divider_colour)
        window.close()

    def test_ready_columns_and_single_geometry_column_are_independently_sized(self) -> None:
        window = self.window()
        window.resize(1400, 1000)
        window.show()
        self.complete_source_step(window)
        window.workflow.slicer_succeeded("Layoutprüfung")
        window.workflow.complete_preparation()
        window.automatic_generation_card.click()
        self.app.processEvents()
        self.assertTrue(window.ready_grid.is_two_column())
        self.assertTrue(
            window.ready_left_column.isAncestorOf(window.geometry_settings_group)
        )
        geometry_sections = (
            window.timing_group,
            window.geometry_group,
        )
        self.assertEqual(
            [section.y() for section in geometry_sections],
            sorted(section.y() for section in geometry_sections),
        )
        for card in (window.geometry_settings_group, window.prediction_frame):
            self.assertFalse(card.isCheckable())
            self.assertTrue(card.isChecked())
            self.assertFalse(card.toggle_button.isVisible())
        self.assertTrue(bool(window.geometry_settings_group.property("outerDropdown")))
        self.assertEqual(window.prediction_frame.property("cardTone"), "preview")
        expanded_geometry_height = window.geometry_settings_group.height()
        window.geometry_settings_group.setChecked(False)
        self.app.processEvents()
        self.assertTrue(window.geometry_settings_group.content_widget.isVisible())
        self.assertTrue(window.prediction_frame.content_widget.isVisible())
        self.assertEqual(
            window.geometry_settings_group.height(),
            expanded_geometry_height,
        )
        self.assertEqual(
            window.geometry_settings_group.title_label.text(),
            "Turmeinstellungen",
        )
        self.assertTrue(bool(window.geometry_group.property("collapsible")))
        self.assertFalse(bool(window.stability_group.property("collapsible")))
        for card in (
            window.geometry_settings_group,
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

    def test_reload_action_revalidates_the_same_stl(self) -> None:
        source = self.root / "referenz.stl"
        source.write_bytes(b"solid test\nendsolid test\n")
        window = self.window()
        window.current_source_path = source
        with patch.object(window.drop_zone, "set_file") as selected:
            window.reload_source()
        selected.assert_called_once_with(source.resolve())
        self.assertEqual(window.drop_zone.reload_button.text(), "STL neu einlesen")
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
        automatic_sources = {
            SlicerDiscoverySource.REGISTRY_SYSTEM,
            SlicerDiscoverySource.REGISTRY_USER,
            SlicerDiscoverySource.APP_PATHS,
            SlicerDiscoverySource.APP_PACKAGE,
            SlicerDiscoverySource.KNOWN_PATH,
            SlicerDiscoverySource.START_MENU,
        }
        for source in SlicerDiscoverySource:
            installation = replace(automatic, discovery_source=source)
            window._set_slicer_header_summary(installation)
            self.assertEqual(
                window.slicer_group.summary(),
                installation.display_name,
            )
            self.assertEqual(
                installation.automatically_discovered,
                source in automatic_sources,
            )
            if source in automatic_sources:
                self.assertEqual(
                    window.slicer_group.title_note_label.text(),
                    "(automatisch erkannt)",
                )
                self.assertEqual(
                    window.slicer_group.title_note_label.property("severity"),
                    "success",
                )
            else:
                self.assertTrue(window.slicer_group.title_note_label.isHidden())
        self.assertTrue(window.slicer_group.summary_note_label.isHidden())
        window.close()

    def test_header_space_hover_chevrons_footer_and_prediction_padding(self) -> None:
        window = self.window()
        window.resize(1100, 900)
        window.show()
        self.unlock_preparation_step(window)
        window.preparation_tabs.setCurrentIndex(1)
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
        self.assertIn("QComboBox QAbstractItemView::item:hover", stylesheet)
        self.assertIn("selection-background-color: #e5f1fa", stylesheet)
        combo_hover = stylesheet[stylesheet.index("QComboBox:hover::drop-down"):]
        combo_hover = combo_hover[:combo_hover.index("}")]
        self.assertIn("background: #eaf1f7", combo_hover)
        self.assertNotIn("border:", combo_hover)
        self.assertNotIn("border-left:", combo_hover)
        self.assertNotIn("border-color:", combo_hover)
        self.assertIn("QComboBox:hover,", stylesheet)
        self.assertIn('QComboBox[hovered="true"]', stylesheet)
        self.assertIn(
            'QComboBox[important="true"][hovered="true"]',
            stylesheet,
        )
        self.assertIn("background: #d8ebf8", stylesheet)
        self.assertIn("QComboBox QAbstractItemView:hover", stylesheet)
        generic_combo_hover = stylesheet[stylesheet.index("QComboBox:hover,"):]
        generic_combo_hover = generic_combo_hover[
            :generic_combo_hover.index("}")
        ]
        popup_hover = stylesheet[
            stylesheet.index("QComboBox QAbstractItemView:hover"):
        ]
        popup_hover = popup_hover[:popup_hover.index("}")]
        explicit_hover_start = stylesheet.rindex(
            'QComboBox[important="true"][hovered="true"] {'
        )
        explicit_hover = stylesheet[explicit_hover_start:]
        explicit_hover = explicit_hover[:explicit_hover.index("}")]
        for hover_rule in (
            generic_combo_hover,
            popup_hover,
            explicit_hover,
        ):
            self.assertNotIn("border:", hover_rule)
            self.assertNotIn("border-left:", hover_rule)
            self.assertNotIn("border-color:", hover_rule)
        for combo in (
            window.slicer_combo,
            window.machine_profile_combo,
            window.filament_profile_combo,
            window.process_profile_combo,
        ):
            combo.setEnabled(True)
            QApplication.sendEvent(combo, QEvent(QEvent.Type.Leave))
            self.app.processEvents()
            geometry_before_hover = combo.geometry()
            normal_image = combo.grab().toImage()
            QApplication.sendEvent(combo, QEvent(QEvent.Type.Enter))
            self.app.processEvents()
            self.assertTrue(combo.property("hovered"))
            self.assertEqual(combo.geometry(), geometry_before_hover)
            hovered_image = combo.grab().toImage()
            self.assertEqual(
                hovered_image.pixelColor(combo.width() // 2, 7).name(),
                "#dceef8",
            )
            self.assertEqual(
                hovered_image.pixelColor(combo.width() - 10, 7).name(),
                "#c7e1f2",
            )
            self.assertEqual(
                hovered_image.pixelColor(0, combo.height() // 2).name(),
                "#70a9d2",
            )
            QApplication.sendEvent(combo, QEvent(QEvent.Type.Leave))
            self.assertFalse(combo.property("hovered"))
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
        button = window.full_infill_info_button
        self.assertEqual(
            (button.width(), button.height()),
            (19, 19),
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
        self.assertTrue(
            popover.testAttribute(
                Qt.WidgetAttribute.WA_TransparentForMouseEvents
            )
        )

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
        self.assertEqual(geometry.title(), "Turmeinstellungen")
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
        self.assertFalse(
            geometry.content_widget.isAncestorOf(window.local_window_spin)
        )
        self.assertTrue(
            window.geometry_split.isAncestorOf(
                window.geometry_group
            )
        )
        self.assertFalse(
            window.stability_group.isAncestorOf(
                window.geometry_calculation_section
            )
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
        self.assertFalse(window.local_window_spin.isHidden())
        self.assertGreater(geometry.content_widget.height(), 0)
        self.assertEqual(window.geometry_group.title_label.font().pointSizeF(), 11.5)
        self.assertEqual(window.geometry_settings_group.title_label.font().pointSizeF(), 12.0)
        self.assertTrue(window.geometry_calculation_section.isHidden())
        stylesheet = window.styleSheet()
        geometry_subsection_selector = (
            'QWidget#geometrySettingsSplit '
            'QFrame#sectionCard[subsection="single"]'
        )
        self.assertIn(geometry_subsection_selector, stylesheet)
        self.assertIn(
            "background: #ffffff;",
            stylesheet[stylesheet.index(geometry_subsection_selector):],
        )
        for subsection in (window.geometry_group,):
            header_image = subsection.header.grab().toImage()
            body_image = subsection.content_widget.grab().toImage()
            self.assertEqual(
                header_image.pixelColor(
                    header_image.width() // 2,
                    5,
                ).name(),
                "#f4f6f8",
            )
            self.assertEqual(
                body_image.pixelColor(
                    body_image.width() - 5,
                    body_image.height() - 5,
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
            "#ffffff",
        )
        window._refresh_collapsible_error_badges(
            {"local_reference_window": ["Ungültiges Zeitfenster"]}
        )
        self.assertEqual(geometry.badge_label.text(), "1 Fehler")
        self.assertEqual(geometry.state(), SectionState.ERROR)
        window._refresh_collapsible_error_badges({})

        window.joint_slice_settings_action.trigger()
        self.app.processEvents()
        dialog = window._joint_slice_settings_dialog
        self.assertTrue(dialog.isVisible())
        self.assertEqual(
            dialog.windowTitle(),
            "Allgemeine Einstellungen",
        )
        dialog_labels = {
            label.text()
            for label in dialog.findChildren(QLabel)
        }
        self.assertIn("Exportordner", dialog_labels)
        self.assertNotIn(
            "Hier legen Sie programmweite Ausgabeoptionen fest.",
            dialog_labels,
        )
        self.assertEqual(window.options_button.text(), "")
        self.assertFalse(window.options_button.icon().isNull())
        self.assertEqual(window.options_button.iconSize().width(), 18)
        self.assertFalse(hasattr(window, "stl_info_button"))
        self.assertLess(
            window.reset_button.geometry().left(),
            window.options_button.geometry().left(),
        )
        window.close()

    def test_additional_options_dialog_is_content_high_and_centred(self) -> None:
        window = self.window()
        window.resize(720, 800)
        window.move(40, 0)
        window.show()
        self.app.processEvents()
        window.joint_slice_settings_action.trigger()
        QTest.qWait(30)
        self.app.processEvents()
        dialog = window._joint_slice_settings_dialog
        self.assertGreaterEqual(dialog.width(), 707)
        self.assertEqual(
            (dialog.separate_spin_box.width(), dialog.spin_box.width(),
             dialog.local_window_spin_box.width()),
            (165, 165, 165),
        )
        self.assertEqual(dialog.height(), dialog.layout().sizeHint().height())
        self.assertLess(dialog.height(), window.height() * 0.65)
        self.assertEqual(dialog.footer_divider.x(), 0)
        self.assertEqual(dialog.footer_divider.width(), dialog.width())
        browse = next(
            button for button in dialog.findChildren(QPushButton)
            if button.text() == "Auswählen …"
        )
        self.assertEqual(browse.height(), dialog.output_root_edit.height())
        export_controls = (dialog.output_root_edit, browse, dialog.output_reset_button)
        self.assertEqual(len({control.height() for control in export_controls}), 1)
        self.assertEqual(
            len({control.mapTo(dialog, QPoint(0, 0)).y() for control in export_controls}),
            1,
        )
        self.assertIsNot(dialog.focusWidget(), dialog.output_root_edit)
        self.assertFalse(dialog.output_root_edit.hasSelectedText())
        footer_buttons = (
            dialog.general_reset_button,
            dialog.apply_button,
            next(button for button in dialog.findChildren(QPushButton)
                 if button.text() == "Abbrechen"),
        )
        self.assertEqual(
            {button.height() for button in footer_buttons},
            {window.reset_button.height()},
        )
        self.assertEqual(
            {button.font().pointSizeF() for button in footer_buttons},
            {window.reset_button.font().pointSizeF()},
        )
        cancel = next(
            button for button in dialog.findChildren(QPushButton)
            if button.text() == "Abbrechen"
        )
        self.assertEqual(
            dialog.footer_divider.y()
            - browse.mapTo(dialog, QPoint(0, browse.height())).y(),
            20,
        )
        self.assertEqual(
            cancel.mapTo(dialog, QPoint(0, 0)).y()
            - (dialog.footer_divider.y() + dialog.footer_divider.height()),
            20,
        )
        self.assertLessEqual(
            abs(
                dialog.frameGeometry().center().y()
                - window.frameGeometry().center().y()
            ),
            2,
        )
        window.close()

    def test_preparation_steps_are_sequential_and_bounded_to_700_px(self) -> None:
        window = self.window()
        window.resize(1205, 1393)
        window.show()
        self.app.processEvents()
        self.assertTrue(window.source_group.isVisible())
        self.assertFalse(window.slicer_group.isVisible())
        self.assertEqual(window.source_group.width(), 700)
        self.assertGreaterEqual(window.drop_zone.height(), 180)
        self.assertEqual(window.settings_scroll.horizontalScrollBar().maximum(), 0)
        window.preparation_tabs.setCurrentIndex(1)
        self.app.processEvents()
        self.assertEqual(window.preparation_tabs.currentIndex(), 0)
        self.assertTrue(window.source_group.isVisible())
        self.assertFalse(window.slicer_group.isVisible())
        self.unlock_preparation_step(window)
        window.preparation_tabs.setCurrentIndex(1)
        self.app.processEvents()
        self.assertFalse(window.source_group.isVisible())
        self.assertTrue(window.slicer_group.isVisible())
        self.assertEqual(window.slicer_group.width(), 700)
        window.close()

    def test_outer_sections_keep_header_colours_without_side_accents(self) -> None:
        window = self.window()
        window.resize(1200, 900)
        window.show()
        self.app.processEvents()
        outer_groups = (
            window.workflow_group,
            window.geometry_settings_group,
            window.prediction_frame,
        )
        for group in outer_groups:
            self.assertTrue(group.property("outerDropdown"))
        self.assertFalse(window.workflow_group.property("bodyHover"))
        self.assertFalse(window.geometry_settings_group.property("bodyHover"))
        self.assertFalse(window.timing_group.property("bodyHover"))
        self.assertFalse(window.prediction_frame.property("bodyHover"))
        self.assertFalse(bool(window.geometry_group.property("outerDropdown")))
        self.assertEqual(window.prediction_frame.property("cardTone"), "preview")
        self.assertIn(
            'QFrame#sectionCard[outerDropdown="true"] > QFrame#sectionCardHeader',
            window.styleSheet(),
        )
        self.assertIn(
            'QFrame#sectionCard[outerDropdown="true"]'
            '[collapsible="true"][bodyHover="true"]:hover',
            window.styleSheet(),
        )
        stylesheet = window.styleSheet()
        outer_hover_start = stylesheet.index(
            'QFrame#sectionCard[outerDropdown="true"]'
            '[collapsible="true"][bodyHover="true"]:hover'
        )
        outer_hover = stylesheet[outer_hover_start:]
        outer_hover = outer_hover[:outer_hover.index("}")]
        collapsible_hover_start = stylesheet.index(
            "QGroupBox#collapsibleGroup:hover"
        )
        collapsible_hover = stylesheet[collapsible_hover_start:]
        collapsible_hover = collapsible_hover[:collapsible_hover.index("}")]
        header_hover_start = stylesheet.index(
            'QFrame#sectionCard[collapsible="true"] '
            "QFrame#sectionCardHeader:hover"
        )
        header_hover = stylesheet[header_hover_start:]
        header_hover = header_hover[:header_hover.index("}")]
        for hover_rule in (outer_hover, collapsible_hover, header_hover):
            self.assertNotIn("border:", hover_rule)
            self.assertNotIn("border-left:", hover_rule)
            self.assertNotIn("border-color:", hover_rule)
            self.assertNotIn("border-radius:", hover_rule)
        # The downstream cards are deliberately hidden during preparation.
        # Reveal them only for this paint-level style check.
        window.ready_grid.show()
        self.app.processEvents()
        initial_header = window.workflow_group.header.grab().toImage()
        self.assertEqual(
            initial_header.pixelColor(initial_header.width() // 2, 5).name(),
            "#ebf5fb",
        )
        self.assertFalse(window.timing_group.property("outerDropdown"))
        self.assertTrue(window.timing_group.header.isHidden())
        geometry_header = window.geometry_settings_group.header.grab().toImage()
        self.assertEqual(
            geometry_header.pixelColor(
                geometry_header.width() // 2,
                5,
            ).name(),
            "#ebf5fb",
        )
        prediction_header = window.prediction_frame.header.grab().toImage()
        self.assertEqual(
            prediction_header.pixelColor(
                prediction_header.width() // 2,
                5,
            ).name(),
            "#f4f1fe",
        )
        for group in (
            window.workflow_group,
            window.geometry_settings_group,
        ):
            self.assertEqual(group.title_label.font().pointSizeF(), 12.0)
            self.assertEqual(group.title_label.font().weight(), 700)
            self.assertEqual(
                group.title_label.palette().color(
                    group.title_label.foregroundRole()
                ).name(),
                "#40576a",
            )
        self.assertEqual(
            window.prediction_frame.title_label.font().pointSizeF(),
            12.0,
        )
        self.assertEqual(
            window.prediction_frame.title_label.font().weight(),
            700,
        )
        self.assertEqual(
            window.prediction_frame.title_label.palette().color(
                window.prediction_frame.title_label.foregroundRole()
            ).name(),
            "#4d3c86",
        )
        expected_accents = {
            window.geometry_settings_group: "#1769aa",
            window.prediction_frame: "#6f52c9",
        }
        for group, colour in expected_accents.items():
            image = group.grab().toImage()
            self.assertNotEqual(
                image.pixelColor(1, image.height() // 2).name(),
                colour,
            )
            self.assertEqual(group.contentsMargins().left(), 0)
            self.assertEqual(group.contentsMargins().right(), 0)
        preparation_image = window.workflow_group.grab().toImage()
        self.assertNotEqual(
            preparation_image.pixelColor(
                1,
                preparation_image.height() // 2,
            ).name(),
            "#1769aa",
        )
        self.assertFalse(window.workflow_group.isCheckable())
        for group in (window.timing_group, window.prediction_frame):
            body_y = min(
                group.height() - 2,
                group.header.height() + 12,
            )
            normal_body = group.grab().toImage().pixelColor(
                group.width() // 2,
                body_y,
            )
            QApplication.sendEvent(group, QEvent(QEvent.Type.Enter))
            self.app.processEvents()
            hovered_body = group.grab().toImage().pixelColor(
                group.width() // 2,
                body_y,
            )
            self.assertEqual(hovered_body, normal_body)
            QApplication.sendEvent(group, QEvent(QEvent.Type.Leave))
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

        self.complete_source_step(window)
        window.workflow.slicer_succeeded("Testslicer")
        window.workflow.complete_preparation()
        window.automatic_generation_card.click()
        window.prediction_frame.set_state(SectionState.SUCCESS)
        QTest.qWait(METRICS.first_success_animation_duration_ms + 100)
        image = window.workflow_group.header.grab().toImage()
        self.assertEqual(
            image.pixelColor(image.width() // 2, 5).name(),
            "#ebf5fb",
        )
        completed_preparation = window.workflow_group.grab().toImage()
        self.assertNotEqual(
            completed_preparation.pixelColor(
                1,
                completed_preparation.height() // 2,
            ).name(),
            "#238a5b",
        )
        prediction_image = window.prediction_frame.grab().toImage()
        self.assertEqual(
            prediction_image.pixelColor(
                5,
                window.prediction_frame.header.height() + 5,
            ).name(),
            "#ffffff",
        )
        self.assertEqual(
            prediction_image.pixelColor(
                1,
                prediction_image.height() // 2,
            ).name(),
            "#ffffff",
        )
        icon_colours = {
            group.status_icon.palette().color(
                group.status_icon.foregroundRole()
            ).name()
            for group in (
                window.workflow_group,
                window.source_group,
                window.slicer_group,
                window.prediction_frame,
            )
        }
        self.assertEqual(icon_colours, {"#176b45"})
        self.assertFalse(hasattr(window, "profile_group"))
        window.close()

    def test_preview_is_embedded_visible_and_fixed_before_first_scene(self) -> None:
        window = self.window()
        window.resize(900, 700)
        window.show()
        self.complete_source_step(window)
        window.workflow.slicer_succeeded("Testslicer")
        window.workflow.complete_preparation()
        window.automatic_generation_card.click()
        self.app.processEvents()
        self.assertTrue(window.preview_dialog.isVisible())
        self.assertFalse(window.preview_dialog.isWindow())
        self.assertTrue(
            window.prediction_frame.isAncestorOf(window.preview_dialog)
        )
        self.assertEqual(
            window.preview_dialog.canvas.height(),
            420,
        )
        self.assertEqual(
            window.preview_dialog.state_label.text(),
            "Vorschau wurde noch nicht erstellt.",
        )
        self.assertTrue(window.preview_dialog.state_label.isHidden())
        self.assertTrue(window.preview_dialog.three_quarter_button.isHidden())
        self.assertFalse(hasattr(window.preview_dialog, "update_button"))
        self.assertFalse(hasattr(window.preview_dialog, "export_button"))
        self.assertTrue(window.preview_dialog.progress.isHidden())
        window.close()

    def test_preview_result_reflows_without_overlapping_the_canvas(self) -> None:
        window = self.window()
        window.resize(1200, 1000)
        window.show()
        self.complete_source_step(window)
        window.workflow.slicer_succeeded("Testslicer")
        window.workflow.complete_preparation()
        window.automatic_generation_card.click()
        self.app.processEvents()
        dialog = window.preview_dialog
        empty_height = dialog.height()
        scene = PreviewScene(
            object_segments=(
                LineSegment3D(Point3D(0, 0, 0.2), Point3D(10, 10, 5)),
            ),
            tower_segments=(
                LineSegment3D(Point3D(20, 20, 0), Point3D(20, 20, 8)),
            ),
            bed_bounds=BedBounds(0, 100, 0, 100),
            tower_center_xy_mm=(20, 20),
            source_segment_count=1234,
            displayed_segment_count=1,
            tower_height_mm=8,
            object_height_mm=5,
            object_layer_count=25,
            tower_layer_count=25,
        )
        dialog.set_preview(
            SimpleNamespace(
                scene=scene,
                calibrated=False,
                slicer_optimized=False,
                output_mode=SimpleNamespace(value="stl"),
            )
        )
        self.app.processEvents()

        self.assertGreater(dialog.height(), empty_height)
        self.assertEqual(
            dialog.preview_info_header.geometry().bottom() + 1,
            dialog.canvas.geometry().top(),
        )
        self.assertEqual(
            dialog.canvas.geometry().bottom() + 1,
            dialog.legend_widget.geometry().top(),
        )
        self.assertEqual(
            dialog.legend_widget.geometry().bottom() + 1,
            dialog.preview_frame.contentsRect().bottom() + 1,
        )
        self.assertEqual(
            dialog.preview_frame.minimumHeight(),
            dialog.preview_frame.maximumHeight(),
        )
        self.assertEqual(
            dialog.preview_title_widget.height(),
            dialog.preview_title_widget.sizeHint().height(),
        )
        self.assertFalse(
            dialog.canvas.geometry().intersects(
                dialog.preview_info_header.geometry()
            )
        )
        self.assertFalse(
            dialog.canvas.geometry().intersects(dialog.legend_widget.geometry())
        )
        self.assertLess(
            dialog.three_quarter_button.geometry().bottom(),
            dialog.preview_frame.geometry().top(),
        )
        self.assertLessEqual(
            dialog.navigation_hint.geometry().bottom(),
            dialog.contentsRect().bottom(),
        )

        frame_height = dialog.preview_frame.height()
        dialog.set_building("Gemeinsamer Slice wird ausgewertet …")
        dialog.set_intermediate_scene(scene)
        self.app.processEvents()
        self.assertEqual(dialog.preview_frame.height(), frame_height)
        self.assertEqual(
            dialog.preview_title_widget.height(),
            dialog.preview_title_widget.sizeHint().height(),
        )
        self.assertEqual(
            dialog.legend_widget.geometry().bottom() + 1,
            dialog.preview_frame.contentsRect().bottom() + 1,
        )
        window.close()

    def test_prediction_method_colours_and_embedded_preview(self) -> None:
        window = self.window()
        window.resize(1200, 900)
        window.show()
        self.complete_source_step(window)
        window.workflow.slicer_succeeded("Testslicer")
        window.workflow.complete_preparation()
        window.automatic_generation_card.click()
        QTest.qWait(METRICS.first_success_animation_duration_ms + 100)
        self.app.processEvents()
        self.assertFalse(hasattr(window, "slicer_prediction_button"))
        window.prediction_method_label.setText("Slicer-gestützte Schätzung")
        window.prediction_method_label.setProperty("mode", "slicer")
        window._refresh_widget_style(window.prediction_method_label)
        self.assertEqual(
            window.prediction_method_label.property("mode"),
            "slicer",
        )
        self.assertIn(
            'QLabel#predictionMethodBadge[mode="slicer"]',
            window.styleSheet(),
        )
        self.assertTrue(
            window.prediction_frame.isAncestorOf(window.preview_dialog)
        )
        self.assertLess(
            window.prediction_preview_divider.y(),
            window.preview_dialog.y(),
        )
        window.close()

    def test_followup_copy_headers_dropdown_widths_and_prediction_columns(self) -> None:
        window = self.window()
        window.resize(1200, 900)
        window.show()
        self.app.processEvents()
        self.assertEqual(
            window.status_label.text(),
            "Bitte STL auswählen",
        )
        self.assertEqual(window.source_group.status_icon.text(), "⇧")
        self.assertIn("STL-Modell", window.source_guide.text())
        self.assertEqual(
            window.source_guide.text(),
            "Wähle das STL-Modell aus, für das ein Kühlturm erstellt werden soll.",
        )
        self.assertEqual(window.geometry_group.title(), "Erweiterte Turmeinstellungen")
        self.assertEqual(window.stability_group.title(), "Standfuß")
        self.assertEqual(window.overhang_group.title(), "Überhänge")
        self.assertEqual(
            window.subtitle_label.text(),
            "Erzeugt Opferobjekte passend zur gewünschten Layerzeit",
        )
        self.assertEqual(window.prediction_frame.title(), "Generierung und Vorschau")
        self.assertEqual(window.preparation_tabs.count(), 2)
        self.assertEqual(window.preparation_tabs.tabText(0), "1. Dateiübergabe")
        self.assertEqual(
            window.preparation_tabs.tabText(1),
            "2. Slicer-Einstellungen",
        )
        self.assertEqual(window.source_group.maximumWidth(), 16777215)
        self.assertEqual(window.slicer_group.maximumWidth(), 16777215)
        self.assertEqual(
            [shell.maximumWidth() for shell in window.preparation_step_shells],
            [700, 700],
        )
        self.assertTrue(window.preparation_tabs.tabBar().isHidden())
        self.assertEqual(
            [
                selector.property("stepTone")
                for selector in window.preparation_step_selectors
            ],
            ["source", "slicer"],
        )
        self.assertTrue(window.source_group.header.isHidden())
        self.assertTrue(window.slicer_group.header.isHidden())
        self.assertFalse(window.slicer_columns.is_two_column())
        self.assertTrue(window.slicer_columns_divider.isHidden())
        self.assertEqual(
            [label.text() for label in window._slicer_width_labels],
            ["Slicer", "Maschinenprofil", "Prozessprofil", "Filamentprofil"],
        )
        slicer_layout = window.slicer_group.content_layout
        self.assertEqual(slicer_layout.indexOf(window.slicer_progress_bar), -1)
        self.assertEqual(
            slicer_layout.indexOf(window.slicer_progress_status_widget), -1
        )
        self.assertLess(
            slicer_layout.indexOf(window.slicer_analysis_details_toggle),
            slicer_layout.indexOf(window.slicer_columns),
        )
        self.assertLess(
            slicer_layout.indexOf(window.slicer_columns),
            slicer_layout.indexOf(window.slicer_details_divider),
        )
        self.assertLess(
            slicer_layout.indexOf(window.slicer_details_divider),
            slicer_layout.indexOf(window.slicer_message_divider_host),
        )
        self.assertLess(
            window.slicer_selectors_layout.indexOf(
                window.show_all_profiles_row
            ),
            window.slicer_selectors_layout.indexOf(
                window.profile_confirmation_stack
            ),
        )
        self.assertLess(
            slicer_layout.indexOf(window.slicer_message_divider_host),
            slicer_layout.indexOf(window.profile_status_label),
        )
        self.assertFalse(hasattr(window, "profile_group"))

        self.assertFalse(hasattr(window, "prediction_content_grid"))
        self.assertLess(
            window.prediction_frame.content_layout.indexOf(
                window.prediction_primary_widget
            ),
            window.prediction_frame.content_layout.indexOf(
                window.prediction_preview_divider
            ),
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

    def test_preview_starts_in_bed_aligned_view_and_exports_from_dialog(self) -> None:
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
            object_height_mm=1,
            object_layer_count=7,
            tower_layer_count=8,
        )
        result = SimpleNamespace(
            scene=scene,
            calibrated=False,
            slicer_optimized=False,
            output_mode=SimpleNamespace(value="stl"),
        )
        window.preview_dialog.set_preview(result)
        self.assertEqual(
            (window.preview_dialog.canvas.yaw_deg, window.preview_dialog.canvas.pitch_deg),
            (-38.0, 28.0),
        )
        self.assertEqual(
            window.preview_dialog.bed_legend.text(),
            "■ Druckplatte",
        )
        self.assertIn("Segmente:", window.preview_dialog.segments_info_label.text())
        self.assertIn("Höhe:", window.preview_dialog.height_info_label.text())
        self.assertIn("Layer:", window.preview_dialog.layers_info_label.text())
        self.assertIn("7", window.preview_dialog.layers_info_label.text())
        self.assertIn("8", window.preview_dialog.layers_info_label.text())
        self.assertIn(
            "100 x 100 mm",
            window.preview_dialog.bed_info_label.text(),
        )
        self.assertEqual(
            window.preview_dialog.legend_title.text(),
            "Legende:",
        )
        self.assertFalse(hasattr(window.preview_dialog, "reset_camera_button"))
        self.assertFalse(hasattr(window.preview_dialog, "fit_objects_button"))
        self.assertFalse(hasattr(window.preview_dialog, "fit_button"))
        camera_buttons = (
            window.preview_dialog.three_quarter_button,
            window.preview_dialog.front_button,
            window.preview_dialog.side_button,
            window.preview_dialog.top_button,
        )
        self.assertEqual(
            tuple(button.text() for button in camera_buttons),
            ("3/4-Ansicht", "Vorderansicht", "Seitenansicht", "Draufsicht"),
        )
        self.assertEqual(len({button.y() for button in camera_buttons}), 1)
        for button in camera_buttons:
            self.assertGreaterEqual(
                button.width(),
                button.fontMetrics().horizontalAdvance(button.text()) + 18,
            )
        self.assertAlmostEqual(
            window.preview_dialog.canvas.zoom,
            1.0,
        )
        window.preview_dialog.canvas.zoom = 2.0
        window.preview_dialog.side_button.click()
        self.assertAlmostEqual(
            window.preview_dialog.canvas.zoom,
            PreviewCanvas.SIDE_VIEW_ZOOM,
        )
        self.assertFalse(hasattr(window.preview_dialog, "export_requested"))
        self.assertFalse(hasattr(window.preview_dialog, "export_button"))
        window.close()

    def test_side_view_selects_an_axis_that_keeps_both_objects_apart(self) -> None:
        canvas = PreviewCanvas()
        canvas.resize(800, 600)
        scene = PreviewScene(
            object_segments=(
                LineSegment3D(Point3D(0, 0, 0), Point3D(10, 1, 8)),
            ),
            tower_segments=(
                LineSegment3D(Point3D(4, 5, 0), Point3D(6, 6, 12)),
            ),
            bed_bounds=BedBounds(0, 100, 0, 100),
            tower_center_xy_mm=(5, 5.5),
            source_segment_count=1,
            displayed_segment_count=1,
            tower_height_mm=12,
        )
        canvas.set_scene(scene)
        canvas.resize(520, 420)
        canvas.side_view()

        self.assertEqual(canvas.yaw_deg, -90.0)
        context = canvas._projection_context()
        object_x = tuple(
            context.project_raw(point)[0]
            for segment in scene.object_segments
            for point in (segment.start, segment.end)
        )
        tower_x = tuple(
            context.project_raw(point)[0]
            for segment in scene.tower_segments
            for point in (segment.start, segment.end)
        )
        self.assertLess(max(object_x), min(tower_x))

    def test_side_view_keeps_export_bed_axis_when_objects_separate_on_x(self) -> None:
        canvas = PreviewCanvas()
        scene = PreviewScene(
            object_segments=(
                LineSegment3D(Point3D(10, 10, 0), Point3D(15, 30, 8)),
                LineSegment3D(Point3D(15, 30, 8), Point3D(30, 20, 0)),
            ),
            tower_segments=(
                LineSegment3D(Point3D(70, 18, 0), Point3D(75, 23, 12)),
            ),
            bed_bounds=BedBounds(0, 100, 0, 100),
            tower_center_xy_mm=(72.5, 20.5),
            source_segment_count=2,
            displayed_segment_count=2,
            tower_height_mm=12,
        )
        canvas.set_scene(scene)
        canvas.side_view()

        self.assertEqual(canvas.yaw_deg, 0.0)
        context = canvas._projection_context()
        for segment in (*scene.object_segments, *scene.tower_segments):
            for point in (segment.start, segment.end):
                self.assertAlmostEqual(
                    context.project_raw(point)[0], point.x - 50.0
                )
        canvas.front_view()
        self.assertEqual(canvas.yaw_deg, -90.0)
        canvas.top_view()
        self.assertEqual(canvas.yaw_deg, 0.0)
        self.assertEqual(canvas.pitch_deg, 89.0)

    def test_side_view_keeps_object_left_for_every_tower_quadrant(self) -> None:
        for tower_x_mm, tower_y_mm in (
            (10, 50),
            (90, 50),
            (50, 10),
            (50, 90),
            (10, 10),
            (90, 90),
        ):
            with self.subTest(tower=(tower_x_mm, tower_y_mm)):
                canvas = PreviewCanvas()
                scene = PreviewScene(
                    object_segments=(
                        LineSegment3D(
                            Point3D(45, 45, 0),
                            Point3D(55, 55, 8),
                        ),
                    ),
                    tower_segments=(
                        LineSegment3D(
                            Point3D(tower_x_mm, tower_y_mm, 0),
                            Point3D(tower_x_mm, tower_y_mm, 12),
                        ),
                    ),
                    bed_bounds=BedBounds(0, 100, 0, 100),
                    tower_center_xy_mm=(tower_x_mm, tower_y_mm),
                    source_segment_count=1,
                    displayed_segment_count=1,
                    tower_height_mm=12,
                )
                canvas.set_scene(scene)
                canvas.side_view()

                context = canvas._projection_context()
                object_x = tuple(
                    context.project_raw(point)[0]
                    for segment in scene.object_segments
                    for point in (segment.start, segment.end)
                )
                tower_x = tuple(
                    context.project_raw(point)[0]
                    for segment in scene.tower_segments
                    for point in (segment.start, segment.end)
                )
                self.assertLess(max(object_x), min(tower_x))

    def test_refreshing_preview_preserves_selected_view_pan_fit_and_zoom(self) -> None:
        window = self.window()

        def result(offset: float):
            return SimpleNamespace(
                scene=PreviewScene(
                    object_segments=(
                        LineSegment3D(
                            Point3D(offset, 0, 0),
                            Point3D(offset + 2, 2, 3),
                        ),
                    ),
                    tower_segments=(
                        LineSegment3D(
                            Point3D(offset + 8, 0, 0),
                            Point3D(offset + 9, 1, 10),
                        ),
                    ),
                    bed_bounds=BedBounds(0, 100, 0, 100),
                    tower_center_xy_mm=(offset + 8.5, 0.5),
                    source_segment_count=1,
                    displayed_segment_count=1,
                    tower_height_mm=10,
                ),
                calibrated=False,
                slicer_optimized=False,
                output_mode=SimpleNamespace(value="stl"),
            )

        window.preview_dialog.set_preview(result(0.0))
        canvas = window.preview_dialog.canvas
        canvas.fit_scene()
        canvas.apply_camera_state(
            {
                "yaw_deg": 37.25,
                "pitch_deg": 16.5,
                "zoom": 2.3456789,
                "pan_x": 41.25,
                "pan_y": -19.75,
            }
        )
        state_before = canvas.camera_state()
        self.assertTrue(canvas._fit_whole_bed)

        window.preview_dialog.set_preview(result(3.0))

        self.assertEqual(canvas.camera_state(), state_before)
        self.assertTrue(canvas._fit_whole_bed)
        window.close()

    def test_side_view_handles_diagonal_placement_with_overlapping_xy_bounds(self) -> None:
        canvas = PreviewCanvas()
        scene = PreviewScene(
            object_segments=(
                LineSegment3D(Point3D(0, 0, 0), Point3D(20, 0, 5)),
                LineSegment3D(Point3D(20, 0, 5), Point3D(20, 5, 0)),
                LineSegment3D(Point3D(20, 5, 0), Point3D(0, 5, 5)),
                LineSegment3D(Point3D(0, 5, 5), Point3D(0, 0, 0)),
            ),
            tower_segments=(
                LineSegment3D(Point3D(19, 7, 0), Point3D(22, 4, 8)),
                LineSegment3D(Point3D(22, 4, 8), Point3D(25, 7, 0)),
                LineSegment3D(Point3D(25, 7, 0), Point3D(22, 10, 8)),
                LineSegment3D(Point3D(22, 10, 8), Point3D(19, 7, 0)),
            ),
            bed_bounds=BedBounds(0, 100, 0, 100),
            tower_center_xy_mm=(22, 7),
            source_segment_count=4,
            displayed_segment_count=4,
            tower_height_mm=8,
        )
        canvas.set_scene(scene)
        canvas.side_view()

        self.assertNotIn(canvas.yaw_deg, (0.0, -90.0))
        context = canvas._projection_context()
        object_x = tuple(
            context.project_raw(point)[0]
            for segment in scene.object_segments
            for point in (segment.start, segment.end)
        )
        tower_x = tuple(
            context.project_raw(point)[0]
            for segment in scene.tower_segments
            for point in (segment.start, segment.end)
        )
        self.assertLess(max(object_x), min(tower_x))

    def test_preview_formats_offset_bed_dimensions_in_legend(self) -> None:
        window = self.window()
        scene = PreviewScene(
            object_segments=(
                LineSegment3D(Point3D(0, 0, 0), Point3D(1, 1, 1)),
            ),
            tower_segments=(
                LineSegment3D(Point3D(5, 0, 0), Point3D(6, 1, 10)),
            ),
            bed_bounds=BedBounds(-10, 244.5, 5, 205),
            tower_center_xy_mm=(5.5, 0.5),
            source_segment_count=1,
            displayed_segment_count=1,
            tower_height_mm=10,
        )
        window.preview_dialog.set_preview(
            SimpleNamespace(
                scene=scene,
                calibrated=False,
                slicer_optimized=False,
                output_mode=SimpleNamespace(value="stl"),
            )
        )

        self.assertEqual(
            window.preview_dialog.bed_legend.text(),
            "■ Druckplatte",
        )
        self.assertIn(
            "254,5 x 200 mm",
            window.preview_dialog.bed_info_label.text(),
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
        self.assertFalse(dialog.top_button.isEnabled())
        dialog.canvas.set_scene(PreviewScene(
            object_segments=(LineSegment3D(Point3D(0, 0, 0), Point3D(1, 1, 1)),),
            tower_segments=(LineSegment3D(Point3D(10, 10, 0), Point3D(10, 10, 1)),),
            bed_bounds=BedBounds(0, 100, 0, 100),
            tower_center_xy_mm=(10, 10),
            source_segment_count=1,
            displayed_segment_count=1,
            tower_height_mm=1,
        ))
        dialog.mark_current()
        dialog.top_button.click()

        self.assertEqual(dialog.canvas.yaw_deg, 0.0)
        self.assertEqual(dialog.canvas.pitch_deg, 89.0)
        self.assertAlmostEqual(dialog.canvas.zoom, 1.0 / 1.2)
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
        self.assertEqual(
            german_user_message(
                "No printable layers were detected in the G-code."
            ),
            "Im erzeugten G-Code wurden keine druckbaren Layer erkannt.",
        )
        generic = german_user_message("Unexpected profile validation failed.")
        self.assertNotIn("validation failed", generic.casefold())
        self.assertNotIn("fehlerprotokoll", generic.casefold())
        self.assertIn("nicht vollständig geprüft", generic.casefold())

        window = self.window()
        self.complete_source_step(window)
        window.workflow.slicer_succeeded("Testslicer")
        window.workflow.complete_preparation()
        window.automatic_generation_card.click()
        window.target_time_spin.setValue(0.0)
        self.app.processEvents()
        inline = window._setting_widgets["target_layer_time_s"].message_label.text()
        self.assertNotIn("Gewünschte Mindest-Layerzeit: 0,0 Sek.", inline)
        self.assertIn("Mindestwert 5,0 Sek.", inline)
        self.assertIn("Gewünschte Mindest-Layerzeit: 0,0 Sek.", window.validation_label.text())
        self.assertIn("Mindestwert 5,0 Sek.", window.validation_label.text())
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
            window.source_progress_status_label.alignment()
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
            title.font().pointSizeF() + 5.0,
        )
        self.assertGreater(
            icon.fontMetrics().height(),
            title.fontMetrics().height(),
        )
        window.workflow.begin_source_validation(is_stl=True)
        self.assertTrue(bool(icon.property("prominent")))
        self.assertEqual(icon.width(), 28)
        self.assertGreater(
            icon.fontMetrics().height(),
            title.fontMetrics().height(),
        )
        self.complete_source_step(window)
        self.assertFalse(bool(icon.property("prominent")))
        self.assertEqual(icon.width(), 18)
        window.close()

    def test_tower_settings_remain_open_at_wide_and_narrow_widths(self) -> None:
        window = self.window()
        self.addCleanup(window.close)
        window.resize(1400, 1000)
        window.show()
        self.complete_source_step(window)
        window.workflow.slicer_succeeded("Testslicer")
        window.workflow.complete_preparation()
        window.automatic_generation_card.click()
        self.app.processEvents()
        prediction_height = window.prediction_frame.height()
        for width in (1400, 760):
            window.resize(width, 1000)
            self.app.processEvents()
            window.geometry_settings_group.setChecked(False)
            self.app.processEvents()
            self.assertTrue(window.timing_group.isVisible())
            self.assertTrue(window.geometry_group.isVisible())
            self.assertTrue(window.geometry_settings_group.isChecked())
            self.assertTrue(window.geometry_settings_group.toggle_button.isHidden())
            self.assertTrue(window.prediction_frame.isVisible())
            self.assertTrue(window.prediction_frame.content_widget.isVisible())
            window.geometry_settings_group.setChecked(True)
            self.app.processEvents()
            self.assertTrue(window.timing_group.isVisible())
            self.assertTrue(window.geometry_group.isVisible())
            self.assertFalse(window.local_window_spin.isVisible())
            self.assertTrue(window.target_time_spin.isVisible())
            self.assertIsNone(window.timing_group.graphicsEffect())
            self.assertIsNone(window.prediction_frame.graphicsEffect())


    def test_fixed_geometry_surface_ignores_legacy_collapse_requests(self) -> None:
        window = self.window()
        geometry = window.geometry_settings_group
        body = geometry.content_widget
        geometry.setChecked(False)
        window.resize(1205, 1393)
        window.show()
        self.complete_source_step(window)
        window.workflow.slicer_succeeded("Testslicer")
        window.workflow.complete_preparation()
        window.automatic_generation_card.click()
        QTest.qWait(METRICS.first_success_animation_duration_ms + 100)
        self.app.processEvents()

        self.assertTrue(geometry.isChecked())
        self.assertFalse(body.isHidden())
        self.assertTrue(window.timing_group.isVisible())
        prediction_y = window.prediction_frame.y()
        prediction_height = window.prediction_frame.height()

        geometry.toggle()
        QTest.qWait(METRICS.animation_duration_ms // 2)
        self.app.processEvents()
        self.assertTrue(geometry.isChecked())
        self.assertFalse(body.isHidden())
        self.assertGreater(body.height(), 1)
        self.assertGreater(geometry.height(), geometry.header.height() + 1)
        self.assertTrue(window.timing_group.isVisible())
        self.assertTrue(window.target_time_spin.isVisible())
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
        self.assertFalse(window.local_window_spin.isVisible())
        self.assertTrue(window.geometry_group.isVisible())
        self.assertTrue(window.geometry_calculation_section.isHidden())
        window.close()

    def test_fixed_geometry_surface_is_complete_when_stacked(self) -> None:
        window = self.window()
        geometry = window.geometry_settings_group
        body = geometry.content_widget
        geometry.setChecked(False)
        window.resize(760, 1000)
        window.show()
        self.complete_source_step(window)
        window.workflow.slicer_succeeded("Testslicer")
        window.workflow.complete_preparation()
        window.automatic_generation_card.click()
        QTest.qWait(METRICS.first_success_animation_duration_ms + 100)
        self.app.processEvents()

        geometry.toggle()
        QTest.qWait(METRICS.animation_duration_ms + 50)
        self.app.processEvents()
        self.assertFalse(body.isHidden())
        self.assertGreaterEqual(body.height(), body.sizeHint().height() - 2)
        self.assertFalse(window.local_window_spin.isVisible())
        self.assertTrue(window.geometry_group.isVisible())
        self.assertTrue(window.geometry_calculation_section.isHidden())
        window.close()

    def test_reset_action_is_hidden_until_settings_are_editable(self) -> None:
        window = self.window()
        window.show()
        self.app.processEvents()
        self.assertTrue(window.reset_button.isHidden())

        window.workflow.begin_source_validation(is_stl=True)
        self.assertTrue(window.reset_button.isHidden())
        self.complete_source_step(window)
        self.assertTrue(window.reset_button.isHidden())
        window.workflow.begin_slicer_search()
        self.assertTrue(window.reset_button.isHidden())

        window.workflow.slicer_succeeded("Testslicer")
        window.workflow.complete_preparation()
        window.automatic_generation_card.click()
        self.assertTrue(window.reset_button.isVisible())
        window.workflow.reset()
        self.assertTrue(window.reset_button.isHidden())
        window.workflow.slicer_unavailable("Kein Slicer verfügbar")
        self.assertTrue(window.reset_button.isHidden())
        window.close()

    def test_workflow_uses_immediate_collapse_and_fade_animation(self) -> None:
        workflow_source = (
            SRC_ROOT / "cooling_tower" / "gui" / "workflow_controller.py"
        ).read_text(encoding="utf-8")
        required = (
            "QPropertyAnimation",
            "QParallelAnimationGroup",
            "QGraphicsOpacityEffect",
        )
        for class_name in required:
            self.assertIn(class_name, workflow_source)
        self.assertNotIn("QVariantAnimation", workflow_source)

    def test_invalid_domain_limits_preserve_the_entered_value(self) -> None:
        window = self.window()
        self.complete_source_step(window)
        window.workflow.slicer_succeeded("Testslicer")
        window.workflow.complete_preparation()
        window.automatic_generation_card.click()
        setting = window._setting_widgets["maximum_expansion_angle_deg"]
        window.profile_angle_limit.checkbox.setChecked(False)
        line_edit = window.maximum_expansion_angle_spin.lineEdit()
        line_edit.setText(
            window.maximum_expansion_angle_spin.textFromValue(90.0)
        )
        self.app.processEvents()
        self.assertTrue(bool(window.maximum_expansion_angle_spin.property("invalid")))
        self.assertEqual(
            line_edit.text(),
            window.maximum_expansion_angle_spin.textFromValue(90.0),
        )
        self.assertIn("unvollständig oder ungültig", setting.message_label.text())
        self.assertTrue(setting.secondary_message_label.isHidden())
        self.assertIn("90,0", window.validation_label.text())

        integer_setting = window._setting_widgets["local_reference_window"]
        window.local_window_spin.lineEdit().setText("0")
        self.app.processEvents()
        self.assertEqual(window.local_window_spin.value(), 0)
        self.assertIn("Mindestwert 1", integer_setting.message_label.text())
        window.local_window_spin.lineEdit().setText("1000")
        self.app.processEvents()
        self.assertEqual(window.local_window_spin.value(), 1000)
        self.assertIn("Maximalwert 999", integer_setting.message_label.text())
        window.close()

    def test_footer_explains_causes_without_solution_suggestions(self) -> None:
        window = self.window()
        self.complete_source_step(window)
        window.workflow.slicer_succeeded("Testslicer")
        window.workflow.complete_preparation()
        window.automatic_generation_card.click()
        window.minimum_outer_spin.setValue(30.0)
        window.maximum_outer_spin.setValue(20.0)
        window._last_changed_setting_name = "maximum_outer_diameter_mm"
        window.validate_form()
        self.assertTrue(window.validation_label.text().strip())
        self.assertNotIn("Mögliche Lösungen", window.validation_label.text())
        self.assertFalse(hasattr(window, "error_solutions_toggle"))
        self.assertFalse(hasattr(window, "error_solutions_label"))
        window.close()

    def test_horizontal_expansion_angle_cannot_fall_below_20(self) -> None:
        window = self.window()
        self.complete_source_step(window)
        window.workflow.slicer_succeeded("Testslicer")
        window.workflow.complete_preparation()
        window.automatic_generation_card.click()
        self.assertEqual(
            window.maximum_expansion_angle_spin.property("validationMinimum"),
            20.0,
        )
        window.maximum_expansion_angle_spin.setValue(5.0)
        self.assertEqual(window.maximum_expansion_angle_spin.value(), 20.0)
        self.assertFalse(window.maximum_expansion_angle_spin.property("invalid"))

        invalid = replace(
            GenerationSettings(),
            limit_expansion_to_profile=False,
            maximum_expansion_angle_deg=70.1,
        )
        with self.assertRaisesRegex(ValueError, "Horizontalen.*außerhalb"):
            validate_solid_settings(invalid)

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
        self.assertIn("20°", solutions[0])
        self.assertFalse(any("89,5° erhöhen" in item for item in solutions))
        self.assertNotIn("Layer", group["inline"])
        self.assertNotIn("Lösungen", group["inline"])
        self.assertIn("Betroffen ist 1 Layer", group["summary"])
        self.assertIn(
            "Erforderlich sind höchstens 0,50° zur Horizontalen. Ohne Profilbindung sind mindestens 20,00° zulässig.",
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
        window.prediction_method_label.setText("Slicer-gestützte Schätzung")
        window.preview_state = PreviewState.BUILDING
        actual_has_active = window.background_job_manager.has_active

        def has_active(kind=None):
            return kind is JobKind.PREVIEW or actual_has_active(kind)

        with patch.object(
            window.background_job_manager,
            "has_active",
            side_effect=has_active,
        ):
            window._refresh_phase17_actions()
            window._update_responsive_action_labels()
            self.assertTrue(window.preview_button.isEnabled())
            self.assertEqual(
                window.preview_button.text(),
                "Generierung abbrechen",
            )
        window.close()

    def test_calculation_settings_follow_only_the_geometry_dropdown(self) -> None:
        window = self.window()
        window.resize(1205, 1393)
        window.show()
        self.complete_source_step(window)
        window.workflow.slicer_succeeded("Testslicer")
        window.workflow.complete_preparation()
        window.automatic_generation_card.click()
        QTest.qWait(METRICS.first_success_animation_duration_ms + 100)
        self.app.processEvents()
        geometry = window.geometry_group
        self.assertTrue(geometry.isChecked())
        self.assertTrue(window.maximum_expansion_angle_spin.isVisible())
        geometry.set_expanded(False, animated=True)
        QTest.qWait(METRICS.animation_duration_ms + 40)
        self.app.processEvents()
        self.assertTrue(geometry.content_widget.isHidden())
        self.assertFalse(window.maximum_expansion_angle_spin.isVisible())
        self.assertTrue(window.timing_group.isVisible())
        self.assertTrue(window.geometry_settings_group.isChecked())
        geometry.set_expanded(True, animated=True)
        QTest.qWait(METRICS.animation_duration_ms + 40)
        self.app.processEvents()
        self.assertFalse(geometry.content_widget.isHidden())
        self.assertTrue(window.maximum_expansion_angle_spin.isVisible())
        window.close()

    def test_export_notice_uses_content_height(self) -> None:
        window = self.window()
        window.resize(2000, 900)
        window.show()
        self.app.processEvents()
        self.app.processEvents()
        self.assertTrue(window.footer.isHidden())
        self.assertLessEqual(window.footer.height(), 350)
        self.assertEqual(window.footer.maximumHeight(), window.footer.height())
        self.complete_source_step(window)
        window.workflow.slicer_succeeded("Layoutprüfung")
        window.workflow.complete_preparation()
        window.automatic_generation_card.click()
        self.assertFalse(window.footer.isHidden())
        window.warning_text.setPlainText(
            "Die Sliceroptimierung hat die Zielzeit noch nicht vollständig "
            "erreicht. Bitte die tatsächliche Layerzeit kontrollieren."
        )
        window._refresh_issue_panels()
        self.app.processEvents()
        window.warning_text.fit_to_document()
        self.app.processEvents()
        self.assertLessEqual(window.warning_text.height(), 120)
        self.assertLess(window.notice_panel.height(), 160)

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
        self.assertIs(window.reset_button.parentWidget(), window.footer_reset_host)
        self.assertTrue(window.footer_message_area.isAncestorOf(window.reset_button))
        window.close()

    def test_manual_slicer_prediction_action_is_removed(self) -> None:
        window = self.window()
        self.assertFalse(hasattr(window, "slicer_prediction_button"))
        self.assertFalse(hasattr(window, "prediction_advice_label"))
        self.assertFalse(hasattr(window, "preview_precise_button"))
        self.assertEqual(window.preview_iterations, 18)
        self.assertEqual(window.preview_joint_slices, 12)
        window.close()

    def test_left_drag_rotation_directions_are_inverted(self) -> None:
        canvas = PreviewCanvas()
        canvas.set_navigation_enabled(True)
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

    def test_preview_navigation_is_locked_until_explicitly_enabled(self) -> None:
        canvas = PreviewCanvas()
        scene = PreviewScene(
            object_segments=(
                LineSegment3D(Point3D(0, 0, 0), Point3D(1, 1, 1)),
            ),
            tower_segments=(
                LineSegment3D(Point3D(5, 0, 0), Point3D(6, 1, 8)),
            ),
            bed_bounds=BedBounds(0, 100, 0, 100),
            tower_center_xy_mm=(5.5, 0.5),
            source_segment_count=1,
            displayed_segment_count=1,
            tower_height_mm=8,
        )
        canvas.set_scene(scene)
        ignored: list[bool] = []
        accepted: list[bool] = []
        event = SimpleNamespace(
            angleDelta=lambda: QPoint(0, 120),
            ignore=lambda: ignored.append(True),
            accept=lambda: accepted.append(True),
        )
        initial_zoom = canvas.zoom

        canvas.wheelEvent(event)
        self.assertEqual(canvas.zoom, initial_zoom)
        self.assertTrue(ignored)
        self.assertFalse(canvas.navigation_enabled)
        self.assertFalse(canvas.navigation_toggle.isChecked())
        self.assertIn("aktivieren", canvas.navigation_toggle.accessibleName())
        self.assertEqual(canvas.navigation_toggle.x(), 10)
        self.assertGreater(
            canvas.navigation_status_label.x(),
            canvas.navigation_toggle.geometry().right(),
        )
        self.assertEqual(
            canvas.navigation_status_label.text(),
            "Navigation deaktiviert",
        )
        self.assertEqual(
            canvas.navigation_status_label.property("state"),
            "disabled",
        )

        canvas.navigation_toggle.click()
        canvas.wheelEvent(event)
        self.assertGreater(canvas.zoom, initial_zoom)
        self.assertTrue(accepted)
        self.assertTrue(canvas.navigation_enabled)
        self.assertTrue(canvas.navigation_toggle.isChecked())
        self.assertIn("deaktivieren", canvas.navigation_toggle.accessibleName())
        self.assertEqual(
            canvas.navigation_status_label.text(),
            "Navigation aktiviert",
        )
        self.assertEqual(
            canvas.navigation_status_label.property("state"),
            "enabled",
        )

        canvas.set_scene(scene, preserve_view=True)
        self.assertFalse(canvas.navigation_enabled)
        self.assertFalse(canvas.navigation_toggle.isChecked())
        canvas.close()

    def test_quality_panel_belongs_to_prediction_and_geometry_has_no_body_hover(self) -> None:
        window = self.window()
        self.assertTrue(
            window.prediction_primary_widget.isAncestorOf(
                window.preview_dialog.quality_widget
            )
        )
        self.assertFalse(window.geometry_settings_group.property("bodyHover"))
        window.close()


if __name__ == "__main__":
    unittest.main()
