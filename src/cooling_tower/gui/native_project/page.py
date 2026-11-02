"""Independent native-project editing page and worker presentation."""
from pathlib import Path
import json
from PySide6.QtCore import Qt, QSize, QPoint, Signal, QSignalBlocker, QUrl
from PySide6.QtGui import QIcon, QPixmap, QDesktopServices
from PySide6.QtWidgets import (QWidget, QLabel, QPushButton, QToolButton, QVBoxLayout,
    QHBoxLayout, QCheckBox, QScrollArea, QMenu, QFileDialog)
from cooling_tower.angles import complementary_angle
from cooling_tower.calibration.gcode_integration import parse_bed_geometry
from cooling_tower.gui.design_tokens import METRICS
from cooling_tower.gui.native_project.controller import NativeProjectController
from cooling_tower.gui.native_project.editor import NativeEditorPanel
from cooling_tower.gui.native_project.header import NativeWorkflowHeader
from cooling_tower.gui.native_project.plate_selector import NativePlateSelector
from cooling_tower.gui.widgets.section_card import SectionCard
from cooling_tower.native_project.context import ProjectProblem
from cooling_tower.native_project.defaults import GENERATION_DEFAULTS
from cooling_tower.native_project.options import NativeCalibrationOptions
from cooling_tower.native_project.settings import NativeGenerationSettings, embedded_expansion_threshold
from cooling_tower.preview.models import PreviewScene
from cooling_tower.tower.solid_profile import validate_solid_settings
from cooling_tower.version import APP_NAME, APP_SUBTITLE, APP_VERSION_LABEL


def _label(text='', *, name=None, wrap=True):
    label = QLabel(text)
    label.setTextFormat(Qt.TextFormat.PlainText)
    label.setWordWrap(wrap)
    if name:
        label.setObjectName(name)
    return label


class NativeProjectPage(QWidget):
    source_selected = Signal(str)
    back_requested = Signal()

    def __init__(self, manager, parent=None, *, controller=None, export_directory=None):
        super().__init__(parent)
        self.setObjectName('nativeProjectPage')
        self.controller = controller or NativeProjectController(manager,self)
        self._busy = False
        self._displayed = self._path = self._last_export = None
        self._last_export_root = None
        self._export_directory = export_directory or Path('output/exports_3mf_projects')
        self._settings_values = dict(GENERATION_DEFAULTS)
        self._input_signature = None
        root = QVBoxLayout(self)
        root.setContentsMargins(0,0,0,0)
        root.setSpacing(0)
        self.main_header = QWidget()
        self.main_header.setObjectName('mainHeader')
        self.main_header.setProperty('preparationConfirmed',True)
        head = QVBoxLayout(self.main_header)
        head.setContentsMargins(0,0,0,0)
        title, subtitle = QLabel(APP_NAME), QLabel(APP_SUBTITLE)
        title.setObjectName('titleLabel'); subtitle.setObjectName('subtitleLabel')
        tools = QWidget()
        tools_layout = QVBoxLayout(tools)
        tools_layout.setContentsMargins(0,0,0,0)
        tools_layout.setSpacing(4)
        self.options_button = QToolButton()
        self.options_button.setObjectName('optionsButton')
        self.options_button.setIcon(QIcon(str(Path(__file__).parents[1]/'assets/menu.svg')))
        self.options_button.setIconSize(QSize(18,18))
        self.options_button.setFixedSize(METRICS.info_button_diameter_px,METRICS.info_button_diameter_px)
        self.options_button.setAccessibleName('Menü öffnen')
        self.options_menu = QMenu(self.options_button)
        self.options_menu.setObjectName('mainOptionsMenu')
        for menu_title,method,icon in (
            ('Allgemeine Einstellungen','show_joint_slice_settings','settings_gear.svg'),
            ('Hilfe && Feedback','show_support_report_dialog','document.svg'),
            ('Buy me a coffee','show_voluntary_support_dialog','coffee.svg'),
            ('Über '+APP_NAME,'show_about_dialog','info_circle.svg')):
            action = self.options_menu.addAction(QIcon(str(Path(__file__).parents[1]/'assets'/icon)),menu_title)
            action.triggered.connect(lambda _checked=False,name=method:getattr(self.window(),name,lambda:None)())
        self.version_label = QLabel(APP_VERSION_LABEL)
        self.version_label.setObjectName('versionLabel')
        tools_layout.addWidget(self.options_button,0,Qt.AlignmentFlag.AlignHCenter)
        tools_layout.addWidget(self.version_label,0,Qt.AlignmentFlag.AlignRight)
        self.header = NativeWorkflowHeader(title,subtitle,tools,button_height=self.options_button.height())
        head.addWidget(self.header)
        root.addWidget(self.main_header)
        self.header.set_shadow_overlay_parent(self)
        self.header.set_generation_mode('native_project')
        self.header.set_actions_visible(True)
        self.header.method_selection.back_button.clicked.connect(self.back_requested)
        self.header.preparation_button.clicked.connect(self.back_requested)
        self.options_button.clicked.connect(self._show_options_menu)
        self.project_group = SectionCard('Datei und eingebettete Projekteinstellungen',collapsible=False)
        info = self.project_group.content_layout
        self.file_label = _label()
        self.context_label = _label()
        self.notice_label = _label(name='nativeNotice')
        info.addWidget(self.file_label); info.addWidget(self.context_label); info.addWidget(self.notice_label)
        self.plates = NativePlateSelector()
        self.plates.currentRowChanged.connect(self._plate_changed)
        info.addWidget(self.plates)
        self.error_label = _label(name='errorLabel')
        self.error_label.hide()
        info.addWidget(self.error_label)
        self.guide = QLabel()
        self.guide.setWordWrap(True)
        self.guide.setTextFormat(Qt.TextFormat.RichText)
        self.guide.setText('<b>Vollständiges Projekt speichern</b><br>'
            'Im erzeugenden Slicer <b>Datei → Projekt speichern als</b> wählen. Das Projekt muss Drucker-, Material- und Prozesseinstellungen enthalten.<br><br>'
            'Anycubic Slicer Next <small>(2.0.0.3)</small><br>Bambu Studio <small>(02.08.02.61)</small><br>'
            'PrusaSlicer <small>(2.9.6)</small><br>OrcaSlicer <small>(Engine 2.4.2 · Paket 2.4.3.0)</small>')
        self.guide.hide(); info.addWidget(self.guide)
        root.addWidget(self.project_group)
        self.editor = NativeEditorPanel()
        self.splitter = self.editor
        self.settings_group = self.editor.input_group
        self.advanced_group = self.editor.advanced_group
        self._inputs = self.editor.inputs
        self.iterations = self.editor.iterations
        self.canvas, self.chart = self.editor.canvas, self.editor.time_chart
        self.chart_label = QLabel('Layerzeiten',self)
        self.chart_label.hide()
        self.layer_spin, self.layer_value = self.editor.layer_spin, self.editor.layer_details
        self.status, self.progress = self.editor.status, self.editor.progress
        self.prepare_button, self.generate_button = self.editor.prepare_button, self.editor.generate_button
        self.cancel_button, self.export_button = self.editor.cancel_button, self.editor.export_button
        self.choose_button = QPushButton('Andere Datei auswählen …',self)
        self.choose_button.hide()
        self.choose_button.clicked.connect(self.choose_source)
        self.settings_scroll = QScrollArea()
        self.settings_scroll.setObjectName('settingsScroll')
        self.settings_scroll.setWidgetResizable(True)
        self.settings_scroll.setFrameShape(QScrollArea.Shape.NoFrame)
        self.settings_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.settings_scroll.setWidget(self.editor)
        root.addWidget(self.settings_scroll,1)
        root.addWidget(self.editor.footer_widget)
        self.prepare_button.clicked.connect(lambda:self.controller.prepare(self.plate_id()))
        self.generate_button.clicked.connect(self._generate)
        self.cancel_button.clicked.connect(self.controller.cancel)
        self.export_button.clicked.connect(self._export)
        self.editor.changed.connect(self._settings_changed)
        self.editor.layer_selected.connect(self._select_layer)
        self.editor.layer_reset_requested.connect(self._reset_layer)
        self.editor.open_output_button.clicked.connect(lambda:self._open_path(self._export_root()))
        self.editor.open_last_button.clicked.connect(lambda:self._open_path(self._last_export.parent if self._last_export else None))
        self.editor.open_report_button.clicked.connect(lambda:self._open_path(self._last_export.parent/'Projektbericht.txt' if self._last_export else None))
        self.controller.imported_ready.connect(self._imported)
        self.controller.prepared_ready.connect(self._prepared)
        self.controller.generated_ready.connect(self._generated)
        self.controller.exported.connect(self._exported)
        self.controller.busy_changed.connect(self._set_busy)
        self.controller.status_changed.connect(self.status.setText)
        self.controller.failed.connect(self._failed)
        self._update_controls()
        self._input_signature = self._settings_signature()

    def _show_options_menu(self):
        menu = self.options_menu
        menu.ensurePolished()
        menu.adjustSize()
        size = menu.sizeHint()
        button = self.options_button.mapToGlobal(QPoint(0,0))
        window = self.window()
        top_left = window.mapToGlobal(QPoint(0,0))
        right,bottom = top_left.x()+window.width(),top_left.y()+window.height()
        x = max(top_left.x(),min(button.x()+self.options_button.width()-size.width(),right-size.width()))
        below = button.y()+self.options_button.height()
        y = below if below+size.height()<=bottom else max(top_left.y(),button.y()-size.height())
        menu.popup(QPoint(x,y))

    def _export_root(self):
        value = self._export_directory() if callable(self._export_directory) else self._export_directory
        return Path(value).expanduser()

    def _open_path(self, path):
        if path is not None and Path(path).exists():
            QDesktopServices.openUrl(QUrl.fromLocalFile(str(Path(path).resolve())))

    def _exported(self, path):
        self._last_export = Path(path)
        self._last_export_root = self._export_root().absolute()
        self.status.setText('Geprüftes natives Projekt exportiert')
        self._refresh_export_actions()

    def _refresh_export_actions(self):
        root = self._export_root().absolute()
        if root != self._last_export_root or (self._last_export is not None and not self._last_export.is_file()):
            self._last_export = None
            candidates = []
            try:
                for project in root.glob('Projekt_*/Projekt_mit_Turm.3mf'):
                    report = project.parent/'Projektbericht.json'
                    if project.parent.resolve().parent != root.resolve() or not project.is_file() or not report.is_file() or report.stat().st_size > 1024*1024:
                        continue
                    try:
                        metadata = json.loads(report.read_text(encoding='utf-8'))
                        if isinstance(metadata, dict) and metadata.get('native_project_report_version') == 1:
                            candidates.append((project.stat().st_mtime_ns,project))
                    except (OSError,ValueError,TypeError):
                        continue
                if candidates:
                    self._last_export = max(candidates,key=lambda item:(item[0],str(item[1])))[1]
            except OSError:
                pass
            self._last_export_root = root
        self.editor.open_output_button.setEnabled(root.is_dir())
        available = self._last_export is not None and self._last_export.is_file()
        self.editor.open_last_button.setVisible(available)
        self.editor.open_report_button.setVisible(available and (self._last_export.parent/'Projektbericht.txt').is_file())
        self.editor.footer_widget._fit_timer.start(0)

    def _export(self):
        self.controller.export_run(self._export_root())

    def collect_settings(self):
        values = dict(self._settings_values)
        for key, (widget, angle) in self._inputs.items():
            if not isinstance(widget,QCheckBox) and widget.isEnabled() and (
                    getattr(widget,'input_pending',False) or not widget.hasAcceptableInput()):
                raise ValueError('Bitte den eingegebenen Zahlenwert bestätigen oder korrigieren.')
            value = widget.isChecked() if isinstance(widget, QCheckBox) else widget.value()
            values[key] = complementary_angle(value) if angle else value
        settings = NativeGenerationSettings.from_mapping(values)
        validate_solid_settings(settings)
        return settings

    def _settings_changed(self, *_):
        if not hasattr(self, 'export_button'):
            return
        signature = self._settings_signature()
        if signature == self._input_signature:
            self._update_controls()
            return
        self._input_signature = signature
        self.editor.show_automatic_values({})
        if self.controller.generated is not None:
            self.controller.generated.close()
            self.controller.generated = None
            if self.controller.prepared:
                self._show_result(self.controller.prepared)
            self.status.setText('Einstellungen geändert · erneut berechnen')
        self._update_controls()

    def _settings_signature(self):
        values = []
        for key,(widget,_angle) in self._inputs.items():
            if isinstance(widget,QCheckBox):
                values.append((key,widget.isChecked()))
            else:
                values.append((key,widget.value(),widget.isEnabled() and widget.input_pending))
        return (*values,('iterations',self.iterations.value(),self.iterations.input_pending))

    def choose_source(self):
        selected, _ = QFileDialog.getOpenFileName(self, 'STL oder natives 3MF-Projekt auswählen',
            str(self._path.parent if self._path else Path.home()), 'Modelle und Projekte (*.stl *.3mf)')
        if selected:
            self.source_selected.emit(selected)

    def open_source(self, path):
        self._path = Path(path)
        self.file_label.setText(self._path.name)
        self.context_label.clear()
        self.notice_label.clear()
        self.error_label.hide()
        self.guide.hide()
        self.splitter.hide()
        self.plates.hide()
        with QSignalBlocker(self.plates):
            self.plates.clear()
        self._clear_display()
        self.controller.load(path)

    def _imported(self, imported):
        context = imported.session.context
        self.editor.set_profile_angle(embedded_expansion_threshold(context))
        installation = imported.installation
        product = installation.display_name if installation else {
            'anycubic_slicer_next':'Anycubic Slicer Next', 'bambu_studio':'Bambu Studio',
            'orca_slicer':'OrcaSlicer', 'prusa_slicer':'PrusaSlicer'}[context.adapter_id]
        self.context_label.setText('Iterativ · Druckplatte auswählen und vorbereiten')
        self.header.set_facts((('Dateiname',self._path.name),('Slicer',product)))
        self.notice_label.setText(f'Projekt erstellt mit {context.producer_version} · {len(context.plates)} Druckplatte(n)')
        thumbnails = dict(imported.thumbnails)
        self.plates.setVisible(len(context.plates) > 1 or bool(thumbnails))
        if len(context.plates) == 1:
            self.notice_label.setText(f'Projekt erstellt mit {context.producer_version} · {context.plates[0].name} · {context.plates[0].object_count} Objektinstanz(en)')
        with QSignalBlocker(self.plates):
            self.plates.clear()
            for plate in context.plates:
                pixmap = None
                if plate.identifier in thumbnails:
                    pixmap = QPixmap()
                    pixmap.loadFromData(thumbnails[plate.identifier], 'PNG')
                self.plates.add_plate(plate,pixmap)
            self.plates.setCurrentRow(0)
        self.plates._refresh_selection()
        self.splitter.setVisible(installation is not None)
        if installation is None:
            self._failed('Der zum Projekt gehörende Slicer wurde nicht ausführbar gefunden. Nach seiner Einrichtung die Datei erneut auswählen.', '', ProjectProblem.MISSING_SLICER)
        else:
            self.status.setText('Projekt erkannt · Druckplatte auswählen und vorbereiten')
        self._update_controls()

    def plate_id(self):
        item = self.plates.currentItem()
        return item.data(Qt.ItemDataRole.UserRole) if item else ''

    def _plate_changed(self, *_):
        if self.controller.imported is None:
            return
        self.controller.select_plate()
        self._clear_display()
        self.error_label.hide()
        self.status.setText('Druckplatte geändert · erneut vorbereiten')
        self._update_controls()

    def _clear_display(self):
        self._displayed = None
        self.editor.show_automatic_values({})
        self.canvas.set_scene(None)
        self.chart.set_data()
        self.layer_value.clear()
        self.layer_spin.setRange(1,1)
        self.layer_spin.setEnabled(False)
        self.editor.layer_reset.setEnabled(False)
        self.editor.set_preview_available(False)
        with QSignalBlocker(self.editor.normalized_scale):
            self.editor.normalized_scale.setChecked(False)

    def _prepared(self, result):
        self._show_result(result)
        self.error_label.hide()
        self.status.setText(f'{result.analysis.layer_count} Schichten vorbereitet · Turm generieren verfügbar')
        if self.controller.imported.session.original_changed():
            self.notice_label.setText('Die Originaldatei wurde extern geändert. Weiterverarbeitet wird die unveränderte importierte Momentaufnahme.')

    def _generated(self, generated):
        self.editor.show_automatic_values({'manual_base_width_mm':getattr(generated,'base_width_mm',None),
                                          'circle_segments':getattr(generated,'circle_segments',None)})
        if generated.prepared:
            self._show_result(generated.prepared, generated=generated)
        self.status.setText(generated.message)

    def _show_result(self, result, *, generated=None):
        self._displayed = result
        self.layer_spin.setEnabled(True)
        self.editor.layer_reset.setEnabled(True)
        self.editor.set_preview_available(True)
        paths = result.toolpaths
        source, tower = [], []
        source_heights, tower_heights = [], []
        center = generated.tower_center_mm if generated else None
        radius = generated.tower_radius_mm if generated else 0.
        logical_heights = paths.segment_layer_z or tuple(segment.end.z for segment in paths.object_segments)
        for segment, logical_z in zip(paths.object_segments, logical_heights, strict=True):
            in_tower = center and all((point.x-center[0])**2+(point.y-center[1])**2 <= (radius+1.)**2 for point in (segment.start,segment.end))
            (tower if in_tower else source).append(segment)
            (tower_heights if in_tower else source_heights).append(logical_z)
        bed = parse_bed_geometry(result.context.settings.as_dict())
        layer_indices={round(layer.z_mm,5):index for index,layer in enumerate(result.analysis.layers)}
        travels=getattr(paths,'travel_segments',())
        travel_heights=getattr(paths,'travel_layer_z',())
        scene = PreviewScene(tuple(source), tuple(tower), bed.bounds, center or (0.,0.),
            paths.source_segment_count, len(paths.object_segments), result.analysis.maximum_print_z_mm if generated else 0.,
            object_height_mm=result.analysis.maximum_print_z_mm, object_layer_count=result.analysis.layer_count,
            tower_layer_count=result.analysis.layer_count if generated else 0, bed_geometry=bed,
            layer_z_mm=tuple(layer.z_mm for layer in result.analysis.layers), seam_points=paths.seam_points,
            tower_travel_segments=travels,
            tower_travel_layer_indices=tuple(layer_indices[round(z,5)] for z in travel_heights))
        initial_view=self.canvas.scene is None
        self.canvas.set_scene(scene, preserve_view=self.canvas.scene is not None,
            object_layer_heights=source_heights, tower_layer_heights=tower_heights,
            seam_layer_heights=paths.seam_layer_z)
        if initial_view:self.editor.three_quarter_view()
        self.chart_label.setText('Gemeinsam geslicte Schichtzeit' if generated else 'Schichtzeit der ursprünglichen Druckplatte')
        layers = result.analysis.layers
        target = self._inputs['target_layer_time_s'][0].value()
        if generated is None:
            self.chart.set_data(tuple(layer.total_time_s for layer in layers), (0.,)*len(layers), (0.,)*len(layers),
                                tuple(layer.z_mm for layer in layers), target)
        else:
            original = {round(layer.z_mm,5): layer.total_time_s for layer in self.controller.prepared.analysis.layers}
            self.chart.set_comparison(tuple(original.get(round(layer.z_mm,5),0.) for layer in layers),
                tuple(layer.total_time_s for layer in layers), tuple(layer.z_mm for layer in layers), target)
        with QSignalBlocker(self.editor.normalized_scale):
            self.editor.normalized_scale.setChecked(self.chart.normalized)
        with QSignalBlocker(self.layer_spin):
            self.layer_spin.setRange(1, len(layers))
        self._select_layer(len(layers),activate_transparency=False)
        self.canvas.set_layer_height(None)

    def _select_layer(self, number, *, activate_transparency=True):
        if self._displayed is None:
            return
        layers = self._displayed.analysis.layers
        number = max(1, min(int(number), len(layers)))
        with QSignalBlocker(self.layer_spin):
            self.layer_spin.setValue(number)
        layer = layers[number-1]
        self.chart.select_layer(number)
        self.canvas.set_layer_height(layer.z_mm)
        self.canvas.set_travel_layer_height(layer.z_mm)
        if activate_transparency:
            self.editor.transparency_toggle.setChecked(True)
        self.canvas.set_layer_transparency_enabled(self.editor.transparency_toggle.isChecked())
        self.layer_value.setText(f'Z {layer.z_mm:.2f} mm · {layer.total_time_s:.2f} s')

    def _reset_layer(self):
        self._select_layer(self.layer_spin.maximum(),activate_transparency=False)
        self.canvas.set_layer_height(None)

    def _generate(self):
        try:
            settings = self.collect_settings()
            self.error_label.hide()
            self.controller.generate(settings, NativeCalibrationOptions(maximum_iterations=self.iterations.value(), time_tolerance_s=settings.layer_time_tolerance_s))
        except ValueError as error:
            self._failed(str(error), '', None)

    def _set_busy(self, value):
        self._busy = bool(value)
        self.progress.setVisible(self._busy)
        self.settings_group.setEnabled(not self._busy)
        self.advanced_group.setEnabled(not self._busy)
        self._update_controls()

    def _update_controls(self):
        imported = self.controller.imported
        ready = imported is not None and imported.installation is not None and bool(self.plate_id())
        try:
            self.collect_settings()
            valid = True
        except ValueError:
            valid = False
        prepared = self.controller.prepared is not None
        generated = self.controller.generated is not None and self.controller.generated.prepared is not None
        self.prepare_button.setVisible(ready and not prepared and not self._busy)
        self.prepare_button.setEnabled(ready and not self._busy)
        self.generate_button.setVisible(prepared and not generated and not self._busy)
        self.generate_button.setEnabled(prepared and valid and not self._busy)
        self.export_button.setVisible(generated and not self._busy)
        self.export_button.setEnabled(generated and not self._busy)
        self.cancel_button.setVisible(self._busy)
        self.cancel_button.setEnabled(self._busy)
        self.editor.footer_widget.setVisible(ready)
        self._refresh_export_actions()

    def _failed(self, message, details, problem):
        self.error_label.setText(message)
        self.error_label.setToolTip(details)
        self.error_label.show()
        self.guide.setVisible(problem is ProjectProblem.INCOMPLETE)
        self.status.setText('Verarbeitung nicht abgeschlossen')
        self._update_controls()

    def deactivate(self):
        self.controller.deactivate()
        self._clear_display()

    def close_after_shutdown(self):
        self.controller.close_after_shutdown()
