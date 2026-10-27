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

## Unabhängige Orca- und Prusa-Zeitpolitiken

Nur eine eindeutige Herstellerzeile und ein gespeicherter `gcode_flavor`
aktivieren die betreffende Politik. Die begrenzte Footer-Lesung akzeptiert
auch CRLF und übernimmt ausschließlich endliche, nichtnegative Maschinenlimits.
Andere Hersteller und Dateien ohne ausreichende Dialektinformation behalten
ihren bestehenden Analysepfad.
Die eigenen Orca-Regeln sind für `marlin`, `marlin2`, `klipper` und
`reprapfirmware` aktiviert, die Prusa-Regeln für `marlin` und `marlin2`.
Andere Dialekte behalten ihren bisherigen allgemeinen Pfad.

`gcode/orca_timing.py` berücksichtigt Orcas Maschinenlimits, ungleiche
Geschwindigkeiten am Übergang und die bei Marlin 2 aus `M205 J` abgeleiteten
Jerk-Grenzen. Klassische Jerk-Werte bleiben separat erhalten und werden bei
abgeschalteter Junction Deviation wieder verwendet. Klippers
`SET_VELOCITY_LIMIT` berücksichtigt XY-Jerk, XY-Geschwindigkeit und
Druck-/Travelbeschleunigung nach Orcas Viewerregeln, ohne dabei unbeabsichtigt
die Retraktionsbeschleunigung zu überschreiben. `gcode/prusa_timing.py`
verwendet dagegen eine geometrische Junction-Deviation-Gleichung mit
vierdimensionalem Richtungsvektor einschließlich Extruder und den jeweiligen
Achsbeschleunigungen. Die Modelle sind nicht austauschbar.

Beide verwenden begrenzte Rückwärts-/Vorwärtsdurchläufe mit 256 Bewegungen
und 64 verbleibenden Lookahead-Bewegungen. Die gemeinsame numerische Mechanik
liegt in `window_planner.py`, die fachlichen Übergangsregeln bleiben in den
eigenen Modulen. Bambu und die allgemeine Zeitplanung verwenden weiterhin ihre
bisherigen Durchläufe. Die C++-Entsprechungen liegen in `orca_timing.hpp` und
`prusa_timing.hpp`; die native Engine trägt Version 6. Eine ältere Erweiterung
darf für diese geänderten Semantiken keinen vermeintlich erfolgreichen
Prusa-Pfad liefern. Der Analyseparserstand 20 verwirft bisherige Analyse- und
Vorslice-Caches; das Schema persistierter Benutzereinstellungen ändert sich nicht.

Die expliziten Schichtmarkierungen der unterstützten Slicer halten auch
Scarf-Z-Rampen in ihrer nominellen Druckschicht. Engine 4 verarbeitet beide
Markierungsformate; ältere Erweiterungen fallen für das Prusa-/Orca-/Anycubic-
Format auf Python zurück. Die gemeinsame Zuordnung und die Abgrenzung von
Startbewegungen sind im [Quellenworkflow](source_workflow.md#quellen--und-analysekontext)
beschrieben. Native Zeitmarken werden weiterhin unabhängig auf passende
Schichtanzahl und Z-Höhen geprüft. Engine 5 ergänzt begrenzte Seams-Punktdaten
im Vorschauprodukt. Ältere Erweiterungen fallen bei angefordertem
Vorschauprodukt auf Python zurück, damit Nahtmarkierungen erhalten bleiben.
Engine 6 beschränkt die Seams-Punkte auf explizit als äußere Wand bezeichnete
Pfade. Die Vorschau verwendet dafür mindestens diese Engine; ältere
Erweiterungen liefern die Punkte über den Python-Fallback.

Die Schichtzeiten bleiben Bewegungsprognosen. Rundung, Firmwareabläufe und
die native Diskretisierung von Kreisbögen können geringe Unterschiede zum
Slicer ergeben. Prusas kurze Bogenübergänge verwenden eine eigene exakte
Winkelfunktion statt der dortigen Polynomapproximation. Der Wiederimporttest
prüft zusätzlich, dass das exportierte 3MF dieselben geprüften Einstellungen,
Objekte und Positionen enthält. Eine Übereinstimmung zwischen Python und C++
allein ist kein unabhängiger Slicer-Zeitnachweis.

Fachliche Referenzen: [OrcaSlicer 2.4.2](https://github.com/OrcaSlicer/OrcaSlicer/blob/v2.4.2/src/libslic3r/GCode/GCodeProcessor.cpp)
und [PrusaSlicer 2.9.6](https://github.com/prusa3d/PrusaSlicer/blob/version_2.9.6/src/libslic3r/GCode/GCodeProcessor.cpp).
Es wird kein fremder Implementierungscode übernommen.
