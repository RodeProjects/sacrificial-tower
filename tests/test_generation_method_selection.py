from __future__ import annotations

import os
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, PropertyMock, patch

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "src"))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("COOLING_TOWER_DISABLE_SLICER_DISCOVERY", "1")

from PySide6.QtCore import QPoint, QRect, Qt
from PySide6.QtGui import QFontDatabase
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

from cooling_tower.gui.background_jobs import JobKind
from cooling_tower.gui.generation_session import GenerationMode
from cooling_tower.gui.main_window import MainWindow
from cooling_tower.gui.widgets import SectionCard
from cooling_tower.gui.widgets.preparation_controls import _PreparationState
from cooling_tower.models import SourceArtifact, SourceKind
from cooling_tower.preview import PreviewState
from gui_lifecycle import dispose_test_widget


class GenerationMethodSelectionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.app = QApplication.instance() or QApplication([])
        cls._font_ids = []
        # Windows offscreen sessions do not always discover system fonts.
        for name in ("segoeui.ttf", "seguisym.ttf"):
            path = Path(os.environ.get("WINDIR", "C:/Windows")) / "Fonts" / name
            if path.is_file():
                font_id = QFontDatabase.addApplicationFont(str(path))
                if font_id >= 0:
                    cls._font_ids.append(font_id)

    @classmethod
    def tearDownClass(cls) -> None:
        for font_id in cls._font_ids:
            QFontDatabase.removeApplicationFont(font_id)
        cls.app.processEvents()

    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.window = MainWindow(
            user_settings_path=Path(self.temporary.name) / "settings.json",
            enable_update_check=False,
            enable_startup_slicer_discovery=False,
        )
        self.window.show()
        self.app.processEvents()

    def tearDown(self) -> None:
        dispose_test_widget(self.window)
        self.app.processEvents()
        self.temporary.cleanup()

    def finish_preparation(self) -> None:
        workflow = self.window.workflow
        workflow.set_slicer_step_visible(True)
        workflow.source_validation_succeeded("modell.stl", analysis_complete=True)
        workflow.slicer_succeeded("Testslicer")
        workflow.complete_preparation()
        self.app.processEvents()

    def test_both_methods_require_source_slicer_and_preparation_confirmation(self) -> None:
        window = self.window
        self.assertEqual(set(GenerationMode), {GenerationMode.AUTOMATIC, GenerationMode.MANUAL, GenerationMode.PREPROCESSOR})
        self.assertEqual(set(window.generation_sessions), set(GenerationMode))
        workflow = window.workflow
        workflow.set_slicer_step_visible(True)
        for stage in ("empty", "source", "slicer"):
            if stage == "source":
                workflow.source_validation_succeeded("modell.stl", analysis_complete=True)
            elif stage == "slicer":
                workflow.slicer_succeeded("Testslicer")
            with self.subTest(stage=stage), patch.object(window.manual_controller, "ensure_context") as prepare:
                for mode in GenerationMode:
                    window.select_generation_mode(mode)
                    self.assertIsNone(window.generation_mode)
                window.show_generation_method_selection()
                self.app.processEvents()
                self.assertTrue(window.generation_workspace.isHidden())
                self.assertTrue(window.footer.isHidden())
                self.assertFalse(window.automatic_generation_card.isEnabled())
                self.assertFalse(window.manual_generation_card.isEnabled())
                prepare.assert_not_called()
        workflow.complete_preparation()
        self.app.processEvents()
        self.assertTrue(window.generation_method_picker.isVisible())
        for mode in GenerationMode:
            with self.subTest(mode=mode), patch.object(window.manual_controller, "ensure_context"):
                window.select_generation_mode(mode)
                self.assertIs(window.generation_mode, mode)
                self.assertFalse(window.workflow_group.isVisible())
                self.assertTrue(window.preparation_open_button.isVisible())
                self.assertIs(window.window_pages.currentWidget(), window.main_surface)
                self.assertEqual(window.footer.isVisible(), mode is not GenerationMode.PREPROCESSOR)
                window.show_generation_method_selection()

    def test_startup_divider_and_overlay_shadow_preserve_brand_top_and_bottom_insets(self) -> None:
        window=self.window
        for width in (1450,720,1450):
            with self.subTest(width=width):
                window.resize(width,1000)
                for _ in range(6):self.app.processEvents()
                header=window.workflow_header
                title=window.title_label.mapTo(window,QPoint())
                subtitle=window.subtitle_label.mapTo(window,QPoint())
                caption=window.preparation_section_header.mapTo(window,QPoint())
                self.assertEqual(title.y(),header.edge_padding)
                self.assertEqual(caption.y()-subtitle.y()-window.subtitle_label.height(),header.edge_padding)
                self.assertTrue(header.separator.isVisible())
                self.assertEqual(header.separator.height(),1)
                self.assertEqual(header.separator.y()+1,window.main_header.height())
                shadow=header.divider_shadow
                self.assertIs(shadow.parentWidget(),window.centralWidget())
                self.assertEqual(shadow.mapTo(window,QPoint()).y(),caption.y())
                self.assertEqual(shadow.width(),window.width())
                self.assertEqual(shadow.height(),8)
                self.assertTrue(shadow.testAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents))

    def test_preparation_surface_has_no_outer_frame_and_touches_header_and_window_edges(self) -> None:
        window=self.window
        for prepared in (False,True):
            if prepared:
                self.finish_preparation()
                window.show_preparation_workspace()
            for width,height in ((1450,1000),(720,1000),(720,500),(1450,1000)):
                with self.subTest(prepared=prepared,width=width,height=height):
                    window.resize(width,height)
                    for _ in range(6):self.app.processEvents()
                    card=window.workflow_group
                    scroll=window.preparation_workspace_scroll if prepared else window.settings_scroll
                    self.assertEqual(card.mapTo(window,QPoint()).x(),0)
                    self.assertEqual(card.width(),scroll.viewport().width())
                    self.assertEqual(card.contentsRect(),card.rect())
                    self.assertEqual(window.preparation_section_header.width(),card.width())
                    self.assertEqual(window.preparation_section_header.mapTo(window,QPoint()).y(),window.main_header.height())
                    self.assertTrue(window.footer.isHidden())
                    self.assertEqual(scroll.horizontalScrollBar().maximum(),0)
                    image=card.grab().toImage()
                    self.assertEqual(image.pixelColor(0,1),image.pixelColor(image.width()//2,1))
                    self.assertEqual(image.pixelColor(0,image.height()-1),image.pixelColor(image.width()//2,image.height()-1))
                    scroll.verticalScrollBar().setValue(0)

    def test_confirmation_reveals_only_method_selection(self) -> None:
        window = self.window
        self.assertFalse(window.main_header.property("preparationConfirmed"))
        self.assertTrue(window.generation_workspace.isHidden())
        self.assertFalse(window.automatic_generation_card.isEnabled())
        self.assertFalse(window.manual_generation_card.isEnabled())
        window.automatic_generation_card.click()
        self.assertIsNone(window.generation_mode)
        self.finish_preparation()
        self.assertTrue(window.main_header.property("preparationConfirmed"))
        header_image = window.main_header.grab().toImage()
        separator = window.workflow_header.separator
        separator_y = separator.mapTo(window.main_header, QPoint()).y()
        self.assertEqual(separator.height(), 1)
        self.assertEqual(separator_y, window.preparation_open_button.height() - 1)
        self.assertEqual(header_image.pixelColor(header_image.width() // 2, separator_y).name(), "#bac7d4")
        self.assertIs(window.workflow_header.divider_shadow.parentWidget(),window.centralWidget())
        self.assertTrue(window.workflow_header.divider_shadow.isVisible())
        self.assertTrue(window.workflow_group.isChecked())
        self.assertFalse(window.workflow_group.isCheckable())
        self.assertTrue(window.generation_method_picker.isVisible())
        self.assertTrue(window.header_method_selection.isHidden())
        self.assertTrue(window.header_workflow_actions.isHidden())
        self.assertTrue(window.ready_grid.isHidden())
        self.assertTrue(window.manual_generation_panel.isHidden())
        self.assertTrue(window.footer.isVisible())
        self.assertTrue(window.generation_method_navigation.isHidden())
        window.automatic_generation_card.click()
        self.app.processEvents()
        self.assertIs(window.generation_mode, GenerationMode.AUTOMATIC)
        self.assertTrue(window.ready_grid.isVisible())
        self.assertTrue(window.footer.isVisible())
        self.assertTrue(window.generation_method_picker.isHidden())
        self.assertTrue(window.header_method_selection.isVisible())
        self.assertTrue(window.automatic_method_button.isChecked())
        self.assertEqual(window.header_method_selection.heading.text(), "Erstellungsmethode")

    def test_return_and_manual_visit_preserve_unexported_automatic_tower(self) -> None:
        window = self.window
        self.finish_preparation()
        window.automatic_generation_card.click()
        window.target_time_spin.setValue(window.target_time_spin.value() + 2)
        artifact = Path(self.temporary.name) / "automatic.stl"
        artifact.write_text("automatic tower", encoding="utf-8")
        dispose = Mock(side_effect=lambda: artifact.unlink())
        preview = SimpleNamespace(
            request_signature="automatic", artifact_sha256="auto-sha", dispose=dispose
        )
        window.current_preview = preview
        window.preview_state = PreviewState.CURRENT
        original_value = window.target_time_spin.value()
        original_request_id = window._preview_request_id
        window._joint_slices_completed = 6
        original_scene = window.preview_dialog.canvas.scene
        with patch.object(window, "_export_block_reason", return_value=None):
            window.manual_method_button.click()
            self.assertTrue(window.manual_generation_panel.isVisible())
            self.assertTrue(window.ready_grid.isHidden())
            self.assertTrue(window.footer.isVisible())
            window.automatic_method_button.click()
            window._refresh_phase17_actions()
        self.assertIs(window.current_preview, preview)
        self.assertIs(window.preview_state, PreviewState.CURRENT)
        self.assertEqual(window.target_time_spin.value(), original_value)
        self.assertEqual(window._joint_slices_completed, 6)
        self.assertEqual(window._preview_request_id, original_request_id)
        self.assertIs(window.preview_dialog.canvas.scene, original_scene)
        self.assertTrue(window.export_button.isEnabled())
        self.assertTrue(artifact.exists())
        dispose.assert_not_called()

    def test_result_hint_and_header_navigation_preserve_automatic_result(self) -> None:
        window = self.window
        self.finish_preparation()
        window.automatic_generation_card.click()
        preview = SimpleNamespace(
            request_signature="automatic", artifact_sha256="auto-sha", dispose=Mock()
        )
        window.current_preview = preview
        window.preview_state = PreviewState.CURRENT
        window._joint_slices_completed = 6
        original_value = window.target_time_spin.value()
        original_request_id = window._preview_request_id
        panel = window.joint_generation_dialog
        panel.begin(10, .2, 6, 10)
        panel.start_slice(6, 10)
        panel.set_achieved(9.8)
        panel.mark_finished(paused=True, can_continue=True)
        self.assertFalse(hasattr(panel, "manual_creation_button"))
        self.assertIn("manuellen Modus", panel.manual_mode_hint.text())
        with patch.object(window, "_export_block_reason", return_value=None), \
             patch.object(window.manual_controller, "ensure_context") as prepare:
            for kind in (JobKind.PREVIEW, JobKind.EXPORT):
                with self.subTest(active_job=kind), patch.object(
                    window.background_job_manager, "has_active",
                    side_effect=lambda requested, active=kind: requested is active,
                ):
                    window._refresh_workflow_navigation_actions()
                    self.assertFalse(window.manual_method_button.isEnabled())
                    window.manual_method_button.click()
                    self.assertIs(window.generation_mode, GenerationMode.AUTOMATIC)
            window._refresh_workflow_navigation_actions()
            self.assertTrue(window.manual_method_button.isEnabled())
            window.manual_method_button.click()
            self.app.processEvents()
            prepare.assert_called_once_with()
            self.assertIs(window.generation_mode, GenerationMode.MANUAL)
            self.assertTrue(window.manual_generation_panel.isVisible())
            self.assertTrue(window.ready_grid.isHidden())
            self.assertIs(window.window_pages.currentWidget(), window.main_surface)
            window.automatic_method_button.click()
        self.assertIs(window.current_preview, preview)
        self.assertIs(window.preview_state, PreviewState.CURRENT)
        self.assertEqual(window.target_time_spin.value(), original_value)
        self.assertEqual(window._preview_request_id, original_request_id)
        self.assertEqual(window._joint_slices_completed, 6)
        self.assertFalse(panel.manual_mode_hint.isHidden())
        self.assertTrue(window.export_button.isEnabled())
        preview.dispose.assert_not_called()

    def test_result_actions_fit_on_both_sides_of_column_breakpoint(self) -> None:
        window = self.window
        self.finish_preparation()
        window.automatic_generation_card.click()
        panel = window.joint_generation_dialog
        panel.begin(10, .2, 6, 10)
        panel.start_slice(6, 10)
        panel.set_achieved(9.8)
        column_modes = set()
        for paused in (True, False):
            panel.mark_finished(paused=paused, can_continue=paused)
            for width in (2200, 1600, 1200, 1100, 1060, 1040, 1000, 720, 1600):
                with self.subTest(paused=paused, width=width):
                    window.resize(width, 1000)
                    for _ in range(5):
                        self.app.processEvents()
                    row = panel.result_actions
                    buttons = ([panel.continue_button] if paused else []) + [panel.export_button]
                    right = -1
                    bottoms = []
                    for button in buttons:
                        position = button.mapTo(row, QPoint())
                        self.assertGreater(position.x(), right)
                        right = position.x() + button.width() - 1
                        self.assertLess(right, row.width())
                        bottoms.append(position.y() + button.height())
                    self.assertLessEqual(max(bottoms) - min(bottoms), 1)
                    self.assertEqual(window.settings_scroll.horizontalScrollBar().maximum(), 0)
                    column_modes.add(window.ready_grid.is_two_column())
        self.assertEqual(column_modes, {True, False})

    def test_preparation_uses_body_hides_footer_and_preserves_header_and_current_method(self) -> None:
        window = self.window
        self.finish_preparation()
        window.automatic_generation_card.click()
        window.target_time_spin.setValue(window.target_time_spin.value() + 2)
        original_value = window.target_time_spin.value()
        for width, height in ((1450, 1000), (700, 700), (1450, 1000)):
            window.resize(width, height)
            window.preparation_open_button.click()
            for _ in range(3):
                self.app.processEvents()
            self.assertIs(window.window_pages.currentWidget(), window.preparation_workspace)
            self.assertEqual(window.preparation_workspace.size(), window.window_pages.size())
            self.assertLess(window.preparation_workspace.height(), window.centralWidget().height())
            self.assertTrue(window.workflow_group.isVisible())
            self.assertTrue(window.main_header.isVisible())
            self.assertTrue(window.footer.isHidden())
            self.assertTrue(window.main_header.isAncestorOf(window.preparation_open_button))
            self.assertTrue(window.main_header.isAncestorOf(window.header_method_selection))
            self.assertLess(window.main_header.geometry().bottom(), window.window_pages.y())
            self.assertFalse(window.workflow_group.isCheckable())
            self.assertTrue(window.workflow_group.toggle_button.isHidden())
            self.assertEqual(window.preparation_workspace_scroll.horizontalScrollBar().maximum(), 0)
            window.automatic_method_button.click()
            self.app.processEvents()
            self.assertIs(window.window_pages.currentWidget(), window.main_surface)
            self.assertTrue(window.footer.isVisible())
            self.assertTrue(window.ready_grid.isVisible())
            self.assertIs(window.generation_mode, GenerationMode.AUTOMATIC)
            self.assertEqual(window.target_time_spin.value(), original_value)

    def test_active_method_returns_from_preparation_without_changing_current_method(self) -> None:
        window = self.window
        self.finish_preparation()
        window.automatic_generation_card.click()
        window.show_generation_method_selection()
        self.assertTrue(window.generation_method_picker.isVisible())
        self.assertTrue(window.header_method_selection.isHidden())
        self.assertTrue(window.main_header.isVisible())
        self.assertTrue(window.footer.isVisible())
        self.assertIs(window.generation_mode, GenerationMode.AUTOMATIC)
        window.preparation_view_button.click()
        self.assertTrue(window.workflow_group.isVisible())
        self.assertTrue(window.header_method_selection.isVisible())
        window._on_workflow_stage_changed(window.workflow.stage.value)
        self.assertTrue(window.workflow_group.isVisible())
        self.assertTrue(window.generation_method_picker.isHidden())
        window.automatic_method_button.click()
        self.assertTrue(window.ready_grid.isVisible())
        self.assertIs(window.generation_mode, GenerationMode.AUTOMATIC)
        window.manual_method_button.click()
        with patch.object(window.manual_controller.panel, "select") as select:
            window.preparation_view_button.click()
            window.manual_method_button.click()
        select.assert_not_called()
        self.assertIs(window.generation_mode, GenerationMode.MANUAL)
        self.assertTrue(window.manual_generation_panel.isVisible())

    def test_preparation_always_hides_footer_and_closing_restores_each_method(self) -> None:
        window=self.window
        self.assertTrue(window.footer.isHidden())
        self.finish_preparation()
        for mode in GenerationMode:
            with self.subTest(mode=mode), patch.object(window.manual_controller,"ensure_context"):
                window.select_generation_mode(mode)
                self.assertEqual(window.footer.isVisible(), mode is not GenerationMode.PREPROCESSOR)
                window.show_preparation_workspace()
                self.app.processEvents()
                self.assertTrue(window.workflow_group.isVisible())
                self.assertTrue(window.footer.isHidden())
                window._on_workflow_stage_changed(window.workflow.stage.value)
                self.assertTrue(window.footer.isHidden())
                window._refresh_phase17_actions()
                self.assertTrue(window.footer.isHidden())
                window.close_preparation_workspace()
                self.app.processEvents()
                self.assertIs(window.generation_mode,mode)
                self.assertEqual(window.footer.isVisible(), mode is not GenerationMode.PREPROCESSOR)

    def test_manual_mode_only_shows_centered_red_notice_in_single_column_layout(self) -> None:
        window = self.window
        self.finish_preparation()
        window.automatic_generation_card.click()
        self.assertTrue(window.generation_method_navigation.isHidden())
        self.assertFalse(hasattr(window, "generation_method_label"))
        window.manual_method_button.click()
        for width, narrow in ((1400, False), (720, True), (1400, False), (720, True)):
            with self.subTest(width=width):
                window.resize(width, 1000)
                for _ in range(10):
                    self.app.processEvents()
                label = window.generation_method_recommendation
                self.assertEqual(label.isVisible(), narrow)
                self.assertEqual(window.generation_method_navigation.isVisible(), narrow)
                if narrow:
                    center = label.mapTo(window.centralWidget(), label.contentsRect().center())
                    self.assertLessEqual(abs(center.x() - window.centralWidget().rect().center().x()), 1)
                    self.assertEqual(label.palette().color(label.foregroundRole()).name(), "#b42318")
        window.automatic_method_button.click()
        self.assertTrue(window.generation_method_navigation.isHidden())

    def test_manual_settings_headers_share_advanced_settings_style_without_collapsing(self) -> None:
        window = self.window
        window.resize(1400, 1000)
        self.finish_preparation()
        window.automatic_generation_card.click()
        for _ in range(5):
            self.app.processEvents()
        automatic = window.geometry_group.header.grab().toImage()
        color = automatic.pixelColor(7, automatic.height() // 2)
        window.manual_method_button.click()
        for _ in range(5):
            self.app.processEvents()
        cards = window.manual_generation_panel.settings_content.findChildren(SectionCard)
        self.assertEqual(len(cards), 2)
        self.assertEqual(window.manual_generation_panel.settings_content.layout().spacing(), 0)
        for previous, following in zip(cards, cards[1:]):
            self.assertEqual(previous.geometry().bottom() + 1, following.y())
        for card in cards:
            with self.subTest(title=card.title_label.text()):
                self.assertFalse(card.isCheckable())
                self.assertTrue(card.toggle_button.isHidden())
                self.assertTrue(card.body_divider.isHidden())
                self.assertEqual(card.contentsRect().top(), 0)
                self.assertEqual(card.contentsRect().bottom(), card.height() - 1)
                rendered = card.header.grab().toImage()
                actual = rendered.pixelColor(7, rendered.height() // 2)
                for first, second in zip(color.getRgb()[:3], actual.getRgb()[:3]):
                    self.assertLessEqual(abs(first - second), 1)
                self.assertEqual(card.title_label.font().pointSizeF(), window.geometry_group.title_label.font().pointSizeF())
                QTest.mouseClick(card.header, Qt.MouseButton.LeftButton, pos=QPoint(8, 8))
                self.assertTrue(card.content_widget.isVisible())

    def test_header_anchors_facts_and_joins_method_heading_and_buttons_beside_menu(self) -> None:
        window = self.window
        self.finish_preparation()
        window.automatic_generation_card.click()
        window.resize(1450, 1000)
        header = window.workflow_header
        rows = (("Dateiname", "modell.stl"), ("Slicer", "Testslicer"),
                ("Maschinenprofil", "Maschine"), ("Filamentprofil", "Filament"),
                ("Prozessprofil", "Prozess"))
        header.set_facts(rows)
        for _ in range(4):
            self.app.processEvents()
        preparation = window.preparation_open_button
        selection = window.header_method_selection
        heading = selection.heading
        self.assertEqual([selection.buttons_layout.itemAt(i).widget().text() for i in range(3)],
            ["Postprozessor", "Iterativ", "Manuell"])
        automatic = window.automatic_method_button
        manual = window.manual_method_button
        menu = window.options_button
        self.assertEqual(preparation.mapTo(window.main_header, QPoint()), QPoint(0, 0))
        self.assertFalse(preparation.isAncestorOf(selection))
        previous_bottom = -1
        for name, value in rows:
            label = header.fact_labels[name]
            self.assertEqual(label.text(), value)
            self.assertGreater(label.mapTo(preparation, QPoint()).y(), previous_bottom)
            previous_bottom = label.mapTo(preparation, label.rect().bottomLeft()).y()
        method_rect = QRect(selection.mapTo(header, QPoint()), selection.size())
        menu_rect = QRect(menu.mapTo(header, QPoint()), menu.size())
        self.assertLess(method_rect.right(), menu_rect.left())
        self.assertEqual(method_rect.top(), 0)
        version_rect = QRect(window.version_label.mapTo(header, QPoint()), window.version_label.size())
        tools_rect = menu_rect.united(version_rect)
        self.assertLessEqual(abs(tools_rect.center().y() - method_rect.center().y()), 1)
        tools_center_x = (method_rect.right() + 1 + header.width() - 1) // 2
        self.assertLessEqual(abs(menu_rect.center().x() - tools_center_x), 1)
        self.assertLessEqual(abs(version_rect.center().x() - tools_center_x), 1)
        self.assertEqual(heading.height() + menu.height(), preparation.height())
        self.assertEqual(selection.height(), preparation.height())
        self.assertEqual(heading.text(), "Erstellungsmethode")
        self.assertTrue(heading.alignment() & Qt.AlignmentFlag.AlignHCenter)
        self.assertEqual(selection.layout().spacing(), 0)
        self.assertEqual(selection.buttons_layout.spacing(), 0)
        self.assertEqual(heading.geometry().bottom() + 1, automatic.y())
        self.assertEqual(automatic.y(), manual.y())
        self.assertEqual(automatic.geometry().right() + 1, manual.x())
        self.assertEqual(automatic.height(), menu.height())
        self.assertEqual(manual.height(), menu.height())
        self.assertLessEqual(abs(automatic.width() - manual.width()), 1)
        self.assertEqual(automatic.text(), "Iterativ")
        self.assertEqual(manual.text(), "Manuell")
        self.assertTrue(automatic.isChecked())
        self.assertFalse(manual.isChecked())
        self.assertFalse(automatic.font().bold())
        self.assertFalse(manual.font().bold())
        QTest.mouseClick(window.windowHandle(), Qt.MouseButton.LeftButton,
                         pos=manual.mapTo(window, manual.rect().center()))
        for _ in range(4):
            self.app.processEvents()
        self.assertIs(window.generation_mode, GenerationMode.MANUAL)
        self.assertTrue(manual.isChecked())
        self.assertFalse(automatic.isChecked())
        self.assertFalse(manual.hasFocus())
        self.assertEqual(manual.accessibleDescription(), "Aktive Methode")
        automatic.setFocus()
        QTest.keyClick(automatic, Qt.Key.Key_Space)
        self.app.processEvents()
        self.assertIs(window.window_pages.currentWidget(), window.main_surface)
        self.assertIs(window.generation_mode, GenerationMode.AUTOMATIC)
        self.assertTrue(automatic.isChecked())
        self.assertFalse(manual.isChecked())
        self.assertFalse(automatic.hasFocus())

    def test_header_centers_then_anchors_brand_and_leaves_space_empty_when_it_hides(self) -> None:
        window = self.window
        self.finish_preparation()
        window.automatic_generation_card.click()
        window.resize(2000, 1000)
        header = window.workflow_header
        rows = (("Dateiname", "modell.stl"), ("Slicer", "Anycubic Slicer Next 2.0.0.3"),
                ("Maschinenprofil", "Anycubic Kobra 3 V2 0.4 nozzle - (Settings v2)"),
                ("Filamentprofil", "PLA - Tecbears - Schwarz (matt)"),
                ("Prozessprofil", "0.20 mm Standard @Kobra 3 V2"))
        header.set_facts(rows)
        self.app.processEvents()
        preparation = window.preparation_open_button
        gap = header.grid.horizontalSpacing()
        card_width = preparation.preferred_width()
        right_width = header.right_widget.sizeHint().width()
        brand_width = header.brand_widget.sizeHint().width()
        centered_boundary = 2 * (max(card_width, right_width) + gap) + brand_width
        text_boundary = card_width + right_width + brand_width + 2 * gap
        anchored_width = (centered_boundary + text_boundary) // 2
        for width, state in ((centered_boundary + 20, "full"), (anchored_width, "full"),
                             (text_boundary, "full"), (text_boundary - 1, "brand_hidden"),
                             (720, "brand_hidden"),
                             (centered_boundary + 20, "full")):
            with self.subTest(width=width, state=state):
                header.setFixedWidth(width)
                for _ in range(5):
                    self.app.processEvents()
                self.assertEqual(header.layout_state, state)
                self.assertEqual(header.brand_widget.isVisible(), state == "full")
                self.assertTrue(preparation.status_label.isHidden())
                self.assertTrue(window.header_method_selection.isVisible())
                self.assertTrue(window.automatic_method_button.isVisible())
                self.assertTrue(window.manual_method_button.isVisible())
                self.assertTrue(window.options_button.isVisible())
                self.assertTrue(window.version_label.isVisible())
                self.assertEqual(preparation.mapTo(header, QPoint()), QPoint(0, 0))
                if state == "full":
                    brand_rect = QRect(header.brand_widget.mapTo(header, QPoint()), header.brand_widget.size())
                    self.assertEqual(brand_rect.x(), min(max((width - brand_width) // 2, preparation.width() + gap), width - right_width - gap - brand_width))
                    self.assertGreaterEqual(header.right_widget.x() - brand_rect.right() - 1, gap)
                    if width <= centered_boundary:
                        if card_width >= right_width:
                            self.assertEqual(brand_rect.x() - preparation.width(), gap)
                        else:
                            self.assertEqual(header.right_widget.x() - brand_rect.right() - 1, gap)
                    for label in (window.title_label, window.subtitle_label):
                        self.assertTrue(label.alignment() & Qt.AlignmentFlag.AlignHCenter)
                        self.assertFalse(label.wordWrap())
                for key, value in rows:
                    label = header.fact_labels[key]
                    self.assertTrue(label.isVisible())
                    self.assertEqual(label.text(), value)
                    self.assertGreaterEqual(label.height(), label.heightForWidth(label.width()))
                    rectangle = QRect(label.mapTo(preparation, QPoint()), label.size())
                    self.assertTrue(preparation.rect().contains(rectangle))

    def test_entire_preparation_facts_button_opens_preparation_and_supports_keyboard(self) -> None:
        window = self.window
        self.finish_preparation()
        window.automatic_generation_card.click()
        window.resize(1450, 1000)
        header = window.workflow_header
        header.set_facts((("Dateiname", "modell.stl"), ("Slicer", "Testslicer")))
        self.app.processEvents()
        preparation = window.preparation_open_button
        for child in (preparation._fact_keys["Dateiname"], header.fact_labels["Dateiname"], header.fact_labels["Slicer"]):
            header.set_facts((("Dateiname", "modell.stl"), ("Slicer", "Testslicer")))
            self.app.processEvents()
            point = child.mapTo(window, child.rect().center())
            QTest.mouseClick(window.windowHandle(), Qt.MouseButton.LeftButton, pos=point)
            self.assertIs(window.window_pages.currentWidget(), window.preparation_workspace)
            self.assertTrue(window.workflow_group.isVisible())
            window.automatic_method_button.click()
        preparation.setFocus()
        QTest.keyClick(preparation, Qt.Key.Key_Space)
        self.assertIs(window.window_pages.currentWidget(), window.preparation_workspace)
        self.assertTrue(window.main_header.isVisible())
        self.assertTrue(window.footer.isHidden())

    def test_header_publishes_all_facts_only_after_successful_final_confirmation(self) -> None:
        window = self.window
        window.current_source_path = Path(self.temporary.name) / "bestätigt.stl"
        window.current_source_path.write_text("solid test\nendsolid test\n", encoding="ascii")
        window.current_source_kind = SourceKind.STL
        window.source_artifact = SourceArtifact.capture(window.current_source_path)
        window.stl_validation_result = SimpleNamespace(valid=True)
        installation = SimpleNamespace(verified=True, display_name="Testslicer")
        for combo, text in ((window.machine_profile_combo, "Maschine"),
                            (window.filament_profile_combo, "Filament"),
                            (window.process_profile_combo, "Prozess")):
            combo.blockSignals(True)
            combo.addItem(text)
            combo.setCurrentIndex(combo.count() - 1)
            combo.blockSignals(False)
        state = _PreparationState(True, True, True, True, True, True, True)
        with patch.object(type(window), "selected_slicer_installation", new_callable=PropertyMock, return_value=installation), \
             patch.object(window, "_current_preparation_state", return_value=state), \
             patch.object(window, "_profile_matching_context", return_value=None):
            for file_confirmed, profiles_confirmed, complete, acknowledged in (
                (True, False, False, False), (True, True, True, False),
                (False, True, True, True), (True, False, True, True),
                (True, True, False, True), (True, True, True, True),
            ):
                with self.subTest(file=file_confirmed, profiles=profiles_confirmed, complete=complete, acknowledged=acknowledged), \
                     patch.object(window, "_source_step_is_complete", return_value=file_confirmed), \
                     patch.object(window, "_catalog_selection_is_confirmed", return_value=profiles_confirmed):
                    window.workflow.preparation_acknowledged = acknowledged
                    window._refresh_preparation_header_summary(complete)
                    self.app.processEvents()
                    facts = dict(window.workflow_header.facts)
                    confirmed = file_confirmed and profiles_confirmed and complete and acknowledged
                    self.assertEqual(len(facts), 5 if confirmed else 0)
                    self.assertEqual(window.preparation_open_button.property("confirmed"), confirmed)
                    self.assertEqual(window.workflow_header.facts_widget.isVisible(), confirmed)
                    if confirmed:
                        self.finish_preparation()
                        window.automatic_generation_card.click()
                        with patch.object(window, "_profile_matching_context", return_value=None):
                            for action in (window.show_preparation_workspace,
                                           window.show_generation_method_selection,
                                           window.close_preparation_workspace):
                                action()
                                window._update_preparation_requirements()
                                self.app.processEvents()
                                self.assertTrue(window.main_header.isVisible())
                                self.assertEqual(window.footer.isHidden(),action == window.show_preparation_workspace)
                                self.assertEqual(dict(window.workflow_header.facts), facts)
                                self.assertTrue(all(label.isVisible() for label in window.workflow_header.fact_labels.values()))

    def test_header_is_compact_aligned_and_keeps_version_directly_below_menu(self) -> None:
        window = self.window
        self.finish_preparation()
        window.automatic_generation_card.click()
        rows = (("Dateiname", "modell.stl"), ("Slicer", "Testslicer"),
                ("Maschinenprofil", "Maschine"), ("Filamentprofil", "Filament"),
                ("Prozessprofil", "Prozess"))
        for width in (1450, 720, 1450):
            window.resize(width, 1000)
            window.workflow_header.set_facts(rows)
            for _ in range(5):
                self.app.processEvents()
            preparation = window.preparation_open_button
            method = window.header_method_selection
            first = QRect(preparation.mapTo(window.main_header, QPoint()), preparation.size())
            second = QRect(method.mapTo(window.main_header, QPoint()), method.size())
            self.assertEqual(first.topLeft(), QPoint(0, 0))
            self.assertEqual(method.height(), preparation.height())
            self.assertLess(first.right(), second.left())
            if width == 1450:
                self.assertLess(preparation.height(), 100)
                self.assertLess(window.main_header.height(), 125)
            menu = QRect(window.options_button.mapTo(window.main_header, QPoint()), window.options_button.size())
            version = QRect(window.version_label.mapTo(window.main_header, QPoint()), window.version_label.size())
            self.assertLess(menu.bottom(), version.top())
            self.assertLessEqual(version.top() - menu.bottom(), 6)
            self.assertLessEqual(abs(menu.center().x() - version.center().x()), 1)
            self.assertEqual(preparation.toolTip(), "Datei- und Slicereinstellungen ändern")

    def test_header_centers_brand_in_tallest_area_and_uses_equal_outer_insets(self) -> None:
        window = self.window
        rows = (("Dateiname", "modell.stl"), ("Slicer", "Testslicer"),
                ("Maschinenprofil", "Maschine"), ("Filamentprofil", "Filament"),
                ("Prozessprofil", "Prozess"))
        for state, width in (("initial", 1400), ("ready", 1400),
                             ("return", 1400), ("narrow", 720), ("wrapped", 720)):
            with self.subTest(state=state):
                if state == "ready":
                    self.finish_preparation()
                    window.automatic_generation_card.click()
                elif state == "return":
                    window.show_generation_method_selection()
                if state != "initial":
                    shown_rows = rows if state != "wrapped" else tuple((key, value * 30) for key, value in rows)
                    window.workflow_header.set_facts(shown_rows)
                window.resize(width, 1000)
                for _ in range(5):
                    self.app.processEvents()
                header = window.workflow_header
                content_top = (window.window_pages.mapToGlobal(QPoint()).y()
                               - window.main_header.mapToGlobal(QPoint()).y()
                               + window.content_layout.contentsMargins().top())
                menu_rect = QRect(window.options_button.mapTo(window.main_header, QPoint()), window.options_button.size())
                version_rect = QRect(window.version_label.mapTo(window.main_header, QPoint()), window.version_label.size())
                if window.header_method_selection.isVisible():
                    method_rect = QRect(window.header_method_selection.mapTo(header, QPoint()), window.header_method_selection.size())
                    tools_rect = menu_rect.united(version_rect)
                    self.assertLessEqual(abs(tools_rect.center().y() - method_rect.center().y()), 1)
                    center_x = (method_rect.right() + header.width()) // 2
                    self.assertLessEqual(abs(menu_rect.center().x() - center_x), 1)
                    self.assertLessEqual(abs(version_rect.center().x() - center_x), 1)
                else:
                    self.assertEqual(header.width() - version_rect.right() - 1, header.edge_padding)
                    self.assertLessEqual(abs(menu_rect.center().x() - version_rect.center().x()), 1)
                    if state == "initial":
                        self.assertEqual(menu_rect.top(), header.edge_padding)
                    else:
                        tools_rect = menu_rect.united(version_rect)
                        self.assertLessEqual(abs(tools_rect.center().y() - header.separator.y() // 2), 1)
                tallest_bottom = version_rect.bottom() + 1
                if state != "initial":
                    tallest_bottom = max(tallest_bottom, window.preparation_open_button.height(),
                                         window.header_method_selection.height())
                else:
                    tallest_bottom = max(tallest_bottom, header.brand_widget.sizeHint().height() + header.edge_padding)
                    tallest_bottom += header.edge_padding
                self.assertEqual(header.height(), tallest_bottom)
                self.assertEqual(content_top - tallest_bottom, window.content_layout.contentsMargins().top())
                self.assertEqual(content_top - tallest_bottom, window.content_layout.contentsMargins().right())
                if header.brand_widget.isVisible():
                    title_rect = QRect(window.title_label.mapTo(window.main_header, QPoint()), window.title_label.size())
                    subtitle_rect = QRect(window.subtitle_label.mapTo(window.main_header, QPoint()), window.subtitle_label.size())
                    brand_rect = title_rect.united(subtitle_rect)
                    upper = brand_rect.top()
                    lower = (content_top if state == "initial" else tallest_bottom) - brand_rect.bottom() - 1
                    self.assertLessEqual(abs(upper - lower), 1)
                    if state == "initial":
                        self.assertLessEqual(abs(brand_rect.center().x() - header.rect().center().x()), 1)
                if state != "initial":
                    self.assertEqual(window.preparation_open_button.mapTo(window.main_header, QPoint()).y(), 0)
                    self.assertEqual(window.header_method_selection.mapTo(window.main_header, QPoint()).y(), 0)
                    self.assertEqual(header.separator.y(), window.preparation_open_button.height() - 1)
                    self.assertEqual(header.separator.height(), 1)
                    if window.header_method_selection.isVisible():
                        self.assertEqual(window.header_method_selection.geometry().bottom(), header.separator.y())

    def test_confirmation_fades_the_visible_body_into_method_selection(self) -> None:
        window = self.window
        workflow = window.workflow
        workflow.set_slicer_step_visible(True)
        workflow.source_validation_succeeded("modell.stl", analysis_complete=True)
        workflow.slicer_succeeded("Testslicer")
        state = _PreparationState(True, True, True, True, True, True, True)
        transition = window.preparation_transition
        transition.duration_ms = 550
        self.app.processEvents()
        original_geometry = window.window_pages.geometry()
        original_page = window.window_pages.currentWidget()
        with patch.object(window, "_current_preparation_state", return_value=state):
            window._finish_preparation()
        self.assertFalse(workflow.preparation_acknowledged)
        self.assertFalse(window.generation_method_picker.isVisible())
        self.assertFalse(window.footer.isVisible())
        self.assertTrue(transition._overlay.isVisible())
        self.assertFalse(transition._overlay.hasScaledContents())
        self.assertEqual(transition._overlay.size(), original_geometry.size())
        self.assertEqual(original_page.graphicsEffect().opacity(), 0.0)
        outgoing = transition._animation
        self.assertEqual(outgoing.duration(), 275)
        outgoing.setCurrentTime(outgoing.duration() // 2)
        self.app.processEvents()
        self.assertEqual(window.window_pages.geometry(), original_geometry)
        self.assertEqual(transition._overlay.size(), original_geometry.size())
        rendered = window.window_pages.grab().toImage()
        # The fading page must blend onto the light window surface, including
        # the bottom band previously exposed by resizing the snapshot.
        for y in (rendered.height() // 2, rendered.height() - 2):
            color = rendered.pixelColor(2, y)
            self.assertGreater(min(color.getRgb()[:3]), 220)
        outgoing.setCurrentTime(outgoing.duration())
        pause = transition._animation
        self.assertEqual(pause.duration(), 100)
        pause.setCurrentTime(pause.duration() - 1)
        self.assertFalse(workflow.preparation_acknowledged)
        self.assertEqual(window.window_pages.geometry(), original_geometry)
        self.assertEqual(transition._overlay.graphicsEffect().opacity(), 0.0)
        pause.setCurrentTime(pause.duration())
        self.assertTrue(workflow.preparation_acknowledged)
        self.assertIs(window.window_pages.currentWidget(), window.preparation_workspace)
        self.assertTrue(window.generation_method_picker.isVisible())
        self.assertTrue(window.main_header.isVisible())
        self.assertTrue(window.footer.isVisible())
        self.assertIsNone(transition._overlay)
        self.assertEqual(window.preparation_workspace.graphicsEffect().opacity(), 0.0)
        animation = transition._animation
        self.assertEqual(animation.duration(), 275)
        animation.setCurrentTime(20)
        self.assertGreater(window.preparation_workspace.graphicsEffect().opacity(), 0.0)
        animation.setCurrentTime(animation.duration())
        self.assertIsNone(transition._animation)
        self.assertIsNone(window.preparation_workspace.graphicsEffect())
        self.assertTrue(window.window_pages.isEnabled())
        # Opening preparation cancels a fade or pause without applying its
        # pending page change later.
        for stage in ("out", "pause"):
            with self.subTest(cancel_stage=stage):
                change = Mock(side_effect=window.show_generation_method_selection)
                transition.run(change)
                if stage == "pause":
                    outgoing = transition._animation
                    outgoing.setCurrentTime(outgoing.duration())
                window.show_preparation_workspace()
                self.assertIsNone(transition._animation)
                self.assertIsNone(window.preparation_workspace.graphicsEffect())
                self.assertTrue(window.window_pages.isEnabled())
                self.assertTrue(window.workflow_group.isVisible())
                QTest.qWait(transition.duration_ms + transition.pause_ms + 20)
                change.assert_not_called()
                self.assertTrue(window.workflow_group.isVisible())

    def test_header_wraps_long_unbroken_names_without_losing_confirmed_information(self) -> None:
        window = self.window
        self.finish_preparation()
        window.automatic_generation_card.click()
        window.resize(720, 1000)
        values = (("Dateiname", "langes_modell_" * 12 + ".stl"),
                  ("Maschinenprofil", "SehrLangerProfilname" * 12))
        header = window.workflow_header
        header.set_facts(values)
        for _ in range(6):
            self.app.processEvents()
        for key, text in values:
            label = header.fact_labels[key]
            self.assertEqual(label.text(), text)
            self.assertGreater(label.height(), label.fontMetrics().height() * 2)
            self.assertGreaterEqual(label.height(), label.heightForWidth(label.width()))
            self.assertTrue(header.facts_widget.rect().contains(QRect(label.mapTo(header.facts_widget, QPoint()), label.size())))
            self.assertTrue(window.main_header.isVisible())
        facts_rectangle = QRect(header.facts_widget.mapTo(header, QPoint()), header.facts_widget.size())
        self.assertTrue(header.rect().contains(facts_rectangle))
        self.assertLess(window.main_header.geometry().bottom(), window.window_pages.y())

    def test_session_results_and_export_status_remain_independent(self) -> None:
        window = self.window
        self.finish_preparation()
        automatic = window.generation_sessions[GenerationMode.AUTOMATIC]
        manual = window.generation_sessions[GenerationMode.MANUAL]
        auto_preview = SimpleNamespace(
            request_signature="auto", artifact_sha256="auto-sha", dispose=Mock()
        )
        manual_preview = SimpleNamespace(
            request_signature="manual", artifact_sha256="manual-sha", dispose=Mock()
        )
        window.current_preview = auto_preview
        window.preview_state = PreviewState.CURRENT
        window._last_exported_preview_identity = ("auto", "auto-sha")
        auto_export = object()
        window.last_export_result = auto_export
        manual.preview = manual_preview
        manual.preview_state = PreviewState.STALE
        manual.exported_preview_identity = ("manual", "manual-sha")
        manual.export_result = object()
        window.manual_generation_card.click()
        self.assertIs(window.current_preview, auto_preview)
        self.assertIs(automatic.export_result, auto_export)
        self.assertIs(manual.preview, manual_preview)
        self.assertIs(manual.preview_state, PreviewState.STALE)
        with patch.object(window, "_export_block_reason", return_value=None):
            window.automatic_method_button.click()
        self.assertTrue(window._current_preview_was_exported())
        self.assertFalse(window.export_button.isEnabled())
        window.close()
        auto_preview.dispose.assert_called_once()
        manual_preview.dispose.assert_called_once()

    def test_preparation_change_resets_selection_and_invalidates_both_towers(self) -> None:
        window = self.window
        self.finish_preparation()
        window.automatic_generation_card.click()
        disposals = []
        for mode in (GenerationMode.AUTOMATIC,GenerationMode.MANUAL):
            session=window.generation_sessions[mode]
            dispose = Mock()
            disposals.append(dispose)
            session.preview = SimpleNamespace(dispose=dispose)
            session.preview_state = PreviewState.CURRENT
        window._discard_generated_tower()
        window.workflow.reset()
        self.app.processEvents()
        self.assertIsNone(window.generation_mode)
        self.assertTrue(window.generation_workspace.isHidden())
        self.assertFalse(window.automatic_generation_card.isEnabled())
        self.assertFalse(window.manual_generation_card.isEnabled())
        self.assertIs(window.window_pages.currentWidget(), window.preparation_workspace)
        self.assertFalse(window.main_header.property("preparationConfirmed"))
        self.assertTrue(window.workflow_group.isVisible())
        self.assertTrue(window.preparation_open_button.isHidden())
        self.assertTrue(window.header_method_selection.isHidden())
        self.assertTrue(window.header_workflow_actions.isHidden())
        window.resize(1400, 1000)
        for _ in range(4):
            self.app.processEvents()
        header = window.workflow_header
        self.assertLessEqual(abs(header.brand_widget.geometry().center().x() - header.rect().center().x()), 1)
        window.close_preparation_workspace()
        self.assertIs(window.window_pages.currentWidget(), window.preparation_workspace)
        for session, dispose in zip((window.generation_sessions[GenerationMode.AUTOMATIC],window.generation_sessions[GenerationMode.MANUAL]), disposals):
            self.assertIsNone(session.preview)
            self.assertIs(session.preview_state, PreviewState.EMPTY)
            dispose.assert_called_once()
        self.finish_preparation()
        self.assertTrue(window.generation_method_picker.isVisible())

    def test_switch_is_locked_while_generating_or_exporting(self) -> None:
        window = self.window
        self.finish_preparation()
        window.automatic_generation_card.click()
        for kind in (JobKind.PREVIEW, JobKind.EXPORT):
            with self.subTest(kind=kind), patch.object(
                window.background_job_manager, "has_active", side_effect=lambda queried: queried is kind
            ):
                window._refresh_phase17_actions()
                self.assertFalse(window.automatic_method_button.isEnabled())
                self.assertFalse(window.manual_method_button.isEnabled())
                self.assertFalse(window.preparation_open_button.isEnabled())
                window.show_preparation_workspace()
                self.assertIs(window.window_pages.currentWidget(), window.main_surface)
                window.show_generation_method_selection()
                window.select_generation_mode(GenerationMode.MANUAL)
                self.assertIs(window.generation_mode, GenerationMode.AUTOMATIC)
        window._refresh_phase17_actions()
        self.assertTrue(window.automatic_method_button.isEnabled())
        self.assertTrue(window.manual_method_button.isEnabled())

    def test_cards_stack_and_whole_card_supports_mouse_and_keyboard(self) -> None:
        window = self.window
        self.finish_preparation()
        for width, columns in ((1400, 3), (1000, 2), (760, 1), (1400, 3)):
            window.resize(width, 850)
            self.app.processEvents()
            grid = window.generation_method_grid
            self.assertEqual(grid.column_count, columns)
            automatic_rect = window.automatic_generation_card.geometry()
            manual_rect = window.manual_generation_card.geometry()
            preprocessor_rect = window.preprocessor_generation_card.geometry()
            if columns >= 2:
                self.assertEqual(automatic_rect.top(), manual_rect.top())
                self.assertLess(automatic_rect.right(), manual_rect.left())
                if columns == 3:
                    self.assertEqual(preprocessor_rect.top(), automatic_rect.top())
                    self.assertLess(preprocessor_rect.right(), automatic_rect.left())
                else:
                    self.assertLess(preprocessor_rect.bottom(), automatic_rect.top())
                    self.assertEqual(preprocessor_rect.left(), automatic_rect.left())
                    self.assertEqual(preprocessor_rect.right(), manual_rect.right())
            else:
                self.assertLess(preprocessor_rect.bottom(), automatic_rect.top())
                self.assertLess(automatic_rect.bottom(), manual_rect.top())
            for card in (window.preprocessor_generation_card, window.automatic_generation_card, window.manual_generation_card):
                self.assertTrue(card.isVisible())
                self.assertLessEqual(card.geometry().right(), grid.width())
                self.assertLessEqual(card.geometry().bottom(), grid.height() - 1)
                self.assertLessEqual(card.action_label.geometry().bottom(), card.height())
        card = window.automatic_generation_card
        QTest.mouseClick(card, Qt.MouseButton.LeftButton, pos=card.title_label.geometry().center())
        self.assertIs(window.generation_mode, GenerationMode.AUTOMATIC)
        window.show_generation_method_selection()
        window.manual_generation_card.setFocus()
        QTest.keyClick(window.manual_generation_card, Qt.Key.Key_Space)
        self.assertIs(window.generation_mode, GenerationMode.MANUAL)
        self.assertTrue(window.manual_generation_panel.isVisible())

    def test_picker_is_centered_and_uses_side_space_before_stacking(self) -> None:
        window = self.window
        self.finish_preparation()
        heading = window.generation_method_heading
        self.assertEqual(heading.text(), "Wie soll der Kühlturm erstellt werden?")
        self.assertTrue(heading.alignment() & Qt.AlignmentFlag.AlignHCenter)
        for card in (window.automatic_generation_card, window.manual_generation_card):
            self.assertTrue(card.title_label.alignment() & Qt.AlignmentFlag.AlignHCenter)
        for width in (1800, 1400, 1060, 1000, 860, 760, 1800):
            with self.subTest(width=width):
                window.resize(width, 850)
                for _ in range(3):
                    self.app.processEvents()
                grid = window.generation_method_grid
                picker = window.generation_method_picker
                self.assertEqual(grid.width(), min(grid.maximumWidth(), picker.width()))
                left_space = grid.x()
                right_space = picker.width() - grid.geometry().right() - 1
                self.assertLessEqual(abs(left_space - right_space), 1)
                self.assertEqual(grid.column_count, grid.columns_for_width(picker.width()))
                if picker.width() <= grid.maximumWidth():
                    self.assertEqual(left_space, 0)
                else:
                    self.assertGreater(left_space, 0)
                for card in (window.preprocessor_generation_card, window.automatic_generation_card, window.manual_generation_card):
                    self.assertTrue(grid.rect().contains(card.geometry()))

    def test_hovering_a_method_card_also_highlights_its_action_text(self) -> None:
        self.finish_preparation()
        window = self.window
        for card in (window.automatic_generation_card, window.manual_generation_card):
            with self.subTest(card=card.accessibleName()):
                QTest.mouseMove(window, QPoint(1, 1))
                self.app.processEvents()
                normal = card.action_label.grab().toImage().pixelColor(10, 10)
                QTest.mouseMove(card, card.title_label.geometry().center())
                self.app.processEvents()
                hovered = card.action_label.grab().toImage().pixelColor(10, 10)
                self.assertNotEqual(normal, hovered)
                self.assertLess(hovered.lightness(), normal.lightness())
                self.assertGreater(hovered.saturation(), normal.saturation())
                QTest.mouseMove(window, QPoint(1, 1))
                self.app.processEvents()
                restored = card.action_label.grab().toImage().pixelColor(10, 10)
                self.assertEqual(normal, restored)

    def test_every_method_description_fits_after_repeated_width_changes(self) -> None:
        from PySide6.QtCore import QRect
        window=self.window
        self.finish_preparation()
        for width in (1800,1060,860,760,950,1400,1800):
            window.resize(width,900)
            for _ in range(4):self.app.processEvents()
            for card in (window.automatic_generation_card,window.manual_generation_card):
                for label in (card.title_label,card.description_label,card.action_label):
                    with self.subTest(width=width,text=label.text()):
                        required=label.fontMetrics().boundingRect(QRect(0,0,label.width(),100000),
                            Qt.TextFlag.TextWordWrap,label.text()).height()
                        self.assertGreaterEqual(label.height(),required)
                        self.assertGreaterEqual(label.y(),0)
                        self.assertLess(label.geometry().bottom(),card.height())


if __name__ == "__main__":
    unittest.main()
