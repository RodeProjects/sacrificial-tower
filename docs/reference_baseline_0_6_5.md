# Referenz- und Qualitätsstand 0.6.5

Erfasst am 27. August 2026 auf Windows 11 (`10.0.26200`, x64) mit
CPython 3.13.2. Maßgeblich ist der unveränderte Git-Commit
`a3d89a55f7560c2e99d854152901cf9a8ffcceb5` mit `APP_VERSION = "0.6.5"`.
Die Messungen wurden aus einem isolierten `git archive` dieses Commits in
einem temporären Anwendungsverzeichnis ausgeführt. Lokale Folgeänderungen
waren dadurch nicht Bestandteil des Referenzlaufs.

## Reproduzierbarer Qualitätsstand

| Prüfung | Ergebnis | Dauer |
| --- | ---: | ---: |
| Native C++-Erweiterung frisch bauen | erfolgreich | im Gesamtlauf enthalten |
| `python -m unittest discover -s tests -q` | 925 erfolgreich, 10 übersprungen | 121,407 s |
| Reale Anycubic-/Bambu-Integration | 5 erfolgreich, 2 mangels Benutzerprofilen übersprungen | 172,884 s |

Die realen Tests liefen mit `COOLING_TOWER_RUN_REAL_SLICER_TESTS=1` gegen die
installierten Programme unter `C:\Program Files\AnycubicSlicerNext` und
`C:\Program Files\Bambu Studio`. Quell-STLs, Slicer-Installationen und
Slicer-Profile wurden ausschließlich gelesen. Die Tests vergleichen die
Hashes beziehungsweise Dateizustände vor und nach den Abläufen; alle
ausgeführten Unveränderlichkeitsprüfungen waren erfolgreich. Sämtliche
Arbeits- und Ausgabedateien lagen in anwendungseigenen temporären
Verzeichnissen.

## Reale Referenzfälle

| Referenzfall | Abdeckung in 0.6.5 | Referenzergebnis |
| --- | --- | --- |
| Anycubic, kontrollierter Pre-Slice | vollständig ausgeführt | Slice, Analyse, Profilquellschutz und Abbruchbereinigung erfolgreich |
| Anycubic, GUI-Benutzerprofile | nicht ausführbar | die drei im Test benannten lokalen Benutzerprofile sind nicht installiert |
| Anycubic, vollständige gemeinsame Kalibrierung | nicht ausführbar | abhängig von denselben fehlenden Benutzerprofilen |
| Bambu, 100-%-Turmfüllung | vollständig ausgeführt | gemeinsame Assembly, Slowdowns, Füllungszuordnung und Profilquellschutz erfolgreich |
| Bambu, vollständige Kalibrierung | vollständig ausgeführt | 6 getrennte und 6 gemeinsame Runden; sicherer bester Zwischenstand exportiert |
| Regelmäßiges Modell | abgedeckt | `input/Test-STL (manifold).stl`, unverändert |
| Stark wechselnde Layerzeiten | teilweise abgedeckt | reale gemeinsame Bambu-Runden und synthetische Unit-Regressionen |
| Enge Spline-/Winkelgrenzen | synthetisch abgedeckt | vollständige Unit-Suite erfolgreich; kein eigener realer Slicer-Messlauf vorhanden |
| Unterschiedliche Ziel-Layerzeiten | synthetisch abgedeckt | vollständige Unit-Suite; realer End-to-End-Lauf nur mit 10,0 s Zielzeit |

Die Bambu-Referenzkalibrierung benötigte zwölf Slicer-Runden. Die gemessenen
kleinsten gemeinsamen Layerzeiten waren:

`6,970 s → 8,641 s → 9,431 s → 9,490 s → 9,572 s → 9,527 s`

Der anhand der vollständigen Bewertungsfunktion gewählte beste Kandidat stammt
aus Runde 9 und besitzt eine kleinste vorhergesagte Layerzeit von 9,431 s. Der
Lauf endete kontrolliert mit `limit_reached`; das exportierte 3MF enthielt
nachweislich genau das Mesh des gewählten Kandidaten (ein passender
Mesh-Treffer). Dieser Wert ist die Regression gegen den früheren
`stale-tower`-Fehler.

## Messmatrix für die drei Optimierungen

| Messgröße | In 0.6.5 belastbar vorhanden | Vergleichsregel |
| --- | --- | --- |
| Gesamttestzeit | 121,407 s | nur als grober Regressionsindikator verwenden |
| Reale Integrationszeit | 172,884 s für sieben geladene Tests | Hardware und installierte Slicer konstant halten |
| Getrennte/gemeinsame Rundenzahl | Bambu: 6/6 | nach der Änderung höchstens dieselbe Slice-Anzahl |
| Kleinste finale Layerzeit | Bambu: 9,431 s beim gewählten Kandidaten | unverändert bis auf Maschinenrundung |
| Gemeinsame Layerzeitfolge | vollständig oben erfasst | normalisierte Werte rundenweise vergleichen |
| Finales Kandidatenmesh im 3MF | exakt bestätigt | nach verzögertem Export weiterhin exakt bestätigen |
| Slicer-Quelldateien | Hash/Dateizustand unverändert | vor und nach jedem realen Lauf vergleichen |
| Block-Cache-Treffer, Verwerfungen, Bytes | Schnittstelle vorhanden, aber im realen Testlauf 0.6.5 nicht je Analyse protokolliert | neue per-Analyse-Diagnostik gegen erzwungenes Cache-an/-aus prüfen |
| Quell-/Vorschauanalysezeit | in 0.6.5 nicht getrennt protokolliert | mit demselben G-Code und derselben Segmentgrenze messen |
| Spitzenspeicher | in 0.6.5 nicht pro Phase protokolliert | Cache-Schätzung und Prozessmessung getrennt ausweisen |
| Profiländerung, Unter-/Überschreitung, Defizitlayer, Volumen, Maximalbreite | in den Bewertungsobjekten vorhanden, im Referenzlauf nicht vollständig ausgegeben | in neuen Regressionstests direkt aus den Iterationen vergleichen |

Fehlende Messwerte werden ausdrücklich nicht nachträglich geschätzt. Für einen
vollständigen Vorher-/Nachher-Leistungsvergleich mit dem früher verwendeten
18,3-MB-G-Code muss genau diese Referenzdatei oder eine freigegebene Kopie in
einem anwendungseigenen Arbeitsverzeichnis bereitgestellt werden. Im
Repository befindet sich derzeit keine `.gcode`- oder `.3mf`-Referenzdatei
dieser Größe. Funktionale Gleichheit wird deshalb zusätzlich mit
deterministischen G-Code-Fixtures, erzwungenen Cache-Richtlinien und den realen
Slicer-Regressionen abgesichert.
