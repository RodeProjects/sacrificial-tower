"""Postprocessor controls using the application's shared settings and card design."""
from __future__ import annotations

from html import escape
from pathlib import Path

from PySide6.QtCore import QEasingCurve, QEvent, QSignalBlocker, QSize, QTimer, Qt, QVariantAnimation, Signal
from PySide6.QtGui import QIcon
from PySide6.QtWidgets import (
    QBoxLayout, QCheckBox, QFrame, QGridLayout, QHBoxLayout, QLabel, QPushButton, QScrollArea, QSizePolicy, QStyle,
    QStyleOptionSpinBox, QVBoxLayout, QWidget,
)

from cooling_tower.gui.design_tokens import METRICS
from cooling_tower.gui.widgets.activity_progress_bar import ActivityProgressBar
from cooling_tower.gui.widgets.footer_actions import fit_footer_actions
from cooling_tower.gui.widgets.info_tool_button import InfoToolButton
from cooling_tower.gui.widgets.numeric_setting import NumericSettingWidget
from cooling_tower.gui.widgets.preview_canvas import PreviewCanvas
from cooling_tower.gui.widgets.responsive_card_grid import ResponsiveCardGrid
from cooling_tower.gui.widgets.resizable_preview_columns import ResizablePreviewColumns
from cooling_tower.gui.widgets.section_card import SectionCard
from cooling_tower.gui.widgets.committed_numeric_inputs import CommittedDoubleSpinBox, CommittedSpinBox
from cooling_tower.postprocessor import PostprocessorSettings
from cooling_tower.postprocessor_profiles import resolve_profile_settings, printhead_envelope
from cooling_tower.calibration.gcode_integration import parse_bed_geometry
from cooling_tower.gui.widgets.postprocessor_time_chart import PostprocessorTimeChart
from cooling_tower.gui.widgets.postprocessor_widgets import ColourLegend, FlowColourLegend, LayerNumberSpinBox, PostprocessorFooter
from cooling_tower.gui.widgets.travel_mode_toggle import TravelModeToggle


AUTOMATIC_FIELDS = {
    "automatic_target_time": ("target_layer_time_s",),
    "automatic_retraction": ("retract_mm", "retract_speed_mm_s"),
    "automatic_z_hop": ("z_hop_mm",),
    "automatic_prime": ("prime_mm",),
    "automatic_print_speed": ("print_speed_mm_s",),
    "automatic_travel_speed": ("travel_speed_mm_s",),
    "automatic_height": ("height_mm",),
    "automatic_diameter": ("diameter_mm",),
    "automatic_base": ("base_width_mm",),
    "automatic_tower_brim_width": ("tower_brim_width_mm",),
    "automatic_tower_brim_gap": ("tower_brim_gap_mm",),
    "automatic_position": ("center_x_mm", "center_y_mm"),
    "automatic_wait_position": ("wait_x_mm", "wait_y_mm"),
}
PROFILE_FIELDS = {name for flag in ("automatic_target_time", "automatic_retraction", "automatic_print_speed", "automatic_travel_speed", "automatic_z_hop",
    "automatic_tower_brim_width", "automatic_tower_brim_gap")
    for name in AUTOMATIC_FIELDS[flag]}

HINTS = {
    "target_layer_time_s": ("Jede Modellschicht vor der letzten soll mindestens die eingestellte Mindest-Layerzeit erreichen. Nach der letzten Schicht folgt direkt die Abschlussfahrt.",
        "Standard sind manuelle 10 Sekunden. Bei aktivierter Automatik gilt die Kühlungsvorgabe des bestätigten Filamentprofils; fehlt sie, bleibt der Ersatzwert sichtbar. Fahrten, Turmdruck und Primen zählen zur Layerzeit mit."),
    "logarithmic_time_scale": ("Stellt kurze und lange Layerzeiten gemeinsam lesbar dar. Gleiche Abstände entsprechen dabei Zeitverhältnissen statt gleichen Zeitunterschieden.",
        "Abschalten zeigt eine lineare Zeitskala. Die berechneten Zeiten, Layerauswahl und der G-Code bleiben unverändert."),
    "normalize_time_scale": ("Layer 1 bleibt mit seiner vollständigen Zeit in Berechnung, Layerauswahl und Zeitangabe erhalten, erhält im Diagramm aber keinen Farbbalken.",
        "Die Zeitskala richtet sich nach den übrigen Layern und der Mindest-Layerzeit. So drückt eine lange erste Schicht die übrigen Balken nicht zusammen.",
        "Zu Beginn aktiviert, wenn Layer 1 allein die längste Gesamtzeit hat. Die Option ändert weder G-Code noch berechnete Zeiten."),
    "height_mm": ("Automatisch wird der Turm nur bis zur letzten kühlungsrelevanten Schicht mit Layerzeitdefizit erzeugt. Die letzte Modellschicht erhält keinen Turmdruck und keine zusätzliche Pause. Sobald alle folgenden Schichten die Mindest-Layerzeit ohne Turm erreichen, endet er.",
        "Manuelle Höhen werden auf vorhandene Schichten abgerundet. Ein zu kurzer Turm sperrt den Export."),
    "diameter_mm": ("Bestimmt die Breite des hohlen Turmschafts.",
        "Automatisch mindestens 12 mm, vergrößert nach dem größten späteren Layerzeitdefizit und der Turmhöhe. Die flache geschlossene Kapsel hat eine breite gerade Fangseite und einen zweibahnigen Mittelsteg mit Rückbahn zur Modellseite. Ein kurzer Mittelsteg stabilisiert die Seiten. Der Schaft wird von unten für den späteren Bedarf aufgebaut; er wächst nicht ungestützt erst an einer langen Pause."),
    "base_width_mm": ("Der breitere Standfuß verbessert Haftung und Stabilität.",
        "Die Breite ist der Außendurchmesser ohne Brim. Automatisch berücksichtigt sie Turmhöhe und Schaftbreite. Die ersten beiden geschlossenen Bodenplatten erhalten automatisch die frühere Flächenreserve im Verhältnis zum Schaft. Ab der dritten Schicht bleibt die sparsamere konkave Fußflanke bestehen. Die manuelle Breite bestimmt direkt die Fußkurve."),
    "tower_brim_width_mm": ("Ein eigener Brim verbessert die Haftung des Turms. Die Brim-Art und Brimbreite des Modellprofils werden dafür nicht übernommen.",
        "Automatisch beträgt die Breite 2 mm pro Seite; manuell sind 0 bis 20 mm möglich. 0 mm deaktiviert den Turm-Brim. Die Runden ergeben sich aus der Profil-Linienbreite für Brims, begrenzt auf die gewählte Brimbreite. Brim und Abstand zählen zusätzlich zur Standfußbreite."),
    "tower_brim_gap_mm": ("Abstand zwischen Turmfuß und eigenem Turm-Brim.",
        "Automatisch gilt der Brimabstand des bestätigten Profils, ersatzweise 0,2 mm. Manuell sind 0,1 bis 1 mm möglich. Der Modell-Brim bleibt unverändert."),
    "positions": ("Die Automatik platziert den Turm möglichst zwischen Modell und Warteplatz. Die Einfangseite bleibt dem Warteplatz zugewandt; die Rückbahn des Mittelstegs endet auf der Modellseite. Dort erfolgt sofort der Rückzug, dann eine kleine Höhenentlastung und ein einmaliger Abziehzug über die Wand. Erst außerhalb folgt der restliche Z-Hop; die frische Bahn wird nicht hin und her abgerieben.",
        "Ohne Automatik öffnet Positionen bearbeiten die Draufsicht: Turm und Wartepunkt lassen sich ziehen oder über X/Y eingeben. Nur gültige Positionen können übernommen werden; am Warteplatz wartet die angehobene Düse die fehlende Schichtzeit ab. Erreicht die Originalschicht allein die Mindest-Layerzeit, fährt die Düse direkt zum Turm."),
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
        "Die Düse darf während der Pause über keinem der beiden Objekte stehen. Auf dem Hinweg wird die vollständige Turmfläche einschließlich Fuß und Brim mit mindestens 2 mm Reserve umfahren."),
    "print_speed_mm_s": ("Geschwindigkeit der zusätzlich gedruckten Turmbahnen.",
        "Die Automatik verwendet das äußere Profil-Wandtempo mit einer Obergrenze von 35 mm/s für kontrollierte Ablage. Bekannte Material-Volumenströme begrenzen auch manuelle Werte; die zusätzliche Prime-Menge ist eingerechnet."),
    "travel_speed_mm_s": ("Geschwindigkeit der zusätzlichen Fahrten ohne Materialablage.",
        "Automatisch gilt das Profil-Fahrtempo, begrenzt durch bekannte X-/Y-Maschinengrenzen. Die Fahrzeiten zählen zur Mindest-Layerzeit."),
    "retract_mm": ("Zusätzlicher Filamentrückzug vor Parken und Rückfahrt.",
        "Automatisch werden Länge und Tempo des aktiven Extruders aus dem bestätigten Profil übernommen, einschließlich gültiger Filamentüberschreibungen."),
    "retract_speed_mm_s": ("Geschwindigkeit für zusätzlichen Rückzug und dessen Ausgleich.",
        "Die Automatik ist mit der Rückzugslänge gekoppelt. Ohne deren Automatik sind beide Werte manuell einstellbar."),
    "z_hop_mm": ("Vor zusätzlichen Fahrten hebt die Düse um den eingestellten Z-Hop an und senkt erst am Ziel wieder ab.",
        "Auto übernimmt den aktivierten Z-Hop des bestätigten Profils, ersatzweise 0,20 mm. Ohne Auto ist der Wert manuell einstellbar; 0,00 mm deaktiviert den zusätzlichen Hub. Der Hub gilt auch für die Abschlussfahrt zur Warteposition; die maximale Druckhöhe darf nicht überschritten werden."),
    "prime_mm": ("Obergrenze für zusätzliches Filament nach einer tatsächlichen Wartepause. Ohne Pause gibt es keine zusätzliche Prime-Menge.",
        "Auto ist standardmäßig aktiv und berechnet die Obergrenze aus Schaftgröße, Profil-Linienbreiten, Schichthöhen und Zeitreserve. Ohne Auto gilt die manuelle Obergrenze. In beiden Fällen wird nach der tatsächlichen Pausendauer mit höchstens 0,02 mm Filament je Sekunde und maximal 15 % der ersten Außenrunde dosiert. Diese Reserve ist kein gemessener Materialverlust; Volumenstrom und Wartezeit werden gemeinsam berechnet."),
    "wall_count": ("Anzahl der gedruckten Wandlinien des hohlen Turms.",
        "1 bis 3 Linien, Standard 2. Die Wandstärke folgt aus den äußeren/inneren Profil-Linienbreiten und ihrer schichthöhenabhängigen Überlappung."),
    "hollow_tower": ("Standard ist eine flache geschlossene Kapsel mit gerader Fangseite, offenen Fangkammern, einem zweibahnigen Mittelsteg und einem getrennten Abziehweg zur Modellseite. Die massive Wand des konkaven Fußes wird unterstützt nach oben dünner; zwei Bodenlagen schließen den Fuß.",
        "Der ankommende Faden wird zuerst auf der Warteplatzseite aufgenommen und in der ersten Kammer seitlich gezogen. Die Kontaktstelle wechselt links/rechts von außen zur Mitte, statt immer dieselbe Stelle zu belasten. Die Anzahl der Stellen folgt der verfügbaren Breite und Linienbreite; das ist keine Garantie für eine wieder freie Kante. Ohne Hohlbauweise wird der Turmkörper gefüllt."),
}


def setting_hint(label, name):
    bullets = "<br>".join("&#8226; " + escape(text) for text in HINTS[name])
    return (f'<p align="left" style="margin-top:0; margin-bottom:0px;"><b>{escape(label)}</b></p>'
        f'<p style="margin-top:0; margin-bottom:10px;">{bullets}</p>')


class PostprocessorValueSpinBox(CommittedDoubleSpinBox):
    """Show calculated values without changing the valid manual input range."""

    _automatic_text: str | None = None
    fixed_decimals = False

    def textFromValue(self, value):  # noqa: N802
        if self._automatic_text is None and self.fixed_decimals:
            return self.locale().toString(float(value), "f", self.decimals())
        return self._automatic_text if self._automatic_text is not None else super().textFromValue(value)

    def show_automatic_value(self, enabled: bool, value: float | None = None):
        previous = self._automatic_text
        self._automatic_text = ("—" if value is None else self.locale().toString(float(value), "f", self.decimals())) if enabled else None
        if previous != self._automatic_text:
            self.lineEdit().setText(self.textFromValue(self.value()))
        self.setToolTip("Automatischer Wert steht nach der Erzeugung von G-Code und Vorschau fest."
            if enabled and value is None else "")


class PostprocessorPanel(QWidget):
    TRAVEL_REVEAL_DURATION_MS = 240

    changed = Signal()
    layout_changed = Signal()

    def __init__(self):
        super().__init__()
        self.setObjectName("postprocessorPanel")
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
        self._layer_view_timer = QTimer(self)
        self._layer_view_timer.setSingleShot(True)
        self._layer_view_timer.setInterval(33)
        self._layer_view_timer.timeout.connect(self._apply_layer_view)
        self._preview_viewport = None
        self._navigation_columns = None
        self._navigation_before_stack = True
        left = QWidget()
        self.settings_column = left
        left_layout = QVBoxLayout(left)
        left_layout.setContentsMargins(0, 0, 0, 0)
        left_layout.setSpacing(0)
        left_layout.setAlignment(Qt.AlignmentFlag.AlignTop)
        self.input_group = SectionCard("Postprozessor-Einstellungen")
        left_layout.addWidget(self.input_group)
        self.inputs, self.automatic, self.rows = {}, {}, {}
        self._automatic_values: dict[str, float | None] = {}
        self._profile_values = {name: getattr(PostprocessorSettings(), name) for name in PROFILE_FIELDS}
        self._profile_safety_note = ""
        self._profile_safety_estimated = False
        self.exclusions = ()
        self.manual_position_edits = set()
        self.reset_buttons, self.info_buttons = {}, {}
        for name, label, unit, low, high, automatic in (
            ("target_layer_time_s", "Mindest-Layerzeit", "s", .1, 3600, "automatic_target_time"),
            ("clearance_mm", "Modellabstand", "mm", 5, 100, None),
            ("wait_clearance_mm", "Warteabstand", "mm", 5, 100, None),
        ):
            self._numeric(self.input_group.content_layout, name, label, unit, low, high, automatic)
        self._numeric(self.input_group.content_layout, "wall_count", "Wandlinien", "", 1, 3, integer=True)
        self.wall_count_spin = self.inputs.pop("wall_count")
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
        for name, label, low, high, automatic in (
            ("height_mm", "Turmhöhe", .01, 1000, "automatic_height"),
            ("diameter_mm", "Turmbreite", 3, 100, "automatic_diameter"),
            ("base_width_mm", "Standfußbreite", 3, 150, "automatic_base"),
        ):
            self._numeric(self.advanced_group.content_layout, name, label, "mm", low, high, automatic)
        self._positions_row()
        self.hollow_checkbox = QCheckBox("Hohler Turm")
        self.hollow_checkbox.setChecked(True)
        self.advanced_group.content_layout.addWidget(self._check_row("hollow_tower", self.hollow_checkbox, True))
        for name, label, low, high, automatic in (
                ("tower_brim_width_mm", "Turm-Brim Breite", 0, 20, "automatic_tower_brim_width"),
                ("tower_brim_gap_mm", "Turm-Brim Abstand", .1, 1, "automatic_tower_brim_gap")):
            self._numeric(self.advanced_group.content_layout, name, label, "mm", low, high, automatic)
        for name, label, unit, low, high in (
            ("edge_clearance_mm", "Druckbettrandabstand", "mm", 5, 100),
            ("print_speed_mm_s", "Turmdruckgeschwindigkeit", "mm/s", 1, 100),
            ("travel_speed_mm_s", "Fahrgeschwindigkeit", "mm/s", 1, 300),
            ("retract_mm", "Zusätzlicher Rückzug", "mm", 0, 10),
            ("retract_speed_mm_s", "Rückzugsgeschwindigkeit", "mm/s", 1, 100),
            ("z_hop_mm", "Z-Hop", "mm", 0, 10),
            ("prime_mm", "Max. zusätzliches Primen", "mm", 0, 5),
        ):
            automatic = {"print_speed_mm_s": "automatic_print_speed", "travel_speed_mm_s": "automatic_travel_speed",
                "retract_mm": "automatic_retraction", "z_hop_mm": "automatic_z_hop", "prime_mm": "automatic_prime"}.get(name)
            self._numeric(self.advanced_group.content_layout, name, label, unit, low, high, automatic)
        self.preview_group = SectionCard("G-Code-Vorschau")
        self.preview_group.content_layout.setAlignment(Qt.AlignmentFlag(0))
        for card in (self.input_group, self.advanced_group, self.preview_group):
            card.setProperty("outerDropdown", True)
            card.setProperty("edgeAttached", True)
        self.columns = ResizablePreviewColumns(left, self.preview_group)
        self.columns.layout_changed.connect(lambda: self._layout_timer.start(0))
        layout.addWidget(self.columns)
        self.canvas = PreviewCanvas()
        self.canvas.set_rotation_drag_inverted(True)
        self.canvas.set_navigation_default(True)
        self.canvas.set_layer_context_enabled(True)
        self.canvas.set_layer_selection_persistent(True)
        self.canvas.layer_highlight_cleared.connect(self._clear_layer_focus)
        self.canvas.setMinimumWidth(0)
        self.canvas.setFixedHeight(420)
        self.preview_display = QWidget()
        self.preview_display.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        self.display_layout = QHBoxLayout(self.preview_display)
        self.display_layout.setContentsMargins(0, 0, 0, 0)
        self.display_layout.setSpacing(12)
        self.preview_view = QWidget()
        preview_layout = QVBoxLayout(self.preview_view)
        preview_layout.setContentsMargins(0, 0, 0, 0)
        preview_layout.setSpacing(6)
        self.display_layout.addWidget(self.preview_view, 3, Qt.AlignmentFlag.AlignTop)
        self.preview_group.content_layout.addWidget(self.preview_display)
        camera_row = QHBoxLayout()
        self.camera_row = camera_row
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
        self.timing_toggle = QPushButton()
        self.timing_toggle.setObjectName("previewLayerTimesToggle")
        self.timing_toggle.setCheckable(True)
        self.timing_toggle.setChecked(True)
        self.timing_toggle.setFixedSize(32, 32)
        self.timing_toggle.setIconSize(QSize(22, 22))
        self.timing_toggle.setIcon(QIcon(str(Path(__file__).parent / "assets" / "layer_times_panel.svg")))
        self.timing_toggle.setAccessibleName("Layerzeiten ein- oder ausblenden")
        self.timing_toggle.setToolTip("Layerzeiten")
        self.timing_toggle.setStyleSheet("QPushButton { min-width: 0; min-height: 0; padding: 0; border-radius: 6px; }"
            "QPushButton:checked { background: #dcebf7; border: 1px solid #afc0d0; }"
            "QPushButton:focus { border: 1px solid #afc0d0; }")
        self.timing_toggle.toggled.connect(self._toggle_timing)
        camera_row.addWidget(self.timing_toggle)
        preview_layout.addLayout(camera_row)
        preview_layout.addWidget(self.canvas)
        for name, title, action in (("preview_reset", "Vorschau zurücksetzen", self.reset_preview),
                ("transparency_toggle", "Transparenz aktiv", None),
                ("travel_visibility_button", "Fahrwege ausblenden", None)):
            button = QPushButton(title, self.canvas)
            button.setAutoDefault(False)
            button.setFixedHeight(32)
            button.setStyleSheet("QPushButton { min-height: 32px; max-height: 32px; border: 0; border-radius: 0; "
                "padding: 0 12px; background: #243344; color: #dbe8f2; }"
                "QPushButton:hover { background: #355269; }"
                "QPushButton:focus { border: 0; }"
                "QPushButton:pressed { background: #1c4561; }"
                "QPushButton:checked { background: #244436; }"
                "QPushButton:checked:hover { background: #355c49; }"
                "QPushButton:checked:pressed { background: #1d4c35; }"
                "QPushButton:disabled { background: #20272e; color: #7b8b98; }")
            if name == "travel_visibility_button":
                button.setCheckable(True)
                button.setChecked(True)
                button.setToolTip("Blendet die Fahrwege ein oder aus. Alle / Einzeln bestimmt die angezeigten Layer.")
                button.toggled.connect(self._toggle_travel_visibility)
            elif name == "transparency_toggle":
                button.setCheckable(True)
                button.setChecked(True)
                button.setToolTip("Stellt die Layer unterhalb der gewählten Schicht transparent dar. "
                    "Die Layerauswahl im Diagramm aktiviert diese Darstellung automatisch.")
                button.toggled.connect(self._set_transparency_active)
            else:
                button.clicked.connect(action)
            button.setEnabled(False)
            setattr(self, name, button)
        self.travel_mode_toggle = TravelModeToggle(self.canvas)
        self.travel_mode_toggle.setFixedHeight(32)
        self.travel_mode_toggle.toggled.connect(self.canvas.set_all_travel_visible)
        self._travel_reveal = 0.0
        self._travel_reveal_animation = QVariantAnimation(self)
        self._travel_reveal_animation.setEasingCurve(QEasingCurve.Type.InOutCubic)
        self._travel_reveal_animation.valueChanged.connect(self._set_travel_reveal)
        self._travel_reveal_animation.finished.connect(self._finish_travel_reveal)
        self.canvas.set_wait_travel_visible(True)
        self.canvas.set_tower_travel_visible(True)
        self.canvas.set_wait_position_visible(True)
        self.canvas.installEventFilter(self)
        self.legend = FlowColourLegend((("Modell", PreviewCanvas.OBJECT_COLOR), ("Turm", PreviewCanvas.TOWER_COLOR),
            ("Warteposition", PreviewCanvas.WAIT_POSITION_COLOR), ("Warteplatzfahrten", PreviewCanvas.WAIT_TRAVEL_COLOR),
            ("Modell-/Turmfahrten", PreviewCanvas.TOWER_TRAVEL_COLOR), ("Brim", PreviewCanvas.BRIM_COLOR),
            ("Seams", PreviewCanvas.SEAM_COLOR)))
        preview_layout.addWidget(self.legend)
        self.safety_hint = QLabel()
        self.safety_hint.setWordWrap(True)
        self.safety_hint.setTextFormat(Qt.TextFormat.PlainText)
        self.safety_hint.hide()
        preview_layout.addWidget(self.safety_hint)
        self.timing_panel = QWidget()
        self.timing_panel.setObjectName("postprocessorLayerTimes")
        self.display_layout.addWidget(self.timing_panel, 2, Qt.AlignmentFlag.AlignTop)
        timing_layout = QVBoxLayout(self.timing_panel)
        timing_layout.setContentsMargins(0, 0, 0, 0)
        timing_layout.setSpacing(6)
        timing_layout.addWidget(QLabel("<b>Layerzeiten</b>"))
        self.time_chart = PostprocessorTimeChart()
        timing_layout.addWidget(self.time_chart, 1)
        self.time_legend = ColourLegend(tuple(zip(("Original", "Zusätzliche Bewegung", "Restwartezeit", "Zielzeit"),
            (*PostprocessorTimeChart.COLORS, PostprocessorTimeChart.TARGET_COLOR))), columns=1)
        timing_layout.addWidget(self.time_legend)
        self.logarithmic_scale = QCheckBox("Logarithmische Zeitskala")
        self.logarithmic_scale.setChecked(True)
        self.logarithmic_scale.setToolTip("Zeigt kurze und lange Layerzeiten gemeinsam lesbar. Alle Zeiten bleiben erhalten; abschalten für eine lineare Skala.")
        self.logarithmic_scale.toggled.connect(self.time_chart.set_logarithmic)
        logarithmic_row = QWidget()
        logarithmic_layout = QHBoxLayout(logarithmic_row)
        logarithmic_layout.setContentsMargins(0, 0, 0, 0)
        logarithmic_layout.setSpacing(6)
        self.logarithmic_info = InfoToolButton(setting_hint("Logarithmische Zeitskala", "logarithmic_time_scale"),
            object_name="settingInfoButton", diameter_px=METRICS.setting_info_diameter_px,
            accessible_name="Informationen zu Logarithmische Zeitskala")
        logarithmic_layout.addWidget(self.logarithmic_info)
        logarithmic_layout.addWidget(self.logarithmic_scale)
        logarithmic_layout.addStretch(1)
        timing_layout.addWidget(logarithmic_row)
        normalization_row = QWidget()
        normalization_layout = QHBoxLayout(normalization_row)
        normalization_layout.setContentsMargins(0, 0, 0, 0)
        normalization_layout.setSpacing(6)
        self.normalized_scale = QCheckBox("Zeitskala normalisieren")
        self.normalized_scale.toggled.connect(self.time_chart.set_normalized)
        self.normalization_info = InfoToolButton(setting_hint("Zeitskala normalisieren", "normalize_time_scale"),
            object_name="settingInfoButton", diameter_px=METRICS.setting_info_diameter_px,
            accessible_name="Informationen zu Zeitskala normalisieren")
        normalization_layout.addWidget(self.normalization_info)
        normalization_layout.addWidget(self.normalized_scale)
        normalization_layout.addStretch(1)
        timing_layout.addWidget(normalization_row)
        self.layer_spin = LayerNumberSpinBox()
        self.layer_spin.setRange(1, 1)
        self.layer_spin.setAccessibleName("Layernummer in der Vorschau")
        self.layer_reset = QPushButton("↺")
        self.layer_reset.setObjectName("settingResetButton")
        self.layer_reset.setFixedSize(METRICS.reset_button_size_px, METRICS.reset_button_size_px)
        self.layer_reset.setAccessibleName("Letzten Layer und vollständiges Modell anzeigen")
        self.layer_reset.setToolTip("Letzten Layer und vollständiges Modell anzeigen")
        self.layer_reset.clicked.connect(self.reset_layer)
        layer_row = QHBoxLayout()
        layer_row.setSpacing(6)
        layer_row.addWidget(QLabel("Layer"))
        layer_row.addWidget(self.layer_spin)
        layer_row.addWidget(self.layer_reset)
        layer_row.addStretch(1)
        timing_layout.addLayout(layer_row)
        self.layer_details = QLabel()
        self.layer_details.setWordWrap(True)
        timing_layout.addWidget(self.layer_details)
        self._timing_result = None
        self._layer_focus_active = False
        self.time_chart.layer_selected.connect(self.select_layer)
        self.time_chart.drag_finished.connect(lambda _layer: self._apply_layer_view())
        self.layer_spin.valueChanged.connect(self.select_layer)
        self.clear_timing()
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

    def eventFilter(self, watched, event):  # noqa: N802
        canvas = getattr(self, "canvas", None)
        if event.type() in (QEvent.Type.FontChange, QEvent.Type.StyleChange) and watched is not canvas:
            self._layout_timer.start(0)
        if watched is canvas and event.type() in (QEvent.Type.Resize, QEvent.Type.Show):
            self._position_preview_reset()
        if watched is canvas and event.type() == QEvent.Type.Hide:
            self._show_travel_modes(self.travel_visibility_button.isChecked() and
                self.travel_visibility_button.isEnabled(), animate=False)
        if watched is self._preview_viewport and event.type() == QEvent.Type.Resize:
            self._layout_timer.start(0)
        return super().eventFilter(watched, event)

    def _position_preview_reset(self):
        left_width = max(self.preview_reset.sizeHint().width(), self.transparency_toggle.sizeHint().width(),
            self.transparency_toggle.fontMetrics().horizontalAdvance("Transparenz inaktiv")+24)
        right_width = max(self.travel_visibility_button.sizeHint().width(), self.travel_mode_toggle.sizeHint().width())
        for button in (self.preview_reset, self.transparency_toggle):
            button.setFixedWidth(left_width)
        for button in (self.travel_visibility_button, self.travel_mode_toggle):
            button.setFixedWidth(right_width)
        self.preview_reset.move(0, max(0, self.canvas.height()-self.preview_reset.height()))
        self.transparency_toggle.move(0, max(0, self.preview_reset.y()-self.transparency_toggle.height()))
        # Both controls are canvas children, so Qt clips the sliding mode
        # toggle at the preview edge throughout the animation.
        revealed_height = round(self.travel_mode_toggle.height()*self._travel_reveal)
        self.travel_mode_toggle.move(self.canvas.width()-right_width, self.canvas.height()-revealed_height)
        self.travel_visibility_button.move(self.canvas.width()-right_width,
            self.travel_mode_toggle.y()-self.travel_visibility_button.height())
        for button in (self.preview_reset, self.transparency_toggle, self.travel_visibility_button, self.travel_mode_toggle):
            button.raise_()

    def _set_travel_reveal(self, value):
        self._travel_reveal = float(value)
        self._position_preview_reset()

    def _finish_travel_reveal(self):
        self.travel_mode_toggle.setVisible(self._travel_reveal > 0)

    def _show_travel_modes(self, visible, *, animate=True):
        animation = self._travel_reveal_animation
        current = self._travel_reveal
        animation.stop()
        target = float(visible)
        self.travel_mode_toggle.setEnabled(visible)
        if not animate or not self.canvas.isVisible() or abs(target-self._travel_reveal) < .001:
            self._set_travel_reveal(target)
            self.travel_mode_toggle.setVisible(visible)
            return
        self.travel_mode_toggle.show()
        # Qt also emits intermediate values while reconfiguring a stopped
        # animation. Keep reversal anchored to the actual visible position.
        with QSignalBlocker(animation):
            animation.setDuration(max(1, round(self.TRAVEL_REVEAL_DURATION_MS*abs(target-current))))
            animation.setStartValue(current)
            animation.setEndValue(target)
            animation.setCurrentTime(0)
        animation.start()

    def _set_transparency_active(self, active):
        self.transparency_toggle.setText("Transparenz aktiv" if active else "Transparenz inaktiv")
        self._apply_layer_view()
        self._position_preview_reset()

    def refresh_layout(self):
        """Reserve expanded content before the scroll area can compress rows."""
        if not self.isVisible():
            return
        self._fit_numeric_fields()
        for row in self.rows.values():
            row.label.setMinimumWidth(max(150, row.label.fontMetrics().horizontalAdvance(row.label.text()) + 30))
        self.positions_label.setMinimumWidth(self.positions_label.fontMetrics().horizontalAdvance(self.positions_label.text()) + 30)
        positions_row = self.positions_label.parentWidget()
        positions_row.layout().invalidate()
        positions_row.setMinimumWidth(positions_row.layout().minimumSize().width())
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
            self._arrange_preview_content()
            self.preview_group.content_layout.activate()
            self.display_layout.activate()
            self.preview_view.layout().activate()
            self._fit_preview_height()
            self.preview_view.layout().invalidate()
            self.preview_view.updateGeometry()
            self.display_layout.invalidate()
            self.preview_display.updateGeometry()
            self._reserve_card_height(self.preview_group)
            required = self.columns.content_height_hint()
            self.columns.setFixedHeight(required)
            self.columns.layout().activate()
            self.columns.splitter.refresh()
            self.preview_group.layout().activate()
            self.preview_group.content_layout.activate()
            if required == self.columns.content_height_hint():
                break
        self._sync_navigation_columns()
        self.updateGeometry()
        self.layout_changed.emit()

    def _sync_navigation_columns(self):
        two_column = self.columns.is_two_column()
        if two_column == self._navigation_columns:
            return
        previous = self._navigation_columns
        self._navigation_columns = two_column
        if not two_column:
            self._navigation_before_stack = self.canvas.navigation_enabled
            self.canvas.set_navigation_default(False)
        elif previous is False:
            # A manual activation in the stacked view wins when widening.
            self.canvas.set_navigation_default(self.canvas.navigation_enabled or self._navigation_before_stack)

    @staticmethod
    def _reserve_card_height(card):
        """Publish wrapped details before a parent can compress their layout."""
        card.setMinimumHeight(0)
        body = card.content_widget
        body.setMinimumHeight(0)
        card.content_layout.invalidate()
        layout = card.content_layout
        margins = layout.contentsMargins()
        width = max(1, body.width()-margins.left()-margins.right())
        heights = []
        for index in range(layout.count()):
            item = layout.itemAt(index)
            widget = item.widget()
            if widget is not None and widget.isHidden():
                continue
            preferred = (widget.heightForWidth(width) if widget is not None and widget.hasHeightForWidth()
                else item.heightForWidth(width) if item.hasHeightForWidth() else item.sizeHint().height())
            heights.append(max(item.minimumSize().height(), preferred))
        # Nested grids can report a zero height-for-width despite a positive
        # minimum. Sum each vertical item's real requirement to preserve gaps.
        required = sum(heights)+max(0, len(heights)-1)*layout.spacing()+margins.top()+margins.bottom()
        body.setMinimumHeight(required)
        body.updateGeometry()
        card.layout().invalidate()
        card.setMinimumHeight(card.layout().minimumSize().height())
        card.updateGeometry()

    def _arrange_preview_content(self):
        """Keep the chart beside the canvas whenever both columns remain readable."""
        body = self.preview_group.content_widget
        margins = self.preview_group.content_layout.contentsMargins()
        width = max(1, body.width()-margins.left()-margins.right())
        height = max(button.sizeHint().height() for button in self.camera_buttons.values())
        self.timing_toggle.setFixedSize(height, height)
        self.layer_spin.fit_text()
        minimum_left = max(self.legend.minimumSizeHint().width(), self.camera_row.minimumSize().width())
        chart_width = max(210, self.timing_panel.minimumSizeHint().width())
        preferred_pair = minimum_left+chart_width+12
        # Choose from intrinsic widths rather than last frame's wrapped layout.
        # Otherwise scrolling can alternate between stacked and paired layouts.
        side_by_side = self.timing_panel.isHidden() or width >= preferred_pair
        self.display_layout.setDirection(QBoxLayout.Direction.LeftToRight if side_by_side else QBoxLayout.Direction.TopToBottom)
        self.timing_panel.setMaximumWidth(chart_width if side_by_side else 16777215)
        details_width = width
        if side_by_side and not self.timing_panel.isHidden():
            details_width -= chart_width+12
        self.legend.setFixedHeight(self.legend.heightForWidth(max(1, details_width)))
        whole_width = self.width()-margins.left()-margins.right()
        minimum = (preferred_pair if not self.timing_panel.isHidden() and whole_width >= preferred_pair else
            minimum_left)
        self.preview_display.setMinimumWidth(minimum)
        self.display_layout.invalidate()
        self.preview_display.updateGeometry()

    def _fit_preview_height(self):
        """Let the viewport and the left preview determine the right column's height."""
        ancestor = self.parentWidget()
        while ancestor is not None and not isinstance(ancestor, QScrollArea):
            ancestor = ancestor.parentWidget()
        available = ancestor.viewport().height() if ancestor is not None else self.window().height()-180
        if ancestor is not None and self._preview_viewport is not ancestor.viewport():
            self._preview_viewport = ancestor.viewport()
            self._preview_viewport.installEventFilter(self)
        # Reserve all wrapped legend rows below the camera and preview.
        footer_height = self.legend.heightForWidth(max(1, self.preview_view.width()))
        self.legend.setFixedHeight(footer_height)
        overhead = self.preview_group.header.height()+28+self.camera_row.sizeHint().height()+12+footer_height
        if self.safety_hint.text():
            overhead += max(0, self.safety_hint.heightForWidth(max(1, self.preview_view.width())))+6
        canvas_height = max(160, min(round(self.canvas.width()*.75), available-overhead))
        self.canvas.setFixedHeight(canvas_height)
        self.preview_view.layout().invalidate()
        self.preview_view.layout().activate()
        left_height = self.preview_view.layout().sizeHint().height()
        self.timing_panel.setMinimumHeight(0)
        self.timing_panel.setMaximumHeight(16777215)
        self.timing_panel.layout().invalidate()
        if self.timing_panel.isVisible():
            minimum = self.timing_panel.layout().minimumSize().height()
            if minimum > left_height:
                self.canvas.setFixedHeight(canvas_height+minimum-left_height)
                self.preview_view.layout().invalidate()
                self.preview_view.layout().activate()
                left_height = self.preview_view.layout().sizeHint().height()
        self.timing_panel.setFixedHeight(left_height)
        self.timing_panel.layout().activate()

    def _numeric(self, layout, name, label, unit, low, high, automatic=None, *, integer=False):
        defaults = PostprocessorSettings()
        spin = CommittedSpinBox() if integer else PostprocessorValueSpinBox()
        spin.setRange(low, high)
        if not integer:
            spin.setDecimals(2)
        if name in {"tower_brim_gap_mm", "z_hop_mm"}:
            spin.setSingleStep(.1)
        if name == "z_hop_mm":
            spin.fixed_decimals = True
        spin.setValue(getattr(defaults, name))
        self.inputs[name] = spin
        row = NumericSettingWidget(setting_name=name, label=label, editor=spin,
            default_provider=lambda: getattr(defaults, name), unit=unit, info_text=setting_hint(label, name))
        spin.setKeyboardTracking(False)
        spin.lineEdit().setStyleSheet("QLineEdit { padding: 0; border: 0; background: transparent; }")
        row.label.setWordWrap(False)
        self.rows[name] = row
        self.reset_buttons[name], self.info_buttons[name] = row.reset_button, row.info_button
        row.reset_button.clicked.disconnect()
        row.reset_button.clicked.connect(lambda: self.reset_field(name))
        if automatic:
            checkbox = QCheckBox()
            checkbox.setChecked(getattr(defaults, automatic))
            checkbox.setAccessibleName(label + " automatisch berechnen")
            self.automatic[automatic] = checkbox
            grid = row.layout()
            for widget in (spin, row.reset_button, row.range_label, row.message_container):
                grid.removeWidget(widget)
            automatic_label = QLabel("Auto")
            automatic_label.setBuddy(checkbox)
            grid.addWidget(automatic_label, 0, 2, Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
            grid.addWidget(checkbox, 0, 3, Qt.AlignmentFlag.AlignVCenter)
            grid.addWidget(spin, 0, 4, Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
            grid.addWidget(row.reset_button, 0, 5, Qt.AlignmentFlag.AlignVCenter)
            grid.addWidget(row.range_label, 1, 1, 1, 4, Qt.AlignmentFlag.AlignRight)
            grid.addWidget(row.message_container, 2, 0, 1, 6)
            checkbox.toggled.connect(self._changed)
        spin.valueChanged.connect(self._changed)
        spin.lineEdit().textChanged.connect(lambda _: self._layout_timer.start(0))
        spin.editingFinished.connect(lambda: self._layout_timer.start(0))
        spin.installEventFilter(self)
        layout.addWidget(row)

    def _fit_numeric_fields(self):
        """Share the smallest width that fits every current value and its unit."""
        for row in self.rows.values():
            row.unit_label.ensurePolished()
        previous_unit_width = max(row.unit_label.fontMetrics().horizontalAdvance(row.unit_label.text())+4
            for row in self.rows.values())
        unit_width = max(previous_unit_width, *(row.unit_label.minimumSizeHint().width()
            for row in self.rows.values()))
        # The label's style padding and glyph bearings need real space too.
        # Take it equally from both value gaps, retaining the existing box budget.
        extra = unit_width-previous_unit_width
        reduction = min(4, (extra+1)//2)
        left_gap, right_gap = 8-reduction, 4-reduction
        width_budget = max(0, 2*reduction-extra)
        required = []
        for row in self.rows.values():
            spin = row.editor
            spin.ensurePolished()
            row.unit_label.setFixedWidth(unit_width)
            padding = f"QDoubleSpinBox, QSpinBox {{ padding: 0 {unit_width+right_gap}px 0 {left_gap}px; }}"
            if spin.styleSheet() != padding:
                spin.setStyleSheet(padding)
            option = QStyleOptionSpinBox()
            spin.initStyleOption(option)
            field = spin.style().subControlRect(QStyle.ComplexControl.CC_SpinBox,
                option, QStyle.SubControl.SC_SpinBoxEditField, spin)
            margins = spin.lineEdit().textMargins()
            text_width = spin.lineEdit().fontMetrics().horizontalAdvance(spin.lineEdit().text() or "0")
            required.append(text_width+margins.left()+margins.right()+4+spin.width()-field.width()+width_budget)
        width = max(required)
        for row in self.rows.values():
            row.editor.setFixedWidth(width)
            row.range_label.setFixedWidth(width+30)
            row._position_unit_label()

    def _positions_row(self):
        # Keep independent editor drafts internally; the settings row controls
        # the pair together, while the dialog can still place just one manually.
        defaults = PostprocessorSettings()
        for flag in ("automatic_position", "automatic_wait_position"):
            checkbox = QCheckBox(self)
            checkbox.setChecked(True)
            checkbox.hide()
            checkbox.toggled.connect(self._changed)
            self.automatic[flag] = checkbox
            for name in AUTOMATIC_FIELDS[flag]:
                spin = PostprocessorValueSpinBox(self)
                spin.setRange(-2000, 2000)
                spin.setDecimals(2)
                spin.setValue(getattr(defaults, name))
                spin.hide()
                spin.valueChanged.connect(lambda _value, key=flag: self.manual_position_edits.add(key))
                spin.valueChanged.connect(self._changed)
                self.inputs[name] = spin
        row = QWidget()
        layout = QHBoxLayout(row)
        layout.setContentsMargins(0, METRICS.form_row_vertical_padding_px, 0, 2)
        layout.setSpacing(METRICS.form_control_gap_px)
        title = "Turm- und Warteposition"
        info = InfoToolButton(setting_hint(title, "positions"), object_name="settingInfoButton",
            diameter_px=METRICS.setting_info_diameter_px, accessible_name="Informationen zu " + title)
        label = QLabel(title)
        self.positions_label = label
        label.setWordWrap(False)
        label.setMinimumWidth(label.fontMetrics().horizontalAdvance(title) + 30)
        self.positions_automatic = QCheckBox()
        self.positions_automatic.setAccessibleName(title + " automatisch berechnen")
        automatic_label = QLabel("Auto")
        automatic_label.setBuddy(self.positions_automatic)
        self.positions_button = QPushButton("Positionen bearbeiten")
        self.positions_button.setFixedHeight(METRICS.form_control_height_px)
        self.positions_button.setStyleSheet("QPushButton { min-height: 34px; max-height: 34px; padding: 0 10px; }")
        self.positions_button.setToolTip("Turm- und Warteposition bearbeiten")
        layout.addWidget(info)
        layout.addWidget(label)
        layout.addStretch(1)
        layout.addWidget(automatic_label)
        layout.addWidget(self.positions_automatic)
        layout.addWidget(self.positions_button)
        self.info_buttons["positions"] = info
        self.positions_automatic.toggled.connect(self._positions_automatic_changed)
        self.advanced_group.content_layout.addWidget(row)

    def _positions_automatic_changed(self, enabled):
        for flag in ("automatic_position", "automatic_wait_position"):
            with QSignalBlocker(self.automatic[flag]):
                self.automatic[flag].setChecked(enabled)
        self._changed()

    def _check_row(self, name, checkbox, default):
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
            layout.addWidget(checkbox)
            layout.addStretch(1)
        layout.addWidget(reset)
        self.reset_buttons[name], self.info_buttons[name] = reset, info
        checkbox.toggled.connect(self._changed)
        checkbox.toggled.connect(self.refresh_resets)
        return row

    def _build_footer(self):
        self.footer_widget = PostprocessorFooter()
        self.footer_widget.setObjectName("postprocessorFooter")
        self.footer_widget.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Maximum)
        layout = QVBoxLayout(self.footer_widget)
        layout.setContentsMargins(22, 8, 22, 8)
        self.footer_columns = ResponsiveCardGrid(horizontal_spacing_px=12, vertical_spacing_px=8)
        layout.addWidget(self.footer_columns)
        self.footer_message_area = QWidget()
        messages = QVBoxLayout(self.footer_message_area)
        messages.setContentsMargins(0, 0, 12, 0)
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
        actions_column.setContentsMargins(12, 0, 0, 0)
        actions_column.addStretch(1)
        self.export_actions = QWidget()
        actions = QGridLayout(self.export_actions)
        self.footer_actions_layout = actions
        actions.setContentsMargins(0, 0, 0, 0)
        actions.setHorizontalSpacing(8)
        actions.setVerticalSpacing(0)
        actions.setColumnStretch(3, 1)
        self.open_output_button = QPushButton("Alle Exporte öffnen")
        self.open_output_button.setObjectName("openBaseOutputFolderButton")
        self.open_last_button = QPushButton("Letzten Export öffnen")
        self.open_last_button.setObjectName("openOutputFolderButton")
        self.open_report_button = QPushButton("Letzten Exportbericht öffnen")
        self.open_report_button.setObjectName("openExportReportButton")
        self.open_last_button.hide()
        self.open_report_button.hide()
        self.generate_button = QPushButton("G-Code und Vorschau erzeugen")
        self.generate_button.setObjectName("previewButton")
        self.export_button = QPushButton("G-Code exportieren")
        self.export_button.setObjectName("exportButton")
        self.cancel_button = QPushButton("Abbrechen")
        self.cancel_button.setObjectName("postprocessorCancelButton")
        self.cancel_button.hide()
        self.export_button.hide()
        for column, button in enumerate((self.open_output_button, self.open_last_button,
                self.open_report_button, self.generate_button, self.cancel_button, self.export_button)):
            button.setSizePolicy(QSizePolicy.Policy.Minimum, QSizePolicy.Policy.Fixed)
            actions.addWidget(button, 0, column if column < 3 else column+1,
                Qt.AlignmentFlag.AlignBottom)
        actions_column.addWidget(self.export_actions)
        vertical, horizontal = QFrame(), QFrame()
        vertical.setObjectName("footerVerticalDivider")
        vertical.setFixedWidth(1)
        horizontal.setObjectName("footerHorizontalDivider")
        horizontal.setFixedHeight(1)
        self.footer_columns.set_vertical_separator(vertical)
        self.footer_columns.set_stacked_separator(horizontal)
        self.footer_columns.add_pair(self.footer_message_area, self.footer_action_area)
        self.footer_widget.watch_content(self.footer_columns, self.footer_action_area, (self.footer_message_area, self.footer_action_area,
            self.status, self.progress, self.export_actions, self.open_last_button, self.open_report_button,
            self.generate_button, self.cancel_button, self.export_button), fit_actions=self._fit_footer_actions)
        self.footer_widget.hide()

    def _fit_footer_actions(self, width):
        def set_labels(shorten_folders, report_level, shorten_actions):
            self.open_output_button.setText("Alle Exporte" if shorten_folders else "Alle Exporte öffnen")
            self.open_last_button.setText("Letzter Export" if shorten_folders else "Letzten Export öffnen")
            self.open_report_button.setText(("Letzten Exportbericht öffnen", "Exportbericht öffnen", "Exportbericht")[report_level])
            self.generate_button.setText("Erzeugen" if shorten_actions else "G-Code und Vorschau erzeugen")
            self.export_button.setText("Exportieren" if shorten_actions else "G-Code exportieren")
        narrow, self._footer_actions_layout_mode = fit_footer_actions(self.footer_actions_layout,
            (self.open_output_button, self.open_last_button, self.open_report_button),
            (self.generate_button, self.cancel_button, self.export_button), max(0, width-24), set_labels)
        return narrow

    def settings(self):
        values = {name: spin.value() for name, spin in self.inputs.items()}
        defaults = PostprocessorSettings()
        for flag, names in AUTOMATIC_FIELDS.items():
            if self.automatic[flag].isChecked():
                for name in names:
                    values[name] = getattr(defaults, name)
        return PostprocessorSettings(**values, **{name: box.isChecked() for name, box in self.automatic.items()},
            hollow_tower=self.hollow_checkbox.isChecked(), wall_count=self.wall_count_spin.value(), exclusions=self.exclusions)

    def set_profile_values(self, values):
        profile_error = None
        try:
            effective, notes = resolve_profile_settings(PostprocessorSettings(automatic_target_time=True), values)
        except ValueError as error:
            effective, notes, profile_error = PostprocessorSettings(), (str(error),), str(error)
        self._profile_values = {name: getattr(effective, name) for name in PROFILE_FIELDS}
        for name in PROFILE_FIELDS:
            self._automatic_values.pop(name, None)
        for flag, names in AUTOMATIC_FIELDS.items():
            if self.automatic[flag].isChecked():
                for name in names:
                    if name in PROFILE_FIELDS:
                        with QSignalBlocker(self.inputs[name]):
                            self.inputs[name].setValue(self._profile_values[name])
        self.profile_hint.setText(profile_error or "Profilvorgaben werden bei aktiver Automatik übernommen; eigene Werte sind manuell einstellbar.")
        self.profile_hint.setToolTip("\n".join(notes))
        geometry = parse_bed_geometry(values)
        if geometry is not None:
            head = printhead_envelope(values, geometry)
            self._profile_safety_estimated = head.estimated and bool(geometry.excluded_polygons)
            self._profile_safety_note = ("Feste Hindernisse werden mit vorsichtigen Ersatzmaßen geprüft; Druckkopfmaße im Profil sind unvollständig."
                if self._profile_safety_estimated else "")
            self.safety_hint.setText(self._profile_safety_note)
            self.safety_hint.setStyleSheet("color: #8a4b08;" if head.estimated else "color: #526b7e;")
        else:
            self._profile_safety_note = "Für diese Quelle fehlt eine bestätigte Druckbettgeometrie."
            self._profile_safety_estimated = True
            self.safety_hint.setText(self._profile_safety_note)
            self.safety_hint.setStyleSheet("color: #8a4b08;")
        self.safety_hint.setVisible(bool(self.safety_hint.text()))
        self._sync_automatic()

    def clear_timing(self):
        self._layer_view_timer.stop()
        self._timing_result = None
        self._layer_focus_active = False
        self.timing_panel.hide()
        self.timing_toggle.hide()
        self.timing_toggle.setEnabled(False)
        self.time_chart.set_data()
        with QSignalBlocker(self.normalized_scale):
            self.normalized_scale.setChecked(False)
        self.preview_reset.setEnabled(False)
        self.transparency_toggle.setEnabled(False)
        self.travel_visibility_button.setEnabled(False)
        self._show_travel_modes(False, animate=False)
        for widget in (self.layer_spin, self.layer_reset):
            widget.setEnabled(False)
        self.layer_details.clear()
        self.safety_hint.setText(self._profile_safety_note)
        self.safety_hint.setVisible(bool(self.safety_hint.text()))
        self.safety_hint.setStyleSheet("color: #8a4b08;" if self._profile_safety_estimated else "color: #526b7e;")
        self.canvas.set_layer_height(None)
        self.canvas.set_layer_transparency_enabled(self.transparency_toggle.isChecked())
        self.canvas.set_travel_layer_height(None)
        self._layout_timer.start(0)

    def show_timing(self, result):
        self._timing_result = result
        self.time_chart.set_data(result.original_layer_times_s, result.added_motion_times_s, result.layer_waits_s,
            result.layer_heights_mm, result.effective_settings.target_layer_time_s)
        with QSignalBlocker(self.normalized_scale):
            self.normalized_scale.setChecked(self.time_chart.normalized)
        for widget in (self.layer_spin,):
            with QSignalBlocker(widget):
                widget.setRange(1, len(result.layer_times_s))
                widget.setValue(len(result.layer_times_s))
            widget.setEnabled(True)
        self._layer_focus_active = False
        self.layer_reset.setEnabled(True)
        self.preview_reset.setEnabled(True)
        self.transparency_toggle.setEnabled(True)
        self.travel_visibility_button.setEnabled(True)
        self._show_travel_modes(self.travel_visibility_button.isChecked(), animate=False)
        note = ("Feste Hindernisse und tiefe Originalfahrten werden mit vorsichtigen Druckkopf-Ersatzmaßen geprüft."
            if result.printhead.estimated and result.placement.head_clearance_required else self._profile_safety_note)
        self.safety_hint.setText(note)
        self.safety_hint.setVisible(bool(note))
        self.safety_hint.setToolTip("\n".join(result.collision_notes))
        self.safety_hint.setStyleSheet("color: #8a4b08;" if result.printhead.estimated else "color: #526b7e;")
        self.time_chart.select_layer(self.layer_spin.maximum())
        self._update_layer_details(self.layer_spin.maximum())
        self._apply_layer_view()
        self.timing_toggle.setEnabled(True)
        self.timing_toggle.show()
        self._toggle_timing(self.timing_toggle.isChecked())
        self._layout_timer.start(0)

    def select_layer(self, layer, *, activate_transparency=True):
        if self._timing_result is None:
            return
        layer = max(1, min(len(self._timing_result.layer_times_s), int(layer)))
        for widget in (self.layer_spin,):
            with QSignalBlocker(widget):
                widget.setValue(layer)
        self.layer_spin.fit_text()
        self.time_chart.select_layer(layer)
        self._layer_focus_active = True
        if activate_transparency:
            self.transparency_toggle.setChecked(True)
        self._update_layer_details(layer)
        if self.time_chart._dragging:
            if not self._layer_view_timer.isActive():
                self._layer_view_timer.start()
        else:
            self._apply_layer_view()

    def _update_layer_details(self, layer):
        r, i = self._timing_result, layer - 1
        self.layer_details.setText(f"Layer {layer} · Z {r.layer_heights_mm[i]:.2f} mm · {r.layer_times_s[i]:.2f} s")
        self.layer_details.setToolTip(f"Original: {r.original_layer_times_s[i]:.2f} s\n"
            f"Bewegung zusätzlich: {r.added_motion_times_s[i]:.2f} s\nWarten: {r.layer_waits_s[i]:.2f} s")

    def _apply_layer_view(self, *_):
        self._layer_view_timer.stop()
        result = self._timing_result
        self.canvas.set_travel_layer_height(None if result is None else result.layer_heights_mm[self.layer_spin.value() - 1])
        self.canvas.set_layer_height(None if result is None or not (
            self._layer_focus_active or self.transparency_toggle.isChecked())
            else result.layer_heights_mm[self.layer_spin.value() - 1])
        self.canvas.set_layer_transparency_enabled(self.transparency_toggle.isChecked())

    def _clear_layer_focus(self):
        self._layer_view_timer.stop()
        self._layer_focus_active = False

    def _toggle_timing(self, visible):
        self.timing_panel.setVisible(visible and self._timing_result is not None)
        self.timing_toggle.setToolTip("Layerzeiten ausblenden" if visible else "Layerzeiten anzeigen")
        self._layout_timer.start(0)

    def _toggle_travel_visibility(self, visible):
        self.travel_visibility_button.setText("Fahrwege ausblenden" if visible else "Fahrwege anzeigen")
        self.canvas.set_wait_travel_visible(visible)
        self.canvas.set_tower_travel_visible(visible)
        self._show_travel_modes(visible and self.travel_visibility_button.isEnabled())

    def reset_layer(self):
        if self._timing_result is None:
            return
        self.select_layer(self.layer_spin.maximum(), activate_transparency=False)
        self._layer_focus_active = False
        self._apply_layer_view()

    def reset_preview(self):
        self._layer_view_timer.stop()
        self.travel_visibility_button.setChecked(True)
        self.travel_mode_toggle.setChecked(False)
        self.transparency_toggle.setChecked(True)
        self.canvas.set_cumulative_travel_visible(False)
        self.canvas.set_wait_position_visible(True)
        self.logarithmic_scale.setChecked(True)
        self.normalized_scale.setChecked(self.time_chart.default_normalization())
        self.reset_layer()
        self.canvas.set_navigation_enabled(True)
        self.three_quarter_view()

    def top_view(self):
        self.canvas.apply_camera_state({**self.canvas.camera_state(), "yaw_deg": 0, "pitch_deg": -89})
        self.canvas.fit_objects()

    def three_quarter_view(self):
        self.canvas.apply_camera_state({**self.canvas.camera_state(), "yaw_deg": self.canvas.separated_yaw(), "pitch_deg": -28})
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
        automatic = all(self.automatic[flag].isChecked() for flag in ("automatic_position", "automatic_wait_position"))
        with QSignalBlocker(self.positions_automatic):
            self.positions_automatic.setChecked(automatic)
        self.positions_button.setEnabled(not automatic)
        self._layout_timer.start(0)

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
        defaults = PostprocessorSettings()
        flag = next((flag for flag, names in AUTOMATIC_FIELDS.items() if name in names), None)
        widgets = dict(self.inputs, wall_count=self.wall_count_spin)
        for field in AUTOMATIC_FIELDS[flag] if flag else (name,):
            widget = widgets[field]
            with QSignalBlocker(widget):
                widget.setValue(getattr(defaults, field))
        if flag:
            with QSignalBlocker(self.automatic[flag]):
                self.automatic[flag].setChecked(getattr(defaults, flag))
            self.manual_position_edits.discard(flag)
        self._changed()

    def refresh_resets(self, *_):
        defaults = PostprocessorSettings()
        widgets = dict(self.inputs)
        if hasattr(self, "wall_count_spin"):
            widgets["wall_count"] = self.wall_count_spin
        for name, button in self.reset_buttons.items():
            flag = next((flag for flag, names in AUTOMATIC_FIELDS.items() if name in names), None)
            if flag:
                automatic = self.automatic[flag].isChecked()
                modified = automatic != getattr(defaults, flag) or (not automatic and any(
                    abs(widgets[field].value()-getattr(defaults, field)) > 1e-8 for field in AUTOMATIC_FIELDS[flag]))
            elif name == "hollow_tower":
                modified = not self.hollow_checkbox.isChecked()
            else:
                modified = abs(widgets[name].value() - getattr(defaults, name)) > 1e-8
            button.setProperty("modified", modified)
            button.setEnabled(modified)
            button.style().unpolish(button)
            button.style().polish(button)

    def reset(self):
        defaults = PostprocessorSettings()
        self.travel_visibility_button.setChecked(True)
        self.travel_mode_toggle.setChecked(False)
        self.transparency_toggle.setChecked(True)
        widgets = dict(self.inputs, wall_count=self.wall_count_spin, hollow_tower=self.hollow_checkbox, **self.automatic)
        for name, widget in widgets.items():
            with QSignalBlocker(widget):
                if isinstance(widget, QCheckBox):
                    widget.setChecked(getattr(defaults, name))
                else:
                    widget.setValue(getattr(defaults, name))
        self.exclusions = ()
        self.manual_position_edits.clear()
        self._changed()
