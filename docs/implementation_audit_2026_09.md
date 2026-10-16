# Umsetzung der Projektprüfung vom September 2026

Diese Datei hält den einmaligen Umbau nachvollziehbar. Maßgebliche dauerhafte
Regeln und Anleitungen stehen nach Abschluss in den verlinkten Themendokumenten.
Ausgangsstand: 0.6.10, Commit `8634206`. Kein Commit oder Push ist beauftragt.

## Reihenfolge und Abnahme

1. Ausgangstests; Lizenzquellen und tatsächlichen Lieferumfang erfassen.
2. Schreibziele schützen; konkurrierende JSON-Speicherung absichern.
3. Aktuelle Einstellungsdefinitionen vereinheitlichen, historische Migrationen erhalten.
4. Qt-Lieferumfang begrenzen, Lizenzmaterial sammeln, Build- und Testabhängigkeiten fixieren.
5. Rechtstexte im Programm zugänglich machen; Herkunft eigener Assets dokumentieren.
6. GUI-Verantwortlichkeiten und große Fachmodule schrittweise entkoppeln.
7. Dokumentationsindex, fachliche Testnavigation, native Verträge und Vertriebsnachweise ergänzen.
8. Vollständige Tests, GUI-/Thread-Prüfungen und frischen Build einschließlich Lieferumfang prüfen.

## Rahmenbedingungen

- Logo und bereitgestellte Test-STL wurden nach ausdrücklicher Bestätigung des
  Rechteinhabers am 14.09.2026 von Florian Rode selbst erstellt; alle Rechte liegen bei ihm.
- Keine Slicer-Originale ändern; reale Slicer-Aufrufe nur mit isolierten Arbeitsdaten.
- Keine kostenpflichtigen Komponenten einführen, keine Kontoeinstellungen oder
  Veröffentlichungen ohne entsprechenden Auftrag ändern.
- Fehlende Anbieterangaben, Vertragsentscheidungen und verbindliche juristische
  Freigaben nicht erfinden. Offene Vertriebsvoraussetzungen ausdrücklich dokumentieren.
- Bestehende Python-APIs und Migrationsketten erhalten; Refactoring anhand
  fachlicher Verantwortlichkeiten statt bloßer Aufteilung großer Dateien.

## Status

Die nachfolgend aufgeführten Änderungen sind implementiert und lokal geprüft.
Der aktuelle Anbieter- und Freigabestand steht in der [Checkliste](missing_data.md);
offene Nachweise erfordern tatsächliche Daten und belastbare Belege.

## Durchgeführte Änderungen

| Bereich | Ergebnis und Nutzen |
|---|---|
| Dokumentation | Kurzer aktueller Einstieg, zentraler Index und thematische Anleitungen; alte Entwicklungsphasen ausdrücklich archiviert. Architektur, Migrationen, Slicerabläufe, native Verträge und Testauswahl sind gezielt auffindbar. |
| Daten-/Slicer-Schutz | Gemeinsame Schreibzielprüfung vor wichtigen Export- und Persistenzzugriffen; bekannte und registrierte portable Slicer-Verzeichnisse sowie explizite Quelldateien werden geschützt. |
| Persistenz | Reentrante Dokumentensperren für Threads und kooperierende Prozesse; kollisionssicheres erstmaliges Anlegen, Snapshot- und Backup-Rennen abgesichert. Schema 10 und historische Migrationsketten bleiben erhalten. |
| Standardwerte | GUI-Modell und CLI beziehen aktuelle Standards aus derselben Konfiguration; historische Migrationswerte werden nicht nachträglich verändert. |
| Modularität | About-Dialog, Vorbereitungselemente, Qt-Vorschaukoordination, Profilregeln und Kandidatenbewertung besitzen eigene Module. Kompatibilitätsimporte bleiben erhalten. Fachliche Vorschauimporte benötigen kein Qt. |
| Thread-Verhalten | Worker-Empfänger explizit als Qt-Slots registriert; GUI-Zugriffe und Folgestarts bleiben im zuständigen Thread. |
| Dependencies | 15 konkrete Windows-/Python-3.13-Wheels mit SHA-256 fixiert; frische Umgebung verwendet nur Essentials statt des vollständigen PySide6-Metapakets. CI und Build folgen derselben Lockdatei. |
| Distribution | Expliziter Qt-Lieferumfang, Lizenzsammlung mit Herkunftsindex, drei geprüfte Quellarchive und Datei-/Binärinventar. Fremde DLLs aus dem Host-PATH werden ausgeschlossen. |
| Rechtstexte | Projektlizenzkennzeichnung, Nutzungsbedingungen der Entwicklungsversion, Datenschutz- und Drittanbietertexte offline im About-Dialog; bestätigte eigene Asset-Rechte dokumentiert. |
| Fehlende Daten | Ein Anbieterprofil, automatisch daraus erzeugte Checkliste mit erwarteten Angaben und Verwendungsorten; Veröffentlichungseinstieg blockiert unvollständige Felder. |
| Startdiagnose | Frühe Import-/DLL-Fehler schreiben ausschließlich in den eigenen Benutzerdatenordner. |

`MainWindow` wurde von 12.275 auf 11.632 Zeilen reduziert. Entscheidend ist die
Trennung der Verantwortlichkeiten; die Hauptklasse ist weiterhin groß. Die
[Architekturhinweise](architecture.md) benennen sinnvolle nächste Modulgrenzen
für spätere Funktionsausbauten. Eine vollständige Neuschreibung oder neue
Codegenerierung wurde mangels belegtem Nutzen nicht eingeführt.

## Prüfungen vom 14.09.2026

| Prüfung | Ergebnis |
|---|---|
| Ausgangssuite | 963 Tests, erfolgreich, 10 übersprungen. |
| Vollsuite nach Umbau, frische Umgebung mit Lockdatei | 981 Tests in 139,249 Sekunden, erfolgreich, 10 übersprungen. |
| Verträge nach letzter Checklistenpräzisierung | 10 Tests erfolgreich; einschließlich Legal-Rendering, Release-Sperre, Herkunftsprüfung und Startfehlerprotokoll. |
| Native Erweiterung | Erzwungener Neubau mit MSVC 14.29.30133 / SDK 10.0.19041.0 erfolgreich; C++-Kerntest sowie gezielte Native-/Vertrags-/CI-Tests erfolgreich. |
| GUI | About- und Rechtstextanzeige visuell geprüft; GUI-/Worker-/Schließverhalten durch Suite und gezielte Tests geprüft. |
| PyInstaller / Lieferumfang | Frischer Build mit Python 3.13.2 und fixierten Wheels erfolgreich; 554 Dateien, 187.818.762 Byte; SHA-256-Inventar unter `dist/installer/build-inventory.json`. |
| Eigenständige EXE | Tatsächlicher Start des endgültigen Pakets mit isolierten Benutzerdaten, deaktivierter Suche/Updateprüfung und automatischem Schließen: Exitcode 0, sauberer Sitzungsabschluss protokolliert. |
| Windows-Installer | Inno Setup 6.7.3: Erstellung erfolgreich. |
| Deinstallation | Integrationstest erfolgreich: laufende Anwendung, Datenerhalt/-löschung und Schutz fremder Dateien. |
| Installer-Ersetzung | Integrationstest erfolgreich: Upgrade, blockierte unbestätigte Neuinstallation/Downgrade, bestätigte Ersetzung sowie Datenerhalt und ausdrücklich angeforderte Löschung. |
| Dokumentationskonsistenz | Lokale Markdown-Dateiverweise vollständig auflösbar; keine neu eingeführten verdächtigen Kodierungszeichen; `git diff --check` erfolgreich. |

Die zehn von der Suite übersprungenen Tests sind nicht als bestanden gezählt.
Die lokalen Build-/Testprotokolle liegen unter `.tmp/audit-*`; diese generierten
Dateien sind nicht Teil des Repositorys. Der abschließende lokale Build trägt
weiterhin 0.6.10, da kein Commit oder Push beauftragt wurde. Ein späterer Push
muss die Versionsregeln des Repositorys anwenden. Es wurde kein CI-Lauf auf
GitHub ausgelöst und keine Veröffentlichung vorgenommen.

## Behobene Probleme der Abschlussprüfung

- Ein Worker-Folgestart benötigte einen expliziten Qt-Slot; die Registrierung
  wurde für die relevanten Worker-Empfänger konsistent ergänzt.
- Tiefe Upstream-Lizenzpfade überschritten die Windows-Installergrenze.
  Kurze eindeutige Dateinamen und ein vollständiger Herkunfts-/Hashindex erhalten
  die Nachweise ohne überlange Zielpfade.
- PyInstaller übernahm eine ABI-inkompatible Qt-DLL aus dem geerbten PATH eines
  fremden Host-Werkzeugs. Eine begrenzte DLL-Suche und Prüfung der tatsächlichen
  Binärherkunft verhindern dies; das neu gebaute Paket startet nachweislich.

## Verbleibende echte Voraussetzungen und Grenzen

- Die [Checkliste fehlender Daten](missing_data.md) führt die aktuell offenen Nachweise auf.
  `release_legal_review` erwartet getrennte Nachweise für Rechtstexte,
  LGPL-Quell-/Binärzuordnung, Toolchain-/Runtime-Berechtigung und CRA-Einordnung.
  Eine ausgefüllte Zeichenkette ersetzt diese Prüfung nicht.
- Versionsgleiche Qt-Quellarchive sind enthalten; vollständige Korrespondenz
  einschließlich Upstream-Patches und Buildkonfiguration ist noch zu belegen.
- Für MSVC ist die tatsächliche Nutzungs-/Redistributionsberechtigung noch zu
  dokumentieren. Kostenfreie Community-Nutzung ist bedingt möglich, aber nicht
  allein durch eine vorhandene Installation bewiesen. Siehe [Dependencies](dependencies.md).
- Der lokale Python-Patchstand 3.13.2 ist ein Prüfnachweis, keine Empfehlung für
  die Veröffentlichung. Für ein Release den aktuellen Sicherheitspatchstand der Reihe
  verwenden und neu bauen; CI folgt deshalb weiterhin `3.13`.
- Dokumentensperren koordinieren die Anwendung. Gegen nicht kooperierende externe
  Editoren bleibt ein kleines Prüf-/Ersetzungszeitfenster; unbekannte Slicerpfade
  benötigen explizite Registrierung. Die Maßnahmen sind keine Betriebssystem-Sandbox.
- Eine verbindliche juristische Freigabe, tatsächliche Veröffentlichungsentscheidungen
  und eine vollständige Neuarchitektur sind mit diesen Änderungen nicht behauptet.
