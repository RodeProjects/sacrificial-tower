"""Independent iterative-project controls using the established editor design."""
from __future__ import annotations

from pathlib import Path
from PySide6.QtCore import QEasingCurve, QEvent, QSignalBlocker, QSize, QTimer, Qt, Signal, QVariantAnimation
from PySide6.QtGui import QIcon, QValidator
from PySide6.QtWidgets import (QBoxLayout, QCheckBox, QFrame, QGridLayout, QHBoxLayout,
    QLabel, QPushButton, QScrollArea, QSizePolicy, QVBoxLayout, QWidget)

from cooling_tower.angles import complementary_angle
from cooling_tower.gui.design_tokens import METRICS
from cooling_tower.gui.widgets.numeric_field_widths import fit_numeric_fields
from cooling_tower.gui.widgets.automatic_setting import add_automatic_control
from cooling_tower.gui.widgets.activity_progress_bar import ActivityProgressBar
from cooling_tower.gui.widgets.committed_numeric_inputs import CommittedDoubleSpinBox, CommittedSpinBox
from cooling_tower.gui.widgets.footer_actions import fit_footer_actions
from cooling_tower.gui.widgets.info_tool_button import InfoToolButton
from cooling_tower.gui.widgets.numeric_setting import NumericSettingWidget
from cooling_tower.gui.widgets.postprocessor_widgets import ColourLegend, FlowColourLegend, LayerNumberSpinBox
from cooling_tower.gui.widgets.resizable_preview_columns import ResizablePreviewColumns
from cooling_tower.gui.widgets.responsive_card_grid import ResponsiveCardGrid
from cooling_tower.gui.widgets.section_card import SectionCard
from cooling_tower.gui.widgets.travel_mode_toggle import TravelModeToggle
from cooling_tower.gui.native_project.canvas import NativePreviewCanvas
from cooling_tower.gui.native_project.footer import NativeFooter
from cooling_tower.gui.native_project.hints import SETTING_INFO_TEXTS, chart_hint, EXPANSION_ANGLE_CAUTION
from cooling_tower.gui.native_project.time_chart import NativeTimeChart
from cooling_tower.gui.native_project.styles import EDITOR_STYLE, FOOTER_STYLE
from cooling_tower.native_project.defaults import GENERATION_DEFAULTS


class _NativeAutomaticText:
    _automatic_text = None

    def textFromValue(self,value):
        return self._automatic_text if self._automatic_text is not None else super().textFromValue(value)

    def validate(self,text,position):
        if self._automatic_text is not None and text == self._automatic_text:
            return QValidator.State.Acceptable,text,position
        return super().validate(text,position)

    def valueFromText(self,text):
        # Qt interprets even disabled spinboxes when their page is hidden.
        # A calculated display must never replace the retained manual value.
        return self.value() if self._automatic_text is not None else super().valueFromText(text)

    def show_automatic_value(self,enabled,value=None):
        self._automatic_text = (('—' if value is None else value if isinstance(value,str) else
            self.locale().toString(int(value)) if self._integer else self.locale().toString(float(value),'f',self.decimals()))
            if enabled else None)
        self.lineEdit().setText(self.textFromValue(self.value()))
        self.setToolTip('Automatischer Wert steht nach der Turmgenerierung fest.' if enabled and value is None else '')


class NativeDoubleSpinBox(_NativeAutomaticText,CommittedDoubleSpinBox):
    pass


class NativeIntegerSpinBox(_NativeAutomaticText,CommittedSpinBox):
    pass


class NativeEditorPanel(QWidget):
    changed = Signal()
    layer_selected = Signal(int)
    layer_reset_requested = Signal()
    layout_changed = Signal()

    def __init__(self):
        super().__init__()
        self.setObjectName('nativeProjectEditor')
        self.setStyleSheet(EDITOR_STYLE)
        self.inputs, self.rows, self.automatic = {}, {}, {}
        self._automatic_values = {}
        self._profile_angle = None
        self._layout_timer = QTimer(self)
        self._layout_timer.setSingleShot(True)
        self._layout_timer.timeout.connect(self.refresh_layout)
        self._preview_viewport = None
        self._has_result = False
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        layout.setAlignment(Qt.AlignmentFlag.AlignTop)
        self.settings_column = QWidget()
        left = QVBoxLayout(self.settings_column)
        left.setContentsMargins(0, 0, 0, 0)
        left.setSpacing(0)
        left.setAlignment(Qt.AlignmentFlag.AlignTop)
        self.input_group = SectionCard('Iterative Turmeinstellungen')
        left.addWidget(self.input_group)
        self._numeric(self.input_group.content_layout, 'target_layer_time_s', 'Mindest-Layerzeit', 's', 5, 30)
        self._numeric(self.input_group.content_layout, 'layer_time_tolerance_s', 'Layerzeit-Toleranz (±)', 's', .1, 3)
        self._check(self.input_group.content_layout, 'simulate_full_tower_infill', '100% Turmfüllung simulieren')
        self._check(self.input_group.content_layout, 'simulate_tower_without_supports', 'Deaktivierte Turmstützen simulieren')
        self.advanced_group = SectionCard('Erweiterte Turmeinstellungen')
        left.addWidget(self.advanced_group)
        self._numeric(self.advanced_group.content_layout, 'tower_wall_count', 'Wandlinien', '', 1, 10, integer=True)
        for key, label, unit, low, high in (
            ('minimum_outer_diameter_mm', 'Minimaler Turmdurchmesser', 'mm', 3, 99),
            ('maximum_outer_diameter_mm', 'Maximaler Turmdurchmesser', 'mm', 5, 200),
            ('minimum_object_tower_distance_mm', 'Modellabstand', 'mm', 5, 100),
            ('manual_base_width_mm', 'Standfußbreite', 'mm', 20, 80),
            ('maximum_expansion_angle_deg', 'Aufweitungswinkel', '°', 20, 89),
            ('maximum_contraction_angle_deg', 'Verjüngungswinkel', '°', 5, 89),
            ('circle_segments', 'Turm-Kreissegmente', '', 4, 256),
        ):
            automatic = {'manual_base_width_mm':'automatic_base_width', 'circle_segments':'automatic_circle_segments', 'maximum_contraction_angle_deg':'automatic_contraction_angle'}.get(key)
            self._numeric(self.advanced_group.content_layout, key, label, unit, low, high,
                          automatic=automatic, integer=key == 'circle_segments', angle=key.endswith('_angle_deg'))
        self._check(self.advanced_group.content_layout, 'limit_expansion_to_profile', 'Aufweitung auf Profil begrenzen')
        self.iterations = CommittedSpinBox()
        self.iterations.setRange(1, 50)
        self.iterations.setValue(12)
        self.iterations.valueChanged.connect(self.changed)
        self.iterations.lineEdit().textEdited.connect(self.changed)
        self.iterations.editingFinished.connect(self.changed)
        iteration_row = NumericSettingWidget(setting_name='maximum_iterations', label='Maximale gemeinsame Slices',
            editor=self.iterations, default_provider=lambda: 12,
            info_text='Begrenzt die gemeinsam geslicten Iterationen. Jeder Durchlauf beginnt mit derselben importierten Projektbasis.')
        self.advanced_group.content_layout.addWidget(iteration_row)
        self.preview_group = SectionCard('G-Code-Vorschau')
        self.preview_group.content_layout.setAlignment(Qt.AlignmentFlag(0))
        for card in (self.input_group, self.advanced_group, self.preview_group):
            card.setProperty('outerDropdown', True)
            card.setProperty('edgeAttached', True)
        self.columns = ResizablePreviewColumns(self.settings_column, self.preview_group)
        self.columns.layout_changed.connect(lambda: self._layout_timer.start(0))
        layout.addWidget(self.columns)
        self.canvas = NativePreviewCanvas()
        self.canvas.set_rotation_drag_inverted(True)
        self.canvas.set_navigation_default(True)
        self.canvas.set_layer_context_enabled(True)
        self.canvas.set_layer_selection_persistent(True)
        self.canvas.setMinimumWidth(0)
        self.canvas.setFixedHeight(420)
        self.canvas.installEventFilter(self)
        self.preview_display = QWidget()
        self.preview_display.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        self.display_layout = QHBoxLayout(self.preview_display)
        self.display_layout.setContentsMargins(0, 0, 0, 0)
        self.display_layout.setSpacing(12)
        self.preview_view = QWidget()
        preview = QVBoxLayout(self.preview_view)
        preview.setContentsMargins(0, 0, 0, 0)
        preview.setSpacing(6)
        self.display_layout.addWidget(self.preview_view, 3, Qt.AlignmentFlag.AlignTop)
        self.preview_group.content_layout.addWidget(self.preview_display)
        self.camera_row = QHBoxLayout()
        self.camera_row.setSpacing(6)
        self.camera_buttons = {}
        for name, label, action in (
            ('three_quarter', '3/4-Ansicht', self.three_quarter_view),
            ('front', 'Vorderansicht', self.canvas.front_view),
            ('side', 'Seitenansicht', self.canvas.side_view),
            ('top', 'Draufsicht', self.top_view),
            ('fit', 'Einpassen', self.canvas.fit_scene),
        ):
            button = QPushButton(label)
            button.setObjectName('previewCameraButton')
            font = button.font(); font.setPointSizeF(10.5); button.setFont(font)
            button.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
            button.setToolTip(label)
            button.clicked.connect(action)
            self.camera_buttons[name] = button
            self.camera_row.addWidget(button, 1)
        self.timing_toggle = QPushButton()
        self.timing_toggle.setObjectName('previewLayerTimesToggle')
        self.timing_toggle.setCheckable(True)
        self.timing_toggle.setChecked(True)
        self.timing_toggle.setFixedSize(32,32)
        self.timing_toggle.setIconSize(QSize(22,22))
        self.timing_toggle.setIcon(QIcon(str(Path(__file__).parents[1]/'assets/layer_times_panel.svg')))
        self.timing_toggle.setAccessibleName('Layerzeiten ein- oder ausblenden')
        self.timing_toggle.setToolTip('Layerzeiten')
        self.timing_toggle.setStyleSheet('QPushButton { min-width:0; min-height:0; padding:0; border-radius:6px; }'
            'QPushButton:checked { background:#dcebf7; border:1px solid #afc0d0; }')
        self.timing_toggle.toggled.connect(self._toggle_timing)
        self.camera_row.addWidget(self.timing_toggle)
        preview.addLayout(self.camera_row)
        preview.addWidget(self.canvas)
        for name,title in (('preview_reset','Vorschau zurücksetzen'),('transparency_toggle','Transparenz aktiv'),
                           ('travel_visibility_button','Fahrwege ausblenden')):
            button = QPushButton(title,self.canvas)
            button.setAutoDefault(False)
            button.setFixedHeight(32)
            button.setStyleSheet('QPushButton { min-height:32px; max-height:32px; border:0; border-radius:0; '
                'padding:0 12px; background:#243344; color:#dbe8f2; }'
                'QPushButton:hover { background:#355269; }'
                'QPushButton:focus { border:0; }'
                'QPushButton:pressed { background:#1c4561; }'
                'QPushButton:checked { background:#244436; }'
                'QPushButton:checked:hover { background:#355c49; }'
                'QPushButton:checked:pressed { background:#1d4c35; }'
                'QPushButton:disabled { background:#20272e; color:#7b8b98; }')
            button.setEnabled(False)
            setattr(self,name,button)
        self.preview_reset.clicked.connect(self.reset_preview)
        self.transparency_toggle.setCheckable(True)
        self.transparency_toggle.setChecked(True)
        self.transparency_toggle.setToolTip('Stellt die Layer unterhalb der gewählten Schicht transparent dar. '
            'Die Layerauswahl im Diagramm aktiviert diese Darstellung automatisch.')
        self.transparency_toggle.toggled.connect(self._set_transparency_active)
        self.canvas.layer_highlight_cleared.connect(lambda:self.transparency_toggle.setChecked(False))
        self.travel_visibility_button.setCheckable(True)
        self.travel_visibility_button.setChecked(True)
        self.travel_visibility_button.setToolTip('Blendet die Fahrwege ein oder aus. Alle / Einzeln bestimmt die angezeigten Layer.')
        self.travel_visibility_button.toggled.connect(self._toggle_travel_visibility)
        self.travel_mode_toggle = TravelModeToggle(self.canvas)
        self.travel_mode_toggle.setFixedHeight(32)
        self.travel_mode_toggle.toggled.connect(self.canvas.set_all_travel_visible)
        self._travel_reveal = 0.0
        self._travel_reveal_animation = QVariantAnimation(self)
        self._travel_reveal_animation.setEasingCurve(QEasingCurve.Type.InOutCubic)
        self._travel_reveal_animation.valueChanged.connect(self._set_travel_reveal)
        self._travel_reveal_animation.finished.connect(lambda:self.travel_mode_toggle.setVisible(self._travel_reveal>0))
        self._show_travel_modes(False,animate=False)
        self.canvas.set_tower_travel_visible(True)
        self.legend = FlowColourLegend((('Modell', self.canvas.OBJECT_COLOR), ('Turm', self.canvas.TOWER_COLOR),
                                       ('Fahrwege',self.canvas.TOWER_TRAVEL_COLOR),('Seams', self.canvas.SEAM_COLOR)))
        preview.addWidget(self.legend)
        self.safety_hint = QLabel()
        self.safety_hint.setWordWrap(True)
        self.safety_hint.hide()
        preview.addWidget(self.safety_hint)
        self.timing_panel = QWidget()
        self.timing_panel.setObjectName('nativeProjectLayerTimes')
        self.display_layout.addWidget(self.timing_panel, 2, Qt.AlignmentFlag.AlignTop)
        timing = QVBoxLayout(self.timing_panel)
        timing.setContentsMargins(0,0,0,0)
        timing.setSpacing(6)
        timing.addWidget(QLabel('<b>Layerzeiten</b>'))
        self.time_chart = NativeTimeChart()
        timing.addWidget(self.time_chart, 1)
        self.time_legend = ColourLegend((('Original', NativeTimeChart.COLORS[0]),
            ('Mit Turm', NativeTimeChart.COLORS[1]), ('Zielzeit', NativeTimeChart.TARGET_COLOR)), columns=1)
        timing.addWidget(self.time_legend)
        self.logarithmic_scale = self._chart_check(timing, 'Logarithmische Zeitskala',
            chart_hint('Logarithmische Zeitskala', 'logarithmic_time_scale'), True)
        self.logarithmic_scale.toggled.connect(self.time_chart.set_logarithmic)
        self.normalized_scale = self._chart_check(timing, 'Zeitskala normalisieren',
            chart_hint('Zeitskala normalisieren', 'normalize_time_scale'), False)
        self.normalized_scale.toggled.connect(self.time_chart.set_normalized)
        self.layer_spin = LayerNumberSpinBox()
        self.layer_spin.setRange(1,1)
        self.layer_spin.setAccessibleName('Layernummer in der Vorschau')
        self.layer_reset = QPushButton('↺')
        self.layer_reset.setObjectName('settingResetButton')
        self.layer_reset.setFixedSize(METRICS.reset_button_size_px, METRICS.reset_button_size_px)
        self.layer_reset.setToolTip('Letzten Layer und vollständiges Modell anzeigen')
        self.layer_reset.setAccessibleName('Letzten Layer und vollständiges Modell anzeigen')
        self.layer_reset.clicked.connect(self.layer_reset_requested)
        layer_row = QHBoxLayout()
        layer_row.addWidget(QLabel('Layer'))
        layer_row.addWidget(self.layer_spin)
        layer_row.addWidget(self.layer_reset)
        layer_row.addStretch(1)
        timing.addLayout(layer_row)
        self.layer_details = QLabel()
        self.layer_details.setWordWrap(True)
        timing.addWidget(self.layer_details)
        self.layer_spin.valueChanged.connect(self.layer_selected)
        self.time_chart.layer_selected.connect(self.layer_selected)
        self._build_footer()
        self._sync_automatic()

    def _numeric(self, layout, key, label, unit, low, high, *, automatic=None, integer=False, angle=False):
        spin = NativeIntegerSpinBox() if integer else NativeDoubleSpinBox()
        spin.setRange(low,high)
        if not integer:
            spin.setDecimals(2)
        default = GENERATION_DEFAULTS[key]
        value = complementary_angle(default) if angle else default
        spin.setValue(value)
        spin.setObjectName('native_'+key)
        row = NumericSettingWidget(setting_name=key, label=label, editor=spin,
            default_provider=lambda value=value: value, unit=unit,
            info_text=SETTING_INFO_TEXTS.get(key, label))
        self.inputs[key] = (spin, angle)
        self.rows[key] = row
        spin.setKeyboardTracking(False)
        spin.valueChanged.connect(self.changed)
        spin.lineEdit().textEdited.connect(self.changed)
        spin.lineEdit().textChanged.connect(lambda _text:self._layout_timer.start(0))
        spin.editingFinished.connect(self.changed)
        if key == 'maximum_expansion_angle_deg':
            spin.valueChanged.connect(self._sync_automatic)
        if automatic:
            flag = QCheckBox()
            flag.setChecked(GENERATION_DEFAULTS[automatic])
            flag.setAccessibleName(label+' automatisch berechnen')
            self.automatic[automatic] = flag
            self.inputs[automatic] = (flag, False)
            add_automatic_control(row, flag)
            flag.toggled.connect(self._sync_automatic)
            flag.toggled.connect(self.changed)
        layout.addWidget(row)

    def _check(self, layout, key, label):
        box = QCheckBox(label)
        box.setChecked(GENERATION_DEFAULTS[key])
        box.setObjectName('native_'+key)
        self.inputs[key] = (box,False)
        row = QHBoxLayout()
        row.setContentsMargins(0,2,0,2)
        row.setSpacing(METRICS.setting_info_text_gap_px)
        info = InfoToolButton(SETTING_INFO_TEXTS.get(key,label), object_name='settingInfoButton',
            diameter_px=METRICS.setting_info_diameter_px, accessible_name='Informationen zu '+label)
        row.addWidget(info)
        row.addWidget(box)
        row.addStretch(1)
        layout.addLayout(row)
        box.toggled.connect(self.changed)
        if key == 'simulate_full_tower_infill':
            box.toggled.connect(self._sync_automatic)
        if key == 'limit_expansion_to_profile':
            box.toggled.connect(self._sync_automatic)

    def _chart_check(self, layout, title, hint, checked):
        row = QHBoxLayout()
        row.setContentsMargins(0,0,0,0)
        row.setSpacing(6)
        info = InfoToolButton(hint, object_name='settingInfoButton',
            diameter_px=METRICS.setting_info_diameter_px, accessible_name='Informationen zu '+title)
        box = QCheckBox(title)
        box.setChecked(checked)
        row.addWidget(info); row.addWidget(box); row.addStretch(1)
        layout.addLayout(row)
        return box

    def _sync_automatic(self):
        for key, field in (('automatic_base_width','manual_base_width_mm'), ('automatic_circle_segments','circle_segments')):
            if key in self.automatic:
                spin = self.inputs[field][0]
                automatic = self.automatic[key].isChecked()
                spin.show_automatic_value(automatic,self._automatic_values.get(field))
                spin.setEnabled(not automatic)
        if 'maximum_contraction_angle_deg' in self.inputs:
            automatic = self.automatic['automatic_contraction_angle'].isChecked()
            spin = self.inputs['maximum_contraction_angle_deg'][0]
            spin.show_automatic_value(automatic, 'auto')
            spin.setEnabled(not automatic)
        if 'tower_wall_count' in self.inputs:
            enabled = not self.inputs['simulate_full_tower_infill'][0].isChecked()
            self.inputs['tower_wall_count'][0].show_automatic_value(not enabled, 'solid')
            self.inputs['tower_wall_count'][0].setEnabled(enabled)
            self.rows['tower_wall_count'].label.setEnabled(enabled)
        if 'limit_expansion_to_profile' in self.inputs:
            automatic = self.inputs['limit_expansion_to_profile'][0].isChecked() and self._profile_angle is not None
            spin = self.inputs['maximum_expansion_angle_deg'][0]
            spin.show_automatic_value(automatic, self._profile_angle)
            spin.setEnabled(not automatic)
            self.rows['maximum_expansion_angle_deg'].set_warning(
                EXPANSION_ANGLE_CAUTION if not automatic and spin.value() <= 29. else '')

    def set_profile_angle(self, angle):
        self._profile_angle = angle
        self.inputs['limit_expansion_to_profile'][0].setEnabled(angle is not None)
        self._sync_automatic()

    def show_automatic_values(self,values):
        self._automatic_values = dict(values)
        self._sync_automatic()

    def _toggle_timing(self, visible):
        self.timing_panel.setVisible(visible)
        self.timing_toggle.setToolTip('Layerzeiten ausblenden' if visible else 'Layerzeiten anzeigen')
        self._layout_timer.start(0)

    def top_view(self):
        self.canvas.apply_camera_state({**self.canvas.camera_state(),'yaw_deg':0,'pitch_deg':-89})
        self.canvas.fit_objects()

    def three_quarter_view(self):
        self.canvas.apply_camera_state({**self.canvas.camera_state(),'yaw_deg':self.canvas.separated_yaw(),'pitch_deg':-28})
        self.canvas.fit_objects()

    def reset(self):
        for key, (widget, angle) in self.inputs.items():
            value = GENERATION_DEFAULTS[key]
            if isinstance(widget,QCheckBox):
                widget.setChecked(value)
            else:
                widget.setValue(complementary_angle(value) if angle else value)
        self.iterations.setValue(12)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._layout_timer.start(0)

    def showEvent(self, event):
        super().showEvent(event)
        self._layout_timer.start(0)

    def eventFilter(self, watched, event):
        if event.type() in (QEvent.Type.Resize,QEvent.Type.LayoutRequest,QEvent.Type.Show):
            self._layout_timer.start(0)
        if watched is self.canvas and event.type() in (QEvent.Type.Resize,QEvent.Type.Show):
            self._position_preview_controls()
        if watched is self.canvas and event.type()==QEvent.Type.Hide:
            self._show_travel_modes(self.travel_visibility_button.isChecked() and
                self.travel_visibility_button.isEnabled(),animate=False)
        return super().eventFilter(watched,event)

    def _position_preview_controls(self):
        if not hasattr(self,'preview_reset'):
            return
        width = max(self.preview_reset.sizeHint().width(),self.transparency_toggle.sizeHint().width(),
            self.transparency_toggle.fontMetrics().horizontalAdvance('Transparenz inaktiv')+24)
        for button in (self.preview_reset,self.transparency_toggle):
            button.setFixedWidth(width)
            button.raise_()
        self.preview_reset.move(0,max(0,self.canvas.height()-self.preview_reset.height()))
        self.transparency_toggle.move(0,max(0,self.preview_reset.y()-self.transparency_toggle.height()))
        right_width=max(self.travel_visibility_button.sizeHint().width(),self.travel_mode_toggle.sizeHint().width())
        for button in (self.travel_visibility_button,self.travel_mode_toggle):
            button.setFixedWidth(right_width)
            button.raise_()
        self.travel_mode_toggle.move(self.canvas.width()-right_width,
            self.canvas.height()-round(self.travel_mode_toggle.height()*self._travel_reveal))
        self.travel_visibility_button.move(self.canvas.width()-right_width,
            self.travel_mode_toggle.y()-self.travel_visibility_button.height())

    def _set_travel_reveal(self,value):
        self._travel_reveal=float(value)
        self._position_preview_controls()

    def _show_travel_modes(self,visible,*,animate=True):
        animation=self._travel_reveal_animation
        current=self._travel_reveal
        animation.stop()
        self.travel_mode_toggle.setEnabled(visible)
        target=float(visible)
        if not animate or not self.canvas.isVisible() or abs(target-current)<.001:
            self._set_travel_reveal(target)
            self.travel_mode_toggle.setVisible(visible)
            return
        self.travel_mode_toggle.show()
        with QSignalBlocker(animation):
            animation.setDuration(max(1,round(240*abs(target-current))))
            animation.setStartValue(current)
            animation.setEndValue(target)
            animation.setCurrentTime(0)
        animation.start()

    def _toggle_travel_visibility(self,visible):
        self.travel_visibility_button.setText('Fahrwege ausblenden' if visible else 'Fahrwege anzeigen')
        self.canvas.set_tower_travel_visible(visible)
        self._show_travel_modes(visible and self.travel_visibility_button.isEnabled())

    def set_preview_available(self,available):
        for button in (self.preview_reset,self.transparency_toggle,self.travel_visibility_button):
            button.setEnabled(available)
        self._show_travel_modes(available and self.travel_visibility_button.isChecked(),animate=False)

    def _set_transparency_active(self,active):
        self.transparency_toggle.setText('Transparenz aktiv' if active else 'Transparenz inaktiv')
        self.canvas.set_layer_transparency_enabled(active)
        self._position_preview_controls()

    def reset_preview(self):
        self.travel_visibility_button.setChecked(True)
        self.travel_mode_toggle.setChecked(False)
        self.canvas.set_cumulative_travel_visible(False)
        self.transparency_toggle.setChecked(True)
        self.logarithmic_scale.setChecked(True)
        self.normalized_scale.setChecked(self.time_chart.default_normalization())
        self.layer_reset_requested.emit()
        self.canvas.set_navigation_enabled(True)
        self.three_quarter_view()


    def refresh_layout(self):
        """Reserve expanded content before the scroll area can compress rows."""
        if not self.isVisible():
            return
        self._fit_numeric_fields()
        for row in self.rows.values():
            if hasattr(row, "_automatic_label_minimum"):
                row._automatic_label_minimum.refresh()
            else:
                row.label.setMinimumWidth(max(150, row.label.fontMetrics().horizontalAdvance(row.label.text()) + 30))
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
        self.updateGeometry()
        self.layout_changed.emit()


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
        # The chart can stack inside the preview. Its side-by-side preference
        # must not force the outer splitter to reparent a focused settings field.
        self.preview_display.setMinimumWidth(minimum_left)
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


    def _fit_numeric_fields(self):
        fit_numeric_fields(self.rows.values())

    def _build_footer(self):
        self.footer_widget = NativeFooter()
        self.footer_widget.setObjectName("nativeProjectFooter")
        self.footer_widget.setStyleSheet(FOOTER_STYLE)
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
        self._footer_actions_layout_mode = "single"
        self.open_output_button = QPushButton("Alle Exporte öffnen")
        self.open_output_button.setObjectName("openBaseOutputFolderButton")
        self.open_last_button = QPushButton("Letzten Export öffnen")
        self.open_last_button.setObjectName("openOutputFolderButton")
        self.open_report_button = QPushButton("Letzten Exportbericht öffnen")
        self.open_report_button.setObjectName("openExportReportButton")
        self.open_last_button.hide()
        self.open_report_button.hide()
        self.prepare_button = QPushButton("Druckplatte vorbereiten")
        self.prepare_button.setObjectName("previewButton")
        self.generate_button = QPushButton("Turm generieren")
        self.generate_button.setObjectName("previewButton")
        self.export_button = QPushButton("Projekt exportieren")
        self.export_button.setObjectName("exportButton")
        self.cancel_button = QPushButton("Abbrechen")
        self.cancel_button.setObjectName("nativeCancelButton")
        self.cancel_button.hide()
        self.export_button.hide()
        for column, button in enumerate((self.open_output_button, self.open_last_button,
                self.open_report_button, self.prepare_button, self.generate_button, self.cancel_button, self.export_button)):
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
            self.prepare_button, self.generate_button, self.cancel_button, self.export_button), fit_actions=self._fit_footer_actions)
        self.footer_widget.hide()


    def _fit_footer_actions(self, width):
        def set_labels(shorten_folders, report_level, shorten_actions):
            self.open_output_button.setText("Alle Exporte" if shorten_folders else "Alle Exporte öffnen")
            self.open_last_button.setText("Letzter Export" if shorten_folders else "Letzten Export öffnen")
            self.open_report_button.setText(("Letzten Exportbericht öffnen", "Exportbericht öffnen", "Exportbericht")[report_level])
            self.prepare_button.setText("Druckplatte vorbereiten")
            self.generate_button.setText("Turm generieren")
            self.export_button.setText("Projekt exportieren")
        narrow, self._footer_actions_layout_mode = fit_footer_actions(self.footer_actions_layout,
            (self.open_output_button, self.open_last_button, self.open_report_button),
            (self.prepare_button, self.generate_button, self.cancel_button, self.export_button), max(0, width-24), set_labels)
        return narrow
