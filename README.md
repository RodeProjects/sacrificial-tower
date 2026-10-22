# Sacrificial Tower – 3D Printing Cooling Tower & G-code Analyzer

**Sacrificial Tower** ist ein kostenloses Windows-Programm für den FDM-/FFF-3D-Druck.
Es analysiert die **minimale Schichtzeit (minimum layer time)** und erzeugt einen
zusätzlichen **Kühlturm (sacrificial cooling tower)**, damit kleine Druckschichten
mehr Zeit zum Abkühlen erhalten. Die Turmform lässt sich automatisch berechnen
oder manuell bearbeiten und mit dem gewählten Slicer prüfen.

**English:** Sacrificial Tower is a free Windows **3D printing sacrificial tower
tool** and **G-code analyzer**. It works as a **minimum layer time cooling optimizer**
by generating a separate printable cooling tower for short FDM/FFF layers.
Analyze STL models through your installed slicer, inspect layer times and export
a tower STL or a supported native 3MF project. Existing text G-code can be analyzed
with the separate command-line interface.

**[Windows-Installer herunterladen](https://github.com/RodeProjects/sacrificial-tower/releases/latest)**
· [Getestete Slicer](#unterstützte-slicer-und-getestete-versionen)
· [FAQ / English answers](docs/faq.md)
· [Dokumentation](docs/README.md)

## Funktionen für 3D-Druck und minimale Schichtzeit

- Lokale STL-Analyse mit bestätigten Drucker-, Prozess- und Filamentprofilen;
  G-Code-Analyse über die CLI.
- Automatischer Kühlturm mit Ziel-Layerzeit oder manueller Béziereditor mit
  festem Prüfslice und tatsächlicher Zeitbewertung.
- Gemeinsame Objekt-/Turmvorschau, STL-Export und native 3MF-Projekte für die
  unterstützten Integrationen.
- Hinweise auf erkannte leere Schichten und optionale objektspezifische
  Stützensimulation bei erkanntem, global ausgeschaltetem Stützenprofil.
- Originalmodelle und installierte Slicerprofile bleiben unverändert;
  abgeleitete Dateien entstehen in eigenen Arbeitsbereichen.

Außendurchmesser, Übergangswinkel und Standfuß begrenzen die Turmgeometrie.
Der geschlossene Turmkörper hat keinen modellierten inneren Hohlraum; das
tatsächliche Infill bestimmt der Slicer. Wenn die Analyse keinen Turm benötigt,
ist das ein erfolgreicher Ausgang ohne zusätzliche STL. Die Anwendung ist
vom Anbieter kostenlos erhältlich und unter der **Apache-2.0-Lizenz** lizenziert;
die [Projektlizenz](LICENSE.md) beschreibt
Nutzungs- und Weitergaberechte.

## Windows-Download und Voraussetzungen

Die [offiziellen GitHub-Releases](https://github.com/RodeProjects/sacrificial-tower/releases)
enthalten den Windows-Installer. Aktuelle Fassungen sind **Entwicklungsversionen
für Tests und Evaluation**. Die Apache-2.0-Umstellung betrifft den aktuellen
Quellstand und daraus kommende Builds. Für bereits veröffentlichte Installer gilt
die jeweils mitgelieferte Lizenz; sie werden durch diese README nicht umlizenziert.
Für den STL-Ablauf zuerst einen unterstützten Slicer
installieren und darin den eigenen Drucker, das Filament und ein Prozessprofil
einrichten. Danach die Profile im Slicer speichern und im Turmprogramm auswählen.
Die Verwendung des Windows-Installers erfordert keine eigene Python-Installation.

Der Entwicklungsstand auf `main` kann neuer als der veröffentlichte Installer
sein. Ein Release gehört zu seinem unveränderlichen Quellcode-Tag `vVERSION`;
Installer, Versionshinweise und signiertes Manifest tragen dieselbe Version.
Bisherige Testinstallationen aus dem alten separaten Updatekanal müssen die neue
Version einmal manuell installieren. Eine automatische Migration ist nicht vorgesehen.

## Start unter Windows

Referenzumgebung: Python 3.13.2, x64. Im Projektordner:

```powershell
py -3.13 -m venv .venv
.\.venv\Scripts\python.exe -m pip install --require-hashes -r requirements-windows.lock
.\.venv\Scripts\python.exe main.py
```

Eine vorhandene Projektumgebung weiterverwenden. Die lokale Entwicklungsverknüpfung
kann mit `scripts/create_dev_shortcut.ps1` erzeugt werden; `start_gui.pyw` ist der
GUI-/PyInstaller-Einstieg. Native Analyse und Buildvoraussetzungen stehen unter
[Entwicklung und Tests](docs/development.md).

## Unterstützte Slicer und getestete Versionen

Zuletzt erfolgreich getestete Referenzstände:

| Slicer | Getestete Version |
|---|---|
| Anycubic Slicer Next | 2.0.0.3 |
| Bambu Studio | 02.08.02.61 |
| PrusaSlicer | 2.9.6 |
| OrcaSlicer | 2.4.2 (Microsoft-Store-Paket 2.4.3.0) |

Das sind getestete Referenzstände, keine pauschale Freigabe aller älteren oder
zukünftigen Versionen. Nachweise und Grenzen stehen unter
[Slicer-Unterstützung](docs/slicer_detection_modules.md#zuletzt-erfolgreich-getestete-versionen).

## Bedienung: Kühlturm aus einer STL erstellen

1. STL auswählen. Quellen werden inhaltlich geprüft und unverändert behalten.
2. Slicer, Drucker-, Prozess- und Filamentprofile auswählen und ausdrücklich bestätigen.
3. Zielzeit und Geometrie festlegen, Vorschau erstellen und Ergebnis prüfen.
4. Den bestätigten Kandidaten in einen eigenen Ausgabeordner exportieren.

STL wird erst nach erfolgreicher Validierung und Bestätigung isoliert vorgeslict;
Der dabei erzeugte G-Code wird lokal analysiert; vorhandenen G-Code verarbeitet die separate CLI. Die Anwendung repariert keine beschädigten Modelle
und schreibt weder Profile noch Installationsdateien eines Slicers um. Bekannte
und erkannte Slicer-Verzeichnisse sind als Ausgabeziele gesperrt. Der detaillierte
[Quellenablauf](docs/source_workflow.md) beschreibt Grenzen und Cacheverhalten.

## Häufige Fragen zu Kühltürmen und G-Code

**Wann hilft ein sacrificial cooling tower?** Bei sehr kurzen Druckschichten
kann ein zusätzlicher Druckkörper den zeitlichen Abstand bis zur nächsten
Schicht am Originalobjekt erhöhen. Die Wirkung hängt vom verwendeten Drucker,
Material und Slicerprofil ab.

**Ersetzt der Kühlturm Stützen am Originalmodell?** Stützen werden weiterhin
für die Geometrie des Originalobjekts benötigt. Die optionale Stützensimulation
kann sie in den eigenen Profilkopien und im gemeinsamen Projekt aktivieren.

**Kann ich vorhandenen G-Code analysieren?** Ja, die CLI analysiert vorhandenen
textuellen G-Code; die grafische Oberfläche beginnt mit einer STL.
Ausführlichere englische Antworten stehen in der [Sacrificial Tower FAQ](docs/faq.md).

## Kommandozeile

Die CLI verarbeitet vorhandenen G-Code. Beispiel mit aktuellen Optionen:

```powershell
.\.venv\Scripts\python.exe cli_main.py `
  --gcode "D:\Prints\modell.gcode" `
  --target-time 11 `
  --output-root ".\output"
.\.venv\Scripts\python.exe cli_main.py --help
```

Ohne `--target-time` bleibt die CLI im Analysemodus. Aktuelle Produktstandardwerte
stehen zentral in `config/default_settings.json`. Frühere Hohlraum-/Wand- und
Radiusoptionen sind keine aktuelle Schnittstelle; die Hilfe ist maßgeblich.
Ausgaben werden pro Lauf getrennt unter dem gewählten Ausgabeordner abgelegt.

## Dokumentation, Rechte und Distribution

Der [Dokumentationsindex](docs/README.md) führt zu Architektur, Tests, Migrationen,
Slicern, nativer Analyse und Programmaktualisierungen. Den aktuellen Bestand aus
älteren Phasen dokumentiert ein ausdrücklich [historisches Archiv](docs/history/development_phases.md).

Eigener Code, eigene Dokumentation und eigene Assets stehen unter der
[Apache License 2.0](LICENSE.md), einer OSI-anerkannten Open-Source-Lizenz,
soweit keine abweichende Lizenz angegeben ist. Nutzung, Klonen, Forken, Änderungen
und Weitergabe sind auch kommerziell einschließlich Verkauf zulässig.
Lizenzkopie, Änderungskennzeichnung und die vorgeschriebenen Urheber-/Herkunftshinweise
aus [NOTICE](NOTICE) sind nach Abschnitt 4 zu erhalten. Es gibt keine Commons Clause
und keine Pflicht, eigene Änderungen zu veröffentlichen. Drittkomponenten behalten
ihre eigenen Lizenzen. Erzeugte Kühltürme dürfen kommerziell verwendet werden.
Lizenzumfang, Beiträge und der Übergang von früheren Fassungen sind unter
[Rechte und Nutzungsmodell](docs/distribution.md#rechte-und-nutzungsmodell) erläutert.

Die Oberfläche enthält vollständige Projektlizenz, Nutzungsbedingungen,
Datenschutzinformationen und Drittanbieterhinweise. Maßgeblich sind
[Abhängigkeiten und Lizenzpflichten](docs/dependencies.md),
[kostenlose Veröffentlichung](docs/distribution.md) und die
[Checkliste offener Nachweise](docs/missing_data.md).
Die aktuelle Fassung ist eine kostenlose Entwicklungsversion. Quellcode und
veröffentlichte Installer gehören zum Hauptrepository; eine Microsoft-Store-
Veröffentlichung und reguläre Vertriebsfreigabe benötigen gesonderte Nachweise. Anbieterwerte werden nur in `config/legal_profile.json`
gepflegt.

Fehler, Funktionswünsche und Fragen laufen über
[GitHub Issues](https://github.com/RodeProjects/sacrificial-tower/issues/new/choose).
[Support und Diagnose](docs/support.md) erklärt die freiwilligen Anhänge,
ihre mögliche öffentliche Sichtbarkeit und den vertraulichen Kontaktweg.

Benutzerdaten liegen getrennt vom Programm unter
`%LOCALAPPDATA%/RodeProjects/SacrificialTower/<Instanz>/`. Der eigenständige
Windows-Build verwendet den signierten GitHub-Updatekanal; Python-Entwicklung
und vorbereiteter Store-Kanal aktivieren ihn standardmäßig nicht.
Siehe [Update-Kanal](docs/update_channel.md), [Persistenz](docs/settings_migrations.md)
und [Deinstallation](docs/uninstallation.md).
