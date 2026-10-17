"""Shared, optional time-deficit coloring controls for both profile editors."""
from __future__ import annotations

import math

from PySide6.QtCore import QLocale, QSignalBlocker, Qt, Signal
from PySide6.QtWidgets import QCheckBox, QHBoxLayout, QLabel, QVBoxLayout, QWidget

from cooling_tower.gui.design_tokens import METRICS
from cooling_tower.gui.widgets.compact_preview_inputs import _DeficitSpin, _InputResetButton
from cooling_tower.gui.widgets.deficit_range_slider import DeficitRangeSlider
from cooling_tower.gui.widgets.info_tool_button import InfoToolButton


class TimeDeficitControls(QWidget):
    thresholds_changed = Signal(float, float)
    CONTROL_NAMES = (
        "color_info_button", "color_enabled_checkbox", "color_settings",
        "color_start_label", "color_full_label", "color_gradient",
        "color_start_spin", "color_full_spin", "color_reset_button",
    )

    def __init__(self, *, enabled=False, start=0.0, full=1.0,
                 reference_description="gewünschten Mindest-Layerzeit",
                 preserve_extended_range=False, parent=None):
        super().__init__(parent)
        self.setObjectName("timeDeficitControls")
        self._preserve_extended_range = preserve_extended_range
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(6)
        header = QHBoxLayout()
        header.setSpacing(6)
        self.color_info_button = InfoToolButton(
            f"• Zeigt, wie viele Sekunden einem Original-Layer zur {reference_description} fehlen.\n"
            "• Zwei Grenzen bestimmen den Übergang von Grün (geringes Defizit) zu Rot (hohes Defizit).\n"
            "• Grenzen per Greifer oder Wertefeld einstellen.\n"
            "• Ändert nur die Vorschaufarben, nicht die Turmberechnung.",
            accessible_name="Informationen zu Zeitdefizit-Einfärbung aktivieren",
            object_name="settingInfoButton", diameter_px=METRICS.setting_info_diameter_px)
        header.addWidget(self.color_info_button)
        self.color_enabled_checkbox = QCheckBox("Zeitdefizit-Einfärbung aktivieren")
        self.color_enabled_checkbox.setLayoutDirection(Qt.LayoutDirection.RightToLeft)
        self.color_enabled_checkbox.setAccessibleName(self.color_enabled_checkbox.text())
        self.color_enabled_checkbox.setChecked(enabled)
        header.addWidget(self.color_enabled_checkbox)
        header.addStretch(1)
        layout.addLayout(header)
        self.color_settings = QWidget()
        limits = QVBoxLayout(self.color_settings)
        limits.setContentsMargins(0, 0, 0, 0)
        limits.setSpacing(3)
        scale = QHBoxLayout()
        scale.setSpacing(6)
        self.color_start_label, self.color_full_label = QLabel(), QLabel()
        self.color_gradient = DeficitRangeSlider()
        scale.addWidget(self.color_start_label)
        scale.addWidget(self.color_gradient, 1)
        scale.addWidget(self.color_full_label)
        limits.addLayout(scale)
        inputs = QHBoxLayout()
        inputs.setContentsMargins(0, 0, 0, 0)
        inputs.setSpacing(6)
        self.color_start_spin = self._spin("Grün bis Defizit", "≤ ")
        self.color_full_spin = self._spin("Vollständig rot ab Defizit", "≥ ")
        inputs.addWidget(self.color_start_spin)
        inputs.addStretch(1)
        inputs.addWidget(self.color_full_spin)
        self.color_reset_button = _InputResetButton(self.color_full_spin)
        self.color_reset_button.setObjectName("settingResetButton")
        self.color_reset_button.setAutoDefault(False)
        self.color_reset_button.setToolTip("Defizitgrenzen auf 0,0 s und 1,0 s zurücksetzen")
        self.color_reset_button.setAccessibleName("Defizitgrenzen zurücksetzen")
        inputs.addWidget(self.color_reset_button, 0, Qt.AlignmentFlag.AlignVCenter)
        limits.addLayout(inputs)
        layout.addWidget(self.color_settings)
        self.color_start_spin.setToolTip("Bis zu diesem Layerzeit-Defizit bleibt das Objekt grün. Danach beginnt der Farbverlauf zu Rot.")
        self.color_full_spin.setToolTip("Ab diesem Layerzeit-Defizit ist das Objekt vollständig rot. Der Wert muss größer als der Beginn des Farbverlaufs sein.")
        self.set_thresholds(start, full)
        self.color_start_spin.valueChanged.connect(self._threshold_changed)
        self.color_full_spin.valueChanged.connect(self._threshold_changed)
        self.color_gradient.start_changed.connect(self.color_start_spin.setValue)
        self.color_gradient.full_changed.connect(self.color_full_spin.setValue)
        self.color_reset_button.clicked.connect(self._reset_thresholds)
        self.color_enabled_checkbox.toggled.connect(self.color_settings.setVisible)
        self.color_settings.setVisible(enabled)

    @staticmethod
    def _spin(name, prefix):
        spin = _DeficitSpin()
        spin.setLocale(QLocale(QLocale.Language.German))
        spin.setDecimals(10)
        spin.setSingleStep(.1)
        spin.setSuffix(" s")
        spin.setPrefix(prefix)
        spin.setKeyboardTracking(False)
        spin.setAccessibleName(name)
        return spin

    def set_thresholds(self, start, full):
        # Older manual preferences allow up to 30 s. Display them faithfully
        # without rewriting stored values merely by opening the editor.
        maximum = (max(DeficitRangeSlider.MAXIMUM_SECONDS, math.ceil(full))
                   if self._preserve_extended_range else DeficitRangeSlider.MAXIMUM_SECONDS)
        self.color_gradient.MAXIMUM_SECONDS = maximum
        self.color_gradient.MAXIMUM_TICKS = round(maximum * 10)
        with QSignalBlocker(self.color_gradient.start_handle), QSignalBlocker(self.color_gradient.full_handle):
            self.color_gradient.start_handle.setMaximum(round(maximum * 10) - 1)
            self.color_gradient.full_handle.setMaximum(round(maximum * 10))
        self.color_gradient.setToolTip(f"Defizitgrenzen mit den beiden Greifern einstellen · Skala: 0,0 bis {maximum:.1f} s".replace(".", ","))
        self.color_gradient.setAccessibleName(f"Defizit-Einfärbung von 0 bis {maximum:g} Sekunden")
        with QSignalBlocker(self.color_start_spin), QSignalBlocker(self.color_full_spin):
            self.color_start_spin.setRange(0, maximum - .1)
            self.color_full_spin.setRange(.1, maximum)
            self.color_start_spin.setValue(start)
            self.color_full_spin.setValue(max(full, self.color_start_spin.value() + .1))
        self._refresh()

    def _threshold_changed(self, _value):
        start, full = self.color_start_spin.value(), self.color_full_spin.value()
        if start >= full:
            if self.sender() is self.color_start_spin:
                with QSignalBlocker(self.color_full_spin):
                    self.color_full_spin.setValue(start + .1)
            else:
                with QSignalBlocker(self.color_start_spin):
                    self.color_start_spin.setValue(full - .1)
        self._refresh()
        self.thresholds_changed.emit(self.color_start_spin.value(), self.color_full_spin.value())

    def _refresh(self):
        start, full = self.color_start_spin.value(), self.color_full_spin.value()
        self.color_gradient.set_thresholds(start, full)
        self.color_start_label.setText(f"{start:.1f} s".replace(".", ","))
        self.color_full_label.setText(f"{full:.1f} s".replace(".", ","))
        changed = start != 0.0 or full != 1.0
        self.color_reset_button.setEnabled(changed)
        self.color_reset_button.setProperty("modified", changed)
        self.color_reset_button.style().unpolish(self.color_reset_button)
        self.color_reset_button.style().polish(self.color_reset_button)

    def _reset_thresholds(self):
        self.set_thresholds(0.0, 1.0)
        self.thresholds_changed.emit(0.0, 1.0)
