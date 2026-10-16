# Manueller Kühlturmeditor

Die Methode **Manuelle Generierung** gestaltet einen rotationssymmetrischen
Kühlturm direkt in der eingebetteten Vorschau. Sie verwendet die vorhandene
bestätigte Quelle und Profilbindung. Datei-/Slicervorbereitung und automatische
Formberechnung bleiben eigenständige bestehende Abläufe. Ein Methodenwechsel
erhält die Entwürfe und ihre getrennten Ergebnis- und Exportstände.

## Inhalt

- [Voraussetzungen und getrennte Methoden](#voraussetzungen-und-getrennte-methoden)
- [Bedienung und eigene Einstellungen](#bedienung-und-eigene-einstellungen)
- [Geometriemodell und Invarianten](#geometriemodell-und-invarianten)
- [Tessellierung und STL](#tessellierung-und-stl)
- [Darstellung, Farben und Hintergrundarbeit](#darstellung-farben-und-hintergrundarbeit)
- [Ein unveränderter Prüfslice](#ein-unveränderter-prüfslice)
- [Ergebniszustände und Export](#ergebniszustände-und-export)
- [Prozesse, Persistenz und Dateisicherheit](#prozesse-persistenz-und-dateisicherheit)
- [Prüfungen und reale Abnahme](#prüfungen-und-reale-abnahme)


## Voraussetzungen und getrennte Methoden

Die Anwendung setzt einen unterstützten Slicer voraus. Beide Methoden stehen
erst nach erfolgreicher Datei-/Slicervorbereitung und ausdrücklicher Bestätigung
der Druckprofile zur Verfügung. Der manuelle Editor verwendet die tatsächlichen
Layer der vorbereiteten Quelle, die Druckbettfläche und die verfügbare
Maschinenhöhe. Generieren prüft die gezeichnete Form mit einem Slicer; Export
übernimmt ausschließlich den vollständig geprüften Stand einschließlich seiner
Zeitbewertung. Eine quellen- und slicerunabhängige Turmerstellung wird nicht angeboten.

Automatische und manuelle Erstellung besitzen getrennte `GenerationSession`-Stände.
Ein Wechsel erhält Entwurf, Einstellungen, Kamera sowie Ergebnis und Exportstatus
der jeweiligen Methode. Beim Wechsel zur manuellen Methode ist kein Punkt ausgewählt.
Beide Methoden verwenden die Hauptfenster-Fußleiste; manuelle Resetaktionen betreffen
nur den manuellen Editor. Bei geöffneter Datei-/Slicervorbereitung ist die gesamte
Fußleiste ausgeblendet und erscheint bei Rückkehr zum Editor wieder.
Änderungen der Quelle oder Profile verwerfen die
betroffenen Ergebnisse beider Methoden und den manuellen Kontext. Laufende
Generierungen und Exporte sperren den Methodenwechsel. Beim Schließen werden
die temporären Ergebnisdateien beider Sitzungen freigegeben.

### Rückgängig und Wiederholen

`Strg+Z` und `Strg+Y` sowie die beiden Pfeilbuttons links oben in der Vorschau
stellen vorherige Bearbeitungsstände wieder her. Zusammenhängendes Ziehen zählt
als eine Aktion; neue Änderungen nach einem Rückgängigmachen verwerfen den
Wiederholungszweig. Die Historie hält höchstens 100 Aktionen pro Objektkontext
und enthält Profilform, Auswahl und die zugehörigen Resetwerte. Sie wird nicht
gespeichert und während einer Generierung oder eines Exports gesperrt.
Der Ansichtstext beginnt rechts neben den Pfeilen und erscheint nur, wenn er
vollständig neben die Ansichtsbuttons passt.

### Objektspezifische Simulationen

Unter „Turm und Standfuß“ steht **100% Turmfüllung simulieren** mit derselben
Erklärung wie im automatischen Modus. Die Form bleibt unverändert; der gemeinsame
Prüfslice und das exportierte 3MF verwenden nur für den Turm 100% Füllung und
das passende Füllmuster. Die Übernahme wird zusätzlich im erzeugten G-Code
geprüft. **Stützen für STL-Objekt simulieren** ist bei erkannten deaktivierten
globalen Stützen verfügbar; ihre gemeinsame Bedeutung und die Grenzen der
Vorschau stehen in [Turmgeometrie](tower_geometry.md#objektspezifische-stützen-für-das-original-stl).
Beide manuellen Optionen starten deaktiviert, gelten für die Sitzung und gehören
zur Ergebnisidentität. Sie verändern weder gespeicherte Slicerprofile noch die
manuelle Objektvorschau. „Alles zurücksetzen“ deaktiviert beide Optionen.

Allgemeine Bedienhinweise und Fehlermeldungen
stehen links in der Fußleiste. Nach dem Vorbereiten lautet der Bedienhinweis
„Turmprofil doppelklicken, um freie Punkte hinzuzufügen.“
Fortschrittsbalken und aktueller Prüfschritt erscheinen rechts in der Fußleiste
über den Aktionsbuttons. Nach der Generierung zeigt derselbe Bereich kompakt
die Mindest-Layerzeit von Objekt und Turm, die Prüfart und die Anzahl bewerteter
Layer. Ein gemeinsamer Prüfslice wird als erreichte Zeit ausgewiesen; ein
separater Turm-Slice bleibt ausdrücklich eine Prognose.
Nach einem erfolgreichen Export entfällt die Zusatzzeile zum gemeinsamen
Prüfslice mit Layeranzahl; die erreichte Mindest-Layerzeit bleibt sichtbar.
Der Exportpfad wird nicht als linke Footer-Meldung wiederholt. Die vorhandenen
Öffnen-Buttons führen zu den exportierten Dateien und ihrem Ordner.
Zusätzliche Hinweise stehen in einem zunächst eingeklappten Bereich. Bei langen Meldungen oder
ausgeklappten Details scrollt nur die Rückmeldung; die Buttons bleiben sichtbar.
Ein veränderter Entwurf behält die Ergebniswerte des bisherigen geprüften
Stands und den zugehörigen Hinweis, bis ein neuer Lauf erfolgreich abschließt.

## Bedienung und eigene Einstellungen

Die festen Einstellungsgruppen verwenden denselben grauen Überschriftenverlauf
und dieselbe Schriftgröße wie „Erweiterte Turmeinstellungen“ im automatischen
Modus. Sie bleiben ohne Dropdown und Chevron. Die Gruppen schließen ohne
vertikalen Zwischenraum aneinander an; ihre Ecken
sind rechtwinklig. Sie reichen horizontal vom linken Fensterrand bis an die
Einklappleiste beziehungsweise den sichtbaren Scrollbalken und besitzen keine
seitlichen Rahmenlinien. Die grauen Überschriften haben jeweils eine obere
und untere Rahmenlinie; Einstellungszeilen bleiben ohne Trennlinien.
Die grauen Bereichsbezeichnungen
oberhalb des Editors entfallen. Nur in einspaltiger Darstellung erscheint der
rote Hinweis zum Verbreitern des Fensters, horizontal zur Fenstermitte zentriert.

**Nebeneinander** und **Voreinander** ermöglichen alle Greiferaktionen. Fußrand,
Körperanschluss, oberer Abschluss und freie Profilpunkte besitzen unterschiedliche Greifer.
Fußhöhe und Turmhöhe besitzen horizontale Strichgreifer, jeweils 33 px rechts
neben dem Körperanschluss beziehungsweise der Turmspitze. Gestrichelte
Verlaufslinien verbinden die Geometrie mit den Greifern, dunkel am Turm und
hellgrau am Griff. Die tatsächliche Geometrie bleibt an ihrer Position.
Fußbreite und Fußhöhe bleiben getrennte Greifer. Die Konturlinie der Fußkurve
verwendet denselben lila Farbton wie die Fußgreifer; die Körperkontur bleibt
im bisherigen Profilfarbton.
Die direkten Zahlenfelder in der Vorschau und die Greifer synchronisieren
sich in beiden Richtungen. Durchmesser werden in Millimetern angezeigt, intern
werden Radien gespeichert.
Bei frei beweglichen Profilpunkten und Béziergriffen begrenzt **Shift + Ziehen**
die Bewegung auf eine Achse: die größere Mausverschiebung seit Ziehbeginn
bestimmt waagerecht oder senkrecht. Die andere Koordinate bleibt exakt auf
ihrem Wert zu Ziehbeginn, einschließlich nicht gerundeter oder nicht auf einem
Layer liegender Werte. Die feste Ursprungskopie des Entwurfs erhält diese
Sperre auch beim Achsenwechsel oder Erreichen einer Geometriegrenze. Die
bewegliche Achse verwendet weiterhin ihre normalen Raster- und Grenzregeln.
Die Funktion gilt in beiden manuellen Methoden; die bereits auf eine Achse
begrenzten Breiten-/Höhengreifer behalten ihr Verhalten.
Beim horizontalen Ziehen eines Profilpunkts rasten dessen Durchmesser innerhalb
von 8 Bildschirmpixeln an den Durchmessern seiner direkten Profilnachbarn ein.
Das gilt für feste und freie Nachbarn, auch außerhalb des 0,1-mm-Rasters.
Bézieranker und nicht direkt benachbarte Punkte sind keine Fangziele.
Die unterschiedlichen Z-Höhen bleiben erhalten; alle bestehenden Form-,
Höhenabstands- und Platzierungsgrenzen gelten auch beim Einrasten.
Beim Laden eines Originalobjekts berechnet die gemeinsame Funktion
`tower/base_calculator.py` den anfänglichen Fuß-Außendurchmesser aus dessen
vollständiger analysierter Höhe: 0,21 mm je Millimeter Objekthöhe, begrenzt auf
25–80 mm. Reicht die tatsächlich freie Druckbettfläche nicht dafür, wird der
anfängliche Fuß auf die verfügbare Breite begrenzt. Eine niedrigere Maschinen- oder später geänderte Turmhöhe verkleinert
diesen Referenzwert nicht. Die bestehende Anschlussregel hält den Fuß bei Bedarf
mindestens 2 mm breiter als den Körperbeginn; die allgemeine 1000-mm-Grenze und
die geprüfte Druckbettplatzierung bleiben verbindlich.
Der resultierende Startwert ist der Fuß-Resetstandard des aktuellen Objekts.
Ein gespeicherter Fußwert vom vorherigen Objekt ersetzt diese Berechnung nicht.
Manuelle Eingaben und Greiferänderungen dürfen vom berechneten Startwert abweichen.
Die anfängliche maximale Fußbreite und ihr Objektstandard ergeben sich aus der
größten sicheren Kreisfläche neben dem belegten Objektbereich auf dem Druckbett
(siehe Platzierungsprüfung unten), statt aus einem pauschalen 80-mm-Wert.
Benötigt eine manuelle Fuß-/Körperverbreiterung mehr als die zwischenzeitlich
verringerte Fußgrenze, wächst diese genau auf die benötigte Fußbreite, sofern
die geprüfte Platzierung dies zulässt.
Die erweiterte Grenze wird zum neuen Standard für dieses Objekt; späteres
Verkleinern des Fußes senkt sie nicht automatisch. Einzel-Reset, Formreset und
Gesamtreset behalten diesen Objektstandard. Eine unabhängig eingegebene größere
Fußgrenze verändert den Standard nicht. Beim Laden eines anderen Objekts werden
die objektbezogenen Standards neu bestimmt.
Bei sehr schmaler freier Bettfläche wird auch der rücksetzbare minimale
Körperdurchmesser so begrenzt, dass sein Fußstandard mit der Anschlussregel
weiterhin platzierbar bleibt. Formreset und Gesamtreset verwenden diese
kontextbezogenen Standards.
Eine schmale, über die gesamte Einstellungshöhe reichende Pfeilleiste liegt
rechts neben dem Einstellungs-Scrollbalken und vor der Trennlinie. Sie klappt
die Einstellungen in 250 ms ein oder aus. Eingeklappt bleibt die Leiste ganz
links, der Pfeil zeigt nach rechts und die Vorschau erhält den freien Platz.
Die Werte bleiben erhalten. Bei schmalen Fenstern bleiben die aufgeklappten
Einstellungen wie bisher oberhalb der Vorschau angeordnet; eingeklappt steht
auch dort nur die schmale Leiste links. Dieser Anzeigezustand wird nicht gespeichert.
Die Scrollposition wird nach dem Aufklappen wiederhergestellt, sobald die
Layout-Umstellung abgeschlossen ist; bei kürzerem Inhalt gilt der verbleibende gültige Bereich.
Kurzzeitig veränderte Scrollbereiche werden während der nachfolgenden
Layoutkorrekturen berücksichtigt. Diese Wiederherstellung ist zeitlich begrenzt
und endet sofort bei einer Scrollaktion des Benutzers.
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
Die Position liegt auf dem bisherigen Profil; eine bestehende Bézierkurve
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
Freie Punkte lassen sich per Rechtsklick oder Entf/Backspace entfernen;
beim Entfernen werden ausschließlich die beiden zum entfernten Punkt gerichteten
Nachbaranker auf Drittelpunkte der neuen Verbindung zurückgesetzt. Das gilt auch
für feste Nachbarpunkte; deren gegenüberliegende Anker und weitere Kurven bleiben
unverändert. Eine Tangentenkopplung an diesen beiden Nachbarn wird gelöst, damit
sie keine zusätzlichen Anker verändert.
Fuß, Körperanschluss und oberer Abschluss bleiben erforderlich. Jeder Abschnitt
kann gerade oder als kubische Bézierkurve bearbeitet werden. Kontrollgreifer
erscheinen am angewählten Punkt: sein eingehender und sein
ausgehender Griff. Neue freie Punkte zeigen beide Griffe sofort nach dem
Hinzufügen per Profildoppelklick.
Bei freien Punkten zeigt bereits der erste einfache Klick
ohne Ziehen beide Griffe, auch wenn die angrenzenden Abschnitte noch linear sind.
Die Anzeige allein ändert weder Kurvenmodus noch Form; das Ziehen eines
Kontrollgriffs formt seinen Abschnitt als Bézierkurve. Das Ziehen am freien
Profilpunkt verschiebt weiterhin den Punkt. Ein weiterer Doppelklick setzt die
Kontrollgriffe erneut zurück, ohne sie auszublenden.
Dieser Doppelklick-Reset gilt ausschließlich in Nebeneinander und Voreinander;
in Drauf- und Untersicht sind Funktion und Bedienungshinweis nicht verfügbar.
Ist ein fester oder freier Profilpunkt oder einer seiner Kontrollgriffe ausgewählt, erscheinen
zusätzlich die zu ihm gerichteten Kontrollgriffe beider direkt benachbarten Punkte,
unabhängig davon, ob diese fest oder frei sind. Bei einem Kontrollgriff bestimmt
sein zugehöriger Profilpunkt die direkte Nachbarschaft; der Kontext bleibt auch
beim Wechsel vom Punkt auf seinen Kontrollgriff erhalten. Die zugewandten
Nachbargriffe bleiben auch bei linearen Abschnitten sichtbar. Weiter entfernte
Punkte und die abgewandten Griffe der Nachbarn werden nicht eingeblendet.
Fußrand und Fußhöhe besitzen
jeweils ihren eigenen Fußkurvengriff sowie die zugewandten Nachbargriffe. Der reine Auswahlklick ändert keine
Geometrie. Beim Auswählen eines Kontrollgriffs bleiben die Griffe seines
zugehörigen Profilpunkts sichtbar.
Ein Klick auf eine leere, nicht interaktive Fläche hebt die Auswahl auf;
Navigationsbewegungen und Profildoppelklick bleiben davon getrennt.
Innenpunkte können ihre Tangenten
koppeln; beide Seiten erhalten dann dieselbe lokale Steigung.

Numerische Einstellungen besitzen Einheit, Info und bei vorhandenem Standardwert
einen Reset. Wiederverwendbare
manuelle Werte werden separat gespeichert, einschließlich Farbreferenz für das
Original, Durchmessergrenzen, Fußwerte und Kreissegmentzahl. Im manuellen Modus
gibt es weder eine gewünschte Mindest-Layerzeit noch eine Layerzeit-Toleranz.
Die Farbreferenz in „Visuelle Prüfung“ färbt ausschließlich Originalschichten;
sie bewertet weder den gestalteten Turm noch das geprüfte Ergebnis. Der Gesamtreset
erzeugt einen neuen gültigen Anfangsentwurf. Manuell hinzugefügte Profilpunkte
haben keinen Positionsstandard und keine Positions-Resetbuttons in der
Vorschau. Ihre Kurven lassen sich weiterhin zurücksetzen.
Feste Punkt-/Kontrollpunktresets verwenden den Ausgangswert des jeweiligen
stabil identifizierten Greifers. Die
Automatikeinstellungen werden dabei nicht verändert.

Der ausgewählte Greifer besitzt zusätzlich einen kompakten Werteeditor in einer
gemeinsamen, abgerundeten Box mit leicht transparentem Hintergrund. Er steht
rechts neben den nahen Punkten und verwendet kleine Bezeichner (7,5 pt) sowie
Eingaben (8 pt). Doppelte numerische Grundinformationen entfallen; eine vorhandene
Layernummer steht als reine Information oberhalb der zugehörigen Eingabefelder.
Übernommene Zahlen werden immer mit zwei Nachkommastellen angezeigt. Die interne
Genauigkeit bleibt erhalten; unverändertes oder leeres Bestätigen übernimmt den
präzisen bisherigen Modellwert und validiert nicht den gerundeten Anzeigetext.
Alle Felder verwenden dieselbe, am längsten angezeigten Inhalt gemessene Breite;
beim Tippen, Übernehmen, Zurücksetzen und externen Ändern wächst oder schrumpft
die ganze Feldspalte gemeinsam. Die feste Einheit `mm` steht innerhalb jedes
Feldes und zählt zur Breite, bleibt jedoch vom editierbaren Zahlentext getrennt.
Reset-Buttons schließen direkt rechts an. Zusätzliche Werte wie die Layernummer
stehen ebenfalls in der Feldspalte, ihr Bezeichner in der Bezeichnerspalte.
Breiten- und Höhengreifer bekommen jeweils ihr eigenes Feld, freie Profilpunkte
beide Koordinaten. Béziergriffe zeigen die Felder des zugehörigen Profilpunkts;
die Box bleibt auf dessen Höhe. Während des Ziehens bleibt ihre Position
erhalten und ändert sich nur bei einem kollidierenden Greifer oder geänderten
Anker-/Vorschaumaßen. Werte mit Standard besitzen einen eigenen Reset auf
den jeweiligen Objektstandard. Die kleinen Reset-Buttons verwenden
einen selbst gezeichneten Rücksetzpfeil, unabhängig von Schriftglyphen.
Die gesamte Box bleibt außerhalb der Ansichtsleiste und innerhalb der Vorschau;
bei fehlendem Platz rechts wechselt sie neben die linken Greifergrenzen.
Die zehn redundanten linken Maß- und Grenzfelder sowie die Buttons
„Punkt hinzufügen“ und „Punkt entfernen“ entfallen. Maße, Durchmessergrenzen
und freie Profilpunktkoordinaten werden direkt in der Vorschau eingestellt;
Punkte werden dort per Doppelklick hinzugefügt und per Rechtsklick oder
Entf/Backspace entfernt. Links bleiben Kreissegmente, geometrische Winkelgrenzen,
Layer-Snapping, Abschnittsmodus, Tangentenkopplung und visuelle Prüfeinstellungen.
Die beiden präzisen Béziergriff-Koordinatenfelder bleiben ebenfalls links, da
der direkte Editor bei einem ausgewählten Kontrollgriff dessen Profilpunkt zeigt.
Die Auswahl der Vorschaugreifer und das Hinzufügen von Punkten benötigen
derzeit weiterhin die Maus.

In den beiden Profilansichten erscheint beim Hover innerhalb von 33 px links
oder rechts einer der beiden Körperkonturen ein heller, leicht transparenter
grüner Einfügepunkt stets auf der rechten Konturkante, auch bei Annäherung
an die linke Turmseite. Eine unverbindliche Einfügeoperation
prüft dieselben Kurven-, Nachbarabstands- und Kontextgrenzen wie die tatsächliche
Aktion. Fußkurven, Stellen nahe vorhandener Greifer oder ungültige Kandidaten
werden nicht angeboten. Ein Doppelklick in diesem Bereich fügt den angebotenen
Punkt ein; Hover allein verändert den Entwurf nicht. Bei Ziehen, Zoom,
Ansichtswechsel und Verlassen der Vorschau verschwindet die Markierung.

Während der Eingabe prüft ein unverbindlicher Entwurf die vollständige Geometrie
und Druckbettplatzierung. Ungültiger Text bleibt rot, bis die Eingabe gültig ist.
Enter übernimmt ausschließlich einen vollständig gültigen Kandidaten; es gibt
keine teilweise akzeptierte Zahlenänderung. Leeres oder unverändertes Bestätigen
erhält den bisherigen internen Wert und den Kurvenmodus. Erfolgreiche Bestätigung
färbt Text und Rahmen 350 ms grün, abgelehnte Bestätigung rot; anschließend läuft
ein 200-ms-Fade. Die Felder und der Eingabefokus bleiben bestehen. Noch nicht
bestätigte Texte überstehen andere Einstellungsänderungen. Hintergrundaufträge
sperren auch diese Eingaben; Enter löst keine Generierung aus.

Ungültige Bewegungen gelangen nur bis zur ersten gültigen Grenze. Bei einer
diagonalen Bewegung werden anschließend beide Achsen einzeln gegen das gesamte
Profil und die Druckbettplatzierung geprüft. So bleibt beispielsweise die Höhe
eines freien Punkts beweglich, wenn sein Durchmesser bereits das Minimum erreicht.
Die tatsächlich
begrenzende Einstellung wird ausschließlich an Bezeichnung und Eingaberahmen
kurz rot markiert; zusätzliche rote Meldungstexte unter den manuellen Feldern
entfallen. Hintergrund und eingegebener Zahlenwert behalten ihre normale Farbe.
Die Farbänderung hält 850 ms und blendet in 200 ms linear zur normalen Farbe zurück;
die Haltephase ist 500 ms länger als die der Grenzlinie. Weitere Ereignisse während
der Animation verlängern sie nicht; nach ihrem Ende kann ein neuer Grenzversuch
die Markierung erneut auslösen. Der Grund bleibt im Footer und für assistive
Technik verfügbar. Auch Werte, die Qt bereits
an seinen Eingabegrenzen abfangen würde, gelangen zur fachlichen Grenzprüfung.
Unmögliche Optionswechsel werden zurückgewiesen. Der letzte gültige Entwurf
bleibt erhalten. Bei einer für die Quelle ungültigen gespeicherten Konfiguration
können Einstellungen korrigiert und die Initialisierung erneut versucht werden.

Die **Draufsicht** erlaubt die Spitzenbreite und die Turm-Durchmessergrenze,
die **Untersicht** die Fußbreite und die Fuß-Durchmessergrenze. Die **Freie 3D-Ansicht** beginnt in der 3/4-Ansicht
und besitzt keine Greiferaktionen. Ihre Navigation entspricht der aktivierten
Navigation der automatischen 3D-Vorschau: linke Maustaste dreht, rechte oder
mittlere Maustaste verschiebt, Mausrad zoomt zur Ansichtsmitte. Drehgeschwindigkeit,
Neigungsgrenzen und Zoomschritte/-grenzen stimmen ebenfalls überein. In den
übrigen Ansichten zoomt das Mausrad weiterhin um die Mausposition und die
mittlere Maustaste verschiebt.
„Einpassen“ stellt beide
Objekte vollständig und mit demselben physikalischen Maßstab dar. Der Button ist
dezent grün, solange Zoom, Verschiebung, Orientierung oder relevante äußere
Abmessungen von der zuletzt eingepassten Darstellung abweichen. Einpassen hebt
diese Markierung auf; Fenstergrößen-, Farb- und Auflösungsänderungen allein
aktivieren sie nicht. Objektrotation,
Transparenz, Auswahl, Hover und Kamera verändern keine Druckdatei.
Die Einpassung nutzt die tatsächlichen projizierten Objektgrenzen und Turmsegmente
ohne pauschale Reserve in Millimetern oder Prozent. In den Profilansichten werden
die Maximaldurchmesser-Griffe nur auf ihrer rechten Seite berücksichtigt, links
die tatsächliche Turmbreite. Überstehende Höhengriffe werden nur mit ihrem
tatsächlichen Pixelbedarf berücksichtigt. Zwischen dem äußersten Griff und dem
Original bleiben beim Einpassen 15 Pixel Abstand. Beide Objekte verwenden
denselben Maßstab und nutzen die verfügbare Höhe vollständig, solange die
gemeinsame Breite einschließlich der Griffe und ihres Abstands hineinpasst.
Die STL-Gesamthöhe wird auch dann berücksichtigt, wenn der letzte Drucklayer
etwas darunter liegt.
Ein neuer Quellenkontext wird auch in einer bereits verwendeten Vorschau neu
eingepasst. Über den Objekten bleiben
mindestens 20 Pixel Abstand zu den Ansichtsbuttons. In den Profilansichten ist
unterhalb der Druckbettebene Platz für die Mindestdurchmesser-Maßlinie reserviert;
die räumlichen Ansichten behalten einen kleinen unteren Abstand von 24 Pixeln.
Die Einheiten stehen jeweils links neben ihrer Skalenleiste, einschließlich
**Layer** an der rechten Leiste. Zahlen und Einheiten überlappen auch bei enger
Einpassung nicht.

Über der Vorschau stehen in einer gemeinsamen Zeile **X-Ray (Transparenz)** mit den zwei
gleich breiten Buttons **Turm** und **STL**,
**Auflösung (STL)** und
**Originalobjekt drehen** mit Slider, Winkelwert und Reset. Diese drei Bereiche
sind kompakt und haben zentrierte Überschriften; ihre Höhe entspricht
einem regulären Aktionsbutton. **Turm** stellt ausschließlich den Turm mit der
bisherigen Deckkraft 35 % dar, **STL** ausschließlich das Original mit 28 %.
Beide Buttons sind unabhängig schaltbar; erneuter Klick deaktiviert die jeweilige
Transparenz. Standardmäßig sind beide ausgeschaltet und dezent orange bzw. hellblau.
Helle obere/linke und dunklere untere/rechte Kanten lassen sie leicht erhaben wirken.
Aktiviert erscheinen sie im kräftigeren umgekehrten Farbverlauf, mit dunkleren
oberen/linken Kanten und fettem, leicht versetztem Text; dadurch wirken sie eingedrückt.
Beide Objekte können gleichzeitig transparent sein. Die Rahmenbreite
bleibt bei allen Zuständen identisch (1 px). Die bevorzugte Buttonbreite wächst
gegenüber der bisherigen Leiste um etwa ein Fünftel. Bei Platzmangel verkleinern
sich zuerst Auflösung und
Drehung; erst danach wird die X-Ray-Gruppe kompakter. Die Überschrift kürzt sich
auf **X-Ray**, die Buttons bleiben gleich breit und schrumpfen bis zur für
beide Texte erforderlichen Mindestbreite. Sie brechen nicht um.
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
Zoom steht zuletzt. Der Drehslider reicht von −180° bis +180°; der Standard 0°
steht genau in der Mitte und wird vom Reset wiederhergestellt. Er besitzt sichtbare Teilstriche alle 45° und
rastet beim Ziehen innerhalb von ±3° an diesen Winkeln ein. Andere Winkel bleiben
einstellbar; Tastaturänderungen erfolgen weiterhin gradweise. Ein Linksklick auf
die Slider-Leiste setzt den Greifer direkt an die angeklickte Position; bei
gehaltener Maustaste lässt er sich von dort weiterziehen. Der Drehslider
verwendet den klassischen Qt-Fusion-Stil mit blauer Leiste und einem schwarzen
1-Pixel-Rahmen; auch der Auflösungsbalken besitzt einen schwarzen 1-Pixel-Rahmen.
Sein weißer, leicht abgerundeter Greifer hat einen schwarzen
2-Pixel-Rahmen, entsprechend der Rahmenstärke des Auflösungs-Sliders. Die
Greifer beider Slider besitzen dieselbe Form und Größe und verwenden dieselbe
zentrale Stildeklaration. Die Darstellung bleibt unabhängig vom Windows-Theme. Seine
45°-Teilstriche liegen unterhalb des Balkens auf derselben Höhe wie die
Schrittmarkierungen der STL-Auflösung. Der kompakte Slider bleibt innerhalb
der bisherigen Werkzeugleistenhöhe und verschiebt die Vorschau nicht. Die
Überschrift behält ihre vertikale Position und ist über der Leiste ohne die
Wert-/Resetspalte zentriert. Über jedem 45°-Einrastpunkt steht dessen Gradwert
im selben grauen Stil wie die Auflösungstexte. Bei Platzmangel werden zuerst
die Werte ±45° und ±135°, danach bei Bedarf ±90° ausgeblendet. Zwischen den
verbleibenden Beschriftungen bleiben mindestens 12 Pixel Abstand; −180°, 0°
und 180° bleiben sichtbar, solange auch dafür genug Platz besteht. Beim
Verbreitern erscheinen die Werte wieder. Die Winkelanzeige steht
rechts neben dem Drehslider mit demselben Textabstand wie der Prozentwert
und zeigt ganze Grad ohne Nachkommastellen. Beide Zahlenwerte sind vertikal
zur Mitte ihres jeweiligen Slider-Balkens ausgerichtet. Beide Balken
sind um 3 Pixel nach oben versetzt; ihre Teilstriche sind nach oben um 1 Pixel verlängert.
Farbquadrate passen sich der Schriftgröße an; bei kritischer
Original-Layeranzeige ist das Objektquadrat diagonal von links unten nach
rechts oben geteilt, links oben rot und rechts unten grün.

Die Maximaldurchmesser werden zusätzlich als verschiebbare vertikale Grenzstriche
angezeigt: violett für den Fuß, blau für den Körper. Ihre Position entspricht dem
halben Durchmesser von der Turmachse aus (Ø 50 mm entspricht 25 mm Abstand).
Eine gestrichelte horizontale Linie verbindet sie mit der Profilkante. Sie
verwendet wie die Mindestdurchmesser-Maßlinie einen Farbverlauf von Dunkelgrau
am Turm bis zum bisherigen Hellgrau am Greifer, auch in Drauf- und Untersicht.
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
validierten 0,1-mm-Durchmesserschritte wie die Maximalgrenzen. Der Mindestwert
beträgt **1,00 mm**. Beim Erhöhen werden alle unterschreitenden festen und freien
Profilpunkte einschließlich Grunddurchmesser, Standfuß, Spitze und Bézier-Anker
an die neue Grenze angehoben. Während einer Greiferbewegung basiert jeder Schritt
auf der Form beim Drücken: Beim Zurückziehen kehren die Punkte bis zu ihren
ursprünglichen Positionen zurück. Erst das Loslassen übernimmt die neue Form
dauerhaft. Eine bestätigte Zahleneingabe übernimmt Grenze und Form sofort;
ein späteres Verkleinern der Mindestgrenze verschiebt die Punkte nicht zurück.
Maximaler Turm- und Standfußdurchmesser bleiben unverändert und verbindlich.
Höhen, gerade Abschnitte und gekoppelte Tangenten bleiben erhalten; die vollständige
Geometrie- und Platzierungsprüfung gilt weiterhin. Der Grunddurchmesser kann die
Mindestgrenze nicht verschieben. Im Greifer-Infobereich heißen die Fußbreiten
**Standfuß-Ø** und **Max. Standfuß-Ø**.
Beide Footer-Resets stellen Mindestgrenze und Turmform wieder her.
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
Auch Grenzversuche mit Béziergriffen blenden die betroffenen Linien ein.
Die Mindestgrenze gilt ebenfalls für die gesamte Fußkurve. Bézier-Kontrollgriffe
dürfen die Durchmessergrenzen überschreiten, solange die vollständige Kurve
einschließlich ihrer analytisch ermittelten Extrema innerhalb der Grenzen bleibt.
Erst eine tatsächlich unzulässige Turmform stoppt die Bewegung und zeigt die
symmetrischen Grenzlinien.
Bei gekoppelten Tangenten werden alle verletzten Durchmessergrenzen der
versuchten vollständigen Form angezeigt. Unzulässige Kontrollgriffhöhen zeigen
die erreichte Grenze als horizontale Linie. Zeitverlauf und gültiges Abfangen
der Geometrie bleiben unverändert.

Der Regler **Auflösung (STL)** besitzt die neun Stufen **0 %, 1 %, 5 %, 10 %,
15 %, 25 %, 50 %, 75 %, 100 %**, von Performance zu Optik.
Der Bereich erscheint in allen fünf Ansichten. Sein
schriftgroßes Info-Icon links neben der Überschrift erklärt beim Überfahren,
dass ausschließlich die Vorschau des Originals reduziert wird und der Export
immer die volle Originalqualität erhält. Alle Stufen über 0 % verwenden eine
automatische Netzqualität; der Wert gewichtet Performance und Optik und ist
kein prozentualer Anteil der Originalflächen.
Die 0-%-Stufe ist hellblau und zeigt eine vollständige Silhouette ohne Netzlinien,
Flächenbeleuchtung oder Netzreduktion. Ihre Konturen verwenden die exakten
Originalkoordinaten und erhalten Löcher sowie getrennte Objektinseln.
Die Kanten-/Flächennachbarschaft wird einmal im Vorbereitungsjob in eigenem
Speicher aufgebaut. Bei Kameraänderungen werden nur die sichtbaren Konturkanten
ausgewählt und deren Endpunkte projiziert. Bei Pan/Zoom bleibt das vorhandene
Vektorbild wiederverwendbar. Diese Variante hat den geringsten Zeichenaufwand;
geschlossene, eindeutig orientierte Netze starten ohne verzögerte Netz-Drahtvorschau.
Gemeinsam genutzte non-manifold Knoten verhindern diesen schnellen Konturweg
nicht, solange alle Kanten geschlossen und konsistent orientiert sind.
Bei offenen, mehrfach belegten oder uneinheitlich orientierten Kanten wird stattdessen
die Vereinigung der projizierten Originaldreiecke gefüllt; dadurch werden keine
geschlossene Hülle, zusätzlichen Verbindungen oder geschlossenen Öffnungen
angenommen. Umfangreiche Fälle werden im Hintergrund gezeichnet. Kritische Layerfarben bleiben
verfügbar: in den Profilansichten als vollständige farbige Silhouettenbänder,
in räumlichen Ansichten als Konturen. Umfangreiche Farbdaten werden weiterhin
im Hintergrund vorbereitet; bis dahin bleibt die vollständige einfache
Silhouette sichtbar. Bei reinen G-Code-Quellen ohne Original-STL bleibt die
vorhandene Druckbahndarstellung erhalten.
Der anschließende Farbverlauf von Grün über Gelb zu Rot richtet sich nach den tatsächlichen
Prozentwerten der Stufen; die vielen niedrigen Stufen bleiben überwiegend grün.
Jede Stufe besitzt einen Teilstrich; der erste ist ebenfalls hellblau.
Die zentrierte Überschrift mit Info-Icon steht in der ersten Zeile.
Darunter stehen links **Performance** und rechts **Optik** in Grau (7,5 pt,
mit beibehaltener Zeilenhöhe), in der dritten Zeile der Slider.
Die beiden Endtexte richten sich ausschließlich nach der Sliderbreite und
verschwinden gemeinsam, bevor ihr Abstand unter 12 Pixel fallen würde.
Die äußere Höhe der gemeinsamen Bedienleiste bleibt erhalten. Beide
Hoverhinweise enthalten ausdrückliche Zeilenumbrüche. Der Reset rechts
stellt die Standardauflösung wieder her und verwendet die üblichen
Resetzustände; während eines Auftrags ist er ebenfalls gesperrt.
Der Standard ist in allen Ansichten **75 %** (Stufe 8).
Ansichtswechsel behalten die eingestellte Auflösung bei. Bestehende gültige
individuelle Prozentwerte bleiben beim Laden erhalten. Einzel-Reset und
**Alles zurücksetzen** stellen die Auflösung auf 75 % zurück;
der reine Ansichtswechsel aktiviert bei sonst unverändertem Zustand keinen Reset.
Der gewählte Prozentwert wird als manuelle Qualitätspräferenz in Schema 9
gespeichert. Kleine Teilnetze mit höchstens 6.000 Dreiecken bleiben vollständig.
Auch größere Teilnetze bleiben unverändert, wenn weniger als 20 % ihrer Flächen
eingespart werden oder die Qualitätsprüfungen fehlschlagen. Niedrige positive
Stufen bevorzugen Performance, hohe Stufen strengere geometrische Genauigkeit;
auch 100 % verwendet diese automatische Entscheidung.

`preview/display_mesh.py` verwendet eine begrenzte, vektorisierte Rasterreduktion
ohne zusätzliche Bibliotheken. Nur über Originalkanten verbundene Punkte
innerhalb desselben Teilobjekts dürfen zusammengefasst werden. Scharfe
Kantenpunkte bleiben exakt. Das ungefähre Zielbudget steigt von etwa 4.000 auf
16.000 Flächen; es hängt nicht proportional an der Originalpolygonzahl.
Der maximale Punktversatz beträgt je nach Präferenz höchstens 2,0 bis 0,7 % der
Teilobjektdiagonale, zusätzlich begrenzt auf 6 % seiner kleinsten räumlichen
Ausdehnung. Größere Facetten dürfen ihre Normale um höchstens 35 Grad ändern;
Facetten unterhalb des geometrischen Fehlermaßstabs dürfen stärker geglättet
werden, aber keine Flächennormale darf umklappen. Die Oberflächenfläche darf um
höchstens 5 % abweichen. Problematische Cluster werden lokal geschützt, statt das
gesamte Teilobjekt beim ersten Fehlversuch auf Originalauflösung zurückzusetzen.
Bei erforderlicher Verfeinerung werden überholte lokale Sperren zurückgesetzt.
Es gibt höchstens 16 begrenzte Verfeinerungsdurchgänge im Hintergrund.
Kandidaten müssen an ihren Kanten geschlossen und konsistent orientiert bleiben;
Komponentenanzahl, Euler-Charakteristik und vorhandene singuläre Knotenpositionen
bleiben erhalten. Das komplette direkte Nachbarschaftsnetz solcher Knoten bleibt
unverändert. Neue singuläre Knoten sind nicht erlaubt.

Offene, degenerierte, doppelte oder uneinheitlich orientierte Teilobjekte werden
nicht reduziert oder repariert. Non-manifold Punktstellen allein führen nicht mehr
zum pauschalen Rückfall: Ihre direkten Nachbarschaften bleiben geschützt, während
sich der restliche sichere Bereich reduzieren lässt. Andere klar getrennte,
sichere Teilobjekte können unabhängig reduziert werden. Exakte Koordinaten und vorhandene Kanten
bestimmen die Komponenten; es gibt kein toleranzbasiertes Verschweißen.
Die Punktverschiebung wird zusätzlich auf 20 % des konservativen Mindestabstands
zwischen den Teilobjekt-Boundingboxen begrenzt. Bei überlappenden Boundingboxen
(auch ineinanderliegenden Hüllen) bleiben die betroffenen Teilobjekte vollständig;
bei mehr als 256 Komponenten entfällt die gesamte Reduktion. Diese Prüfungen ersetzen keine allgemeine
Selbstschnittprüfung oder Reparatur der Original-STL. Eine aufwendige QEM-Optimierung,
kamera-/zoomabhängige Netzneuberechnung und dauernde Laufzeitregelung werden nicht
eingeführt. Die Topologie wird einmal vorbereitet, bis zu acht zuletzt verwendete
Auflösungsvarianten bleiben im begrenzten Sitzungscache; Kameraänderungen verwenden
sie erneut. Farbliche Original-Layerkonturen verwenden weiterhin ihre
unreduzierten Quellkoordinaten; ihre Bildschirmzeichnung folgt bei großen Quellen
der gewählten Rasterqualität. Originaldaten, Analyse, Turm und Druckexport bleiben
in ihrer bisherigen Genauigkeit. Die Regleränderung erneuert nur den
Original-Flächencache; Pan, Zoom, Einpassen und Transparenz bauen keine neuen
Flächen. Fertige Ansichten werden zusätzlich wiederverwendet: höchstens zehn
Zeichenfolgen mit zusammen maximal 32 MiB einschließlich ihrer X-Ray-Varianten.
Quellenwechsel löschen diesen Cache. Konturen werden unabhängig von der Netzstufe
zwischengespeichert (höchstens acht Varianten, konservatives Speicherbudget 16 MiB).
Das Zurückschalten auf eine bereits aufgebaute Stufe startet keinen neuen Worker.
Für alle Netzstufen über 0 % zeigen alle fünf Ansichten einschließlich
der **freien 3D-Ansicht** zusätzlich die exakte Silhouette aus dem
vollständigen Originalnetz. Sie füllt die Außenform unter dem schattierten Netz
mit einem einfarbigen hellen Button-Blau (`#add3ee`, 82 % Deckkraft);
Original-X-Ray wirkt weiterhin auf die gesamte Originaldarstellung.
Das Netz wird an dieser Kontur einschließlich innerer Öffnungen beschnitten.
Eine schmale Konturlinie macht die tatsächlichen Grenzen sichtbar. Die Netzstufe
bestimmt weiterhin Flächendetails und Tiefe. Für die Dreiecksvereinigung unsicherer
Netze entfällt die Konturlinie, damit keine internen Dreieckskanten als Außenkontur
erscheinen.
Die Silhouette und das Netz verwenden dieselbe Objektdrehung und Projektion;
ein neuer Winkel erneuert beides. Pan/Zoom verwenden das fertige Vektorbild erneut.
Bei Hintergrundberechnung zeigen auch freie Ansichten bereits die vollständige
Silhouette geschlossener sicherer Netze, bis das Polygonnetz fertig ist. Bei
unsicheren umfangreichen Netzen bleibt eine begrenzte Drahtvorschau sichtbar,
bis die Originaldarstellung bereitsteht.

Bei insgesamt mehr als 6.000 Originaldreiecken zeichnet der Worker die
Flächenschattierung in ein eigenes begrenztes `QImage` und zeichnet dieses einmal
in die fertige `QPicture`-Zeichenfolge. Die lange Bildkante steigt mit der
Qualitätspräferenz von rund 512 auf 1.280 Pixel (plus kleiner Rand). Der GUI-Thread
spielt beim Pan/Zoom dadurch ein Bild statt zehntausender Flächen-/Knotenbefehle
ab. Originalkonturen bleiben Vektoren in tatsächlicher Bildschirmpräzision;
innere Schattierung darf bei niedrigen Stufen bzw. starkem Zoom weicher sein.
Alle großen Netzstufen verzichten auf Einzelpunkte; Kanten erscheinen erst ab
75 %. Kleine Quellen behalten die volle vektorielle Detaildarstellung. Normal-
und X-Ray-Bilder werden separat mit ihrer bisherigen Deckkraft pro Fläche
berechnet; X-Ray wird nicht nachträglich als pauschale Bildtransparenz angenähert.
Widget- oder `QPixmap`-Zugriffe erfolgen dabei nicht im Worker.

Während eines Vorbereitungs-/Generierungs-/Exportauftrags ist der
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

`ManualContext.validate()` ergänzt Kontextbindung, Höhe und die manuelle
Druckbettplatzierung. `manual/placement.py` sucht den größten sicheren Kreis
innerhalb des Bettpolygons, außerhalb aller Sperrflächen und mit mindestens
**0,3 mm** zum belegten Objektbereich. Dieser Bereich ist das konservative
XY-Rechteck der vorbereiteten Quelle einschließlich Stützen; freie Löcher oder
Einbuchtungen innerhalb dieses Rechtecks werden nicht als Stellfläche angenommen.
Der wirksame Turm-Brim wird vom Radius abgezogen. Die zweistellige maximale
Fußbreite wird nach unten gerundet und ist ebenso wie das **gesamte** Profil
bei jeder Änderung verbindlich. Vorschau und Slice verwenden denselben
sicheren Kreismittelpunkt; die automatische Methode behält ihre vorhandene
Platzierung mit größeren Sicherheitsabständen.

Für rechteckige Betten ohne Sperrflächen wird die maximale Kreisbreite über
eine Radius-Bisektion und die Ecken des eingerückten Bettrechtecks berechnet.
Andere Bettpolygone verwenden eine räumliche Suche mit konservativen
Distanzobergrenzen und höchstens 0,002 mm Radiusabweichung. Die Berechnung läuft
bei der Referenzaufbereitung im abbrechbaren Hintergrundjob; bis zu 32
unveränderte Geometriekontexte werden zwischengespeichert, damit Ziehen und
Zahlenvalidierung keine erneute Suche auslösen. Fehlende verlässliche Bettdaten
oder eine nicht passende Form erlauben keine normale Generierung.

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
`max(30, ceil(Fußdurchmesser in mm))` festgelegt und anschließend als eigener
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

„Überhangstellen visuell markieren“ ist standardmäßig aktiviert; eine gespeicherte
Abwahl bleibt erhalten. „Alles zurücksetzen“ aktiviert die Markierung wieder.
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
bei kleinen Netzen kontrastierende Netzkanten und sichtbare Knoten. Details werden zusammen mit
jeder Fläche nach Tiefe gezeichnet, damit verdeckte Rückseiten verdeckt bleiben.
Die Normalen werden erst nach der Originalrotation berechnet; 0° behält die
ursprüngliche Orientierung. In Drauf-, Unter- und freier Ansicht verwenden Original
und Turm dieselbe Beleuchtung; in den Referenzansichten bleibt der Turm ein Profil.
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
gezeichnete Turmfläche. Der Bildschirmcache selbst wird nicht nachträglich
transparent zusammengesetzt: Große Quellen verwenden die eigene, bereits mit
Deckkraft pro Fläche aufgebaute X-Ray-Rastervariante. Ihre innere Schattierung
wird bei geändertem Ausschnitt skaliert; die Originalkonturen bleiben Vektoren.
Der zusätzliche Bildspeicher beträgt ungefähr `4 × Breite × Höhe × Pixeldichte²`
Bytes (3,2 MB bei 1.000 × 800 Pixeln und einfacher Pixeldichte).
Teure räumliche Originalflächen bzw. große Druckbahndarstellungen werden als
`JobKind.MANUAL_VIEW` durch den bestehenden `BackgroundJobManager` vorbereitet.
Ein kurzer Timer bündelt Kameradrehungen. Solange die Flächen fehlen, zeigt die
Vorschau möglichst bereits die Originalsilhouette, bei unklaren Konturen reduzierte
Kanten desselben Original-STL, andernfalls echte Druckbahnen.
Proxy und vollständige Flächen verwenden dieselbe Originalrotation und denselben
Mittelpunkt; 0° am Slider entspricht der Originalausrichtung. Auch die statischen
Ansichten verwenden diese Rotation. Die Quellkoordinaten bleiben unverändert.
Der Worker zeichnet ausschließlich in eigene `QPicture`-/`QImage`-Objekte; `QPixmap` und
Widgets bleiben im GUI-Thread. Request-ID und vollständige Kamera-/Farbidentität
verwerfen verspätete Ergebnisse. Ein Quellen-/Ansichtswechsel bricht ersetzte Jobs ab. Das
Schließen des Hauptfensters verhindert neue Renderjobs und nutzt den zentralen
kontrollierten Shutdown.
Der Wechsel zu einer direkt gezeichneten Auflösungsstufe beendet ausstehende
Renderaufträge und verwirft ihre verspäteten Ergebnisse. Beim erneuten Wählen
derselben höheren Stufe wird eine fertige Cache-Zeichenfolge wiederverwendet oder
ein neuer Auftrag eingeplant; eine gespeicherte Kennung allein gilt nicht als
laufende Arbeit. Wird während des Abbruchs erneut
gewechselt, startet der neueste Auftrag nach der Freigabe des alten Threads.

### Performance-Regressionsprüfung vom 13.10.2026

Die erste automatische Umsetzung ließ das große Testmodell wegen 102 singulärer
Punktstellen vollständig auf 88.924 Dreiecken und baute auch für 0 % eine
aufwendige Vereinigung aller projizierten Dreiecke. Der gekürzte Körper enthält
15 solche Punktstellen. Die ursprüngliche Einstufung koppelte unnötig die
Reduktionsfreigabe an den schnellen Konturweg. Die Dreieck-/Punkt-Zeichenfolge des
großen Körpers belegte rund 57,7 MB und brauchte etwa 628 ms für eine Wiedergabe.

Lokale Stichprobe mit `700 × 1.000` Bildpixeln, Originalhöhe auf 750 Pixel
eingepasst, Profilansicht ohne kritische Layerfarben, auf demselben Windows-Host:

| Testmodell | Originaldreiecke | Dreiecke bei 1 % | Dreiecke bei 100 % | Aufbau 1 %, kalt | Wiedergabe 1 % | 0 % erster Aufbau / wiederholt |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| `Test-STL (manifold).stl` | 88.924 | 40.714 | 47.024 | 945 ms | 4,2 ms | 17 / 0,9 ms |
| `Test-STL (manifold) gekürzt.stl` | 40.598 | 17.062 | 25.996 | 381 ms | 2,3 ms | 6,7 / 0,6 ms |
| `Test-STL Vase (manifold).stl` | 46.336 | 9.292 | 27.560 | 162 ms | 1,3 ms | 1,7 / 0,4 ms |

Der kalte Aufbau umfasst Reduktion und beide Rasterbilder im Worker; beim
erneuten Wählen einer bereits aufgebauten Stufe wird ihre gesamte Zeichenfolge
wiederverwendet. Diese Werte sind modell-/geräteabhängig und messen nicht die
komplette Anwendung. `test_manual_view_performance.py` sichert alle positiven
Stufen der drei Modelle, den schnellen 0-%-Konturweg, erhaltene Topologie,
begrenzte Zeichenfolgen-/Rastergrößen, erhaltene Öffnungen und Objektabstände in
freier Projektion (auch mit offenen Kanten) und separate X-Ray-Deckkraft ab. Die
zwei zusätzlich lokal bereitgestellten Modelle sind bei fehlenden Dateien optional.

### Historische Performance-Messungen vom 11.10.2026

Die folgenden Stichproben dokumentieren die historische Zeichenroutine vom
11.10.2026, nicht die aktuelle automatische Qualitätswahl und begrenzte
Rasterwiedergabe. Eine lokale Stichprobe verwendete ein selbst erzeugtes Ellipsoid
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
Beide Optimierungen wurden damals in der Anwendung umgesetzt. Der zusätzliche
Bildcache beschleunigte Wiederholungen desselben Bildausschnitts; geänderte
Bildtransformationen wurden weiterhin exakt aus den Flächen gezeichnet. Der Faktor
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
benötigten damals weiterhin eine neue Rasterisierung aller Flächen. Für große
Quellen ersetzt die Umsetzung vom 13.10.2026 diese Arbeit nun durch die
Wiedergabe der begrenzten Worker-Rasterbilder und der Originalkonturen.

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
verwendet; die tatsächliche Zeitquelle (`gcode`, Slicer-Metadaten oder native
Slicer-Zeitmarken) bleibt im technischen Bericht erhalten. Das reguläre Fehlen
nativer Einzel-Layerzeiten, etwa im Bambu-CLI-Pfad, erzeugt keine zusätzliche
Ergebniswarnung. Der gemeinsame Slice liefert die wirklichen gemeinsamen
Druckbahnen; ihre Zeiten werden aus Bewegungen und Beschleunigungen berechnet,
nicht während eines realen Drucks gemessen. Auch native Slicer-Zeiten sind
Schätzungen nach dem jeweiligen Slicer-Modell. Die Anzahl der gemeinsamen
Slices verbessert die Formanpassung, begründet aber keine Genauigkeitsgarantie
für die reale Druckdauer. Konkrete Analyseabweichungen bleiben sichtbar.
Bei einem kürzeren manuellen Turm
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

`manual_settings.json` hat ein eigenes Schema 8 und läuft über
`VersionedJsonStore`. Geometriepunkte, Quellenbindung und Artefakte werden nicht
persistiert. Unbekannte neuere, beschädigte oder extern geänderte Dateien
werden nicht überschrieben. 1→2 übernimmt die alte Zielzeit ausschließlich als
Farbreferenz für Originalschichten und entfernt die Toleranz. Details zur
direkten und mehrstufigen 0→1→2→3→4→5→6→7→8-Migration, zum Layer-Snapping,
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
Abbruch. Zusätzliche 0-%-Prüfungen decken vollständige Konturen, Löcher,
getrennte Inseln, erhaltene Layerfarben und die Wiederverwendung der
vorbereiteten Topologie ab. Die GUI-Tests prüfen zusätzlich Punktmodi, Rechtsklick-Löschen,
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
Der abgeschlossene Vorbereitungskopf behält seine aus den angezeigten Fakten
berechnete Höhe auch beim Ein-/Ausblenden von Grenzmeldungen und Footertexten.
Die GUI-Regression prüft dabei auch Zwischenframes bei mehreren Fensterbreiten.

Eine lokale Messung mit 20.480 Dreiecken, ausgeschalteter kritischer
Layeranzeige und drei Wiederholungen ergab für den Aufbau des Vektorbilds
etwa 0,8 ms bei 0 %, 45 ms bei 5 %, 63 ms bei 10 % und 289 ms bei 100 %.
Die einmalige Konturvorbereitung dauerte etwa 44 ms. Dies beschreibt diesen
synthetischen Messfall und keine allgemeine Bildratenzusage.
Eine Übersicht der entfernten und verbleibenden linken Bedienfelder steht in
[Bedienelemente und Vorschau](manual_controls_analysis.md).

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
