# Präprozessor: Abkühlpausen und hohler Abstreifturm

## Bedienung

Nach STL-Auswahl, Slicer-/Profilbestätigung und Pre-Slice steht neben
**Automatisch** und **Manuell** die dritte Methode **Präprozessor** bereit.
Unterstützt werden Anycubic Slicer Next, Bambu Studio, OrcaSlicer und PrusaSlicer.
Dieser Modus bearbeitet den bereits vorhandenen Pre-Slice; eine Änderung der
Turmeinstellungen startet keinen weiteren Slicerlauf.

**G-Code und Vorschau erzeugen** startet die Berechnung ausdrücklich.
Einstellungsänderungen verwerfen das alte Ergebnis und starten keine Berechnung.
Links stehen die Einstellungen, rechts die Vorschau. Die Bereiche schließen
ohne Außenabstände und Rundungen aneinander und an den Fensterrand an.
Die Trennlinie besitzt einen sichtbaren Griff, einen horizontalen Ziehcursor
und eine dezente Hervorhebung bei Mauskontakt. Ziehen ändert beide Breiten
einschließlich der Vorschau; deren Höhe wächst proportional zur Breite.
Doppelklick setzt die Trennlinie exakt in die horizontale Mitte zurück.
Diese Halbierung bleibt auch bei anschließenden Größenänderungen erhalten.
Die Trennlinie stoppt an den Mindestbreiten der Bedienelemente. Einstellungsnamen,
Schalterbeschriftungen und Vorschau-Buttons bleiben ohne zusätzliche Umbrüche
lesbar. Mehrzeilige Hinweise und Ergebnistexte passen sich der Spaltenbreite an.
Schmale Fenster stapeln die Vorschau über den Einstellungen; beim erneuten
Verbreitern wird die gewählte Aufteilung wiederhergestellt. Die automatische
Methode behält ihre feste Halbierung. Alle Einstellungen besitzen links
ein Hover-Hinweis-Icon mit kurzer Erklärung und rechts einen Reset im gemeinsamen
Design. Bei Automatikzeilen folgen rechts auf den Funktionsnamen der Text
**Automatisch**, die Checkbox, das Eingabefeld und der Reset. Bei **Hohler Turm**
steht die Checkbox hinter dem Namen; der Reset bleibt am rechten Rand.
Turmhöhe, Schaftdurchmesser, Standfußbreite, Turm- und Warteposition besitzen jeweils eine
eigene Automatik. Automatische Positionen werden als kompakte Zeile dargestellt;
erst nach Abschalten der jeweiligen Automatik erscheinen X- und Y-Koordinaten.
Deaktivieren übernimmt den zuletzt berechneten Wert zur
manuellen Bearbeitung, soweit er im zulässigen manuellen Bereich liegt.
Automatisch berechnete Eingabefelder sind deaktiviert und grau dargestellt.
Nach der Erzeugung zeigen sie den verwendeten Wert. Ohne aktuelles Ergebnis
steht dort ein Gedankenstrich; nach Einstellungsänderungen werden alte Werte
nicht weiter als aktuell angezeigt. Wird kein Turm benötigt, zeigen seine
automatischen Maße 0,00 und nicht verwendete Positionen einen Gedankenstrich.
Die Einstellungen bleiben während der Sitzung erhalten;
sie werden derzeit nicht als globale Benutzervorgaben gespeichert.

### Profilvorgaben und Geschwindigkeitsgrenzen

Mindest-Schichtzeit, Turmdrucktempo, Fahrtempo sowie gekoppelte Rückzugslänge
und Rückzugstempo besitzen ebenfalls eine standardmäßig aktive Automatik.
Sie liest ausschließlich das bestätigte Profil des aktiven Extruders:

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

**Erweiterte Einstellungen anzeigen** öffnet Wandlinien, Voll-/Hohlbauweise,
Randabstand, Turmdruck-/Fahrgeschwindigkeit, Rückzug, Rückzugsgeschwindigkeit,
Sicherheitshub, Warteabstand und zusätzliche Prime-Menge. Standard ist ein hohler Turm mit
zwei Wandlinien, einem gefüllten konkaven Standfuß und mindestens zwei
geschlossenen Bodenlagen. **Wandlinien** erlaubt 1–3 Linien und ist bei einem
vollständig gefüllten Turm deaktiviert. Bei geänderten Einstellungen
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
- Der Standfuß verwendet dieselbe konkave Kurve und Höhenregel wie die
  automatische Methode mit 100 % Füllung: mindestens 6 mm, 22 reale
  Schichtintervalle oder 2,5 % der Modellhöhe, begrenzt durch die Turmhöhe.
  Soweit darüber noch Schichten verfügbar sind, endet die Kurve fünf
  Schichten später. Ihr Beginn liegt auf der ersten Schicht; der letzte
  Kurvenquerschnitt geht in den angegebenen Schaftdurchmesser über. Der Fuß
  wird bis dahin gefüllt, damit stark nach innen versetzte Wandbahnen
  unterstützt bleiben. Darüber ist der Schaft hohl; eine obere Deckfläche
  entfällt. Auch bei gleich breitem Fuß und Schaft schließen die ersten
  zwei Schichten den Boden.
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
  Zu enge manuelle Durchmesser werden abgewiesen, automatische Durchmesser
  lassen mindestens eine Linienbreite für den inneren Hohlraum frei.
  Die ausgewählten 1–3 Wandlinien werden direkt als G-Code-Bahnen erzeugt.
  `wall_loops` und `perimeters` des Profils beeinflussen ihre Anzahl nicht;
  es werden keine objektspezifischen Slicer-Einstellungen gesetzt oder
  Profilwerte verändert.
- Die automatische Position sucht in einem Raster von 33 × 33 Kandidaten.
  Modell-, Rand- und Sperrflächenabstände begrenzen die gültigen Kandidaten.
  Mit vollständigen Profilangaben werden kurze Gesamtfahrwege von
  repräsentativen Schichtendpunkten bevorzugt. Bei unvollständigen
  Druckkopfangaben hat größerer Modellabstand Vorrang.
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

### Druckkopf-Freihüllen und fehlende Geometrieangaben

**Druckkopf-Freihüllen anzeigen** blendet die verwendeten unteren und oberen
Hüllen am Warteplatz und Turm-Anfahrpunkt ein: blau gestrichelt für Profilwerte,
gelb für Ersatzschätzungen. Die Schichtauswahl verschiebt die Hüllen auf die
zugehörige Fahrhöhe; bei allen Schichten wird die letzte Turmschicht gezeigt.
Das sind Profilannahmen, keine vermessene Maschinengeometrie. Ein sichtbarer
Hinweis benennt den Prüfumfang; zusätzliche Grenzen stehen im Tooltip und in
den Exportberichten. Bei abgewiesenen Turmpositionen kann die Fehlermeldung
die betreffende Originalzeile und betroffene Freihülle nennen. Firmwareinterne
Start-, End- und Referenzabläufe bleiben nur eingeschränkt prüfbar.

Die Prüfung verwendet konservative zylindrische Freihüllen statt eines
vermeintlich exakten, nicht vorhandenen Druckkopf-Meshs. Der untere Bereich
nutzt `extruder_clearance_radius` ab Düsenhöhe. Weiter ausladende Teile
berücksichtigen zusätzlich `extruder_clearance_max_radius` und
`extruder_clearance_dist_to_rod`; die größte gültige Radiusangabe gilt.
Für die obere Hülle wird die niedrigste gültige Angabe aus
`extruder_clearance_height` und `extruder_clearance_height_to_rod` verwendet.
Die Deckelhöhe ist kein Ersatz für die Freihöhe des unteren Kopfbereichs.
Originale spätere Bewegungen werden gegen den bereits aufgebauten Turm
einschließlich beider Hüllen geprüft. Liegt ein Querträger bei einer späteren
niedrigen Originalfahrt unter der aufgebauten Turmhöhe, umfasst die Prüfung
zusätzlich über die Bettbreite reichende Hüllstreifen. Ohne eindeutig
bestätigte Ausrichtung werden beide Achsrichtungen konservativ berücksichtigt.
Die maximale Hülle erweitert die
Abstände zu Druckbett-Sperrflächen auch auf den neuen Fahr- und Druckbahnen.

Bei fehlenden, unbrauchbaren oder nur teilweise vorhandenen Angaben erscheint
ein sichtbarer Hinweis in der Vorschau und im Exportbericht. Die Ersatzhülle
verwendet mindestens 70 mm Radius, sonst 30 % der kürzeren Bettseite bis
100 mm; größere bekannte Radien bleiben erhalten. Eine unbekannte Freihöhe
wird konservativ als 0 behandelt. Der zusätzliche Z-Hop beträgt mindestens
2 mm. Turm- und Warteplatz erhalten vergrößerte Modellabstände; für den
Warteplatz stehen bei Bedarf zusätzliche Bett-Rasterkandidaten bereit.
Alle gewählten Hin- und Rückwege müssen die Prüfung bestehen. Ohne zulässige
Kombination wird kein Export freigegeben.

Die Bettkontur beschreibt den zulässigen Düsen-Bewegungsbereich; ein
Druckkopf darf konstruktionsbedingt darüber hinausragen. Physische Hindernisse
müssen durch Profil- oder eigene Sperrflächen abgebildet sein. Ersatzhüllen
sind eine vorsichtige Schätzung, keine Messung und kein Nachweis für unbekannte
Bauformen, Umbauten oder undokumentierte Hindernisse.

### Eigene Sperrflächen

**Eigene Sperrflächen bearbeiten …** öffnet einen eigenen, vergrößerbaren
Editor mit Druckbett-Draufsicht und den Originalmodellbahnen. Links ziehen
zeichnet ein Rechteck; Ziehen in einer Fläche verschiebt sie, Ziehen an ihren
Ecken ändert ihre Größe. Mausrad zoomt, rechte oder mittlere Maustaste
verschiebt die Ansicht. **Einpassen**, **Rückgängig**, **Auswahl löschen**
und **Eigene Flächen leeren** stehen direkt bereit. Entf löscht, Strg+Z macht
rückgängig; Escape verwirft einen laufenden Ziehvorgang.

Profilflächen bleiben rot und unverändert, eigene Flächen sind orange.
Eine gestrichelte Kontur zeigt den zusätzlichen Druckkopf-Abstand der Auswahl.
Koordinaten, Bettursprung und Bettform werden nicht umgerechnet oder zentriert.
Es sind höchstens 64 Rechtecke mit mindestens 0,2 mm Kantenlänge möglich.
**Übernehmen** verwirft ein vorhandenes Ergebnis und übernimmt die Flächen;
**Abbrechen** erhält die bisherigen Einstellungen. Ein Wechsel von Quelle
oder Druckbett verwirft die eigenen Flächen. Sie gelten nur für die Sitzung.

Die Flächen begrenzen Turm, Warteplatz und alle zusätzlichen Fahrwege. Auch
Originalbewegungen müssen den unbekannt hohen eigenen Hindernissen
einschließlich Druckkopf-Abstand ausweichen. Kollidiert der unveränderte
Original-G-Code bereits damit, wird die Bearbeitung gesperrt: Dann muss die
Fläche korrigiert oder das Modell im Slicer neu platziert werden.
Spätere Firmware-Referenzfahrten sind bei eigenen Sperrflächen ebenfalls
gesperrt, weil ihr tatsächlicher Weg und die Hindernishöhe unbekannt sind.
In diesem Fall ist eine Quelle mit bekannter Endsequenz ohne erneutes Homing
erforderlich. Start-/Homing-Makros vor der Modellablage werden unverändert
aus der bestätigten Quelle übernommen; unbekannte Firmwareabläufe lassen
sich damit nicht als vollständige Maschinen-Kollisionsprüfung ausweisen.

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

Unter der Vorschau stehen drei unabhängige Schalter mit Hinweis und Einzelreset:

- **Warteposition anzeigen**: gelbe Markierung, standardmäßig sichtbar.
- **Fahrwege zum/vom Warteplatz anzeigen**: violette gestrichelte Wege vom
  Modell zum Warteplatz und weiter zum Turm, standardmäßig ausgeblendet.
- **Fahrwege Modell ↔ Turm anzeigen**: rosa gestrichelte Rückfahrt vom Turm
  zum Modell samt zugehöriger lokaler Turmfahrten, standardmäßig ausgeblendet.

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

### Schichtzeitdiagramm und Schichtauswahl

Unter der Vorschau zeigt das Diagramm Originalzeit, zusätzliche Bewegungszeit
und Restwartezeit getrennt. Eine gestrichelte grüne Linie markiert die
wirksame Mindestzeit. Klick ins Diagramm, Pfeiltasten, Schieberegler und
Schichtnummer wählen dieselbe Schicht. Der Text nennt ihre Höhe und alle
Zeitanteile einschließlich Gesamtdauer.

Die Vorschau zeigt dann ausschließlich die Ablagebahnen dieser Schicht.
Zusätzliche Fahrten einschließlich ihrer Z-Hops und Warteposition werden über
ihre tatsächliche Schichtzuordnung gefiltert. Kamera, Einpassung und
Objektkoordinaten bleiben unverändert. **Alle Schichten anzeigen** stellt
die vollständige Ansicht wieder her. Die Auswahl ändert keinen G-Code und
startet keine Berechnung. Einstellungsänderungen oder Fehler entfernen das
Diagramm zusammen mit der ungültig gewordenen Vorschau.

Sehr lange Reihen werden im Diagramm auf Bildschirmspalten zusammengefasst;
der Vertreter mit der größten Restwartezeit erhält kritische Defizite. Die
Schichtauswahl und der numerische Zeitbericht verwenden weiterhin alle
einzelnen Schichten.

Die Ansicht startet mit vollständig eingepasstem Bett und zeigt X+/Y+ am
G-Code-Ursprung. Wie im automatischen Modus gibt es **3/4-Ansicht**,
**Vorderansicht**, **Seitenansicht** und **Draufsicht**, zusätzlich **Einpassen**
für das vollständige Druckbett. **Draufsicht** legt X nach rechts und Y nach oben/hinten. Die Ansicht lässt sich
drehen, verschieben und zoomen. Sehr große Bahnlisten werden nur für die
Darstellung ausgedünnt; der exportierte G-Code enthält alle erzeugten Bahnen.

## Implementierung und Abnahme

`preprocessor.py` enthält unveränderliche Einstellungen/Requests, Planung,
Zeitberechnung und Export. `preprocessor_placement.py` indiziert Originalbahnen
und prüft Modell-/Turmabstände. `preprocessor_travel.py` plant die Fahrwege
und prüft eigene Hindernisse gegen Originalfahrten. `preprocessor_state.py`
erfasst den Flusszustand unabhängig von den Zeitberechnungsdialekten.
`preprocessor_profiles.py` löst Profilvorgaben und
Druckkopf-Hüllen auf; `preprocessor_safety.py` validiert eigene Sperrrechtecke.
`gui/preprocessor_exclusions.py` enthält den eigenständigen Sperrflächeneditor,
`gui/widgets/preprocessor_time_chart.py` das Schichtzeitdiagramm.
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
