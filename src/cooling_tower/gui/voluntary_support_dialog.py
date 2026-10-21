from __future__ import annotations

from decimal import Decimal, InvalidOperation
from html import escape
from math import ceil
from pathlib import Path

from PySide6.QtCore import QRect, QRegularExpression, QSignalBlocker, QSize, Qt, QUrl, Signal
from PySide6.QtGui import (
    QColor, QDesktopServices, QIcon, QPainter, QPixmap, QRegularExpressionValidator,
    QResizeEvent, QTextDocument, QValidator,
)
from PySide6.QtWidgets import (
    QDialog, QFormLayout, QFrame, QGridLayout, QHBoxLayout, QLabel, QLineEdit,
    QPushButton, QScrollArea, QSizePolicy, QToolButton, QVBoxLayout, QWidget,
)

from cooling_tower.legal_documents import legal_profile
from cooling_tower.voluntary_support import (
    PAYPAL_PRIVACY_URL, SUPPORT_AMOUNT_MIN, SUPPORT_AMOUNT_MAX, SUPPORT_AMOUNT_PATTERN,
    SUPPORT_AMOUNT_RANGE_TEXT, SUPPORT_PRESETS, parse_support_amount,
    paypal_support_url, validate_support_recipient,
)


ASSETS = Path(__file__).with_name('assets')


class _AmountChoiceButton(QPushButton):
    def paintEvent(self, event) -> None:  # noqa: N802
        super().paintEvent(event)
        if self.property('preferredAmount'):
            painter = QPainter(self)
            painter.setOpacity(0.55)
            heart = QIcon(str(ASSETS / 'support_heart.svg'))
            for x in (5, self.width() - 13):
                heart.paint(painter, QRect(x, 5, 8, 8))


def _coffee_action_icon() -> QIcon:
    """Add four logical pixels after the cup while keeping high-DPI rendering."""
    result = QIcon()
    source = QIcon(str(ASSETS / 'coffee.svg'))
    for scale in (1.0, 1.25, 1.5, 2.0, 3.0):
        pixmap = QPixmap(round(22 * scale), round(18 * scale))
        pixmap.setDevicePixelRatio(scale)
        pixmap.fill(Qt.GlobalColor.transparent)
        painter = QPainter(pixmap)
        source.paint(painter, QRect(0, 0, 18, 18))
        painter.end()
        result.addPixmap(pixmap)
    return result


class _InlineLegalNotice(QWidget):
    """Center links in the space after the last text line, with a narrow fallback."""

    def __init__(self, body: QLabel, links: QLabel) -> None:
        super().__init__()
        self.body = body
        self.links = links
        for label in (body, links):
            label.setParent(self)
            label.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop)
            label.show()
        links.setAlignment(Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignTop)
        policy = QSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Preferred)
        policy.setHeightForWidth(True)
        self.setSizePolicy(policy)

    def _geometry_for_width(self, width: int) -> tuple[int, QRect, QRect]:
        width = max(1, width)
        self.body.ensurePolished()
        self.links.ensurePolished()
        # Both labels use Qt rich-text layout, including identical line metrics.
        body_document = QTextDocument()
        body_document.setDefaultFont(self.body.font())
        body_document.setDocumentMargin(0)
        body_document.setHtml(self.body.text())
        body_document.setTextWidth(width)
        body_height = ceil(body_document.size().height())
        body_block = body_document.lastBlock()
        body_layout = body_block.layout()
        last_line = body_layout.lineAt(body_layout.lineCount() - 1)
        document = QTextDocument()
        document.setDefaultFont(self.links.font())
        document.setDocumentMargin(0)
        document.setHtml(self.links.text())
        links_width = min(width, ceil(document.idealWidth()))
        document.setTextWidth(links_width)
        links_height = ceil(document.size().height())
        links_block = document.firstBlock()
        links_layout = links_block.layout()
        fits_last_line = (
            last_line.naturalTextWidth() + 10 + links_width <= width
            and links_layout.lineCount() == 1
        )
        if fits_last_line:
            body_baseline = (
                body_document.documentLayout().blockBoundingRect(body_block).top()
                + last_line.y() + last_line.ascent()
            )
            links_line = links_layout.lineAt(0)
            links_baseline = (
                document.documentLayout().blockBoundingRect(links_block).top()
                + links_line.y() + links_line.ascent()
            )
            links_y = round(body_baseline - links_baseline)
            text_end = ceil(last_line.naturalTextWidth())
            links_x = text_end + (width - text_end - links_width) // 2
        else:
            links_y = body_height + 2
            links_x = (width - links_width) // 2
        return (
            max(body_height, links_y + links_height),
            QRect(0, 0, width, body_height),
            QRect(links_x, links_y, links_width, links_height),
        )

    def heightForWidth(self, width: int) -> int:  # noqa: N802
        return self._geometry_for_width(width)[0]

    def sizeHint(self) -> QSize:  # noqa: N802
        return QSize(480, self.heightForWidth(480))

    def minimumSizeHint(self) -> QSize:  # noqa: N802
        return QSize(0, 0)

    def resizeEvent(self, event: QResizeEvent) -> None:  # noqa: N802
        _, body, links = self._geometry_for_width(event.size().width())
        self.body.setGeometry(body)
        self.links.setGeometry(links)
        super().resizeEvent(event)


class _SupportAmountValidator(QRegularExpressionValidator):
    """Reject malformed edits; allow unfinished amounts without enabling payment."""

    def __init__(self, parent=None) -> None:
        super().__init__(QRegularExpression(SUPPORT_AMOUNT_PATTERN), parent)

    def validate(self, text: str, position: int):
        state, text, position = super().validate(text, position)
        if state != QValidator.State.Invalid and text:
            # Check the upper bound while editing, including a trailing separator.
            if Decimal(text.replace(',', '.')) > SUPPORT_AMOUNT_MAX:
                return QValidator.State.Invalid, text, position
        if state == QValidator.State.Acceptable:
            try:
                parse_support_amount(text)
            except ValueError:
                state = QValidator.State.Intermediate
        return state, text, position


class _SupportAmountEdit(QLineEdit):
    """Keep strict text editing and fit two step buttons inside the same width."""

    step_requested = Signal(int)

    def __init__(self) -> None:
        super().__init__()
        self.setTextMargins(0, 0, 12, 0)
        self.step_up_button = self._step_button('spin_up.svg', 1, 'Betrag um 0,50 € erhöhen')
        self.step_down_button = self._step_button('spin_down.svg', -1, 'Betrag um 0,50 € verringern')

    def _step_button(self, filename: str, direction: int, description: str) -> QToolButton:
        button = QToolButton(self)
        button.setObjectName('supportAmountStep')
        source = QIcon(str(ASSETS / filename))
        icon = QIcon()
        for scale in (1, 2, 3, 4):
            pixmap = source.pixmap(8 * scale, 6 * scale)
            icon.addPixmap(pixmap, QIcon.Mode.Normal)
            disabled_pixmap = pixmap.copy()
            painter = QPainter(disabled_pixmap)
            painter.setCompositionMode(QPainter.CompositionMode.CompositionMode_SourceIn)
            painter.fillRect(disabled_pixmap.rect(), QColor('#a8b2ae'))
            painter.end()
            icon.addPixmap(disabled_pixmap, QIcon.Mode.Disabled)
        button.setIcon(icon)
        button.setIconSize(QSize(8, 6))
        button.setAutoRepeat(True)
        button.setAutoRepeatDelay(250)
        button.setAutoRepeatInterval(250)
        button.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        button.setCursor(Qt.CursorShape.PointingHandCursor)
        button.setAccessibleName(description)
        button.setToolTip(description)
        button.clicked.connect(lambda _checked=False: self.step_requested.emit(direction))
        return button

    def resizeEvent(self, event: QResizeEvent) -> None:  # noqa: N802
        half_height = max(2, (self.height() - 8) // 2)
        self.step_up_button.setGeometry(self.width() - 21, 4, 18, half_height)
        self.step_down_button.setGeometry(self.width() - 21, 4 + half_height, 18, half_height)
        super().resizeEvent(event)


class _AmountChoices(QWidget):
    """Keep all amounts visible when fonts or a smaller display need more rows."""

    choice_width_changed = Signal(int)

    def __init__(self, buttons: list[QPushButton]) -> None:
        super().__init__()
        self.buttons = buttons
        self.grid = QGridLayout(self)
        self.grid.setContentsMargins(0, 0, 0, 0)
        self.grid.setSpacing(8)
        self.columns = 0

    def resizeEvent(self, event: QResizeEvent) -> None:  # noqa: N802
        minimum = max(button.minimumSizeHint().width() for button in self.buttons)
        columns = max(1, min(5, (event.size().width() + 8) // (minimum + 8)))
        if columns != self.columns:
            for button in self.buttons:
                self.grid.removeWidget(button)
            for column in range(5):
                self.grid.setColumnStretch(column, 1 if column < columns else 0)
            for index, button in enumerate(self.buttons):
                self.grid.addWidget(button, index // columns, index % columns)
            self.columns = columns
        self.grid.setGeometry(self.rect())
        self.choice_width_changed.emit(self.buttons[2].width())
        super().resizeEvent(event)


class VoluntarySupportDialog(QDialog):
    """A compact local chooser; only the explicit PayPal action opens a browser."""

    legal_document_requested = Signal(str)
    PREFERRED_SIZE = QSize(560, 592)

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        profile = legal_profile()
        self.recipient = profile['support_paypal_email']
        validate_support_recipient(self.recipient)
        self._selected_preset: str | None = None
        self.setObjectName('voluntarySupportDialog')
        self.setWindowTitle('Buy me a coffee')
        self.setWindowIcon(QIcon(str(ASSETS / 'coffee.svg')))
        self.setWindowFlags(
            Qt.WindowType.Dialog | Qt.WindowType.CustomizeWindowHint
            | Qt.WindowType.WindowTitleHint | Qt.WindowType.WindowCloseButtonHint
            | Qt.WindowType.MSWindowsFixedSizeDialogHint
        )

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)
        self.scroll = QScrollArea()
        self.scroll.setObjectName('supportScroll')
        self.scroll.setFrameShape(QFrame.Shape.NoFrame)
        self.scroll.setWidgetResizable(True)
        self.scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.scroll.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        content = QWidget()
        content.setObjectName('supportContent')
        layout = QVBoxLayout(content)
        layout.setContentsMargins(22, 20, 22, 10)
        layout.setSpacing(10)
        layout.setAlignment(Qt.AlignmentFlag.AlignTop)
        self.scroll.setWidget(content)
        outer.addWidget(self.scroll, 1)

        hero = QFrame()
        hero.setObjectName('supportCoffeeHero')
        hero_row = QHBoxLayout(hero)
        hero_row.setContentsMargins(9, 12, 18, 11)
        hero_row.setSpacing(8)
        # 85 / 100 preserves the cup's previous 68 / 80 scale.
        hero_row.addWidget(self._icon('support_coffee.svg', 85))
        hero_text = QVBoxLayout()
        hero_text.setSpacing(4)
        hero_text.setAlignment(Qt.AlignmentFlag.AlignVCenter)
        self._label(hero_text, 'BUY ME A COFFEE', 'supportEyebrow')
        self._label(hero_text, 'Ein kleines Dankeschön.', 'supportHeading')
        self._label(hero_text, 'Mit einem Kaffee die Entwicklung von Sacrificial Tower unterstützen.', 'supportIntroduction')
        hero_row.addLayout(hero_text, 1)
        layout.addWidget(hero)

        benefits = QHBoxLayout()
        benefits.setContentsMargins(4, 0, 4, 0)
        benefits.setSpacing(8)
        benefits_label = self._label(
            benefits, 'Ganz freiwillig · einmalig · App bleibt kostenlos', 'supportBenefits',
        )
        benefits_label.setMinimumHeight(19)
        benefits_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addLayout(benefits)

        amount_card = QFrame()
        amount_card.setObjectName('supportAmountCard')
        amount_layout = QVBoxLayout(amount_card)
        amount_layout.setContentsMargins(16, 12, 16, 12)
        amount_layout.setSpacing(8)
        amount_title = self._label(
            amount_layout, 'Jede Unterstützung ist willkommen', 'supportSectionTitle',
        )
        amount_title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.preset_buttons: list[QPushButton] = []
        for amount in SUPPORT_PRESETS:
            text = amount.removesuffix('.00').replace('.', ',') + ' €'
            button = _AmountChoiceButton(text)
            button.setObjectName('supportAmountChoice')
            button.setProperty('preferredAmount', amount == '5.00')
            button.setCheckable(True)
            button.setAutoDefault(False)
            button.setCursor(Qt.CursorShape.PointingHandCursor)
            button.setAccessibleName(f'{text} als Unterstützungsbetrag auswählen')
            button.clicked.connect(lambda _checked=False, value=amount: self.select_amount(value))
            self.preset_buttons.append(button)
        self.amount_choices = _AmountChoices(self.preset_buttons)
        amount_layout.addWidget(self.amount_choices)

        amount_row = QGridLayout()
        amount_row.setHorizontalSpacing(6)
        amount_row.setColumnStretch(0, 1)
        amount_row.setColumnStretch(2, 1)
        amount_label = QLabel('Eigener Betrag')
        amount_label.setObjectName('supportMutedText')
        amount_label.setWordWrap(True)
        amount_label.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        self.amount_edit = _SupportAmountEdit()
        self.amount_edit.setObjectName('voluntarySupportAmount')
        self.amount_edit.setMaxLength(16)
        self.amount_edit.setValidator(_SupportAmountValidator(self.amount_edit))
        self.amount_edit.setPlaceholderText('z. B. 7,50')
        self.amount_edit.setFixedWidth(self.preset_buttons[2].minimumSizeHint().width())
        self.amount_choices.choice_width_changed.connect(self.amount_edit.setFixedWidth)
        self.amount_edit.setAccessibleName('Unterstützungsbetrag in Euro')
        self.amount_edit.setAccessibleDescription(f'Zulässiger Betrag: {SUPPORT_AMOUNT_RANGE_TEXT}')
        self.amount_edit.setToolTip(f'{SUPPORT_AMOUNT_RANGE_TEXT}, höchstens zwei Nachkommastellen')
        amount_label.setBuddy(self.amount_edit)
        amount_row.addWidget(amount_label, 0, 0)
        amount_row.addWidget(self.amount_edit, 0, 1)
        self.amount_currency = QLabel('€')
        self.amount_currency.setObjectName('supportCurrency')
        amount_row.addWidget(self.amount_currency, 0, 2, Qt.AlignmentFlag.AlignLeft)
        manual_amount = QVBoxLayout()
        manual_amount.setSpacing(4)
        manual_amount.addLayout(amount_row)
        self._minimum_amount_text = f'{SUPPORT_AMOUNT_MIN:.2f} €'.replace('.', ',')
        maximum_amount_text = f'{SUPPORT_AMOUNT_MAX:.2f} €'.replace('.', ',')
        self._amount_range_hint = f'Mindestens {self._minimum_amount_text} · höchstens {maximum_amount_text}'
        amount_layout.addLayout(manual_amount)

        details_row = QFormLayout()
        details_row.setContentsMargins(0, 0, 0, 0)
        details_row.setHorizontalSpacing(12)
        details_row.setVerticalSpacing(4)
        details_row.setRowWrapPolicy(QFormLayout.RowWrapPolicy.WrapLongRows)
        details_row.setFieldGrowthPolicy(QFormLayout.FieldGrowthPolicy.AllNonFixedFieldsGrow)
        hint_group = QWidget()
        hint_row = QHBoxLayout(hint_group)
        hint_row.setContentsMargins(0, 0, 0, 0)
        hint_row.setSpacing(6)
        self.amount_hint_label = self._label(hint_row, self._amount_range_hint, 'supportAmountHint')
        self.amount_hint_label.setWordWrap(False)
        self.amount_hint_label.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
        recipient_group = QWidget()
        recipient_group.setMinimumHeight(18)
        recipient_row = QHBoxLayout(recipient_group)
        recipient_row.setContentsMargins(0, 0, 0, 0)
        recipient_row.setSpacing(9)
        recipient_row.addStretch(1)
        self.recipient_label = self._label(
            recipient_row, self.recipient, 'supportRecipient',
        )
        self.recipient_label.setWordWrap(False)
        self.recipient_label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        details_row.addRow(hint_group, recipient_group)
        amount_layout.addLayout(details_row)
        layout.addWidget(amount_card)

        notice = QFrame()
        notice.setObjectName('supportPaymentNotice')
        notice_row = QHBoxLayout(notice)
        notice_row.setContentsMargins(13, 12, 13, 12)
        notice_row.setSpacing(11)
        notice_row.addWidget(self._icon('privacy.svg', 22), 0, Qt.AlignmentFlag.AlignVCenter)
        notice_text = QVBoxLayout()
        notice_text.setSpacing(3)
        self._label(notice_text, 'In Ruhe bei PayPal bestätigen', 'supportNoticeTitle')
        self._label(notice_text, 'Öffnet PayPal im Browser. Erst dort prüfen und bestätigen Sie Ihre Zahlung.', 'supportNoticeText')
        notice_row.addLayout(notice_text, 1)
        layout.addWidget(notice)

        self.fine_print_label = QLabel(escape(
            'Ohne Gegenleistung, keine steuerbegünstigte Spende. PayPal-Gebühren '
            'können anfallen. PayPal verarbeitet Verbindungs- und Zahlungsdaten; '
            'der Empfänger erhält bei einer Zahlung Zahlungs- und ggf. Kontaktdaten.'
        ))
        self.fine_print_label.setObjectName('supportFinePrint')
        self.fine_print_label.setTextFormat(Qt.TextFormat.RichText)
        self.fine_print_label.setWordWrap(True)
        self.legal_links = QLabel(
            '<a href="terms" style="color:#627f70">Nutzungsbedingungen</a> · '
            '<a href="privacy" style="color:#627f70">Datenschutz</a> · '
            '<a href="paypal-privacy" style="color:#627f70">PayPal-Datenschutz ↗</a>'
        )
        self.legal_links.setObjectName('supportLegalLinks')
        self.legal_links.setWordWrap(True)
        self.legal_links.setOpenExternalLinks(False)
        self.legal_links.setTextInteractionFlags(
            Qt.TextInteractionFlag.LinksAccessibleByMouse
            | Qt.TextInteractionFlag.LinksAccessibleByKeyboard
        )
        self.legal_links.setAccessibleName('Rechtliche Hinweise: Nutzungsbedingungen und Datenschutz unter Über; PayPal-Datenschutz im Browser')
        self.legal_links.linkActivated.connect(self._activate_legal_link)
        self.legal_notice = _InlineLegalNotice(self.fine_print_label, self.legal_links)
        layout.addWidget(self.legal_notice)

        footer = QFrame()
        footer.setObjectName('supportFooter')
        footer_layout = QVBoxLayout(footer)
        footer_layout.setContentsMargins(22, 12, 22, 16)
        footer_layout.setSpacing(8)
        self.status_label = self._label(footer_layout, '', 'voluntarySupportStatus')
        actions = QHBoxLayout()
        self.close_button = QPushButton('Vielleicht später')
        self.close_button.setObjectName('supportLaterButton')
        self.close_button.setAutoDefault(False)
        self.close_button.clicked.connect(self.close)
        actions.addWidget(self.close_button)
        actions.addStretch(1)
        self.continue_button = QPushButton('Weiter zu PayPal  ↗')
        self.continue_button.setObjectName('supportPayPalButton')
        self.continue_button.setIcon(_coffee_action_icon())
        self.continue_button.setIconSize(QSize(22, 18))
        self.continue_button.setAutoDefault(False)
        self.continue_button.clicked.connect(self.open_paypal)
        actions.addWidget(self.continue_button)
        footer_layout.addLayout(actions)
        outer.addWidget(footer)
        self.amount_edit.textChanged.connect(self._amount_changed)
        self.amount_edit.step_requested.connect(self._step_amount)
        self.select_amount('5.00')
        self.status_label.setText('5 € als Vorschlag · frei änderbar.')
        self.fit_to_screen()

    @staticmethod
    def _icon(filename: str, size: int) -> QLabel:
        label = QLabel()
        label.setPixmap(QIcon(str(ASSETS / filename)).pixmap(size, size))
        label.setFixedSize(size, size)
        return label

    @staticmethod
    def _label(layout, text: str, name: str = '') -> QLabel:
        label = QLabel(text)
        label.setTextFormat(Qt.TextFormat.PlainText)
        label.setWordWrap(True)
        label.setObjectName(name)
        layout.addWidget(label)
        return label

    def fit_to_screen(self, available_size: QSize | None = None) -> None:
        """Reset native sizing too, including after a maximized parent/reopening."""
        if available_size is None:
            screen = self.parentWidget().screen() if self.parentWidget() else self.screen()
            available_size = screen.availableGeometry().size() if screen else self.PREFERRED_SIZE
        self.setWindowState(Qt.WindowState.WindowNoState)
        self.setFixedSize(
            min(self.PREFERRED_SIZE.width(), max(320, available_size.width() - 40)),
            min(self.PREFERRED_SIZE.height(), max(300, available_size.height() - 60)),
        )
        self.layout().activate()
        self.scroll.widget().layout().activate()

    def select_amount(self, text: str) -> None:
        self._selected_preset = text
        # Clearing a custom entry must not cancel the newly selected preset.
        with QSignalBlocker(self.amount_edit):
            self.amount_edit.clear()
        self._update_amount_state()

    def _amount_changed(self, _text: str) -> None:
        self._selected_preset = None
        self._update_amount_state()

    def _amount_text(self) -> str:
        return self._selected_preset if self._selected_preset is not None else self.amount_edit.text()

    def _step_base_amount(self) -> Decimal | None:
        text = self._amount_text()
        if self.amount_edit.validator().validate(text, len(text))[0] == QValidator.State.Invalid:
            return None
        try:
            amount = Decimal(text.replace(',', '.'))
        except InvalidOperation:
            return None
        return amount if amount.is_finite() else None

    def _step_amount(self, direction: int) -> None:
        base = self._step_base_amount()
        amount = SUPPORT_AMOUNT_MIN if base is None else base + Decimal('0.50') * direction
        amount = min(SUPPORT_AMOUNT_MAX, max(SUPPORT_AMOUNT_MIN, amount))
        self.amount_edit.setText(f'{amount:.2f}'.replace('.', ','))
        self.amount_edit.setFocus()

    def _update_amount_state(self) -> None:
        text = self._amount_text()
        step_base = self._step_base_amount()
        self.amount_edit.step_up_button.setEnabled(step_base is None or step_base < SUPPORT_AMOUNT_MAX)
        self.amount_edit.step_down_button.setEnabled(step_base is not None and step_base > SUPPORT_AMOUNT_MIN)
        try:
            below_minimum = bool(text.strip()) and Decimal(text.strip().replace(',', '.')) < SUPPORT_AMOUNT_MIN
        except InvalidOperation:
            below_minimum = False
        self.amount_hint_label.setText(
            f'Bitte mindestens {self._minimum_amount_text} eingeben.'
            if below_minimum else self._amount_range_hint
        )
        if self.amount_hint_label.property('belowMinimum') != below_minimum:
            self.amount_hint_label.setProperty('belowMinimum', below_minimum)
            self.amount_hint_label.style().unpolish(self.amount_hint_label)
            self.amount_hint_label.style().polish(self.amount_hint_label)
        try:
            selected = parse_support_amount(text)
        except ValueError as error:
            selected = None
            self.continue_button.setEnabled(False)
            self.status_label.setText(str(error) if text.strip() else 'Betrag auswählen oder selbst eingeben.')
        else:
            self.continue_button.setEnabled(True)
            self.status_label.setText('Einmalig unterstützen – ohne Abo.')
        for amount, button in zip(SUPPORT_PRESETS, self.preset_buttons):
            button.setChecked(self._selected_preset == amount and selected is not None)

    def _activate_legal_link(self, link: str) -> None:
        title = {'terms': 'Lizenzbedingungen', 'privacy': 'Datenschutzerklärung'}.get(link)
        if title:
            self.legal_document_requested.emit(title)
        elif link == 'paypal-privacy':
            self.open_paypal_privacy()

    def _open_url(self, url: str) -> bool:
        try:
            opened = QDesktopServices.openUrl(QUrl(url))
        except (OSError, RuntimeError):
            opened = False
        if not opened:
            self.status_label.setText('Der Browser konnte nicht geöffnet werden. Bitte prüfen Sie Ihren Standardbrowser.')
        return opened

    def open_paypal(self) -> None:
        try:
            url = paypal_support_url(self._amount_text(), self.recipient)
        except ValueError as error:
            self.status_label.setText(str(error))
            return
        if self._open_url(url):
            self.status_label.setText('PayPal wurde an den Browser übergeben. Eine Zahlung wird erst dort bestätigt.')

    def open_paypal_privacy(self) -> None:
        self._open_url(PAYPAL_PRIVACY_URL)
