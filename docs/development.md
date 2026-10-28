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
| Supportpakete, Datenfilterung | `test_support_report`, `test_support_diagnostic_events` |
| Lieferumfang, Rechtstexte, Architekturgrenzen | `test_project_contracts`, `test_legal_documents`, `test_update_packaging` |
| Update-/CI-Sicherheit | `test_update_*`, `test_release_*`, `test_ci_change_classifier` |

Die Muster sind Navigation, keine automatisch vollständige Testauswahl. Aktuelle
Dateien mit `rg --files tests` ermitteln; bei nicht vorhandener historischer
Bezeichnung passende Tests im gleichen Fachbereich wählen. Beispiel:

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s tests -p 'test_stl_*.py' -q
.\.venv\Scripts\python.exe -m unittest discover -s tests -q
```

Die Vollsuite läuft nach ausführungsrelevanten Pushes in GitHub Actions auf dem
offiziellen selbst gehosteten Runner. Eine zusätzliche lokale Vollprüfung oder
die frühere eigene CI-Nachbildung ist vor einem Push nicht erforderlich.
Gezielte Tests während der Entwicklung bleiben möglich. Die Push- und
Release-Regeln stehen in `AGENTS.md`.
Externe Slicer und Installer-Tests besitzen eigene Voraussetzungen;
ein übersprungener Test ersetzt keine echte Integrationsabnahme. Vorhandene
Windows-Stressskripte und CI separat für Thread-/Prozessänderungen verwenden.
Die lokale Auswahl erkannter Slicer, Profile und Eingabedateien steht zentral in
[den Slicer-Abnahmetests](slicer_acceptance_tests.md).

`test_update_handoff_native.py` verwendet den vorhandenen Inno-Compiler aus
`INNO_ROOT`, `build/tools/InnoSetup` oder `build/inno-portable/compiler`. Die
Testinstallation unter `build/update-handoff-tests` hat keine Deinstallation und
keinen Bezug zur realen Installation. Sie prüft den echten Übergabecontroller,
Abbruch, fehlende Freigabe, tatsächliches Prozessende, Austausch einer Testdatei
und den anschließenden Start eines harmlosen Testprozesses. Der Installer-Workflow
führt sie nach Installation des festgelegten Compilers verpflichtend aus.

In einer eingeschränkten Codex-AppContainer-Umgebung können native Kindprozesse
und Qt-Schließvorgänge vom normalen Windows-Benutzerkontext abweichen. Auf dem
betroffenen Entwicklungsgerät die nativen/GUI-Prüfungen daher im Host-Kontext
mit `QT_QPA_PLATFORM=offscreen` und einem eigenen, beschreibbaren `TEMP`/`TMP`
unter `build/` ausführen. Scanner bleiben aktiv. Ein eventuelles virtuelles
Startsignal ohne sichtbare Statusdatei wird ausdrücklich als nicht freigegebene
Übergabe geprüft und nicht als erfolgreiche Installation gewertet.

Die offizielle private CI verwendet den gemeinsamen Teststarter ihrer
Infrastruktur. Dieser priorisiert neue und zuletzt geänderte Tests anhand der
Git-Historie und bricht beim ersten Fehler ab. Der Projektadapter richtet die
Importpfade zum Projektstamm und zu `src` ein; die Anwendung und ihre Testdateien
benötigen keine Abhängigkeit vom privaten Starter. Der lokale Helfer
`python scripts/run_isolated_tests.py` bleibt für lokale Aufrufe verfügbar.
Beide führen die Testauswahl pro Testdateimuster in einem eigenen Python-Prozess
aus. Vor dem Start zählt eine isolierte Discovery die einzelnen
`unittest`-Testfälle je Muster. Die Fortschrittsanzeige zählt diese Testfälle
kumulativ über die gesamte Suite und rundet den Prozentwert auf volle Prozent;
ein Testfall entspricht dabei einem `TestCase`-Aufruf, nicht einem einzelnen
`subTest`. Ändert sich die Fallzahl zwischen Planung und Ausführung, schlägt der
Lauf mit einer klaren Meldung fehl, statt einen falschen Gesamtstand anzuzeigen.
Jeder Prozess verwendet die normale `unittest`-Discovery einschließlich
Unterpaketen; gleiche Dateinamen werden als gemeinsames Muster geprüft. Dadurch
sammeln sich Qt-Objekte verschiedener GUI-Testmodule nicht bis zum gemeinsamen
Interpreterende an. Start, Ergebnis und Dauer jedes Testfalls werden einzeln
angezeigt. Klassen- und Modul-Skips werden für jede betroffene Testmethode
einzeln gezählt und als übersprungen ausgegeben. Fehler, Abstürze und ein
Zeitlimit von zehn Minuten pro Muster lassen
den Gesamtlauf fehlschlagen. Die Ausgabe zeigt nur Zeiteinheiten mit Wert größer
null: Sekunden, Minuten und Sekunden, Stunden, Minuten und Sekunden sowie ab
einem Tag zusätzlich Tage. Der CI-Job ist einschließlich Prozessstarts auf
30 Minuten begrenzt. Das Workflow-Skript spiegelt die Fortschrittszeilen in eine
Datei unter `RUNNER_TEMP`, damit die lokale Runner-Konsole sie live anzeigt.

GUI-Fixtures müssen ihre eigenen Fenster nach dem Test auch nativ freigeben:
`dispose_test_widget` aus `tests/gui_lifecycle.py` schließt das jeweilige Widget
und verarbeitet ausschließlich dessen verzögerte Qt-Löschung. Ein bloßes
`close()` versteckt das Fenster, lässt aber seine Qt-Objekte im gemeinsamen
Testprozess bestehen. Andere, noch verwendete Testwidgets bleiben erhalten.

## Offizielle Prüfungen

Die öffentlichen Workflows prüfen externe Beiträge mit GitHub Actions.
Eigene Änderungen durchlaufen die getrennt verwaltete offizielle CI vor der
Übernahme nach `main`. Prozess-, Thread- und GUI-Lebenszyklusänderungen benötigen
zusätzlich die vollständige Stressmatrix. Eine bereits bestätigte unveränderte
Vollprüfung wird wiederverwendet.

[Prüfung und Veröffentlichung](ci.md) beschreibt die öffentliche Schnittstelle.
Die konkrete Ausführungsumgebung wird außerhalb dieses Repositories verwaltet.

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
Windows-Pfadlängengrenzen; `legal/notice-index.json` erhält die ursprünglichen Fundstellen.
Entwicklungspakete dürfen sichtbar markierte offene Angaben enthalten. Für ausdrücklich
beauftragte Entwicklungsreleases gilt die begrenzte Ausnahme aus
[Veröffentlichung](distribution.md); fehlende Pflichtangaben blockieren den jeweiligen Weg.

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

## Anbieter und Installer-Metadaten

Der rechtliche Herausgeber stammt aus `config/legal_profile.json`.
PyInstaller übernimmt den Namen in `CompanyName`. Inno Setup verlangt zusätzlich
`/DAppPublisherName=<provider_name>`; der Workflow und beide Installer-Testskripte
lesen ihn aus demselben Profil. `AppId`, Datenpfade und Entwicklerkennung bleiben
stabil, damit vorhandene Installationen und Benutzerdaten weiter erkannt werden.

Bei der interaktiven Installationsordner-Auswahl aktiviert
`AppendDefaultDirName=no` den integrierten Button „Neuen Ordner erstellen“ unten
links im Durchsuchen-Dialog. Ein neuer Unterordner kann am ausgewählten Ort
als Installationsziel angelegt und benannt werden; auf dem Datenträger entsteht
er erst bei der Installation. Der Dialog übernimmt den tatsächlich ausgewählten
Ordner; er hängt „SacrificialTower“ nicht automatisch an. Der vorgeschlagene
Standardpfad und ausdrücklich übergebene `/DIR`-Pfade bleiben unverändert.
Es wird keine zusätzliche Bibliothek verwendet. Grundlage:
[Inno-Setup-Dokumentation](https://jrsoftware.org/ishelp/topic_setup_appenddefaultdirname.htm);
die vorhandene Lizenzdokumentation für Inno Setup gilt weiter.

`python scripts/export_legal_documents.py` exportiert dieselben aufgelösten
Rechtstexte wie die Oberfläche nach `build/legal-public/`. Darin enthält
`terms.md` bereits den vollständigen Apache-2.0-Lizenztext und die Herkunftshinweise
aus NOTICE; `terms.txt` enthält denselben Text mit UTF-8-BOM für Inno Setup.
LICENSE.md und NOTICE werden zusätzlich unverändert als einzelne Dateien exportiert.
Der Paketbuild kopiert beide aus dem Repository in das Rechtsverzeichnis;
die Lieferumfangsprüfung vergleicht beide, die Rechtstextvorlagen, die Quellbuild-
und Austauschhinweise sowie das Anbieterprofil mit dem aktuellen Quellstand.
Sie verlangt auch die zugehörigen aktuellen Exportdateien; übereinstimmende
Exporte veralteter Vorlagen reichen nicht aus.
Die native Erweiterung kennzeichnet ihre Paketmetadaten mit Apache-2.0 und führt
LICENSE.md und NOTICE als Lizenzdateien mit. Die Vorlagen unter `legal/` unverändert als
Vorlagen behalten und öffentliche Kopien nach jeder Text-/Profiländerung neu
erzeugen. Der PyInstaller-Build übernimmt die aufgelösten Kopien unter
`_internal/legal/published/`; die Lieferumfangsprüfung erkennt fehlende oder
veraltete Fassungen. Inno Setup zeigt `terms.txt` vor der interaktiven Installation
auf seiner Lizenzseite. Bei interaktiven Installationen wird „Zustimmen und weiter“
erst freigeschaltet, nachdem das Textende einmal sichtbar war. Der Klick auf
diesen Button ist die ausdrückliche Zustimmung; eine zusätzliche Auswahl per
Radiobutton entfällt. Das bloße Scrollen wechselt die Seite nicht.
Zurückblättern und erneutes Öffnen der Seite behalten die Freigabe des Buttons.
Vollständig sichtbare kurze Texte brauchen keine künstliche Scrollbewegung.
`installer/LicenseScroll.iss` prüft den nativen Scrollbereich unabhängig davon,
ob Maus, Tastatur oder Scrollbalken verwendet werden. Die Navigation wird zusätzlich
gegen ein vorzeitiges Weitergehen geprüft; beim Verlassen wird die Überwachung
beendet. Der Installer-Workflow prüft die Steuerelemente in kleinen isolierten
Test-Installern mit `scripts/test_installer_license.ps1 -IsccPath <ISCC.exe>`:
langer Text, Navigation zum Textende über die Texteingabemarke, die tatsächlich
ausgelieferten Bedingungen, vollständig sichtbarer kurzer Text und stiller Ablauf.
Geprüft werden auch vorzeitiges Weitergehen, Beschriftung, sich nicht überlappende
Buttons, Rückkehr zur Lizenzseite und die Wiederherstellung der üblichen Buttons
auf anderen Seiten.
Dabei werden weder Anwendung noch Benutzerdaten installiert oder verändert.
Stille Programmaktualisierungen zeigen keine Lizenzseite und werden nicht durch
die Scrollsperre blockiert. Automatische Updates gelten nicht als Zustimmung zu
nachträglich verschärften Bedingungen. Der Export lädt nichts hoch und ersetzt
keine Veröffentlichungsfreigabe.
