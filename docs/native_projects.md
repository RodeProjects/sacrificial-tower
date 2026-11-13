# Native 3MF-Projekte im iterativen Modus

Ein natives 3MF-Projekt enthält Modelle, ihre Platzierungen und die eingebettete
Slicerkonfiguration. Eine reine Geometrie-3MF genügt nicht. Die Anwendung erkennt
den Erzeuger anhand des Inhalts und verarbeitet eine ausgewählte Druckplatte
mit der zugehörigen separat installierten Engine.

## Eingabe und Bedienung

Die Dateiübergabe besitzt einen einzigen Ablagebereich für STL und 3MF. Der
Dateityp bestimmt den weiteren Ablauf: STL verwendet die bestehende Geometrie-
und Slicervorbereitung; ein vollständiges natives 3MF öffnet nach dem Einlesen
direkt die Projektmaske. Die Archivprüfung läuft im Hintergrund, während die
Dateiübergabe mit ihren Informationen und dem Ladebalken sichtbar bleibt.

Die Dateiinfo enthält den erkannten Slicer, Erzeugerversion, Drucker, Düse,
Maschinen-, Filament- und Prozessprofile sowie die Druckplatten. Filamentprofile
werden untereinander angezeigt. Der Header der Projektmaske bündelt Dateiname,
Slicer, Methode, Erzeugerversion und Druckplatteninformation. Seine Infofläche
und **Zurück zur Dateiübergabe** öffnen die vollständige Dateiinfo. Eine zusätzliche manuelle Profilbestätigung
entfällt. Auch aus der Projektinfo kann wieder eine STL oder eine 3MF ausgewählt
oder abgelegt werden.

Bei mehreren Platten zeigt die Auswahl kompakte Karten mit Namen, Objektanzahl
und auf den sichtbaren Inhalt zugeschnittener Vorschau. Die Leiste lässt sich horizontal mit
gedrückter linker Maustaste oder per Touch verschieben; ein Ziehen verändert
die gewählte Platte nicht. Klick und Pfeiltasten wählen die Platte aus.
Jede Platte wird getrennt vorbereitet und berechnet. Alle
Objekte und Instanzen der gewählten Platte werden gemeinsam geslict.
Die Turmeinstellungen wirken auf den ergänzten Kühlturm; ursprüngliche
Objektplatzierungen und eingebettete Profile werden nicht neu angeordnet.

Die native Projektmaske bietet ausschließlich die Methode **Iterativ**.
Links stehen die Turmeinstellungen, in der Mitte die Vorschau und rechts das
Schichtzeitdiagramm. Die Trennleiste lässt sich verschieben; bei schmalen
Fenstern werden die Bereiche untereinander angeordnet. Die Navigation ist
standardmäßig eingeschaltet. Ansichtsbuttons und die Diagrammumschaltung
stehen über der Vorschau. Das Diagramm öffnet sich, sobald Layerzeiten vorliegen.
Es zeigt die ursprünglichen und gemeinsam geslicten Zeiten. Während der getrennten
Kalibrierung zeigt die G-Code-Vorschau nur die Bahnen des Turms. Das Diagramm zeigt
in dieser Phase die geschätzte Summe aus Modell- und Turmzeiten. Logarithmische
und normalisierte Skala ändern ausschließlich die Darstellung.
Kameraperspektive, Ziehrichtungen und Zoom am Mauszeiger entsprechen dem
STL-Postprozessor. Unten rechts lassen sich die Fahrwege ein-/ausblenden und
zwischen **Alle** (bis zur gewählten Schicht) und **Einzeln** umschalten.
Z-Hops bleiben ihrer Druckschicht zugeordnet. Diese Ansichtsänderungen ändern
weder die Turmberechnung noch den exportierten Projektinhalt.
Die Vorschau bietet dieselben Bedienelemente zum Zurücksetzen und zur
Transparenz der unteren Schichten. Die Layerauswahl aktiviert Transparenz;
Zurücksetzen zeigt wieder das vollständige Modell in der Ausgangsansicht.

Die obere Projektübersicht enthält die Druckplattenauswahl. **Druckplatte
vorbereiten** erscheint, solange der Ausgangsslice fehlt. Danach wird **Turm
generieren** angeboten. Einstellungen ändern verwirft das davon abhängige
Turmergebnis. Über **Zurück zur Dateiübergabe** wird die Eingabeseite geöffnet.
Manueller Editor und Postprozessor bleiben Bestandteile des STL-Ablaufs.
Ein Quellen- oder Plattenwechsel verwirft die abhängigen nativen Ergebnisse.
Abbruch und Dateiauswahl bleiben von verspäteten Hintergrundresultaten getrennt.

Unvollständige Geometriecontainer werden mit konkretem Grund und einer kurzen
Speicheranleitung zurückgewiesen. Im Slicer **Datei → Projekt speichern als …**
verwenden und eine neue native Projektdatei erzeugen. Die Versionsangaben in der
Anleitung bezeichnen den jeweiligen Anleitungsstand.

## Versionszuordnung

Die native Windows-Anbindung verwendet diese Engine-Einstiege:

| Slicer | Versionsstand | Native Projektkonfiguration |
|---|---|---|
| Anycubic Slicer Next | 2.0.0.3 | eingebettete JSON- und Objektkonfiguration der Bambu-Familie; ältere Projekte können BambuStudio als Erzeugerkennung tragen |
| Bambu Studio | 02.08.02.61 | eingebettete JSON-, Objekt- und Plattenkonfiguration |
| PrusaSlicer | 2.9.6 | `Slic3r_PE.config`, Objekt-/Volumen- und Bereichskonfiguration |
| OrcaSlicer | Engine 2.4.2 im Windows-Paket 2.4.3.0 | eingebettete JSON-, Objekt- und Plattenkonfiguration |

Eine andere Erzeugerversion ist nicht allein ein Ablehnungsgrund. Erforderliche
Erweiterungen, Projektinformationen und die tatsächliche Interpretierbarkeit
durch die installierte Engine sind maßgeblich. Gleichnamige lokale Benutzerprofile
ersetzen keine eingebetteten Werte. Fehlende Installationen, beschädigte Archive,
unvollständige Projekte und nicht unterstützte Abläufe werden getrennt behandelt.

## Datenfluss und unveränderliche Basis

`native_project.archive` prüft ZIP-Struktur, Ressourcenlimits, Prüfsummen aller
Einträge und interne Beziehungen. Externe Beziehungen, Pfadausbrüche, Aliasnamen,
verknüpfte ZIP-Einträge sowie DTDs und XML-Entitäten werden abgewiesen.
Eingebettete Nachbearbeitungsskripte dürfen nicht ausgeführt werden.

`NativeProjectSession` arbeitet mit einer konsistent erfassten, überprüften
Eingangskopie. Modelle werden weder aus gespeicherten Quellenpfaden nachgeladen
noch über STL rekonstruiert. Originale Mesh-Dokumente und Dreiecksreihenfolgen
bleiben erhalten; dadurch bleiben native Bauteil- und Zeichnungszuordnungen
an ihren ursprünglichen Geometriedaten gebunden. Komponenten, Einheiten,
vollständige Transformationen und Instanzen werden im Projektkontext abgebildet.
Die native Einheitenauflösung skaliert Meshkoordinaten in Millimeter;
Komponenten- und Instanztranslationen bleiben entsprechend den Engine-Lesern
bereits in Millimetern. Auch ergänzte Turmressourcen verwenden diese Auflösung.

Analyse und Ergebnisbindung umfassen Eingangsfingerabdruck, Plattenauswahl,
eingebettete Werte, Optionen sowie die Bytes von Launcher, Engine-DLL und eigenem
Starthelfer. Eine externe Quellenänderung wird gemeldet; weiterverarbeitet wird
die bereits importierte Momentaufnahme. Ein Ergebnis mit geänderter Engine,
verändertem G-Code oder verändertem zugehörigem Projekt wird nicht exportiert.

## Kalibrierung und Export

Der Ausgangsslice entsteht neu aus der unveränderten Projektbasis. Bereits
eingebetteter G-Code ersetzt diese Vorbereitung nicht. `append_tower` ergänzt
eigene Ressourcen und native Einstellungen ausschließlich für den Kühlturm.
Jede Iteration beginnt mit derselben kontrollierten Basis. Nach der Vorbereitung
vermisst die getrennte Kalibrierung den Turm alleine. Die nativen Originalinstanzen
der gewählten Platte sind dazu ausschließlich in der temporären Ausführungskopie
vom Druck ausgeschlossen. Lassen sich die getrennten Bahnen oder Höhen nicht
eindeutig zuordnen, fährt die Berechnung mit der gemeinsamen Kalibrierung fort.
Die getrennte Phase kann durch ein Limit von 0 übersprungen werden. Die gemeinsame
Phase passt den Turm an die gemessenen Zeiten der vollständigen Platte an.
Die Vorschau aktualisiert sich nach jedem geprüften Slice. Die Rückkopplung
vergrößert oder verkleinert den Turm, bis die gemessene Mindest-Layerzeit in der
gewählten Toleranz liegt. An einer Geometrie-, Durchlauf- oder Laufzeitgrenze
bleibt das gemeinsam geprüfte Ergebnis mit dem kleinsten absoluten Abstand zur
Zielzeit erhalten. Die Generierung zeigt dessen erreichte Mindest-Layerzeit
und Durchlaufnummer an.

Ab dem ersten vollständig geprüften gemeinsamen Slice kann das beste bisherige
Ergebnis vorläufig übernommen und exportiert werden. Beim Fortsetzen auf derselben
Druckplatte mit denselben Einstellungen bleiben alle geprüften Durchläufe in der
Auswahl. Die Kalibrierung beginnt beim ersten noch offenen gemeinsamen Slice
und verwendet die Rückkopplung aus dem letzten geprüften Durchlauf. Das Zeitlimit
zählt nur die aktive Kalibrierung. Der Exportbericht benennt den exportierten
Durchlauf und kennzeichnet eine vorläufige Übernahme.

Ein Turm erhält immer eigene Einstellungen ohne Brim; der automatisch
berechnete Standfuß sorgt für seine Auflagefläche. Der Brim der Originalobjekte
bleibt von dieser Einstellung unberührt. Verwenden die Modelle der ausgewählten
Platte ein einziges Filament, erhält auch der Turm dieses Filament. Die Position
wird anhand der tatsächlich belegten Druckfläche möglichst nah am Modell
gesucht. Wipe-/Prime-Tower einschließlich ihrer Innenfläche, Objektabstände,
Bettkontur und Sperrflächen werden berücksichtigt. Die Platzsuche wird an den
jeweiligen Turmdurchmesser angepasst.

**Auto** übernimmt beim Aufweitungswinkel den eingebetteten Stützwinkel. Das
gesperrte Eingabefeld zeigt den wirksamen Winkel und bewahrt den manuellen Wert.
Der Verjüngungswinkel besitzt eine eigene, standardmäßig aktive Auto-Checkbox.
Die Stützen des Turms sind standardmäßig deaktiviert. Die Anzahl der oberen und
unteren Vollschichten lässt sich jeweils von 0 bis 5 einstellen und steht
standardmäßig auf 1. **Auto** übernimmt die jeweilige Schichtzahl einschließlich
größerer Profilwerte. Beim konkaven Standfuß sorgt ein eigener Höhenbereich mit
100 % Fülldichte für Auflage, wo sie für die einwärts versetzten Wände nötig ist.
Die gewählte Bodenschichtzahl gilt unabhängig davon. Oberhalb des Standfußes
gilt wieder die Füllung des Prozessprofils. Die
gemeinsamen Geometrieregeln stehen unter [Turmgeometrie](tower_geometry.md).
Bei deaktivierter 100-%-Turmfüllung warnt das Feld **Minimaler Turmdurchmesser**,
wenn Wandlinien und Füllregeln des eingebetteten Profils einen massiven
Querschnitt erwarten lassen. Wenn möglich zeigt es einen größeren Durchmesser an.

Konstante Schichten übernehmen die eingebetteten Höhen unmittelbar. Für eine
abweichende Schichtfolge wird ein natives Höhenprofil des Turms ergänzt.
Dadurch wird ein unnötiges adaptives Profil vermieden, das native Prime-Tower-
Prüfungen trotz gleicher Schichten stören könnte. Die tatsächlichen gemeinsamen
Schichten, Turmbahnen, Platzierung und Schichtzeiten werden anschließend geprüft.
Ein Iterationslimit oder nicht erreichter Zielwert bleibt als solcher sichtbar.

Der Turm übernimmt die passende eingebettete Höhenkurve des
ausgewählten Originalobjekts, wenn ihre Endhöhe übereinstimmt. Dadurch bleiben
auch interpolierte Verläufe mit dem nativen Kurvenvergleich des Wipe-/Prime-Towers
vereinbar; ursprüngliche Profilzeilen werden unverändert erhalten.
Die Modelloberkante der Kurve bleibt auch dann erhalten, wenn die letzte
gerundete Druckschicht geringfügig darunter liegt.
Bei aktivem Wipe-/Prime-Tower erhält der Kühlturm außerdem die passenden
objekt- und bereichsbezogenen Schichthöhen. Andere Bereichsüberschreibungen,
etwa Wandzahl, Füllung oder Materialwechsel, bleiben auf die Originale begrenzt.

Unabhängig geplante Supporthöhen werden von den Modellschichten unterschieden.
Der Turm folgt der nativen Modellschichtfolge; zusätzliche reine Supportschichten
bleiben vollständig in der gemeinsamen Zeitbewertung enthalten. Die Rückkopplung
berücksichtigt auch geänderte Kühlung und Fahrzeiten des gemeinsamen Slices.

**Turm +1 Layer höher generieren (druck endet am Turm)** prüft die Turmbahnen der letzten regulären
Schicht. Es setzt eine Kappe mit Mindestdurchmesser in die Mitte oder an die
nächstgelegene ausreichend gefüllte Stelle. Bei fehlender Auflage folgt der
zusätzliche Layer der vorherigen Turmwand. Ein weiterer gemeinsamer Slice prüft
die Anzahl der zusätzlichen Schichten und die Auflage der neuen Bahnen.
Die Option erzeugt auch dann einen Turm, wenn die Ausgangsplatte die Zielzeit
bereits erreicht. Das exportierte 3MF enthält den geprüften Zusatzlayer.
Die zusätzliche Schicht bleibt in der Vorschau sichtbar und bei der gemeldeten
Mindest-Layerzeit unberücksichtigt. Der Slicer kann daher eine deutlich
kürzere Mindest-Layerzeit anzeigen.

Der Export enthält ein vollständiges natives 3MF mit den ursprünglichen Platten
und dem ergänzten Kühlturm. Veraltete Slice-/Vorschaueinträge werden entfernt.
Beim Anpassen interner Beziehungen bleiben die ursprünglichen XML-Namensräume
und unveränderte Beziehungen erhalten. Exporte werden atomar veröffentlicht;
geschützte Eingaben und Slicerverzeichnisse sind keine erlaubten Exportziele.
Alle Vorfahren eines Ausgabeziels werden während des Exports gegen Austausch
gesperrt. Für native Windows-App-Installationen werden die konkreten geschützten
Installationsordner mit lesendem Zugriff gesperrt; dafür werden keine zusätzlichen
Rechte auf systemverwaltete übergeordnete Verzeichnisse angefordert.

**Projekt exportieren** schreibt einen eigenen Laufordner unter dem Ziel
**Projekte (3MF)**. Standardmäßig heißt dieses Ziel `exports_3mf_projects`;
es lässt sich unter **Allgemeine Einstellungen** unabhängig von den STL-Zielen
ändern. Jeder Lauf enthält `Projekt_mit_Turm.3mf`, einen technischen JSON-Bericht
und einen lesbaren Projektbericht. Die Footer-Buttons öffnen den Exportordner,
den letzten vollständigen Export oder dessen Bericht. Der Bericht öffnet sich
nach dem Export und lässt sich im selben Dialog wie im STL-Modus erneut aufrufen.
Bei Fehler oder Abbruch
wird nur der unvollständige neue Lauf entfernt; vorhandene Exporte bleiben erhalten.

Ein eigener Herkunftsnachweis bindet die ergänzten Inhalte und gesicherten
Originaleinträge über Inhaltsfingerabdrücke. Beim erneuten Import eines
unveränderten eigenen Exports wird die genaue Projektbasis wiederhergestellt,
damit sich Kühltürme nicht vervielfachen. Veränderte eigene Exporte werden nicht
ungeprüft auf diese Weise zurückgesetzt. Objektnamen sind kein Herkunftsnachweis.

Native Höhenbereichsdateien enthalten für jeden Bereich eine Schichthöhe,
auch wenn seine sichtbare Änderung nur Wandzahl oder Füllung betrifft. Fehlt
diese vom nativen Leser benötigte Angabe, wird der Bereich vor dem Slicerstart
als unvollständig gemeldet.

## Technische Trennung und Grenzen

Die Fachlogik liegt unter `native_project`, die eigenen Masken, Controller,
Vorschau und Diagramme unter `gui/native_project`. Anpassbare STL- und
3MF-Bausteine besitzen getrennte Implementierungen und Zustände. Gemeinsam bleiben
allgemeine Infrastruktur wie Prozessüberwachung, gesicherte Dateioperationen
und die G-Code-Zeitanalyse.

Der automatische Kühlturm benötigt gemeinsamen schichtweisen Druck. Sequentieller
Objektdruck wird vor der Berechnung zurückgewiesen. Die Ausgabe ist eine
slicerbasierte Simulation und keine physische Druckprüfung.

PrusaSlicer 2.9.6 erwartet beim nativen Slice eine absolute erste Schichthöhe.
Ältere Projektwerte wie `150%` können von seinem Konfigurationsleser eingelesen,
vom Slice aber als zu große Schichthöhe zurückgewiesen werden. In diesem Fall
die erste Schichthöhe im Slicer in Millimetern angeben und das Projekt neu speichern.

Der Windows-Originalschutz einschließlich Laufzeitinitialisierung und
Kindprozessen steht unter [Slicer-Prozesse](slicer_qprocess_compatibility.md).
Lizenz- und Distributionsbedingungen der Engines und ihrer direkten CLI-Anbindung
stehen unter [Dependencies](dependencies.md).
