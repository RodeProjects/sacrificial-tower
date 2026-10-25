"""Preprocessor controls using the application's shared settings and card design."""
from __future__ import annotations

from html import escape

from PySide6.QtCore import QSignalBlocker, QTimer, Qt, Signal
from PySide6.QtWidgets import (
    QCheckBox, QFrame, QHBoxLayout, QLabel, QPushButton, QSizePolicy, QSlider, QVBoxLayout, QWidget,
)

from cooling_tower.gui.design_tokens import METRICS
from cooling_tower.gui.widgets.activity_progress_bar import ActivityProgressBar
from cooling_tower.gui.widgets.info_tool_button import InfoToolButton
from cooling_tower.gui.widgets.numeric_setting import NumericSettingWidget
from cooling_tower.gui.widgets.preview_canvas import PreviewCanvas
from cooling_tower.gui.widgets.responsive_card_grid import ResponsiveCardGrid
from cooling_tower.gui.widgets.resizable_preview_columns import ResizablePreviewColumns
from cooling_tower.gui.widgets.section_card import SectionCard
from cooling_tower.gui.widgets.wheel_safe_inputs import WheelSafeDoubleSpinBox, WheelSafeSpinBox
from cooling_tower.preprocessor import PreprocessorSettings
from cooling_tower.preprocessor_profiles import resolve_profile_settings, printhead_envelope
from cooling_tower.calibration.gcode_integration import parse_bed_geometry
from cooling_tower.gui.widgets.preprocessor_time_chart import PreprocessorTimeChart


AUTOMATIC_FIELDS = {
    "automatic_target_time": ("target_layer_time_s",),
    "automatic_retraction": ("retract_mm", "retract_speed_mm_s"),
    "automatic_print_speed": ("print_speed_mm_s",),
    "automatic_travel_speed": ("travel_speed_mm_s",),
    "automatic_height": ("height_mm",),
    "automatic_diameter": ("diameter_mm",),
    "automatic_base": ("base_width_mm",),
    "automatic_position": ("center_x_mm", "center_y_mm"),
    "automatic_wait_position": ("wait_x_mm", "wait_y_mm"),
}
VIEW_DEFAULTS = {"show_wait_position": True, "show_wait_travel": False, "show_tower_travel": False, "show_clearance": False}
PROFILE_FIELDS = {name for flag in ("automatic_target_time", "automatic_retraction", "automatic_print_speed", "automatic_travel_speed")
    for name in AUTOMATIC_FIELDS[flag]}

HINTS = {
    "show_clearance": ("Zeigt die verwendete Druckkopf-Freihülle am Warteplatz und am Turm-Anfahrpunkt der gewählten Schicht.",
        "Blau gestrichelt: Profilabstände. Gelb gestrichelt: geschätzte Ersatzhülle. Das ist keine vermessene Maschinengeometrie; bei allen Schichten wird die letzte Turmschicht dargestellt."),
    "target_layer_time_s": ("Jede Schicht soll mindestens diese Zeit erreichen.",
        "Automatisch gilt die aktive Kühlungsvorgabe des bestätigten Filamentprofils; fehlt sie, bleibt der Ersatzwert sichtbar. Fahrten, Turmdruck und Primen zählen mit."),
    "height_mm": ("Automatisch reicht der Turm bis zur letzten Originalschicht mit Zeitdefizit.",
        "Manuelle Höhen werden auf vorhandene Schichten abgerundet. Ein zu kurzer Turm sperrt den Export."),
    "diameter_mm": ("Bestimmt die Breite des hohlen Turmschafts.",
        "Dies ist der Außendurchmesser. Der Innendurchmesser ergibt sich aus Profil-Linienbreiten, Schichthöhe und Wandlinienzahl."),
    "base_width_mm": ("Der breitere Standfuß verbessert Haftung und Stabilität.",
        "Automatisch berücksichtigt er Turmhöhe und Schaftbreite. Die konkave Form entspricht der Automatik bei 100 % Füllung; der gekrümmte Fuß wird zur sicheren Unterstützung gefüllt."),
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
        "Automatisch gilt das äußere Wandtempo des Profils. Bekannte Material-Volumenströme begrenzen auch manuelle Werte; die zusätzliche Prime-Menge ist eingerechnet."),
    "travel_speed_mm_s": ("Geschwindigkeit der zusätzlichen Fahrten ohne Materialablage.",
        "Automatisch gilt das Profil-Fahrtempo, begrenzt durch bekannte X-/Y-Maschinengrenzen. Die Fahrzeiten zählen zur Mindest-Schichtzeit."),
    "retract_mm": ("Zusätzlicher Filamentrückzug vor Parken und Rückfahrt.",
        "Automatisch werden Länge und Tempo des aktiven Extruders aus dem bestätigten Profil übernommen, einschließlich gültiger Filamentüberschreibungen."),
    "retract_speed_mm_s": ("Geschwindigkeit für zusätzlichen Rückzug und dessen Ausgleich.",
        "Die Automatik ist mit der Rückzugslänge gekoppelt. Ohne deren Automatik sind beide Werte manuell einstellbar."),
    "z_hop_mm": ("Vor zusätzlichen Fahrten hebt die Düse senkrecht an und senkt erst am Ziel wieder ab.",
        "Es gilt mindestens der Z-Hop des gewählten Profils. Originale Z-Bewegungen bleiben erhalten; die maximale Druckhöhe darf nicht überschritten werden."),
    "prime_mm": ("Zusätzlich gefördertes Filament am Turm nach dem Warten.",
        "Diese Menge wird während der ersten Wandumrundung verteilt. Der Startpunkt wandert mit jeder Schicht; bekannte Volumenstromgrenzen bleiben eingehalten."),
    "wall_count": ("Anzahl der gedruckten Wandlinien des hohlen Turms.",
        "1 bis 3 Linien, Standard 2. Die Wandstärke folgt aus den äußeren/inneren Profil-Linienbreiten und ihrer schichthöhenabhängigen Überlappung."),
    "hollow_tower": ("Standard ist ein hohler Schaft mit gefülltem konkavem Fuß und mindestens zwei geschlossenen Bodenlagen.",
        "Ohne Hohlbauweise wird auch der Turmkörper gefüllt. Die nötige Restzeit entsteht weiterhin durch Warten."),
    "show_wait_position": ("Zeigt den freien Warteplatz als gelbe Markierung an.",
        "Die Markierung bleibt unabhängig von den Fahrwegen sichtbar. Dieser Schalter ändert nur die Ansicht."),
    "show_wait_travel": ("Zeigt die Fahrten vom Modell zum Warteplatz und weiter zum Turm violett an, einschließlich der Sicherheitshübe.",
        "Standardmäßig ausgeblendet. Der erzeugte G-Code bleibt unabhängig von der Anzeige gleich."),
    "show_tower_travel": ("Zeigt die Rückfahrt vom Turm zum Modell sowie zugehörige lokale Turmfahrten und Z-Hops rosa an.",
        "Standardmäßig ausgeblendet. Warteplatzfahrten und Warteposition lassen sich getrennt einblenden."),
}


def setting_hint(label, name):
    bullets = "<br>".join("&#8226; " + escape(text) for text in HINTS[name])
    return (f'<p align="left" style="margin-top:0; margin-bottom:0px;"><b>{escape(label)}</b></p>'
        f'<p style="margin-top:0; margin-bottom:10px;">{bullets}</p>')


class PreprocessorValueSpinBox(WheelSafeDoubleSpinBox):
    """Show calculated values without changing the valid manual input range."""

    _automatic_text: str | None = None

    def textFromValue(self, value):  # noqa: N802
        return self._automatic_text if self._automatic_text is not None else super().textFromValue(value)

    def show_automatic_value(self, enabled: bool, value: float | None = None):
        self._automatic_text = ("—" if value is None else self.locale().toString(float(value), "f", self.decimals())) if enabled else None
        self.lineEdit().setText(self.textFromValue(self.value()))
        self.setToolTip("Automatischer Wert steht nach der Erzeugung von G-Code und Vorschau fest."
            if enabled and value is None else "")


class PreprocessorPanel(QWidget):
    changed = Signal()
    layout_changed = Signal()

    def __init__(self):
        super().__init__()
        self.setObjectName("preprocessorPanel")
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        layout.setAlignment(Qt.AlignmentFlag.AlignTop)
        self.error_label = QLabel()
        self.error_label.setWordWrap(True)
        self.error_label.setObjectName("errorLabel")
        self.error_label.hide()
        layout.addWidget(self.error_label)
        self._layout_timer = QTimer(self)
        self._layout_timer.setSingleShot(True)
        self._layout_timer.timeout.connect(self.refresh_layout)
        left = QWidget()
        self.settings_column = left
        left_layout = QVBoxLayout(left)
        left_layout.setContentsMargins(0, 0, 0, 0)
        left_layout.setSpacing(0)
        left_layout.setAlignment(Qt.AlignmentFlag.AlignTop)
        self.input_group = SectionCard("Präprozessor-Einstellungen")
        left_layout.addWidget(self.input_group)
        self.inputs, self.automatic, self.rows = {}, {}, {}
        self._automatic_values: dict[str, float | None] = {}
        self._profile_values = {name: getattr(PreprocessorSettings(), name) for name in PROFILE_FIELDS}
        self._profile_safety_note = ""
        self._profile_safety_estimated = False
        self.exclusions = ()
        self.reset_buttons, self.info_buttons = {}, {}
        for name, label, unit, low, high, automatic in (
            ("target_layer_time_s", "Mindest-Schichtzeit", "s", .1, 3600, "automatic_target_time"),
            ("height_mm", "Turmhöhe", "mm", .01, 1000, "automatic_height"),
            ("diameter_mm", "Außendurchmesser", "mm", 3, 100, "automatic_diameter"),
            ("base_width_mm", "Standfußbreite", "mm", 3, 150, "automatic_base"),
            ("center_x_mm", "Turmmitte X", "mm", -2000, 2000, "automatic_position"),
            ("center_y_mm", "Turmmitte Y", "mm", -2000, 2000, None),
            ("clearance_mm", "Modellabstand", "mm", 5, 100, None),
            ("wait_x_mm", "Warteposition X", "mm", -2000, 2000, "automatic_wait_position"),
            ("wait_y_mm", "Warteposition Y", "mm", -2000, 2000, None),
        ):
            self._numeric(self.input_group.content_layout, name, label, unit, low, high, automatic)
        self.exclusions_button = QPushButton("Eigene Sperrflächen bearbeiten …")
        self.input_group.content_layout.addWidget(self.exclusions_button)
        self.profile_hint = QLabel()
        self.profile_hint.setWordWrap(True)
        self.profile_hint.setObjectName("helpText")
        self.input_group.content_layout.addWidget(self.profile_hint)
        self.advanced_group = SectionCard("Erweiterte Einstellungen anzeigen", collapsible=True, expanded=False)
        self.advanced_toggle = self.advanced_group.header
        self.advanced_group.toggled.connect(lambda opened: self.advanced_group.setTitle(
            "Erweiterte Einstellungen ausblenden" if opened else "Erweiterte Einstellungen anzeigen"))
        self.advanced_group.toggled.connect(lambda _: self._layout_timer.start(0))
        left_layout.addWidget(self.advanced_group)
        self.hollow_checkbox = QCheckBox("Hohler Turm")
        self.hollow_checkbox.setChecked(True)
        self.advanced_group.content_layout.addWidget(self._check_row("hollow_tower", self.hollow_checkbox, True))
        self._numeric(self.advanced_group.content_layout, "wall_count", "Wandlinien", "", 1, 3, integer=True)
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
            automatic = {"print_speed_mm_s": "automatic_print_speed", "travel_speed_mm_s": "automatic_travel_speed",
                "retract_mm": "automatic_retraction"}.get(name)
            self._numeric(self.advanced_group.content_layout, name, label, unit, low, high, automatic)
        self.preview_group = SectionCard("G-Code-Vorschau")
        for card in (self.input_group, self.advanced_group, self.preview_group):
            card.setProperty("outerDropdown", True)
            card.setProperty("edgeAttached", True)
        self.columns = ResizablePreviewColumns(left, self.preview_group)
        self.columns.layout_changed.connect(lambda: self._layout_timer.start(0))
        layout.addWidget(self.columns)
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
        legend = QLabel("Türkis: Modell · Orange: Turm · Gelb: Warteposition.\n"
            "Violett: Fahrten zum/vom Warteplatz · Rosa: Modell-/Turmfahrwege.\n"
            "Freihüllen gestrichelt: Blau aus Profilwerten, Gelb geschätzt.\n"
            "Die Koordinaten und Bettform entsprechen dem Pre-Slice und dem gewählten Druckprofil.")
        legend.setWordWrap(True)
        legend.setObjectName("helpText")
        self.preview_group.content_layout.addWidget(legend)
        self.view_checkboxes = {}
        for name, label, action in (
            ("show_wait_position", "Warteposition anzeigen", self.canvas.set_wait_position_visible),
            ("show_wait_travel", "Fahrwege zum/vom Warteplatz anzeigen", self.canvas.set_wait_travel_visible),
            ("show_tower_travel", "Fahrwege Modell ↔ Turm anzeigen", self.canvas.set_tower_travel_visible),
            ("show_clearance", "Druckkopf-Freihüllen anzeigen", self.canvas.set_clearance_visible),
        ):
            checkbox = QCheckBox(label)
            checkbox.setChecked(VIEW_DEFAULTS[name])
            self.view_checkboxes[name] = checkbox
            self.preview_group.content_layout.addWidget(self._check_row(name, checkbox, VIEW_DEFAULTS[name], view_action=action))
            action(VIEW_DEFAULTS[name])
        self.summary = QLabel("Einstellungen wählen und G-Code und Vorschau erzeugen.")
        self.summary.setWordWrap(True)
        self.safety_hint = QLabel()
        self.safety_hint.setWordWrap(True)
        self.safety_hint.setTextFormat(Qt.TextFormat.PlainText)
        self.preview_group.content_layout.addWidget(self.safety_hint)
        self.time_chart = PreprocessorTimeChart()
        self.preview_group.content_layout.addWidget(self.time_chart)
        self.time_legend = QLabel("Türkis: Original · Orange: zusätzliche Bewegung · Violett: Restwartezeit · Grün: Zielzeit")
        self.time_legend.setWordWrap(True)
        self.preview_group.content_layout.addWidget(self.time_legend)
        self.layer_slider = QSlider(Qt.Orientation.Horizontal)
        self.layer_slider.setAccessibleName("Vorschau-Schicht auswählen")
        self.layer_slider.setRange(1, 1)
        self.layer_spin = WheelSafeSpinBox()
        self.layer_spin.setRange(1, 1)
        self.layer_spin.setAccessibleName("Vorschau-Schichtnummer")
        self.all_layers = QCheckBox("Alle Schichten anzeigen")
        self.all_layers.setChecked(True)
        layer_row = QHBoxLayout()
        layer_row.addWidget(self.layer_slider, 1)
        layer_row.addWidget(self.layer_spin)
        layer_row.addWidget(self.all_layers)
        self.preview_group.content_layout.addLayout(layer_row)
        self.layer_details = QLabel()
        self.layer_details.setWordWrap(True)
        self.preview_group.content_layout.addWidget(self.layer_details)
        self._timing_result = None
        self.time_chart.layer_selected.connect(self.select_layer)
        self.layer_spin.valueChanged.connect(self.select_layer)
        self.layer_slider.valueChanged.connect(self.select_layer)
        self.all_layers.toggled.connect(self._apply_layer_view)
        self.clear_timing()
        self.preview_group.content_layout.addWidget(self.summary)
        self._build_footer()
        self._sync_automatic()
        self.wall_count_spin.setEnabled(self.hollow_checkbox.isChecked())
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
        for row in self.rows.values():
            row.label.setMinimumWidth(max(150, row.label.fontMetrics().horizontalAdvance(row.label.text()) + 2))
        for card in (self.input_group, self.advanced_group, self.preview_group):
            card.content_layout.invalidate()
            card.layout().invalidate()
        self.settings_column.layout().invalidate()
        self.columns.setMinimumHeight(0)
        self.columns.setMaximumHeight(16777215)
        self.columns.refresh_layout()
        for _ in range(3):
            self.columns.layout().activate()
            self.columns.splitter.refresh()
            self.canvas.setFixedHeight(max(280, round(self.canvas.width() * .65)))
            self.preview_group.setMinimumHeight(0)
            self.preview_group.content_layout.invalidate()
            self.preview_group.layout().invalidate()
            self.preview_group.setMinimumHeight(ResponsiveCardGrid._height_for_width(
                self.preview_group, self.preview_group.width()))
            required = self.columns.content_height_hint()
            self.columns.setFixedHeight(required)
            self.columns.layout().activate()
            self.columns.splitter.refresh()
            if required == self.columns.content_height_hint():
                break
        self.updateGeometry()
        self.layout_changed.emit()

    def _numeric(self, layout, name, label, unit, low, high, automatic=None, *, integer=False):
        defaults = PreprocessorSettings()
        spin = WheelSafeSpinBox() if integer else PreprocessorValueSpinBox()
        spin.setRange(low, high)
        if not integer:
            spin.setDecimals(2)
        spin.setValue(getattr(defaults, name))
        self.inputs[name] = spin
        row = NumericSettingWidget(setting_name=name, label=label, editor=spin,
            default_provider=lambda: getattr(defaults, name), unit=unit, info_text=setting_hint(label, name))
        row.label.setWordWrap(False)
        self.rows[name] = row
        self.reset_buttons[name], self.info_buttons[name] = row.reset_button, row.info_button
        row.reset_button.clicked.disconnect()
        row.reset_button.clicked.connect(lambda: self.reset_field(name))
        if automatic:
            checkbox = QCheckBox()
            checkbox.setChecked(True)
            checkbox.setAccessibleName(label + " automatisch berechnen")
            self.automatic[automatic] = checkbox
            grid = row.layout()
            for widget in (spin, row.reset_button, row.range_label, row.message_container):
                grid.removeWidget(widget)
            automatic_label = QLabel("Automatisch")
            automatic_label.setBuddy(checkbox)
            grid.addWidget(automatic_label, 0, 2, Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
            grid.addWidget(checkbox, 0, 3, Qt.AlignmentFlag.AlignVCenter)
            grid.addWidget(spin, 0, 4, Qt.AlignmentFlag.AlignVCenter)
            grid.addWidget(row.reset_button, 0, 5, Qt.AlignmentFlag.AlignVCenter)
            grid.addWidget(row.range_label, 1, 4, Qt.AlignmentFlag.AlignRight)
            grid.addWidget(row.message_container, 2, 0, 1, 6)
            checkbox.toggled.connect(self._changed)
        spin.valueChanged.connect(self._changed)
        layout.addWidget(row)

    def _check_row(self, name, checkbox, default, *, view_action=None):
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
        if name == "hollow_tower":
            label = QLabel(checkbox.text())
            label.setBuddy(checkbox)
            checkbox.setAccessibleName(checkbox.text())
            checkbox.setText("")
            layout.addWidget(label)
            layout.addWidget(checkbox)
            layout.addStretch(1)
        else:
            layout.addWidget(checkbox, 1)
        layout.addWidget(reset)
        self.reset_buttons[name], self.info_buttons[name] = reset, info
        checkbox.toggled.connect(view_action or self._changed)
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
        self.export_actions = QWidget()
        export_actions = QHBoxLayout(self.export_actions)
        export_actions.setContentsMargins(0, 0, 0, 0)
        export_actions.setSpacing(8)
        export_actions.addStretch(1)
        self.open_output_button = QPushButton("Alle Exporte öffnen")
        self.open_output_button.setObjectName("openBaseOutputFolderButton")
        self.open_last_button = QPushButton("Letzten Export öffnen")
        self.open_last_button.setObjectName("openOutputFolderButton")
        self.open_report_button = QPushButton("Letzten Exportbericht öffnen")
        self.open_report_button.setObjectName("openExportReportButton")
        for button in (self.open_output_button, self.open_last_button, self.open_report_button):
            button.setSizePolicy(QSizePolicy.Policy.Minimum, QSizePolicy.Policy.Fixed)
            export_actions.addWidget(button)
        actions_column.addWidget(self.export_actions)
        self.export_actions.hide()
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
            hollow_tower=self.hollow_checkbox.isChecked(), wall_count=self.wall_count_spin.value(), exclusions=self.exclusions)

    def set_profile_values(self, values):
        profile_error = None
        try:
            effective, notes = resolve_profile_settings(PreprocessorSettings(), values)
        except ValueError as error:
            effective, notes, profile_error = PreprocessorSettings(), (str(error),), str(error)
        self._profile_values = {name: getattr(effective, name) for name in PROFILE_FIELDS}
        for name in PROFILE_FIELDS:
            self._automatic_values.pop(name, None)
        for flag, names in AUTOMATIC_FIELDS.items():
            if self.automatic[flag].isChecked():
                for name in names:
                    if name in PROFILE_FIELDS:
                        with QSignalBlocker(self.inputs[name]):
                            self.inputs[name].setValue(self._profile_values[name])
        self.profile_hint.setText(profile_error or "Profilvorgaben werden automatisch übernommen; eigene Werte sind über die jeweilige Automatik wählbar.")
        self.profile_hint.setToolTip("\n".join(notes))
        geometry = parse_bed_geometry(values)
        if geometry is not None:
            head = printhead_envelope(values, geometry)
            self._profile_safety_note, self._profile_safety_estimated = head.note, head.estimated
            self.safety_hint.setText(head.note)
            self.safety_hint.setStyleSheet("color: #8a4b08;" if head.estimated else "color: #526b7e;")
        else:
            self._profile_safety_note = "Für diese Quelle fehlt eine bestätigte Druckbettgeometrie."
            self._profile_safety_estimated = True
            self.safety_hint.setText(self._profile_safety_note)
            self.safety_hint.setStyleSheet("color: #8a4b08;")
        self._sync_automatic()

    def clear_timing(self):
        self._timing_result = None
        self.time_chart.set_data()
        for widget in (self.layer_spin, self.layer_slider, self.all_layers):
            widget.setEnabled(False)
        self.layer_details.clear()
        self.safety_hint.setText(self._profile_safety_note)
        self.safety_hint.setStyleSheet("color: #8a4b08;" if self._profile_safety_estimated else "color: #526b7e;")
        self.canvas.set_layer_height(None)

    def show_timing(self, result):
        self._timing_result = result
        self.time_chart.set_data(result.original_layer_times_s, result.added_motion_times_s, result.layer_waits_s,
            result.layer_heights_mm, result.effective_settings.target_layer_time_s)
        for widget in (self.layer_spin, self.layer_slider):
            with QSignalBlocker(widget):
                widget.setRange(1, len(result.layer_times_s))
                widget.setValue(1)
            widget.setEnabled(True)
        self.all_layers.setEnabled(True)
        self.all_layers.setChecked(True)
        self.safety_hint.setText("\n".join((result.printhead.note, *result.collision_notes[1:2])))
        self.safety_hint.setToolTip("\n".join(result.collision_notes))
        self.safety_hint.setStyleSheet("color: #8a4b08;" if result.printhead.estimated else "color: #526b7e;")
        self._update_layer_details(1)
        self._apply_layer_view()

    def select_layer(self, layer):
        if self._timing_result is None:
            return
        layer = max(1, min(len(self._timing_result.layer_times_s), int(layer)))
        for widget in (self.layer_slider, self.layer_spin):
            with QSignalBlocker(widget):
                widget.setValue(layer)
        self.time_chart.select_layer(layer)
        self.all_layers.setChecked(False)
        self._update_layer_details(layer)
        self._apply_layer_view()

    def _update_layer_details(self, layer):
        r, i = self._timing_result, layer - 1
        self.layer_details.setText(f"Schicht {layer} · Z {r.layer_heights_mm[i]:.2f} mm · Original {r.original_layer_times_s[i]:.2f} s · "
            f"Bewegung zusätzlich {r.added_motion_times_s[i]:.2f} s · Warten {r.layer_waits_s[i]:.2f} s · Gesamt {r.layer_times_s[i]:.2f} s")

    def _apply_layer_view(self, *_):
        result = self._timing_result
        self.canvas.set_layer_height(None if result is None or self.all_layers.isChecked()
            else result.layer_heights_mm[self.layer_spin.value() - 1])

    def top_view(self):
        self.canvas.apply_camera_state({**self.canvas.camera_state(), "yaw_deg": 0, "pitch_deg": -89})
        self.canvas.fit_objects()

    def three_quarter_view(self):
        self.canvas.apply_camera_state({**self.canvas.camera_state(), "yaw_deg": -38, "pitch_deg": -28})
        self.canvas.fit_objects()

    def _sync_automatic(self):
        for flag, names in AUTOMATIC_FIELDS.items():
            for name in names:
                automatic = self.automatic[flag].isChecked()
                value = self._automatic_values.get(name, self._profile_values.get(name))
                if automatic and value is not None:
                    with QSignalBlocker(self.inputs[name]):
                        self.inputs[name].setValue(value)
                self.inputs[name].show_automatic_value(automatic, value)
                self.inputs[name].setEnabled(not automatic)
        for flag, x, y, title in (("automatic_position", "center_x_mm", "center_y_mm", "Turmposition"),
                ("automatic_wait_position", "wait_x_mm", "wait_y_mm", "Warteposition")):
            automatic = self.automatic[flag].isChecked()
            self.rows[x].label.setText(title if automatic else ("Turmmitte X" if x == "center_x_mm" else "Warteposition X"))
            self.inputs[x].setVisible(not automatic)
            self.rows[y].setVisible(not automatic)
            self.rows[x].range_label.setVisible(not automatic)

    def show_automatic_values(self, values: dict[str, float | None]):
        self._automatic_values = dict(values)
        for flag, names in AUTOMATIC_FIELDS.items():
            if self.automatic[flag].isChecked():
                for name in names:
                    value = values.get(name)
                    if value is not None:
                        with QSignalBlocker(self.inputs[name]):
                            self.inputs[name].setValue(value)
        self._sync_automatic()

    def clear_automatic_values(self):
        self._automatic_values.clear()
        self._sync_automatic()

    def _changed(self, *_):
        self._sync_automatic()
        self.wall_count_spin.setEnabled(self.hollow_checkbox.isChecked())
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
            elif name in VIEW_DEFAULTS:
                modified = self.view_checkboxes[name].isChecked() != VIEW_DEFAULTS[name]
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
        for name, checkbox in self.view_checkboxes.items():
            checkbox.setChecked(VIEW_DEFAULTS[name])
        self.exclusions = ()
        self.exclusions_button.setText("Eigene Sperrflächen bearbeiten …")
        self._changed()
