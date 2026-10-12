# Entwicklung, Tests und Build

## Entwicklungsumgebung

Referenzplattform: Windows x64, CPython 3.13; lokal geprüft mit 3.13.2. Im Repository vorhandene `.venv`
verwenden. Der geprüfte vollständige Abhängigkeitsstand einschließlich Buildwerkzeugen
ist mit Wheel-Prüfsummen eingefroren:

```powershell
py -3.13 -m venv .venv
.\.venv\Scripts\python.exe -m pip install --require-hashes -r requirements-windows.lock
.\.venv\Scripts\python.exe main.py
```

`py -3.13` wählt eine installierte 3.13-Version. CI verwendet weiterhin die
aktuelle verfügbare Patchversion dieser Reihe. Der lokal vorhandene Stand 3.13.2
wird nicht als Sicherheitsbaseline festgeschrieben; vor Vertrieb aktuellen
Patchstand verwenden und im Build-Inventar nachweisen. `requirements.txt` beschreibt die zulässigen
direkten Entwicklungsabhängigkeiten; `requirements-build.txt` ergänzt deren
Werkzeuge. Die Lockdatei ist die maßgebliche getestete Windows-Auflösung. Sie
enthält nur Wheels für diese Plattform, keine allgemeine Linux-/macOS-Auflösung.
PySide6-Essentials liefert die benötigten Qt-Widgets; das große Addons-Metapaket
ist keine Projektanforderung mehr. Bereits installierte Addons werden nicht
automatisch aus einer bestehenden Umgebung entfernt. Für Lieferumfangsprüfungen
eine frische Umgebung mit ausschließlich der Lockdatei verwenden.

## Tests nach Änderungsbereich

Alle Befehle im Repository-Root ausführen; Pfade mit Leerzeichen korrekt zitieren.
Für GUI-Tests vorab `$env:QT_QPA_PLATFORM='offscreen'` setzen.

| Änderung | Sinnvoller Einstieg in die bestehende Suite |
|---|---|
| Persistenz, Schreibschutz | `test_versioned_json`, `test_settings_downgrade`, `test_write_safety` |
| Standards, Parameter, Solid-Geometrie | `test_solid_tower_changes`, `test_project_contracts` |
| Slicer-Erkennung | `test_phase14`, `test_slicer_detection_modules` |
| Profile und STL-Bestätigung | `test_phase15`, `test_stl_profile_matching` |
| Quellen, Geometrievalidierung, Preslice | `test_source_workflow` und `test_stl_*` |
| Kalibrierung und gemeinsame Projekte | `test_phase16`, `test_joint_*`, `test_bambu_*` |
| Native Zeitberechnung/Parsing | `test_native_gcode_analysis`, `test_acceleration_timing`, `test_phase13` |
| GUI, About und Lebenszyklen | `test_latest_gui_requirements`, `test_background_job_manager`, `test_gui_crash_stability` |
| Lieferumfang, Rechtstexte, Architekturgrenzen | `test_project_contracts`, `test_update_packaging` |
| Update-/CI-Sicherheit | `test_update_*`, `test_release_*`, `test_ci_change_classifier` |

Die Muster sind Navigation, keine automatisch vollständige Testauswahl. Aktuelle
Dateien mit `rg --files tests` ermitteln; bei nicht vorhandener historischer
Bezeichnung passende Tests im gleichen Fachbereich wählen. Beispiel:

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s tests -p 'test_stl_*.py' -q
.\.venv\Scripts\python.exe -m unittest discover -s tests -q
```

Die Vollsuite ist nach übergreifenden Änderungen und vor einem ausführungsrelevanten
Push nach `main` erforderlich. Die Regeln zur vorherigen/nachfolgenden CI-Prüfung
stehen in `AGENTS.md`. Externe Slicer und Installer-Tests besitzen eigene Voraussetzungen;
ein übersprungener Test ersetzt keine echte Integrationsabnahme. Vorhandene
Windows-Stressskripte und CI separat für Thread-/Prozessänderungen verwenden.

GitHub Actions führt die vollständige Testauswahl mit
`python scripts/run_isolated_tests.py` pro Testdateimuster in einem eigenen
Python-Prozess aus. Jeder Prozess verwendet die normale `unittest`-Discovery
einschließlich Unterpaketen; gleiche Dateinamen werden als gemeinsames Muster
geprüft. Dadurch sammeln sich Qt-Objekte verschiedener GUI-Testmodule nicht
bis zum gemeinsamen Interpreterende an. Fehler, Abstürze und ein Zeitlimit
von zehn Minuten pro Muster lassen den Gesamtlauf fehlschlagen; der CI-Job
ist einschließlich Prozessstarts auf 30 Minuten begrenzt.

## Native Erweiterung und Windows-Paket

Eine für den eigenen Anwendungscode gültig lizenzierte Visual-Studio-/Build-Tools-
Installation mit C++-Toolchain und Windows SDK muss vorhanden sein. Die kostenfreie
Community-Option setzt die entsprechende Nutzungsberechtigung voraus. Details stehen in den
[Dependency-Hinweisen](dependencies.md).

```powershell
.\.venv\Scripts\python.exe setup_native.py build_ext --inplace
.\.venv\Scripts\python.exe scripts/test_native_analysis_core.py
.\.venv\Scripts\python.exe scripts/prepare_qt_sources.py
.\.venv\Scripts\python.exe -m PyInstaller --noconfirm --clean SacrificialTower.spec
.\.venv\Scripts\python.exe scripts/distribution_compliance.py --bundle dist/SacrificialTower --output dist/installer/build-inventory.json
```

Der Source-Schritt lädt ausschließlich versions- und hashgebundene Archive zur
Buildzeit und extrahiert nur Nachweistexte; keine heruntergeladenen Skripte werden
ausgeführt. Der Build isoliert die DLL-Suchpfade von fremden Programmen. `legal/binary-origins.json`
belegt den Ursprung jeder gebündelten Binärdatei und enthält keine persönlichen
absoluten Hostpfade. Nicht freigegebene Herkunft und Qt-Dateien außerhalb des
fixierten Wheels führen zum Abbruch. Der Build sammelt Lizenztexte aus den exakten installierten Wheels,
Python und Qt, übernimmt Quellarchive und entfernt nicht erlaubte Qt-Plugins.
Unbekannte Qt-DLLs blockieren den Build. `build-inventory.json` dokumentiert jede
ausgelieferte Datei mit Größe und SHA-256. Kurze Lizenzablagepfade vermeiden
Windows-Pfadlängengrenzen; `legal/notice-index.json` erhält die ursprünglichen Fundstellen. Entwicklungspakete dürfen sichtbare
rechtliche Platzhalter enthalten; `publish_update.ps1` blockiert ihre Veröffentlichung.

Der CI-Build verwendet Inno Setup 6.7.3 mit festem Downloadhash und führt danach
isolierte Installer-/Deinstallertests aus. Vorgehen: [Update-Kanal](update_channel.md).
Ein lokal erfolgreicher PyInstaller-Build ist noch kein nachgewiesener Installer-Test.

## Aktualisieren und reproduzieren

Neue Versionen zuerst rechtlich und technisch prüfen. Wheels für Python 3.13/Windows
x64 in eine frische temporäre Umgebung laden, deren Versionen und SHA-256 in
Lockdatei und Artefaktregister gemeinsam übernehmen, Vollsuite und frischen Build
prüfen. Qt-Versionen zusätzlich in `qt_sources.json` und Quellhinweisen angleichen.
Die Lockdatei nicht durch einen unkontrollierten `pip freeze` mit persönlichen
Zusatzpaketen ersetzen. Keine globale Python-Installation verändern.

Diese Maßnahmen reproduzieren die Python-Artefaktauswahl. Sie versprechen keine
bitidentischen EXE-Dateien: Windows-Runner, MSVC/SDK, Zeitstempel und Signaturen
sind weitere Einflussgrößen. Zum Release Commit, Toolchain-/SDK-Version, Buildlog,
Inventar und Installer zusammen aufbewahren. GitHub-Artefakte laufen nach 14 Tagen
ab; sie sind kein dauerhaftes Releasearchiv.

In eingeschränkten Windows-Testkonten kann PyInstaller beim Prüfen eines fremden
User-Site-Ordners scheitern. Für einen isolierten lokalen Build pro Prozess
`PYTHONNOUSERSITE=1` und `PYTHONUSERBASE=<Repository>/.tmp/python-userbase` setzen;
keine Zugriffsrechte an persönlichen Python-Verzeichnissen verändern.
