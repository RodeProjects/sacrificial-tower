from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSizePolicy,
    QTextEdit,
    QWidget,
)


class _NoticeHeading(QWidget):
    def __init__(self) -> None:
        super().__init__()
        self.setObjectName("stlNoticeHeading")
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(6)
        self.icon = QLabel()
        self.icon.setObjectName("stlFeedbackIcon")
        self.icon.setFixedWidth(16)
        self.icon.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.title = QLabel()
        self.title.setObjectName("stlFeedbackTitle")
        self.title.setTextFormat(Qt.TextFormat.PlainText)
        self.title.setWordWrap(True)
        layout.addWidget(self.icon, 0, Qt.AlignmentFlag.AlignTop)
        layout.addWidget(self.title, 1)
        self.hide()

    def set_notice(self, title: str, severity: str, icon: str) -> None:
        self.icon.setText(icon)
        self.title.setText(title)
        for label in (self.icon, self.title):
            label.setProperty("severity", severity)
            label.style().unpolish(label)
            label.style().polish(label)
        self.show()

    def clear(self) -> None:
        self.icon.clear()
        self.title.clear()
        self.hide()


class StlValidationFeedback(QWidget):
    """Compact notices with a shared header row for collapsed diagnostics.

    Only the heading shares space with the disclosure. Explanation text always
    spans both columns; opening diagnostics moves the heading below them.
    """

    def __init__(self) -> None:
        super().__init__()
        self.setObjectName("stlValidationFeedback")
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        self.grid = QGridLayout(self)
        self.grid.setContentsMargins(10, 0, 6, 2)
        self.grid.setHorizontalSpacing(12)
        self.grid.setVerticalSpacing(3)
        self.grid.setColumnStretch(0, 1)
        self.heading = _NoticeHeading()
        self.warning_heading = _NoticeHeading()
        self.warning_heading.layout().setContentsMargins(0, 8, 0, 0)
        self.message = self._body("stlValidationMessage")
        self.warning_message = self._body("stlValidationWarningMessage")
        self.details_toggle = QPushButton("Details anzeigen ▸")
        self.details_toggle.setObjectName("stlValidationDetailsToggle")
        self.details_toggle.setProperty("compactDisclosure", True)
        self.details_toggle.setAccessibleName("Details einblenden")
        self.details_toggle.setCheckable(True)
        self.details_toggle.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.details_toggle.setCursor(Qt.CursorShape.PointingHandCursor)
        self.details_toggle.setMinimumHeight(24)
        self.details_toggle.setSizePolicy(
            QSizePolicy.Policy.Maximum, QSizePolicy.Policy.Fixed
        )
        self.details_toggle.hide()
        self.details = QTextEdit()
        self.details.setObjectName("stlValidationDetails")
        self.details.setReadOnly(True)
        self.details.setFixedHeight(150)
        self.details.setSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed
        )
        self.details.hide()
        self.grid.addWidget(self.heading, 0, 0, Qt.AlignmentFlag.AlignVCenter)
        self.grid.addWidget(self.details_toggle, 0, 1, Qt.AlignmentFlag.AlignRight)
        self.grid.addWidget(self.details, 1, 0, 1, 2)
        self.grid.addWidget(self.message, 3, 0, 1, 2)
        self.grid.addWidget(self.warning_heading, 4, 0, 1, 2)
        self.grid.addWidget(self.warning_message, 5, 0, 1, 2)
        self.hide()

    @staticmethod
    def _body(name: str) -> QLabel:
        label = QLabel()
        label.setObjectName(name)
        label.setProperty("severity", "neutral")
        label.setTextFormat(Qt.TextFormat.RichText)
        label.setWordWrap(True)
        label.setContentsMargins(0, 0, 0, 0)
        label.hide()
        return label

    def set_primary(self, title: str, text: str, *, severity: str, icon: str) -> None:
        self.heading.set_notice(title, severity, icon)
        self.message.setText(text)
        self.message.setProperty("severity", severity)
        self.message.show()
        self.show()

    def set_warning(self, title: str, text: str) -> None:
        self.warning_heading.set_notice(title, "warning", "ⓘ")
        self.warning_message.setText(text)
        self.warning_message.setProperty("severity", "warning")
        self.warning_message.show()
        self.show()

    def clear_warning(self) -> None:
        self.warning_heading.clear()
        self.warning_message.clear()
        self.warning_message.setProperty("severity", "neutral")
        self.warning_message.hide()

    def set_expanded(self, expanded: bool) -> None:
        self.details.setVisible(expanded)
        self.grid.removeWidget(self.heading)
        if expanded:
            self.grid.addWidget(self.heading, 2, 0, 1, 2)
        else:
            self.grid.addWidget(self.heading, 0, 0, Qt.AlignmentFlag.AlignVCenter)
        self.grid.invalidate()
        self.updateGeometry()

    def clear(self) -> None:
        self.heading.clear()
        self.message.clear()
        self.message.setProperty("severity", "neutral")
        self.message.hide()
        self.clear_warning()
        self.details.clear()
        self.details_toggle.setChecked(False)
        self.set_expanded(False)
        self.details_toggle.hide()
        self.hide()
