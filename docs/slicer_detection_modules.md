# Modulare Slicer-Erkennung

Die Erkennung von Installation, Profilkatalog und zuletzt aktiven Presets ist
pro Slicer in `cooling_tower.slicers.detection` gekapselt. Gemeinsame UI- und
Profilabgleichslogik darf keine herstellerspezifischen Dateinamen, Schlüssel
oder Verzeichnisse voraussetzen.

## Modulvertrag

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
der Laufzeit abgewiesen.

Aktuell implementiert sind:

- Anycubic Slicer Next
- Bambu Studio

Als ausdrückliche, nicht aktive Platzhalter existieren:

- UltiMaker Cura
- PrusaSlicer
- OrcaSlicer
- Creality Print

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
