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
- `services`: Anwendungsfälle für Analyse, Generierung und Ausgabe
- `gui`: Qt-Oberfläche und dünne Worker für lang laufende Anwendungsfälle
- `persistence`: versionierte, gesicherte und atomare Benutzerdaten

Abhängigkeiten sollen von der Oberfläche in Richtung Fachlogik verlaufen.
Fachmodule dürfen keine Qt-Abhängigkeit erhalten.

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
- `config/distribution.json` ist unveränderliche Build-Metadaten. Der Kanal
  `standalone` darf den Sacrificial-Tower-Updater verwenden; der Kanal
  `microsoft-store` schaltet ihn zwingend ab.

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
