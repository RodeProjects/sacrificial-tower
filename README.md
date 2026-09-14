# Sacrificial Tower

Windows-Anwendung zur Analyse lokaler G-Code- und STL-Dateien und zur Erzeugung
eines adaptiven, geschlossenen Kühlturms. Der aktuelle Turm besitzt keinen
modellierten inneren Hohlraum; das tatsächliche Infill bestimmt der Slicer.
Ziel-Layerzeit, Außendurchmesser, Übergangswinkel und Standfuß begrenzen die
Geometrie. Slicerbasierte Vorschau und Kalibrierung prüfen den ausgewählten
Kandidaten vor dem Export. Wenn kein Turm benötigt wird, ist das ein erfolgreicher
Analyseausgang ohne unnötige STL.

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

## Bedienung

1. G-Code oder STL auswählen. Quellen werden inhaltlich geprüft und unverändert behalten.
2. Slicer, Drucker-, Prozess- und Filamentprofile auswählen und ausdrücklich bestätigen.
3. Zielzeit und Geometrie festlegen, Vorschau erstellen und Ergebnis prüfen.
4. Den bestätigten Kandidaten in einen eigenen Ausgabeordner exportieren.

STL wird erst nach erfolgreicher Validierung und Bestätigung isoliert vorgeslict;
G-Code wird direkt analysiert. Die Anwendung repariert keine beschädigten Modelle
und schreibt weder Profile noch Installationsdateien eines Slicers um. Bekannte
und erkannte Slicer-Verzeichnisse sind als Ausgabeziele gesperrt. Der detaillierte
[Quellenablauf](docs/source_workflow.md) beschreibt Grenzen und Cacheverhalten.

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

Der eigene Code ist [proprietär](LICENSE.md). Die Oberfläche enthält offline
lesbare Nutzungsbedingungen für die Entwicklungsversion, Datenschutzinformationen
und Drittanbieterhinweise. [Dependencies und Lizenzpflichten](docs/dependencies.md)
sowie der [kommerzielle Freigabeprozess](docs/commercial_release.md) sind zentral
dokumentiert. Noch fehlende Daten stehen vollständig in der
[Platzhaltercheckliste](docs/missing_data.md); Anbieterwerte nur in
`config/legal_profile.json` ergänzen. Die Entwicklungsversion ist noch nicht
für den regulären Verkauf freigegeben.

Benutzerdaten liegen getrennt vom Programm unter
`%LOCALAPPDATA%/RodeProjects/SacrificialTower/<Instanz>/`. Der eigenständige
Windows-Build verwendet den signierten GitHub-Updatekanal; Python-Entwicklung
und vorbereiteter Store-Kanal aktivieren ihn standardmäßig nicht.
Siehe [Update-Kanal](docs/update_channel.md), [Persistenz](docs/settings_migrations.md)
und [Deinstallation](docs/uninstallation.md).
