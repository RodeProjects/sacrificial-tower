from __future__ import annotations
from pathlib import Path
from html import escape
from PySide6.QtCore import Qt, QSize, Signal, QUrl
from PySide6.QtGui import QFontMetrics, QIcon, QPixmap, QTextDocument
from PySide6.QtWidgets import QDialog, QWidget, QLabel, QPushButton, QGridLayout, QVBoxLayout, QHBoxLayout, QFrame, QScrollArea, QSizePolicy
from cooling_tower.version import APP_NAME, APP_SUBTITLE, APP_VERSION_LABEL
from cooling_tower.legal_documents import legal_profile, render_legal_document
from cooling_tower.runtime_paths import RESOURCE_ROOT
from cooling_tower.gui.widgets.chevron_button import ChevronButton

GUI_ASSET_ROOT = Path(__file__).with_name("assets")
ABOUT_DIALOG_MINIMUM_WIDTH_PX = 450
CURRENT_LICENSE_STATUS = "development"
LICENSE_STATUS_DEFINITIONS = {
    "development": {
        "label": "Entwicklungsversion",
        "description": (
            "Diese kostenlose Version befindet sich noch in Entwicklung und ist nicht "
            "für den regulären Vertrieb bestimmt."
        ),
        "foreground": "#6b4b00",
        "background": "#fff3ce",
        "border": "#e3c365",
    },
    "free": {
        "label": "Kostenlose Version",
        "description": "Kostenlose Nutzung einschließlich gewerblicher Verwendung zulässiger Ergebnisse.",
        "foreground": "#17633a",
        "background": "#e7f6ed",
        "border": "#8fc9a5",
    },
}

class _ResponsiveLegalButtonGrid(QWidget):
    """Flow three legal-document actions across as many columns as fit."""

    def __init__(
        self,
        buttons: list[QPushButton],
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.buttons = buttons
        self.grid = QGridLayout(self)
        self.grid.setContentsMargins(0, 0, 0, 0)
        self.grid.setHorizontalSpacing(8)
        self.grid.setVerticalSpacing(8)
        self.column_count = 0
        for button in self.buttons:
            button.setSizePolicy(
                QSizePolicy.Policy.Expanding,
                QSizePolicy.Policy.Fixed,
            )
        # Start with the preferred one-row arrangement so the parent dialog's
        # natural width can account for all three actions. A real resize then
        # reduces the column count when the available viewport is narrower.
        self._relayout(10_000)

    def _columns_for_width(self, width: int) -> int:
        widths = [
            QFontMetrics(button.font()).horizontalAdvance(button.text())
            + button.iconSize().width()
            + 55
            for button in self.buttons
        ]
        spacing = max(0, self.grid.horizontalSpacing())
        if width >= sum(widths) + spacing * (len(widths) - 1):
            return 3
        if width >= sum(sorted(widths, reverse=True)[:2]) + spacing:
            return 2
        return 1

    def _relayout(self, width: int) -> None:
        columns = self._columns_for_width(width)
        if columns == self.column_count:
            return
        for button in self.buttons:
            self.grid.removeWidget(button)
        for index, button in enumerate(self.buttons):
            row, column = divmod(index, columns)
            is_last_unpaired = (
                columns == 2
                and index == len(self.buttons) - 1
                and len(self.buttons) % columns
            )
            self.grid.addWidget(
                button,
                row,
                column,
                1,
                columns if is_last_unpaired else 1,
            )
        for column in range(3):
            self.grid.setColumnStretch(column, 0)
        for column in range(columns):
            self.grid.setColumnStretch(column, 1)
        self.column_count = columns
        self.grid.invalidate()
        self.updateGeometry()

    def resizeEvent(self, event: QResizeEvent) -> None:  # noqa: N802
        self._relayout(event.size().width())
        super().resizeEvent(event)


class _LegalDocumentButton(ChevronButton):
    """Keep the document chevron aligned at the far right of the button."""

    def __init__(self, caption: str, parent: QWidget | None = None) -> None:
        super().__init__(caption, parent)

    def set_document_open(self, opened: bool) -> None:
        self.set_opened(opened)
        self.setAccessibleDescription(
            "Dokument geöffnet" if opened else "Dokument geschlossen"
        )


class AboutDialog(QDialog):
    """Owns program information and legal-document presentation."""
    content_changed = Signal()

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        dialog = self
        dialog.setObjectName("aboutDialog")
        dialog.setWindowTitle(f"Über {APP_NAME}")
        dialog.setModal(False)
        dialog.setMinimumWidth(ABOUT_DIALOG_MINIMUM_WIDTH_PX)
        dialog.setSizeGripEnabled(True)

        dialog_layout = QVBoxLayout(dialog)
        dialog_layout.setContentsMargins(0, 0, 0, 0)
        dialog_layout.setSpacing(0)

        scroll = QScrollArea(dialog)
        scroll.setObjectName("aboutScroll")
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setHorizontalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAsNeeded
        )
        scroll.setVerticalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAsNeeded
        )

        content = QWidget()
        content.setObjectName("aboutContent")
        content.setMinimumWidth(320)
        content_layout = QVBoxLayout(content)
        content_layout.setContentsMargins(24, 22, 24, 20)
        content_layout.setSpacing(14)
        content_layout.setAlignment(Qt.AlignmentFlag.AlignTop)
        self.about_content_layout = content_layout

        hero = QFrame()
        hero.setObjectName("aboutHero")
        hero.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Maximum)
        hero_layout = QHBoxLayout(hero)
        hero_layout.setContentsMargins(18, 16, 18, 16)
        hero_layout.setSpacing(20)

        program_icon = QLabel()
        program_icon.setObjectName("aboutProgramIcon")
        program_icon.setAccessibleName(f"Programmsymbol {APP_NAME}")
        program_icon.setAlignment(Qt.AlignmentFlag.AlignCenter)
        icon_pixmap = QPixmap(
            str(GUI_ASSET_ROOT / "icon_tower_render.png")
        )
        program_icon.setPixmap(
            icon_pixmap.scaled(
                104,
                140,
                Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.SmoothTransformation,
            )
        )
        program_icon.setFixedSize(108, 144)
        hero_layout.addWidget(program_icon)

        hero_text = QVBoxLayout()
        hero_text.setSpacing(6)
        product_title = QLabel(APP_NAME)
        product_title.setObjectName("aboutProductTitle")
        self.about_product_title = product_title
        product_description = QLabel(APP_SUBTITLE)
        product_description.setObjectName("aboutProductDescription")
        product_description.setWordWrap(True)
        self.about_product_description = product_description
        version = QLabel(APP_VERSION_LABEL)
        version.setObjectName("aboutVersion")
        hero_text.addWidget(product_title)
        hero_text.addWidget(product_description)
        hero_text.addWidget(version)
        hero_layout.addLayout(hero_text, 1)
        hero_layout.setAlignment(hero_text, Qt.AlignmentFlag.AlignVCenter)
        content_layout.addWidget(hero)

        developer_section = QFrame()
        developer_section.setObjectName("aboutSection")
        developer_layout = QVBoxLayout(developer_section)
        developer_layout.setContentsMargins(18, 16, 18, 16)
        developer_layout.setSpacing(10)
        provider = legal_profile()
        developer_name = QLabel(provider["provider_name"])
        developer_name.setTextFormat(Qt.TextFormat.PlainText)
        developer_name.setObjectName("aboutEmphasis")
        self.about_developer_name = developer_name
        self.about_developer_row = self._about_icon_text_row(
            "user.svg",
            "Entwickelt von:",
            heading=True,
            value_widget=developer_name,
        )
        developer_layout.addLayout(self.about_developer_row)
        self.about_copyright_row = self._about_symbol_text_row(
            "©",
            f"2026 {provider['provider_name']} · Alle Rechte vorbehalten.",
        )
        developer_layout.addLayout(self.about_copyright_row)
        proprietary_notice = QLabel(
            "Kostenlose Software. Klonen, Forken und Weiterentwicklung sind "
            "nach der Projektlizenz erlaubt; kommerzielle Weiterverbreitung "
            "ist untersagt. Erzeugte Kühltürme dürfen kommerziell genutzt werden."
        )
        proprietary_notice.setWordWrap(True)
        proprietary_notice.setObjectName("aboutBodyText")
        developer_layout.addWidget(proprietary_notice)
        content_layout.addWidget(developer_section)

        license_section = QFrame()
        license_section.setObjectName("aboutSection")
        license_layout = QVBoxLayout(license_section)
        license_layout.setContentsMargins(18, 16, 18, 16)
        license_layout.setSpacing(9)
        development_status = QLabel()
        development_status.setObjectName("aboutStatusBadge")
        development_status.setSizePolicy(
            QSizePolicy.Policy.Fixed,
            QSizePolicy.Policy.Fixed,
        )
        self.about_license_status_label = development_status
        self.about_license_status_row = self._about_icon_text_row(
            "shield.svg",
            "Lizenzstatus:",
            heading=True,
            value_widget=development_status,
        )
        license_layout.addLayout(self.about_license_status_row)
        development_notice = QLabel()
        development_notice.setWordWrap(True)
        development_notice.setObjectName("aboutBodyText")
        self.about_license_status_description = development_notice
        self._set_about_license_status(CURRENT_LICENSE_STATUS)
        license_layout.addWidget(development_notice)
        content_layout.addWidget(license_section)

        legal_specs = (
            ("document.svg", "Lizenzbedingungen"),
            ("privacy.svg", "Datenschutzerklärung"),
            ("packages.svg", "Drittanbieter-Lizenzen"),
        )
        self.about_legal_buttons: list[QPushButton] = []
        for icon_name, caption in legal_specs:
            button = _LegalDocumentButton(caption)
            button.setObjectName("aboutLegalButton")
            button.setIcon(QIcon(str(GUI_ASSET_ROOT / icon_name)))
            button.setIconSize(QSize(18, 18))
            button.setToolTip(caption)
            button.clicked.connect(
                lambda _checked=False, name=caption: (
                    self.show_document(name)
                )
            )
            self.about_legal_buttons.append(button)
        self.about_legal_grid = _ResponsiveLegalButtonGrid(
            self.about_legal_buttons
        )
        self.about_legal_grid.setObjectName("aboutLegalGrid")
        content_layout.addWidget(self.about_legal_grid)

        self.about_document_label = QLabel()
        self._shown_document_title: str | None = None
        # Preserve the previous public widget handle during the dialog extraction.
        self.about_placeholder_label = self.about_document_label
        self.about_placeholder_label.setObjectName("aboutPlaceholder")
        self.about_placeholder_label.setWordWrap(True)
        self.about_placeholder_label.hide()
        content_layout.addWidget(self.about_placeholder_label)

        support_frame = QFrame()
        support_frame.setObjectName("aboutSupport")
        support_layout = QHBoxLayout(support_frame)
        support_layout.setContentsMargins(14, 10, 14, 10)
        support_layout.setSpacing(9)
        support_icon = QLabel()
        support_icon.setPixmap(
            QIcon(str(GUI_ASSET_ROOT / "mail.svg")).pixmap(20, 20)
        )
        support_icon.setAccessibleName("GitHub Issues")
        support_layout.addWidget(support_icon)
        support_url = escape(provider["support_url"], quote=True)
        support_link = QLabel(
            f'Freiwilliger Support: <a href="{support_url}">'
            '<span style="color:#123c63;">GitHub Issues</span></a>'
        )
        support_link.setObjectName("aboutSupportLink")
        support_link.setOpenExternalLinks(True)
        support_layout.addWidget(support_link, 1)
        content_layout.addWidget(support_frame)

        close_row = QHBoxLayout()
        close_row.addStretch(1)
        close_button = QPushButton("Schließen")
        close_button.setObjectName("aboutCloseButton")
        close_button.setIcon(
            QIcon(str(GUI_ASSET_ROOT / "close.svg"))
        )
        close_button.setIconSize(QSize(18, 18))
        close_button.clicked.connect(dialog.close)
        close_row.addWidget(close_button)
        content_layout.addLayout(close_row)

        scroll.setWidget(content)
        dialog_layout.addWidget(scroll)
        self.about_scroll = scroll
        self.about_content = content
        self.about_program_icon = program_icon
        self.about_support_link = support_link
        self.about_close_button = close_button

    def _about_icon_text_row(
        self,
        icon_name: str,
        text: str,
        *,
        heading: bool = False,
        value_widget: QWidget | None = None,
    ) -> QHBoxLayout:
        row = QHBoxLayout()
        row.setSpacing(8)
        icon = QLabel()
        icon.setPixmap(QIcon(str(GUI_ASSET_ROOT / icon_name)).pixmap(20, 20))
        icon.setFixedSize(22, 22)
        icon.setAlignment(Qt.AlignmentFlag.AlignCenter)
        label = QLabel(text)
        label.setObjectName("aboutSectionTitle" if heading else "aboutMetaText")
        label.setWordWrap(value_widget is None)
        icon_alignment = (
            Qt.AlignmentFlag.AlignVCenter
            if value_widget is not None
            else Qt.AlignmentFlag.AlignTop
        )
        row.addWidget(icon, 0, icon_alignment)
        row.addWidget(label, 0 if value_widget is not None else 1)
        if value_widget is not None:
            row.addWidget(value_widget)
            row.addStretch(1)
        return row

    def _about_symbol_text_row(
        self,
        symbol: str,
        text: str,
    ) -> QHBoxLayout:
        row = QHBoxLayout()
        row.setSpacing(8)
        symbol_label = QLabel(symbol)
        symbol_label.setObjectName("aboutCopyrightSymbol")
        symbol_label.setAccessibleName("Copyright")
        symbol_label.setFixedWidth(22)
        symbol_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        text_label = QLabel(text)
        text_label.setObjectName("aboutMetaText")
        text_label.setWordWrap(True)
        row.addWidget(symbol_label, 0, Qt.AlignmentFlag.AlignTop)
        row.addWidget(text_label, 1)
        self.about_copyright_symbol = symbol_label
        self.about_copyright_text = text_label
        return row

    def _set_about_license_status(self, status: str) -> None:
        try:
            definition = LICENSE_STATUS_DEFINITIONS[status]
        except KeyError as error:
            raise ValueError(f"Unbekannter Lizenzstatus: {status}") from error
        self.about_license_status_label.setText(definition["label"])
        self.about_license_status_label.setProperty("licenseStatus", status)
        self.about_license_status_description.setText(
            definition["description"]
        )
        self.about_license_status_label.style().unpolish(
            self.about_license_status_label
        )
        self.about_license_status_label.style().polish(
            self.about_license_status_label
        )

    def show_document(self, title: str) -> None:
        if self._shown_document_title == title:
            self.reset_document()
            return
        try:
            text = render_legal_document(title)
        except (OSError, ValueError, KeyError) as error:
            text = f"Das Rechtsdokument konnte nicht geladen werden: {error}"
        document = QTextDocument()
        document.setMarkdown(text)
        rendered = document.toHtml()
        if title == "Drittanbieter-Lizenzen":
            location = escape(QUrl.fromLocalFile(str(RESOURCE_ROOT / "legal")).toString(), quote=True)
            rendered = rendered.replace("</body>", f'<p><a href="{location}">Lizenz- und Quellverzeichnis öffnen</a></p></body>')
        self.about_document_label.setTextFormat(Qt.TextFormat.RichText)
        self.about_document_label.setText(rendered)
        self.about_document_label.setTextInteractionFlags(
            Qt.TextInteractionFlag.TextSelectableByMouse | Qt.TextInteractionFlag.LinksAccessibleByMouse
        )
        self.about_document_label.setOpenExternalLinks(True)
        self.about_placeholder_label.show()
        self._shown_document_title = title
        self._sync_legal_button_chevrons()
        self.about_content_layout.invalidate()
        self.content_changed.emit()

    def reset_document(self) -> None:
        self._shown_document_title = None
        self._sync_legal_button_chevrons()
        self.about_document_label.clear()
        self.about_placeholder_label.hide()
        self.about_content_layout.invalidate()
        self.content_changed.emit()

    def _sync_legal_button_chevrons(self) -> None:
        for button in self.about_legal_buttons:
            button.set_document_open(button.text() == self._shown_document_title)
