"""Reserve native print space from deposition rather than helper volumes."""
from __future__ import annotations

import math

from cooling_tower.models import OccupiedBounds
from cooling_tower.native_project.archive import ProjectArchive, parse_xml


def occupied_print_bounds(prepared) -> OccupiedBounds:
    actual = prepared.toolpaths.occupied_bounds
    if actual is None:
        raise ValueError('Die native Platte besitzt keine nachgewiesene belegte Druckfläche.')
    context = prepared.context
    basis = max(*context.nozzle_diameters, *(layer.height_mm for layer in prepared.analysis.layers))
    # Zero widths mean native automatic width selection. Include a conservative
    # allowance, plus any wider global, object, volume or height-range override.
    width = basis * 1.5

    def include(key, value):
        nonlocal width
        if not (key in {'line_width', 'extrusion_width'} or key.endswith(('_line_width', '_extrusion_width'))):
            return
        for item in value if isinstance(value, (list, tuple)) else (value,):
            try:
                text = str(item).strip()
                candidate = float(text.rstrip('%')) * (basis / 100 if text.endswith('%') else 1)
            except (TypeError, ValueError):
                continue
            if math.isfinite(candidate) and candidate > width:
                width = candidate

    for key, value in context.settings.as_dict().items():
        include(key, value)
    with ProjectArchive(context.snapshot.path) as archive:
        for name in ('Metadata/model_settings.config', 'Metadata/Slic3r_PE_model.config',
                     'Metadata/layer_config_ranges.xml', 'Metadata/Prusa_Slicer_layer_config_ranges.xml'):
            if name not in archive.names:
                continue
            for node in parse_xml(archive.read(name, metadata=True)).iter():
                key = node.get('key', node.get('opt_key', ''))
                include(key, node.get('value', node.text or ''))
    half = width / 2
    return OccupiedBounds(actual.minimum_x_mm - half, actual.maximum_x_mm + half,
                          actual.minimum_y_mm - half, actual.maximum_y_mm + half)
