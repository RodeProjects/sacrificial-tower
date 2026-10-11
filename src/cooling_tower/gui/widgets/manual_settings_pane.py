"""Settings viewport with a narrow, full-height collapse rail outside the scroll area."""
from PySide6.QtCore import QSize,Qt,Signal
from PySide6.QtWidgets import QWidget,QToolButton,QSizePolicy


class ManualSettingsPane(QWidget):
    toggle_requested=Signal()
    RAIL_WIDTH=18

    def __init__(self,scroll,parent=None):
        super().__init__(parent)
        self.scroll=scroll
        self.compact=False
        self.animating=False
        self.content_width=scroll.minimumWidth()
        self.clip=QWidget(self)
        scroll.setParent(self.clip)
        self.button=QToolButton(self)
        self.button.setObjectName("manualSettingsCollapseButton")
        self.button.setFixedWidth(self.RAIL_WIDTH)
        self.button.setIconSize(QSize(10,10))
        self.button.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.button.setStyleSheet(
            "QToolButton { min-width: 0; min-height: 0; padding: 0; color: #416782; "
            "border: 1px solid #bac8d5; border-radius: 3px; "
            "background: qlineargradient(x1:0,y1:0,x2:1,y2:0,stop:0 #f3f7fa,stop:1 #dce6ee); } "
            "QToolButton:hover { border-color: #7896b0; background: #dfeaf4; } "
            "QToolButton:pressed { background: #c7d9e6; } "
            "QToolButton:focus { border-color: #2476ca; }")
        self.button.clicked.connect(self.toggle_requested)
        self.setSizePolicy(QSizePolicy.Policy.Preferred,QSizePolicy.Policy.Ignored)
        self.set_compact(False)
        self.set_target_collapsed(False)

    @property
    def expanded_minimum_width(self):
        return self.scroll.minimumWidth()+self.RAIL_WIDTH

    def minimumSizeHint(self):
        return QSize(self.RAIL_WIDTH if self.compact else self.expanded_minimum_width,0)

    def sizeHint(self):
        return QSize(self.expanded_minimum_width,self.scroll.sizeHint().height())

    def set_compact(self,compact):
        self.compact=compact
        self.setMinimumWidth(self.RAIL_WIDTH if compact else self.expanded_minimum_width)
        self.updateGeometry()

    def set_target_collapsed(self,collapsed):
        self.button.setArrowType(Qt.ArrowType.RightArrow if collapsed else Qt.ArrowType.LeftArrow)
        text="Einstellungen aufklappen" if collapsed else "Einstellungen einklappen"
        self.button.setToolTip(text)
        self.button.setAccessibleName(text)

    def begin_animation(self):
        if not self.compact:
            self.content_width=max(self.scroll.minimumWidth(),self.width()-self.RAIL_WIDTH)
        self.animating=True
        self.set_compact(True)
        self.clip.show();self.scroll.show()

    def finish_animation(self,collapsed):
        self.animating=False
        self.set_compact(collapsed)
        self.clip.setVisible(not collapsed)
        self.scroll.setVisible(not collapsed)
        self._position_children()

    def _position_children(self):
        available=max(0,self.width()-self.RAIL_WIDTH)
        self.clip.setGeometry(0,0,available,self.height())
        self.button.setGeometry(available,0,self.RAIL_WIDTH,self.height())
        if not self.animating and not self.compact:
            self.content_width=max(self.scroll.minimumWidth(),available)
        self.scroll.setGeometry(0,0,self.content_width,self.height())
        self.button.raise_()

    def resizeEvent(self,event):
        self._position_children()
        super().resizeEvent(event)
