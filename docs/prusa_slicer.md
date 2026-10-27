# PrusaSlicer-Integration

PrusaSlicer besitzt einen eigenen Adapter, INI-Profilkatalog und Projektbau.
Profilbestätigung, Vorslice, iterative und manuelle Erstellung verwenden
denselben aufgelösten Profilkontext. Installationsdateien, Originalprofile und
Slicer-Konfigurationen werden ausschließlich gelesen. Jeder CLI-Aufruf erhält
ein eigenes Arbeits- und Datenverzeichnis außerhalb der Slicer-Verzeichnisse.

## Module und Datenfluss

- `slicers/prusa_profile_catalog.py` liest Benutzerprofile und aktive bzw.
  mitgelieferte Herstellerkataloge einschließlich Vererbung.
- `slicers/prusa_adapter.py` erzeugt die temporäre vollständige INI, fordert
  textuellen G-Code an und schützt Arbeits-/Ausgabeorte. Vorbereitete native
  Projekte werden mit eingebetteten Einstellungen und `--dont-arrange`
  geslict; externe Profile dürfen diese Einstellungen nicht überlagern.
- `slicers/prusa_joint_project.py` erzeugt ein eigenes natives Zweiobjekt-3MF
  mit `Slic3r_PE.config` und `Slic3r_PE_model.config`. Die vollständigen
  Standard-/Profileinstellungen liefert ein isolierter `--load … --save …`-
  Aufruf der installierten Prusa-Version.
- `slicers/prusa_infill.py` prüft die tatsächliche Turmfüllung. Prusa nennt
  auch dichte rectilineare Füllung `Internal infill`; dieser Name allein ist
  daher kein Beweis für Sparse Infill. Die Prüfung ergänzt eindeutige
  Objektkennzeichnungen um den Abstand ausreichend langer paralleler
  Fülllinien relativ zur ausgegebenen Linienbreite. Nicht belegbare Fälle
  ergeben eine verständliche Fehlermeldung.
- `gcode/prusa_timing.py` enthält die eigene Zeitpolitik; Einzelheiten stehen
  im [Vertrag der nativen Analyse](native_analysis.md).

## Wichtige Projekt- und Vorschauinvarianten

Das gemeinsame Projekt enthält Originalobjekt und Kühlturm mit festen Positionen.
Nur exakt identische STL-Vertexkoordinaten werden zu gemeinsamen 3MF-Indizes
zusammengeführt. Es gibt keine geometrische Vereinfachung. Diese Vernetzung ist
für den nativen Prusa-Import wichtig, obwohl Prusa gewöhnliche STL beim Import
selbst repariert. Die OPC-Dokumente verwenden unpräfixierte Elemente mit
Standardnamespace: namespacepräfixierte Beziehungen werden von der geprüften
Prusa-Version trotz gültigem XML nicht zuverlässig übernommen.

100 % rectilineare Füllung und deaktivierte Turmstützen sind objektspezifisch.
Die gespeicherte Füllung des Originalobjekts bleibt erhalten. Optional simulierte
Objektstützen gehören ausschließlich zum Originalobjekt. Objektkennzeichnungen
werden für das Projekt eingeschaltet und als `M486 S…`/`M486 A…` bzw. passende
Firmwarekennzeichnungen ausgewertet. Maschinenzustände werden auch beim
Ausblenden der Turmwerkzeugpfade vollständig weitergeführt.

Die Start-Purge-Linie vor dem ersten `LAYER_CHANGE` gehört nicht zum
Modellgrundriss. Python und C++ lassen sie deshalb bei Prusas Vorschau und
Platzierungsgrenzen weg; ihre Befehle werden weiterhin für den Modalzustand
gelesen. Dasselbe gilt für die Objektvorschau aus einem gemeinsamen Slice.

Ein Projekt wird erst nach Validierung und erneuter Prüfung der STL-Hashes
atomar übernommen. Fehler, Zeitlimit und Abbruch lassen einen vorhandenen
Zielstand bestehen. Die Regeln für die Phasen der iterativen Methode, Übernahme und Export
stehen zentral im [Quellenablauf](source_workflow.md#tests-und-reale-abnahme).

## Tests und Grenzen des Nachweises

`test_prusa_joint_project` prüft OPC-Format, Positionen, Vertexindizes,
objektspezifische Einstellungen, Firmwarelabels, dichte und sparse Füllung,
Purge-Ausschluss in beiden Analysepfaden sowie Schutz- und Fehlerfälle.
`test_slicer_timing_policies` prüft Zeitgleichungen, Dialekte, Einheiten,
Abbruch, beschränkten Speicher und Python-/C++-Parität einschließlich Bögen.

Die opt-in Tests `test_prusa_slicer_integration` und
`test_user_slicer_regressions` verwenden die installierte Version 2.9.6.
Die vollständige bereitgestellte 98-mm-STL mit 490 Layern durchläuft sechs
Einzelslices und anschließend gemeinsame Slices, Seitenvorschau, STL-/3MF-Export
und erneutes Slicen des exportierten Projekts. Minimalzeiten dürfen beim
unabhängigen Prusa-Wiederslicen höchstens 0,05 s abweichen, da parallele
Polygon-/Bogenberechnungen kleine Pfadunterschiede erzeugen können.
Die ursprünglichen STL-, Profil- und Konfigurationsdateien werden vor/nachher
auf Inhalt und Bestand geprüft. Der separate Installationstest umfasst auch
den manuellen Modus. Es wird kein Bildschirm oder Eingabefokus benötigt.

Formatreferenz: [PrusaSlicers 3MF-Implementierung](https://github.com/prusa3d/PrusaSlicer/blob/version_2.9.6/src/libslic3r/Format/3mf.cpp).
Die Integration besteht aus eigenem Code; weder Prusa-Quellcode noch eine
zusätzliche Laufzeitbibliothek wird eingebettet. Der Slicer bleibt ein separat
installiertes externes Programm; siehe [Dependency-Dokumentation](dependencies.md).
