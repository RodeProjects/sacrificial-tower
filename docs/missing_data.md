# Fehlende Angaben und Platzhalter

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
| eingetragen | `provider_name` | Vollständiger Name des verantwortlichen Anbieters | `legal/privacy.md`, `legal/terms.md`, `src/cooling_tower/gui/about_dialog.py` |
| eingetragen | `provider_brand` | Geschäfts-/Produktbezeichnung | `legal/privacy.md`, `legal/terms.md` |
| eingetragen | `provider_email` | Erreichbare Kontakt-E-Mail-Adresse | `legal/privacy.md`, `legal/terms.md`, `src/cooling_tower/gui/about_dialog.py` |
| OFFEN | `provider_postal_address` | Ladungsfähige Anschrift: Straße, Hausnummer, PLZ, Ort, Land | `legal/privacy.md`, `legal/terms.md` |
| OFFEN | `provider_additional_details` | Rechtsform, Vertretung, Register und USt-ID, soweit einschlägig; andernfalls ausdrücklich nicht einschlägig | `legal/terms.md` |
| OFFEN | `support_retention_policy` | Tatsächliche Löschfristen und eingesetzte Support-/Maildienstleister | `legal/privacy.md` |
| OFFEN | `commercial_terms` | Vertriebs-/Nutzungsmodell sowie konkrete Support- und Updatezusagen | Freigabeprozess |
| OFFEN | `release_legal_review` | Datierte Freigabe mit Nachweisen: Rechtstexte, LGPL-Quell-/Binärzuordnung, Build-Tool-Lizenzberechtigung samt Runtime-Redistribution und CRA-Einordnung | Freigabeprozess |

Wenn alle Einträge erledigt sind und die Prüfung erfolgreich ist, sind sämtliche
hier registrierten Daten eingepflegt. Das bestätigt die Vollständigkeit der
Felder, nicht die materielle Richtigkeit einer Rechtsprüfung. Die datierte
Freigabe muss die Nachweise aus [Kommerzieller Vertrieb](commercial_release.md)
tatsächlich prüfen; ein beliebiger Text ist keine juristische Freigabe.
Die Rechtstexte beschreiben bis zu einer bewussten Überarbeitung weiterhin eine
Entwicklungsversion. Ein ausgefülltes kommerzielles Modell allein ändert das nicht.
