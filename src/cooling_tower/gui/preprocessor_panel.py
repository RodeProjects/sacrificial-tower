"""Third-method UI and managed, cancelable G-code generation."""
from __future__ import annotations

from copy import deepcopy
from dataclasses import replace
import traceback

from PySide6.QtCore import QObject, Signal, Slot, Qt
from PySide6.QtWidgets import QApplication

from cooling_tower.gui.background_jobs import JobKind
from cooling_tower.gui.generation_session import GenerationMode
from cooling_tower.gui.worker_contract import CancelableWorker
from cooling_tower.preprocessor import PreprocessorRequest, PreprocessorService
from cooling_tower.preprocessor_export import export_preprocessor_run
from cooling_tower.preview import PreviewState
from cooling_tower.preview.toolpath import PreviewCancelled


from cooling_tower.gui.preprocessor_controls import PreprocessorPanel
from cooling_tower.gui.preprocessor_exclusions import PreprocessorExclusionDialog
from cooling_tower.calibration.gcode_integration import parse_bed_geometry
from cooling_tower.preview.toolpath import analyze_deposition_toolpaths
from cooling_tower.preprocessor_profiles import printhead_envelope


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
        self.exclusion_dialog = None
        panel.changed.connect(self.changed)
        panel.generate_button.clicked.connect(self.generate)
        panel.cancel_button.clicked.connect(self.cancel)
        panel.export_button.clicked.connect(self.export)
        panel.exclusions_button.clicked.connect(self.open_exclusion_editor)
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
            had_exclusions = bool(self.panel.exclusions)
            self.panel.exclusions = ()
            self.panel.exclusions_button.setText("Eigene Sperrflächen bearbeiten …")
            if self.exclusion_dialog is not None:
                self.exclusion_dialog.reject()
            if had_exclusions:
                self.panel.status.setText("Quelle oder Druckbett geändert: Eigene Sperrflächen wurden zurückgesetzt. Bitte Hindernisse erneut prüfen.")
        self._zone_context = signature
        profile_key = repr(profile.effective_values)
        if self._profile_context != profile_key:
            self._profile_context = profile_key
            self.panel.set_profile_values(profile.effective_values)

    def open_exclusion_editor(self):
        if self.job_id is not None:
            return
        try:
            request = self.request()
            geometry = parse_bed_geometry(request.profile.effective_values)
            if geometry is None:
                raise ValueError("Für den Sperrflächeneditor fehlt eine bestätigte Druckbettgeometrie.")
            request.validate_source()
            QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
            try:
                segments = (self.panel.canvas.scene.object_segments if self.panel.canvas.scene is not None else
                    analyze_deposition_toolpaths(request.prepared_source.analysis_gcode_path,
                        expected_layer_count=request.snapshot.layer_count).object_segments)
            finally:
                QApplication.restoreOverrideCursor()
        except (ValueError, OSError) as error:
            self.panel.status.setText(str(error))
            return
        if self.exclusion_dialog is not None:
            self.exclusion_dialog.raise_()
            return
        dialog = PreprocessorExclusionDialog(geometry, self.panel.exclusions, segments, self.window,
            head_radius_mm=printhead_envelope(request.profile.effective_values, geometry).radius_mm + 1)
        self.exclusion_dialog = dialog
        context = self._zone_context
        def apply():
            if self._zone_context != context:
                return
            zones = dialog.canvas.zones
            if zones != self.panel.exclusions:
                self.panel.exclusions = zones
                self.panel.exclusions_button.setText(f"Eigene Sperrflächen bearbeiten … ({len(zones)})")
                self.changed()
        dialog.accepted.connect(apply)
        dialog.finished.connect(lambda _: self._close_editor(dialog))
        dialog.open()

    def _close_editor(self, dialog):
        if self.exclusion_dialog is dialog:
            self.exclusion_dialog = None
        dialog.deleteLater()

    def changed(self):
        self.invalidate()
        self.panel.status.setText("Einstellungen geändert. G-Code und Vorschau bitte neu erzeugen.")

    def invalidate(self):
        if self.job_id is not None:
            self.cancel()
        self.session.discard_preview()
        self.panel.clear_automatic_values()
        self.panel.canvas.set_scene(None)
        self.panel.clear_timing()
        self.panel.error_label.hide()
        self.panel.summary.setText("G-Code und Vorschau bitte aus dem ursprünglichen Pre-Slice neu erzeugen.")
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
        self.panel.status.setText("Präprozessor startet …")
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

    def succeeded(self, request_id, result):
        if request_id != self.request_id or self.cancelled or self.window._closing:
            result.dispose()
            return
        self.session.preview = result
        self.session.preview_state = PreviewState.CURRENT
        self.session.successful_request = result.request
        self.panel.canvas.set_scene(result.scene)
        self.panel.canvas.apply_camera_state({**self.panel.canvas.camera_state(), "yaw_deg": -38, "pitch_deg": -28})
        self.panel.canvas.fit_scene()
        self.panel.canvas.set_navigation_enabled(True)
        self.panel.show_automatic_values({
            **{name: getattr(result.effective_settings, name) for name in (
                "target_layer_time_s", "print_speed_mm_s", "travel_speed_mm_s", "retract_mm", "retract_speed_mm_s")},
            "height_mm": result.height_mm, "diameter_mm": result.diameter_mm,
            "base_width_mm": result.base_width_mm,
            **dict(zip(("center_x_mm", "center_y_mm"), result.scene.tower_center_xy_mm if result.height_mm else (None, None))),
            **dict(zip(("wait_x_mm", "wait_y_mm"), result.scene.wait_position_xy_mm or (None, None))),
        })
        self.panel.refresh_resets()
        self.panel.show_timing(result)
        self.panel.summary.setText(f"Höhe {result.height_mm:.2f} mm · Durchmesser {result.diameter_mm:.2f} mm · "
            f"Standfuß {result.base_width_mm:.2f} mm · Mitte X {result.scene.tower_center_xy_mm[0]:.2f}, "
            f"Y {result.scene.tower_center_xy_mm[1]:.2f} mm\n"
            f"{result.wait_count} Wartephasen · {result.total_wait_s:.1f} s Restwartezeit. "
            f"Kürzeste berechnete Schichtzeit: {min(result.layer_times_s):.2f} s. "
            + (f"Warteposition X {result.scene.wait_position_xy_mm[0]:.2f}, Y {result.scene.wait_position_xy_mm[1]:.2f} mm · "
                if result.scene.wait_position_xy_mm else "")
            + f"Sicherheitshub {result.effective_z_hop_mm:.2f} mm. "
            +
            "Fahrten, Abstreifen und Primen sind eingerechnet. Automatische Maße sind Stabilitätsrichtwerte; "
            "Material, Haftung und Drucker beeinflussen die tatsächliche Stabilität.")
        if result.height_mm and result.request.settings.hollow_tower:
            low, high = result.wall_thickness_range_mm
            thickness = f"{low:.2f} mm" if abs(high - low) < .005 else f"{low:.2f}–{high:.2f} mm"
            inner_low, inner_high = result.diameter_mm - 2 * high, result.diameter_mm - 2 * low
            inner = f"{inner_low:.2f} mm" if abs(inner_high - inner_low) < .005 else f"{inner_low:.2f}–{inner_high:.2f} mm"
            self.panel.summary.setText(self.panel.summary.text()
                + f"\n{result.request.settings.wall_count} Wandlinien · Wandstärke {thickness} · "
                + f"Schaft-Innendurchmesser {inner}.")
        self.panel.status.setText("G-Code und rekonstruierte Vorschau sind bereit." if result.height_mm else
            "Alle Schichten erreichen die Zielzeit. Der G-Code bleibt unverändert; kein Turm erforderlich.")
        self.panel.refresh_layout()
        self.refresh()

    def failed(self, request_id, message, _details):
        if request_id == self.request_id and not self.window._closing:
            self.critical_error(message)

    def critical_error(self, message):
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
        for widget, enabled in self._locked_inputs:
            widget.setEnabled(enabled)
        self._locked_inputs = []
        if not self.window._closing:
            if self.cancelled:
                self.panel.status.setText("Präprozessor abgebrochen.")
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
