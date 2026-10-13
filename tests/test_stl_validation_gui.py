from __future__ import annotations

import hashlib
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch


PROJECT_ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = PROJECT_ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("COOLING_TOWER_DISABLE_SLICER_DISCOVERY", "1")

from PySide6.QtCore import QEventLoop, QMimeData, QTimer, Qt, QUrl
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QMessageBox

from cooling_tower.gui.main_window import (
    INTERNAL_DIALOG_REVEAL_DELAY_MS,
    MainWindow,
)
from cooling_tower.gui.workflow_controller import WorkflowStage
from cooling_tower.models import SourceKind


class StlValidationGuiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.fixture_root = PROJECT_ROOT / "tests" / "fixtures" / "stl"

    def tearDown(self) -> None:
        self.app.processEvents()
        self.temporary.cleanup()

    def window(self) -> MainWindow:
        return MainWindow(
            user_settings_path=self.root / "settings.json",
            enable_update_check=False,
        )

    def wait_for_stl_result(self, window: MainWindow, timeout_s: float = 30.0) -> None:
        loop = QEventLoop()
        poll_timer = QTimer()
        poll_timer.setInterval(20)
        poll_timer.timeout.connect(
            lambda: loop.quit()
            if window.stl_validation_result is not None
            else None
        )
        timeout_timer = QTimer()
        timeout_timer.setSingleShot(True)
        timeout_timer.timeout.connect(loop.quit)
        poll_timer.start()
        timeout_timer.start(round(timeout_s * 1000))
        loop.exec()
        poll_timer.stop()
        timeout_timer.stop()
        self.assertIsNotNone(window.stl_validation_result)

    def wait_for_stage(
        self,
        window: MainWindow,
        stage: WorkflowStage,
        timeout_s: float = 15.0,
    ) -> None:
        loop = QEventLoop()
        poll_timer = QTimer()
        poll_timer.setInterval(20)
        poll_timer.timeout.connect(
            lambda: loop.quit() if window.workflow.stage is stage else None
        )
        timeout_timer = QTimer()
        timeout_timer.setSingleShot(True)
        timeout_timer.timeout.connect(loop.quit)
        poll_timer.start()
        timeout_timer.start(round(timeout_s * 1000))
        loop.exec()
        poll_timer.stop()
        timeout_timer.stop()
        self.assertIs(window.workflow.stage, stage)

    @staticmethod
    def drop_file(window: MainWindow, path: Path) -> bool:
        class DropEventStub:
            def __init__(self, source: Path) -> None:
                self._mime_data = QMimeData()
                self._mime_data.setUrls([QUrl.fromLocalFile(str(source))])
                self.accepted = False

            def mimeData(self):
                return self._mime_data

            def acceptProposedAction(self) -> None:
                self.accepted = True

            def ignore(self) -> None:
                self.accepted = False

        event = DropEventStub(path)
        window.drop_zone.dropEvent(event)
        return event.accepted

    def test_non_manifold_stl_blocks_downstream_and_shows_details(self) -> None:
        source = self.fixture_root / "test_model_non_manifold.stl"
        before = hashlib.sha256(source.read_bytes()).hexdigest()
        window = self.window()
        try:
            self.assertTrue(window.drop_zone.set_file(source))
            self.wait_for_stl_result(window)
            result = window.stl_validation_result
            assert result is not None
            self.assertFalse(result.valid)
            self.assertIs(window.current_source_kind, SourceKind.STL)
            self.assertIs(window.workflow.stage, WorkflowStage.SOURCE_INVALID)
            self.assertEqual(window.workflow_group.status_icon.text(), "×")
            self.assertTrue(
                window.workflow_group.property("preparationError")
            )
            self.assertTrue(window.source_group.isChecked())
            self.assertFalse(window.source_group.content_widget.isHidden())
            self.assertTrue(window.ready_grid.isHidden())
            self.assertFalse(window.slicer_group.isVisibleTo(window))
            self.assertEqual(window.preparation_tabs.currentIndex(), 0)
            self.assertTrue(window.workflow_group.isChecked())
            self.assertTrue(window.stl_validation_message.isVisibleTo(window))
            self.assertEqual(
                window.stl_validation_message.property("severity"),
                "error",
            )
            self.assertIn(
                "non-manifold (nicht vollständig geschlossen)",
                window.stl_validation_message.text(),
            )
            margins = window.stl_validation_message.contentsMargins()
            self.assertEqual(
                (margins.left(), margins.top(), margins.right(), margins.bottom()),
                (0, 0, 0, 0),
            )
            self.assertFalse(window.stl_validation_details_toggle.isHidden())
            self.assertFalse(window.accept_rejected_stl_button.isHidden())
            self.assertEqual(
                window.accept_rejected_stl_button.text(),
                "STL trotzdem verwenden",
            )
            self.assertIn("Offene Kanten: 161", window.stl_validation_details.toPlainText())
            self.assertIs(
                window.stl_validation_message.parent(),
                window.stl_validation_feedback,
            )
            self.assertTrue(window.source_guide_row.isHidden())
            self.assertEqual(
                window.drop_zone.prompt_label.text(),
                window.drop_zone.EMPTY_PROMPT,
            )
            self.assertTrue(window.drop_zone.prompt_label.isHidden())
            self.assertFalse(window.drop_zone.info_widget.isHidden())
            self.assertTrue(window.source_progress_bar.isHidden())
            self.assertEqual(
                window.source_progress_status_label.text(),
                "STL-Prüfung fehlgeschlagen",
            )
            self.assertEqual(window.drop_zone.reload_button.text(), "STL neu einlesen")
            self.assertEqual(window.drop_zone.browse_button.text(), "Andere STL auswählen")
            self.assertEqual(window.drop_zone.remove_button.text(), "STL entfernen")
            self.assertFalse(window.drop_zone.browse_button.isHidden())
            self.assertFalse(window.drop_zone.reload_button.isHidden())
            self.assertFalse(window.drop_zone.remove_button.isHidden())
            self.assertTrue(window.drop_zone.browse_button.isEnabled())
            self.assertTrue(window.drop_zone.reload_button.isEnabled())
            self.assertTrue(window.drop_zone.remove_button.isEnabled())
            reload_column = window.drop_zone.actions_layout.getItemPosition(
                window.drop_zone.actions_layout.indexOf(
                    window.drop_zone.reload_button
                )
            )[1]
            remove_column = window.drop_zone.actions_layout.getItemPosition(
                window.drop_zone.actions_layout.indexOf(
                    window.drop_zone.remove_button
                )
            )[1]
            self.assertGreater(remove_column, reload_column)
            self.assertEqual(hashlib.sha256(source.read_bytes()).hexdigest(), before)
        finally:
            window.close()
            window.deleteLater()
            self.app.processEvents()

    def test_unreadable_or_empty_stl_never_offers_override(self) -> None:
        for name, payload in (
            ("leer.stl", b""),
            ("defekt.stl", b"dies ist kein STL-Container"),
        ):
            with self.subTest(name=name):
                source = self.root / name
                source.write_bytes(payload)
                window = self.window()
                try:
                    handed_off = window.drop_zone.set_file(source)
                    if handed_off:
                        self.wait_for_stl_result(window)
                        result = window.stl_validation_result
                        assert result is not None
                        self.assertFalse(result.valid)
                        self.assertEqual(result.face_count, 0)
                    self.assertTrue(
                        window.accept_rejected_stl_button.isHidden()
                    )
                finally:
                    window.close()
                    window.deleteLater()
                    self.app.processEvents()

    def test_rejected_stl_requires_warning_confirmation_before_acceptance(self) -> None:
        source = self.fixture_root / "test_model_non_manifold.stl"
        before = hashlib.sha256(source.read_bytes()).hexdigest()
        window = self.window()
        try:
            self.assertTrue(window.drop_zone.set_file(source))
            self.wait_for_stl_result(window)

            with patch.object(
                window,
                "_ask_rejected_stl_confirmation",
                side_effect=(
                    False,
                    True,
                ),
            ) as confirmation:
                window.accept_rejected_stl_button.click()
                self.assertFalse(window.stl_validation_result.accepted)
                self.assertIs(window.workflow.stage, WorkflowStage.SOURCE_INVALID)
                self.assertFalse(window.accept_rejected_stl_button.isHidden())

                window.accept_rejected_stl_button.click()

            result = window.stl_validation_result
            assert result is not None
            self.assertEqual(confirmation.call_count, 2)
            warning_text = window._create_rejected_stl_message_box().text()
            self.assertIn("nicht zufriedenstellenden Ergebnissen", warning_text)
            self.assertIn("Fehlern oder Fehlverhalten", warning_text)
            self.assertFalse(result.valid)
            self.assertTrue(result.user_confirmed)
            self.assertTrue(result.accepted)
            self.assertTrue(window._source_step_is_complete())
            self.assertIs(window.workflow.stage, WorkflowStage.DISCOVERING_SLICER)
            self.assertEqual(window.workflow_group.status_icon.text(), "⇧")
            self.assertFalse(
                window.workflow_group.property("preparationError")
            )
            self.assertTrue(window.preparation_next_button.isEnabled())
            self.assertFalse(
                window.preparation_step_selectors[1].property("locked")
            )
            self.assertTrue(window.accept_rejected_stl_button.isHidden())
            self.assertEqual(window.drop_zone.status_value_label.text(), "STL user-bestätigt")
            self.assertEqual(
                window.stl_validation_message.property("severity"),
                "warning",
            )
            self.assertIn("user-bestätigt", window.stl_validation_message.text())
            self.assertEqual(
                window.stl_validation_feedback.heading.title.text(),
                "STL auf eigenes Risiko akzeptiert",
            )
            self.assertEqual(window.stl_validation_feedback.heading.icon.text(), "!")
            self.assertIn("Akzeptanz: user-bestätigt", window.stl_validation_details.toPlainText())
            self.assertEqual(hashlib.sha256(source.read_bytes()).hexdigest(), before)
        finally:
            window.close()
            window.deleteLater()
            self.app.processEvents()

    def test_rejected_stl_confirmation_is_visible_on_screen_and_cancellable(self) -> None:
        window = self.window()
        window.resize(900, 800)
        window.show()
        self.app.processEvents()
        observed: dict[str, object] = {}
        callback_errors: list[BaseException] = []

        def rejected_dialog() -> QMessageBox:
            dialogs = [
                widget
                for widget in self.app.topLevelWidgets()
                if isinstance(widget, QMessageBox)
                and widget.objectName() == "rejectedStlConfirmationDialog"
            ]
            self.assertEqual(len(dialogs), 1)
            return dialogs[0]

        def inspect_concealed_position() -> None:
            try:
                dialog = rejected_dialog()
                observed["initial_opacity"] = dialog.windowOpacity()
                observed["initial_center_offset"] = (
                    dialog.frameGeometry().center()
                    - window.frameGeometry().center()
                )
                QTimer.singleShot(
                    INTERNAL_DIALOG_REVEAL_DELAY_MS + 20,
                    inspect_and_cancel,
                )
            except BaseException as error:
                callback_errors.append(error)
                reject_pending_dialog()

        def inspect_and_cancel() -> None:
            dialog = None
            try:
                dialog = rejected_dialog()
                observed["visible"] = dialog.isVisible()
                observed["opacity"] = dialog.windowOpacity()
                observed["modality"] = dialog.windowModality()
                observed["on_screen"] = bool(
                    dialog.frameGeometry().intersects(
                        dialog.screen().availableGeometry()
                    )
                )
                observed["center_offset"] = (
                    dialog.frameGeometry().center()
                    - window.frameGeometry().center()
                )
                observed["default"] = dialog.defaultButton().text()
                observed["escape"] = dialog.escapeButton().text()
            except BaseException as error:
                callback_errors.append(error)
            finally:
                if dialog is not None and dialog.isVisible():
                    cancel_button = getattr(
                        dialog, "_rejected_stl_cancel_button", None
                    )
                    if cancel_button is not None:
                        cancel_button.click()
                    else:
                        dialog.reject()

        def reject_pending_dialog() -> None:
            for widget in self.app.topLevelWidgets():
                if (
                    isinstance(widget, QMessageBox)
                    and widget.objectName() == "rejectedStlConfirmationDialog"
                    and widget.isVisible()
                ):
                    widget.reject()

        watchdog = QTimer(window)
        watchdog.setSingleShot(True)
        watchdog.setInterval(5000)

        def cancel_if_still_open() -> None:
            if any(
                isinstance(widget, QMessageBox)
                and widget.objectName() == "rejectedStlConfirmationDialog"
                and widget.isVisible()
                for widget in self.app.topLevelWidgets()
            ):
                callback_errors.append(
                    TimeoutError("STL-Bestätigungsdialog wurde nicht geschlossen.")
                )
                reject_pending_dialog()

        watchdog.timeout.connect(cancel_if_still_open)

        try:
            watchdog.start()
            QTimer.singleShot(0, inspect_concealed_position)
            self.assertFalse(window._ask_rejected_stl_confirmation())
            watchdog.stop()
            if callback_errors:
                raise callback_errors[0]

            initial_center_offset = observed.pop("initial_center_offset")
            self.assertLessEqual(abs(initial_center_offset.x()), 3)
            self.assertLessEqual(abs(initial_center_offset.y()), 3)
            center_offset = observed.pop("center_offset")
            self.assertLessEqual(abs(center_offset.x()), 3)
            self.assertLessEqual(abs(center_offset.y()), 3)
            self.assertEqual(
                observed,
                {
                    "initial_opacity": 0.0,
                    "visible": True,
                    "opacity": 1.0,
                    "modality": Qt.WindowModality.WindowModal,
                    "on_screen": True,
                    "default": "Abbrechen",
                    "escape": "Abbrechen",
                },
            )
        finally:
            watchdog.stop()
            reject_pending_dialog()
            window.close()
            window.deleteLater()
            self.app.processEvents()

    def test_tolerated_manifold_stl_reaches_slicer_gate_with_file_actions(self) -> None:
        source = self.fixture_root / "test_model_manifold.stl"
        before = hashlib.sha256(source.read_bytes()).hexdigest()
        window = self.window()
        try:
            window.resize(1530, 1392)
            window.show()
            self.app.processEvents()
            self.assertTrue(window.drop_zone.set_file(source))
            self.wait_for_stl_result(window)
            for _ in range(6):
                self.app.processEvents()
            result = window.stl_validation_result
            assert result is not None
            self.assertTrue(result.valid, result.technical_summary)
            self.assertIs(window.workflow.stage, WorkflowStage.DISCOVERING_SLICER)
            self.assertIsNone(window.current_gcode_path)
            self.assertIsNone(window.analysis_snapshot)
            self.assertIsNotNone(window.source_artifact)
            self.assertTrue(window.ready_grid.isHidden())
            self.assertEqual(window.drop_zone.status_value_label.text(), "STL-Prüfung abgeschlossen")
            self.assertFalse(window.drop_zone.browse_button.isHidden())
            self.assertFalse(window.drop_zone.reload_button.isHidden())
            self.assertFalse(window.drop_zone.remove_button.isHidden())
            self.assertTrue(window.drop_zone.browse_button.isEnabled())
            self.assertTrue(window.drop_zone.reload_button.isEnabled())
            self.assertTrue(window.drop_zone.remove_button.isEnabled())
            self.assertEqual(window.drop_zone.browse_button.text(), "Andere STL auswählen")
            self.assertEqual(window.drop_zone.reload_button.text(), "STL neu einlesen")
            self.assertEqual(window.drop_zone.remove_button.text(), "STL entfernen")
            self.assertEqual(len(result.warning_issues), 1)
            self.assertTrue(window.drop_zone.property("completed"))
            self.assertTrue(window.drop_zone.prompt_label.isHidden())
            self.assertFalse(window.stl_validation_message.isHidden())
            self.assertFalse(window.stl_validation_warning_message.isHidden())
            self.assertEqual(
                window.stl_validation_message.property("severity"),
                "success",
            )
            self.assertEqual(
                window.stl_validation_warning_message.property("severity"),
                "warning",
            )
            self.assertIn(
                "Das Mesh ist geschlossen und topologisch manifold.",
                window.stl_validation_message.text(),
            )
            self.assertIn(
                "Es wurden keine offenen Kanten erkannt.",
                window.stl_validation_message.text(),
            )
            feedback = window.stl_validation_feedback
            success_notice = window.stl_validation_message.text()
            warning_notice = window.stl_validation_warning_message.text()
            self.assertEqual(feedback.heading.icon.text(), "✓")
            self.assertEqual(feedback.heading.title.text(), "STL-Datei akzeptiert")
            self.assertNotIn("<b>", success_notice)
            self.assertIn("&#x2022;", success_notice)
            self.assertNotIn("- Das Mesh", success_notice)
            self.assertEqual(feedback.warning_heading.icon.text(), "ⓘ")
            self.assertEqual(
                feedback.warning_heading.title.text(), "Kleine Geometrieabweichungen"
            )
            self.assertNotIn("<b>", warning_notice)
            self.assertIn("&#x2022;", warning_notice)
            self.assertNotIn("- Es wurden", warning_notice)
            self.assertIn(
                "Es wurden geringfügige lokale Flächenüberschneidungen erkannt.",
                warning_notice,
            )
            self.assertIn(
                "zuverlässig verarbeitbaren G‑Code",
                warning_notice,
            )
            self.assertIn(
                "Ein Pre-Slice prüft im letzten Vorbereitungsschritt zusätzlich",
                warning_notice,
            )
            margins = window.stl_validation_message.contentsMargins()
            self.assertEqual(
                (margins.left(), margins.top(), margins.right(), margins.bottom()),
                (0, 0, 0, 0),
            )
            self.assertEqual(
                window.source_group.summary_note_label.text(),
                "mit Geometriehinweis",
            )
            # The nested SectionCard header is intentionally replaced by the
            # integrated step introduction.  The geometry qualifier remains
            # visible in the warning notice instead of a second card header.
            self.assertFalse(window.source_group.summary_note_label.isVisibleTo(window))
            self.assertTrue(window.source_group.header.isHidden())
            self.assertEqual(
                window.preparation_step_state_labels[0].text(),
                "Abgeschlossen",
            )
            self.assertTrue(window.preparation_step_state_labels[0].isHidden())
            self.assertEqual(
                window.preparation_step_selector_icons[0].text(),
                "",
            )
            self.assertEqual(
                window.preparation_step_selector_icons[0].property("state"),
                "complete",
            )
            drop_zone = window.drop_zone
            self.assertGreaterEqual(
                drop_zone.height(),
                drop_zone.minimumHeight(),
            )
            for upper, lower in zip(
                (drop_zone.info_widget, drop_zone.actions_widget),
                (drop_zone.actions_widget,),
            ):
                self.assertLess(
                    upper.geometry().bottom(),
                    lower.geometry().top(),
                )
            self.assertLess(drop_zone.geometry().bottom(), feedback.geometry().top())
            blocks = (
                window.stl_validation_details_toggle,
                window.stl_validation_message,
                feedback.warning_heading,
                window.stl_validation_warning_message,
            )
            for upper, lower in zip(blocks, blocks[1:]):
                self.assertLess(
                    upper.geometry().bottom(),
                    lower.geometry().top(),
                )
            self.assertLessEqual(
                drop_zone.actions_widget.geometry().bottom(),
                drop_zone.rect().bottom()
                - drop_zone.root_layout.contentsMargins().bottom(),
            )
            self.assertEqual(hashlib.sha256(source.read_bytes()).hexdigest(), before)
        finally:
            window.close()
            window.deleteLater()
            self.app.processEvents()

    def test_fully_valid_stl_shows_green_confirmation_below_file_facts(self) -> None:
        source = self.fixture_root / "known_valid_tetrahedron_ascii.stl"
        window = self.window()
        try:
            self.assertTrue(window.drop_zone.set_file(source))
            self.wait_for_stl_result(window)

            self.assertFalse(window.stl_validation_message.isHidden())
            self.assertEqual(
                window.stl_validation_message.property("severity"),
                "success",
            )
            self.assertIn(
                "für die weitere Verarbeitung geeignet",
                window.stl_validation_message.text(),
            )
            self.assertIs(
                window.stl_validation_message.parent(),
                window.stl_validation_feedback,
            )
            self.assertTrue(window.drop_zone.property("completed"))
            self.assertTrue(window.drop_zone.prompt_label.isHidden())
            self.assertTrue(window.source_guide_row.isHidden())
        finally:
            window.close()
            window.deleteLater()
            self.app.processEvents()

    def test_notice_headings_share_disclosure_row_and_follow_open_details(self) -> None:
        window = self.window()
        window.show()
        try:
            for filename, title, icon in (
                ("known_valid_tetrahedron_ascii.stl", "STL-Datei akzeptiert", "✓"),
                ("test_model_manifold.stl", "STL-Datei akzeptiert", "✓"),
                ("test_model_non_manifold.stl", "STL-Geometrie prüfen", "×"),
            ):
                with self.subTest(source=filename):
                    self.assertTrue(window.drop_zone.set_file(self.fixture_root / filename))
                    self.wait_for_stl_result(window)
                    feedback = window.stl_validation_feedback
                    self.assertEqual(feedback.heading.title.text(), title)
                    self.assertEqual(feedback.heading.icon.text(), icon)
                    for width in (760, 1000, 1440):
                        with self.subTest(width=width):
                            window.resize(width, 1100)
                            for _ in range(4):
                                self.app.processEvents()
                            heading = feedback.heading
                            toggle = feedback.details_toggle
                            body = feedback.message
                            closed_height = window.preparation_tabs.height()
                            self.assertLess(heading.geometry().right(), toggle.geometry().left())
                            self.assertLessEqual(
                                abs(heading.geometry().center().y() - toggle.geometry().center().y()),
                                2,
                            )
                            self.assertGreater(body.geometry().top(), toggle.geometry().bottom())
                            self.assertLess(body.geometry().left(), toggle.geometry().left())
                            self.assertGreaterEqual(body.geometry().right(), toggle.geometry().right())
                            self.assertLessEqual(body.geometry().top() - heading.geometry().bottom(), 10)
                            self.assertGreaterEqual(body.height(), body.heightForWidth(body.width()))

                            QTest.mouseClick(toggle, Qt.MouseButton.LeftButton)
                            for _ in range(4):
                                self.app.processEvents()
                            self.assertTrue(toggle.isChecked())
                            self.assertTrue(feedback.details.isVisibleTo(window))
                            self.assertLess(toggle.geometry().bottom(), feedback.details.geometry().top())
                            self.assertLess(feedback.details.geometry().bottom(), heading.geometry().top())
                            self.assertLess(heading.geometry().bottom(), body.geometry().top())
                            self.assertGreater(window.preparation_tabs.height(), closed_height)
                            self.assertLessEqual(body.geometry().bottom(), feedback.rect().bottom())

                            QTest.mouseClick(toggle, Qt.MouseButton.LeftButton)
                            for _ in range(4):
                                self.app.processEvents()
                            self.assertFalse(toggle.isChecked())
                            self.assertTrue(feedback.details.isHidden())
                            self.assertEqual(window.preparation_tabs.height(), closed_height)
                            self.assertLess(heading.geometry().right(), toggle.geometry().left())
                            if not feedback.warning_message.isHidden():
                                self.assertLess(
                                    body.geometry().bottom(), feedback.warning_heading.geometry().top()
                                )
                                self.assertLessEqual(
                                    feedback.warning_message.geometry().top()
                                    - feedback.warning_heading.geometry().bottom(),
                                    5,
                                )
                                self.assertLessEqual(
                                    feedback.warning_message.geometry().bottom(), feedback.rect().bottom()
                                )
        finally:
            window.close()
            window.deleteLater()
            self.app.processEvents()

    def test_clearing_geometry_notice_also_clears_header_qualifier(self) -> None:
        window = self.window()
        try:
            window.stl_validation_message.setText("Geometriehinweis")
            window.stl_validation_message.show()
            window.source_group.set_summary_note(
                "mit Geometriehinweis",
                severity="warning",
            )

            window._clear_stl_validation_details()

            self.assertEqual(window.stl_validation_message.text(), "")
            self.assertTrue(window.stl_validation_message.isHidden())
            self.assertEqual(window.stl_validation_warning_message.text(), "")
            self.assertTrue(window.stl_validation_warning_message.isHidden())
            self.assertTrue(window.stl_validation_feedback.heading.isHidden())
            self.assertTrue(window.stl_validation_feedback.warning_heading.isHidden())
            self.assertTrue(window.stl_validation_feedback.isHidden())
            self.assertEqual(window.source_group.summary_note_label.text(), "")
            self.assertTrue(window.source_group.summary_note_label.isHidden())
        finally:
            window.close()
            window.deleteLater()
            self.app.processEvents()

    def test_invalid_stl_can_be_replaced_by_dropping_a_valid_stl(self) -> None:
        invalid = self.fixture_root / "test_model_non_manifold.stl"
        valid = self.fixture_root / "known_valid_tetrahedron_ascii.stl"
        window = self.window()
        try:
            self.assertTrue(window.drop_zone.set_file(invalid))
            self.wait_for_stl_result(window)
            self.assertIs(window.workflow.stage, WorkflowStage.SOURCE_INVALID)

            self.assertTrue(self.drop_file(window, valid))
            self.wait_for_stl_result(window)
            result = window.stl_validation_result
            self.assertIsNotNone(result)
            assert result is not None
            self.assertEqual(result.source_artifact.original_path, valid.resolve())
            self.assertTrue(result.valid, result.technical_summary)
            self.assertIs(window.workflow.stage, WorkflowStage.DISCOVERING_SLICER)
            self.assertEqual(window.drop_zone.selected_path, valid.resolve())
        finally:
            window.close()
            window.deleteLater()
            self.app.processEvents()

    def test_rejected_stl_reload_runs_a_fresh_validation(self) -> None:
        source = self.fixture_root / "test_model_non_manifold.stl"
        window = self.window()
        try:
            self.assertTrue(window.drop_zone.set_file(source))
            self.wait_for_stl_result(window)
            first_result = window.stl_validation_result
            first_request_id = window._stl_validation_request_id
            self.assertIs(window.workflow.stage, WorkflowStage.SOURCE_INVALID)

            window.drop_zone.reload_button.click()

            self.assertGreater(window._stl_validation_request_id, first_request_id)
            self.wait_for_stl_result(window)
            self.assertIsNot(window.stl_validation_result, first_result)
            self.assertIs(window.workflow.stage, WorkflowStage.SOURCE_INVALID)
            self.assertEqual(window.drop_zone.selected_path, source.resolve())
            self.assertTrue(window.drop_zone.prompt_label.isHidden())
            self.assertFalse(window.drop_zone.remove_button.isHidden())
        finally:
            window.close()
            window.deleteLater()
            self.app.processEvents()

    def test_removing_rejected_stl_restores_complete_initial_overview(self) -> None:
        source = self.fixture_root / "test_model_non_manifold.stl"
        window = self.window()
        try:
            self.assertTrue(window.drop_zone.set_file(source))
            self.wait_for_stl_result(window)
            self.assertIs(window.workflow.stage, WorkflowStage.SOURCE_INVALID)
            self.assertFalse(window.drop_zone.remove_button.isHidden())

            window.drop_zone.remove_button.click()
            self.app.processEvents()

            self.assertIs(window.workflow.stage, WorkflowStage.WAITING_FOR_SOURCE)
            self.assertIsNone(window.current_source_path)
            self.assertIsNone(window.current_source_kind)
            self.assertIsNone(window.source_artifact)
            self.assertIsNone(window.stl_validation_result)
            self.assertIsNone(window.drop_zone.selected_path)
            self.assertIsNone(window.drop_zone.selected_kind)
            self.assertEqual(
                window.drop_zone.prompt_label.text(),
                window.drop_zone.EMPTY_PROMPT,
            )
            self.assertFalse(window.drop_zone.prompt_label.isHidden())
            self.assertTrue(window.drop_zone.info_widget.isHidden())
            self.assertFalse(window.drop_zone.browse_button.isHidden())
            self.assertTrue(window.drop_zone.reload_button.isHidden())
            self.assertTrue(window.drop_zone.remove_button.isHidden())
            self.assertEqual(
                window.drop_zone.browse_button.text(),
                "STL auswählen …",
            )
            self.assertTrue(window.stl_validation_message.isHidden())
            self.assertTrue(window.stl_validation_details_toggle.isHidden())
            self.assertFalse(window.source_guide_row.isHidden())
            self.assertEqual(window.source_group.summary_label.text(), "")
            self.assertEqual(window.source_group.summary_note_label.text(), "")
            self.assertTrue(window.source_group.isChecked())
            self.assertFalse(window.source_group.content_widget.isHidden())
            self.assertFalse(window.slicer_group.isVisibleTo(window))
            self.assertEqual(window.preparation_tabs.currentIndex(), 0)
            self.assertTrue(window.ready_grid.isHidden())
            self.assertEqual(
                window.status_label.text(),
                "Bitte STL auswählen",
            )
        finally:
            window.close()
            window.deleteLater()
            self.app.processEvents()

    def test_unexpected_stl_parser_failure_restores_drop_overview(self) -> None:
        class FailingValidationService:
            def validate(self, *_args, **_kwargs):
                raise OSError("kontrollierter Lesefehler")

        source = self.fixture_root / "known_valid_tetrahedron_ascii.stl"
        window = MainWindow(
            user_settings_path=self.root / "settings.json",
            enable_update_check=False,
            stl_validation_service=FailingValidationService(),
        )
        try:
            self.assertTrue(window.drop_zone.set_file(source))
            self.wait_for_stage(window, WorkflowStage.SOURCE_INVALID)
            self.assertIsNone(window.stl_validation_result)
            self.assertEqual(
                window.drop_zone.prompt_label.text(),
                window.drop_zone.EMPTY_PROMPT,
            )
            self.assertTrue(window.drop_zone.prompt_label.isHidden())
            self.assertFalse(window.drop_zone.info_widget.isHidden())
            self.assertTrue(window.source_progress_bar.isHidden())
            self.assertEqual(
                window.source_progress_status_label.text(),
                "STL-Prüfung fehlgeschlagen",
            )
            self.assertFalse(window.drop_zone.browse_button.isHidden())
            self.assertFalse(window.drop_zone.reload_button.isHidden())
            self.assertEqual(
                window.stl_validation_message.property("severity"),
                "error",
            )
            self.assertIn(
                "nicht vollständig und sicher gelesen",
                window.stl_validation_message.text(),
            )
            self.assertEqual(
                window.stl_validation_feedback.heading.title.text(),
                "STL-Datei konnte nicht geprüft werden",
            )
            self.assertEqual(window.stl_validation_feedback.heading.icon.text(), "×")
        finally:
            window.close()
            window.deleteLater()
            self.app.processEvents()


if __name__ == "__main__":
    unittest.main()
