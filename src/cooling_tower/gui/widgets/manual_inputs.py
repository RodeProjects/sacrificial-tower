"""Wheel-safe numeric editors that report attempts hidden by Qt hard bounds."""
import math
import re
from PySide6.QtCore import QLocale,QRect,QTimer,Signal,QVariantAnimation
from PySide6.QtGui import QColor,QPalette,QValidator
from PySide6.QtWidgets import QAbstractSpinBox,QDoubleSpinBox,QStyle,QStyleOptionFrame,QStyleOptionSpinBox
from cooling_tower.gui.design_tokens import BOUNDARY_FEEDBACK_FADE_MS,COLORS
from cooling_tower.gui.widgets.numeric_setting import NumericSettingWidget
from cooling_tower.gui.widgets.wheel_safe_inputs import WheelSafeDoubleSpinBox,WheelSafeSpinBox


class _AttemptAware:
    def __init__(self,*args,**kwargs):
        super().__init__(*args,**kwargs)
        locale=QLocale(QLocale.Language.German,QLocale.Country.Germany)
        locale.setNumberOptions(QLocale.NumberOption.OmitGroupSeparator|QLocale.NumberOption.RejectGroupSeparator)
        self.setLocale(locale)
        self.setProperty("manualCompactInput",True)
        self._edit_serial=0
        self.lineEdit().textEdited.connect(self._accepted_edit)

    def _number(self,text):
        text=text.strip()
        if self.prefix() and text.startswith(self.prefix()):text=text[len(self.prefix()):]
        if self.suffix() and text.endswith(self.suffix()):text=text[:-len(self.suffix())]
        return text.strip().replace(".",",")

    def _parse(self,text):
        number=self._number(text)
        if not re.fullmatch(r"[+-]?(?:\d+(?:,\d*)?|,\d+)",number):return None
        value=float(number.replace(",","."))
        return value if math.isfinite(value) else None

    def _reject(self,message):
        if not self.hasFocus():return
        serial=self._edit_serial
        QTimer.singleShot(0,self,lambda:self.input_rejected.emit(message) if self._edit_serial==serial else None)

    def _accepted_edit(self,text):
        self._edit_serial+=1
        value=self._parse(text)
        if not isinstance(self,QDoubleSpinBox) and "," in self._number(text):
            self.input_rejected.emit("Bitte eine ganze Zahl eingeben.")
            return
        if value is not None and self.minimum()<=value<=self.maximum():self.valid_input_edited.emit()

    def validate(self,text,position):
        text=text.replace(".",",")
        number=self._number(text)
        if number in {"","-","+",",","-,","+,"}:
            return QValidator.State.Intermediate,text,position
        value=self._parse(text)
        if value is None:
            self._reject("Bitte eine gültige Zahl eingeben.")
            return QValidator.State.Invalid,text,position
        if not isinstance(self,QDoubleSpinBox) and "," in number:
            return QValidator.State.Intermediate,text,position
        if isinstance(self,QDoubleSpinBox) and len(number.partition(",")[2])>self.decimals():
            self._reject(f"Max. Nachkommastellen = {self.decimals()}")
            return QValidator.State.Invalid,text,position
        state=QValidator.State.Acceptable if self.minimum()<=value<=self.maximum() else QValidator.State.Intermediate
        return state,text,position

    def valueFromText(self,text):
        value=self._parse(text)
        if value is None:return self.value()
        return value if isinstance(self,QDoubleSpinBox) else int(value)

    def fixup(self,text):
        value=self._parse(text)
        if not isinstance(self,QDoubleSpinBox) and "," in self._number(text):
            self.input_rejected.emit("Bitte eine ganze Zahl eingeben.")
            value=self.value()
        elif value is None:
            self._reject("Bitte eine gültige Zahl eingeben.")
            value=self.value()
        elif not self.minimum()<=value<=self.maximum():
            self.limit_attempted.emit(value)
            value=min(self.maximum(),max(self.minimum(),value))
        return self.prefix()+self.textFromValue(value if isinstance(self,QDoubleSpinBox) else int(value))+self.suffix()

    def stepEnabled(self):
        if self.isReadOnly():return QAbstractSpinBox.StepEnabledFlag.StepNone
        return QAbstractSpinBox.StepEnabledFlag.StepUpEnabled|QAbstractSpinBox.StepEnabledFlag.StepDownEnabled

    def stepBy(self,steps):
        self.interpretText()
        attempted = self.value()+steps*self.singleStep()
        if self.minimum()<=attempted<=self.maximum():self.valid_input_edited.emit()
        super().stepBy(steps)
        if attempted < self.minimum() or attempted > self.maximum():
            self.limit_attempted.emit(attempted)


class ManualDoubleSpinBox(_AttemptAware,WheelSafeDoubleSpinBox):
    limit_attempted = Signal(float)
    input_rejected = Signal(str)
    valid_input_edited = Signal()


class ManualSpinBox(_AttemptAware,WheelSafeSpinBox):
    limit_attempted = Signal(float)
    input_rejected = Signal(str)
    valid_input_edited = Signal()


def boundary_message(editor,value,name):
    maximum=value>editor.maximum()
    bound=editor.maximum() if maximum else editor.minimum()
    text=f"{bound:g}".replace(".",",")
    return f"{'Max.' if maximum else 'Min.'} {name} = {text}{editor.suffix()}"


def compact_manual_width(editors):
    """Measure native value/suffix, text insets, caret and arrow column once."""
    widths=[]
    for editor in editors:
        editor.ensurePolished()
        metrics=editor.lineEdit().fontMetrics()
        digit=max("0123456789",key=metrics.horizontalAdvance)
        samples=[editor.prefix()+editor.textFromValue(value)+editor.suffix() for value in (editor.minimum(),editor.maximum())]
        samples=[re.sub(r"\d",digit,text) for text in samples]
        option=QStyleOptionSpinBox();editor.initStyleOption(option)
        option.rect=QRect(0,0,1000,editor.height())
        field=editor.style().subControlRect(QStyle.ComplexControl.CC_SpinBox,option,QStyle.SubControl.SC_SpinBoxEditField,editor)
        line_option=QStyleOptionFrame();editor.lineEdit().initStyleOption(line_option)
        line_option.rect=option.rect
        contents=editor.lineEdit().style().subElementRect(QStyle.SubElement.SE_LineEditContents,line_option,editor.lineEdit())
        margins=editor.lineEdit().textMargins()
        widths.append(max(metrics.horizontalAdvance(text) for text in samples)+2000-field.width()-contents.width()+margins.left()+margins.right()+4)
    return max(widths,default=80)


class ManualNumericSettingWidget(NumericSettingWidget):
    """Brief field feedback with a readable reason directly below the input."""
    error_feedback_finished = Signal()

    def __init__(self,**kwargs):
        super().__init__(**kwargs)
        self.editor.setSuffix(" "+kwargs["unit"] if kwargs.get("unit") else "")
        self.layout().removeWidget(self.message_container)
        self.layout().addWidget(self.message_container,2,2,1,2)
        self.message_label.setStyleSheet(f"color: {COLORS['error']}; font-size: 8pt; padding: 0;")
        self.editor.input_rejected.connect(self.set_error)
        self.editor.valid_input_edited.connect(lambda:self.set_error(None))
        duration=2000+BOUNDARY_FEEDBACK_FADE_MS
        self._feedback_animation=QVariantAnimation(self)
        self._feedback_animation.setDuration(duration)
        self._feedback_animation.setStartValue(1.)
        self._feedback_animation.setKeyValueAt(2000/duration,1.)
        self._feedback_animation.setEndValue(0.)
        self._feedback_animation.valueChanged.connect(self._set_feedback_amount)
        self._feedback_animation.finished.connect(lambda:self.set_error(None))
        self._feedback_message=None
        self._feedback_amount=0.

    def _position_unit_label(self):
        self.unit_label.hide()

    def _update_reset_metadata(self):
        available = self.default_provider() is not None
        self.reset_button.setVisible(available)
        if available:
            super()._update_reset_metadata()

    def _update_modified_state(self,_value=None):
        if self.default_provider() is None:
            self.reset_button.setEnabled(False)
            self.reset_button.setProperty("modified",False)
            return
        super()._update_modified_state(_value)

    def set_error(self,message):
        if not message:
            if self._feedback_message is None:return False
            self._feedback_animation.stop()
            self.label.setStyleSheet(self._normal_label_style)
            self.editor.setStyleSheet(self._normal_editor_style)
            self.editor.setAccessibleDescription(self._normal_description)
            self._feedback_message=None
            self._feedback_amount=0.
            self.message_container.hide()
            self.message_label.hide()
            self.refresh_content_height()
            self.error_feedback_finished.emit()
            return True
        self._feedback_animation.stop()
        if self._feedback_message is None:
            self.label.ensurePolished()
            self._normal_label_style=self.label.styleSheet()
            self._normal_editor_style=self.editor.styleSheet()
            self._normal_label_color=self.label.palette().color(QPalette.ColorRole.WindowText)
            self._normal_description=self.editor.accessibleDescription()
        self._feedback_message=str(message)
        self.message_label.setText(str(message))
        self.message_label.show()
        self.message_container.show()
        self.refresh_content_height()
        self.editor.setAccessibleDescription(str(message))
        self._set_feedback_amount(1.)
        self._feedback_animation.start()
        return True

    def _set_feedback_amount(self,value):
        self._feedback_amount=float(value)
        red=QColor(COLORS["error"])
        def blend(normal):
            return QColor(*(round(a+(b-a)*self._feedback_amount)
                for a,b in zip(normal.getRgb()[:3],red.getRgb()[:3]))).name()
        self.label.setStyleSheet(self._normal_label_style+f" QLabel {{ color: {blend(self._normal_label_color)}; }}")
        border=blend(QColor("#b8c5d1"))
        self.editor.setStyleSheet(self._normal_editor_style+
            f" QAbstractSpinBox, QAbstractSpinBox:hover, QAbstractSpinBox:focus {{ border-color: {border}; }}")
