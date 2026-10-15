"""Compact view actions positioned inside the preview without changing its frame."""
from PySide6.QtCore import QEvent,Qt
from PySide6.QtWidgets import QWidget,QPushButton,QButtonGroup,QGridLayout,QLayout


class ManualViewControls(QWidget):
    VIEWS = (("side","Nebeneinander"),("front","Voreinander"),("top","Draufsicht"),
             ("bottom","Untersicht"),("free","Freie 3D-Ansicht"))

    def __init__(self,canvas):
        super().__init__(canvas)
        self.setObjectName("manualPreviewViewControls")
        self.setStyleSheet("QWidget#manualPreviewViewControls { background: transparent; border: none; } "
                          "QPushButton { font-size: 8pt; padding: 3px 5px; min-height: 0; min-width: 0; border-radius: 3px; "
                          "border: 1px solid #bdcad5; color: #21384f; background: qlineargradient(x1:0,y1:0,x2:0,y2:1,stop:0 #fafcfd,stop:1 #e8eef3); } "
                          "QPushButton:hover { border-color: #92a9bd; background: qlineargradient(x1:0,y1:0,x2:0,y2:1,stop:0 #f1f6fa,stop:1 #dce7f0); } "
                          "QPushButton:checked { border-color: #1769aa; color: #153b60; background: qlineargradient(x1:0,y1:0,x2:0,y2:1,stop:0 #eaf4fb,stop:1 #cee2f1); } "
                          'QPushButton[needsFit="true"] { border-color: #81b292; color: #245c36; background: qlineargradient(x1:0,y1:0,x2:0,y2:1,stop:0 #eff9f1,stop:1 #d6ecdc); } '
                          'QPushButton[needsFit="true"]:hover { background: qlineargradient(x1:0,y1:0,x2:0,y2:1,stop:0 #e6f5eb,stop:1 #c4e2cf); } '
                          "QPushButton:pressed { background: qlineargradient(x1:0,y1:0,x2:0,y2:1,stop:0 #dce6ee,stop:1 #cfdce6); }")
        self.grid = QGridLayout(self)
        self.grid.setContentsMargins(0,0,0,0)
        self.grid.setSpacing(4)
        self.grid.setSizeConstraint(QLayout.SizeConstraint.SetNoConstraint)
        self.group = QButtonGroup(self)
        self.view_buttons = {}
        for view,text in self.VIEWS:
            button = QPushButton(text)
            button.setCheckable(True)
            button.clicked.connect(lambda checked,v=view:canvas.set_view(v))
            self.group.addButton(button)
            self.view_buttons[view] = button
        self.view_buttons[canvas.view].setChecked(True)
        self.fit_button = QPushButton("Einpassen")
        self.fit_button.setProperty("needsFit",False)
        self.fit_button.clicked.connect(canvas.fit_scene)
        self.buttons = [*self.view_buttons.values(),self.fit_button]
        self.rows = 0
        self.button_height = 23
        self.relayout()

    def set_button_height(self,height):
        self.button_height = height+6
        self.relayout()

    def set_fitted(self,fitted):
        needs_fit = not fitted
        if self.fit_button.property("needsFit") == needs_fit:
            return
        self.fit_button.setProperty("needsFit",needs_fit)
        self.fit_button.style().unpolish(self.fit_button)
        self.fit_button.style().polish(self.fit_button)
        self.fit_button.update()

    def relayout(self):
        if not hasattr(self,"buttons"):
            return
        available = max(1,self.parentWidget().width()-16)
        self.button_height = max(self.button_height,max(button.fontMetrics().height()+8 for button in self.buttons))
        for button in self.buttons:
            button.setFixedHeight(self.button_height)
        widths = [button.sizeHint().width() for button in self.buttons]
        natural = sum(widths)+self.grid.spacing()*5
        self.rows = 1 if natural <= available else 2
        for button in self.buttons:
            self.grid.removeWidget(button)
        for column in range(6):
            self.grid.setColumnStretch(column,0)
        for i,button in enumerate(self.buttons):
            row,column = (0,i) if self.rows == 1 else divmod(i,3)
            self.grid.addWidget(button,row,column)
            self.grid.setColumnStretch(column,1 if self.rows == 2 else 0)
        width = natural if self.rows == 1 else available
        height = self.button_height*self.rows+self.grid.spacing()*(self.rows-1)
        x = self.parentWidget().width()-8-width
        history = getattr(self.parentWidget(), "history_controls", None)
        y = history.geometry().bottom()+8 if history is not None and x <= history.geometry().right()+8 else 8
        self.setGeometry(x,y,width,height)
        self.grid.activate()
        self.raise_()
        self.parentWidget().update()

    def changeEvent(self,event):
        super().changeEvent(event)
        if event.type() in {QEvent.Type.FontChange,QEvent.Type.StyleChange}:
            self.relayout()
