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
- Jede Schemaänderung benötigt Tests für den direkten und mehrstufigen
  Versionssprung, Sicherung und atomisches Schreiben sowie Fehler-, Downgrade-
  und Wiederherstellungsfälle.
