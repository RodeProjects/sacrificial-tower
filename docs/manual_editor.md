# Manueller Kühlturmeditor

Die Methode **Manuelle Generierung** gestaltet einen rotationssymmetrischen
Kühlturm direkt in der eingebetteten Vorschau. Sie verwendet die vorhandene
bestätigte Quelle und Profilbindung. Datei-/Slicervorbereitung und automatische
Formberechnung bleiben eigenständige bestehende Abläufe. Ein Methodenwechsel
erhält beide Entwürfe und ihre getrennten Ergebnis- und Exportstände.

## Bedienung und eigene Einstellungen

**Nebeneinander** und **Voreinander** ermöglichen alle Greiferaktionen. Fußrand,
Körperanschluss, oberer Abschluss und freie Profilpunkte besitzen unterschiedliche Greifer.
Der Fußhöhen-Greifer ist neben dem Körperanschluss versetzt; die tatsächliche
Geometrie bleibt an dessen Position. Zahlenfelder und Greifer synchronisieren
sich in beiden Richtungen. Durchmesser werden in Millimetern angezeigt, intern
werden Radien gespeichert.
Eine schmale, über die gesamte Einstellungshöhe reichende Pfeilleiste liegt
rechts neben dem Einstellungs-Scrollbalken und vor der Trennlinie. Sie klappt
die Einstellungen in 250 ms ein oder aus. Eingeklappt bleibt die Leiste ganz
links, der Pfeil zeigt nach rechts und die Vorschau erhält den freien Platz.
Die Werte bleiben erhalten. Bei schmalen Fenstern bleiben die aufgeklappten
Einstellungen wie bisher oberhalb der Vorschau angeordnet; eingeklappt steht
auch dort nur die schmale Leiste links. Dieser Anzeigezustand wird nicht gespeichert.
Die Scrollposition wird nach dem Aufklappen wiederhergestellt, sobald die
Layout-Umstellung abgeschlossen ist; bei kürzerem Inhalt gilt der verbleibende gültige Bereich.
Horizontale Greiferbewegungen ändern Durchmesser in Schritten von 0,1 mm,
einschließlich Bézierkontrollgriffen sowie Drauf- und Untersicht. Grenzen
zwischen zwei Schritten stoppen auf dem letzten gültigen Zehntelmillimeter;
vertikale Bewegung bleibt dabei unabhängig möglich. Numerische Eingaben
behalten ihre Präzision. Rein vertikales Ziehen verändert keine Breite.
Rechts neben dem ausgewählten Greifer erscheint eine dezente Wertanzeige:
Spitzen-, Grund- und Fußgreifer zeigen den aktuellen Außendurchmesser;
freie Profilpunkte, Fußhöhe, Höhengreifer und Kurvengriffe zeigen bei aktiviertem
Layer-Snapping die Original-Layernummer, sonst die Höhe in Millimetern.
Oberhalb des Originals steht bei der Layernummer „–“.
Der rote Spitzengreifer steuert ausschließlich die Spitzenbreite und löst sie
von der anfänglichen Kopplung an den Körperbeginn. Der blaue Höhengreifer liegt
daneben und verändert ausschließlich die Höhe. Auswählen des Spitzengreifers
zeigt genau den oberen Bézierkontrollpunkt des letzten Körperabschnitts; einen
zusätzlichen Übergangsgreifer gibt es dort nicht. Die bearbeitbare rechte
Profilkante ist kräftig hellviolett hervorgehoben.
Alle Fließkommafelder zeigen gerundet zwei Nachkommastellen; die Modell- und
Speicherpräzision bleibt erhalten. Kreissegmente bleiben ganzzahlig. Der Toggle
**Vertikale Greifer auf Layer einrasten** ist standardmäßig aktiv und wird
separat mit den manuellen Einstellungen gespeichert. Höhen-, Fußhöhen-, freie
Profil- und Bézierkontrollgreifer rasten auf die tatsächlichen Originalschichten
ein, einschließlich variabler Layerhöhen. Oberhalb des Originals wird das
Raster mit dessen letzter Schichthöhe bis zur Maschinenhöhe fortgesetzt;
dort gibt es weiterhin keine Original-Layernummer. Geometriegrenzen stoppen
Bewegungen auf der letzten erreichbaren Schicht. Enthält der erlaubte Bereich
keine erreichbare Schicht, bleibt die bisherige Höhe erhalten; radiale Bewegungen
bleiben möglich. Bei ausgeschaltetem Toggle erfolgt das Ziehen stufenlos,
einschließlich des oberen Höhengreifers. Numerische Höhen bleiben unabhängig
vom Toggle frei eingebbar. Der obere Höhengreifer rastet großzügig innerhalb
von 14 Bildschirm-Pixeln auf die Objekt-Endhöhe ein. Diese Oberkante hat dort
Vorrang vor benachbarten Layern. Dabei erscheint für 850 ms eine horizontale Hilfslinie mit der
Beschriftung „Objektoberkante“. Sie verbindet die Höhe optisch über die
Vorschau hinweg und folgt demselben Maßstab wie Turm und Original. Fortgesetztes
Ziehen auf derselben Schicht verlängert die Anzeige nicht; beim Verlassen
verschwindet sie sofort und erscheint beim erneuten Einrasten wieder. Andere
benachbarte Layer sind außerhalb dieses Bereichs einzeln erreichbar. Snapping
und Anzeige berücksichtigen Zoom und Pan.
Beim vertikalen Ziehen eines Höhen-, Fußhöhen-, freien Profil- oder
Bézierkontrollgreifers folgt außerdem eine horizontale Hilfslinie dessen
tatsächlich angenommener Höhe über die gesamte Vorschau. Sie reicht über das
Originalobjekt und zeigt „Höhe: … mm · Layer: …“. Die Layernummer ist einsbasiert
und gehört zur tatsächlichen Originalschicht an dieser Höhe; oberhalb des
Originals erscheint „–“. Diese Linie bleibt während
des Ziehens sichtbar und verschwindet beim Loslassen. Rein horizontale
Greiferbewegungen blenden sie nicht ein; Geometriegrenzen und Snapping werden
in ihrer Position berücksichtigt.

Links steht eine schmale Höhenskala in Millimetern, rechts eine Layerskala mit
den tatsächlichen, gegebenenfalls variablen Originalschichthöhen. Beide folgen
Zoom und Verschiebung. Die Teilung wird bei kleinem Maßstab ausgedünnt; bei
ausreichendem Zoom sind einzelne Schichten als Teilstriche und anschließend
auch als Beschriftungen erkennbar. Drauf- und Untersicht zeigen Höhe und Layer
des jeweiligen Abschlusses, da die Höhenachse dort senkrecht zur Bildebene liegt.

Ein Doppelklick auf das Körperprofil fügt einen neuen Punkt ein.
Alternativ fügt die Punktaktion einen Punkt in den ausgewählten Körperabschnitt
ein. Die Position liegt auf dem bisherigen Profil; eine bestehende Bézierkurve
wird formtreu geteilt, ohne die zum neuen Punkt gerichteten Kurven fester oder
manueller Nachbarn zurückzusetzen. Gerade Abschnitte bleiben linear.
Ein Doppelklick auf einen
Profilpunkt setzt seine angrenzenden Bézier-Kurven zurück und lässt deren eigene
Anker sichtbar. Körperkurven beginnen dabei mit Kontrollpunkten bei einem bzw.
zwei Dritteln der geraden Verbindung. Feste Punkte lassen sich ebenfalls
zurücksetzen: Fußrand und Fußhöhe setzen nur die Fußkurve auf ihre übliche
Grundform zwischen den aktuellen Endpunkten zurück; der Körperbeginn setzt
Fußkurve und ausgehenden Abschnitt zurück, die Spitze ihren letzten Abschnitt.
Punktpositionen und Durchmesser bleiben erhalten. Die Abschnittsauswahl erlaubt
weiterhin den gezielten Wechsel zu einer geraden Verbindung.
Freie Punkte lassen sich per Rechtsklick, über die Aktion oder die Entf-Taste entfernen;
beim Entfernen werden ausschließlich die beiden zum entfernten Punkt gerichteten
Nachbaranker auf Drittelpunkte der neuen Verbindung zurückgesetzt. Das gilt auch
für feste Nachbarpunkte; deren gegenüberliegende Anker und weitere Kurven bleiben
unverändert. Eine Tangentenkopplung an diesen beiden Nachbarn wird gelöst, damit
sie keine zusätzlichen Anker verändert.
Fuß, Körperanschluss und oberer Abschluss bleiben erforderlich. Jeder Abschnitt
kann gerade oder als kubische Bézierkurve bearbeitet werden. Kontrollgreifer
erscheinen ausschließlich am angewählten Punkt: sein eingehender und sein
ausgehender Griff. Neue freie Punkte zeigen beide Griffe sofort nach dem
Hinzufügen, sowohl per Profildoppelklick als auch über die Punktaktion.
Bei freien Punkten zeigt bereits der erste einfache Klick
ohne Ziehen beide Griffe, auch wenn die angrenzenden Abschnitte noch linear sind.
Die Anzeige allein ändert weder Kurvenmodus noch Form; das Ziehen eines
Kontrollgriffs formt seinen Abschnitt als Bézierkurve. Das Ziehen am freien
Profilpunkt verschiebt weiterhin den Punkt. Ein weiterer Doppelklick setzt die
Kontrollgriffe erneut zurück, ohne sie auszublenden.
Dieser Doppelklick-Reset gilt ausschließlich in Nebeneinander und Voreinander;
in Drauf- und Untersicht sind Funktion und Bedienungshinweis nicht verfügbar.
Nachbarpunkte zeigen keine zusätzlichen Griffe. Fußrand und Fußhöhe besitzen
jeweils nur ihren eigenen Fußkurvengriff. Der reine Auswahlklick ändert keine
Geometrie. Beim Auswählen eines Kontrollgriffs bleiben die Griffe seines
zugehörigen Profilpunkts sichtbar.
Innenpunkte können ihre Tangenten
koppeln; beide Seiten erhalten dann dieselbe lokale Steigung.

Jede numerische Einstellung besitzt Einheit, Info und Reset. Wiederverwendbare
manuelle Werte werden separat gespeichert, einschließlich Farbreferenz für das
Original, Durchmessergrenzen, Fußwerte und Kreissegmentzahl. Im manuellen Modus
gibt es weder eine gewünschte Mindest-Layerzeit noch eine Layerzeit-Toleranz.
Die Farbreferenz in „Visuelle Prüfung“ färbt ausschließlich Originalschichten;
sie bewertet weder den gestalteten Turm noch das geprüfte Ergebnis. Der Gesamtreset
erzeugt einen neuen gültigen Anfangsentwurf. Punkt-/Kontrollpunktresets verwenden
den Ausgangswert des jeweiligen stabil identifizierten Greifers. Die
Automatikeinstellungen werden dabei nicht verändert.

Ungültige Bewegungen gelangen nur bis zur ersten gültigen Grenze. Bei einer
diagonalen Bewegung werden anschließend beide Achsen einzeln gegen das gesamte
Profil und die Druckbettplatzierung geprüft. So bleibt beispielsweise die Höhe
eines freien Punkts beweglich, wenn sein Durchmesser bereits das Minimum erreicht.
Die tatsächlich
begrenzende Einstellung wird kurz rot markiert; weitere Ereignisse derselben
Interaktion verlängern das Blinken nicht ständig. Auch Werte, die Qt bereits
an seinen Eingabegrenzen abfangen würde, gelangen zur fachlichen Grenzprüfung.
Unmögliche Optionswechsel werden zurückgewiesen. Der letzte gültige Entwurf
bleibt erhalten. Bei einer für die Quelle ungültigen gespeicherten Konfiguration
können Einstellungen korrigiert und die Initialisierung erneut versucht werden.

Die **Draufsicht** erlaubt die Spitzenbreite und die Turm-Durchmessergrenze,
die **Untersicht** die Fußbreite und die Fuß-Durchmessergrenze. Die **Freie 3D-Ansicht** beginnt in der 3/4-Ansicht
und besitzt keine Greiferaktionen. Mausrad zoomt um die Mausposition; mittlere
Maustaste verschiebt, rechte Maustaste dreht nur die freie räumliche Kamera.
„Einpassen“ stellt beide
Objekte vollständig und mit demselben physikalischen Maßstab dar. Der Button ist
dezent grün, solange Zoom, Verschiebung, Orientierung oder relevante äußere
Abmessungen von der zuletzt eingepassten Darstellung abweichen. Einpassen hebt
diese Markierung auf; Fenstergrößen-, Farb- und Auflösungsänderungen allein
aktivieren sie nicht. Objektrotation,
Transparenz, Auswahl, Hover und Kamera verändern keine Druckdatei.
Die Einpassung nutzt die tatsächlichen projizierten Objektgrenzen und Turmsegmente
ohne pauschale Reserve in Millimetern oder Prozent. Über den Objekten bleiben
mindestens 14 Pixel Abstand zu den Ansichtsbuttons. In den Profilansichten ist
unterhalb der Druckbettebene Platz für die Mindestdurchmesser-Maßlinie reserviert;
die räumlichen Ansichten behalten einen kleinen unteren Abstand von 24 Pixeln.
Die Einheiten stehen jeweils links neben ihrer Skalenleiste, einschließlich
**Layer** an der rechten Leiste. Zahlen und Einheiten überlappen auch bei enger
Einpassung nicht.

Über der Vorschau stehen in einer gemeinsamen Zeile **X-Ray (Transparenz)** mit den drei
gleich breiten farbigen Buttons **Turm**, **Keine** und **STL**,
**Auflösung (STL)** und
**Originalobjekt drehen** mit Slider, Winkelwert und Reset. Diese drei Bereiche
sind zweizeilig und haben zentrierte Überschriften; ihre Höhe entspricht
einem regulären Aktionsbutton. **Turm** stellt ausschließlich den Turm mit der
bisherigen Deckkraft 35 % dar, **STL** ausschließlich das Original mit 28 %.
**Keine** ist der Standard und zeigt beide normal. Der aktive Button besitzt
einen kräftigeren Farbverlauf, farbigen Rahmen und fetten Text; die Rahmenbreite
bleibt bei allen Zuständen identisch (1 px). Die Buttons sind zunächst etwa ein
Drittel breiter als zuvor. Bei Platzmangel verkleinern sich zuerst Auflösung und
Drehung; erst danach wird die X-Ray-Gruppe kompakter. Die Überschrift kürzt sich
auf **X-Ray**, die Buttons bleiben gleich breit und schrumpfen bis zur für alle
drei Texte erforderlichen Mindestbreite. Sie brechen nicht um.
Die Ansichtsbuttons liegen rechtsbündig oben
innerhalb der Zeichenfläche, von links nach rechts: **Nebeneinander**,
**Voreinander**, **Draufsicht**, **Untersicht**, **Freie 3D-Ansicht**, **Einpassen**.
Ihre Höhe beträgt etwa ein Drittel der bisherigen Einpassen-Höhe zuzüglich
je drei Pixel Platz ober- und unterhalb des Textes. X-Ray- und
Ansichtsbuttons verwenden dieselben vertikalen Farbverläufe wie die übrigen
Aktionsbuttons. Wenn eine
Zeile nicht passt, belegen zwei Zeilen mit je drei Buttons die verfügbare Breite;
Einpassen steht rechts in der zweiten Zeile. Der Beschreibungstext links oben
wird bei einer Überlappung mit der Gruppe ausgeblendet. Der Drehungs-Reset
verwendet dieselbe 36-Pixel-Größe und dieselben Standard-/Änderungs-/Hoverzustände
wie die numerischen Reset-Buttons. Unter der Vorschau stehen **Legende** links und
**Bedienung** rechts, getrennt durch eine graue vertikale Linie. Die acht
Legendeneinträge stehen bei genügend Platz in zwei Spalten mit je vier Einträgen.
Umgebrochene Legendeneinträge bleiben oben an ihrem Farbquadrat ausgerichtet;
der danebenliegende Eintrag wird nicht vertikal verschoben. Die
Bedienungsstichpunkte beginnen bündig unter ihrer Überschrift, ohne Satzendpunkt;
Zoom steht zuletzt. Der Drehslider besitzt sichtbare Teilstriche alle 45° und
rastet beim Ziehen innerhalb von ±3° an diesen Winkeln ein. Andere Winkel bleiben
einstellbar; Tastaturänderungen erfolgen weiterhin gradweise.
Farbquadrate passen sich der Schriftgröße an; bei kritischer
Original-Layeranzeige ist das Objektquadrat diagonal von links unten nach
rechts oben geteilt, links oben rot und rechts unten grün.

Die Maximaldurchmesser werden zusätzlich als verschiebbare vertikale Grenzstriche
angezeigt: violett für den Fuß, blau für den Körper. Ihre Position entspricht dem
halben Durchmesser von der Turmachse aus (Ø 50 mm entspricht 25 mm Abstand).
Eine hellgraue gestrichelte horizontale Linie verbindet sie mit der Profilkante.
Ziehen ändert ausschließlich die jeweilige Grenze in 0,1-mm-Durchmesserschritten;
der aktuelle Maximaldurchmesser steht rechts daneben. Die vollständige Validierung
stoppt das Verkleinern an der bestehenden Form. Grenze und Zahlenfeld bleiben
synchron; die Form und das Druckartefakt ändern sich dadurch nicht.
Der Mindest-Turmdurchmesser besitzt in **Nebeneinander** und **Voreinander** eine
eigene Maßlinie unterhalb des Turms, beschriftet mit **Min. Turm-Ø**. Zwei
gestrichelte Linien führen von der Druckbettebene nach unten. Ihre Farbe geht
linear vom um ein Drittel abgedunkelten Grau der 0-Linie zum hellen Grau
am Bezeichner über; ihre Positionen sind
symmetrisch zur Turmachse und liegen genau den eingestellten Mindestdurchmesser
auseinander. Der blaue Punkt am rechten unteren Ende lässt sich horizontal ziehen.
Beide Linien verschieben sich symmetrisch, während rechts neben dem ausgewählten
Punkt der aktuelle Mindestdurchmesser erscheint. Der Griff verwendet dieselben
validierten 0,1-mm-Durchmesserschritte wie die Maximalgrenzen und verändert die
bestehende Form nicht. Das Erhöhen stoppt an der kleinsten zulässigen Breite der
vorhandenen Form. Beide Footer-Resets stellen Mindestgrenze und Turmform wieder her.
Beim horizontalen Ziehen eines manuellen oder festen Profilpunkts erscheint an einer erreichten
Mindest- oder Maximalbreite sofort eine sattblaue gestrichelte vertikale Linie
mit einer Breite von 1 Pixel. Sie bleibt 350 ms vollständig sichtbar und blendet
danach innerhalb von 200 ms linear vollständig aus. Alle kurz eingeblendeten
Breitengrenzen reichen von der 0-Linie bis zum oberen Ende der gezeichneten
vertikalen Skalenlinie, unabhängig vom letzten Skalenwert oder der Objekt-/Fußhöhe.
Ihre horizontale Position bleibt der jeweilige Grenzradius.
Bei Unterschreitung des Mindest-Turmdurchmessers erscheinen beide Grenzlinien
symmetrisch links und rechts der Turmachse mit demselben Zeitverlauf.
Weitere Mausbewegungen verlängern diesen Impuls nicht; nach dessen Ende
blendet ein erneuter Versuch in Richtung der Grenze ihn wieder sofort ein.
Die Markierung erneuert keine Originalflächen und verwendet das fertige Originalbild weiter.

Der Regler **Auflösung (STL)** besitzt die zehn Stufen **1 %, 3 %, 5 %, 10 %,
15 %, 20 %, 25 %, 50 %, 75 %, 100 %**, von Performance zu Optik.
Der Bereich erscheint in allen fünf Ansichten. Sein
Farbverlauf von Grün über Gelb zu Rot richtet sich nach den tatsächlichen
Prozentwerten der Stufen; die vielen niedrigen Stufen bleiben überwiegend grün.
Jede Stufe besitzt einen Teilstrich. Über dem Regler stehen links „performance“ und
rechts „optik“ in Grau, mit zentrierter Überschrift. Bevor diese Texte sich
überlappen, werden beide seitlichen Hinweise ausgeblendet. Der Reset rechts
stellt die Standardauflösung wieder her und verwendet die üblichen
Resetzustände; während eines Auftrags ist er ebenfalls gesperrt.
Neue Einstellungen und der Reset verwenden **10 %** (Stufe 4).
Er wird als manuelle Präferenz
gespeichert. Niedrigere Stufen reduzieren ausschließlich die räumlichen
Originalflächen durch Zusammenfassen naher Meshknoten. Die Stufe beschreibt
ein ungefähres Flächenbudget; es werden keine einzelnen Dreiecke ausgelassen,
die sichtbare Löcher verursachen würden. 100 % verwendet die vollständige
bisherige Originalauflösung. Kleine Meshes bleiben vollständig, wenn eine
Reduktion keinen sinnvollen Vorteil bietet. Farbliche Original-Layerkonturen,
Originaldaten, Analyse, Turm und Druckexport bleiben
in ihrer bisherigen Genauigkeit. Die Regleränderung erneuert nur den
Original-Flächencache; Pan, Zoom, Einpassen und Transparenz bauen keine neuen
Flächen. Während eines Vorbereitungs-/Generierungs-/Exportauftrags ist der
Auflösungsregler gesperrt.

Bei kleinen Fensterbreiten wechseln Einstellungen und Vorschau von einer
nebeneinanderliegenden zu einer gestapelten Anordnung. Die Einstellungen bleiben
scrollbar; Aktionen und Vorschau sind weiterhin zugänglich. Neben der
Methodenbezeichnung erscheint dann rot „(Zweispaltige Ansicht empfohlen - Fenster
verbreitern)“, zentriert im verbleibenden Bereich rechts neben der linksbündigen
Methodenbezeichnung; in der zweispaltigen Anordnung verschwindet der Hinweis.
Die Trennlinie übernimmt die Gestaltung des Bereichseditors: ein Pixel Breite,
14 Pixel Abstand der Inhalte auf beiden Seiten und keine einklappbaren Bereiche.
Die linke Scrollfläche bestimmt weder Höhe noch Position der Vorschau. Auch
eingeblendete Grenzmeldungen und eine veränderte Scrollbalkenreichweite lassen
die Darstellung unverändert stehen.
Die Vorschau passt sich bei Fenster-/Methodenwechseln und nach abgeschlossenen
Vorbereitungs-/Generierungsjobs an den verfügbaren Bereich oberhalb des Footers
an. Während der Bearbeitung bleibt diese Höhe fest. Der äußere Scrollbalken wird
nur bei tatsächlichem Überlauf angezeigt. Eine gleichbleibende schmale
Randreserve verhindert horizontale Sprünge beim Ein-/Ausblenden; die
Höhenberechnung berücksichtigt den gesamten unteren Inhaltsrand. In der
gestapelten Anordnung wird die Pane-Größe auf die tatsächliche Einstellungsfläche
begrenzt; verbleibender Platz kommt der Vorschau zugute.
Beim Verlassen der Methode wird die vorherige Scrollpolitik wiederhergestellt.
Bei sehr kleinen Fenstern bleibt die Mindestfläche der Bedienelemente erhalten
und der Inhalt lässt sich vollständig zur Vorschau scrollen.
Die Vorschau besitzt dafür eine eigene Mindesthöhe aus Zeichenfläche und
Bedienelementen. Sie gilt auch beim Wechsel zur gestapelten Anordnung, damit
beibehaltene Trennergrößen keine Überlagerung der Bedienelemente verursachen.

In „Nebeneinander“ liegen Turm und Original nebeneinander. „Voreinander“
projiziert sie um 90° gedreht hintereinander auf dieselbe Referenzachse.
X-Ray und vorrangige Greifer ermöglichen die Bearbeitung bei Überlagerung.
Diese Referenzansichten sind von der tatsächlichen Druckbettanordnung in den
räumlichen Ansichten unterscheidbar beschriftet.
Auch dort wird das Original als schattiertes Dreiecksnetz gerendert, mit einer
orthogonalen Kamera ohne Höhenneigung (0° bzw. 90° um die Hochachse). Dadurch
bleiben Originalhöhe, Layermaßstab und Profilhöhe deckungsgleich. Der Turm bleibt
in diesen beiden Ansichten ein gefülltes bearbeitbares Profil.
Turmaktionen, Auswahl und erneutes Einstellen derselben Drehung erneuern dort
keine Originalflächen. Ein neuer Drehwinkel erneuert den Original-Flächencache
einmal; Originalauflösung und Originalfarbparameter aktualisieren ihn ebenfalls.
Die Vorschau zeigt beim Hover keine Popup-Bedienhinweise; die Bedienung steht
dauerhaft in der Legende darunter.

Generieren/Aktualisieren, Exportieren, Abbrechen, „Alles zurücksetzen“ und
„Turmform zurücksetzen“ liegen im **Hauptfenster-Footer**. Die beiden Resetaktionen
stehen linksbündig unten im linken Footer-Bereich. Derselbe Footer verwaltet
die Ordner-/Berichtsaktionen, Kürzungsreihenfolge und Umbrüche wie bei der
automatischen Methode. Die Aktionen richten sich nach der aktiven Methode;
der Reset bestätigt ausdrücklich den manuellen Umfang. Status, Fortschritt
und Hinweise zum bisherigen geprüften Stand stehen ebenfalls im Footer.
Leere Textfelder und die zugehörige leere Scrollfläche werden ausgeblendet;
ohne Meldungen benötigt der Footer nur die Höhe seiner sichtbaren Aktionen.

## Geometriemodell und Invarianten

`manual/geometry.py` enthält das Qt-unabhängige Modell aus unveränderlichen
`ManualSettings`, `ProfilePoint`, `Cubic` und `ManualDraft`. Eine Koordinate
ist `(Radius, absolute Z-Höhe)` in Millimetern. Stabile Punktkennungen sind
unabhängig von Listenposition und Darstellung. Geometrieoperationen erstellen
einen neuen, vollständig validierten Entwurf; ungültige Zwischenstände werden
nicht übernommen.

Der Fußrand liegt auf der **ersten tatsächlichen Druckschicht** des vorbereiteten
Originals. Das Mesh besitzt zusätzlich einen Ring bei Z=0 und geschlossene
Boden-/Deckelkappen. Die initiale Fußkurve ist eine echte konkave Bézierkurve
mit vertikaler Tangente am Körperanschluss. Der initiale Körper hat überall
exakt den eigenen Mindestdurchmesser und reicht bis zur Objekthöhe, begrenzt
durch die verifizierte Maschinenhöhe. Eine fehlende Maschinenhöhe führt zur
ausdrücklich angegebenen sicheren Begrenzung auf die analysierte Objekthöhe.
Sehr niedrige Objekte ohne Platz für Fuß und Körper werden konkret zurückgewiesen.

Die Fußgrenze gilt separat vom maximalen Körperdurchmesser. Wird der
Körperanschluss breiter als der bisherige Fuß, wächst der Fuß lokal mit bis
zu 2 mm Durchmessermarge, begrenzt durch seine eigene Obergrenze. Eine spätere
Verkleinerung des Körpers verkleinert den Fuß nicht automatisch. Änderungen
am Anschluss erhalten die relativen Fußkontrollpunkte. Freie Körperpunkte
behalten ihre individuelle Lage; nur der noch nicht individualisierte
Anfangskörper folgt als Ganzes seiner Anschlussbreite.

Einfügen unterteilt den bisherigen Abschnitt mit De Casteljau exakt formtreu.
Kurvenmodus und Tangentenrichtungen der Nachbarn einschließlich vorhandener
Tangentenkopplungen bleiben erhalten. `insert_point(..., linear=True)` erlaubt
bei ausdrücklich gewünschter Linearisierung weiterhin gerade Verbindungen.
Ein Punkt-Moduswechsel setzt
beide Abschnitte atomar zurück; Tangentenkopplungen an den betroffenen
Anschlüssen werden aufgehoben, damit gerade Abschnitte tatsächlich gerade
bleiben. Löschen
verbindet die Nachbarpunkte erneut und akzeptiert die neue Verbindung nur bei
gültigem Gesamtprofil. Neue Körperpunkte benötigen beim Einfügen mindestens
**0,1 mm** Z-Abstand zu beiden Nachbarn einschließlich Körperbeginn und Spitze.
Für das spätere Verschieben bestehender Punkte bleiben **0,05 mm** gültig;
Kontrollpunkte dürfen in Z nicht rückläufig sein. Zusätzlich muss die analytisch
geprüfte Z-Ableitung im vollständigen Abschnitt einschließlich der Enden strikt
positiv sein. Das garantiert einen eindeutigen Radius je Höhe und verhindert
Falten sowie nahezu horizontale, numerisch unzuverlässige Abschnitte.

Durchmesser werden an Enden und **analytischen Radius-Extrema** geprüft. Für
Aufweitung und Verjüngung werden die Enden sowie sämtliche inneren Extrema von
`dr/dz` ausgewertet. Ein schmales Überschwingen zwischen Anzeige- oder
Druckschichten kann deshalb nicht unbemerkt bleiben.

Die Winkel beziehen sich auf die Vertikale:

```
Aufweitung:  atan(max(0,  dr/dz))
Verjüngung:  atan(max(0, -dr/dz))
```

Beide Grenzen sind zunächst deaktiviert und lassen sich unabhängig aktivieren.
Die Prüfung gilt für die vollständige Kurve einschließlich des Fußes. Eine
verschärfte Grenze wird nur angenommen, wenn das unveränderte Profil sie erfüllt.
Gekoppelte Tangenten werden bei Punkt-/Greiferänderungen atomar mitgeführt und
ebenfalls geprüft.

`ManualContext.validate()` ergänzt Kontextbindung, Höhe und die bestehende
Druckbettplatzierung. Sie verwendet den größten Radius des **gesamten** Profils,
den wirksamen Brim sowie die vorhandenen Bettpolygone und Ausschlussflächen;
Objekt- und Randabstand betragen jeweils 5 mm. Fehlende verlässliche Bettdaten
oder eine nicht passende Form erlauben keine Generierung.

## Tessellierung und STL

Das geschlossene Rotationsmesh folgt denselben Kurven wie die Editoransicht.
Adaptive De-Casteljau-Unterteilung begrenzt den radialen Abstand zwischen Kurve
und Höhen-Sehne mit der konvexen Hülle ihrer Kontrollpunkte auf **0,02 mm**.
Ein Höhenintervall ist höchstens 1 mm lang. Diese geometrische Unterteilung ist
unabhängig von den tatsächlichen Drucklayern. Eine Rekursionsgrenze verhindert
unbeschränkten Aufwand; bei Nichterfüllung wird abgebrochen statt ein ungenaues
Mesh als gültig auszugeben.

Alle STL-Ringe einschließlich Boden verwenden exakt dieselbe tatsächliche
Kreissegmentzahl (12–720). Ohne eigene Wahl wird bei der Initialisierung
`max(25, ceil(Fußdurchmesser in mm))` festgelegt und anschließend als eigener
manueller Wert geführt. Die radiale Polygonabweichung in XY ist davon getrennt:
`Radius * (1 - cos(pi / Segmentzahl))`. Die räumliche Turmanzeige verwendet
immer die vollständige eingestellte Kreissegmentzahl, unabhängig von der
Objektauflösung. Formänderungen erscheinen unmittelbar in der Vorschau.
Nebeneinander- und Vorderansicht behalten ihre flache Profilprojektion.

Die Mesh-Konstruktion übernimmt die etablierte Ring-/Kappentopologie.
Die vorhandene Mesh-Validierung und der binäre STL-Schreiber werden verwendet.
Anschließend prüft `StlValidationService` auch das tatsächlich geschriebene
Float32-STL streng auf die technischen Geometriebedingungen. Erst danach wird
die feste Form geslicet. Abbruchprüfungen erfolgen während Unterteilung,
Ring-/Flächenerzeugung, Schreiben und STL-Prüfung.

## Darstellung, Farben und Hintergrundarbeit

Original-STL und vollständige echte Layerquerschnitte werden einmal pro
Quellenkontext im Hintergrund vorbereitet und unverändert gehalten. Das Original
verwendet in allen fünf Ansichten denselben Meshrenderer. Die Referenzansichten
projizieren das Original orthogonal neben bzw. vor das zweidimensionale Turmprofil.
Sie erzeugen keine fiktive Originalgeometrie aus G-Code.
Ohne Original-STL werden ausschließlich die vorhandenen Druckbahnen angezeigt.

Kritische Originalschichten verwenden exakt `LayerRangeCanvas.layer_color()`
mit den tatsächlichen ursprünglichen Layerzeiten. Farbreferenz, Beginn des Defizitverlaufs
und volle Rotmarkierung sind eigene manuelle Werte. Sie zeigen den vorbereiteten
Originalstand; geprüfte gemeinsame Layerzeiten stehen getrennt im Ergebnis.

Die Überhangmarkierung ist rein visuell. Sie betrifft nur nach außen wachsende
Abschnitte und prüft die lokale positive Steigung, einschließlich exakter
Übergangspunkte am Warnwinkel. Ein interpretierbarer Orca-/Bambu-/Anycubic-Wert
`support_threshold_angle` wird von der Horizontalen umgerechnet:
`90° - Profilwert`. Fehlende oder mehrdeutige Werte verwenden einen sichtbar
erklärten Fallback von 45° zur Vertikalen. Der Profilstandard bleibt über Reset
verfügbar; eigene Winkel werden als solche gekennzeichnet.

Geometriebearbeitung erneuert das Turmprofil und nutzt die zwischengespeicherte
Originaldarstellung weiter. Räumliche Original- und Turmflächen werden als
viewportunabhängige `QPicture`-Zeichenfolgen zwischengespeichert. Pan, Zoom,
Fenstergrößenänderung, Transparenz und Einpassen spielen die vorhandenen
Flächen mit neuer Bildschirmtransformation ab. Änderungen an Quelle, Kamera,
Originalrotation oder Flächenfarben erneuern nur die betroffene Darstellung.
Die räumlichen Flächen besitzen eine kamerabezogene Facettenschattierung,
kontrastierende Netzkanten und sichtbare Knoten. Details werden zusammen mit
jeder Fläche nach Tiefe gezeichnet, damit verdeckte Rückseiten verdeckt bleiben.
Die Normalen werden erst nach der Originalrotation berechnet; 0° behält die
ursprüngliche Orientierung. In Drauf-, Unter- und freier Ansicht verwenden Original
und Turm dieselbe Darstellungsart; in den Referenzansichten bleibt der Turm ein Profil.
Kosmetische Stifte halten Kanten- und Knotengrößen beim Zoom konstant.
Identische gerundete Flächenfarben und ihre kosmetischen Kanten-/Knotenstifte
werden pro Original-Renderjob nur einmal erzeugt und wiederverwendet. Die
Farbpalette ändert weder Facetten, Tiefensortierung noch Schattierung und besitzt
keinen gemeinsamen veränderlichen Zustand zwischen Threads.

Zusätzlich hält der Canvas genau ein fertiges Originalbild einschließlich
Hintergrund in der aktuellen Bildschirmgröße und Pixeldichte. Turm, Skalen,
Maßlinien und Griffe werden anschließend darüber gezeichnet. Bei unverändertem
Bildausschnitt verwenden Turmbearbeitung, Auswahl und Hover dieses Bild weiter.
Die Kennung umfasst Bildschirmtransformation, Original-Zeichenfolge, Deckkraft
und Pixeldichte. Zoom, Verschiebung, Einpassen mit geändertem Ausschnitt,
Fenstergröße, Kamera oder Original-X-Ray erzeugen neue Bildpixel aus den vorhandenen
Flächen. Neue Quellen, Originalrotation, Auflösung, Farben und eintreffende
Worker-Ergebnisse ersetzen zusätzlich die zugrunde liegende Original-Zeichenfolge
und machen das Bild ungültig. Turm-X-Ray betrifft ausschließlich die danach
gezeichnete Turmfläche. Das Bild wird nicht nachträglich skaliert oder nochmals
transparent zusammengesetzt: Auch überlappende X-Ray-Netzkanten bleiben unverändert.
Der zusätzliche Bildspeicher beträgt ungefähr `4 × Breite × Höhe × Pixeldichte²`
Bytes (3,2 MB bei 1.000 × 800 Pixeln und einfacher Pixeldichte).
Teure räumliche Originalflächen bzw. große Druckbahndarstellungen werden als
`JobKind.MANUAL_VIEW` durch den bestehenden `BackgroundJobManager` vorbereitet.
Ein kurzer Timer bündelt Kameradrehungen. Solange die Flächen fehlen, zeigt die
Vorschau reduzierte Kanten desselben Original-STL, andernfalls echte Druckbahnen.
Proxy und vollständige Flächen verwenden dieselbe Originalrotation und denselben
Mittelpunkt; 0° am Slider entspricht der Originalausrichtung. Auch die statischen
Ansichten verwenden diese Rotation. Die Quellkoordinaten bleiben unverändert.
Der Worker zeichnet ausschließlich in sein eigenes `QPicture`; `QPixmap` und
Widgets bleiben im GUI-Thread. Request-ID und vollständige Kamera-/Farbidentität
verwerfen verspätete Ergebnisse. Ein Quellen-/Ansichtswechsel bricht ersetzte Jobs ab. Das
Schließen des Hauptfensters verhindert neue Renderjobs und nutzt den zentralen
kontrollierten Shutdown.

Eine lokale Stichprobe am 11.10.2026 verwendete ein selbst erzeugtes Ellipsoid
aus einer Icosphere mit 5.120 Dreiecken, ohne kritische Layerkonturen. Median
aus drei `QPicture`-Aufbauten pro Stufe auf demselben Windows-Host:

| Stufe | Angezeigte Flächen | Aufbau |
| --- | ---: | ---: |
| 10 % | 555 | 20 ms |
| 50 % | 2.564 | 73 ms |
| 100 % | 5.120 | 114 ms |

Das sind modell- und geräteabhängige Vergleichswerte, keine garantierten
Laufzeiten. Wiederholtes Verschieben oder Zoomen spielt den fertigen Cache ab.

Eine zusätzliche explorative Messung am selben Tag nutzte 20.480 Dreiecke bei
100 % ohne kritische Layerkonturen und ein Bild mit 1.000 × 800 Pixeln. Ein
separater Prototyp berechnete identische Farbwerte gesammelt und verwendete
Farben und Stifte wieder: Der Aufbau sank von 419 auf 303 ms (Median aus drei
Durchläufen, etwa 28 % weniger Zeit). Die Wiedergabe des fertigen `QPicture`
benötigte etwa 57 ms; das Kopieren eines bereits in genau diesem Bildausschnitt
fertig gezeichneten Bildes etwa 0,52 ms. Beide Prototypen erzeugten in dieser
Stichprobe pixelidentische Ergebnisse, normal und mit Original-X-Ray.
Beide Optimierungen sind inzwischen in der Anwendung umgesetzt. Der zusätzliche
Bildcache beschleunigt Wiederholungen desselben Bildausschnitts; geänderte
Bildtransformationen werden weiterhin exakt aus den Flächen gezeichnet. Der Faktor
über 100 aus dieser vorangegangenen Prototypmessung gilt ausschließlich für die isolierte
Original-Wiedergabe dieser Stichprobe, nicht für die komplette Vorschau oder
Anwendung. Andere Modelle, kritische Konturen und Geräte benötigen eigene Prüfungen.

Die anschließende Messung der eingebauten Umsetzung mit 20.480 Dreiecken und
1.000 × 800 Pixeln ergab **421 ms statt 295 ms für den Aufbau** (Median aus fünf
Durchläufen, rund 30 % weniger Zeit). Beim unveränderten Bildausschnitt sank die
isolierte Originalwiedergabe von **63,2 auf 0,53 ms**, mit Original-X-Ray von
**59,0 auf 0,53 ms** (Median aus 15 bzw. 30 Durchläufen). Die Bilder waren gegenüber
der vorherigen Zeichenroutine in beiden Fällen pixelidentisch. Diese lokale
Stichprobe betrifft ausschließlich Originalaufbau und -wiedergabe; vollständige
Vorschauzeiten enthalten zusätzlich Turm und Bedienelemente. Zoomen und Verschieben
benötigen weiterhin eine neue Rasterisierung und erhalten nur den schnelleren
Flächenaufbau sowie dessen vorhandene Zeichenfolge.

## Ein unveränderter Prüfslice

`ManualGenerationService` friert Entwurf, Zeitprüfung und bestätigten Kontext ein.
Er ruft **keine** automatische Kalibrierung, Radiuskorrektur oder Bedarfsverkürzung
auf. Auch bei bereits ausreichender Original-Layerzeit ist die manuelle Methode
nutzbar. Der normale Lauf benötigt genau einen Slice der festen Form.

Mit verifizierter Original-STL und geeignetem Adapter werden Objekt und Turm
an den verifizierten Positionen gemeinsam geslicet. Die vorhandenen nativen
Projekt-/Assembly-Konventionen werden erhalten. Bambu bevorzugt sein natives
gemeinsames 3MF; andere vorhandene Adapter können ihren isolierten
Assembly-Eingang verwenden und das identische native Projekt erhalten.
Der bestehende Adapter-Transportzweck heißt intern `calibration`, weil er den
bereits abgesicherten isolierten Prüfprozess auswählt. Er löst im manuellen
Dienst keine Kalibrierungsiteration aus; Berichte nennen ausdrücklich einen
manuellen festen Prüfslice.

Ohne verifizierte Original-STL oder ohne gemeinsame Projektfähigkeit wird nur
der Turm geslicet. Die Bewertung addiert dessen vorhandene Zeit-Auswertung zum
analysierten Original-G-Code und heißt ausdrücklich **Prognose**. Es wird kein
gemeinsam verifiziertes Originalmesh oder 3MF behauptet. Die aktuelle eingebettete
Quellenauswahl nimmt STL entgegen; der manuelle Dienst unterstützt zusätzlich
den vorhandenen G-Code-/Snapshot-Vertrag. Es wird kein neuer GUI-G-Code-Modus
eingeführt und die bestehende Vorbereitung nicht verändert.

Layer werden nur bei sicherer Z-Übereinstimmung zugeordnet. Der maximale
Höhenabstand beträgt `max(0,005 mm, min(0,03 mm, 0,15 * Layerhöhe))`.
Unsichere Zuordnungen, insbesondere bei variablen Layern, brechen die Bewertung
mit konkreter Schichtangabe ab. Die bestehenden Analyse-/Zeitquellen werden
verwendet; fehlende native Layerzeiten, etwa im Bambu-Pfad, werden wahrheitsgemäß
als G-Code-basierte Auswertung bezeichnet. Bei einem kürzeren manuellen Turm
bleiben die ursprünglichen Layerzeiten oberhalb des Turms im Ergebnis enthalten.
Zusätzliche tatsächlich geslicete gemeinsame Schichten werden ebenfalls erfasst.

Technischer Abschluss und gemeinsame Verifikation/Prognose bleiben getrennte
Merkmale. Das Ergebnis zeigt die erreichten Layerzeiten einschließlich ihres
Minimums, ohne Zielerreichung, Defizit oder Toleranzbewertung. Technisch vollständig
geprüfte Ergebnisse sind unabhängig von der erreichten Zeit exportierbar. Fehlgeschlagene,
abgebrochene oder unvollständige Läufe werden nicht als Ergebnis übernommen.

## Ergebniszustände und Export

Im manuellen Footer steht **Turmform zurücksetzen** direkt rechts neben
**Alles zurücksetzen**. Der Formreset stellt die Standardform wieder her und
entfernt freie Punkte sowie Kurvenanpassungen. Er setzt auch minimale/maximale
Turmdurchmesser, Fußdurchmesser/-höhe/-grenze, Kreissegmente und geometrische
Aufweitungs-/Verjüngungsgrenzen auf Standards zurück. Visuelle Präferenzen,
Layer-Snapping, Originalauflösung und Originaldrehung bleiben erhalten;
das letzte geprüfte Ergebnis bleibt für den bisherigen Export verfügbar und
wird bei abweichender Form als veraltet markiert. Der Button ist auch in der
freien Ansicht nutzbar und während eines laufenden Auftrags gesperrt.
**Alles zurücksetzen** setzt zusätzlich alle manuellen Einstellungen,
Originaldrehung, Transparenz und Kamerazustände auf Standards zurück und passt
die aktuelle Ansicht ein. Beide Resets sind in allen Ansichten verfügbar. Der
Gesamtreset reagiert auch auf reine Drehungs-/Auflösungsänderungen und lässt die
aktive Ansicht sowie Automatik-/Vorbereitungswerte erhalten.

`ManualController` führt drei getrennte Stände: bearbeitbaren Entwurf,
laufenden unveränderlichen Auftrag und letztes vollständiges Ergebnis mitsamt
seinem erfolgreichen Auftrag. Die bestehenden automatischen Sitzungsübergänge
werden nicht verändert.

| Zustand | Aktionen und Verhalten |
|---|---|
| Kein Ergebnis | „Kühlturm generieren“; Entwurf bearbeitbar |
| Geprüfter Stand entspricht Entwurf | Grüner Exportbutton |
| Entwurf verändert | Grüner Export des bisherigen geprüften Standes und blauer Aktualisierungsbutton; Ergebniswerte ausdrücklich dem geprüften Stand zugeordnet |
| Neuer Lauf aktiv | Relevante Eingaben gesperrt, Export verborgen, roter Abbruchbutton; altes Ergebnis intern erhalten |
| Neuer Lauf erfolgreich | Ergebnis und Auftrag atomar ersetzen; alte temporäre Ressourcen freigeben |
| Neuer Lauf fehlgeschlagen/abgebrochen | Entwurf und gültiges früheres Ergebnis erhalten; erneute Aktualisierung und ausdrücklich alter Export verfügbar |
| Quelle/Profil ungültig | Auftrag abbrechen; quellengebundenen Entwurf und Ergebnisse verwerfen |

Die kanonische Identität enthält tatsächliche Kurven-/Kontrollkoordinaten,
erste Layerhöhe, tatsächliche Kreissegmentzahl, relevante
Profil-/Objektwerte, Quellen- und Profilidentitäten. Reine Grenzwerte, die ohne
Formänderung lediglich die zentrale Validierung verschärfen, werden neu geprüft,
erzeugen aber kein anderes Artefakt. Punktkennungen, Tangentenkopplung ohne
Koordinatenänderung und rein visuelle Werte gehören nicht zur Artefaktidentität.
Ein exaktes Rücksetzen auf den erfolgreichen Stand entfernt den Aktualisierungsbedarf.
Die automatischen Signaturprüfungen bleiben unverändert.
Die manuelle Request-Schema-Version ist 2; die Farbreferenz gehört ausschließlich
zur Darstellung. Der technische Exportbericht verwendet Schema 3 und enthält
Layernummer, Z-Höhe und erreichte Zeit ohne Ziel-/Defizitfelder.

Der Export übergibt dem bestehenden Integritätsvertrag den **gespeicherten
erfolgreichen Auftrag**, auch wenn der aktuelle Entwurf inzwischen anders
aussieht. Er kopiert dessen geprüftes STL, gegebenenfalls natives gemeinsames
3MF, `verification.gcode`, Slicer-/Projektdiagnosen, technischen JSON-Bericht und
Benutzerzusammenfassung in einen eindeutigen Laufordner. Keine neue Generierung
und kein neuer Slice findet statt. Quellen, Profile, STL, 3MF und G-Code werden
erneut auf unveränderte Identität bzw. Prüfsummen geprüft. Unvollständige
Exportordner werden entfernt. Ein identischer Ergebnisstand kann innerhalb
seiner Sitzung nur einmal exportiert werden; beide Methoden führen diese
Identität getrennt. Der letzte Exportbericht bleibt als gemeinsamer Verlauf
aufrufbar und behält die zutreffende Art seiner Zeitprüfung.

## Prozesse, Persistenz und Dateisicherheit

Generierung und Export verwenden die bestehenden verwalteten Jobarten
`PREVIEW`/`EXPORT`, sodass vorhandene Sperren diese Jobs erkennen. Eigene
negative Request-IDs trennen die manuellen Callbacks von der Automatik.
Das gemeinsame Cancellation-Event erreicht Geometrie, STL-Prüfung, Analyse,
Adapter und bestehendes Prozessbackend. Abbruch wird erst nach vollständiger
Job-/Threadfreigabe als beendet behandelt. Wiederholte Anforderungen und
verspätete Ergebnisse sind sicher; ein altes vollständiges Ergebnis bleibt
bei fehlgeschlagener Aktualisierung erhalten.

Originalquellen und Slicerprofile werden ausschließlich gelesen. Sämtliche
materialisierten Profile, STL/3MF/G-Code, Assembly-Dateien und Diagnosen liegen
in programmeigenen Arbeitsverzeichnissen. Die vorhandene Schreibschutz- und
Prozessisolation wird wiederverwendet. Neue Drittkomponenten sind nicht erforderlich.
Jeder Prüfslice erhält strukturierte Transportdiagnosen und stdout-/stderr-Logs.
Bei einem fehlgeschlagenen Slice bleiben nur diese Diagnoseverzeichnisse in
einem separaten `manual_failed_*`-Ordner erhalten; der Fehlermeldung ist dessen
Pfad beigefügt. Unvollständige Druckartefakte werden weiterhin freigegeben.

`manual_settings.json` hat ein eigenes Schema 5 und läuft über
`VersionedJsonStore`. Geometriepunkte, Quellenbindung und Artefakte werden nicht
persistiert. Unbekannte neuere, beschädigte oder extern geänderte Dateien
werden nicht überschrieben. 1→2 übernimmt die alte Zielzeit ausschließlich als
Farbreferenz für Originalschichten und entfernt die Toleranz. Details zur
direkten und mehrstufigen 0→1→2→3→4→5-Migration, zum Layer-Snapping,
zur Vorschauauflösung und den
Sicherungen stehen in [Persistenz](settings_migrations.md).

## Prüfungen und reale Abnahme

`test_manual_geometry.py` prüft Anfangsform, Fußabhängigkeiten, exakte
Unterteilung, Punktoperationen, Tangenten, vollständige Kurvenextrema,
Winkelgrenzen, Mesh-Topologie, Fehlergrenze und Abbruch.
`test_manual_persistence.py` prüft Normalisierung, getrennte Werte, Migration,
Backup, atomare Speicherung, unbekannte neuere und beschädigte Dateien sowie
externe Änderungen. `test_manual_generation.py` prüft den festen Einzel-Slice,
gemeinsame Verifikation und Prognose, sichere Layerzuordnung, Originalzeiten
oberhalb eines verkürzten Turms,
Quellen-/Profilschutz und unveränderte exportierte Artefakte.
`test_manual_view_resolution.py` prüft alle Auflösungsstufen, geschlossene
reduzierte Testoberflächen, erhaltene Quelldaten, exakte 100-%-Darstellung und
Abbruch. Die GUI-Tests prüfen zusätzlich Punktmodi, Rechtsklick-Löschen,
eigene Kontrollgriffe, großzügiges Objekt-Endhöhen-Snapping, Toolbarreihenfolge,
zweispaltige Hinweise und das diagonal geteilte Farbsymbol.
Die Stil-Wiederverwendung wird gegen die vorherige Zeichenroutine auf identische
Pixel einschließlich Original-X-Ray und kritischer Layerkonturen geprüft. Weitere
GUI-Regressionen vergleichen den Bildcache mit direkter Flächenwiedergabe in allen
fünf Ansichten bei einfacher und doppelter Pixeldichte. Sie prüfen außerdem
Cache-Wiederverwendung bzw. Invalidierung, enge Einpassung, überlappungsfreie
Skalenüberschriften, die animierte Pfeilleiste einschließlich Richtungswechsel
und Fenstergrößenänderung sowie die symmetrische Mindestmaßlinie und beide Resets.
Die abschließenden 158 manuellen Regressionen bestanden in 35,833 Sekunden,
sechs ergänzende Footer-/Startfensterprüfungen in 1,809 Sekunden. Die Grenzhinweise
werden für manuelle und feste Grund-/Spitzen-/Fußpunkte geprüft, einschließlich
sofortiger Anzeige, 350 ms Haltephase, 200 ms linearem Fade, Wiederauftauchen,
ansichtsabhängiger Entfernung und unverändertem Originalbild. Die breiten,
gestapelten und eingeklappten Layouts sowie vollständig gerenderte Testoberflächen
und beide Phasen des Grenzhinweises wurden zusätzlich visuell kontrolliert.
`test_manual_gui.py` ergänzt Greifer-/Zahlenfeldsynchronisierung, Projektion,
kleine Fenster, Ansichtssperren, Grenzfeedback, unabhängige Sitzungen,
Ergebnisübergänge, alten Export, verspätete Callbacks, tatsächlichen Prozessabbruch,
Schließen und verwaltete räumliche Renderjobs. Zusätzliche Regressionen decken
den unabhängigen Spitzengreifer mit genau einem Kurvenanker, fortgesetzte
Bewegung an Achsengrenzen, zoomabhängige Skalen, ansichtsabhängige Aktionen,
unveränderte Flächencaches bei Pan/Zoom/Resize/Einpassen, identische Proxy- und
Flächenrotation sowie wiederholtes Einpassen reiner G-Code-Quellen ab.
Zusätzliche Tests prüfen Höhen-Snapping, zwei sichtbare Nachkommastellen bei
erhaltener Modellpräzision, die überlagerte Vorderansicht, stabile Vorschaugeometrie
bei Meldungen sowie den echten Hauptfenster-Footer einschließlich gleicher
Kürzungs-/Umbruchregeln und ausschließlich manuellem Reset.

Die abschließende Regressionsprüfung verwendet die vollständige vorhandene
Suite mit `.\.venv\Scripts\python.exe -m unittest discover -s tests -q` und
`QT_QPA_PLATFORM=offscreen`. Unter Windows hält `PYTHONUTF8=1` die Kodierung
von CLI-Unterprozessen und deren Textdekodierung einheitlich; bei gesetztem
`PYTHONIOENCODING=utf-8` muss auch der aufrufende Python-Prozess UTF-8 verwenden.
Reale manuelle Slicerprüfungen stehen zusätzlich
in `test_real_manual_generation.py` und werden explizit mit
`COOLING_TOWER_RUN_REAL_SLICER_TESTS=1` aktiviert. Ohne installiertes passendes
Programm werden sie übersprungen; das ersetzt keine reale Abnahme.

Die ergänzende UI-Prüfung vom 11.10.2026 für die gemeinsame Bedienleiste,
adaptiven Legendenspalten, verschiebbaren Grenzstriche und vollständigen
Turmsegmente bestand mit **1347 Tests in 250,390 Sekunden, 13 übersprungen**.
Breites und schmales Layout sowie Grenzwertanzeige und räumliche Turmdetails
wurden zusätzlich anhand gerenderter Prüfbilder kontrolliert. Die Windows-
Schriftregistrierung der GUI-Testklassen wird nach jeder Klasse vollständig
zurückgenommen, damit nachfolgende Layouttests ihren vorherigen Schriftzustand behalten.

Die anschließenden Ergänzungen für **Turm zurücksetzen**, die kompakten
Ansichtsbuttons mit 2×3-Umbruch und den einheitlichen Drehungs-Reset wurden mit
69 GUI-Tests und 17 Footer-/Methodenauswahlprüfungen abgesichert. Ein- und
zweizeilige Ansichtsgruppen sowie die bedingte Textausblendung wurden zusätzlich
visuell geprüft.

### Abnahme vom 11.10.2026

Die 85 gezielten manuellen Tests bestanden in 16,625 Sekunden. Die reale
Generierung und der Export bestanden mit beiden installierten Adaptern
(zwei Tests in 62,128 Sekunden). Die vollständige Regressionssuite bestand
mit **1315 Tests in 261,130 Sekunden, 13 übersprungen**. Die separat aktivierten
realen manuellen Slicerprüfungen sind damit zusätzlich nachgewiesen. Wegen der
Windows-Sandboxbeschränkungen bei atomaren Hardlinks liefen die Prüfungen mit
dem Projektinterpreter im Host-Kontext; `PYTHONUTF8=1` verhinderte die zuvor
beobachtete unterschiedliche Umlautdekodierung des CLI-Unterprozesses.
Der reale Lauf verwendete 990 Originalschichten,
60.000 Vorschausegmente und neun Profilpunkte; Original-STL und Slicerprofile
blieben nach Vorher-/Nachher-Prüfsummen unverändert. Die kleinsten erreichten
gemeinsamen Layerzeiten betrugen 6,209 s bei Anycubic Slicer Next und 6,0291 s
bei Bambu Studio; Ergebnis und Berichte enthalten keine Zielbewertung mehr.

| Adapter | Bearbeitungsframe, Mittelwert | Langsamster Frame | Erster räumlicher Frame | Vollständige räumliche Flächen bereit |
|---|---:|---:|---:|---:|
| Anycubic Slicer Next | 9,68 ms | 23,69 ms | 102,63 ms | 562,92 ms |
| Bambu Studio | 10,04 ms | 23,44 ms | 103,81 ms | 640,83 ms |

Die Messung lief gleichzeitig mit der vollständigen Regressionssuite und
beschreibt eine lokale Stichprobe. Zusätzliche gerenderte Ansichten prüften
Breiten-Greifer, einzelne Layer bei starkem Zoom, den blauen Hinweis bei
700 Pixeln Fensterbreite und den leeren Footer. Ohne Meldungen betrug seine
Höhe 80 Pixel in der breiten Ansicht beziehungsweise 129 Pixel bei gestapelten
Buttons. Die dazugehörigen Bilder liegen unter `.tmp/resume-manual-*.png`.

### Historische Abnahme vom 10.10.2026

Die folgenden Messungen beschreiben den damaligen Stand mit Zielzeitbewertung;
sie bleiben als historische Vergleichswerte erhalten.
Die vollständige Abschlussprüfung am 10.10.2026 endete nach 459,153 Sekunden
mit `OK (skipped=14)` bei 1299 Tests. Die realen manuellen Prüfungen wurden
zusätzlich aktiviert und bestanden. Die 34 GUI-Tests des manuellen Editors
bestanden auch separat, einschließlich überlagerungsfreier Bedienelemente nach
mehrfachen Wechseln zwischen breiter und gestapelter Oberfläche.
Nach Ergänzung der Snap- und Greiferhöhen-Hilfslinien bestanden die erweiterten
35 GUI-Tests in 12,290 Sekunden. Sie prüfen die sichtbaren Linien in beiden
bearbeitbaren Ansichten, automatische Ausblendung, fortgesetztes Ziehen,
Geometriegrenzen und das sofortige Entfernen der Greiferhöhenlinie beim Loslassen.

Der repräsentative Abnahmelauf nutzt `input/Test-STL (manifold).stl`, das
bestätigte Maschinen-/Druck-/Materialprofil, 990 Originalschichten und ein
manuelles Profil mit neun Punkten und mehreren Aufweitungen/Verjüngungen.
Er erzeugt und exportiert mit den installierten Anycubic-Slicer-Next- und
Bambu-Studio-Adaptern je einen tatsächlichen gemeinsamen Prüfslice. Original-STL
und Originalprofile werden vor und nach dem Lauf gehasht. Die Abnahme zeichnet
30 Bearbeitungsframes mit vollständiger Seitenansicht sowie die erste und
vollständig aufgebaute räumliche Darstellung auf; vollständiges Stylesheet,
Originaldruckbahnen und vollständige STL-Flächen werden verwendet. Auf Windows
lädt der Offscreen-Test die installierte Systemschrift ausdrücklich, weil das
Offscreen-Plugin die Systemschriften nicht selbst aufzählt.
Die Generierung läuft dabei über den produktiven `ManualWorker` und
`BackgroundJobManager` mit dem gemeinsamen Cancellation-Event und eigenem
Qt-Prozessdispatcher. Jeder Adapter erhält für die reale Abnahme einen eigenen
Python-/Qt-Prozess; es gibt keine automatischen Wiederholungen fehlgeschlagener
Prüfslices. Kombinierte Abnahmen mit mehreren geöffneten/geschlossenen
Vorschaufenstern in derselben Qt-Instanz zeigten auf diesem Windows-System
sporadische Bambu-Zeitüberschreitungen nach bereits geschriebenem G-Code.
Die genaue Ursache ist nicht abschließend geklärt. Auch solche Läufe werden
kontrolliert beendet, niemals als geprüftes Ergebnis übernommen und hinterlassen
separate Fehlerdiagnosen. Die vorhandenen Sliceradapter bleiben unverändert.

Die abschließende reale Abnahme am **10.10.2026** bestand mit beiden installierten
Adaptern: zwei Tests in 109,740 Sekunden. Die großen Ansichten wurden bei
1450 × 1000 Pixeln, die gestapelte Oberfläche bei 720 × 1100 Pixeln geprüft.
Die letzte Messung lief gleichzeitig mit der vollständigen Regressionssuite
auf demselben Rechner; sie enthält daher diese zusätzliche CPU-Last.

| Adapter | Bearbeitungsframe, Mittelwert | Langsamster Frame | Erster räumlicher Frame | Vollständiges räumliches Bild bereit |
|---|---:|---:|---:|---:|
| Anycubic Slicer Next | 20,65 ms | 60,23 ms | 262,48 ms | 1764,49 ms |
| Bambu Studio | 21,06 ms | 55,35 ms | 278,20 ms | 1815,16 ms |

Diese Werte beziehen sich auf je 30 Bearbeitungsframes mit neun Profilpunkten,
990 Originalschichten und 60.000 Originaldruckbahnsegmenten. Die erste räumliche
Darstellung zeigt bereits echte reduzierte Druckbahnen; das vollständige
Original-STL wird anschließend im verwalteten Hintergrundjob aufgebaut.
Die geprüfte feste Form blieb beim Slice und Export identisch. Ihre kleinsten
gemeinsamen Layerzeiten betrugen 6,209 s beziehungsweise 6,0291 s. Das Ziel
von 10 s ± 0,25 s wurde damit bewusst nicht erreicht; beide technisch geprüften
Ergebnisse waren mit zutreffender Warnung exportierbar. Original-STL und
Originalprofile blieben gemäß Vorher-/Nachher-Prüfsummen unverändert.

Reproduzierbare Messdaten, Screenshots der großen/kleinen Oberfläche und
exportierte Dateien liegen in `.tmp/manual_acceptance_<adapter>/`;
`acceptance.json` enthält die tatsächlich gemessenen Zeiten und Pfade.
Die Werte beschreiben diese lokale Stichprobe, keine allgemeine Framerate-
oder Zielzeitgarantie. Ergebnisse und Grenzen weiterer nicht installierter
Adapter dürfen daraus nicht abgeleitet werden.
