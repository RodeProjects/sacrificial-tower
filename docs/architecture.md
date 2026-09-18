# Architektur und Wartungsleitlinien

## Laufzeitpfade

Die Anwendung besitzt zwei bewusst getrennte Einstiegspunkte:

- `main.py` beziehungsweise `start_gui.pyw` startet die Windows-Oberfläche.
- `cli_main.py` startet die Kommandozeile.

Beide verwenden die Fachlogik unter `src/cooling_tower`. Die GUI erzeugt
Ausgaben ausschließlich über den Vorschau-/Exportpfad. Der CLI-Dienst
`GenerationService` bleibt der direkte, skriptfähige Generierungspfad.

Installations- und Ressourcenpfade sind schreibgeschützte Eingaben. Die GUI
speichert Konfiguration, Logs und Standardausgaben in einem getrennten,
beschreibbaren AppData-Instanzordner. Python-Entwicklung, eigenständiger
Installer und späterer Store-Build verwenden unterschiedliche Instanzen;
gezielte parallele Tests können eine eigene Instanz-ID setzen. Details und die
nicht überschreibende Legacy-Übernahme stehen in
`docs/settings_migrations.md`.

## Paketverantwortung

- `gcode`: G-Code-Parsing und Zeitberechnung
- `models`: unveränderliche fachliche Datenmodelle
- `tower`: Profil-, Standfuß- und Mesh-Berechnung
- `slicers`: Erkennung, Profilinventar und abgesicherte Slicer-Aufrufe
- `calibration`: slicerbasierte Iteration und G-Code-Auswertung
- `preview`: Vorschauaufbau, Export und Berichte
- `services`: Anwendungsfälle für Quellenerkennung, STL-Prüfung, Pre-Slice,
  Analyse, Generierung und Ausgabe
- `gui`: Qt-Oberfläche und dünne Worker für lang laufende Anwendungsfälle
- `persistence`: versionierte, gesicherte und atomare Benutzerdaten

Abhängigkeiten sollen von der Oberfläche in Richtung Fachlogik verlaufen.
Fachmodule dürfen keine Qt-Abhängigkeit erhalten. Die bewusst
gekapselte Laufzeitausnahme ist das austauschbare Slicer-Transportbackend
`slicers.qprocess_backend`; Adapter, Prozessauftrag und fachliche Auswertung
bleiben Qt-unabhängig.

## Gemeinsame Infrastruktur

- Datei-Hashes werden über `cooling_tower.file_integrity.sha256_file`
  berechnet. Die Funktion liest große Dateien blockweise.
- GUI-Hintergrundaufgaben werden über
  `cooling_tower.gui.background_jobs.start_background_job` gestartet. Der
  Aufrufer verbindet zuvor nur die aufgabenspezifischen Signale.
- Änderbare Beschriftungen, Hilfetexte und Prognosezeilen liegen in
  `cooling_tower.gui.texts`, sofern sie von mehreren Aufbau- oder
  Aktualisierungspfaden verwendet werden.
- Standardwerte liegen in `config/default_settings.json`; persistierte
  Benutzereinstellungen, Slicer-Pfade und Profilzuordnungen werden gefiltert
  und über `VersionedJsonStore` schrittweise, gesichert und atomar migriert. Die
  verbindlichen Regeln für neue Einstellungs- und Profilschemata stehen in
  `docs/settings_migrations.md`.
- `slicer_settings.json` ordnet die letzten expliziten Maschinen-, Prozess- und
  Filamententscheidungen der stabilen Identität einer konkreten
  Slicerinstallation zu. Pfad und Profil-ID werden gemeinsam gespeichert;
  unauffindbare Rollen oder inkompatibel gewordene Pakete fallen auf das
  aktuelle Matching zurück.
- `config/distribution.json` ist unveränderliche Build-Metadaten. Der Kanal
  `standalone` darf den Sacrificial-Tower-Updater verwenden; der Kanal
  `microsoft-store` schaltet ihn zwingend ab.

## Quellen- und Analysepipeline

Die GUI besitzt einen einzigen quellenneutralen Einstieg. `SourceArtifact`
hält die unveränderte Benutzereingabe einschließlich Hash fest;
`PreparedAnalysisSource` hält getrennt davon den analysierten G-Code und seine
Herkunft. Ein vorhandener G-Code wird direkt vorbereitet. Eine STL muss zuerst
die strenge `StlValidationService`-Prüfung und die ausdrückliche
Profilbestätigung bestehen und wird danach durch `SourcePreSliceService`
isoliert in G-Code überführt. Beide Pfade münden ausschließlich in
`GCodeAnalysisSnapshot`; Turmprofil, Prognose, Vorschau, Kalibrierung und Export
enthalten keine STL-Sonderberechnung.

Die fachliche Zustandsmaschine unterscheidet Quelle, Validierung,
Slicererkennung, Profilzuordnung und optionalen Pre-Slice explizit. Zulässige
Übergänge werden zentral geprüft. Jeder Quellentausch erhöht die Request-ID,
bricht zugehörige Jobs ab und verwirft Analyse-, Bestätigungs-, Cache-,
Prognose- und Vorschauzustand. Später eintreffende Worker-Ergebnisse dürfen nur
bei identischer Request-ID übernommen werden.

`PreSliceCache` ist ein optionaler Beschleuniger, keine fachliche
Wahrheitsquelle. Sein vollständiger Schlüssel bindet Quelle, Slicer, Profile,
effektive Werte, Adapter und Parser. Jeder Treffer wird in einen neuen
temporären Arbeitsbereich kopiert, erneut gehasht, analysiert und gegen die
Bestätigung geprüft. Persistenz erfolgt schema-versioniert und atomar; ein
unsicherer, zukünftiger oder beschädigter Index wird ignoriert, aber nicht
überschrieben. Die vollständigen Regeln stehen in `docs/source_workflow.md`.

Benutzerquellen und sämtliche Slicerdateien sind unveränderliche Eingaben.
Temporäre Ausgaben, Profilkopien, Diagnose und Cache liegen außerhalb von
Quell- und Slicerverzeichnissen. Produktionscode darf dort niemals Dateien
anlegen, ändern, umbenennen oder entfernen. Orca-Familienadapter ergänzen
fehlende, katalogvererbte Profiltypen ausschließlich in kurzlebigen Kopien des
isolierten Slicer-Arbeitsbereichs. Bestätigung und Cache binden auch sämtliche
geerbten Basisprofile ein.

## Thread-Lebenszyklus

Für sämtliche Hintergrundaufgaben gelten diese überprüfbaren Invarianten:

1. Jeder Worker und sein `QThread` haben genau einen Besitzer, den
   `BackgroundJobManager` im GUI-Thread.
2. Starke Worker- und Thread-Referenzen werden erst nach dem vollständigen
   nativen Threadende entfernt.
3. `QObject`, `QTimer` und `QProcess` werden ausschließlich in ihrem
   zugehörigen Thread erzeugt und zerstört.
4. Abbruchanforderungen über `cancel()` und das gemeinsame
   `threading.Event` sind mehrfach gefahrlos aufrufbar.
5. Kein laufender Thread wird mit `terminate()` gewaltsam zerstört.
6. Nur der GUI-Thread verändert Widgets.

Jeder GUI-Worker besitzt `run()`, genau ein eindeutiges `finished`-Signal und
den gemeinsamen Cancel-Vertrag. Der `BackgroundJobManager` ist der einzige
produktive Erzeuger von `QThread`-Instanzen. Er führt jeden Auftrag durch die
feste Zustandsmaschine
`CREATED → STARTING → RUNNING → CANCEL_REQUESTED → WORKER_FINISHED →
THREAD_FINISHED → RELEASED`. Direkte Normalabschlüsse überspringen
`CANCEL_REQUESTED`, nicht aber die beiden beobachtbaren Abschlusszustände.
Unzulässige Übergänge werden im Entwicklungsbetrieb sofort diagnostiziert.

Das Hauptfenster hält keine Job-Dictionaries, Kompatibilitätsansichten oder
eigenen Worker-/Thread-Paare. Laufende Arbeiten werden ausschließlich über
`BackgroundJobManager.has_active()`, `active_jobs()` und `job_for_request()`
abgefragt. Dadurch bleibt der Manager auch für reine Statusabfragen die einzige
Wahrheitsquelle für Hintergrundarbeit.

Der Worker meldet zuerst seinen fachlichen Abschluss. Das beendet die
Thread-Ereignisschleife; `QThread.finished` plant die Löschung des Workers in
dessen Thread ein. Der Manager wartet anschließend auf das tatsächliche native
Threadende, entfernt erst dann beide starken Referenzen und meldet `RELEASED`.

Beim Schließen fordert der Manager alle Jobs idempotent zum Abbruch auf, setzt
zusätzlich `QThread.requestInterruption()` und wartet mit einem gemeinsamen,
begrenzten Timeout. Ein noch laufender Job bleibt bei Zeitüberschreitung
registriert; die Oberfläche verweigert den unsicheren Programmabschluss und
versucht niemals, den Thread gewaltsam freizugeben.

## Externe Slicer-Prozesse

`prepare_slice()`, Prozess-Runner und `finalize_slice()` bilden drei getrennte
Phasen. Das QProcess-Backend erzeugt Controller, QProcess und alle zugehörigen
Timer erst im ausführenden Worker-Thread. `cancel()` setzt aus dem GUI-Thread
ausschließlich das threadsichere Abbruch-Event; ein Timer im Prozess-Controller
übersetzt es in ein queued Signal. Nur dessen Slot darf `terminate()` oder
`kill()` am QProcess ausführen.

Ein lokaler Qt-Eventloop verarbeitet Prozess- und Ausgabesignale ohne
`waitForFinished()`, Shell-Aufruf oder Python-Lesethread. Der Runner kehrt erst
zurück, nachdem das finale Prozesssignal eingetroffen ist, beide Ausgabekanäle
vollständig ausgelesen, Diagnose- und Job-Object-Handles geschlossen, die
isolierte Umgebung entfernt und die QObjects im Eigentümer-Thread zerstört
wurden. Erst danach darf der übergeordnete Worker sein `finished`-Signal senden.

Unter Windows wird die konkrete Slicer-PID einem Job Object mit
`KILL_ON_JOB_CLOSE` zugeordnet. Kann Windows die Zuordnung nicht herstellen,
bleibt die konkrete PID-Baumaufnahme als diagnostizierter Fallback erhalten;
eine Namenssuche ist verboten. Standardausgabe und Standardfehler haben je
eine Speicherobergrenze. Bei Überschreitung bleibt der jeweilige Tail im
Ergebnis und die vollständigen Bytes werden in einer Diagnosedatei archiviert.
Backend-Schalter, Adaptermatrix und Doppelvalidierung sind in
`docs/slicer_qprocess_compatibility.md` beschrieben.

### Getrennte und gemeinsame Generierungsphase

Jede neue Generierung beginnt unabhängig von einer vorhandenen Vorschau mit
sechs getrennten Turm-Slices. Nur diese Vorstufe verwendet den
Fortschrittsbalken im Hauptfenster. Beim ersten vollständigen Objekt-/Turm-Slice
wechselt die Darstellung in `gui/generation_progress_dialog.py`. Der Worker
meldet jeden vollständig ausgewerteten gemeinsamen Kandidaten als unveränderlichen
`JointSliceProgress`; ausschließlich der GUI-Thread aktualisiert Bildfüllstand,
Zähler und Bestwerte. Der Vorlauf-Fortschritt verwendet ausschließlich rechts
im Footer dieselbe Darstellung wie der Vorbereitungsfortschritt; sein einzeiliger
Status und der Abstand zur Aktionszeile bleiben während des Laufs höhenstabil.
Beim Wechsel in die gemeinsame Phase wird dieser Block ausgeblendet.
Ergebnisanzeigen zählen ausschließlich gemeinsame Slices; die sechs getrennten
Vorläufe erscheinen nur in ihrem eigenen Fortschrittsblock.

Das gemeinsame Budget ist als `maximum_joint_slices` (5–25, Standard 10)
persistiert. Ein Lauf endet bei ausgeschöpftem Budget, einer Abweichung von
höchstens ±0,1 Sekunden, einem Fehler, einer Stagnation über drei gemeinsame
Slices oder einer Benutzerentscheidung. Stagnation liegt nur vor, wenn sich
weder die Turmform noch die gemessenen Layerzeiten nennenswert verändern. Eine
vorzeitige Übernahme setzt ein separates threadsicheres Event: Ein eventuell
laufender Slicer-Prozess wird sicher beendet, während der letzte vollständig
geprüfte gemeinsame Kandidat erhalten bleibt. „Fortsetzen“ startet nur das
verbleibende gemeinsame Budget mit diesem Kandidaten als Seed; eine echte neue
Generierung führt dagegen stets erneut die getrennte Vorstufe aus. Nach der
Übernahme bleibt der Dialog als alleiniger Export-Einstieg erhalten: Dort kann
der Benutzer den besten Kandidaten exportieren oder die Angleichung mit dem
nächsten gemeinsamen Slice fortsetzen. Der Hauptfenster-Button öffnet diesen
Entscheidungsdialog lediglich erneut.

Ein Kandidat, der die feste Zielschwelle von ±0,1 Sekunden erreicht, wird vor
der Abschlussmeldung atomar zugleich als bester Anzeige- und Exportkandidat
markiert. Dadurch beziehen sich Generierungsdialog, Prognose und Exportbericht
immer auf dieselbe Slicer-Auswertung. Automatische vorzeitige Abschlussgründe
(Zielschwelle, Stagnation oder ein verwertbarer Fehlerzustand) werden unterhalb
des besten Ergebnisses angezeigt; ein regulär ausgeschöpftes Budget und die
manuelle Übernahme benötigen keinen zusätzlichen Hinweis.

Bei gemeinsamen Slices ist die absolute Abweichung der kürzesten relevanten
Layerzeit von der Zielzeit das primäre Vergleichskriterium. Weitere
Konvergenz-, Zeitüberschuss- und Materialwerte entscheiden nur bei gleicher
Abweichung. Ein einmal gefundener Bestwert kann dadurch weder in der Anzeige
noch im später exportierten Kandidaten durch eine größere Abweichung ersetzt
werden.

Der modale Generierungsdialog berechnet seine feste Inhaltsgröße vor dem ersten
sichtbaren Frame und wird bei jeder inhaltlichen Höhenänderung erneut über dem
Hauptfenster zentriert. Zielvorgabe und bisher bestes Ergebnis stehen gemeinsam
in einer zweizeiligen Übersicht. Abbruchhinweise verwenden den Bestwert als
Statusgrundlage: Ergebnisse innerhalb der eingestellten Toleranz erscheinen
grün, größere Abweichungen gelb und Fehler separat rot; Trennlinien bleiben
neutral grau.

### Windows-Prozessfehler ohne blockierende Systemdialoge

`cooling_tower.windows_process` installiert beim frühesten Paketstart genau
eine prozessweite Windows-Richtlinie. Sie ergänzt vorhandene Fehlerflags um
`SEM_FAILCRITICALERRORS`, `SEM_NOGPFAULTERRORBOX` und
`SEM_NOOPENFILEERRORBOX` und aktiviert zusätzlich
`WER_FAULT_REPORTING_NO_UI`. Die Richtlinie wird anschließend nicht wieder
zurückgesetzt: Dadurch gibt es kein globales Setzen-und-Zurücksetzen zwischen
Threads, und sämtliche mit `subprocess` oder `QProcess` erzeugten Nachkommen
erben denselben nichtinteraktiven Fehlermodus.

Im Quell- und Testbetrieb lädt `sitecustomize.py` ausschließlich dieses
leichtgewichtige Modul, bevor Test-Discovery oder Anwendungsimporte beginnen.
Der normale Paketimport wiederholt die Einrichtung idempotent; ein zunächst
unvollständiger WinAPI-Aufruf wird bei der nächsten Sicherungsstelle erneut
versucht. `CREATE_DEFAULT_ERROR_MODE` ist für programmverwaltete Kindprozesse
verboten, weil dieses Flag die Vererbung absichtlich umgehen würde.

Unterdrückt wird nur die Windows-Systemoberfläche. Exitcode, signierter oder
unsignierter NTSTATUS, Crashzustand und Diagnoseereignisse bleiben erhalten.
Bekannte Loader-, Architektur-, Zugriffs- und Fast-Fail-Statuscodes erhalten
eine verständliche Beschreibung. Slicerfehler werden im betroffenen
Programmschritt angezeigt; native Programmabbrüche bleiben über Sitzungsmarker,
Crashlog und den Hinweis beim nächsten Start erkennbar.

## Diagnose und Stresstests

`DiagnosticJournal` schreibt pro Sitzung eine rotierende, append-only
JSONL-Datei. Jeder technische und fachliche Job-Eintrag enthält Sitzungs- und
Korrelations-ID, Programmversion, Ereignisnummer, UTC- und monotone Zeit,
Zustandsübergang, Worker- und Thread-Identität, Abbruch-/Fehlergrund und Dauer.
Pfade, lange Inhalte sowie Schlüssel- und Profilinhalte werden redigiert.

Der zentrale Qt-Message-Handler erfasst insbesondere Timer-, ThreadStorage-,
`setParent`- und vorzeitig zerstörte `QThread`-Warnungen zusammen mit einem
threadsicheren Snapshot der aktiven Jobs. Er öffnet keine GUI, wirft keine
Ausnahme in Qt zurück und reicht Nachrichten an einen zuvor installierten
Handler weiter.

Ein atomarer Sitzungsmarker unterscheidet saubere Abschlüsse von einem
unerwarteten Abbruch. Beim nächsten Start kann der Benutzer den ausschließlich
lokalen technischen Bericht anzeigen, kopieren, seinen Protokollordner öffnen
oder den Hinweis verwerfen. Es gibt keinen automatischen Upload.

Native Stressfälle laufen über `cooling_tower.gui.job_stress` jeweils in einem
eigenen Python-Prozess mit festem Zufalls-Seed. Der Elternprozess prüft
Exitcode, Abschlussmarker, Timeout, kritische Qt-Warnungen, leere Job-Registry
und verwaiste Fake-Slicer-Unterprozesse. Damit beendet ein möglicher nativer
Qt-Abbruch nicht die übrige Testsuite und bleibt mit dem ausgegebenen Seed
reproduzierbar.

Die vollständige G-Code-Datei wird bei jeder gemeinsamen Slicer-Prüfung erneut
gelesen. Ein begrenzter, ausschließlich flüchtiger Block-Cache darf innerhalb
des laufenden Programms nur bitgenau gleiche Maschinenzustände und vollständig
gleiche Quellzeilen wiederverwenden. Er speichert weder Turmkandidaten noch
Sitzungsdaten und darf deshalb keine Kalibrierungsentscheidung ersetzen.

Der Architekturtest wertet den Python-Syntaxbaum aus und erkennt auch
aliasierte beziehungsweise qualifizierte `QThread`-Konstruktoren sowie direkte
`deleteLater`- und `terminate`-Umgehungen. Zusätzlich verbietet er die
Wiedereinführung der entfernten Legacy-Job-API im produktiven Quellcode.

## Regeln für Änderungen

1. Einen bestehenden Anwendungsfall erweitern, statt einen zweiten parallelen
   Laufzeitpfad einzuführen.
2. Fachberechnungen in Fachmodulen halten; GUI-Slots koordinieren nur Zustand,
   Darstellung und Worker.
3. Öffentliche Kompatibilität nur bewusst entfernen. Die kleinen
   Import-Wrapper im Projektwurzelverzeichnis bleiben für ältere Skripte
   absichtlich erhalten.
4. Jede Fehlerkorrektur durch einen fokussierten Regressionstest absichern.
5. Nach strukturellen Änderungen mindestens Syntaxprüfung, vollständige
   Testsuite, GUI-Starttest sowie einen Thread-/Schließtest ausführen.
6. Generierte Caches, virtuelle Umgebungen und Build-Artefakte nicht
   versionieren.

## Verantwortlichkeiten nach dem Wartbarkeitsumbau September 2026

- `gui/about_dialog.py`: eigener Dialog mit Rechtstextanzeige und responsive
  Anordnung. `MainWindow` koordiniert lediglich Öffnen und Positionierung.
- `gui/widgets/preparation_controls.py`: Vorbereitungsnavigation, Statusmodell
  und Fortschrittsanzeige ohne Kenntnis der Hauptfenster-Implementierung.
- `gui/preview_controller.py`: Qt-Thread-/Statuskoordination der Vorschau.
  `preview/controller.py` bleibt nur als schmale Kompatibilitätsweiterleitung;
  die Paket-API lädt den Controller erst bei explizitem Zugriff.
- `slicers/profile_rules.py`: reine Identitäts-, Normalisierungs-, Düsen- und
  Kompatibilitätsregeln. Inventar-I/O und Matching-Orchestrierung bleiben im
  Matching-Service. Alte Funktionsimporte werden weiterhin bereitgestellt.
- `calibration/candidate_evaluation.py`: reine Kandidatenbewertung und
  Konvergenzmessgrößen. Der Service besitzt weiterhin den iterativen Ablauf und
  priorisiert gemeinsame gegenüber isolierten Kandidaten.
- `settings_defaults.py`: aktuelle Standards aus der Ressourcen-JSON; historische
  Migrationswerte bleiben explizit in ihren Migrationsschritten.
- `write_policy.py`: gemeinsame Prüfung eigener Schreibziele gegen bekannte und
  registrierte Slicer-Verzeichnisse; Datei-/Junction-Auflösung vor Schreibzugriffen.
- `persistence/document_lock.py`: gemeinsame Sperre pro kanonischem Dokumentpfad
  über Threads und kooperierende Prozesse, ohne zusätzliche Bibliothek.
- `start_gui.pyw`: auch frühe Import-/DLL-Fehler protokollieren nur im eigenen
  Benutzerdatenordner; das Installationsverzeichnis bleibt unverändert.
- `legal_documents.py`: offline gerenderte Texte aus einer einzigen Anbieterdatei.
  Build-/Vertriebsprüfungen liegen unter `scripts/`, nicht im Produktablauf.

Qt-Signalempfänger für Worker-Ergebnisse sind ausdrücklich als Slots registriert.
Widgetänderungen und Folgestarts bleiben im GUI-Thread. Die Qt-Transportklasse
wird erst bei tatsächlicher Verwendung geladen; ein Import des fachlichen
Vorschaupakets lädt kein Qt. Kompatibilitätsimporte sind kein Vorbild für neue
Fachmodule: neue Aufrufer verwenden die zuständige konkrete Komponente.

## Grenzen und nächste größere Strukturänderungen

`MainWindow` und die Kalibrierungsschleife bleiben umfangreiche Orchestratoren.
Die Auslagerungen beseitigen konkrete vermischte Verantwortlichkeiten, ersetzen
aber keine vollständige Zerlegung. Beim nächsten betroffenen Funktionsausbau
sollten Quellenvorbereitung/Profilbestätigung und Einstellungsansicht jeweils
Eigentümer ihres Zustands und ihrer Widgets werden. Dafür konkrete Übergaben
und Signale definieren; keine Mixins mit beliebigem Zugriff auf hunderte
Hauptfensterattribute einführen. Die bestehende Workflow-Zustandsmaschine und
Request-ID-Prüfung bleiben verbindlich.

Für den Parser ist die Python-/C++-Parität der entscheidende Vertrag, siehe
[native Analyse](native_analysis.md). Eine Komplettumschreibung oder gemeinsame
Codegenerierung würde derzeit zusätzlichen Prüfaufwand und neue Risiken erzeugen.
Gezielte Funktionsänderungen benötigen nur die verantwortlichen Module und
passenden Tests, nicht jedes Mal die gesamte Historie. Testnavigation und
abschließender Prüfumfang: [Entwicklung](development.md).
