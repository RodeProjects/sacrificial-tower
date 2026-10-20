"""Conservative evidence of missing deposition planes in a source slice.

Nominal profile heights and travel Z moves cannot prove an empty layer. Use
the analyzed deposition planes together with the slicer's extrusion-height
comments, or an explicit slicing warning. No slicer implementation is copied.
"""
from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
import math
import re

from cooling_tower.models.analysis import GCodeAnalysisSnapshot


_REPORTED_EMPTY = re.compile(
    r"\bempty (?:initial |first )layer\b|\bempty layers? (?:detected|found|between)\b"
    r"|\bno extrusions on the first layer\b"
    r"|\bleere (?:erste )?schichten? (?:erkannt|gefunden)\b",
    re.IGNORECASE,
)
_TOLERANCE_MM = 0.005


def reports_empty_layers(output: str) -> bool:
    return any(
        _REPORTED_EMPTY.search(line)
        and not re.search(r"\b(?:no|without) empty layers?\b", line, re.IGNORECASE)
        for line in output.splitlines()
    )


@dataclass(frozen=True, slots=True)
class EmptyLayerEvidence:
    reported_by_slicer: bool = False
    gaps_mm: tuple[tuple[float, float], ...] = ()

    @property
    def detected(self) -> bool:
        return self.reported_by_slicer or bool(self.gaps_mm)


def inspect_empty_layers(
    snapshot: GCodeAnalysisSnapshot,
    *,
    slicer_output: str = "",
    check_cancel: Callable[[], None] | None = None,
) -> EmptyLayerEvidence:
    """Inspect comments in one bounded-memory pass, reusing motion analysis.

    HEIGHT can change again after LAYER_CHANGE: Prusa's boundary initially
    describes the Z step, while its extrusion tag describes actual thickness.
    Use the value at the first confirmed deposition, never the travel height.
    Support/raft transitions may deliberately leave contact gaps and are not
    diagnosed geometrically. Missing or ambiguous tags do not prove a gap.
    """
    reported = reports_empty_layers(slicer_output)
    printed = [layer for layer in snapshot.layers
               if layer.deposition_count > 0 and layer.first_deposition_line > 0]
    gaps = []
    if printed:
        for layer in snapshot.layers:
            if (layer.deposition_count == 0
                    and printed[0].z_mm < layer.z_mm < printed[-1].z_mm):
                gaps.append((max(0.0, layer.z_mm - layer.height_mm), layer.z_mm))
    layers = iter(printed)
    current = next(layers, None)
    previous = None
    previous_role = ""
    height = z = None
    role = ""
    with snapshot.gcode_path.open("rb") as handle:
        for number, line in enumerate(handle, 1):
            if check_cancel is not None and number % 2048 == 1:
                check_cancel()
            comment = line.strip()
            if comment.startswith(b";"):
                comment = comment[1:].strip()
                if comment in {b"LAYER_CHANGE", b"CHANGE_LAYER"}:
                    z = height = None
                    role = ""
                else:
                    key, _, value = comment.partition(b":")
                    key, value = key.strip(), value.strip()
                    if key in {b"HEIGHT", b"LAYER_HEIGHT", b"Z", b"Z_HEIGHT"}:
                        try:
                            parsed = float(value)
                            parsed = parsed if math.isfinite(parsed) and parsed > 0 else None
                        except ValueError:
                            parsed = None
                        if key in {b"HEIGHT", b"LAYER_HEIGHT"}:
                            height = parsed
                        else:
                            z = parsed
                    elif key in {b"TYPE", b"FEATURE"}:
                        role = value.decode("ascii", errors="ignore").casefold()
            if current is None or number != current.first_deposition_line:
                continue
            contact_transition = any(
                token in name for name in (role, previous_role)
                for token in ("support", "raft", "skirt", "brim", "wipe", "prime")
            )
            if (previous is not None and z is not None and height is not None
                    and abs(z - current.z_mm) <= _TOLERANCE_MM
                    and role and previous_role and not contact_transition
                    and current.z_mm - height > previous.z_mm + _TOLERANCE_MM):
                gaps.append((previous.z_mm, current.z_mm - height))
            previous, previous_role = current, role
            current = next(layers, None)
    if check_cancel is not None:
        check_cancel()
    return EmptyLayerEvidence(reported, tuple(sorted(set(gaps))))


def empty_layer_message(
    evidence: EmptyLayerEvidence, *, simulation_available: bool, supports_active: bool = False,
    direct_simulation_action: bool = False,
) -> str:
    message = (
        "Bei der Druckvorbereitung wurden leere Schichten erkannt: An einigen Stellen des Modells "
        "würde kein Material gedruckt, z. B. weil diese Bereiche zu dünn sind. "
        "Teile darüber können dadurch ohne Unterlage beginnen und beim Drucken misslingen."
    )
    if evidence.gaps_mm:
        ranges = ", ".join(
            f"{start:.3f}–{end:.3f}".replace(".", ",")
            for start, end in evidence.gaps_mm[:5]
        )
        message += f"\n\nBetroffene Höhenbereiche: {ranges} mm."
    if supports_active:
        return message + "\n\nStützen sind bereits aktiviert. Prüfe im Slicer, ob sie die betroffenen Stellen ausreichend abstützen."
    message += "\n\nEmpfehlung: Aktiviere Stützen für das Originalobjekt."
    if simulation_available:
        if direct_simulation_action:
            message += (
                ' Mit „Stützen simulieren“ werden sie bei der automatischen und '
                "manuellen Turmerstellung berücksichtigt."
            )
        else:
            message += ' Verwende dafür die Option „Stützen für STL-Objekt simulieren“ oder aktiviere sie im Slicer.'
    else:
        message += " Aktiviere sie dazu im Slicer."
    return message + " Prüfe das Ergebnis anschließend im Slicer."
