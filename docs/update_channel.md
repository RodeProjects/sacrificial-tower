# Sacrificial-Tower-Update-Kanal

Die eigenständig installierte Windows-Anwendung prüft im Hintergrund das
öffentliche Manifest unter:

`https://raw.githubusercontent.com/RodeProjects/sacrificial-tower-updates/main/latest.json`

Das private Quellcode-Repository und persönliche GitHub-Zugangsdaten sind für
Endnutzer nicht erforderlich. Der öffentliche Kanal enthält ausschließlich den
Windows-Installer, das kryptografisch signierte Manifest und die zugehörigen
Prüfdaten.

Ist eine neue Version verfügbar, erscheint unter Menü und Versionsnummer am
rechten Headerrand die kompakte Schaltfläche „Aktualisieren“. Beim Download
bleibt sie blau und zeigt „Lädt... x%“; direkt rechts liegt ein quadratischer
Abbruchbutton mit X im gemeinsamen roten Abbruchdesign. Die Zeile endet ohne
Außenabstand an der Headertrennlinie. Nur in diesen Updatezuständen werden Menü
und Versionsnummer horizontal über der gesamten Updatezeile einschließlich
des Abbruchbuttons zentriert. Beim Einblenden des X bleiben beide an ihrer
horizontalen Position. Die
Erstellungsmethode reserviert daneben den benötigten Platz; falls die Höhe
nicht reicht, wächst der Header nach unten.

## Kostenlose kryptografische Absicherung

Der Windows-Installer wird vorerst ohne Authenticode-Zertifikat erzeugt. Deshalb
kann Windows bei einem manuell heruntergeladenen Installer weiterhin vor einem
unbekannten Herausgeber warnen. Die Sicherheit des automatischen
Sacrificial-Tower-Updates hängt davon nicht ab:

- Jede Version erhält ein Ed25519-signiertes Manifest.
- Der private Ed25519-Schlüssel liegt ausschließlich als verschlüsseltes
  GitHub-Actions-Secret `UPDATE_MANIFEST_SIGNING_KEY_BASE64` im privaten
  Quellcode-Repository.
- Die Anwendung enthält nur den öffentlichen Prüfschlüssel und lehnt fehlende,
  unbekannte oder ungültige Signaturen ab.
- Signiert werden Versionsnummer, Installer-URL, SHA-256, Dateigröße und
  Versionshinweise gemeinsam. Keine dieser Angaben kann unbemerkt verändert
  werden.
- Der Installer wird erst nach erfolgreicher Signatur-, Größen- und
  SHA-256-Prüfung gestartet.

Version 0.4.2 ignoriert die zusätzlichen Signaturfelder, prüft aber weiterhin
Größe und SHA-256. Dadurch kann sie auf die erste signierte Manifest-Version
wechseln. Ab Version 0.4.5 ist die Manifest-Signatur verpflichtend.

Der optionale Authenticode-Abschnitt in `installer/SacrificialTower.iss` bleibt
für eine spätere öffentlich vertrauenswürdige Zertifikatsignierung erhalten.
Eine spätere Signierung ändert weder das Manifestformat noch die bestehende
Inno-Setup-`AppId`.

### Getrennte Signierung und Schlüsselverwaltung

Der neue öffentliche Prüfschlüssel heißt `2026-10-private-publisher`. Der private
Schlüssel wird ausschließlich unter dem Entwicklerkonto mit Windows-DPAPI
verschlüsselt gespeichert. Test-/Buildjobs erhalten ihn nicht. Der frühere
GitHub-Schlüssel kann aus dem Repository-Secret nicht ausgelesen werden; deshalb
ist für diese Trennung ein neuer Prüfschlüssel erforderlich. Die beauftragte
Umstellung verlangt keine Migration der wenigen bisherigen Testinstallationen;
diese erhalten die neue Version später durch manuelle Installation.

Für künftige Rotationen bei weiterlaufenden Installationen bleibt eine kontrollierte
Übergangsversion erforderlich, die vor Aktivierung eines neuen Signierschlüssels
dessen öffentlichen Anteil verteilt. Unverschlüsselte Schlüssel niemals in
Dateien, Logs, Git oder Artefakten ablegen. Der frühere Helfer
`provision_update_signing_key.py` beschreibt den alten GitHub-Secret-Pfad und wird
für die neue lokale Signierung nicht verwendet. Sicherung/Wiederherstellung des
DPAPI-Schlüssels muss das zugehörige Windows-Profil berücksichtigen.

## Veröffentlichung einer neuen Version

Der vollständige aktuelle CI-/Pushablauf steht unter [Private CI](private_ci.md).
Die technische Abnahme der neuen Einrichtung ist noch in Arbeit; bis zu ihrem
Erfolg bleibt die Veröffentlichung gesperrt.

1. Patchversion in `src/cooling_tower/version.py` erhöhen, Commitnachricht und
   Runner nennen, freigegebene Änderung auf `codex/`-Prüfbranch pushen und PR
   erstellen. Der zentrale `Complete-CheckedPush.ps1` prüft offizielle private
   Actions und übernimmt dieselbe SHA automatisch nach main. Für einen Release-
   Push ohne wiederverwendbare Vollprüfung `-HostedFirst` verwenden.
2. Der Helfer bestätigt anschließend Remote-main und die ursprünglichen privaten
   Nachweise. Kein zweiter Volltest derselben unverändert geprüften SHA.
3. Im normalen Entwicklerkonto mit PowerShell 7 ausführen:

   ```powershell
   ./scripts/publish_update.ps1 -DevelopmentRelease
   ```

   Erst nach vollständiger tatsächlicher regulärer Freigabe ohne
   `-DevelopmentRelease` veröffentlichen. Die weiterhin offenen Angaben werden
   wahrheitsgemäß in [Checkliste](missing_data.md) verfolgt.

Der zentrale Releasehelfer verwendet die private vertrauenswürdige CI-Steuerung.
Er prüft Projektcommit und Basis getrennt vom CI-Steuerungscommit und verifiziert
ursprünglichen Lauf, Pflichtjobs und verwendeten Runner gegen GitHub. Gültige
unveränderte Vollprüfungen werden wiederverwendet. Für erforderliche neue
Release-/Installerprüfungen zuerst GitHub-Hardware verwenden und bei belegtem
`failure`, `timed_out` oder `startup_failure` genau einmal denselben Stand lokal
auf dem privaten offiziellen Runner prüfen. Abbruch, veränderter Ref und
Dispatch ohne verlässliche Lauf-ID erlauben keine blinden Doppelstarts. Auch ein
lokaler Fehler blockiert die Veröffentlichung. Beide Ergebnisse bleiben unter
`state/release-runs/` im geschützten zentralen Toolordner dokumentiert.

Die frühere Entwicklungsrelease-Zeitlimit-Ausnahme mit eigener lokaler Vollsuite
ist durch den offiziellen privaten Fallback ersetzt. `-AllowTimedOutCI` wird
nicht mehr akzeptiert. Die Entwicklungsausnahme verschiebt weiterhin nur die
konkret erlaubten Freigabeangaben; erfolgreiche offizielle Prüfungen sowie
Lieferumfangs-, Installer-, Signatur- und Integritätsprüfungen bleiben Pflicht.
Entwicklungsreleases bleiben sichtbar im Titel, Beschreibung und signierten
Versionshinweisen gekennzeichnet. GitHub erhält kein Prerelease-Flag und
`--latest`; das ist keine reguläre Vertriebsfreigabe.

Die gemeinsame, unmittelbar releasebezogene Buildfolge steht in
`scripts/build_update.ps1` und wird sowohl vom privaten Projektadapter als auch
von der ausschließlich gehosteten öffentlichen Builddatei verwendet. Sie
bereitet dieselben gepinnten Abhängigkeiten/Qt-Quellen vor, baut und prüft den
Installer und erzeugt Metadaten. Keine Signierung im Test-/Buildjob. Der
Verwaltungsprozess lädt den nachgewiesenen Lauf aus dem privaten CI-Repository,
vergleicht Version, Größe und SHA-256, signiert das Manifest unter dem
Entwicklerkonto und prüft es vor Veröffentlichung erneut. Das Manifestformat und
die kryptografischen Prüfungen bleiben erhalten.

Die privaten Stresstests führen bei Pflicht die vollständige Dreiseed-Matrix aus.
Öffentliche manuelle Stressworkflows laufen ausschließlich auf GitHub-Hardware.
Der alte `github_hosted`-Eingang kann dort keine lokale Ausführung mehr auswählen.
Schlägt die Veröffentlichung des Manifests nach dem Erstellen des Releases
fehl, wird das unvollständige Release entfernt. Im Programm und Installer werden
keine Verwaltungs- oder GitHub-Zugänge gespeichert.

## Automatische Release-Aufbewahrung

Nach einer vollständig erfolgreichen Veröffentlichung führt
`scripts/publish_update.ps1` die Bereinigung des öffentlichen Update-Repositories
aus. Die Regeln liegen nachvollziehbar in
`config/release_retention.json`:

- Die neuesten 100 veröffentlichten Releases bleiben immer erhalten.
- Release-Assets dürfen zusammen höchstens 10 GiB belegen.
- Ungeschützte Releases außerhalb der neuesten 100 werden nach 90 Tagen
  entfernt.
- Ist die 10-GiB-Grenze erreicht, werden die ältesten geeigneten Releases ohne
  Rücksicht auf ihr Alter entfernt, bis die Größe wieder unter der Grenze liegt.
- Jede Version `x.y.0` und die ausdrücklich eingetragene Version `0.4.9` sind
  dauerhaft geschützt.
- Das gerade veröffentlichte Release, Entwürfe, unveränderliche Releases und
  nicht eindeutig als `x.y.z` erkennbare Tags werden ebenfalls nie automatisch
  gelöscht.

Die Mindestanzahl und die Schutzregeln haben Vorrang vor der Größenbegrenzung.
Kann die Größenbegrenzung deshalb nicht eingehalten werden, bricht die
Bereinigung mit einem eindeutigen Hinweis ab, statt ein geschütztes Release zu
löschen. Git-Tags bleiben auch beim Löschen eines Release erhalten.

Ein ungefährlicher Probelauf gegen ein beliebiges Repository ist möglich mit:

```powershell
.\scripts\cleanup_releases.ps1 `
  -Repository RodeProjects/sacrificial-tower-updates `
  -LatestVersion 0.4.9 `
  -DryRun
```

## Eigenständiger und vorbereiteter Store-Build

`config/distribution.json` legt den Vertriebskanal eines Builds fest:

- `standalone`: verwendet den Sacrificial-Tower-Update-Kanal.
- `microsoft-store`: deaktiviert den eigenen Updater vollständig; Updates
  werden später ausschließlich durch den Microsoft Store verwaltet.

Die normale Entwicklung und der aktuelle Inno-Setup-Installer bleiben
`standalone`. Ein zukünftiger MSIX-Build erhält vor dem Paketbau eine
Store-spezifische Variante der Distributionsdatei.

## Verhalten im Programm

- Die automatische Prüfung findet nur in einem gebauten eigenständigen
  Windows-Programm statt.
- Store-Builds können den eigenständigen Updater nicht versehentlich starten.
- Netzwerkfehler oder ein nicht erreichbarer Kanal stören die normale Nutzung
  nicht.
- Der Button `Aktualisieren` erscheint nur bei einer numerisch höheren Version.
- Das Manifest muss einen eingebetteten vertrauenswürdigen Ed25519-Schlüssel
  verwenden und eine gültige Signatur besitzen.
- Der Installer wird vollständig heruntergeladen und gegen Dateigröße und
  SHA-256 aus dem signierten Manifest geprüft.
- Während des Downloads kann der Vorgang abgebrochen werden; die unvollständige
  Datei und ihr temporärer Ordner werden entfernt. Nach erfolgreicher Prüfung
  läuft ein zehnsekündiger Neustart-Countdown, der ebenfalls abgebrochen werden
  kann. Der blaue Button `Jetzt neu starten` rechts unten beendet den Countdown
  sofort und startet denselben Installations-/Neustartablauf. `Abbrechen` steht
  links daneben; beim Abbrechen wird der bereits geladene Installer entfernt.
- HTTPS-Zertifikate werden über den nativen Windows-Zertifikatsspeicher
  geprüft.
- Nach erfolgreicher Prüfung wird Inno Setup über die nachfolgend beschriebene
  bestätigte Übergabe gestartet, die Anwendung geordnet beendet, ersetzt und
  anschließend neu geöffnet.

### Bestätigte Übergabe und sicheres Beenden

`Jetzt neu starten` beendet den Countdown sofort und öffnet unmittelbar eine
bedienbare Fortschrittsanzeige. Der Betriebssystemaufruf zum Starten des Setups
und die erneute Größen-/SHA-256-Prüfung laufen außerhalb des Qt-Oberflächenthreads.
Das gilt auch nach bestätigter Datei-, Slicer- und Profilauswahl in der Übersicht
der Erstellungsmethoden. Die eigentliche Installation benötigt weiterhin Zeit;
der Button kann weder eine Windows-/Virenscanner-Prüfung überspringen noch einen
sofortigen erfolgreichen Neustart garantieren.

Die Übergabe verwendet drei pro Versuch zufällig benannte lokale Windows-Ereignisse
(`ready`, `commit`, `cancel`) und ein vom Setup geöffnetes Handle des ursprünglichen
Programmprozesses. Das Setup bestätigt seine Bereitschaft erst in `PrepareToInstall`.
Die Anwendung prüft zusätzlich das zum Versuch und zur Zielversion passende,
tatsächlich sichtbare Statusprotokoll. Ein Ereignis aus einer virtualisierten
Scanner-Ausführung allein genügt nicht als Bestätigung.

Erst danach werden Hintergrundaufgaben kooperativ abgebrochen und deren tatsächliche
Thread-Enden abgewartet. Auch manuelle und allgemeine Einstellungen müssen erfolgreich
gespeichert sein. Die Installation erhält erst nach dem akzeptierten Schließen des
Fensters eine Freigabe und wartet zusätzlich auf das **wirkliche Prozessende**.
Ohne beide Voraussetzungen ersetzt das Setup keine Programmdateien. Ein erzwungenes
Prozessende ohne Freigabe, ein Abbruch und eine verspätete Setup-Ausführung können
deshalb kein bereits verworfenes Update nachträglich installieren.

Für die Startbestätigung gelten 90 Sekunden, für das kooperative Beenden der
Hintergrundaufgaben 30 Sekunden und im Setup höchstens 120 Sekunden für die
bestätigte Prozessbeendigung. Ein Startfehler lässt die laufende Anwendung geöffnet.
Ein weiterhin blockierter nativer Startaufruf hält keine Qt-Objekte oder verwalteten
QThreads fest; seine verspätete Ausführung bleibt durch die fehlende Freigabe gesperrt.
Der neue Aufruf verwendet `/NOCLOSEAPPLICATIONS` und `/NORESTARTAPPLICATIONS`.
Andere Programme werden damit nicht zwangsweise geschlossen. Das Setup startet
die Anwendung erst nach erfolgreicher Installation einmal neu. Scheitert der
Neustart, wird das separat protokolliert.

Ältere installierte Versionen ohne dieses Übergabeprotokoll können weiterhin den
neuen Installer starten. Ihre bisherige Start-/Fehlerbehandlung wird dadurch
jedoch nicht rückwirkend ersetzt. Der Fix muss zunächst als neue Programmversion
installiert werden. Ein bereits installierter Altstand erhält keine lokalen
Quellcodeänderungen automatisch.

Das bestätigte Protokoll beginnt mit Version 0.8.14. Der neue Startpfad akzeptiert
nur eine neuere Zielversion ab dieser Grenze; ein älterer Installer darf nicht
versehentlich ohne die erforderliche Installationssperre ausgeführt werden.

### Update-Diagnose

Das strukturierte Journal `logs/background_jobs.jsonl` protokolliert Manifestprüfung,
Downloadprüfung, Neustartwunsch, erneute Integritätsprüfung, Prozesserzeugung,
Bereitschaft, Abbruch, Zeitüberschreitungen und die sichere Beendigung. Dazu gehören
Zielversion, Dauer, tatsächlich verfügbare Windows-/Betriebssystemfehlernummern,
HTTP-Status und Rückgabecodes eines vorzeitig beendeten Setup-Prozesses. Eine
Windows-Zugriffsverweigerung allein wird nicht als Virenscannerfund ausgegeben.

Jeder Versuch erhält außerdem unter `logs/updates/` einen eindeutigen Namen:
`update-<Kennung>.log` enthält das native Inno-Protokoll; die danebenliegende
`.status`-Datei enthält Protokollversion, Versuch, Zielversion und feste Phasenmarker.
In der installierten Fassung liegen diese Dateien standardmäßig unter
`%LOCALAPPDATA%\RodeProjects\SacrificialTower\standalone\logs\updates`.
Diese Dateien bleiben außerhalb des temporären Downloads auch nach Programmende
erhalten. Damit sind Datei-/Installationsfehler und Neustartfehler auch nach dem
Schließen der alten Anwendung nachvollziehbar. Beim nächsten Start werden die
bestätigten Phasen des jüngsten Versuchs begrenzt in das Journal übernommen und
die tatsächlich gestartete Programmversion zugeordnet. Das bestätigt den Start
der Zielversion, ohne einen manuellen Start als automatischen Neustart auszugeben.

Das native Setup-Protokoll ist laut Inno ausdrücklich kein stabiles maschinenlesbares
Format. Deshalb werden ausschließlich die eigenen festen Statusmarker automatisch
ausgewertet. Ein abgebrochenes oder vom Betriebssystem/Virenscanner beendetes Setup
kann nur den letzten bestätigten Stand hinterlassen. Nach Ende der alten Anwendung
existiert kein dauerhafter Agent, der jeden späteren nativen Prozess-Exitcode erfassen
könnte. Die Anwendung verspricht auch keinen atomaren Austausch des gesamten
Installationsordners oder eine vollständige Wiederherstellung nach Stromausfall.
Bei einem Fehler während des tatsächlichen Dateiaustauschs die nativen Logs prüfen
und gegebenenfalls den verifizierten Installer erneut manuell ausführen.

Rohlogs bleiben lokal und können vollständige Pfade und Fehlertexte enthalten.
Supportexporte übernehmen nur ausdrücklich freigegebene Ereignisse, technische
Fehlernummern und Versions-/Phasenangaben. Pfade, Versuch-Kennungen, freie Fehlertexte
und die nativen Setup-Rohlogs werden nicht automatisch exportiert. Einzelheiten:
[Support und Datenschutzgrenze](support.md).

### Virenscanner: Unterbrechungen reduzieren, Schutz erhalten

Avast beschreibt CyberCapture als Prüfung seltener oder unbekannter ausführbarer
Dateien. Ein gültiges Update-Manifest schützt die Herkunft und Integrität des
Downloads; es ersetzt keine Authenticode-Publisher-Reputation beim Virenscanner.
Eine Garantie gegen Fehlalarme oder echte Blockierungen ist technisch nicht möglich.
Es werden keine Scanner deaktiviert, Ausnahmen angelegt, Sicherheitsabfragen
umgangen oder blockierte Prozesse automatisch immer wieder gestartet.

Kostenlos umsetzbar sind ein konsistenter öffentlicher Vertriebskanal, nachvollziehbare
Builds, unveränderte geprüfte Releaseartefakte und das Einreichen des konkreten
Installers beim Hersteller zur Prüfung einer vermuteten Falscherkennung. Eine solche
Einreichung übermittelt die Datei an einen externen Anbieter und erfolgt deshalb
nicht automatisch. Erst nach Prüfung des Herstellerergebnisses über den konkreten
Fund entscheiden; eine passende Prüfsumme beweist für sich allein keine Schadlosigkeit.

Vertrauenswürdige Authenticode-Signaturen für Programm, Installer und Uninstaller
können die Publisher-Reputation verbessern. Selbstsignierte Zertifikate schaffen
diese öffentliche Reputation nicht. Auch bezahlte OV-/EV-Zertifikate garantieren
keine unterbrechungsfreie Ausführung; eine kostenpflichtige Signaturdienstleistung
wurde nicht eingeführt. Der Microsoft Store ist ein gesondert zu prüfender
Vertriebsweg mit anderer Signatur-/Updateverwaltung. Seine SmartScreen-Vorteile
sind keine Zusage über das Verhalten unabhängiger Virenscanner. Bestehende
Store-/Rechts-/Distributionsprüfungen bleiben erforderlich.

Offizielle Quellen, geprüft am 17.10.2026:
[Inno-Parameter und Logging](https://jrsoftware.org/ishelp/topic_setupcmdline.htm),
[Inno-Ereignisse](https://jrsoftware.org/ishelp/topic_scriptevents.htm),
[Inno-Rückgabecodes](https://jrsoftware.org/ishelp/topic_setupexitcodes.htm),
[Avast CyberCapture](https://support.avast.com/avast/en/ww/home/current/solutions/antivirus-cybercapture),
[Avast-Dateiprüfung](https://support.avast.com/article/258/),
[Microsoft Publisher-Reputation](https://learn.microsoft.com/en-us/windows/apps/package-and-deploy/smartscreen-reputation).

## Build- und Veröffentlichungsprüfung

CI verwendet die Python-Reihe 3.13 mit aktueller Patchversion. Alle Windows-Wheels
werden über `requirements-windows.lock` einschließlich SHA-256 fixiert. Vor PyInstaller wird das versionierte Qt-
Quellmaterial vorbereitet; Lizenztexte, Quellen und zulässiger DLL-Lieferumfang
werden im Paket geprüft. Der Workflow archiviert `build-inventory.json` zusammen
mit dem Installer. Details: [Entwicklung](development.md) und
[Dependencies](dependencies.md).

`scripts/publish_update.ps1` führt vor seinen GitHub-Aufrufen
`check_release_readiness.py --release` aus. Solange rechtliche Platzhalter oder
unregistrierte Vorlagenfelder vorhanden sind, wird keine Veröffentlichung
begonnen. Alle offenen Daten stehen in [missing_data.md](missing_data.md).
Ein interner Entwicklungsbuild bleibt mit sichtbaren Platzhaltern möglich.
Diese maschinelle Vollständigkeitsprüfung ersetzt nicht die inhaltliche
[Veröffentlichungsprüfung](distribution.md).
