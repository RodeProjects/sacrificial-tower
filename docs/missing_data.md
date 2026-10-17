# Fehlende Angaben und Platzhalter

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
| eingetragen | `provider_name` | Vollständiger Name des verantwortlichen Anbieters | `legal/privacy.md`, `legal/terms.md`, `legal/third_party.md`, `src/cooling_tower/gui/about_dialog.py` |
| eingetragen | `provider_display_name` | Bevorzugter Anzeigename der Oberfläche; ersetzt nicht den rechtlichen Anbieternamen | `src/cooling_tower/gui/voluntary_support_dialog.py` |
| eingetragen | `provider_brand` | Entwicklerkennung, keine eigene Firmierung | `legal/privacy.md`, `legal/terms.md` |
| eingetragen | `support_url` | GitHub-Issue-Auswahl für freiwilligen Support | `legal/privacy.md`, `legal/terms.md`, `src/cooling_tower/gui/about_dialog.py` |
| eingetragen | `provider_email` | Erreichbare Kontakt-E-Mail-Adresse | `legal/privacy.md`, `legal/terms.md` |
| eingetragen | `support_paypal_email` | Bestätigte PayPal-Empfängeradresse für freiwillige Unterstützung ohne Gegenleistung | `legal/privacy.md`, `legal/terms.md`, `src/cooling_tower/gui/voluntary_support_dialog.py` |
| eingetragen | `provider_postal_address` | Ladungsfähige Anschrift: Straße, Hausnummer, PLZ, Ort, Land | `legal/privacy.md`, `legal/terms.md` |
| eingetragen | `provider_additional_details` | Rechtsform, Vertretung, Register und USt-ID, soweit einschlägig; andernfalls ausdrücklich nicht einschlägig | `legal/terms.md` |
| eingetragen | `support_retention_policy` | Speicher-/Löschkriterien und eingesetzte GitHub-/Maildienste | `legal/privacy.md` |
| eingetragen | `distribution_terms` | Vertriebs-/Nutzungsmodell sowie konkrete Support- und Updatezusagen | Freigabeprozess |
| OFFEN | `release_legal_review` | Datierte Prüfung mit Nachweisen: individuelle Lizenz/Rechtstexte, GitHub-/Mail-Datenschutzbedingungen, LGPL-Quell-/Binärzuordnung und Store-Austausch, Toolchain-/Runtime-Berechtigung sowie CRA-Einordnung | Freigabeprozess |

Wenn alle Einträge erledigt sind und die Prüfung erfolgreich ist, sind sämtliche
hier registrierten Daten eingepflegt. Das bestätigt die Vollständigkeit der
Felder, nicht die materielle Richtigkeit einer Rechtsprüfung. Die datierte
Freigabe muss die Nachweise aus [Kostenlose Veröffentlichung](distribution.md)
tatsächlich prüfen; ein beliebiger Text ist keine juristische Freigabe.
Die aktuelle Fassung bleibt als Entwicklungsversion gekennzeichnet. Ausgefüllte
Felder sind keine juristische Freigabe und kein Nachweis einer Store-Veröffentlichung.
