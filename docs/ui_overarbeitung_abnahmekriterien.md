# UI-Überarbeitung – verbindliche Zustände und Abnahmekriterien

Dieses Dokument ist die Prüfbasis für die schrittweise UI-Überarbeitung. Es
beschreibt beobachtbare Zustände und keine interne Implementierung. Ein Zustand
gilt nur dann als erfüllt, wenn die Oberfläche, die Bedienbarkeit und die
zugehörigen automatisierten Tests übereinstimmen.

Die maschinenlesbare Fassung befindet sich in
`tests/references/ui_overhaul_acceptance.json`.

## Übergreifende Regeln

- Die Oberfläche bleibt bei 720 px Fensterbreite sowie bei 100, 125, 150, 175
  und 200 Prozent Windows-Skalierung ohne horizontales Scrollen bedienbar.
- Der Scrollbalken liegt zwischen Fensteraußenkante und Inhalt. Die Karten
  behalten links und rechts denselben Inhaltsabstand.
- Fortschrittsanzeigen enthalten Prozentwert, Statussymbol und einen deutschen
  Arbeitsschritt unmittelbar unter dem Balken.
- Während der Vorschauerstellung zeigen Haupt- und Vorschaufenster bewusst den
  gleichen Fortschritt.
- Slicerdateien und Slicerprofile werden ausschließlich gelesen und niemals
  verändert.
- Ein fehlender Slicer blockiert den analytischen STL-Arbeitsweg nicht.
- Automatisches Einklappen erfolgt nur beim ersten erfolgreichen Abschluss. Eine
  spätere manuelle Entscheidung des Benutzers wird respektiert.
- Erfolgsfärbung und automatisches Einklappen dauern beim ersten erfolgreichen
  Abschluss von Referenz-G-Code und Slicer 1.000 ms. Alle weiteren Animationen
  dauern 250 ms.
- Karten derselben Reihe sind in der zweispaltigen Darstellung gleich hoch und
  richten ihren Inhalt oben aus.
- Interaktive Bedienelemente und aufklappbare Kartenköpfe besitzen einen
  sichtbaren Hover-Zustand; Dropdowns zeigen einen Chevron-Pfeil.
- Das Info-Symbol rechts oben ist exakt kreisförmig und zeigt seinen
  erklärenden Hinweis ausschließlich für die Dauer des Hoverns.
- Hover-Hinweise bleiben als kompakte Popover vollständig innerhalb
  des jeweiligen Haupt- oder Vorschaufensters und weichen an dessen Rand nach
  links beziehungsweise oben aus.
- In Hinweiszeilen sind Symbol und Text vertikal zentriert. Hinweistext bleibt
  auch bei schmalen Fenstern und langen Inhalten vollständig lesbar.
- Jede geöffnete Karte trennt ihren Kopf mit einer dünnen, gegenüber dem
  Außenrahmen dezenteren Linie vom Inhalt.
- Slicer-Dropdowns sind gleich breit, dürfen bis zu einem Drittel der
  verfügbaren Slicer-Kartenbreite nutzen und öffnen lange Einträge breit genug.

## Verbindliche Oberflächenzustände

### 1. Kein G-Code ausgewählt

- Der G-Code-Bereich ist der einzige fachliche Arbeitsschritt.
- Der feste Status fordert zur G-Code-Auswahl auf; der Bereich erklärt die
  Abfolge Slicen, G-Code exportieren und anschließend importieren.
- Import-Symbol und Überschrift stehen gemeinsam links; ein verteilter Punkt
  wird nicht verwendet.
- Das anfängliche Pfeilsymbol besitzt eine eigene, ausreichend große
  Renderfläche und ist sichtbar größer als die späteren Statussymbole.
- Vorschau und Export sind deaktiviert und ihr Grund ist verständlich sichtbar.
- Es werden keine Prognosen als berechnet dargestellt.

### 2. G-Code wird analysiert

- Der Analysefortschritt ist im G-Code-Bereich sichtbar.
- Prozentwert, laufender Arbeitsschritt und Statussymbol stimmen überein.
- Der Export bleibt während der Analyse deaktiviert.

### 3. G-Code erfolgreich analysiert

- Dateiname, Layerzahl und erfolgreicher Status sind verfügbar.
- Die vollständigen Dateiinformationen bleiben nach erneutem Öffnen erreichbar.
- Die rekonstruierte Konfiguration startet geschlossen.
- Die Datei kann über „G-Code neu einlesen“ erneut analysiert werden.

### 4. Slicer werden gesucht

- Die Suche zeigt einen eigenen Fortschritt und behauptet noch keine
  unbestätigte Profilzuordnung.
- Der G-Code-Erfolg bleibt erkennbar.

### 5. Slicer erfolgreich erkannt

- Der ausgewählte Slicer ist in der Zusammenfassung erkennbar.
- Profilinformationen werden nur mit ihrer tatsächlich bekannten Sicherheit
  bezeichnet.
- Automatisch erkannte Installationen tragen im Kartenkopf den farbigen Zusatz
  „(automatisch erkannt)“.
- Die eingebettete Konfiguration ist im Slicer-Bereich auf- und zuklappbar und
  startet geschlossen.

### 6. Kein verwendbarer Slicer erkannt

- Der Zustand wird als Warnung und nicht als Programmfehler dargestellt.
- Manuelle Auswahl, erneute Suche und analytisches Fortfahren bleiben möglich.

### 7. Einstellungen und Prognose verfügbar

- Kühlziel und Prognose sind die visuell wichtigsten Bereiche.
- Beschriftung und Wert einer Prognosezeile sind eindeutig zuzuordnen.
- Die Prognose reserviert getrennte Spalten für Beschriftungen, Werte und
  Hinweise.
- Bei analytischer Schätzung warnt die Hinweisspalte vor der geringen
  Genauigkeit. Ein verwendbarer Slicer bietet dort eine einmalige Schätzung mit
  exakt fünf Durchläufen an, ohne den eingestellten Durchlaufwert zu verändern.
- Technische Einstellungen bleiben erreichbar, dominieren die Hauptansicht aber
  nicht.

### 8. Geometrie mit gültigen Werten

- Es gibt keine rote Feldmarkierung und keinen Fehlerbereich.
- Die Prognose verwendet keinen Fehlerstatus.

### 9. Geometrie mit Fehlern

- Fehler werden nach Ursache gruppiert, nicht nach Layer wiederholt.
- Nur das zuletzt geänderte, fehlerauslösende Feld wird rot markiert.
- Der Feldhinweis enthält nur eine kurze Zusammenfassung ohne Layerangaben;
  Diagnose, betroffene Layer und Lösungswege stehen im roten Fußbereich.
- Außerhalb der Prognose werden betroffene Layer ausschließlich im fixierten
  roten Fußbereich genannt.
- Grenzdiagnosen benennen ausdrücklich, ob ein Wert minimal oder maximal
  möglich ist, beispielsweise „maximal möglich 70,00°“.
- Der erste Lösungsvorschlag korrigiert immer den auslösenden Wert durch
  Erhöhen, Verringern oder Zurücksetzen.
- Der Aufweitungswinkel ist bei der Eingabe und in Lösungsvorschlägen auf
  höchstens 70° begrenzt; ab 51° erscheint ein Vorsichtshinweis.
- Prognose und Fehlerstatus dürfen sich nicht widersprechen.
- Die vollständigen Rohdaten verbleiben im technischen Bericht.

### 10. Vorschau wird erstellt

- Haupt- und Vorschaufenster zeigen denselben Fortschritt.
- In beiden Fenstern steht der Arbeitsschritt unter dem Fortschrittsbalken.
- Beide Vorschau-Buttons sind deaktiviert und tragen den eindeutigen Text
  „Vorschau wird erstellt...“.

### 11. Vorschau ist aktuell

- Der Zustand ist grün und eindeutig erkennbar.
- Der Export bleibt unabhängig von der optionalen Vorschau möglich.
- Die erste Kameraansicht und der Button „Seitenansicht“ verwenden dieselbe,
  weiter herausgezoomte Seitenansicht.
- Ein rechtsbündiger Button „Kühlturm exportieren“ verwendet denselben
  Exportzustand wie die Hauptansicht.
- Beim ersten Öffnen steht das Fenster nach Möglichkeit rechts neben dem
  Hauptfenster; andernfalls gibt das Hauptfenster Bildschirmfläche frei.

### 12. Vorschau ist veraltet

- Haupt- und Vorschaufenster kennzeichnen den Zustand deutlich.
- Beim Export werden die drei vereinbarten Entscheidungen angeboten.

### 13. Export wird ausgeführt

- Vorschau- und Einstellaktionen können keinen konkurrierenden Auftrag starten.
- Fortschritt und aktueller deutscher Arbeitsschritt sind sichtbar.

### 14. Export erfolgreich

- Die erzeugte STL-Datei, der Kurzbericht und der technische Bericht sind
  verständlich erreichbar.
- Die Ausgabe wird nicht als unstrukturierter technischer Textblock dargestellt.
- Der gelbe Hinweisbereich wächst mit seinem Inhalt, bleibt bei kurzem Text
  kompakt und scrollt nur bei tatsächlich langen Hinweisen.

### 15. Responsive und skalierte Darstellung

- Karten wechseln am definierten Haltepunkt zwischen zwei Spalten und einer
  Spalte.
- Die beiden Geometrie-Teilbereiche werden nur in der breiten Darstellung
  durch eine senkrechte Linie optisch voneinander getrennt.
- Eingabefelder, Reset-Buttons und Spinbox-Pfeile überlappen nicht.
- Hauptaktionen werden bei schmaler Breite nicht abgeschnitten.
- Beschriftungen stehen links, gleich große Editoren und Reset-Schaltflächen
  rechts.
- Zusatzinformationen erhalten nach dem nur bedarfsgroßen Überschriftentext
  den gesamten verbleibenden Platz.
- Verschachtelte Bereichstitel stehen links und ihr Chevron am rechten Rand.
- Beim Öffnen der Ausgabeoptionen bleibt der Kartenkopf während der Animation
  stabil, der Inhalt wächst nach unten und die vollständige Karte wird danach
  einschließlich Sicherheitsabstand oberhalb des fixierten Fußbereichs
  sichtbar gescrollt. Wiederholtes Schließen und Öffnen liefert denselben
  Zustand.

## Abnahme je Arbeitspaket

Jedes Arbeitspaket wird mit gezielten Tests abgeschlossen. Die gesamte
Überarbeitung gilt erst nach erfolgreicher vollständiger Testsuite, Prüfung der
realen 891-Layer-Referenzdatei und einem visuellen Zustandsabgleich als fertig.
