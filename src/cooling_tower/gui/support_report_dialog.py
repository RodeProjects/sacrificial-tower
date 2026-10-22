from __future__ import annotations

from collections.abc import Callable, Mapping
from html import escape
from pathlib import Path
from typing import Any

from PySide6.QtCore import QEasingCurve, QPoint, QPropertyAnimation, QSequentialAnimationGroup, QSize, Qt, QUrl, QUrlQuery, Signal
from PySide6.QtGui import QColor, QDesktopServices, QIcon, QPainter, QPen
from PySide6.QtWidgets import (
    QDialog, QFrame, QGraphicsOpacityEffect, QGridLayout, QHBoxLayout, QLabel, QPushButton,
    QScrollArea, QSizePolicy, QTabWidget, QVBoxLayout, QWidget,
)

from cooling_tower.gui.widgets.preparation_controls import (
    PREPARATION_TRANSITION_DURATION_MS, _SequentialPreparationTabs,
)
from cooling_tower.gui.widgets.hint_popover import hide_window_hint
from cooling_tower.gui.widgets.info_tool_button import InfoToolButton
from cooling_tower.support_report import SupportReportService
from cooling_tower.legal_documents import legal_profile


SUPPORT_TOPICS = (
    ("bug", "Fehler melden", "Etwas funktioniert nicht wie erwartet.", "document.svg"),
    ("question", "Frage stellen", "Hilfe zur Bedienung oder zum Projekt erhalten.", "info_circle.svg"),
    ("feature", "Funktion vorschlagen", "Eine Idee oder Verbesserung einbringen.", "settings_gear.svg"),
    ("review", "Bewertung abgeben", "Erfahrungen mit dem Programm teilen.", "star.svg"),
    ("support", "Entwickler unterstützen", "Mit einem Kaffee Danke sagen.", "coffee.svg"),
    ("contact", "Etwas anderes", "Andere oder vertrauliche Anliegen", "mail.svg"),
)
ISSUE_TEMPLATES = {"bug": "01-bug.yml", "feature": "02-feature.yml", "question": "03-question.yml"}
ISSUE_ACTIONS = {
    "bug": "Fehler auf GitHub melden",
    "question": "Frage auf GitHub stellen",
    "feature": "Funktion auf GitHub vorschlagen",
}


class _SupportLayoutButton(QPushButton):
    """Include child contents when Qt sizes a button with its own layout."""

    def sizeHint(self) -> QSize:  # noqa: N802
        return self.layout().totalSizeHint() if self.layout() is not None else super().sizeHint()

    def minimumSizeHint(self) -> QSize:  # noqa: N802
        return self.layout().totalMinimumSize() if self.layout() is not None else super().minimumSizeHint()


class _SupportContactLink(_SupportLayoutButton):
    def _set_link_hover(self, hovered: bool) -> None:
        address = self.findChild(QLabel, "supportContactLinkText")
        if address is not None:
            address.setProperty("linkHovered", hovered)
            style = address.style()
            style.unpolish(address)
            style.polish(address)
            address.update()

    def enterEvent(self, event) -> None:  # noqa: N802
        super().enterEvent(event)
        self._set_link_hover(True)

    def leaveEvent(self, event) -> None:  # noqa: N802
        super().leaveEvent(event)
        self._set_link_hover(False)

    def hideEvent(self, event) -> None:  # noqa: N802
        self._set_link_hover(False)
        super().hideEvent(event)


class _SupportTopicCard(_SupportLayoutButton):
    def __init__(self, title: str, description: str, icon: QIcon) -> None:
        super().__init__()
        self.setObjectName("supportTopicCard")
        self.setAutoDefault(False)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setAccessibleName(title)
        self.setAccessibleDescription(description)
        policy = QSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        policy.setHeightForWidth(True)
        self.setSizePolicy(policy)
        row = QHBoxLayout(self)
        row.setContentsMargins(14, 11, 14, 11)
        row.setSpacing(12)
        picture = QLabel()
        picture.setPixmap(icon.pixmap(24, 24))
        row.addWidget(picture)
        words = QVBoxLayout()
        words.setSpacing(3)
        for text, name in ((title, "supportTopicTitle"), (description, "supportTopicDescription")):
            label = QLabel(text)
            label.setObjectName(name)
            label.setWordWrap(True)
            label.setTextFormat(Qt.TextFormat.PlainText)
            words.addWidget(label)
        row.addLayout(words, 1)
        for label in self.findChildren(QLabel):
            label.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)

    def heightForWidth(self, width: int) -> int:  # noqa: N802
        return self.layout().totalHeightForWidth(width)

    def keyPressEvent(self, event) -> None:  # noqa: N802
        if event.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
            self.click()
            event.accept()
            return
        super().keyPressEvent(event)


class _SupportPages(_SequentialPreparationTabs):
    """Fade between support pages while keeping the dialog manually resizable."""

    def _create_overlay_animation(
        self, overlays: tuple[tuple[QLabel, QPoint, QPoint], ...],
    ) -> QSequentialAnimationGroup:
        group = QSequentialAnimationGroup(self)
        outgoing_duration = self._effective_transition_duration_ms // 2
        for index, (overlay, start, end) in enumerate(overlays):
            overlay.move(start if index == 0 else end)
            effect = QGraphicsOpacityEffect(overlay)
            effect.setOpacity(1.0 if index == 0 else 0.0)
            overlay.setGraphicsEffect(effect)
            animation = QPropertyAnimation(effect, b"opacity", group)
            animation.setDuration(
                outgoing_duration if index == 0 else self._effective_transition_duration_ms - outgoing_duration
            )
            animation.setStartValue(1.0 if index == 0 else 0.0)
            animation.setEndValue(0.0 if index == 0 else 1.0)
            animation.setEasingCurve(QEasingCurve.Type.InOutCubic)
            group.addAnimation(animation)
        return group

    def minimumSizeHint(self) -> QSize:  # noqa: N802
        return QSize(0, 0)

    def reset_to_selection(self) -> None:
        self._finish_transition()
        QTabWidget.setCurrentIndex(self, 0)

    def _finish_transition(self) -> None:
        super()._finish_transition()
        self.setMinimumHeight(0)
        self.setMaximumHeight(16777215)

    def resizeEvent(self, event) -> None:  # noqa: N802
        if self._transition_animation is not None:
            self._complete_transition()
        super().resizeEvent(event)


class _SupportWorkflowFrame(QFrame):
    """Connect step markers without affecting the height of their contents."""

    def __init__(self) -> None:
        super().__init__()
        self.markers: list[QLabel] = []

    def paintEvent(self, event) -> None:  # noqa: N802
        super().paintEvent(event)
        if len(self.markers) < 2:
            return
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setPen(QPen(QColor("#d5e0e9"), 1.0))
        painter.drawLine(
            self.markers[0].geometry().center(),
            self.markers[-1].geometry().center(),
        )


class SupportReportDialog(QDialog):
    """Route support requests to their own short, local guidance."""

    bundle_created = Signal()
    geometry_requested = Signal(bool)
    voluntary_support_requested = Signal()

    def __init__(
        self, service: SupportReportService, *,
        application_context_provider: Callable[[], Mapping[str, Any]],
        open_directory: Callable[[str | Path], None], asset_root: Path, parent=None,
    ) -> None:
        super().__init__(parent)
        self.service = service
        self._application_context_provider = application_context_provider
        self._open_directory = open_directory
        self._asset_root = Path(asset_root)
        self.last_bundle_path: Path | None = None
        self.selected_topic: str | None = None
        self._sizing_page: int | None = None
        self.setObjectName("supportReportDialog")
        self.setWindowTitle("Support & Diagnose")
        self.setModal(False)
        self.setMinimumSize(520, 360)
        self.resize(700, 670)
        self._build_ui()

    @property
    def content(self) -> QWidget:
        index = self.pages.currentIndex() if self._sizing_page is None else self._sizing_page
        return self.selection_content if index == 0 else self.detail_content

    @property
    def content_layout(self) -> QVBoxLayout:
        return self.content.layout()

    @property
    def scroll(self) -> QScrollArea:
        index = self.pages.currentIndex() if self._sizing_page is None else self._sizing_page
        return self.selection_scroll if index == 0 else self.detail_scroll

    def content_height_for_width(self, width: int) -> int:
        return self._content_height(self.content, width)

    def maximum_content_height_for_width(self, width: int) -> int:
        return max(
            self._content_height(content, width)
            for content in (self.selection_content, *self.route_contents.values())
        )

    @staticmethod
    def _content_height(content: QWidget, width: int) -> int:
        content.layout().invalidate()
        for widget in content.findChildren(QWidget):
            if widget.layout() is not None:
                widget.layout().invalidate()
        return content.layout().totalMinimumHeightForWidth(width)

    @staticmethod
    def _label(text: str, name: str) -> QLabel:
        label = QLabel(text)
        label.setObjectName(name)
        label.setWordWrap(True)
        label.setTextFormat(Qt.TextFormat.PlainText)
        return label

    def _step(self, title: str) -> QVBoxLayout:
        layout = QVBoxLayout()
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(7)
        layout.addWidget(self._label(title, "supportReportStepTitle"))
        return layout

    def _button(
        self, text: str, name: str, icon: str | None = None, *,
        button_type: type[QPushButton] = QPushButton,
    ) -> QPushButton:
        button = button_type(text)
        button.setObjectName(name)
        button.setProperty("supportAction", name != "supportReportClose")
        if icon is not None:
            button.setIcon(QIcon(str(self._asset_root / icon)))
            button.setIconSize(QSize(16, 16))
        button.setAutoDefault(False)
        button.setCursor(Qt.CursorShape.PointingHandCursor)
        return button

    @staticmethod
    def _scroll_for(content: QWidget) -> QScrollArea:
        scroll = QScrollArea()
        scroll.setObjectName("supportReportScroll")
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        scroll.setWidget(content)
        return scroll

    def _heading(self, layout: QVBoxLayout, title: str, introduction: str) -> None:
        for text, name in ((title, "supportReportTitle"), (introduction, "supportReportIntroduction")):
            label = self._label(text, name)
            label.setAlignment(Qt.AlignmentFlag.AlignHCenter)
            layout.addWidget(label)

    def _build_ui(self) -> None:
        outer = QVBoxLayout(self)
        outer.setContentsMargins(22, 20, 22, 18)
        outer.setSpacing(12)
        self._build_bug_content()
        self.selection_content = QWidget()
        self.selection_content.setObjectName("supportReportContent")
        selection = QVBoxLayout(self.selection_content)
        selection.setContentsMargins(0, 0, 0, 0)
        selection.setSpacing(10)
        self._heading(selection, "Was möchten Sie tun?", "Klicken Sie auf Ihr Anliegen, um den passenden Bereich zu öffnen.")
        choices = QGridLayout()
        choices.setSpacing(8)
        choices.setColumnStretch(0, 1)
        choices.setColumnStretch(1, 1)
        self.topic_buttons: dict[str, _SupportTopicCard] = {}
        for index, (key, title, description, icon) in enumerate(SUPPORT_TOPICS):
            card = _SupportTopicCard(title, description, QIcon(str(self._asset_root / icon)))
            self.topic_buttons[key] = card
            card.clicked.connect(lambda checked=False, topic=key: self._select_topic(topic))
            choices.addWidget(card, index % 3, index // 3)
        selection.addLayout(choices)
        selection.addStretch(1)
        self.detail_content = QWidget()
        self.detail_content.setObjectName("supportReportContent")
        detail = QVBoxLayout(self.detail_content)
        detail.setContentsMargins(0, 0, 0, 0)
        detail.setSpacing(0)
        self.route_contents = {"bug": self.bug_content}
        for topic in ("question", "feature", "review", "contact"):
            self.route_contents[topic] = self._build_simple_route(topic)
        for route in self.route_contents.values():
            detail.addWidget(route)
            route.hide()
        detail.addStretch(1)
        self.selection_scroll = self._scroll_for(self.selection_content)
        self.detail_scroll = self._scroll_for(self.detail_content)
        self.pages = _SupportPages(transition_duration_ms=PREPARATION_TRANSITION_DURATION_MS)
        self.pages.setObjectName("supportReportPages")
        self.pages.addTab(self.selection_scroll, "Auswahl")
        self.pages.addTab(self.detail_scroll, "Anliegen")
        self.pages.tabBar().hide()
        self.pages.set_step_guard(lambda index: index == 0 or self.selected_topic is not None)
        self.pages.set_transition_targets(
            (self.selection_scroll.viewport(), self.detail_scroll.viewport()), self._prepare_page_layout
        )
        outer.addWidget(self.pages, 1)
        actions = QHBoxLayout()
        actions.setSpacing(8)
        self.back_button = self._button("Zurück", "supportReportBack")
        self.back_button.clicked.connect(lambda: self._navigate(0))
        actions.addWidget(self.back_button)
        actions.addStretch(1)
        self.skip_button = self._button("Ohne Diagnosepaket fortfahren", "supportReportSkip")
        self.skip_button.clicked.connect(lambda: QDesktopServices.openUrl(self.issue_url("bug")))
        actions.addWidget(self.skip_button)
        self.close_button = self._button("Schließen", "supportReportClose", "close.svg")
        self.close_button.clicked.connect(self.close)
        actions.addWidget(self.close_button)
        outer.addLayout(actions)
        self.pages.currentChanged.connect(self._page_changed)
        self.pages.transition_started.connect(self._transition_started)
        self._update_navigation()

    def _build_simple_route(self, topic: str) -> QWidget:
        content = QWidget()
        layout = QVBoxLayout(content)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(14)
        definitions = {
            "question": ("Frage stellen", "Hilfe zur Bedienung oder zum Projekt"),
            "feature": ("Funktion vorschlagen", "Ihre Idee für Sacrificial Tower"),
            "review": ("Bewertung abgeben", "Danke, dass Sie Ihre Erfahrungen teilen möchten."),
            "contact": ("Kontakt aufnehmen", "Direkter Kontakt zum Entwickler"),
        }
        self._heading(layout, *definitions[topic])
        panel = QFrame()
        panel.setObjectName("supportInfoPanel")
        body = QVBoxLayout(panel)
        body.setContentsMargins(20, 18, 20, 18)
        body.setSpacing(14)
        if topic in ISSUE_TEMPLATES:
            text = (
                "Beschreiben Sie Ihre Frage und was Sie bereits ausprobiert haben. "
                "Ein Diagnosepaket ist dafür normalerweise nicht nötig."
                if topic == "question" else
                "Beschreiben Sie Ihre Idee und wofür sie hilfreich wäre. "
                "Ein Diagnosepaket ist für einen Funktionswunsch nicht nötig."
            )
            body.addWidget(self._label(text, "supportRouteDescription"))
            body.addWidget(self._label(
                "Das passende GitHub-Formular öffnet sich im Browser. Dort können Sie "
                "Ihr Anliegen beschreiben und absenden. GitHub-Konto erforderlich; "
                "Meldungen und Anhänge sind öffentlich sichtbar.", "supportReportAccountHint"
            ))
            button = self._button(ISSUE_ACTIONS[topic], "supportReportIssueButton", "external_link_white.svg")
            button.clicked.connect(lambda checked=False, key=topic: QDesktopServices.openUrl(self.issue_url(key)))
            setattr(self, topic + "_button", button)
            body.addWidget(button, 0, Qt.AlignmentFlag.AlignHCenter)
        elif topic == "review":
            stars = QHBoxLayout()
            stars.setSpacing(6)
            stars.addStretch(1)
            for _ in range(5):
                icon = QLabel()
                icon.setObjectName("supportReviewStar")
                icon.setFixedSize(20, 20)
                icon.setPixmap(QIcon(str(self._asset_root / "star.svg")).pixmap(20, 20))
                stars.addWidget(icon)
            stars.addStretch(1)
            body.addLayout(stars)
            notice = self._label(
                "Aktuell gibt es noch keine Plattformen, auf denen Sie Sacrificial Tower "
                "bewerten können.\nSobald Bewertungsmöglichkeiten verfügbar sind, "
                "finden Sie hier die passenden Links.", "supportReviewPlaceholder"
            )
            notice.setAlignment(Qt.AlignmentFlag.AlignHCenter)
            body.addWidget(notice)
        else:
            body.setSpacing(14)
            email = legal_profile()["provider_email"]
            introduction = self._label(
                "Für andere oder vertrauliche Anliegen können Sie mich gerne "
                "per E-Mail kontaktieren.", "supportRouteDescription"
            )
            introduction.setAlignment(Qt.AlignmentFlag.AlignHCenter)
            body.addWidget(introduction)
            self.contact_button = self._button("", "supportReportContact", button_type=_SupportContactLink)
            self.contact_button.setAccessibleName(email)
            contact_row = QHBoxLayout(self.contact_button)
            # Balance the visible gap below the text with the introduction above.
            contact_row.setContentsMargins(11, 5, 11, 9)
            contact_row.setSpacing(10)
            icon = QLabel()
            icon.setObjectName("supportContactLinkIcon")
            icon.setFixedSize(18, 18)
            icon.setPixmap(QIcon(str(self._asset_root / "mail.svg")).pixmap(18, 18))
            address = self._label(email, "supportContactLinkText")
            address.setWordWrap(False)
            for element in (icon, address):
                element.setAlignment(Qt.AlignmentFlag.AlignVCenter)
                element.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
                contact_row.addWidget(element, 0, Qt.AlignmentFlag.AlignVCenter)
            self.contact_button.clicked.connect(lambda: QDesktopServices.openUrl(QUrl(f"mailto:{email}")))
            body.addWidget(self.contact_button, 0, Qt.AlignmentFlag.AlignHCenter)
            divider = QFrame()
            divider.setObjectName("supportContactDivider")
            divider.setFixedHeight(1)
            body.addWidget(divider)
            guidance_layout = QVBoxLayout()
            guidance_layout.setSpacing(5)
            guidance_layout.addWidget(self._label(
                "Der passende Kanal für Ihr Anliegen", "supportContactGuidanceTitle"
            ))
            guidance_layout.addWidget(self._label(
                "Passt Ihr Anliegen zu „Fehler melden“, „Frage stellen“ oder "
                "„Funktion vorschlagen“, nutzen Sie bitte die jeweilige Rubrik "
                "und das dort verlinkte GitHub-Formular.", "supportContactGuidanceText"
            ))
            body.addLayout(guidance_layout)
        layout.addWidget(panel)
        layout.addStretch(1)
        return content

    @staticmethod
    def issue_url(topic: str) -> QUrl:
        url = QUrl(legal_profile()["support_url"])
        url.setPath(url.path().removesuffix("/choose"))
        query = QUrlQuery()
        query.addQueryItem("template", ISSUE_TEMPLATES[topic])
        url.setQuery(query)
        return url

    def _select_topic(self, topic: str) -> None:
        if self.pages._transition_animation is not None:
            return
        if topic == "support":
            if self.close():
                self.voluntary_support_requested.emit()
            return
        self.selected_topic = topic
        self._update_navigation()
        self._continue_to_topic()

    def _continue_to_topic(self) -> None:
        if self.selected_topic is None or self.pages._transition_animation is not None:
            return
        for key, content in self.route_contents.items():
            content.setVisible(key == self.selected_topic)
        self.detail_content.layout().invalidate()
        self.detail_scroll.verticalScrollBar().setValue(0)
        self._navigate(1)

    def _navigate(self, index: int) -> None:
        if self.pages._transition_animation is not None or index == self.pages.currentIndex():
            return
        self._sizing_page = index
        try:
            self.geometry_requested.emit(True)
        finally:
            self._sizing_page = None
        self.pages.setCurrentIndex(index)

    def _prepare_page_layout(self) -> None:
        self.layout().activate()
        self.selection_content.layout().activate()
        self.detail_content.layout().activate()

    def _transition_started(self, old: int, new: int, duration: int) -> None:
        hide_window_hint(self)
        self.back_button.hide()
        self.back_button.setEnabled(False)
        self.selection_content.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)

    def _page_changed(self, index: int) -> None:
        self._update_navigation()
        if self.isVisible():
            self.geometry_requested.emit(False)

    def _update_navigation(self) -> None:
        selection = self.pages.currentIndex() == 0
        self.back_button.setVisible(not selection)
        self.back_button.setEnabled(True)
        self.selection_content.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, False)
        self.skip_button.setVisible(not selection and self.selected_topic == "bug" and self.last_bundle_path is None)

    def hideEvent(self, event) -> None:  # noqa: N802
        hide_window_hint(self)
        if not event.spontaneous():
            self.selected_topic = None
            self.pages.reset_to_selection()
            self.selection_scroll.verticalScrollBar().setValue(0)
            self._update_navigation()
        super().hideEvent(event)

    def _build_bug_content(self) -> None:
        self.bug_content = QWidget()
        self.bug_content.setObjectName("supportReportContent")
        self.bug_layout = QVBoxLayout(self.bug_content)
        self.bug_layout.setContentsMargins(0, 0, 0, 0)
        self.bug_layout.setSpacing(12)
        title = self._label("Fehler melden", "supportReportTitle")
        title.setAlignment(Qt.AlignmentFlag.AlignHCenter)
        self.bug_layout.addWidget(title)
        self.workflow_frame = _SupportWorkflowFrame()
        self.workflow_frame.setObjectName("supportReportWorkflow")
        workflow = QGridLayout(self.workflow_frame)
        workflow.setContentsMargins(14, 16, 16, 16)
        workflow.setHorizontalSpacing(12)
        workflow.setVerticalSpacing(14)
        workflow.setColumnStretch(1, 1)
        for number, row in enumerate((0, 2, 4), 1):
            marker = QLabel(str(number))
            marker.setObjectName("supportReportStepMarker")
            marker.setAccessibleName(f"Schritt {number}")
            marker.setAlignment(Qt.AlignmentFlag.AlignCenter)
            marker.setFixedSize(24, 24)
            workflow.addWidget(marker, row, 0, Qt.AlignmentFlag.AlignTop)
            self.workflow_frame.markers.append(marker)
        self.bug_layout.addWidget(self.workflow_frame)

        create_layout = self._step("Diagnosepaket erstellen")
        create_layout.addWidget(self._label(
            "Optional, aber sehr hilfreich bei der Fehlersuche.\nDie ZIP bleibt lokal.",
            "supportReportCreateHint",
        ))
        workflow.addLayout(create_layout, 0, 1)
        self.create_button = self._button(
            "Diagnosepaket erstellen", "primaryButton", "document_white.svg"
        )
        self.create_button.clicked.connect(self.create_bundle)
        workflow.addWidget(self.create_button, 0, 2, Qt.AlignmentFlag.AlignTop)
        self.result_label = self._label("", "supportReportResult")
        self.result_label.hide()
        self.result_label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        workflow.addWidget(self.result_label, 1, 1, 1, 2)

        review_layout = self._step("ZIP prüfen")
        review_layout.addWidget(self._label(
            "Prüfen Sie alle Dateien in der ZIP aus Schritt 1 auf persönliche Daten.",
            "supportReportReviewHint",
        ))
        privacy_row = QHBoxLayout()
        privacy_row.setSpacing(6)
        privacy_summary = self._label("Nicht garantiert anonym.", "supportReportPrivacySummary")
        privacy_summary.setWordWrap(False)
        privacy_row.addWidget(privacy_summary)
        self.privacy_info = InfoToolButton(
            "Das Diagnosepaket enthält nur freigegebene technische Angaben.\n\n"
            "Profilnamen, freie Fehlermeldungen, Rohlogs, Originaldateien und Profile "
            "werden nicht beigefügt. Vollständige Anonymität ist trotzdem nicht garantiert.\n\n"
            "Prüfen Sie vor dem Hochladen auch eigene Texte, Screenshots und Anhänge. "
            "Sie werden nicht automatisch bereinigt. Meldungen und Anhänge auf GitHub "
            "sind öffentlich. Persönliche oder sensible Daten nicht veröffentlichen.\n\n"
            "Die Dateien lassen sich meist direkt in der ZIP lesen. Entpacken ist nur bei Bedarf nötig.",
            accessible_name="Datenschutzhinweise zum Diagnosepaket",
            object_name="settingInfoButton", diameter_px=20,
        )
        self.privacy_info.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.privacy_info.setCursor(Qt.CursorShape.PointingHandCursor)
        self.privacy_info.clicked.connect(self.privacy_info.show_hint)
        privacy_row.addWidget(self.privacy_info)
        privacy_row.addStretch(1)
        review_layout.addLayout(privacy_row)
        workflow.addLayout(review_layout, 2, 1)
        self.open_folder_button = self._button(
            "Ordner öffnen", "supportReportOpenFolder", "folder.svg"
        )
        self.open_folder_button.setEnabled(False)
        self.open_folder_button.clicked.connect(self.open_report_folder)
        workflow.addWidget(self.open_folder_button, 2, 2, Qt.AlignmentFlag.AlignTop)
        issue_layout = self._step("Auf GitHub melden")
        self.issue_hint = self._label(
            "Fehler beschreiben, die geprüfte ZIP bei Bedarf anhängen und Meldung absenden.",
            "supportReportIssueHint",
        )
        issue_layout.addWidget(self.issue_hint)
        workflow.addLayout(issue_layout, 4, 1)
        self.issue_button = self._button(
            ISSUE_ACTIONS["bug"], "supportReportIssueButton", "external_link_white.svg"
        )
        self.issue_button.setToolTip("Öffnet das Fehlerformular auf GitHub")
        support_url = self.issue_url("bug")
        self.issue_button.clicked.connect(lambda: QDesktopServices.openUrl(support_url))
        workflow.addWidget(self.issue_button, 4, 2, Qt.AlignmentFlag.AlignTop)
        workflow.addWidget(self._label(
            "Freiwilliger Support. GitHub-Konto nötig. Meldungen und Anhänge sind öffentlich.",
            "supportReportAccountHint",
        ), 5, 1, 1, 2)
        self.bug_layout.addStretch(1)

    def create_bundle(self) -> None:
        self.create_button.setEnabled(False)
        self.result_label.show()
        self.result_label.setTextFormat(Qt.TextFormat.PlainText)
        self.result_label.setProperty("state", "working")
        self.result_label.setText("Diagnosepaket wird erstellt …")
        self._refresh_result_style()
        try:
            bundle = self.service.create_bundle(
                application_context=self._application_context_provider(),
            )
        except Exception as error:  # GUI boundary: keep report failures visible
            self.result_label.setProperty("state", "error")
            self.result_label.setText(f"Das Diagnosepaket konnte nicht erstellt werden: {error}")
            self._refresh_result_style()
            self.geometry_requested.emit(False)
            return
        finally:
            self.create_button.setEnabled(True)
        self.last_bundle_path = bundle.path
        self.open_folder_button.setEnabled(True)
        self.result_label.setProperty("state", "success")
        self.result_label.setTextFormat(Qt.TextFormat.RichText)
        self.result_label.setText(
            "ZIP erstellt – noch nicht gesendet:<br>"
            f"<b>{escape(bundle.path.name)}</b><br>"
            "Weiter mit Schritt 2: ZIP prüfen."
        )
        self._refresh_result_style()
        self._update_navigation()
        self.bundle_created.emit()

    def open_report_folder(self) -> None:
        try:
            directory = self.service.ensure_output_directory()
            self._open_directory(directory)
        except OSError as error:
            self.result_label.setProperty("state", "error")
            self.result_label.setTextFormat(Qt.TextFormat.PlainText)
            self.result_label.setText(f"Der Ordner konnte nicht geöffnet werden: {error}")
            self._refresh_result_style()
            self.geometry_requested.emit(False)

    def _refresh_result_style(self) -> None:
        self.result_label.style().unpolish(self.result_label)
        self.result_label.style().polish(self.result_label)
