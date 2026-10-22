# Sacrificial-Tower-Updatekanal

## Ein Kanal im Hauptrepository

Installer, signiertes Manifest und aufgelöste Rechtstexte werden als Anhänge
unveränderlicher Releases in `RodeProjects/sacrificial-tower` veröffentlicht.
Die maßgebliche Kanaldefinition für Programm und Publisher liegt ausschließlich
in `src/cooling_tower/update_channel.py`. Die Anwendung liest ohne GitHub-Anmeldung:

`https://github.com/RodeProjects/sacrificial-tower/releases/latest/download/latest.json`

Ein Manifest für Version `x.y.z` muss exakt auf
`https://github.com/RodeProjects/sacrificial-tower/releases/download/vx.y.z/SacrificialTowerSetup-x.y.z.exe`
zeigen. Signierte Verweise auf andere Repositorys oder Versionen werden ebenfalls
abgewiesen. Der Installer liegt nicht im Quellcodebestand. `main` kann neuer als
der letzte veröffentlichte Installer sein; jeder Release-Tag identifiziert dessen
tatsächlich geprüften Quellcommit.

**Bisherige Tester müssen die neue Version einmal manuell installieren.**
Testinstallationen aus `RodeProjects/sacrificial-tower-updates` wechseln nicht
automatisch. Der alte Kanal wird nach erfolgreicher öffentlicher Abnahme als
abgelöst gekennzeichnet und archiviert. Kein paralleler aktiver Kanal, keine
Übergangsarchitektur und keine dauerhafte Kompatibilität zum alten Kanal.

## Signierung und Integrität

Jedes Manifest ist mit Ed25519 signiert. Version, Installeradresse, SHA-256,
Dateigröße und Versionshinweise sind gemeinsam geschützt. Die Anwendung enthält
nur den öffentlichen Schlüssel `2026-10-private-publisher` und lehnt unbekannte,
fehlende oder ungültige Signaturen ab. Vor Start des Installers werden Größe und
Hash erneut geprüft. Versionsvergleich, HTTPS-Zertifikatsprüfung über Windows,
Abbruch und bestätigte native Installationsübergabe bleiben erhalten.

Der private Schlüssel liegt ausschließlich Windows-DPAPI-verschlüsselt unter dem
Entwicklerkonto. Test-/Buildjobs erhalten weder diesen Schlüssel noch persönliche
GitHub-/SSH-Zugänge. Das frühere GitHub-Signiergeheimnis wurde entfernt. Der alte
Provisionierungshelfer ist historisch und wird nicht mehr verwendet. Eine spätere
Schlüsselrotation bei weiterlaufenden Installationen benötigt eine rechtzeitig
verteilte Übergangsversion. Sicherung/Wiederherstellung muss das zugehörige
Windows-Profil und die DPAPI-Wiederherstellung berücksichtigen.

Die Installer sind derzeit **ohne Authenticode-Zertifikat**. Windows kann bei
manuellen Downloads vor einem unbekannten Herausgeber warnen. Die Manifestprüfung
ersetzt keine öffentliche Herausgeberreputation oder Virenscannerprüfung.

## Geprüft veröffentlichen

Zuerst den [privaten Prüfbranch-/Pushablauf](private_ci.md) abschließen. Anschließend
im normalen Entwicklerkonto aus dem sauberen Projektordner mit PowerShell 7:

```powershell
./scripts/publish_update.ps1 -DevelopmentRelease
```

Dieser eine Aufruf wiederverwendet gültige unveränderte Vollprüfungen und führt
fehlende offizielle Releaseprüfungen über die private vertrauenswürdige Steuerung
aus. Neue Releaseprüfungen verwenden zuerst GitHub-Hardware; nur bei belegtem
`failure`, `timed_out` oder `startup_failure` folgt genau ein lokaler offizieller
Fallback derselben SHA. Abbruch, geänderter Ref oder unklarer Dispatch erlauben
keinen blinden Neustart. Die gehostete Lizenzdialogprüfung bleibt eine gesonderte
Pflicht. Fehlende Nachweise blockieren. Keine zusätzliche lokale Vollsuite und
keine Zeitlimit-Umgehung mit `-AllowTimedOutCI`.

Buildjobs erzeugen Installer und Metadaten ohne Verwaltungszugänge. Der geschützte
Übernahmehelfer prüft ursprünglichen Lauf, Pflichtjobs, Projekt-SHA, Basis,
CI-Steuerung sowie die tatsächlichen Dateien. Erst danach signiert das
Entwicklerkonto. Der Publisher erstellt den zum geprüften Commit gehörenden Tag
`vVERSION` und einen Releaseentwurf mit genau diesen Anhängen:

- `SacrificialTowerSetup-VERSION.exe`
- `latest.json`
- `legal-texts.zip` mit aufgelösten Anbieter-/Datenschutz-/Lizenztexten

Vor Veröffentlichung werden Tag, Dateigrößen und GitHubs SHA-256-Digests erneut
abgeglichen. Erst der vollständige Entwurf wird veröffentlicht und als `Latest`
markiert. GitHub schützt anschließend Tag und Anhänge durch aktivierte
unveränderliche Releases. Der Publisher lädt die veröffentlichten Dateien
tatsächlich erneut herunter und bestätigt Signatur, Größe und Hash. Bei Fehlern
darf nur sein eigener nachweislich unveröffentlichter Entwurf entfernt werden.
Entwurf, Upload, Veröffentlichung und eventuelle Entwurfsbereinigung verwenden
die konkrete von GitHub zurückgegebene Release-ID. Der Tag-Endpunkt ist erst für
veröffentlichte Releases geeignet.
Veröffentlichte Releases und historische Nachweise werden nicht automatisch
gelöscht; der alte Aufbewahrungshelfer blockiert Löschungen im Hauptrepository.

Solange `release_legal_review` offen ist, ausschließlich den erlaubten
Entwicklungsreleasepfad verwenden: sichtbare Kennzeichnung im Titel, in der
Beschreibung und im signierten Manifest, kein Prerelease-Flag und `Latest`.
Dies verschiebt keine Lizenzpflichten und behauptet keine reguläre Vertriebs-
oder Storefreigabe. Nach tatsächlich abgeschlossener regulärer Freigabe entfällt
der Schalter. Details: [Veröffentlichung](distribution.md).

## Abnahme des veröffentlichten Versionsübergangs

Gezielte Tests prüfen Abruf, Versionsvergleich, Signaturen, exakte Kanaladresse,
Download/Integrität und Fehlerfälle. Zusätzlich ist im privaten CI-Adapter die
Operation `update-acceptance.yml` fest konfiguriert. Sie darf ausschließlich im
eingerichteten Windows-Standardkonto und einem neuen eigenen Jobverzeichnis laufen,
wenn dort noch keine Installation registriert ist. Keine Administratorrechte,
kein Zugriff auf die reguläre Installation oder Benutzerdaten des Entwicklerkontos.

Die Abnahme lädt zwei tatsächlich veröffentlichte, unveränderliche benachbarte
Versionen anonym herunter. Sie installiert den alten echten Installer und führt
den ursprünglichen Qt-Updatercode seines Release-Tags aus. Dieser lädt den neuen
echten Installer, bestätigt den nativen Übergabeablauf und startet das neue
installierte Frozen-Programm. Versionsregistrierung, geänderte Programmbytes,
native Statusreihenfolge, tatsächlicher Programmversionsnachweis und ein eigener
Benutzerdaten-Canary werden geprüft. Nur die eigene Testinstallation wird danach
deinstalliert. Die alte gepackte Oberfläche selbst wird dabei nicht automatisiert;
das ist ausdrücklich eine Grenze dieser Abnahme. Die Lizenzdialoge werden durch
die separate gehostete GUI-Pflichtprüfung abgedeckt.

Manipulierte echte Signatur und Hashabweichung vor Prozessstart werden zusätzlich
ungefährlich geprüft. Vollständig anonymer Abruf ist erst nach der beauftragten
Öffnung möglich und wird unmittelbar danach abgenommen; zuvor prüft der Publisher
die tatsächlichen veröffentlichten Dateien mit dem Verwaltungszugang.

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

`scripts/publish_update.ps1 -DevelopmentRelease` prüft die ausdrücklich erlaubte
Entwicklungsfreigabe; ohne diesen Schalter bleibt die reguläre vollständige
Freigabe erforderlich. Die maschinelle Vollständigkeitsprüfung ersetzt keine
inhaltliche Vertriebs- oder Storeprüfung. Offene Angaben stehen unter
[Checkliste](missing_data.md) und [Veröffentlichung](distribution.md).
