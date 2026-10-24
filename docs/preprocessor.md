# Präprozessor: Abkühlpausen und hohler Abstreifturm

## Bedienung

Nach STL-Auswahl, Slicer-/Profilbestätigung und Pre-Slice steht neben
**Automatisch** und **Manuell** die dritte Methode **Präprozessor** bereit.
Unterstützt werden Anycubic Slicer Next, Bambu Studio, OrcaSlicer und PrusaSlicer.
Dieser Modus bearbeitet den bereits vorhandenen Pre-Slice; eine Änderung der
Turmeinstellungen startet keinen weiteren Slicerlauf.

**G-Code und Vorschau erzeugen** startet die Berechnung ausdrücklich.
Einstellungsänderungen verwerfen das alte Ergebnis und starten keine Berechnung.
Links stehen die Einstellungen, rechts die Vorschau; schmale Fenster stapeln
die Bereiche wie im automatischen Modus. Alle Einstellungen besitzen links
ein Hover-Hinweis-Icon mit kurzer Erklärung und rechts einen Reset im gemeinsamen
Design. Bei Automatikzeilen steht der Reset rechts neben **Automatisch**.
Turmhöhe, Schaftdurchmesser, Standfußbreite, Turm- und Warteposition besitzen jeweils eine
eigene Automatik. Deaktivieren übernimmt den zuletzt berechneten Wert zur
manuellen Bearbeitung. Die Einstellungen bleiben während der Sitzung erhalten;
sie werden derzeit nicht als globale Benutzervorgaben gespeichert.

**Erweiterte Einstellungen anzeigen** öffnet Wandlinien, Voll-/Hohlbauweise,
Randabstand, Turmdruck-/Fahrgeschwindigkeit, Rückzug, Rückzugsgeschwindigkeit,
Sicherheitshub, Warteabstand und zusätzliche Prime-Menge. Standard ist ein hohler Turm mit
zwei Wandlinien und zwei geschlossenen Bodenlagen. Bei geänderten Einstellungen
wird das alte abgeleitete Ergebnis verworfen; die unveränderte Pre-Slice-Datei
bleibt die Ausgangsbasis. Der Methodenwechsel erhält die jeweilige Vorschau.
Ein Quellen-/Profilwechsel verwirft sie.

Der geteilte Footer bleibt außerhalb des scrollbaren Inhalts erreichbar.
Links stehen Status und **Standardwerte**; rechts der blaue Erzeugen-Button.
Nach erfolgreicher Erzeugung steht der grüne Export-Button ganz rechts und
verschiebt den Erzeugen-Button nach links. **Abbrechen** erscheint nur bei
laufender Erzeugung. In schmalen Fenstern werden auch die Footerbereiche gestapelt.

**G-Code exportieren** speichert die geprüfte Vorschau als `.gcode`. Dieser
Modus benötigt keinen erneuten Slice und exportiert kein gemeinsames 3MF/STL.
Kritische Fehler erscheinen sichtbar als **Export gesperrt** und entfernen die
Exportberechtigung. Auch veränderte oder fehlende Original-/Ergebnisdateien
blockieren den Export. Vorhandene Exporte werden nur nach der Bestätigung im
Speicherdialog ersetzt. Die Datei wird zunächst vollständig in eine temporäre
Nachbardatei geschrieben, geprüft und anschließend atomar übernommen.

## Geometrie und Platzierung

Der Turm stellt eine Abstreiffläche bereit. Seine Querschnittsfläche wird nicht
zum Ausgleichen der Schichtzeit dynamisch kalibriert.

- Die automatische Höhe umfasst die Originalschichten bis zum letzten
  Schichtzeitdefizit und überbrückt ausreichende Zwischenschichten. Oberhalb
  davon entsteht kein Turm. Eine manuelle Höhe wird auf vorhandene Schichten
  abgerundet; sie darf den nötigen Bereich nicht unterschreiten und die
  Modellhöhe nicht überschreiten. Ein Turmlayer kann selbst bereits genügend
  Zeit erzeugen; dann entfällt dort die eigentliche Wartezeit.
- Der automatische Schaftdurchmesser beträgt `max(6 mm, 0,10 × Turmhöhe)`.
  Bei breiten Düsen oder mehr Wandlinien wächst er zusätzlich so weit, dass
  ein innerer Hohlraum erhalten bleibt.
  Die automatische Standfußbreite ist
  `max(14 mm, 1,8 × Schaftdurchmesser, 0,25 × Turmhöhe)`.
  Das sind geometrische Stabilitätsrichtwerte, keine Material-/Haftungsgarantie.
- Die Linienbreite beträgt 110 % des Profil-Düsendurchmessers. Die ersten zwei
  Schichten schließen den Fuß; anschließend wandert die hohle Wand höchstens
  um die halbe jeweilige Schichthöhe nach innen. Damit überlappen die
  Wandbahnen der Folgeschichten. Bei kurzen Türmen endet diese Verjüngung vor
  Erreichen des nominellen Schaftdurchmessers. Eine obere Deckfläche entfällt.
- Die automatische Position sucht in einem Raster von 33 × 33 Kandidaten.
  Modell-, Rand- und Sperrflächenabstände begrenzen die gültigen Kandidaten.
  Bevorzugt werden kurze Gesamtfahrwege von repräsentativen Schichtendpunkten.
  Kandidaten mit Kollisionen späterer Originalbahnen oder ohne sichere
  Hin-/Rückwege werden verworfen. Die Prüfung reserviert konservativ den
  gesamten Fußdurchmesser über die Turmhöhe. Auch manuelle Positionen müssen
  diese Prüfungen bestehen.
- Die getrennte Warteposition liegt innerhalb der nutzbaren Bettfläche und
  außerhalb der Modellgrundfläche und des vollständigen Turmfußes. Ihr
  einstellbarer Mindestabstand beträgt standardmäßig 10 mm. Die Automatik
  sucht um gültige Turmpositionen nach kurzen, erreichbaren Wartewegen.
  Auch eine manuelle Warteposition muss alle Abstands- und Fahrwegprüfungen
  bestehen; fehlt eine gültige Kombination, bleibt der Export gesperrt.

Ohne Originaldefizit entsteht standardmäßig kein Turm und die exportierten
G-Code-Bytes bleiben unverändert. Ein Platz für einen unnötigen Turm muss in
diesem Fall nicht gefunden werden.

## Druckablauf, Fahrwege und Zeitberechnung

Nach der letzten Ablagebewegung einer betroffenen Schicht:

1. Filament zurückziehen und senkrecht über die bereits gedruckte Höhe anheben.
   Der zusätzliche Hub ist mindestens so hoch wie die Profilwerte
   `retract_lift`, `z_hop`, `filament_retract_lift` und `filament_z_hop`.
   Ein höherer manueller Sicherheitshub wird übernommen. Profil- und
   Original-G-Code-Hübe bleiben erhalten; alle neuen Hübe müssen innerhalb
   der bestätigten maximalen Druckhöhe liegen.
2. Die außerhalb von Modell und Turm liegende freie Warteposition anfahren. Ein
   Sichtbarkeitsgraph mit kürzester Wegsuche führt bei Bedarf um die im Profil
   definierten Sperrflächen herum; auch die tatsächliche Bettkontur begrenzt
   den Weg. Ohne nachgewiesenen Weg wird die Bearbeitung abgebrochen.
3. Mit `M400` die Ankunft abwarten und nur das verbleibende Defizit als
   `G4 P...` ausgleichen. Lange Pausen werden in höchstens 60 Sekunden lange
   Befehle aufgeteilt. `G4 P0` markiert ohne zusätzliche Pause denselben
   Stillstand auch in Schichten, deren Fahr-/Turmzeit bereits ausreicht.
4. Bei weiterhin angehobener Düse den geprüften Weg zum Turm fahren. Erst
   dort absenken, unretracten/primen und die Fuß- beziehungsweise Wandbahnen
   drucken. Diese Bahnen nehmen das Oozing auf.
5. Wieder zurückziehen, anheben, den sicheren Weg zurückfahren und am
   ursprünglichen Modellpunkt absenken. XYZ-Modus, Extrusionsmodus,
   E-Koordinate und Vorschub werden wiederhergestellt.

Der erste Berechnungsschritt erzeugt die vollständigen Fahr-, Prime- und
Turmbahnen ohne zusätzliche Wartezeit. Der bestehende Beschleunigungs-/Slicer-
Zeitrechner analysiert diesen Stand. Aus der Differenz zur unveränderten
Bewegungszeitbasis und den Originalzeiten entstehen die Schichtzeiten
einschließlich aller neuen Bewegungen. Nur `Zielzeit − Schichtzeit` wird,
auf Millisekunden aufgerundet und bei null begrenzt, als Wartezeit eingefügt.
Der fertige G-Code wird nochmals analysiert. Abweichende Schichtzahlen,
Z-Werte, unberechenbare Bewegungen oder nicht bestätigte Zielzeiten blockieren
den Export. Das Zeitmodell bleibt eine Berechnung; reale Firmware- und
Druckerabweichungen werden damit nicht zu einer Messgarantie.

Anycubic-Pre-Slices besitzen maßgebliche native Zeitmarken. Sie bleiben für die
Originalzeit maßgeblich; die gemessene zusätzliche Bewegungszeit wird addiert.
Die kumulativen Marken werden ausschließlich in der Exportkopie aktualisiert.
Prusa-Start-Purgelinien werden für diese Methode anhand der expliziten
Modellschichtmarker von den Druckschichten getrennt. Der normale Analysecache
wird nicht für die abweichende Bewegungszeitbasis verwendet.

Abschließendes reines XY-Homing ohne weitere räumliche Folgebewegungen erhält
vorher einen geprüften Z-Sicherheitshub über Modell und Turm. Unbekannte
Referenzfahrten einschließlich Z-Homing, Koordinatenwechsel, Mehrwerkzeugdruck,
volumetrische Extrusion, nichtplanarer/Spiraldruck, Prüfsummenzeilen und
bereits bearbeitete Quellen werden gesperrt. Diese Einschränkungen werden
konkret gemeldet; Originalprofile werden dafür nicht verändert.

## Vorschau und Orientierung

Modellbahnen werden aus den absoluten G-Code-Koordinaten rekonstruiert;
Turmbahnen aus den tatsächlich erzeugten Befehlen. Es gibt kein unabhängiges
Zentrieren, Drehen oder Spiegeln von Modell, Turm oder Druckbett.
Die Bettkontur einschließlich negativer Ursprünge, runder/polygonaler Formen
und Sperrflächen stammt aus dem bestätigten Druckprofil. Wissenschaftliche
Schreibweise wie `7e-15` bleibt beim Einlesen erhalten.

Gelbe gestrichelte Linien zeigen die erzeugten Fahrwege einschließlich der
Z-Hops. **Warten** markiert die tatsächliche angehobene Position eines
`G4`-Befehls; ohne nötige Pause bleibt der geplante XY-Punkt sichtbar.
Der Schalter **Fahrwege, Z-Hops und Warteposition anzeigen** beeinflusst
ausschließlich die Darstellung. Externe Slicer können Pausen und Leerfahrten
je nach Vorschaufilter anders oder gar nicht darstellen. Der G-Code enthält
die Fahrtbefehle unabhängig von deren Darstellung.

Die Ansicht startet mit vollständig eingepasstem Bett und zeigt X+/Y+ am
G-Code-Ursprung. Wie im automatischen Modus gibt es **3/4-Ansicht**,
**Vorderansicht**, **Seitenansicht** und **Draufsicht**, zusätzlich **Einpassen**
für das vollständige Druckbett. **Draufsicht** legt X nach rechts und Y nach oben/hinten. Die Ansicht lässt sich
drehen, verschieben und zoomen. Sehr große Bahnlisten werden nur für die
Darstellung ausgedünnt; der exportierte G-Code enthält alle erzeugten Bahnen.

## Implementierung und Abnahme

`preprocessor.py` enthält unveränderliche Einstellungen/Requests, Planung,
Zeitberechnung und Export. `preprocessor_travel.py` prüft Originalbahnen und
plant die Fahrwege. `gui/preprocessor_controls.py` stellt gemeinsame
Einstellungszeilen, Hinweis-Popover, Reset-Aktionen, Vorschau und Footer zusammen.
`gui/preprocessor_panel.py` besitzt den eigenen Sitzungsstand und den
verwalteten, abbrechbaren Vorschaujob. Temporäre
Dateien werden beim Verwerfen, Abbruch und regulären Schließen freigegeben.
Die Funktion verwendet bestehende Abhängigkeiten; es wurde kein Code des im
[modwait-Konzept beschriebenen Ansatzes](https://github.com/kdsohn/modwait)
übernommen und keine neue Drittkomponente eingeführt.

Die Tests `test_preprocessor*.py` decken Kern, Zeitbilanz, Originalzustände,
Fahrwege, Orientierung, Fehler-/Exportsperren, Neuberechnung, atomaren Export
und GUI-Lebenszyklus ab. `test_preprocessor_real_slicers.py` führt optional
den vollständigen Ablauf mit allen vier installierten Slicern aus und prüft
die ausgewählten Originalprofile per SHA-256. Konfiguration und Aufruf stehen
in [Slicer-Abnahmen](slicer_acceptance_tests.md).

### Lokale Abnahme vom 24. Oktober 2026

- 36 gezielt ausgewählte Testmodule: 682 erfasste Testfälle, davon 680
  bestanden und zwei optionale Fälle übersprungen. Die zuvor gefundenen
  Fehler in Dateipfadhöhen und aufgeklappten Einstellungsbereichen sind
  korrigiert und durch die betroffenen GUI-Regressionen geprüft.
- Der vollständige STL-/Pre-Slice-/Präprozessor-/Exportablauf lief erfolgreich
  mit Anycubic Slicer Next, Bambu Studio, OrcaSlicer und PrusaSlicer. SHA-256-
  Vergleiche bestätigen die unveränderten ausgewählten Originalprofile.
- Ein zusätzlicher vorhandener Pre-Slice mit 544 Schichten und 97,94 mm Höhe
  wurde mit 30 Sekunden Zielzeit verarbeitet. Das Ergebnis enthält 540
  Wartephasen; die kürzeste berechnete Schicht erreicht 30 Sekunden.
  Der Original-Pre-Slice blieb unverändert.
- Breite und schmale Oberfläche, Hinweis-Popover, aufgeklappte Einstellungen,
  Vorschau und Footer wurden zusätzlich anhand gerenderter Bilder geprüft.
  Die abschließenden GUI-Tests liefen auch mit den tatsächlichen
  Windows-Schriften.

Diese Abnahme prüft Software, G-Code und berechnete Zeiten. Ein physischer
Probedruck wurde nicht durchgeführt.
