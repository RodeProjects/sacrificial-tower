"""Independent native GUI state, with late-result and job-release protection."""
from dataclasses import dataclass
from threading import Event
import traceback

from PySide6.QtCore import QObject, Signal, Slot
from cooling_tower.gui.background_jobs import JobKind
from cooling_tower.gui.worker_contract import CancelableWorker
from cooling_tower.native_project.archive import ProjectArchive
from cooling_tower.native_project.automatic import NativeAutomaticService
from cooling_tower.native_project.export import export_project_run, verified_export_result
from cooling_tower.native_project.context import NativeProjectError, ProjectProblem
from cooling_tower.native_project.session import NativeOperationCancelled, NativeProjectSession, check_cancel
from cooling_tower.slicers import SlicerDiscoveryService
from cooling_tower.export_io import atomic_export


@dataclass(frozen=True)
class NativeImported:
    session: NativeProjectSession
    installation: object | None
    thumbnails: tuple[tuple[str, bytes], ...]

    def close(self):
        self.session.close()


@dataclass(frozen=True)
class NativeExportCompleted:
    path: object

    def close(self):
        # A successfully published user export never belongs to scratch cleanup.
        pass


def import_project(path, cancelled, notify, discovery_factory=SlicerDiscoveryService):
    session = NativeProjectSession(path)
    try:
        notify('Native Projekteinstellungen werden geprüft')
        check_cancel(cancelled)
        discovered = discovery_factory().discover_installations()
        candidates = [item for item in discovered.installations if item.adapter_id == session.context.adapter_id and item.can_slice]
        # Deterministic selection among installations of the detected product;
        # no user preset discovery or manual profile confirmation is involved.
        candidates.sort(key=lambda item: tuple(int(part) for part in __import__('re').findall(r'\d+', item.version or '0')), reverse=True)
        thumbnails = []
        with ProjectArchive(session.context.snapshot.path) as archive:
            for plate in session.context.plates:
                if plate.thumbnail:
                    raw = archive.read(plate.thumbnail, metadata=True)
                    # Bound decoded images, not just their compressed size.
                    if raw.startswith(b'\x89PNG\r\n\x1a\n') and len(raw) >= 24:
                        import struct
                        width, height = struct.unpack('>II', raw[16:24])
                        if 0 < width <= 4096 and 0 < height <= 4096 and width * height <= 8_000_000:
                            thumbnails.append((plate.identifier, raw))
        check_cancel(cancelled)
        return NativeImported(session, candidates[0] if candidates else None, tuple(thumbnails))
    except BaseException:
        session.close()
        raise


class NativeOperationWorker(CancelableWorker):
    succeeded = Signal(int, object)
    failed = Signal(int, str, str)
    problem = Signal(int, object)
    progress = Signal(int, str)
    preview = Signal(int, object)
    finished = Signal(int)

    def __init__(self, request_id, operation):
        super().__init__()
        self.request_id, self.operation = request_id, operation

    @Slot()
    def run(self):
        try:
            result = self.operation(
                self.cancellation_event,
                lambda text: self.progress.emit(self.request_id, text),
                lambda value: self.preview.emit(self.request_id, value),
            )
            if self.cancellation_requested():
                if callable(getattr(result, 'close', None)):
                    result.close()
            else:
                self.succeeded.emit(self.request_id, result)
        except NativeOperationCancelled:
            pass
        except Exception as error:
            if not self.cancellation_requested():
                self.problem.emit(self.request_id, getattr(error, 'problem', None))
                self.failed.emit(self.request_id, str(error), getattr(error, 'technical_details', '') or traceback.format_exc())
        finally:
            self.finished.emit(self.request_id)


class NativeProjectController(QObject):
    imported_ready = Signal(object)
    prepared_ready = Signal(object)
    generated_ready = Signal(object)
    iteration_ready = Signal(object)
    best_changed = Signal(object)
    exported = Signal(str)
    busy_changed = Signal(bool)
    status_changed = Signal(str)
    failed = Signal(str, str, object)

    def __init__(self, manager, parent=None, *, importer=import_project):
        super().__init__(parent)
        self.manager, self.importer = manager, importer
        self.imported = self.prepared = self.generated = None
        self.best_candidate = None
        self._acceptance_event = None
        self.request_id = 0
        self._jobs, self._retired = {}, []
        self._closed = False
        self._problem = None
        manager.job_released.connect(self._released)

    @property
    def busy(self):
        return any(request == self.request_id for request, _ in self._jobs.values())

    def _retire_results(self):
        for value in (self.generated, self.prepared):
            if value is not None:
                self._retired.append(value)
        self.generated = self.prepared = None
        self._set_best(None)

    def _set_best(self, candidate):
        if self.best_candidate != candidate:
            self.best_candidate = candidate
            self.best_changed.emit(candidate)

    def _collect_retired(self, *, force=False):
        if self._jobs and not force:
            return
        retired, self._retired = self._retired, []
        for value in retired:
            value.close()

    def cancel(self):
        self.request_id += 1
        self._acceptance_event = None
        if self.generated is None:
            self._set_best(None)
        for job_id in tuple(self._jobs):
            self.manager.cancel_job(job_id, reason='native_request_replaced')
        self.status_changed.emit('Abbruch wird abgeschlossen' if self._jobs else 'Abgebrochen')
        if not self._jobs:
            self.busy_changed.emit(False)

    def deactivate(self):
        self.cancel()
        self._retire_results()
        if self.imported is not None:
            self._retired.append(self.imported)
            self.imported = None
        self._collect_retired()

    def load(self, path):
        self.deactivate()
        self._start(JobKind.NATIVE_IMPORT, lambda event, notify, _preview: self.importer(path, event, notify))

    def select_plate(self):
        self.cancel()
        self._retire_results()
        self._collect_retired()

    def prepare(self, plate_id):
        imported = self.imported
        if imported is None or imported.installation is None or self.busy:
            return
        self._retire_results()
        self._collect_retired()
        self._start(JobKind.NATIVE_PREPARE, lambda event, notify, _preview: imported.session.slice(
            imported.installation, plate_id, cancellation_event=event, notify=notify))

    def invalidate_generation(self):
        if self.generated is not None:
            self._retired.append(self.generated)
            self.generated = None
        self._set_best(None)
        self._collect_retired()

    @property
    def calibrating(self):
        return self._acceptance_event is not None

    @property
    def can_accept_best(self):
        return self.calibrating and not self._acceptance_event.is_set() and self.best_candidate is not None

    @property
    def can_continue(self):
        return self.generated is not None and getattr(self.generated, 'continuation', None) is not None

    def accept_best(self):
        if self.can_accept_best:
            self._acceptance_event.set()
            self.status_changed.emit('Bester geprüfter Kandidat wird übernommen …')
            self.best_changed.emit(self.best_candidate)

    def generate(self, settings, options):
        if self.imported is None or self.prepared is None or self.busy or self._closed:
            return
        self.invalidate_generation()
        self._start_generation(settings, options)

    def continue_generation(self):
        if not self.can_continue or self.busy or self._closed:
            return
        resume, self.generated = self.generated, None
        self._start_generation(resume.settings, resume.continuation.options, resume=resume)

    def _start_generation(self, settings, options, *, resume=None):
        session, prepared = self.imported.session, self.prepared
        acceptance = self._acceptance_event = Event()
        try:
            self._start(JobKind.NATIVE_AUTOMATIC, lambda event, notify, preview: NativeAutomaticService().run(
                session, prepared, settings, options=options, cancellation_event=event,
                progress=lambda number, maximum, text: notify(f'Durchlauf {number} von {maximum} · {text}'),
                preview=preview, acceptance_event=acceptance, resume=resume))
        except Exception:
            self._acceptance_event = None
            self.generated = resume
            raise

    def export(self, destination):
        if self.imported is None or self.generated is None or self.generated.prepared is None or self.busy:
            return
        generated = self.generated
        original = self.imported.session.source_snapshot.original_path
        def operation(event, notify, _preview):
            check_cancel(event)
            notify('Geprüftes natives Projekt wird exportiert')
            result = verified_export_result(generated)
            installation = result.installation
            try:
                path = atomic_export(result.project_path, destination, expected_sha256=result.project_sha256,
                    protected_files=(original, installation.executable_path),
                    protected_roots=(installation.executable_path.parent, *installation.profile_roots),
                    overwrite=True, cancellation_callback=event.is_set)
            except InterruptedError as error:
                raise NativeOperationCancelled(str(error)) from error
            return NativeExportCompleted(path)
        self._start(JobKind.NATIVE_EXPORT, operation)

    def export_run(self, output_root):
        if self.imported is None or self.generated is None or self.generated.prepared is None or self.busy:
            return
        session, generated = self.imported.session, self.generated
        def operation(event, notify, _preview):
            notify('Geprüftes natives Projekt wird exportiert')
            try:
                result = export_project_run(session, generated, output_root, cancellation_event=event)
            except InterruptedError as error:
                raise NativeOperationCancelled(str(error)) from error
            return NativeExportCompleted(result.path)
        self._start(JobKind.NATIVE_EXPORT, operation)

    def _start(self, kind, operation):
        if self._closed:
            return
        self.request_id += 1
        request = self.request_id
        self._problem = None
        worker = NativeOperationWorker(request, operation)
        worker.succeeded.connect(self._succeeded)
        worker.failed.connect(self._failed)
        worker.problem.connect(self._set_problem)
        worker.progress.connect(self._progress)
        worker.preview.connect(self._preview)
        job = self.manager.start_job(kind=kind, request_id=request, worker=worker)
        self._jobs[job] = (request, kind)
        self.busy_changed.emit(True)

    @Slot(int, object)
    def _succeeded(self, request, result):
        if self._closed or request != self.request_id:
            result.close()
            return
        if isinstance(result, NativeImported):
            self.imported = result
            self.imported_ready.emit(result)
        elif isinstance(result, NativeExportCompleted):
            self.exported.emit(str(result.path))
        elif hasattr(result, 'iterations'):
            self.generated = result
            self._acceptance_event = None
            self._set_best(getattr(result, 'best_candidate', None))
            self.generated_ready.emit(result)
        else:
            self.prepared = result
            self.prepared_ready.emit(result)

    @Slot(int, object)
    def _set_problem(self, request, problem):
        if request == self.request_id:
            self._problem = problem

    @Slot(int, str, str)
    def _failed(self, request, message, details):
        if not self._closed and request == self.request_id:
            if self.calibrating:
                self._acceptance_event = None
                self._set_best(None)
            self.failed.emit(message, details, self._problem)

    @Slot(int, str)
    def _progress(self, request, text):
        if not self._closed and request == self.request_id and (
                not self.calibrating or not self._acceptance_event.is_set()):
            self.status_changed.emit(text)

    @Slot(int, object)
    def _preview(self, request, value):
        if not self._closed and request == self.request_id:
            self._set_best(getattr(value, 'best_candidate', None))
            if not self.calibrating or not self._acceptance_event.is_set():
                self.iteration_ready.emit(value)

    @Slot(object)
    def _released(self, job):
        previous = self._jobs.pop(job.job_id, None)
        if previous is None:
            return
        if previous == (self.request_id, JobKind.NATIVE_AUTOMATIC):
            self._acceptance_event = None
        self._collect_retired()
        if not self.busy:
            self.busy_changed.emit(False)

    def close_after_shutdown(self):
        self._closed = True
        self.request_id += 1
        self._acceptance_event = None
        self._retire_results()
        if self.imported is not None:
            self._retired.append(self.imported)
            self.imported = None
        self._collect_retired(force=True)
