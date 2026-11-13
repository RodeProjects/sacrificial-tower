"""Publish one verified native project and its reports in a separate run folder."""
from dataclasses import dataclass
from datetime import datetime
import math
from pathlib import Path
import json

from cooling_tower.export_io import atomic_export, atomic_export_data, export_directory
from cooling_tower.native_project.session import NativeSliceError, check_cancel


@dataclass(frozen=True, slots=True)
class NativeProjectExport:
    path: Path
    report_path: Path
    user_report_path: Path


@dataclass(frozen=True, slots=True)
class NativeExportReport:
    output_path: Path
    target_layer_time_s: float | None
    minimum_verified_layer_time_s: float | None
    calibration_time_tolerance_s: float | None
    extra_layer: bool

    generation_method = 'native_project'

    @classmethod
    def read(cls, project_path: Path):
        report = project_path.with_name('Projektbericht.json')
        try:
            with report.open('rb') as stream:
                raw = stream.read(1024 * 1024 + 1)
            if len(raw) > 1024 * 1024:
                return None
            data = json.loads(raw)
        except (OSError, ValueError, RecursionError):
            return None
        if not isinstance(data, dict) or type(data.get('native_project_report_version')) is not int or data['native_project_report_version'] != 1:
            return None

        def seconds(key):
            value = data.get(key)
            return float(value) if type(value) in (float, int) and 0 <= value <= 1e9 and math.isfinite(value) else None

        return cls(project_path, seconds('target_layer_time_s'), seconds('minimum_layer_time_s'),
                   seconds('layer_time_tolerance_s'), data.get('extra_layer_z_mm') is not None)


def verified_export_result(generated):
    result = generated.prepared
    if result is None:
        raise ValueError('Ein geprüftes Turmprojekt ist für den Export erforderlich.')
    if getattr(generated.settings, 'extra_top_layer', False):
        extra_z = getattr(generated, 'extra_layer_z_mm', None)
        if (extra_z is None or result.composed is None or result.composed.extra_layer_base_z is None
                or abs(result.analysis.layers[-1].z_mm - extra_z) > 1e-4):
            raise NativeSliceError('Im geprüften Exportprojekt fehlt der angeforderte zusätzliche Turmlayer.')
    result.verify()
    return result


def export_project_run(session, generated, output_root, *, cancellation_event=None):
    check_cancel(cancellation_event)
    result = verified_export_result(generated)
    installation = result.installation
    protections = {'protected_files': (session.source_snapshot.original_path, installation.executable_path),
        'protected_roots': (installation.executable_path.parent, *installation.profile_roots)}
    name = 'Projekt_' + datetime.now().strftime('%Y-%m-%d_%H-%M-%S')
    minimum = getattr(generated, 'minimum_layer_time_s', None)
    extra_z = getattr(generated, 'extra_layer_z_mm', None)
    if minimum is None:
        minimum = min(layer.total_time_s for layer in result.analysis.layers
                      if extra_z is None or abs(layer.z_mm-extra_z) > 1e-4)
    separate_iterations = getattr(generated, 'separate_iterations', 0)
    best_iteration = getattr(generated, 'best_iteration', None)
    candidate_line = f'Exportierter Kandidat: Durchlauf {best_iteration}\n' if best_iteration is not None else ''
    state = generated.state.value
    status = {'converged': 'Zielzeit erreicht', 'paused': 'Vorläufig übernommen'}.get(
        state, 'Iterations- oder Geometriegrenze erreicht')
    with export_directory(output_root, name, pin_protected_roots_only=True, **protections) as directory:
        path = atomic_export(result.project_path, directory/'Projekt_mit_Turm.3mf',
            expected_sha256=result.project_sha256, cancellation_callback=(cancellation_event.is_set if cancellation_event else None),
            **protections)
        data = {'native_project_report_version': 1, 'adapter_id': result.context.adapter_id, 'state': state,
            'project_sha256': result.project_sha256, 'plate_id': result.plate_id,
            'target_layer_time_s': generated.settings.target_layer_time_s,
            'print_layer_count': result.analysis.layer_count,
            'minimum_layer_time_s': minimum,
            'layer_time_tolerance_s': getattr(generated.settings, 'layer_time_tolerance_s', .25),
            'extra_layer_z_mm': extra_z,
            'tower_center_mm': generated.tower_center_mm, 'tower_radius_mm': generated.tower_radius_mm,
            'iterations': len(generated.iterations), 'separate_iterations': separate_iterations,
            'best_iteration': best_iteration,
            'tower_brim_enabled': False}
        report = atomic_export_data((json.dumps(data, indent=2)+'\n').encode('utf-8'),
                                   directory/'Projektbericht.json', **protections)
        summary = ('Natives 3MF-Projekt · Iterativ\n\n'
            f'Ergebnis: {status}\n'
            f'Gewünschte Mindest-Layerzeit: {generated.settings.target_layer_time_s:g} s\n'
            f'Erreichte Mindest-Layerzeit: {minimum:.2f} s\n'
            f'Getrennte Slices: {separate_iterations}\n'
            f'Gemeinsame Slices: {len(generated.iterations)}\n'
            f'{candidate_line}'
            f'Druckschichten: {result.analysis.layer_count}\n'
            'Turm-Brim: deaktiviert\n\n'
            'Das Projekt enthält den gemeinsam geslicten Kühlturm und die eingebetteten Projekteinstellungen.\n'
            'Die Schichtzeiten sind slicerbasierte Berechnungen.\n'
            + ('Der zusätzliche Turmlayer bleibt bei der erreichten Mindest-Layerzeit unberücksichtigt.\n'
               if extra_z is not None else ''))
        user_report = atomic_export_data(summary.encode('utf-8'), directory/'Projektbericht.txt', **protections)
        check_cancel(cancellation_event)
    return NativeProjectExport(path, report, user_report)
