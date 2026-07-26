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
- Ein Push darf erst erfolgen, nachdem der Benutzer ihn ausdrücklich erlaubt
  hat. Ohne diese Freigabe weder pushen noch sie aus dem Kontext ableiten.
