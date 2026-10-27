# Postprozessor: Abkühlpausen und hohler Abstreifturm

## Bedienung

Nach STL-Auswahl, Slicer-/Profilbestätigung und Pre-Slice steht neben
**Iterativ** und **Manuell** die dritte Methode **Postprozessor** bereit.
Unterstützt werden Anycubic Slicer Next, Bambu Studio, OrcaSlicer und PrusaSlicer.
Dieser Modus bearbeitet den bereits vorhandenen Pre-Slice; eine Änderung der
Turmeinstellungen startet keinen weiteren Slicerlauf.

**G-Code und Vorschau erzeugen** startet die Berechnung ausdrücklich.
Sobald ein gültiger G-Code zum Export bereitsteht, ersetzt **G-Code exportieren**
diese Schaltfläche. Nach Änderungen an Quelle oder Druckeinstellungen erscheint
die Erzeugung wieder; reine Ansichtsänderungen behalten den Exportzustand bei.
Einstellungsänderungen verwerfen das alte Ergebnis und starten keine Berechnung.
Links stehen die Einstellungen, rechts die Vorschau. Die Bereiche schließen
ohne Außenabstände und Rundungen aneinander und an den Fensterrand an.
Die Trennlinie besitzt einen sichtbaren Griff, einen horizontalen Ziehcursor
und eine dezente Hervorhebung bei Mauskontakt. Ziehen ändert beide Breiten
einschließlich der Vorschau. Ihre Höhe folgt der Breite bis zur verfügbaren
Fensterhöhe; die vollständigen Bedienelemente darunter werden dabei reserviert.
Standardmäßig erhält die Einstellungsleiste nur die notwendige Breite. Zwischen
Einstellungsname und erstem rechten Bedienelement bleiben mindestens 30 Pixel
Abstand; alle Felder und Reset-Buttons bleiben rechts bündig. Doppelklick setzt
die Trennlinie in die horizontale Mitte, soweit die Mindestbreiten der
Bedienelemente dies zulassen. Bei mehr Platz wird die mittige Aufteilung
wiederhergestellt. Eine per Ziehen oder Doppelklick
gewählte Aufteilung bleibt bei anschließenden Größenänderungen erhalten.
Die Trennlinie stoppt an den Mindestbreiten der Bedienelemente. Einstellungsnamen,
Schalterbeschriftungen und Vorschau-Buttons bleiben ohne zusätzliche Umbrüche
lesbar. Mehrzeilige Hinweise und Ergebnistexte passen sich der Spaltenbreite an.
Schmale Fenster stapeln die Vorschau über den Einstellungen; beim erneuten
Verbreitern wird die gewählte Aufteilung wiederhergestellt. Die iterative
Methode behält ihre feste Halbierung. Die Einstellungen besitzen links
ein Hover-Hinweis-Icon mit kurzer Erklärung. Numerische Einstellungen haben rechts einen Reset im gemeinsamen
Design. Bei numerischen Automatikzeilen folgen rechts auf den Funktionsnamen der Text
**Auto**, die Checkbox, das Eingabefeld und der Reset. Alle Zahlenfelder verwenden
die gemeinsame Breite des breitesten aktuellen Inhalts einschließlich Einheit
und Pfeiltasten. Die Breite folgt auch unbestätigten Texteingaben, ohne sie zu
übernehmen oder den Cursor zu verändern. Bei **Hohler Turm**
steht die Checkbox hinter dem Namen; der Reset bleibt am rechten Rand.
Turmhöhe, Schaftdurchmesser und Standfußbreite besitzen jeweils eine eigene
Automatik. Die gemeinsame Zeile **Turm- und Warteposition** enthält rechts
**Auto**, die Checkbox und **Positionen bearbeiten**. Abschalten aktiviert den
Editor-Button; Einschalten setzt beide Positionen wieder auf Automatik.
Die Koordinaten bleiben im Positionseditor: jeweils ein verbundenes X/Y-Feld,
X wie die Vorschauachse rot, Y grün. Im Editor können die beiden Positionen
auch einzeln auf Automatik zurückgesetzt werden.
Deaktivieren übernimmt den zuletzt berechneten Wert zur
manuellen Bearbeitung, soweit er im zulässigen manuellen Bereich liegt.
Automatisch berechnete Eingabefelder sind deaktiviert und grau dargestellt.
Nach der Erzeugung zeigen sie den verwendeten Wert. Ohne aktuelles Ergebnis
steht dort ein Gedankenstrich; nach Einstellungsänderungen werden alte Werte
nicht weiter als aktuell angezeigt. Wird kein Turm benötigt, zeigen seine
automatischen Maße 0,00 und nicht verwendete Positionen einen Gedankenstrich.
Die Einstellungen bleiben während der Sitzung erhalten;
sie werden derzeit nicht als globale Benutzervorgaben gespeichert.

**Wandlinien** und **Warteabstand** stehen in den Postprozessor-Einstellungen.
**Z-Hop** bezeichnet den Sicherheitshub in den erweiterten Einstellungen.
**Turm-Brim Breite** und **Turm-Brim Abstand** stehen ebenfalls in den erweiterten
Einstellungen und steuern einen eigenen Brim nur
für den Turm. Brim-Art und Brimbreite des Modellprofils werden dafür nicht
übernommen; die bereits geslicten Modellbahnen einschließlich Modell-Brim
bleiben erhalten. Die Breitenautomatik und der Standard erzeugen 2 mm pro Seite. Manuell sind
0 bis 20 mm einstellbar; 0 mm schaltet den Turm-Brim aus. Die Abstandsautomatik
liest `brim_separation` beziehungsweise `brim_object_gap`, ersatzweise gelten
0,2 mm. Manuell sind 0,1 bis 1 mm möglich. Auch ein automatischer Profilabstand
von 0 mm bleibt zulässig. Brim und Abstand werden bei Platzierung und
Kollisionsprüfungen zusätzlich zum Fußradius berücksichtigt. Die angezeigte
Standfußbreite enthält beide nicht.

Die Rundenanzahl folgt aus Brimbreite, Profil-Linienbreite und Schichthöhe.
Die Linienbreite für Brims stammt bei Prusa aus `first_layer_extrusion_width`,
ersatzweise `perimeter_extrusion_width` und `extrusion_width`; bei den übrigen
Slicern aus `initial_layer_line_width`, ersatzweise `inner_wall_line_width`
und `line_width`. Ohne expliziten Wert gelten 110 % des Düsendurchmessers.
Prozentwerte verwenden bei Prusa die erste tatsächliche Schichthöhe, sonst
den Düsendurchmesser. Diese Fallbackfolge entspricht den Profil-Schnittstellen
von [PrusaSlicer](https://github.com/prusa3d/PrusaSlicer/blob/version_2.8.1/src/libslic3r/Print.cpp)
und [OrcaSlicer](https://github.com/SoftFever/OrcaSlicer/blob/main/src/libslic3r/Print.cpp).
Der äußerste und innerste Ring begrenzen das gewählte Band; der Ringabstand
wird gleichmäßig verteilt, eine schmalere Bandbreite begrenzt die Linienbreite.
Extrusionsmengen, Vorschaukennzeichnungen und Volumenstrombegrenzung verwenden
die tatsächlich gedruckte Breite. Die erste Brimbahn wird mit Sicherheitshub
angefahren. Der Brim erscheint ausschließlich auf der ersten Turmschicht.

Manuelle Zahlenfelder übernehmen Texteingaben erst mit Enter oder beim
Verlassen des Feldes, etwa durch Tab oder einen Klick auf ein anderes Element.
Während des Tippens bleiben Text, Auswahl und Cursor unverändert. Punkt und
Komma sind als Dezimaltrenner zulässig. Beim Übernehmen erscheinen Dezimalwerte
mit Komma, auf höchstens zwei Nachkommastellen gerundet und ohne unnötige
Endnullen. Leere oder unvollständige Eingaben kehren zum letzten gültigen Wert
zurück; außerhalb des Wertebereichs liegende Zahlen werden auf dessen Grenzen
begrenzt. Pfeiltasten und Schrittbuttons übernehmen den Entwurf vor dem Schritt.
Das gilt auch für Koordinaten und Randabstand im Positionseditor. Seine
Positions- und Fahrwegprüfung wartet auf den Abschluss der Eingabe; während
eines offenen Entwurfs bleibt Übernehmen gesperrt.
Enter bestätigt im Positionseditor ausschließlich das Zahlenfeld. Erst die
separate Schaltfläche Übernehmen übernimmt geprüfte Positionen in die Einstellungen.

### Profilvorgaben und Geschwindigkeitsgrenzen

Die Mindest-Layerzeit beträgt standardmäßig manuelle **10 Sekunden**. Einzelreset
und Standardwerte stellen diesen Wert mit deaktivierter Automatik wieder her.
Die optionale Automatik liest die Kühlungsvorgabe des bestätigten Profils.
Turmdrucktempo, Fahrtempo sowie gekoppelte Rückzugslänge und Rückzugstempo
besitzen weiterhin eine standardmäßig aktive Automatik. Diese Vorgaben stammen
ausschließlich aus dem bestätigten Profil des aktiven Extruders:

- Die Mindestzeit stammt aus `slow_down_layer_time` beziehungsweise
  `slowdown_below_layer_time`. Bei ausdrücklich deaktivierter Profilkühlung
  oder fehlendem gültigem Wert bleibt ein gekennzeichneter Ersatzwert aktiv.
- Gültige Filamentüberschreibungen für Rückzug haben Vorrang vor den
  Maschinenwerten; `nil` bedeutet Vererbung, eine Rückzugslänge von 0 ist
  zulässig. Ein eigenes Profiltempo für den Rückzugsausgleich wird beachtet.
- Das äußere Wandtempo bestimmt den Turmdruck. Prozentangaben beziehen sich
  auf das innere Wand-/Perimetertempo. Bekannte X-/Y-Maschinengrenzen begrenzen
  das Fahrtempo.
- Positive Material-/Prozess-Volumenstromgrenzen gelten auch bei manuellen
  Geschwindigkeiten. Linienbreite, tatsächliche Schichthöhe und zusätzliche
  Prime-Menge gehen in die Begrenzung ein. Ein Volumenstromwert 0 bedeutet
  keine zusätzliche Profilgrenze. Die Eingabebereiche bleiben ebenfalls aktiv.

Automatische Profilwerte sind schon vor der Erzeugung sichtbar. Das Ergebnis
zeigt die tatsächlich verwendeten, gegebenenfalls begrenzten Werte. Hinweise
erklären Übernahme und Ersatzwerte; technische Berichte enthalten sowohl die
gewählten Einstellungen als auch die wirksamen Werte. Abschalten einer
Automatik übernimmt den zuletzt sichtbaren Wert zur manuellen Bearbeitung.
M220-Geschwindigkeitsfaktoren werden bei neuen Druck-/Fahrvorschüben
ausgeglichen; Originalbefehle und ihre Faktoren bleiben erhalten.

Die erste Turmschicht verwendet eigene Profilobergrenzen für Wand und Füllung:
`initial_layer_speed`/`first_layer_speed` sowie, falls vorhanden,
`initial_layer_infill_speed`/`first_layer_infill_speed`. Prozentwerte beziehen
sich auf das jeweilige reguläre Merkmaltempo. Ein langsamerer manuell gewählter
Turmwert bleibt maßgeblich. Ohne eindeutiges Erstschichttempo gilt höchstens
20 mm/s; ein fehlendes Fülltempo übernimmt das Erstschicht-Wandtempo.
`initial_layer_line_width`/`first_layer_extrusion_width` bestimmen Bahnmitten,
Ringabstände und Materialmenge der ersten Schicht. 0 bedeutet automatische
Breite und verwendet die reguläre Profilbreite als gekennzeichneten Ersatz.
Bei Prusa beziehen sich Prozentbreiten auf die erste tatsächliche Schichthöhe;
bei Anycubic, Orca und Bambu auf den Düsendurchmesser.
Volumenstrom und zusätzliche Prime-Mengen begrenzen das Tempo weiterhin.

Der eigene Turm-Brim zählt mit Fahrten, Extrusion und Flussgrenzen zur
Schichtzeit. Die Vorschauen zeigen ihn in einem dunkleren Blau, den Turm orange.
Modell-, Bett- und Warteabstände berücksichtigen seine volle Breite.

Bei automatischem Rückzug wird auch `filament_retract_restart_extra`,
ersatzweise `retract_restart_extra`, berücksichtigt. `nil` übernimmt den
Maschinenwert; explizit 0 hebt ihn auf. Die vorzeichenbehaftete Zusatzmenge
gilt für jeden tatsächlich ausgeführten Rückzugsausgleich am Turm und Modell.
Ohne Rückzug wird sie nicht angewendet. Eine negative Zusatzmenge größer als
der Rückzug sperrt die Erzeugung. Rückzugsausgleichstempo 0 übernimmt das
Rückzugstempo; bekannte Extruder-Geschwindigkeitsgrenzen bleiben wirksam.
Manueller Rückzug übernimmt keine zusätzlichen Profilmengen. Das gesonderte
**Zusätzliche Primen** bleibt eine unabhängig gewählte Ablage auf dem Turm.
Ein vorhandener M221-Flussfaktor wird bei den neuen Materialmengen ausgeglichen;
Bambu-spezifische M221-T-Befehle gelten dabei nicht als Flussänderung.
Bei Bambu gelten `T255`, `T1000` und `T1100` als herstellerspezifische
Steuerbefehle; sie ändern den erfassten realen Extruder nicht. Tatsächliche
Werkzeugwechsel bleiben auf den unterstützten einzelnen Extruder begrenzt.

**Erweiterte Einstellungen anzeigen** öffnet Wandlinien, Voll-/Hohlbauweise,
Randabstand, Turmdruck-/Fahrgeschwindigkeit, Rückzug, Rückzugsgeschwindigkeit,
Sicherheitshub, Warteabstand und zusätzliche Prime-Menge. Standard ist ein hohler Turm mit
zwei Wandlinien, einem außen gefüllten konkaven Standfuß und zwei
geschlossenen Bodenlagen. **Wandlinien** erlaubt 1–3 Linien und ist bei einem
vollständig gefüllten Turm deaktiviert. Bei geänderten Einstellungen
wird das alte abgeleitete Ergebnis verworfen; die unveränderte Pre-Slice-Datei
bleibt die Ausgangsbasis. Der Methodenwechsel erhält die jeweilige Vorschau.
Ein Quellen-/Profilwechsel verwirft sie.

Der geteilte Footer bleibt außerhalb des scrollbaren Inhalts erreichbar.
Links stehen Status und **Standardwerte**; rechts der blaue Erzeugen-Button.
Nach erfolgreicher Erzeugung steht der grüne Export-Button ganz rechts und
verschiebt den Erzeugen-Button nach links. **Abbrechen** erscheint nur bei
laufender Erzeugung. Seine Höhe folgt Fortschrittsanzeige, mehrzeiligen
Status-/Fehlertexten und Exportaktionen, sodass auch **Standardwerte** sichtbar
bleibt. In schmalen Fenstern werden die Footerbereiche gestapelt.

**G-Code exportieren** speichert die geprüfte Vorschau als `.gcode`. Dieser
Modus benötigt keinen erneuten Slice und exportiert kein gemeinsames 3MF/STL.
Wie die anderen Methoden legt er im konfigurierten Methodenordner einen neuen
Zeitstempel-Unterordner mit G-Code, Kurzbericht und technischem Bericht an.
Danach stehen **Alle Exporte öffnen**, **Letzten Export öffnen** und
**Letzten Exportbericht öffnen** zur Verfügung. Der Exportdialog beschreibt
die direkte Verwendung des fertigen G-Codes und dessen berechnete Schichtzeiten.
Kritische Fehler erscheinen sichtbar als **Export gesperrt** und entfernen die
Exportberechtigung. Auch veränderte oder fehlende Original-/Ergebnisdateien
blockieren den Export. Vorhandene Exporte bleiben erhalten. Die Datei wird zunächst vollständig in eine temporäre
Nachbardatei geschrieben, geprüft und anschließend atomar übernommen.

## Geometrie und Platzierung

Der Turm stellt eine Abstreiffläche bereit. Seine Querschnittsfläche wird nicht
zum Ausgleichen der Schichtzeit dynamisch kalibriert.

- Die automatische Höhe umfasst die Originalschichten bis zum letzten
  Schichtzeitdefizit. Sobald alle nachfolgenden Originalschichten die
  Mindest-Layerzeit allein erreichen oder überschreiten, endet der Turm;
  er wird nicht grundsätzlich bis zur letzten Modellschicht erzeugt.
  Ausreichende Zwischenschichten werden überbrückt, wenn später wieder ein
  Defizit auftritt. Erreicht das Original die Zielzeit überall, entfällt der
  automatische Turm vollständig. Eine manuelle Höhe wird auf vorhandene
  Schichten abgerundet; sie darf den nötigen Bereich nicht unterschreiten und die
  Modellhöhe nicht überschreiten. Ein Turmlayer kann selbst bereits genügend
  Zeit erzeugen; dann entfällt dort die eigentliche Wartezeit.
- Der automatische Schaftdurchmesser beträgt `max(6 mm, 0,10 × Turmhöhe)`.
  Bei breiten Düsen oder mehr Wandlinien wächst er zusätzlich so weit, dass
  ein innerer Hohlraum erhalten bleibt.
  Die automatische Standfußbreite ist
  `min(150 mm, 1,25 × max(14 mm, 1,8 × Schaftdurchmesser, 0,25 × Turmhöhe))`.
  Das sind geometrische Stabilitätsrichtwerte, keine Material-/Haftungsgarantie.
- Der Standfuß verwendet dieselbe konkave Kurve und Höhenregel wie die
  iterative Methode mit 100 % Füllung: mindestens 6 mm, 22 reale
  Schichtintervalle oder 2,5 % der Modellhöhe, begrenzt durch die Turmhöhe.
  Soweit darüber noch Schichten verfügbar sind, endet die Kurve fünf
  Schichten später. Die verbreiterte zweite Schicht schließt bis zur dritten
  Schicht linear an die konkave Kontur an. Ihr Beginn liegt auf der ersten Schicht; der letzte
  Kurvenquerschnitt geht in den angegebenen Schaftdurchmesser über. Die ersten
  zwei Turmschichten schließen den Boden vollständig. Darüber bleibt der Kern
  auch innerhalb des Standfußes offen: Nur der Bereich außerhalb des späteren
  Schafts einschließlich seiner Wandstärke wird massiv gefüllt. So bleiben
  nach innen versetzte Fußbahnen unterstützt, ohne den gesamten Fußquerschnitt
  bis zum Ende der Kurve zu füllen. Der Hohlraum folgt dem Schaft-Innendurchmesser.
  Eine obere Deckfläche entfällt. Ein deaktivierter Hohlbau erzeugt weiterhin
  einen durchgehend gefüllten Turm.
- Als Maßeingabe genügt der **Außendurchmesser**. Die äußere Wandlinie nutzt
  `outer_wall_line_width` beziehungsweise `external_perimeter_extrusion_width`,
  weitere Linien `inner_wall_line_width` beziehungsweise
  `perimeter_extrusion_width`. Fehlende oder automatische Werte (0) verwenden
  die allgemeine `line_width`/`extrusion_width`, ersatzweise 110 % des
  Düsendurchmessers. Prozentwerte beziehen sich bei Anycubic, Orca und Bambu
  auf den Düsendurchmesser. Prusa verwendet die jeweilige tatsächliche
  Schichthöhe; die Breiten werden bei variablen Schichten deshalb neu bestimmt.
  Die Bezugsgröße beschreibt die [Prusa-Profildokumentation](https://help.prusa3d.com/article/creating-profiles-for-different-nozzles_127540).
  Bei Schichthöhe `h` und `n` Linien beträgt die radiale Wandstärke
  `w_außen + (n − 1) × (w_innen − h × (1 − π/4))`.
  Der Innendurchmesser ist `Außendurchmesser − 2 × Wandstärke`; ein eigenes
  Eingabefeld ist nicht erforderlich. Die Bahnmitten und Extrusionsmengen
  verwenden dieselben Breiten und dieselbe Überlappung. Variable Schichthöhen
  ergeben entsprechend einen Wertebereich, den die Ergebnisübersicht ausweist.

Die geschlossenen Bodenlagen werden mit äußeren und inneren Wandlinien und
anschließend dicht nebeneinanderliegenden geraden Füllbahnen erzeugt.
Die zweite Bodenlage kreuzt die Füllrichtung der ersten. Auf der ersten
Turmschicht gelten Erstschicht-Linienbreite und Erstschichttempo aus dem Profil;
sie wird als **Bottom surface**, bei Prusa als **Solid infill**, gekennzeichnet.
Die zweite Lage ist eine interne Vollfüllung. Oberhalb der Bodenlagen füllen
konzentrische Bahnen ausschließlich den ringförmigen Materialquerschnitt.
Restbreiten im Fuß werden auf vollständige Bahnen verteilt, damit weder
winzige Gap-Fill-Bahnen noch doppelt extrudierte Ringe entstehen. Die tatsächlichen
Bahnbreiten bestimmen jeweils Extrusionsmenge und Volumenstrombegrenzung;
im normalen Schaft gelten die unveränderten Profilbreiten und Wandlinienzahlen.
Der eigene Turm-Brim bleibt ausschließlich auf der ersten Schicht.

Der erzeugte G-Code enthält eigene Rollen-, Breiten- und Höhenkommentare.
Er übernimmt keine Gap-Fill-Kennzeichnung oder schmale Anzeige aus einer
vorangegangenen Modellbahn. Vor dem Rücksprung werden deren Anzeigewerte und
Wipe-Zustand wiederhergestellt; die Originalzeilen bleiben erhalten.
Prusa verwendet `TYPE`/`WIDTH`/`HEIGHT`; Bambu beziehungsweise native Orca-Dateien
verwenden `FEATURE`/`LINE_WIDTH`/`LAYER_HEIGHT`. Die vorhandene Schreibweise
wird aus der Quelle erkannt. Die Kennzeichnungen folgen den Quellcode-Schnittstellen von
[PrusaSlicer](https://github.com/prusa3d/PrusaSlicer/blob/version_2.8.1/src/libslic3r/GCode/GCodeProcessor.cpp),
[Bambu Studio](https://github.com/bambulab/BambuStudio/blob/master/src/libslic3r/GCode/GCodeProcessor.cpp)
und [OrcaSlicer](https://github.com/SoftFever/OrcaSlicer/blob/main/src/libslic3r/GCode/GCodeProcessor.cpp).
  Zu enge manuelle Durchmesser werden abgewiesen, automatische Durchmesser
  lassen mindestens eine Linienbreite für den inneren Hohlraum frei.
  Die ausgewählten 1–3 Wandlinien werden direkt als G-Code-Bahnen erzeugt.
  `wall_loops` und `perimeters` des Profils beeinflussen ihre Anzahl nicht;
  es werden keine objektspezifischen Slicer-Einstellungen gesetzt oder
  Profilwerte verändert.
- Die automatische Position sucht in einem Raster von 33 × 33 Kandidaten.
  Modell-, Rand- und Sperrflächenabstände begrenzen die gültigen Kandidaten.
  Kurze Gesamtfahrwege von repräsentativen Schichtendpunkten werden bevorzugt.
  Wartepositionen auf derselben Modellseite wie der Turm haben Vorrang vor
  unnötigen Modellüberfahrten. Die Wegsuche umgeht andere Modellinseln, soweit
  ein zumutbarer Umweg möglich ist. Ausgangs- und Zielinseln bleiben erreichbar.
  Die Inselhüllen werden aus dem vollständigen Ablageindex abgeleitet und
  dienen nur dieser Wegpräferenz. Sie sperren keine ansonsten sicheren
  angehobenen Fahrten; feste Hindernisse bleiben zwingend zu umgehen.
  Kandidaten mit Kollisionen späterer Originalbahnen oder ohne sichere
  Hin-/Rückwege werden verworfen. Für Modellabstände zählen die ungekürzten
  Ablagebahnen einschließlich Linienbreitenreserve und der Turmquerschnitt
  auf der jeweiligen Höhe. Freie Zwischenräume zwischen Modellbereichen
  werden dadurch nicht pauschal durch eine gemeinsame Umgrenzung gesperrt.
  Spätere Originalfahrten werden weiterhin konservativ gegen den gesamten
  Fußdurchmesser geprüft. Auch manuelle Positionen müssen diese Prüfungen bestehen.
  Ein räumlicher Bewegungsindex bewahrt die Chronologie und wird pro Erzeugung
  einmal aufgebaut. Seine Begrenzungsrechtecke dienen nur zur Vorauswahl;
  entscheidend bleiben Linienabstände, Höhen und konservative Bogenhüllen.
  Vollkreise mit gleichem Anfangs-/Endpunkt bleiben enthalten. Wiederholte
  Hin-/Rückwege nutzen einen begrenzten lokalen Routencache. Die Darstellungs-
  ausdünnung beeinflusst keine dieser Sicherheitsprüfungen.
- Die getrennte Warteposition liegt innerhalb der nutzbaren Bettfläche und
  außerhalb der Modellgrundfläche und des vollständigen Turmfußes. Ihr
  einstellbarer Mindestabstand beträgt standardmäßig 10 mm. Die Automatik
  sucht um gültige Turmpositionen nach kurzen, erreichbaren Wartewegen.
  Auch eine manuelle Warteposition muss alle Abstands- und Fahrwegprüfungen
  bestehen; fehlt eine gültige Kombination, bleibt der Export gesperrt.

### Interne Kollisionsprüfung und fehlende Geometrieangaben

Die Vorschauen zeigen keine pauschalen Druckkopfkreise. Beim unterstützten
schichtweisen Druck befindet sich der Kopf oberhalb der Düse und damit über
der aktuellen Schicht. Ein rundum freier Druckkopfradius zwischen gewöhnlichen
Modellen würde deshalb unnötig Bettfläche sperren. Modell- und Warteabstände
werden durch die eingestellten Abstände und den tatsächlichen Turmfuß bestimmt;
fehlende Kopfmaße vergrößern sie und den Z-Hop nicht.

Die interne Kollisionsprüfung berücksichtigt weiterhin Originalfahrten,
Turm, Warteposition und zusätzliche Fahrwege. Bei abgewiesenen Positionen nennt
die Fehlermeldung den betroffenen Abstand oder Fahrweg; bei Originalfahrten
kann sie zusätzlich die Zeilennummer nennen. Grenzen stehen im Tooltip und
in den Exportberichten. Firmwareinterne Start-, End- und Referenzabläufe
bleiben nur eingeschränkt prüfbar.

Die Prüfung verwendet konservative zylindrische Sicherheitsbereiche statt eines
vermeintlich exakten, nicht vorhandenen Druckkopf-Meshs. Der untere Bereich
nutzt `extruder_clearance_radius` nur, wenn die Originaldüse später unter die
bereits aufgebaute Turmhöhe fährt. Weiter ausladende Teile
berücksichtigen zusätzlich `extruder_clearance_max_radius` und
`extruder_clearance_dist_to_rod`; die größte gültige Radiusangabe gilt.
Für den oberen Bereich wird die niedrigste gültige Angabe aus
`extruder_clearance_height` und `extruder_clearance_height_to_rod` verwendet.
Die Deckelhöhe ist kein Ersatz für die Freihöhe des unteren Kopfbereichs.
Originale spätere Bewegungen werden gegen den bereits aufgebauten Turm
einschließlich der höhenabhängigen Sicherheitsbereiche geprüft. Bei normaler
Schichtfolge gilt der Düsen-/Fußabstand. Liegt ein Querträger bei einer späteren
niedrigen Originalfahrt unter der aufgebauten Turmhöhe, umfasst die Prüfung
zusätzlich über die Bettbreite reichende Sicherheitsstreifen. Ohne eindeutig
bestätigte Ausrichtung werden beide Achsrichtungen konservativ berücksichtigt.
Der maximale Platzbedarf erweitert die
Abstände zu Druckbett-Sperrflächen auch auf den neuen Fahr- und Druckbahnen.

G2-/G3-Kreisbögen werden für die Sicherheitsprüfung entlang ihres tatsächlichen
Winkelbereichs in kurze Sehnen zerlegt. Deren Abstand zur Kurve bleibt als
zusätzliche Sicherheitsreserve erhalten, ebenso Rundungsabweichungen zwischen
Start- und Endradius. Die Unterteilung zielt auf höchstens 0,01 mm
Kurvenabweichung; erreicht sie ihre Größenbegrenzung, wird die verbleibende
Abweichung vollständig als Reserve berücksichtigt. Ein großer Kreisradius bei
einem kurzen, flachen Bogen sperrt dadurch keine entfernten Bettflächen.
Vollkreise, Drehrichtung, Bogenebene, absolute oder relative Mittelpunkte und
R-Radien werden berücksichtigt. Platzierung, Positionsraster und die Prüfung
eigener Sperrflächen verwenden dieselben Hüllen; die Originalbefehle bleiben
unverändert.

Nur bei tatsächlich relevanten festen Hindernissen oder tiefen Originalfahrten
erscheint bei fehlenden Kopfmaßen ein Hinweis in der Vorschau. Der Exportbericht
enthält die verwendeten Annahmen. Der geschätzte Platzbedarf
verwendet mindestens 70 mm Radius, sonst 30 % der kürzeren Bettseite bis
100 mm; größere bekannte Radien bleiben erhalten. Eine unbekannte Freihöhe
wird konservativ als 0 behandelt. Die Ersatzmaße gelten ausschließlich für
feste Hindernisse und Originalbewegungen unterhalb des aufgebauten Turms.
Alle gewählten Hin- und Rückwege müssen die Prüfung bestehen. Ohne zulässige
Kombination wird kein Export freigegeben.

Die Bettkontur beschreibt den zulässigen Düsen-Bewegungsbereich; ein
Druckkopf darf konstruktionsbedingt darüber hinausragen. Physische Hindernisse
müssen durch Profil- oder eigene Sperrflächen abgebildet sein. Ersatzabstände
sind eine vorsichtige Schätzung, keine Messung und kein Nachweis für unbekannte
Bauformen, Umbauten oder undokumentierte Hindernisse.

### Positionseditor

**Positionen bearbeiten** in der Zeile **Turm- und Warteposition** öffnet bei ausgeschalteter
Automatik eine vergrößerbare Draufsicht
mit dem Druckbett, geschützten Profilflächen, Modellbahnen, Turmfuß und
Wartepunkt. Ausgangspunkt sind die automatisch berechneten Positionen;
bereits ausdrücklich geänderte manuelle Koordinaten bleiben beim erneuten
Öffnen erhalten. Turm und Wartepunkt lassen sich mit der linken Maustaste
ziehen. Die jeweilige Automatik wird dabei ausgeschaltet; alternativ können
X und Y direkt eingegeben oder die Automatik wieder aktiviert werden.
Mausrad zoomt, rechte oder mittlere Maustaste verschiebt die Ansicht.
Die Anfangsansicht zeigt das vollständige Druckbett. **Druckbett einpassen**
liegt rechts oben in der Vorschau und wird bei veränderter Einpassung grün. X zeigt nach
rechts, Y nach oben; negative Bettursprünge und die tatsächliche Bettform
bleiben erhalten. Profil-Sperrflächen werden nur angezeigt und bleiben geschützt.

Nach jeder Änderung werden alle Positionen und sämtliche Hin-/Rückwege mit
derselben Platzierungsprüfung wie bei der G-Code-Erzeugung geprüft. Die
Darstellung darf Modellbahnen ausdünnen; die Sicherheitsprüfung verwendet den
vollständigen Bewegungsindex einschließlich Chronologie und Höhen. Dieser
Index, Modellvorschau und Endzustände werden aus demselben G-Code-Durchlauf
gewonnen. Index und geprüfte Positionen werden während der Sitzung wiederverwendet.
Ein erneutes Öffnen zeigt bereits berechnete, unveränderte Positionen sofort,
auch wenn zuvor nur G-Code und Vorschau erzeugt wurden. Der Cache bindet
Quelle, Dateizustand, Profil, Analyse und alle relevanten Einstellungen.
Geänderte Dateien oder Eingaben dürfen keine fremden Prüfergebnisse übernehmen.
Die Originalquelle wird vor der Übernahme weiterhin vollständig geprüft.
Gleichzeitige Zugriffe auf einen wiederverwendeten Prüfindex werden serialisiert. Berechnung und Prüfung laufen als verwaltete, abbrechbare
Hintergrundaufgaben. Neuere Änderungen entwerten ältere Prüfergebnisse sofort.
Während einer Prüfung und bei ungültigen Positionen ist **Übernehmen** grau
und gesperrt. Die Meldung benennt beispielsweise einen zu geringen Modell-,
Turm- oder Randabstand oder einen blockierten Fahrweg. Geprüfte gültige
Positionen schalten **Übernehmen** grün frei. Die angezeigten Fahrwege dienen
der Orientierung; geprüft werden die Wege aller betroffenen Schichten.

Nur während des Ziehens erscheint für das gezogene Objekt ein grünes/rotes
Flächenraster. Es bezieht sich auf die Gegenposition beim Ziehbeginn und
berücksichtigt Modell-, Rand-, Turm- und Fahrwegprüfungen. Die Flächen werden
im Hintergrund aus dem vollständigen Bewegungsindex vorbereitet und für beide
Griffe zwischengespeichert. Identische XY-Bahnen verwenden den größten nötigen
Abstand über alle betroffenen Höhen; keine Originalbahn wird dafür ausgelassen.
Gebündelte Array-Berechnungen ersetzen wiederholte Einzelprüfungen jeder Zelle.
Eine zusätzliche Reserve um den Zellmittelpunkt hält die ganze grüne Zelle
von Hindernissen frei. Bei nicht konvexen Druckbetten oder gesperrten
Profilflächen wird zusätzlich die Erreichbarkeit von Zellmitte und Ecken geprüft.
Nahe einer Grenze bleibt das Raster eine konservative Orientierung: Beim
Loslassen verschwindet es und die genaue Positionsprüfung entscheidet über
**Übernehmen**. Vorbereitungen sind abbrechbar und an Quelle, Einstellungen
und Randabstand gebunden. Eine geänderte Gegenposition benötigt nur noch eine
Abstandsmaske auf den vorbereiteten Flächen.
Die initiale Vorbereitung schließt die Flächen für beide Griffe ein. Bei
einer bereits vorhandenen Vorschau werden die Positionen sofort angezeigt;
gegebenenfalls noch fehlende Ablageflächen werden mit einer Fortschrittsanzeige
vorbereitet. Die Griffe werden freigegeben, sobald ihre vollständigen Farbflächen
bereitstehen. Ein erneutes Öffnen verwendet auch diese gespeicherten Flächen.
Positionsänderungen brechen eine laufende gemeinsame Flächenvorbereitung nicht
ab; anschließend wird die Maske für die neueste Gegenposition aktualisiert.
Die Flächenfarben bleiben dezent. Zusätzlich wird der Umriss des gezogenen
Objekts grün für eine gültige und rot für eine ungültige Position hervorgehoben.
Ein eigener abbrechbarer Prüfer verarbeitet pro Ziehvorgang jeweils nur die
neueste Mausposition. Er prüft die genaue Koordinate unabhängig vom konservativen
Flächenraster; veraltete Antworten ändern die aktuelle Markierung nicht.

Die statische Bett- und Modellzeichnung wird getrennt von den bewegten
Griffen gepuffert. Mausbewegungen setzen nur diese fertigen Bilder und die
Flächenanzeige zusammen; sie projizieren oder zeichnen die Modellbahnen nicht
erneut. Ein nötiger Neuaufbau bündelt Linien in nativen Zeichenaufrufen, damit
parallel laufende Prüfungen die Oberfläche nicht durch tausendfache
Threadwechsel blockieren.

Während der ersten Berechnung erscheinen Fortschrittsbalken und aktueller
Berechnungsschritt zentral in der Vorschau. Ein dezenter bewegter Lichtverlauf
signalisiert die laufende Arbeit; die Animation stoppt bei Abschluss, Fehler,
Abbruch oder verborgenem Fenster. Ihre Bewegung folgt einer unabhängigen
Zeitbasis und läuft auch bei unverändertem Fortschritt weiter; neue
Berechnungsmeldungen starten sie nicht neu. Dieselbe Ladeansicht begleitet die
G-Code-Erzeugung in der Postprozessor-Vorschau. Fortschrittsangaben stammen aus
den tatsächlichen Verarbeitungsschritten.

Die Wellen, der Lichtverlauf und der wandernde Glanz werden als eigenes
animiertes SVG von Qt mit einer Zielrate von 60 Bildern pro Sekunde gezeichnet.
Es gibt keine Python-Timer oder Python-Zeichenaufrufe pro Animationsbild. Ein
einmalig erfasstes Szenenbild im SVG verhindert auch erneute Python-Aufrufe zum
Zeichnen des Hintergrunds. Fortschrittsmeldungen ändern nur Text und Balken;
eine neue Szene oder Fenstergröße erneuert den Hintergrund. Beim Verbergen
oder Beenden wird der native Animationstimer angehalten. Es werden keine
externen SVG-Dateien oder Netzwerkressourcen geladen.

Bei nachträglichen Positionsprüfungen bleibt die Szene frei: Der Effekt ist
außerhalb des Druckbetts deutlich abgeschwächt und innerhalb seiner tatsächlichen
Kontur nur minimal sichtbar. Die zentrale Ladebox entfällt; ein kompakter
Fortschrittsbalken und der aktuelle Schritt stehen unten bei den Meldungen.
Die Animation behält ihre Form und ihre unabhängige Zeitbasis. Eine gepufferte
Szene vermeidet, dass unveränderte Modellbahnen für jedes Animationsbild erneut
gezeichnet werden; Positions-, Kamera-, Randabstands- und andere sichtbare
Änderungen erneuern den Puffer.

Unter der Draufsicht stehen von links nach rechts **Turmmitte**,
**Warteposition**, die vertikale **Farblegende** und die vertikale
**Bedien-Legende**. Die Reset-Buttons rechts neben **Automatisch** setzen die
jeweilige Position wieder auf Automatik. **Positionen zurücksetzen** liegt
links unten innerhalb der Vorschau und setzt beide Positionen auf Automatik;
der Button bleibt ohne manuelle Position ausgegraut. Statusmeldungen und
Übernahme-/Abbruchaktionen bleiben darunter.

Der **Randabstand** ist standardmäßig 5 mm und im Editor zwischen 5 und
100 mm einstellbar. Die türkise gestrichelte Innenkontur zeigt diesen Abstand
zu den tatsächlichen äußeren Bettkanten, auch bei unregelmäßigen Bettformen.
Die Prüfung berücksichtigt beim Turm zusätzlich seinen vollständigen Fuß.
Die Einstellung ist dieselbe wie **Druckbettrandabstand** in den erweiterten
Postprozessor-Einstellungen. Änderungen gelten zunächst nur im Dialog und
werden erst mit **Übernehmen** gemeinsam mit den Positionen übertragen.

**Abbrechen** ist rot und jederzeit verfügbar; es erhält Einstellungen und
ein vorhandenes G-Code-Ergebnis. Erst **Übernehmen** ändert die Positionen
und verwirft die bisherige Vorschau. Die Originalquelle wird vor der Übernahme
erneut auf Veränderungen geprüft. Quellen-, Profil- oder relevante
Einstellungsänderungen schließen den Editor. Wenn kein Turm benötigt wird,
weist der Editor darauf hin und bietet keine Positionsübernahme an.
Es werden keine Slicer-Dateien oder -Profile verändert.

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
2. Nur bei einem Zeitdefizit der Originalschicht die außerhalb von Modell und
   Turm liegende freie Warteposition anfahren. Erreicht oder überschreitet das
   Original allein die Mindest-Layerzeit, führt der Weg direkt zum Turm;
   Warteplatzanfahrt, `M400` und `G4` entfallen in dieser Schicht. Ein
   Sichtbarkeitsgraph mit kürzester Wegsuche führt bei Bedarf um die im Profil
   definierten Sperrflächen herum; auch die tatsächliche Bettkontur begrenzt
   den Weg. Ohne nachgewiesenen Weg wird die Bearbeitung abgebrochen.
3. Bei angefahrener Warteposition mit `M400` die Ankunft abwarten und nur das
   verbleibende Defizit als `G4 P...` ausgleichen. Lange Pausen werden in höchstens 60 Sekunden lange
   Befehle aufgeteilt. `G4 P0` markiert ohne zusätzliche Pause denselben
   Stillstand auch in ursprünglich defizitären Schichten, deren Fahr-/Turmzeit
   bereits ausreicht. Die Entscheidung für den direkten Weg basiert auf der
   Originalzeit und bleibt bei der anschließenden Restwarteberechnung stabil.
4. Bei weiterhin angehobener Düse den geprüften Weg zum Turm fahren. Erst
   dort absenken und den Rückzug ausgleichen. Die zusätzliche Prime-Menge
   wird während der ersten äußeren Umrundung verteilt; anschließend folgen
   die weiteren Fuß- beziehungsweise Wandbahnen. Diese Bahnen nehmen Oozing auf.
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

Der Startwinkel wandert je Schicht um den Goldenen Winkel
`π × (3 − √5)`. Dadurch gibt es keine kurze periodische Wiederholung der
Prime-/Nahtposition. Derselbe Winkel gilt für alle Ringe einer Schicht.
Anfahrt, tatsächlicher Bahnbeginn und Rückfahrt verwenden denselben geprüften
Punkt. Die Umrundungsrichtung bleibt konstant; Originalmodellbahnen und
Druckreihenfolge bleiben erhalten. Die gesamte erste Umrundung verteilt die
zusätzliche Prime-Menge ohne Stillstandsblob; ihr zusätzlicher Volumenstrom
wird bei der Geschwindigkeit berücksichtigt.

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

Direkt unter der Vorschau steht ausschließlich die Farblegende mit Modell,
Turm, Warteposition, Warteplatzfahrten, Modell-/Turmfahrten und Brim. Zwischen
benachbarten Einträgen liegen 15 Pixel; bei minimaler Breite stehen die Einträge
einspaltig untereinander. Die Fahrwege werden innerhalb der Vorschau bedient.

- Die **Warteposition** bleibt als gelbe Markierung sichtbar.
- **Warteplatzfahrten**: violette gestrichelte Wege vom
  Modell zum Warteplatz und weiter zum Turm.
- **Modell-/Turmfahrten**: rosa gestrichelte direkte Anfahrt in
  Schichten ohne Originaldefizit und Rückfahrt vom Turm zum Modell samt
  zugehöriger lokaler Turmfahrten. Dieselbe
  Zuordnung gilt in der Draufsicht des Positionseditors.

Legenden verwenden sichtbare Farbfelder mit denselben Farben wie die
zugehörigen Vorschauobjekte beziehungsweise Diagrammreihen.
Die Farblegende unter der Vorschau nutzt deren gesamte Breite. Ihre Einträge
stehen in Leserichtung nebeneinander und wandern bei Platzmangel einzeln in
die nächste Zeile; die Höhe berücksichtigt sämtliche entstandenen Zeilen.
Am Druckbettursprung sind die positiven Achsen mit **X+** in Rot, **Y+** in Grün
und **Z+** in Blau gekennzeichnet.
Beide Fahrweggruppen enthalten ihre jeweiligen Sicherheitshübe. Die Zuordnung
wird beim Rekonstruieren der tatsächlich ausgegebenen Befehle vorgenommen;
die G-Code-Befehle selbst ändern sich dabei nicht. **Warten** markiert die
tatsächliche angehobene Position eines `G4`-Befehls; ohne nötige Pause bleibt
der geplante XY-Punkt sichtbar. Originalobjekt und Turm bleiben sichtbar.
Die Schalter ändern ausschließlich die Darstellung und starten keine
Neuberechnung. Auch die Einpassung und Objektpositionen bleiben beim Umschalten
stabil. Externe Slicer können Pausen und Leerfahrten
je nach Vorschaufilter anders oder gar nicht darstellen. Der G-Code enthält
die Fahrtbefehle unabhängig von deren Darstellung.

### Layerzeiten und Layerauswahl

**Layerzeiten** erscheinen mit einer gültigen Vorschau standardmäßig geöffnet
und verschwinden beim Verwerfen wieder. Auch der zugehörige Symbolbutton
bleibt ohne vorhandene Vorschau ausgeblendet. Der quadratische Symbolbutton ganz
rechts in der Kamera-Buttonleiste über der eigentlichen Vorschau blendet sie ein oder aus. Das
generische Panel-Symbol ist ein eigenes SVG-Asset. Die Darstellung liegt direkt
auf der Vorschaufläche und besitzt keinen gesonderten Dropdown-Rahmen.
Sie steht rechts
neben der schmaleren Vorschau und übernimmt die Höhe der gesamten linken
Vorschau einschließlich Kameraleiste, Anzeigefunktionen und Legende. Die
Kameraleiste endet am rechten Rand der Vorschau; die Diagrammspalte nutzt auch
den Platz rechts daneben. Die Vorschauhöhe wird
an die verfügbare Fensterhöhe angepasst, damit dieser Bereich vollständig
sichtbar bleibt. In besonders kleinen Fenstern bleiben alle Inhalte über
den Scrollbereich erreichbar; bei zu wenig Breite werden die Bereiche gestapelt.

Die Layer laufen von unten nach oben an der rechten vertikalen Achse; nur der
Achsenname **Layer** ist um 90 Grad nach links gedreht. Die Zahlen bleiben
horizontal lesbar. Die horizontale Achse zeigt die Zeit in Sekunden.
Originalzeit, zusätzliche Bewegungszeit und Restwartezeit besitzen getrennte
Farben. Eine gestrichelte grüne Linie und ein kleines Dreieck auf der Zeitachse
markieren die wirksame Mindest-Layerzeit. Nur das Dreieck bietet einen kurzen
Hover-Hinweis mit der eingestellten Zeit.

**Logarithmische Zeitskala** ist standardmäßig aktiv: `log(1 + Sekunden)` bildet
auch 0 ab und hält kurze Schichtzeiten trotz langer Standfußschichten lesbar.
Alle Werte und Ausreißer bleiben enthalten; die Grenzpunkte der gestapelten
Zeitanteile werden gemeinsam transformiert. Abschalten stellt die lineare
Skala her. Die darunterliegende Farblegende steht einspaltig. Die Diagrammspalte
benötigt regulär 210 Pixel; größere Schrift kann ihre Mindestbreite erhöhen.

**Zeitskala normalisieren** steht direkt unter der logarithmischen Skala.
Bei aktiver Option bestimmt Layer 1 weder die Skalenbreite noch die Farbbalken;
die Skala verwendet die übrigen Layer und mindestens die eingestellte
Mindest-Layerzeit. Layer 1 bleibt als auswählbarer Layer samt vollständiger
Zeitangabe und unveränderten Berechnungs- und Exportdaten erhalten. Es entsteht
kein zusätzlicher Legendeneintrag. Beide Skalenoptionen lassen sich unabhängig
kombinieren. Vor beiden Checkboxen steht dasselbe Informationssymbol mit einem
passenden Hover-Hinweis zur jeweiligen Skala.

Bei neuen Vorschauzeiten und beim Zurücksetzen der Vorschau ist die
Normalisierung aktiviert, wenn Layer 1 allein die längste Gesamtzeit aus
Original, zusätzlicher Bewegung und Restwartezeit besitzt. Bei Gleichstand,
einem späteren Höchstwert oder nur einem Layer bleibt sie standardmäßig aus.
Die Diagrammübersicht berücksichtigt bei zusammengefassten Bildschirmzeilen
die verbleibenden Layer und hält den Bereich von Layer 1 ungefärbt.

Der Greifer auf der rechten Layerachse ersetzt den gesonderten Schieberegler.
Ziehen, Klick ins Diagramm, Auf-/Ab-Tasten und Layernummer wählen denselben
Layer. Das Nummernfeld wächst mit dem aktuellen Wert und bleibt auf 1 bis zur
Layeranzahl des Pre-Slice begrenzt. Seine Breite berücksichtigt den tatsächlichen
Texteingabebereich einschließlich Schrift und Pfeiltasten. Standard ist der
letzte Layer mit vollständig dargestelltem Modell. Der Resetbutton rechts
neben dem Nummernfeld stellt diesen Zustand wieder her und setzt auch den
Achsgreifer auf den letzten Layer. Unter dem Diagramm stehen die Auswahl
und eine kompakte Zeile mit Layer, Höhe und Gesamtzeit. Ausführliche
Ergebnisdaten bleiben in den Exportberichten.

Die Vorschau hebt den gewählten Layer mit seinen normalen Farben hervor.
Darunterliegende Modell-, Turm- und Brimbahnen bleiben mit leicht reduzierter
Farbsättigung und 65 Prozent Deckkraft sichtbar. Oberhalb liegende Layer bleiben
während dieser Auswahl ausgeblendet.
Zusätzliche Fahrten einschließlich ihrer Z-Hops und Warteposition werden über
ihre tatsächliche Schichtzuordnung gefiltert. Kamera, Einpassung und
Objektkoordinaten bleiben unverändert. Klicks und Kamerabedienung in der
Postprozessor-Vorschau sowie das Ausblenden der Layerzeiten behalten Layer und
Fahrwege bei. Die Auswahl ändert keinen G-Code und
startet keine Berechnung. Einstellungsänderungen oder Fehler entfernen das
Diagramm zusammen mit der ungültig gewordenen Vorschau.

Rechts unten in der Vorschau bestimmt der Umschalter **Alle / Einzeln** den Anzeigemodus
der Fahrwege. **Alle** zeigt ihre Fahrwege bis einschließlich
des gewählten Layers; ohne aktive Layerbegrenzung sind alle Layer sichtbar.
**Einzeln** zeigt nur die Fahrwege des gewählten Layers und ist der Standard.
Auch bei vollständiger Modelldarstellung bleibt dabei die gewählte
Fahrwegschicht wirksam. Die Zuordnung verwendet auch bei Z-Hops den Drucklayer.
Der Auswahlhintergrund gleitet beim Umschalten horizontal zur anderen Seite.
Der Modus lässt sich auch mit Leertaste und Links-/Rechtstasten bedienen.
Die beiden Fahrweggruppen werden gemeinsam über **Fahrwege anzeigen** geschaltet;
ein Moduswechsel verändert weder Kamera, Layerauswahl noch G-Code.

**Vorschau zurücksetzen** links unten innerhalb der Vorschau stellt die
eingepasste 3/4-Ansicht mit möglichst nebeneinander sichtbaren Objekten her.
Warteposition, Fahrwegschalter, Anzeigemodus, logarithmische Skala und Layerauswahl erhalten
ihre Standardwerte; die Navigation wird aktiviert. Die Sichtbarkeit der
Diagrammspalte bleibt erhalten. Direkt darüber schaltet **Transparenz aktiv**
beziehungsweise **Transparenz inaktiv** die vorhandene Färbung und reduzierte
Deckkraft der unteren Modell- und Fahrweglayer um. Bei aktiver Transparenz
verwendet auch die Gesamtansicht dieselbe Darstellung wie die Diagrammauswahl
des letzten Layers. Die Layerauswahl über Diagramm oder Nummernfeld aktiviert
die Transparenz automatisch. Ausschalten stellt die normalen Farben und die
volle Deckkraft wieder her; ein ausgewählter Layer und die Kamera bleiben
erhalten. Der Layerreset zeigt das vollständige Modell und behält den
Transparenzzustand bei. Eingeschaltet ist die Schaltfläche dunkelgrün;
ausgeschaltet dunkelblau. Beide linken Schaltflächen sind gleich breit und
schließen bündig und ohne Rundungen mit dem Vorschaurand ab. Diese Funktionen
ändern keine Druckeinstellungen und starten keine G-Code-Erzeugung.

Direkt über dem Umschalter **Alle / Einzeln** schaltet **Fahrwege anzeigen** beide
Fahrweggruppen gemeinsam ein oder aus. Der gewählte
Anzeigemodus **Alle** oder **Einzeln** bleibt dabei erhalten.
Der Schalter ist standardmäßig eingeschaltet und dunkelgrün; ausgeschaltet
erscheint er dunkelblau. Beim Ausschalten gleitet der Modusumschalter nach unten
aus der Vorschau, während **Fahrwege anzeigen** zur rechten unteren Ecke wandert.
Beim Einschalten läuft die Bewegung umgekehrt. Die 240-ms-Animation beginnt bei
einem schnellen Richtungswechsel an der aktuellen Position; die Vorschau
schneidet die Bedienelemente an ihrer Grenze ab. Ohne gültige Vorschau bleibt
der Modusumschalter verborgen. Kamera, Modell-Layerauswahl, Färbung und G-Code
bleiben unverändert. **Vorschau zurücksetzen** und die allgemeinen Standardwerte
aktivieren die Fahrwege und stellen den Anzeigemodus **Einzeln** wieder her;
Transparenzumschaltung und Layerreset behalten den Modus bei.
Die beiden rechten Bedienelemente haben dieselbe Breite und eckige Kanten.
Der aktive Teil des gleitenden Umschalters ist dunkelgrün.
Ohne gültige Vorschau ist die Schaltfläche nicht bedienbar. Die Projektion
der vollständigen Fahrweggruppen wird beim Layerwechsel wiederverwendet und
bei Änderungen von Szene oder Kamera neu aufgebaut.

Der Brim bleibt eine eigene blaue Geometriegruppe. Seine hintere Hälfte wird
vor dem Turm, seine vordere danach gezeichnet, sodass sich Turm und Brim
entsprechend der Blickrichtung verdecken. Die Aufteilung erfolgt an der
Tiefenebene durch die Turmachse und erhält die gebündelte Linienzeichnung.

Sehr lange Reihen werden im Diagramm auf Bildschirmzeilen zusammengefasst;
der Vertreter mit der größten Restwartezeit erhält kritische Defizite. Die
Schichtauswahl und der numerische Zeitbericht verwenden weiterhin alle
einzelnen Schichten.

Skala und Übersicht werden bis zu Größen-, Daten- oder Skalenänderungen
gepuffert. Beim Ziehen bewegt sich der Greifer direkt; die 3D-Vorschau erhält
höchstens alle 33 ms den neuesten Layer und beim Loslassen sofort den Endwert.
Die Kameraberechnung wird bei unveränderter Szene und Ansicht wiederverwendet.
Die projizierten Einpassungsgrenzen bleiben bei Verschieben, Zoom und
Größenänderungen erhalten. Größere Liniengruppen werden mit unveränderter
Rechenreihenfolge gebündelt projiziert; ein begrenzter Koordinatenpuffer
verwendet die Quelldaten bei Kamerabewegungen erneut. Kleine Gruppen werden
direkt ohne temporäre Qt-Punktobjekte projiziert. Linienauswahl, Reihenfolge,
Farben und Strichbreiten bleiben dabei gleich.
Ein begrenzter Layerindex vermeidet das wiederholte Durchsuchen sämtlicher
Modell- und Fahrwegsegmente; die genaue Höhen-Toleranz bleibt erhalten.
Für die unteren Layer werden die bereits projizierten Druckbahnen wiederverwendet.
Die Gruppierung prüft gemeinsame Höhen einmal je Höhenwert und behält die
Zuordnung angehobener Fahrwege zu ihrem Drucklayer bei.
Bis zu sechs Raster-Zwischenstände verkürzen den Bildaufbau beim Ziehen;
ihre Anzahl sinkt bei großen oder hochauflösenden Vorschauen entsprechend dem
Bildspeicherbudget. Kamera-, Größen- und Szenenänderungen erneuern diese Puffer.

Die Ansicht startet mit vollständig eingepasstem Bett und zeigt X+/Y+ am
G-Code-Ursprung. Wie im iterativen Modus gibt es **3/4-Ansicht**,
**Vorderansicht**, **Seitenansicht** und **Draufsicht**, zusätzlich **Einpassen**
für das vollständige Druckbett. **3/4-Ansicht** sucht anhand der XY-Umrisse der
dargestellten Modell- und Turmbahnen eine Richtung mit möglichst großer
horizontaler Trennung. Die Richtung wird pro Szene wiederverwendet; die
Objektkoordinaten ändern sich dabei nicht. **Draufsicht** legt X nach rechts
und Y nach oben/hinten. Die Mausnavigation ist im Postprozessor in der
mehrspaltigen Ansicht standardmäßig aktiviert:
Links ziehen dreht, rechts oder mittig ziehen verschiebt, das Mausrad zoomt
zum Mauszeiger. Der Punkt unter dem Zeiger bleibt beim Vergrößern und
Verkleinern an derselben Bildschirmposition, auch nach dem Verschieben
der Ansicht. An den Zoomgrenzen verschiebt sich das Bild nicht weiter.
Die Drehrichtung beider Mausachsen ist auf die G-Code-Ansicht abgestimmt,
damit sich das Ziehen wie in der Vorschau der iterativen Methode anfühlt. Verschieben
und Zoom verwenden die gemeinsame Steuerung.
Symbol oder Statusschalter schalten die Mausnavigation um. Bei deaktivierter
Navigation erreicht das Mausrad die umgebende Seite. Ansichtsbuttons bleiben
unabhängig davon bedienbar.
Beim Wechsel der gesamten Einstellungen-/Vorschauansicht in eine Spalte wird
die Navigation genau einmal deaktiviert, damit das Mausrad die Seite scrollt.
Eine manuelle Aktivierung in dieser Ansicht bleibt während weiterer
Layoutaktualisierungen erhalten. Beim Vergrößern wird der vorherige Zustand
wiederhergestellt; eine in der einspaltigen Ansicht vorgenommene Aktivierung
bleibt dabei wirksam. Ein erneuter Umbruch in eine Spalte deaktiviert sie wieder.
Sehr große Bahnlisten werden nur für die
Darstellung ausgedünnt; der exportierte G-Code enthält alle erzeugten Bahnen.

## Implementierung und Abnahme

Die internen Modulnamen und gespeicherten Methodenkennungen behalten aus
Kompatibilitätsgründen ihre bisherigen `preprocessor`-Kennungen. Oberflächentexte,
Exportdateinamen und neue G-Code-Markierungen verwenden Postprozessor/Postprocessor.
Alte G-Code-Markierungen bleiben für die Erkennung bereits bearbeiteter Dateien
lesbar; solche Dateien dürfen keinen zweiten Turm erhalten.

`preprocessor.py` enthält unveränderliche Einstellungen/Requests, Planung,
Zeitberechnung und Export. `preprocessor_placement.py` indiziert Originalbahnen
und prüft Modell-/Turmabstände. `preprocessor_travel.py` plant die Fahrwege
und prüft eigene Hindernisse gegen Originalfahrten. `preprocessor_state.py`
erfasst den Flusszustand unabhängig von den Zeitberechnungsdialekten.
`preprocessor_toolpaths.py` erzeugt die Bodenschichten und den ringförmigen
Fußquerschnitt; `preprocessor_features.py` kapselt Slicer-Kennzeichnungen und
die Wiederherstellung der ursprünglichen Vorschau-Metadaten.
`preprocessor_profiles.py` löst Profilvorgaben und
Druckkopf-Hüllen auf; `preprocessor_safety.py` validiert eigene Sperrrechtecke.
`gui/preprocessor_positions.py` enthält den Positionseditor mit verwalteter
Hintergrundprüfung; `PreprocessorService.placement_context()` stellt den
unveränderten Platzierungskern ohne Dateierzeugung bereit.
`gui/widgets/preview_busy_overlay.py` enthält die gemeinsame Ladeansicht.
`gui/widgets/preprocessor_widgets.py` enthält Koordinatenpaar, Farblegende und
inhaltsabhängigen Footer sowie das automatisch bemessene Layernummernfeld;
`gui/widgets/preprocessor_time_chart.py` das Layerzeitdiagramm.
`gui/widgets/preview_layer_context.py` puffert die gedämpft dargestellten unteren
Layer als begrenzte Raster-Zwischenstände aus bereits projizierten Linien.
`gui/preprocessor_controls.py` stellt gemeinsame
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
- Der vollständige STL-/Pre-Slice-/Postprozessor-/Exportablauf lief erfolgreich
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
