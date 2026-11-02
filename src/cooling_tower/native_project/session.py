"""Native-project preparation and jointly sliced results, independent of STL."""
from __future__ import annotations

from dataclasses import dataclass
import hashlib
import itertools
import json
import math
from pathlib import Path
import shutil
from threading import Event

from cooling_tower.models.analysis import GCodeAnalysisSnapshot
from cooling_tower.models.calibration import OccupiedBounds
from cooling_tower.native_project.archive import ProjectArchive
from cooling_tower.native_project.compose import ComposedProject, plate_origin, restore_basis
from cooling_tower.native_project.compatibility import execution_project
from cooling_tower.native_project.context import NativeProjectContext, NativeProjectError, ProjectProblem, load_context
from cooling_tower.native_project.toolpath import DepositionToolpathCollector, DepositionToolpathAnalysis
from cooling_tower.protected_io import InputSnapshot, OwnedWorkspace, read_locked
from cooling_tower.services.analysis_service import GCodeAnalysisService, AnalysisCancelled
from cooling_tower.slicers import SlicerInstallation, default_adapters
from cooling_tower.slicers.protected_process import native_host_path


class NativeOperationCancelled(RuntimeError):
    pass


class NativeSliceError(RuntimeError):
    def __init__(self, message: str, technical_details: str = ''):
        super().__init__(message)
        self.technical_details = technical_details


def check_cancel(event: Event | None) -> None:
    if event is not None and event.is_set():
        raise NativeOperationCancelled('Die native Projektverarbeitung wurde abgebrochen.')


def _engine_identity(installation: SlicerInstallation) -> str:
    digest = hashlib.sha256()
    names = [installation.executable_path]
    library = installation.executable_path.with_name({
        'bambu_studio': 'BambuStudio.dll', 'anycubic_slicer_next': 'AnycubicSlicer.dll',
        'orca_slicer': 'OrcaSlicer.dll', 'prusa_slicer': 'PrusaSlicer.dll',
    }[installation.adapter_id])
    if library.is_file():
        names.append(library)
    host = native_host_path()
    if host.is_file():
        names.append(host)
    for path in names:
        with read_locked(path) as stream:
            digest.update(hashlib.file_digest(stream, 'sha256').digest())
    return digest.hexdigest()


@dataclass(frozen=True, slots=True)
class NativePreparedResult:
    context: NativeProjectContext
    plate_id: str
    binding: str
    installation: SlicerInstallation
    engine_identity: str
    analysis: GCodeAnalysisSnapshot
    gcode_path: Path
    project_path: Path
    workspace: OwnedWorkspace
    toolpaths: DepositionToolpathAnalysis
    project_sha256: str
    composed: ComposedProject | None = None

    def verify(self) -> None:
        self.context.snapshot.verify()
        if not self.analysis.matches_file() or _engine_identity(self.installation) != self.engine_identity:
            raise NativeSliceError('Das Analyseergebnis oder die installierte Slicer-Engine wurde zwischenzeitlich verändert.')
        with read_locked(self.gcode_path) as stream:
            if hashlib.file_digest(stream, 'sha256').hexdigest() != self.analysis.content_sha256:
                raise NativeSliceError('Die geprüften Druckbahnen wurden zwischenzeitlich verändert.')
        with read_locked(self.project_path) as stream:
            if hashlib.file_digest(stream, 'sha256').hexdigest() != self.project_sha256:
                raise NativeSliceError('Das zugehörige native Ergebnisprojekt wurde zwischenzeitlich verändert.')

    def close(self) -> None:
        self.workspace.close()


def _apply(point, matrix):
    x, y, z = point
    return (x * matrix[0] + y * matrix[3] + z * matrix[6] + matrix[9],
            x * matrix[1] + y * matrix[4] + z * matrix[7] + matrix[10],
            x * matrix[2] + y * matrix[5] + z * matrix[8] + matrix[11])


def project_bounds(context: NativeProjectContext, plate_id: str) -> OccupiedBounds:
    """Conservative transformed original bounds, including modifier volumes."""
    graph = context.graph
    origin = plate_origin(context, plate_id)
    minima, maxima = [math.inf] * 3, [-math.inf] * 3

    def points(model_path, object_id):
        obj = graph.object(model_path, object_id)
        if obj.bounds_mm:
            bounds = obj.bounds_mm
            yield from itertools.product(*[(bounds[i], bounds[i + 3]) for i in range(3)])
        else:
            for component in obj.components:
                for point in points(component.model_path, component.object_id):
                    yield _apply(point, component.transform)

    for index in context.plate(plate_id).build_indices:
        item = graph.main.build[index]
        for point in points(graph.main_path, item.object_id):
            transformed = _apply(point, item.transform)
            local = (transformed[0] - origin[0], transformed[1] - origin[1], transformed[2])
            for axis in range(3):
                minima[axis] = min(minima[axis], local[axis])
                maxima[axis] = max(maxima[axis], local[axis])
    if not all(math.isfinite(value) for value in (*minima, *maxima)):
        raise NativeProjectError(ProjectProblem.INCOMPLETE, 'Die ausgewählte Platte enthält keine vollständige druckbare Geometrie.')
    return OccupiedBounds(minima[0], maxima[0], minima[1], maxima[1])


class NativeProjectSession:
    """One retained import snapshot, independent native jobs, no preset reads."""

    def __init__(self, path: str | Path, *, workspace_parent: Path | None = None):
        self.workspace = OwnedWorkspace(parent=workspace_parent, prefix='ni_')
        self.closed = False
        try:
            self.source_snapshot = self.workspace.capture(path, name='import.3mf')
            basis = restore_basis(self.source_snapshot.path, workspace=self.workspace)
            self.context = load_context(self.workspace.capture(basis, name='basis.3mf') if basis else self.source_snapshot)
        except BaseException:
            self.workspace.close()
            self.closed = True
            raise

    def original_changed(self) -> bool:
        return not self.source_snapshot.original_is_unchanged()

    def close(self) -> None:
        if not self.closed:
            self.workspace.close()
            self.closed = True

    def slice(self, installation: SlicerInstallation, plate_id: str, *,
              cancellation_event: Event | None = None, timeout_s: float = 480.,
              composed: ComposedProject | None = None, notify=None) -> NativePreparedResult:
        if self.closed:
            raise NativeSliceError('Die native Projektsitzung wurde geschlossen.')
        context = self.context
        plate = context.plate(plate_id)
        if installation.adapter_id != context.adapter_id or not installation.can_slice:
            raise NativeProjectError(ProjectProblem.MISSING_SLICER, 'Der zum nativen Projekt gehörende Slicer ist nicht ausführbar vorhanden.')
        if not plate.build_indices:
            raise NativeProjectError(ProjectProblem.INCOMPLETE, 'Die ausgewählte Druckplatte enthält keine druckbaren Objekte.')
        values = context.settings
        overrides = dict(plate.metadata)
        sequence = overrides.get('print_sequence', values.get('print_sequence', 'by layer'))
        complete = values.get('complete_objects', '0')
        if sequence == 'by object' or str(complete).casefold() in {'1', 'true'}:
            raise NativeProjectError(ProjectProblem.UNSUPPORTED, 'Der automatische Kühlturm benötigt schichtweisen gemeinsamen Druck. Das Projekt verwendet sequentiellen Objektdruck.')
        check_cancel(cancellation_event)
        context.snapshot.verify()
        identity = _engine_identity(installation)
        options = {'output': 'plain_gcode', 'joint': composed.mesh_sha256 if composed else None,
                   'tower_placement': composed.placement_mm if composed else None}
        binding = context.binding(plate_id, engine_version=(installation.version or '') + ':' + identity, options=options)
        work = OwnedWorkspace(prefix='ns_')
        try:
            model_snapshot = work.capture(composed.path if composed else context.snapshot.path, name='project.3mf')
            model = model_snapshot.path
            if composed:
                binding = context.binding(plate_id, engine_version=(installation.version or '') + ':' + identity,
                    options={**options, 'joint_project_sha256': model_snapshot.sha256})
            execution_model = execution_project(context, model, work, plate_id=plate_id)
            output, data = work.child('out'), work.child('data')
            output.mkdir()
            data.mkdir()
            if context.adapter_id == 'prusa_slicer':
                arguments = ('--datadir', str(data), '--dont-arrange', '--no-binary-gcode', '--export-gcode',
                             '--output', str(output / 'native.gcode'), str(execution_model))
            else:
                arguments = ('--datadir', str(data), '--slice', str(plate.ordinal), '--outputdir', str(output), str(execution_model))
            adapter = next(adapter for adapter in default_adapters() if adapter.adapter_id == context.adapter_id)
            if notify:
                notify('Projekt wird mit eingebetteten Einstellungen geslict')
            outcome = adapter.runner.run(installation.executable_path, arguments, working_directory=work.path,
                timeout_s=timeout_s, cancellation_event=cancellation_event, adapter_id=context.adapter_id,
                purpose='native_project_slice')
            check_cancel(cancellation_event)
            if outcome.cancelled:
                raise NativeOperationCancelled('Der native Slicerlauf wurde abgebrochen.')
            if outcome.timed_out:
                raise NativeSliceError('Der native Slicerlauf hat das Zeitlimit überschritten.',
                    outcome.stdout + '\n' + outcome.stderr)
            if outcome.return_code != 0 or outcome.crashed:
                status = ('kein Rückgabecode' if outcome.return_code is None else
                    f'{outcome.return_code} (0x{outcome.return_code & 0xffffffff:08X})')
                raise NativeSliceError('Der Slicer konnte das native Projekt nicht vollständig verarbeiten.',
                    f'Nativer Prozess: {status}\n' + outcome.stdout + '\n' + outcome.stderr)
            files = tuple(output.rglob('*.gcode'))
            if len(files) != 1:
                raise NativeSliceError('Der Slicer hat keinen eindeutig zugeordneten Druck-G-Code erzeugt.', outcome.stdout + '\n' + outcome.stderr)
            if notify:
                notify('Gemeinsame Druckbahnen werden analysiert')
            collector = DepositionToolpathCollector(maximum_segments=60_000)
            try:
                analysis = GCodeAnalysisService().analyze(files[0],
                    event_observers=(collector.consume,),
                    cancellation_callback=(cancellation_event.is_set if cancellation_event else None))
                toolpaths = collector.finish(expected_layer_count=analysis.layer_count,layer_records=analysis.layers)
            finally:
                collector.close()
            if not analysis.layers or not any(layer.deposition_count for layer in analysis.layers):
                raise NativeSliceError('Die native Druckplatte enthält keine analysierbaren Druckbahnen.')
            if identity != _engine_identity(installation):
                raise NativeSliceError('Die Slicerinstallation wurde während der Verarbeitung verändert.')
            return NativePreparedResult(context, plate_id, binding, installation, identity, analysis, files[0], model, work, toolpaths, model_snapshot.sha256, composed)
        except AnalysisCancelled as error:
            work.close()
            raise NativeOperationCancelled('Die native Druckbahnanalyse wurde abgebrochen.') from error
        except BaseException:
            work.close()
            raise
