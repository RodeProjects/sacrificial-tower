"""Preprocessor controls using the application's shared settings and card design."""
from __future__ import annotations

from html import escape

from PySide6.QtCore import QSignalBlocker, QTimer, Qt, Signal
from PySide6.QtWidgets import (
    QCheckBox, QFrame, QHBoxLayout, QLabel, QPushButton, QSizePolicy, QVBoxLayout, QWidget,
)

from cooling_tower.gui.design_tokens import METRICS
from cooling_tower.gui.widgets.activity_progress_bar import ActivityProgressBar
from cooling_tower.gui.widgets.info_tool_button import InfoToolButton
from cooling_tower.gui.widgets.numeric_setting import NumericSettingWidget
from cooling_tower.gui.widgets.preview_canvas import PreviewCanvas
from cooling_tower.gui.widgets.responsive_card_grid import ResponsiveCardGrid
from cooling_tower.gui.widgets.section_card import SectionCard
from cooling_tower.gui.widgets.wheel_safe_inputs import WheelSafeDoubleSpinBox, WheelSafeSpinBox
from cooling_tower.preprocessor import PreprocessorSettings


AUTOMATIC_FIELDS = {
    "automatic_height": ("height_mm",),
    "automatic_diameter": ("diameter_mm",),
    "automatic_base": ("base_width_mm",),
    "automatic_position": ("center_x_mm", "center_y_mm"),
    "automatic_wait_position": ("wait_x_mm", "wait_y_mm"),
}

HINTS = {
    "target_layer_time_s": ("Jede Schicht soll mindestens diese Zeit erreichen.",
        "Fahrten, Z-Hops, Turmdruck und Primen zählen mit. Nur die fehlende Restzeit wird vor dem Abstreifen gewartet."),
    "height_mm": ("Automatisch reicht der Turm bis zur letzten Originalschicht mit Zeitdefizit.",
        "Manuelle Höhen werden auf vorhandene Schichten abgerundet. Ein zu kurzer Turm sperrt den Export."),
    "diameter_mm": ("Bestimmt die Breite des hohlen Turmschafts.",
        "Automatisch wächst sie mit der Turmhöhe und der nötigen Wandstärke. Mehr Breite erhöht die Stabilität."),
    "base_width_mm": ("Der breitere Standfuß verbessert Haftung und Stabilität.",
        "Automatisch berücksichtigt er Turmhöhe und Schaftbreite. Die ersten zwei Schichten sind geschlossen; darüber bleibt der Turm hohl."),
    "center_x_mm": ("X-Koordinate der Turmmitte im G-Code-Koordinatensystem.",
        "Automatisch wird eine erreichbare Position mit kurzen Wegen und ausreichend Abstand zu Modell, Bettkante und Sperrflächen gesucht."),
    "center_y_mm": ("Y-Koordinate der Turmmitte; dieselbe Platzierungsautomatik gilt für X und Y.",
        "Auch manuelle Positionen müssen alle Abstands- und Fahrwegprüfungen bestehen."),
    "clearance_mm": ("Mindestens dieser Abstand bleibt zwischen Modell und vollständigem Turmfuß frei.",
        "Größere Abstände benötigen mehr Bettfläche und längere Fahrwege."),
    "wait_x_mm": ("X-Koordinate des freien Warteplatzes außerhalb von Modell und Turm.",
        "Erst hier wird die fehlende Schichtzeit abgewartet. Danach fährt die angehobene Düse zum Abstreifen an den Turm."),
    "wait_y_mm": ("Y-Koordinate des freien Warteplatzes; die Automatik für X und Y ist gekoppelt.",
        "Die Düse wartet mit Sicherheitshub. Ungültige Positionen sperren den Export."),
    "edge_clearance_mm": ("Mindestabstand von Turm und Warteplatz zur Bettkante und zu Profil-Sperrflächen.",
        "Die tatsächliche Bettform und ihr Koordinatenursprung werden berücksichtigt."),
    "wait_clearance_mm": ("Mindestabstand des Warteplatzes zu Modell und vollständigem Turmfuß.",
        "Die Düse darf während der Pause über keinem der beiden Objekte stehen."),
    "print_speed_mm_s": ("Geschwindigkeit der zusätzlich gedruckten Turmbahnen.",
        "Die berechnete Druckzeit zählt bereits zur Mindest-Schichtzeit."),
    "travel_speed_mm_s": ("Geschwindigkeit der zusätzlichen Fahrten ohne Materialablage.",
        "Beschleunigungen und Fahrzeiten werden bei der Restwartezeit berücksichtigt."),
    "retract_mm": ("Zusätzlicher Filamentrückzug vor Parken und Rückfahrt.",
        "Der Rückzug wird anschließend ausgeglichen; zusätzliche Prime-Menge lässt sich getrennt einstellen."),
    "retract_speed_mm_s": ("Geschwindigkeit für zusätzlichen Rückzug und dessen Ausgleich.",
        "Wähle einen für den verwendeten Extruder geeigneten Wert."),
    "z_hop_mm": ("Vor zusätzlichen Fahrten hebt die Düse senkrecht an und senkt erst am Ziel wieder ab.",
        "Es gilt mindestens der Z-Hop des gewählten Profils. Originale Z-Bewegungen bleiben erhalten; die maximale Druckhöhe darf nicht überschritten werden."),
    "prime_mm": ("Zusätzlich gefördertes Filament am Turm nach dem Warten.",
        "Es füllt die Düse vor der Rückkehr zum Modell. Zu große Mengen können Klumpen am Turm erzeugen."),
    "wall_count": ("Anzahl der gedruckten Wandlinien des hohlen Turms.",
        "Mehr Linien verstärken die Wand und benötigen mehr Material. Der innere Hohlraum muss erhalten bleiben."),
    "hollow_tower": ("Standard ist ein hohler Turm mit zwei geschlossenen Bodenlagen.",
        "Ohne Hohlbauweise wird auch der Turmkörper gefüllt. Die nötige Restzeit entsteht weiterhin durch Warten."),
    "show_travel": ("Zeigt zusätzliche Leerfahrten, Z-Hops und den freien Warteplatz gelb an.",
        "Dieser Schalter ändert nur die Ansicht; der erzeugte G-Code bleibt gleich."),
}


def setting_hint(label, name):
    bullets = "<br>".join("&#8226; " + escape(text) for text in HINTS[name])
    return (f'<p align="left" style="margin-top:0; margin-bottom:0px;"><b>{escape(label)}</b></p>'
        f'<p style="margin-top:0; margin-bottom:10px;">{bullets}</p>')


class PreprocessorPanel(QWidget):
    changed = Signal()
    layout_changed = Signal()

    def __init__(self):
        super().__init__()
        self.setObjectName("preprocessorPanel")
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(METRICS.card_spacing_px)
        layout.setAlignment(Qt.AlignmentFlag.AlignTop)
        self.error_label = QLabel()
        self.error_label.setWordWrap(True)
        self.error_label.setObjectName("errorLabel")
        self.error_label.hide()
        layout.addWidget(self.error_label)
        self.columns = ResponsiveCardGrid(horizontal_spacing_px=0, vertical_spacing_px=0)
        self._layout_timer = QTimer(self)
        self._layout_timer.setSingleShot(True)
        self._layout_timer.timeout.connect(self.refresh_layout)
        divider = QFrame()
        divider.setObjectName("readyColumnsDivider")
        divider.setFixedWidth(1)
        self.columns.set_vertical_separator(divider)
        layout.addWidget(self.columns)
        left = QWidget()
        self.settings_column = left
        left_layout = QVBoxLayout(left)
        left_layout.setContentsMargins(0, 0, 0, 0)
        left_layout.setSpacing(METRICS.card_spacing_px)
        left_layout.setAlignment(Qt.AlignmentFlag.AlignTop)
        self.input_group = SectionCard("Präprozessor-Einstellungen")
        left_layout.addWidget(self.input_group)
        self.inputs, self.automatic, self.rows = {}, {}, {}
        self.reset_buttons, self.info_buttons = {}, {}
        for name, label, unit, low, high, automatic in (
            ("target_layer_time_s", "Mindest-Schichtzeit", "s", .1, 3600, None),
            ("height_mm", "Turmhöhe", "mm", .01, 1000, "automatic_height"),
            ("diameter_mm", "Turmdurchmesser", "mm", 3, 100, "automatic_diameter"),
            ("base_width_mm", "Standfußbreite", "mm", 3, 150, "automatic_base"),
            ("center_x_mm", "Turmmitte X", "mm", -2000, 2000, "automatic_position"),
            ("center_y_mm", "Turmmitte Y", "mm", -2000, 2000, None),
            ("clearance_mm", "Modellabstand", "mm", 5, 100, None),
            ("wait_x_mm", "Warteposition X", "mm", -2000, 2000, "automatic_wait_position"),
            ("wait_y_mm", "Warteposition Y", "mm", -2000, 2000, None),
        ):
            self._numeric(self.input_group.content_layout, name, label, unit, low, high, automatic)
        self.advanced_group = SectionCard("Erweiterte Einstellungen anzeigen", collapsible=True, expanded=False)
        self.advanced_toggle = self.advanced_group.header
        self.advanced_group.toggled.connect(lambda opened: self.advanced_group.setTitle(
            "Erweiterte Einstellungen ausblenden" if opened else "Erweiterte Einstellungen anzeigen"))
        self.advanced_group.toggled.connect(lambda _: self._layout_timer.start(0))
        left_layout.addWidget(self.advanced_group)
        self.hollow_checkbox = QCheckBox("Hohler Turm")
        self.hollow_checkbox.setChecked(True)
        self.advanced_group.content_layout.addWidget(self._check_row("hollow_tower", self.hollow_checkbox, True))
        self._numeric(self.advanced_group.content_layout, "wall_count", "Wandlinien", "", 2, 6, integer=True)
        self.wall_count_spin = self.inputs.pop("wall_count")
        for name, label, unit, low, high in (
            ("edge_clearance_mm", "Druckbettrandabstand", "mm", 5, 100),
            ("wait_clearance_mm", "Warteabstand", "mm", 5, 100),
            ("print_speed_mm_s", "Turmdruckgeschwindigkeit", "mm/s", 1, 100),
            ("travel_speed_mm_s", "Fahrgeschwindigkeit", "mm/s", 1, 300),
            ("retract_mm", "Zusätzlicher Rückzug", "mm", 0, 10),
            ("retract_speed_mm_s", "Rückzugsgeschwindigkeit", "mm/s", 1, 100),
            ("z_hop_mm", "Sicherheitshub", "mm", .2, 10),
            ("prime_mm", "Zusätzliches Primen", "mm", 0, 5),
        ):
            self._numeric(self.advanced_group.content_layout, name, label, unit, low, high)
        self.preview_group = SectionCard("G-Code-Vorschau")
        self.columns.add_pair(left, self.preview_group, equal_height=False, stacked_right_first=True)
        self.canvas = PreviewCanvas()
        self.canvas.setMinimumWidth(0)
        self.canvas.setFixedHeight(420)
        self.canvas.set_navigation_enabled(True)
        camera_row = QHBoxLayout()
        camera_row.setSpacing(6)
        self.camera_buttons = {}
        for name, label, method in (
            ("three_quarter", "3/4-Ansicht", self.three_quarter_view),
            ("front", "Vorderansicht", self.canvas.front_view),
            ("side", "Seitenansicht", self.canvas.side_view),
            ("top", "Draufsicht", self.top_view),
            ("fit", "Einpassen", self.canvas.fit_scene),
        ):
            button = QPushButton(label)
            button.setObjectName("previewCameraButton")
            font = button.font()
            font.setPointSizeF(10.5)
            button.setFont(font)
            button.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
            button.setToolTip(label)
            button.clicked.connect(method)
            self.camera_buttons[name] = button
            camera_row.addWidget(button, 1)
        self.preview_group.content_layout.addLayout(camera_row)
        self.preview_group.content_layout.addWidget(self.canvas)
        legend = QLabel("Türkis: Modell · Orange: Turm · Gelb: Fahrwege und Warteposition.\n"
            "Die Koordinaten und Bettform entsprechen dem Pre-Slice und dem gewählten Druckprofil.")
        legend.setWordWrap(True)
        legend.setObjectName("helpText")
        self.preview_group.content_layout.addWidget(legend)
        self.show_travel_checkbox = QCheckBox("Fahrwege, Z-Hops und Warteposition anzeigen")
        self.show_travel_checkbox.setChecked(True)
        self.preview_group.content_layout.addWidget(self._check_row("show_travel", self.show_travel_checkbox, True, view_only=True))
        self.summary = QLabel("Einstellungen wählen und G-Code und Vorschau erzeugen.")
        self.summary.setWordWrap(True)
        self.preview_group.content_layout.addWidget(self.summary)
        self._build_footer()
        self._sync_automatic()
        self.refresh_resets()

    def resizeEvent(self, event):  # noqa: N802
        super().resizeEvent(event)
        if self.isVisible():
            self._layout_timer.start(0)

    def showEvent(self, event):  # noqa: N802
        super().showEvent(event)
        self._layout_timer.start(0)

    def refresh_layout(self):
        """Reserve expanded content before the scroll area can compress rows."""
        if not self.isVisible():
            return
        for card in (self.input_group, self.advanced_group, self.preview_group):
            card.content_layout.invalidate()
            card.layout().invalidate()
        self.settings_column.layout().invalidate()
        self.columns.setMinimumHeight(0)
        self.columns.setMaximumHeight(16777215)
        self.columns.refresh_layout()
        for _ in range(3):
            required = self.columns.content_height_hint()
            self.columns.setFixedHeight(required)
            self.columns.grid.activate()
            if required == self.columns.content_height_hint():
                break
        self.updateGeometry()
        self.layout_changed.emit()

    def _numeric(self, layout, name, label, unit, low, high, automatic=None, *, integer=False):
        defaults = PreprocessorSettings()
        spin = WheelSafeSpinBox() if integer else WheelSafeDoubleSpinBox()
        spin.setRange(low, high)
        if not integer:
            spin.setDecimals(2)
        spin.setValue(getattr(defaults, name))
        self.inputs[name] = spin
        row = NumericSettingWidget(setting_name=name, label=label, editor=spin,
            default_provider=lambda: getattr(defaults, name), unit=unit, info_text=setting_hint(label, name))
        self.rows[name] = row
        self.reset_buttons[name], self.info_buttons[name] = row.reset_button, row.info_button
        row.reset_button.clicked.disconnect()
        row.reset_button.clicked.connect(lambda: self.reset_field(name))
        if automatic:
            checkbox = QCheckBox("Automatisch")
            checkbox.setChecked(True)
            checkbox.setAccessibleName(label + " automatisch berechnen")
            self.automatic[automatic] = checkbox
            row.layout().removeWidget(row.reset_button)
            row.layout().addWidget(checkbox, 0, 3, Qt.AlignmentFlag.AlignVCenter)
            row.layout().addWidget(row.reset_button, 0, 4, Qt.AlignmentFlag.AlignVCenter)
            checkbox.toggled.connect(self._changed)
        spin.valueChanged.connect(self._changed)
        layout.addWidget(row)

    def _check_row(self, name, checkbox, default, *, view_only=False):
        row = QWidget()
        layout = QHBoxLayout(row)
        layout.setContentsMargins(0, METRICS.form_row_vertical_padding_px, 0, 2)
        layout.setSpacing(METRICS.form_control_gap_px)
        info = InfoToolButton(setting_hint(checkbox.text(), name), object_name="settingInfoButton",
            diameter_px=METRICS.setting_info_diameter_px, accessible_name="Informationen zu " + checkbox.text())
        reset = QPushButton("↺")
        reset.setObjectName("settingResetButton")
        reset.setFixedSize(METRICS.reset_button_size_px, METRICS.reset_button_size_px)
        reset.setAccessibleName(checkbox.text() + " auf Standardwert zurücksetzen")
        reset.setToolTip("Auf den Standardwert zurücksetzen")
        reset.clicked.connect(lambda: checkbox.setChecked(default))
        layout.addWidget(info)
        layout.addWidget(checkbox, 1)
        layout.addWidget(reset)
        self.reset_buttons[name], self.info_buttons[name] = reset, info
        checkbox.toggled.connect(self.canvas.set_travel_visible if view_only else self._changed)
        checkbox.toggled.connect(self.refresh_resets)
        return row

    def _build_footer(self):
        self.footer_widget = QWidget()
        self.footer_widget.setObjectName("preprocessorFooter")
        self.footer_widget.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Maximum)
        layout = QVBoxLayout(self.footer_widget)
        layout.setContentsMargins(22, 8, 22, 8)
        self.footer_columns = ResponsiveCardGrid(horizontal_spacing_px=12, vertical_spacing_px=8)
        layout.addWidget(self.footer_columns)
        self.footer_message_area = QWidget()
        messages = QVBoxLayout(self.footer_message_area)
        messages.setContentsMargins(0, 0, 0, 0)
        messages.setSpacing(8)
        self.status = QLabel("Einstellungen wählen und die Erzeugung starten.")
        self.status.setWordWrap(True)
        self.status.setTextFormat(Qt.TextFormat.PlainText)
        self.progress = ActivityProgressBar()
        self.progress.setObjectName("mainProgressBar")
        messages.addWidget(self.progress)
        messages.addWidget(self.status)
        messages.addStretch(1)
        resets = QHBoxLayout()
        self.reset_button = QPushButton("Standardwerte")
        self.reset_button.setObjectName("headerResetButton")
        self.reset_button.clicked.connect(self.reset)
        resets.addWidget(self.reset_button)
        resets.addStretch(1)
        messages.addLayout(resets)
        self.footer_action_area = QWidget()
        self.footer_action_area.setObjectName("footerActionArea")
        actions_column = QVBoxLayout(self.footer_action_area)
        actions_column.setContentsMargins(0, 0, 0, 0)
        actions_column.addStretch(1)
        actions = QHBoxLayout()
        actions.setSpacing(8)
        actions.addStretch(1)
        self.generate_button = QPushButton("G-Code und Vorschau erzeugen")
        self.generate_button.setObjectName("previewButton")
        self.export_button = QPushButton("G-Code exportieren")
        self.export_button.setObjectName("exportButton")
        self.cancel_button = QPushButton("Abbrechen")
        self.cancel_button.setObjectName("preprocessorCancelButton")
        for button in (self.generate_button, self.cancel_button, self.export_button):
            actions.addWidget(button)
        actions_column.addLayout(actions)
        vertical, horizontal = QFrame(), QFrame()
        vertical.setObjectName("footerVerticalDivider")
        vertical.setFixedWidth(1)
        horizontal.setObjectName("footerHorizontalDivider")
        horizontal.setFixedHeight(1)
        self.footer_columns.set_vertical_separator(vertical)
        self.footer_columns.set_stacked_separator(horizontal)
        self.footer_columns.add_pair(self.footer_message_area, self.footer_action_area)
        self.footer_widget.hide()

    def settings(self):
        values = {name: spin.value() for name, spin in self.inputs.items()}
        defaults = PreprocessorSettings()
        for flag, names in AUTOMATIC_FIELDS.items():
            if self.automatic[flag].isChecked():
                for name in names:
                    values[name] = getattr(defaults, name)
        return PreprocessorSettings(**values, **{name: box.isChecked() for name, box in self.automatic.items()},
            hollow_tower=self.hollow_checkbox.isChecked(), wall_count=self.wall_count_spin.value())

    def top_view(self):
        self.canvas.apply_camera_state({**self.canvas.camera_state(), "yaw_deg": 0, "pitch_deg": -89})
        self.canvas.fit_objects()

    def three_quarter_view(self):
        self.canvas.apply_camera_state({**self.canvas.camera_state(), "yaw_deg": -38, "pitch_deg": -28})
        self.canvas.fit_objects()

    def _sync_automatic(self):
        for flag, names in AUTOMATIC_FIELDS.items():
            for name in names:
                self.inputs[name].setEnabled(not self.automatic[flag].isChecked())

    def _changed(self, *_):
        self._sync_automatic()
        self.refresh_resets()
        self.changed.emit()

    def reset_field(self, name):
        defaults = PreprocessorSettings()
        flag = next((flag for flag, names in AUTOMATIC_FIELDS.items() if name in names), None)
        widgets = dict(self.inputs, wall_count=self.wall_count_spin)
        for field in AUTOMATIC_FIELDS[flag] if flag else (name,):
            widget = widgets[field]
            with QSignalBlocker(widget):
                widget.setValue(getattr(defaults, field))
        if flag:
            with QSignalBlocker(self.automatic[flag]):
                self.automatic[flag].setChecked(True)
        self._changed()

    def refresh_resets(self, *_):
        defaults = PreprocessorSettings()
        widgets = dict(self.inputs)
        if hasattr(self, "wall_count_spin"):
            widgets["wall_count"] = self.wall_count_spin
        for name, button in self.reset_buttons.items():
            flag = next((flag for flag, names in AUTOMATIC_FIELDS.items() if name in names), None)
            if flag:
                modified = not self.automatic[flag].isChecked()
            elif name == "hollow_tower":
                modified = not self.hollow_checkbox.isChecked()
            elif name == "show_travel":
                modified = not self.show_travel_checkbox.isChecked()
            else:
                modified = abs(widgets[name].value() - getattr(defaults, name)) > 1e-8
            button.setProperty("modified", modified)
            button.setEnabled(modified)
            button.style().unpolish(button)
            button.style().polish(button)

    def reset(self):
        defaults = PreprocessorSettings()
        widgets = dict(self.inputs, wall_count=self.wall_count_spin, hollow_tower=self.hollow_checkbox, **self.automatic)
        for name, widget in widgets.items():
            with QSignalBlocker(widget):
                if isinstance(widget, QCheckBox):
                    widget.setChecked(getattr(defaults, name))
                else:
                    widget.setValue(getattr(defaults, name))
        self.show_travel_checkbox.setChecked(True)
        self._changed()
