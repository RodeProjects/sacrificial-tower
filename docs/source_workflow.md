# Quellenworkflow für STL und G-Code

## Unterstützte Eingaben

Die GUI besitzt genau einen Datei-/Drop-Bereich und akzeptiert jeweils eine
Datei mit der Endung `.gcode` oder `.stl`. Die Endung dient nur als erster
Routinghinweis. `SourceRecognitionService` liest einen begrenzten Dateianfang
und prüft anschließend das erwartete Format. Leere, beschädigte oder lediglich
umbenannte Dateien werden nicht an die Fachpipeline weitergereicht.

`Andere Datei auswählen`, `G-Code neu einlesen` beziehungsweise `STL neu
einlesen` und `G-Code entfernen` beziehungsweise `STL entfernen` invalidieren
sämtliche abhängigen Analyse-, Profil-, Pre-Slice-, Prognose- und
Vorschauergebnisse. Ein
monotoner Request-Bezeichner verhindert, dass ein verspätetes Ergebnis eines
abgebrochenen Hintergrundjobs eine inzwischen neu gewählte Quelle übernimmt.

## Quellen- und Analysekontext

`SourceArtifact` beschreibt ausschließlich die unveränderte Benutzereingabe:

- Art, absolut aufgelöster Pfad, Größe und Änderungszeitpunkt,
- SHA-256 der vollständig gelesenen Datei.

`PreparedAnalysisSource` trennt davon den tatsächlich analysierten G-Code. Bei
einem Benutzer-G-Code zeigt er auf dieselbe Datei und verwendet
`USER_SUPPLIED`. Bei einer STL zeigt er auf den isoliert erzeugten temporären
G-Code und verwendet `GENERATED_PRESLICE`. Sliceridentität,
Profilfingerabdruck und `PreSliceProvenance` bleiben bis in Vorschau, Export und
technischen Bericht erhalten. Ab diesem Übergang arbeiten beide Eingabewege
mit demselben `GCodeAnalysisSnapshot`.

## STL-Prüfung

Ein geschlossenes (manifold) Netz garantiert keine mit jedem Profil druckbare
erste Schicht. Die Datei `input/Test-STL (manifold).stl` steht auf einer dünnen
Spitze: bei Z=0,1 mm misst ihr Querschnitt nur etwa 0,50 × 0,29 mm. Mit dem
Anycubic-Profil des gemeldeten Fehlers (0,4-mm-Düse, erste Linienbreite 0,5 mm,
Elefantenfußkompensation 0,1 mm, Stützen aus) entsteht keine erste Druckbahn.
Anycubic Slicer Next meldet dabei lediglich `Errors` und Exitcode `-100`.
Die Fehleranzeige verweist deshalb auf Auflagefläche und Stützen, statt einen
Windows-Absturz zu behaupten. Ein Kontrollslice mit Stützen war erfolgreich;
auch die Testdatei mit abrupten Flächenänderungen läuft ohne Stützen durch.
Die Anwendung fragt bei passenden Slicerfehlern in einem zentrierten Popup,
ob der Pre-Slice mit simulierten Stützen wiederholt werden soll. Erst nach
Zustimmung aktiviert sie Stützen in ihrer Profilkopie für diese STL; alle
anderen Stützenparameter bleiben unverändert. Abbrechen belässt die
fehlgeschlagene Analyse unverändert. Original-STL und Slicerprofile bleiben
immer schreibgeschützt. Untersuchung: 16.09.2026.
Der [Anycubic-Quellcode](https://github.com/ANYCUBIC-3D/AnycubicSlicerNext/blob/main/src/libslic3r/GCode.cpp)
erklärt die Ablehnung einer ersten Schicht ohne Extrusion in
`GCode::collect_layers_to_print`.

Bambu Studio meldet mit Exitcode `-61` eine Unverträglichkeit zwischen dem
wirksamen Filamentprofil und Druckbett-Typ; die [offizielle CLI-Codedefinition](https://github.com/bambulab/BambuStudio/blob/master/src/libslic3r/Utils.hpp)
bezeichnet ihn als `CLI_FILAMENT_NOT_MATCH_BED_TYPE`. Die
[Bambu-Prüfung](https://github.com/bambulab/BambuStudio/blob/master/src/libslic3r/Print.cpp)
löst ihn aus, wenn die im Profil hinterlegte Betttemperatur für den gewählten
Druckbett-Typ `0 °C` beträgt. Die Anwendung zeigt dafür eine konkrete
Handlungsanweisung an. Eine gültige, geschlossene STL oder ein
Neustart nach einer Programmaktualisierung erklärt diesen Code nicht. Der
Diagnosebericht ST-20260923-213527-B19F9B enthält diesen Code beim Bambu-
Vorslice, aber keine STL oder konkreten Profil- und Druckbettwerte; die genaue
unverträgliche Kombination lässt sich daraus nicht bestimmen.

### Zustimmung und Weitergabe simulierter Stützen

`SourcePreSliceError.support_simulation_available` beschreibt ein mögliches
Wiederherstellungsangebot, keine sichere Fehlerdiagnose. Es wird bei einem
Hinweis auf eine leere erste Schicht oder Anycubics unspezifischem Slicingfehler
`-100` angeboten, sofern Stützen noch deaktiviert sind. Abstürze, Zeitlimits,
Abbrüche und ein bereits mit Simulation fehlgeschlagener Versuch lösen das
Angebot nicht aus. Der vorhandene Thread wird vor dem erneuten Start freigegeben.
Eine veraltete Zustimmung nach Quellen-/Profilwechsel oder beim Beenden wird verworfen.

Alternativ lädt „Ich habe die Stützen selbst aktiviert und gespeichert“ den gesamten
Profilkatalog des gewählten Slicers erneut von den Quelldateien. Die bisherigen
Profile werden anhand ihrer Kennung und ihres Pfads wieder vorausgewählt,
sofern vorhanden. Alte Bestätigungen und Fehlerhinweise werden verworfen;
der Benutzer muss die frisch eingelesenen Profile erneut bestätigen, bevor
ein weiterer Pre-Slice startet. Auch der Profilimport wartet auf die Freigabe
des vorherigen Pre-Slice-Prozesses.

Die Simulation ist auf den aktuellen Auftrag begrenzt und wird nicht als
Benutzervoreinstellung gespeichert. Ihr Status gehört zum Pre-Slice-Cachekey
und bleibt auch bei Cachetreffern im Ergebnis erhalten. Der Vorschauauftrag
übernimmt ihn in `EffectiveProfile.supports_simulated` und seine Signatur.
`build_calibration_profile` aktiviert dadurch Stützen auch in allen folgenden
temporären Profilkopien und beim Erzeugen des gemeinsamen 3MF-Projekts.
Die ursprüngliche Profilbestätigung und Überwachung der Quelldateien bleiben
auf die unveränderten Originale bezogen. Beim Laden einer anderen Quelle
oder Profilauswahl wird das Pre-Slice-Ergebnis einschließlich Simulation verworfen.

Das abschließende Zusammenfassungsfenster und die Exportberichte kennzeichnen
simulierte Stützen. Nur eine tatsächlich exportierte 3MF übernimmt deren
Aktivierung automatisch. Bei STL-Import oder Verwendung eines anderen Projekts
muss der Benutzer sie ggf. selbst aktivieren; das gilt ebenso für simulierte
100-%-Turmfüllung. Eine fehlende 3MF wird im Hinweis ausdrücklich berücksichtigt.

Das Zusammenfassungsfenster listet die im exportierten 3MF simulierten Eigenschaften
einzeln in Grün (aktivierte Stützen und/oder 100-%-Turmfüllung). Grundlage ist der
Exportauftrag, nicht der spätere Zustand der Einstellungsfelder. Ohne exportiertes
3MF erscheint keine Liste automatisch übernommener Simulationseinstellungen.

Die STL-Prüfung läuft lesend und abbrechbar in einem Hintergrundjob. Binäre und
ASCII-STL werden ohne automatische Reparatur oder Normalisierung verarbeitet.
Vor der Freigabe werden insbesondere geprüft:

- vollständiges Format, Dateigröße und deklarierte Dreieckszahl,
- endliche Koordinaten und Normalen innerhalb der Ressourcenlimits,
- degenerierte, kollabierte, doppelte oder widersprüchliche Flächen,
- genau zwei entgegengesetzt ausgerichtete Flächen je geometrischer Kante,
- geschlossene Komponenten mit jeweils positivem endlichem Volumen,
- eindeutige Flächenüberschneidungen zwischen und innerhalb von Komponenten.

Für die Topologie werden geometrisch identische Vertices mit einer festen
Toleranz von `1e-6 mm` zugeordnet. Das verändert weder Quelldaten noch die dem
Slicer übergebene STL. Die Schnittprüfung ist durch ein Kandidatenlimit
begrenzt. Ein überschrittenes Sicherheitslimit blockiert die Quelle, anstatt
eine unvollständige Prüfung als Erfolg zu behandeln. Überschneidungen zwischen
getrennten Komponenten sowie tiefe, großflächige oder zu zahlreiche
Überschneidungen bleiben strikt blockierend. Nur eine begrenzte Anzahl flacher
lokaler Überschneidungen innerhalb derselben ansonsten topologisch sauberen
Komponente wird als Warnhinweis klassifiziert. Dafür gelten zugleich ein
absolutes Eindringtiefenlimit von `0,1 mm`, ein modellrelatives Limit von
`0,1 %` der Modell-Diagonale und ein Mengenlimit von `2048` Paaren;
maßgeblich ist jeweils die strengere räumliche Grenze. Der Slicer-G-Code wird
danach weiterhin inhaltlich und gegen die bestätigten Profile validiert.

Die beiden vom Benutzer bereitgestellten Dateien liegen byteidentisch unter
`tests/fixtures/stl/`. Die Datei `test_model_non_manifold.stl` deckt offene und
nicht-manifold Kanten, degenerierte und doppelte Flächen sowie inkonsistente
Ausrichtung ab. `test_model_manifold.stl` ist kantenmanifold und geschlossen.
Ihre ausschließlich flachen lokalen Flächenüberschneidungen werden analog zur
praktischen Slicerbewertung als nicht blockierender Geometriehinweis behandelt.
Damit decken die beiden Originaldateien sowohl den strikt abzuweisenden als
auch den kontrolliert tolerierbaren Grenzfall dauerhaft ab.

Schlägt die STL-Prüfung fehl, bleibt die abgelehnte Quelle mit verständlicher
Fehlermeldung, optionalen technischen Details und den vorhandenen Aktionen
sichtbar. `Andere Datei auswählen` ersetzt sie, `STL neu einlesen` prüft sie
vollständig neu und `STL entfernen` stellt als einzige Aktion wieder die leere
Startübersicht mit Drop-Bereich her. Dieselben drei Aktionen stehen auch nach
erfolgreicher Prüfung zur Verfügung.

## Slicer- und Profilbestätigung

Beide Eingabearten verwenden einen gemeinsamen, quellenneutralen
`ProfileMatchingContext`. Für G-Code stehen eingebettete Metadaten und
zeitkritische Werte als Evidenz zur Verfügung. Für STL werden ausschließlich
verifizierte Installationen, aktives beziehungsweise zuletzt bestätigtes
Preset und das lesend inventarisierte Profilangebot verwendet. Es wird kein
leerer oder künstlicher G-Code-Snapshot erzeugt.

STL erlaubt nur Volladapter mit bestätigter CLI-Slice-Fähigkeit. Maschine,
Prozess und mindestens ein Filament müssen kompatibel und ausgewählt sein. Die
Bestätigung bindet Profil-IDs, effektive Werte, Slicerpfad und -version an Hash,
Größe, Änderungszeitpunkt und Pfad der konkreten Quelle. Jede Änderung hebt die
Bestätigung und alle davon abhängigen Resultate auf.

Explizit ausgewählte oder bestätigte Maschinen-, Prozess- und Filamentprofile
werden je konkreter Slicerinstallation in `slicer_settings.json` gespeichert.
Beim nächsten Start wird zuerst der bisherige Profilpfad und nach einem
Verschieben durch ein Slicer-Update die stabile Profil-ID gesucht. Fehlt eine
Rolle, verwendet das Matching dafür die aktuelle Vorauswahl. Ist ein nur noch
teilweise erhaltenes gespeichertes Paket inzwischen inkompatibel, blockiert es
den Workflow nicht, sondern wird einmalig durch die aktuelle sichere
Standardzuordnung ersetzt. Gespeicherte oder manuell gewählte Slicerpfade
werden im Header nicht als `automatisch erkannt` bezeichnet.

## Isolierter STL-Pre-Slice

`SourcePreSliceService` startet erst nach gültiger STL-Prüfung und expliziter
Bestätigung. Er arbeitet ausschließlich in einem markierten Verzeichnis
`cooling_tower_source_preslice_*` unter dem programmeigenen temporären Bereich:

1. Quelle, Slicer sowie ausgewählte und geerbte Profilquellen werden unmittelbar
   vor dem Start erneut gegen ihre bestätigten Fingerabdrücke geprüft.
2. Das Adapter-Backend kopiert die STL und erforderliche temporäre Daten in
   seinen isolierten Arbeitsbereich. GUI-erzeugte Presets der Orca-/Bambu-/
   Anycubic-Familie können ihren Konfigurationstyp nur aus dem Slicerkatalog
   erben. Für den eigenständigen CLI-Lauf erzeugt der Adapter deshalb
   typisierte JSON-Kopien unter `effective_profiles/`. Slicerprofile selbst
   werden ausschließlich gelesen und niemals als CLI-Ausgabeziel verwendet.
3. Der Prozess wird ohne Shell mit Zeitlimit, begrenzter Ausgabe und
   Prozessbaum-Abbruch gestartet.
4. Exitcode, Ausgabepfad, G-Code-Inhalt, druckbare Layer sowie Slicer- und
   Profilmetadaten werden geprüft.
5. Erst danach entsteht ein `PreparedAnalysisSource`; Fehler und Abbruch
   bereinigen unvollständige Arbeitsdaten.

Die G-Code-Analyse sammelt zugleich die Druckbahnen für die 3D-Vorschau des
Originalobjekts. Bis zu einer erfolgreichen Turmgenerierung und nach deren
Abbruch bleibt diese Objektvorschau mit allen Ansichtsbuttons sichtbar.

Ausgabe- und Cachepfade dürfen weder in einem Slicerverzeichnis noch direkt
neben der Benutzer-STL liegen. Hashprüfungen vor und nach dem Vorgang sichern
die Unverändertheit der Quelle und aller verwendeten Profile ab. Technische
Fehlerdetails enthalten begrenzte Prozessausgabe, aber keine STL-Inhalte.

## Cache und Invalidierung

Der optionale Pre-Slice-Cache wird über einen schema-versionierten,
prüfsummenbewehrten `VersionedJsonStore` atomar verwaltet. Cache-Artefakte
werden nur aus sicheren, intern erzeugten Dateinamen geladen. Beschädigte,
zukünftige oder pfadmanipulierte Indizes werden weder verwendet noch
automatisch überschrieben.

Der Schlüssel berücksichtigt mindestens:

- STL-SHA-256,
- Adapterkennung und Pre-Slice-Adapterversion,
- Slicerpfad und Slicerversion,
- Maschinen-, Prozess- und Filamentprofil-IDs,
- Fingerabdruck aller effektiven Werte und des Profilinventars,
- Pfad, Größe, Änderungszeit und SHA-256 jeder ausgewählten oder geerbten
  Profilquelle,
- G-Code-Parser-Version.

Ein Treffer wird in ein neues temporäres Arbeitsverzeichnis kopiert und erneut
analysiert sowie gegen Quelle und bestätigte Metadaten geprüft. Fehlende oder
veränderte G-Codes gelten als Cache-Miss. Cache-Fehler dürfen einen ansonsten
vollständig verifizierten neuen Pre-Slice nicht nachträglich fehlschlagen
lassen.

## Persistenz, Berichte und Datenschutz

Neue persistierte Formate verwenden `VersionedJsonStore`, schrittweise
Migrationen, Sicherung vor migrationsbedingtem Umschreiben und atomisches
Speichern. Unbekannte neuere, beschädigte oder extern veränderte Dateien werden
nicht überschrieben.

Der technische Laufbericht enthält Quellenart und -hash, Herkunft und Hash des
Analyse-G-Codes, Slicer und Version, bestätigte Profile, Profilfingerabdruck,
Pre-Slice-Zeitpunkt, Dauer und Cache-Status. Supportberichte redigieren Pfade
und übernehmen weder STL-Inhalte noch vollständige Prozessausgaben. Es findet
keine Netzwerkübertragung des Modells statt.

## Tests und reale Abnahme

Beide Generierungsmethoden lesen denselben bestätigten `SourceArtifact`-,
`PreparedAnalysisSource`- und Profilkontext. Ein Quellen-/Profilwechsel verwirft
auch den quellengebundenen manuellen Entwurf und dessen geprüfte Ergebnisse.
Wiederverwendbare manuelle Einstellungen bleiben in einer eigenen Datei erhalten.
Es gibt keinen zweiten Vorbereitungsworkflow. Die aktuelle GUI nimmt STL als
Originalquelle an; vorhandene Analyse-G-Code-Snapshots lassen sich im manuellen
Dienst separat bewerten. Ohne verifizierte Original-STL beziehungsweise native
Projektfähigkeit entsteht ausschließlich eine deutlich gekennzeichnete
Zeitprognose, niemals eine behauptete gemeinsame Verifikation.
Ein erfolgreich geprüftes natives gemeinsames 3MF bewahrt exakt die geslicte
Form und feste Anordnung. Einzelheiten stehen im [manuellen Editor](manual_editor.md).

Die normalen Tests verwenden synthetische STL-Fälle, die bereitgestellten
Regressionen, Fake-Slicer sowie temporäre Verzeichnisse. Der reale
Anycubic-Slicer-Test ist bewusst opt-in:

```powershell
$env:COOLING_TOWER_RUN_REAL_SLICER_TESTS="1"
python -m unittest tests.test_real_source_preslice.RealSourcePreSliceAnycubicTests -v
```

Er verwendet eine deterministische, streng validierte Würfel-STL und die
installierten Kobra-3-V2-/Standard-/PLA-Profile. Zusätzlich wird die
bereitgestellte Manifold-Regressions-STL mit den in der Anycubic-GUI erzeugten
Benutzerpresets vollständig über Profilmatching, Bestätigung, Pre-Slice,
G-Code-Analyse und Metadatenabgleich geführt. Geprüft werden außerdem ein
kontrollierter Referenzlauf, Cache-Wiederverwendung, Abbruch, Bereinigung sowie
byteidentische Quelle und Profile.
