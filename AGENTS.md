# Repository-Regeln

Diese Regeln gelten ergänzend zur globalen `AGENTS.md` für das Repository `sacrificial-tower`. Allgemeine Arbeits-, Coding-, Eskalations-, Fortschritts-, Lizenz-/Rechts-, Dokumentations- und Python-Regeln werden hier nicht wiederholt.

## Git- und GitHub-Zugriff

- Für dieses Repository ist der Git-Remote `git@github.com:RodeProjects/sacrificial-tower.git` maßgeblich. Abrufen und Pushen erfolgen direkt mit Git über SSH aus dem Arbeitsverzeichnis dieses Repositories.
- Vor einem Abruf oder Push mit `git remote -v`, `git branch --show-current` und `git status -sb` Repository, Branch, Arbeitszustand und SSH-Remote prüfen. Für normale Git-Vorgänge insbesondere `git fetch origin <branch>` und `git push origin <branch>` verwenden.
- Die GitHub-CLI `gh` und Git über SSH verwenden getrennte Authentifizierungen. Ein ungültiges oder fehlendes `gh`-Token ist kein Nachweis für einen fehlerhaften SSH-Zugriff.
- Ist auf dem aktuellen Gerät bzw. in der aktuellen Ausführungsumgebung bereits nachgewiesen, dass isolierte Codex-Prozesse keinen Zugriff auf die im systemgebundenen Anmeldespeicher vorhandene `gh`-Authentifizierung des Host-Benutzers haben, alle erforderlichen GitHub-API- und CI-Befehle von Anfang an direkt im authentifizierten Host-Benutzerkontext mit der erforderlichen Berechtigung ausführen. Keinen bereits als aussichtslos bekannten Sandbox-Erstversuch wiederholen. Git über SSH bleibt davon unabhängig.
- Ist dieses getrennte Benutzerkontext-Verhalten noch nicht bekannt und tritt in der Sandbox bei einem erforderlichen GitHub-API- oder CI-Aufruf ein verdächtiger API-404 oder eine angeblich ungültige `gh`-Anmeldung auf, zunächst `gh auth status -h github.com` im tatsächlichen Host-Benutzerkontext prüfen und bei gültiger Anmeldung anschließend auch den ursprünglich benötigten Befehl dort ausführen. Funktioniert dieser, den Sandbox-Fehler als Benutzerkontextproblem behandeln und keinen erneuten Login verlangen. Schlägt auch der eigentliche Host-Aufruf fehl, dessen Fehler normal diagnostizieren; eine gültige `gh`-Anmeldung allein beweist nicht, dass Repository, Workflow oder angeforderte Ressource existieren. Einen erneuten Login nur in Betracht ziehen, wenn auch die Host-Authentifizierung tatsächlich fehlschlägt.
- Bei einem ausdrücklich angeforderten direkten Git-Push weder `gh auth status` als Voraussetzung behandeln noch zu `gh auth login -h github.com` auffordern, solange der konfigurierte SSH-Remote funktioniert. `gh` nur einsetzen, wenn tatsächlich GitHub-API-Funktionen benötigt werden, insbesondere für CI-Informationen oder Pull Requests.
- Ein Push-Auftrag nach `main` folgt dem globalen Prüfbranch-/Pull-Request-Ablauf. Nach erfolgreichen Prüfungen denselben Commit automatisch mit dem vorhandenen SSH-Remote nach `main` übernehmen. Nur eine ausdrücklich abweichende Benutzeranweisung erlaubt einen ungeprüften Direkt-Push.
- Schlägt ein SSH-Abruf oder SSH-Push fehl, zunächst selbstständig Arbeitsordner, Remote, Branch, Netzwerkzugriff und SSH-Erreichbarkeit diagnostizieren. Dazu je nach Bedarf `git remote -v`, `git status -sb`, `git fetch`, `git ls-remote origin` oder `ssh -T git@github.com` verwenden.
- Den Benutzer erst einbeziehen, wenn der Git-/SSH-Weg im korrekten Repository nach diesen Prüfungen weiterhin fehlschlägt oder eine neue Berechtigung bzw. Benutzerentscheidung erforderlich ist.

## Versionierung und Push-Freigabe

- Für jeden Push muss eine vorhandene Versionsnummer im Format `x.y.z` vor dem Commit erhöht werden, indem ausschließlich die letzte Zahl (`z`) um `1` steigt. Die Versionserhöhung muss im selben Commit und Push wie die zugehörigen Änderungen enthalten sein.
- Prüfbranch und anschließende automatische Übernahme desselben Commits nach `main` bilden eine logische Änderung; dabei keine zweite Versionsanhebung vornehmen. Maßgeblich ist die zuletzt auf `main` gepushte Version. Ist die lokale Versionsnummer bereits genau um `1` höher, wird sie in den nächsten Commit aufgenommen und nicht erneut erhöht.
- Die ersten beiden Versionsbestandteile (`x.y`) dürfen nur auf ausdrückliche Anweisung des Benutzers geändert werden.
- Der letzte Versionsbestandteil (`z`) läuft fortlaufend weiter. Er darf nur zurückgesetzt bzw. neu begonnen werden, wenn im selben Versionswechsel mindestens einer der vorangestellten Bestandteile (`x` oder `y`) erhöht wird.
- Vor jedem Push zuerst die vorgesehene Commit-Message ausgeben. Sie muss die zu pushenden Änderungen zusammenfassen.
- Commit-Messages müssen sprachlich einheitlich und überwiegend auf Deutsch formuliert sein. Eigennamen, etablierte Anglizismen und fachsprachliche Begriffe dürfen auf Englisch bleiben.
- Aktualisierungen dieser Anwendung als `Programmaktualisierung` oder `Sacrificial-Tower-Update` bezeichnen. `Windows-Update` ausschließlich für Aktualisierungen des Windows-Betriebssystems und `Windows-Installer` für das gebaute Installationspaket verwenden.
- Eine ausdrückliche Anweisung des Benutzers, den aktuellen Stand direkt zu einem genannten Remote oder Branch wie `main` zu pushen, gilt bereits als Push-Freigabe. In diesem Fall keine zusätzliche formelhafte Bestätigung wie „Push freigegeben“ verlangen.
- Während der Push-Vorbereitung rein administrative oder mechanische Begleitänderungen wie die vorgeschriebene Anhebung der statischen Versionsnummer, vom Benutzer im Rahmen der aktuellen Aufgabe angeforderte Anpassungen an `AGENTS.md`, Formatkorrekturen oder vergleichbare nicht ausführungsrelevante Metadatenänderungen erfordern keine erneute Push-Freigabe.
- Eine erneute ausdrückliche Push-Freigabe einholen, wenn nach der ursprünglichen Freigabe zusätzliche inhaltliche Änderungen hinzukommen, die Programmlogik, Laufzeitverhalten, Build/Packaging, Abhängigkeiten, ausführungsrelevante Konfiguration, Persistenz/Migrationen, Schnittstellen, Kompatibilität, Tests oder CI möglicherweise beeinflussen. Dabei nicht danach unterscheiden, ob die funktionale Änderung subjektiv klein oder wesentlich erscheint. Die Freigabe nicht aus einer lediglich allgemeinen Änderungs- oder Arbeitsanweisung ableiten, die keinen Push nennt.

## Offizielle private Actions vor der Übernahme nach main

- Ausschließlich `RodeProjects/project-ci` darf den lokalen offiziellen Runner
  `FLO-PC-private` besitzen. Haupt- und Update-Repository erhalten auch über
  Gruppen keinen Zugriff. Öffentliche Workflows laufen nur auf GitHub-Hardware;
  keine öffentlichen Ereignisse oder privilegierten Dispatch-Brücken anbinden.
- Normale freigegebene Pushes: Patchversion erhöhen, Commitnachricht und Runner
  nennen, `codex/`-Prüfbranch über SSH pushen und PR nach `main` erstellen.
  `D:\Entwicklung Software\_Tools\github_actions_runner\scripts\Complete-CheckedPush.ps1`
  mit Repositorypfad, Repository, PR und exakter SHA verwenden. Der Helfer
  erzeugt die konkrete lokale Freigabe, startet offizielle private Actions und
  übernimmt nach gültigen Nachweisen automatisch dieselbe SHA per SSH-Fast-Forward.
- Projektcommit, Basis und CI-Steuerungscommit unterscheiden. Freigaben/Nachweise
  binden Repository-ID, Quellbaum, Prüflogik, ursprünglichen Lauf, Versuch und
  vollständige Pflichtjobs. Fehlende, fehlgeschlagene oder nur übersprungene
  Prüfungen und geänderte Commit-/Basis-/Prüflogik blockieren. Kein Artefakt oder
  freier SHA-Wert ersetzt den erneuten GitHub-Abgleich.
- Nach Übernahme Remote-main und ursprüngliche private Nachweise erneut bestätigen.
  Keine zweite Vollsuite für exakt dieselbe unverändert geprüfte SHA starten.
  Öffentliche main-Pushes lösen deshalb keine redundante Vollsuite aus.
- Normale Prüfungen laufen nur auf dem privaten lokalen offiziellen Runner.
  Bei offline geschaltetem Runner warten. Keine eigene lokale CI-Nachbildung
  und keine zusätzliche lokale Vollsuite als Push-Voraussetzung verwenden.
- Prozess-/Thread- und GUI-Lebenszyklusänderungen benötigen zusätzlich die volle
  private Stressmatrix: `-Workflows tests.yml,windows-stress-tests.yml`.
- Sacrificial Tower behält die projektspezifische gehostete Releaseprüfung mit
  genau einem lokalen offiziellen Fallback bei `failure`, `timed_out` oder
  `startup_failure`. Beide verwenden die private vertrauenswürdige Steuerung und
  dieselbe Projekt-SHA. Gültige unveränderte Vollprüfungen werden wiederverwendet.
  Abbruch, veränderter Ref oder unklarer Dispatch erlaubt keinen blinden Neustart.
- `scripts/publish_update.ps1 -DevelopmentRelease` verwendet den zentralen
  Releasehelfer; Builds ohne Verwaltungszugänge, Signierung und Veröffentlichung
  anschließend im geschützten Entwicklerkonto. Die frühere CI-Zeitlimit-Ausnahme
  mit eigener lokaler Vollsuite wird durch den nachgewiesenen offiziellen Fallback
  ersetzt; `-AllowTimedOutCI` autorisiert keine Umgehung.
- Runnerbetrieb als Windows-Standardkonto `RodeCiRunner`, Verwaltung weiter unter
  dem bisherigen Entwicklerkonto. Code/Konfiguration/Freigaben/Nachweise gegen
  Runner-Schreibzugriff und persönliche Anmeldungen/Schlüssel gegen Jobzugriff
  schützen. Profilvariablen und Venvs sind keine Sicherheitsgrenze.
- Fremde PRs zunächst nur gehostet prüfen. Lokale Ausführung fremden Codes nur
  nach bewusster Vertrauensentscheidung für den konkreten Commit einschließlich
  Tests, Buildskripten und Abhängigkeiten; spätere Commits sind nicht umfasst.
  Ohne VM bleiben gemeinsame Hardware und Runnerkonto kompromittierbar.
- Bestehende unabhängige Änderungen und Benutzerdaten erhalten. Setup/Details und
  aktuelle Abnahme: `docs/private_ci.md` sowie das private Infrastrukturrepository.
  Vor erfolgreicher Phase-1-Abnahme weder Phase 2 noch öffentliche Freigabe beginnen.

## Entwicklungsreleases und nachzureichende Freigabeangaben

- Solange in `config/legal_profile.json` Anbieter-, Datenschutz-, Vertriebs- oder rechtliche Freigabeangaben fehlen oder als Platzhalter vorliegen, alle betroffenen Programmversionen als **Entwicklungsversionen für Tests und Evaluation** behandeln. Eine Versionsnummer allein begründet keine abgeschlossene Freigabe für reguläre kostenlose Veröffentlichung.
- Fordert der Benutzer ein Release oder Update-Release an, bei noch offenen Angaben selbstständig den vorhandenen Entwicklungsreleasepfad wählen: `scripts/publish_update.ps1 -DevelopmentRelease`. Der Benutzer muss die Ausnahme nicht erneut erklären oder ausdrücklich das Wort „Entwicklungsrelease“ verwenden. Die bekannten zurückgestellten Angaben allein sind kein Grund, die Veröffentlichung abzulehnen oder eine erneute Bestätigung zu verlangen.
- Die ausdrücklich erlaubte Zurückstellung umfasst `provider_postal_address`, `provider_additional_details`, `support_retention_policy`, `distribution_terms` und `release_legal_review`. Die Werte wahrheitsgemäß offen lassen, in der bestehenden Checkliste nachverfolgen und später zentral in `config/legal_profile.json` nachtragen; keine Angaben oder Freigaben erfinden. Die maßgebliche technische Prüfung ist `scripts/check_release_readiness.py --development-release`.
- Name, Marke und erreichbarer Kontakt sowie die eindeutige Kennzeichnung in den Nutzungsbedingungen bleiben erforderlich. Unbekannte Vorlagenschlüssel, fehlerhafte Konfigurationen und sonstige technische Blockaden werden durch die Ausnahme nicht freigegeben.
- Entwicklungsreleases im Releasetitel, in der Releasebeschreibung und im signierten Update-Manifest sichtbar als Entwicklungsversion kennzeichnen. Auf GitHub ohne Prerelease-Flag und mit `--latest` veröffentlichen, damit auch die neueste Entwicklungsversion als „Latest“ angezeigt wird; GitHub erlaubt „Latest“ nicht für Prereleases. Diese Markierung begründet keine abgeschlossene Veröffentlichungsprüfung. Den bestehenden öffentlichen Updatekanal einschließlich `latest.json` verwenden, damit bereits installierte Testversionen das Update erhalten; der Kanal ist öffentlich verfügbar und kein privater Testkanal.
- Versionsanhebung, Push-Freigabe, erfolgreiche CI für den konkreten `main`-Commit, Installerprüfungen, Lieferumfangs-/Lizenztextprüfungen, Signatur- und Integritätsprüfungen bleiben nach den bestehenden Regeln erforderlich. Die Entwicklungsausnahme verschiebt die dokumentierten Freigabeangaben; sie behauptet keine Befreiung von gesetzlichen oder Drittanbieter-Lizenzpflichten.
- Erst bei vollständig nachgetragenen und tatsächlich geprüften Angaben den regulären kostenlosen Veröffentlichungsweg ohne `-DevelopmentRelease` verwenden. Die Anwendung bleibt kostenlos; die Workflow-Art heißt `free`. Ausgefüllte Felder sind keine juristische Freigabe oder Store-Zertifizierung. Einzelheiten stehen in `docs/update_channel.md`, `docs/distribution.md` und `docs/missing_data.md`.
- Eigener Code, eigene Dokumentation und eigene Assets stehen nach `LICENSE.md` unter der reinen Apache License 2.0 (`Apache-2.0`). Nutzung, Klonen, Forken, Änderungen und Weitergabe einschließlich kommerzieller Weitergabe sind unter ihren Bedingungen erlaubt. Keine Commons Clause oder zusätzliche kommerzielle Beschränkung einführen. `NOTICE` und vorgeschriebene Lizenz-/Urheberhinweise mitliefern; Drittkomponenten behalten ihre eigenen Lizenzen. Zulässige Ergebnisse dürfen kommerziell verwendet werden. Die spätere Veröffentlichung und die Repositorysichtbarkeit sind gesondert zu beauftragen.
- Rechtlicher Anbieter ist Wolfgang Florian Rode als Einzelunternehmer; RodeProjects bleibt Entwicklerkennung. Gewöhnlicher Support erfolgt freiwillig über GitHub Issues. Vertrauliche Anliegen verwenden den Kontakt aus dem Anbieterprofil. Repositorysichtbarkeit nur auf ausdrücklichen Auftrag ändern.
- Diagnoseexporte müssen Felder und technische Zeichenketten ausdrücklich freigeben. Frei gewählte Namen, unbekannte Schlüssel, Profilinhalte und freie Fehlermeldungstexte dürfen nicht allein anhand einer Musterfilterung exportiert werden. Eigene Problembeschreibungen bleiben sichtbar als unveränderte Nutzereingaben gekennzeichnet. Details: `docs/support.md`.

## Projektdokumentation

- Die Dokumentation dieses Projekts modular unter `docs/` führen; eine vorhandene gleichwertige Dokumentationsstruktur beibehalten, statt parallel eine zweite Struktur anzulegen.
- Falls noch keine gleichwertige Struktur vorhanden ist, `docs/README.md` als zentralen Dokumentationsindex verwenden und fachlich getrennte Themen in eigenen Dateien unter `docs/` dokumentieren.
- Für Drittkomponenten eine zentrale Dependency-/Lizenzdokumentation führen; falls noch keine entsprechende Datei existiert, `docs/dependencies.md` verwenden. Dort mindestens Komponente/Version bzw. Versionsreihe, Lizenz und belastbare Lizenzquelle, kommerzielle/proprietäre Nutzung, erforderliche Attribution/Weitergabepflichten, relevante Einschränkungen, Kosten-/Umsatzschwellen und Datum der letzten Prüfung dokumentieren.
- Vor erneuter externer Lizenzrecherche zunächst `docs/dependencies.md` bzw. die vorhandene gleichwertige Dokumentation prüfen. Unveränderte und ausreichend dokumentierte Komponenten nur bei den global definierten Anlässen erneut lizenzrechtlich prüfen.
- Projektspezifisch besonders wichtige Bereiche wie Slicer-Integration, Preslice-/Analyseabläufe, Profil-/Konfigurationsverarbeitung, Persistenz/Migrationen und andere komplexe Kernbereiche so dokumentieren, dass Aufbau, Datenfluss, relevante Invarianten und nicht offensichtliche Entscheidungen nachvollziehbar bleiben.
- Keine in der globalen `AGENTS.md` bereits geregelten allgemeinen Dokumentationsprinzipien duplizieren.

## Migration von Benutzerdaten

- Persistierte Benutzereinstellungen und zukünftige Einstellungsprofile müssen über `VersionedJsonStore` geladen und atomar gespeichert werden.
- Jede strukturelle oder semantische Änderung eines gespeicherten Formats muss dessen Schema-Version genau um `1` erhöhen und eine explizite Migration von der direkten Vorversion registrieren. Frühere Migrationsschritte dürfen nicht übersprungen oder ohne ausdrückliche Aufgabe entfernt werden.
- Vor migrationsbedingten Umschreibungen muss das Original gesichert werden.
- Unbekannte neuere, beschädigte oder zwischenzeitlich extern veränderte Dateien dürfen nicht automatisch überschrieben werden.
- Bei der Zusammenführung von Einstellungen nach einem Downgrade dürfen nur Werte mit stabiler Kennung und ausdrücklich bestätigter semantischer Kompatibilität übernommen werden.
- Jeder Übernahmekandidat muss zuvor nach Typen, Wertebereichen, Einheiten, Abhängigkeiten und sonstigen Regeln der Zielversion normalisiert und validiert werden. Ein zuletzt geänderter Wert hat niemals Vorrang vor diesen Sicherheitsregeln.
- Ist ein während des Downgrades geänderter Wert in der neueren Zielversion ungültig oder nicht eindeutig übersetzbar, darf er nicht übernommen werden. Stattdessen bleibt der erhaltene gültige Wert der neueren Konfiguration bestehen oder es wird kontrolliert deren sicherer Standardwert verwendet.
- Diese Entscheidung muss pro Einstellung erfolgen und darf nicht durch eine pauschale Zusammenführung anhand gleicher Feldnamen ersetzt werden.
- Jede Schemaänderung benötigt Tests für den direkten und mehrstufigen Versionssprung, Sicherung und atomisches Schreiben sowie Fehler-, Downgrade- und Wiederherstellungsfälle.
- Downgrade-Tests müssen zusätzlich inkompatible Typen, geänderte Einheiten und in der Zielversion verschärfte Minimal- und Maximalwerte abdecken.

## Unveränderlichkeit von Slicer-Dateien

- Bei sämtlichen Entwicklungen und Programmabläufen dürfen Dateien und Verzeichnisse eines Slicers ausschließlich lesend verwendet werden. Dies gilt insbesondere für Installationsdateien, Profile, Presets, Konfigurationen, Datenbanken, Caches und vom Slicer verwaltete G-Code- oder Projektdateien.
- Slicer-Dateien und Slicer-Verzeichnisse dürfen niemals angelegt, verändert, überschrieben, umbenannt, verschoben oder gelöscht werden. Dies gilt auch dann, wenn eine Slicer-API oder Kommandozeilenfunktion solche Änderungen technisch ermöglichen würde.
- Benötigt die Anwendung veränderte oder zusammengesetzte Daten, müssen diese ausschließlich in eigenen programminternen Speicherbereichen oder eigenen temporären Dateien außerhalb aller Slicer-Verzeichnisse erzeugt werden.
- Slicer-Originale bleiben unverändert; auch temporäre Ausgaben dürfen nicht in slicerverwaltete Pfade geschrieben werden.
- Neue und geänderte Slicer-Integrationen nach Möglichkeit durch Tests absichern, die sicherstellen, dass alle slicereigenen Quelldateien vor und nach dem Vorgang unverändert vorhanden und inhaltlich identisch sind.
