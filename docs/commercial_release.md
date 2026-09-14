# Kommerzieller und rechtlicher Vertriebsstand

Stand: 14.09.2026. Das Produkt soll proprietär und ohne verpflichtende laufende
Drittanbieter-Lizenzzahlungen vertrieben werden. Die aktuelle Oberfläche und
Nutzungsbedingungen kennzeichnen ausdrücklich eine **Entwicklungsversion**.
Die vorhandenen technischen Maßnahmen sind keine Freigabe für den regulären Verkauf.

## Eigene Rechte und Rechtstexte

Eigener Anwendungscode: [proprietäre Projektkennzeichnung](../LICENSE.md).
Eigene Grafiken und Test-STL: [Herkunftsnachweis](../src/cooling_tower/gui/assets/ASSET_LICENSES.md).
Der Nutzer bestätigte seine vollständigen Rechte an Logo und Test-STL ausdrücklich.
Das erlaubt deren Nutzung im eigenen kommerziellen Produkt; daraus wird keine
freie Lizenz für beliebige Dritte abgeleitet.

Unter `legal/` stehen Nutzungsbedingungen für die Entwicklungsversion,
Datenschutzinformationen und Drittanbieterhinweise. Die drei Dokumente sind im
Dialog „Über …“ offline erreichbar. Anbieterangaben stammen ausschließlich aus
`config/legal_profile.json`; der [Platzhalterkatalog](missing_data.md) nennt jeden
fehlenden Wert und alle verwendenden Vorlagen. Keine Adresse, Registerdaten,
Löschfristen oder Kaufbedingungen werden erfunden.

Vor Verkauf sind das konkrete Lizenz-/Preismodell, Support-/Updatepflichten,
Verbraucherrechte bei digitalen Produkten, Anbieterkennzeichnung, gegebenenfalls
Widerruf und steuerliche Angaben passend zu Kundengruppe und Vertriebsweg zu
definieren. Eine EULA oder ein Haftungshinweis ersetzt diese Entscheidungen nicht.
Die Entwürfe erhalten zwingende Rechte und LGPL-Rechte ausdrücklich.

## LGPL-Distribution

Qt/PySide bleiben dynamisch austauschbar. Das Paket enthält LGPL/GPL-Texte,
Wheel-Lizenztexte, versionsgebundene Qt-Base-/SVG-/PySide-Quellarchive mit Hashes
und [Hinweise zum Austausch und Quellbuild](../legal/source_build_notes.md).
Nicht benötigte GPL-only-/QML-/Quick-/PDF-Bestandteile werden ausgeschlossen;
eine explizite DLL-/Plugin-Liste prüft den tatsächlichen Lieferumfang.

Vor Freigabe muss ein konkreter Nachweis die Zuordnung zwischen Wheel-Binärdateien
und Quellen bestätigen, einschließlich Upstream-Patches, Buildkonfiguration und
eingebetteter Komponenten. Das alleinige Vorliegen gleich benannter Archive ist
kein vollständiger Nachweis. Fehlendes Material ist vor Vertrieb zu ergänzen.
Aufbewahrung und Erreichbarkeit von Quellen dürfen nicht von ablaufenden CI-Artefakten
abhängen. Die Archive werden deshalb unmittelbar mit dem Anwendungspaket geliefert.
Ein Store-/DRM-Vertrieb erfordert eine neue Prüfung der Austauschmöglichkeiten.
Die kommerzielle Qt-Lizenz wird nicht benötigt, sofern die LGPL-Pflichten für den
konkreten Lieferumfang zuverlässig erfüllt werden. [Qt: LGPL-Pflichten](https://www.qt.io/development/open-source-lgpl-obligations).

## Datenschutz und Produktsicherheit

Modell-/Profilverarbeitung bleibt lokal. Der eigenständige Build kontaktiert für
Updates GitHub; keine Telemetrie wurde hinzugefügt. Bei freiwillig übermittelten
Supportpaketen sind tatsächlich verwendeter Mail-/Supportdienst und Löschfristen
zu ergänzen. Die Datenverarbeitung muss zur Beschreibung passen.
Grundlagen: [DSGVO](https://eur-lex.europa.eu/eli/reg/2016/679/oj),
[§ 5 DDG](https://www.gesetze-im-internet.de/ddg/__5.html).

Der Cyber Resilience Act muss für die konkrete kommerzielle Bereitstellung
eingeordnet werden. Meldepflichten beginnen nach der EU-Kommission am 11.09.2026,
die Hauptpflichten am 11.12.2027. Ein Prozess für Schwachstellenannahme, Bewertung,
Behebung, Sicherheitsupdates und erforderliche Meldungen ist zu bestimmen.
Aus dem lokalen Desktopbetrieb folgt keine automatische Ausnahme.
[EU-Kommission: CRA](https://digital-strategy.ec.europa.eu/en/policies/cyber-resilience-act).

## Freigabe in sinnvoller Reihenfolge

1. Platzhalterliste vollständig abarbeiten und tatsächliche Anbieter-/Vertragsdaten prüfen.
2. Rechtstexte auf das gewählte Angebot umstellen; fachkundige Prüfung bei wesentlichen
   verbleibenden Unsicherheiten, insbesondere Verbraucherrecht, LGPL und CRA.
3. Quell-/Binärzuordnung, Attributionen und Austauschtest für die konkrete Distribution
   belegen. Zusätzlich die [Microsoft-Toolchain-Berechtigung](dependencies.md#microsoft-toolchain-noch-offener-berechtigungsnachweis)
   für eigenen Code und Runtime-Weitergabe dokumentieren; `release_legal_review`
   erst nach Prüfung aller Teilnachweise mit Datum und Referenzen ausfüllen.
4. Aktuellen Sicherheitspatchstand der Python-Reihe verwenden; Tests, nativen Build,
   frisches Anwendungspaket und Installerprüfungen durchführen.
5. Inventar, Lockdatei, Quellen, Toolchain-Versionen und Prüfnachweise dauerhaft archivieren.
6. `scripts/check_release_readiness.py --release` prüfen. Der Publish-Einstieg führt
   diese Prüfung vor seinen Netzwerk-/Veröffentlichungsschritten aus.

Die Prüfung blockiert fehlende und nicht registrierte Felder. Sie kann nicht
feststellen, ob ein Mensch einen inhaltlich richtigen Freigabenachweis eingetragen
hat. Die bestehende Commit-/Push-/Veröffentlichungsfreigabe bleibt erforderlich.
Dieser Arbeitsauftrag veröffentlicht weder Quellcode noch Produkt oder Updates.
