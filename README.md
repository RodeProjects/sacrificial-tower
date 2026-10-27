# Sacrificial Tower - Erstellung dynamischer Opferobjekte passend zur gewünschten Layerzeit

Bei kurzen Layerzeiten kann beim FDM-/FFF-3D-Druck zu wenig Zeit zum Abkühlen bleiben.
**Sacrificial Tower** erstellt dafür einen zusätzlichen **Kühlturm (bzw. ein
Opferobjekt)**: Er wird neben deinem Modell mitgedruckt und erzeugt durch seine
dynamische Form an den nötigen Stellen zusätzliche Layerzeit.

Das kostenlose Windows-Programm wertet die Layerzeiten deines STL-Modells mit
dem gewählten Slicer aus. Im **iterativen Modus** berechnet und prüft es einen
Turm für die gewünschte Mindest-Layerzeit. Im **manuellen Modus** gestaltest du die
Turmform selbst und lässt ihre Wirkung auf die Layerzeiten prüfen.
Wie gut ein iterativ erstellter Turm die gewünschte Layerzeit erreicht,
hängt maßgeblich von den im Programm gewählten Profilen und deren Einstellungen ab.
Beide Modi
exportieren ein **gemeinsames 3MF-Projekt mit Modell und Kühlturm** für deinen
Slicer; die Turm-STL wird zusätzlich gespeichert.
Die dritte Methode **Postprozessor** ergänzt den vorhandenen Pre-Slice um
Abkühlpausen und einen standardmäßig hohlen Abstreifturm. Sie berücksichtigt
Fahr- und Turmzeiten, zeigt Druckbett, Modell und Turm in rekonstruierten
G-Code-Koordinaten und exportiert direkt geprüften G-Code.

**English: Sacrificial Tower / Cooling Tower Generator - Creating dynamic
sacrificial objects tailored to your desired layer time**

Short layer times can leave too little time for cooling. Sacrificial Tower is a
free Windows application for FDM/FFF 3D printing that creates an additional
**cooling tower (a sacrificial object)**, printed alongside your model. Its dynamic
shape adds layer time where needed. It evaluates your STL model's layer times using your selected
slicer. **Iterative mode** calculates and tests a tower for your desired minimum
layer time; **manual mode** lets you shape the tower yourself and check the
resulting layer times. How closely an iteratively generated tower matches your
desired layer time depends substantially on the profiles selected in the
application and their settings. Both modes export a **3MF project containing your model
and tower**, plus a separate tower STL.
The third **Preprocessor** method adds cooling pauses and a hollow wiping tower
to the existing pre-slice. It accounts for travel and tower time, reconstructs
the bed and toolpaths in their G-code coordinates, and exports verified G-code.

**[Windows-Installer herunterladen](https://github.com/RodeProjects/sacrificial-tower/releases/latest)**
· [Getestete Slicer](#unterstützte-slicer-und-getestete-versionen)
· [FAQ / English answers](docs/faq.md)
· [Dokumentation](docs/README.md)

## Funktionen für 3D-Druck und minimale Layerzeit

- Lokale Auswertung der Layerzeiten eines STL-Modells über den gewählten
  Slicer; Analyse der Layerzeiten von vorhandenem G-Code über die CLI.
- Iterative Kühlturmerstellung mit Ziel-Layerzeit oder manueller Béziereditor mit
  festem Prüfslice und tatsächlicher Zeitbewertung.
- Gemeinsame Objekt-/Turmvorschau und 3MF-Export mit Modell und Kühlturm in beiden
  Modi; zusätzliche STL-Datei des Turms.
- [Postprozessor](docs/preprocessor.md) mit hohlem Abstreifturm, automatischer
  sicherer Platzierung, Restwartezeiten und direktem G-Code-Export.
- Hinweise auf erkannte leere Layer und optionale objektspezifische
  Stützensimulation bei erkanntem, global ausgeschaltetem Stützenprofil.
- Originalmodelle und installierte Slicerprofile bleiben unverändert;
  abgeleitete Dateien entstehen in eigenen Arbeitsbereichen.

Außendurchmesser, Übergangswinkel und Standfuß begrenzen die Turmgeometrie.
In den Geometriemodi hat der geschlossene Turmkörper keinen modellierten
inneren Hohlraum; das tatsächliche Infill bestimmt der Slicer. Der
Postprozessor erzeugt dagegen standardmäßig eine hohle Abstreifwand.
Wenn die Analyse keinen Turm benötigt,
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
Für den STL-Ablauf zuerst einen unterstützten Slicer installieren und darin den
eigenen Drucker einrichten. Danach den Slicer und die gewünschten Einstellungen
im Turmprogramm auswählen und bestätigen.
Die Verwendung des Windows-Installers erfordert keine eigene Python-Installation.

Der Entwicklungsstand auf `main` kann neuer als der veröffentlichte Installer
sein. Ein Release gehört zu seinem unveränderlichen Quellcode-Tag `vVERSION`;
Installer, Versionshinweise und signiertes Manifest tragen dieselbe Version.
Bisherige Testinstallationen aus dem alten separaten Updatekanal müssen die neue
Version einmal manuell installieren. Eine automatische Migration ist nicht vorgesehen.
Das frühere Update-Repository ist als abgelöst gekennzeichnet und archiviert.

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

**Wann hilft ein sacrificial cooling tower?** Bei sehr kurzen Layerzeiten
kann ein zusätzlicher Druckkörper den zeitlichen Abstand bis zum nächsten
Layer am Originalobjekt erhöhen. Die Wirkung hängt vom verwendeten Drucker,
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
