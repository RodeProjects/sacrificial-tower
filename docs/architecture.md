# Architektur und Wartungsleitlinien

## Inhalt

- [Laufzeitpfade](#laufzeitpfade)
- [Paketverantwortung](#paketverantwortung)
- [Gemeinsame Infrastruktur](#gemeinsame-infrastruktur)
- [Quellen- und Analysepipeline](#quellen--und-analysepipeline)
- [Thread-Lebenszyklus](#thread-lebenszyklus)
- [Externe Slicer-Prozesse](#externe-slicer-prozesse)
- [Diagnose und Stresstests](#diagnose-und-stresstests)
- [Regeln für Änderungen](#regeln-für-änderungen)
- [Verantwortlichkeiten nach dem Wartbarkeitsumbau September 2026](#verantwortlichkeiten-nach-dem-wartbarkeitsumbau-september-2026)
- [Grenzen und nächste größere Strukturänderungen](#grenzen-und-nächste-größere-strukturänderungen)


## Laufzeitpfade

Die Anwendung besitzt zwei bewusst getrennte Einstiegspunkte:

- `main.py` beziehungsweise `start_gui.pyw` startet die Windows-Oberfläche.
- `cli_main.py` startet die Kommandozeile.

Beide verwenden die Fachlogik unter `src/cooling_tower`. Die GUI erzeugt
Ausgaben ausschließlich über den Vorschau-/Exportpfad. Der CLI-Dienst
`GenerationService` bleibt der direkte, skriptfähige Generierungspfad.

Installations- und Ressourcenpfade sind schreibgeschützte Eingaben. Die GUI
speichert Konfiguration, Logs und Standardausgaben in einem getrennten,
beschreibbaren AppData-Instanzordner. Python-Entwicklung, eigenständiger
Installer und späterer Store-Build verwenden unterschiedliche Instanzen;
gezielte parallele Tests können eine eigene Instanz-ID setzen. Details und die
nicht überschreibende Legacy-Übernahme stehen in
`docs/settings_migrations.md`.

## Paketverantwortung

- `gcode`: G-Code-Parsing und Zeitberechnung
- `models`: unveränderliche fachliche Datenmodelle
- `tower`: Profil-, Standfuß- und Mesh-Berechnung
- `slicers`: Erkennung, Profilinventar und abgesicherte Slicer-Aufrufe
- `calibration`: slicerbasierte Iteration und G-Code-Auswertung
- `preview`: Vorschauaufbau, Export und Berichte
- `services`: Anwendungsfälle für Quellenerkennung, STL-Prüfung, Pre-Slice,
  Analyse, Generierung und Ausgabe
- `gui`: Qt-Oberfläche und dünne Worker für lang laufende Anwendungsfälle
- `persistence`: versionierte, gesicherte und atomare Benutzerdaten

Abhängigkeiten sollen von der Oberfläche in Richtung Fachlogik verlaufen.
Fachmodule dürfen keine Qt-Abhängigkeit erhalten. Die bewusst
gekapselte Laufzeitausnahme ist das austauschbare Slicer-Transportbackend
`slicers.qprocess_backend`; Adapter, Prozessauftrag und fachliche Auswertung
bleiben Qt-unabhängig.

Die GUI orchestriert Slicer-Suche und Profiloperationen zusätzlich über
`slicers.operation_process` in begrenzten Hilfsprozessen. Diese Transportgrenze
verwendet den bestehenden Windows-Job-Object-Controller des QProcess-Backends,
ohne die Adapterlogik zu verändern. Zweck, Zeitlimits, Abbruch und Trennung von
der Dateiübergabe sind zentral in
[Slicer-Erkennung](slicer_detection_modules.md#laufzeitfreigabe-und-fehlergrenzen)
dokumentiert.

## Gemeinsame Infrastruktur

- Datei-Hashes werden über `cooling_tower.file_integrity.sha256_file`
  berechnet. Die Funktion liest große Dateien blockweise.
- GUI-Hintergrundaufgaben werden über
  `cooling_tower.gui.background_jobs.start_background_job` gestartet. Der
  Aufrufer verbindet zuvor nur die aufgabenspezifischen Signale.
- Änderbare Beschriftungen, Hilfetexte und Prognosezeilen liegen in
  `cooling_tower.gui.texts`, sofern sie von mehreren Aufbau- oder
  Aktualisierungspfaden verwendet werden.
- Standardwerte liegen in `config/default_settings.json`; persistierte
  Benutzereinstellungen, Slicer-Pfade und Profilzuordnungen werden gefiltert
  und über `VersionedJsonStore` schrittweise, gesichert und atomar migriert. Die
  verbindlichen Regeln für neue Einstellungs- und Profilschemata stehen in
  `docs/settings_migrations.md`.
- `slicer_settings.json` ordnet die letzten expliziten Maschinen-, Prozess- und
  Filamententscheidungen der stabilen Identität einer konkreten
  Slicerinstallation zu. Pfad und Profil-ID werden gemeinsam gespeichert;
  unauffindbare Rollen oder inkompatibel gewordene Pakete fallen auf das
  aktuelle Matching zurück.
- `config/distribution.json` ist unveränderliche Build-Metadaten. Der Kanal
  `standalone` darf den Sacrificial-Tower-Updater verwenden; der Kanal
  `microsoft-store` schaltet ihn zwingend ab.

## Quellen- und Analysepipeline

Die GUI besitzt einen einzigen quellenneutralen Einstieg. `SourceArtifact`
hält die unveränderte Benutzereingabe einschließlich Hash fest;
`PreparedAnalysisSource` hält getrennt davon den analysierten G-Code und seine
Herkunft. Die aktuelle GUI nimmt ausschließlich STL als Originalquelle an und
führt zuerst die strenge `StlValidationService`-Prüfung und die ausdrückliche
Profilbestätigung durch; danach überführt `SourcePreSliceService` die STL
isoliert in G-Code. Die separate CLI analysiert vorhandenen G-Code direkt.
Die gemeinsame Analyselogik liefert
`GCodeAnalysisSnapshot`; Turmprofil, Prognose, Vorschau, Kalibrierung und Export
enthalten keine STL-Sonderberechnung.

Die fachliche Zustandsmaschine unterscheidet Quelle, Validierung,
Slicererkennung, Profilzuordnung und optionalen Pre-Slice explizit. Zulässige
Übergänge werden zentral geprüft. Jeder Quellentausch erhöht die Request-ID,
bricht zugehörige Jobs ab und verwirft Analyse-, Bestätigungs-, Cache-,
Prognose- und Vorschauzustand. Später eintreffende Worker-Ergebnisse dürfen nur
bei identischer Request-ID übernommen werden.

`PreSliceCache` ist ein optionaler Beschleuniger, keine fachliche
Wahrheitsquelle. Sein vollständiger Schlüssel bindet Quelle, Slicer, Profile,
effektive Werte, Adapter und Parser. Jeder Treffer wird in einen neuen
temporären Arbeitsbereich kopiert, erneut gehasht, analysiert und gegen die
Bestätigung geprüft. Persistenz erfolgt schema-versioniert und atomar; ein
unsicherer, zukünftiger oder beschädigter Index wird ignoriert, aber nicht
überschrieben. Die vollständigen Regeln stehen in `docs/source_workflow.md`.

Benutzerquellen und sämtliche Slicerdateien sind unveränderliche Eingaben.
Temporäre Ausgaben, Profilkopien, Diagnose und Cache liegen außerhalb von
Quell- und Slicerverzeichnissen. Produktionscode darf dort niemals Dateien
anlegen, ändern, umbenennen oder entfernen. Orca-Familienadapter ergänzen
fehlende, katalogvererbte Profiltypen ausschließlich in kurzlebigen Kopien des
isolierten Slicer-Arbeitsbereichs. Bestätigung und Cache binden auch sämtliche
geerbten Basisprofile ein.

## Thread-Lebenszyklus

Für sämtliche Hintergrundaufgaben gelten diese überprüfbaren Invarianten:

1. Jeder Worker und sein `QThread` haben genau einen Besitzer, den
   `BackgroundJobManager` im GUI-Thread.
2. Starke Worker- und Thread-Referenzen werden erst nach dem vollständigen
   nativen Threadende entfernt.
3. `QObject`, `QTimer` und `QProcess` werden ausschließlich in ihrem
   zugehörigen Thread erzeugt und zerstört.
4. Abbruchanforderungen über `cancel()` und das gemeinsame
   `threading.Event` sind mehrfach gefahrlos aufrufbar.
5. Kein laufender Thread wird mit `terminate()` gewaltsam zerstört.
6. Nur der GUI-Thread verändert Widgets.

Jeder GUI-Worker besitzt `run()`, genau ein eindeutiges `finished`-Signal und
den gemeinsamen Cancel-Vertrag. Der `BackgroundJobManager` ist der einzige
produktive Erzeuger von `QThread`-Instanzen. Er führt jeden Auftrag durch die
feste Zustandsmaschine
`CREATED → STARTING → RUNNING → CANCEL_REQUESTED → WORKER_FINISHED →
THREAD_FINISHED → RELEASED`. Direkte Normalabschlüsse überspringen
`CANCEL_REQUESTED`, nicht aber die beiden beobachtbaren Abschlusszustände.
Unzulässige Übergänge werden im Entwicklungsbetrieb sofort diagnostiziert.

Das Hauptfenster hält keine Job-Dictionaries, Kompatibilitätsansichten oder
eigenen Worker-/Thread-Paare. Laufende Arbeiten werden ausschließlich über
`BackgroundJobManager.has_active()`, `active_jobs()` und `job_for_request()`
abgefragt. Dadurch bleibt der Manager auch für reine Statusabfragen die einzige
Wahrheitsquelle für Hintergrundarbeit.

Der Worker meldet zuerst seinen fachlichen Abschluss. Das beendet die
Thread-Ereignisschleife; `QThread.finished` plant die Löschung des Workers in
dessen Thread ein. Der Manager wartet anschließend auf das tatsächliche native
Threadende, entfernt erst dann beide starken Referenzen und meldet `RELEASED`.

Beim Schließen fordert der Manager alle Jobs idempotent zum Abbruch auf, setzt
zusätzlich `QThread.requestInterruption()` und wartet mit einem gemeinsamen,
begrenzten Timeout. Ein noch laufender Job bleibt bei Zeitüberschreitung
registriert; die Oberfläche verweigert den unsicheren Programmabschluss und
versucht niemals, den Thread gewaltsam freizugeben.

Verzögerte `singleShot`-Callbacks des Hauptfensters, des manuellen Controllers
und ihrer GUI-Widgets verwenden den jeweiligen `QObject` als Qt-Kontext.
Wird das Fenster nativ
gelöscht, verwirft Qt noch wartende Callbacks, bevor sie auf bereits gelöschte
Layout- oder Vorschauwidgets zugreifen können.

## Externe Slicer-Prozesse

`prepare_slice()`, Prozess-Runner und `finalize_slice()` bilden drei getrennte
Phasen. Das QProcess-Backend erzeugt Controller, QProcess und alle zugehörigen
Timer erst im ausführenden Worker-Thread. `cancel()` setzt aus dem GUI-Thread
ausschließlich das threadsichere Abbruch-Event; ein Timer im Prozess-Controller
übersetzt es in ein queued Signal. Nur dessen Slot darf `terminate()` oder
`kill()` am QProcess ausführen.

Der Anycubic-Adapter ergänzt ausschließlich in den materialisierten
Maschinenprofilkopien Kommentar-Marker und native Inline-Zeitplatzhalter.
`gcode/slicer_layer_times.py` liest die vom Slicer ausgegebenen kumulierten
Normalmodus-Zeiten und validiert ihre Vollständigkeit, Reihenfolge und Z-Höhen.
Die zentrale Analyse verwendet ihre Differenzen als maßgebliche Layer-Gesamtzeiten;
Bewegungskomponenten bleiben geometrische Schätzgrößen. Dadurch verwenden
Pre-Slice, gemeinsame Angleichung und Exportbewertung dieselbe Zeitquelle.
Parser-Version 17 verhindert die Wiederverwendung älterer Analyse- und
Pre-Slice-Ergebnisse ohne diese Zeitdaten. Nach einer G-Code-Integration sind
die Zeitstände der Eingabedateien ungültig. Slicerdateien werden nicht geändert.

Die gemeinsamen Bambu-Slices verwenden direkt das native 3MF des jeweiligen
Kandidaten mit dessen enthaltenen Einstellungen. Erneutes Laden von
Maschinen-/Prozess- oder Filamentprofilen entfällt dabei, damit die Angleichung
denselben Eingang verwendet wie das spätere Slicen des Exports.
Der Bambu-Export enthält den tatsächlich ausgewählten Turmkandidaten und die
Filamentwerte der gemeinsamen Slices. Leere native Einträge
`extruder_nozzle_stats` und `extruder_nozzle_stats_new` werden nur im eigenen
3MF weggelassen: Bambu initialisiert damit die Düsen aus dem Maschinenprofil
wie beim direkten Slice. Nichtleere Düsenkonfigurationen bleiben erhalten.
Die realen Integrationstests slicen das exportierte 3MF zusätzlich ohne die
Assembly-Datei und ohne Profilüberschreibungen; Geometrie, vollständige
Layerzahl und G-Code-Auswertung werden mit dem ausgewählten Kandidaten verglichen.
Dieser Vergleich ersetzt keine unabhängige Prüfung der nativen Bambu-Layerzeiten.
Die geprüfte Bambu-CLI 2.8.2.61 gibt native Gesamt- und Featurezeiten aus,
aber keine vollständige Layerzeitliste und keine Anycubic-Inline-Zeitstempel.
Ihre Layerzeiten werden deshalb weiterhin aus dem G-Code mit dem
Bambu-kompatiblen Bewegungsmodell ausgewertet. Die identische Auswertung von
Kandidat und erneut geslictem Export belegt deren Konsistenz; sie garantiert
keine absolute Identität mit Bambus internem Zeitmodell. Die ausschließliche
Übernahme nativer Bambu-Layerzeiten bleibt offen.

Ein lokaler Qt-Eventloop verarbeitet Prozess- und Ausgabesignale ohne
`waitForFinished()`, Shell-Aufruf oder Python-Lesethread. Der Runner kehrt erst
zurück, nachdem das finale Prozesssignal eingetroffen ist, beide Ausgabekanäle
vollständig ausgelesen, Diagnose- und Job-Object-Handles geschlossen, die
isolierte Umgebung entfernt und die QObjects im Eigentümer-Thread zerstört
wurden. Erst danach darf der übergeordnete Worker sein `finished`-Signal senden.

Unter Windows wird die konkrete Slicer-PID einem Job Object mit
`KILL_ON_JOB_CLOSE` zugeordnet. Kann Windows die Zuordnung nicht herstellen,
bleibt die konkrete PID-Baumaufnahme als diagnostizierter Fallback erhalten;
eine Namenssuche ist verboten. Standardausgabe und Standardfehler haben je
eine Speicherobergrenze. Bei Überschreitung bleibt der jeweilige Tail im
Ergebnis und die vollständigen Bytes werden in einer Diagnosedatei archiviert.
Backend-Schalter, Adaptermatrix und Doppelvalidierung sind in
`docs/slicer_qprocess_compatibility.md` beschrieben.

### Getrennte und gemeinsame Generierungsphase

Jede neue Generierung beginnt unabhängig von einer vorhandenen Vorschau mit
der unter „Max. getrennte Slices“ konfigurierten Anzahl getrennter Turm-Slices
(1–25, Standard 6). Der eingebettete Bereich „Generierung und
Vorschau“ verwendet `gui/generation_panel.py`; es öffnet sich kein separates
Generierungsfenster. Der Worker
meldet jeden vollständig ausgewerteten gemeinsamen Kandidaten als unveränderlichen
`JointSliceProgress`; ausschließlich der GUI-Thread aktualisiert Zähler und
intern die Werte des bisher besten vollständig ausgewerteten Kandidaten.
Die getrennten Slices bilden die Vorbereitungsphase. Währenddessen zeigt der
eingebettete Bereich ausschließlich „Turmgenerierung wird vorbereitet...“, einen
über alle konfigurierten getrennten Slices fortlaufenden Gesamtfortschrittsbalken und den
aktuellen Arbeitsschritt. Das Turmbild und gemeinsame Ergebniswerte bleiben
verborgen. Beim Wechsel in die gemeinsame Phase verschwindet der gesamte
Vorbereitungsblock; an seiner Stelle erscheinen das fortschreitende Turmbild,
Slice-Zähler und die Angaben zum bislang besten gemeinsamen Kandidaten. Der
Übergang blendet erst die Vorbereitung aus, tauscht bei unsichtbarem Inhalt die
Ansicht und blendet danach die gemeinsame Phase ein. Bei Abbruch, Fehler oder
einem neuen Lauf wird eine laufende Animation gestoppt und die normale
Deckkraft wiederhergestellt.
Ein Abbruch vor dem ersten verwertbaren gemeinsamen Slice meldet seinen Grund
im Statusbereich unten links; ohne Kandidaten bleibt die Ergebnisansicht
verborgen. Beim Fortsetzen bleibt die gemeinsame Ergebnisansicht sichtbar.
Ergebnisanzeigen zählen ausschließlich gemeinsame Slices; die getrennten
Vorläufe erscheinen nur in ihrem eigenen Fortschrittsblock. Vorbereitung,
Ausführung und Auswertung benennen jeweils den aktuellen getrennten oder
gemeinsamen Slice mit dem Zähler dieser Phase. Bei einer Fortsetzung zeigt der
Footer für gemeinsame Slices den bisherigen Gesamtzähler an.

Das gemeinsame Budget ist als `maximum_joint_slices` (5–25, Standard 12)
persistiert. Die ersten drei gemeinsamen Slices sind verpflichtend. Direkt nach
dem dritten vollständig geprüften Slice wird die bisher beste absolute
Zielabweichung geprüft: Liegt sie ungerundet bei höchstens 0,09 Sekunden,
endet der Lauf vorzeitig. Ein schlechterer aktueller Slice verdrängt einen
früheren, bereits geprüften Zieltreffer nicht.
Das getrennte Budget ist unabhängig davon als `maximum_separate_slices`
(1–25, Standard 6) persistiert. Beide Budgets werden in den allgemeinen
Einstellungen einzeln zurückgesetzt und bleiben beim globalen Zurücksetzen der
übrigen Generierungseinstellungen erhalten.
Auch Stagnation und die manuelle Übernahme dürfen erst nach drei vollständig
geprüften gemeinsamen Slices zum vorzeitigen Abschluss führen. Stagnation liegt
vor, wenn sich weder die Turmform noch die gemessenen Layerzeiten nennenswert
verändern. Ein Lauf endet außerdem bei ausgeschöpftem Budget oder einem Fehler.
Eine vorzeitige Übernahme setzt ein separates threadsicheres Event: Ein eventuell
laufender Slicer-Prozess wird sicher beendet, während der letzte vollständig
geprüfte gemeinsame Kandidat erhalten bleibt. „Fortsetzen“ startet nur das
verbleibende gemeinsame Budget mit diesem Kandidaten als Seed. Die bereits
abgeschlossenen gemeinsamen Slices werden dabei für Mindestanzahl und
Zielschwelle weitergezählt, sodass der erste neue Slice nach drei Pflicht-Slices
bereits der vierte insgesamt ist. Der Abschlusszähler gehört dabei nicht zur
Geometriekompatibilität des Seeds. Eine echte neue Generierung führt dagegen
stets erneut die getrennte Vorstufe aus. „Angleichung fortsetzen“ erscheint ab
dem dritten gemeinsamen Slice zunächst deaktiviert und ist nur bei einem
vorzeitig übernommenen Zwischenstand mit verbleibendem Slice-Budget bedienbar.
Beim Fortsetzen wird es wieder deaktiviert. Nach der Übernahme bleibt das Ergebnis
im Hauptfenster erhalten. Neben „Angleichung
fortsetzen“ erscheint dann im Generierungsergebnis rechts „Kühlturm exportieren“;
beide Export-Schaltflächen starten denselben Export und verwenden dieselbe Optik.
Der Footer-Button bleibt während der gesamten Generierung und nach einer
vorzeitigen manuellen Übernahme links neben „Kühlturm exportieren“ als
„Generierung abbrechen“ verfügbar. Ist der Exportbericht-Button sichtbar,
wird bei Platzmangel zuerst sein Name zu „Exportbericht öffnen“ und danach zu
„Exportbericht“ gekürzt. Anschließend folgen die beiden linken
Exportordner-Aktionen, zuletzt Export und Abbruch. Reicht der Platz danach
weiterhin nicht, wechselt der Footer in die horizontal getrennte Ansicht, in der
zunächst wieder die vollständigen Bezeichnungen verwendet werden. Reicht auch
dort der Platz nicht, werden sie in derselben Reihenfolge gekürzt; danach
wechselt die rechte Aktionsgruppe bei Bedarf in eine eigene Zeile.
Ein ausdrücklicher Abbruch verwirft auch einen zuvor übernommenen Kandidaten samt
Vorschau und ermöglicht sofort einen neuen Lauf mit unveränderten Einstellungen.
Nur „Bestes bisheriges Ergebnis übernehmen“ im Generierungsbereich hält einen
Kandidaten für Export und mögliche Fortsetzung fest. Während des Abbruchs zeigt
der Footer-Button deaktiviert „Abbruch wird ausgeführt …“.
Der finale Projektbau des übernommenen Kandidaten bleibt vom Übernahme-Event
unbeeinflusst; nur ein echter Abbruch darf ihn stoppen. Vor Abschluss des dritten
gemeinsamen Slices wird der Lauf ohne exportfähiges Ergebnis abgebrochen.

Ein Kandidat, der innerhalb der drei Pflichtslices oder später die feste
Zielschwelle von höchstens 0,09 Sekunden erreicht, bleibt bereits während
der Pflichtslices das beste Anzeigeergebnis. Nach dem dritten Slice kann
der Lauf mit diesem Kandidaten enden; Generierungsanzeige und Exportbericht
auf dieselbe Slicer-Auswertung. Während des Laufs bleibt der bislang beste
Kandidat intern und in der Ergebnisanzeige erhalten; schlechtere Folgeslices
ändern nur den Fortschrittszähler. Der erste erfolgreich geprüfte gemeinsame
Slice stellt auf die Seitenansicht um; diese zeigt die Form des aktuellen
Kandidaten auch nach Abschluss, bis der Benutzer die Kamera ändert. Export
und Fortsetzen setzen sie nicht zurück; der erste neue Slice stellt wieder
die Seitenansicht ein. Dafür werden
die bereits vorbereiteten Objektlinien und das Turmprofil verwendet; es ist kein
zusätzlicher Slicer-Lauf nötig. Während der Generierung bleiben Navigation und
Ansichtsbuttons gesperrt. Bei einem fehlgeschlagenen Lauf wird die vorherige
Ergebnisvorschau wiederhergestellt, sofern eine vorhanden war.
Beim erneuten Stoppen einer Fortsetzung wird auch der zuvor übernommene
Kandidat verworfen.
Ein fehlgeschlagener Fortsetzungslauf lässt das zuvor exportfähige Ergebnis
und, bei verbleibendem Slice-Budget, die Fortsetzungsoption verfügbar.
Ein erfolgreich exportierter Kandidat wird innerhalb der Sitzung anhand von
Anfrage und Turmdatei-Prüfsumme erkannt. Wird bei einer Fortsetzung ein neuer
bester Turm erzeugt, sind die Exportaktionen wieder verfügbar; derselbe
Kandidat bleibt gegen einen doppelten Export gesperrt.
Fehler der Generierung erscheinen mit ihrer vollständigen Ursache nur im
Statusbereich unten links. Der Ergebnisbereich zeigt bei erhaltenem Kandidaten
weiterhin dessen Werte und mögliche Aktionen, aber keinen zweiten Fehlertext.

Die Ergebnisanzeige enthält kürzeste gemeinsame Layerzeit/Ziel/Toleranz,
vorzeichenbehaftete Abweichung, zuerst das Ergebnis und danach tatsächlich
aktivierte Simulationen (Stützen und/oder 100-%-Turmfüllung). Nach manueller
Übernahme und nach regulärem Abschluss steht dort „Kühlturm exportieren“.
Nur erreichte Zeit und
Abweichung werden abhängig von der Toleranz eingefärbt; Zielzeit und Toleranz
bleiben neutral. Die Ansichtsbuttons über der 3D-Vorschau stehen in einer Zeile.
Vor dem ersten gemeinsamen Messwert bleibt die Dreispaltenansicht erhalten,
solange die drei Inhalte einschließlich Innenabständen nebeneinander passen.
Die Felder teilen freie Breite untereinander: Der längere Platzhalter zur
Layerzeit erhält seinen benötigten Raum, die übrigen Felder rücken zusammen.
Erst wenn dabei eine Zeile umbrechen müsste, wechselt die Anzeige ins 2×2-Layout.
Sobald ein gemeinsamer Messwert vorliegt, erhalten alle drei blauen Ergebnisfelder die gleiche
Breite; unteilbare Pixel werden mit höchstens einem Pixel Unterschied verteilt.
Ihre erforderlichen Textbreiten einschließlich Innenabständen bestimmen die
Umbruchgrenze. Die Bewertung reserviert unabhängig vom aktuellen Zustand
die Breite ihrer längstmöglichen Statusmeldung. Dadurch ändert ein Wechsel etwa
zwischen erreichter, unter- oder überschrittener Zielzeit weder ihre Breite noch
die Umbruchgrenze. Bevor die Bewertung oder der Hinweis neben den Ergebnisbuttons
zusätzlich umbrechen müsste, wechseln die Felder in
zwei Zeilen: Zeit und Abweichung oben, der Hinweis auf den manuellen Modus unten
links und die Bewertung unten rechts. Im 2×2-Layout erhalten alle vier Zellen
jeweils die halbe verfügbare Breite; die senkrechten Trennlinien beider Zeilen
liegen übereinander. Bei ungerader Pixelbreite ist die linke Spalte einen Pixel
breiter. In breiter Ansicht bleibt der Hinweis neben den rechts angeordneten
Ergebnisaktionen.
Bei sehr kleinen Breiten dürfen Texte innerhalb der Zellen umbrechen. Beide
Zeilen werden anhand ihrer tatsächlichen Breite in der Höhe bemessen.
Außerhalb der Toleranz wird
nach zusätzlicher Abweichung unterschieden: bis einschließlich 0,5 s „leicht“,
über 0,5 bis einschließlich 1 s ohne Verstärkung, über 1 s „stärker“.
Vor der ersten Generierung ersetzt ein kurzer Start-Hinweis diese Informationen;
nach dem Pre-Slice erklärt er, dass die Vorschau zunächst nur das Originalobjekt
ohne Kühlturm zeigt.
Alle horizontalen Ladebalken verwenden `ActivityProgressBar`: Der Fortschrittstext
steht mit dem rotierenden Halbkreis `◐ ◓ ◑ ◒` gemeinsam im Balken; der Animationstakt
beträgt wie bei der Profilbestätigung 140 ms. Die Frames werden als Kreise mit
geglätteten Kanten und identischer Breite und Höhe gezeichnet, unabhängig von Schriftart und
Zeichenform. Ihr äußerer Durchmesser entspricht der sichtbaren Schriftzeichenhöhe
des Textes direkt links daneben, einschließlich der Kontur. Schrift- und Textänderungen
aktualisieren diese Größe. Bei knappen Balkenhöhen verkleinern sie sich gleichmäßig;
die Kontur bleibt einschließlich Rand innerhalb des verfügbaren Platzes.
Ausgeblendete und abgeschlossene
Balken stoppen ihre Animation. Der Preslice-Controller steuert seine bisherigen
Frames weiterhin selbst; währenddessen pausiert die automatische Widget-Animation.
Ausgenommen sind der Gesamtbalken „Fortschritt der Vorbereitungen“ und der
vertikale Kühlturm-Bildbalken während der Generierung.
Aktuell/veraltet
steht als Badge direkt neben „3D-Vorschau“.

### Auswahl der Generierungsmethode und Sitzungszustände

Nach bestätigter Datei-/Slicer-Vorbereitung und „Fertig“ zeigt der Inhaltsbereich
zunächst drei responsive Methodenkarten für „Iterativ“, „Manuell“ und
„Postprozessor“. Die Karten stehen zunächst in drei Spalten mit dem Postprozessor
an erster Stelle. Bei weniger Platz steht er über Iterativ und Manuell;
anschließend werden alle drei in dieser Reihenfolge untereinander angeordnet.
Die Methodenbuttons im Header folgen derselben Reihenfolge.
Unter „Im Export enthalten“ benennen einzeilige Tags die Druckdateien:
Modell und Kühlturm als gemeinsames 3MF sowie die separate Kühlturm-STL bei
Iterativ und Manuell, bearbeiteter G-Code beim Postprozessor. Bei Platzmangel
werden die Tagtexte in der Mitte gekürzt, sodass die Dateiendungen sichtbar
bleiben. Der Tooltip und die zugängliche Kartenbeschreibung enthalten die
vollständigen Exportangaben.
Die bestehenden Geometriemodi behalten ihren dezenten Lilaton
beziehungsweise dunkleren Blauton. Die hellen Aktionsflächen
innerhalb der Karten zeigen dauerhaft ihren bisherigen violetten bzw. blauen
Hover-Verlauf. Beim Hover werden ausschließlich diese inneren Flächen zusätzlich
farblich kräftiger und ihre Konturen deutlicher; die bestehende Hover-Darstellung
der äußeren Karten bleibt erhalten. Beim Verlassen wird der neue Normalzustand
wiederhergestellt. `GenerationMode` kennzeichnet die
ausgewählte Methode; `None` bedeutet, dass noch keine Methode gewählt wurde. Die Vorbereitung und
deren Analysequelle werden von allen drei Methoden gemeinsam genutzt.
`window_pages` wechselt im Inhaltsbereich zwischen `settings_scroll` und
`preparation_workspace`. Der Header bleibt sichtbar. Solange „Datei und Slicer
vorbereiten“ geöffnet ist, bleibt der gesamte Footer ausgeblendet. Nach Rückkehr
zur Methodenwahl oder zu einem Geometriemodus erscheint er wieder.
Der Postprozessor verwendet eigene Fortschritts-, Fehler- und Exportaktionen
in einem ebenfalls geteilten Footer außerhalb des scrollbaren Arbeitsbereichs;
der gemeinsame Geometrie-Footer bleibt dort verborgen.
Nach der ersten abgeschlossenen Vorbereitung liegt dieselbe
Vorbereitungskarte dauerhaft in dieser Ansicht und ist kein Dropdown mehr.
`WorkflowHeader` verankert den kompakten `PreparationFactsButton` direkt am
oberen linken Fensterrand. Die fünf bestätigten Angaben stehen in kleinerer,
lesbarer Schrift untereinander ohne zusätzlichen Haken. Die Infofläche verwendet
7 Pixel oberen, 8 Pixel unteren und jeweils 7 Pixel seitlichen Innenabstand.
Ihre Inhaltshöhe bestimmt die
gemeinsame Headerhöhe; Methodenwahl und Update-/Abbruchleiste schließen weiterhin
an derselben unteren Trennlinie ab. Die grüne Infofläche hat ausschließlich
rechtwinklige Ecken.
Titel und Untertitel stehen horizontal mittig im Fenster, auch bei sichtbarer
Infofläche und Methodenwahl. Bei schmaler werdendem Fenster folgt die Gruppe
der Fenstermitte, bis sie den üblichen Zwischenabstand von 12 Pixeln zur Infofläche
erreicht. Dort bleibt sie stehen. Erreicht die rechte Methodenwahl denselben
Abstand zur Gruppe, wird der Text bei weiterer Verkleinerung ausgeblendet;
der Platz bleibt frei. Beim Vergrößern erscheint die Titelgruppe wieder.
Während der unbestätigten Vorbereitung steht die Titelgruppe vertikal mittig
zwischen Fensteroberkante und der Vorbereitungskarte. Nach erfolgreichem
Abschluss steht sie mittig auf Höhe des höchsten Header-Elements,
üblicherweise der Infofläche. Die Programmheader-Trennlinie erscheint bereits
beim Start. Während der unbestätigten Vorbereitung gehören die bisherigen
oberen und unteren Abstände der Titelgruppe zur Headerfläche; die vertikalen
Titelpositionen bleiben erhalten. Ein 8 Pixel hoher, für Mausereignisse
durchlässiger Schatten liegt als Overlay im zentralen Widget über der folgenden
Seite und erzeugt keinen Layoutabstand.
„Datei und Slicer vorbereiten“ schließt unmittelbar an den Header an und reicht
bis zu den seitlichen Fensterrändern beziehungsweise zum aktiven Scrollbalken.
Die äußere Fläche besitzt weder Rahmenlinien noch abgerundete Ecken. Ihr
eigener Header enthält ausschließlich die zentrierte Überschrift; das verborgene
Standardheader-Widget behält die Zustands-/Summary-Schnittstelle für den
WorkflowController. Schrittstatus und Fehlerrückmeldungen stehen weiterhin in
den jeweiligen Vorbereitungsschritten. Die Methodenwahl behält ihre äußeren
Abstände von 22 Pixeln. Die manuelle Generierungsseite behält diese Abstände
oben, unten und rechts; ihre Einstellungsseite schließt links bündig mit dem
Fensterrand ab.
Die Vorbereitungsfläche verwendet durchgehend den grauen Programmhintergrund
(`#f3f6f9`); am unteren Rand ist kein eigener Farbverlauf oder Abstand nötig. Bei
sichtbarer Methodenwahl sind Menü und Version jeweils horizontal zwischen
Methodenfläche und rechtem Fensterrand zentriert. Gemeinsam sind sie vertikal
zwischen Fensteroberkante und der Header-Trennlinie zentriert.
Ohne Methodenfläche behält die Version ihre bisherigen äußeren Abstände;
der Menübutton steht horizontal zentriert direkt darüber.
Eine dünne horizontale Linie trennt den Header dauerhaft vom Content, auch
am oberen Scrollrand. Nach Bestätigung liegt sie auf Höhe der grünen Unterkante
und ersetzt dort die untere Rahmenkante,
sodass keine doppelte Linie entsteht.
Die Methodenwahl beginnt links neben dem Menübereich direkt am oberen
Fensterrand. In der Kartenansicht bleibt dieser Bereich ausgeblendet.
Nach der Wahl erscheint `HeaderMethodSelection` als verbundenes
Element: oben die zentrierte Textüberschrift „Erstellungsmethode“, unmittelbar
darunter nebeneinander „Iterativ“ und „Manuell“. Die Buttons behalten die
Höhe des Menübuttons; die Überschriftenfläche wächst bis zur Höhe der Infofläche,
sodass beide Bereiche bündig an der gemeinsamen Header-Trennlinie enden.
Layoutabstände sind null. Alle Ecken der Methodenfläche und ihrer Buttons sind
rechtwinklig. Die Buttons verwenden die violetten
bzw. blauen Verläufe der Methodenkarten. Die aktive Methode ist exklusiv
ausgewählt und wirkt durch einen hellen umgekehrten Verlauf, eine dünne obere
Schattenkante und eine helle Unterkante eingedrückt. Beide Beschriftungen verwenden
normale Schriftstärke. Nach dem Klick bleibt kein Fokusrahmen zurück. Tab und Leertaste
bleiben verfügbar. Die Version steht direkt unter dem Menü.
„Datei und Slicer vorbereiten“ bleibt als zugänglicher
Name erhalten und erscheint nicht als sichtbarer Buttontext. Der Tooltip lautet
„Datei- und Slicereinstellungen ändern“.
Der Infobutton nutzt denselben grünen Bestätigungsverlauf wie die vorhandenen
Bestätigungsaktionen; die Methodenbuttons besitzen passende Hover- und Druckzustände.
Angaben und Buttons bleiben im Header; lange Angaben umbrechen innerhalb
der Infofläche. Menü und Version bleiben rechts.
Lange Angaben werden umgebrochen und bleiben vollständig lesbar. Nicht mehr
bestätigte Angaben werden gemeinsam entfernt. Vor dem erfolgreichen Abschluss
werden keine Teilangaben im Header angezeigt.
Die Methodenbuttons wechseln direkt in den jeweiligen Arbeitsbereich und dienen
auch zur Rückkehr aus der Vorbereitung. Ein Klick auf die bereits aktive Methode
erhält die aktuelle Auswahl im manuellen Editor. Bei unbestätigter Vorbereitung
werden Infofläche und Methodenaktionen gemeinsam ausgeblendet.
Der bestehende iterative Arbeitsbereich bleibt beim Navigieren erhalten;
er wird lediglich ausgeblendet. `ManualGenerationPanel` besitzt einen eigenen
eingebetteten Editor mit links angeordneten Einstellungen und rechts der Vorschau.
Ein Methodenwechsel startet keinen Slice und invalidiert kein Ergebnis.
Bei erneut erforderlicher Vorbereitung öffnet sich die Vorbereitung wieder;
nach „Fertig“ folgt erneut die Methodenauswahl. `ContentTransition` blendet
beim Abschluss den bisherigen Inhaltsbereich aus und die Methodenauswahl ein.
Auf 0,275 Sekunden Fade-out folgen 0,1 Sekunden Pause bei vollständig unsichtbarem
Inhalt und anschließend 0,275 Sekunden Fade-in; der Gesamtübergang dauert 0,65 Sekunden.
Das ausblendende Bild behält seine ursprüngliche Größe. Der Layoutwechsel mit
angepasstem Header und eingeblendetem Footer erfolgt erst zwischen beiden
Fades, wenn der Inhalt vollständig unsichtbar ist. Ein durchgehend heller
Hintergrund verhindert eine dunkle Leerfläche während der Überblendung.
Beide Fades verändern ausschließlich die Deckkraft und behalten die Farben der
Bedienelemente bei. Ein auf den Inhaltsbereich begrenzter Ereignisfilter sperrt
Eingaben während Fade-out, Pause und Fade-in, ohne Widgets zu deaktivieren und
dadurch Qt-typische graue Disabled-Farben auszulösen.
Der Header bleibt während des Übergangs sichtbar. Die Animation wird
beim erneuten Öffnen der Vorbereitung, bei ungültiger Vorbereitung oder beim
Schließen beendet und die Bedienbarkeit wiederhergestellt.
Das Öffnen der Methodenauswahl erhält die aktuelle Methode bis zur Auswahl
einer anderen Methode. Laufende Generierung und Export sperren beide Header-Zugänge.

`generation_sessions` enthält pro Methode einen eigenen `GenerationSession`
mit Vorschauergebnis/-status, Exportergebnis und Identität des exportierten
Turmstands. Die bisherigen Attribute `current_preview`, `preview_state`,
`last_export_result` und `_last_exported_preview_identity` greifen ausdrücklich
auf die Sitzung der iterativen Methode zu. So können Callbacks der iterativen Methode kein
manuelles Ergebnis überschreiben, auch wenn die Ansicht der iterativen Methode verborgen ist.
Ein Quell-/Profilwechsel verwirft die betroffenen Vorschauen aller Methoden;
beim Schließen werden deren temporäre Artefakte freigegeben. Der letzte
Exportbericht bleibt als sitzungsweiter Verlauf verfügbar.
Der Postprozessor besitzt eine eigene Sitzung, einen verwalteten Vorschaujob und
einen unmittelbaren G-Code-Export. Sein Datenfluss und seine Sicherheits-/
Zeitinvarianten stehen unter [Postprozessor](postprocessor.md).
Die Einstellungen und Fortschrittssteuerung der iterativen Methode bleiben in ihrem
bestehenden Arbeitsbereich. Manuelle Eingaben verwenden ausschließlich die
manuelle Sitzung mit `manual_draft`, `running_request` und `successful_request`.
`ManualGenerationController` orchestriert methodenspezifische Worker; negative
Request-IDs und eigene Signalverbindungen trennen sie von Jobs der iterativen Methode.
Die vorhandenen Jobarten `PREVIEW` und `EXPORT` erhalten alle gemeinsamen Sperren
und die kontrollierte Thread-/Prozessfreigabe. `ManualGenerationService` erzeugt
eine ausdrücklich gestaltete Form und ermittelt ihre Layerzeiten mit einem
vollständigen Prüfslice, ohne `CalibrationService.calibrate()` oder iterative
Formung. Die manuelle Methode bewertet keine Zielzeit oder Toleranz.
Die manuellen Fachmodule unter `manual/` bleiben Qt-unabhängig.
Die Methodenauswahl und Ergebnisse werden nicht in Benutzereinstellungen gespeichert.
Das Einstellungsschema der iterativen Methode 21 bleibt unverändert; manuelle,
wiederverwendbare Werte liegen getrennt in `manual_settings.json`; dessen eigenes
Schema und Migrationen stehen in [Persistenz](settings_migrations.md#getrennte-manuelle-einstellungen-eigenes-schema-10).
Modell, Zustände, Bedienung und Prüfnachweise stehen im
[manuellen Editor](manual_editor.md).
Beide Methoden verwenden die bestehenden Aktionen und die responsive Anordnung
des Hauptfenster-Footers. Manuelle Status-/Ergebniswidgets sind dort separat
eingebunden; Buttonaktionen und Reset werden nach der aktiven Methode geroutet.
Die Vorschauhöhe wird bei Fenster-/Methodenwechseln an den verfügbaren Bereich
angepasst und bleibt bei Einstellungs- bzw. Grenzmeldungen stabil.
Die manuelle Einstellungsseite besitzt eine 250-ms-Pfeilleiste außerhalb ihres
Scrollbereichs; der rein flüchtige Zustand verändert keine Fachwerte oder
persistierten Einstellungen. Neben den viewportunabhängigen Originalflächen
speichert der Canvas ein fertiges Originalbild für den aktuellen Bildausschnitt.
Turm, Skalen und Bearbeitungsgriffe bleiben eigene, anschließend gezeichnete
Elemente. Transformation, Deckkraft, Pixeldichte und Original-Zeichenfolge bestimmen
die Bildgültigkeit. Details zu Einpassung, Mindestmaßgriff und verlustfreien
Renderoptimierungen stehen im [manuellen Editor](manual_editor.md).

Unter „Turmeinstellungen“ steht die Mindest-Layerzeit.
Auf die Mindest-Layerzeit folgen „100% Turmfüllung simulieren“ und
„Deaktivierte Turmstützen simulieren“. Die
bei global deaktivierten Stützen angebotene Option „Stützen für STL-Objekt
simulieren“ folgt darunter; ihre Wirkungsweise steht in
[Turmgeometrie](tower_geometry.md#objektspezifische-stützen-für-das-original-stl). Die
darunterliegenden Geometrie- und Berechnungswerte sind im standardmäßig
geöffneten Unterbereich „Erweiterte Turmeinstellungen“ ein- und ausklappbar.
Er ist in „Turmgeometrie“ und „Generierung“ unterteilt. Dezente Überschriften
stehen jeweils knapp über einer horizontalen Trennlinie. „Turmgeometrie“
enthält die Abmessungen, Standfuß-, Überhang- und Ausschlussbereicheinstellungen.
„Generierung“ enthält Layerzeit-Toleranz, maximale getrennte und gemeinsame
Slices sowie das lokale Zeitfenster. Alle vier Optionen besitzen Einzelresets
und gehören zum Reset der Turmeinstellungen. Die gespeicherten Werte und ihre
Bedeutung bleiben beim Verschieben erhalten.
Die äußeren Bereiche der iterativen Methode „Turmeinstellungen“ und „Generierung und Vorschau“
sind dauerhaft geöffnet und besitzen keine Aufklappdreiecke, seitlichen Rahmen
oder abgerundeten Ecken. Beide schließen ohne oberen oder seitlichen Außenabstand
an den Programmheader und die nutzbaren Fensterränder an; der Headerschatten
liegt über ihren Überschriften. In der zweispaltigen Ansicht trennt eine
ein Pixel breite vertikale Linie die unmittelbar angrenzenden Bereiche bis zur
Unterkante des höheren Bereichs. In schmalen Fenstern bleiben sie ohne
Zwischenabstand gestapelt, mit „Generierung und Vorschau“ an erster Stelle;
die vertikale Linie wird dabei ausgeblendet. Innere Inhaltsabstände und der
untere Seitenabstand bleiben erhalten.
Die Dropdown-Köpfe verwenden einheitliche, selbst gezeichnete Dreiecke ohne
eigenen Rahmen, Hintergrund oder Hover-Effekt. Beide Richtungen entstehen
durch Drehung um die Mitte desselben festen Symbolbereichs.
Die Checkboxen für die 100-%-Turmfüllung, die Turmstützen und die automatische Standfußbreite
zeigen den Haken rechts neben ihrem Text. Der Text mit Checkbox der
automatischen Standfußbreite beginnt mit dem gleichen Abstand zum Info-Hinweis
wie die übrigen Einstellungsnamen; Breitenfeld und Reset behalten die
rechtsbündigen Spalten der übrigen Zahleneinstellungen.
Die automatische Standfußbreite ist
standardmäßig aktiv; Checkbox, Breitenfeld und Reset stehen in einer Zeile.
Bei aktiver Automatik zeigt das deaktivierte, leicht ausgegraute Feld den
berechneten Wert. Bei deaktivierter Automatik ist es normal editierbar; die
Breite liegt zwischen 20 und 100 mm. Der stets sichtbare Reset setzt auf den
derzeit berechneten Automatikwert zurück. Ein vor dem Umschalten eingegebener
manueller Wert bleibt für die laufende Sitzung erhalten.
Entspricht der angezeigte Wert dem auf zwei Nachkommastellen gerundeten
Automatikwert, ist der Reset deaktiviert.
Die Untergrenze der gewünschten Mindest-Layerzeit bleibt unabhängig vom
Pre-Slice bei 5 s. Die beim Pre-Slice ermittelte kürzeste Layerzeit des
Originalobjekts erscheint im Info-Hinweis. Bei eingeblendeten
Eingabegrenzen stehen Mindest- und Höchstwert gekürzt als
„Minimum - Maximum Einheit“ unter dem Feld; einzelne Höchstwerte behalten
die Beschriftung „Max.“. Die Nachkommastellen entsprechen denen des
jeweiligen Eingabefelds. Ein
bereits eingegebener Wert unter 5 s bleibt sichtbar und wird als ungültig
markiert. Die Layerzeit-Toleranz beginnt bei ±0,1 s.
Der minimale Turmdurchmesser hat weiterhin 5 mm als Voreinstellung und liegt
zwischen 3 mm und dem kleineren Wert aus aktuellem Maximaldurchmesser und
99 mm. Der Maximaldurchmesser liegt zwischen
dem größeren Wert aus 5 mm und `Minimaldurchmesser + 1 mm` sowie 100 mm.
Überschreitungen werden direkt beim jeweiligen Durchmesserfeld angezeigt und
verschwinden nach einer gültigen Korrektur.
Wenn alle analysierten Schichten die eingestellte Zielzeit bereits erreichen,
nennen der Einstellungsbereich und die Aktionsmeldung Zielzeit und kürzeste
gemessene Schichtzeit als Grund; die Turmgenerierung bleibt gesperrt.
Bei einem Mehrbedarf von höchstens 0,5 s erscheint stattdessen ein gelber
Hinweis, die Generierung bleibt möglich.
Ein aktiviertes Draft Shield in den bestätigten Profilen wird vor dem Pre-Slice
gesondert angezeigt. Nach ausdrücklicher Wahl werden Draft Shield und
Skirt-Loops nur in temporären Profilkopien deaktiviert; die Kopien fließen
in Pre-Slice, gemeinsame Slices und den exportierten 3MF-Projektstand ein.
Nach Bestätigung wird ein Turm über die gesamte Modellhöhe erzwungen; dabei
darf allein die durch die aktuelle Messung erhöhte Zielzeit-Untergrenze für
diesen Lauf unterschritten werden. Andere Eingabefehler bleiben gesperrt.
Eingabegrenzen sind standardmäßig verborgen; die frühere Anzeigeoption ist aus
„Allgemeine Einstellungen“ entfernt. Dort befinden sich die getrennten
Exportordner der drei Methoden mit Einzelresets und gemeinsamem Reset;
ein eigener Exportordner-Menüpunkt entfällt. Die Ordner sind bereits vor
Abschluss der Vorbereitung einstellbar. Änderungen und Resets werden erst mit
„Übernehmen“ gespeichert. Ein durchgehender
Trennstrich setzt die Aktionen „Abbrechen“ und „Übernehmen“ mit gleichem
Innenabstand vom Inhalt ab.
Das Ausblenden verkleinert die gesamte Einstellungskarte. Einige Zahlenfelder
zeigen zur besseren Lesbarkeit eine Nachkommastelle; die Speicherpräzision
bleibt erhalten. Die Eingabeprüfung
ist stets aktiv; eine Dev-Umgehung existiert nicht. Fehlermeldungen an den
Einstellungen prüfen jeweils nur den eigenen Wert und wachsen mit dem Inhalt,
ohne die Bedienelemente zu überdecken.

In der iterativen Methode befindet sich „Standardwerte wiederherstellen“
links unten im Footer. Die manuellen Resets beschreibt [manual_editor.md](manual_editor.md).
Nach dem
Zurücksetzen wird das lokale Zeitfenster an die analysierte Layerzahl angepasst
und die Geometrieprüfung mit den neuen Werten erneut gestartet. Rechts
bleiben Exportordner, letzter Export, Exportbericht und die aktuelle Hauptaktion
als Gruppen erhalten. Ihre Anordnung richtet sich nach der verfügbaren Breite;
der Footer nimmt nur die für Meldungen und Aktionen erforderliche Höhe ein und
verkleinert sich auch nach einer Rückvergrößerung des Fensters. Rechts behalten
alle Aktionsbuttons einschließlich später eingeblendeter Aktionen ihre
ursprüngliche Höhe von 50 Pixeln; die Resets links bleiben 32 Pixel hoch.
Die Meldungen links stehen unabhängig von der Höhe rechts am oberen Rand.
Zusätzliche Höhe fließt nur in den Abstand vor den linken Resets. Die beiden
Bereiche werden getrennt bemessen; in der zweispaltigen Ansicht bestimmt der
größere tatsächliche Inhaltsbedarf die Footerhöhe. Leere Ergebniszeilen
reservieren keine Höhe; umbrochene Meldungen werden anhand ihrer tatsächlich
verfügbaren Breite bemessen.

Bei gemeinsamen Slices ist die absolute Abweichung der kürzesten Layerzeit des
vollständigen Projekts von der Zielzeit das Vergleichskriterium. Ausschlüsse
steuern die lokale Zeitkorrektur und Konvergenz, nicht die gemessene Gesamtprojekt-
Layerzeit. Bei gleicher Abweichung bleibt der zuerst vollständig geprüfte Kandidat
bestehen, außer ein Lauf mit Ausschlüssen erreicht eine bessere Angleichung der
nicht ausgeschlossenen Layer. Weder die Anzeige
noch der später exportierte Kandidat können durch einen gleichen oder
schlechteren Folgeslice ersetzt werden.

Der eingebettete Generierungsbereich zeigt Zielvorgabe und bisher bestes
Ergebnis gemeinsam an. Abbruchhinweise verwenden den Bestwert als
Statusgrundlage: Ergebnisse innerhalb der eingestellten Toleranz erscheinen
grün, größere Abweichungen gelb und Fehler separat rot; Trennlinien bleiben
neutral grau. Nach einem ausdrücklichen Abbruch steht oberhalb der Trennlinie
„Die Generierung wurde manuell abgebrochen.“ und direkt darunter „Der bisherige
Kühlturm wurde verworfen.“

### Windows-Prozessfehler ohne blockierende Systemdialoge

`cooling_tower.windows_process` installiert beim frühesten Paketstart genau
eine prozessweite Windows-Richtlinie. Sie ergänzt vorhandene Fehlerflags um
`SEM_FAILCRITICALERRORS`, `SEM_NOGPFAULTERRORBOX` und
`SEM_NOOPENFILEERRORBOX` und aktiviert zusätzlich
`WER_FAULT_REPORTING_NO_UI`. Die Richtlinie wird anschließend nicht wieder
zurückgesetzt: Dadurch gibt es kein globales Setzen-und-Zurücksetzen zwischen
Threads, und sämtliche mit `subprocess` oder `QProcess` erzeugten Nachkommen
erben denselben nichtinteraktiven Fehlermodus.

Im Quell- und Testbetrieb lädt `sitecustomize.py` ausschließlich dieses
leichtgewichtige Modul, bevor Test-Discovery oder Anwendungsimporte beginnen.
Der normale Paketimport wiederholt die Einrichtung idempotent; ein zunächst
unvollständiger WinAPI-Aufruf wird bei der nächsten Sicherungsstelle erneut
versucht. `CREATE_DEFAULT_ERROR_MODE` ist für programmverwaltete Kindprozesse
verboten, weil dieses Flag die Vererbung absichtlich umgehen würde.

Unterdrückt wird nur die Windows-Systemoberfläche. Exitcode, signierter oder
unsignierter NTSTATUS, Crashzustand und Diagnoseereignisse bleiben erhalten.
Bekannte Loader-, Architektur-, Zugriffs- und Fast-Fail-Statuscodes erhalten
eine verständliche Beschreibung. Slicerfehler werden im betroffenen
Programmschritt angezeigt; native Programmabbrüche bleiben über Sitzungsmarker,
Crashlog und den Hinweis beim nächsten Start erkennbar.

## Diagnose und Stresstests

`DiagnosticJournal` schreibt pro Sitzung eine rotierende, append-only
JSONL-Datei. Jeder technische und fachliche Job-Eintrag enthält Sitzungs- und
Korrelations-ID, Programmversion, Ereignisnummer, UTC- und monotone Zeit,
Zustandsübergang, Worker- und Thread-Identität, Abbruch-/Fehlergrund und Dauer.
Lokale Logs besitzen eine Grundfilterung, können aber weiterhin Namen,
Dateinamen und freie Fehlermeldungen enthalten. Sie sind keine freigegebenen
öffentlichen Supportdateien. Der davon getrennte Export über `SupportReportService`
verwendet eine ausdrückliche Feld- und Wertefreigabe in `support_privacy.py`,
begrenzte Lesezugriffe und neutrale Sitzungs-/Profilbezeichnungen.
[Support und Diagnose](support.md) dokumentiert Inhalt und verbleibende Grenzen.

Der zentrale Qt-Message-Handler erfasst insbesondere Timer-, ThreadStorage-,
`setParent`- und vorzeitig zerstörte `QThread`-Warnungen zusammen mit einem
threadsicheren Snapshot der aktiven Jobs. Er öffnet keine GUI, wirft keine
Ausnahme in Qt zurück und reicht Nachrichten an einen zuvor installierten
Handler weiter.

Ein atomarer Sitzungsmarker unterscheidet saubere Abschlüsse von einem
unerwarteten Abbruch. Beim nächsten Start kann der Benutzer den ausschließlich
lokalen technischen Bericht anzeigen, kopieren, seinen Protokollordner öffnen
oder den Hinweis verwerfen. Es gibt keinen automatischen Upload.

Native Stressfälle laufen über `cooling_tower.gui.job_stress` jeweils in einem
eigenen Python-Prozess mit festem Zufalls-Seed. Der Elternprozess prüft
Exitcode, Abschlussmarker, Timeout, kritische Qt-Warnungen, leere Job-Registry
und verwaiste Fake-Slicer-Unterprozesse. Damit beendet ein möglicher nativer
Qt-Abbruch nicht die übrige Testsuite und bleibt mit dem ausgegebenen Seed
reproduzierbar.

Die vollständige G-Code-Datei wird bei jeder gemeinsamen Slicer-Prüfung erneut
gelesen. Ein begrenzter, ausschließlich flüchtiger Block-Cache darf innerhalb
des laufenden Programms nur bitgenau gleiche Maschinenzustände und vollständig
gleiche Quellzeilen wiederverwenden. Er speichert weder Turmkandidaten noch
Sitzungsdaten und darf deshalb keine Kalibrierungsentscheidung ersetzen.

Der Architekturtest wertet den Python-Syntaxbaum aus und erkennt auch
aliasierte beziehungsweise qualifizierte `QThread`-Konstruktoren sowie direkte
`deleteLater`- und `terminate`-Umgehungen. Zusätzlich verbietet er die
Wiedereinführung der entfernten Legacy-Job-API im produktiven Quellcode.

## Regeln für Änderungen

1. Einen bestehenden Anwendungsfall erweitern, statt einen zweiten parallelen
   Laufzeitpfad einzuführen.
2. Fachberechnungen in Fachmodulen halten; GUI-Slots koordinieren nur Zustand,
   Darstellung und Worker.
3. Öffentliche Kompatibilität nur bewusst entfernen. Die kleinen
   Import-Wrapper im Projektwurzelverzeichnis bleiben für ältere Skripte
   absichtlich erhalten.
4. Jede Fehlerkorrektur durch einen fokussierten Regressionstest absichern.
5. Nach strukturellen Änderungen mindestens Syntaxprüfung, vollständige
   Testsuite, GUI-Starttest sowie einen Thread-/Schließtest ausführen.
6. Generierte Caches, virtuelle Umgebungen und Build-Artefakte nicht
   versionieren.

## Verantwortlichkeiten nach dem Wartbarkeitsumbau September 2026

- `gui/about_dialog.py`: eigener Dialog mit Rechtstextanzeige und responsive
  Anordnung. `MainWindow` koordiniert lediglich Öffnen und Positionierung.
- `gui/widgets/preparation_controls.py`: Vorbereitungsnavigation, Statusmodell
  und Fortschrittsanzeige ohne Kenntnis der Hauptfenster-Implementierung.
- `gui/preview_controller.py`: Qt-Thread-/Statuskoordination der Vorschau.
  `preview/controller.py` bleibt nur als schmale Kompatibilitätsweiterleitung;
  die Paket-API lädt den Controller erst bei explizitem Zugriff.
- `slicers/profile_rules.py`: reine Identitäts-, Normalisierungs-, Düsen- und
  Kompatibilitätsregeln. Inventar-I/O und Matching-Orchestrierung bleiben im
  Matching-Service. Alte Funktionsimporte werden weiterhin bereitgestellt.
- `calibration/candidate_evaluation.py`: reine Kandidatenbewertung und
  Konvergenzmessgrößen. Der Service besitzt weiterhin den iterativen Ablauf und
  priorisiert gemeinsame gegenüber isolierten Kandidaten.
- `settings_defaults.py`: aktuelle Standards aus der Ressourcen-JSON; historische
  Migrationswerte bleiben explizit in ihren Migrationsschritten.
- `write_policy.py`: gemeinsame Prüfung eigener Schreibziele gegen bekannte und
  registrierte Slicer-Verzeichnisse; Datei-/Junction-Auflösung vor Schreibzugriffen.
- `persistence/document_lock.py`: gemeinsame Sperre pro kanonischem Dokumentpfad
  über Threads und kooperierende Prozesse, ohne zusätzliche Bibliothek.
- `start_gui.pyw`: auch frühe Import-/DLL-Fehler protokollieren nur im eigenen
  Benutzerdatenordner; das Installationsverzeichnis bleibt unverändert.
- `legal_documents.py`: offline gerenderte Texte aus einer einzigen Anbieterdatei.
  Build-/Vertriebsprüfungen liegen unter `scripts/`, nicht im Produktablauf.

Qt-Signalempfänger für Worker-Ergebnisse sind ausdrücklich als Slots registriert.
Widgetänderungen und Folgestarts bleiben im GUI-Thread. Die Qt-Transportklasse
wird erst bei tatsächlicher Verwendung geladen; ein Import des fachlichen
Vorschaupakets lädt kein Qt. Kompatibilitätsimporte sind kein Vorbild für neue
Fachmodule: neue Aufrufer verwenden die zuständige konkrete Komponente.

## Grenzen und nächste größere Strukturänderungen

`MainWindow` und die Kalibrierungsschleife bleiben umfangreiche Orchestratoren.
Die Auslagerungen beseitigen konkrete vermischte Verantwortlichkeiten, ersetzen
aber keine vollständige Zerlegung. Beim nächsten betroffenen Funktionsausbau
sollten Quellenvorbereitung/Profilbestätigung und Einstellungsansicht jeweils
Eigentümer ihres Zustands und ihrer Widgets werden. Dafür konkrete Übergaben
und Signale definieren; keine Mixins mit beliebigem Zugriff auf hunderte
Hauptfensterattribute einführen. Die bestehende Workflow-Zustandsmaschine und
Request-ID-Prüfung bleiben verbindlich.

Für den Parser ist die Python-/C++-Parität der entscheidende Vertrag, siehe
[native Analyse](native_analysis.md). Eine Komplettumschreibung oder gemeinsame
Codegenerierung würde derzeit zusätzlichen Prüfaufwand und neue Risiken erzeugen.
Gezielte Funktionsänderungen benötigen nur die verantwortlichen Module und
passenden Tests, nicht jedes Mal die gesamte Historie. Testnavigation und
abschließender Prüfumfang: [Entwicklung](development.md).
