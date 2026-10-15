from __future__ import annotations

from PySide6.QtCore import QEvent, QLocale, QPoint, QRect, QSize, QSignalBlocker, QTimer, Qt, Signal
from PySide6.QtGui import QColor, QFont, QFontMetrics, QLinearGradient, QPainter
from PySide6.QtWidgets import (
    QCheckBox, QDialog, QFrame, QGridLayout, QHBoxLayout, QLabel, QPushButton, QScrollArea, QSizePolicy, QStyle, QStyleOptionFrame, QStyleOptionSpinBox,
    QSplitter, QVBoxLayout, QWidget,
)

from cooling_tower.gui.widgets.layer_range_canvas import LayerRangeCanvas
from cooling_tower.gui.widgets.info_tool_button import InfoToolButton
from cooling_tower.gui.widgets.wheel_safe_inputs import WheelSafeDoubleSpinBox, WheelSafeSpinBox
from cooling_tower.gui.widgets.wrapping_layout import WrappingLayout
from cooling_tower.gui.widgets.deficit_range_slider import DeficitRangeSlider, round_deficit
from cooling_tower.gui.widgets.manual_resolution_control import RotationSlider, RotationEndLabels
from cooling_tower.gui.widgets.manual_xray_controls import xray_button_style
from cooling_tower.gui.design_tokens import METRICS
from cooling_tower.gui.texts import SETTING_INFO_TEXTS
from cooling_tower.models.layer_ranges import normalize_layer_ranges
from cooling_tower.settings_defaults import GENERATION_DEFAULTS


class _CompactSpin:
    """Reserve a value sample plus room for one additional digit."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.setProperty("rangeCompactInput", True)
        self.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
        self.valueChanged.connect(lambda _value: self.updateGeometry())
        # Track uncommitted typed text as well as the numeric value.
        self.lineEdit().textChanged.connect(lambda _text: self.updateGeometry())

    def setValue(self, value):
        super().setValue(value)
        # Qt suppresses the editor's text signal during programmatic updates.
        # Recompute width even when the caller blocks valueChanged as well.
        self.updateGeometry()

    def sizeHint(self):
        hint = super().sizeHint()
        line_edit = self.lineEdit()
        metrics = line_edit.fontMetrics()
        option = QStyleOptionSpinBox()
        self.initStyleOption(option)
        option.rect = QRect(0, 0, 1000, hint.height())
        editor = self.style().subControlRect(QStyle.ComplexControl.CC_SpinBox, option,
                                            QStyle.SubControl.SC_SpinBoxEditField, self)
        line_option = QStyleOptionFrame()
        line_edit.initStyleOption(line_option)
        line_option.rect = QRect(0, 0, 1000, hint.height())
        contents = line_edit.style().subElementRect(QStyle.SubElement.SE_LineEditContents,
                                                   line_option, line_edit)
        margins = line_edit.textMargins()
        # Include native text insets and caret space, as well as one spare digit.
        overhead = 1000 - editor.width() + 1000 - contents.width() + margins.left() + margins.right() + 4
        text = self._width_sample()
        text_width = max(metrics.horizontalAdvance(text), metrics.boundingRect(text).width())
        hint.setWidth(overhead + text_width + metrics.horizontalAdvance("0"))
        return hint

    def _width_sample(self):
        return self.lineEdit().displayText()

    def minimumSizeHint(self):
        return self.sizeHint()


class _CompactDoubleSpin(_CompactSpin, WheelSafeDoubleSpinBox):
    pass


class _CompactLayerSpin(_CompactSpin, WheelSafeSpinBox):
    def _width_sample(self):
        # Layer edits share a fixed digit budget for this object's full range.
        # Font/style changes still remeasure it; moving a range does not.
        metrics = self.lineEdit().fontMetrics()
        digit = max("0123456789", key=metrics.horizontalAdvance)
        return digit * len(str(self.maximum()))


class _DeficitSpin(_CompactDoubleSpin):
    def textFromValue(self, value):
        return self.locale().toString(round_deficit(value), "f", 1)

    def valueFromText(self, text):
        return round_deficit(super().valueFromText(text))

    def setValue(self, value):
        super().setValue(round_deficit(value))


class _InputResetButton(QPushButton):
    def __init__(self, editor):
        super().__init__("↺")
        self.setProperty("rangeCompactReset", True)
        self.editor = editor
        self.setFixedWidth(METRICS.reset_button_size_px)
        self.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)

    def sizeHint(self):
        return QSize(METRICS.reset_button_size_px, self.editor.sizeHint().height())

    def minimumSizeHint(self):
        return self.sizeHint()


class _XRayButton(QPushButton):
    FULL_TEXT = "X-Ray (Transparenz)"
    SHORT_TEXT = "X-Ray"

    def width_for_text(self, text):
        bold = QFont(self.font())
        bold.setBold(True)
        return QFontMetrics(bold).horizontalAdvance(text) + 14

    def sizeHint(self):
        return QSize(self.width_for_text(self.text()), METRICS.form_control_height_px)

    def minimumSizeHint(self):
        return self.sizeHint()


class DeficitGradient(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedHeight(10)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.setAccessibleName("Farbverlauf von Grün bis Rot")

    def paintEvent(self, event):
        painter = QPainter(self)
        gradient = QLinearGradient(0, 0, self.width(), 0)
        gradient.setColorAt(0, QColor(LayerRangeCanvas.OBJECT_COLOR))
        gradient.setColorAt(1, QColor(LayerRangeCanvas.CRITICAL_COLOR))
        painter.fillRect(self.rect(), gradient)


class _RotationControls(QWidget):
    """Use the manual editor's track, grip and caption layout."""

    def __init__(self, slider, angle):
        super().__init__()
        self.angle = angle
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        column = QVBoxLayout(self)
        column.setContentsMargins(0, 0, 0, 0)
        column.setSpacing(1)
        self.title = QLabel("Objekt drehen")
        self.title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.title.setStyleSheet("font-size: 8pt; padding: 0;")
        header = QHBoxLayout()
        header.setContentsMargins(0, 0, 0, 0)
        header.setSpacing(3)
        header.addWidget(self.title, 1)
        angle.setMinimumWidth(angle.fontMetrics().horizontalAdvance("-180°"))
        header.addSpacing(angle.minimumWidth() + 3)
        column.addLayout(header)
        row = QHBoxLayout()
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(3)
        slider_host = QWidget()
        slider_column = QVBoxLayout(slider_host)
        slider_column.setContentsMargins(0, 0, 0, 0)
        slider_column.setSpacing(0)
        self.end_labels = RotationEndLabels(slider)
        slider_column.addWidget(self.end_labels)
        slider_column.addWidget(slider)
        row.addWidget(slider_host, 1)
        row.addWidget(angle, 0, Qt.AlignmentFlag.AlignVCenter)
        column.addLayout(row)

    def quarter_label_width(self):
        row = self.layout().itemAt(1).layout()
        return max(self.minimumSizeHint().width(),
                   self.end_labels.minimum_width_for_step(90)
                   + max(self.angle.minimumWidth(), self.angle.sizeHint().width())
                   + row.spacing())


class _PreviewControls(QWidget):
    """Shorten captions before stacking the buttons beside two aligned sliders."""

    GAP = 8

    def __init__(self, xray, resolution, rotation, fit):
        super().__init__()
        self.xray, self.resolution, self.rotation, self.fit = xray, resolution, rotation, fit
        for widget in (xray, resolution, rotation, fit):
            widget.setParent(self)
        policy = QSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        policy.setHeightForWidth(True)
        self.setSizePolicy(policy)

    def _widths(self):
        fit = self.fit
        fit_padding = fit.sizeHint().width() - fit.fontMetrics().horizontalAdvance(fit.text())
        return (self.resolution.minimumSizeHint().width(), self.rotation.quarter_label_width(),
                self.xray.width_for_text(self.xray.FULL_TEXT), self.xray.width_for_text(self.xray.SHORT_TEXT),
                fit.fontMetrics().horizontalAdvance("Objekt einpassen") + fit_padding,
                fit.fontMetrics().horizontalAdvance("Einpassen") + fit_padding)

    def _horizontal_width(self, mode):
        resolution, rotation, xray_full, xray_short, fit_full, fit_short = self._widths()
        return (resolution + rotation + (xray_full if mode == 0 else xray_short)
                + (fit_full if mode < 2 else fit_short) + 3 * self.GAP)

    def _mode(self, width):
        return next((mode for mode in range(3) if width >= self._horizontal_width(mode)), 3)

    def sizeHint(self):
        return QSize(self._horizontal_width(0), self._row_height())

    def minimumSizeHint(self):
        widths = self._widths()
        return QSize(max(widths[:2]) + max(widths[3], widths[5]) + self.GAP, self._row_height())

    def _row_height(self):
        return max(self.resolution.sizeHint().height(), self.rotation.sizeHint().height(), self.fit.height())

    def heightForWidth(self, width):
        height = self._row_height()
        return height * 2 + self.GAP if self._mode(width) == 3 else height

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._arrange()

    def _arrange(self):
        widths = self._widths()
        mode = self._mode(self.width())
        xray, fit = self.xray, self.fit
        xray.setText(xray.FULL_TEXT if mode == 0 else xray.SHORT_TEXT)
        fit.setText("Objekt einpassen" if mode < 2 else "Einpassen")
        xray_width = widths[2] if mode == 0 else widths[3]
        fit_width = widths[4] if mode < 2 else widths[5]
        height = self._row_height()
        if mode == 3:
            button_width = max(xray_width, fit_width)
            button_x = self.width() - button_width
            slider_width = button_x - self.GAP
            self.resolution.setGeometry(0, 0, slider_width, height)
            self.rotation.setGeometry(0, height + self.GAP, slider_width, height)
            xray.setGeometry(button_x, height - xray.height(), button_width, xray.height())
            fit.setGeometry(button_x, height * 2 + self.GAP - fit.height(), button_width, fit.height())
        else:
            available = self.width() - xray_width - fit_width - 3 * self.GAP
            extra = max(0, available - sum(widths[:2]))
            resolution_width = widths[0] + extra // 3
            resolution_x = xray_width + self.GAP
            self.resolution.setGeometry(resolution_x, 0, resolution_width, height)
            self.rotation.setGeometry(resolution_x + resolution_width + self.GAP, 0, available - resolution_width, height)
            xray.setGeometry(0, height - xray.height(), xray_width, xray.height())
            fit.setGeometry(self.width() - fit_width, height - fit.height(), fit_width, fit.height())
        self.resolution.layout().activate()
        self.rotation.layout().activate()

    def changeEvent(self, event):
        super().changeEvent(event)
        if event.type() in (QEvent.Type.FontChange, QEvent.Type.StyleChange) and hasattr(self, "fit"):
            self.updateGeometry()
            self._arrange()


class LayerTimeLegend(QWidget):
    EXCLUSION_NOTES = (
        "In diesen Bereichen wird der Turm keine zusätzliche Layerzeit erzeugen",
        "Der Turm wird, wenn möglich, bis auf seinen Min.-Durchmesser schrumpfen.",
        "Ausnahmen: Der Standfuß und nötige Aufweitungen für nicht-ausgeschlossene Bereiche",
    )

    def __init__(self, parent=None):
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(6)
        self.color_key = QWidget()
        header = WrappingLayout(self.color_key)
        scale = QWidget()
        scale.setFixedWidth(170)
        scale_layout = QVBoxLayout(scale)
        scale_layout.setContentsMargins(0, 0, 0, 0)
        scale_layout.addWidget(DeficitGradient())
        header.addWidget(scale)
        header.addWidget(QLabel("Layerzeit-Defizit"))
        layout.addWidget(self.color_key)
        exclusions = QGridLayout()
        exclusions.setHorizontalSpacing(6)
        exclusions.setVerticalSpacing(0)
        exclusions.setColumnStretch(1, 1)
        self.exclusion_swatch = QFrame()
        self.exclusion_swatch.setFixedSize(16, 12)
        self.exclusion_swatch.setStyleSheet(f"background: {LayerRangeCanvas.NEUTRAL_OBJECT_COLOR};")
        self.exclusion_title = QLabel("<b>Ausschlussbereiche:</b>")
        self.exclusion_text = QLabel("<br>".join("• " + note for note in self.EXCLUSION_NOTES))
        self.exclusion_text.setTextFormat(Qt.TextFormat.RichText)
        self.exclusion_text.setWordWrap(True)
        self.exclusion_text.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop)
        exclusions.addWidget(self.exclusion_swatch, 0, 0, Qt.AlignmentFlag.AlignVCenter)
        exclusions.addWidget(self.exclusion_title, 0, 1, Qt.AlignmentFlag.AlignVCenter)
        exclusions.addWidget(self.exclusion_text, 1, 1)
        layout.addLayout(exclusions)
        self.set_thresholds(0.0, 1.0)

    @staticmethod
    def _number(value):
        return f"{round_deficit(value):.1f}".replace(".", ",")

    def set_thresholds(self, start, full):
        self.start_deficit_s, self.full_deficit_s = start, full
        self.setAccessibleName(f"Legende: Grün bis {self._number(start)} Sekunden Defizit, Rot ab {self._number(full)} Sekunden Defizit; transparente blaue Flächen sind Ausschlussbereiche")
        self.update()

    def set_time_coloring_enabled(self, enabled):
        self.color_key.setVisible(enabled)
        self.setAccessibleName(
            f"Legende: Grün bis {self._number(self.start_deficit_s)} Sekunden Defizit, "
            f"Rot ab {self._number(self.full_deficit_s)} Sekunden Defizit; Ausschlussbereiche sind dunkelblau umrahmt"
            if enabled else "Legende: Blaues Originalobjekt; Ausschlussbereiche sind dunkelblau umrahmt")


class LayerRangeDialog(QDialog):
    ranges_changed = Signal(object)
    target_time_changed = Signal(float)
    color_thresholds_changed = Signal(float, float)

    def __init__(self, layers, segments, *, target_time_s, target_minimum,
                 target_maximum, target_decimals=2, ranges=(),
                 gradient_start_deficit_s=0.0, gradient_full_deficit_s=1.0,
                 time_coloring_enabled=False, xray_enabled=False,
                 silhouette=None, target_time_hint=None, target_default=None,
                 source_artifact=None, render_manager=None, parent=None):
        super().__init__(parent)
        self.setObjectName("layerRangeDialog")
        self.setWindowTitle("Bereichseditor · Aufweitung ausschließen")
        self.setWindowModality(Qt.WindowModality.WindowModal)
        self.layer_count = len(layers)
        self.ranges = self._ordered_ranges(ranges)
        self.selected = -1
        self.range_rows = []
        self._rows_pending = False
        self._rows_rebuild_timer = QTimer(self)
        self._rows_rebuild_timer.setSingleShot(True)
        self._rows_rebuild_timer.timeout.connect(self._rebuild_rows)
        self._selection_scroll_timer = QTimer(self)
        self._selection_scroll_timer.setSingleShot(True)
        self._selection_scroll_timer.timeout.connect(self._ensure_selected_row_visible)
        self._pane_resize_timer = QTimer(self)
        self._pane_resize_timer.setSingleShot(True)
        self._pane_resize_timer.timeout.connect(self._resize_panes)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        body = QWidget()
        body_layout = QVBoxLayout(body)
        body_layout.setContentsMargins(18, 18, 18, 12)
        self.splitter = QSplitter(Qt.Orientation.Horizontal)
        self.splitter.setObjectName("layerRangeSplitter")
        self.splitter.setHandleWidth(1)
        self.splitter.setChildrenCollapsible(False)
        body_layout.addWidget(self.splitter)
        layout.addWidget(body, 1)

        self.settings_panel = QWidget()
        left = QVBoxLayout(self.settings_panel)
        left.setContentsMargins(0, 0, 14, 0)
        left.setSpacing(10)
        title = QLabel("Allgemeine Einstellungen")
        title.setObjectName("embeddedPreviewTitle")
        left.addWidget(title)
        label = QLabel("Gew. Min-Layerzeit")
        target_header = WrappingLayout()
        target_label = QWidget()
        target_label_layout = QHBoxLayout(target_label)
        target_label_layout.setContentsMargins(0, 0, 0, 0)
        target_label_layout.setSpacing(6)
        self.target_info_button = self._info_button(target_time_hint or SETTING_INFO_TEXTS["target_layer_time_s"], label.text())
        target_label_layout.addWidget(self.target_info_button)
        target_label_layout.addWidget(label)
        target_header.addWidget(target_label)
        self.target_spin = _CompactDoubleSpin()
        self.target_spin.setLocale(QLocale(QLocale.Language.German))
        self.target_spin.setDecimals(target_decimals)
        self.target_spin.setRange(target_minimum, target_maximum)
        self.target_spin.setSingleStep(0.1)
        self.target_spin.setSuffix(" s")
        self.target_spin.setKeyboardTracking(False)
        self.target_spin.setValue(target_time_s)
        self.target_spin.setAccessibleName("Gewünschte Mindest-Layerzeit")
        label.setBuddy(self.target_spin)
        target_header.addWidget(self.target_spin)
        self._target_default = float(min(target_maximum, max(target_minimum,
            GENERATION_DEFAULTS["target_layer_time_s"] if target_default is None else target_default)))
        self.target_reset_button = _InputResetButton(self.target_spin)
        self.target_reset_button.setObjectName("settingResetButton")
        self.target_reset_button.setAutoDefault(False)
        self.target_reset_button.setAccessibleName("Mindest-Layerzeit zurücksetzen")
        self.target_reset_button.setToolTip(f"Mindest-Layerzeit auf {self.target_spin.locale().toString(self._target_default, 'f', 1)} s zurücksetzen")
        target_header.addWidget(self.target_reset_button)
        left.addLayout(target_header)
        color_header = QHBoxLayout()
        color_header.setSpacing(6)
        self.color_info_button = self._info_button(
            "• Zeigt, wie viele Sekunden einem Layer zur gewünschten Mindest-Layerzeit fehlen.\n"
            "• Zwei Grenzen bestimmen den Übergang von Grün (geringes Defizit) zu Rot (hohes Defizit).\n"
            "• Grenzen per Greifer oder Wertefeld einstellen (0–2 s).\n"
            "• Ändert nur die Vorschaufarben, nicht die Turmberechnung.",
            "Zeitdefizit-Einfärbung aktivieren")
        color_header.addWidget(self.color_info_button)
        color_label = QLabel("Zeitdefizit-Einfärbung aktivieren")
        color_label.setWordWrap(True)
        color_header.addWidget(color_label, 1)
        self.color_enabled_checkbox = QCheckBox()
        self.color_enabled_checkbox.setAccessibleName(color_label.text())
        self.color_enabled_checkbox.setChecked(time_coloring_enabled)
        color_label.setBuddy(self.color_enabled_checkbox)
        color_header.addWidget(self.color_enabled_checkbox)
        left.addLayout(color_header)
        self.color_settings = QWidget()
        color_limits = QVBoxLayout(self.color_settings)
        color_limits.setContentsMargins(0, 0, 0, 0)
        color_limits.setSpacing(3)
        scale_layout = QHBoxLayout()
        scale_layout.setSpacing(6)
        self.color_start_label, self.color_full_label = QLabel(), QLabel()
        self.color_gradient = DeficitRangeSlider()
        self.color_gradient.setToolTip("Defizitgrenzen mit den beiden Greifern einstellen · Skala: 0,0 bis 2,0 s")
        scale_layout.addWidget(self.color_start_label)
        scale_layout.addWidget(self.color_gradient, 1)
        scale_layout.addWidget(self.color_full_label)
        color_limits.addLayout(scale_layout)
        limit_inputs = QHBoxLayout()
        limit_inputs.setContentsMargins(0, 0, 0, 0)
        limit_inputs.setSpacing(6)
        self.color_start_spin = self._color_spin(gradient_start_deficit_s, 0, DeficitRangeSlider.MAXIMUM_SECONDS - .1,
                                                "Grün bis Defizit", "≤ ")
        self.color_full_spin = self._color_spin(max(gradient_full_deficit_s, self.color_start_spin.value() + .1), .1, DeficitRangeSlider.MAXIMUM_SECONDS,
                                               "Vollständig rot ab Defizit", "≥ ")
        limit_inputs.addWidget(self.color_start_spin)
        limit_inputs.addStretch(1)
        limit_inputs.addWidget(self.color_full_spin)
        self.color_reset_button = _InputResetButton(self.color_full_spin)
        self.color_reset_button.setObjectName("settingResetButton")
        self.color_reset_button.setAutoDefault(False)
        self.color_reset_button.setToolTip("Defizitgrenzen auf 0,0 s und 1,0 s zurücksetzen")
        self.color_reset_button.setAccessibleName("Defizitgrenzen zurücksetzen")
        limit_inputs.addWidget(self.color_reset_button, 0, Qt.AlignmentFlag.AlignVCenter)
        color_limits.addLayout(limit_inputs)
        left.addWidget(self.color_settings)
        self.color_start_spin.setToolTip("Bis zu diesem Layerzeit-Defizit bleibt das Objekt grün. Danach beginnt der Farbverlauf zu Rot.")
        self.color_full_spin.setToolTip("Ab diesem Layerzeit-Defizit ist das Objekt vollständig rot. Der Wert muss größer als der Beginn des Farbverlaufs sein.")
        divider = QFrame()
        divider.setObjectName("footerHorizontalDivider")
        divider.setFixedHeight(1)
        left.addWidget(divider)
        heading = QLabel("Ausschlussbereiche")
        heading.setObjectName("embeddedPreviewTitle")
        left.addWidget(heading)
        inputs = WrappingLayout()
        self.range_info_button = self._info_button(
            "• Layernummern gelten einschließlich beider Grenzen.\n"
            "• Überlappende oder direkt angrenzende Bereiche werden verbunden.\n"
            "• Die Bereiche werden von oben nach unten nummeriert.\n"
            "• Greifer und Eingabefelder bearbeiten dieselben Layergrenzen.",
            "Layerbereiche festlegen")
        self.new_start_spin = self._layer_spin(1, "Neuer Bereich: erster Layer")
        self.new_end_spin = self._layer_spin(min(50, self.layer_count), "Neuer Bereich: letzter Layer")
        inputs.addWidget(self._input_group("Von Layer", self.new_start_spin, self.range_info_button))
        inputs.addWidget(self._input_group("bis", self.new_end_spin))
        left.addLayout(inputs)
        self.add_button = self._button("Bereich hinzufügen", "add")
        left.addWidget(self.add_button)
        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        self.scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.scroll.setMinimumHeight(120)
        self.rows_host = QWidget()
        self.rows_layout = QVBoxLayout(self.rows_host)
        self.rows_layout.setContentsMargins(0, 0, 4, 0)
        self.rows_layout.setSpacing(8)
        self.scroll.setWidget(self.rows_host)
        # Qt can update the content extent after the selection timer ran.
        # Follow those layout changes, while still allowing manual scrolling.
        self.scroll.verticalScrollBar().rangeChanged.connect(
            lambda _minimum, _maximum: self._selection_scroll_timer.start(0))
        left.addWidget(self.scroll, 1)
        self.status_label = QLabel()
        self.status_label.setWordWrap(True)
        self.status_label.setAccessibleName("Bereichsstatus")
        left.addWidget(self.status_label)
        self.splitter.addWidget(self.settings_panel)

        right = QWidget()
        right_layout = QVBoxLayout(right)
        right_layout.setContentsMargins(14, 0, 0, 0)
        right_layout.setSpacing(8)
        self.fit_button = QPushButton("Objekt einpassen")
        self.fit_button.setObjectName("layerRangeFitButton")
        self.fit_button.setProperty("needsFit", False)
        self.fit_button.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
        self.fit_button.setAutoDefault(False)
        self.fit_button.setEnabled(False)
        self.fit_button.setFixedHeight(METRICS.form_control_height_px)
        self.canvas = LayerRangeCanvas(layers, segments, silhouette=silhouette)
        self.canvas.set_time_coloring_enabled(time_coloring_enabled)
        self.canvas.set_xray_enabled(xray_enabled)
        self.xray_button = _XRayButton(_XRayButton.FULL_TEXT)
        self.xray_button.setAccessibleName(_XRayButton.FULL_TEXT)
        self.xray_button.setObjectName("layerRangeXRayButton")
        self.xray_button.setAutoDefault(False)
        self.xray_button.setCheckable(True)
        self.xray_button.setChecked(xray_enabled)
        self.xray_button.setStyleSheet(xray_button_style("object"))
        self.xray_button.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
        self.xray_button.setFixedHeight(METRICS.form_control_height_px)
        self.xray_button.setToolTip("Transparenz des Originalobjekts ein-/ausschalten")
        self.xray_button.toggled.connect(self.canvas.set_xray_enabled)
        from cooling_tower.gui.widgets.object_resolution_control import ObjectResolutionControl
        self.resolution_control = ObjectResolutionControl(title="Auflösung", show_reset=False)
        self.resolution_slider = self.resolution_control.resolution_slider
        self.resolution_label = self.resolution_control.resolution_label
        self.resolution_control.percent_changed.connect(self.canvas.set_resolution)
        if source_artifact is not None and render_manager is not None and silhouette is not None:
            self.canvas.prepare_object_view(source_artifact, render_manager)
            self.finished.connect(lambda _: self.canvas.object_view.close())
        self.canvas.setMinimumWidth(240)
        self.rotation_slider = RotationSlider()
        self.rotation_slider.setMinimumWidth(50)
        self.rotation_slider.setRange(-180, 180)
        self.rotation_slider.setTickInterval(45)
        self.rotation_slider.setAccessibleName("Originalobjekt um seine vertikale Achse drehen")
        self.rotation_slider.setToolTip("Beim Ziehen rastet der Regler alle 90° ein. Alternativ mit der rechten Maustaste horizontal in der Vorschau ziehen\nDoppelklick auf den Greifer: 0° wiederherstellen.")
        self.rotation_label = QLabel("0°")
        self.rotation_controls = _RotationControls(self.rotation_slider, self.rotation_label)
        self.preview_controls = _PreviewControls(self.xray_button, self.resolution_control,
                                                 self.rotation_controls, self.fit_button)
        right_layout.addWidget(self.preview_controls)
        self.canvas.set_target_time(target_time_s)
        self.canvas.set_color_thresholds(self.color_start_spin.value(), self.color_full_spin.value())
        right_layout.addWidget(self.canvas, 1)
        help_label = QLabel("Freie Fläche: Bereich zeichnen · Greifer: Grenzen ändern · Bereichsfläche: verschieben\nMausrad: zoomen · mittlere Taste: Ansicht verschieben · rechte Taste: Objekt drehen")
        help_label.setWordWrap(True)
        self.preview_notes = QScrollArea()
        self.preview_notes.setObjectName("layerRangePreviewNotes")
        self.preview_notes.setFrameShape(QFrame.Shape.NoFrame)
        self.preview_notes.setWidgetResizable(True)
        self.preview_notes.setMinimumHeight(64)
        self.preview_notes.setMaximumHeight(150)
        self.preview_notes.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        notes_content = QWidget()
        notes_layout = QVBoxLayout(notes_content)
        notes_layout.setContentsMargins(0, 0, 4, 0)
        notes_layout.setSpacing(8)
        notes_layout.addWidget(help_label)
        self.legend = LayerTimeLegend()
        self.legend.set_thresholds(self.color_start_spin.value(), self.color_full_spin.value())
        notes_layout.addWidget(self.legend)
        self.preview_notes.setWidget(notes_content)
        right_layout.addWidget(self.preview_notes)
        self.splitter.addWidget(right)
        self.splitter.setStretchFactor(0, 0)
        self.splitter.setStretchFactor(1, 1)
        self.ensurePolished()
        self.footer_divider = QFrame()
        self.footer_divider.setObjectName("footerHorizontalDivider")
        self.footer_divider.setFixedHeight(1)
        layout.addWidget(self.footer_divider)
        footer_host = QWidget()
        footer = QHBoxLayout(footer_host)
        footer.setContentsMargins(18, 12, 18, 14)
        notice = QLabel("Änderungen werden erst mit Übernehmen angewendet.")
        notice.setWordWrap(True)
        footer.addWidget(notice, 1)
        self.cancel_button = QPushButton("Abbrechen")
        self.cancel_button.setObjectName("layerRangeCancelButton")
        self.cancel_button.setAutoDefault(False)
        self.cancel_button.clicked.connect(self.reject)
        footer.addWidget(self.cancel_button)
        self.apply_button = QPushButton("Übernehmen")
        self.apply_button.setObjectName("layerRangeApplyButton")
        self.apply_button.setAutoDefault(False)
        self.apply_button.clicked.connect(self._accept_changes)
        footer.addWidget(self.apply_button)
        layout.addWidget(footer_host)

        self.target_spin.valueChanged.connect(self._target_changed)
        self.target_reset_button.clicked.connect(lambda: self.target_spin.setValue(self._target_default))
        self._refresh_target_reset()
        self.color_start_spin.valueChanged.connect(self._color_threshold_changed)
        self.color_full_spin.valueChanged.connect(self._color_threshold_changed)
        self.color_gradient.start_changed.connect(self.color_start_spin.setValue)
        self.color_gradient.full_changed.connect(self.color_full_spin.setValue)
        self.color_gradient.set_thresholds(self.color_start_spin.value(), self.color_full_spin.value())
        self._refresh_color_labels()
        self.color_reset_button.clicked.connect(self._reset_color_thresholds)
        self.add_button.clicked.connect(self._add_range)
        self.fit_button.clicked.connect(self.canvas.fit_object)
        self.canvas.fit_available_changed.connect(self._fit_available_changed)
        self.canvas.range_committed.connect(self.commit_range)
        self.canvas.remove_requested.connect(self.remove_range)
        self.canvas.selection_changed.connect(self.select_range)
        self.rotation_slider.valueChanged.connect(self._slider_rotation_changed)
        self.canvas.rotation_changed.connect(self._rotation_changed)
        self._refresh_color_reset()
        self.color_enabled_checkbox.toggled.connect(self._time_coloring_toggled)
        self._time_coloring_toggled(time_coloring_enabled)
        self._rebuild_rows()
        self._sync_selection()
        self._preferred_pane_widths = (self._unwrapped_settings_width(), 650 + 14)
        self.settings_panel.setMinimumWidth(self._preferred_pane_widths[0])
        self._settings_width_signature = self._settings_content_signature()
        self.settings_panel.installEventFilter(self)
        self.rows_host.installEventFilter(self)
        self.splitter.setSizes(self._preferred_pane_widths)
        self.resize(self.sizeHint())

    def _unwrapped_settings_width(self):
        # Measure full labels and single-row layouts, including list controls
        # and space for its scrollbar. Empty-list prose remains free to wrap.
        labels = [label for label in self.settings_panel.findChildren(QLabel)
                  if label.wordWrap() and label.objectName() != "layerRangeEmptyHint"]
        layouts = self.settings_panel.findChildren(QVBoxLayout) + self.settings_panel.findChildren(QHBoxLayout)
        for label in labels:
            label.setWordWrap(False)
        for layout in layouts:
            layout.invalidate()
        left = self.settings_panel.layout()
        margins = left.contentsMargins()
        row_margins = self.rows_layout.contentsMargins()
        rows_width = (max((row.sizeHint().width() for row, _, _, _ in self.range_rows), default=0)
                      + row_margins.left() + row_margins.right() + self.scroll.verticalScrollBar().sizeHint().width()
                      + self.scroll.frameWidth() * 2 + margins.left() + margins.right())
        # The scroll area's cached size hint can include the empty-list prose.
        # Measure its real range rows separately and ignore that prose entirely.
        controls_width = max((left.itemAt(index).sizeHint().width() for index in range(left.count())
                              if left.itemAt(index).widget() is not self.scroll), default=0)
        width = max(controls_width + margins.left() + margins.right(), rows_width)
        for label in labels:
            label.setWordWrap(True)
        for layout in layouts:
            layout.invalidate()
        return width

    def _settings_content_signature(self):
        # Avoid remeasuring unchanged labels: temporarily disabling word wrap
        # during measurement itself queues another Qt layout request.
        return tuple(("layer-number" if isinstance(widget, _CompactLayerSpin) else widget.text(),
                      widget.font().toString(), widget.sizeHint().width())
                     for widget in self.settings_panel.findChildren(QWidget)
                     if isinstance(widget, (QLabel, QPushButton, _CompactSpin))
                     and widget.objectName() != "layerRangeEmptyHint")

    def eventFilter(self, watched, event):
        if event.type() in (QEvent.Type.LayoutRequest, QEvent.Type.FontChange, QEvent.Type.StyleChange):
            if hasattr(self, "_settings_width_signature"):
                if self._settings_content_signature() != self._settings_width_signature:
                    self._pane_resize_timer.start(0)
        return super().eventFilter(watched, event)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        # Wait until the body layout has assigned the splitter's new width.
        self._pane_resize_timer.start(0)

    def _resize_panes(self):
        if not hasattr(self, "_preferred_pane_widths"):
            return
        signature = self._settings_content_signature()
        if signature != self._settings_width_signature:
            width = self._unwrapped_settings_width()
            self.settings_panel.setMinimumWidth(width)
            self._preferred_pane_widths = (width, self._preferred_pane_widths[1])
            self._settings_width_signature = self._settings_content_signature()
        available = self.splitter.contentsRect().width() - self.splitter.handleWidth()
        left_width = self._preferred_pane_widths[0]
        self.splitter.setSizes((left_width, max(0, available - left_width)))

    def initial_size(self, available_size=None):
        """Fit the controls around a 650 × 550 preview, within available space."""
        body = self.layout().itemAt(0).widget()
        body_margins = body.layout().contentsMargins()
        right_layout = self.splitter.widget(1).layout()
        right_margins = right_layout.contentsMargins()
        width = (self._preferred_pane_widths[0] + 650 + right_margins.left() + right_margins.right()
                 + self.splitter.handleWidth() + body_margins.left() + body_margins.right())
        if available_size is not None:
            width = max(self.minimumSizeHint().width(), min(width, available_size.width()))
        preview_width = (width - body_margins.left() - body_margins.right() - self.splitter.handleWidth()
                         - self._preferred_pane_widths[0] - right_margins.left() - right_margins.right())
        overhead = right_margins.top() + right_margins.bottom() + right_layout.spacing() * (right_layout.count() - 1)
        for index in range(right_layout.count()):
            item = right_layout.itemAt(index)
            if item.widget() is self.canvas:
                continue
            if item.widget() is self.preview_notes:
                notes_height = max(self.preview_notes.sizeHint().height(),
                                   self.preview_notes.widget().layout().totalHeightForWidth(preview_width))
                overhead += max(self.preview_notes.minimumHeight(), min(self.preview_notes.maximumHeight(), notes_height))
            else:
                overhead += item.heightForWidth(preview_width) if item.hasHeightForWidth() else item.sizeHint().height()
        height = max(self.settings_panel.minimumSizeHint().height(), 550 + overhead)
        height += body_margins.top() + body_margins.bottom()
        for index in range(1, self.layout().count()):
            item = self.layout().itemAt(index)
            height += item.heightForWidth(width) if item.hasHeightForWidth() else item.sizeHint().height()
        if available_size is not None:
            height = max(self.minimumSizeHint().height(), min(height, available_size.height()))
        return QSize(width, height)

    def sizeHint(self):
        if hasattr(self, "_preferred_pane_widths"):
            return self.initial_size()
        return super().sizeHint()

    def _accept_changes(self):
        if not self.apply_button.isEnabled():
            return
        # Commit the focused numeric editor before transferring the draft.
        focus = self.focusWidget()
        if focus is not None:
            focus.clearFocus()
        for spin in (self.target_spin, self.color_start_spin, self.color_full_spin):
            spin.interpretText()
        self.accept()

    def _rotation_changed(self, angle):
        with QSignalBlocker(self.rotation_slider):
            self.rotation_slider.setValue(angle)
        self.rotation_label.setText(f"{angle}°")
        self.preview_controls.updateGeometry()
        self.preview_controls._arrange()

    def _fit_available_changed(self, available):
        self.fit_button.setEnabled(available)
        self.fit_button.setProperty("needsFit", available)
        self.fit_button.style().unpolish(self.fit_button)
        self.fit_button.style().polish(self.fit_button)
        self.fit_button.update()

    def _slider_rotation_changed(self, angle):
        if self.rotation_slider.isSliderDown():
            nearest = round(angle / 90) * 90
            if abs(angle - nearest) < 10:
                angle = nearest
                with QSignalBlocker(self.rotation_slider):
                    self.rotation_slider.setValue(angle)
        self.canvas.set_rotation(angle)

    def _ordered_ranges(self, ranges):
        # Canonical model data is ascending; the editor's visible order is top-down.
        return normalize_layer_ranges(ranges, layer_count=self.layer_count)[::-1]

    @staticmethod
    def _info_button(hint, label):
        return InfoToolButton(hint, accessible_name=f"Informationen zu {label}",
                              object_name="settingInfoButton", diameter_px=METRICS.setting_info_diameter_px)

    def _color_spin(self, value, minimum, maximum, label, prefix):
        spin = _DeficitSpin()
        spin.setLocale(QLocale(QLocale.Language.German))
        # Accept precise typed values, then normalize with decimal half-up rounding.
        spin.setDecimals(10)
        spin.setRange(minimum, maximum)
        spin.setSingleStep(.1)
        spin.setSuffix(" s")
        spin.setPrefix(prefix)
        spin.setKeyboardTracking(False)
        spin.setValue(value)
        spin.setAccessibleName(label)
        return spin

    @staticmethod
    def _input_group(label, spin, info=None):
        group = QWidget()
        layout = QHBoxLayout(group)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(6)
        if info is not None:
            layout.addWidget(info)
        text = QLabel(label)
        text.setBuddy(spin)
        layout.addWidget(text)
        layout.addWidget(spin)
        return group

    def _color_threshold_changed(self, _value):
        start, full = self.color_start_spin.value(), self.color_full_spin.value()
        if start >= full:
            if self.sender() is self.color_start_spin:
                with QSignalBlocker(self.color_full_spin):
                    self.color_full_spin.setValue(start + .1)
            else:
                with QSignalBlocker(self.color_start_spin):
                    self.color_start_spin.setValue(full - .1)
        start, full = self.color_start_spin.value(), self.color_full_spin.value()
        self.canvas.set_color_thresholds(start, full)
        self.legend.set_thresholds(start, full)
        self.legend.set_time_coloring_enabled(self.color_enabled_checkbox.isChecked())
        self.color_gradient.set_thresholds(start, full)
        self._refresh_color_labels()
        self._refresh_color_reset()
        self.color_thresholds_changed.emit(start, full)

    def _time_coloring_toggled(self, enabled):
        self.color_settings.setVisible(enabled)
        self.canvas.set_time_coloring_enabled(enabled)
        self.legend.set_time_coloring_enabled(enabled)
        self.preview_notes.updateGeometry()

    def _refresh_color_labels(self):
        self.color_start_label.setText(f"{self.color_start_spin.value():.1f} s".replace(".", ","))
        self.color_full_label.setText(f"{self.color_full_spin.value():.1f} s".replace(".", ","))

    def _refresh_color_reset(self):
        changed = self.color_start_spin.value() != 0.0 or self.color_full_spin.value() != 1.0
        self.color_reset_button.setEnabled(changed)
        self.color_reset_button.setProperty("modified", changed)
        self.color_reset_button.style().unpolish(self.color_reset_button)
        self.color_reset_button.style().polish(self.color_reset_button)

    def _reset_color_thresholds(self):
        with QSignalBlocker(self.color_start_spin), QSignalBlocker(self.color_full_spin):
            self.color_start_spin.setValue(0.0)
            self.color_full_spin.setValue(1.0)
        self._color_threshold_changed(None)

    @staticmethod
    def _compact_button(button):
        button.setProperty("rangeCompact", True)
        button.setFixedHeight(METRICS.info_button_diameter_px)

    @staticmethod
    def _button(text, action):
        button = QPushButton(text)
        button.setProperty("rangeAction", action)
        button.setAutoDefault(False)
        LayerRangeDialog._compact_button(button)
        return button

    def _layer_spin(self, value, name):
        spin = _CompactLayerSpin()
        spin.setRange(1, self.layer_count)
        spin.setKeyboardTracking(False)
        spin.setValue(value)
        spin.setAccessibleName(name)
        return spin

    def set_target_time(self, value):
        with QSignalBlocker(self.target_spin):
            self.target_spin.setValue(value)
        self.canvas.set_target_time(value)
        self._refresh_target_reset()

    def set_ranges(self, ranges):
        self.ranges = self._ordered_ranges(ranges)
        self.selected = -1
        self._sync_selection()
        self._schedule_rows()

    def _target_changed(self, value):
        self.canvas.set_target_time(value)
        self._refresh_target_reset()
        self.target_time_changed.emit(value)

    def _refresh_target_reset(self):
        changed = self.target_spin.value() != self._target_default
        self.target_reset_button.setEnabled(changed)
        self.target_reset_button.setProperty("modified", changed)
        self.target_reset_button.style().unpolish(self.target_reset_button)
        self.target_reset_button.style().polish(self.target_reset_button)

    def set_editing_enabled(self, enabled):
        self.settings_panel.setEnabled(enabled)
        self.canvas.setEnabled(enabled)
        self.apply_button.setEnabled(enabled)

    def _add_range(self):
        start, end = sorted((self.new_start_spin.value(), self.new_end_spin.value()))
        self.commit_range(-1, start, end)

    def commit_range(self, index, start, end):
        spans = list(self.ranges)
        previous_count = len(spans)
        if 0 <= index < len(spans):
            spans[index] = (start, end)
        else:
            spans.append((start, end))
        normalized = self._ordered_ranges(spans)
        changed = normalized != self.ranges
        self.ranges = normalized
        self.selected = next(i for i, (a, b) in enumerate(normalized) if a <= start <= end <= b)
        merged = len(normalized) < previous_count + (index < 0)
        self._sync_selection()
        if changed:
            self._schedule_rows()
        else:
            self._selection_scroll_timer.start(0)
        self.status_label.setText("Überlappende / angrenzende Bereiche wurden verbunden." if merged else f"{len(normalized)} Bereich(e) · {sum(b - a + 1 for a, b in normalized)} Layer ausgeschlossen")
        if changed:
            self.ranges_changed.emit(self.ranges)

    def remove_range(self, index):
        if not 0 <= index < len(self.ranges):
            return
        self.ranges = self.ranges[:index] + self.ranges[index + 1:]
        self.selected = min(index, len(self.ranges) - 1)
        self._sync_selection()
        self._schedule_rows()
        self.status_label.setText(f"{len(self.ranges)} Bereich(e) · Bereich entfernt")
        self.ranges_changed.emit(self.ranges)

    def select_range(self, index):
        self.selected = index
        self._sync_selection()
        self._selection_scroll_timer.start(0)

    def _sync_selection(self):
        self.canvas.set_ranges(self.ranges, self.selected)
        for index, (row, _, _, button) in enumerate(self.range_rows):
            row.setProperty("selected", index == self.selected)
            row.style().unpolish(row)
            row.style().polish(row)
            row.update()
            with QSignalBlocker(button):
                button.setChecked(index == self.selected)

    def _schedule_rows(self):
        if not self._rows_pending:
            self._rows_pending = True
            self._rows_rebuild_timer.start(0)

    def _rebuild_rows(self):
        self._rows_pending = False
        self.range_rows = []
        while self.rows_layout.count():
            item = self.rows_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
        for index, (start, end) in enumerate(self.ranges):
            row = QFrame()
            row.setObjectName("layerRangeRow")
            row.setProperty("selected", index == self.selected)
            box = QVBoxLayout(row)
            box.setContentsMargins(0, 0, 0, 0)
            box.setSpacing(0)
            header = QHBoxLayout()
            header.setContentsMargins(0, 0, 0, 0)
            header.setSpacing(0)
            select = QPushButton(f"Ausschlussbereich {index + 1}")
            select.setObjectName("layerRangeSelectButton")
            self._compact_button(select)
            select.setAutoDefault(False)
            select.setCheckable(True)
            select.setChecked(index == self.selected)
            select.clicked.connect(lambda checked=False, i=index: self.select_range(i))
            select.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
            header.addWidget(select, 1)
            remove = self._button("Entfernen", "remove")
            remove.setObjectName("layerRangeRemoveButton")
            remove.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
            remove.setAccessibleName(f"Ausschlussbereich {index + 1} entfernen")
            remove.clicked.connect(lambda checked=False, i=index: self.remove_range(i))
            header.addWidget(remove)
            box.addLayout(header)
            editors_host = QWidget()
            editors = QHBoxLayout(editors_host)
            editors.setContentsMargins(10, 8, 10, 8)
            editors.setSpacing(6)
            first = self._layer_spin(start, f"Ausschlussbereich {index + 1}: erster Layer")
            last = self._layer_spin(end, f"Ausschlussbereich {index + 1}: letzter Layer")
            for label, spin in (("Von Layer", first), ("bis", last)):
                editors.addWidget(self._input_group(label, spin))
            editors.addStretch(1)
            box.addWidget(editors_host)
            for spin in (first, last):
                spin.editingFinished.connect(lambda r=row: self._commit_row(r))
            self.rows_layout.addWidget(row)
            self.range_rows.append((row, first, last, select))
        if not self.ranges:
            empty = QLabel("Es wurden noch keine Bereiche definiert.\n\n"
                           "Füge einen festen Bereich hinzu oder zeichne einen direkt in die Vorschau ein.")
            empty.setObjectName("layerRangeEmptyHint")
            empty.setWordWrap(True)
            self.rows_layout.addWidget(empty)
        self.rows_layout.addStretch()
        # Wait for the scroll area's layout after rebuilding its content.
        self._selection_scroll_timer.start(0)

    def _ensure_selected_row_visible(self):
        if 0 <= self.selected < len(self.range_rows):
            self.rows_layout.activate()
            rect = self.range_rows[self.selected][0].geometry()
            bar = self.scroll.verticalScrollBar()
            height = self.scroll.viewport().height()
            if rect.top() - 6 < bar.value():
                bar.setValue(rect.top() - 6)
            elif rect.bottom() + 6 >= bar.value() + height:
                bar.setValue(rect.bottom() + 7 - height)

    def _commit_row(self, row):
        if self._rows_pending:
            return
        for index, (candidate, first, last, _) in enumerate(self.range_rows):
            if candidate is row:
                start, end = sorted((first.value(), last.value()))
                if (start, end) != self.ranges[index]:
                    self.commit_range(index, start, end)
                break
