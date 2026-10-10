"""Embedded editor UI; all changes pass through the domain's atomic validator."""
from __future__ import annotations

from dataclasses import replace
from functools import partial

from PySide6.QtCore import QSignalBlocker, QTimer, Qt, Signal, QSize
from PySide6.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, QLayout, QLabel, QPushButton, QSizePolicy,
                              QCheckBox, QScrollArea, QSplitter, QSlider, QProgressBar)

from cooling_tower.gui.widgets import SectionCard, NumericSettingWidget, WheelSafeComboBox
from cooling_tower.gui.widgets.manual_canvas import ManualCanvas
from cooling_tower.gui.widgets.manual_inputs import ManualDoubleSpinBox,ManualSpinBox
from cooling_tower.gui.design_tokens import COLORS
from cooling_tower.manual.geometry import (ManualSettings, Coordinate, GeometryError, bounded_edit, initial_draft,
                                          insert_point, move_point, remove_point, set_curve, couple_point, validate, validate_settings)


class ManualGenerationPanel(QWidget):
    draft_changed = Signal(object)
    generate_requested = Signal()
    export_requested = Signal()
    cancel_requested = Signal()
    retry_reference_requested = Signal()
    status_changed = Signal()

    LABELS = {
        "target_layer_time_s": ("Gewünschte Mindest-Layerzeit", "s", 5, 30),
        "layer_time_tolerance_s": ("Layerzeit-Toleranz ±", "s", .1, 3),
        "minimum_diameter_mm": ("Minimaler Turm-Außendurchmesser", "mm", .1, 1000),
        "maximum_diameter_mm": ("Maximaler Turm-Außendurchmesser", "mm", .1, 1000),
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
        self.draft = self.reference = self.initial = None
        self.selected = "base"
        self._busy = False
        self._interaction_feedback = set()
        self._syncing = False
        self._point_defaults = {}
        self._control_defaults = {}
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
        self.settings_content = QWidget()
        form = QVBoxLayout(self.settings_content)
        form.setContentsMargins(0,0,14,0)
        self.settings_scroll.setWidget(self.settings_content)
        self.splitter.addWidget(self.settings_scroll)
        for title, names in (
            ("Layerzeit und Bewertung", ("target_layer_time_s","layer_time_tolerance_s")),
            ("Turm und Standfuß", ("minimum_diameter_mm","maximum_diameter_mm","base_diameter_mm","foot_diameter_mm",
                                  "maximum_foot_diameter_mm","foot_height_mm","height_mm","circle_segments")),
            ("Geometrische Winkelgrenzen", ("expansion_angle_deg","contraction_angle_deg")),
            ("Ausgewählter Profilpunkt und Kurve", ("point_diameter_mm","point_height_mm","control_diameter_mm","control_height_mm")),
            ("Visuelle Prüfung", ("overhang_angle_deg","gradient_start_deficit_s","gradient_full_deficit_s"))):
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
        self.reset_button = QPushButton("↺ Manuellen Entwurf zurücksetzen")
        self.reset_button.clicked.connect(self.reset_all)
        form.addWidget(self.reset_button)
        form.addStretch()

        preview = QWidget()
        preview.setSizePolicy(QSizePolicy.Policy.Expanding,QSizePolicy.Policy.Ignored)
        self.preview_container = preview
        preview_layout = QVBoxLayout(preview)
        preview_layout.setContentsMargins(14,0,0,0)
        preview_layout.setSizeConstraint(QLayout.SizeConstraint.SetNoConstraint)
        tools = QHBoxLayout()
        self.view_combo = WheelSafeComboBox()
        self.view_combo.addItems(["Seitenansicht", "Vorderansicht", "3/4-Ansicht", "Draufsicht", "Freie 3D-Ansicht"])
        self.view_names = ("side","front","three_quarter","top","free")
        self.view_combo.currentIndexChanged.connect(lambda i:self.canvas.set_view(self.view_names[i]))
        tools.addWidget(self.view_combo,1)
        self.fit_button = QPushButton("Einpassen")
        self.fit_button.clicked.connect(lambda:self.canvas.fit_scene())
        tools.addWidget(self.fit_button)
        preview_layout.addLayout(tools)
        self.canvas = ManualCanvas()
        self.canvas.move_requested.connect(self.move)
        self.canvas.control_requested.connect(self.move_control)
        self.canvas.selection_changed.connect(self.select)
        self.canvas.insert_requested.connect(self.insert)
        self.canvas.remove_requested.connect(self.remove)
        self.canvas.interaction_started.connect(self._begin_interaction)
        self.canvas.interaction_finished.connect(self._end_interaction)
        self.canvas.view_changed.connect(self._view_changed)
        preview_layout.addWidget(self.canvas,1)
        self.view_hint = QLabel()
        self.view_hint.setWordWrap(True)
        preview_layout.addWidget(self.view_hint)
        rotation = QHBoxLayout()
        rotation.addWidget(QLabel("Original drehen"))
        self.rotation_slider = QSlider(Qt.Orientation.Horizontal)
        self.rotation_slider.setRange(0,360)
        self.rotation_slider.valueChanged.connect(self._queue_rotation)
        rotation.addWidget(self.rotation_slider,1)
        self.rotation_label = QLabel("0,00°")
        rotation.addWidget(self.rotation_label)
        self.rotation_reset = QPushButton("↺")
        self.rotation_reset.setObjectName("settingResetButton")
        self.rotation_reset.clicked.connect(lambda:self.rotation_slider.setValue(0))
        rotation.addWidget(self.rotation_reset)
        preview_layout.addLayout(rotation)
        self._rotation_timer = QTimer(self)
        self._rotation_timer.setSingleShot(True)
        self._rotation_timer.setInterval(16)
        self._rotation_timer.timeout.connect(lambda:self.canvas.set_rotation(self.rotation_slider.value()))
        self.highlight_combo = WheelSafeComboBox()
        self.highlight_combo.addItems(["Beide hervorheben", "Turm hervorheben", "Original hervorheben"])
        self.highlight_combo.currentIndexChanged.connect(lambda i:self.canvas.set_highlight(("both","tower","object")[i]))
        preview_layout.addWidget(self.highlight_combo)
        legend = QLabel("● Violett: Fuß / Fußhöhe   ● Blau: Grunddurchmesser / Turmhöhe   ● Grün: freie Punkte   ■ Grau: Kurvengriffe")
        legend.setWordWrap(True)
        preview_layout.addWidget(legend)
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
        row = NumericSettingWidget(setting_name=name,label=label,editor=spin,unit=unit,
                                   default_provider=lambda:self.default_value(name),
                                   info_text="Alle Breiten sind Außendurchmesser. Fußhöhe und Turmhöhe sind absolute Z-Höhen über dem Druckbett." if unit == "mm" else
                                   "Winkel zur Vertikalen; lokale Radiussteigung. Die visuelle Prüfung verändert keine Geometrie." if unit == "°" else
                                   "Gleiche Kreissegmentzahl für alle STL-Ringe; unabhängig von Drucklayern und Kurvenunterteilungen." if name == "circle_segments" else "")
        row.set_feedback_enabled(True)
        row.reset_button.clicked.disconnect()
        row.reset_button.clicked.connect(lambda:self.reset_value(name))
        spin.setKeyboardTracking(False)
        spin.valueChanged.connect(partial(self._numeric_changed,name))
        spin.limit_attempted.connect(lambda value:self._numeric_changed(name,int(value) if name == "circle_segments" else value))
        spin.lineEdit().editingFinished.connect(partial(self._detect_numeric_attempt,name))
        self.rows[name],self.editors[name] = row,spin
        return row

    def default_value(self,name):
        if name.startswith("point_"):
            identity = "base" if self.selected == "foot_height" else self.selected
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
            if hasattr(self.initial.settings,name): return getattr(self.initial.settings,name)
        value = getattr(ManualSettings(),name,None)
        return value if value is not None else 25 if name == "circle_segments" else 0.1

    def initialize(self,reference,settings=None):
        self.reference = reference
        self.selected = self.canvas.selected = "base"
        s = settings or self.settings
        self.initial = initial_draft(replace(ManualSettings(),overhang_angle_deg=s.overhang_angle_deg),reference.context.layers,reference.context.maximum_height_mm,reference.context.key)
        draft = initial_draft(s,reference.context.layers,reference.context.maximum_height_mm,reference.context.key)
        reference.context.validate(draft)
        self.canvas.set_reference(reference)
        self.height_note.setText(reference.context.height_note)
        self.retry_button.hide()
        self._point_defaults = {p.identity:p.position for p in draft.points}
        self._control_defaults = {(draft.points[i].identity,n):getattr(c,f"control{n}") for i,c in enumerate(draft.curves) for n in (1,2)}
        self.commit(draft)

    def commit(self,draft):
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
            values.update(base_diameter_mm=self.draft.base_diameter_mm,height_mm=self.draft.height_mm)
            point = next((p for p in self.draft.points if p.identity == self.selected),None)
            if point:
                values.update(point_diameter_mm=point.position.diameter_mm,point_height_mm=point.position.z_mm)
                self.selection_label.setText(f"{'Freier Profilpunkt' if point.kind == 'free' else {'foot':'Fußrand','base':'Körperbeginn','top':'Oberer Abschluss'}[point.kind]} · {point.position.z_mm:.2f} mm")
            if self.selected == "foot_height":
                p = self.draft.points[1]
                values.update(point_diameter_mm=p.position.diameter_mm,point_height_mm=p.position.z_mm)
                self.selection_label.setText("Fußübergang · vertikal verschieben")
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
            self.editors["point_diameter_mm"].setEnabled(point is not None and point.kind != "top")
            self.editors["point_height_mm"].setEnabled(self.selected == "foot_height" or (point is not None and point.kind in {"free","top"}))
            self.remove_point_button.setEnabled(point is not None and point.kind == "free")
            self.smooth_checkbox.setEnabled(point is not None and point.kind in {"base","free"})
            with QSignalBlocker(self.smooth_checkbox): self.smooth_checkbox.setChecked(point.smooth if point else False)
            index = self._segment_index()
            self.segment_combo.setEnabled(index is not None and index > 0)
            with QSignalBlocker(self.segment_combo):
                self.segment_combo.setCurrentIndex(int(self.draft.curves[index].curved) if index is not None else 0)
            count = sum(l.total_time_s < s.target_layer_time_s-s.layer_time_tolerance_s for l in self.reference.context.layers)
            self.critical_note.setText(f"Original: {count} von {len(self.reference.context.layers)} Layern unter Ziel − Toleranz. Die Farben zeigen das tatsächliche Defizit.")
        for name,spin in self.editors.items():
            with QSignalBlocker(spin):
                value = values.get(name,self.default_value(name))
                spin.setValue(value if value is not None else 25)
            self.rows[name].refresh_reset_state()
        for name,box in self.checks.items():
            with QSignalBlocker(box): box.setChecked(getattr(s,name))
        self._syncing = False
        self._apply_view_editability()

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
        if name in {"base_diameter_mm","foot_diameter_mm","foot_height_mm","height_mm"}:
            identity = {"base_diameter_mm":"base","foot_diameter_mm":"foot","foot_height_mm":"foot_height","height_mm":"top"}[name]
            p = self.draft.points[1 if identity == "foot_height" else 0 if identity == "foot" else -1 if identity == "top" else 1].position
            self.move(identity,value if name in {"base_diameter_mm","foot_diameter_mm"} else p.diameter_mm,
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

    def move(self,identity,diameter,z):
        if self._busy or self.draft is None: return
        actual = "base" if identity == "foot_height" else identity
        p = next((p for p in self.draft.points if p.identity == actual),None)
        if p is None: return
        if identity == "base": z = p.position.z_mm
        if identity == "foot_height": diameter = p.position.diameter_mm
        old = self.draft
        def operation(t):
            return self._checked(move_point(old,actual,diameter_mm=p.position.diameter_mm+(diameter-p.position.diameter_mm)*t,
                                           z_mm=p.position.z_mm+(z-p.position.z_mm)*t))
        candidate,error = bounded_edit(old,operation)
        if error: self.feedback(error,"point_height_mm")
        else: self.status_label.clear()
        self.commit(candidate)

    def move_control(self,index,n,diameter,z):
        if self._busy or self.draft is None: return
        old = self.draft
        p = getattr(old.curves[index],f"control{n}")
        candidate,error = bounded_edit(old,lambda t:self._checked(set_curve(old,index,control=n,
                                                      position=p.lerp(Coordinate(diameter/2,z),t))))
        if error: self.feedback(error,"control_height_mm")
        else: self.status_label.clear()
        self.commit(candidate)

    def select(self,identity):
        self.selected = self.canvas.selected = identity
        self._sync()
        self.canvas.update()

    def _selected_control(self):
        return tuple(map(int,self.selected.split(":")[1:])) if self.selected.startswith("control:") else None

    def _segment_index(self):
        if self.selected in {"foot","foot_height"}: return 0
        control = self._selected_control()
        if control: return control[0]
        return next((i for i,p in enumerate(self.draft.points[:-1]) if p.identity == self.selected),None) if self.draft else None

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
        self._point_defaults[identity] = next(p.position for p in draft.points if p.identity == identity)
        for i,c in enumerate(draft.curves):
            for n in (1,2): self._control_defaults.setdefault((draft.points[i].identity,n),getattr(c,f"control{n}"))
        self.commit(draft)

    def add_point(self):
        if self.draft is None: return
        i = self._segment_index()
        i = max(1,i or 1)
        c = self.draft.curves[min(i,len(self.draft.curves)-1)]
        self.insert((c.start.z_mm+c.end.z_mm)/2)

    def remove(self,identity):
        if self._busy or self.draft is None: return
        try: draft = self._checked(remove_point(self.draft,identity))
        except (GeometryError,StopIteration) as e:
            self.feedback(e,"points")
            return
        self.selected = self.canvas.selected = "base"
        self.commit(draft)

    def reset_value(self,name):
        self._interaction_feedback.clear()
        if name.startswith("point_") and self.draft is not None:
            identity = "base" if self.selected == "foot_height" else self.selected
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
            s = ManualSettings()
            if self.initial is not None:
                s = replace(s,overhang_angle_deg=self.initial.settings.overhang_angle_deg)
            draft = initial_draft(s,self.reference.context.layers,self.reference.context.maximum_height_mm,self.reference.context.key)
            self._checked(draft)
        except GeometryError as e:
            self.feedback(e,"points")
            return
        self.initial = draft
        self.selected = self.canvas.selected = "base"
        self.commit(draft)

    def feedback(self,error,fallback):
        name = getattr(error,"setting",fallback)
        self.status_label.setText(str(error))
        self.status_changed.emit()
        row = self.rows.get(name)
        if row is not None and name not in self._interaction_feedback:
            self._interaction_feedback.add(name)
            row.set_error(str(error))
            QTimer.singleShot(700,lambda:row.set_error(None))

    def _begin_interaction(self): self._interaction_feedback.clear()
    def _end_interaction(self): self._interaction_feedback.clear(); self._sync()

    def _queue_rotation(self,angle):
        self.rotation_label.setText(f"{angle:.2f}°".replace(".",","))
        if not self._rotation_timer.isActive(): self._rotation_timer.start()

    def _view_changed(self,view):
        with QSignalBlocker(self.view_combo): self.view_combo.setCurrentIndex(self.view_names.index(view))
        self.view_hint.setText("Greifer ziehen · Profil doppelklicken: Punkt hinzufügen · Mausrad: Zoom · Mitteltaste oder freie Fläche: Pan" if view in {"side","front"} else
                               "Profilbearbeitung in Seiten- und Vorderansicht. Freie 3D-Ansicht: rechte Maustaste dreht die Kamera.")
        if self.draft is not None: self._sync()
        self._apply_view_editability()

    def _apply_view_editability(self):
        if not hasattr(self,"canvas"): return
        editable = self.canvas.view in {"side","front"}
        self.smooth_checkbox.setEnabled(editable and self.draft is not None and self.selected in {p.identity for p in self.draft.points[1:-1]})
        for name,row in self.rows.items():
            if name not in {"target_layer_time_s","layer_time_tolerance_s","overhang_angle_deg","gradient_start_deficit_s","gradient_full_deficit_s"}:
                row.setEnabled(editable)
        for name in ("expansion_enabled","contraction_enabled"):
            self.checks[name].setEnabled(editable)
        self.add_point_button.setEnabled(editable)
        self.reset_button.setEnabled(editable)
        if not editable:
            self.segment_combo.setEnabled(False)
            self.smooth_checkbox.setEnabled(False)
            self.remove_point_button.setEnabled(False)

    def set_busy(self,busy,cancelling=False,exporting=False):
        self._busy = busy
        self.settings_content.setEnabled(not busy and self.reference is not None)
        self.canvas.editing_enabled = not busy
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

    def resizeEvent(self,event):
        narrow = self.width() < 1000
        self.splitter.setOrientation(Qt.Orientation.Vertical if narrow else Qt.Orientation.Horizontal)
        self.settings_content.layout().setContentsMargins(0,0,0,14) if narrow else self.settings_content.layout().setContentsMargins(0,0,14,0)
        self.preview_container.layout().setContentsMargins(0,14,0,0) if narrow else self.preview_container.layout().setContentsMargins(14,0,0,0)
        self.settings_scroll.setMaximumHeight(360 if narrow else 16777215)
        self.settings_scroll.setMinimumHeight(240 if narrow else 0)
        if not getattr(self,"footer_hosted",False):
            self.setMinimumHeight(950 if narrow else 740)
        super().resizeEvent(event)

    def minimumSizeHint(self):
        return QSize(460,540 if getattr(self,"footer_hosted",False) else 740)
