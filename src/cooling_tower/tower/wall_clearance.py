"""Diameter advice for the slicer's small-area solid-infill rule."""

import math

from cooling_tower.postprocessor_profiles import profile_number
from cooling_tower.tower.mesh_generator import MINIMUM_AUTOMATIC_CIRCLE_SEGMENTS


def wall_clearance_hint(values, adapter_id, wall_count, diameter, *, circle_segments=None):
    """Recommend a usable outer diameter, including the remaining infill area.

    Wall widths are summed without their overlap, conservatively reserving room
    for both shells. The inscribed polygon left inside those shells must exceed
    the profile's minimum sparse-infill area. This is advice for that rule, not
    a prediction of top/bottom shells or arbitrary sloping tower toolpaths.
    """
    prusa = adapter_id == 'prusa_slicer'
    orca = adapter_id in {'orca_slicer', 'anycubic_slicer_next', 'bambu_studio'}
    density_keys = ('fill_density',) if prusa else ('sparse_infill_density',) if orca else ('infill_sparse_density',)
    density, _ = profile_number(values, density_keys, allow_zero=True, percent_base=100)
    if density is not None and density >= 100:
        return 'Das Slicer-Profil hat 100 % Füllung. Für einen nicht massiven Turm die Profil-Fülldichte reduzieren.'
    area_keys = ('solid_infill_below_area',) if prusa else ('minimum_sparse_infill_area',) if orca else ()
    area, _ = profile_number(values, area_keys, allow_zero=True)
    unknown = 'Mindestdurchmesser gegen Vollfüllung aus diesem Profil nicht bestimmbar.'
    if density is None or (density > 0 and area is None):
        return unknown
    nozzle, _ = profile_number(values, ('nozzle_diameter', 'machine_nozzle_size'))
    height, _ = profile_number(values, ('layer_height',))
    base = height if adapter_id == 'prusa_slicer' else nozzle
    general, _ = profile_number(values, ('line_width', 'extrusion_width'), percent_base=base)
    outer, _ = profile_number(values, ('outer_wall_line_width', 'external_perimeter_extrusion_width'), percent_base=base)
    inner, _ = profile_number(values, ('inner_wall_line_width', 'perimeter_extrusion_width'), percent_base=base)
    outer, inner = outer or general, inner or general
    if not outer or (wall_count > 1 and not inner):
        return unknown
    segments = MINIMUM_AUTOMATIC_CIRCLE_SEGMENTS if circle_segments is None else circle_segments
    shell = outer + (wall_count - 1) * (inner or 0)
    # Regular polygon area = n/2 * sin(2*pi/n) * circumradius**2.
    # Moving its sides inward by the shell thickness reduces its apothem.
    area_factor = segments / 2 * math.sin(2 * math.pi / segments)
    core_radius = math.sqrt((area if density > 0 else 0) / area_factor)
    # Also retain room for an actual open core when the area rule is disabled.
    core_radius = max(core_radius, (inner or outer) / 2)
    required = 2 * (shell / math.cos(math.pi / segments) + core_radius)
    # The field displays tenths of a millimetre. Always give an enterable value
    # strictly above the boundary (the slicer also solidifies equal areas).
    recommended = (math.floor(required * 10 + 1e-9) + 1) / 10
    if diameter >= recommended - 1e-9:
        return ''
    amount = f'{recommended:.1f}'.replace('.', ',')
    return f'Kleine Querschnitte können massiv werden. Empfehlung: mindestens {amount} mm einstellen.'
