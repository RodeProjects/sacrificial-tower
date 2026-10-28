# Auffanggeometrie und Wischablauf

Der Postprozessor verwendet eine flache geschlossene Kapsel mit zwei parallelen
geraden Seiten und abgerundeten Enden. Die breite Fangseite zeigt zum Warteplatz,
ein mittiger zweibahniger Steg verbindet die Seiten und endet zur Modellseite. Der konkave Standfuß bleibt
außen erhalten; seine innere Begrenzung verjüngt sich unterstützt zum Schaft.
Bedienung und Export beschreibt der [Postprozessor](postprocessor.md).

## Auswahl der Form

| Form | Vorteil | Einschränkung |
|---|---|---|
| Hohler Rundturm | Geschlossen, gleichmäßige Richtungswechsel, geringer Wandaufwand | Kein breiter gerader Bereich mit einheitlichen Anfahrbedingungen |
| Hohles Rechteck | Breite gerade Fangseite, gut verteilbare Kontaktstellen | Richtungswechsel an den Ecken; große Tiefe verlängert den Druckweg |
| Offener Bogen/Trichter mit Ansatz | Breiter Einfangbereich, wenig Material | Freie Arme können nachgeben; wenig Trennung von Auffang- und Abfahrbereich |
| Offenes Zickzack | Mehrere mögliche Kontaktkanten hintereinander | Ein verbliebener Faden kann über mehrere spätere Druckbahnen verteilt werden |
| Geschlossene flache Kapsel | Gerade Fangseite, kurze Perimeter, geschlossene Enden, getrennte Abfahrt auf einem zweibahnigen Mittelsteg | Weniger Ablageraum als ein tiefer Turm; die Wirkung benötigt einen Probedruck |

Die Kapsel behält eine breite Kontaktzone, spart aber Tiefe und lange zusätzliche
Wischstege. Die geschlossenen gerundeten Enden stützen die langen Wände.
Ein kurzer zweibahniger Mittelsteg verbindet beide Seiten; die Fangbewegungen bleiben
seitlich davon. Der Druck soll weiterhin überwiegend durch eine echte Pause
gekühlt werden. Die Turmfläche wird deshalb nur mäßig mit dem Zeitdefizit
vergrößert und nicht auf vollständigen Zeitausgleich durch Drucken ausgelegt.
Die Auswahl ist konstruktiv begründet, keine allgemein nachgewiesene optimale
Form. Eine Ecke wirkt nicht automatisch als Schere. Die Düse fährt nicht
absichtlich gegen feste Wände.

## Geometrie und vorausschauende Bemessung

Die Turmbreite `D` bezeichnet die lange Achse der Kapsel. Der automatische
Richtwert verwendet das größte ursprüngliche Schichtzeitdefizit `R`:

`D = min(100 mm, max(12 mm, 0,10 × Turmhöhe, 12 mm × sqrt(1 + R / 90 s)))`

Die Tiefe beträgt zunächst `max(5 mm, 0,35 × D)`. Ausreichender Platz für die
Profil-Wandstärke und offene Kammern hat Vorrang. Beide Größen bleiben über den
Schaft konstant: Ein später größerer Bedarf muss bereits unten unterstützt
werden. Kontaktstellen und Prime-Mengen ändern sich dagegen während des Drucks.
Die Bemessung ist eine geometrische Reserve und keine Messung austretenden
Filaments. Längere Wartezeit bedeutet nicht zwingend proportional mehr Ooze.

Die konkave Fußflanke berücksichtigt eine verbreiterte lange Achse
(mindestens 14 mm, 110 % der Schaftbreite oder 25 % der Turmhöhe, anschließend
25 % Fußreserve) sowie mindestens 12 mm Tiefe oder 25 % der Turmhöhe.
Breite Erstschichtbahnen können zusätzliche Tiefe erfordern. Die Obergrenze
beträgt 150 mm. Die vorhandene konkave Höhenfunktion verändert beide Achsen
um denselben absoluten Betrag; echte parallele Wandversätze erhalten den
Linienabstand an den geraden Seiten und an den Enden.

Die ersten zwei Schichten sind geschlossene, zusätzlich verbreiterte Bodenplatten.
In der Fußautomatik erhalten sie das frühere Verhältnis von Bodenfläche zu
Schaftfläche der runden Form: Der frühere kreisförmige Referenzfuß verwendet
`min(150 mm, 1,25 × max(14 mm, 1,8 × D, 0,25 × Turmhöhe))` und dieselbe
Höhenkurve. Seine beiden Flächenverhältnisse werden auf die tatsächliche
Kapsel-Schaftfläche übertragen. Der Endradius der Kapsel wird dafür aus
`A = π × r² + 4 × s × r` berechnet; `s` ist die feste halbe Länge des geraden
Mittelteils. Bloß die lange Achse um denselben Faktor zu vergrößern würde die
Flächenreserve der flachen Form verfehlen. Die Bodenplatten werden mindestens
so groß wie die normale Fußflanke. Ab der dritten Schicht bleibt die sparsamere
konkave Kontur erhalten. Die Platzierungsprüfung und der Brim berücksichtigen
die vollständige größere Bodenplatte. Bei manueller Fußbreite gilt diese direkt
als Außenbreite der Fußkurve; die zusätzliche automatische Flächenreserve entfällt.

Darüber wird der äußere Fuß
mit vollständigen versetzten Konturen gefüllt; seine innere Begrenzung folgt
65 % der äußeren Aufweitung gegenüber dem Schaft. Dadurch bleibt unten mehr
Material und die gefüllte Wand wird nach oben dünner. Eine rückwärts berechnete
Stützgrenze reduziert diese Einsparung, wenn nötig: Die Innenkante darf sich
pro Folgeschicht höchstens um die halbe Schichthöhe und höchstens 30 % der
kleineren inneren Linienbreite nach innen verschieben. Die äußere konkave Kurve
bleibt unverändert. Eine obere Deckfläche entfällt.

Nach allen Außen- und Innenkonturen folgen zwei parallele Stegbahnen: zuerst
zur Warteplatzseite, dann zurück zur Modellseite. Der Abstand entspricht der
Profil-Linienbreite abzüglich der schichthöhenabhängigen Überlappung. Ihre Enden
binden an die Innenkanten der Wände an; eine erneute Extrusion quer durch alle
Wandlinien würde dort wiederholt Material aufschichten und entfällt.
Am Ende der Rückbahn erfolgt sofort der vollständige Profil-Rückzug, ohne
nochmals auf der weichen neuen Bahn vor und zurück zu fahren. Eine kleine
Höhenentlastung beträgt höchstens 0,05 mm, ein Viertel der Schichthöhe und den
gewählten Z-Hop. Anschließend führt genau ein Zug ohne Extrusion über die
Modellseite nach außen; erst dort wird der restliche Z-Hop ausgeführt.
Bei Z-Hop 0 entfällt auch die Höhenentlastung. Die vorhandene Rückzugslänge
wird nicht erhöht. Der Rückzug bleibt auf dem geprüften Weg zum Modell bestehen.
Für manuell sehr schmale Formen ohne Mittelsteg beginnt dieser Abziehweg an
der inneren Wand. Die Stegbreite verwendet die größte reguläre innere
Profil-Linienbreite; die Konturen behalten ihre schichtspezifischen Breiten.

Frische Stege und Wände können noch weich sein. Der Ablauf setzt daher keine
harte Schneidkante voraus und drückt die Düse nicht absichtlich in die neue
Oberfläche. Höhenentlastung, unmittelbarer Druckabbau und einmaliges Abziehen
sollen das Mitnehmen weichen Materials verringern; eine physische Trennung
oder vollständige Fadenfreiheit wird damit nicht nachgewiesen.

## Frühes Einfangen und verteilte Kontakte

Die automatische Platzierung bevorzugt die Reihenfolge
**Modell → Turm → Warteplatz**. Feste Hindernisse, Bettkontur und unveränderte
Originalfahrten bleiben maßgeblich. Passt diese Ausrichtung nicht, werden
andere sichere Richtungen geprüft. Die Kapsel richtet sich nach dem tatsächlich
gewählten Wartepunkt aus.

Nach einer Parkphase erreicht die Düse die gerade Fangseite mit Z-Hop. Erst
dort senkt sie auf die nominelle Höhe der neuen Turmschicht ab, weiterhin über
der vorherigen Schicht. Ein kurzer Zug führt über die vordere Wand in die seitliche
offene Kammer; dort folgt eine seitliche Bewegung ohne Extrusion. Der Faden
soll bereits an dieser ersten Kante haften oder sich lösen und in der Kammer
landen. Ein pauschales Überqueren sämtlicher Stege mit dem alten Faden entfällt.
Anschließend fährt die Düse mit Z-Hop zum getrennten Druckbeginn.

Im anfänglich massiven äußeren Fußbereich endet der Einfangzug bereits kurz
hinter den äußeren Wänden. Er überquert nicht den gesamten gefüllten Ring bis
zum späteren Schafthohlraum. Dieser Bereich muss massiv bleiben, damit die
konkav nach innen wandernden Außenbahnen weiterhin unterstützt sind.

Die Kontaktstellen wechseln spiegelbildlich: außen links, außen rechts, weiter
innen links, weiter innen rechts, bis zur Mitte. Danach beginnt die Folge neu.
Je nach verfügbarer Breite gibt es zwei bis zwölf Spuren. Die Verteilung strebt
mindestens `max(0,8 mm, 2 × innere Linienbreite)` Abstand an; kleine manuelle
Maße können nur zwei engere Stellen bereitstellen. Die Folge zählt Parkanfahren
statt sämtliche Modellschichten. Die erste Turmschicht besitzt noch keine
vorherige Auffangwand und überspringt diesen Einfangzug.

Das Verteilen reduziert wiederholte Belastung derselben Stelle. Es beweist
nicht, dass Ablagerungen nach zwei, vier oder einer anderen festen Anzahl von
Schichten verschwunden sind. Ohne Messung kann der Postprozessor weder einen
verbliebenen Faden noch einen überhöhten Kunststoffklumpen erkennen.

## Umfahrung und Druckabschluss

Die Fahrt vom Modell zur Warteposition umgeht die gesamte projizierte Turmfläche
einschließlich Standfuß und Brim. Eine umschreibende polygonale Kapsel und der
Fahrwegplaner halten mindestens 2 mm zusätzlichen Abstand. Diese Umfahrung ist
verbindlich; die optionale Bevorzugung modellfreier Wege darf sie nicht aufheben.
Profil-Sperrflächen bleiben zusätzlich mit ihrem Druckkopfabstand maßgeblich.
Die tatsächlichen Wegpunkte stehen identisch in G-Code, Vorschau und Zeitrechnung.

Die letzte Modellschicht erhält keine weitere Turmschicht und keine Kühlpause.
Nach sofortigem Rückzug erfolgt die Abfahrt zum nächstgelegenen Punkt mit
0,5 mm Abstand an der gedachten Schaftkontur. Bei freiem Weg werden XY und
Z-Hop in einem einzigen Fahrbefehl kombiniert. Auch nach vorzeitigem Turmende
bleibt diese gedachte Kontur das Ziel; zum niedrigeren Turm wird nicht abgesenkt.
Der Abschluss und die letzte berechnete Schichtzeit werden getrennt von der
Mindestzeit aller noch kühlungsrelevanten Schichten ausgewiesen.

## Rückzüge und Prime-Automatik

Vor der Fahrt vom Modell folgt der Rückzug bis zu 3 mm der zuletzt tatsächlich
gedruckten zusammenhängenden, geraden und planaren Bahn rückwärts. Für Bögen
oder Scarf-Rampen wird keine vermeintlich gleichwertige Bahn erfunden; fehlt
eine geeignete Bahn, erfolgt der bestehende stehende Rückzug. Originalbefehle
und ursprüngliche Druckbewegungen bleiben erhalten.
Mikroskopische Reststücke unter 0,2 mm werden nicht zum Wischen verwendet;
sehr fein segmentierte Enden erhalten eine begrenzte Rückwegliste.

Am Turm wird am Ende der zur Modellseite laufenden Rückbahn sofort zurückgezogen.
Danach folgen Höhenentlastung und einmaliger Abziehweg gemäß dem oben
beschriebenen Ablauf. Eine zusätzliche Rückfahrt auf dem frischen Mittelsteg
entfällt. Der freie Fahrweg beginnt vollständig zurückgezogen außerhalb der
Wand. Der Profil-Rückzugsausgleich erfolgt erst wieder am Modell.

**Max. zusätzliches Primen** hat standardmäßig Auto aktiviert. Die automatische
Obergrenze folgt aus Schaftgeometrie, Linienbreiten, Schichthöhen und Zeitreserve;
sie beträgt höchstens 1 mm Filament und höchstens 15 % einer nominellen
Schaft-Außenrunde. Ohne Auto gilt der manuell gewählte Wert als Obergrenze.
Die tatsächlich ausgegebene Menge ist in beiden Fällen:

`min(Obergrenze, tatsächliche Pause × 0,02 mm/s, 15 % der ersten Außenrunde)`

Ohne tatsächliche Pause ist sie null. Der Faktor ist eine technische
Dosierreserve, keine kalibrierte Oozing-Rate. Der Rückzugsausgleich und eine
gültige Profil-Wiederanlaufmenge bleiben davon getrennt. Die Zugabe verteilt
sich auf die erste Außenrunde. Materialfluss, M220/M221 und Profilgrenzen
werden weiterhin berücksichtigt. Pause und Prime-Menge werden gemeinsam
berechnet; nicht bestätigte Zeiten sperren den Export.

## Sicherheits- und Abnahmegrenzen

Die Platzierung verwendet weiterhin den konservativen umschreibenden Kreis
einschließlich Fuß und Brim. Alle lokalen Kontur-, Fang- und Wischbahnen liegen in
dieser Hülle. Die neuen äußeren Fahrwege verbinden die tatsächlichen Endpunkte
der Modell- und Turmwischbewegungen. Die Vorschau wird aus dem ausgegebenen
G-Code rekonstruiert und enthält diese Bewegungen.

Softwareprüfungen können Wandabstände, Unterstützung, Rückzüge, begrenzte
Extrusion, Dateiintegrität und berechnete Zeiten bestätigen. Sie ersetzen
keinen Probedruck und bestätigen keine zuverlässige physische Fadentrennung.
Materialfeuchte, Temperatur, Düsenverschmutzung, passive Austrittsmenge und
bereits angesammelte Klumpen bleiben außerhalb des geometrischen Modells.
