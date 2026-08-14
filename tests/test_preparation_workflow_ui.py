from __future__ import annotations

import os
import sys
import tempfile
import time
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import PropertyMock, patch


PROJECT_ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = PROJECT_ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("COOLING_TOWER_DISABLE_SLICER_DISCOVERY", "1")

from PySide6.QtCore import Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import (
    QApplication,
    QLabel,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from cooling_tower.gui.main_window import MainWindow
from cooling_tower.gui.widgets import SectionCard, SectionState
from cooling_tower.gui.workflow_controller import WorkflowController, WorkflowStage
from cooling_tower.models import SourceKind


class PreparationWorkflowUiTests(unittest.TestCase):
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
        return MainWindow(
            user_settings_path=self.root / "settings.json",
            enable_update_check=False,
            enable_startup_slicer_discovery=False,
        )

    def mark_valid_source(
        self,
        window: MainWindow,
        name: str = "modell.stl",
    ) -> Path:
        source = (self.root / name).resolve()
        source.write_text("solid x\nendsolid x\n", encoding="ascii")
        window.current_source_path = source
        window.current_source_kind = SourceKind.STL
        window.source_artifact = SimpleNamespace(
            original_path=source,
            matches_current_file=lambda: True,
        )
        window.stl_validation_result = SimpleNamespace(valid=True)
        window._update_preparation_requirements()
        return source

    def test_named_steps_follow_overview_and_start_with_file_transfer(self) -> None:
        window = self.window()
        try:
            self.assertEqual(window.preparation_tabs.count(), 2)
            self.assertEqual(window.preparation_tabs.tabText(0), "1. Dateiübergabe")
            self.assertEqual(
                window.preparation_tabs.tabText(1),
                "2. Slicer-Einstellungen",
            )
            self.assertEqual(window.preparation_tabs.currentIndex(), 0)
            self.assertLess(
                window.workflow_group.content_layout.indexOf(
                    window.preparation_overview_host
                ),
                window.workflow_group.content_layout.indexOf(
                    window.preparation_tabs
                ),
            )
            self.assertFalse(window.workflow_group.property("bodyHover"))
            self.assertFalse(window.workflow_group.isCheckable())
            self.assertTrue(window.workflow_group.isChecked())
            self.assertTrue(window.workflow_group.toggle_button.isHidden())
            window.workflow_group.setChecked(False)
            self.assertTrue(window.workflow_group.isChecked())
            self.assertTrue(window.preparation_tabs.tabBar().isHidden())
            self.assertEqual(len(window.preparation_step_selectors), 2)
            margins = window.preparation_overview.layout().contentsMargins()
            self.assertEqual(
                (margins.left(), margins.top(), margins.right(), margins.bottom()),
                (24, 14, 24, 14),
            )
            self.assertEqual(window.preparation_overview.maximumWidth(), 748)
            self.assertEqual(
                window.preparation_requirements.grid.horizontalSpacing(),
                0,
            )
            self.assertEqual(
                window.preparation_requirements.grid.verticalSpacing(),
                12,
            )
            self.assertTrue(window.preparation_step_selectors[0].isChecked())
            self.assertFalse(window.preparation_step_selectors[1].isChecked())
            self.assertEqual(
                [
                    selector.cursor().shape()
                    for selector in window.preparation_step_selectors
                ],
                [
                    Qt.CursorShape.PointingHandCursor,
                    Qt.CursorShape.ForbiddenCursor,
                ],
            )
            self.assertEqual(window.preparation_progress_bar.value(), 0)
            self.assertEqual(window.preparation_step_connector.text(), "›››")
            self.assertTrue(
                window.preparation_step_selectors[1].property("locked")
            )
            self.assertEqual(
                [label.text() for label in window.preparation_step_selector_titles],
                ["1. Dateiübergabe", "2. Slicer-Einstellungen"],
            )
            self.assertEqual(len(window.preparation_step_shells), 2)
            self.assertTrue(
                all(
                    shell.maximumWidth() == 700
                    for shell in window.preparation_step_shells
                )
            )
            self.assertTrue(window.source_group.property("embeddedStep"))
            self.assertTrue(window.slicer_group.property("embeddedStep"))
            self.assertTrue(window.source_group.header.isHidden())
            self.assertTrue(window.slicer_group.header.isHidden())
            self.assertEqual(window.source_group.title(), "Dateiübergabe")
            self.assertEqual(window.slicer_group.title(), "Slicer-Einstellungen")
        finally:
            window.close()

    def test_step_contents_use_available_width_without_clipping_profile_text(self) -> None:
        window = self.window()
        window.resize(1500, 900)
        window.show()
        self.app.processEvents()
        try:
            self.mark_valid_source(window)
            window.preparation_tabs.setCurrentIndex(1)
            profile_text = (
                "Anycubic Kobra 3 V2 0.4 nozzle – Settings v2"
            )
            window.machine_profile_combo.addItem(profile_text)
            window.machine_profile_combo.setCurrentText(profile_text)
            window._refresh_preparation_section_layout()
            self.app.processEvents()

            self.assertEqual(window.slicer_group.width(), 700)
            self.assertEqual(
                window.preparation_requirements.width(),
                window.slicer_group.width(),
            )
            required_text_width = (
                window.machine_profile_combo.fontMetrics().horizontalAdvance(
                    profile_text
                )
                + 54
            )
            self.assertGreaterEqual(
                window.machine_profile_combo.width(),
                required_text_width,
            )
            self.assertTrue(window.preparation_step_selectors[1].isChecked())
            self.assertFalse(window.preparation_step_selectors[0].isChecked())
            self.assertEqual(
                window.preparation_tabs.property("stepTone"),
                "slicer",
            )
        finally:
            window.close()

    def test_embedded_step_cards_match_bottom_and_side_insets(self) -> None:
        window = self.window()
        window.resize(1200, 900)
        window.show()
        self.app.processEvents()
        try:
            self.mark_valid_source(window)
            for index, card in enumerate(
                (window.source_group, window.slicer_group)
            ):
                window.preparation_tabs.setCurrentIndex(index)
                window._refresh_preparation_section_layout()
                self.app.processEvents()
                margins = card.content_layout.contentsMargins()
                self.assertEqual(
                    (
                        margins.left(),
                        margins.top(),
                        margins.right(),
                        margins.bottom(),
                    ),
                    (20, 20, 20, 20),
                )
                for state in (
                    "analyzing",
                    "failed",
                    "ready",
                ):
                    window.drop_zone.set_analysis_state(state)
                    window._refresh_preparation_section_layout()
                    state_margins = card.content_layout.contentsMargins()
                    self.assertEqual(
                        (
                            state_margins.left(),
                            state_margins.top(),
                            state_margins.right(),
                            state_margins.bottom(),
                        ),
                        (20, 20, 20, 20),
                    )
            selector_margins = (
                window.slicer_selectors_layout.contentsMargins()
            )
            self.assertEqual(
                (
                    selector_margins.left(),
                    selector_margins.top(),
                    selector_margins.right(),
                    selector_margins.bottom(),
                ),
                (0, 0, 0, 0),
            )
            window.preparation_tabs.setCurrentIndex(1)
            window._refresh_preparation_section_layout()
            self.app.processEvents()
            visible_slicer_items = [
                window.slicer_group.content_layout.itemAt(index).widget()
                for index in range(
                    window.slicer_group.content_layout.count()
                )
                if (
                    window.slicer_group.content_layout.itemAt(index).widget()
                    is not None
                    and window.slicer_group.content_layout.itemAt(index)
                    .widget()
                    .isVisibleTo(window)
                )
            ]
            last_bottom = max(
                widget.geometry().bottom()
                for widget in visible_slicer_items
            )
            self.assertEqual(
                window.slicer_group.content_widget.rect().bottom()
                - last_bottom,
                20,
            )
        finally:
            window.close()

    def test_secondary_details_are_compact_and_precede_primary_actions(self) -> None:
        window = self.window()
        try:
            self.assertTrue(
                window.stl_validation_details_toggle.property(
                    "compactDisclosure"
                )
            )
            self.assertLess(
                window.source_group.content_layout.indexOf(
                    window.stl_validation_details_toggle
                ),
                window.source_group.content_layout.indexOf(
                    window.stl_validation_message
                ),
            )
            self.assertTrue(
                window.slicer_analysis_details_toggle.property(
                    "compactDisclosure"
                )
            )
            self.assertLess(
                window.slicer_group.content_layout.indexOf(
                    window.slicer_analysis_details_toggle
                ),
                window.slicer_group.content_layout.indexOf(window.slicer_columns),
            )
            self.assertLess(
                window.slicer_group.content_layout.indexOf(window.slicer_columns),
                window.slicer_group.content_layout.indexOf(
                    window.profile_confirm_button
                ),
            )
        finally:
            window.close()

    def test_step_introductions_are_centered_between_aligned_pills(self) -> None:
        window = self.window()
        window.resize(1200, 900)
        window.show()
        self.app.processEvents()
        try:
            for index, shell in enumerate(window.preparation_step_shells):
                window.preparation_tabs.setCurrentIndex(index)
                self.app.processEvents()
                intro = shell.findChild(QWidget, "preparationStepIntro")
                copy = shell.findChild(QWidget, "preparationStepCopy")
                left = window.preparation_step_left_pills[index]
                right = window.preparation_step_right_pills[index]
                heading = window.preparation_step_heading_labels[index]
                description = copy.findChild(
                    QLabel,
                    "preparationStepDescription",
                )

                self.assertEqual(left.geometry().top(), right.geometry().top())
                self.assertEqual((left.height(), right.height()), (26, 26))
                self.assertLessEqual(
                    abs(copy.geometry().center().x() - intro.rect().center().x()),
                    1,
                )
                self.assertTrue(
                    heading.alignment() & Qt.AlignmentFlag.AlignHCenter
                )
                self.assertTrue(
                    description.alignment() & Qt.AlignmentFlag.AlignHCenter
                )
        finally:
            window.close()

    def test_detail_toggles_remain_visible_and_restore_closed_height(self) -> None:
        window = self.window()
        window.resize(1200, 900)
        window.show()
        self.app.processEvents()
        try:
            self.mark_valid_source(window)
            self.assertIsInstance(window.slicer_analysis_details, QScrollArea)
            self.assertIs(
                window.slicer_analysis_details.widget(),
                window.slicer_analysis_details_content,
            )
            self.assertIs(
                window.slicer_analysis_details.horizontalScrollBarPolicy(),
                Qt.ScrollBarPolicy.ScrollBarAlwaysOff,
            )
            self.assertIs(
                window.slicer_analysis_details.verticalScrollBarPolicy(),
                Qt.ScrollBarPolicy.ScrollBarAsNeeded,
            )
            for toggle in (
                window.stl_validation_details_toggle,
                window.slicer_analysis_details_toggle,
            ):
                self.assertIs(toggle.focusPolicy(), Qt.FocusPolicy.NoFocus)
                self.assertGreaterEqual(toggle.minimumHeight(), 24)

            window.preparation_tabs.setCurrentIndex(1)
            window.slicer_analysis_details_toggle.show()
            window._refresh_preparation_section_layout()
            self.app.processEvents()
            slicer_closed_height = window.preparation_tabs.height()
            window.slicer_analysis_details_toggle.click()
            self.app.processEvents()
            self.app.processEvents()
            self.assertTrue(window.slicer_analysis_details.isVisibleTo(window))
            self.assertGreaterEqual(
                window.slicer_analysis_details_toggle.height(),
                24,
            )
            self.assertFalse(window.slicer_analysis_details_toggle.hasFocus())
            self.assertGreater(
                window.preparation_tabs.height(),
                slicer_closed_height,
            )
            window.slicer_analysis_details_toggle.click()
            self.app.processEvents()
            self.app.processEvents()
            self.assertTrue(window.slicer_analysis_details.isHidden())
            self.assertEqual(
                window.preparation_tabs.height(),
                slicer_closed_height,
            )

            window.preparation_tabs.setCurrentIndex(0)
            window.stl_validation_details.setPlainText("A\nB\nC")
            window.stl_validation_details_toggle.show()
            window._refresh_preparation_section_layout()
            self.app.processEvents()
            stl_closed_height = window.preparation_tabs.height()
            window.stl_validation_details_toggle.click()
            self.app.processEvents()
            self.assertTrue(window.stl_validation_details.isVisibleTo(window))
            self.assertGreater(window.preparation_tabs.height(), stl_closed_height)
            window.stl_validation_details_toggle.click()
            self.app.processEvents()
            self.app.processEvents()
            self.assertTrue(window.stl_validation_details.isHidden())
            self.assertEqual(
                window.preparation_tabs.height(),
                stl_closed_height,
            )
            stylesheet = window.styleSheet()
            self.assertIn(
                'QPushButton[compactDisclosure="true"]:focus',
                stylesheet,
            )
            self.assertIn(
                "QScrollArea#slicerAnalysisDetails QLabel",
                stylesheet,
            )
            self.assertIn("QTextEdit#stlValidationDetails", stylesheet)
        finally:
            window.close()

    def test_preparation_header_lead_icon_is_larger_than_title_text(self) -> None:
        window = self.window()
        window.show()
        self.app.processEvents()
        try:
            icon = window.workflow_group.status_icon
            title = window.workflow_group.title_label
            self.assertTrue(icon.property("headerLead"))
            self.assertEqual((icon.width(), icon.height()), (45, 40))
            self.assertGreaterEqual(
                icon.font().pointSizeF(),
                title.font().pointSizeF(),
            )
            window.workflow_group.set_state(SectionState.ERROR)
            self.assertEqual((icon.width(), icon.height()), (45, 40))
        finally:
            window.close()

    def test_step_heads_share_colours_and_page_surface_stays_connected(self) -> None:
        window = self.window()
        window.resize(1200, 900)
        window.show()
        self.app.processEvents()
        try:
            stylesheet = window.styleSheet()
            active_rule = stylesheet.split(
                'QPushButton#preparationStepSelector[stepTone="source"]'
                '[active="true"] {',
                1,
            )[1].split("}", 1)[0]
            self.assertIn("background: qlineargradient(", active_rule)
            self.assertIn("stop: 0 #eef7fc", active_rule)
            self.assertIn("stop: 1 #cfe3ef", active_rule)
            self.assertIn("color: #40576a;", active_rule)
            self.assertIn(
                'QWidget#preparationStepPage[stepTone="source"],',
                stylesheet,
            )
            preparation_body_rule = stylesheet.split(
                'QFrame#sectionCard[outerDropdown="true"]'
                '[role="preparation"] > QFrame#sectionCardBody {',
                1,
            )[1].split("}", 1)[0]
            self.assertIn("stop: 0 #e7f1f7", preparation_body_rule)
            overview_rule = stylesheet.split(
                "QWidget#preparationOverview,",
                1,
            )[1].split("}", 1)[0]
            self.assertIn("background: transparent;", overview_rule)
            page_rule = stylesheet.split(
                'QWidget#preparationStepPage[stepTone="source"],',
                1,
            )[1].split("}", 1)[0]
            self.assertIn("background: transparent;", page_rule)
            for tone in ("source", "slicer"):
                pane_rule = stylesheet.split(
                    f'QTabWidget#preparationSteps[stepTone="{tone}"]::pane {{',
                    1,
                )[1].split("}", 1)[0]
                self.assertIn("background: transparent;", pane_rule)
                self.assertIn("border: none;", pane_rule)
                self.assertIn("border-top: 2px solid #7fb8d8;", pane_rule)

            selector_rule = stylesheet.split(
                "QPushButton#preparationStepSelector {",
                1,
            )[1].split("}", 1)[0]
            self.assertIn("border: 1px solid #76a2be;", selector_rule)
            self.assertIn("border-top-left-radius: 8px;", selector_rule)
            self.assertIn("border-top-right-radius: 8px;", selector_rule)
            self.assertIn("border-bottom-left-radius: 0;", selector_rule)
            self.assertIn("border-bottom-right-radius: 0;", selector_rule)

            self.mark_valid_source(window)
            source, slicer = window.preparation_step_selectors
            source_image = source.grab().toImage()
            slicer_image = slicer.grab().toImage()
            for y in (8, source.height() - 8):
                self.assertEqual(
                    source_image.pixelColor(6, y),
                    slicer_image.pixelColor(6, y),
                )
            slicer.click()
            self.app.processEvents()
            source_image = source.grab().toImage()
            slicer_image = slicer.grab().toImage()
            for y in (8, source.height() - 8):
                self.assertEqual(
                    source_image.pixelColor(6, y),
                    slicer_image.pixelColor(6, y),
                )
        finally:
            window.close()

    def test_general_progress_replaces_separate_step_fills(self) -> None:
        window = self.window()
        window.resize(1200, 900)
        window.show()
        self.app.processEvents()
        try:
            selector = window.preparation_step_selectors[0]
            title = window.preparation_step_selector_titles[0]
            selector.set_progress_value(50)
            self.app.processEvents()
            self.assertTrue(selector.progress_label.isHidden())
            self.assertTrue(
                window.preparation_step_selectors[1].progress_label.isHidden()
            )
            self.assertEqual(window.preparation_progress_bar.value(), 0)
            self.assertEqual(
                title.palette().color(title.foregroundRole()).name(),
                "#40576a",
            )

            self.mark_valid_source(window)
            self.app.processEvents()
            self.assertEqual(window.preparation_progress_bar.value(), 50)
            self.assertEqual(window.preparation_step_connector.text(), "›››")
            self.assertFalse(
                window.preparation_step_selectors[1].property("locked")
            )
        finally:
            window.close()

    def test_step_progress_values_do_not_overpaint_navigation_outline(self) -> None:
        window = self.window()
        window.resize(1200, 900)
        window.show()
        self.app.processEvents()
        try:
            self.mark_valid_source(window)
            for selector in window.preparation_step_selectors:
                for progress in (1, 50, 100):
                    selector.set_progress_value(progress)
                    self.app.processEvents()
                    image = selector.grab().toImage()
                    self.assertEqual(image.pixelColor(8, 0).name(), "#76a2be")
                    self.assertEqual(image.pixelColor(0, 8).name(), "#76a2be")
                    self.assertEqual(
                        image.pixelColor(0, selector.height() - 8).name(),
                        "#76a2be",
                    )
                    corner = image.pixelColor(2, 2)
                    self.assertLess(corner.blue(), 245)

                window._set_preparation_step_hovered(
                    window.preparation_step_selectors.index(selector),
                    True,
                )
                self.app.processEvents()
                hovered = selector.grab().toImage()
                self.assertEqual(hovered.pixelColor(8, 0).name(), "#6198b9")
                self.assertEqual(hovered.pixelColor(0, 8).name(), "#6198b9")
                window._set_preparation_step_hovered(
                    window.preparation_step_selectors.index(selector),
                    False,
                )
        finally:
            window.close()

    def test_embedded_step_cards_are_framed_against_tinted_workspace(self) -> None:
        window = self.window()
        try:
            stylesheet = window.styleSheet()
            for tone in ("source", "slicer"):
                card_rule = stylesheet.split(
                    f'QFrame#sectionCard[embeddedStep="true"][stepTone="{tone}"] {{',
                    1,
                )[1].split("}", 1)[0]
                body_rule = stylesheet.split(
                    f'QFrame#sectionCard[embeddedStep="true"][stepTone="{tone}"] '
                    "> QFrame#sectionCardBody {",
                    1,
                )[1].split("}", 1)[0]
                self.assertIn("background: #ffffff;", card_rule)
                self.assertIn("border: 1px solid #c4d6e2;", card_rule)
                self.assertIn("border-radius: 10px;", card_rule)
                self.assertIn("background: #ffffff;", body_rule)
                self.assertIn("border-radius: 10px;", body_rule)

            stl_drop_zone_rule = stylesheet.split(
                "QFrame#sourceDropZone {",
                1,
            )[1].split("}", 1)[0]
            self.assertIn("background: #f6fafd;", stl_drop_zone_rule)
            self.assertIn("border: 2px dashed #2f6690;", stl_drop_zone_rule)

            slicer_combo_rule = stylesheet.split(
                'QWidget#slicerSelectorColumn QComboBox[important="true"] {',
                1,
            )[1].split("}", 1)[0]
            self.assertIn("color: #123f63;", slicer_combo_rule)
            self.assertIn("background: #eef6fb;", slicer_combo_rule)
            self.assertIn("border-color: #9fc7e5;", slicer_combo_rule)
        finally:
            window.close()

    def test_integrated_file_step_badge_reflects_validation_failure(self) -> None:
        window = self.window()
        try:
            window.current_source_path = self.root / "fehlerhaft.stl"
            window.stl_validation_result = SimpleNamespace(valid=False)
            window._update_preparation_requirements()

            badge = window.preparation_step_state_labels[0]
            self.assertEqual(badge.text(), "Prüfung fehlgeschlagen")
            self.assertEqual(badge.property("state"), "error")
            self.assertFalse(window.source_group.header.isVisible())
        finally:
            window.close()

    def test_invalid_stl_keeps_file_step_blocks_separate(self) -> None:
        window = self.window()
        window.resize(1342, 1308)
        window.show()
        self.app.processEvents()
        source = (self.root / "fehlerhaft.stl").resolve()
        source.write_text("solid bad\nendsolid bad\n", encoding="ascii")
        artifact = SimpleNamespace(original_path=source)
        try:
            window.current_source_path = source
            window.current_source_kind = SourceKind.STL
            window._stl_validation_request_id = 3
            window.drop_zone._selected_path = source
            window.drop_zone._selected_kind = SourceKind.STL
            window.drop_zone.setProperty("loaded", True)
            window.workflow.begin_source_validation(is_stl=True)
            window._on_stl_validation_succeeded(
                3,
                SimpleNamespace(
                    valid=False,
                    source_artifact=artifact,
                    technical_summary="Nicht manifold",
                ),
            )
            for _ in range(6):
                self.app.processEvents()

            drop_zone = window.drop_zone
            self.assertGreaterEqual(
                drop_zone.height(),
                drop_zone.minimumHeight(),
            )
            self.assertGreaterEqual(
                drop_zone.info_widget.height(),
                drop_zone.info_widget.minimumSizeHint().height(),
            )
            self.assertTrue(drop_zone.prompt_label.isHidden())
            internal_blocks = (
                drop_zone.info_widget,
                drop_zone.actions_widget,
            )
            for upper, lower in zip(internal_blocks, internal_blocks[1:]):
                self.assertLess(upper.geometry().bottom(), lower.geometry().top())

            source_blocks = (
                drop_zone,
                window.stl_validation_details_toggle,
                window.stl_validation_message,
            )
            for upper, lower in zip(source_blocks, source_blocks[1:]):
                self.assertLess(upper.geometry().bottom(), lower.geometry().top())
            self.assertLessEqual(
                window.stl_validation_message.geometry().bottom(),
                window.source_group.content_widget.rect().bottom()
                - window.source_group.content_layout.contentsMargins().bottom(),
            )
        finally:
            window.close()

    def test_requirements_live_inside_persistent_coloured_step_containers(self) -> None:
        window = self.window()
        window.show()
        self.app.processEvents()
        try:
            source_selector, slicer_selector = window.preparation_step_selectors
            self.assertIs(
                window.preparation_source_requirements.parentWidget(),
                window.preparation_step_selector_containers[0],
            )
            self.assertIs(
                window.preparation_slicer_requirements.parentWidget(),
                window.preparation_step_selector_containers[1],
            )
            self.assertEqual(source_selector.property("stepTone"), "source")
            self.assertEqual(slicer_selector.property("stepTone"), "slicer")
            self.assertLess(
                window.preparation_step_selector_containers[0]
                .layout()
                .indexOf(source_selector),
                window.preparation_step_selector_containers[0]
                .layout()
                .indexOf(
                    window.preparation_source_requirements
                ),
            )
            self.assertEqual(
                window.preparation_overview.layout().indexOf(
                    window.preparation_requirements
                ),
                2,
            )
            self.assertTrue(source_selector.isVisibleTo(window))
            self.assertTrue(slicer_selector.isVisibleTo(window))

            self.mark_valid_source(window)
            slicer_selector.click()
            self.app.processEvents()
            self.assertEqual(window.preparation_tabs.currentIndex(), 1)
            self.assertEqual(window.preparation_tabs.property("stepTone"), "slicer")
            self.assertTrue(source_selector.isVisibleTo(window))
            self.assertTrue(slicer_selector.isVisibleTo(window))
            stylesheet = window.styleSheet()
            self.assertIn(
                'QPushButton#preparationStepSelector[stepTone="source"]',
                stylesheet,
            )
            self.assertIn(
                'QPushButton#preparationStepSelector[stepTone="slicer"]',
                stylesheet,
            )
            self.assertIn(
                'QWidget#preparationStepPage[stepTone="source"]',
                stylesheet,
            )
            self.assertIn(
                'QWidget#preparationStepPage[stepTone="slicer"]',
                stylesheet,
            )
        finally:
            window.close()

    def test_missing_requirements_remain_static(self) -> None:
        window = self.window()
        try:
            _icon, label = window.preparation_requirement_rows[
                "source_selected"
            ]
            self.assertIsNone(label.graphicsEffect())
            self.assertFalse(hasattr(label, "attention_animation"))

            self.mark_valid_source(window)
            self.assertIsNone(label.graphicsEffect())
            self.assertFalse(hasattr(label, "attention_animation"))
        finally:
            window.close()

    def test_incomplete_preparation_fills_viewport_and_scrolls_only_on_overflow(
        self,
    ) -> None:
        window = self.window()
        window.resize(1530, 1393)
        window.show()
        for _ in range(6):
            self.app.processEvents()
        try:
            self.assertEqual(
                window.settings_scroll.verticalScrollBarPolicy(),
                Qt.ScrollBarPolicy.ScrollBarAsNeeded,
            )
            self.assertEqual(
                window.settings_scroll.verticalScrollBar().maximum(),
                0,
            )
            self.assertFalse(
                window.settings_scroll.verticalScrollBar().isVisible()
            )
            margins = window.content_layout.contentsMargins()
            self.assertEqual(margins.bottom(), margins.left())
            self.assertEqual(margins.bottom(), margins.right())
            self.assertEqual(
                window.settings_content.height()
                - window.workflow_group.geometry().bottom()
                - 1,
                margins.bottom(),
            )
            progress_header = window.preparation_progress_header.geometry()
            progress_bar = window.preparation_progress_bar.geometry()
            requirements = window.preparation_requirements.geometry()
            self.assertLessEqual(progress_header.top(), 16)
            self.assertLessEqual(
                progress_bar.top() - progress_header.bottom() - 1,
                10,
            )
            self.assertLessEqual(
                requirements.top() - progress_bar.bottom() - 1,
                10,
            )
            self.assertEqual(
                window.preparation_tabs.geometry().top(),
                window.preparation_overview_host.geometry().bottom() + 1,
            )
            self.assertGreater(
                window.workflow_group.content_widget.height()
                - window.preparation_tabs.geometry().bottom(),
                100,
            )

            # The taller Slicer step still fits at this height. A shrinking
            # decorative bottom margin must not create a premature scrollbar.
            self.mark_valid_source(window)
            window.preparation_tabs.setCurrentIndex(1)
            window.resize(1400, 1120)
            for _ in range(6):
                self.app.processEvents()
            self.assertFalse(
                window.settings_scroll.verticalScrollBar().isVisible()
            )
            slicer_bottom = window.slicer_group.mapTo(
                window.settings_content,
                window.slicer_group.rect().bottomLeft(),
            ).y()
            self.assertLess(
                slicer_bottom,
                window.settings_scroll.viewport().height(),
            )

            window.resize(760, 600)
            for _ in range(6):
                self.app.processEvents()
            self.assertGreater(
                window.settings_scroll.verticalScrollBar().maximum(),
                0,
            )
            self.assertTrue(
                window.settings_scroll.verticalScrollBar().isVisible()
            )
        finally:
            window.close()

    def test_confirmed_profiles_offer_analysis_after_later_stl_upload(self) -> None:
        window = self.window()
        source = (self.root / "modell.stl").resolve()
        source.write_text("solid x\nendsolid x\n", encoding="ascii")
        artifact = SimpleNamespace(original_path=source)
        result = SimpleNamespace(
            valid=True,
            source_artifact=artifact,
            face_count=4,
            component_count=1,
            warning_issues=(),
            technical_summary="STL gültig",
        )
        installation = SimpleNamespace(
            verified=True,
            can_slice=True,
            identity_key="testslicer",
            display_name="Testslicer",
        )
        window.current_source_path = source
        window.current_source_kind = SourceKind.STL
        window._stl_validation_request_id = 7
        window.profile_catalog = SimpleNamespace(
            complete=True,
            execution_slicer=SimpleNamespace(identity_key="testslicer"),
        )
        try:
            with (
                patch.object(
                    type(window),
                    "selected_slicer_installation",
                    new_callable=PropertyMock,
                    return_value=installation,
                ),
                patch.object(
                    window,
                    "_catalog_selection_is_confirmed",
                    return_value=True,
                ),
                patch.object(
                    window,
                    "_profile_matching_context",
                    return_value=object(),
                ),
                patch.object(window, "start_profile_matching") as start_match,
            ):
                window._on_stl_validation_succeeded(7, result)

                self.assertFalse(window.profile_confirm_button.isHidden())
                self.assertTrue(window.profile_confirm_button.isEnabled())
                self.assertEqual(
                    window.profile_confirm_button.text(),
                    "Modell bestätigen und mit Profilen analysieren",
                )
                window.profile_confirm_button.click()
                start_match.assert_called_once_with()
                self.assertFalse(window.profile_confirm_button.isEnabled())
                self.assertEqual(
                    window.profile_confirm_button.text(),
                    "Modellanalyse wird vorbereitet …",
                )
        finally:
            window.close()

    def test_completed_steps_use_tab_checks_without_green_content_badges(self) -> None:
        window = self.window()
        window.current_source_path = self.root / "modell.stl"
        window.current_source_kind = SourceKind.STL
        window.stl_validation_result = SimpleNamespace(valid=True)
        window.source_artifact = object()
        installation = SimpleNamespace(
            verified=True,
            identity_key="testslicer",
            display_name="Testslicer 1.0",
        )
        window.profile_catalog = SimpleNamespace(
            complete=True,
            execution_slicer=SimpleNamespace(identity_key="testslicer"),
        )
        window.profile_match_result = SimpleNamespace(user_confirmed=True)
        window.confirmed_profile_context = SimpleNamespace(
            matches_source=lambda _source: True
        )
        window.analysis_snapshot = object()
        window.source_preslice_result = SimpleNamespace(cleanup=lambda: None)
        window.prepared_analysis_source = object()
        try:
            with (
                patch.object(
                    type(window),
                    "selected_slicer_installation",
                    new_callable=PropertyMock,
                    return_value=installation,
                ),
                patch.object(
                    window,
                    "_catalog_selection_is_confirmed",
                    return_value=True,
                ),
            ):
                window._update_preparation_requirements()

                self.assertTrue(window.workflow_group.isCheckable())
                self.assertEqual(
                    [
                        icon.text()
                        for icon in window.preparation_step_selector_icons
                    ],
                    ["✓", "✓"],
                )
                self.assertTrue(
                    all(
                        badge.isHidden()
                        for badge in window.preparation_step_state_labels
                    )
                )
                self.assertEqual(
                    [
                        page.property("stepTone")
                        for page in window.preparation_tab_pages
                    ],
                    ["source", "slicer"],
                )
                window.workflow_group.setChecked(False)
                self.assertFalse(window.workflow_group.isChecked())
                window.analysis_snapshot = None
                window._update_preparation_requirements()
                self.assertFalse(window.workflow_group.isCheckable())
                self.assertTrue(window.workflow_group.isChecked())
                self.assertTrue(window.workflow_group.toggle_button.isHidden())
        finally:
            window.close()

    def test_source_success_opens_slicer_with_500_ms_transition(self) -> None:
        window = self.window()
        source = self.mark_valid_source(window)
        window._stl_validation_request_id = 7
        try:
            window.workflow.source_validation_succeeded(
                "modell.stl · Geometrie gültig",
                analysis_complete=False,
            )
            self.assertIs(window.source_group.state(), SectionState.SUCCESS)
            self.assertEqual(window.preparation_tabs.currentIndex(), 0)
            window._schedule_slicer_step_open(7, source)
            self.app.processEvents()
            self.assertEqual(window.preparation_tabs.currentIndex(), 1)
            self.assertEqual(
                window.preparation_tabs.last_transition,
                (0, 1, 500),
            )
        finally:
            window.close()

    def test_locked_forward_step_relocks_after_invalid_replacement(self) -> None:
        window = self.window()
        try:
            window.preparation_tabs.setCurrentIndex(1)
            self.assertEqual(window.preparation_tabs.currentIndex(), 0)
            self.assertEqual(window.preparation_tabs.last_blocked_index, 1)

            self.mark_valid_source(window, "erste.stl")
            window.preparation_tabs.setCurrentIndex(1)
            self.assertEqual(window.preparation_tabs.currentIndex(), 1)
            window.preparation_tabs.setCurrentIndex(0)
            self.assertEqual(window.preparation_tabs.currentIndex(), 0)

            replacement = (self.root / "ungueltig.stl").resolve()
            replacement.write_text("keine stl", encoding="utf-8")
            window.current_source_path = replacement
            window.current_source_kind = SourceKind.STL
            window.source_artifact = None
            window.stl_validation_result = SimpleNamespace(valid=False)
            window._update_preparation_requirements()

            self.assertTrue(
                window.preparation_step_selectors[1].property("locked")
            )
            self.assertEqual(window.preparation_progress_bar.value(), 25)
            window.preparation_tabs.setCurrentIndex(1)
            self.assertEqual(window.preparation_tabs.currentIndex(), 0)
        finally:
            window.close()

    def test_each_direction_change_starts_a_fresh_card_animation(self) -> None:
        window = self.window()
        window.resize(1200, 900)
        window.show()
        self.app.processEvents()
        transitions: list[tuple[int, int, int]] = []
        window.preparation_tabs.transition_started.connect(
            lambda old, new, duration: transitions.append(
                (old, new, duration)
            )
        )
        # Keep this offscreen regression fast while retaining the production
        # duration published by every transition.
        window.preparation_tabs._effective_transition_duration_ms = 30
        try:
            self.mark_valid_source(window)
            window.preparation_tabs.setCurrentIndex(1)
            self.app.processEvents()
            self.assertEqual(window.preparation_tabs.currentIndex(), 0)
            self.assertIsNotNone(
                window.preparation_tabs._transition_animation
            )
            self.assertIsNotNone(
                window.preparation_tabs._transition_viewport
            )
            self.assertEqual(
                window.preparation_tabs._transition_viewport.width(),
                window.source_group.width(),
            )
            self.assertEqual(
                window.preparation_tabs._transition_animation.duration(),
                30,
            )
            QTest.qWait(50)
            self.app.processEvents()
            self.assertEqual(window.preparation_tabs.currentIndex(), 1)

            window.preparation_tabs.setCurrentIndex(0)
            QTest.qWait(50)
            self.app.processEvents()
            window.preparation_tabs.setCurrentIndex(1)
            self.app.processEvents()

            self.assertEqual(
                transitions,
                [
                    (0, 1, 500),
                    (1, 0, 500),
                    (0, 1, 500),
                ],
            )
        finally:
            window.close()

    def test_background_slicer_error_is_deferred_until_step_two(self) -> None:
        window = self.window()
        try:
            self.mark_valid_source(window)
            window.workflow.begin_source_validation(is_stl=True)
            window.workflow.required_slicer_unavailable("Slicer fehlt")
            self.assertEqual(window.preparation_tabs.currentIndex(), 0)
            self.assertIs(window.workflow_group.state(), SectionState.ACTIVE)
            self.assertIs(window.slicer_group.state(), SectionState.ERROR)
            window.preparation_tabs.setCurrentIndex(1)
            self.app.processEvents()
            self.assertIs(window.workflow_group.state(), SectionState.ERROR)
            self.assertIs(window.workflow.stage, WorkflowStage.ERROR)
        finally:
            window.close()

    def test_requirements_are_reassigned_to_stl_and_slicer_steps(self) -> None:
        window = self.window()
        try:
            self.assertEqual(
                set(window.preparation_requirement_rows),
                {
                    "source_selected",
                    "source_validated",
                    "slicer_detected",
                    "profiles_loaded",
                    "profiles_confirmed",
                    "model_analyzed",
                },
            )
            source_keys = {"source_selected", "source_validated"}
            slicer_keys = set(window.preparation_requirement_rows) - source_keys
            self.assertTrue(
                all(
                    window.preparation_requirement_rows[key][0].parent()
                    is window.preparation_source_requirements
                    for key in source_keys
                )
            )
            self.assertTrue(
                all(
                    window.preparation_requirement_rows[key][0].parent()
                    is window.preparation_slicer_requirements
                    for key in slicer_keys
                )
            )
        finally:
            window.close()

    def test_double_success_collapses_preparation_before_revealing_settings(self) -> None:
        window = self.window()
        window.show()
        self.app.processEvents()
        try:
            window.workflow.set_slicer_step_visible(True)
            window.workflow.source_validation_succeeded(
                "modell.stl · Geometrie gültig",
                analysis_complete=True,
            )
            window.workflow.slicer_succeeded("Testslicer")
            self.app.processEvents()
            self.assertIs(window.workflow.stage, WorkflowStage.READY)
            self.assertIs(window.workflow_group.state(), SectionState.SUCCESS)
            self.assertFalse(window.workflow_group.isChecked())
            self.assertFalse(window.ready_grid.isHidden())
        finally:
            window.close()

    def test_immediate_collapse_starts_the_settings_fade(self) -> None:
        host = QWidget()
        layout = QVBoxLayout(host)
        preparation = SectionCard(
            "Datei und Slicer vorbereiten",
            collapsible=True,
            expanded=True,
        )
        source = SectionCard("Dateiübergabe", collapsible=False)
        slicer = SectionCard("Slicer-Einstellungen", collapsible=False)
        preparation.content_layout.addWidget(source)
        preparation.content_layout.addWidget(slicer)
        settings = QLabel("Kühlturm-Einstellungen")
        layout.addWidget(preparation)
        layout.addWidget(settings)
        controller = WorkflowController(
            source_card=source,
            slicer_card=slicer,
            workflow_card=preparation,
            downstream_widgets=(settings,),
            parent=host,
            duration_ms=500,
            first_success_duration_ms=1000,
        )
        controller.reset()
        host.resize(800, 700)
        host.show()
        self.app.processEvents()
        try:
            controller.set_slicer_step_visible(True)
            controller.source_validation_succeeded(
                "modell.stl geprüft",
                analysis_complete=True,
            )
            controller.slicer_succeeded("Testslicer")

            self.assertIs(preparation.state(), SectionState.SUCCESS)
            self.assertFalse(preparation.isChecked())
            self.assertFalse(settings.isHidden())
            effect = settings.graphicsEffect()
            self.assertIsNotNone(effect)
            self.assertLess(effect.opacity(), 1.0)

            deadline = time.monotonic() + 2
            while (
                settings.graphicsEffect() is not None
                and time.monotonic() < deadline
            ):
                self.app.processEvents()
                QTest.qWait(10)
            self.assertIsNone(settings.graphicsEffect())
            self.assertIs(controller.stage, WorkflowStage.READY)
        finally:
            host.close()


if __name__ == "__main__":
    unittest.main()
