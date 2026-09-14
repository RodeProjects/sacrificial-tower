# Vertrag der nativen G-Code-Analyse

## Zuständigkeiten

`gcode/parser.py` und `gcode/layer_detector.py` enthalten die Python-Semantik.
`native/native_analysis.cpp` bildet die vollständige unterstützte Analyse in C++ ab;
`native/native_timing.cpp` stellt die CPython-Schnittstelle und Zeitplanung bereit.
`gcode/native_analysis.py` übersetzt Ergebnisse in gemeinsame Python-Datenmodelle.
Die C++-Implementierung wird mit strikter Gleitkommaarithmetik gebaut; Fast-Math
darf nicht zur scheinbaren Beschleunigung eingeschaltet werden.

Die zweite Implementierung ist eine gezielte Leistungsoptimierung für große
Dateien. Änderungen an Modalzuständen, Einheiten, Extrusion, Bögen, Layergrenzen,
Metadaten oder Timing müssen beide Pfade und ihre Parität berücksichtigen. Eine
komplette Neuschreibung des Python-Parsers ist dafür nicht erforderlich.

## Ergebnisse und Fallback

Ein erfolgreiches natives Gesamtergebnis besteht aus Analyse, Metadaten und
Zeitnachweisen. Vorschau-/Infill-Produkte werden nur auf Anfrage gesammelt.
Der Status des Wrappers ist maßgeblich: nicht unterstützte Befehle oder fehlende
native Erweiterung dürfen nicht als erfolgreiches, nur teilweise gefülltes
Ergebnis übernommen werden. Die aufrufende Analyseschicht fällt kontrolliert
auf Python zurück. `fallback_line`, `fallback_command` und Diagnosekennungen
machen den Grund nachvollziehbar. Abbruch ist ein eigener Ausgang und darf
nicht durch einen anschließenden vollständigen Python-Lauf verdeckt werden.

Unterstützung immer am tatsächlichen Parser und an den Fixtures überprüfen;
die Nennung einer Slicerfamilie garantiert nicht die Unterstützung jedes
herstellerspezifischen Befehls. Zeitnachweise aus Metadaten und aus berechneten
Bewegungen haben unterschiedliche Aussagekraft. Kein Pfad verändert G-Code.

## Prüfen und ändern

- `tests/test_native_gcode_analysis.py` vergleicht Python/C++ anhand synthetischer
  Fälle und der Bambu-/Orca-/Anycubic-Fixtures.
- `tests/references/native_analysis_golden.json` ist die eingecheckte Referenz.
  Änderungen müssen durch eine fachlich begründete Semantikänderung erklärt sein;
  Referenzen niemals lediglich an einen fehlerhaften Istwert anpassen.
- `scripts/test_native_analysis_core.py` baut und prüft den eigenständigen C++-Kern.
- `scripts/benchmark_native_analysis.py` misst Leistung getrennt von Korrektheit.
- `COOLING_TOWER_FORCE_PYTHON_ANALYSIS=1` erzwingt für Diagnose den Python-Gesamtpfad.

Bei verändertem Ergebnisformat oder veränderter Bedeutung auch betroffene
Cache-Schemata und Signaturen prüfen. Ein alter Cache darf eine neue Semantik
nicht umgehen. Native Erweiterung und Python-Paket stammen stets aus demselben
Commit; die `.pyd` nicht unabhängig aus einem alten Release übernehmen.
