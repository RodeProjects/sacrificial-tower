"""Validate free distribution and explicitly labelled development releases."""
from __future__ import annotations
import argparse
import json
from pathlib import Path
import re

ROOT = Path(__file__).resolve().parents[1]
EXPECTED = {
    "provider_name": "Vollständiger Name des verantwortlichen Anbieters",
    "provider_display_name": "Bevorzugter Anzeigename der Oberfläche; ersetzt nicht den rechtlichen Anbieternamen",
    "provider_brand": "Entwicklerkennung, keine eigene Firmierung",
    "support_url": "GitHub-Issue-Auswahl für freiwilligen Support",
    "provider_email": "Erreichbare Kontakt-E-Mail-Adresse",
    "support_paypal_email": "Bestätigte PayPal-Empfängeradresse für freiwillige Unterstützung ohne Gegenleistung",
    "provider_postal_address": "Ladungsfähige Anschrift: Straße, Hausnummer, PLZ, Ort, Land",
    "provider_additional_details": "Rechtsform, Vertretung, Register und USt-ID, soweit einschlägig; andernfalls ausdrücklich nicht einschlägig",
    "support_retention_policy": "Speicher-/Löschkriterien und eingesetzte GitHub-/Maildienste",
    "distribution_terms": "Vertriebs-/Nutzungsmodell sowie konkrete Support- und Updatezusagen",
    "release_legal_review": "Datierte Prüfung mit Nachweisen: individuelle Lizenz/Rechtstexte, GitHub-/Mail-Datenschutzbedingungen, LGPL-Quell-/Binärzuordnung und Store-Austausch, Toolchain-/Runtime-Berechtigung sowie CRA-Einordnung",
}

DEVELOPMENT_DEFERRED_FIELDS = {
    "provider_postal_address",
    "provider_additional_details",
    "support_retention_policy",
    "distribution_terms",
    "release_legal_review",
}
DEVELOPMENT_TERMS_MARKERS = (
    "## Aktuelle Entwicklungsversion",
    "kostenlose Entwicklungsversion für Tests und Evaluation",
)


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


def development_release_blockers(
    root: Path = ROOT,
) -> list[tuple[str, str]]:
    """Return issues that must still block a free test release."""
    blockers = [
        (key, description)
        for key, description in missing_fields(root)
        if key not in DEVELOPMENT_DEFERRED_FIELDS
    ]
    terms_path = root / "legal" / "terms.md"
    terms = terms_path.read_text(encoding="utf-8")
    normalized_terms = re.sub(r"\s+", " ", terms)
    for marker in DEVELOPMENT_TERMS_MARKERS:
        normalized_marker = re.sub(r"\s+", " ", marker)
        if normalized_marker not in normalized_terms:
            blockers.append(
                (
                    str(terms_path.relative_to(root)),
                    "Entwicklungsrelease ist nicht eindeutig als kostenlose "
                    f"Entwicklungsversion gekennzeichnet: {marker!r}",
                )
            )
    return blockers


def checklist(root: Path = ROOT) -> str:
    missing = dict(missing_fields(root))
    rows = []
    for key, description in EXPECTED.items():
        uses = [f"`legal/{path.name}`" for path in sorted((root / "legal").glob("*.md"))
                if "{{" + key + "}}" in path.read_text(encoding="utf-8")]
        if key in {"provider_name", "support_url"}:
            uses.append("`src/cooling_tower/gui/about_dialog.py`")
        if key in {"provider_display_name", "support_paypal_email"}:
            uses.append("`src/cooling_tower/gui/voluntary_support_dialog.py`")
        rows.append(f"| {'OFFEN' if key in missing else 'eingetragen'} | `{key}` | {description} | {', '.join(uses) or 'Freigabeprozess'} |")
    return """# Fehlende Angaben und Platzhalter

Automatisch aus `config/legal_profile.json` und den Rechtstext-Vorlagen erstellt.
**Alle Werte ausschließlich in dieser JSON-Datei eintragen.** Die Anwendung setzt
sie beim Öffnen der Rechtstexte ein; Vorlagen nicht zusätzlich von Hand ausfüllen.
Nach Änderungen `python scripts/check_release_readiness.py --write-checklist`
ausführen. Vor einer regulären kostenlosen Veröffentlichung muss
`python scripts/check_release_readiness.py --release` erfolgreich sein.
Ausdrücklich gekennzeichnete, kostenlose Entwicklungsversionen dürfen mit
`--development-release` veröffentlicht werden; dabei bleiben die unten genannten
Angaben offen und müssen vor regulärer Veröffentlichung nachgetragen werden. Nicht
registrierte Felder und Platzhalter in Vorlagen blockieren beide Releasearten.
Die Liste erfasst die Anbieter-/Vertriebsangaben, keine gewöhnlichen
Eingabefeld-Hinweise der GUI oder Beispielvariablen in Anleitungen.

| Status | Feld in config/legal_profile.json | Erwartete Daten | Verwendung |
|---|---|---|---|
""" + "\n".join(rows) + """

Wenn alle Einträge erledigt sind und die Prüfung erfolgreich ist, sind sämtliche
hier registrierten Daten eingepflegt. Das bestätigt die Vollständigkeit der
Felder, nicht die materielle Richtigkeit einer Rechtsprüfung. Die datierte
Freigabe muss die Nachweise aus [Kostenlose Veröffentlichung](distribution.md)
tatsächlich prüfen; ein beliebiger Text ist keine juristische Freigabe.
Die aktuelle Fassung bleibt als Entwicklungsversion gekennzeichnet. Ausgefüllte
Felder sind keine juristische Freigabe und kein Nachweis einer Store-Veröffentlichung.
"""


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    release_kind = parser.add_mutually_exclusive_group()
    release_kind.add_argument("--release", action="store_true")
    release_kind.add_argument("--development-release", action="store_true")
    parser.add_argument("--write-checklist", action="store_true")
    args = parser.parse_args()
    if args.write_checklist:
        (ROOT / "docs/missing_data.md").write_text(checklist(), encoding="utf-8", newline="\n")
    missing = missing_fields()
    for key, description in missing:
        print(f"OFFEN config/legal_profile.json -> {key}: {description}")
    if not missing:
        print("Alle registrierten Anbieter- und Freigabeangaben sind ausgefüllt.")
    if args.development_release:
        blockers = development_release_blockers()
        for key, description in blockers:
            print(f"BLOCKIERT {key}: {description}")
        if not blockers:
            print(
                "Entwicklungsrelease zulässig: offene Freigabeangaben bleiben "
                "für den regulären Vertrieb verpflichtend."
            )
        raise SystemExit(1 if blockers else 0)
    raise SystemExit(1 if args.release and missing else 0)
