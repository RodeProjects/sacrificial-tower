# Modulare Slicer-Erkennung

Die Erkennung von Installation, Profilkatalog und zuletzt aktiven Presets ist
pro Slicer in `cooling_tower.slicers.detection` gekapselt. Gemeinsame UI- und
Profilabgleichslogik darf keine herstellerspezifischen Dateinamen, Schlüssel
oder Verzeichnisse voraussetzen.

## Modulvertrag

### Zuletzt erfolgreich getestete Versionen

Stand der Nachweisprüfung: **20.10.2026**. Die Unterstützung bezieht sich auf
die folgenden durch reale lokale Slices/Exporte belegten Referenzstände:

| Slicer | Getestete Version | Nachweis |
|---|---|---|
| Anycubic Slicer Next | 2.0.0.3 | Gemeinsamer manueller Prüfslice und Export mit Stützensimulation am 15.10.2026 |
| Bambu Studio | 02.08.02.61 | Gemeinsamer manueller Prüfslice und Export mit Stützensimulation am 15.10.2026 |
| PrusaSlicer | 2.9.6 | Export mit iterativer/manueller Methode und Wieder-Slice am 19.10.2026; zusätzlicher Leerlagen-Kontrollslice am 20.10.2026 |
| OrcaSlicer | 2.4.2 (Microsoft-Store-Paket 2.4.3.0) | Export mit iterativer/manueller Methode und Wieder-Slice am 19.10.2026 |

Orcas Paketversion und die vom CLI/G-Code gemeldete Version unterscheiden sich;
beide Werte beschreiben dieselbe geprüfte Installation. Bambu meldet die
Version mit führenden Nullen. Andere Versionsstände sind durch diese Abnahmen
nicht automatisch bestätigt. Details zu Umfang und Grenzen stehen bei
[OrcaSlicer](orca_slicer.md), [PrusaSlicer](prusa_slicer.md),
[manueller Abnahme](tower_geometry.md) und [Vorslice/Leerlagen](source_workflow.md).
Die lokalen Exportberichte liegen unter
`.tmp/manual_acceptance_{anycubic,bambu}_simulations/exports/` sowie
`build/support-activation-acceptance/{prusa_slicer,orca_slicer}/`; sie sind
Entwicklungsnachweise und kein Bestandteil der Distribution.

### Modulschnittstelle

Ein Modul ist eine Implementierung von `SlicerDetectionModule` und liefert:

- stabile Adapter- und Produktkennungen,
- bekannte ausführbare Dateien und Installationsverzeichnisse,
- ausschließlich lesbare Profilwurzeln,
- ein Schema für die lokal gespeicherte aktive Presetauswahl und
- eine eng begrenzte Liste lokaler Nutzungsmarker und
- eine konservative Filterregel für echte Presetdateien.

Adapter akzeptieren ein kompatibles Ersatzmodul per Dependency Injection. Ein
Ersatz muss dieselbe Adapterkennung tragen und als implementiert markiert sein.
Dadurch kann eine Erkennung ausgetauscht werden, ohne Profilabgleich, UI oder
andere Slicer-Module anzupassen. Nicht implementierte Platzhalter werden von
der Suche und der Laufzeit abgewiesen.

Aktuell implementiert sind:

- Anycubic Slicer Next
- Bambu Studio
- PrusaSlicer
- OrcaSlicer

Als ausdrückliche, nicht aktive Platzhalter existieren:

- UltiMaker Cura
- Creality Print

PrusaSlicer besitzt mit `PrusaSlicerAdapter` und `PrusaProfileCatalog` eine
eigene Integration. Der Katalog liest die FFF-Presetbereiche `printer`,
`print`, `filament`, aktive Herstellerkataloge und mitgelieferte
`resources/profiles`-Vorlagen. Er verarbeitet sowohl flache Benutzer-INI-Dateien
als auch Herstellerdateien mit Abschnitten wie `[printer:Name]` und
`[print:Name]`. Ausgeblendete `*...*`-Vorlagen bleiben für die Vererbung
verfügbar, erscheinen jedoch nicht als auswählbare Profile. Aktive
Herstellerkataloge haben Vorrang vor gebündelten Spiegelkopien; abstrakte
Vorlagen werden zusätzlich nach Hersteller aufgelöst. Cache- und
`physical_printer`-Verzeichnisse bleiben außerhalb der Inventarwurzeln.

Der eigene Adapter serialisiert ein aufgelöstes Maschinen-, Prozess- und
Filamentprofil in eine temporäre INI-Datei innerhalb des isolierten Auftrags
und ruft den Prusa-CLI-Export auf. Profile, Einstellungen, Cache und sonstige
Slicer-Verzeichnisse bleiben lesend. Die gemeinsame Vererbungssuche verwendet
vorgebaute ID- und Namensindizes, damit große Herstellerkataloge nicht für
jeden Elternverweis vollständig durchsucht werden.

Für die interne Analyse fordert der Adapter in jeder temporären Konfiguration
explizit textuellen G-Code an, auch wenn das gewählte Maschinenprofil oder eine
globale PrusaSlicer-Einstellung binären G-Code bevorzugt. Ein trotzdem mit der
Signatur `GCDE` geliefertes Ergebnis wird vor der Analyse mit verständlicher
Fehlermeldung abgewiesen. Laufbezogene Überschreibungen werden nach den
aufgelösten Profilwerten angewendet. Die in iterativer und manueller
Kalibrierung optionale 100-%-Füllung kombiniert bei PrusaSlicer
`fill_density = 100%` mit `fill_pattern = rectilinear`, weil PrusaSlicer das
häufig verwendete Muster `grid` bei dieser Dichte ablehnt. Sämtliche Werte
existieren nur im programminternen Arbeitsverzeichnis.

## Installationserkennung von Windows-Apps

Die Windows-Suche berücksichtigt neben klassischen Installationen auch die
für den aktuellen Benutzer registrierten MSIX-/AppX-Pakete, einschließlich
Microsoft-Store-Installationen. `slicers.windows_app_packages` liest deren
App-Manifeste und ordnet die deklarierten Programmeinstiege anhand der bekannten
ausführbaren Slicerdateien den vorhandenen Adaptern zu. Dies gilt für die vier
unterstützten Slicer und setzt keinen bestimmten Paketnamen oder Herausgebernamen
voraus. VFS-Unterverzeichnisse und abweichende Schreibweisen werden unterstützt.
OrcaSlicers Store-Installation verwendet denselben eigenen Profil- und
Slicing-Adapter wie die klassische Installation. Seine Katalogregeln,
Versionslayouts und Abnahmetests stehen in [OrcaSlicer](orca_slicer.md).

Die Abfrage verwendet einmalig Windows PowerShell und die lesenden Cmdlets
`Get-AppxPackage`/`Get-AppxPackageManifest`, mit zwölf Sekunden Zeitlimit. Sie
startet keine gefundenen Apps, benötigt keine administrativen Rechte und
durchsucht nicht rekursiv den geschützten WindowsApps-Ordner. Nur bekannte
EXE-Namen, existierende Dateien und innerhalb des jeweiligen Paketordners
aufgelöste Pfade werden akzeptiert. Fehlende, unlesbare, ungültige oder zu große
Antworten beeinträchtigen die übrigen Erkennungswege nicht. Die Abfrage läuft
innerhalb der bereits begrenzten und abbrechbaren Slicer-Suche.

Regression: `test_windows_app_packages`; die zusätzliche Prüfung mit dem lokal
installierten Store-OrcaSlicer wird mit
`COOLING_TOWER_RUN_INSTALLED_STORE_SLICER_TEST=1` aktiviert.

## Vorauswahl und fehlende Installation

Eine verfügbare, im Turmprogramm zuletzt ausdrücklich ausgewählte Installation
hat Vorrang. Dropdownwechsel und die Bestätigung von Slicer/Profilen speichern
diese Wahl über den vorhandenen `last_selected_key`. Im Dropdown erhält nur
diese Installation bei mehreren Einträgen „– zuletzt ausgewählt“; automatische
Vorauswahl allein schreibt keine Benutzerentscheidung. Die gespeicherte
Dokumentstruktur und Schema-Version bleiben unverändert.

Ohne verfügbare gespeicherte Wahl wird der Slicer mit dem eindeutig neuesten
lokalen Nutzungsmarker vorausgewählt. Diese Marker sind eine konservative
Näherung an die letzte Öffnung: es werden nur die Änderungszeiten der jeweils
ausdrücklich benannten Hauptkonfigurationen gelesen, keine Nutzungsprotokolle.
Gleiche Zeitstempel verschiedener Produkte, fehlende Marker oder mehrere mit
demselben Marker verbundene Installationen gelten als uneindeutig. Dann wird
alphabetisch nach Produktname ausgewählt. Externe Nutzung erhält keinen
„zuletzt ausgewählt“-Zusatz und überschreibt keine gespeicherte Programmwahl.

Ohne erkannte Installation erklärt ein Hinweis die fehlgeschlagene automatische
Erkennung und listet die vier unterstützten Slicer auf. Er bietet die manuelle
EXE-Auswahl an. Falls noch keiner installiert ist, verweist er auf Installation
eines unterstützten Slicers und die vorherige Einrichtung des eigenen Druckers.

## Laufzeitfreigabe und Fehlergrenzen

`slicers.support` ist die gemeinsame Freigabegrenze. Ein registriertes Modul
mit `implemented=False` wird unabhängig von älteren Adapterfähigkeiten oder
gespeicherten Installationsdaten nicht gesucht oder als Installation angeboten.
Die Standardsuche enthält ausschließlich Anycubic Slicer Next, Bambu Studio,
PrusaSlicer und OrcaSlicer. Der gemeinsame Discovery-Dienst filtert zusätzlich
Platzhalter und reine Erkennungsadapter vor der Suche; gespeicherte Pfade und
manuelle EXE-Auswahl können diese Grenze nicht umgehen. Inventar- und
Slice-Einstiegspunkte weisen nicht unterstützte Installationen weiterhin vor
Dateisuche, Cachezugriff oder Prozessstart ab. Die Modulplatzhalter bleiben
als Erweiterungspunkte im Quellcode erhalten.

Die normale GUI führt Installationssuche und Profiloperationen über
`slicers.operation_process` in eigenen Python-Hilfsprozessen aus. Jeder Auftrag
besitzt ein eigenes temporäres Arbeitsverzeichnis und feste Obergrenzen:

| Auftrag | Maximale Laufzeit |
|---|---|
| Installationssuche oder manuelle Verifikation | 30 Sekunden |
| Profilkatalog oder Änderungsprüfung | 60 Sekunden |
| Profilabgleich einschließlich Probeslices | 300 Sekunden |

Abbruch und Schließen warten nicht auf die Kooperation eines Adapters. Unter
Windows besitzt der Elternprozess einen Job Object mit `KILL_ON_JOB_CLOSE`;
der Hilfsprozess darf erst nach erfolgreicher Zuordnung mit der Arbeit beginnen.
Abbruch, Zeitlimit und normales Auftragsende schließen auch diesen Prozessbaum.
Qt-Arbeitsthreads werden regulär beendet und niemals gewaltsam terminiert.
Beim Wechsel des Slicers im Dropdown wird ein aktiver Profilauftrag sofort
abgebrochen und seine Auftragskennung ungültig. Die Prozessgrenze beendet
auch einen nicht kooperierenden Profilparser. Erst nach regulärer Freigabe
des bisherigen Threads startet die Profilsuche für die neueste Auswahl;
zwischenzeitliche Auswahlen, verspätete Ergebnisse/Fehler und bereits
eingeplante Starts mit veralteter Kennung werden verworfen. Gemeinsame
Profil- und Cache-Dienste werden weiterhin seriell verwendet.
Die bestehenden Adapter und ihre Profilfilter/Vererbungsregeln bleiben die
Fachimplementierung. Die Hilfsprozesse verwenden dieselben persistenten
Inventar-/Zuordnungscaches. Flüchtige Dienst-Caches leben jeweils nur für den
Auftrag; die zusätzliche Prozessinitialisierung ist die bewusste Gegenleistung
für die Begrenzung von Hängern und nativen Abstürzen.

Der private Ergebnistransport verwendet ausschließlich vom eigenen Hilfsprozess
erzeugte Python-Objekte, liest erst nach dessen Prozessende und begrenzt das
Ergebnis auf 128 MiB. Externe Profil- oder Benutzerdateien werden niemals als
Pickle eingelesen. Die Einstiegspunkte verwenden `freeze_support`, damit auch
gepackte Windows-Programme einen Hilfsprozess ohne zweite GUI starten können.
Explizit injizierte Testdienste laufen standardmäßig direkt, damit bestehende
kontrollierte Testdoubles unverändert nutzbar bleiben; die normale Anwendung
aktiviert immer die Prozessgrenze.

Schritt 1 darf eine begrenzte Installationssuche vornehmen, wertet jedoch keine
Profile aus. Profilladen und Profilabgleich beginnen erst in Schritt 2. Beim
Wechsel zurück zur Dateiübergabe wird eine aktive Profilprüfung abgebrochen;
sie kann beim nächsten Öffnen von Schritt 2 erneut beginnen. Die STL-Prüfung
besitzt einen eigenen Hintergrundauftrag und wird durch Slicerfehler nicht
abgebrochen. Sichtbare Fehlermeldungen gehören zu den Slicer-Einstellungen;
deren Zustand wird nicht als Fehler der Dateiübergabe dargestellt.

`gui.slicer_operation_guard` sichert Auftragsstarts, Auswahlevents und die
Übernahme von Ergebnissen ab. Auch leere Fehlermeldungen, fehlende Ergebnisse,
fehlerhafte Integrationen und unerwartete Ausnahmen führen zu verständlichem
Text, gesperrter Profilbestätigung und beendetem Ladezustand. Unbekannte Ursachen
erhalten eine allgemeine Fehlermeldung mit Handlungsmöglichkeit. Veraltete
Auftragsergebnisse dürfen den neueren Fehler- oder Auswahlzustand nicht ersetzen.

Gezielte Regression: `test_slicer_failure_safety` und
`test_prusa_slicer_integration`. Die optionale Prüfung mit dem lokal
installierten PrusaSlicer wird mit
`COOLING_TOWER_RUN_INSTALLED_PRUSA_INTEGRATION_TEST=1` aktiviert. Sie lädt die
realen Profile, slicet ein kleines Modell mit der bestätigten Konfiguration und
erneut mit den Kalibrierungsüberschreibungen, durchläuft außerdem den
Kalibrierungsdienst der iterativen Methode und den manuellen Generierungsdienst,
analysiert deren textuelle G-Code-Ergebnisse und vergleicht danach Inhalt,
Größe und Änderungszeit aller Quelldateien.

## Datenschutz- und Integritätsgrenzen

- Slicer-Verzeichnisse und Slicer-Dateien werden ausschließlich gelesen.
- „Zuletzt verwendet“ wird nur aus dem Änderungszeitpunkt der vom jeweiligen
  Modul ausdrücklich benannten Hauptkonfiguration abgeleitet. Deren Inhalt
  wird hierfür nicht gelesen; Logs, Projekte und beliebige Benutzerordner
  werden weder durchsucht noch protokolliert.
- Temporäre oder abgeleitete Daten werden nie in Slicer-Verzeichnisse geschrieben.
- Die Erkennung benötigt keinen Netzwerkzugriff und überträgt keine Daten.
- Diagnoseereignisse enthalten Zustände und Anzahlen, aber keine Profilinhalte.
- Ungültige Kataloge werden geschlossen abgewiesen; interne Hilfsdateien werden
  nicht als Benutzerprofile dargestellt.

Die neue Modulinfrastruktur verwendet ausschließlich die Python-Standardbibliothek
und bestehenden Projektcode. Sie fügt keine externe Laufzeitabhängigkeit und
keinen fremden Quellcode hinzu.
