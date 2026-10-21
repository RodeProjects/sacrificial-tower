# Private CI und geprüfte Veröffentlichung

Stand: 21.10.2026. **Phase 1 vollständig abgenommen.** Das Hauptrepository
bleibt bis zur abschließenden Kanal- und Veröffentlichungsprüfung privat.
Die direkte Runnerregistrierung am Hauptrepository wurde entfernt.

Unter privater Steuerung 1.0.6 (`5587253`) hat Version 0.9.24 (`cea9269`)
alle 1961 Einzeltests im ursprünglichen lokalen Lauf `39670077257` bestanden.
PR 10 wurde automatisch mit exakt derselben SHA per SSH übernommen; Remote-main,
Basis und ursprüngliche Nachweise wurden anschließend erneut bestätigt.
Die gehostete GUI-Pflichtprüfung `39670084139` bestand alle fünf Lizenzdialogfälle.
Der gehostete Build `39672682633` bestand sämtliche Build-/Installerprüfungen,
scheiterte ausschließlich am Actions-Artefaktspeicherkontingent. Genau ein
automatischer lokaler offizieller Fallback `39673818036` bestand einschließlich
aller fünf nativen Übergabetests, Ersetzung und Deinstallation. Tatsächlicher
Dateitransport, Hashes und Signaturprüfung des gebauten Installers wurden abgenommen.

Die gemeinsame Infrastruktur wurde mit dem harmlosen Node-Build `39670240350`
auch für einen anderen Projekttyp geprüft. Ein tatsächlich ohne geschützte
Freigabedatei ausgelöster Lauf `39671232313` blockierte bereits im Jobstarthook;
Projektcode wurde nicht ausgeführt. Unbekanntes Projekt, nicht freigegebene SHA,
abweichende Basis/Prüflogik, fehlende oder fehlgeschlagene Pflichtprüfungen,
falscher Lauf und veränderte Artefaktbytes wurden ebenfalls zuverlässig blockiert.
Fehlender GUI-Nachweis verhinderte die Dateiübernahme. Serverseitig besitzt nur
das private CI-Repository einen Runner; anonymer privater Dispatch ist unzulässig.
Die vollständigen maschinenbezogenen Belege liegen geschützt außerhalb des
Quellrepositories in `state/private-ci-migration/phase1-accepted.json` und den
dort referenzierten Originalnachweisen. Historische Diagnoseberichte im privaten
CI-Repository sind entsprechend gekennzeichnet.

Steuerung 1.0.7 (`86d5cc4`) ergänzt ausschließlich den Tower-Adapter um die
fest konfigurierte Abnahme `update-acceptance.yml`. PR 7 und Controllerlauf
`39678575537` wurden erfolgreich geprüft; dieselbe SHA ist geschützt installiert.
Diese Operation installiert nur im fest eingerichteten Standardkonto, verlangt
die freigegebene Version/Releaseart und verwendet ein frisches Jobverzeichnis.
Gemeinsame Autorisierungs- und Übernahmelogik bleiben unverändert. Der konkrete
veröffentlichte Versionsübergang wird nach der Öffnung zusätzlich abgenommen;
siehe [Updatekanal](update_channel.md).

Lizenzdialoge sind eine eigene **gehostete** Releasepflicht (`installer-checks.yml`).
Ihre unveränderten Assertions funktionieren nicht vollständig in Windows-Session 0;
produktive Lizenzoberfläche und Dialogbedingungen wurden nicht verändert. Nur
die harmlose Testfixture beendet nach den Assertions ihre Nachrichtenschleife.
Releaseadapter und Artefaktübernahme bestätigen den ursprünglichen GUI-Erfolg für
dieselbe Projekt-SHA, Basis und CI-Steuerung erneut. Der lokale Buildfallback
behält native Übergabe, Ersetzung und Deinstallation bei. Fehlende gehostete
GUI-Prüfung blockiert; keine Testausführung im privilegierten Entwicklerkonto.

Serverseitig sind für Haupt- und CI-Repository ausschließlich offizielle
GitHub-Actions mit vollständigen Commit-SHAs erlaubt. Standardtoken sind
schreibgeschützt; Actions dürfen keine PRs genehmigen. Das frühere
Manifest-Signiergeheimnis wurde aus dem Hauptrepository entfernt.

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
Der gemeinsame offizielle Actions-Arbeitsbereich enthält einen vor jedem Job
frisch aus dem genehmigten Bundle erstellten Quellcheckout; diese Wiederverwendung
ist keine zusätzliche Sicherheitsisolierung zwischen Projekten.

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

Gehostete Builds nutzen `approved-build`. Lokale Builds exportieren stattdessen
die konfigurierten Dateien in einen nach Freigabe und Lauf benannten Runnerbereich.
Ein eigener erfolgreicher offizieller Schritt protokolliert relative Dateinamen,
Größen, SHA-256 und die zugehörigen Commit-/Laufidentitäten. Der geschützte
`Get-PrivateBuildArtifacts.ps1` liest ausschließlich diesen Export-Schrittlog,
bestätigt den ursprünglichen Build über GitHub und übernimmt nur passende Dateien
in einen leeren Verwaltungsordner. Änderungen, Pfadumleitungen, fehlende oder
mehrdeutige Nachweise blockieren. Damit braucht der lokale Ersatzlauf weder den
Actions-Artefaktspeicher noch einen zusätzlichen Schreibzugang. Dies ist ein
Datenübernahmeweg nach offiziellen Actions, keine zusätzliche lokale CI.

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
damit abgenommen. Der dokumentierte Einrichtungsaufruf wurde zusätzlich in einer
separaten lokalen Kopie praktisch geprüft: bestehende Berechtigung/Repository-ID,
Konfiguration, Adaptervorlagen und Ablehnung einer doppelten Kennung; kein weiteres
GitHub-Repository angelegt. Zusätzliche SDKs, andere reale Buildverfahren und weitere
Veröffentlichungsziele sind erst am nächsten entsprechenden Projekt zu prüfen.
