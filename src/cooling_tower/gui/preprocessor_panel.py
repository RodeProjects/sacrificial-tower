"""Third-method UI and managed, cancelable G-code generation."""
from __future__ import annotations

from copy import deepcopy
from dataclasses import replace
import traceback

from PySide6.QtCore import QObject, Signal, Slot, QSignalBlocker

from cooling_tower.gui.background_jobs import JobKind
from cooling_tower.gui.generation_session import GenerationMode
from cooling_tower.gui.worker_contract import CancelableWorker
from cooling_tower.preprocessor import PreprocessorRequest, PreprocessorService
from cooling_tower.preprocessor_export import export_preprocessor_run
from cooling_tower.preview import PreviewState
from cooling_tower.preview.toolpath import PreviewCancelled


from cooling_tower.gui.preprocessor_controls import PreprocessorPanel
from cooling_tower.gui.preprocessor_positions import PreprocessorPositionDialog, PositionCache, position_cache_key, position_solution_key
from cooling_tower.calibration.gcode_integration import parse_bed_geometry


class PreprocessorWorker(CancelableWorker):
    progress = Signal(int, int, str)
    succeeded = Signal(int, object)
    failed = Signal(int, str, str)
    finished = Signal(int)

    def __init__(self, request_id, service, request):
        super().__init__()
        self.request_id, self.service, self.request = request_id, service, request

    @Slot()
    def run(self):
        try:
            result = self.service.prepare(self.request, cancellation_event=self.cancellation_event,
                progress_callback=lambda p, s: self.progress.emit(self.request_id, p, s))
        except PreviewCancelled:
            pass
        except Exception as error:
            if not self.cancellation_requested():
                self.failed.emit(self.request_id, str(error), traceback.format_exc())
        else:
            if self.cancellation_requested():
                result.dispose()
            else:
                self.succeeded.emit(self.request_id, result)
        finally:
            self.finished.emit(self.request_id)


class PreprocessorController(QObject):
    def __init__(self, window, panel):
        super().__init__(window)
        self.window, self.panel = window, panel
        self.session = window.generation_sessions[GenerationMode.PREPROCESSOR]
        self.service = PreprocessorService(window.user_data_root / "temporary")
        self.job_id = None
        self.request_id = -1_000_000
        self.cancelled = False
        self._locked_inputs = []
        self._zone_context = None
        self._profile_context = None
        self.position_dialog = None
        self._position_cache = None
        self._generation_position_key = None
        panel.changed.connect(self.changed)
        panel.generate_button.clicked.connect(self.generate)
        panel.cancel_button.clicked.connect(self.cancel)
        panel.export_button.clicked.connect(self.export)
        panel.positions_button.clicked.connect(self.open_position_editor)
        panel.open_output_button.clicked.connect(window.open_output_directory)
        panel.open_last_button.clicked.connect(window.open_stl_directory)
        panel.open_report_button.clicked.connect(window.show_last_export_report)
        window.background_job_manager.job_released.connect(self.released)
        self.refresh()

    def request(self):
        window = self.window
        result = window.profile_match_result
        if (window.prepared_analysis_source is None or window.analysis_snapshot is None
                or result is None or result.selected is None or not result.user_confirmed):
            raise ValueError("Zuerst STL, Slicer und Profile vorbereiten und bestätigen.")
        profile = result.selected.effective_profile
        profile = replace(profile, effective_values=deepcopy(dict(profile.effective_values)))
        self._sync_context(profile, window.prepared_analysis_source)
        return PreprocessorRequest(window.prepared_analysis_source, window.analysis_snapshot, profile, self.panel.settings())

    def ensure_context(self):
        result = self.window.profile_match_result
        if result is not None and result.selected is not None and self.window.prepared_analysis_source is not None:
            self._sync_context(result.selected.effective_profile, self.window.prepared_analysis_source)
        self.refresh()

    def _sync_context(self, profile, prepared):
        geometry = parse_bed_geometry(profile.effective_values)
        signature = (prepared.source_artifact.original_path, prepared.source_artifact.original_sha256, geometry)
        if self._zone_context is not None and signature != self._zone_context:
            self._position_cache = None
            self.panel.exclusions = ()
            if self.position_dialog is not None:
                self.position_dialog.reject()
            self.panel.manual_position_edits.clear()
        self._zone_context = signature
        profile_key = repr(profile.effective_values)
        if self._profile_context != profile_key:
            self._position_cache = None
            if self.position_dialog is not None:
                self.position_dialog.reject()
            self._profile_context = profile_key
            self.panel.set_profile_values(profile.effective_values)

    def open_position_editor(self):
        if self.job_id is not None:
            return
        if self.position_dialog is not None:
            self.position_dialog.raise_()
            return
        try:
            request = self.request()
            geometry = parse_bed_geometry(request.profile.effective_values)
            if geometry is None:
                raise ValueError("Für den Positionseditor fehlt eine bestätigte Druckbettgeometrie.")
        except (ValueError, OSError) as error:
            self.panel.status.setText(str(error))
            return
        if self._position_cache is None or not self._position_cache.matches(request):
            self._position_cache = PositionCache(position_cache_key(request))
        dialog = PreprocessorPositionDialog(request, self.service, self.window.background_job_manager,
            geometry, self.panel.manual_position_edits, self.window, cache=self._position_cache)
        self.position_dialog = dialog
        def apply():
            self._position_cache.requested_key = position_solution_key(dialog.settings)
            for flag, fields in (("automatic_position", ("center_x_mm", "center_y_mm")),
                    ("automatic_wait_position", ("wait_x_mm", "wait_y_mm"))):
                with QSignalBlocker(self.panel.automatic[flag]):
                    self.panel.automatic[flag].setChecked(getattr(dialog.settings, flag))
                for field in fields:
                    with QSignalBlocker(self.panel.inputs[field]):
                        self.panel.inputs[field].setValue(getattr(dialog.settings, field))
                if not getattr(dialog.settings, flag):
                    self.panel.manual_position_edits.add(flag)
            with QSignalBlocker(self.panel.inputs["edge_clearance_mm"]):
                self.panel.inputs["edge_clearance_mm"].setValue(dialog.settings.edge_clearance_mm)
            self.panel._changed()
        dialog.accepted.connect(apply)
        dialog.finished.connect(lambda _: self._close_editor(dialog))
        dialog.open()

    def _close_editor(self, dialog):
        if self.position_dialog is dialog:
            self.position_dialog = None
        dialog.deleteLater()

    def changed(self):
        self.invalidate()
        self.panel.status.setText("Einstellungen geändert. G-Code und Vorschau bitte neu erzeugen.")

    def invalidate(self):
        if self.position_dialog is not None and self.position_dialog.isVisible():
            self.position_dialog.reject()
        if self.job_id is not None:
            self.cancel()
        self.session.discard_preview()
        self.panel.clear_automatic_values()
        self.panel.canvas.set_scene(None)
        self.panel.canvas.set_busy(False)
        self.panel.clear_timing()
        self.panel.error_label.hide()
        self.refresh()

    def generate(self):
        if (self.window._closing or self.job_id is not None
                or self.window.generation_mode is not GenerationMode.PREPROCESSOR):
            return
        if self.window.background_job_manager.has_active(JobKind.PREVIEW) or self.window.background_job_manager.has_active(JobKind.EXPORT):
            return
        try:
            request = self.request()
        except ValueError as error:
            self.critical_error(str(error))
            return
        self.session.discard_preview()
        self.panel.clear_automatic_values()
        self.panel.error_label.hide()
        self.request_id -= 1
        self.panel.canvas.set_scene(None)
        self.panel.clear_timing()
        worker = PreprocessorWorker(self.request_id, self.service, request)
        worker.progress.connect(self.progress)
        worker.succeeded.connect(self.succeeded)
        worker.failed.connect(self.failed)
        self.cancelled = False
        self.session.preview_state = PreviewState.BUILDING
        self.panel.progress.setValue(0)
        self.panel.status.setText("Postprozessor startet …")
        self.panel.canvas.set_busy(True, step="Originalquelle und Druckprofil prüfen …")
        self._generation_position_key = position_cache_key(request)
        self.job_id = self.window.background_job_manager.start_job(kind=JobKind.PREVIEW,
            request_id=self.request_id, worker=worker, parent_operation_id="preprocessor")
        self._locked_inputs = [(widget, widget.isEnabled()) for widget in (
            self.window.drop_zone, self.window.slicer_combo, self.window.slicer_refresh_button,
            self.window.slicer_manual_button, self.window.machine_profile_combo, self.window.process_profile_combo,
            self.window.filament_profile_combo, self.window.show_all_profiles_checkbox, self.window.profile_confirm_button)]
        for widget, _enabled in self._locked_inputs:
            widget.setEnabled(False)
        self.refresh()
        self.window._refresh_phase17_actions()

    def progress(self, request_id, percent, status):
        if request_id == self.request_id and not self.window._closing:
            self.panel.progress.setValue(percent)
            self.panel.status.setText(status)
            self.panel.canvas.set_busy(True, percent=percent, step=status)

    def succeeded(self, request_id, result):
        if request_id != self.request_id or self.cancelled or self.window._closing:
            result.dispose()
            return
        self.session.preview = result
        self.session.preview_state = PreviewState.CURRENT
        self.session.successful_request = result.request
        self.panel.canvas.set_busy(False)
        if result.placement is not None:
            self._position_cache = PositionCache(self._generation_position_key, result.placement)
            self._position_cache.remember(result.effective_settings, result.placement_solution, "")
        self.panel.canvas.set_scene(result.scene)
        self.panel.canvas.apply_camera_state({**self.panel.canvas.camera_state(),
            "yaw_deg": self.panel.canvas.separated_yaw(), "pitch_deg": -28})
        self.panel.canvas.fit_scene()
        self.panel.show_automatic_values({
            **{name: getattr(result.effective_settings, name) for name in (
                "target_layer_time_s", "print_speed_mm_s", "travel_speed_mm_s", "retract_mm", "retract_speed_mm_s",
                "tower_brim_width_mm", "tower_brim_gap_mm")},
            "height_mm": result.height_mm, "diameter_mm": result.diameter_mm,
            "base_width_mm": result.base_width_mm,
            **dict(zip(("center_x_mm", "center_y_mm"), result.scene.tower_center_xy_mm if result.height_mm else (None, None))),
            **dict(zip(("wait_x_mm", "wait_y_mm"), result.scene.wait_position_xy_mm or (None, None))),
        })
        self.panel.refresh_resets()
        self.panel.show_timing(result)
        self.panel.status.setText("G-Code und rekonstruierte Vorschau sind bereit." if result.height_mm else
            "Alle Schichten erreichen die Zielzeit. Der G-Code bleibt unverändert; kein Turm erforderlich.")
        self.panel.refresh_layout()
        self.refresh()

    def failed(self, request_id, message, _details):
        if request_id == self.request_id and not self.window._closing:
            self.critical_error(message)

    def critical_error(self, message):
        self.panel.canvas.set_busy(False)
        self.session.discard_preview()
        self.panel.clear_automatic_values()
        self.session.preview_state = PreviewState.FAILED
        self.panel.canvas.set_scene(None)
        self.panel.clear_timing()
        self.panel.error_label.setText("Export gesperrt · " + message)
        self.panel.error_label.show()
        self.panel.status.setText(message)
        self.refresh()
        if self.window.generation_mode is GenerationMode.PREPROCESSOR:
            self.window.settings_scroll.ensureWidgetVisible(self.panel.error_label)

    def released(self, job):
        if job.job_id != self.job_id:
            return
        self.job_id = None
        self.panel.canvas.set_busy(False)
        for widget, enabled in self._locked_inputs:
            widget.setEnabled(enabled)
        self._locked_inputs = []
        if not self.window._closing:
            if self.cancelled:
                self.panel.status.setText("Postprozessor abgebrochen.")
                self.session.preview_state = PreviewState.EMPTY
            self.refresh()
            self.window._refresh_phase17_actions()

    def cancel(self):
        if self.job_id is not None:
            self.cancelled = True
            self.window.background_job_manager.cancel_job(self.job_id, reason="preprocessor_cancelled")
        self.refresh()

    def refresh(self):
        busy = self.job_id is not None
        self.panel.input_group.setEnabled(not busy)
        self.panel.advanced_group.setEnabled(not busy)
        self.panel.generate_button.setEnabled(not busy)
        self.panel.reset_button.setEnabled(not busy)
        self.panel.cancel_button.setEnabled(busy and not self.cancelled)
        self.panel.cancel_button.setVisible(busy)
        self.panel.export_button.setEnabled(not busy and self.session.preview is not None)
        self.panel.export_button.setVisible(not busy and self.session.preview is not None)
        self.panel.progress.setVisible(busy)
        exported = self.session.last_export_report
        self.panel.export_actions.setVisible(exported is not None)
        self.panel.open_output_button.setEnabled(not busy)
        directory = self.session.latest_export_directory
        self.panel.open_last_button.setEnabled(not busy and directory is not None and directory.is_dir())
        self.panel.open_report_button.setEnabled(not busy and exported is not None)

    def export(self):
        result = self.session.preview
        if result is None or self.job_id is not None:
            return
        try:
            current = self.request()
            if current != result.request:
                raise ValueError("Die Einstellungen oder Quelle haben sich geändert. Bitte G-Code neu erzeugen.")
            exported = export_preprocessor_run(self.service, result,
                self.window.export_directory(GenerationMode.PREPROCESSOR))
        except ValueError as error:
            self.critical_error(str(error))
        except OSError as error:
            self.panel.status.setText(str(error))
            if not result.gcode_path.is_file():
                self.critical_error("Die erzeugte G-Code-Datei ist nicht mehr verfügbar. Bitte neu erzeugen.")
        else:
            self.session.export_result = exported
            self.session.last_export_report = exported
            self.session.latest_export_directory = exported.run_directory
            self.session.latest_export_root = str(self.window.export_directory(GenerationMode.PREPROCESSOR))
            self.session.latest_export_unavailable_reason = ""
            self.panel.status.setText(f"G-Code exportiert: {exported.output_path.name}")
            self.window._refresh_folder_action_states()
            self.window._show_export_success_dialog(exported)
            self.refresh()
