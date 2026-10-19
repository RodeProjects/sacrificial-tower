from __future__ import annotations

import re


_EXACT_TRANSLATIONS = {
    "Target layer time must be greater than zero.": (
        "Die Ziel-Layerzeit muss größer als 0 sein."
    ),
    "The target layer time must be greater than zero.": (
        "Die Ziel-Layerzeit muss größer als 0 sein."
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
        "Der Aufweitungswinkel zur Horizontalen muss mindestens 20° und weniger als 90° betragen."
    ),
    "No printable layers were detected in the G-code.": (
        "Im erzeugten G-Code wurden keine druckbaren Layer erkannt."
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

_VISIBLE_ERROR_CODE_PATTERN = re.compile(
    r"\b(?:Fehlercode|Fehler-Code|Exitcode|Exit-Code|Returncode)\s*[:=]?\s*"
    r"(-?(?:0x[0-9a-f]+|\d+))\b",
    re.IGNORECASE,
)

_SLICER_CODE_CAUSES = {
    "-50": (
        "Der Slicer hat die Modellgeometrie abgelehnt und konnte daraus "
        "keinen zuverlässig verarbeitbaren G-Code erzeugen."
    ),
    "-17": (
        "Das ausgewählte Prozessprofil ist mit dem Maschinenprofil nicht "
        "kompatibel."
    ),
    "-2": (
        "Der Slicer konnte mindestens eine übergebene Modell- oder "
        "Profildatei nicht laden oder nicht mit der gewählten Konfiguration "
        "verarbeiten."
    ),
    "-1": "Der Slicer konnte den übergebenen Auftrag nicht verarbeiten.",
    "1": "Der Slicer konnte den übergebenen Auftrag nicht verarbeiten.",
    "2": (
        "Die installierte Slicer-Version hat mindestens eine benötigte "
        "Kommandozeilenoption nicht akzeptiert."
    ),
}

_WINDOWS_STATUS_PATTERN = re.compile(
    r"\bWindows-Status\s+(0x[0-9a-f]{8})\b",
    re.IGNORECASE,
)

_WINDOWS_STATUS_CAUSES = {
    "0xc0000005": "eine Zugriffsverletzung im beteiligten Programm",
    "0xc000001d": "einen vom Prozessor nicht unterstützten Programmbefehl",
    "0xc000007b": "ein inkompatibles Programm- oder Bibliotheksformat",
    "0xc0000135": "eine fehlende benötigte Programmbibliothek",
    "0xc0000142": "eine fehlgeschlagene Initialisierung einer Programmbibliothek",
    "0xc0000409": "einen internen Sicherheitsabbruch des beteiligten Programms",
}


def german_user_message(message: object) -> str:
    """Return a German-only message suitable for visible GUI feedback."""

    text = str(message).strip()
    if not text:
        return "Die angeforderte Aktion konnte nicht abgeschlossen werden."
    prefix, separator, diagnostic = text.partition(" Slicer-Ausgabe:")
    if separator and diagnostic.strip().strip(".! ").casefold() == "errors":
        text = prefix.rstrip()
    folded = text.casefold()
    if "no valid nozzle found" in folded:
        return (
            "Bambu Studio konnte dem gemeinsamen Projekt keine gültige "
            "Düse zuordnen."
        )

    windows_status = _WINDOWS_STATUS_PATTERN.search(text)
    if windows_status is not None:
        cause = _WINDOWS_STATUS_CAUSES.get(windows_status.group(1).casefold())
        if cause is not None:
            return f"Der Vorgang wurde durch {cause} beendet."
        return (
            "Ein beteiligtes Programm wurde von Windows wegen eines "
            "internen Prozessfehlers beendet."
        )

    error_code = _VISIBLE_ERROR_CODE_PATTERN.search(text)
    if error_code is not None:
        folded = text.casefold()
        if "slicer" in folded:
            if "unknown config type" in folded:
                return (
                    "Mindestens ein ausgewähltes Profil besitzt keinen vom "
                    "Slicer erkennbaren Profiltyp."
                )
            return _SLICER_CODE_CAUSES.get(
                error_code.group(1).casefold(),
                (
                    "Der Slicer hat den Auftrag wegen eines internen oder "
                    "nicht näher beschriebenen Verarbeitungsfehlers "
                    "abgebrochen."
                ),
            )
        return (
            "Ein beteiligtes Programm hat die angeforderte Aktion wegen "
            "eines internen Verarbeitungsfehlers abgebrochen."
        )
    translated = _EXACT_TRANSLATIONS.get(text)
    if translated is not None:
        return translated

    manual_width = re.fullmatch(
        r"Manual base width must be at least ([0-9.]+) mm\.", text
    )
    if manual_width:
        value = manual_width.group(1).replace(".", ",")
        return f"Die manuelle Standfußbreite muss mindestens {value} mm betragen."

    manual_width_maximum = re.fullmatch(
        r"Manual base width must be at most ([0-9.]+) mm\.", text
    )
    if manual_width_maximum:
        value = manual_width_maximum.group(1).replace(".", ",")
        return f"Die manuelle Standfußbreite darf höchstens {value} mm betragen."

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
