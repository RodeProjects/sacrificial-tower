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

from PySide6.QtCore import QEvent, QPoint, QPointF, Qt
from PySide6.QtGui import QEnterEvent, QHelpEvent, QPalette
from PySide6.QtTest import QTest
from PySide6.QtWidgets import (
    QApplication,
    QLabel,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from cooling_tower.gui.background_jobs import JobKind
from cooling_tower.gui.main_window import MainWindow
from cooling_tower.gui.widgets import SectionCard, SectionState
from cooling_tower.gui.workflow_controller import WorkflowController, WorkflowStage
from cooling_tower.models import SourceKind
from gui_lifecycle import dispose_test_widget
from cooling_tower.slicers import (
    ProfileCatalog,
    ProfileKind,
    ProfileMatchState,
    ProfileRecord,
    ProfileSelectionReference,
)


class PreparationWorkflowUiTests(unittest.TestCase):
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
        window = MainWindow(
            user_settings_path=self.root / "settings.json",
            enable_update_check=False,
            enable_startup_slicer_discovery=False,
        )
        self.addCleanup(dispose_test_widget, window)
        return window

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
            source_kind=SourceKind.STL,
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
                (24, 14, 24, 0),
            )
            self.assertEqual(window.preparation_overview.maximumWidth(), 748)
            self.assertEqual(
                window.preparation_requirements.grid.horizontalSpacing(),
                0,
            )
            self.assertEqual(
                window.preparation_requirements.grid.verticalSpacing(),
                0,
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
            self.assertTrue(window.preparation_step_connector.isHidden())
            self.assertTrue(
                window.preparation_step_selectors[1].property("locked")
            )
            self.assertTrue(window.preparation_back_button.isHidden())
            self.assertEqual(
                window.preparation_navigation_title_label.text(),
                "Dateiübergabe",
            )
            self.assertEqual(window.preparation_next_button.text(), "Weiter 🔒")
            self.assertFalse(window.preparation_next_button.isEnabled())
            self.assertIn(
                "gültigen STL",
                window.preparation_next_button.toolTip(),
            )
            self.assertEqual(
                window.preparation_next_button.toolTip(),
                window.preparation_step_selectors[1].toolTip(),
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

    def test_locked_step_and_disabled_continue_use_same_bounded_tooltip(self) -> None:
        window = self.window()
        window.show()
        self.app.processEvents()
        try:
            selector = window.preparation_step_selectors[1]
            button = window.preparation_next_button
            self.assertFalse(button.isEnabled())
            self.assertEqual(selector.toolTip(), button.toolTip())

            for target in (selector, button):
                local = target.rect().center()
                event = QHelpEvent(
                    QEvent.Type.ToolTip,
                    local,
                    target.mapToGlobal(local),
                )
                QApplication.sendEvent(target, event)
                self.app.processEvents()
                popover = getattr(window, "_bounded_hint_popover")
                self.assertEqual(popover.objectName(), "hintPopover")
                self.assertEqual(popover.label.text(), selector.toolTip())
                self.assertFalse(popover.isHidden())
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
                window.stl_validation_feedback.grid.indexOf(
                    window.stl_validation_details_toggle
                ),
                window.stl_validation_feedback.grid.indexOf(
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
                window.slicer_selectors_layout.indexOf(
                    window.show_all_profiles_row
                ),
                window.slicer_selectors_layout.indexOf(
                    window.profile_confirmation_stack
                ),
            )
        finally:
            window.close()

    def test_preslice_activity_reuses_confirmation_slot_without_reflow(self) -> None:
        window = self.window()
        window.resize(1200, 1000)
        window.show()
        self.mark_valid_source(window)
        window.preparation_tabs.setCurrentIndex(1)
        self.app.processEvents()
        try:
            self.assertTrue(window.slicer_status_label.isHidden())
            self.assertTrue(window.slicer_analysis_details_toggle.isHidden())
            self.assertIs(
                window.profile_confirmation_stack.currentWidget(),
                window.profile_confirm_button,
            )
            self.assertEqual(
                window.profile_confirm_button.height(),
                window.profile_confirmation_stack.height(),
            )
            self.assertEqual(
                window.profile_confirm_button.sizeHint().height(),
                window.profile_confirmation_stack.height(),
            )
            height_before = window.preparation_tabs.height()
            stack_geometry_before = window.profile_confirmation_stack.geometry()

            window._set_preslice_activity(
                True,
                "Preslice läuft · Modell wird analysiert …",
                percent=37,
            )
            for _ in range(3):
                self.app.processEvents()
            self.assertIs(
                window.profile_confirmation_stack.currentWidget(),
                window.profile_confirmation_progress,
            )
            self.assertEqual(window.profile_confirmation_progress.minimum(), 0)
            self.assertEqual(window.profile_confirmation_progress.maximum(), 100)
            self.assertEqual(window.profile_confirmation_progress.value(), 37)
            self.assertEqual(
                window.profile_confirmation_progress.format(),
                "Slicer und Profile bestätigt, Pre-Slice wird "
                "durchgeführt... (%p%)",
            )
            self.assertFalse(window.profile_confirmation_progress.isTextVisible())
            self.assertEqual(
                window.profile_confirmation_progress.text_label.text(),
                "Slicer und Profile bestätigt, Pre-Slice wird "
                "durchgeführt... (37%)",
            )
            self.assertIn(
                window.profile_confirmation_progress.activity_label.text(),
                "◐◓◑◒",
            )
            progress_text = window.profile_confirmation_progress.text_label
            text_height = progress_text.fontMetrics().tightBoundingRect(progress_text.text()).height()
            self.assertEqual(
                window.profile_confirmation_progress.activity_label.text_height(),
                text_height,
            )
            self.assertTrue(window.slicer_progress_bar.isHidden())
            stylesheet = window.styleSheet()
            progress_rule = stylesheet.split(
                "QProgressBar#profileConfirmationProgress {",
                1,
            )[1].split("}", 1)[0]
            progress_chunk_rule = stylesheet.split(
                "QProgressBar#profileConfirmationProgress::chunk {",
                1,
            )[1].split("}", 1)[0]
            self.assertIn("color: #28563d;", progress_rule)
            self.assertIn("background: #edf8f2;", progress_rule)
            self.assertIn("background: #c9e5d3;", progress_chunk_rule)
            self.assertEqual(window.preparation_tabs.height(), height_before)
            self.assertEqual(
                window.profile_confirmation_stack.geometry(),
                stack_geometry_before,
            )

            window._set_preslice_activity(False)
            for _ in range(3):
                self.app.processEvents()
            self.assertIs(
                window.profile_confirmation_stack.currentWidget(),
                window.profile_confirm_button,
            )
            self.assertEqual(window.preparation_tabs.height(), height_before)
        finally:
            window.close()

    def test_preslice_activity_animates_immediately_and_cancel_is_deferred(
        self,
    ) -> None:
        window = self.window()
        window._preslice_request_id = 12
        window._start_preslice_runtime_watchdog(12)
        window._set_preslice_activity(True, percent=35)
        window.preslice_cancel_button.show()
        window.preslice_cancel_button.setEnabled(True)
        try:
            self.assertEqual(window._preslice_runtime_timer.interval(), 480_000)
            self.assertTrue(window._preslice_activity_timer.isActive())
            self.assertEqual(
                window.profile_confirmation_progress.text_label.text(),
                "Slicer und Profile bestätigt, Pre-Slice wird "
                "durchgeführt... (35%)",
            )
            first_frame = (
                window.profile_confirmation_progress.activity_label.text()
            )
            self.assertIn(first_frame, "◐◓◑◒")
            window._advance_preslice_activity_frame()
            self.assertNotEqual(
                window.profile_confirmation_progress.activity_label.text(),
                first_frame,
            )

            with (
                patch.object(
                    window.background_job_manager,
                    "has_active",
                    return_value=True,
                ),
                patch.object(
                    window.background_job_manager,
                    "cancel_jobs",
                ) as cancel_jobs,
                patch.object(
                    window,
                    "_refresh_dynamic_preparation_layout",
                ) as refresh_layout,
            ):
                cancel_width = window.preslice_cancel_button.width()
                window.preslice_cancel_button.pressed.emit()
                self.assertTrue(window.preslice_cancel_button.isEnabled())
                self.assertFalse(window._preslice_cancel_requested)
                cancel_jobs.assert_not_called()

                window.preslice_cancel_button.clicked.emit()
                self.assertFalse(window.preslice_cancel_button.isEnabled())
                self.assertEqual(
                    window.preslice_cancel_button.text(),
                    "Abbruch wird ausgeführt …",
                )
                self.assertEqual(
                    window.preslice_cancel_button.width(),
                    cancel_width,
                )
                refresh_layout.assert_not_called()
                self.assertTrue(
                    window.profile_confirmation_progress.format().startswith(
                        "Pre-Slice wird abgebrochen... ("
                    )
                )
                cancel_jobs.assert_not_called()
                self.app.processEvents()
                cancel_jobs.assert_called_once_with(
                    JobKind.PRESLICE,
                    reason="preslice_cancelled_by_user",
                )
        finally:
            window._stop_preslice_runtime_watchdog()
            window.close()

    def test_preslice_timeout_cancels_after_eight_minutes_with_message(
        self,
    ) -> None:
        window = self.window()
        window._preslice_request_id = 13
        window._start_preslice_runtime_watchdog(13)
        window._set_preslice_activity(True, percent=55)
        window.preslice_cancel_button.show()
        try:
            with (
                patch.object(
                    window.background_job_manager,
                    "has_active",
                    return_value=True,
                ),
                patch.object(
                    window.background_job_manager,
                    "cancel_jobs",
                ) as cancel_jobs,
            ):
                window._on_preslice_runtime_timeout()
                self.assertEqual(window._preslice_timeout_request_id, 13)
                self.assertEqual(
                    window.preslice_cancel_button.text(),
                    "Zeitlimit erreicht …",
                )
                self.assertTrue(
                    window.profile_confirmation_progress.format().startswith(
                        "Zeitlimit von 8 Minuten erreicht, "
                    )
                )
                self.app.processEvents()
                cancel_jobs.assert_called_once_with(
                    JobKind.PRESLICE,
                    reason="preslice_timeout",
                )

            with (
                patch.object(window, "_set_slicer_progress"),
                patch.object(window.workflow, "preslice_failed"),
                patch.object(
                    window,
                    "_reset_preslice_confirmation_for_retry",
                ) as reset_for_retry,
                patch.object(window, "_set_main_status"),
                patch.object(window, "_update_preparation_requirements"),
                patch.object(window, "validate_form"),
            ):
                window._on_source_preslice_cancelled(13)
            reset_message = reset_for_retry.call_args.args[0]
            self.assertIn("maximale Laufzeit von 8 Minuten", reset_message)
        finally:
            window._stop_preslice_runtime_watchdog()
            window.close()

    def test_preparation_dividers_and_source_progress_use_constant_gaps(
        self,
    ) -> None:
        window = self.window()
        window.resize(1200, 1000)
        window.show()
        self.app.processEvents()
        try:
            self.assertEqual(
                window.preparation_progress_title_label.text(),
                "Fortschritt der Vorbereitungen",
            )
            source_layout = window.source_group.content_layout
            slicer_layout = window.slicer_group.content_layout
            self.assertEqual(source_layout.spacing(), slicer_layout.spacing())
            expected_gap = source_layout.spacing()

            def gap(upper: QWidget, lower: QWidget) -> int:
                return lower.geometry().top() - upper.geometry().bottom() - 1

            self.assertEqual(
                gap(
                    window.preparation_source_requirements,
                    window.preparation_source_divider,
                ),
                expected_gap,
            )
            self.assertEqual(
                gap(window.preparation_source_divider, window.source_guide_row),
                expected_gap,
            )

            window.source_guide_row.hide()
            window.source_progress_bar.show()
            window._refresh_dynamic_preparation_layout()
            self.app.processEvents()
            self.assertEqual(
                gap(window.preparation_source_divider, window.source_progress_bar),
                expected_gap,
            )
            self.assertEqual(
                gap(window.source_progress_bar, window.drop_zone),
                expected_gap,
            )

            window.source_progress_bar.hide()
            window._refresh_dynamic_preparation_layout()
            self.app.processEvents()
            self.assertEqual(
                gap(window.preparation_source_divider, window.drop_zone),
                expected_gap,
            )

            self.mark_valid_source(window)
            window.preparation_tabs.setCurrentIndex(1)
            window._refresh_dynamic_preparation_layout()
            self.app.processEvents()
            self.assertEqual(
                gap(
                    window.preparation_slicer_requirements,
                    window.preparation_slicer_info_divider,
                ),
                expected_gap,
            )
            self.assertEqual(gap(window.preparation_slicer_info_divider, window.preparation_profile_hint), expected_gap)
            self.assertEqual(gap(window.preparation_profile_hint, window.preparation_slicer_divider), expected_gap)
            self.assertEqual(
                gap(window.preparation_slicer_divider, window.slicer_columns),
                expected_gap,
            )
        finally:
            window.close()

    def test_drag_hover_does_not_reflow_loaded_source_during_analysis(
        self,
    ) -> None:
        window = self.window()
        source = self.mark_valid_source(window)
        window.drop_zone.set_file(source)
        window.drop_zone.set_analysis_state("analyzing")
        window.source_guide_row.hide()
        window.source_progress_bar.show()
        window.resize(1200, 1000)
        window.show()
        window._refresh_dynamic_preparation_layout()
        self.app.processEvents()

        def snapshot() -> tuple[object, ...]:
            drop_zone = window.drop_zone
            return (
                drop_zone.height(),
                drop_zone.minimumHeight(),
                drop_zone.sizeHint().height(),
                window.source_group.content_widget.height(),
                window.preparation_tabs.height(),
                tuple(
                    (
                        item.widget().objectName(),
                        item.widget().isHidden(),
                        item.widget().geometry(),
                    )
                    for index in range(drop_zone.root_layout.count())
                    if (item := drop_zone.root_layout.itemAt(index)).widget()
                    is not None
                ),
            )

        try:
            stable_snapshot = snapshot()
            window.drop_zone._set_drag_active(True)
            self.app.processEvents()
            self.assertEqual(snapshot(), stable_snapshot)

            window.drop_zone._set_drag_active(False)
            self.app.processEvents()
            self.assertEqual(snapshot(), stable_snapshot)
        finally:
            window.close()

    def test_preslice_and_profile_notice_never_compress_slicer_controls(
        self,
    ) -> None:
        window = self.window()
        self.mark_valid_source(window)
        window.resize(1280, 1000)
        window.preparation_tabs.setCurrentIndex(1)
        window.show()
        self.app.processEvents()
        try:
            window.preslice_cancel_button.show()
            window._set_preslice_activity(True, percent=42)
            window._set_profile_notice(
                "Das Modell konnte mit den bestätigten Einstellungen nicht "
                "sicher analysiert werden.",
                state="error",
            )
            for _ in range(4):
                self.app.processEvents()

            layout = window.slicer_group.content_layout
            visible_blocks = [
                layout.itemAt(index).widget()
                for index in range(layout.count())
                if (
                    layout.itemAt(index).widget() is not None
                    and not layout.itemAt(index).widget().isHidden()
                )
            ]
            for upper, lower in zip(visible_blocks, visible_blocks[1:]):
                self.assertGreaterEqual(
                    lower.geometry().top() - upper.geometry().bottom() - 1,
                    layout.spacing(),
                )

            selector_blocks = [
                window.slicer_selection_label.parentWidget(),
                window.slicer_combo,
                (window.slicer_refresh_button, window.slicer_manual_button),
                window.machine_profile_label,
                window.machine_profile_combo,
                window.filament_profile_label,
                window.filament_profile_combo,
                window.process_profile_label,
                window.process_profile_combo,
                window.show_all_profiles_checkbox,
                window.profile_confirmation_stack,
                window.preslice_cancel_button,
            ]

            def vertical_bounds(block) -> tuple[int, int]:
                widgets = block if isinstance(block, tuple) else (block,)
                tops = [
                    widget.mapTo(window.slicer_selector_column, QPoint(0, 0)).y()
                    for widget in widgets
                ]
                bottoms = [
                    top + widget.height() - 1
                    for top, widget in zip(tops, widgets)
                ]
                return min(tops), max(bottoms)

            bounds = [vertical_bounds(block) for block in selector_blocks]
            for upper, lower in zip(bounds, bounds[1:]):
                self.assertGreater(lower[0], upper[1])
            self.assertGreater(
                window.preslice_cancel_button.geometry().top(),
                window.profile_confirmation_stack.geometry().bottom(),
            )
            self.assertEqual(
                window.preslice_cancel_button.geometry().right(),
                window.slicer_selector_column.rect().right(),
            )
            self.assertEqual(
                layout.indexOf(window.preslice_cancel_button),
                -1,
            )
            self.assertGreater(
                window.slicer_selectors_layout.indexOf(
                    window.preslice_cancel_button
                ),
                window.slicer_selectors_layout.indexOf(
                    window.profile_confirmation_stack
                ),
            )
            selector_parent = window.slicer_selector_column

            def top_in_selector(widget: QWidget) -> int:
                return widget.mapTo(selector_parent, QPoint(0, 0)).y()

            action_top = min(
                top_in_selector(window.slicer_refresh_button),
                top_in_selector(window.slicer_manual_button),
            )
            combo_bottom = (
                top_in_selector(window.slicer_combo)
                + window.slicer_combo.height()
                - 1
            )
            confirmation_bottom = (
                top_in_selector(window.profile_confirmation_stack)
                + window.profile_confirmation_stack.height()
                - 1
            )
            cancel_top = top_in_selector(window.preslice_cancel_button)
            self.assertEqual(
                action_top - combo_bottom - 1,
                cancel_top - confirmation_bottom - 1,
            )
            self.assertGreaterEqual(
                window.slicer_group.content_widget.rect().bottom()
                - visible_blocks[-1].geometry().bottom(),
                layout.contentsMargins().bottom(),
            )
        finally:
            window.close()

    def test_profile_checkbox_uses_the_field_gap_above_and_below(self) -> None:
        window = self.window()
        self.mark_valid_source(window)
        window.preparation_tabs.setCurrentIndex(1)
        window.resize(1200, 1000)
        window.show()
        self.app.processEvents()
        try:
            def gap(upper: QWidget, lower: QWidget) -> int:
                parent = window.slicer_selector_column
                upper_top = upper.mapTo(parent, QPoint(0, 0)).y()
                lower_top = lower.mapTo(parent, QPoint(0, 0)).y()
                return lower_top - (upper_top + upper.height() - 1) - 1

            field_gap = gap(
                window.process_profile_label,
                window.process_profile_combo,
            )
            self.assertEqual(
                (
                    gap(
                        window.process_profile_combo,
                        window.show_all_profiles_checkbox,
                    ),
                    gap(
                        window.show_all_profiles_checkbox,
                        window.profile_confirmation_stack,
                    ),
                ),
                (field_gap, field_gap),
            )
        finally:
            window.close()

    def test_ambiguous_profile_match_requires_confirmation_without_notice(
        self,
    ) -> None:
        window = self.window()
        installation = SimpleNamespace(
            identity_key="testslicer",
            display_name="Testslicer",
        )
        result = SimpleNamespace(
            execution_slicer=installation,
            requires_confirmation=True,
            state=ProfileMatchState.AMBIGUOUS,
            profile_filter_summary="",
            selected=None,
            source_kind=SourceKind.STL,
            can_use_stl_mode=True,
            message="Mehrere passende Profilkombinationen wurden gleich gut bewertet.",
            user_confirmed=False,
        )
        window._profile_request_id = 9
        try:
            with (
                patch.object(
                    type(window),
                    "selected_slicer_installation",
                    new_callable=PropertyMock,
                    return_value=installation,
                ),
                patch.object(window, "_populate_profile_combos"),
                patch.object(window, "_invalidate_preview"),
                patch.object(window, "_set_slicer_progress"),
                patch.object(window, "_refresh_stl_availability"),
                patch.object(window, "_update_preparation_requirements"),
                patch.object(window, "update_wall_path_preview"),
            ):
                window._on_profile_matching_succeeded(9, result)

            self.assertTrue(window.profile_status_label.isHidden())
            self.assertTrue(window.slicer_message_divider_host.isHidden())
            self.assertTrue(window.profile_confirm_button.isEnabled())
        finally:
            window.close()

    def test_profile_confirmation_requires_existing_catalog_backed_files(self) -> None:
        window = self.window()
        self.mark_valid_source(window)
        executable = self.root / "slicer.exe"
        executable.write_bytes(b"MZ")
        installation = SimpleNamespace(
            verified=True,
            can_slice=True,
            identity_key="testslicer",
            executable_path=executable,
            display_name="Testslicer",
        )

        def profile(role: str, kind: ProfileKind) -> ProfileRecord:
            path = self.root / f"{role}.json"
            path.write_text("{}", encoding="utf-8")
            return ProfileRecord(
                adapter_id="testslicer",
                profile_id=role,
                name=role.title(),
                kind=kind,
                path=path,
                source="user",
            )

        machine = profile("machine", ProfileKind.MACHINE)
        filament = profile("filament", ProfileKind.FILAMENT)
        process = profile("process", ProfileKind.PROCESS)
        catalog = ProfileCatalog(
            execution_slicer=installation,
            inventory_fingerprint="inventory",
            machine_options=(machine,),
            filament_options=(filament,),
            process_options=(process,),
            selected_machine=ProfileSelectionReference(
                machine.profile_id, machine.path
            ),
            selected_filament=ProfileSelectionReference(
                filament.profile_id, filament.path
            ),
            selected_process=ProfileSelectionReference(
                process.profile_id, process.path
            ),
        )
        try:
            with patch.object(
                type(window),
                "selected_slicer_installation",
                new_callable=PropertyMock,
                return_value=installation,
            ):
                window.profile_catalog = catalog
                window._populate_profile_combos(catalog)
                window._update_preparation_requirements()

                self.assertTrue(window.profile_confirm_button.isEnabled())
                self.assertEqual(
                    window.profile_confirm_button.text(),
                    "Slicer und Profile bestätigen",
                )
                self.assertFalse(
                    window.profile_confirm_button.property("confirmed")
                )

                filament.path.unlink()
                window._update_preparation_requirements()
                self.assertFalse(window.profile_confirm_button.isEnabled())
                self.assertTrue(
                    window.profile_confirm_button.text().endswith("🔒")
                )
                self.assertIn(
                    "vorhandenes Maschinen-, Filament- und Prozessprofil",
                    window.profile_confirm_button.toolTip(),
                )
        finally:
            window.close()

    def test_show_all_toggle_reloads_catalog_for_a_source_ready_step(self) -> None:
        window = self.window()
        self.mark_valid_source(window)
        executable = self.root / "slicer-toggle.exe"
        executable.write_bytes(b"MZ")
        installation = SimpleNamespace(
            verified=True,
            can_slice=True,
            identity_key="toggle-slicer",
            executable_path=executable,
            display_name="Toggle Slicer",
        )

        def profile(role: str, kind: ProfileKind) -> ProfileRecord:
            path = self.root / f"toggle-{role}.json"
            path.write_text("{}", encoding="utf-8")
            return ProfileRecord(
                adapter_id="toggle-slicer",
                profile_id=f"toggle-{role}",
                name=f"Toggle {role}",
                kind=kind,
                path=path,
                source="system",
            )

        machine = profile("machine", ProfileKind.MACHINE)
        filament = profile("filament", ProfileKind.FILAMENT)
        process = profile("process", ProfileKind.PROCESS)
        catalog = ProfileCatalog(
            execution_slicer=installation,
            inventory_fingerprint="toggle-inventory",
            machine_options=(machine,),
            filament_options=(filament,),
            process_options=(process,),
            selected_machine=ProfileSelectionReference(
                machine.profile_id, machine.path
            ),
            selected_filament=ProfileSelectionReference(
                filament.profile_id, filament.path
            ),
            selected_process=ProfileSelectionReference(
                process.profile_id, process.path
            ),
        )
        try:
            with patch.object(
                type(window),
                "selected_slicer_installation",
                new_callable=PropertyMock,
                return_value=installation,
            ):
                window.profile_catalog = catalog
                window._populate_profile_combos(catalog)
                with (
                    patch.object(
                        window, "start_profile_catalog_loading"
                    ) as reload_catalog,
                    patch.object(window, "start_profile_matching") as match,
                ):
                    window._on_show_all_profiles_toggled(True)

                match.assert_not_called()
                reload_catalog.assert_called_once()
                arguments = reload_catalog.call_args.kwargs
                self.assertTrue(arguments["include_all_profiles"])
                self.assertEqual(
                    arguments["selected_machine"].profile_id,
                    machine.profile_id,
                )
                self.assertEqual(
                    set(arguments["selected_profile_ids"]),
                    {"machine", "process", "filament"},
                )

                window._profile_request_id = 4
                window._profile_catalog_match_source_request_id = 4
                with patch.object(window, "start_profile_matching") as match:
                    window._on_profile_catalog_succeeded(4, catalog)
                match.assert_called_once()
                self.assertIsNone(
                    window._profile_confirmation_blocking_reason()
                )
        finally:
            window.close()

    def test_slicer_notice_and_divider_are_below_confirmation_slot(self) -> None:
        window = self.window()
        try:
            self.mark_valid_source(window)
            layout = window.slicer_group.content_layout
            self.assertLess(
                layout.indexOf(window.slicer_columns),
                layout.indexOf(window.slicer_message_divider_host),
            )
            self.assertLess(
                layout.indexOf(window.slicer_message_divider_host),
                layout.indexOf(window.profile_status_label),
            )
            self.assertTrue(window.slicer_message_divider_host.isHidden())
            window._set_profile_notice(
                "Die ausgewählten Profile sind nicht kompatibel.",
                state="error",
            )
            window.resize(1200, 1000)
            window.preparation_tabs.setCurrentIndex(1)
            window.show()
            self.app.processEvents()
            self.assertFalse(window.slicer_message_divider_host.isHidden())
            self.assertFalse(window.profile_status_label.isHidden())
            divider_top = (
                window.slicer_message_divider_host.geometry().top()
                + window.slicer_message_divider.geometry().top()
            )
            divider_bottom = (
                divider_top + window.slicer_message_divider.height() - 1
            )
            reference_gap = (
                layout.spacing()
                + window.preparation_slicer_requirements.layout()
                .contentsMargins()
                .bottom()
            )
            confirmation_top = window.profile_confirmation_stack.mapTo(
                window.slicer_group.content_widget,
                QPoint(0, 0),
            ).y()
            confirmation_bottom = (
                confirmation_top
                + window.profile_confirmation_stack.height()
                - 1
            )
            self.assertEqual(
                divider_top
                - confirmation_bottom
                - 1,
                reference_gap,
            )
            self.assertEqual(
                window.profile_status_label.geometry().top() - divider_bottom - 1,
                reference_gap,
            )
            window._set_profile_notice()
            self.assertTrue(window.slicer_message_divider_host.isHidden())
            self.assertTrue(window.profile_status_label.isHidden())
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
            window.stl_validation_feedback.show()
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

    def test_preparation_header_only_displays_its_centered_caption_in_every_state(self) -> None:
        window = self.window()
        window.show()
        self.app.processEvents()
        try:
            title=window.preparation_section_title
            self.assertEqual(title.text(),"Datei und Slicer vorbereiten")
            self.assertEqual(title.alignment(),Qt.AlignmentFlag.AlignCenter)
            for state in (SectionState.ACTIVE,SectionState.ERROR,SectionState.SUCCESS):
                window.workflow_group.set_state(state)
                window.workflow_group.set_summary("Vorbereitung abgeschlossen")
                window.workflow_group.set_badge("Status")
                self.app.processEvents()
                self.assertTrue(window.workflow_group.header.isHidden())
                self.assertFalse(window.workflow_group.status_icon.isVisible())
                self.assertFalse(window.workflow_group.summary_label.isVisible())
                self.assertFalse(window.workflow_group.badge_label.isVisible())
                self.assertTrue(title.isVisible())
                center=title.mapTo(window,QPoint(title.width()//2,0)).x()
                self.assertLessEqual(abs(center-window.width()//2),1)
        finally:
            window.close()

    def test_preparation_surface_matches_window_background_without_bottom_fade(self) -> None:
        window = self.window()
        self.addCleanup(window.close)
        window.resize(1200, 1000)
        window.show()
        for _ in range(5):
            self.app.processEvents()
        for width, height in ((1200, 1000), (760, 700), (1400, 1000)):
            window.resize(width, height)
            for _ in range(5):
                self.app.processEvents()
            body = window.workflow_group.content_widget
            self.assertEqual(body.geometry().bottom(), window.workflow_group.rect().bottom())
            image = body.grab().toImage()
            for y in (0, image.height() // 2, image.height() - 1):
                self.assertEqual(image.pixelColor(10, y).name(), "#f3f6f9")
        window.workflow.set_slicer_step_visible(True)
        window.workflow.source_validation_succeeded("Test-STL", analysis_complete=True)
        window.workflow.slicer_succeeded("Testslicer")
        window.workflow.complete_preparation()
        window.automatic_generation_card.click()
        window.show_preparation_workspace()
        for _ in range(5):
            self.app.processEvents()
        body = window.workflow_group.content_widget
        self.assertEqual(
            body.geometry().bottom(),
            window.workflow_group.rect().bottom(),
        )
        image = body.grab().toImage()
        for y in (0, image.height() // 2, image.height() - 1):
            self.assertEqual(image.pixelColor(10, y).name(), "#f3f6f9")

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
            self.assertIn("background: #f3f6f9;", preparation_body_rule)
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
            pressed_rule = stylesheet.split(
                "QPushButton#preparationStepSelector:pressed,",
                1,
            )[1].split("}", 1)[0]
            self.assertIn("background: qlineargradient(", pressed_rule)
            self.assertNotIn("border", pressed_rule)
            locked_pressed_rule = stylesheet.split(
                'QPushButton#preparationStepSelector[locked="true"]:pressed {',
                1,
            )[1].split("}", 1)[0]
            self.assertIn("background: qlineargradient(", locked_pressed_rule)
            self.assertNotIn("border", locked_pressed_rule)

            self.mark_valid_source(window)
            source, slicer = window.preparation_step_selectors
            source_image = source.grab().toImage()
            slicer_image = slicer.grab().toImage()
            self.assertNotEqual(
                source_image.pixelColor(6, source.height() - 8),
                slicer_image.pixelColor(6, slicer.height() - 8),
            )
            slicer.click()
            self.app.processEvents()
            source_image = source.grab().toImage()
            slicer_image = slicer.grab().toImage()
            self.assertNotEqual(
                source_image.pixelColor(6, source.height() - 8),
                slicer_image.pixelColor(6, slicer.height() - 8),
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
            self.assertEqual(window.preparation_progress_bar.value(), 29)
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
            drag_rule_position = stylesheet.rfind(
                'QFrame#sourceDropZone[dragActive="true"] {'
            )
            self.assertGreater(
                drag_rule_position,
                stylesheet.rfind('QFrame#sourceDropZone[loaded="true"] {'),
            )
            self.assertGreater(
                drag_rule_position,
                stylesheet.rfind(
                    'QFrame#sourceDropZone[completed="true"] {'
                ),
            )
            completed_page_rule_position = stylesheet.rfind(
                'QWidget#preparationStepPage[stepTone="source"] '
                'QFrame#sourceDropZone[completed="true"] {'
            )
            completed_drag_rule_position = stylesheet.rfind(
                'QWidget#preparationStepPage[stepTone="source"]\n'
                'QFrame#sourceDropZone[dragActive="true"] {'
            )
            self.assertGreater(
                completed_drag_rule_position,
                completed_page_rule_position,
            )
            completed_drag_rule = stylesheet[
                completed_drag_rule_position:
            ].split("}", 1)[0]
            self.assertIn("background: #deeff8;", completed_drag_rule)

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
                window.stl_validation_feedback,
            )
            for upper, lower in zip(source_blocks, source_blocks[1:]):
                self.assertLess(upper.geometry().bottom(), lower.geometry().top())
            self.assertLessEqual(
                window.stl_validation_feedback.geometry().bottom(),
                window.source_group.content_widget.rect().bottom()
                - window.source_group.content_layout.contentsMargins().bottom(),
            )
        finally:
            window.close()

    def test_requirements_live_at_top_of_their_white_step_contents(self) -> None:
        window = self.window()
        window.show()
        self.app.processEvents()
        try:
            source_selector, slicer_selector = window.preparation_step_selectors
            self.assertIs(
                window.preparation_source_requirements.parentWidget(),
                window.source_group.content_widget,
            )
            self.assertIs(
                window.preparation_slicer_requirements.parentWidget(),
                window.slicer_group.content_widget,
            )
            self.assertEqual(source_selector.property("stepTone"), "source")
            self.assertEqual(slicer_selector.property("stepTone"), "slicer")
            self.assertLess(
                window.source_group.content_layout.indexOf(
                    window.preparation_source_requirements
                ),
                window.source_group.content_layout.indexOf(window.drop_zone),
            )
            self.assertLess(
                window.slicer_group.content_layout.indexOf(
                    window.preparation_slicer_requirements
                ),
                window.slicer_group.content_layout.indexOf(
                    window.slicer_columns
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

    def test_only_step_selector_hover_changes_the_tab_presentation(self) -> None:
        window = self.window()
        window.show()
        self.app.processEvents()
        try:
            selector = window.preparation_step_selectors[0]
            requirements = window.preparation_source_requirements
            content = window.source_group.content_widget
            window._set_preparation_step_hovered(0, False)

            self.assertEqual(
                requirements.cursor().shape(),
                Qt.CursorShape.ArrowCursor,
            )
            self.assertEqual(
                requirements.focusPolicy(),
                Qt.FocusPolicy.NoFocus,
            )
            for white_area in (content, requirements):
                enter = QEnterEvent(
                    QPointF(1, 1),
                    QPointF(1, 1),
                    QPointF(1, 1),
                )
                QApplication.sendEvent(white_area, enter)
                self.app.processEvents()
                self.assertFalse(bool(selector.property("groupHovered")))

            selector.hover_changed.emit(True)
            self.app.processEvents()
            self.assertTrue(selector.property("groupHovered"))
            selector.hover_changed.emit(False)
            QApplication.sendEvent(selector, QEvent(QEvent.Type.Leave))
            self.app.processEvents()
            self.assertFalse(selector.property("groupHovered"))
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
                patch.object(
                    window,
                    "_profile_confirmation_inputs_ready",
                    return_value=True,
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

    def test_completed_steps_unlock_finish_without_tab_status_duplication(self) -> None:
        window = self.window()
        window.current_source_path = self.root / "modell.stl"
        window.current_source_kind = SourceKind.STL
        window.stl_validation_result = SimpleNamespace(valid=True)
        window.source_artifact = object()
        installation = SimpleNamespace(
            verified=True,
            identity_key="testslicer",
            display_name="Testslicer 1.0",
            can_slice=True,
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
                window.workflow.set_slicer_step_visible(True)
                window.workflow.source_validation_succeeded(
                    "modell.stl · Geometrie gültig",
                    analysis_complete=True,
                )
                window.workflow.slicer_succeeded("Testslicer")
                window._update_preparation_requirements()

                self.assertFalse(window.workflow_group.isCheckable())
                self.assertTrue(window.workflow_group.isChecked())
                self.assertTrue(window.workflow_group.toggle_button.isHidden())
                self.assertEqual(
                    [
                        icon.text()
                        for icon in window.preparation_step_selector_icons
                    ],
                    ["", ""],
                )
                self.assertTrue(
                    all(
                        badge.isHidden()
                        for badge in window.preparation_step_state_labels
                    )
                )
                window.preparation_tabs.setCurrentIndex(1)
                self.assertFalse(window.preparation_back_button.isHidden())
                self.assertEqual(
                    window.preparation_navigation_title_label.text(),
                    "Slicer-Einstellungen",
                )
                self.assertTrue(window.preparation_next_button.isHidden())
                self.assertFalse(window.preparation_finish_button.isHidden())
                self.assertTrue(window.preparation_finish_button.isEnabled())
                self.assertEqual(
                    window.preparation_finish_button.text(),
                    "Fertig",
                )
                self.assertEqual(
                    [
                        page.property("stepTone")
                        for page in window.preparation_tab_pages
                    ],
                    ["source", "slicer"],
                )
                window.preparation_finish_button.click()
                self.app.processEvents()
                self.assertFalse(window.workflow_group.isCheckable())
                self.assertTrue(window.workflow_group.isChecked())
                self.assertTrue(window.workflow_group.toggle_button.isHidden())
                self.assertIs(window.window_pages.currentWidget(), window.preparation_workspace)
                self.assertTrue(window.generation_method_picker.isVisibleTo(window.preparation_workspace))
                self.assertIs(
                    window.workflow_group.state(),
                    SectionState.SUCCESS,
                )
                self.assertEqual(window.workflow_group.status_icon.text(), "✓")
                window.analysis_snapshot = None
                window._update_preparation_requirements()
                self.assertFalse(window.workflow_group.isCheckable())
                self.assertFalse(window.preparation_finish_button.isEnabled())
                self.assertEqual(
                    window.preparation_finish_button.text(),
                    "Fertig 🔒",
                )
                self.assertTrue(window.workflow_group.isChecked())
                self.assertTrue(window.workflow_group.toggle_button.isHidden())
        finally:
            window.close()

    def test_continue_opens_slicer_with_400_ms_transition(self) -> None:
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
            self.assertTrue(window.preparation_next_button.isEnabled())
            self.assertEqual(window.preparation_next_button.text(), "Weiter")
            window.preparation_next_button.click()
            self.app.processEvents()
            self.assertEqual(window.preparation_tabs.currentIndex(), 1)
            self.assertEqual(
                window.preparation_tabs.last_transition,
                (0, 1, 400),
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
            self.assertEqual(window.preparation_progress_bar.value(), 14)
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

        def wait_for_transition(target_index: int) -> None:
            deadline = time.monotonic() + 2.0
            while time.monotonic() < deadline:
                self.app.processEvents()
                if (
                    window.preparation_tabs.currentIndex() == target_index
                    and window.preparation_tabs._transition_animation is None
                ):
                    return
                QTest.qWait(10)
            self.fail(f"Preparation transition to step {target_index} timed out")

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
            wait_for_transition(1)
            self.assertEqual(window.preparation_tabs.currentIndex(), 1)

            window.preparation_tabs.setCurrentIndex(0)
            wait_for_transition(0)
            window.preparation_tabs.setCurrentIndex(1)
            wait_for_transition(1)

            self.assertEqual(
                transitions,
                [
                    (0, 1, 400),
                    (1, 0, 400),
                    (0, 1, 400),
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
            self.assertEqual(window.workflow_group.status_icon.text(), "⇧")
            window.preparation_tabs.setCurrentIndex(1)
            self.app.processEvents()
            self.assertIs(window.workflow_group.state(), SectionState.ERROR)
            self.assertEqual(window.workflow_group.status_icon.text(), "×")
            self.assertTrue(
                window.workflow_group.property("preparationError")
            )
            self.assertFalse(window.workflow_group.status_icon.isVisible())
            self.assertIs(window.workflow.stage, WorkflowStage.ERROR)
            window.workflow.begin_slicer_search()
            self.assertIs(window.workflow_group.state(), SectionState.ACTIVE)
            self.assertEqual(window.workflow_group.status_icon.text(), "⇧")
            self.assertFalse(
                window.workflow_group.property("preparationError")
            )
            self.assertFalse(window.workflow_group.status_icon.isVisible())
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
                    "preslice_completed",
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

    def test_double_success_waits_for_finish_before_revealing_settings(self) -> None:
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
            self.assertIs(window.workflow_group.state(), SectionState.ACTIVE)
            self.assertTrue(window.workflow_group.isChecked())
            self.assertFalse(window.workflow_group.isCheckable())
            self.assertTrue(window.workflow_group.toggle_button.isHidden())
            self.assertEqual(window.workflow_group.status_icon.text(), "⇧")
            self.assertTrue(window.ready_grid.isHidden())
            self.assertTrue(window.workflow.complete_preparation())
            self.app.processEvents()
            self.assertIs(window.workflow_group.state(), SectionState.SUCCESS)
            self.assertFalse(window.workflow_group.isCheckable())
            self.assertEqual(window.workflow_group.status_icon.text(), "✓")
            self.assertTrue(window.workflow_group.isChecked())
            self.assertTrue(window.workflow_group.isHidden())
            self.assertIs(window.window_pages.currentWidget(), window.preparation_workspace)
            self.assertTrue(window.ready_grid.isHidden())
            self.assertFalse(window.generation_method_picker.isHidden())
            window.automatic_generation_card.click()
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
