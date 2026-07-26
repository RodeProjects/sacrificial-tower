from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QPushButton,
    QSizePolicy,
    QToolButton,
    QVBoxLayout,
    QWidget,
)


class FooterNoticeDropdown(QFrame):
    """Compact, accessible footer notice that starts collapsed."""

    toggled = Signal(bool)

    def __init__(
        self,
        title: str,
        *,
        severity: str,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setObjectName("issuePanel")
        self.setProperty("severity", severity)
        self.setSizePolicy(
            QSizePolicy.Policy.Expanding,
            QSizePolicy.Policy.Maximum,
        )

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        self.header_widget = QFrame(self)
        self.header_widget.setObjectName("footerNoticeHeaderRow")
        header_layout = QHBoxLayout(self.header_widget)
        header_layout.setContentsMargins(0, 0, 0, 0)
        header_layout.setSpacing(0)

        self.header_button = QPushButton(self.header_widget)
        self.header_button.setObjectName("footerNoticeHeader")
        self.header_button.setProperty("severity", severity)
        self.header_button.setCheckable(True)
        self.header_button.setChecked(False)
        self.header_button.setText(title)
        self.header_button.setAccessibleName(f"{title}, eingeklappt")
        self.header_button.setSizePolicy(
            QSizePolicy.Policy.Expanding,
            QSizePolicy.Policy.Fixed,
        )
        header_layout.addWidget(self.header_button, 1)

        # A dedicated fixed-width control is more reliable than Qt's
        # text/arrow layout heuristics and keeps every chevron at the far
        # right, independent of title length or platform style.
        self.chevron_button = QToolButton(self.header_widget)
        self.chevron_button.setObjectName("footerNoticeChevron")
        self.chevron_button.setProperty("severity", severity)
        self.chevron_button.setArrowType(Qt.ArrowType.DownArrow)
        self.chevron_button.setToolButtonStyle(
            Qt.ToolButtonStyle.ToolButtonIconOnly
        )
        self.chevron_button.setAccessibleName(
            f"{title} ausklappen"
        )
        self.chevron_button.setSizePolicy(
            QSizePolicy.Policy.Fixed,
            QSizePolicy.Policy.Fixed,
        )
        header_layout.addWidget(self.chevron_button)
        root.addWidget(self.header_widget)

        self.content_widget = QFrame(self)
        self.content_widget.setObjectName("footerNoticeBody")
        self.content_layout = QVBoxLayout(self.content_widget)
        self.content_layout.setContentsMargins(12, 8, 12, 8)
        self.content_layout.setSpacing(4)
        self.content_layout.setAlignment(Qt.AlignmentFlag.AlignTop)
        self.content_widget.hide()
        root.addWidget(self.content_widget)

        self.header_button.toggled.connect(self._set_expanded)
        self.chevron_button.clicked.connect(self.header_button.toggle)

    def title(self) -> str:
        return self.header_button.text()

    def set_title(self, title: str) -> None:
        self.header_button.setText(title)
        state = "ausgeklappt" if self.is_expanded() else "eingeklappt"
        self.header_button.setAccessibleName(f"{title}, {state}")

    def is_expanded(self) -> bool:
        return self.header_button.isChecked()

    def set_expanded(self, expanded: bool) -> None:
        self.header_button.setChecked(bool(expanded))

    def reset_collapsed(self) -> None:
        self.set_expanded(False)

    def _set_expanded(self, expanded: bool) -> None:
        self.content_widget.setVisible(expanded)
        self.chevron_button.setArrowType(
            Qt.ArrowType.UpArrow
            if expanded
            else Qt.ArrowType.DownArrow
        )
        self.chevron_button.setAccessibleName(
            f"{self.title()} "
            f"{'einklappen' if expanded else 'ausklappen'}"
        )
        self.header_button.setAccessibleName(
            f"{self.title()}, "
            f"{'ausgeklappt' if expanded else 'eingeklappt'}"
        )
        self.updateGeometry()
        self.toggled.emit(expanded)
