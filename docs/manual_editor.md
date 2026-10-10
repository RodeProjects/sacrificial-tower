# Manueller Kühlturmeditor

Die Methode **Manuelle Generierung** gestaltet einen rotationssymmetrischen
Kühlturm direkt in der eingebetteten Vorschau. Sie verwendet die vorhandene
bestätigte Quelle und Profilbindung. Datei-/Slicervorbereitung und automatische
Formberechnung bleiben eigenständige bestehende Abläufe. Ein Methodenwechsel
erhält beide Entwürfe und ihre getrennten Ergebnis- und Exportstände.

## Bedienung und eigene Einstellungen

Seiten- und Vorderansicht ermöglichen die Bearbeitung. Fußrand, Körperanschluss,
oberer Abschluss und freie Profilpunkte besitzen unterschiedliche Greifer.
Der Fußhöhen-Greifer ist neben dem Körperanschluss versetzt; die tatsächliche
Geometrie bleibt an dessen Position. Zahlenfelder und Greifer synchronisieren
sich in beiden Richtungen. Durchmesser werden in Millimetern angezeigt, intern
werden Radien gespeichert.
Alle Fließkommafelder zeigen gerundet zwei Nachkommastellen; die Modell- und
Speicherpräzision bleibt erhalten. Kreissegmente bleiben ganzzahlig. Der obere
Höhengreifer rastet innerhalb von 14 Bildschirm-Pixeln auf die tatsächliche
Objekt-Endhöhe ein. Außerhalb dieses Bereichs und bei numerischen Eingaben bleibt
die Höhe stufenlos. Der Bildschirmabstand berücksichtigt Zoom und Pan.
Beim Einrasten erscheint für 850 ms eine horizontale Hilfslinie mit der
Beschriftung „Objektoberkante“. Sie verbindet die Höhe optisch über die
Vorschau hinweg und folgt demselben Maßstab wie Turm und Original. Fortgesetztes
Ziehen innerhalb des Snap-Bereichs verlängert die Anzeige nicht; beim Verlassen
des Bereichs verschwindet sie sofort und erscheint beim erneuten Einrasten wieder.
Beim vertikalen Ziehen eines Höhen-, Fußhöhen-, freien Profil- oder
Bézierkontrollgreifers folgt außerdem eine horizontale Hilfslinie dessen
tatsächlich angenommener Höhe über die gesamte Vorschau. Sie reicht über das
Originalobjekt und zeigt die Höhe in Millimetern. Diese Linie bleibt während
des Ziehens sichtbar und verschwindet beim Loslassen. Rein horizontale
Greiferbewegungen blenden sie nicht ein; Geometriegrenzen und Snapping werden
in ihrer Position berücksichtigt.

Ein Doppelklick auf das Körperprofil fügt einen Punkt ohne Formänderung ein.
Alternativ fügt die Punktaktion einen Punkt in den ausgewählten Körperabschnitt
ein. Freie Punkte lassen sich über die Aktion oder die Entf-Taste entfernen;
Fuß, Körperanschluss und oberer Abschluss bleiben erforderlich. Jeder Abschnitt
kann gerade oder als kubische Bézierkurve bearbeitet werden. Kontrollgreifer
erscheinen für die angrenzenden Abschnitte. Innenpunkte können ihre Tangenten
koppeln; beide Seiten erhalten dann dieselbe lokale Steigung.

Jede numerische Einstellung besitzt Einheit, Info und Reset. Wiederverwendbare
manuelle Werte werden separat gespeichert, einschließlich eigener Zielzeit,
Toleranz, Durchmessergrenzen, Fußwerte und Kreissegmentzahl. Der Gesamtreset
erzeugt einen neuen gültigen Anfangsentwurf. Punkt-/Kontrollpunktresets verwenden
den Ausgangswert des jeweiligen stabil identifizierten Greifers. Die
Automatikeinstellungen werden dabei nicht verändert.

Ungültige Bewegungen gelangen nur bis zur ersten gültigen Grenze. Die tatsächlich
begrenzende Einstellung wird kurz rot markiert; weitere Ereignisse derselben
Interaktion verlängern das Blinken nicht ständig. Auch Werte, die Qt bereits
an seinen Eingabegrenzen abfangen würde, gelangen zur fachlichen Grenzprüfung.
Unmögliche Optionswechsel werden zurückgewiesen. Der letzte gültige Entwurf
bleibt erhalten. Bei einer für die Quelle ungültigen gespeicherten Konfiguration
können Einstellungen korrigiert und die Initialisierung erneut versucht werden.

3/4-, Drauf- und freie Ansicht dienen der Betrachtung und sperren geometrische
Bearbeitung. Mausrad zoomt um die Mausposition; mittlere Maustaste verschiebt,
rechte Maustaste dreht die räumliche Kamera. „Ansicht einpassen“ stellt beide
Objekte vollständig und mit demselben physikalischen Maßstab dar. Objektrotation,
Hervorhebung, Auswahl, Hover und Kamera verändern keine Druckdatei.

Bei kleinen Fensterbreiten wechseln Einstellungen und Vorschau von einer
nebeneinanderliegenden zu einer gestapelten Anordnung. Die Einstellungen bleiben
scrollbar; Aktionen und Vorschau sind weiterhin zugänglich.
Die Trennlinie übernimmt die Gestaltung des Bereichseditors: ein Pixel Breite,
14 Pixel Abstand der Inhalte auf beiden Seiten und keine einklappbaren Bereiche.
Die linke Scrollfläche bestimmt weder Höhe noch Position der Vorschau. Auch
eingeblendete Grenzmeldungen und eine veränderte Scrollbalkenreichweite lassen
die Darstellung unverändert stehen.
Die Vorschau passt sich bei Fenster-/Methodenwechseln und nach abgeschlossenen
Vorbereitungs-/Generierungsjobs an den verfügbaren Bereich oberhalb des Footers
an. Während der Bearbeitung bleibt diese Höhe fest. Eine reservierte Breite des
äußeren Scrollbalkens verhindert zusätzlich horizontale Sprünge durch Meldungen;
beim Verlassen der Methode wird die vorherige Scrollpolitik wiederhergestellt.
Bei sehr kleinen Fenstern bleibt die Mindestfläche der Bedienelemente erhalten
und der Inhalt lässt sich vollständig zur Vorschau scrollen.
Die Vorschau besitzt dafür eine eigene Mindesthöhe aus Zeichenfläche und
Bedienelementen. Sie gilt auch beim Wechsel zur gestapelten Anordnung, damit
beibehaltene Trennergrößen keine Überlagerung der Bedienelemente verursachen.

In der Seitenansicht liegen Turm und Original nebeneinander. Die um 90° gedrehte
Vorderansicht projiziert beide hintereinander auf dieselbe Referenzachse.
Hervorhebung und vorrangige Greifer ermöglichen die Bearbeitung bei Überlagerung.
Diese Referenzansichten sind von der tatsächlichen Druckbettanordnung in den
räumlichen Ansichten unterscheidbar beschriftet.

Generieren/Aktualisieren, Exportieren, Abbrechen und „Standardwerte
wiederherstellen“ liegen im **Hauptfenster-Footer**. Derselbe Footer verwaltet
die Ordner-/Berichtsaktionen, Kürzungsreihenfolge und Umbrüche wie bei der
automatischen Methode. Die Aktionen richten sich nach der aktiven Methode;
der Reset bestätigt ausdrücklich den manuellen Umfang. Status, Fortschritt
und Hinweise zum bisherigen geprüften Stand stehen ebenfalls im Footer.

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

Einfügen verwendet De Casteljau und teilt die vorhandene Kurve exakt. Löschen
verbindet die Nachbarpunkte erneut und akzeptiert die neue Verbindung nur bei
gültigem Gesamtprofil. Profilpunkte benötigen mindestens 0,05 mm Z-Abstand;
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
`Radius * (1 - cos(pi / Segmentzahl))`. Die räumliche Anzeige darf weniger
Winkelsegmente zeichnen; die STL-Segmentzahl bleibt unverändert.

Die Mesh-Konstruktion übernimmt die etablierte Ring-/Kappentopologie.
Die vorhandene Mesh-Validierung und der binäre STL-Schreiber werden verwendet.
Anschließend prüft `StlValidationService` auch das tatsächlich geschriebene
Float32-STL streng auf die technischen Geometriebedingungen. Erst danach wird
die feste Form geslicet. Abbruchprüfungen erfolgen während Unterteilung,
Ring-/Flächenerzeugung, Schreiben und STL-Prüfung.

## Darstellung, Farben und Hintergrundarbeit

Original-STL und vollständige echte Layerquerschnitte werden einmal pro
Quellenkontext im Hintergrund vorbereitet und unverändert gehalten. Die statischen
Ansichten verwenden den bestehenden `LayerRangeCanvas` für die vollständige
Querschnittsprojektion. Sie erzeugen keine fiktive Originalgeometrie aus G-Code.
Ohne Original-STL werden ausschließlich die vorhandenen Druckbahnen angezeigt.

Kritische Originalschichten verwenden exakt `LayerRangeCanvas.layer_color()`
mit den tatsächlichen ursprünglichen Layerzeiten. Ziel, Beginn des Defizitverlaufs
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
Originaldarstellung weiter. Teure räumliche Originalflächen bzw. große
Druckbahndarstellungen werden als `JobKind.MANUAL_VIEW` durch den bestehenden
`BackgroundJobManager` gerendert. Ein kurzer Timer bündelt Kamerabewegungen;
währenddessen erscheinen reduzierte echte Originaldruckbahnen. Der Worker
zeichnet ausschließlich in sein eigenes `QImage`. `QPixmap` und Widgets bleiben
im GUI-Thread. Request-ID und vollständige Kamera-/Farbidentität verwerfen
verspätete Bilder. Ein Quellen-/Ansichtswechsel bricht ersetzte Jobs ab. Das
Schließen des Hauptfensters verhindert neue Renderjobs und nutzt den zentralen
kontrollierten Shutdown.

## Ein unveränderter Prüfslice

`ManualGenerationService` friert Entwurf, Bewertung und bestätigten Kontext ein.
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
bleiben die ursprünglichen Defizite oberhalb des Turms im Ergebnis sichtbar.
Zusätzliche tatsächlich geslicete gemeinsame Schichten werden ebenfalls bewertet.

Technischer Abschluss, gemeinsame Verifikation/Prognose und Zielerreichung
sind getrennte Merkmale. Das Ziel gilt, wenn jede bewertete Schicht mindestens
`Zielzeit - Toleranz` erreicht. Ein technisch vollständig geprüfter Stand mit
verbleibendem Zeitdefizit ist mit deutlicher Warnung exportierbar. Fehlgeschlagene,
abgebrochene oder unvollständige Läufe werden nicht als Ergebnis übernommen.

## Ergebniszustände und Export

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
erste Layerhöhe, tatsächliche Kreissegmentzahl, Ziel/Toleranz, relevante
Profil-/Objektwerte, Quellen- und Profilidentitäten. Reine Grenzwerte, die ohne
Formänderung lediglich die zentrale Validierung verschärfen, werden neu geprüft,
erzeugen aber kein anderes Artefakt. Punktkennungen, Tangentenkopplung ohne
Koordinatenänderung und rein visuelle Werte gehören nicht zur Artefaktidentität.
Ein exaktes Rücksetzen auf den erfolgreichen Stand entfernt den Aktualisierungsbedarf.
Die automatischen Signaturprüfungen bleiben unverändert.

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

`manual_settings.json` hat ein eigenes Schema 1 und läuft über
`VersionedJsonStore`. Geometriepunkte, Quellenbindung und Artefakte werden nicht
persistiert. Unbekannte neuere, beschädigte oder extern geänderte Dateien
werden nicht überschrieben. Details zur expliziten 0→1-Migration und den
Sicherungen stehen in [Persistenz](settings_migrations.md).

## Prüfungen und reale Abnahme

`test_manual_geometry.py` prüft Anfangsform, Fußabhängigkeiten, exakte
Unterteilung, Punktoperationen, Tangenten, vollständige Kurvenextrema,
Winkelgrenzen, Mesh-Topologie, Fehlergrenze und Abbruch.
`test_manual_persistence.py` prüft Normalisierung, getrennte Werte, Migration,
Backup, atomare Speicherung, unbekannte neuere und beschädigte Dateien sowie
externe Änderungen. `test_manual_generation.py` prüft den festen Einzel-Slice,
gemeinsame Verifikation und Prognose, sichere Layerzuordnung, höhere Defizite,
Quellen-/Profilschutz und unveränderte exportierte Artefakte.
`test_manual_gui.py` ergänzt Greifer-/Zahlenfeldsynchronisierung, Projektion,
kleine Fenster, Ansichtssperren, Grenzfeedback, unabhängige Sitzungen,
Ergebnisübergänge, alten Export, verspätete Callbacks, tatsächlichen Prozessabbruch,
Schließen und verwaltete räumliche Renderjobs.
Zusätzliche Tests prüfen Höhen-Snapping, zwei sichtbare Nachkommastellen bei
erhaltener Modellpräzision, die überlagerte Vorderansicht, stabile Vorschaugeometrie
bei Meldungen sowie den echten Hauptfenster-Footer einschließlich gleicher
Kürzungs-/Umbruchregeln und ausschließlich manuellem Reset.

Die abschließende Regressionsprüfung verwendet die vollständige vorhandene
Suite mit `.\.venv\Scripts\python.exe -m unittest discover -s tests -q` und
`QT_QPA_PLATFORM=offscreen`. Reale manuelle Slicerprüfungen stehen zusätzlich
in `test_real_manual_generation.py` und werden explizit mit
`COOLING_TOWER_RUN_REAL_SLICER_TESTS=1` aktiviert. Ohne installiertes passendes
Programm werden sie übersprungen; das ersetzt keine reale Abnahme.
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
