# Linke Bedienelemente und direkte Vorschau

Stand: 17.10.2026. Die redundanten Maßfelder und Punktbuttons wurden aus der
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
| Vertikale Greifer auf Layer einrasten | Dauerhafter Layer-/Millimeter-Schalter |
| Maximaler Aufweitungswinkel; darunter „Max. Aufweitungswinkel in Vorschau begrenzen“ | Winkelwert und Aktivierung der verbindlichen Geometriegrenze |
| Turm-Kreissegmente | Eigener Regler für den erzeugten Turm; Auflösung (STL) steuert die Originaldarstellung |
| Überhangstellen markieren und visueller Grenzwinkel | Schalter und Warnwinkel |
| Layerzeit-Einfärbungen aktivieren | Checkbox direkt hinter dem Text; darunter Rot bis / Grün ab (6 s / 10 s), feste Beschriftungen links/rechts und editierbares Skalenende (Standard 14 s, mindestens 3 s); grüne Grenze und Endwert teilen die objektabhängige Obergrenze (normalerweise 60 s). Graues Dreieck unter der Leiste für das Objekt-Minimum, bei Platzmangel als Zusatztext unter allen Werten. Greifer stoppen still; nur ungültige Boxeingaben zeigen rote Hinweise. |

Eine sichtbare Wirkung ersetzt keine Einstellmöglichkeit. Die visuelle
Überhangwarnung markiert Stellen; die geometrischen Winkelgrenzen verhindern
ungültige Formen. Diese Funktionen bleiben getrennt. Beide Béziergriff-Felder
erscheinen links nur bei ausgewähltem Kontrollgriff. Die verbliebenen Form- und
Kurvenfelder sind weiterhin an die editierbaren Profilansichten gebunden;
visuelle Prüfeinstellungen bleiben auch in den räumlichen Ansichten verfügbar.

Die verbliebenen Einstellungen stehen in nur zwei Bereichen: **Turmform und
Bearbeitung** sowie **Visuelle Prüfung**. Verjüngungsschalter und -winkel,
Abschnittsdropdown und Tangentenkopplungsschalter sowie die zusätzlichen
Profilwert-/Farbvergleichstexte wurden entfernt. Griffziehen aktiviert weiterhin
Bézierabschnitte; Punkt-Doppelklick setzt ihre Kurven zurück. Bestehende
Winkel- und Tangentendaten bleiben intern kompatibel.

**Turmform zurücksetzen** entfernt freie Punkte und stellt feste Punkte sowie
Béziergriffe unter den aktuellen Grenzen wieder her. Unabhängige Einstellungen
bleiben erhalten. **Alles zurücksetzen** stellt zusätzlich alle manuellen
Einstellungen und Vorschaupräferenzen auf ihre Standards zurück. Einzelheiten
und der Umgang mit engeren Grenzen stehen im [manuellen Editor](manual_editor.md#ergebniszustände-und-export).
