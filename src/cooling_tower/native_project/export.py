"""Publish one verified native project and its reports in a separate run folder."""
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
import json

from cooling_tower.export_io import atomic_export, atomic_export_data, export_directory
from cooling_tower.native_project.session import check_cancel


@dataclass(frozen=True, slots=True)
class NativeProjectExport:
    path: Path
    report_path: Path
    user_report_path: Path


def export_project_run(session, generated, output_root, *, cancellation_event=None):
    result = generated.prepared
    if result is None:
        raise ValueError('Ein geprüftes Turmprojekt ist für den Export erforderlich.')
    check_cancel(cancellation_event)
    result.verify()
    installation = result.installation
    protections = {'protected_files': (session.source_snapshot.original_path, installation.executable_path),
        'protected_roots': (installation.executable_path.parent, *installation.profile_roots)}
    name = 'Projekt_' + datetime.now().strftime('%Y-%m-%d_%H-%M-%S')
    with export_directory(output_root, name, pin_protected_roots_only=True, **protections) as directory:
        path = atomic_export(result.project_path, directory/'Projekt_mit_Turm.3mf',
            expected_sha256=result.project_sha256, cancellation_callback=(cancellation_event.is_set if cancellation_event else None),
            **protections)
        data = {'native_project_report_version': 1, 'adapter_id': result.context.adapter_id, 'state': generated.state.value,
            'project_sha256': result.project_sha256, 'plate_id': result.plate_id,
            'target_layer_time_s': generated.settings.target_layer_time_s,
            'print_layer_count': result.analysis.layer_count,
            'minimum_layer_time_s': min(layer.total_time_s for layer in result.analysis.layers),
            'tower_center_mm': generated.tower_center_mm, 'tower_radius_mm': generated.tower_radius_mm,
            'iterations': len(generated.iterations), 'tower_brim_enabled': False}
        report = atomic_export_data((json.dumps(data, indent=2)+'\n').encode('utf-8'),
                                   directory/'Projektbericht.json', **protections)
        summary = ('Natives 3MF-Projekt · Iterativ\n\n'
            f'Ergebnis: {"Zielzeit erreicht" if generated.state.value == "converged" else "Iterations- oder Geometriegrenze erreicht"}\n'
            f'Mindest-Layerzeit: {generated.settings.target_layer_time_s:g} s\n'
            f'Gemeinsame Slices: {len(generated.iterations)}\n'
            f'Druckschichten: {result.analysis.layer_count}\n'
            'Turm-Brim: deaktiviert\n\n'
            'Das Projekt enthält den gemeinsam geslicten Kühlturm und die eingebetteten Projekteinstellungen.\n'
            'Die Schichtzeiten sind slicerbasierte Berechnungen.\n')
        user_report = atomic_export_data(summary.encode('utf-8'), directory/'Projektbericht.txt', **protections)
        check_cancel(cancellation_event)
    return NativeProjectExport(path, report, user_report)
