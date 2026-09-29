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
`config/default_settings.json` gepflegte Produktstandard beträgt 10 s. Die
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
