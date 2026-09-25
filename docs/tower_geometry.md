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
   nach der absoluten Abweichung der kürzesten relevanten gemeinsamen
   Layerzeit gewählt. Ein späterer gleich guter Kandidat verdrängt ihn nicht.

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
2. Die feste Standfußbreite und die Höhe der ersten zwei Layer bleiben Randbedingungen. Kann von dort ein
   Radius nicht mit dem erlaubten Winkel erreicht werden, bleibt diese Grenze
   als Diagnose erhalten. Die anschließenden Testslices beurteilen die
   tatsächlich erzielte Zusatzzeit durch Wände und Füllung.
3. Verjüngungen verlaufen entlang einer nach innen gebogenen quadratischen
   Kurve: `r(z) = r_min + (r_start - r_min) * (1 - t)²`, mit auf `[0,1]`
   begrenztem `t`. Der Radius fällt anfangs stärker und nähert sich flach dem
   Mindestdurchmesser. Die Kurve wird über den gesamten absteigenden Abschnitt
   geplant und nicht an jedem Layer neu gestartet. Ihre Dauer wird so gewählt,
   dass ein späterer Radiusbedarf erhalten bleibt. Ohne 100-%-Turmfüllung gilt
   zusätzlich die maximale Verjüngungsneigung. Bei 100-%-Turmfüllung wird diese
   Winkelgrenze vollständig ignoriert, auch für gekrümmte Übergänge und den Fuß.

### Automatischer Standfuß

Der zylindrische Fuß besteht aus genau zwei tatsächlichen Layern (bei kürzeren
Türmen entsprechend weniger). Es gibt keine manuelle Höhenangabe mehr.
Eine anschließende konkave Verjüngung strebt 2,5 % der Originalobjekthöhe an,
bevorzugt höchstens 5 mm, mindestens aber die Höhe von 20 weiteren Layern.
Die 20 Layer haben Vorrang vor den 5 mm; ein früheres Turmende begrenzt die
Verjüngung. Unterschiedliche Layerhöhen werden über ihre tatsächlichen Z-Werte
berücksichtigt. Der Zielradius bleibt mindestens so groß wie der eingestellte
Mindestdurchmesser und der vorausschauend benötigte Radius. Ohne Vollfüllung
kann die Winkelgrenze die Verjüngung über dieses Höhenziel hinaus verlängern.

### Direkte Absätze bei 100 % Turmfüllung

Nur `simulate_full_tower_infill=True` erlaubt einen horizontalen Absatz nach
innen. Als abrupter Bedarfseinbruch gilt eine Radiusabnahme größer als die
Layerhöhe (feste Erkennungsschwelle, unabhängig vom ignorierten Verjüngungswinkel)
oder ein starker Zeitsprung in einen selbst ausreichenden Objektlayer.
Der erste Übergang aus dem Standfuß bleibt konkav.

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

Die Platzierung reserviert vor dem ersten gemeinsamen Slice den angegebenen
maximalen Turmdurchmesser einschließlich eines nötigen Standfußes und eines
aktiven Brims. Aus den über alle Höhen ermittelten Außenmaßen des Originalobjekts
wird die größte freie Distanz zu einer Druckbettseite gewählt; der Turmmittelpunkt
liegt mittig in diesem Zwischenraum. Blockieren eine Ausschlussfläche oder die
Mindestabstände diese Seite, wird die nächste freie Seite geprüft. Zu Objekt und
Druckbettrand bleiben jeweils mindestens 5 mm frei. Der Turm darf seinen
maximalen Außendurchmesser auch bei späterer Kalibrierung nicht überschreiten.

Die Kreissegmentzahl wird pro Kandidat aus dessen größtem aktuellen Durchmesser
berechnet: `ceil(0,9 × Durchmesser in mm)`, auf 16 bis 128 begrenzt.
Alle Ringe eines STL verwenden dieselbe Segmentzahl,
damit das Netz geschlossen bleibt. Getrennte und gemeinsame Slices verwenden
dieselbe Regel; eine veränderte Kandidatenbreite kann die Auflösung im nächsten
Kalibrierungsdurchlauf ändern.
Die 3D-Vorschau zeigt die für den dargestellten Kandidaten verwendete Zahl als
„Turm-Kreissegmente“ oberhalb der Höhenangabe an.

Nach jeder abgeschlossenen Generierung wird die Seitenansicht neu eingepasst.
Sie richtet sich nach der Platzierung von Objekt und Turm, sodass beide möglichst
nebeneinander sichtbar sind. Die Vorderansicht liegt dazu um 90° gedreht.
Höhen und Layeranzahlen werden getrennt für Originalobjekt und Turm angezeigt.
Die Navigationsanzeige und ihr Symbol schalten denselben Navigationszustand um.
Beide liegen als Overlay eine Zeilenhöhe oberhalb der Canvas-Standardposition;
die Bedienelemente bleiben dabei über den Vorschauinformationen anklickbar.

Nach Abschluss der Datei-/Slicer-Vorbereitung enthält das gemeinsame Dropdown
„Turm-Einstellungen“ Kühlzeit, Abmessungen, Standfuß, Überhänge, Auflösung und
Zeitfenster. Die Abschnittsüberschriften wiederholen keine Einstellungswerte.
Der aktuelle Standard des lokalen Zeitfensters ist 51 Layer; explizit gespeicherte
Benutzerwerte bleiben erhalten. Das Speicherformat und die Bedeutung des Feldes
ändern sich dadurch nicht; es ist keine Schema-Migration erforderlich.

## Prüfungen

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
Die Fußhöhe betrug exakt 0,38 mm entsprechend den ersten zwei Layern.
Auch dieser auf drei Durchläufe begrenzte Test prüfte Geometrie und Datenfluss,
nicht vollständige Konvergenz. Originaldateien blieben bytegleich.

`test_automatic_foot.py` prüft die 20-Layer-Priorität, variable Layerhöhen,
kurze Türme, die füllungsabhängige Winkelgrenze, den geschlossenen Absatz sowie
die getrennte Zeitreferenz und den Schutz vor Verjüngung vor einem Bedarfseinbruch.
