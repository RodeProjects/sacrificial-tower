# Repository-Regeln

## Versionierung und Push-Freigabe

- Für jeden Push muss eine vorhandene Versionsnummer in der Form `x.y.z` vor
  dem Commit erhöht werden, indem ausschließlich die letzte Zahl (`z`) um `1`
  steigt. Diese Versionserhöhung muss im selben Commit und Push wie die
  zugehörigen Änderungen enthalten sein.
- Maßgeblich ist die zuletzt gepushte Version: Ist die lokale Versionsnummer
  bereits genau um `1` höher, wird sie in den nächsten Commit aufgenommen und
  nicht ein zweites Mal erhöht.
- Die ersten beiden Versionsbestandteile (`x.y`) dürfen nur geändert werden,
  wenn der Benutzer dies ausdrücklich anweist.
- Der letzte Versionsbestandteil (`z`) läuft fortlaufend weiter und darf nur
  dann von neuem beginnen beziehungsweise zurückgesetzt werden, wenn im selben
  Versionswechsel mindestens einer der vorangestellten Bestandteile (`x` oder
  `y`) auf eine höhere Zahl gesetzt wird.
- Vor jedem Push muss dem Benutzer zuerst die vorgesehene Commit-Message
  ausgegeben werden. Sie muss die zu pushenden Änderungen zusammenfassen.
- Commit-Messages müssen sprachlich einheitlich und überwiegend auf Deutsch
  formuliert sein. Eigennamen, etablierte Anglizismen und fachsprachliche
  Begriffe dürfen auf Englisch bleiben; die Hauptsprache der gesamten
  Commit-Message muss Deutsch sein.
- Aktualisierungen dieser Anwendung werden als „Programmaktualisierung“ oder
  „Sacrificial-Tower-Update“ bezeichnet. Der Ausdruck „Windows-Update“ bleibt
  Aktualisierungen des Windows-Betriebssystems vorbehalten; für das gebaute
  Installationspaket ist „Windows-Installer“ zu verwenden.
- Ein Push darf erst erfolgen, nachdem der Benutzer ihn ausdrücklich erlaubt
  hat. Ohne diese Freigabe weder pushen noch sie aus dem Kontext ableiten.

## Migration von Benutzerdaten

- Persistierte Benutzereinstellungen und zukünftige Einstellungsprofile müssen
  über `VersionedJsonStore` geladen und atomar gespeichert werden.
- Jede strukturelle oder semantische Änderung eines gespeicherten Formats muss
  dessen Schema-Version genau um `1` erhöhen und eine explizite Migration von
  der direkten Vorversion registrieren. Frühere Migrationsschritte dürfen nicht
  übersprungen oder ohne ausdrückliche Aufgabe entfernt werden.
- Vor migrationsbedingten Umschreibungen muss das Original gesichert werden.
  Unbekannte neuere, beschädigte oder zwischenzeitlich extern veränderte Dateien
  dürfen nicht automatisch überschrieben werden.
- Bei der Zusammenführung von Einstellungen nach einem Downgrade dürfen nur
  Werte mit stabiler Kennung und ausdrücklich bestätigter semantischer
  Kompatibilität übernommen werden. Jeder einzelne Kandidat muss zuvor nach
  den Typen, Wertebereichen, Einheiten, Abhängigkeiten und sonstigen Regeln der
  Zielversion normalisiert und validiert werden. Ein zuletzt geänderter Wert
  hat niemals Vorrang vor diesen Sicherheitsregeln.
- Ist ein während des Downgrades geänderter Wert in der neueren Zielversion
  ungültig oder nicht eindeutig übersetzbar, darf er nicht übernommen werden.
  Stattdessen bleibt der erhaltene gültige Wert der neueren Konfiguration
  bestehen oder es wird kontrolliert deren sicherer Standardwert verwendet.
  Diese Entscheidung muss pro Einstellung erfolgen und darf nicht durch eine
  pauschale Zusammenführung anhand gleicher Feldnamen ersetzt werden.
- Jede Schemaänderung benötigt Tests für den direkten und mehrstufigen
  Versionssprung, Sicherung und atomisches Schreiben sowie Fehler-, Downgrade-
  und Wiederherstellungsfälle. Downgrade-Tests müssen außerdem inkompatible
  Typen, geänderte Einheiten und in der Zielversion verschärfte Minimal- und
  Maximalwerte abdecken.

## Unveränderlichkeit von Slicer-Dateien

- Bei sämtlichen Entwicklungen und Programmabläufen dürfen Dateien und
  Verzeichnisse eines Slicers ausschließlich lesend verwendet werden. Das gilt
  insbesondere für Installationsdateien, Profile, Presets, Konfigurationen,
  Datenbanken, Caches und vom Slicer verwaltete G-Code- oder Projektdateien.
- Slicer-Dateien und Slicer-Verzeichnisse dürfen niemals angelegt, verändert,
  überschrieben, umbenannt, verschoben oder gelöscht werden. Dies gilt auch
  dann, wenn eine Slicer-API oder Kommandozeilenfunktion solche Änderungen
  technisch ermöglichen würde.
- Benötigt die Anwendung veränderte oder zusammengesetzte Daten, muss sie diese
  ausschließlich in eigenen programminternen Speicherbereichen oder eigenen
  temporären Dateien außerhalb aller Slicer-Verzeichnisse erzeugen. Das
  Original bleibt unverändert; auch temporäre Ausgaben dürfen nicht in
  slicerverwaltete Pfade geschrieben werden.
- Neue und geänderte Slicer-Integrationen müssen nach Möglichkeit durch Tests
  absichern, dass alle slicereigenen Quelldateien vor und nach dem Vorgang
  unverändert vorhanden und inhaltlich identisch sind.
