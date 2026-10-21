from __future__ import annotations

from decimal import Decimal
from math import ceil
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch
from urllib.parse import parse_qs, urlsplit

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("COOLING_TOWER_DISABLE_SLICER_DISCOVERY", "1")

from PySide6.QtCore import QSize, Qt
from PySide6.QtGui import QFont, QFontDatabase, QFontMetricsF, QValidator
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QDialog, QLabel, QScrollArea, QTextBrowser

from cooling_tower.gui.voluntary_support_dialog import VoluntarySupportDialog, _InlineLegalNotice
from cooling_tower.legal_documents import legal_profile
from cooling_tower.voluntary_support import (
    SUPPORT_AMOUNT_MIN, SUPPORT_PRESETS, parse_support_amount, paypal_support_url,
)
from gui_lifecycle import dispose_test_widget


class SupportAmountTests(unittest.TestCase):
    def test_unambiguous_amounts_and_boundaries(self):
        for text, expected in (
            ("2,50", "2.50"), (" 5 ", "5"), ("10.1", "10.10"),
            ("50", "50.00"), ("50.00", "50.00"),
        ):
            with self.subTest(text=text):
                self.assertEqual(parse_support_amount(text), Decimal(expected))

    def test_invalid_amounts_are_rejected_without_rounding(self):
        for text in (
            "", " ", "0", "0,00", "-2", "+5", "10000", "1.234", "2,501",
            "1.000,00", "1,000.00", "1 000", "1e2", "NaN", "Infinity",
            "2,5 EUR", ".50", "5.", "５", "5&business=other@example.test",
            "0,01", "0,50", "1,49", "2,49", "50,01", "9999.99",
        ):
            with self.subTest(text=text), self.assertRaises(ValueError):
                parse_support_amount(text)

    def test_presets_and_custom_amount_build_only_allowlisted_fields(self):
        recipient = "support+test@example.test"
        for amount in (*SUPPORT_PRESETS, "12,34", "2.50", "50,00"):
            with self.subTest(amount=amount):
                url = urlsplit(paypal_support_url(amount, recipient))
                self.assertEqual((url.scheme, url.netloc, url.path),
                                 ("https", "www.paypal.com", "/cgi-bin/webscr"))
                self.assertFalse(url.fragment)
                self.assertEqual(parse_qs(url.query), {
                    "cmd": ["_donations"], "business": [recipient],
                    "item_name": ["Sacrificial Tower - freiwillige Unterstützung ohne Gegenleistung"],
                    "amount": [format(parse_support_amount(amount), ".2f")],
                    "currency_code": ["EUR"], "no_shipping": ["1"],
                    "charset": ["utf-8"], "lc": ["DE"],
                })

    def test_minimum_retains_at_least_one_euro_at_the_documented_standard_fee(self):
        fee = SUPPORT_AMOUNT_MIN * Decimal("0.0249") + Decimal("0.35")
        self.assertGreaterEqual(SUPPORT_AMOUNT_MIN - fee, Decimal("1.00"))

    def test_invalid_recipient_is_rejected(self):
        for recipient in ("", "[[PAYPAL_EMAIL]]", "a@b", "a b@example.test", "a@example.test\n"):
            with self.subTest(recipient=recipient), self.assertRaises(ValueError):
                paypal_support_url("5", recipient)


class VoluntarySupportDialogTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])
        cls.original_font = cls.app.font()
        cls.font_id = -1
        # The Windows offscreen plugin does not always discover installed fonts.
        font_path = Path(os.environ.get("WINDIR", "C:/Windows")) / "Fonts/segoeui.ttf"
        if os.name == "nt" and font_path.is_file():
            cls.font_id = QFontDatabase.addApplicationFont(str(font_path))
            if cls.font_id >= 0:
                cls.app.setFont(QFont(QFontDatabase.applicationFontFamilies(cls.font_id)[0], 10))

    @classmethod
    def tearDownClass(cls):
        cls.app.setFont(cls.original_font)
        if cls.font_id >= 0:
            QFontDatabase.removeApplicationFont(cls.font_id)

    def setUp(self):
        self.browser_patch = patch(
            "cooling_tower.gui.voluntary_support_dialog.QDesktopServices.openUrl",
            return_value=True,
        )
        self.open_url = self.browser_patch.start()
        self.addCleanup(self.browser_patch.stop)
        self.dialog = VoluntarySupportDialog()
        self.addCleanup(dispose_test_widget, self.dialog)

    def test_opening_and_selecting_never_contacts_paypal(self):
        self.dialog.show()
        self.app.processEvents()
        self.assertEqual(self.dialog.amount_edit.text(), "")
        self.assertTrue(self.dialog.continue_button.isEnabled())
        self.assertEqual([b.isChecked() for b in self.dialog.preset_buttons],
                         [False, True, False, False, False])
        self.assertEqual([b.property("preferredAmount") for b in self.dialog.preset_buttons],
                         [False, True, False, False, False])
        self.assertIn("Vorschlag", self.dialog.status_label.text())
        self.assertIn("frei änderbar", self.dialog.status_label.text())
        self.assertEqual([b.text() for b in self.dialog.preset_buttons],
                         ["3,50 €", "5 €", "10 €", "15 €", "20 €"])
        for amount, button in zip(SUPPORT_PRESETS, self.dialog.preset_buttons):
            button.click()
            self.assertEqual(self.dialog.amount_edit.text(), "")
            self.assertTrue(button.isChecked())
            self.assertEqual(sum(b.isChecked() for b in self.dialog.preset_buttons), 1)
            self.assertTrue(self.dialog.continue_button.isEnabled())
        self.open_url.assert_not_called()

    def test_default_amount_requires_explicit_continue_and_keeps_custom_field_empty(self):
        self.dialog.show()
        self.app.processEvents()
        self.assertEqual(self.dialog.amount_edit.text(), "")
        self.assertEqual(self.dialog.amount_edit.placeholderText(), "z. B. 7,50")
        QTest.keyClick(self.dialog, Qt.Key.Key_Return)
        self.dialog.amount_edit.setFocus()
        QTest.keyClick(self.dialog.amount_edit, Qt.Key.Key_Return)
        self.open_url.assert_not_called()
        self.dialog.continue_button.click()
        self.open_url.assert_called_once()
        self.assertEqual(parse_qs(urlsplit(self.open_url.call_args.args[0].toString()).query)["amount"],
                         ["5.00"])
        self.assertEqual(self.dialog.amount_edit.text(), "")

    def test_presets_clear_custom_input_and_send_the_selected_amount(self):
        for amount, button in zip(SUPPORT_PRESETS, self.dialog.preset_buttons):
            with self.subTest(amount=amount):
                self.dialog.amount_edit.setText("12,34")
                button.click()
                self.assertEqual(self.dialog.amount_edit.text(), "")
                self.assertEqual(self.dialog.amount_edit.placeholderText(), "z. B. 7,50")
                self.assertTrue(button.isChecked())
                self.dialog.continue_button.click()
                self.assertEqual(parse_qs(urlsplit(self.open_url.call_args.args[0].toString()).query)["amount"],
                                 [amount])

    def test_cleared_custom_amount_does_not_fall_back_to_a_previous_preset(self):
        self.dialog.preset_buttons[-1].click()
        self.dialog.amount_edit.setText("12,34")
        self.dialog.amount_edit.clear()
        self.assertFalse(any(b.isChecked() for b in self.dialog.preset_buttons))
        self.assertFalse(self.dialog.continue_button.isEnabled())
        self.dialog.open_paypal()
        self.open_url.assert_not_called()

    def test_step_buttons_turn_the_active_preset_into_a_custom_amount(self):
        edit = self.dialog.amount_edit
        self.assertEqual(edit.text(), "")
        edit.step_up_button.click()
        self.assertEqual(edit.text(), "5,50")
        self.assertFalse(any(b.isChecked() for b in self.dialog.preset_buttons))
        edit.step_down_button.click()
        self.assertEqual(edit.text(), "5,00")
        self.dialog.preset_buttons[0].click()
        self.assertEqual(edit.text(), "")
        edit.step_down_button.click()
        self.assertEqual(edit.text(), "3,00")
        self.open_url.assert_not_called()
        self.dialog.continue_button.click()
        self.assertEqual(parse_qs(urlsplit(self.open_url.call_args.args[0].toString()).query)["amount"],
                         ["3.00"])

    def test_step_buttons_use_exact_half_euro_steps_and_respect_both_bounds(self):
        edit = self.dialog.amount_edit
        for text, direction, expected in (
            ("7,25", 1, "7,75"), ("7.75", -1, "7,25"),
            ("49,50", 1, "50,00"), ("50,00", -1, "49,50"),
            ("49,99", 1, "50,00"), ("2,51", -1, "2,50"),
        ):
            with self.subTest(text=text, direction=direction):
                edit.setText(text)
                button = edit.step_up_button if direction > 0 else edit.step_down_button
                button.click()
                self.assertEqual(edit.text(), expected)
                self.assertTrue(edit.hasAcceptableInput())
        for text, blocked, allowed in (
            ("2,50", edit.step_down_button, edit.step_up_button),
            ("50,00", edit.step_up_button, edit.step_down_button),
        ):
            edit.setText(text)
            self.assertFalse(blocked.isEnabled())
            self.assertTrue(allowed.isEnabled())
            blocked.click()
            self.assertEqual(edit.text(), text)
        self.open_url.assert_not_called()

    def test_step_buttons_handle_empty_unfinished_and_below_minimum_custom_input(self):
        edit = self.dialog.amount_edit
        edit.setText("7,50")
        edit.clear()
        self.assertFalse(edit.step_down_button.isEnabled())
        edit.step_up_button.click()
        self.assertEqual(edit.text(), "2,50")
        for text, expected in (("1,00", "2,50"), ("12,", "12,50"),
                               ("0,", "2,50"), ("NaN", "2,50"), ("1e2", "2,50")):
            with self.subTest(text=text):
                edit.setText(text)
                edit.step_up_button.click()
                self.assertEqual(edit.text(), expected)
                self.assertTrue(self.dialog.continue_button.isEnabled())
                self.assertFalse(any(b.isChecked() for b in self.dialog.preset_buttons))
        self.open_url.assert_not_called()

    def test_holding_either_step_button_repeats_four_times_per_second_and_release_stops(self):
        self.dialog.show()
        self.app.processEvents()
        edit = self.dialog.amount_edit
        for button, direction in ((edit.step_up_button, 1), (edit.step_down_button, -1)):
            with self.subTest(direction=direction):
                edit.setText("10,00")
                clicks = []
                button.clicked.connect(lambda _checked=False, values=clicks: values.append(True))
                self.assertEqual(button.autoRepeatInterval(), 250)
                self.assertEqual(button.autoRepeatDelay(), 250)
                QTest.mousePress(button, Qt.MouseButton.LeftButton)
                try:
                    QTest.qWait(850)
                    self.assertGreaterEqual(len(clicks), 2)
                    self.assertEqual(parse_support_amount(edit.text()),
                                     Decimal("10.00") + Decimal("0.50") * direction * len(clicks))
                finally:
                    QTest.mouseRelease(button, Qt.MouseButton.LeftButton)
                released_value = edit.text()
                QTest.qWait(350)
                self.assertEqual(edit.text(), released_value)
        self.open_url.assert_not_called()

    def test_holding_a_step_button_stops_at_the_amount_boundary(self):
        self.dialog.show()
        self.app.processEvents()
        edit = self.dialog.amount_edit
        for text, button, expected in (
            ("49,50", edit.step_up_button, "50,00"),
            ("3,00", edit.step_down_button, "2,50"),
        ):
            with self.subTest(text=text):
                edit.setText(text)
                QTest.mousePress(button, Qt.MouseButton.LeftButton)
                try:
                    QTest.qWait(600)
                    self.assertEqual(edit.text(), expected)
                    self.assertFalse(button.isEnabled())
                finally:
                    QTest.mouseRelease(button, Qt.MouseButton.LeftButton)
        self.open_url.assert_not_called()

    def test_manual_amount_is_checked_and_opened_only_on_explicit_click(self):
        self.dialog.show()
        self.dialog.amount_edit.setText("12,34")
        self.dialog.amount_edit.setFocus()
        self.app.processEvents()
        QTest.keyClick(self.dialog.amount_edit, Qt.Key.Key_Return)
        self.open_url.assert_not_called()
        self.dialog.continue_button.click()
        self.open_url.assert_called_once()
        query = parse_qs(urlsplit(self.open_url.call_args.args[0].toString()).query)
        self.assertEqual(query["amount"], ["12.34"])
        self.assertEqual(query["business"], [legal_profile()["support_paypal_email"]])
        self.assertEqual(self.dialog.recipient_label.text(), legal_profile()["support_paypal_email"])
        self.assertIn("erst dort bestätigt", self.dialog.status_label.text())

    def test_invalid_amount_cannot_be_submitted_even_by_direct_call(self):
        for amount in ("0", "-1", "1,999", "10000", "2,49", "50,01"):
            self.dialog.amount_edit.setText(amount)
            self.assertFalse(self.dialog.continue_button.isEnabled())
            self.dialog.open_paypal()
        self.open_url.assert_not_called()

    def test_typing_rejects_letters_symbols_extra_decimals_and_excess_amounts(self):
        edit = self.dialog.amount_edit
        edit.clear()
        QTest.keyClicks(edit, "letters-+ /_")
        self.assertEqual(edit.text(), "")
        QTest.keyClicks(edit, "12,34")
        self.assertEqual(edit.text(), "12,34")
        QTest.keyClicks(edit, "5.,abc")
        self.assertEqual(edit.text(), "12,34")
        edit.clear()
        QTest.keyClicks(edit, "50,00")
        self.assertTrue(edit.hasAcceptableInput())
        QTest.keyClicks(edit, "9")
        self.assertEqual(edit.text(), "50,00")
        edit.clear()
        QTest.keyClicks(edit, "500")
        self.assertEqual(edit.text(), "50")
        self.open_url.assert_not_called()

    def test_inserting_invalid_text_rejects_the_entire_edit_without_changing_amount(self):
        edit = self.dialog.amount_edit
        for value in ("abc", "-5", "+5", "5 €", " 5 ", "1e2", "１２", "١٢",
                      "12,345", "12.345", "10000", "10000,00", "1.000,00", "50,01", "51"):
            with self.subTest(value=value):
                edit.setText("5,00")
                edit.selectAll()
                edit.insert(value)
                self.assertEqual(edit.text(), "5,00")
        for value in ("2,50", "5", "7.25", "2,49", "50.00"):
            with self.subTest(value=value):
                edit.selectAll()
                edit.insert(value)
                self.assertEqual(edit.text(), value)
                self.assertEqual(edit.hasAcceptableInput(), value != "2,49")
        self.open_url.assert_not_called()

    def test_unfinished_amounts_allow_editing_but_cannot_continue(self):
        edit = self.dialog.amount_edit
        validator = edit.validator()
        self.dialog.show()
        self.assertTrue(self.dialog.amount_hint_label.isVisible())
        self.assertIn("Mindestens 2,50 €", self.dialog.amount_hint_label.text())
        self.assertIn("höchstens 50,00 €", self.dialog.amount_hint_label.text())
        edit.setText("7,50")
        for value in ("", "0", "0,", "0.0", "0,00", "1", "1,00", "2,49", "12,", "12."):
            with self.subTest(value=value):
                self.assertEqual(validator.validate(value, len(value))[0], QValidator.State.Intermediate)
                edit.setText(value)
                self.assertFalse(edit.hasAcceptableInput())
                self.assertFalse(self.dialog.continue_button.isEnabled())
                if value and Decimal(value.replace(",", ".")) < SUPPORT_AMOUNT_MIN:
                    self.assertTrue(self.dialog.amount_hint_label.isVisible())
                    self.assertEqual(self.dialog.amount_hint_label.text(), "Bitte mindestens 2,50 € eingeben.")
                    self.assertTrue(self.dialog.amount_hint_label.property("belowMinimum"))
        edit.setText("2,5")
        edit.insert("0")
        self.assertEqual(edit.text(), "2,50")
        self.assertTrue(self.dialog.continue_button.isEnabled())
        self.assertFalse(self.dialog.amount_hint_label.property("belowMinimum"))
        self.assertIn("Mindestens 2,50 €", self.dialog.amount_hint_label.text())

    def test_browser_failure_is_visible_and_does_not_claim_payment(self):
        for result in (False, OSError("browser unavailable")):
            with self.subTest(result=result):
                self.open_url.side_effect = result if isinstance(result, Exception) else None
                self.open_url.return_value = False
                self.dialog.amount_edit.setText("5")
                self.dialog.continue_button.click()
                self.assertIn("nicht geöffnet", self.dialog.status_label.text())
                self.assertTrue(self.dialog.isEnabled())

    def test_legal_links_request_existing_documents_without_duplicate_dialogs(self):
        self.dialog.show()
        requested = []
        self.dialog.legal_document_requested.connect(requested.append)
        self.dialog.legal_links.linkActivated.emit("terms")
        self.dialog.legal_links.linkActivated.emit("privacy")
        self.assertEqual(requested, ["Lizenzbedingungen", "Datenschutzerklärung"])
        self.assertEqual(self.dialog.findChildren(QDialog), [])
        self.assertEqual(self.dialog.findChildren(QTextBrowser), [])
        self.open_url.assert_not_called()

    def test_repeated_preset_selection_stays_active_and_manual_input_replaces_it(self):
        button = self.dialog.preset_buttons[1]
        button.click()
        button.click()
        self.assertTrue(button.isChecked())
        for text in ("10", "5", "7,50"):
            self.dialog.amount_edit.setText(text)
            self.assertEqual(self.dialog.amount_edit.text(), text)
            self.assertFalse(any(b.isChecked() for b in self.dialog.preset_buttons))
            self.assertTrue(self.dialog.continue_button.isEnabled())

    def test_amount_field_and_single_line_details_keep_their_alignment_after_resizing(self):
        dialog = self.dialog
        dialog.setStyleSheet((ROOT / "src/cooling_tower/gui/styles.qss").read_text(encoding="utf-8"))
        dialog.show()
        for available in (QSize(1000, 900), QSize(520, 580), QSize(1000, 900)):
            with self.subTest(available=available):
                dialog.fit_to_screen(available)
                QTest.qWait(30)
                middle = dialog.preset_buttons[2]
                self.assertEqual(dialog.amount_edit.width(), middle.width())
                for button in (dialog.amount_edit.step_up_button, dialog.amount_edit.step_down_button):
                    self.assertTrue(dialog.amount_edit.rect().contains(button.geometry()))
                self.assertFalse(dialog.amount_edit.step_up_button.geometry().intersects(
                    dialog.amount_edit.step_down_button.geometry()))
                field_center = dialog.amount_edit.mapTo(dialog, dialog.amount_edit.rect().center())
                middle_center = middle.mapTo(dialog, middle.rect().center())
                self.assertLessEqual(abs(field_center.x() - middle_center.x()), 1)
                self.assertEqual(dialog.scroll.horizontalScrollBar().maximum(), 0)
                self.assertFalse(dialog.scroll.horizontalScrollBar().isVisible())
                self.assertFalse(dialog.scroll.verticalScrollBar().isVisible())
                self.assertFalse(dialog.amount_hint_label.wordWrap())
                self.assertFalse(dialog.recipient_label.wordWrap())
                if dialog.width() == dialog.PREFERRED_SIZE.width() and self.font_id >= 0:
                    self.assertEqual(dialog.scroll.verticalScrollBar().maximum(), 0)
                    hint_center = dialog.amount_hint_label.mapTo(dialog, dialog.amount_hint_label.rect().center())
                    recipient_center = dialog.recipient_label.mapTo(dialog, dialog.recipient_label.rect().center())
                    self.assertLessEqual(abs(hint_center.y() - recipient_center.y()), 1)
                    for label in (dialog.amount_hint_label, dialog.recipient_label):
                        self.assertGreaterEqual(label.contentsRect().width(),
                                                ceil(QFontMetricsF(label.font()).horizontalAdvance(label.text())))

    def test_legal_links_center_in_remaining_space_and_move_below_when_narrow(self):
        body = QLabel("Kurzer Hinweis.")
        body.setTextFormat(Qt.TextFormat.RichText)
        body.setWordWrap(True)
        links = QLabel('<a href="terms">Nutzungsbedingungen</a> · <a href="privacy">Datenschutz</a>')
        links.setWordWrap(True)
        notice = _InlineLegalNotice(body, links)
        self.addCleanup(dispose_test_widget, notice)
        notice.resize(1200, notice.heightForWidth(1200))
        notice.show()
        self.app.processEvents()
        text_end = ceil(QFontMetricsF(body.font()).horizontalAdvance(body.text()))
        left_gap = links.x() - text_end
        right_gap = notice.width() - links.geometry().right() - 1
        self.assertLessEqual(abs(left_gap - right_gap), 2)
        self.assertEqual(links.y(), 0)
        self.assertEqual(notice.height(), body.height())
        notice.resize(100, notice.heightForWidth(100))
        self.app.processEvents()
        self.assertGreaterEqual(links.y(), body.height())
        self.assertLessEqual(links.geometry().bottom(), notice.height() - 1)

    def test_closing_without_continuing_does_not_open_browser(self):
        self.dialog.show()
        self.assertTrue(self.dialog.preset_buttons[1].isChecked())
        self.dialog.close_button.click()
        self.assertFalse(self.dialog.isVisible())
        self.open_url.assert_not_called()

    def test_paypal_privacy_is_a_separate_explicit_link_without_amount(self):
        self.dialog.amount_edit.setText("20")
        self.dialog.open_paypal_privacy()
        self.assertEqual(self.open_url.call_args.args[0].toString(),
                         "https://www.paypal.com/de/legalhub/paypal/privacy-full")

    def test_menu_creates_the_dialog_lazily_and_reuses_it(self):
        from cooling_tower.gui.main_window import MainWindow
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "settings.json"
            window = MainWindow(user_settings_path=path)
            try:
                self.assertIsNone(window._voluntary_support_dialog)
                self.assertIn(window.voluntary_support_action, window.options_menu.actions())
                with patch.object(window, "_show_internal_dialog_without_flash"):
                    window.voluntary_support_action.trigger()
                    dialog = window._voluntary_support_dialog
                    self.assertIsInstance(dialog, VoluntarySupportDialog)
                    dialog.amount_edit.setText("12,34")
                    window.voluntary_support_action.trigger()
                    self.assertIs(window._voluntary_support_dialog, dialog)
                    self.assertEqual(dialog.amount_edit.text(), "12,34")
                dialog.show()
                for width, height in ((620, 700), (480, 520)):
                    dialog.fit_to_screen(QSize(width + 40, height + 60))
                    self.app.processEvents()
                    scroll = dialog.findChild(QScrollArea)
                    self.assertEqual(scroll.horizontalScrollBar().maximum(), 0)
                    self.assertTrue(dialog.continue_button.isVisible())
                window.close()
                stored = json.loads(path.read_text(encoding="utf-8"))
                self.assertNotIn("12,34", json.dumps(stored))
                self.assertNotIn("support_paypal_email", json.dumps(stored))
            finally:
                dispose_test_widget(window)
        self.open_url.assert_not_called()

    def test_maximized_parent_and_reopening_keep_a_compact_normal_dialog(self):
        from cooling_tower.gui.main_window import MainWindow
        with tempfile.TemporaryDirectory() as directory:
            window = MainWindow(user_settings_path=Path(directory) / "settings.json")
            try:
                window.showMaximized()
                window.voluntary_support_action.trigger()
                QTest.qWait(150)
                dialog = window._voluntary_support_dialog
                for reopen in (False, True):
                    if reopen:
                        dialog.close()
                        dialog.setWindowState(Qt.WindowState.WindowMaximized)
                        window.voluntary_support_action.trigger()
                        QTest.qWait(150)
                    self.assertFalse(dialog.isMaximized())
                    self.assertLessEqual(dialog.width(), dialog.PREFERRED_SIZE.width())
                    self.assertLessEqual(dialog.height(), dialog.PREFERRED_SIZE.height())
                    self.assertFalse(dialog.windowFlags() & Qt.WindowType.WindowMaximizeButtonHint)
                    self.assertEqual(dialog.size(), dialog.maximumSize())
                self.assertIsNone(window._about_dialog)
                for link, title in (("terms", "Lizenzbedingungen"), ("privacy", "Datenschutzerklärung")):
                    dialog.legal_links.linkActivated.emit(link)
                    self.assertEqual(window.about_dialog._shown_document_title, title)
                    self.assertFalse(window.about_dialog.about_document_label.text() == "")
                self.assertEqual(dialog.findChildren(QDialog), [])
            finally:
                dispose_test_widget(window)
        self.open_url.assert_not_called()


if __name__ == "__main__":
    unittest.main()
