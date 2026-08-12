from __future__ import annotations

import re


_EXACT_TRANSLATIONS = {
    "Target layer time must be greater than zero.": (
        "Die Ziel-Layerzeit muss größer als 0 sein."
    ),
    "The target layer time must be greater than zero.": (
        "Die Ziel-Layerzeit muss größer als 0 sein."
    ),
    "The safety factor must be at least 1.0.": (
        "Der Sicherheitsfaktor muss mindestens 1,0 betragen."
    ),
    "Minimum outer diameter must be greater than zero.": (
        "Der kleinste Außendurchmesser muss größer als 0 sein."
    ),
    "The minimum radius must be greater than zero.": (
        "Der Mindestradius muss größer als 0 sein."
    ),
    "Maximum outer diameter must be greater than or equal to minimum outer diameter.": (
        "Der größte Außendurchmesser muss mindestens dem kleinsten Außendurchmesser entsprechen."
    ),
    "The maximum radius must be greater than or equal to the minimum radius.": (
        "Der Maximalradius muss mindestens dem Mindestradius entsprechen."
    ),
    "Base height must not be negative.": (
        "Die Standfußhöhe darf nicht negativ sein."
    ),
    "The local time-factor window must be greater than zero.": (
        "Das lokale Referenzfenster muss größer als 0 sein."
    ),
    "The local time-factor window must be an odd number.": (
        "Das lokale Referenzfenster muss eine ungerade Zahl sein."
    ),
    "Automatic base width must be a boolean value.": (
        "Die automatische Standfußbreite besitzt einen ungültigen Schaltzustand."
    ),
    "Full tower infill simulation must be a boolean value.": (
        "Die Simulation der vollständigen Turmfüllung besitzt einen ungültigen Schaltzustand."
    ),
    "Maximum expansion angle must be greater than zero and at most 70 degrees.": (
        "Der Aufweitungswinkel muss größer als 0° und darf höchstens 70° sein."
    ),
}

_ENGLISH_MARKERS = re.compile(
    r"\b(the|must|cannot|failed|invalid|required|greater|less|minimum|maximum|"
    r"error|not|between|finite|empty|missing|unsupported|timeout|building|"
    r"preparing|processing|loading|writing|slicing|creating|completed)\b",
    re.IGNORECASE,
)

_ADDITIONAL_ENGLISH_MARKERS = re.compile(
    r"\b(is|are|was|were|has|have|could|would|should|unable|available|"
    r"unavailable|found|provided|selected|during|while|with|without|from|"
    r"this|that|these|those|please|occurred|wrong|scanning|reading|saving|"
    r"does|did|needs?|belongs|different|lost|below|above|converge|exist|"
    r"denied|crashed|exception|source|data)\b",
    re.IGNORECASE,
)


def german_user_message(message: object) -> str:
    """Return a German-only message suitable for visible GUI feedback."""

    text = str(message).strip()
    if not text:
        return "Die angeforderte Aktion konnte nicht abgeschlossen werden."
    translated = _EXACT_TRANSLATIONS.get(text)
    if translated is not None:
        return translated

    manual_width = re.fullmatch(
        r"Manual base width must be at least ([0-9.]+) mm\.", text
    )
    if manual_width:
        value = manual_width.group(1).replace(".", ",")
        return f"Die manuelle Standfußbreite muss mindestens {value} mm betragen."

    generation_setting = re.fullmatch(
        r"Generation setting ([A-Za-z0-9_]+) must be finite\.", text
    )
    if generation_setting:
        return "Der eingegebene Zahlenwert muss endlich und vollständig sein."

    finite_value = re.fullmatch(r"The (.+) must be a finite number\.", text)
    if finite_value:
        return "Der eingegebene Zahlenwert muss endlich und vollständig sein."

    if _ENGLISH_MARKERS.search(text) or _ADDITIONAL_ENGLISH_MARKERS.search(text):
        return (
            "Die Eingaben oder Ausgangsdaten konnten nicht vollständig "
            "geprüft werden."
        )
    return text
