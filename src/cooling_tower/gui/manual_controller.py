"""Manual request routing, result ownership and explicit editor state transitions."""
from __future__ import annotations

import copy
from dataclasses import replace
from pathlib import Path

from PySide6.QtCore import QObject, Slot, QPoint, QTimer, Qt
from PySide6.QtWidgets import QWidget, QVBoxLayout, QScrollArea, QFrame, QLabel

from cooling_tower.gui.background_jobs import JobKind
from cooling_tower.gui.export_worker import ExportWorker
from cooling_tower.gui.generation_session import GenerationMode
from cooling_tower.gui.manual_worker import ManualWorker
from cooling_tower.gui.widgets.footer_notice_dropdown import FooterNoticeDropdown
from cooling_tower.manual.context import overhang_default
from cooling_tower.manual.geometry import ManualSettings
from cooling_tower.manual.service import ManualGenerationService, ManualExportService, ManualRequest
from cooling_tower.manual.settings_store import ManualSettingsStore
from cooling_tower.models import GenerationSettings, CalibrationConfig
from cooling_tower.preview import OutputMode, PreviewState


class ManualGenerationController(QObject):
    def __init__(self, window, panel):
        super().__init__(window)
        self.window,self.panel = window,panel
        panel.canvas.set_render_manager(window.background_job_manager)
        self.mode = GenerationMode.MANUAL
        self.session = window.generation_sessions[self.mode]
        self.store = ManualSettingsStore(window.settings_store.user_path.with_name("manual_settings.json"))
        panel.settings = self.store.load()
        self.service = ManualGenerationService(window.preview_service,window.user_data_root / "temporary")
        self.export_service = ManualExportService()
        self.reference = None
        self._reference_request = None
        self.request_id = 0
        self.job_id = None
        self.operation = None
        self.cancelled = False
        self._result_received = False
        self._locked_inputs = []
        self._automatic_scrollbar_policy = None
        self._automatic_viewport_margins = None
        window.settings_scroll.verticalScrollBar().rangeChanged.connect(self._sync_scrollbar_gutter)
        panel.generate_requested.connect(self.generate)
        panel.export_requested.connect(self.export)
        panel.cancel_requested.connect(self.cancel)
        panel.retry_reference_requested.connect(self.ensure_context)
        panel.draft_changed.connect(self.draft_changed)
        panel.status_changed.connect(self.refresh_footer)
        panel.canvas.view_changed.connect(self.refresh_footer)
        panel.canvas.view_state_changed.connect(self._refresh_reset_actions)
        panel.settings_visibility_changed.connect(lambda:QTimer.singleShot(0,self,self.fit_editor_to_window))
        window.background_job_manager.job_released.connect(self.job_released)
        if self.store.warning:
            panel.status_label.setText(self.store.warning)

    def build_request(self, draft=None):
        w = self.window
        result = w.profile_match_result
        if w.analysis_snapshot is None or result is None or result.selected is None or not result.user_confirmed or not result.can_use_stl_mode:
            raise ValueError("Zuerst Quelle, Slicer und Druckprofile vollständig vorbereiten und bestätigen.")
        profile = result.selected.effective_profile
        if w.source_preslice_result is not None:
            if (getattr(w.source_preslice_result,"supports_simulated",False)
                    and not (draft is not None and self.panel.source_supports_checkbox.isChecked())):
                from cooling_tower.slicers.support_simulation import with_simulated_supports
                profile = with_simulated_supports(profile)
            if getattr(w.source_preslice_result,"draft_shield_simulated",False):
                from cooling_tower.slicers.draft_shield import with_simulated_draft_shield_disabled
                profile = with_simulated_draft_shield_disabled(profile)
        # Freeze nested values too; UI/session changes cannot alter a running job.
        profile = replace(profile,effective_values=copy.deepcopy(dict(profile.effective_values)))
        settings = draft.settings if draft is not None else ManualSettings()
        export_settings = GenerationSettings(minimum_outer_diameter_mm=settings.minimum_diameter_mm,
                                             maximum_outer_diameter_mm=settings.maximum_diameter_mm,
                                             automatic_base_width=False,manual_base_width_mm=settings.foot_diameter_mm,
                                             simulate_full_tower_infill=draft is not None and self.panel.full_infill_checkbox.isChecked(),
                                             simulate_source_supports=draft is not None and self.panel.source_supports_checkbox.isChecked(),
                                             simulate_tower_without_supports=False,
                                             excluded_layer_ranges=())
        return ManualRequest(snapshot=w.analysis_snapshot,settings=export_settings,output_mode=OutputMode.STL,
                             calibration_config=CalibrationConfig(maximum_iterations=1),
                             slicer_identity_key=result.execution_slicer.identity_key,
                             profile_fingerprint=f"{result.inventory_fingerprint}:{result.selected.bundle_id}:1",
                             effective_profile=profile,adapter=w.slicer_service.adapter_for(result.execution_slicer),
                             source_artifact=w.source_artifact,prepared_analysis_source=w.prepared_analysis_source,
                             prepared_source_data=w.source_preslice_result.preview_source_data if w.source_preslice_result is not None else None,
                             draft=draft,context=self.reference.context if self.reference is not None else None,
                             profile_source_hashes=self.reference.profile_source_hashes if self.reference is not None else ())

    def ensure_context(self):
        if self.job_id is not None or self.window._closing:
            return
        try:
            request = self.build_request()
            # Reference signature is independent of both methods' changed values.
            request = replace(request,context=None,profile_source_hashes=())
        except ValueError as error:
            self.panel.status_label.setText(str(error))
            self.refresh_footer()
            return
        if self._reference_request is not None and self.reference is not None and self.panel.draft is not None and request.signature() == self.reference.context.key:
            self.refresh()
            return
        self.invalidate_context()
        self._reference_request = request
        self._start(ManualWorker(self._next_id(),request,self.service,reference=True),"reference",JobKind.PREVIEW)

    def _next_id(self):
        # The automatic method retains its positive request IDs and callbacks.
        self.request_id -= 1
        return self.request_id

    def _start(self,worker,operation,kind):
        if self.window.background_job_manager.has_active(JobKind.PREVIEW) or self.window.background_job_manager.has_active(JobKind.EXPORT):
            self.panel.status_label.setText("Eine Generierung oder ein Export läuft bereits.")
            self.refresh_footer()
            return
        self.operation,self.cancelled,self._result_received = operation,False,False
        worker.progress.connect(self.progress)
        worker.succeeded.connect(self.succeeded)
        worker.failed.connect(self.failed)
        self.panel.progress.setRange(0,100)
        self.panel.progress.setValue(0)
        self.panel.status_label.clear()
        self._progress_status_label.setText("Manuelle Vorschau wird vorbereitet …" if operation == "reference" else
                                           "Geprüfter manueller Stand wird exportiert …" if operation == "export" else "Feste manuelle Geometrie wird geprüft …")
        self.job_id = self.window.background_job_manager.start_job(kind=kind,request_id=self.request_id,worker=worker,
                                                                    parent_operation_id=f"manual-{operation}-{abs(self.request_id)}")
        self._locked_inputs = [(widget,widget.isEnabled()) for widget in
                               (self.window.drop_zone,self.window.slicer_combo,self.window.slicer_refresh_button,
                                self.window.slicer_manual_button,self.window.machine_profile_combo,self.window.process_profile_combo,
                                self.window.filament_profile_combo,self.window.show_all_profiles_checkbox,self.window.profile_confirm_button)]
        self.refresh()
        self.window._refresh_phase17_actions()
        self.window._update_slicer_discovery_controls()
        for widget,_ in self._locked_inputs: widget.setEnabled(False)

    def generate(self):
        if self.job_id is not None or self.panel.draft is None: return
        try:
            self.reference.context.validate(self.panel.draft)
            request = self.build_request(self.panel.draft)
            if not self._context_current(): raise ValueError("Der bestätigte Quellen-/Profilkontext hat sich geändert.")
        except (ValueError,RuntimeError) as error:
            self.panel.status_label.setText(str(error))
            self.refresh_footer()
            return
        self.session.running_request = request
        self._start(ManualWorker(self._next_id(),request,self.service),"generation",JobKind.PREVIEW)

    def export(self):
        if self.job_id is not None or self.session.preview is None or self.session.successful_request is None: return
        if self.session.exported_preview_identity == self.identity(self.session.preview): return
        if not self._context_current():
            self.invalidate_context()
            self.panel.status_label.setText("Der Quellen-/Profilkontext hat sich geändert; bitte erneut vorbereiten.")
            self.refresh_footer()
            return
        worker = ExportWorker(self._next_id(),self.session.preview,self.session.successful_request,
                              Path(self.window.output_root_edit.text()),self.export_service)
        self._start(worker,"export",JobKind.EXPORT)

    @staticmethod
    def identity(result):
        return result.request_signature,result.artifact_sha256

    def _context_current(self):
        if self.reference is None: return False
        try:
            current = replace(self.build_request(),context=None,profile_source_hashes=())
            return current.signature() == self.reference.context.key
        except (ValueError,AttributeError): return False

    @Slot(int,int,str)
    def progress(self,request_id,percent,status):
        if request_id != self.request_id or self.window._closing: return
        self.panel.progress.setValue(percent)
        self._progress_status_label.setText(status)
        self.sync_footer_content_visibility()
        self.window._schedule_footer_height_update()

    @Slot(int,object)
    def succeeded(self,request_id,result):
        if request_id != self.request_id or self.window._closing or self.cancelled:
            if callable(getattr(result,"dispose",None)): result.dispose()
            return
        if self.operation == "reference":
            current = replace(self.build_request(),context=None,profile_source_hashes=())
            if current.signature() != result.context.key: return
            self.reference = result
            settings = self.panel.settings
            angle,note = overhang_default(current.effective_profile)
            self.panel.overhang_note.setText(note if not settings.overhang_user_set else "Eigener Überhangwinkel; Profilstandard über Reset verfügbar.")
            if not settings.overhang_user_set: settings = replace(settings,overhang_angle_deg=angle)
            try:
                self.panel.initialize(result,settings)
            except (ValueError,RuntimeError) as error:
                self.panel.status_label.setText(str(error))
                self.panel.retry_button.show()
                self.refresh_footer()
                return
            self.panel.status_label.setText(self.store.warning or "Turmprofil doppelklicken, um freie Punkte hinzuzufügen.")
        elif self.operation == "generation":
            if not self._context_current():
                result.dispose()
                return
            previous = self.session.preview
            self.session.preview,self.session.successful_request = result,self.session.running_request
            self.session.preview_state = PreviewState.CURRENT
            self.session.exported_preview_identity = None
            if previous is not None: previous.dispose()
            e = result.manual_evaluation
            mode = "Gemeinsamer Prüfslice" if e.joint_sliced else "Separate Zeitprognose"
            title = "Erreichte Mindest-Layerzeit" if e.joint_sliced else "Prognostizierte Mindest-Layerzeit"
            self.panel.result_label.setText(
                f"<b>{title}: {e.minimum_time_s:.3f} s</b><br>"
                f"{mode} · {len(e.layer_times)} Layer")
            self._result_warnings_label.setText("\n".join(result.warnings))
            self._result_notice.reset_collapsed()
            self.panel.status_label.clear()
        elif self.operation == "export":
            self.session.export_result = result
            self.session.exported_preview_identity = self.identity(self.session.preview)
            self.panel.status_label.clear()
            if self.session.preview.manual_evaluation.joint_sliced:
                self.panel.result_label.setText(self.panel.result_label.text().partition("<br>")[0])
            self.window._last_export_report_result = result
            self.window._latest_export_directory = result.run_directory
            self.window._latest_export_root_text = self.window.output_root_edit.text().strip()
            self.window._latest_export_unavailable_reason = ""
            self.window._refresh_last_export_report_action()
            self.window._show_export_success_dialog(result)
        self._progress_status_label.clear()
        self._result_received = True
        self.refresh()

    @Slot(int,str,str)
    def failed(self,request_id,message,details):
        if request_id != self.request_id or self.window._closing: return
        self.window._write_gui_error_log("manual_generation_error.log",details)
        self.panel.status_label.setText("Neuer manueller Lauf fehlgeschlagen: "+message)
        self._progress_status_label.clear()
        if self.operation == "reference": self.panel.retry_button.show()
        self.refresh_footer()

    @Slot(object)
    def job_released(self,job):
        if job.job_id != self.job_id: return
        operation,cancelled,received = self.operation,self.cancelled,self._result_received
        self.job_id = self.operation = None
        self._progress_status_label.clear()
        for widget,enabled in self._locked_inputs: widget.setEnabled(enabled)
        self._locked_inputs = []
        self.session.running_request = None
        if self.window._closing: return
        if cancelled:
            self.panel.status_label.setText("Manueller Lauf abgebrochen. Entwurf und bisheriger geprüfter Stand bleiben erhalten.")
            if operation == "reference": self.panel.retry_button.show()
        elif not received and operation == "generation" and not self.panel.status_label.text().startswith("Neuer"):
            self.panel.status_label.setText("Der neue Lauf lieferte kein vollständiges Ergebnis.")
        self.refresh()
        self.window._refresh_phase17_actions()
        if received and operation in {"reference","generation"}:
            QTimer.singleShot(0,self,self.fit_editor_to_window)

    def cancel(self):
        if self.job_id is None or self.operation == "export": return
        self.cancelled = True
        self.window.background_job_manager.cancel_job(self.job_id,reason="manual_user_request")
        self.refresh()

    def invalidate_context(self):
        if self.job_id is not None:
            self.cancelled = True
            self.window.background_job_manager.cancel_job(self.job_id,reason="manual_context_changed")
        self.request_id -= 1
        self.reference = self._reference_request = None
        self.session.discard_preview()
        self.session.manual_draft = self.session.running_request = None
        self.panel.draft = self.panel.canvas.draft = None
        self.panel.canvas.invalidate_reference()
        self.panel.reference = None
        self.panel.result_label.clear()
        self._result_warnings_label.clear()
        self._result_notice.reset_collapsed()
        self.panel.canvas.update()
        self.refresh()

    def draft_changed(self,draft):
        self.session.manual_draft = draft
        self.refresh()

    def refresh(self):
        busy = self.job_id is not None
        result = self.session.preview
        dirty = result is not None and self.session.preview_state is PreviewState.STALE
        if result is not None and self.panel.draft is not None and self.session.successful_request is not None:
            try: dirty = self.build_request(self.panel.draft).signature() != result.request_signature
            except ValueError: dirty = True
        self.session.preview_state = PreviewState.BUILDING if busy and self.operation == "generation" else PreviewState.STALE if dirty else PreviewState.CURRENT if result is not None else PreviewState.EMPTY
        exported = result is not None and self.session.exported_preview_identity == self.identity(result)
        self.panel.set_actions(result is not None,dirty,exported,busy)
        self.panel.set_busy(busy,cancelling=self.cancelled,exporting=self.operation == "export")
        self.refresh_footer()

    def attach_footer(self):
        """Use the existing main footer and its responsive action layout."""
        w,p = self.window,self.panel
        scroll = QScrollArea(w.footer_action_area)
        scroll.setObjectName("manualFooterStatusScroll")
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        scroll.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        w.manual_footer_status_scroll = scroll
        host = QWidget()
        host.setObjectName("manualFooterStatusContent")
        self._footer_status_widget = host
        w.manual_footer_status_widget = host
        layout = QVBoxLayout(host)
        layout.setContentsMargins(0,0,0,0)
        layout.setSpacing(6)
        self._progress_status_label = QLabel()
        self._progress_status_label.setTextFormat(Qt.TextFormat.PlainText)
        self._progress_status_label.setWordWrap(True)
        for widget in (p.progress,p.result_label,p.action_hint):
            p.preview_container.layout().removeWidget(widget)
            layout.addWidget(widget)
        layout.insertWidget(1,self._progress_status_label)
        self._footer_message_widget = QWidget(w.footer_messages_content)
        self._footer_message_widget.setObjectName("manualFooterMessageContent")
        w.manual_footer_message_widget = self._footer_message_widget
        message_layout = QVBoxLayout(self._footer_message_widget)
        message_layout.setContentsMargins(0,0,0,0)
        p.preview_container.layout().removeWidget(p.status_label)
        message_layout.addWidget(p.status_label)
        w.footer_messages_layout.addWidget(self._footer_message_widget)
        self._footer_message_widget.hide()
        self._result_notice = FooterNoticeDropdown("Hinweise zum Ergebnis",severity="warning",parent=host)
        self._result_warnings_label = QLabel()
        self._result_warnings_label.setTextFormat(Qt.TextFormat.PlainText)
        self._result_warnings_label.setWordWrap(True)
        self._result_notice.content_layout.addWidget(self._result_warnings_label)
        self._result_notice.toggled.connect(w._schedule_footer_height_update)
        layout.insertWidget(3,self._result_notice)
        scroll.setWidget(host)
        w.footer_action_layout.insertWidget(0,scroll)
        host.hide()
        scroll.hide()
        p.actions_host.hide()
        p.reset_button.hide()
        p.footer_hosted = True
        p.setMinimumHeight(0)

    def fit_editor_to_window(self):
        """Resize for window changes, never for inline feedback during editing."""
        w,p = self.window,self.panel
        if w._closing or w.generation_mode is not self.mode or not p.isVisible() or p._settings_transitioning:
            return
        w._fit_footer_height()
        w.centralWidget().layout().activate()
        w.content_layout.activate()
        top = p.mapTo(w.settings_scroll.viewport(),QPoint()).y()+w.settings_scroll.verticalScrollBar().value()
        available = w.settings_scroll.viewport().height()-top-w.content_layout.contentsMargins().bottom()
        layout = p.preview_container.layout()
        margins = layout.contentsMargins()
        width = max(1,p.preview_container.width()-margins.left()-margins.right())
        heights = []
        for i in range(layout.count()):
            item = layout.itemAt(i)
            widget = item.widget()
            if widget is not None:
                if widget.isHidden():continue
                height = widget.minimumHeight() if widget is p.canvas else (
                    widget.heightForWidth(width) if widget.hasHeightForWidth() else widget.minimumSizeHint().height())
                heights.append(max(widget.minimumHeight(),height,0))
            else:
                heights.append(item.minimumSize().height())
        minimum = sum(heights)+max(0,len(heights)-1)*layout.spacing()+margins.top()+margins.bottom()
        # QSplitter preserves pane sizes across orientation changes. Give the
        # preview its own floor so it cannot allocate less than its canvas and
        # controls need, even when both panes ignore their content size hints.
        p.preview_container.setMinimumHeight(minimum)
        if p.splitter.orientation() == Qt.Orientation.Vertical:
            minimum += p.settings_pane.minimumHeight()+p.splitter.handleWidth()
        p.setFixedHeight(max(minimum,available))
        p.layout().activate()
        if p.splitter.orientation() == Qt.Orientation.Vertical:
            settings_height = min(p.settings_pane.maximumHeight(),
                                  max(p.settings_pane.minimumHeight(),p.height()-p.preview_container.minimumHeight()-p.splitter.handleWidth()))
            p.splitter.setSizes([settings_height,p.height()-settings_height-p.splitter.handleWidth()])

    def update_scrollbar_policy(self,manual):
        """Scroll only for real overflow; restore the other method's policy."""
        scroll = self.window.settings_scroll
        if manual:
            if self._automatic_scrollbar_policy is None:
                self._automatic_scrollbar_policy = scroll.verticalScrollBarPolicy()
                self._automatic_viewport_margins = scroll.viewportMargins()
            scroll.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
            self._sync_scrollbar_gutter()
        elif self._automatic_scrollbar_policy is not None:
            policy,margins = self._automatic_scrollbar_policy,self._automatic_viewport_margins
            self._automatic_scrollbar_policy = None
            self._automatic_viewport_margins = None
            scroll.setVerticalScrollBarPolicy(policy)
            scroll.setViewportMargins(margins)

    def _sync_scrollbar_gutter(self,*_):
        if self._automatic_viewport_margins is None:
            return
        scroll = self.window.settings_scroll
        margins = self._automatic_viewport_margins
        bar = scroll.verticalScrollBar()
        right = margins.right()+(bar.sizeHint().width() if bar.maximum() == 0 else 0)
        current = scroll.viewportMargins()
        if (current.left(),current.top(),current.right(),current.bottom()) != (margins.left(),margins.top(),right,margins.bottom()):
            scroll.setViewportMargins(margins.left(),margins.top(),right,margins.bottom())

    def sync_footer_content_visibility(self):
        w,p = self.window,self.panel
        for label in (p.status_label,p.action_hint,self._progress_status_label):
            label.setVisible(bool(label.text().strip()))
        self._footer_message_widget.setVisible(w.generation_mode is self.mode and bool(p.status_label.text().strip()))
        checking = self.job_id is not None and self.operation == "generation" and not self._result_received
        p.result_label.setVisible(bool(p.result_label.text().strip()) and not checking)
        self._result_notice.setVisible(not p.result_label.isHidden() and bool(self._result_warnings_label.text().strip()))
        visible = (
            w.generation_mode is self.mode and
            any(not widget.isHidden() for widget in (p.progress,self._progress_status_label,p.result_label,p.action_hint)))
        self._footer_status_widget.setVisible(visible)
        w.manual_footer_status_scroll.setVisible(visible)

    def fit_footer_message(self,width):
        """Keep general messages readable in the left scrollable footer column."""
        host,label = self._footer_message_widget,self.panel.status_label
        host.setMinimumHeight(0)
        label.setMinimumHeight(0)
        if host.isHidden():
            return
        label.setMinimumHeight(max(label.minimumSizeHint().height(),label.heightForWidth(width)))
        layout=host.layout()
        layout.invalidate()
        host.setMinimumHeight(max(0,layout.heightForWidth(width),layout.minimumSize().height()))

    def fit_footer_status(self,maximum_height):
        """Wrap feedback at the action width and scroll long details above buttons."""
        w = self.window
        scroll,host = w.manual_footer_status_scroll,self._footer_status_widget
        if scroll.isHidden():
            scroll.setFixedHeight(0)
            return 0
        # Reserve the scrollbar gutter so enabling it cannot add wrapped lines
        # after calculating the content height.
        width = max(1,w.footer_action_area.width()-scroll.verticalScrollBar().sizeHint().width())
        host.setMinimumHeight(0)
        layout = host.layout()
        layout.invalidate()
        height = max(0,layout.heightForWidth(width),layout.minimumSize().height())
        host.setMinimumHeight(height)
        scroll.setFixedHeight(min(height,max(0,maximum_height)))
        return scroll.height()

    def refresh_footer(self,*_):
        w,p = self.window,self.panel
        if w.generation_mode is not self.mode or not hasattr(self,"_footer_status_widget"):
            return
        visible = not w.footer.isHidden()
        cancelling = self.job_id is not None and self.operation != "export"
        retry = p.draft is None and not p.retry_button.isHidden() and self.job_id is None
        primary_visible = cancelling or retry or not p.generate_button.isHidden()
        w.preview_action_control.setVisible(visible and primary_visible)
        w.preview_button.setVisible(visible and primary_visible)
        w.preview_button.setEnabled(not self.cancelled if cancelling else retry or p.generate_button.isEnabled())
        w.export_button.setVisible(visible and not p.export_button.isHidden())
        w.export_button.setEnabled(p.export_button.isEnabled())
        w.export_button.setToolTip(p.export_button.toolTip())
        self._refresh_reset_actions()
        w.action_availability_widget.hide()
        w._refresh_footer_auxiliary_visibility()
        w._update_responsive_action_labels()
        w._refresh_folder_action_states()
        w._schedule_footer_height_update()

    def primary_action(self):
        if self.job_id is not None:
            self.cancel()
        elif self.panel.draft is None:
            self.ensure_context()
        else:
            self.generate()

    def _refresh_reset_actions(self):
        if self.window.generation_mode is not self.mode:
            return
        w,p = self.window,self.panel
        w.reset_button.setEnabled(self.job_id is None and p.can_reset_all())
        w.reset_button.setToolTip("Alle manuellen Werte, die Turmform und die Vorschau auf Standardwerte zurücksetzen")
        w.tower_reset_button.setEnabled(self.job_id is None and p.can_reset_tower())
        w.tower_reset_button.setToolTip("Turmform, Durchmessergrenzen und geometrische Winkelgrenzen zurücksetzen")

    def request_reset_defaults(self):
        if self.job_id is not None or self.panel.reference is None:
            return
        box = self.window._create_reset_defaults_message_box()
        box.setWindowTitle("Alles zurücksetzen")
        box.setText("Alle Werte der manuellen Methode, die Turmform und die Vorschau werden auf ihre Standardwerte zurückgesetzt. Die automatische Methode und die Dateivorbereitung bleiben erhalten.")
        box.exec()
        if box.clickedButton() is box._reset_yes_button:
            self.panel.reset_all()

    def save_settings(self):
        try: self.store.save(self.panel.settings)
        except (OSError,ValueError) as error: self.panel.status_label.setText(str(error))

    def describe_export(self,result):
        w = self.window
        evidence = "gemeinsam geprüfte" if result.joint_sliced else "prognostizierte"
        w.export_success_achieved_label.setText(f"Kleinste {evidence} Layerzeit: {result.minimum_verified_layer_time_s:.3f} s")
        w.export_success_deviation_label.clear()
        w.export_success_deviation_label.hide()
        if result.joint_sliced:
            usage = "Die gestaltete Form wurde in einem vollständigen gemeinsamen Slice geprüft. Das exportierte native 3MF enthält exakt die geprüfte Anordnung. Beim getrennten STL-Import müssen Anordnung und bestätigte Profile erhalten bleiben."
        else:
            usage = "Separater Turm-Slice: Die Zeitbewertung ist eine Prognose zum Original-G-Code, keine gemeinsame Verifikation. Prüfen Sie die tatsächlichen Zeiten nach dem gemeinsamen Slicen von Objekt und Turm. Es wurde kein gemeinsames 3MF geprüft."
        w.export_success_usage_label.setText(usage)
