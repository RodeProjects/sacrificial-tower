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

## CI-Absicherung bei direkten Pushes

- Vor einem direkten Push nach `main` muss der letzte abgeschlossene Lauf des
  GitHub-Actions-Workflows `Tests` für `main` geprüft werden. Ist dieser Lauf
  fehlgeschlagen, muss die Ursache vor einem weiteren Push untersucht und ein
  noch vorhandener Fehler behoben werden.
- Die lokale Abschlussprüfung muss mindestens den in `.github/workflows/tests.yml`
  verwendeten Befehl `python -m unittest discover -s tests -q` umfassen. Weitere
  für die Änderung relevante Tests bleiben zusätzlich erforderlich.
- Nach einem direkten Push nach `main` muss der dadurch ausgelöste Workflow
  `Tests` bis zum Abschluss beobachtet werden. Die Push-Aufgabe darf erst als
  erfolgreich abgeschlossen gemeldet werden, wenn dieser Lauf erfolgreich ist.
  Bei einem Fehlschlag sind die Actions-Logs unmittelbar auszuwerten und der
  Benutzer ist mit der konkreten Ursache zu informieren.
- Die CI-Prüfung kann mit `gh run list`, `gh run watch --exit-status` und
  `gh run view --log-failed` erfolgen. Eine fehlende GitHub-CLI-Authentifizierung
  betrifft nur diese CI-Abfrage und ist kein Nachweis für ein Problem mit dem
  separat konfigurierten SSH-Zugriff von Git.

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
