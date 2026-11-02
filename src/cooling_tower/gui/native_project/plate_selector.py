"""Readable native plate cards with click selection and horizontal drag scrolling."""
from PySide6.QtCore import QSize, Qt
from PySide6.QtWidgets import (QAbstractItemView, QApplication, QFrame, QHBoxLayout,
    QLabel, QListView, QListWidget, QListWidgetItem, QScroller, QScrollerProperties,
    QSizePolicy, QVBoxLayout)


_STYLE = '''
QListWidget#nativePlateSelector {
    background:#eef4f9; color:#23394f; border:1px solid #c2d1df;
    border-radius:7px; padding:4px; outline:0;
}
QListWidget#nativePlateSelector::item,
QListWidget#nativePlateSelector::item:selected { background:transparent; border:0; }
QFrame#nativePlateCard { background:#ffffff; border:1px solid #c1d0df; border-radius:6px; }
QFrame#nativePlateCard[selected="true"] { background:#dcecf9; border-color:#337fba; }
QFrame#nativePlateCard QLabel { color:#23394f; background:transparent; border:0; }
QFrame#nativePlateCard QLabel#plateTitle { font-weight:650; font-size:10pt; }
QFrame#nativePlateCard QLabel#plateCount { color:#526b80; }
QFrame#nativePlateCard QLabel#plateThumbnail { background:#f7f9fc; border:1px solid #d6e0e9; border-radius:4px; }
'''


class NativePlateCard(QFrame):
    def __init__(self,name,count,pixmap=None):
        super().__init__()
        self.setObjectName('nativePlateCard')
        self.setProperty('selected',False)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(8,8,8,8)
        layout.setSpacing(10)
        self.thumbnail = QLabel('Keine\nVorschau')
        self.thumbnail.setObjectName('plateThumbnail')
        self.thumbnail.setFixedSize(104,104)
        self.thumbnail.setAlignment(Qt.AlignmentFlag.AlignCenter)
        if pixmap is not None and not pixmap.isNull():
            self.thumbnail.setPixmap(pixmap.scaled(96,96,Qt.AspectRatioMode.KeepAspectRatio,
                                                  Qt.TransformationMode.SmoothTransformation))
        layout.addWidget(self.thumbnail)
        details = QVBoxLayout()
        details.setContentsMargins(0,0,0,0)
        details.setSpacing(6)
        self.title = QLabel(name)
        self.title.setObjectName('plateTitle')
        self.title.setTextFormat(Qt.TextFormat.PlainText)
        self.title.setWordWrap(True)
        self.title.setSizePolicy(QSizePolicy.Policy.Ignored,QSizePolicy.Policy.Preferred)
        self.count = QLabel(f'{count} Objekt' if count == 1 else f'{count} Objekte')
        self.count.setObjectName('plateCount')
        details.addWidget(self.title,1)
        details.addWidget(self.count)
        layout.addLayout(details,1)

    def set_selected(self,selected):
        if self.property('selected') != selected:
            self.setProperty('selected',selected)
            self.style().unpolish(self)
            self.style().polish(self)
            self.update()


class NativePlateSelector(QListWidget):
    def __init__(self,parent=None):
        super().__init__(parent)
        self.setObjectName('nativePlateSelector')
        self.setStyleSheet(_STYLE)
        self.setFlow(QListView.Flow.LeftToRight)
        self.setWrapping(False)
        self.setMovement(QListView.Movement.Static)
        self.setResizeMode(QListView.ResizeMode.Adjust)
        self.setSpacing(6)
        self.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.setDragDropMode(QAbstractItemView.DragDropMode.NoDragDrop)
        self.setHorizontalScrollMode(QAbstractItemView.ScrollMode.ScrollPerPixel)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setFixedHeight(156)
        self.setAccessibleName('Druckplatte auswählen')
        self.setAccessibleDescription('Druckplatten anklicken oder mit den Pfeiltasten auswählen. '
            'Die Auswahl lässt sich mit gedrückter linker Maustaste horizontal verschieben.')
        self._press_position = None
        self._dragging = False
        self._scroll_start = 0
        self.currentRowChanged.connect(self._refresh_selection)
        self.horizontalScrollBar().rangeChanged.connect(lambda *_:self._refresh_cursor())
        QScroller.grabGesture(self.viewport(),QScroller.ScrollerGestureType.TouchGesture)
        scroller = QScroller.scroller(self.viewport())
        properties = scroller.scrollerProperties()
        for metric in (QScrollerProperties.ScrollMetric.HorizontalOvershootPolicy,
                       QScrollerProperties.ScrollMetric.VerticalOvershootPolicy):
            properties.setScrollMetric(metric,QScrollerProperties.OvershootPolicy.OvershootAlwaysOff)
        scroller.setScrollerProperties(properties)

    def add_plate(self,plate,pixmap=None):
        item = QListWidgetItem(f'{plate.name}\n{plate.object_count} Objekte')
        item.setData(Qt.ItemDataRole.UserRole,plate.identifier)
        item.setSizeHint(QSize(280,122))
        item.setToolTip(f'{plate.name}\n{plate.object_count} Objektinstanz(en)\nZum Verschieben horizontal ziehen')
        self.addItem(item)
        self.setItemWidget(item,NativePlateCard(plate.name,plate.object_count,pixmap))

    def _refresh_selection(self,*_):
        for row in range(self.count()):
            card = self.itemWidget(self.item(row))
            if card is not None:
                card.set_selected(row == self.currentRow())

    def _refresh_cursor(self):
        cursor = (Qt.CursorShape.ClosedHandCursor if self._dragging else
            Qt.CursorShape.OpenHandCursor if self.horizontalScrollBar().maximum() else Qt.CursorShape.ArrowCursor)
        self.viewport().setCursor(cursor)

    def _cancel_drag(self):
        self._press_position = None
        self._dragging = False
        self._refresh_cursor()

    def clear(self):
        self._cancel_drag()
        QScroller.scroller(self.viewport()).stop()
        super().clear()

    def hideEvent(self,event):
        self._cancel_drag()
        super().hideEvent(event)

    def focusOutEvent(self,event):
        self._cancel_drag()
        super().focusOutEvent(event)

    def mousePressEvent(self,event):
        if event.button() != Qt.MouseButton.LeftButton:
            return super().mousePressEvent(event)
        self._press_position = event.position().toPoint()
        self._scroll_start = self.horizontalScrollBar().value()
        self._dragging = False
        self.setFocus(Qt.FocusReason.MouseFocusReason)
        event.accept()

    def mouseMoveEvent(self,event):
        if self._press_position is None:
            return super().mouseMoveEvent(event)
        delta = event.position().toPoint()-self._press_position
        if abs(delta.x()) >= QApplication.startDragDistance() and abs(delta.x()) >= abs(delta.y()):
            self._dragging = True
        if self._dragging:
            self.horizontalScrollBar().setValue(self._scroll_start-delta.x())
            self._refresh_cursor()
        event.accept()

    def mouseReleaseEvent(self,event):
        if event.button() != Qt.MouseButton.LeftButton or self._press_position is None:
            return super().mouseReleaseEvent(event)
        if not self._dragging and (event.position().toPoint()-self._press_position).manhattanLength() < QApplication.startDragDistance():
            item = self.itemAt(event.position().toPoint())
            if item is not None:
                self.setCurrentItem(item)
                self.itemClicked.emit(item)
                self.clicked.emit(self.indexFromItem(item))
        self._press_position = None
        self._dragging = False
        self._refresh_cursor()
        event.accept()
