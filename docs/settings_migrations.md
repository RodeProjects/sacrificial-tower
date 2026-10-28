# Migrationen für Benutzereinstellungen und Profile

Benutzerdaten besitzen eine eigene Schema-Version. Sie ist unabhängig von der
Programmversion: Mehrere Programmversionen dürfen dasselbe Datenschema verwenden,
und eine Programmversion darf mehrere Datenschemata migrieren können.

Die gemeinsame Implementierung liegt in
`cooling_tower.persistence.versioned_json.VersionedJsonStore`. Die globalen
GUI-Einstellungen, bestätigte Slicer-Pfade und Profilzuordnungen verwenden
diesen Mechanismus bereits. Zukünftige speicherbare Einstellungsprofile müssen
ihn ebenfalls verwenden. Reine, jederzeit neu aufbaubare Caches dürfen ein
einfacheres Format behalten.

## Inhalt

- [Speicherorte und parallele Installationen](#speicherorte-und-parallele-installationen)
- [Garantien](#garantien)
- [Neue Schema-Version anlegen](#neue-schema-version-anlegen)
- [Regeln je Änderungstyp](#regeln-je-änderungstyp)
- [Sichere Änderungen während eines Downgrades](#sichere-änderungen-während-eines-downgrades)
- [Zukünftige Einstellungsprofile](#zukünftige-einstellungsprofile)
- [Parallelzugriffe und aktuelle Standardwerte](#parallelzugriffe-und-aktuelle-standardwerte)
- [Schema 11: einstellbare Layerzeit-Toleranz](#schema-11-einstellbare-layerzeit-toleranz)
- [Schema 12: automatische Standfußhöhe](#schema-12-automatische-standfußhöhe)
- [Schema 13: Ziel-Layerzeit und neue Standardwerte](#schema-13-ziel-layerzeit-und-neue-standardwerte)
- [Schema 14: maximale gemeinsame Slices](#schema-14-maximale-gemeinsame-slices)
- [Schema 15: optionale Eingabegrenzen](#schema-15-optionale-eingabegrenzen)
- [Schema 16: automatische Geometrieparameter](#schema-16-automatische-geometrieparameter)
- [Schema 17: Untergrenzen der Layerzeiten](#schema-17-untergrenzen-der-layerzeiten)
- [Schema 18: Durchmessergrenzen](#schema-18-durchmessergrenzen)
- [Schema 19: maximale getrennte Slices](#schema-19-maximale-getrennte-slices)
- [Schema 20: Simulation ohne Turmstützen](#schema-20-simulation-ohne-turmstützen)
- [Schema 21: maximale Standfußbreite](#schema-21-maximale-standfußbreite)
- [Schema 22: Profilbindung des Aufweitungswinkels](#schema-22-profilbindung-des-aufweitungswinkels)
- [Schema 23: Segmentwahl für iterativ erzeugte Türme](#schema-23-segmentwahl-für-iterativ-erzeugte-türme)
- [Schema 24: getrennte Exportordner](#schema-24-getrennte-exportordner)
- [Schema 25: Postprozessor-Standardordner](#schema-25-postprozessor-standardordner)
- [Schema 26: Postprozessor-Methodenkennung](#schema-26-postprozessor-methodenkennung)
- [Schema 27: Standardnamen der Exportordner](#schema-27-standardnamen-der-exportordner)
- [Getrennte manuelle Einstellungen (eigenes Schema 19)](#getrennte-manuelle-einstellungen-eigenes-schema-19)


## Speicherorte und parallele Installationen

Unveränderliche Programmressourcen bleiben im Installations- beziehungsweise
PyInstaller-Ressourcenverzeichnis. Veränderliche Benutzerdaten liegen unter:

`%LOCALAPPDATA%\RodeProjects\SacrificialTower\<Instanz>\`

Jede Instanz besitzt getrennte Unterordner `config`, `logs` und `output`.
Dadurch beeinflussen sich die normalen Varianten nicht gegenseitig:

- `development`: direkt aus Python gestartete Entwicklungsversion
- `standalone`: regulärer Inno-Setup-Build
- `microsoft-store`: späterer MSIX-/Store-Build
- frei wählbare Testinstanz über `COOLING_TOWER_INSTANCE_ID`

`COOLING_TOWER_USER_DATA_ROOT` kann für automatisierte Tests oder bewusst
portable Sonderfälle einen vollständig eigenen Stammordner festlegen. Die
Instanz-ID erlaubt nur Buchstaben, Ziffern, Punkt, Unterstrich und Bindestrich;
Pfadbestandteile wie `..` werden abgelehnt.

Zwei reguläre Inno-Setup-Versionen mit derselben `AppId` sind dagegen keine
getrennten Installationen: Eine neuere ersetzt die vorherige. Sollen zwei
eigenständige Builds wirklich parallel installiert werden, brauchen sie neben
getrennten Dateninstanzen auch verschiedene Setup-Identitäten und
Installationsverzeichnisse.

Beim ersten Start einer Python- oder gebauten eigenständigen Version werden
vorhandene Legacy-Konfigurationsdateien aus dem bisherigen Programmordner nur
dann in den jeweiligen AppData-Bereich kopiert, wenn am Ziel noch keine Datei
existiert. Quelle und bestehende Zieldateien bleiben unangetastet. Erst danach
läuft die jeweilige Schema-Migration mit eigener Sicherung.

Ohne gespeicherte Fenstergröße startet das Hauptfenster mit 1250 × 1080 Pixeln.
Bereits gespeicherte Größen und Positionen werden bei weiteren Starts übernommen.
Der Standardwert ändert weder das Speicherformat noch bestehende Einstellungen.

## Garantien

- Eine Datei wird ausschließlich als UTF-8-JSON-Objekt akzeptiert.
- Jede ältere Schema-Version wird Schritt für Schritt migriert. Für Schema 1
  nach Schema 4 müssen deshalb die Schritte 1→2, 2→3 und 3→4 vorhanden sein.
- Vor einer migrations- oder normalisierungsbedingten Umschreibung wird eine
  bytegetreue Sicherung neben der Originaldatei angelegt.
- Die neue Datei wird zunächst vollständig in eine temporäre Datei geschrieben
  und anschließend atomar an die Zielstelle verschoben.
- Eine unbekannte neuere Schema-Version wird nie automatisch verändert. Eine
  ältere Programmversion darf ausschließlich ausdrücklich kompatible Werte in
  einer getrennten Arbeitsdatei ändern.
- Nach einem Lade-, Validierungs- oder Migrationsfehler bleibt Schreiben
  gesperrt. Dadurch kann das Speichern beim Programmende die Originaldatei
  nicht mit Standardwerten überschreiben.
- Eine bewusst ausgelöste Wiederherstellung ist möglich, legt aber ebenfalls
  zuerst eine Sicherung an.
- Mehrere Prozesse erkennen eine Datei, die nach dem Laden extern verändert
  wurde, und brechen den Schreibvorgang ab.

## Neue Schema-Version anlegen

Bei jeder strukturellen oder semantischen Änderung:

1. Die Schema-Version genau um eins erhöhen.
2. Eine Migration unter der bisherigen Version registrieren.
3. Die Migration als reine Funktion schreiben: Eingabeobjekt kopieren,
   übersetzen und zurückgeben; keine Dateioperationen darin ausführen.
4. Den Normalisierer auf das neue Zielformat aktualisieren.
5. Tests für die direkte Vorversion und mindestens eine mehrstufige Migration
   ergänzen.
6. Testen, dass Sicherung, Originalerhalt bei Fehlern und atomisches Speichern
   weiterhin funktionieren.

Frühere Migrationen dürfen nicht gelöscht werden, solange entsprechende
Benutzerdateien noch unterstützt werden sollen.

## Regeln je Änderungstyp

- **Neue Einstellung:** Fehlt der Wert, gilt der aktuelle Standardwert.
- **Umbenennung:** Den alten Namen explizit auf den neuen Namen übertragen und
  anschließend entfernen.
- **Entfernte Funktion:** Den nicht mehr unterstützten Wert kontrolliert
  entfernen. Andere Einstellungen des Profils bleiben erhalten.
- **Einheitenänderung:** Den gespeicherten Wert während der Migration
  mathematisch umrechnen.
- **Bedeutungsänderung:** Den alten Wert nur übernehmen, wenn eine eindeutige
  Übersetzung existiert. Andernfalls auf einen sicheren Standard zurückfallen
  und einen nutzerverständlichen Hinweis vorsehen.
- **Ungültiger Einzelwert:** Nur diesen Wert verwerfen und den Standardwert
  verwenden; nicht das gesamte Profil verlieren.
- **Neueres unbekanntes Schema:** Originaldatei erhalten und den Nutzer
  informieren. Nur Werte mit stabiler Kennung und identischem
  Bedeutungsschlüssel dürfen in eine getrennte Downgrade-Arbeitsdatei
  übernommen werden.

## Sichere Änderungen während eines Downgrades

Schema 4 ergänzt `setting_compatibility`. Der Katalog ordnet jeder gemeinsam
verwendbaren Einstellung eine stabile Kennung und einen Bedeutungsschlüssel zu.
Der Schlüssel enthält insbesondere die Einheit und wird bei einer semantischen
Änderung geändert. Ein gleicher JSON-Feldname allein beweist keine
Kompatibilität.

Erkennt eine ältere Programmversion eine neuere Einstellungsdatei, bleibt diese
bytegenau unangetastet. Die ältere Version:

1. übernimmt nur Werte mit gleicher stabiler Kennung und gleichem
   Bedeutungsschlüssel;
2. prüft Typ, endliche Zahlen, Auswahlwerte, eigene Mindest- und Höchstwerte
   sowie Abhängigkeiten zwischen zusammengehörigen Feldern;
3. speichert spätere Änderungen atomar in
   `user_settings.json.downgrade-changes.json`;
4. bindet das Journal mit einem SHA-256-Hash an genau die geschützte
   Originaldatei.

Unterstützt eine spätere Programmversion das geschützte Schema wieder, prüft sie
jeden Journalwert erneut gegen ihre eigenen Regeln. Gültige Werte werden
übernommen. Ungültige, nicht mehr gleichbedeutende oder außerhalb neuer Grenzen
liegende Werte werden nicht begrenzt und nicht umgedeutet, sondern verworfen;
der gültige Wert der neueren Datei bleibt bestehen. Abhängige Geometriewerte
werden als Gruppe übernommen oder vollständig abgelehnt. Erst nach einer
erfolgreichen atomaren Speicherung wird das Journal als angewendet markiert.

Stimmt der gespeicherte Datei-Hash nicht mehr, wird das Journal nicht
automatisch angewendet. Dadurch können Änderungen aus verschiedenen
Dateiständen nicht unbemerkt miteinander kombiniert werden.

Die getrennte Änderungsübernahme steht für Programmversionen ab Schema 4 zur
Verfügung. Bereits veröffentlichte ältere Versionen können nicht nachträglich
mit dieser Logik ausgestattet werden; ihr bisheriges Schreibverbot schützt eine
unbekannte neuere Originaldatei weiterhin, zeichnet währenddessen aber keine
Änderungen für eine spätere Rückübernahme auf.

## Zukünftige Einstellungsprofile

Ein Profil erhält einen eigenen Schemaschlüssel, beispielsweise
`profile_schema_version`, und eine eigene Migrationskette. Das Profilschema darf
nicht stillschweigend an `settings_schema_version` gekoppelt werden, weil beide
Formate sich unabhängig entwickeln können.

```python
store = VersionedJsonStore(
    profile_path,
    schema_key="profile_schema_version",
    current_version=2,
    migrations={
        0: migrate_profile_0_to_1,
        1: migrate_profile_1_to_2,
    },
    normalizer=normalize_profile,
    document_name="Das Einstellungsprofil",
)
```

Ein vorhandenes Profil muss vor dem Überschreiben immer erfolgreich mit
`load()` geladen worden sein. Nur eine ausdrücklich vom Nutzer ausgelöste
Reparatur darf `replace_with_recovery()` verwenden.

## Parallelzugriffe und aktuelle Standardwerte

`VersionedJsonStore` sperrt Laden/Migrieren, Speichern und explizite Wiederherstellung
pro kanonischem Dokumentpfad. Unter Windows verwendet `document_lock` einen
benannten Kernel-Mutex; kooperierende Prozesse in derselben Windows-Sitzung und
Threads werden serialisiert. Auf POSIX wird eine advisory Dateisperre in einem
eigenen Temp-Unterordner verwendet. Rekursion im selben Thread ist erlaubt,
Wartezeiten sind begrenzt. Ein abgestürzter Windows-Prozess hinterlässt keine
permanent blockierende Sperrdatei.

Der nach dem Laden gespeicherte Vergleichsstand stammt aus exakt den gelesenen
beziehungsweise geschriebenen Bytes. Eine spätere externe Änderung wird nicht
als vermeintlich eigener Stand eingelesen. Bei erstmaliger Anlage erzeugt ein
atomarer Hardlink die Zieldatei nur, wenn sie weiterhin fehlt; eine zwischenzeitlich
angelegte Datei wird nicht ersetzt. Das setzt ein Dateisystem mit Hardlink-
Unterstützung voraus (Referenz: NTFS); andernfalls scheitert der Schreibvorgang
sicher. Backups werden exklusiv angelegt; eine fremde kollidierende Sicherung
wird bei einem Fehler nicht gelöscht. Auch Migrationssicherungen unterliegen
dem Slicer-Schreibschutz.

**Grenze:** Fremde Editoren nehmen nicht an dieser kooperativen Sperre teil.
Der Bytesvergleich erkennt Änderungen vor dem letzten Austausch. Zwischen
Prüfung und `os.replace` einer bereits vorhandenen Datei bleibt gegenüber einem
nicht kooperierenden Schreiber ein kleines Betriebssystem-Zeitfenster. Eine
vollständige dateisystemweite Compare-and-Swap-Garantie wird nicht behauptet.
Keine parallele Bearbeitung derselben Einstellungsdatei durch externe Werkzeuge
während einer Speicherung vorsehen. Netzwerkdateisysteme und unterschiedliche
Windows-Sitzungen benötigen eine gesonderte Integrationsprüfung.

Aktuelle Standardwerte für neu erzeugte Konfigurationen stehen ausschließlich in
`config/default_settings.json`; GUI, Modellkonstruktor und CLI verwenden sie.
Historische Migrationen
behalten ihre damaligen expliziten Werte. Gespeichertes Format, stabile Kennungen
und Einheiten wurden bei dieser Vereinheitlichung nicht verändert (Schema 10).
Ohne `--target-time` bleibt die CLI bewusst im Analysemodus.

## Schema 11: einstellbare Layerzeit-Toleranz

Die Migration 10→11 ergänzt `generation.layer_time_tolerance_s` mit 0,2 Sekunden.
Die Einstellung akzeptiert endliche Zahlen von 0,01 bis 3 Sekunden; ungültige
gespeicherte Werte fallen auf den Standard zurück. Vor der Migration wird das
Original gesichert, der neue Stand atomar geschrieben. Frühere Migrationsschritte
bleiben erhalten. Die stabile Kennung `generation.layer_time_tolerance_s` verwendet
den Einheitentoken `layer-time-tolerance-seconds-v1`; Downgrade-Übernahmen mit
anderen Einheiten, ungültigen Typen oder außerhalb des Zielbereichs werden verworfen.

Unter „Layerzeit und Toleranz“ gilt die Toleranz symmetrisch um die Ziel-Layerzeit.
Sie wird an die Kalibrierung übergeben und gehört zur Vorschau-Signatur. Der Export
behält die beim Generieren verwendete Toleranz für seine farbige Abweichungsanzeige.

## Schema 12: automatische Standfußhöhe

11→12 entfernt `generation.base_height_mm` und dessen Kompatibilitätskennung.
Die Sicherung vor der atomaren Migration erhält den alten Wert. Neu gespeicherte
Konfigurationen enthalten keine manuelle Fußhöhe; auch eine Downgrade-Übernahme
kann diese entfernte Einstellung nicht erneut aktivieren. Eine interne Python-
Kompatibilitätseigenschaft bleibt für historische Hohlprofil-Berechnungen erhalten,
hat aber keinen Einfluss auf die aktive Vollkörpergeometrie. Deren Regeln stehen
in [Turmgeometrie](tower_geometry.md#automatischer-standfuß).

## Schema 13: Ziel-Layerzeit und neue Standardwerte

12→13 begrenzt gespeicherte Ziel-Layerzeiten auf 30 Sekunden; ungültige Typen,
nicht endliche Zahlen und Werte unter 0,01 Sekunden werden durch 9 Sekunden
ersetzt. Die bestehende Sicherung und atomare Speicherung bleiben aktiv.
Gültige Benutzerwerte bleiben erhalten. Downgrade-Übernahmen prüfen den neuen
Bereich von 0,01 bis 30 Sekunden und verwerfen inkompatible Werte.

Bei Einführung des Schemas verwendeten neue Einstellungen und Zurücksetzen
eine Ziel-Layerzeit von 9 s. Der aktuelle, zentral in
`config/default_settings.json` gepflegte Produktstandard beträgt 9 s. Er gilt
für neue Konfigurationen und das Zurücksetzen; gespeicherte gültige Benutzerwerte
bleiben unverändert. Dieser Standardwechsel benötigt keine Schemamigration. Die
weiteren damaligen Vorgaben waren Toleranz ±0,25 s,
minimaler Turmdurchmesser 5 mm, Verjüngungswinkel 55°, Objektabstand 15 mm und
Zeit-Sicherheitsfaktor 1,0. Diese historischen Vorgaben wurden in Schema 16
durch die feste 5-mm-Platzierungsregel und den Verzicht auf den Sicherheitsfaktor
ersetzt.
Historische Migrationen behalten ihre damaligen Standardwerte.

## Schema 14: maximale gemeinsame Slices

13→14 ergänzt die stabile UI-Einstellung `maximum_joint_slices`. Sie steuert
nach den sechs getrennten Turm-Slices das Budget der vollständigen gemeinsamen
Objekt-/Turm-Slices. Der Standardwert ist 10; gespeichert und übernommen werden
nur Ganzzahlen von 5 bis 25. Ungültige Werte fallen auf 10 zurück.
Dies beschreibt die historische Migration; der aktuelle Produktstandard für
neue Konfigurationen und „Standardwerte wiederherstellen“ ist 12. Gespeicherte
gültige Benutzerwerte behalten ihren Wert. Der Standardwechsel ändert weder
Schema noch Bedeutung des Feldes.

Die Kompatibilitätskennung `maximum_joint_slices` verwendet den Token
`joint-slice-budget-v1`. Die Einstellung gehört zur Vorschau-Signatur, sodass
eine Änderung einen zuvor generierten Stand korrekt als veraltet markiert.
Sicherung, schrittweise Migration und atomisches Schreiben entsprechen den
vorherigen Schemata.

## Schema 15: optionale Eingabegrenzen

14→15 ergänzt `show_setting_limits` mit Standard `false`. Die Einstellung
steuert ausschließlich die Darstellung der Grenzwerte unter Zahlenfeldern;
Validierungen bleiben unverändert aktiv. Nur echte boolesche Werte werden
akzeptiert, Zeichenketten und Zahlen fallen auf `false` zurück. Bei verborgenen
Grenzen reserviert das Layout keinen Platz für die Hinweiszeile.

Der Kompatibilitätstoken lautet `numeric-limits-visibility-v1`. Eine Übernahme
nach Downgrade setzt gleichen Token und booleschen Typ voraus; numerische
Wertebereiche und Einheiten sind für diese Darstellungseinstellung nicht
anwendbar. Die bestehenden Schutzregeln für Sicherung, atomare Speicherung,
beschädigte, extern geänderte und neuere Dateien bleiben erhalten. Die Verlagerung
des Exportordners in die allgemeinen Einstellungen ändert dessen gespeichertes
Format nicht.

## Schema 16: automatische Geometrieparameter

15→16 entfernt `generation.safety_factor` und `generation.mesh_segments` sowie
deren Downgrade-Kompatibilitätskennungen. Frühere Werte werden nicht übernommen.
`generation.minimum_object_tower_distance_mm` wird auf 5 mm gesetzt und ist
nicht mehr als Eingabe oder Downgrade-Wert verfügbar. Die Sicherung des Originals
und das atomare Schreiben laufen vor beziehungsweise nach der direkten Migration
über `VersionedJsonStore`; alle früheren Migrationsschritte bleiben erhalten.

## Schema 17: Untergrenzen der Layerzeiten

16→17 hebt gespeicherte Ziel-Layerzeiten unter 5 s auf 5 s und gespeicherte
Layerzeit-Toleranzen unter 0,1 s auf 0,1 s an, sofern sie im bisherigen
gültigen Bereich lagen. Andere gültige Werte bleiben erhalten. Ungültige
Werte fallen bei der Normalisierung auf die aktuellen Standardwerte zurück.
Die Downgrade-Übernahme akzeptiert für diese Kennungen nur noch 5–30 s
beziehungsweise 0,1–3 s; Kennungen und Einheitentoken bleiben gleich.
`VersionedJsonStore` sichert das Original vor der direkten oder mehrstufigen
Migration und schreibt die neue Fassung atomar. Die zusätzliche, vom
Pre-Slice-Ergebnis abhängige Ziel-Untergrenze gehört zur GUI-Validierung und
wird nicht in den Einstellungen gespeichert.

## Schema 18: Durchmessergrenzen

17→18 begrenzt gespeicherte minimale Turmdurchmesser auf 3–99 mm und maximale
Turmdurchmesser auf 5–100 mm. Liegt das Maximum weniger als 1 mm über dem
Minimum, wird das Minimum bei der Migration auf `Maximum − 1 mm` abgesenkt;
das bisherige Maximum bleibt dadurch soweit möglich erhalten. Bereits gültige
Werte bleiben unverändert. Direkte und mehrstufige Migrationen nutzen weiterhin
Sicherung und atomisches Schreiben. Die Downgrade-Übernahme prüft die neuen
Einzelgrenzen und den Abstand von mindestens 1 mm als gemeinsame Gruppe.

## Schema 19: maximale getrennte Slices

18→19 ergänzt die stabile UI-Einstellung `maximum_separate_slices`. Sie legt
das Budget der getrennten Turm-Slices vor der gemeinsamen Objekt-/Turm-Phase
fest. Der Standardwert ist 6; gespeichert und übernommen werden ausschließlich
Ganzzahlen von 1 bis 25. Ungültige Werte fallen auf 6 zurück. Der
Kompatibilitätstoken `separate-slice-budget-v1` erlaubt eine Downgrade-Übernahme
nur bei identischer Bedeutung und gültigem Wertebereich.

`maximum_separate_slices`, `maximum_joint_slices`, das lokale Zeitfenster,
die Anzeige numerischer Grenzen und der Exportordner gehören zu
„Allgemeine Einstellungen“. Der globale
Button „Standardwerte wiederherstellen“ verändert diese Werte nicht; jeder
dieser Werte kann über seinen zugehörigen Einzel-Reset oder den gemeinsamen
Reset links unten im Dialog zurückgesetzt werden. Die Änderungen werden erst
mit „Übernehmen“ angewendet.

## Schema 20: Simulation ohne Turmstützen

19→20 ergänzt `simulate_tower_without_supports` mit dem Standardwert `false`
und dem stabilen Bool-Kompatibilitätstoken `tower-support-simulation-v1`.
Beim Laden alter Einstellungen wird die neue Option deaktiviert ergänzt;
Migrationen sichern die Originaldatei und schreiben atomar. Gespeicherte
Slice-Budgets werden seit dieser Programmversion auf 1–15 getrennte und
5–20 gemeinsame Slices begrenzt; zu große Altwerte fallen auf die jeweiligen
Standardwerte 6 und 12 zurück. Das lokale Zeitfenster verbleibt semantisch
unverändert im Generierungsteil des gespeicherten Formats, erscheint aber
in den allgemeinen Einstellungen und wird vom globalen Reset ausgenommen.

## Schema 21: maximale Standfußbreite

20→21 begrenzt die manuelle Standfußbreite auf 80 mm. Gespeicherte größere
Werte werden auf 80 mm gesetzt; kleinere gültige Werte bleiben erhalten.
Die automatische Breite verwendet jetzt 0,21 mm je 1 mm Original-Objekthöhe
und bleibt zwischen 25 und 80 mm. Die Migration sichert die Originaldatei
vor dem atomaren Schreiben. Bei Downgrade-Übernahmen werden Werte über 80 mm
verworfen.

## Schema 22: Profilbindung des Aufweitungswinkels

21→22 ergänzt `generation.limit_expansion_to_profile` als strikt boolesche,
anfangs deaktivierte Option. Bestehende Winkel werden **nicht** numerisch
umgeschrieben: Gespeicherte Werte und Geometrie-APIs behalten ihren vertikalen
Bezug; Oberfläche und CLI rechnen an der Ein-/Ausgabe zur Horizontalen um.
Dadurch ändern Upgrade, Downgrade oder Rücksetzen keine vorhandene Turmform.
Die bisherigen Kompatibilitätskennungen der Winkel bleiben gültig.

Bei aktiver Bindung wird der freie Winkel gespeichert; der effektive Winkel
wird erst aus dem bestätigten aktuellen Prozessprofil abgeleitet. Damit kann
ein alter Profilwert keinen anderen Slicer-/Profilkontext überschreiben. Die
neue Option besitzt eine eigene stabile Kompatibilitätskennung. Unbekannte
neuere Dateien, externe Änderungen und beschädigte Dateien behalten die
bisherigen Schutzregeln einschließlich Sicherung und atomarem Schreiben.

## Schema 23: Segmentwahl für iterativ erzeugte Türme

22→23 ergänzt `generation.automatic_circle_segments` als boolesche, anfangs
aktivierte Option und `generation.circle_segments` als manuelle Ganzzahl mit
Standardwert 32. Zulässig sind 4 bis 256 Segmente. Die Migration erhält das
bisherige automatische Verhalten; die manuelle Zahl bleibt beim Umschalten
unverändert. Die Anzeige „auto“ beziehungsweise die Segmentzahl des zuletzt
übernommenen Turms ist reine Sitzungsinformation und wird nicht gespeichert.

Der Originalstand wird vor dem atomaren Umschreiben gesichert. Ungültige Typen
oder Zahlen außerhalb beider Grenzen fallen beim Laden auf die Produktstandards
zurück. Die Kompatibilitätstoken `automatic-circle-segments-v1` und
`circle-segments-count-v1` binden beide Werte an eine validierte Gruppe.
Downgrades übernehmen ausschließlich boolesche Aktivierung und Ganzzahlen im
Zielbereich bei gleicher Bedeutung; Gradangaben oder andere Einheiten sind
inkompatibel. Neuere, beschädigte und extern geänderte Originaldateien bleiben
nach den allgemeinen Schutzregeln erhalten.

## Schema 24: getrennte Exportordner

23→24 ergänzt `export_roots` mit den stabilen Methodenkennungen `automatic`,
`manual` und der damaligen Kennung der dritten Methode. Die Migration leitet unterhalb des bisherigen
`output_root` je einen gleichnamigen Unterordner ab. Vorhandene Exporte werden
weder verschoben noch verändert. Ohne gültigen bisherigen Pfad gelten die
Standardordner der Anwendung. `output_root` bleibt als Schnittstelle zum
Exportpfad der iterativen Methode erhalten und wird bei der Migration auf diesen gesetzt.
Sein neues Kompatibilitätstoken `automatic-export-directory-path-v2` verhindert,
dass eine ältere Version ihren gemeinsamen Exportpfad ungeprüft auf die drei
unabhängigen Ziele überträgt.

Jeder Methodenpfad lässt sich in den allgemeinen Einstellungen unabhängig
auswählen und auf `output/<Methode>` im Datenverzeichnis der Anwendung
zurücksetzen. Nur nicht leere Pfadzeichenketten ohne Steuerzeichen sind gültig.
Ungültige Einzelwerte fallen auf den Methodenstandard zurück. Die neuen
Kompatibilitätskennungen `export_roots.<Methode>` verwenden jeweils das Token
`method-export-directory-path-v1`; andere Typen oder Bedeutungen werden auch
bei Downgrade-Übernahmen abgewiesen. Bestehende Migrationsschritte, Sicherung,
atomare Speicherung und Schutz vor neueren, beschädigten oder extern
veränderten Dateien bleiben wirksam.

## Schema 25: Postprozessor-Standardordner

24→25 ändert den früheren Standardunterordner der dritten Methode zu `postprocessor`.
Die interne Methodenkennung und die gültige Bedeutung eigener Pfade bleiben
erhalten. Umgestellt wird ein alter Pfad mit dem damaligen Methodennamen als letztem
Bestandteil, wenn mindestens ein anderer Methodenpfad noch dessen gemeinsamer
Standardstruktur `automatic` beziehungsweise `manual` entspricht. Abweichende
eigene Ziele bleiben unverändert.

`VersionedJsonStore` sichert das Original vor der Migration und schreibt atomar.
Exporte werden nicht verschoben oder zusammengeführt. Die Exporthistorie kann
zusätzlich den früheren Geschwisterordner lesen, damit alte Ergebnisse nach der
Umstellung erreichbar bleiben. Die bisherigen Typ-/Einheiten-/Pfadprüfungen
sowie Schutz und Wiederherstellung beschädigter, neuerer oder extern geänderter
Dateien gelten unverändert. Postprozessor-Druckparameter bleiben sitzungsgebunden
und sind von dieser Pfadmigration unabhängig.

## Getrennte manuelle Einstellungen (eigenes Schema 19)

`manual_settings.json` verwendet den eigenen Schlüssel
`manual_settings_schema_version` und `VersionedJsonStore`. Das bestehende
gemeinsame Format verwendet Schema 27. `ManualSettingsStore` normalisiert
strikte boolesche Werte, endliche Zahlen, gekoppelte Durchmessergrenzen und
gültige Zeit-/Defizitwerte einschließlich ihrer Abhängigkeit.
18→19 ergänzt die zunächst deaktivierte Option `limit_expansion_to_profile`.
Auch hier bleiben gespeicherte Winkel vertikal, und bei aktiver Bindung wird
der freie Wert gespeichert. Neue und bestehende Dateien werden ausschließlich
über `VersionedJsonStore` verarbeitet; die Originaldatei wird vor Migrationen
gesichert.
Die explizite Legacy-Migration 0→1 ergänzt den Schemaschlüssel. 1→2 ersetzt
`target_layer_time_s` durch `color_reference_time_s` und entfernt
`layer_time_tolerance_s`. Die bisherige Zielzeit dient damit ausschließlich als
Farbreferenz für Originalschichten, nicht als Bewertung des manuellen Turms.
Gültige Werte von 5–30 s bleiben erhalten; inkompatible Typen, nicht endliche
Zahlen, andere Einheiten und Werte außerhalb dieses Bereichs fallen auf den
Standard zurück. Andere gültige manuelle Werte bleiben erhalten.
2→3 ergänzt `layer_snap_enabled` mit dem Standard `true`. Das boolesche
Feld steuert ausschließlich vertikale Greiferbewegungen; vorhandene numerische
Geometriepräferenzen bleiben unverändert. Im aktuellen Schema wird auch ein
ausgeschalteter Toggle gespeichert; andere Typen werden nicht als boolesche
Werte interpretiert und fallen auf den aktivierten Standard zurück.
3→4 ergänzt `object_resolution_percent` mit dem Standard `50`. Der Wert
steuert ausschließlich die räumliche Darstellung des Originalobjekts; er ist
in Schema 4 ein strikter Integer von 10 bis 100 in Zehnerschritten.
Vorhandene gültige Einstellungen einschließlich eines ausgeschalteten
Layer-Snappings bleiben erhalten. Bei 100 wird die volle Originalauflösung
angezeigt; Druckdaten und Artefaktsignaturen hängen nicht von dieser Präferenz ab.
4→5 ersetzt die lineare Stufenfolge durch `1, 3, 5, 10, 15, 20, 25, 50, 75, 100`.
Vorhandene gültige Prozentwerte werden auf die nächste unterstützte Stufe abgebildet;
bei gleichem Abstand gewinnt die präzisere Stufe. Bereits unterstützte Werte bleiben
erhalten, etwa 50 oder 100. Alte ungültige Typen, Einheiten und Werte außerhalb
der damaligen Zehnerschritte fallen auf den damaligen Standard 10 zurück. In Schema 5
werden ausschließlich diese zehn strikten Integer-Stufen akzeptiert; der
Standard entspricht dort Sliderposition 4 (10 %). Neue Dateien starten
mit diesem Standard, bestehende gültige Präferenzen behalten ihren Prozentwert
bzw. dessen nächstgelegene Stufe. Die Änderung des Standardwerts von 15 auf 10 %
ändert weder Format noch Bedeutung gespeicherter Prozentwerte und benötigt
deshalb keine zusätzliche Schemamigration.
5→6 ersetzt die 20-%-Netzstufe durch die neue 0-%-Silhouette. Die Folge in Schema 6
lautet `0, 1, 3, 5, 10, 15, 25, 50, 75, 100`; 0 ist eine exakte flache
Konturdarstellung und keine Netzreduktion auf null Dreiecke.
Gültige alte 20-%-Werte werden zu 25 % migriert; alle anderen gültigen Stufen
bleiben erhalten. In Schema 5 ungültige Werte, insbesondere 0, boolesche Werte,
Fließkommazahlen und abweichende Einheiten, werden auf den Standard 10
normalisiert. In Schema 6 ist der strikte Integer 0 gültig, 20 dagegen
ungültig. Der damalige Standard 10 % liegt dort auf Sliderposition 5.
Die historische 4→5-Migration verwendet weiterhin ihre damalige Stufenfolge,
bevor 5→6 ausgeführt wird. Eine alte Programmversion mit Schema 5 darf die neue
Datei einschließlich 0-%-Werten weder übernehmen noch überschreiben.
Die manuellen Downgrade-Prüfungen blockieren auch inkompatible Typen, andere
Einheiten und Werte außerhalb der jeweiligen Stufengrenzen vollständig.
6→7 reduziert die Skala auf `0, 5, 10, 15, 25, 50, 75, 100`.
Vorher gültige 1-%- und 3-%-Werte werden zu 5 %; 0 % und alle übrigen gültigen
Werte bleiben erhalten. In Schema 6 ungültige Typen, Einheiten oder Werte
fallen beim Migrationsschritt weiterhin auf den damaligen Standard 10 zurück.
Neue Dateien und ungültige Werte in Schema 7 verwenden 0 %.
Die Oberfläche verwendete damals je Ansicht unterschiedliche Standards: 0 % für
Nebeneinander/Voreinander, 15 % für die anderen Ansichten. Bestehende gültige
individuelle Prozentwerte bleiben erhalten; die Ansichtsstandards verändern
weder die Bedeutung noch die Einheit der gespeicherten Werte. Einzel- und
Gesamt-Reset beachteten die aktuelle Ansicht. Die Ansicht selbst wird nicht gespeichert.
Auch ältere Programmversionen mit Schema 6 dürfen Dateien mit Schema 7 nicht
übernehmen oder überschreiben. Der historische Rückfallwert 10 bleibt in allen
früheren Auflösungsmigrationen festgeschrieben.
7→8 ergänzt die 1-%-Stufe zwischen 0 und 5. Alle in Schema 7 gültigen strikten
Integer-Stufen bleiben erhalten; dort ungültige Werte (auch 1 und 3), Typen oder
Einheiten fallen auf 0 % zurück. Erst Schema 8 akzeptiert den strikten Integer 1.
Die historischen 6→7-Regeln bleiben erhalten: Eine ursprünglich dort gespeicherte
1-%- oder 3-%-Wahl wird bei einem mehrstufigen Sprung weiterhin zuerst zu 5 %.
Schema 8 verwendete dieselben ansichtsabhängigen Standards. Ältere Versionen mit
Schema 7 dürfen neue Dateien einschließlich 1-%-Werten nicht lesen oder überschreiben.
8→9 ändert die Bedeutung positiver `object_resolution_percent`-Werte: Sie sind
nun Gewichtungen der automatischen Vorschauqualität zwischen Performance und
Optik, keine gewünschten Flächenprozente. 0 bleibt die Originalsilhouette.
Alle in Schema 8 gültigen strikten Integer-Stufen bleiben als entsprechende
Präferenz erhalten; ungültige Werte/Typen/Einheiten fallen auf 0 zurück.
Die damaligen Ansichtsstandards und Druck-/Artefaktdaten bleiben bei der Migration
unverändert. Ältere Versionen mit Schema 8 dürfen Schema 9 nicht lesen oder überschreiben, damit eine
Qualitätspräferenz nicht als früheres Flächenbudget interpretiert wird.
9→10 setzt die Untergrenze für `minimum_diameter_mm` auf 1,00 mm. Alte endliche,
positive Durchmesser unter 1 mm werden auf 1 mm angehoben, einschließlich der
zugehörigen Maximal-/Standfußwerte, damit zuvor gültige kleine Durchmessergruppen
konsistent bleiben. Typen, Einheiten oder Werte, die bereits im alten Schema
ungültig waren, werden weiterhin streng normalisiert. Andere gültige Präferenzen
bleiben erhalten. Ältere Versionen dürfen Schema 10 weder übernehmen noch überschreiben.
10→11 ersetzt die bisherigen Defizitgrenzen durch absolute Layerzeiten für die
manuelle Einfärbung. `color_reference_time_s` ist nun die grüne Obergrenze
(5–30 s), `color_red_time_s` die absolute Rotgrenze (größer als die grüne Grenze,
maximal 60 s). Die Oberfläche zeigte in Schema 11 die Differenz beider gespeicherten Werte
als „Zeitüberschreitung bis Rot“ an; 10/14 s erschienen dort als 10 s plus 4 s.
Das Speicherformat und seine Semantik blieben bei dieser Darstellung unverändert. Bis zur grünen Grenze bleibt das Original grün; darüber wird
linear zu Rot interpoliert. Die frühere Defizitbewertung hatte die umgekehrte
Farbrichtung. Ihre gültige Farbreferenz bleibt als gewünschte Layerzeit erhalten;
die Breite `gradient_full_deficit_s - gradient_start_deficit_s` wird zur neuen
Zeit bis Rot addiert. Die beiden alten Defizitfelder entfallen. Ungültige alte
Farbgrenzen verwenden einen Übergang von 1 s. Beispiel: Referenz 12 s,
Defizitbeginn 0,5 s und vollständig Rot ab 2 s werden zu Grün bis 12 s und
Rot ab 13,5 s. Die Abbildung erhält die Übergangsbreite, nicht die alte
Farbaussage. Andere gültige Präferenzen bleiben erhalten. Der Bereichseditor
verwendet weiterhin seine eigene Defizitbewertung; seine Darstellung wird über
separate, nicht persistierte Farbeinstellungen an denselben Renderer übergeben.
Ältere Versionen mit Schema 10 dürfen die neue Datei weder interpretieren noch
überschreiben; automatische Übernahmen gleichnamiger Farbwerte sind wegen der
geänderten Semantik nicht zulässig.
11→12 korrigiert die Farbrichtung auf kürzere, defizitäre Layerzeiten.
`color_reference_time_s` bleibt die gewünschte Layerzeit (Standard 10 s).
Das neue Feld `color_deficit_time_s` speichert einen positiven Defizitbetrag
(Standard 4 s; validierte Werte größer als 0 bis 60 s). `color_red_time_s`
entfällt im Dokument und wird im Modell ausschließlich als
`color_reference_time_s - color_deficit_time_s` abgeleitet. Layer ab der
gewünschten Zeit sind grün, ab dem vollen Defizit und darunter rot.
Einzelresets stellen unabhängig 10 s beziehungsweise 4 s wieder her.

Die Migration validiert den alten absoluten Sekundenwert streng nach den
Schema-11-Regeln und übernimmt bei gültigen Werten die Übergangsbreite
`alte Rotgrenze - gewünschte Layerzeit` als positiven Defizitbetrag. Beispiel:
10/14 s wird zu 10 s gewünschter Layerzeit und 4 s Defizit, mit Rot bei 6 s
oder weniger. Die Übergangsbreite bleibt erhalten; die Farbaussage kehrt sich
bewusst um. Fehlende/ungültige alte Rotgrenzen verwenden 4 s, ungültige
Referenzen 10 s. Typen, andere Einheiten, nicht endliche Zahlen und damalige
Grenzverletzungen werden nicht als gültige Werte übernommen. Andere gültige
Einstellungen bleiben erhalten. Aktuelle Referenz- und Defizitwerte werden
unabhängig normalisiert. Ältere Versionen mit Schema 11 dürfen Schema 12
weder lesen noch überschreiben oder gleichnamige Farbwerte automatisch
zurückübernehmen.
12→13 begrenzt `circle_segments` auf maximal 256. Nach den alten Regeln gültige
Integerwerte 257–720 werden auf 256 korrigiert; Typen und schon zuvor ungültige
Werte erhalten weiterhin den sicheren Standard. Der positive interne Defizitwert
bleibt gespeichert, darf aber die grüne Layerzeit nicht mehr übersteigen:
damit ist die daraus abgeleitete absolute Rotgrenze nie negativ. Gültige alte
Defizite über der grünen Zeit werden auf diese begrenzt (Rot bei 0 s).
Die Oberfläche zeigt jetzt zuerst die absolute Rotgrenze (Standard 6 s), dann
die absolute grüne Layerzeit (Standard 10 s); beide Einzelresets arbeiten mit
diesen absoluten Werten. Aktuelle grüne Referenz und Defizit werden in ihrer
Abhängigkeit validiert. Ältere Versionen mit Schema 12 dürfen Schema 13 weder
lesen noch überschreiben; eine automatische Rückübernahme ist nicht freigegeben.

13→14 ergänzt `color_scale_max_time_s` als rein visuelles Ende der Layerzeit-Farbskala.
Der Standard ist 14 s; liegt die bisherige gültige grüne Zeit höher, wird die
Skala mindestens bis zu ihr erweitert (auf den nächsten 0,1-s-Schritt aufgerundet).
Beide bestehenden Farbgrenzen, ihre Bedeutung und ihre Präzision bleiben erhalten.
Das neue Feld muss endlich, mindestens so groß wie die grüne Zeit und höchstens
3600 s sein. Es wird in 0,1-s-Schritten normalisiert. Ungültige Typen, fremde
Einheiten und unzulässige Werte erhalten den passenden sicheren Standard.
Die Oberfläche verwendet jetzt Greifpunkte statt der beiden separaten Zeitfelder;
die Skala wird mitgespeichert, wirkt aber weder auf Druckartefakte noch auf
Modellgeometrie. Schema 13 darf die neue Datei weder lesen noch überschreiben;
eine automatische Rückübernahme ist nicht freigegeben.

14→15 erweitert die gültige grüne Layerzeit von 5–30 s auf 3–30 s. Dadurch
kann das Skalenende in der Oberfläche bis auf 3 s sinken; darüber liegende
Farbgrenzen werden gemeinsam und mit mindestens 0,1 s Abstand angepasst.
Der linke Skalenstart bleibt 0 s. Der gespeicherte Endwert muss weiterhin
mindestens die grüne Grenze umfassen. Die Migration erhält sämtliche zuvor
gültigen Zeiten einschließlich ihrer Präzision. In Schema 14 ungültige grüne
Werte unter 5 s werden nicht nachträglich gültig, sondern erhalten den sicheren
Standard 10 s. Bei neuen gültigen grünen Zeiten unter 4 s wird ein ungültiges
Defizit auf höchstens diese Referenz begrenzt, damit Rot niemals negativ wird.
Ältere Versionen mit Schema 14 dürfen Schema 15 weder lesen noch überschreiben;
eine automatische Rückübernahme ist nicht freigegeben.

15→16 ersetzt die feste Skalenobergrenze von 3600 s durch eine objektabhängige
Bediengrenze: normalerweise 60 s, bei längeren Original-Layerzeiten höchstens
deren tatsächliches Maximum (auf 0,1 s abgerundet). Diese Grenze wird beim
Laden des vorbereiteten Originals einmal berechnet, nicht als Objektdatum in
den wiederverwendbaren Einstellungen gespeichert. Gültige gespeicherte
Endwerte bleiben bei der Migration erhalten und werden erst mit bekanntem
Objekt auf dessen zulässige Obergrenze begrenzt. So bleiben Werte für Objekte
mit Layerzeiten über 60 s auch nach einem Neustart nutzbar. Für die Ausnahme
sind nun auch endliche Endwerte über 3600 s erlaubt; in Schema 15 unzulässige
Werte über 3600 s erhalten bei der Migration weiterhin den sicheren Standard.
Typen, Einheit und 0,1-s-Schritte werden wie bisher validiert. Die Obergrenze
greift bei direkter Eingabe, Pfeiltasten, Laden, Objektwechsel und Undo.
Schema 15 darf die neue Datei weder lesen noch überschreiben; eine automatische
Rückübernahme ist nicht freigegeben.

16→17 erweitert auch die grüne Zeitgrenze von bisher 3–30 s auf dieselbe
objektabhängige Obergrenze wie das Skalenende: normalerweise 60 s, bei längeren
Original-Layerzeiten deren Maximum, auf 0,1 s abgerundet. Gespeichert wird
weiter die absolute grüne Referenz plus positives Defizit. Die Normalisierung
prüft endliche Werte, Referenz mindestens 3 s, nichtnegative rote Grenze und
ein Skalenende, das die Referenz umfasst. Erst der geladene Originalkontext
bestimmt die konkrete Obergrenze; kleinere Objektgrenzen korrigieren alle
betroffenen Werte gemeinsam. Zuvor gültige Werte und ihre Präzision bleiben
erhalten; in Schema 16 ungültige grüne Referenzen über 30 s fallen weiterhin
auf 10 s zurück. Schema 16 darf die neue Datei weder lesen noch überschreiben;
eine automatische Rückübernahme ist nicht freigegeben.
Die neue Minimum-Markierung wird aus den Originaldaten abgeleitet und erzeugt
keine zusätzliche Einstellung oder Formatänderung.

17→18 erlaubt `color_deficit_time_s = 0` als gemeinsame rote/grüne Grenze.
Die Darstellung schaltet dann unter der Referenz auf Rot und ab einschließlich
der Referenz auf Grün; Leiste und Modell verwenden dieselbe harte Grenze ohne
Division durch eine Übergangsbreite. Beide Greifer bleiben getrennt bedienbar,
die Überschrift „Übergang“ entfällt. Aktuelle Defizite werden als endliche Zahlen
von 0 bis zur grünen Referenz validiert. Zuvor gültige positive Defizite bleiben
erhalten. Da 0 in Schema 17 ungültig war, ersetzt die Migration solche alten
Einträge weiterhin durch den damaligen sicheren Standard (höchstens 4 s).
Schema 17 darf die neue Datei weder lesen noch überschreiben; eine automatische
Rückübernahme ist nicht freigegeben.

Vor direkten und mehrstufigen Migrationen 0→1→2→3→4→5→6→7→8→9→10→11→12→13→14→15→16→17→18 wird das Original gesichert,
anschließend atomar gespeichert. Alle früheren Migrationsschritte bleiben erhalten.

Der aktuelle Oberflächenstandard beträgt in allen Ansichten 75 %; Einzel- und
Gesamt-Reset verwenden ebenfalls 75 %. Neue Einstellungen und ungültige Werte
bei der Normalisierung im aktuellen Schema erhalten diesen Standard. Bestehende
gültige individuelle Werte und alle historischen Migrationsregeln bleiben erhalten.
Diese Standardänderung verändert weder Format, Einheit noch Bedeutung gespeicherter
Qualitätspräferenzen und benötigt keine zusätzliche Schemamigration. Die Bedienung ist in
[manual_editor.md](manual_editor.md) beschrieben.

Unbekannte neuere oder beschädigte Dateien sperren jede Speicherung;
zwischenzeitliche externe Änderungen werden vom vorhandenen Bytesvergleich
erkannt. Explizite Wiederherstellung nutzt `replace_with_recovery()` mit Backup.
Die manuelle Datei hat keinen gemeinsamen Kompatibilitätskatalog mit der
iterativen Methode: Downgrades können manuelle Werte niemals anhand ähnlicher Feldnamen
in Werte der iterativen Methode übernehmen. Neue manuelle Schemata benötigen eine direkte
Migration und die bestehenden Sicherungs-/Fehler-/Downgrade-Prüfungen.

Gespeichert werden wiederverwendbare manuelle Werte einschließlich der eigenen
Kreissegmentzahl. Profilpunkte, Turmhöhe, Quellidentität, laufende Aufträge,
Artefakte und Exportidentitäten bleiben ausschließlich sitzungsgebunden.
Beim Initialisieren eines neuen Quellenkontexts wird der aktuelle Fußdurchmesser
aus der vollständigen Originalhöhe neu berechnet. Der numerische gespeicherte
Fußwert und seine Einheit bleiben unverändert; er liefert keinen quellenunabhängigen
Startwert mehr. Automatisch erweiterte Fußgrenzen bleiben gültige Millimeterwerte;
deren Resetstandard ist an das aktuelle Objekt gebunden und wird nicht separat
persistiert. Diese Initialisierungs-/Resetregeln verändern das gespeicherte Format
und dessen Wertebereiche nicht.

## Schema 26: Postprozessor-Methodenkennung

25→26 benennt den gespeicherten Methodenschlüssel in `export_roots.postprocessor`
um. Gültige eigene Pfade behalten ihren Wert; bei gleichzeitig vorhandenen
alten und aktuellen Schlüsseln hat der aktuelle Schlüssel Vorrang. Frühere
Schritte bleiben vorhanden. Originaldateien werden vor der Migration gesichert
und atomar aktualisiert; neuere, beschädigte oder extern geänderte Dateien
bleiben geschützt.

Die ausdrücklich kompatible Pfadbedeutung verwendet weiterhin das Token
`method-export-directory-path-v1`. Frühere Änderungsjournale und geschützte
neuere Einstellungen werden über die zentrale historische Kennung eingelesen.
Typ-, Token- und Pfadvalidierung gelten vor jeder Übernahme; ein historischer
Schlüssel überschreibt keinen gleichzeitig vorhandenen aktuellen Wert.
Neue Berichte und Programmkennungen verwenden ausschließlich `postprocessor`.

## Schema 27: Standardnamen der Exportordner

26→27 stellt die bisherigen Methodenordner auf folgende Standardnamen um:

| Methode | Standardordner unter `output/` |
|---|---|
| Iterativ | `exports_automatic_mode` |
| Manuell | `exports_manual_mode` |
| Postprozessor | `exports_postprocessor` |

Die internen Methodenkennungen bleiben unverändert. Erkannt werden die bekannten
Pfade im Standarddatenverzeichnis sowie gemeinsame frühere Standardstrukturen.
Abweichende eigene Ziele behalten ihren Wert. `output_root` folgt weiterhin dem
Exportpfad der iterativen Methode. Alle vorigen Migrationsschritte bleiben
vorhanden; Sicherung, atomare Speicherung, Typ-/Pfadprüfung und der Schutz
neuerer, beschädigter oder extern geänderter Dateien bleiben wirksam.

Die Exporthistorie berücksichtigt für jede Methode zusätzlich ihre früheren
Geschwisterordner. Vorhandene Berichte bleiben auch nach einer Ordnerumbenennung
lesbar: Die Druckdatei wird relativ zum Berichtordner gefunden, ohne historische
Berichte umzuschreiben. Ordnerauswahl und Standardwert-Reset verwenden dieselbe
zentrale Zuordnung. Eine automatische Zusammenführung alter Exportinhalte findet
bei der Einstellungsmigration nicht statt.
