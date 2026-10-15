# Turmgeometrie und Vorschau

## Bedarf und Höhe

`services/tower_need_service.py` bewertet die Druckzeit jedes Original-Layers
gegen die gewünschte Mindest-Layerzeit. Die Fläche allein entscheidet nicht:
Druckgeschwindigkeit, Wände, Füllung und Slicer-Kühlregeln beeinflussen den Bedarf.
Ohne Defizit entsteht kein Turm. Andernfalls reicht er vom Druckbett bis zum
letzten Layer mit Defizit. Auch eine zwischenzeitliche Bedarfspause wird
überbrückt, wenn weiter oben erneut Zusatzzeit benötigt wird.

- Folgen auf den letzten Bedarf mindestens zwei ausreichende Objektlayer, endet der Turm
  genau am letzten benötigten Layer.
- Reicht der Bedarf bis zum letzten oder vorletzten Objektlayer, endet der Turm
  exakt auf der letzten Objektschicht. Variable Layerhöhen werden berücksichtigt.
  Die Anzahl der Turmlayer entspricht dann der Anzahl der Objektlayer.
  Ein einziger ausreichender Schlusslayer löst somit kein vorzeitiges Ende aus.

`TowerNeedAssessment.tower_layer_count` bezeichnet die Zahl der einbezogenen
Original-Layer und dient zum Zuschneiden der Analyse.
`SolidTowerProfile.printable_layer_count` zählt die Turmlayer. Die Vorschau verwendet diese Zahl;
zusätzliche Mesh-Ringe für gekrümmte Flächen sind keine Drucklayer.

## Ablauf eines Generierungslaufs

1. Nach der Quellprüfung liefert der Vorslice die tatsächlichen Layerhöhen,
   Layerzeiten und Druckbahnen des Originalobjekts. Aus dem lokalen Zeitfenster
   wird für jeden benötigten Layer eine erste Außenradius-Schätzung abgeleitet.
   Der frühere Zeit-Sicherheitsfaktor entfällt: Wände, Füllung und weitere
   Slicer-Effekte werden anhand der folgenden Testslices gemessen, statt die
   geschätzte Zusatzzeit pauschal zu vergrößern.
2. Die Bedarfsprüfung bestimmt das Turmende. Erst danach werden Standfuß,
   Mindest- und Höchstdurchmesser, zukünftige Radiusspitzen sowie Aufweitungs-
   und Verjüngungsregeln zu einem durchgehenden Vollkörperprofil verbunden.
   Die Schätzung ist noch kein Nachweis, dass die gewünschte Layerzeit erreicht
   wurde; unerreichbare Radien bleiben als Diagnose sichtbar.
3. Die Platzierung reserviert den **maximal erlaubten** Turmdurchmesser und die
   nötigen Sicherheitsabstände. Der Kandidat wird als geschlossenes STL mit
   automatisch bestimmter Kreissegmentzahl gebaut. Sechs getrennte Turm-Slices
   liefern die günstige Vorstufe; danach messen gemeinsame Objekt-/Turm-Slices
   die tatsächlich erzielten Layerzeiten. Die Einzelheiten der Phasen, des
   Kandidatenvergleichs und der Übernahme stehen in
   [Architektur](architecture.md#getrennte-und-gemeinsame-generierungsphase).
4. Die Kalibrierung passt das Radiusprofil anhand der gemessenen Zusatzzeiten
   an und baut den nächsten Kandidaten erneut nach denselben Geometrie- und
   Platzierungsregeln. Mindestens fünf gemeinsame Slices werden vollständig
   ausgewertet; das Standardbudget beträgt zwölf. Der beste Kandidat wird
   nach der absoluten Abweichung der kürzesten Layerzeit des vollständigen
   gemeinsamen Projekts gewählt. Bei Ausschlüssen und gleicher Gesamtprojekt-
   Abweichung gewinnt eine bessere Angleichung der nicht ausgeschlossenen
   Layer; ansonsten bleibt der frühere Kandidat bestehen.

Ein Turm beginnt stets am Druckbett. Genügen alle Objektlayer bereits der
Zielzeit, erzeugt der reguläre Lauf keine Turmdatei. Nach ausdrücklicher
Bestätigung kann dennoch ein Turm über die gesamte Modellhöhe erzeugt werden.
Endet der Bedarf früher, wird auch
der Turm nach der unten beschriebenen Schlusslayerregel gekürzt; oberhalb
davon entstehen keine unnötigen Turmlayer.

## Durchmesser und Übergänge

`tower/solid_profile.py` baut den geschlossenen Vollkörper.
`tower/diameter_transitions.py` plant seine Übergänge. Derselbe Aufbau wird bei
jeder slicerbasierten Kalibrierungsiteration erneut verwendet.

1. Aus den lokalen Radien wird rückwärts eine Hüllkurve gebildet. Mit
   `g = tan(Aufweitungswinkel)` gilt an benachbarten Höhen
   `Bedarf[i] = max(lokaler Radius[i], Bedarf[i+1] - g * Δz)`.
   Dadurch beginnt eine nötige Verbreiterung rechtzeitig und verläuft linear.
2. Die feste Standfußbreite und die Höhe des ersten Layers bleiben Randbedingungen. Kann von dort ein
   Radius nicht mit dem erlaubten Winkel erreicht werden, bleibt diese Grenze
   als Diagnose erhalten. Die anschließenden Testslices beurteilen die
   tatsächlich erzielte Zusatzzeit durch Wände und Füllung.
3. Verjüngungen verlaufen entlang einer nach innen gebogenen quadratischen
   Kurve: `r(z) = r_min + (r_start - r_min) * (1 - t)²`, mit auf `[0,1]`
   begrenztem `t`. Der Radius fällt anfangs stärker und nähert sich flach dem
   Mindestdurchmesser. Die Kurve wird über den gesamten absteigenden Abschnitt
   geplant und nicht an jedem Layer neu gestartet. Ihre Dauer wird so gewählt,
   dass ein späterer Radiusbedarf erhalten bleibt. Ohne 100-%-Turmfüllung gilt
   zusätzlich die eingestellte maximale Verjüngungsneigung. Bei 100-%-Turmfüllung
   wird dieser Eingabewert ignoriert: Gekrümmte Übergänge ohne Absatz erhalten
   stattdessen eine feste maximale Radiusabnahme von 1 mm pro mm Höhe; der
   Standfußübergang behält seine eigene Höhenregel.

### Automatischer Standfuß

Die automatische Außenbreite folgt `0,21 mm je 1 mm Original-Objekthöhe` und ist auf
25 bis 80 mm begrenzt. Die manuelle Breite darf 20 bis 80 mm betragen.
Die GUI zeigt und prüft diese unterschiedlichen Untergrenzen; ab rund
381 mm Objekthöhe wird der automatische Wert auf 80 mm begrenzt.

Der äußere gerade Fußrand besteht aus genau einem tatsächlichen Layer.
Es gibt keine manuelle Höhenangabe mehr.
Eine anschließende konkave Verjüngung strebt 2,5 % der Originalobjekthöhe an.
Sie reicht mindestens 6 mm oder über 22 weitere Layer, je nachdem, welche
Strecke länger ist. Bei einem zweistufigen Fuß beginnt diese Strecke nach dem
zweiten Layer. Mit 100-%-Turmfüllung liegt das Kurvenende weitere fünf
tatsächliche Layer höher. Ein früheres Turmende begrenzt die Verjüngung.
Unterschiedliche Layerhöhen werden über ihre tatsächlichen Z-Werte
berücksichtigt. Der Zielradius bleibt mindestens so groß wie der eingestellte
Mindestdurchmesser und der vorausschauend benötigte Radius. Ohne Vollfüllung
kann die Winkelgrenze die Verjüngung über dieses Höhenziel hinaus verlängern.
Der Standfußübergang verwendet eine eigene Kontur mit nahezu waagerechtem
Ansatz außen und senkrechtem Anschluss am Turmschaft. Seine normierte Höhe
über dem Fuß beträgt `1 - √(1 - q^p)` für den radialen Fortschritt `q` vom
Fußrand zum Schaft. Bei 100-%-Turmfüllung gilt `p = 3,2`: Der äußere Bereich
bleibt länger flach. Ohne diese Option gilt `p = 2,15`, sodass der Anstieg
früher beginnt. Die ersten 2 % der Übergangshöhe werden dabei linear an die
Soll-Kurve angeschlossen, damit ihr Anfang eine endliche Neigung hat. Liegt
die gesamte Kontur innerhalb des eingestellten Verjüngungswinkels, bleibt sie
erhalten. Andernfalls werden nur zu steile Abschnitte durch eine Linie mit dem
maximal erlaubten Winkel begrenzt. Ohne 100-%-Füllung und bei mehr als 30 mm
Standfußbreite wird die überschüssige Durchmesserbreite halbiert. Die äußere
Hälfte ist einen Layer hoch, die innere zwei Layer. Ein 50-mm-Fuß hat damit
oben auf dem ersten Layer einen Absatz auf 40 mm und oben auf dem zweiten
Layer einen Absatz auf 30 mm. Ab 30 mm beginnt die gezeichnete konkave Kurve.
Sie bleibt erhalten, soweit die Winkelgrenze es zulässt; andernfalls gilt
abschnittsweise der eingestellte Winkel. Die Verjüngung nach dem zweiten
Absatz umfasst mindestens 6 mm oder 22 Layer, sofern der Turm hoch genug ist. Bei
höchstens 30 mm Fußbreite beginnt sie nach dem ersten Layer. Andere
Turmverjüngungen behalten die quadratische Grundkurve.

### Direkte Absätze bei 100 % Turmfüllung

Die zwei beschriebenen Standfußabsätze sind auch ohne Vollfüllung zulässig.
Andere horizontale Absätze nach innen erfordern
`simulate_full_tower_infill=True`. Ein solcher Absatz ist ausschließlich beim
Übergang in einen Objektlayer zulässig,
dessen eigene gemessene Layerzeit das Ziel innerhalb der eingestellten Toleranz
bereits erreicht. Ein starker Rückgang des berechneten Radius allein reicht
dafür nicht aus: Gerade bei einem kurzen Objektlayer muss der Turm weiterhin
Zusatzzeit bereitstellen. Der erste Übergang aus dem Standfuß bleibt konkav.

Das lokale Zeitfenster wird an starken Übergängen über die Zielzeit getrennt
(Zeitverhältnis über 1,5), damit spätere breite Objektflächen die Zeitreferenz
der vorherigen schmalen Schichten nicht verändern. Bei Vollfüllung bleibt ein
unmittelbar vor einem solchen Bedarfseinbruch absteigender Radiusbedarf bis
zum letzten betroffenen Layer auf seinem Ausgangsniveau. Der Absatz beginnt
erst auf dessen Oberseite; später nötige Verbreiterungen bleiben durch die
rückwärts berechnete Hüllkurve abgesichert.

Der Absatz liegt auf der Oberseite des vorherigen Layers. Sein neuer Radius ist
das Maximum aus Mindest-Radius, lokalem Bedarf des nächsten Layers und dessen
rückwärts reserviertem Bedarf abzüglich der möglichen linearen Verbreiterung
über die nächste Layerhöhe. So bleibt der neue Turmabschnitt so dünn wie möglich,
ohne eine spätere Engstelle unerreichbar zu machen.

Das Mesh enthält dort zwei unterschiedlich große Ringe auf exakt derselben Höhe.
Ihre Verbindung bildet eine nach oben gerichtete Ringfläche; der Turm bleibt ein
einzelnes geschlossenes Volumen. Gleiche Höhen sind im Mesh-Validator nur für
explizite Absätze nach innen bei Vollfüllung erlaubt. Ein Absatz nach außen,
absteigende Höhen und Ringe ohne Flächeninhalt bleiben unzulässig.

Das exportierte gemeinsame Projekt übernimmt die 100-%-Füllung objektspezifisch.

## Vorschau und Bedienung

### Bereichseditor für ausgeschlossene Layer

Nach dem abgeschlossenen Pre-Slice öffnet **Erweiterte Turmeinstellungen →
Bereichseditor öffnen** ein separates, am Hauptfenster zentriertes Fenster.
Der Button steht als letztes Element dieses Einstellungsbereichs, mit einem
Info-Button links daneben. Seine Breite folgt dem Text einschließlich der
Innenabstände; seine Höhe entspricht „Standardwerte wiederherstellen“ im Footer.
Rechts daneben steht ausschließlich die Anzahl als „1 Ausschlussbereich“ oder
„x Ausschlussbereiche“. Ohne Bereiche bleibt diese Anzeige verborgen.
Die Stichpunkte des Info-Buttons erklären das Ignorieren von
Layerzeit-Defiziten in gewählten Bereichen und den weiterhin geltenden Mindestdurchmesser.
Links stehen die gespiegelte Mindest-Layerzeit, die beiden Farbgrenzen und
darunter die Layerbereiche;
rechts steht die Seitenansicht des Originalobjekts. Alle Eingaben bearbeiten
zunächst einen Entwurf. Rechts unten übernimmt der grüne Button „Übernehmen“
die Layerbereiche, Mindest-Layerzeit, Farbgrenzen und Anzeigeoptionen gemeinsam. „Abbrechen“,
Esc und das Schließen des Fensters verwerfen den Entwurf vollständig.
Über der Vorschau stehen **Auflösung** links und **Objekt drehen** rechts
nebeneinander. Beide verwenden die Regler- und Greifergestaltung des manuellen
Editors mit der Beschriftung über der Leiste. Nur im Bereichseditor entfällt
der Zusatz „(STL)“ im Auflösungstitel.
Die bisherige Überschrift „Originalobjekt · Seitenansicht · … Layer“ und die
Reset-Buttons der beiden Regler entfallen. Links neben der Auflösung schaltet
„X-Ray (Transparenz)“ die Transparenz des gesamten Originalobjekts wie im manuellen
Modus. Die neutrale Objektfarbe verwendet in beiden Editoren denselben etwas
kräftigeren Blauton; Netzflächen, Silhouette und Legende verwenden die gemeinsame Palette.
Im Bereichseditor ist X-Ray standardmäßig ausgeschaltet.
Ein Doppelklick auf den Greifer stellt die Auflösung auf 75 % beziehungsweise die
Drehung auf 0° zurück. Das gilt auch für dieselben Regler im manuellen Modus;
Doppelklicks auf die freie Leiste lösen diesen Reset nicht aus.
Der Auflösungsregler bietet wie im manuellen Editor:
Standard 75%, neun Stufen von 0% (Silhouette) bis 100%. Er verändert nur die
Darstellung. STL-Flächen und exakte Konturen werden mit der gemeinsamen manuellen
Mesh-Aufbereitung geladen; anspruchsvolle Bilder entstehen in verwalteten,
abbrechbaren Hintergrundjobs. Eine begrenzte Bildablage und normalisierte
Bildkoordinaten vermeiden neue Mesh-Berechnungen beim Zoomen und Verschieben.
Bis ein neues Bild bereitsteht, bleibt die vollständige Layersilhouette sichtbar.
Die Auflösung wird beim Öffnen des Bereichseditors auf 75% gesetzt.
Das Hauptfenster bleibt während der Bearbeitung gesperrt, damit sich der
zugrunde liegende Zustand nicht parallel ändern kann. Die Mindest-Layerzeit
startet mit dem Wert des Hauptfensters und wird beim Übernehmen dort aktualisiert;
die Pfeilbuttons ändern sie in Schritten von 0,1 Sekunden. Das Eingabefeld steht
rechts neben dem Label „Gew. Min-Layerzeit“. Ein gleichhoher Reset-Button
rechts vom Eingabefeld stellt den Standardwert aus den Benutzervorgaben des
Hauptfensters wieder her und ist bei diesem Wert deaktiviert.
„Zeitdefizit-Einfärbung aktivieren“ besitzt rechts eine Checkbox und ist zunächst
deaktiviert. Einschalten zeigt Farbregler, Wertefelder und Farbverlaufslegende;
Ausschalten blendet sie wieder aus.
Die Grenzwerte bleiben für ein späteres Einschalten erhalten; währenddessen zeigt
die Vorschau das Objekt ohne Zeitdefizitfarben in Hellblau, bei jeder Auflösungsstufe.
X-Ray wirkt unabhängig von der Einfärbung und lässt Bereichsmarkierungen unverändert.
Übernommene Anzeigeoptionen bleiben beim erneuten Öffnen in derselben Programmsitzung
erhalten. Sie verändern weder Analyse noch Generierung oder gespeicherte Benutzervorgaben.
Die linke Spalte startet mit der für alle ungekürzten Beschriftungen
und einzeiligen Bedienelemente erforderlichen Breite, einschließlich der
Bereichsliste und ihres Scrollbalkens.
Der Leerlisten-Hinweis fließt nicht in die Breitenberechnung ein und bricht
dynamisch nach verfügbarem Platz um. Die erforderliche Breite ist zugleich
die Mindestbreite der linken Spalte und wird bei geänderten Eingaben oder
Bereichen aktualisiert. Beim Verkleinern des Fensters schrumpft stattdessen
die Vorschau; das Objekt behält dabei seine Proportionen. Ihre Bedienleiste,
Hinweise und Legende umbrechen nach verfügbarem Platz. Die bisherige
500-px-Mindestbreite der Vorschau entfällt. Wertefelder reservieren neben dem angezeigten Wert und
der Einheit Platz für eine weitere Ziffer und die nötigen Text-/Cursorränder.
Die Felder für Layernummern reservieren dagegen von Anfang an Platz für die
maximale Layernummer des aktuellen Objekts. Dadurch ändern Ziffernwechsel beim
Verschieben oder Bearbeiten eines Bereichs weder Feld- noch Spaltenbreite und
verschieben auch die Vorschau nicht. Schrift- und Stiländerungen sowie sonstige
tatsächlich breitere Inhalte können die linke Spalte weiterhin anpassen.
Alle numerischen Eingaben im Bereichseditor verwenden dieselben kompakten
vertikalen Innenabstände: Layerfelder, Mindest-Layerzeit und Farbgrenzen.
Text und native Pfeilbuttons bleiben vollständig sichtbar. Die zugehörigen
Eingabe-Resets passen ihre Höhe an diese Felder an.
Andere Wertefelder wachsen auch während der Eingabe und bei signalblockierten
Änderungen, damit längere Werte nicht abgeschnitten werden.
Das Werkzeug öffnet sich mit der für seine Inhalte nötigen Größe und einer
Vorschaufläche von bevorzugt 650 × 550 px. Reicht der Bildschirmplatz dafür
nicht, wird die Startgröße begrenzt; 500 × 500 px bleiben erhalten, wenn
dafür genügend Platz vorhanden ist. Größere Bildschirme vergrößern das
Werkzeug nicht automatisch. Die manuellen Größenänderungen bleiben möglich.
Unter 500 px Vorschau-Breite schrumpfen die seitlichen Leerabstände stufenlos.
Layernummern, Greifer und Löschbutton behalten den benötigten Platz; die
Überschrift „Layer“ rückt bei gleicher Höhe nach rechts. Die frei werdende
Breite steht dem Objekt und den Bereichsflächen zur Verfügung.
Beide Layergrenzen sowie Bereichsname und Entfernen-Button bleiben jeweils
in einer Zeile; die Mindestbreite berücksichtigt die vollständig sichtbaren Werte.
Während Generierung
und Export ist die Bereichsbearbeitung gesperrt.

Bereiche verwenden die **einschließlichen, ab 1 gezählten Positionen der
tatsächlichen druckbaren Original-Layer**, auch bei variablen Layerhöhen.
Numerische Eingaben und grafische Auswahl bearbeiten denselben Zustand.
Vertikales Ziehen auf einer freien Vorschaufläche legt jederzeit einen Bereich
an; ein umschaltbarer Zeichenmodus ist nicht erforderlich. Die beiden
Greifer ändern die Grenzen; Hover und aktives Ziehen heben den jeweiligen
Greifer durch Farbe und Kontur hervor. Ziehen der markierten Fläche verschiebt den
gesamten Bereich. Entf, das rote X in der Vorschau oder der rote
Entfernen-Button im Listeneintrag löscht den jeweiligen Bereich.
Bereiche und Greifer sind blau; die roten X-Buttons bleiben als Löschaktion
erkennbar. Nach dem Anlegen oder Abbrechen eines Ziehvorgangs können sofort
weitere Bereiche auf freien Flächen angelegt werden. Neue Bereiche sind
alternativ mit den Layereingaben und dem grünen Hinzufügen-Button möglich.
Die Liste und die Namen „Ausschlussbereich 1/2/3 …“ sind absteigend nach Höhe geordnet: Ausschlussbereich 1
ist der oberste Bereich. Die Modell-/Generierungsdaten bleiben aufsteigend
normalisiert. Jede Karte besitzt eine bündige zweigeteilte Kopfzeile ohne
Zwischenraum oder Außenpadding: Der Bereichsbutton nimmt die verbleibende
Breite ein, „Entfernen“ nur seine erforderliche Textbreite mit Buttonpadding.
Die äußeren oberen Ecken sind abgerundet; die gemeinsame Naht ist gerade.
Eine dunklere horizontale Trennlinie unter beiden Kopfbuttons sowie eine
senkrechte Linie zwischen ihnen setzen den Kopf klar ab. Ausgewählte Karten
verwenden im Eingabebereich einen dezenten, zum übrigen Design passenden hellblauen Hintergrund.
Der Bereichsbutton behält auch bei Auswahl den üblichen grauen Farbverlauf.
„Entfernen“ verwendet dieselbe rote Farbgebung wie „Abbrechen“ im Fußbereich.
Der Abstand zu den darunterliegenden Layereingaben bleibt bestehen.
In der Vorschau steht dagegen nur „Bereich x“ ohne Layerangabe links oben in
der jeweiligen Auswahlfläche, auf einem leicht transparenten Texthintergrund.
Beim Auswählen scrollt die Liste den gesamten Bereichseintrag
in den sichtbaren Ausschnitt. Ein unveränderter Klick baut die Liste nicht neu
auf. Notwendige Anpassungen nach Änderungen berücksichtigen die verzögerte
Aktualisierung des Scrollbereichs durch Qt; manuelles Scrollen bleibt möglich.
Die Mindest-Layerzeit übernimmt den gleichen Hover-Hinweis wie das Hauptfenster.
Farbgrenzen und neue Layerbereiche haben eigene Info-Buttons; die Bereichsregeln
stehen dort als Stichpunkte. Die Aktionsbuttons sind so hoch wie der globale
Reset im Hauptfenster. Der Fußbereich wird durch eine graue Linie über die
volle Fensterbreite abgesetzt; die übrigen Trennlinien beachten das Fensterpadding.
Pfeiltasten verschieben die Auswahl um einen Layer, mit Umschalt um zehn.
Die interaktive Vorschau ist durch einen dunkleren Hintergrund und einen
Rahmen vom Fenster abgesetzt. Das Mausrad zoomt mit unveränderten Proportionen
an der Zeigerposition, die mittlere Maustaste verschiebt die Ansicht in beiden
Achsen. Der Drehregler oder horizontales Ziehen mit der rechten Maustaste
dreht das Originalobjekt um seine eigene vertikale Achse. Der Drehregler zeigt
Markierungen alle 45° und rastet beim Ziehen weiterhin bei weniger als 10° Abstand an 90°-Punkten
ein. Andere Winkel bleiben einstellbar; die Tastatur erlaubt exakte Einzelschritte.
Rechts neben den Reglern steht
„Objekt einpassen“. Bei Platzmangel schrumpft zuerst der freie Reglerraum.
Danach heißt der linke Button nur „X-Ray“, anschließend der rechte „Einpassen“.
Sobald die Drehleiste ihre ±90°-Beschriftungen
nicht mehr vollständig anzeigen könnte, stehen die beiden Leisten untereinander.
Die Buttons bilden dann rechts eine gleich breite Spalte: X-Ray neben der Auflösung
oben, Einpassen neben der Drehleiste unten. Beide Leisten stehen links davon
bündig übereinander. Der Einpassen-Button schließt mit der unteren Reglergruppe ab,
hat dieselbe Höhe wie der X-Ray-Button und bleibt unmittelbar über der Vorschau. Er
stellt den vollständigen Höhenbereich wieder her, ohne Bereiche oder Drehung zu ändern.
Er ist nur aktiv, wenn Zoom oder Verschiebung von der eingepassten Ansicht
abweichen und erscheint dann wie im manuellen Modus grün. In der eingepassten
Ansicht bleibt er grau und deaktiviert. Einpassen oder Zurückzoomen zur
Ausgangsansicht deaktiviert ihn wieder.

Überlappende und direkt angrenzende Bereiche bilden eine gemeinsame Union.
Beim Ziehen bleiben die numerischen Bereichszeilen zunächst stabil; erst beim
Loslassen wird vereinigt und die linke Liste aktualisiert. Esc verwirft einen
noch nicht abgeschlossenen Ziehvorgang, ohne das Fenster zu schließen;
außerhalb einer aktiven Vorschauaktion wirkt Esc wie „Abbrechen“.
Während sich Bereiche beim Ziehen
überlappen oder berühren, sind die betroffenen Flächen vorübergehend grün markiert
und ein Hinweis „Bereiche verbinden“ erscheint am Zeiger. Beides verschwindet
sofort, sobald sie wieder getrennt werden, sowie beim Loslassen oder Abbrechen.
Die Vorschau und die Layereingaben
rasten immer auf tatsächlichen Original-Layern ein.

Die Färbung verwendet die gemessene Original-Layerzeit, unabhängig davon,
ob der Layer ausgeschlossen ist: Ausreichende Layer sind grün. Die Einstellungen
unter „Defizit-Einfärbung nach Mindest-Layerzeit“ zeigen einen Farbverlauf-Slider
von 0 bis 2 Sekunden mit zwei Greifern und zwei Eingabefeldern darunter.
Der aktuelle grüne Grenzwert steht links, der aktuelle rote rechts neben dem
Slider; dazwischen nutzt der Slider die gesamte verfügbare Breite.
Linker Greifer und linkes Wertefeld steuern die grüne Grenze, rechter Greifer
und rechtes Wertefeld die rote Grenze. Eingaben und Greiferpositionen bleiben
in beide Richtungen synchron. Pfeiltasten ändern die fokussierte Grenze um
0,1 Sekunden, Bildtasten um 0,5 Sekunden; Pos1/Ende erreichen die Grenzwerte.
Eng benachbarte Greifer liegen auf verschiedenen Seiten des Balkens, damit
beide unabhängig erreichbar bleiben. Im linken Feld stehen „≤“, der Wert und „s“;
im rechten Feld stehen „≥“, der Wert und „s“. Sie steuern den linearen
Übergang von Grün zu Rot; die Standardgrenzen sind 0 und 1 Sekunde.
Links der grünen Grenze bleibt der Slider grün, rechts der roten Grenze rot.
Ein gemeinsamer Reset rechts neben den Eingabefeldern stellt diese beiden
Standardgrenzen wieder her und gehört wie die übrigen Eingaben zum Entwurf.
Er ist so hoch wie die Eingabefelder und vertikal auf deren Zeile zentriert.
Bis zur ersten Grenze bleibt die Farbe grün, ab der zweiten bleibt sie rot.
Die zweite Grenze ist stets größer als die erste; beim Überholen passt sich
die jeweils andere Grenze um 0,1 Sekunden an. Anzeige und Werte verwenden
eine Nachkommastelle. Genauere Eingaben werden dezimal kaufmännisch gerundet
(zum Beispiel 1,25 → 1,3 Sekunden); die Pfeilbuttons ändern die Defizitgrenzen
um 0,1 Sekunden.
Beide Grenzen
und die Legende aktualisieren sich im Entwurf sofort, ohne die Zielzeit oder die
Turmberechnung zu verändern. Übernommene Ansichtseinstellungen bleiben innerhalb
der laufenden Programmsitzung beim erneuten Öffnen und bei Quellenwechseln
erhalten. Bei STL-Auflösungen über 0 % nehmen die schattierten Objektflächen,
Netzkanten und Knoten selbst die höhenabhängigen Layerfarben an. Deckende
Layerlinien über dem Netz entfallen; Details, Öffnungen und getrennte Inseln
bleiben sichtbar. Die Profilansichten verwenden dafür ein höhenbezogenes
Flächenmaterial, auch bei der im Hintergrund gerasterten Detailvorschau.
Die Topologie-Netzlinien des Originalobjekts verwenden in beiden Editoren
kosmetische 0,5-Pixel-Stifte. Die Originalkontur bleibt davon unberührt.
Bereichseditor und manuelle Vorschau verwenden dieselbe Objektpalette mit dezenten
Netzkanten und Knoten nahe an der jeweiligen Flächenfarbe. Objektfarbe und
Netzkontrast sind zentral festgelegt; Kontur und Layerfarben behalten ihre Darstellung.
Ausschlussbereiche besitzen eine sehr leichte rote diagonale Kreuzschraffur
im 12-Pixel-Raster sowie eine dezente transparente Auswahlfläche; dunkelblaue Rahmen und Greifer kennzeichnen
weiterhin Auswahl und Zusammenführung. Die Schraffur gilt auch für den gerade
gezogenen Entwurf, wird immer nach dem Objektbild darüber gezeichnet und
verändert weder Layerzeiten noch die Defizitfarben.
Die Legende steht links unten im Vorschaubereich.
Sie zeigt den Farbbalken und rechts daneben „Layerzeit-Defizit“ ohne Zahlen
unter dem Balken; die Grenzwerte stehen bei den Einstellungen.
Der Ausschluss-Hinweis verwendet die neutrale blaue Objektfarbe als Farbmuster,
den fetten Titel „Ausschlussbereiche:“ und darunter drei bündige Stichpunkte:
keine zusätzliche Layerzeit, Schrumpfen bis zum Mindestdurchmesser, sofern möglich, sowie die
Ausnahmen für Standfuß und nötige Aufweitungen zu nicht ausgeschlossenen Bereichen.
Bedienhinweise und Legendentexte umbrechen nach verfügbarer Breite; bei
Platzmangel werden sie über Scrollbars vollständig erreichbar gehalten.
Die Kontur
verwendet vollständige Schnitte der unveränderten Original-STL in der Mitte
jedes tatsächlichen Layers. Nur die gerade vom Schnitt betroffenen Dreiecke
werden verarbeitet; die Schnittsegmente liegen unveränderlich im Sitzungsspeicher
und erlauben die Rotation ohne erneutes Lesen oder Sampling. Geometrieinseln
und echte Zwischenräume bleiben erhalten. Die Aufbereitung ist auf zwei
Millionen Schnittsegmente begrenzt (höchstens etwa 64 MB reine XY-Schnittdaten);
bei Überschreitung erscheint eine verständliche Meldung statt unbeschränkter
Speicherbelegung. Der Bestand wird beim Verwerfen des
Pre-Slices zurückgesetzt. Ohne STL-Schnitte (etwa bei isolierten GUI-Fixtures)
gibt es einen angenäherten Fallback auf die äußere Hülle der Druckbahnen.
Die ausgedünnten 3D-Druckbahnen allein dürfen keine künstlichen Löcher in der
STL-Silhouette verursachen. Gruppierte Farbrechtecke verwenden Winding-Füllung,
damit überlappende Subpixel-Layer sich beim Herauszoomen nicht gegenseitig
ausstanzen. Layerzeiten, Auswahlgrenzen und Turmberechnung verwenden immer
sämtliche tatsächlichen Pre-Slice-Layer.

`GenerationSettings.excluded_layer_ranges` enthält diese objektgebundenen
Sitzungsdaten. Sie werden **nicht in globale Benutzereinstellungen oder
Standardwerte gespeichert**. Übernommene Bereiche bleiben beim Schließen und
erneuten Öffnen des Werkzeugs erhalten; eine neue Quelle, geänderte Slicerprofile oder ein neuer
Pre-Slice setzen sie zurück. Der globale Reset entfernt sie ebenfalls.
Das globale Einstellungsschema bleibt unverändert. Vorschau-Signaturen und
Exportberichte enthalten die Bereiche, damit Ergebnisse eindeutig bleiben.

Die Bedarfsprüfung setzt ihr lokales Zeitdefizit auf null; ausgeschlossene
Schlusslayer verlängern den Turm nicht. Ohne verbleibenden Bedarf entsteht
kein Turm. Radius-Schätzung und jede Kalibrierungsrunde ignorieren ihren
lokalen Zeitbedarf. Konvergenz, vorzeitige Zielerreichung und lokale
Zeitkorrekturen berücksichtigen nur die nicht ausgeschlossenen Layer.
Die angezeigte beste Layerzeit und ihre Abweichung stammen dagegen aus dem
**vollständigen gemeinsamen G-Code des ausgewählten Kandidaten**, einschließlich
ausgeschlossener Layer und Objektlayer oberhalb des Turmendes. Derselbe gespeicherte
Messwert wird während der Generierung, nach Übernahme sowie für Vorschau und
Export verwendet. Die Vorschau zeigt ebenfalls die Form dieses besten Kandidaten.
Bei gleicher Gesamtprojekt-Abweichung kann ein Kandidat mit besser angeglichenen
nicht ausgeschlossenen Layern übernehmen; ausgeschlossene Layer erhalten dadurch
keine eigene Zeitvorgabe. Die unveränderten Originalzeiten bleiben für Analyse
und Färbung verfügbar.

Für Anycubic Slicer Next werden in den eigenen temporären Profilkopien reine
Kommentar-Marker an den Layergrenzen ergänzt. Der native Slicer-Postprozessor
ersetzt seine Inline-Zeitplatzhalter durch kumulierte Normalmodus-Zeiten mit
Millisekundenauflösung. Aus aufeinanderfolgenden Zeitständen entstehen die
Layerzeiten für Bedarf, Angleichung, Kandidatenvergleich und Anzeige. Die
Druckbefehle bleiben unverändert. Unvollständige, doppelte oder nicht zu den
G-Code-Layern passende Zeitstände dürfen nicht als vollständiges Slicer-Ergebnis
verwendet werden. Bereits vorhandene G-Codes ohne diese Marker und die übrigen
Slicer verwenden weiterhin die bisherige Bewegungsanalyse; vorhandene native
Layerzeit-Metadaten haben bei der Slice-Bewertung Vorrang. Ein erneuter Slice
des 3MF muss denselben Slicerstand, dieselben Druckprofile und
Objektüberschreibungen verwenden. Slicereigene Originalprofile bleiben lesend.

Die rückwärts berechnete Hüllkurve sichert weiterhin spätere Bedarfsspitzen.
Ohne Vollfüllung verjüngt sich der Turm innerhalb eines Bereichs unter
Einhaltung des Verjüngungswinkels. Der Standfuß und dessen eigene Kurve bleiben
bei beiden Füllungsvarianten erhalten: Ausgeschlossene Standfuß-Layer wirken
wie Layer ohne Defizit. Automatische und manuelle Standfußbreiten sowie ihre
Validierung gelten auch bei einem ausgeschlossenen ersten Layer unverändert.
Layer auf dem Mindestdurchmesser verlängern eine Verjüngung nicht; nach deren
Abschluss bleibt der Stamm minimal, bis späterer Bedarf eine Aufweitung verlangt.
Mit 100-%-Füllung darf er oberhalb des Standfußübergangs direkt am
Bereichsanfang einen geschlossenen Absatz zum kleinsten noch nötigen Radius
bilden. Innerhalb des Standfußübergangs darf ein Ausschluss weder dessen Kurve
abbrechen noch dessen Breite auf den Mindestdurchmesser reduzieren.
Eine Aufweitung innerhalb der Bereiche sichert ausschließlich späteren,
nicht ausgeschlossenen Bedarf.

`test_layer_range_tool.py` prüft Bereichsvereinigung, Original-Indexzuordnung,
variable Höhen, Turmende, Standfußschutz, spätere Spitzen, Winkel, geschlossene
Absatz-Meshes, Kalibrierung, Quellunveränderlichkeit, Vorschauidentität sowie
grafische und numerische Bearbeitung, Freigabe beim Loslassen, Drehung,
Übernehmen/Verwerfen aller Einstellungen, Zeitschritte und Rücksetzung im Hauptfenster.
Zusätzliche GUI-Prüfungen sichern die Farbgrenzen, ihre Reihenfolge und
Synchronisation mit der Legende, die vorübergehende Überlagerungsanzeige sowie
proportionstreuen Zoom mit verankerter Zeigerposition und Verschieben der Ansicht.
Zusätzliche Fälle prüfen automatisches Zeichnen auf freien Flächen, absteigende
Nummerierung, stabile vollständig sichtbare Auswahlzeilen nach echten Mausklicks
und Listenänderungen, 90°-Einrasten, Drehungsreset, STL-Inseln und Quellschutz.
Layoutprüfungen verwenden die tatsächlichen Styles für kompakte Eingabefelder,
die mitwachsende Mindestbreite links, proportionale Vorschauverkleinerung,
Umbrüche in der rechten Spalte, gestufte Einpassen-Beschriftungen
und vollständig scrollbare Hinweistexte einschließlich großer Defizitwerte.
Weitere Tests prüfen das Ziehen beider Farbgreifer, die Grenze von 2 Sekunden,
bidirektionale Eingabesynchronisation, Tastaturbedienung und den Reset auf 0/1 Sekunden.
Der Standfußfall mit ausgeschlossenen Layern 1–951 wird bei 990 Layern und
178,22 mm Höhe für automatische/manuelle Standfüße und beide Füllungsvarianten
gegen Mindeststamm, spätere Bedarfsspitzen und geschlossene Meshes geprüft.
„Test-STL (manifold).stl“ wird mit 990 Layern und 178,22 mm Vorschauhöhe
auf vollständige Geometrie bei mehreren Drehwinkeln geprüft; ein dichter
1000-Layer-Fall verhindert ausgeblendete Bildzeilen durch überlappende Farbflächen.

### 3D-Vorschau und übrige Turmeinstellungen

Die Platzierung reserviert vor dem ersten gemeinsamen Slice den angegebenen
maximalen Turmdurchmesser einschließlich eines nötigen Standfußes und eines
aktiven Brims. Aus den über alle Höhen ermittelten Außenmaßen des Originalobjekts
wird die größte freie Distanz zu einer Druckbettseite gewählt; der Turmmittelpunkt
liegt mittig in diesem Zwischenraum. Blockieren eine Ausschlussfläche oder die
Mindestabstände diese Seite, wird die nächste freie Seite geprüft. Zu Objekt und
Druckbettrand bleiben jeweils mindestens 5 mm frei. Der Turm darf seinen
maximalen Außendurchmesser auch bei späterer Kalibrierung nicht überschreiten.

Die Kreissegmentzahl wird pro Kandidat aus dessen größtem aktuellen Durchmesser
berechnet: `max(30, ceil(1,0 × Durchmesser in mm))`. Damit haben
kleine Türme mindestens 30 Segmente; bei größeren Durchmessern gilt
ein Segment pro Millimeter ohne obere Begrenzung.
Alle Ringe eines STL verwenden dieselbe Segmentzahl,
damit das Netz geschlossen bleibt. Getrennte und gemeinsame Slices verwenden
dieselbe Regel; eine veränderte Kandidatenbreite kann die Auflösung im nächsten
Kalibrierungsdurchlauf ändern.
Die 3D-Vorschau zeigt die für den dargestellten Kandidaten verwendete Zahl als
„Turm-Kreissegmente“ oberhalb der Höhenangabe an.

Das Originalobjekt erscheint nach dem Pre-Slice zunächst in der 3/4-Ansicht.
Der erste abgeschlossene gemeinsame Slice stellt auf die Seitenansicht um;
weitere Zwischenstände und der Abschluss behalten diese Kamera. Nach dem
Export oder einem Klick auf „Fortsetzen“ bleibt eine manuell gewählte Ansicht
erhalten. Erst der erste abgeschlossene Slice der nächsten Generierungsphase
stellt wieder auf die Seitenansicht um.
Beim Wiederherstellen der Standardwerte gilt wieder die 3/4-Ansicht.
Der Button „Seitenansicht“ wählt eine möglichst trennende Druckbettachse und
zeigt das Originalobjekt links sowie den Turm rechts. Nur wenn sich beide
Achsenprojektionen überlappen, nutzt er einen schrägen Blickwinkel. Die
Vorderansicht liegt zur Seitenansicht um 90° gedreht.
Höhen und Layeranzahlen werden getrennt für Originalobjekt und Turm angezeigt.
Die Navigationsanzeige und ihr Symbol schalten denselben Navigationszustand um.
Beide liegen als Overlay links etwa eine Textzeile unter der Layer-Information.
Die tiefer reichende Druckplatteninformation rechts bestimmt ihre Position nicht.
Wird die Canvas nach dem Einblenden neu positioniert,
folgen ihr die Navigationselemente. Die vier Ansichtsbuttons über der Canvas
sind 32 px hoch.

Nach Abschluss der Datei-/Slicer-Vorbereitung erscheint im Inhaltsbereich die
Methodenauswahl mit der zentrierten Überschrift „Wie soll der Kühlturm erstellt werden?“. Die Karten
„Automatisch“ und „Manuell“ stehen bei ausreichend Platz nebeneinander,
ansonsten untereinander. Die gemeinsame Kartenbreite ist auf 980 px begrenzt;
die Gruppe steht zentriert. Beim Verkleinern schrumpfen zunächst die seitlichen
Freiräume bis zum regulären Seitenrand, bevor die Karten unter 800 px
verfügbarer Breite umbrechen. Die Kartentitel sind ebenfalls zentriert.
„Automatisch“ öffnet den bestehenden Arbeitsbereich;
„Manuell“ öffnet den eingebetteten [Profil- und Béziereditor](manual_editor.md).
Nach der ersten Wahl über die Karten sind beide Methoden im Header direkt erreichbar.
Die grauen Bereichsbezeichnungen oberhalb der jeweiligen Inhalte entfallen.
Nur im einspaltigen manuellen Modus bleibt der rote Breitenhinweis fensterzentriert.
Der Vorbereitungsbutton öffnet die gemeinsame Vorbereitung im Inhaltsbereich.
Er beginnt direkt am oberen linken Fensterrand und zeigt die fünf Angaben
untereinander ohne Haken. Oben stehen 7 Pixel, unten 8 Pixel und seitlich jeweils
7 Pixel Innenabstand zur Verfügung; die gemeinsame Headerhöhe wächst mit dem Inhalt. Alle Ecken sind rechtwinklig;
kleinere Schrift und der vorhandene grüne Bestätigungsverlauf halten ihn kompakt.
Die Angaben erscheinen erst
gemeinsam nach erfolgreichem Abschluss; unbestätigte Teilangaben bleiben verborgen.
Der Hover-Hinweis lautet „Datei- und Slicereinstellungen ändern“.
Die Methodenwahl beginnt links neben dem Menü direkt am oberen Fensterrand.
In der Kartenansicht bleibt dieser Bereich ausgeblendet. Nach der Wahl steht
dort „Erstellungsmethode“ als zentrierte Textüberschrift.
Ihre Fläche wächst in der Höhe, sodass die darunterliegenden Methodenbuttons
mit der Infofläche und der Header-Trennlinie bündig abschließen.
Direkt darunter schließen die violette Aktion „Automatisch“ und die blaue Aktion
„Manuell“ nebeneinander ohne Abstand an. Alle Ecken sind rechtwinklig;
zusammen bilden sie ein Element. Die aktive Methode wirkt durch einen
hellen umgekehrten Verlauf und dünne Schatten-/Lichtkanten eingedrückt. Die Schrift
bleibt normal. Die Aktionen wechseln
direkt zum Arbeitsbereich und ersetzen auch „Zurück“ beim Öffnen der Vorbereitung.
Nach dem Klick bleibt kein Fokusrahmen stehen. Beim Hover der Methodenkarten
wird auch ihre enthaltene Aktionsfläche passend eingefärbt.
Titel und Untertitel stehen horizontal mittig im Fenster. Beim Verkleinern
folgen sie der Fenstermitte, bis der Abstand zur linken Infofläche 12 Pixel
beträgt. An dieser Stelle bleiben sie, bis rechts zur Methodenwahl ebenfalls
nur 12 Pixel frei sind. Bei weiterer Verkleinerung verschwindet die Titelgruppe;
der Platz bleibt frei. Beim Vergrößern erscheint die Titelgruppe wieder.
Während der unbestätigten Vorbereitung steht die Titelgruppe vertikal mittig
zwischen Fensteroberkante und Vorbereitungskarte. Nach Abschluss wird sie
mittig zur höchsten Header-Fläche ausgerichtet. Der Abstand
zu Methodenwahl und Generierungsseiten beträgt 22 Pixel, wie deren seitliche
Content-Ränder. Die Vorbereitungsfläche schließt dagegen ohne Abstand an den
Header an, reicht horizontal bis zum Fensterrand bzw. Scrollbalken und besitzt
keine äußeren Rahmenlinien oder abgerundeten Ecken. Ihr Header zeigt nur die
zentrierte Überschrift. Details zur gemeinsamen Header-/Overlay-Anordnung
stehen in [architecture.md](architecture.md#auswahl-der-generierungsmethode-und-sitzungszustände).
Bei sichtbarer Methodenwahl sind Menü und Version jeweils im verbleibenden
rechten Bereich horizontal zentriert. Ihre gemeinsame vertikale Mitte liegt
zwischen Fensteroberkante und der Header-Trennlinie. Die Version bleibt
unter dem Menü. Ohne sichtbare Methodenwahl bleibt die Position der Version
erhalten; der Menübutton steht horizontal zentriert darüber.
Die dünne horizontale Trennlinie und ihr über die nächste Seite reichender
Schatten sind bereits beim Programmstart sichtbar. Die bisherige vertikale
Zentrierung der Titelgruppe bei unbestätigter Vorbereitung bleibt erhalten.
Nach erfolgreicher Vorbereitung liegt die Linie auf Höhe der grünen Unterkante
und ersetzt dort die untere Rahmenkante der Infofläche.
Angaben und Buttons bleiben im Header. Der Abschluss wechselt mit Aus- und Einblenden zur
Methodenauswahl. Der Header bleibt sichtbar; der Footer ist in der geöffneten
Vorbereitung ausgeblendet und erscheint mit der Methodenauswahl wieder.
Einstellungen, Vorschau,
Generierungsergebnis und Exportstatus bleiben innerhalb der Sitzung erhalten.
Während einer laufenden Generierung oder eines Exports ist der Wechsel gesperrt.

Die automatische Segmentanzeige verwendet
`max(30, ceil(größter tatsächlicher Außendurchmesser in mm))`. Der manuelle
Editor leitet seinen ersten Segmentstandard einmalig aus seiner eigenen
initialen Geometrie einschließlich Fuß ab und verwaltet danach eine eigene
editierbare Kreissegmentzahl. Beide Auflösungen bleiben unabhängig.

Das manuelle Radiusprofil besteht aus kubischen Bézierkurven mit analytisch
geprüften Durchmesser- und Steigungsextrema. Die Winkel verwenden `atan(dr/dz)`
zur Vertikalen; Aufweitung und Verjüngung sind getrennt aktivierbar. Die
STL-Tessellierung begrenzt den vertikalen radialen Kurvenfehler auf 0,02 mm;
Kreispolygonfehler und Drucklayer sind separate Größen. Das Mesh beginnt bei
Z=0 und besitzt geschlossenen Boden und Deckel. Fachliche Invarianten,
Fußabhängigkeiten und Sicherheitsgrenzen stehen zentral in
[Manueller Editor – Geometrie](manual_editor.md#geometriemodell-und-invarianten).

Im automatischen Arbeitsbereich enthält das gemeinsame Dropdown
„Turmeinstellungen“ Kühlzeit, Abmessungen, Standfuß, Überhänge und die
Simulation deaktivierter Turmstützen. Das lokale Zeitfenster befindet sich
in „Allgemeine Einstellungen“ und besitzt dort einen eigenen Reset.
Der aktuelle Standard des lokalen Zeitfensters ist 51 Layer; explizit gespeicherte
Benutzerwerte bleiben erhalten. Das Speicherformat und die Bedeutung des Feldes
ändern sich dadurch nicht. Der globale Reset lässt den Wert unverändert.

Die Aufweitung wird zur Vertikalen gemessen. Bei Orca-, Bambu- und
Anycubic-Profilen ist `support_threshold_angle` dagegen zur Horizontalen
definiert. Nach einem erfolgreichen Pre-Slice wird bei aktiven Stützen ab
`90° − support_threshold_angle` am Aufweitungswinkel gewarnt. Der Hinweis
entfällt bei deaktivierten Stützen oder aktivierter Simulation ohne Stützen.
Die Simulation steht direkt unter „100% Turmfüllung simulieren“ und schreibt
ausschließlich temporäre Profilkopien und objektspezifische Einstellungen
im programmeigenen gemeinsamen 3MF bzw. in
der temporären Bambu-Assembly. Die Stützeneinstellung des Originalobjekts
bleibt unverändert.

Nach dem Pre-Slice zeigt die 3D-Ansicht zunächst die Druckbahnen des
Originalobjekts; ein kurzer Hinweis oberhalb der Trennlinie erklärt den noch
fehlenden Kühlturm. Nach einem Generierungsabbruch kehrt sie dorthin zurück;
alle vier Ansichtsbuttons funktionieren auch ohne Turmgeometrie. Änderungen
an Turmeinstellungen kennzeichnen diese reine Originalobjektansicht nicht als
veraltet; die Veraltet-Anzeige gilt erst für Szenen mit Kühlturm.

### Objektspezifische Stützen für das Original-STL

Ist die globale Stützeneinstellung im bestätigten Prozessprofil eindeutig
deaktiviert, wird in beiden Methoden **Stützen für STL-Objekt simulieren**
angeboten. Die Option startet deaktiviert und wird nicht als globale
Benutzervoreinstellung gespeichert. Im automatischen Modus steht sie unter
„Deaktivierte Turmstützen simulieren“, manuell unter „Turm und Standfuß“.
Der gemeinsame objektspezifische 3MF-Pfad ist für Orca Slicer, Bambu Studio und
Anycubic Slicer Next verfügbar. Bei anderen Adaptern bleibt die angebotene Option
mit einer Erklärung deaktiviert; ein nicht unterstützter API-Auftrag wird
abgewiesen, statt die Simulation stillschweigend zu ignorieren.

`GenerationSettings.simulate_source_supports` wird nur in objektbezogene
Signaturen aufgenommen. Gemeinsame Slices und der exportierte native 3MF-Container
setzen `enable_support=1` ausschließlich am Originalobjekt. Die globale
Stützeneinstellung und sämtliche weiteren Stützenparameter bleiben erhalten;
Turmfüllung und Turmstützen werden unabhängig am Turm gesetzt. Bambu erhält
dieselbe Einstellung zusätzlich im objektspezifischen `print_params` der
temporären Assembly. Auch der verzögert erstellte automatische Endexport trägt
diesen Wert weiter. Native Projektvalidierung prüft die Übernahme am richtigen
Objekt. Slicer-Originale werden ausschließlich gelesen.
Wurde zuvor bereits der Pre-Slice nach einem Fehler mit simulierten Stützen
wiederholt, ersetzt die aktive neue Option dessen globale Weitergabe im
Generierungsauftrag durch die objektspezifische Aktivierung. Damit schaltet sie
keine zusätzlichen Turmstützen ein; das vorbereitete Original bleibt erhalten.

Die vorbereitete Originalanalyse und die manuelle Vorschau bleiben unverändert.
Bei aktiver Objektstützensimulation liest die automatische Vorschau die
Originalbahnen einschließlich der Stützen aus dem tatsächlichen gemeinsamen
G-Code des besten Kandidaten. Benannte Objektblöcke trennen Original und Turm;
Bambus numerische Objektkennungen werden anhand ihrer exakten Druckbahngrenzen
und der bestätigten Turmposition eindeutig zugeordnet. Ein mehrdeutiger
G-Code wird nicht als korrekte Stützenvorschau ausgegeben. Die Aufbereitung
verwendet begrenzte Segmentstichproben und erfolgt im vorhandenen Worker nur
einmal je geändertem besten Kandidaten; finale Ansicht und Zwischenvorschau
verwenden dieselben Daten. Der vorbereitete Originalcache bleibt erhalten.
Die gemeinsame Zeitbewertung berücksichtigt dadurch auch die tatsächlich
erzeugten Stützbahnen. Zur Berechnung und Aussagekraft dieser Zeiten siehe
[gemeinsamer Prüfslice](manual_editor.md#ein-unveränderter-prüfslice).

Beim Aktualisieren eines vorzeitig übernommenen Ergebnisses werden Fortsetzung
und Export gesperrt und die Hauptaktion heißt „Kühlturm aktualisieren“. Sie
verwirft den alten Stand und beginnt mit den aktuellen Einstellungen neu.
Werden die Einstellungen exakt wiederhergestellt, gelten wieder die bisherigen
Aktionen. Sobald ein neuer gemeinsamer Slice sichtbar ist, wird dessen Vorschau
als aktuell angezeigt; Export bleibt bis zur Ergebnisübernahme gesperrt.
Außerhalb einer Generierung erscheint das Turm-Fortschrittsbild vollständig,
während sein letzter interner Fortschrittswert für die Fortsetzung erhalten bleibt.

## Prüfungen

`test_october_editor_changes.py` deckt die unabhängige Wiederherstellung der
Profilrollen, Historienschritte und Wiederholungszweige, schmale Vorschauleisten,
den sicheren Neustart eines übernommenen Ergebnisses, die aktuelle gemeinsame
Vorschau sowie objektspezifische Stützen und Turmfüllung einschließlich des
verzögerten automatischen Endexports ab. `test_real_object_simulations.py`
prüft bei `COOLING_TOWER_RUN_REAL_SLICER_TESTS=1` beide installierten nativen
Adapter in getrennten Prozessen, einschließlich G-Code-Nachweis der Turmfüllung,
3MF-Metadaten, getrennten Original-/Stützbahnen für die Vorschau und unveränderten
Quellen/Profilen. `test_profile_and_preview_refinements.py` prüft zusätzlich
Nachbar-Snapping einschließlich Mausziehen und Undo, responsive Profilhinweise,
die tatsächlichen Stützbahnen in Zwischen- und Endansicht sowie die sichere
Übergabe nach Entfernen des temporären Slice-Verzeichnisses. Die technische
Zeitquelle bleibt trotz entfallener pauschaler Ergebniswarnung erhalten.

Die lokale native Abnahme am **15.10.2026** bestand für Bambu Studio und Anycubic
Slicer Next mit 990 Original-Layern und 60.000 Vorschausegmenten. Artefakte und
Messdaten liegen unter `.tmp/manual_acceptance_bambu_simulations/` und
`.tmp/manual_acceptance_anycubic_simulations/`. Das belegt diese beiden lokalen
Slicerversionen und Profile; es ist keine Abnahme anderer Adapter oder Profile.

`test_generation_refinements.py` prüft vorzeitiges Ende, variable Layerhöhen,
Begrenzung auf Objekthöhe, zukünftige Bedarfsspitzen, konkave Kurven, Winkelgrenzen sowie
geschlossene, zusammenhängende und nach außen orientierte Absatz-Meshes.
`test_requested_refinements_ui.py` prüft Navigation, Ansichtsrücksetzung,
Layeranzeige, Abbruchfarben, Pre-Slice-Voraussetzung und Standardwerte.

Ein realer Kontrolllauf mit Anycubic Slicer Next und der spitzen
`Test-STL (manifold).stl` wurde nach Zustimmung mit simulierten Stützen
erfolgreich geslict und als gemeinsames 3MF erzeugt: Objekt und Turm hatten
jeweils 990 Layer bei 178,22 mm Höhe, die 3MF enthielt aktivierte Stützen.
Die Original-STL und die verwendeten Originalprofile blieben bytegleich.
Der auf drei Kalibrierungsrunden begrenzte Kontrolllauf prüfte den Datenfluss
und die Geometrie; er belegte keine vollständige Konvergenz zur Zielzeit.

Der anschließende Kontrolllauf der automatischen Fußregel mit
`Test-STL apprupte Flächenänderung (manifold).stl` erzeugte ein gemeinsames 3MF
mit 889 Objektlayern (160,04 mm) und 683 Turmlayern (122,96 mm, vorzeitiges Ende).
Die Fußhöhe betrug nach der damaligen Zwei-Layer-Regel exakt 0,38 mm.
Auch dieser auf drei Durchläufe begrenzte Test prüfte Geometrie und Datenfluss,
nicht vollständige Konvergenz. Originaldateien blieben bytegleich.

`test_automatic_foot.py` prüft die 25-Layer-Priorität, variable Layerhöhen,
kurze Türme, die füllungsabhängige Winkelgrenze, den geschlossenen Absatz sowie
die getrennte Zeitreferenz und den Schutz vor Verjüngung vor einem Bedarfseinbruch.
