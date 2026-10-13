"""Embedded editor UI; all changes pass through the domain's atomic validator."""
from __future__ import annotations

from dataclasses import replace
from functools import partial
import math

from PySide6.QtCore import QSignalBlocker, QTimer, Qt, Signal, QSize, QPointF,QVariantAnimation,QEasingCurve
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, QLayout, QLabel, QPushButton, QSizePolicy,
                              QCheckBox, QScrollArea, QSplitter, QSlider, QProgressBar)

from cooling_tower.gui.widgets import SectionCard, WheelSafeComboBox
from cooling_tower.gui.widgets.manual_canvas import ManualCanvas
from cooling_tower.gui.widgets.manual_inputs import ManualDoubleSpinBox,ManualSpinBox,ManualNumericSettingWidget
from cooling_tower.gui.widgets.manual_preview_info import ManualPreviewInformation
from cooling_tower.gui.widgets.manual_resolution_control import ResolutionHeading,ResolutionSlider,ResolutionEndLabels
from cooling_tower.gui.widgets.manual_xray_controls import XRayControls,PreviewToolsRow
from cooling_tower.gui.widgets.manual_settings_pane import ManualSettingsPane
from cooling_tower.gui.widgets.manual_point_editor import ManualPointEditor,PointField
from cooling_tower.gui.design_tokens import COLORS,METRICS
from cooling_tower.manual.geometry import (ManualSettings, Coordinate, GeometryError, OBJECT_RESOLUTION_STAGES, object_resolution_default, bounded_edit, bounded_coordinate_edit, initial_draft,
                                          insert_point, move_point, remove_point, set_curve, reset_point_curves, couple_point, validate, validate_settings)
from cooling_tower.manual.layer_snap import snap_layer_height


class ManualGenerationPanel(QWidget):
    FORM_SETTINGS = ("minimum_diameter_mm","maximum_diameter_mm","foot_diameter_mm","maximum_foot_diameter_mm",
                     "foot_height_mm","circle_segments","expansion_enabled","expansion_angle_deg",
                     "contraction_enabled","contraction_angle_deg")
    draft_changed = Signal(object)
    generate_requested = Signal()
    export_requested = Signal()
    cancel_requested = Signal()
    retry_reference_requested = Signal()
    status_changed = Signal()
    layout_changed = Signal(bool)
    settings_visibility_changed = Signal()

    LABELS = {
        "color_reference_time_s": ("Farbreferenz für Original-Layer", "s", 5, 30),
        "minimum_diameter_mm": ("Minimaler Turm-Außendurchmesser", "mm", .1, 1000),
        "maximum_diameter_mm": ("Maximaler Turm-Außendurchmesser", "mm", .1, 1000),
        "top_diameter_mm": ("Außendurchmesser der Turmspitze", "mm", .1, 1000),
        "base_diameter_mm": ("Grunddurchmesser am Körperbeginn", "mm", .1, 1000),
        "foot_diameter_mm": ("Aktueller Fuß-Außendurchmesser", "mm", .1, 1000),
        "maximum_foot_diameter_mm": ("Maximaler Fuß-Außendurchmesser", "mm", .1, 1000),
        "foot_height_mm": ("Standfußhöhe (ab Druckbett)", "mm", .05, 1000),
        "height_mm": ("Obere Turmhöhe (ab Druckbett)", "mm", .1, 1000),
        "circle_segments": ("Turm-Kreissegmente", "", 12, 720),
        "expansion_angle_deg": ("Maximaler Aufweitungswinkel", "°", .1, 89),
        "contraction_angle_deg": ("Maximaler Verjüngungswinkel", "°", .1, 89),
        "overhang_angle_deg": ("Visueller Überhang-Grenzwinkel", "°", .1, 89),
        "gradient_start_deficit_s": ("Layerdefizit: Farbbeginn", "s", 0, 29.9),
        "gradient_full_deficit_s": ("Layerdefizit: vollständig Rot", "s", .1, 30),
        "point_diameter_mm": ("Ausgewählter Punkt: Außendurchmesser", "mm", .01, 1000),
        "point_height_mm": ("Ausgewählter Punkt: Höhe", "mm", .001, 1000),
        "control_diameter_mm": ("Kurvengriff: Durchmesserposition", "mm", .01, 1000),
        "control_height_mm": ("Kurvengriff: Höhe", "mm", .001, 1000),
    }

    def __init__(self, settings=None, parent=None):
        super().__init__(parent)
        self.setObjectName("manualGenerationPanel")
        self.settings = settings or ManualSettings()
        self._resolution_default_percent = object_resolution_default()
        self.draft = self.reference = self.initial = None
        self.selected = ""
        self._busy = False
        self._interaction_feedback = set()
        self._syncing = False
        self._point_defaults = {}
        self._control_defaults = {}
        self._settings_collapsed = False
        self._settings_transitioning = False
        self._settings_horizontal_extent = 480
        self._settings_vertical_extent = 360
        self._settings_scroll_position = 0
        self.rows, self.editors, self.checks = {}, {}, {}
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0,0,0,0)
        layout.setSizeConstraint(QLayout.SizeConstraint.SetNoConstraint)
        self.splitter = QSplitter(Qt.Orientation.Horizontal)
        self.splitter.setObjectName("layerRangeSplitter")
        self.splitter.setHandleWidth(1)
        self.splitter.setChildrenCollapsible(False)
        layout.addWidget(self.splitter,1)
        self.settings_scroll = QScrollArea()
        self.settings_scroll.setWidgetResizable(True)
        self.settings_scroll.setSizePolicy(QSizePolicy.Policy.Preferred,QSizePolicy.Policy.Ignored)
        self.settings_scroll.setMinimumWidth(460)
        self.settings_scroll.setFrameShape(QScrollArea.Shape.NoFrame)
        self.settings_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.settings_content = QWidget()
        form = QVBoxLayout(self.settings_content)
        form.setContentsMargins(0,0,14,0)
        self.settings_scroll.setWidget(self.settings_content)
        self.settings_pane = ManualSettingsPane(self.settings_scroll)
        self.settings_collapse_button = self.settings_pane.button
        self.settings_pane.toggle_requested.connect(self.toggle_settings)
        self.splitter.addWidget(self.settings_pane)
        for title, names in (
            ("Turm und Standfuß", ("minimum_diameter_mm","maximum_diameter_mm","base_diameter_mm","foot_diameter_mm",
                                  "maximum_foot_diameter_mm","foot_height_mm","height_mm","top_diameter_mm","circle_segments")),
            ("Geometrische Winkelgrenzen", ("expansion_angle_deg","contraction_angle_deg")),
            ("Ausgewählter Profilpunkt und Kurve", ("point_diameter_mm","point_height_mm","control_diameter_mm","control_height_mm")),
            ("Visuelle Prüfung", ("overhang_angle_deg","color_reference_time_s","gradient_start_deficit_s","gradient_full_deficit_s"))):
            card = SectionCard(title)
            form.addWidget(card)
            for name in names:
                if name in {"expansion_angle_deg","contraction_angle_deg","overhang_angle_deg"}:
                    option = name.replace("_angle_deg","_enabled")
                    text = {"expansion_enabled":"Aufweitung begrenzen", "contraction_enabled":"Verjüngung begrenzen",
                            "overhang_enabled":"Überhangstellen visuell markieren"}[option]
                    box = QCheckBox(text)
                    box.pressed.connect(self._begin_interaction)
                    box.released.connect(self._end_interaction)
                    box.toggled.connect(partial(self.change_setting,option))
                    self.checks[option] = box
                    card.content_layout.addWidget(box)
                card.content_layout.addWidget(self._numeric(name))
            if title == "Turm und Standfuß":
                self.height_note = QLabel()
                self.height_note.setWordWrap(True)
                card.content_layout.addWidget(self.height_note)
            elif title.startswith("Ausgewählter"):
                box = QCheckBox("Vertikale Greifer auf Layer einrasten")
                box.setToolTip("Aktiv: Greifer rasten auf Druckschichten ein. Aus: Höhen stufenlos ziehen. Zahlenfelder bleiben frei eingebbar.")
                box.toggled.connect(partial(self.change_setting,"layer_snap_enabled"))
                self.checks["layer_snap_enabled"] = box
                card.content_layout.insertWidget(0,box)
                self.selection_label = QLabel("Greifer auswählen oder Profil doppelklicken.")
                self.selection_label.setWordWrap(True)
                card.content_layout.insertWidget(0,self.selection_label)
                self.segment_combo = WheelSafeComboBox()
                self.segment_combo.addItems(["Ausgehender Abschnitt: gerade", "Ausgehender Abschnitt: Bézierkurve"])
                self.segment_combo.currentIndexChanged.connect(self._segment_changed)
                card.content_layout.addWidget(self.segment_combo)
                self.smooth_checkbox = QCheckBox("Tangenten am ausgewählten Punkt koppeln")
                self.smooth_checkbox.toggled.connect(self._smooth_changed)
                card.content_layout.addWidget(self.smooth_checkbox)
                buttons = QHBoxLayout()
                self.add_point_button = QPushButton("Punkt hinzufügen")
                self.remove_point_button = QPushButton("Punkt entfernen")
                self.add_point_button.clicked.connect(self.add_point)
                self.remove_point_button.clicked.connect(lambda: self.remove(self.selected))
                buttons.addWidget(self.add_point_button)
                buttons.addWidget(self.remove_point_button)
                card.content_layout.addLayout(buttons)
            elif title == "Visuelle Prüfung":
                box = QCheckBox("Kritische Original-Layer anzeigen")
                box.toggled.connect(partial(self.change_setting,"critical_layers_enabled"))
                self.checks["critical_layers_enabled"] = box
                card.content_layout.insertWidget(0,box)
                self.overhang_note = QLabel()
                self.overhang_note.setWordWrap(True)
                card.content_layout.addWidget(self.overhang_note)
                self.critical_note = QLabel()
                self.critical_note.setWordWrap(True)
                card.content_layout.addWidget(self.critical_note)
        self.reset_button = QPushButton("Alles zurücksetzen")
        self.reset_button.clicked.connect(self.reset_all)
        form.addWidget(self.reset_button)
        form.addStretch()

        preview = QWidget()
        preview.setSizePolicy(QSizePolicy.Policy.Expanding,QSizePolicy.Policy.Ignored)
        self.preview_container = preview
        preview_layout = QVBoxLayout(preview)
        preview_layout.setContentsMargins(14,0,0,0)
        preview_layout.setSizeConstraint(QLayout.SizeConstraint.SetNoConstraint)
        self.highlight_host = XRayControls()
        self.highlight_title = self.highlight_host.title
        self.highlight_group = self.highlight_host.group
        self.highlight_buttons = self.highlight_host.buttons
        self.highlight_host.choice_changed.connect(lambda choice:self.canvas.set_highlight(choice))
        self.resolution_host = QWidget()
        self.resolution_host.setSizePolicy(QSizePolicy.Policy.Expanding,QSizePolicy.Policy.Fixed)
        resolution_group = QVBoxLayout(self.resolution_host)
        resolution_group.setContentsMargins(0,0,0,0)
        resolution_group.setSpacing(1)
        self.resolution_heading = ResolutionHeading()
        self.resolution_title = self.resolution_heading.title
        resolution_header = QHBoxLayout()
        resolution_header.setSpacing(3)
        resolution_header.addWidget(self.resolution_heading,1)
        resolution_group.addLayout(resolution_header)
        resolution = QHBoxLayout()
        resolution.setContentsMargins(0,0,0,0)
        resolution.setSpacing(3)
        slider_host=QWidget()
        slider_column=QVBoxLayout(slider_host)
        slider_column.setContentsMargins(0,0,0,0)
        slider_column.setSpacing(0)
        self.resolution_end_labels=ResolutionEndLabels()
        slider_column.addWidget(self.resolution_end_labels)
        self.resolution_slider = ResolutionSlider()
        self.resolution_slider.setFixedHeight(20)
        self.resolution_slider.setMinimumWidth(65)
        self.resolution_slider.setToolTip("Performance → Optik:\n"+", ".join(map(str,OBJECT_RESOLUTION_STAGES))+" %.\n"
            "0 %: hochauflösende Silhouette.\n"
            "Über 0 %: automatische Netzqualität mit geschützter Mindestqualität.\n"
            "Der Wert gewichtet Performance und Optik, nicht den Anteil der Flächen.\n"
            "Analyse und Druckdaten bleiben gleich.")
        self.resolution_slider.setRange(1,len(OBJECT_RESOLUTION_STAGES))
        self.resolution_slider.setTickPosition(QSlider.TickPosition.TicksBelow)
        self.resolution_slider.setTickInterval(1)
        self.resolution_slider.setSingleStep(1)
        # Stop positions follow the slider stages; colors follow their real
        # percentages, keeping the many low-resolution stages predominantly green.
        colors = (QColor("#41a878"),QColor("#e5bf48"),QColor("#e5484d"))
        stops = []
        for index,percent in enumerate(OBJECT_RESOLUTION_STAGES):
            if percent == 0:
                stops.append("stop:0 #8dc9f4")
                continue
            first,last = colors[:2] if percent <= 50 else colors[1:]
            fraction = percent/50 if percent <= 50 else (percent-50)/50
            rgb = [round(a+(b-a)*fraction) for a,b in zip(first.getRgb()[:3],last.getRgb()[:3])]
            stops.append(f"stop:{index/(len(OBJECT_RESOLUTION_STAGES)-1):.6f} {QColor(*rgb).name()}")
        self.resolution_slider.setStyleSheet(
            "QSlider::groove:horizontal { height: 4px; border: none; border-radius: 2px; "
            "background: qlineargradient(x1:0, y1:0, x2:1, y2:0, "+", ".join(stops)+"); } "
            "QSlider::sub-page:horizontal, QSlider::add-page:horizontal { background: transparent; border: none; } "
            "QSlider::handle:horizontal { width: 10px; margin: -4px 0; border: 2px solid #536980; "
            "border-radius: 6px; background: #f8fbfd; }")
        self.resolution_slider.valueChanged.connect(lambda value:self.change_setting("object_resolution_percent",OBJECT_RESOLUTION_STAGES[value-1]))
        slider_column.addWidget(self.resolution_slider)
        resolution.addWidget(slider_host,1)
        self.resolution_label = QLabel()
        self.resolution_label.setStyleSheet("font-size: 8pt; padding: 0;")
        self.resolution_label.setMinimumWidth(self.resolution_label.fontMetrics().horizontalAdvance("100 %"))
        resolution_group.addLayout(resolution)
        value_host=QWidget()
        value_column=QVBoxLayout(value_host)
        value_column.setContentsMargins(0,0,0,0)
        value_column.setSpacing(0)
        value_column.addSpacing(self.resolution_end_labels.height())
        value_column.addWidget(self.resolution_label,1)
        resolution.addWidget(value_host)
        self.resolution_reset = QPushButton("↺")
        self.resolution_reset.setObjectName("settingResetButton")
        self.resolution_reset.setFixedSize(METRICS.reset_button_size_px,METRICS.reset_button_size_px)
        self.resolution_reset.setAccessibleName("Auflösung des Originalobjekts zurücksetzen")
        self.resolution_reset.setToolTip("Standardauflösung des Originalobjekts wiederherstellen")
        self.resolution_reset.clicked.connect(lambda:self.change_setting("object_resolution_percent",self.default_value("object_resolution_percent")))
        resolution.addWidget(self.resolution_reset)
        resolution_header.addSpacing(self.resolution_label.minimumWidth()+self.resolution_reset.width()+6)
        self.rotation_host = QWidget()
        self.rotation_host.setSizePolicy(QSizePolicy.Policy.Expanding,QSizePolicy.Policy.Fixed)
        rotation_group = QVBoxLayout(self.rotation_host)
        rotation_group.setContentsMargins(0,0,0,0)
        rotation_group.setSpacing(1)
        self.rotation_title = QLabel("Originalobjekt drehen")
        self.rotation_title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.rotation_title.setStyleSheet("font-size: 8pt; padding: 0;")
        rotation_group.addWidget(self.rotation_title)
        rotation = QHBoxLayout()
        rotation.setSpacing(3)
        self.rotation_slider = QSlider(Qt.Orientation.Horizontal)
        self.rotation_slider.setMinimumWidth(50)
        self.rotation_slider.setRange(-180,180)
        self.rotation_slider.setTickPosition(QSlider.TickPosition.TicksBelow)
        self.rotation_slider.setTickInterval(45)
        self.rotation_slider.setToolTip("Originalobjekt drehen: −180° bis +180° · 0° in der Mitte · Rastpunkte alle 45°")
        self.rotation_slider.valueChanged.connect(self._queue_rotation)
        rotation.addWidget(self.rotation_slider,1)
        self.rotation_label = QLabel("0,00°")
        self.rotation_label.setStyleSheet("font-size: 8pt; padding: 0;")
        rotation.addWidget(self.rotation_label)
        self.rotation_reset = QPushButton("↺")
        self.rotation_reset.setObjectName("settingResetButton")
        self.rotation_reset.setFixedSize(METRICS.reset_button_size_px,METRICS.reset_button_size_px)
        self.rotation_reset.setProperty("modified",False)
        self.rotation_reset.setEnabled(False)
        self.rotation_reset.setAccessibleName("Objektdrehung zurücksetzen")
        self.rotation_reset.setToolTip("Originalorientierung wiederherstellen")
        self.rotation_reset.clicked.connect(self.reset_rotation)
        rotation.addWidget(self.rotation_reset)
        rotation_group.addLayout(rotation)
        self.preview_tools = PreviewToolsRow(self.highlight_host,self.resolution_host,self.rotation_host)
        preview_layout.addWidget(self.preview_tools)
        self.canvas = ManualCanvas()
        self.point_editor = ManualPointEditor(self.canvas,self._validate_point_value,self._apply_point_value)
        self.canvas.point_editor = self.point_editor
        self.canvas.view_state_changed.connect(lambda:self.reset_button.setEnabled(self.can_reset_all()))
        self.canvas.view_state_changed.connect(lambda:self.highlight_host.set_choice(self.canvas.highlight))
        self.view_buttons = self.canvas.view_controls.view_buttons
        self.fit_button = self.canvas.view_controls.fit_button
        self.canvas.move_requested.connect(self._move_from_canvas)
        self.canvas.control_requested.connect(self._control_from_canvas)
        self.canvas.selection_changed.connect(self.select)
        self.canvas.insert_requested.connect(self.insert)
        self.canvas.validate_insertion = self._validate_insertion
        self.canvas.remove_requested.connect(self.remove)
        self.canvas.curve_reset_requested.connect(self.reset_point_curves)
        self.canvas.interaction_started.connect(self._begin_interaction)
        self.canvas.interaction_finished.connect(self._end_interaction)
        self.canvas.view_changed.connect(self._view_changed)
        preview_layout.addWidget(self.canvas,1)
        self._rotation_timer = QTimer(self)
        self._rotation_timer.setSingleShot(True)
        self._rotation_timer.setInterval(16)
        self._rotation_timer.timeout.connect(lambda:self.canvas.set_rotation(self.rotation_slider.value()))
        self.preview_information = ManualPreviewInformation()
        self.view_hint = self.preview_information.instructions
        preview_layout.addWidget(self.preview_information)
        self.result_label = QLabel()
        self.result_label.setWordWrap(True)
        preview_layout.addWidget(self.result_label)
        self.status_label = QLabel()
        self.status_label.setWordWrap(True)
        preview_layout.addWidget(self.status_label)
        self.progress = QProgressBar()
        self.progress.hide()
        preview_layout.addWidget(self.progress)
        self.action_hint = QLabel()
        self.action_hint.setWordWrap(True)
        preview_layout.addWidget(self.action_hint)
        self.actions_host = QWidget()
        actions = QHBoxLayout(self.actions_host)
        actions.setContentsMargins(0,0,0,0)
        actions.addStretch()
        self.retry_button = QPushButton("Vorschau erneut vorbereiten")
        self.retry_button.clicked.connect(self.retry_reference_requested)
        self.retry_button.hide()
        actions.addWidget(self.retry_button)
        self.generate_button = QPushButton("Kühlturm generieren")
        self.generate_button.setObjectName("previewButton")
        self.generate_button.setStyleSheet(f"QPushButton {{ background: {COLORS['primary']}; color: white; padding: 9px 12px; border-radius: 6px; }} QPushButton:disabled {{ background: #c5d2df; color: #526274; }}")
        self.generate_button.clicked.connect(self.generate_requested)
        actions.addWidget(self.generate_button)
        self.export_button = QPushButton("Kühlturm exportieren")
        self.export_button.setObjectName("exportButton")
        self.export_button.clicked.connect(self.export_requested)
        actions.addWidget(self.export_button)
        self.cancel_button = QPushButton("Abbrechen")
        self.cancel_button.setStyleSheet("QPushButton { background: #b42318; color: white; padding: 9px; }")
        self.cancel_button.clicked.connect(self.cancel_requested)
        actions.addWidget(self.cancel_button)
        preview_layout.addWidget(self.actions_host)
        self.splitter.addWidget(preview)
        self.splitter.setStretchFactor(1,1)
        self.splitter.setSizes([480,850])
        self._settings_animation = QVariantAnimation(self)
        self._settings_animation.setDuration(250)
        self._settings_animation.setEasingCurve(QEasingCurve.Type.InOutCubic)
        self._settings_animation.valueChanged.connect(self._animate_settings_extent)
        self._settings_animation.finished.connect(self._finish_settings_animation)
        self._sync()
        self.set_actions(False,False,False,False)
        self._view_changed("side")

    def _numeric(self,name):
        label,unit,lo,hi = self.LABELS[name]
        spin = ManualSpinBox() if name == "circle_segments" else ManualDoubleSpinBox()
        spin.setRange(lo,hi)
        if name != "circle_segments":
            spin.setDecimals(6)
            spin.set_display_decimals(2)
            spin.setSingleStep(.1 if unit in {"mm","s"} else 1)
        row = ManualNumericSettingWidget(setting_name=name,label=label,editor=spin,unit=unit,
                                   default_provider=lambda:self.default_value(name),
                                   info_text="Alle Breiten sind Außendurchmesser. Fußhöhe und Turmhöhe sind absolute Z-Höhen über dem Druckbett." if unit == "mm" else
                                   "Winkel zur Vertikalen; lokale Radiussteigung. Die visuelle Prüfung verändert keine Geometrie." if unit == "°" else
                                   "Gleiche Kreissegmentzahl für alle STL-Ringe; unabhängig von Drucklayern und Kurvenunterteilungen." if name == "circle_segments" else "")
        row.set_feedback_enabled(True)
        row.error_feedback_finished.connect(lambda:self._interaction_feedback.discard(name))
        row.reset_button.clicked.disconnect()
        row.reset_button.clicked.connect(lambda:self.reset_value(name))
        spin.setKeyboardTracking(False)
        spin.valueChanged.connect(partial(self._numeric_changed,name))
        spin.limit_attempted.connect(lambda value:self._numeric_changed(name,int(value) if name == "circle_segments" else value))
        spin.lineEdit().editingFinished.connect(partial(self._detect_numeric_attempt,name))
        self.rows[name],self.editors[name] = row,spin
        return row

    def default_value(self,name):
        if name == "object_resolution_percent":
            return object_resolution_default(self.canvas.view)
        if name.startswith("point_"):
            selected = self.canvas.information_identity() if hasattr(self,"canvas") else self.selected
            identity = "base" if selected == "foot_height" else "top" if selected == "top_width" else selected
            if self.draft is not None and any(p.identity == identity and p.kind == "free" for p in self.draft.points):
                return None
            p = self._point_defaults.get(identity)
            if p: return p.diameter_mm if name == "point_diameter_mm" else p.z_mm
        if name.startswith("control_") and self.draft is not None:
            control = self._selected_control()
            if control:
                i,n = control
                p = self._control_defaults.get((self.draft.points[i].identity,n))
                if p: return p.diameter_mm if name == "control_diameter_mm" else p.z_mm
        if self.initial is not None:
            if name == "base_diameter_mm": return self.initial.base_diameter_mm
            if name == "height_mm": return self.initial.height_mm
            if name == "top_diameter_mm": return self.initial.points[-1].position.diameter_mm
            if hasattr(self.initial.settings,name): return getattr(self.initial.settings,name)
        value = getattr(ManualSettings(),name,None)
        return value if value is not None else 25 if name == "circle_segments" else 0.1

    def initialize(self,reference,settings=None):
        self.reference = reference
        self.selected = self.canvas.selected = ""
        s = settings or self.settings
        limit = reference.context.maximum_foot_diameter_mm
        if limit < s.minimum_diameter_mm+2-1e-9:
            raise GeometryError("maximum_foot_diameter_mm", "Für den Standfuß ist neben dem Originalobjekt nicht genügend freie Druckbettfläche vorhanden.")
        s = replace(s,maximum_foot_diameter_mm=limit,foot_diameter_mm=min(s.foot_diameter_mm,limit))
        draft = initial_draft(s,reference.context.layers,reference.context.maximum_height_mm,reference.context.key)
        if draft.foot_diameter_mm > limit:
            draft = initial_draft(s,reference.context.layers,reference.context.maximum_height_mm,reference.context.key,foot_diameter_mm=limit)
        default_foot_limit = limit
        self.initial = initial_draft(replace(ManualSettings(),overhang_angle_deg=s.overhang_angle_deg,
                                           minimum_diameter_mm=min(ManualSettings().minimum_diameter_mm,limit-2),
                                           maximum_foot_diameter_mm=default_foot_limit,
                                           foot_diameter_mm=draft.foot_diameter_mm,
                                           object_resolution_percent=self.default_value("object_resolution_percent")),
                                     reference.context.layers,reference.context.maximum_height_mm,reference.context.key,
                                     foot_diameter_mm=draft.foot_diameter_mm)
        reference.context.validate(draft)
        self.canvas.set_reference(reference)
        self.height_note.setText(reference.context.height_note)
        self.retry_button.hide()
        self._point_defaults = {p.identity:p.position for p in draft.points if p.kind != "free"}
        self._control_defaults = {(draft.points[i].identity,n):getattr(c,f"control{n}") for i,c in enumerate(draft.curves) for n in (1,2)}
        self.commit(draft)

    def commit(self,draft):
        if (self.initial is not None and self.draft is not None and
                self.draft.context_key == draft.context_key and
                draft.foot_diameter_mm > self.draft.settings.maximum_foot_diameter_mm and
                draft.settings.maximum_foot_diameter_mm == draft.foot_diameter_mm):
            self.initial = replace(self.initial,settings=replace(self.initial.settings,
                                   maximum_foot_diameter_mm=draft.settings.maximum_foot_diameter_mm))
        self.draft,self.settings = draft,draft.settings
        self.canvas.set_draft(draft)
        self._sync()
        self.generate_button.setEnabled(not self._busy)
        self.draft_changed.emit(draft)

    def _sync(self):
        self._syncing = True
        s = self.settings
        values = s.to_dict()
        if self.draft:
            values.update(base_diameter_mm=self.draft.base_diameter_mm,height_mm=self.draft.height_mm,
                          top_diameter_mm=self.draft.points[-1].position.diameter_mm)
            point = next((p for p in self.draft.points if p.identity == ("top" if self.selected == "top_width" else self.selected)),None)
            if not self.selected:self.selection_label.setText("Kein Profilpunkt ausgewählt")
            if point:
                values.update(point_diameter_mm=point.position.diameter_mm,point_height_mm=point.position.z_mm)
                self.selection_label.setText(f"{'Freier Profilpunkt' if point.kind == 'free' else {'foot':'Fußrand','base':'Körperbeginn','top':'Oberer Abschluss'}[point.kind]} · {point.position.z_mm:.2f} mm")
            if self.selected == "foot_height":
                p = self.draft.points[1]
                values.update(point_diameter_mm=p.position.diameter_mm,point_height_mm=p.position.z_mm)
                self.selection_label.setText("Fußübergang · vertikal verschieben")
            if self.selected in self.canvas.LIMITS:
                self.selection_label.setText(self.LABELS[self.selected][0]+" · horizontal verschieben")
            control = self._selected_control()
            if control:
                i,n = control
                p = getattr(self.draft.curves[i],f"control{n}")
                values.update(control_diameter_mm=p.diameter_mm,control_height_mm=p.z_mm)
                self.selection_label.setText(f"Bézier-Kontrollgriff {n} · Abschnitt {i+1}")
            self.rows["control_diameter_mm"].setVisible(control is not None)
            self.rows["control_height_mm"].setVisible(control is not None)
            self.rows["point_diameter_mm"].setVisible(control is None)
            self.rows["point_height_mm"].setVisible(control is None)
            self.editors["point_diameter_mm"].setEnabled(point is not None and (point.kind != "top" or self.selected == "top_width"))
            self.editors["point_height_mm"].setEnabled(self.selected == "foot_height" or (point is not None and (point.kind == "free" or self.selected == "top")))
            self.remove_point_button.setEnabled(point is not None and point.kind == "free")
            self.smooth_checkbox.setEnabled(point is not None and point.kind in {"base","free"})
            with QSignalBlocker(self.smooth_checkbox): self.smooth_checkbox.setChecked(point.smooth if point else False)
            index = self._segment_index()
            self.segment_combo.setEnabled(index is not None and index > 0)
            with QSignalBlocker(self.segment_combo):
                self.segment_combo.setCurrentIndex(int(self.draft.curves[index].curved) if index is not None else 0)
            self.critical_note.setText(f"Die Farben vergleichen ausschließlich die Original-Layer mit der Farbreferenz von {s.color_reference_time_s:g} s; sie bewerten nicht den manuellen Turm.")
        for name,spin in self.editors.items():
            with QSignalBlocker(spin):
                value = values.get(name,self.default_value(name))
                spin.setValue(value if value is not None else 25)
            self.rows[name].refresh_reset_state()
        for name,box in self.checks.items():
            with QSignalBlocker(box): box.setChecked(getattr(s,name))
        with QSignalBlocker(self.resolution_slider):
            self.resolution_slider.setValue(OBJECT_RESOLUTION_STAGES.index(s.object_resolution_percent)+1)
        self.resolution_label.setText(f"{s.object_resolution_percent} %")
        self._refresh_resolution_reset()
        self.preview_information.set_state(self.canvas.view,s.critical_layers_enabled)
        self._syncing = False
        self._apply_view_editability()
        self.point_editor.sync_fields(self.canvas.information_identity(),self._point_fields(),self.canvas.selected_handle_text(),not self._busy)

    def _point_fields(self):
        if self.draft is None:return ()
        selected = self.canvas.information_identity()
        names={"foot":("foot_diameter_mm",),"base":("base_diameter_mm",),
               "foot_height":("foot_height_mm",),"top":("height_mm",),
               "top_width":("top_diameter_mm",)}.get(selected)
        values={**self.settings.to_dict(),"base_diameter_mm":self.draft.base_diameter_mm,
                "height_mm":self.draft.height_mm,"top_diameter_mm":self.draft.points[-1].position.diameter_mm}
        if selected in self.canvas.LIMITS:names=(selected,)
        elif names is None:
            point=next((p for p in self.draft.points if p.identity==selected and p.kind=="free"),None)
            if point:
                names=("point_diameter_mm","point_height_mm")
                values.update(point_diameter_mm=point.position.diameter_mm,point_height_mm=point.position.z_mm)
        short={"minimum_diameter_mm":"Min. Turm-Ø","maximum_diameter_mm":"Max. Turm-Ø",
               "maximum_foot_diameter_mm":"Max. Fuß-Ø","base_diameter_mm":"Grund-Ø",
               "foot_diameter_mm":"Fuß-Ø","foot_height_mm":"Fußhöhe","height_mm":"Turmhöhe",
               "top_diameter_mm":"Spitzen-Ø","point_diameter_mm":"Durchmesser","point_height_mm":"Höhe",
               "control_diameter_mm":"Ø-Position","control_height_mm":"Höhe"}
        return tuple(PointField(name,short[name],values[name],self.default_value(name),self.LABELS[name][0])
                     for name in names or ())

    def _point_value_candidate(self,name,value):
        if self.draft is None or name not in {field.name for field in self._point_fields()}:
            raise GeometryError(name,"Dieser Greifer kann derzeit nicht bearbeitet werden.")
        _,_,low,high=self.LABELS[name]
        if not math.isfinite(value) or not low<=value<=high:
            raise GeometryError(name,f"Der Wert muss zwischen {low:g} und {high:g} mm liegen.")
        if name in self.canvas.LIMITS:
            return self._checked(validate(replace(self.draft,settings=replace(self.settings,**{name:value}))))
        if name.startswith("control_"):
            i,n=self._selected_control();position=getattr(self.draft.curves[i],f"control{n}")
            position=Coordinate(value/2,position.z_mm) if name=="control_diameter_mm" else Coordinate(position.radius_mm,value)
            return self._checked(set_curve(self.draft,i,control=n,position=position))
        identity={"base_diameter_mm":"base","foot_diameter_mm":"foot","foot_height_mm":"base",
                  "height_mm":"top","top_diameter_mm":"top"}.get(name,self.canvas.information_identity())
        position=next(p.position for p in self.draft.points if p.identity==identity)
        diameter=value if name.endswith("diameter_mm") else position.diameter_mm
        height=value if name.endswith("height_mm") else position.z_mm
        return self._checked(move_point(self.draft,identity,diameter_mm=diameter,z_mm=height))

    def _validate_point_value(self,name,value):
        # A dry run uses the complete geometry and placement validators.
        # Accepted values alone are committed; typing never moves a handle.
        try:self._point_value_candidate(name,value)
        except (GeometryError,ValueError) as error:return str(error)
        return None

    def _apply_point_value(self,name,value):
        current=next((field.value for field in self._point_fields() if field.name==name),None)
        if self._busy or current is None:return False
        if value==current:return True
        try:candidate=self._point_value_candidate(name,value)
        except (GeometryError,ValueError) as error:
            self.feedback(error,name)
            return False
        self.status_label.clear();self.commit(candidate)
        return True

    def _checked(self,draft):
        self.reference.context.validate(draft)
        return draft

    def change_setting(self,name,value):
        if self._syncing or self._busy:
            return
        if self.draft is None:
            if self.reference is None: return
            try:
                settings = replace(self.settings,**{name:value})
                validate_settings(settings)
                self.settings = settings
                self.initialize(self.reference,settings)
            except (ValueError,RuntimeError) as error:
                self.feedback(error,name)
                self._sync()
            return
        try:
            s = replace(self.draft.settings,**{name:value},**({"overhang_user_set":True} if name == "overhang_angle_deg" else {}))
            candidate = self._checked(validate(replace(self.draft,settings=s)))
        except (GeometryError,ValueError) as error:
            self.feedback(error,name)
            self._sync()
            return
        self.status_label.clear()
        self.commit(candidate)

    def _numeric_changed(self,name,value):
        if self._syncing or self._busy: return
        if self.draft is None:
            if hasattr(self.settings,name): self.change_setting(name,value)
            return
        if name in {"base_diameter_mm","foot_diameter_mm","foot_height_mm","height_mm","top_diameter_mm"}:
            identity = {"base_diameter_mm":"base","foot_diameter_mm":"foot","foot_height_mm":"foot_height","height_mm":"top","top_diameter_mm":"top_width"}[name]
            p = self.draft.points[1 if identity == "foot_height" else 0 if identity == "foot" else -1 if identity in {"top","top_width"} else 1].position
            self.move(identity,value if name in {"base_diameter_mm","foot_diameter_mm","top_diameter_mm"} else p.diameter_mm,
                      value if name in {"height_mm","foot_height_mm"} else p.z_mm)
        elif name in {"point_diameter_mm","point_height_mm"}:
            self.move(self.selected,self.editors["point_diameter_mm"].value(),self.editors["point_height_mm"].value())
        elif name in {"control_diameter_mm","control_height_mm"}:
            control = self._selected_control()
            if control: self.move_control(*control,self.editors["control_diameter_mm"].value(),self.editors["control_height_mm"].value())
        else:
            self.change_setting(name,value)

    def _detect_numeric_attempt(self,name):
        # Domain bounds are deliberately wider than user-defined geometry
        # limits, so a typed attempt reaches the same validator as a drag.
        self._interaction_feedback.clear()

    def _move_from_canvas(self,identity,diameter,z):
        if self._busy or self.draft is None:
            return
        if identity in self.canvas.LIMITS:
            if self.canvas.horizontal_drag_snaps():
                self.move_limit(identity,diameter)
            return
        error = self.move(identity,diameter,z,layer_snap=self.canvas.vertical_drag_snaps(),
                          diameter_snap=self.canvas.horizontal_drag_snaps())
        actual_identity="top" if identity == "top_width" else identity
        point = next((p for p in self.draft.points if p.identity == actual_identity),None)
        if self.canvas.horizontal_drag_snaps():
            setting = None
            if error is not None and error.setting in {"minimum_diameter_mm","maximum_diameter_mm","maximum_foot_diameter_mm"}:
                setting = error.setting
            elif point is not None:
                bounds=("minimum_diameter_mm","maximum_foot_diameter_mm" if point.kind == "foot" else "maximum_diameter_mm")
                for name in bounds:
                    boundary = getattr(self.settings,name)
                    if math.isclose(point.position.diameter_mm,boundary,rel_tol=0,abs_tol=1e-7):
                        setting = name
                        break
            self.canvas.set_width_limit_feedback(setting,diameter)

    def move_limit(self,name,diameter):
        if self._busy or self.draft is None or name not in self.canvas.LIMITS:
            return
        old = self.draft
        start = getattr(old.settings,name)
        target = min(1000,max(.1,round(diameter*10)/10))
        def operation(value):
            return self._checked(validate(replace(old,settings=replace(old.settings,**{name:value}))))
        candidate,error = bounded_edit(old,lambda t:operation(start+(target-start)*t))
        if error:
            boundary = getattr(candidate.settings,name)*10
            snapped = (math.floor(boundary+1e-8) if target > start else math.ceil(boundary-1e-8))/10
            candidate = old
            # Try the adjacent grid value too: the bounded search returns a
            # safe approximation just before an exactly reachable boundary.
            adjacent = (math.ceil(boundary-1e-8) if target > start else math.floor(boundary+1e-8))/10
            for value in dict.fromkeys((adjacent,snapped)):
                if not min(start,target)-1e-8 <= value <= max(start,target)+1e-8:continue
                try:
                    candidate = operation(value)
                    break
                except GeometryError:
                    pass
            self.feedback(error,name)
        else:
            self.status_label.clear()
        self.commit(candidate)

    def _control_from_canvas(self,index,n,diameter,z):
        if self._busy or self.draft is None:return
        attempted_error=None
        origin=self.canvas.constrained_drag_origin() or self.draft
        try:self._checked(set_curve(origin,index,control=n,position=Coordinate(diameter/2,z)))
        except GeometryError as error:attempted_error=error
        error=self.move_control(index,n,diameter,z,layer_snap=self.canvas.vertical_drag_snaps(),
                          diameter_snap=self.canvas.horizontal_drag_snaps())
        self.canvas.set_control_limit_feedback(attempted_error or error,index,n,diameter,z)

    def _edit_coordinate(self,old,coordinate_for,destination,operation,layer_snap,diameter_snap):
        if not layer_snap and not diameter_snap:
            return bounded_coordinate_edit(old,coordinate_for,destination,operation)
        try:
            return operation(old,destination),None
        except GeometryError as error:
            limiting = error
        # A continuous boundary can sit between layers. Keep radial motion,
        # then stop on the last reachable layer instead of accepting that boundary.
        start = coordinate_for(old)
        horizontal,_ = bounded_coordinate_edit(old,coordinate_for,
            Coordinate(destination.radius_mm,start.z_mm),operation)
        if diameter_snap:
            boundary = coordinate_for(horizontal).radius_mm*20
            radius = (math.floor(boundary+1e-8) if destination.radius_mm > start.radius_mm
                      else math.ceil(boundary-1e-8))/20
            horizontal = old
            if min(start.radius_mm,destination.radius_mm)-1e-8 <= radius <= max(start.radius_mm,destination.radius_mm)+1e-8:
                try:
                    horizontal = operation(old,Coordinate(radius,start.z_mm))
                except GeometryError:
                    pass
        start = coordinate_for(horizontal)
        vertical,_ = bounded_coordinate_edit(horizontal,coordinate_for,
            Coordinate(start.radius_mm,destination.z_mm),operation)
        if not layer_snap:
            return vertical,limiting
        boundary = coordinate_for(vertical).z_mm
        lower,upper=min(start.z_mm,destination.z_mm),max(start.z_mm,destination.z_mm)
        direction=-1 if destination.z_mm > start.z_mm else 1
        z = snap_layer_height(boundary,self.canvas._layer_tops,
            lower=lower,upper=upper,direction=direction)
        while z is not None:
            try:
                return operation(horizontal,Coordinate(start.radius_mm,z)),limiting
            except GeometryError:
                # Endpoint derivatives impose open bounds. A layer numerically
                # on that boundary can fail; try the next layer toward the
                # original valid height instead of abandoning all motion.
                if direction>0:lower=z+1e-7
                else:upper=z-1e-7
                z=snap_layer_height(boundary,self.canvas._layer_tops,lower=lower,upper=upper,direction=direction)
        return horizontal,limiting

    def move(self,identity,diameter,z,*,layer_snap=False,diameter_snap=False):
        if self._busy or self.draft is None: return
        actual = "base" if identity == "foot_height" else "top" if identity == "top_width" else identity
        p = next((p for p in self.draft.points if p.identity == actual),None)
        if p is None: return
        if identity in {"base","top_width"}: z = p.position.z_mm
        if identity in {"foot_height","top"}: diameter = p.position.diameter_mm
        if diameter_snap:
            diameter = round(diameter*10)/10
        old = self.canvas.constrained_drag_origin() or self.draft
        candidate,error = self._edit_coordinate(
            old, lambda d: next(point.position for point in d.points if point.identity == actual),
            Coordinate(diameter/2,z),
            lambda d,pos: self._checked(move_point(d,actual,diameter_mm=pos.diameter_mm,z_mm=pos.z_mm)),layer_snap,diameter_snap)
        if error: self.feedback(error,"point_height_mm")
        else: self.status_label.clear()
        self.commit(candidate)
        return error

    def move_control(self,index,n,diameter,z,*,layer_snap=False,diameter_snap=False):
        if self._busy or self.draft is None: return
        if diameter_snap:
            diameter = round(diameter*10)/10
        old = self.canvas.constrained_drag_origin() or self.draft
        candidate,error = self._edit_coordinate(
            old, lambda d: getattr(d.curves[index],f"control{n}"), Coordinate(diameter/2,z),
            lambda d,pos: self._checked(set_curve(d,index,control=n,position=pos)),layer_snap,diameter_snap)
        if error: self.feedback(error,"control_height_mm")
        else: self.status_label.clear()
        self.commit(candidate)

        return error

    def select(self,identity):
        self.selected = self.canvas.selected = identity
        if not identity:
            self.canvas._revealed_control_anchor=None
            self.canvas.hovered=None
        self._sync()
        self.canvas.update()

    def reset_point_curves(self,identity):
        if self._busy or self.draft is None: return
        try:
            candidate = self._checked(reset_point_curves(self.draft,identity))
        except GeometryError as error:
            self.feedback(error,"points")
            return
        self.selected = self.canvas.selected = identity
        self.canvas._revealed_control_anchor = {"foot_height":"base","top_width":"top"}.get(identity,identity)
        for i,curve in enumerate(candidate.curves):
            if curve != self.draft.curves[i]:
                for n in (1,2):
                    self._control_defaults[(candidate.points[i].identity,n)] = getattr(curve,f"control{n}")
        self.commit(candidate)

    def _selected_control(self):
        return tuple(map(int,self.selected.split(":")[1:])) if self.selected.startswith("control:") else None

    def _segment_index(self):
        if self.selected in {"foot","foot_height"}: return 0
        if self.selected in {"top","top_width"} and self.draft is not None: return len(self.draft.curves)-1
        control = self._selected_control()
        if control: return control[0]
        return next((i for i,p in enumerate(self.draft.points[:-1]) if p.identity == ("top" if self.selected == "top_width" else self.selected)),None) if self.draft else None

    def _segment_changed(self,index):
        if self._syncing or self._busy or self.draft is None: return
        i = self._segment_index()
        if i is not None:
            try: self.commit(self._checked(set_curve(self.draft,i,curved=bool(index))))
            except GeometryError as e: self.feedback(e,"points"); self._sync()

    def _smooth_changed(self,enabled):
        if self._syncing or self._busy or self.draft is None: return
        try: self.commit(self._checked(couple_point(self.draft,self.selected,enabled)))
        except GeometryError as e: self.feedback(e,"points"); self._sync()

    def insert(self,z):
        if self._busy or self.draft is None: return
        try:
            draft,identity = insert_point(self.draft,z)
            self._checked(draft)
        except GeometryError as e:
            self.feedback(e,"point_height_mm")
            return
        self.selected = self.canvas.selected = identity
        self.canvas._revealed_control_anchor = identity
        for i,c in enumerate(draft.curves):
            for n in (1,2): self._control_defaults.setdefault((draft.points[i].identity,n),getattr(c,f"control{n}"))
        self.commit(draft)

    def _validate_insertion(self,z):
        if self._busy or self.draft is None:return False
        try:self._checked(insert_point(self.draft,z)[0])
        except (GeometryError,ValueError):return False
        return True

    def add_point(self):
        if self.draft is None: return
        i = self._segment_index()
        i = max(1,i or 1)
        c = self.draft.curves[min(i,len(self.draft.curves)-1)]
        self.insert((c.start.z_mm+c.end.z_mm)/2)

    def remove(self,identity):
        if self._busy or self.draft is None: return
        try:
            index = next(i for i,p in enumerate(self.draft.points) if p.identity == identity)
            draft = self._checked(remove_point(self.draft,identity))
        except (GeometryError,StopIteration) as e:
            self.feedback(e,"points")
            return
        self.selected = self.canvas.selected = "base"
        self._point_defaults.pop(identity,None)
        self._control_defaults = {key:value for key,value in self._control_defaults.items() if key[0] != identity}
        for n in (1,2):
            self._control_defaults[(draft.points[index-1].identity,n)] = getattr(draft.curves[index-1],f"control{n}")
        self.commit(draft)

    def reset_value(self,name):
        self._interaction_feedback.clear()
        if name.startswith("point_") and self.draft is not None:
            identity = "base" if self.selected == "foot_height" else "top" if self.selected == "top_width" else self.selected
            default = self._point_defaults.get(identity)
            current = next((p.position for p in self.draft.points if p.identity == identity),None)
            if default and current:
                self.move(self.selected,default.diameter_mm if name == "point_diameter_mm" else current.diameter_mm,
                          default.z_mm if name == "point_height_mm" else current.z_mm)
            return
        if name.startswith("control_") and self.draft is not None:
            control = self._selected_control()
            if control:
                i,n = control
                default = self._control_defaults.get((self.draft.points[i].identity,n))
                current = getattr(self.draft.curves[i],f"control{n}")
                if default:
                    self.move_control(i,n,default.diameter_mm if name == "control_diameter_mm" else current.diameter_mm,
                                      default.z_mm if name == "control_height_mm" else current.z_mm)
            return
        self._numeric_changed(name,self.default_value(name))
        if name == "overhang_angle_deg" and self.draft is not None:
            self.commit(replace(self.draft,settings=replace(self.draft.settings,overhang_user_set=False)))

    def reset_all(self):
        if self._busy or self.reference is None: return
        try:
            s = replace(ManualSettings(),object_resolution_percent=self.default_value("object_resolution_percent"),
                        maximum_foot_diameter_mm=self.default_value("maximum_foot_diameter_mm"),
                        foot_diameter_mm=self.default_value("foot_diameter_mm"))
            if self.initial is not None:
                s = replace(s,overhang_angle_deg=self.initial.settings.overhang_angle_deg,
                            minimum_diameter_mm=self.initial.settings.minimum_diameter_mm)
            draft = initial_draft(s,self.reference.context.layers,self.reference.context.maximum_height_mm,self.reference.context.key,
                                  foot_diameter_mm=self.default_value("foot_diameter_mm"))
            self._checked(draft)
        except GeometryError as e:
            self.feedback(e,"points")
            return
        self.initial = draft
        self._restore_form(draft)
        self.reset_rotation()
        self.canvas.set_highlight("both")
        self.canvas.set_view(self.canvas.view)

    def can_reset_all(self):
        initial = (replace(self.initial,settings=replace(self.initial.settings,
                   object_resolution_percent=self.default_value("object_resolution_percent")))
                   if self.initial is not None else None)
        return (not self._busy and self.draft is not None and self.initial is not None and
                (self.draft != initial or self.canvas.object_rotation%360 != 0 or
                 self.rotation_slider.value() != 0 or self.canvas.highlight != "both" or
                 self.canvas.zoom != 1 or self.canvas.pan != QPointF() or
                 (self.canvas.view == "free" and (self.canvas.yaw_deg,self.canvas.pitch_deg) != (-35,25))))

    def _restore_form(self,draft):
        self.selected = self.canvas.selected = "base"
        self.canvas._revealed_control_anchor = None
        self._point_defaults = {p.identity:p.position for p in draft.points if p.kind != "free"}
        self._control_defaults = {(draft.points[i].identity,n):getattr(c,f"control{n}")
                                  for i,c in enumerate(draft.curves) for n in (1,2)}
        self.status_label.clear()
        self.commit(draft)

    def tower_reset_draft(self):
        defaults = self.initial.settings if self.initial is not None else ManualSettings()
        settings = replace(self.settings,**{name:getattr(defaults,name) for name in self.FORM_SETTINGS})
        settings = replace(settings,maximum_foot_diameter_mm=self.default_value("maximum_foot_diameter_mm"))
        return self._checked(initial_draft(settings,self.reference.context.layers,
                                          self.reference.context.maximum_height_mm,self.reference.context.key,
                                          foot_diameter_mm=self.default_value("foot_diameter_mm")))

    def can_reset_tower(self):
        if self._busy or self.draft is None or self.reference is None:
            return False
        try:
            target = self.tower_reset_draft()
        except GeometryError:
            return False
        return self.draft != target

    def reset_tower(self):
        if self._busy or self.reference is None or self.draft is None:
            return
        try:
            draft = self.tower_reset_draft()
        except GeometryError as error:
            self.feedback(error,"points")
            return
        self._restore_form(draft)

    def reset_rotation(self):
        self.rotation_slider.setValue(0)
        self._queue_rotation(0)
        self._rotation_timer.stop()
        self.canvas.set_rotation(0)

    def _refresh_resolution_reset(self):
        modified = self.settings.object_resolution_percent != self.default_value("object_resolution_percent")
        self.resolution_reset.setProperty("modified",modified)
        self.resolution_reset.setEnabled(modified and not self._busy and self.reference is not None)
        self.resolution_reset.style().unpolish(self.resolution_reset)
        self.resolution_reset.style().polish(self.resolution_reset)

    def feedback(self,error,fallback):
        name = getattr(error,"setting",fallback)
        self.status_label.setText(str(error))
        self.status_changed.emit()
        row = self.rows.get(name)
        if row is not None and name not in self._interaction_feedback:
            self._interaction_feedback.add(name)
            row.set_error(str(error))

    def _begin_interaction(self): self._interaction_feedback.clear()
    def _end_interaction(self): self._interaction_feedback.clear(); self._sync()

    def _queue_rotation(self,angle):
        if self.rotation_slider.isSliderDown():
            snapped = round(angle/45)*45
            if angle != snapped and abs(angle-snapped) <= 3:
                self.rotation_slider.setValue(snapped)
                return
        self.rotation_label.setText(f"{angle:.2f}°".replace(".",","))
        self.rotation_reset.setProperty("modified",angle != 0)
        self.rotation_reset.setEnabled(angle != 0)
        self.rotation_reset.style().unpolish(self.rotation_reset)
        self.rotation_reset.style().polish(self.rotation_reset)
        if not self._rotation_timer.isActive(): self._rotation_timer.start()
        # Reset availability follows the slider immediately, even when a busy
        # event loop delays the coalesced canvas rotation.
        self.reset_button.setEnabled(self.can_reset_all())
        self.status_changed.emit()

    def _view_changed(self,view):
        previous_default = self._resolution_default_percent
        self._resolution_default_percent = object_resolution_default(view)
        # Follow the view's default while keeping an individually chosen stage.
        if (self._resolution_default_percent != previous_default and
                self.settings.object_resolution_percent == previous_default):
            settings = replace(self.settings,object_resolution_percent=self._resolution_default_percent)
            if self.draft is not None:
                self.commit(replace(self.draft,settings=settings))
            else:
                self.settings = settings
        self.view_buttons[view].setChecked(True)
        self.resolution_host.show()
        self.preview_information.set_state(view,self.settings.critical_layers_enabled)
        if view in {"top","bottom"}:
            self.selected = self.canvas.selected = "top_width" if view == "top" else "foot"
        self._sync()
        self._apply_view_editability()

    def _apply_view_editability(self):
        if not hasattr(self,"canvas"): return
        editable = self.canvas.view in {"side","front"}
        plan_field = {"top":"top_diameter_mm","bottom":"foot_diameter_mm"}.get(self.canvas.view)
        plan_limit = {"top":"maximum_diameter_mm","bottom":"maximum_foot_diameter_mm"}.get(self.canvas.view)
        self.smooth_checkbox.setEnabled(editable and self.draft is not None and self.selected in {p.identity for p in self.draft.points[1:-1]})
        for name,row in self.rows.items():
            if name not in {"color_reference_time_s","overhang_angle_deg","gradient_start_deficit_s","gradient_full_deficit_s"}:
                row.setEnabled(editable or (plan_field is not None and name in {plan_field,plan_limit}))
        for name in ("expansion_enabled","contraction_enabled"):
            self.checks[name].setEnabled(editable)
        if plan_field is not None and self.selected in {"top_width","foot"}:
            self.rows["point_diameter_mm"].setEnabled(True)
        self.add_point_button.setEnabled(editable)
        self.reset_button.setEnabled(self.can_reset_all())
        if not editable:
            self.segment_combo.setEnabled(False)
            self.smooth_checkbox.setEnabled(False)
            self.remove_point_button.setEnabled(False)

    def set_busy(self,busy,cancelling=False,exporting=False):
        self._busy = busy
        self.resolution_slider.setEnabled(not busy and self.reference is not None)
        self._refresh_resolution_reset()
        self.settings_content.setEnabled(not busy and self.reference is not None)
        self.canvas.editing_enabled = not busy
        self.point_editor.setEnabled(not busy)
        self.canvas.update()
        self.progress.setVisible(busy)
        self.cancel_button.setVisible(busy and not exporting)
        self.cancel_button.setEnabled(not cancelling)
        self.cancel_button.setText("Abbruch wird ausgeführt …" if cancelling else "Abbrechen")
        if busy:
            self.generate_button.hide()
            self.export_button.hide()

    def set_actions(self,has_result,dirty,exported,busy):
        self.generate_button.setText("Kühlturm aktualisieren" if has_result else "Kühlturm generieren")
        self.generate_button.setVisible(not busy and (not has_result or dirty))
        self.generate_button.setEnabled(self.draft is not None)
        self.export_button.setVisible(not busy and has_result)
        self.export_button.setEnabled(not exported)
        self.export_button.setToolTip("Dieser geprüfte Stand wurde bereits exportiert." if exported else
                                      "Exportiert exakt den bisherigen geprüften Stand." if dirty else "Exportiert exakt den geprüften Turm.")
        self.cancel_button.setVisible(busy)
        self.action_hint.setText("Export und Analyse beziehen sich auf den bisherigen geprüften Stand. Die Vorschau zeigt den aktuellen Entwurf." if has_result and dirty else
                                 "Dieser geprüfte Stand wurde bereits exportiert." if exported else "")

    @property
    def settings_collapsed(self):
        return self._settings_collapsed

    def toggle_settings(self):
        self.set_settings_collapsed(not self._settings_collapsed)

    def _should_stack_settings(self):
        return self.width() < max(1000,self.settings_pane.expanded_minimum_width+
                                  self.preview_tools.minimumSizeHint().width()+30)

    def set_settings_collapsed(self,collapsed):
        if collapsed == self._settings_collapsed:
            return
        reversing=self._settings_transitioning
        self._settings_animation.stop()
        if collapsed and not reversing:
            self._settings_scroll_position=self.settings_scroll.verticalScrollBar().value()
            if self.splitter.orientation() == Qt.Orientation.Horizontal:
                self._settings_horizontal_extent=self.settings_pane.width()
            else:
                self._settings_vertical_extent=self.settings_pane.height()
        self._settings_collapsed=collapsed
        self._settings_transitioning=True
        self.settings_pane.set_target_collapsed(collapsed)
        self.settings_pane.begin_animation()
        self.settings_pane.setMinimumHeight(0)
        self.settings_pane.setMaximumHeight(16777215)
        if not collapsed:
            orientation=Qt.Orientation.Vertical if self._should_stack_settings() else Qt.Orientation.Horizontal
            self._configure_settings_margins(orientation == Qt.Orientation.Vertical)
            if orientation != self.splitter.orientation():
                self.splitter.setOrientation(orientation)
                start=0 if orientation == Qt.Orientation.Vertical else self.settings_pane.RAIL_WIDTH
            else:
                start=self.splitter.sizes()[0]
        else:
            start=self.splitter.sizes()[0]
        vertical=self.splitter.orientation() == Qt.Orientation.Vertical
        self.splitter.setCollapsible(0,vertical)
        if collapsed:
            end=0 if vertical else self.settings_pane.RAIL_WIDTH
        elif vertical:
            end=max(240,min(360,self._settings_vertical_extent,
                            self.splitter.height()-self.preview_container.minimumHeight()-1))
        else:
            end=max(self.settings_pane.expanded_minimum_width,
                    min(self._settings_horizontal_extent,self.splitter.width()-self.preview_container.minimumSizeHint().width()-1))
        self._settings_animation.setStartValue(float(start))
        self._settings_animation.setEndValue(float(end))
        self._animate_settings_extent(float(start))
        self._settings_animation.start()

    def _animate_settings_extent(self,value):
        total=(self.splitter.height() if self.splitter.orientation() == Qt.Orientation.Vertical else self.splitter.width())
        total-=self.splitter.handleWidth()
        self.splitter.setSizes([round(value),max(1,total-round(value))])

    def _finish_settings_animation(self):
        self._settings_transitioning=False
        self.settings_pane.finish_animation(self._settings_collapsed)
        self.splitter.setCollapsible(0,False)
        self._configure_settings_layout()
        if self._settings_collapsed:
            self._animate_settings_extent(self.settings_pane.RAIL_WIDTH)
        else:
            self.settings_pane._position_children()
        self.settings_visibility_changed.emit()
        if not self._settings_collapsed:
            QTimer.singleShot(0,self,self._restore_settings_scroll_position)

    def _restore_settings_scroll_position(self):
        if not self._settings_collapsed and not self._settings_transitioning:
            self.settings_scroll.verticalScrollBar().setValue(self._settings_scroll_position)

    def _configure_settings_margins(self,narrow):
        self.settings_content.layout().setContentsMargins(0,0,0 if narrow else 14,14 if narrow else 0)
        self.preview_container.layout().setContentsMargins(0 if narrow else 14,14 if narrow else 0,0,0)

    def _configure_settings_layout(self):
        narrow=not self._settings_collapsed and self._should_stack_settings()
        self.splitter.setOrientation(Qt.Orientation.Vertical if narrow else Qt.Orientation.Horizontal)
        self._configure_settings_margins(narrow)
        self.settings_scroll.setMaximumHeight(360 if narrow else 16777215)
        self.settings_scroll.setMinimumHeight(240 if narrow else 0)
        self.settings_pane.setMaximumHeight(360 if narrow else 16777215)
        self.settings_pane.setMinimumHeight(240 if narrow else 0)
        if not getattr(self,"footer_hosted",False):
            self.setMinimumHeight(950 if narrow else 740)
        if narrow != getattr(self,"_narrow_layout",None):
            self._narrow_layout=narrow
            self.layout_changed.emit(narrow)

    def resizeEvent(self,event):
        baseline = max(34,self.reset_button.sizeHint().height())
        self.canvas.view_controls.set_button_height(max(12,round(baseline/3)))
        height = max(baseline,self.rotation_reset.height()+self.rotation_title.fontMetrics().height()+1)
        for host,title in ((self.highlight_host,self.highlight_title),(self.resolution_host,self.resolution_title),
                           (self.rotation_host,self.rotation_title)):
            host.setFixedHeight(height)
            title.setFixedHeight(title.fontMetrics().height())
        self.resolution_heading.setFixedHeight(self.resolution_title.height())
        for button in self.highlight_buttons.values():
            button.setFixedHeight(max(14,height-self.highlight_title.height()-1))
        for title,widgets in ((self.resolution_title,(self.resolution_slider,self.resolution_label)),
                              (self.rotation_title,(self.rotation_slider,self.rotation_label))):
            row_height=height-title.height()-1
            if title is self.resolution_title:row_height-=self.resolution_end_labels.height()
            for widget in widgets:
                widget.setFixedHeight(max(14,row_height))
        if not self._settings_transitioning:
            self._configure_settings_layout()
            if self._settings_collapsed:
                self._animate_settings_extent(self.settings_pane.RAIL_WIDTH)
        super().resizeEvent(event)

    def minimumSizeHint(self):
        return QSize(460,540 if getattr(self,"footer_hosted",False) else 740)
