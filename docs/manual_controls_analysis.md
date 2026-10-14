# Linke Bedienelemente und direkte Vorschau

Stand: 14.10.2026. Die redundanten Maßfelder und Punktbuttons wurden aus der
linken Leiste des manuellen Modus entfernt. Die maßgebliche Bedienungsbeschreibung
steht in [Manueller Editor](manual_editor.md); dieses Dokument ordnet die
verbleibenden Einstellungen und noch offenen Bedienmöglichkeiten ein.

## Bereits aus der linken Leiste entfernt

| Entfernte Bedienelemente | Bedienung in der rechten Vorschau |
|---|---|
| Minimaler/maximaler Turm-Außendurchmesser, maximaler Fuß-Außendurchmesser | Mindestmaß- bzw. Grenzgreifer mit genauer Zahleneingabe und Einzelreset |
| Grunddurchmesser, aktueller Fuß-Außendurchmesser, Standfußhöhe, obere Turmhöhe, Spitzen-Außendurchmesser | Jeweiliger Breiten-/Höhengreifer mit genauer Zahleneingabe und Einzelreset |
| Ausgewählter Profilpunkt: Außendurchmesser/Höhe | Beide Koordinaten direkt am freien Profilpunkt; feste Punkte über ihre eigenen Greifer |
| Punkt hinzufügen | Doppelklick auf das Körperprofil in Nebeneinander/Voreinander |
| Punkt entfernen | Rechtsklick auf einen freien Punkt oder Entf/Backspace bei ausgewähltem Punkt in Nebeneinander/Voreinander |

Die zehn entfernten Zahlenfelder sind vollständig durch den direkten Werteeditor
ersetzt. Eingaben werden mit Enter übernommen, verwenden die zentrale
Geometrie-/Kontextprüfung und erhalten die interne Zahlenpräzision. Feste Maße
und Grenzen besitzen weiterhin ihre Objektstandards und Einzelresets; freie
Profilpunktpositionen haben bewusst keinen Standard und keinen Positionsreset.
Alle fachlichen Grenzen und gespeicherten Einstellungen bleiben erhalten.

Die Greiferauswahl und das Hinzufügen von Punkten benötigen derzeit weiterhin
die Maus. Eine Auswahl per Tastatur und eine tastaturbedienbare Hinzufügeaktion
in der Vorschau sind mögliche weitere Verbesserungen.

## Weiterhin eigenständige Einstellungen links

| Linke Einstellung | Noch fehlender gleichwertiger Bedienweg rechts |
|---|---|
| Béziergriff: Durchmesserposition/Höhe | Präzise Griffkoordinaten; der direkte Editor zeigt beim ausgewählten Griff dessen Profilpunkt |
| Gerade/Bézierkurve | Direkte Abschnittsumschaltung; Griffziehen aktiviert Bézier, Punkt-Doppelklick setzt Kurven zurück |
| Tangenten koppeln | Sichtbarer Kopplungszustand und bedienbarer Schalter |
| Vertikale Greifer auf Layer einrasten | Dauerhafter Layer-/Millimeter-Schalter |
| Aufweitung/Verjüngung begrenzen und jeweiliger Winkel | Aktivierung und Winkelwerte für die verbindlichen Geometriegrenzen |
| Turm-Kreissegmente | Eigener Regler für den erzeugten Turm; Auflösung (STL) steuert die Originaldarstellung |
| Überhangstellen markieren und visueller Grenzwinkel | Schalter und Warnwinkel |
| Kritische Original-Layer, Farbreferenz, Farbbeginn und vollständig Rot | Aktivierung, Sekundenwert und Farbgrenzen |

Eine sichtbare Wirkung ersetzt keine Einstellmöglichkeit. Die visuelle
Überhangwarnung markiert Stellen; die geometrischen Winkelgrenzen verhindern
ungültige Formen. Diese Funktionen bleiben getrennt. Beide Béziergriff-Felder
erscheinen links nur bei ausgewähltem Kontrollgriff. Die verbliebenen Form- und
Kurvenfelder sind weiterhin an die editierbaren Profilansichten gebunden;
visuelle Prüfeinstellungen bleiben auch in den räumlichen Ansichten verfügbar.
