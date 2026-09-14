"""List unresolved provider/release fields; --release fails closed."""
from __future__ import annotations
import argparse
import json
from pathlib import Path
import re

ROOT = Path(__file__).resolve().parents[1]
EXPECTED = {
    "provider_name": "Vollständiger Name des verantwortlichen Anbieters",
    "provider_brand": "Geschäfts-/Produktbezeichnung",
    "provider_email": "Erreichbare Kontakt-E-Mail-Adresse",
    "provider_postal_address": "Ladungsfähige Anschrift: Straße, Hausnummer, PLZ, Ort, Land",
    "provider_additional_details": "Rechtsform, Vertretung, Register und USt-ID, soweit einschlägig; andernfalls ausdrücklich nicht einschlägig",
    "support_retention_policy": "Tatsächliche Löschfristen und eingesetzte Support-/Maildienstleister",
    "commercial_terms": "Vertriebs-/Nutzungsmodell sowie konkrete Support- und Updatezusagen",
    "release_legal_review": "Datierte Freigabe mit Nachweisen: Rechtstexte, LGPL-Quell-/Binärzuordnung, Build-Tool-Lizenzberechtigung samt Runtime-Redistribution und CRA-Einordnung",
}


def missing_fields(root: Path = ROOT) -> list[tuple[str, str]]:
    profile = json.loads((root / "config/legal_profile.json").read_text(encoding="utf-8"))
    missing = [(key, description) for key, description in EXPECTED.items()
            if not isinstance(profile.get(key), str) or not profile[key].strip()
            or re.search(r"\[\[.*?\]\]", profile[key])]
    for key, value in profile.items():
        if key not in EXPECTED:
            missing.append((key, "Nicht registrierte Anbieterangabe: Beschreibung und Checkliste ergänzen"))
    for path in sorted((root / "legal").glob("*.md")):
        content = path.read_text(encoding="utf-8")
        for key in re.findall(r"\{\{([a-z_]+)\}\}", content):
            if key not in EXPECTED:
                missing.append((str(path.relative_to(root)), f"Unregistrierter Vorlagenschlüssel: {key}"))
        if re.search(r"\[\[.*?\]\]", content):
            missing.append((str(path.relative_to(root)), "Direkter Platzhalter: in legal_profile.json zentralisieren"))
    return missing


def checklist(root: Path = ROOT) -> str:
    missing = dict(missing_fields(root))
    rows = []
    for key, description in EXPECTED.items():
        uses = [f"`legal/{path.name}`" for path in sorted((root / "legal").glob("*.md"))
                if "{{" + key + "}}" in path.read_text(encoding="utf-8")]
        if key in {"provider_name", "provider_email"}:
            uses.append("`src/cooling_tower/gui/about_dialog.py`")
        rows.append(f"| {'OFFEN' if key in missing else 'eingetragen'} | `{key}` | {description} | {', '.join(uses) or 'Freigabeprozess'} |")
    return """# Fehlende Angaben und Platzhalter

Automatisch aus `config/legal_profile.json` und den Rechtstext-Vorlagen erstellt.
**Alle Werte ausschließlich in dieser JSON-Datei eintragen.** Die Anwendung setzt
sie beim Öffnen der Rechtstexte ein; Vorlagen nicht zusätzlich von Hand ausfüllen.
Nach Änderungen `python scripts/check_release_readiness.py --write-checklist`
ausführen. `python scripts/check_release_readiness.py --release` muss anschließend
erfolgreich sein. Nicht registrierte Felder und Platzhalter in Vorlagen blockieren
die Prüfung ebenfalls. Die Liste erfasst die Anbieter-/Vertriebsangaben, keine
gewöhnlichen Eingabefeld-Hinweise der GUI oder Beispielvariablen in Anleitungen.

| Status | Feld in config/legal_profile.json | Erwartete Daten | Verwendung |
|---|---|---|---|
""" + "\n".join(rows) + """

Wenn alle Einträge erledigt sind und die Prüfung erfolgreich ist, sind sämtliche
hier registrierten Daten eingepflegt. Das bestätigt die Vollständigkeit der
Felder, nicht die materielle Richtigkeit einer Rechtsprüfung. Die datierte
Freigabe muss die Nachweise aus [Kommerzieller Vertrieb](commercial_release.md)
tatsächlich prüfen; ein beliebiger Text ist keine juristische Freigabe.
Die Rechtstexte beschreiben bis zu einer bewussten Überarbeitung weiterhin eine
Entwicklungsversion. Ein ausgefülltes kommerzielles Modell allein ändert das nicht.
"""


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--release", action="store_true")
    parser.add_argument("--write-checklist", action="store_true")
    args = parser.parse_args()
    if args.write_checklist:
        (ROOT / "docs/missing_data.md").write_text(checklist(), encoding="utf-8")
    missing = missing_fields()
    for key, description in missing:
        print(f"OFFEN config/legal_profile.json -> {key}: {description}")
    if not missing:
        print("Alle registrierten Anbieter- und Freigabeangaben sind ausgefüllt.")
    raise SystemExit(1 if args.release and missing else 0)
