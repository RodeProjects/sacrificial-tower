# Private CI und geprüfte Veröffentlichung

Stand: 21.10.2026, Einrichtung und Abnahme noch in Arbeit. Die bisherige direkte
Runnerregistrierung am Hauptrepository wurde entfernt. Phase 2 und die Öffnung
bleiben bis zur vollständigen Abnahme gesperrt.

Private Steuerung 1.0.2 (`ae80a9a`) ist über PR 2 offiziell geprüft und
installiert. Lokale Infrastrukturabnahme `39627221957`: 25 Sicherheitsfälle,
neun ungefährliche Fallbacksimulationen, zwei Node-Tests und tatsächliche
Zugriffsproben unter dem getrennten Standardkonto erfolgreich. Der vollständige
Anwendungslauf, die automatische Übernahme und reale Installerabnahme bleiben
für die Phase-1-Freigabe erforderlich.

## Verantwortlichkeiten und Schutzgrenze

`RodeProjects/project-ci` ist die gemeinsame **private** Actions-Steuerung. Nur
dieses Repository besitzt `FLO-PC-private`. Haupt- und Update-Repository besitzen
keine lokalen Runner. Öffentliche Workflowdateien verwenden ausschließlich
GitHub-Hardware, keine privaten Dispatches und keine Verwaltungsgeheimnisse.
Issues, PRs, Kommentare, Labels oder Artefakte autorisieren keine lokale Ausführung.

Der Verwaltungsprozess unter dem bisherigen Entwicklerkonto wählt einen sauberen
Projektcommit ausdrücklich aus und bindet ihn an Repository-ID, Projektkennung,
Basis, Quellbaum, CI-Commit, Prüflogik und Pflichtoperation. Ein geschütztes
Git-Bundle transportiert genau diesen Quellstand. Der offizielle private Workflow
prüft vor Ausführung den tatsächlichen Checkout. Die Übernahmeprüfung verifiziert
die ursprünglichen privaten Actions-Läufe und Pflichtjobs erneut über GitHub.
Projekt-SHA und CI-SHA sind verschiedene Identitäten; frei angegebene SHAs oder
ungeprüfte Artefakte ersetzen keinen Nachweis. Geänderte Basis/Prüflogik macht
alte Nachweise ungültig. Übernommen wird ausschließlich dieselbe SHA per
SSH-Fast-Forward. Danach werden Remote-main und Prüfnachweise nochmals bestätigt;
eine zweite Vollsuite derselben unveränderten geprüften SHA entfällt.

Fremde PRs werden auf GitHub-Hardware geprüft. Wer fremden Code bewusst für einen
lokalen Lauf auswählt, muss dessen **konkreten Commit** einschließlich Tests,
Buildskripten und Abhängigkeiten als vertrauenswürdig beurteilen. Eine solche
Freigabe umfasst keine späteren Commits und ersetzt keine Vertrauensprüfung.

## Windows-Betrieb ohne VM

Der Runner läuft als getrenntes Windows-Standardkonto `RodeCiRunner`; der
Aufgabenplaner übernimmt den Start ohne Kontowechsel beim Entwickeln/Pushen.
Verwaltungscode, Konfiguration, Freigaben, Nachweise und verschlüsselte
Signierschlüssel sind für dieses Konto nicht beschreibbar bzw. nicht lesbar.
Persönliche GitHub-Anmeldung und SSH-Schlüssel werden nicht in Jobs eingebracht.
Schreibbereiche für Jobs/Caches sind nach Projekt bzw. Freigabe benannt.

Das ist **keine VM und keine vollständige Projektisolierung**. Ausdrücklich
freigegebener Projektcode führt seine Tests, Buildskripte, Paketinstallationen
und Abhängigkeiten auf gemeinsam genutzter Hardware aus. Er kann das Runnerkonto
und dessen veränderliche Bereiche kompromittieren, Netzwerkzugriffe ausführen
und allgemein zugängliche Dateien lesen. Projekte mit unterschiedlichem
Vertrauensniveau dürfen nicht ungeprüft dieselbe Umgebung teilen. Venvs und
Profilumleitungen stellen keine zusätzliche Sicherheitsgrenze dar.

## Geprüfter Push

Patchversion erhöhen, Commitnachricht und vorgesehenen Runner nennen, sauberen
`codex/`-Prüfbranch über SSH pushen und PR erstellen. Unter dem Entwicklerkonto:

```powershell
& 'D:\Entwicklung Software\_Tools\github_actions_runner\scripts\Complete-CheckedPush.ps1' `
  -RepositoryPath 'D:\Entwicklung Software\sacrificial_tower' `
  -Repository RodeProjects/sacrificial-tower -PullRequest NUMMER -ExpectedSha EXAKTE_SHA
```

Für Prozess-/Thread-/GUI-Lebenszyklusänderungen zusätzlich
`-Workflows tests.yml,windows-stress-tests.yml`. Normale Prüfläufe verwenden
ausschließlich den privaten lokalen offiziellen Runner. Öffentliche Checks können
eine Übernahme blockieren, aber niemals eine lokale Ausführung autorisieren.

## Releases

```powershell
./scripts/publish_update.ps1 -DevelopmentRelease
```

Der geschützte zentrale Releasehelfer verwendet dieselbe private Steuerung.
Unveränderte gültige vollständige Prüfungen werden wiederverwendet. Fehlt ein
wiederverwendbarer Nachweis, wird bei Sacrificial Tower zuerst auf GitHub-Hardware
geprüft; bei belegtem Fehlschlag folgt genau ein lokaler offizieller Ersatzlauf
derselben SHA. Installer-Builds verwenden ebenfalls diese Reihenfolge. Ein
absichtlicher Abbruch, veränderter Ref oder unklarer Dispatch wird nicht durch
einen blinden zweiten Start übergangen. Beide tatsächlichen Ergebnisse bleiben
im geschützten zentralen `state/release-runs/` dokumentiert.

Builds erhalten keine Signierschlüssel. Nach erfolgreicher Prüfung lädt der
Verwaltungsprozess das dem ursprünglichen Lauf zugeordnete Build-Artefakt,
vergleicht Version, Größe und SHA-256, signiert das Manifest unter dem
Entwicklerkonto und prüft die Signatur erneut. Der private Schlüssel ist mit
Windows-DPAPI geschützt und an dieses Konto gebunden. Er liegt nicht mehr als
Jobgeheimnis in Tests/Builds. Nur der öffentliche Prüfschlüssel wird ausgeliefert.
Ein Verlust des Windows-Profils/Schlüssels kann eine manuelle Neuinstallation
oder rechtzeitig vorbereitete Schlüsselrotation erfordern; verschlüsselte
Sicherungen müssen die passende Windows-Wiederherstellung berücksichtigen.

Die frühere Zeitlimit-Ausnahme mit einer eigenen lokalen Vollsuite ist mit der
neuen Nachweisgrenze nicht vereinbar und wird nicht mehr akzeptiert. Stattdessen
muss der offizielle private Fallback erfolgreich sein. Die erlaubte Kennzeichnung
als Entwicklungsversion und die begrenzt zurückgestellten Freigabeangaben gelten
unverändert; siehe [Veröffentlichung](distribution.md).

## Weitere Projekte

Im privaten CI-Repository `templates/project.json` und `templates/Invoke.ps1`
verwenden. `scripts/Initialize-CiProject.ps1 -ProjectId KENNUNG -Repository
RodeProjects/NAME` prüft die vorhandene Projektberechtigung und bereitet Eintrag
und Adapter vor. Nur tatsächlich nötige SDKs und feste Test-/Buildbefehle
konfigurieren, Pflichtprüfungen und gegebenenfalls Veröffentlichungsziel/
Signierung festlegen. Anschließend private Steuerung prüfen, übernehmen und
bewusst installieren; keine zweite Runnerregistrierung am Projekt anlegen.

Den Einrichtungsaufruf in einer separaten sauberen CI-Arbeitskopie auf einem
`codex/`-Branch verwenden. Pflichtjobnamen, zugeordnete private Workflows und
relativer Artefaktpfad sind Projektkonfiguration. Projektspezifische
Parameterprüfung und Veröffentlichungsverfahren liegen in `Validate-Request.ps1`
bzw. `Release.ps1` des Adapters; gemeinsame Kernlogik bleibt unverändert.

Die vollständige Verwaltungsanleitung und maschinenbezogene Abnahme stehen im
privaten Repository unter `docs/private-ci.md` und `docs/private-ci-acceptance.md`.
Ein kleines Node-Projekt ohne Abhängigkeiten ist als abweichender Projekttyp
tatsächlich über denselben privaten offiziellen Ablauf geprüft. Konfiguration,
Projektzuordnung, Quelltransport, Checkout, Pflichtjobs und Nachweisbildung sind
damit abgenommen. Zusätzliche SDKs, andere reale Buildverfahren und weitere
Veröffentlichungsziele sind erst am nächsten entsprechenden Projekt zu prüfen.
