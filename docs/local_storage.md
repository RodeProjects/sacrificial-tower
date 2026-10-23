# Lokale Daten: Lebensdauer und Speichergrenzen

Die Anwendung trennt flüchtige Vorschauzustände, wiederverwendbare Caches,
lokale Fehlernachweise und ausdrücklich erzeugte Exporte. Eine Sitzung endet,
wenn der Anwendungsprozess beendet wird. Nicht alle lokalen Dateien werden
dabei gelöscht.

## Vorschauen und Arbeitsdateien

Die gemerkten Objektansichten des manuellen 3D-Editors sind `QPicture`-/Bild-
und Materialdaten im Arbeitsspeicher, keine gespeicherten Screenshots.
`ManualCanvas._object_pictures` verwendet einen LRU-Cache: höchstens zehn
Einträge, ältere werden bei mehr als 64 MiB geschätzter Belegung verdrängt.
Ein einzelner verbleibender Eintrag darf diese Zielgröße überschreiten.
Hinzu kommen die aktuelle Darstellung und temporäre Renderpuffer; 64 MiB ist
deshalb keine Obergrenze für den gesamten Speicherverbrauch der Anwendung.
Bei einem Quellen-/Referenzwechsel wird dieser Ansichtscache geleert.
Beim Prozessende gibt das Betriebssystem den gesamten Arbeitsspeicher frei.
Diese Ansichten belegen keine zunehmend wachsende Dateisammlung auf der Platte.

`PreviewSourceDataCache` hält maximal zwei versionierte Quellgeometrieeinträge
ebenfalls nur im Arbeitsspeicher. Die automatische und manuelle Methode
besitzen jeweils ihren aktuellen Sitzungsstand. Ihre temporären STL-, 3MF-
und Prüfdaten werden beim Verwerfen des Ergebnisses und beim regulären
Schließen freigegeben. Slicer-Arbeits- und isolierte Umgebungsordner werden
nach dem jeweiligen Aufruf entfernt.

Nach einem Prozessabsturz, erzwungenem Beenden oder fehlgeschlagener
Dateibereinigung können temporäre Reste bestehen bleiben. Eine allgemeine
Startbereinigung beliebiger alter Temp-Ordner existiert nicht. Insbesondere
werden unbekannte Ordner und mögliche Daten anderer noch laufender Prozesse
nicht pauschal gelöscht.

## Fehlernachweise und Protokolle

| Daten | Lebensdauer / Begrenzung |
|---|---|
| `logs/background_jobs.jsonl` | Sitzungsübergreifend. Rotation bei 5 MiB, drei Sicherungen: ungefähr 20 MiB zusammen. |
| `logs/slicer_failures/` | Fehlgeschlagene, abgebrochene oder ins Zeitlimit gelaufene Sliceraufrufe: höchstens zehn Fälle, zusammen 128 MiB, höchstens 32 MiB je Fall, Altersgrenze 14 Tage. Bereinigung beim Programmstart und beim Sichern weiterer Fälle. |
| `application_runtime.log`, `native_crash.log` | Werden angehängt; derzeit keine automatische Größen-/Altersrotation. |
| `application_startup.log`, einzelne GUI-Fehlerdateien | Je Dateiname wird der letzte Bericht überschrieben; keine Sammlung je Fehler. |
| Native Update-Logs und ältere separate Slicer-Rohlogs | Können sitzungsübergreifend liegen bleiben; keine allgemeine automatische Gesamtquote. |
| Bewusst erzeugte Diagnose-ZIPs und Exporte | Bleiben bis zur ausdrücklichen Nutzerlöschung erhalten. |

Fehlernachweise bleiben absichtlich nach dem Sitzungsende verfügbar. Die
14-Tage-Grenze bedeutet eine Bereinigung beim nächsten Start oder weiteren
Sicherungsvorgang, keinen unabhängig vom Programm laufenden Löschdienst.
Zehn Fälle und die Größenquote verdrängen ältere Fälle gegebenenfalls früher.
Kann das Betriebssystem Dateien nicht lesen oder löschen, ist eine erfolgreiche
Sicherung/Bereinigung nicht garantiert. Die Anwendung protokolliert einen
fehlgeschlagenen Sicherungsversuch, ohne den ursprünglichen Slicerfehler zu ersetzen.

Das Archiv enthält den konkreten kopierten Kandidaten, vorhandene temporäre
Profilkopien, den Aufruf, Prozesskennung, Version, Runde, Laufzeit, Abbruchstatus
und begrenzte Ausgabe. Dateien erhalten eine SHA-256-Prüfsumme. Bei einer
CLI-Objektliste werden auch ihre STL-/3MF-Eingaben berücksichtigt. Die native
Projekterstellung wird ebenfalls vor ihrer Bereinigung abgesichert. Zu große
Dateien werden vollständig ausgelassen und als solche vermerkt; Modelle werden
nicht als unbrauchbare Teilkopien gespeichert. Große Textausgaben behalten
einen begrenzten Schlussabschnitt. Der im Journal hinterlegte Diagnosepfad
verweist auf das dauerhafte Archiv, nicht auf den entfernten Arbeitsordner.

Diese Rohdaten können Modellgeometrie, Profilinhalte, Namen und lokale Pfade
enthalten. Sie bleiben lokal und werden **nicht automatisch** in das
datensparsame Supportpaket aufgenommen oder übertragen. Vor einer gesonderten
manuellen Weitergabe müssen sie geprüft werden. Der zentrale Ablauf gilt für
die Anwendungs-Sitzung mit Diagnosejournal. Headless-Aufrufer ohne Journal
verwenden weiterhin ihr ausdrücklich übergebenes `diagnostics_root` und
verantworten dessen Lebensdauer selbst.

Die frühere manuelle Fehlerablage `manual_failed_*` wird nicht mehr unbegrenzt
neu erzeugt: reguläre Slicerfehler nutzen dasselbe Sitzungsarchiv. Der
Headless-/Test-Rückfall verwendet eine ebenfalls begrenzte Ablage unter
`manual_failures/`. Alte, bereits vorhandene Fehlerordner werden nicht
rückwirkend als vermeintlich entbehrlich gelöscht.

## Caches auf der Festplatte

- `cache/source_preslice/`: bis zu acht G-Code-Artefakte samt versioniertem
  Index. Ältere Einträge werden beim Einfügen neuer Einträge entfernt.
  Der Cache bleibt nach dem Programmende erhalten; es gibt derzeit keine
  zusätzliche Gesamtgrenze in Bytes. Acht große G-Codes können entsprechend
  viel Speicher beanspruchen. Nach einem Absturz während des Schreibens können
  nicht mehr im Index erfasste Reste verbleiben.
- `config/gcode_analysis_cache.json`: ein zuletzt gespeicherter
  Analysestand, auf 64 MiB begrenzt; keine Datei je Sitzung. Zu große neue
  Ergebnisse ersetzen den bestehenden Cache nicht.
- `config/profile_inventory_cache.json`: persistentes Profilinventar, wird
  aktualisiert. Es wird beim Sitzungsende nicht gelöscht und besitzt keine
  globale Bytequote.
- Einstellungen, Profilzuordnungen und Migrationssicherungen bleiben bewusst
  erhalten. Sie sind keine flüchtigen Vorschaubilder.

Es gibt somit bereits wirksame Grenzen für mehrere Speicherklassen, aber
keine harte Gesamtquote für **alle** lokalen Anwendungsdaten. Insbesondere
Exporte, sonstige Fehler-/Update-Logs und verwaiste temporäre Reste können
weiteren Speicher belegen. Die Deinstallation und ihre ausdrücklich wählbare
Datenbereinigung stehen unter [Deinstallation](uninstallation.md).
