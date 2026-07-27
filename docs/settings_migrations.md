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
