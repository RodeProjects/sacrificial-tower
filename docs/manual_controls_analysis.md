# Linke Bedienelemente und direkte Vorschau

Stand: 12.10.2026. Diese Bewertung bezieht sich auf die manuelle Methode und
die Greiferaktionen einschließlich der direkten Wertefelder. Links bleiben
alle bisherigen Bedienelemente vorerst erhalten. Maßgeblich
sind `manual_panel.py`, `widgets/manual_canvas.py` und die zentralen
Geometrie-/Validierungsfunktionen in `manual/geometry.py`.

## Bereits weitgehend durch Greifer abgedeckt

| Linke Bedienelemente | Direkte Bedienung in der Vorschau | Voraussetzung für eine vollständige Entfernung links |
|---|---|---|
| Minimaler/maximaler Turm-Außendurchmesser, maximale Fußbreite | Mindestmaßpunkt/Grenzstrich ziehen oder direktes Wertefeld mit Einzel-Reset | Numerisch vollständig ersetzt; für Entfernung links noch die Greiferauswahl ohne Maus anbieten |
| Grunddurchmesser, aktuelle Fußbreite, Standfußhöhe, obere Turmhöhe, Spitzenbreite | Eigener Breiten-/Höhengreifer mit direkter Eingabe, Enter und Einzel-Reset | Numerisch vollständig ersetzt; eine Tastaturauswahl der festen Greifer ergänzen |
| Ausgewählter Punkt: Durchmesser/Höhe | Beide Koordinaten direkt am gewählten Punkt bearbeiten; eine Layernummer steht als Zusatzinformation oben | Zahlenfunktion ersetzt; freie Punkte haben bewusst keinen Positionsreset. Auswahlwechsel ohne Maus ergänzen |
| Kurvengriff: Durchmesserposition/Höhe | Ziehen des Béziergriffs; rechts bleiben die Informationen und Felder seines Profilpunkts sichtbar | Für das Entfernen links fehlt weiterhin eine präzise numerische Eingabe der Griffposition; die Profilpunktfelder ersetzen diese Koordinaten nicht |
| Punkt hinzufügen / Punkt entfernen | Profil doppelklicken; freien Punkt rechtsklicken oder Entf drücken | Eine tastaturbedienbare, sichtbare Hinzufügeaktion in der Vorschau ergänzen; Einfügen in den ausgewählten Abschnitt weiterhin anbieten |

Die Punkt- und Grenzwerte der ersten drei Zeilen sind durch den Punkteeditor numerisch abgedeckt:
horizontales Ziehen arbeitet in 0,1-mm-Schritten, direkte Texteingaben erlauben
präzisere Werte. Höhengreifer rasten standardmäßig auf Layer ein, direkte
Werte erlauben freie Höhen. Live-Prüfung, Enter-Feedback und Einzel-Reset
verwenden dieselbe Geometrieprüfung wie die linke Leiste. Einzelresets verwenden
dieselben Standards, sofern ein Standard vorhanden ist; freie Punktpositionen
besitzen keinen solchen Standard.
Erreichte Grenzen und abgelehnte Eingaben müssen nach Entfernen der linken
Felder direkt am Greifer oder seinem Werteeditor verständlich sichtbar bleiben.
Die Fußgrenze wächst inzwischen bei einer automatisch berechneten oder direkt
verbreiterten Fußform mit; die benötigte Breite wird zum Objektstandard. Als
eigene Grenze für die vollständige Fußkurve bleibt sie relevant, etwa bei
angepassten Béziergriffen. Ihr Zahlenfeld ist deshalb weiterhin erst mit einer
direkt editierbaren Grenzanzeige vollständig ersetzt; diese ist jetzt vorhanden.

Die gemeinsamen Zahlenfelder der ausgewählten Punkte überschneiden sich
zusätzlich mit den speziellen Feldern für Grund-, Fuß- und Spitzenbreite sowie
Turm-/Fußhöhe. Ein einzelner kontextabhängiger Editor am ausgewählten Greifer
ersetzt diese Zahlenfunktionen bereits und unterscheidet die getrennten Höhen-
und Breitengreifer mit derselben atomaren Geometrieprüfung.
Der Entfernen-Button ist am ehesten bereits entbehrlich: Rechtsklick und Entf
decken seine Funktion ab. Beim Hinzufügen fehlt noch eine entsprechende
Tastaturaktion; der Doppelklick ist nur in den beiden Profilansichten verfügbar.

## Noch ohne direkte gleichwertige Einstellung

| Linke Einstellung | Was in der Vorschau noch fehlt |
|---|---|
| Gerade / Bézierkurve | Eine direkte Abschnittsaktion für beide Modi; Ziehen eines Kontrollgriffs aktiviert bereits Bézier, der Punkt-Doppelklick setzt aber Bézier zurück und stellt keine Gerade her |
| Tangenten koppeln | Ein sichtbarer Kopplungszustand und ein bedienbarer Schalter am ausgewählten Punkt; beide Griffe müssen weiterhin dieselbe Steigung erhalten |
| Vertikale Greifer auf Layer einrasten | Ein dauerhafter Layer-/Millimeter-Schalter in der Vorschau; das vorhandene Einrasten macht den Wechsel selbst nicht überflüssig |
| Aufweitung/Verjüngung begrenzen und jeweiliger Winkel | Sichtbare Winkelgrenzen mit Greifer, Winkelanzeige und Aktivierung; diese müssen weiter das gesamte Kurvenprofil begrenzen |
| Turm-Kreissegmente | Ein eigener Turm-Auflösungsregler in der Vorschau oder eine neue, ausdrücklich definierte automatische Qualitätsregel; die Original-STL-Auflösung steuert diesen Wert nicht |
| Überhangstellen markieren und visueller Grenzwinkel | Bedienbarer Warnwinkel und Schalter an der Turmlegende; die Anzeige bleibt von den verbindlichen geometrischen Winkelgrenzen getrennt |
| Kritische Original-Layer, Farbreferenz, Farbbeginn und vollständig Rot | Eine interaktive Original-Legende mit Aktivierung, Sekundenwert und zwei Farbgrenzen; rote/grüne Flächen allein ermöglichen diese Eingaben nicht |

Diese Funktionen werden durch eine bereits sichtbare Auswirkung noch nicht
obsolet. Nach direkter Bedienung in der Vorschau können ihre linken Widgets
entfallen, ihre Werte, Einheiten und Validierungsregeln bleiben relevant.
Insbesondere darf die visuelle Überhangwarnung keine geometrische Winkelgrenze
ersetzen: die eine markiert Stellen, die andere verhindert ungültige Formen.

## Empfohlene Vereinfachung

1. Die jetzt vorhandenen Wertefelder nutzen und eine sichtbare Tastaturauswahl
   der Greifer ergänzen, damit alle Zahlenfunktionen auch ohne Maus erreichbar sind.
2. Abschnittsmodus, Tangentenkopplung und Hinzufügen/Entfernen direkt am
   ausgewählten Profilabschnitt anbieten; Layer-/Millimeterwechsel sichtbar halten.
3. Die acht allgemeinen Form-/Grenzfelder und zwei Profilpunkt-Koordinatenfelder
   links entfernen, sobald zusätzlich zur genauen Eingabe und den vorhandenen
   Resets auch die Auswahl per Tastatur vollständig durch die Vorschau abgedeckt
   ist. Die zwei Béziergriff-Koordinatenfelder bleiben bis zu einem gleichwertigen
   präzisen Bedienweg erforderlich.
4. Die noch eigenständigen Winkel-, Segment- und Farbeinstellungen kompakt
   beibehalten oder gezielt an passende Vorschau-/Legendenelemente verschieben.

Bereichsgrenzen, Quellenbindung, echte Layerhöhen, Rücksetzwerte und
Zahlenpräzision müssen dabei erhalten bleiben. Die Greiferaktionen und die
neuen direkten Eingaben verwenden dieselbe zentrale Validierung; das
Verschieben oder Entfernen eines Widgets entfernt keine fachliche Grenze.
