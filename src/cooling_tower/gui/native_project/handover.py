"""One visual source slot with independently implemented STL/project contents."""
from PySide6.QtCore import QSize, Qt
from PySide6.QtWidgets import QWidget, QSizePolicy, QVBoxLayout


class SourceHandoverStack(QWidget):
    """Hidden project details must not inflate the unchanged STL handover."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName('sourceHandover')
        self.setSizePolicy(QSizePolicy.Policy.Preferred,QSizePolicy.Policy.Maximum)
        self._widgets = []
        self._current = None
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0,0,0,0)
        layout.setSpacing(0)
        # QStackedLayout centres a fixed-height drop zone in surplus space.
        # Keep the selected contents at the top throughout card transitions.
        layout.setAlignment(Qt.AlignmentFlag.AlignTop)

    def addWidget(self,widget):
        self.layout().addWidget(widget)
        self._widgets.append(widget)
        if self._current is None:
            self._current = widget
        else:
            widget.hide()
        return len(self._widgets)-1

    def currentWidget(self):
        return self._current

    def setCurrentWidget(self,widget):
        if widget not in self._widgets:
            raise ValueError('Unknown file handover widget')
        self._current = widget
        for child in self._widgets:
            child.setVisible(child is widget)
        self.layout().invalidate()
        self.updateGeometry()

    def sizeHint(self):
        widget = self.currentWidget()
        return widget.sizeHint().expandedTo(widget.minimumSize()) if widget is not None else QSize(0,0)

    def minimumSizeHint(self):
        widget = self.currentWidget()
        # The empty drop zone reserves more height than its layout's hint.
        # Forward its explicit minimum as well so the outer card cannot clip it.
        return widget.minimumSizeHint().expandedTo(widget.minimumSize()) if widget is not None else QSize(0,0)

    def hasHeightForWidth(self):
        widget = self.currentWidget()
        return widget is not None and widget.hasHeightForWidth()

    def heightForWidth(self,width):
        widget = self.currentWidget()
        if widget is None:
            return 0
        return max(widget.minimumHeight(),
            widget.heightForWidth(width) if widget.hasHeightForWidth() else widget.sizeHint().height())
