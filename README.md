# Kühlturm-Generator

Die Anwendung analysiert die Layerzeiten eines Referenz-G-Codes und erzeugt
einen hohlen, wasserdichten Kühlturm als binäre STL. Außen- und Innenkontur
folgen einem adaptiv abgetasteten, C²-stetigen Quintic-Spline. Zunächst wächst
der Außenradius bei gleichbleibender Mindestwand; erst am regulären
Maximalradius wird die Wand fließend dicker. Hohlraum, Winkelgrenzen,
Maximalradius und Maximalwandstärke bleiben dabei geschützt.

## Installation unter Windows

Im VS-Code-Terminal im Projektordner:

```powershell
py -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
```

## GUI starten

Für den normalen Windows-Start `start_gui.vbs` doppelklicken. Dieser Launcher
verwendet `.venv\Scripts\pythonw.exe`; dadurch bleibt ausschließlich das
Programmfenster sichtbar und es wird kein Konsolenfenster offengehalten.
`start_gui.pyw` ist der zugehörige GUI-Einstiegspunkt. `start_gui.bat` bleibt
als kompatibler Aufruf erhalten und delegiert ebenfalls an den unsichtbaren
Launcher.

Für Entwicklung und Diagnose kann die GUI weiterhin bewusst aus einer Konsole
gestartet werden:

```powershell
.\.venv\Scripts\Activate.ps1
python main.py
```

In der Oberfläche eine `.gcode`-Datei ablegen oder auswählen, Ziel-Layerzeit
und Geometrie einstellen, die Vorschau erstellen und den geprüften Kühlturm
anschließend exportieren.

Die gewünschte Layerzeit wird in der GUI im Abschnitt
`2. Zielzeit und Berechnung` unter `Ziel-Layerzeit [s]` eingestellt.

### Installierte Version und automatische Updates

Die veröffentlichte Windows-Version wird über den per-user Installer
`SacrificialTowerSetup-x.x.x.exe` installiert. Sie prüft einen öffentlichen,
kostenlosen GitHub-Update-Kanal im Hintergrund. Ist dort eine numerisch höhere
Version verfügbar, erscheint rechts neben der aktuellen Versionsnummer der
Button `Aktualisieren`. Ein Klick lädt den Installer direkt herunter und prüft
zuerst das eingebettete Ed25519-Vertrauensmodell des signierten Manifests,
danach Dateigröße und SHA-256. Erst dann wird das Update still installiert und
das Programm neu gestartet. Endnutzer benötigen dafür weder Git noch
GitHub-Zugangsdaten.

Veränderliche Einstellungen, Logs und Standardausgaben liegen getrennt vom
Programm unter
`%LOCALAPPDATA%\RodeProjects\SacrificialTower\<Instanz>\`. Python-Entwicklung,
eigenständige Installation und ein späterer Store-Build verwenden getrennte
Instanzen. Aufbau, sichere Legacy-Übernahme und Schema-Migration sind in
[`docs/settings_migrations.md`](docs/settings_migrations.md) beschrieben.

Build und Veröffentlichung des Installers sind in
[`docs/update_channel.md`](docs/update_channel.md) dokumentiert.

## Entwicklung und Wartung

Die Paketverantwortungen, der einheitliche Thread-Lebenszyklus und die Regeln
für künftige Erweiterungen sind in
[`docs/architecture.md`](docs/architecture.md) beschrieben.

Nach der Auswahl wird der G-Code sofort im Hintergrund analysiert. Änderungen
der Ziel-Layerzeit werden anschließend ohne erneutes Einlesen live bewertet.
Wenn kein Layer die Zielzeit unterschreitet, zeigt die Oberfläche
`Kein Kühlturm erforderlich` an und erzeugt weder eine STL noch einen leeren
Laufordner. Wird ein Turm benötigt, endet er beim letzten Layer mit Zeitdefizit
zuzüglich eines Abschlusslayers, statt unnötig bis zur vollständigen
Modellhöhe weiterzulaufen.

Nach der Analyse werden auch die eingestellten Geometriegrenzen live geprüft.
Kann die gewünschte Zeit beispielsweise wegen des Aufweitungswinkels, des
Maximalradius oder der Maximalwandstärke nicht erreicht werden, erhält jedes
betroffene Feld einen roten Rahmen und einen konkreten Hinweis direkt unter der
Eingabe. Nach einer wirksamen Korrektur verschwinden diese Markierungen wieder.
Die Generierung bleibt bis dahin deaktiviert.

Jeder numerische Wert, der Standfußmodus und der Ausgabeordner besitzen einen
eigenen `↺`-Button. Er setzt ausschließlich die betreffende Einstellung auf
den zentral in `config/default_settings.json` hinterlegten Standard zurück.
Der allgemeine Button `Alle Standardwerte` setzt weiterhin die gesamte
Oberfläche zurück.

Der Standfuß ist standardmäßig mindestens 20 mm breit und wird ansonsten mit
dem Faktor `0,2 × vollständige G-Code-Objekthöhe` berechnet. Alternativ lässt sich
ein manueller Außendurchmesser ab 20 mm wählen. Aufweitungs- und
Verjüngungswinkel werden getrennt relativ zur vertikalen Z-Achse eingestellt;
beide Standardwerte betragen 50°.

## Kommandozeile

```powershell
.\.venv\Scripts\Activate.ps1
python cli_main.py `
  --gcode ".\input\rabe_koerper_18cm.gcode" `
  --target-time 10 `
  --minimum-radius 5 `
  --maximum-radius 40 `
  --minimum-wall 0.8 `
  --maximum-wall 4.2 `
  --wall-path-width 0.42 `
  --minimum-inner-radius 2 `
  --expansion-angle 50 `
  --contraction-angle 50 `
  --output-root ".\output"
```

Ohne weitere Option wird die Standfußbreite automatisch berechnet. Mit
`--manual-base-width 30` wird stattdessen beispielsweise ein manueller
Außendurchmesser von 30 mm verwendet.

Jeder Lauf landet kollisionssicher unter
`output/runs/Datum_Uhrzeit_GCodeName/`. Dort liegen STL, Layeranalyse,
Turmprofil, tatsächlich verwendete Einstellungen, Zusammenfassung und Log in
getrennten Unterordnern.

Auch die CLI behandelt `kein Kühlturm erforderlich` als erfolgreichen Lauf
ohne STL-Ausgabe und nennt die Begründung ausdrücklich.

Die Layerzeitanalyse berücksichtigt die im G-Code gesetzte
Bewegungsdynamik. Unterstützt werden die achsbezogenen Maximalwerte aus
`M201`, die Druck-, Travel- und Retract-Beschleunigungen aus `M204`,
Classic-Jerk-Grenzen aus `M205` sowie Klippers `SET_VELOCITY_LIMIT` mit
`ACCEL` und `SQUARE_CORNER_VELOCITY`. Ein begrenzter Look-ahead berechnet für
aufeinanderfolgende Bewegungen Einfahr-, Spitzen- und Ausfahrgeschwindigkeit
und verwendet abhängig von Weg, Sollgeschwindigkeit und Beschleunigung ein
dreieckiges oder trapezförmiges Geschwindigkeitsprofil. Enthält ein G-Code
keine Beschleunigungsangaben, bleibt für diese Bewegungen die bisherige
konstante Sollgeschwindigkeitsrechnung aktiv, statt unbekannte Maschinenwerte
zu erfinden.

Die berechnete Zusatzzeit ist eine auf dem Referenz-G-Code beruhende Näherung.
Die tatsächlich entstehende Zeit hängt zusätzlich von den später verwendeten
Slicer-, Material- und Druckerprofilen ab. Der Sicherheitsfaktor verbessert
die Reserve, ist aber kein Ersatz für den in den folgenden Phasen geplanten
slicerbasierten Zeitnachweis.

## Phase 13: Metadaten und belastbare Zeitnachweise

Die G-Code-Analyse erfasst zusätzlich zur Layerzeit nun versionierte Slicer-
und Profilmetadaten. Jeder Wert behält seine Herkunft, beispielsweise
Header-Kommentar, eingebetteter Konfigurationsblock oder Maschinenbefehl.
Explizite Angaben werden von technischen Signaturen getrennt; Marlin- oder
Klipper-Befehle allein werden weder als bestimmter Slicer noch als bestimmtes
Druckermodell ausgegeben.

Timing-Ergebnisse unterscheiden ausdrücklich zwischen Quell-G-Code,
analytischer Kühlturmschätzung, späterem Slicer-Kalibrierungslauf und finalem
Gesamt-G-Code. Generierungsläufe enthalten den technischen Bericht
`analysis/gcode_metadata.json` mit Schema-Version, Quellen, Timing-Evidenz und
einem Fingerabdruck der zeitkritischen effektiven Profilwerte.

Der beobachtete Fall „15 s eingestellt, ungefähr 11 s im Slicer erreicht“ ist
unter `tests/references/phase13_15s_regression.json` als fachliche Regression
dokumentiert. Solange ein belegtes Zeitdefizit fortbesteht, darf die
Zeitkapazität des Turms in einem nachfolgenden Layer nicht reduziert werden.

## Phase 14: Automatische Slicer-Erkennung

Die Anwendung erkennt installierte Slicer unter Windows über begrenzte,
nachvollziehbare Quellen: Uninstall-Einträge der System- und Benutzer-Registry,
32-/64-Bit-Ansichten, `App Paths`, bekannte Herstellerverzeichnisse,
Startmenü-Verknüpfungen und bereits manuell bestätigte Pfade. Es findet kein
unkontrollierter Scan aller Laufwerke statt. Jeder Kandidat wird anhand von
Dateiversionsinformationen oder einem kurzen, ungefährlichen Versions-/Hilfe-
Aufruf verifiziert, bevor er in der GUI erscheint.

Mehrere Produkte und Versionen werden einzeln angeboten. Die Vorauswahl
berücksichtigt die im Quell-G-Code belegte Slicerfamilie und Version; der
Benutzer kann sie jederzeit ändern oder über `EXE auswählen …` eine portable
Installation einmalig bestätigen. Fehlt eine Information, zeigt die GUI nur
einen neutralen Status und erfindet weder Drucker- noch Profilnamen.

Anycubic Slicer Next ist als erster real geprüfter Volladapter integriert.
OrcaSlicer und Bambu Studio verwenden nur ihre nachweislich gemeinsame
technische Basis. PrusaSlicer besitzt eine eigene INI-Vererbungs- und CLI-
Behandlung, Cura eine getrennte Definition-/CuraEngine-Anbindung. ideaMaker
und Simplify3D werden derzeit lediglich erkannt und entsprechend als
`nur erkannt` gekennzeichnet.

Alle Hintergrundaufrufe verwenden eine Argumentliste ohne Shell, ein isoliertes
temporäres Arbeitsverzeichnis, Timeout, Prozessbaum-Abbruch sowie Exitcode- und
Ausgabedateiprüfung. Temporäre Arbeitsdaten werden bereinigt; bei Fehlern bleibt
ein technischer JSON-Diagnosebericht erhalten. System- und Benutzerprofile
werden ausschließlich gelesen und niemals verändert.

## Phase 15: Belastbare Profilzuordnung

Nach G-Code-Analyse und Slicerauswahl inventarisiert die Anwendung die
zugänglichen Maschinen-, Prozess- und Filamentprofile getrennt. Mehrstufige
Vererbungen werden zu effektiven Werten aufgelöst; Düsengröße, Technologie,
G-Code-Dialekt, Bauraum, Extruderzahl und Profilversion wirken als harte
Ausschlusskriterien. Profilnamen dienen nur als schwacher Zusatzhinweis.

Enthält der Quell-G-Code eine ausreichend vollständige Konfiguration, wird
daraus bevorzugt ein isoliertes temporäres Arbeitsprofil erstellt. Es gilt erst
nach einem erfolgreichen Probeslice als rekonstruiert. System- und
Benutzerprofile bleiben unverändert. Weniger eindeutige, aber kompatible
Kombinationen zeigt die GUI in drei getrennten Auswahlfeldern an und verlangt
eine einmalige Bestätigung. Die gespeicherte Zuordnung wird automatisch
ungültig, sobald sich Slicerfamilie, kompatibler Versionsbereich,
Quellfingerabdruck, kritische Zeitwerte oder Profil-IDs ändern.

Die GUI bietet ausschließlich den STL-Export an. Ein Slicerwechsel oder eine
extern erkannte Profiländerung löst eine neue Zuordnung aus. Jeder erfolgreiche
GUI-Lauf schreibt den technischen Bericht `analysis/profile_match.json`; die
Hauptoberfläche zeigt weiterhin nur neutrale, tatsächlich belegte Angaben.

## Phase 16: slicerbasierte Kalibrierung

Die analytische Turmform kann jetzt über `GenerationService.calibrate(...)`
mit den tatsächlich vom ausgewählten Slicer erzeugten Bahnen nachgeregelt
werden. Für jeden Durchlauf wird ausschließlich in einem temporären
Arbeitsverzeichnis eine Kandidaten-STL erzeugt. Die beschleunigungsabhängige
G-Code-Analyse ermittelt anschließend die reale Zusatzzeit je Layer. Solange
ein Restdefizit besteht, darf das Profil an dieser Stelle nicht verjüngt
werden; Außenradius, Wandstärke, Splines und Winkelgrenzen werden in ihrer
bisherigen Reihenfolge erneut angewendet.

Exportiert wird ausschließlich die konvergierte STL-Geometrie als belastbarere
Prognose. Spätere Änderungen im Slicer können deren Wirkung weiterhin
verändern. Eine direkte G-Code-Ausgabe ist derzeit nicht Bestandteil der
Benutzeroberfläche; die Entwicklung konzentriert sich auf einen möglichst
präzisen und weiterhin im Slicer bearbeitbaren STL-Kühlturm.

Kühlungsbedingte Mindestlayerzeit-Verlangsamung wird nur in einer temporären
Kalibrierungskopie des effektiven Profils neutralisiert. Quellprofile bleiben
unverändert. Ein Export entsteht erst nach Konvergenz und bestandener Mesh-,
Profil-, Druckbett-, Modalzustands- und Zeitprüfung. Details einschließlich
Iterationsergebnissen, Hashwerten und Abbruchursachen stehen im erzeugten
`calibration_report.json`.

## Phase 18: UI-Update und Verbesserungen

Die UI-Überarbeitung seit Phase 17 wird als Phase 18 geführt. Einstellkarten
stehen responsiv in einer oder zwei Spalten; zusammengehörige Geometriekarten
sind gleich hoch, unabhängig einklappbare Karten behalten ihre natürliche
Höhe und alle Inhalte beginnen oben. Beschriftungen bleiben links, während die
gleich großen Editoren und Reset-Schaltflächen rechts ausgerichtet sind.

Der erste erfolgreiche Abschluss der G-Code-Analyse und Slicererkennung
animiert Erfolgszustand und automatisches Einklappen für 1.000 ms. Alle
weiteren Animationen verwenden 250 ms und eine spätere manuelle Kartenwahl
wird nicht überschrieben. Referenz-G-Code kann erneut eingelesen werden, die
eingebettete Konfiguration liegt geschlossen im Slicer-Bereich und automatisch
erkannte Slicer werden direkt neben dem Titel „Slicer“ gekennzeichnet.

Hover-Zustände, Dropdown-Chevrons, gleichmäßige Prognoseabstände, eine dezente
Trennung zum fixen Fußbereich und die invertierte Rotation per linker
Maustaste vervollständigen die Überarbeitung. Hinweise werden als kompakte,
fenstergebundene Popover dargestellt und können weder rechts noch links aus
dem jeweiligen Fenster ragen. Icon-Hinweise erscheinen ausschließlich während
des Hoverns. Der leere G-Code-Bereich blendet Dateidaten und Folgeaktionen aus,
behält aber seine Höhe; während der Analyse erscheinen die Dateidaten und nach
erfolgreichem Abschluss zusätzlich die Aktionen zum Neueinlesen und Entfernen.
Der Startzustand erklärt außerdem den Weg vom Slicer-Objekt zum importierbaren
G-Code. Das anfängliche Pfeilsymbol neben „Referenz-G-Code“ wird mit eigener
Renderbreite und deutlich größerer Schrift als die nachfolgenden Statussymbole
dargestellt.

Die einklappbare Prognose besitzt einen leichten lila Kartenhintergrund sowie
getrennte Spalten für Bezeichnung, Wert und Hinweise. Ihr kompakter gelber
Genauigkeitshinweis beginnt direkt unter dem Kartenkopf und wächst nur bis zur
tatsächlich benötigten Höhe.
Solange nur analytisch geschätzt wird, warnt sie vor der geringen Genauigkeit
und bietet bei einem verwendbaren Slicer eine einmalige, stets auf fünf
Durchläufe festgelegte Slicer-Schätzung an. Hinweistext und lila Aktionsbutton
bilden dabei zwei bündige Zeilen derselben Box. Analytische Schätzungen sind
orange, Slicer-Schätzungen lila gekennzeichnet. Das Vorschaufenster startet in einer
  um genau einen Mausradschritt herausgezoomten Seitenansicht, enthält einen eigenen Export-Button, wird
  vor dem Anzeigen zuverlässig normalisiert und nach Möglichkeit rechts neben
  dem Hauptfenster angeordnet. Exporthinweise wachsen nur bis zur tatsächlich
  benötigten Texthöhe.

Abmessungen, Standfuß und Überhänge sind in der gemeinsamen Karte
„Turmgeometrie“ fachlich getrennt. In der breiten Ansicht stehen die
Abmessungen links; Standfuß, Überhänge sowie „Auflösung und Zeitfenster“
bilden eigenständige Bereiche in der rechten Spalte. Eine senkrechte, dezente
Linie trennt beide Spalten. In der einspaltigen Darstellung werden sie
untereinander angeordnet und die Trennlinie verschwindet. Nur die
Teilüberschriften sind leicht grau hinterlegt; ihre Inhalte bleiben weiß und
ohne zusätzlichen Kartenrahmen. Jede geöffnete
Karte besitzt zusätzlich eine
noch dezentere Trennlinie zwischen Kopf und Inhalt. Die automatische
Standfußbreite ist wieder umschaltbar; ihr manueller Reset erscheint nur im
manuellen Modus, verändert beim Hover weder Breite noch Textposition und alle
Reset-Schaltflächen sind bei Standardwerten deaktiviert.
Der Ausgabebereich hält beim Animieren seinen Kartenkopf an der Ausgangsposition,
wächst ausschließlich nach unten und wird erst nach abgeschlossener Animation
vollständig mit Sicherheitsabstand in den sichtbaren Scrollbereich gebracht.
Seine verschachtelten Inhalte bestimmen dabei explizit Karten- und Scrollhöhe;
mehrfaches Ein- und Ausklappen hinterlässt weder abgeschnittene Inhalte noch
einen veralteten Scrollbereich.

In der einspaltigen Hauptansicht steht die Prognose direkt unter dem Slicer
und vor „Kühlzeit und Qualität“. In der breiten Ansicht bleiben Kühlzeit und
Prognose als linke und rechte Karte derselben Zeile angeordnet. Fehler-,
Warn- und Informationshinweise im fixierten Footer starten als eingeklappte
Dropdowns. Je aktiver Hinweisart entsteht eine gleich breite Spalte; bei
Platzmangel scrollt jede Spalte unabhängig, während die Aktionsbuttons
sichtbar bleiben.

Sämtliche sichtbaren Validierungstexte werden deutsch ausgegeben und die drei
Hinweisarten verwenden einheitliche Typografie und Abstände. Fehler markieren
nur noch das zuletzt geänderte auslösende Feld. Direkt unter einem Wert steht
nur die kurze Fehlerursache ohne Layerangaben; Details und Lösungswege stehen
im roten Fußbereich. Angaben zu betroffenen Layern erscheinen – abgesehen von
den dafür vorgesehenen Prognosewerten – ausschließlich in diesem fixierten
Fußbereich. Erreichte Grenzen werden eindeutig als minimal oder maximal
möglich bezeichnet. Dort korrigiert die erste Lösung stets den auslösenden
Wert, und mehr als drei Vorschläge werden platzsparend aufklappbar
zusammengefasst. Der maximale Aufweitungswinkel ist in Eingabe, Fachlogik und
Lösungsvorschlägen auf 70° begrenzt; ab 51° warnt die Oberfläche vor den
erhöhten Anforderungen an die Druckerkalibrierung. Kompakte Fehler-Badges
verändern die Kartenkopfhöhe nicht. Die Vorschauqualität verwendet feste
Stufen mit einem, drei oder fünf Slicer-Durchläufen; der Export verwendet
immer fünf. Während eine Vorschau aufgebaut wird, sind beide Vorschau-Aktionen
gesperrt und mit „Vorschau wird erstellt...“ beschriftet. Die drei
Qualitätsstufen sind als obere Einstellzeile direkt mit dem lila
Vorschaubutton verbunden. Der fixe Fußbereich verwendet nur seine natürliche
Höhe bis maximal 280 px; längere Meldungen scrollen getrennt oberhalb der
dauerhaft sichtbaren Aktionszeile.

Die zuvor als Phase 18 geplante Gesamtintegration wird ab
  jetzt als Phase 19 geführt.

## Tests

```powershell
.\.venv\Scripts\Activate.ps1
$env:QT_QPA_PLATFORM="offscreen"
python -m unittest discover -s tests -v
```

Einzelne Phasen lassen sich beispielsweise so prüfen:

```powershell
python -m unittest tests.test_phase6 -v
python -m unittest tests.test_phase7 -v
python -m unittest tests.test_phase8 -v
python -m unittest tests.test_phase9 -v
python -m unittest tests.test_phase10 -v
python -m unittest tests.test_phase11 -v
python -m unittest tests.test_phase13 -v
python -m unittest tests.test_phase14 -v
python -m unittest tests.test_phase15 -v
python -m unittest tests.test_phase18 -v
python -m unittest tests.test_acceleration_timing -v
```

Der echte lokale Anycubic-Integrationslauf ist bewusst opt-in, damit normale
Regressionstests keine externen Programme starten:

```powershell
$env:COOLING_TOWER_RUN_REAL_SLICER_TESTS="1"
python -m unittest tests.test_phase14.Phase14RealAnycubicIntegrationTest -v
python -m unittest tests.test_phase15.Phase15RealAnycubicProfileTest -v
```

## Legacy-Ausgaben migrieren

Das Migrationsskript verschiebt nur flache Altdateien und überschreibt keine
vorhandene Datei:

```powershell
python scripts\migrate_output_structure.py --output-root .\output
```

Im aktuellen Projekt wurde die Phase-8-Migration bereits ausgeführt. Der
Bericht liegt unter `output/migrated_legacy/logs/`.

## Anycubic-Slicer-Nachweis

Das reale Referenz-STL wurde zusätzlich mit dem lokal installierten
AnycubicSlicerNext 1.4.1.2 geprüft und mit dem Systemprofil
`Anycubic Kobra 3 V2 0.4 nozzle`, dem 0,20-mm-Standardprozess und Anycubic PLA
vollständig geslict. Der Slicer meldet das STL als manifold und erzeugte 802
Schichten bis 160,4 mm. G-Code, Metadaten und der maschinenlesbare Prüfbericht
liegen im Referenz-Run unter `slicer_validation/`.

Nach der Umstellung der Konturkopplung und der automatischen Standfußbreite
wurde ein weiterer realer Lauf unter
`output/runs/20260714_123849_rabe_koerper_18cm/` geprüft. Der neue Standfuß ist
bei 160,4 mm G-Code-Objekthöhe 32,08 mm breit. Das wasserdichte STL mit 178.800
Dreiecken wurde vom gleichen realen Slicer erfolgreich in 803 Schichten bis
160,6 mm umgesetzt; G-Code, Metadaten und Prüfbericht liegen wieder im
Unterordner `slicer_validation/`.
