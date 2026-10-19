"""Prusa-specific support simulation; organic supports require Prusa 2.6+."""
import re


def simulated_support_settings(version: str | None) -> dict[str, str]:
    values = {"support_material": "1", "support_material_auto": "1"}
    match = re.match(r"(?:PrusaSlicer\s+)?(\d+)\.(\d+)", version or "")
    if match and tuple(map(int, match.groups())) >= (2, 6):
        values["support_material_style"] = "organic"
    return values
