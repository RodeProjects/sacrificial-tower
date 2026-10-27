# Quellenworkflow: STL vorbereiten und G-Code analysieren

## Inhalt

- [Unterstützte Eingaben](#unterstützte-eingaben)
- [Quellen- und Analysekontext](#quellen--und-analysekontext)
- [STL-Prüfung](#stl-prüfung)
- [Slicer- und Profilbestätigung](#slicer--und-profilbestätigung)
- [Isolierter STL-Pre-Slice](#isolierter-stl-pre-slice)
- [Cache und Invalidierung](#cache-und-invalidierung)
- [Persistenz, Berichte und Datenschutz](#persistenz-berichte-und-datenschutz)
- [Tests und reale Abnahme](#tests-und-reale-abnahme)


## Unterstützte Eingaben

Die GUI besitzt genau einen Datei-/Drop-Bereich und akzeptiert jeweils eine
STL-Datei mit der Endung `.stl`. Vorhandenen G-Code verarbeitet die separate CLI;
er ist keine aktuelle GUI-Eingabe. Die Endung dient nur als erster Routinghinweis.
`recognize_source` liest einen begrenzten Dateianfang
und prüft anschließend das erwartete Format. Leere, beschädigte oder lediglich
umbenannte Dateien werden nicht an die Fachpipeline weitergereicht.

`Andere Datei auswählen`, `STL neu einlesen` und `STL entfernen` invalidieren
sämtliche abhängigen Analyse-, Profil-, Pre-Slice-, Prognose- und
Vorschauergebnisse. Ein
monotoner Request-Bezeichner verhindert, dass ein verspätetes Ergebnis eines
abgebrochenen Hintergrundjobs eine inzwischen neu gewählte Quelle übernimmt.

## Quellen- und Analysekontext

Die gemeinsame Analyse für Postprozessor, iterative und manuelle Erstellung
unterstützt klassische Nähte und Scarf-Nähte. Bei Anycubic Slicer Next,
OrcaSlicer und PrusaSlicer legen die zusammengehörigen Kommentare
`LAYER_CHANGE`, `Z` und `HEIGHT` die nominellen Druckschichten fest; Bambu Studio
verwendet `CHANGE_LAYER`, `Z_HEIGHT` und `LAYER_HEIGHT`. Material ablegende
Z-Rampen innerhalb einer Scarf-Naht erzeugen dadurch keine zusätzlichen Layer.
Die tatsächlichen Bewegungen bleiben in der Vorschau und Bewegungszeitberechnung
erhalten. Anycubics native Zeitmarken müssen weiterhin zur Anzahl und Höhe der
Druckschichten passen. Unbekannte Anfahrzeiten vor dem ersten Materialauftrag
werden als Startbewegungen erfasst; unvollständig berechnete Bewegungen innerhalb
gedruckter Schichten bleiben erkennbar. Dateien ohne passende Slicer-Markierungen
verwenden weiterhin die geometrische Layererkennung.

### Profilauswahl bei erneuter Erkennung

„Slicer und Profile erneut erkennen“ erhält die aktuelle Auswahl des Slicers
und prüft jede Profilrolle getrennt. Eine Auswahl wird wiederhergestellt, wenn
Kennung, Pfad und Inhaltsfingerabdruck einschließlich wirksamer geerbter Werte
übereinstimmen. Geänderte oder nicht mehr gefundene Profile fallen auf die erste
wählbare Option ihrer neu geladenen Liste zurück. Die Profilauswahl muss nach
dem Neuladen erneut bestätigt werden. Diese Sitzungsauswahl hat bei einer
expliziten erneuten Erkennung Vorrang vor gespeicherten aktiven Slicer-Presets.

Die Slicer-Vorbereitung zeigt vier Statuspunkte: Slicererkennung, geladene Profile,
bestätigte Auswahl und erfolgreichen Pre-Slice. Bei ausreichender Textbreite stehen
die ersten beiden links und die nächsten beiden rechts, ohne Trennlinie. Sobald
ein Text in zwei Spalten umbrechen müsste, erscheinen alle vier Punkte untereinander.
Die Analyse mit den bestätigten Profilen läuft weiterhin im Hintergrund und bleibt
Voraussetzung für „Fertig“, besitzt jedoch keinen eigenen sichtbaren Statuspunkt.

Die Vorbereitung erklärt oberhalb der Profilfelder, dass dieselben gespeicherten
globalen Profileinstellungen wie beim tatsächlichen Objektdruck gewählt werden
sollen. Vor „Slicer“ listet ein Hover-Info-Icon die aktiven Integrationen aus
dem Modulregister auf. Der Fußhinweis erklärt die Einzelentwicklung und verweist
bei Slicer-/Druckerproblemen auf „Hilfe & Feedback“ im Burgermenü.
Der Profilfilter besitzt einen eigenen Hover-Hinweis; „Filter deaktivieren
/ alle Profile anzeigen“ lädt die vollständige erkannte Auswahl. Nur das
Kontrollkästchen reagiert auf Mausklick und Hover; der Funktionstext bleibt
passiv. Die übliche Tastaturbedienung des fokussierten Kästchens bleibt erhalten.

`SourceArtifact` beschreibt ausschließlich die unveränderte Benutzereingabe:

- Art, absolut aufgelöster Pfad, Größe und Änderungszeitpunkt,
- SHA-256 der vollständig gelesenen Datei.

`PreparedAnalysisSource` trennt davon den tatsächlich analysierten G-Code.
Er zeigt auf den isoliert erzeugten temporären G-Code und verwendet
`GENERATED_PRESLICE`. Sliceridentität,
Profilfingerabdruck und `PreSliceProvenance` bleiben bis in Vorschau, Export und
technischen Bericht erhalten. Ab diesem Übergang verwendet die GUI einen
`GCodeAnalysisSnapshot`; die CLI nutzt dieselbe G-Code-Analyselogik.

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
Zustimmung aktiviert sie Stützen in ihrer Profilkopie für diese STL. Bei
Anycubic bleiben die anderen Stützenparameter unverändert; für Orca und Prusa
gelten die unten erläuterten Vorgaben zur Stützenart. Abbrechen belässt die
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
`-100` angeboten, sofern Stützen ausdrücklich als deaktiviert erkannt wurden. Abstürze, Zeitlimits,
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

Für OrcaSlicer und PrusaSlicer liegen die Einstellungen simulierter Stützen in
eigenen Integrationsmodulen (`orca_supports.py`, `prusa_supports.py`). Orca nutzt
`tree(auto)` mit kompatiblem Standardstil und deaktivierter unabhängiger
Stützenschichthöhe; Prusa aktiviert automatische Stützen und ab Version 2.6
den Stil `organic`. Diese Vorgaben gelten sowohl für die temporäre
Pre-Slice-Profilkopie als auch für die Quellobjekt-Einstellungen im gemeinsamen
Prüf-/Exportprojekt. Bereits aktivierte Profilstützen bleiben unverändert.
Die Schlüssel und ihre Bedeutung sind in den offiziellen Konfigurationsdefinitionen
von [OrcaSlicer](https://github.com/SoftFever/OrcaSlicer/blob/v2.4.0/src/libslic3r/PrintConfig.cpp)
und [PrusaSlicer](https://github.com/prusa3d/PrusaSlicer/blob/version_2.9.3/src/libslic3r/PrintConfig.cpp)
nachvollziehbar; es wird daraus kein fremder Implementierungscode übernommen.
Die Anycubic-/Bambu-Simulationsvorgaben bleiben ebenfalls unverändert.
Geometriebedingt können trotz Baumstützen einzelne zusätzliche Kontaktlagen
entstehen; tatsächlich gedruckte Schichten werden bei der Zeitbewertung nicht
ausgeblendet. Der Pre-Slice-Adapterstand 4 trennt alte Cacheergebnisse von der
neuen Simulation.

Bei Generierungsfehlern mit einem Hinweis auf die erste Schicht/Auflagefläche
ergänzt die GUI einen fett hervorgehobenen Verweis auf „Stützen für STL-Objekt
simulieren“ und den Button „Funktion jetzt aktivieren“. Das gilt nur bei
bestätigtem STL-Profil mit ausdrücklich erkanntem Stützen-Aus-Wert und
unterstütztem objektspezifischen Projekt. Unbekannte oder bereits aktivierte
Stützeneinstellungen erhalten kein Angebot. Während eines laufenden Auftrags
bleibt der Button gesperrt; beim Klick wird der aktuelle Kontext erneut geprüft.
Er aktiviert die vorhandene Option, ohne automatisch eine Generierung zu starten.
Freie Slicerfehlermeldungen bleiben als Klartext getrennt vom festen HTML-Hinweis.

Die reale Abnahme in `tests/test_source_support_regressions.py` wird mit
`COOLING_TOWER_RUN_SUPPORT_REGRESSION=1` ausdrücklich eingeschaltet. Sie verwendet
die vollständige Test-STL `input/Test-STL (manifold).stl` aus dem Repository
und benötigt die benannten Testprofile in einer installierten Slicer-Umgebung.
Der Dateipfad wird relativ zum Projektverzeichnis bestimmt und muss nach einem
Klon nicht angepasst werden. Die Abnahme prüft iterativen und manuellen
Prüfslice, die Quellobjekt-Metadaten im 3MF, erneutes Slicen des Exports,
Layerzahl/Zeitübereinstimmung und unveränderte Slicerquelldateien.
Standardmäßig beginnt dieser Test ohne Stützen im Vorslice und schaltet die
Objektsimulation erst für die Generierung ein. Mit
`COOLING_TOWER_SUPPORT_PRESLICE_SIMULATED=1` prüft er zusätzlich den Ausgang
mit bereits simulierten Stützen im Vorslice.

### Leere Schichten im Vorslice

Auch ein erfolgreicher Slice kann leere Schichten enthalten, etwa wenn sehr
dünne Querschnitte keine Druckbahn ergeben. `gcode.empty_layers` übernimmt
ausdrückliche Leerlagenwarnungen aus stdout/stderr und prüft den G-Code
zusätzlich unabhängig davon: bestätigte Materialablagen werden mit den
Schicht-/Extrusionshöhenkommentaren des Slicers verglichen. Eindeutige Lücken
und explizite leere Zwischenschichten werden als Hinweis übernommen.
Variable Schichthöhen, bloße Z-Hops, fehlende/ungültige Höhenangaben und
vorgesehene Stützen-/Raft-Kontaktabstände begründen keine geometrische Diagnose.
Die Prüfung untersucht vollständige Ablageebenen; lokal fehlende Flächen bei
anderweitig bedruckter Ebene benötigen eine ausdrückliche Slicerwarnung.
Sie ersetzt keine allgemeine Tragfähigkeits- oder Überhangprüfung.

Die erfolgreiche Analyse bleibt nutzbar und zeigt einen Warnhinweis mit
gegebenenfalls erkannten Höhenbereichen. Er empfiehlt Stützen für das
Originalobjekt. „Stützen simulieren“ aktiviert direkt die bestehende Option
für die iterative und manuelle Turmerstellung, auch vor dem ersten Öffnen
des manuellen Editors; ein neuer Lauf wird damit noch nicht gestartet.
Der grüne Button wird nur bei bestätigtem, unterstütztem Profil mit erkanntem
Stützen-Aus-Wert angeboten. Die Aktion prüft den Quellen-/Profilkontext erneut.
„Weiter ohne Stützen“, Escape und Schließen verwerfen nur den Dialog und
behalten alle Einstellungen bei. Die Buttons verwenden die vorhandenen
hellgrünen/hellroten Verläufe einschließlich Hover-/Druckzuständen. Bereits
aktivierte/simulierte Stützen führen stattdessen zum Hinweis, ihre Abdeckung
im Slicer zu prüfen. Bei einem fehlgeschlagenen Slice wird die Leerlagendiagnose
in der Fehleranzeige erklärt; der vorhandene Wiederholungsdialog bleibt nutzbar.

Geometrische Evidenz wird auch bei Cachetreffern aus dem G-Code rekonstruiert.
Slices mit ausdrücklicher CLI-Leerlagenwarnung werden nicht gecacht, damit eine
nur im Prozessprotokoll enthaltene Warnung bei späterem Laden nicht verloren
geht. Adapterstand 5 trennt frühere Cacheeinträge von dieser Prüfung.
Regression: `test_empty_layers`, `test_support_simulation`. Reale Kontrolle
am 20.10.2026 mit `input/Test-STL (manifold).stl` und PrusaSlicer: ohne Stützen
Warnung bei erfolgreichem Slice, mit simulierten Stützen keine Warnung;
625 überwachte Quelldateien einschließlich STL und Slicerprofilen unverändert.
Die Kommentarformate wurden anhand des
[PrusaSlicer-G-Code-Generators](https://github.com/prusa3d/PrusaSlicer/blob/version_2.9.3/src/libslic3r/GCode.cpp)
geprüft; die Erkennung ist eigenständig implementiert.

### Temporärer manueller Prüfslice

Der manuelle Prüfslice liefert die gemessenen Layerzeiten und wird ausschließlich
im eigenen temporären Arbeitsbereich gehalten. Der Export enthält STL, ggf.
3MF, Berichte und Diagnosen, jedoch keine zusätzliche `verification.gcode`.
Nach erfolgreichem Export wird die temporäre Prüf-G-Code-Datei gelöscht.
Messwerte und SHA-256 bleiben im technischen Bericht erhalten. Wiederholte
Exporte benötigen keinen neuen Slice und prüfen weiterhin Quellen, Profile,
STL und Projekt. Bei fehlgeschlagenem Export bleibt die temporäre Prüfdatei
für einen erneuten Versuch erhalten; das Verwerfen des Ergebnisses räumt
den gesamten temporären Auftrag auf.

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

Bei geladener Datei wird die Box anhand der tatsächlichen Breite einschließlich
Pfadumbrüchen auf ihre Inhaltshöhe begrenzt. Der Innenabstand bleibt ringsum
gleich; alte Größen der leeren Ansicht dürfen weder die Faktenzeilen noch die
Blöcke rund um die Trennlinie auseinanderziehen. Die Fortschrittsanzeige und
neu hinzukommende Prüfergebnisse behalten ihren regulären Platz im Ablauf.
Dateiauswahl und Prüfergebnis werden einschließlich ihrer Layoutanpassung als
gemeinsame Darstellungsänderung veröffentlicht. Vorübergehende native
Neuzeichnungen dürfen keine Mischung aus alten Dateizeilen und neuer
Akzeptanzmeldung zeigen. Verschachtelung und Fehlerpfade stellen den
vorherigen Zustand der Zeichenfreigabe wieder her.
Abgeschlossene STL-Prüfaufträge nehmen keine weiteren Fortschrittsmeldungen
an. Layoutarbeit steht am Ende der letzten Fortschrittsaktualisierung, damit
ein dabei verschachtelt zugestelltes Prüfergebnis anschließend nicht wieder
auf „wird geprüft“ zurückgesetzt wird.

Die Prüfergebnisse verwenden kompakte Meldungen mit jeweils eigener Überschrift
und einem Status-Icon. Nur diese tragen einen dezenten Farbakzent; die
Erklärungstexte bleiben neutral und erhalten weder farbige Flächen noch Rahmen.
Geringfügige lokale Überschneidungen erscheinen als ergänzender Geometriehinweis
mit Info-Symbol. Bei eingeklappten technischen Details steht die erste Überschrift
links neben dem Detail-Link, während ihr Text die gesamte Breite darunter nutzt.
Beim Aufklappen rückt die vollständige Meldung unter die technischen Details;
beim Einklappen kehrt die Überschrift in die gemeinsame Zeile zurück.

## Slicer- und Profilbestätigung

Die Dateiübergabe bleibt von der Slicer-Vorbereitung unabhängig. Eine vorläufige
Installationssuche ist in einem abbrechbaren Hilfsprozess begrenzt; Profile
werden in der normalen Anwendung erst beim Öffnen der Slicer-Einstellungen
ausgewertet. Fehler dieser Verarbeitung erscheinen ausschließlich in Schritt 2.
Auch eine hängende Slicer-Verarbeitung darf weder die STL-Prüfung noch das
kontrollierte Schließen blockieren. Die technischen Grenzen und Tests stehen
unter [Slicer-Erkennung und Fehlergrenzen](slicer_detection_modules.md#laufzeitfreigabe-und-fehlergrenzen).

Die GUI verwendet einen quellenneutralen `ProfileMatchingContext`.
Der Fachdienst kann zusätzlich Metadaten vorhandener G-Code-Analysen auswerten;
daraus folgt kein G-Code-Import in der GUI. Für die STL-Vorbereitung werden ausschließlich
verifizierte Installationen, aktives beziehungsweise zuletzt bestätigtes
Preset und das lesend inventarisierte Profilangebot verwendet. Es wird kein
leerer oder künstlicher G-Code-Snapshot erzeugt.

STL erlaubt nur Volladapter mit bestätigter CLI-Slice-Fähigkeit. Maschine,
Prozess und mindestens ein Filament müssen kompatibel und ausgewählt sein. Die
Bestätigung bindet Profil-IDs, effektive Werte, Slicerpfad und -version an Hash,
Größe, Änderungszeitpunkt und Pfad der konkreten Quelle. Jede Änderung hebt die
Bestätigung und alle davon abhängigen Resultate auf.

Bei der Slicer-Vorauswahl hat die zuletzt im Programm explizit gewählte,
weiterhin verfügbare Installation Vorrang. Ohne gültige gespeicherte Auswahl
folgt der anhand lokaler Nutzungsmarker zuletzt verwendete Slicer; fehlt auch
diese Information, wird der erste verwendbare Eintrag der Liste ausgewählt.
Die Kennzeichnung „zuletzt verwendet“ beschreibt weiterhin ausschließlich die
externen Nutzungsmarker, unabhängig von der tatsächlich vorausgewählten Installation.

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
Pre-Slice-Zeitpunkt, Dauer und Cache-Status. Dieser lokale technische Laufbericht
ist vom freiwilligen Support-ZIP zu unterscheiden: Ein Supportpaket übernimmt
nur ausdrücklich freigegebene Felder und technische Werte, keine Originalprofile,
Rohlogs oder freien Fehlermeldungen. Eine Problembeschreibung wird ausschließlich
direkt im GitHub-Issue eingegeben, nicht im Paket gespeichert.
Details: [Support und Diagnose](support.md). Es gibt keine automatische
Netzwerkübertragung des Modells oder Supportpakets.

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

Für unterstützte native Projekte, einschließlich PrusaSlicer, führt die
iterative Methode zuerst die eingestellte Anzahl isolierter Turmslices und danach die
gemeinsamen Objekt-/Turmslices aus. Eine vorzeitige Übernahme ist erst nach
mindestens drei erfolgreich geprüften gemeinsamen Slices möglich; höhere
konfigurierte Mindestzahlen bleiben verbindlich. Nach jedem gemeinsamen Slice
wird die Seitenvorschau aktualisiert. Der beste geprüfte gemeinsame Stand bleibt
bei Zielerreichung, zulässiger Übernahme oder späterer Stagnation verfügbar.
Ein ausschließlich isolierter Turmslice darf bei angefordertem gemeinsamen
STL-Projekt keine erfolgreiche gemeinsame Fertigstellung vortäuschen.
Fehlende native Projektunterstützung wird verständlich gemeldet. Zu einem
erfolgreich gemeinsam geprüften STL-Ergebnis gehört das geprüfte 3MF im Export.

Die normalen Tests verwenden synthetische STL-Fälle, die bereitgestellten
Regressionen, Fake-Slicer sowie temporäre Verzeichnisse. Der reale
Anycubic-Slicer-Test ist bewusst opt-in:

```powershell
$env:COOLING_TOWER_RUN_REAL_SLICER_TESTS="1"
python -m unittest tests.test_real_source_preslice.RealSourcePreSliceAnycubicTests -v
```

Er verwendet eine deterministische, streng validierte Würfel-STL. Die
Systemprofile für den kontrollierten Referenzlauf und die lokal ausgewählten
Benutzerprofile für die GUI-Regressionsfälle werden in
`tests/slicer_acceptance.local.json` ausgewählt. Es werden keine persönlichen
Profile mit dem Projekt verteilt. Fehlen Installation oder benötigte
Profilangaben, überspringt der jeweilige optionale Test sich mit einer klaren
Meldung. Profilquellen bleiben unverändert; temporäre Arbeitskopien liegen
außerhalb der Slicer-Verzeichnisse. Geprüft werden kontrollierter Referenzlauf,
Cache-Wiederverwendung, Abbruch, Bereinigung sowie byteidentische Quelle und
Profile. Die gemeinsame Einrichtung steht unter
[optionale Slicer-Abnahmetests](slicer_acceptance_tests.md).
