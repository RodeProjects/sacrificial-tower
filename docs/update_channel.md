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

### Schlüsselrotation

Der derzeitige Schlüssel heißt `2026-07-primary`. Eine reguläre Rotation muss
zweistufig erfolgen:

1. Eine noch mit dem alten Schlüssel signierte Programmversion veröffentlicht
   zusätzlich den neuen öffentlichen Schlüssel.
2. Erst nachdem diese Übergangsversion verteilt wurde, wird das GitHub-Secret
   durch den neuen privaten Schlüssel ersetzt und die neue Schlüssel-ID für
   Builds aktiviert.

Der private Schlüssel darf niemals in Dateien, Logs, Commit-Nachrichten oder
Artefakten gespeichert werden. `scripts/provision_update_signing_key.py` sendet
ihn bei einer kontrollierten Rotation direkt über die GitHub CLI an das Secret
und gibt ausschließlich den öffentlichen Anteil aus.

## Veröffentlichung einer neuen Version

1. `APP_VERSION` in `src/cooling_tower/version.py` erhöhen.
2. Änderungen vollständig testen, committen und auf `main` übernehmen.
3. Den GitHub-Actions-Workflow `Tests` für exakt diesen `main`-Commit
   erfolgreich abschließen lassen; für die unten beschriebene, ausdrücklich
   freigegebene Zeitlimit-Ausnahme gilt der lokale Kompletttest.
4. Veröffentlichungsart wählen und das Skript im normalen
   Windows-Benutzerkontext ausführen:
   - Kommerziell freigegeben: `scripts/publish_update.ps1`
   - Unverkäufliche Testversion: `scripts/publish_update.ps1 -DevelopmentRelease`

Nach einem durch das CI-Zeitlimit abgebrochenen `Tests`-Lauf kann ein
ausdrücklich freigegebenes Entwicklungsrelease mit
`scripts/publish_update.ps1 -DevelopmentRelease -AllowTimedOutCI`
veröffentlicht werden, wenn der lokale vollständige Testlauf für den
Anwendungscode erfolgreich war. Die Ausnahme wird im Installer-Workflow
protokolliert und ist für kommerzielle Releases nicht verfügbar. Der
Installer-Build sowie Lieferumfangs-, Installations-, Signatur- und
Integritätsprüfungen bleiben verpflichtend.

Ein Entwicklungsrelease ist nur zulässig, solange die ausgelieferten
Nutzungsbedingungen das Programm eindeutig als noch nicht für den regulären
Verkauf freigegebene Entwicklungsversion kennzeichnen. Es darf ausschließlich
die bekannten Anbieter-, Vertriebs- und Abschlussnachweise zurückstellen. Name,
Marke und Kontakt, die erfolgreiche `main`-CI oder die dokumentierte
Zeitlimit-Ausnahme, die Lieferumfangsprüfung,
Installerprüfungen, Signatur und Integritätskontrollen bleiben verpflichtend.
Der Releasetitel, die Releasebeschreibung und die signierten Versionshinweise
kennzeichnen die Entwicklungsversion weiterhin ausdrücklich. GitHub-Releases
erhalten auch für Entwicklungsversionen kein Prerelease-Flag, damit die neueste
veröffentlichte Version mit `--latest` als „Latest“ angezeigt werden kann.
GitHub erlaubt diese Markierung nicht für Prereleases. Die Markierung als
„Latest“ begründet keine kommerzielle Freigabe; die offenen Angaben müssen vor
einem kommerziellen Release nachgetragen werden.

Das Skript startet den Workflow
`Windows-Installer für Sacrificial-Tower-Update bauen`, wartet auf den
erfolgreichen Build und lädt dessen Artefakt herunter. Anschließend prüft es die
Ed25519-Signatur sowie Installergröße und SHA-256 erneut. Erst danach erstellt
es im öffentlichen Update-Repository ein Release und veröffentlicht exakt das
bereits im privaten Build signierte `latest.json`.

Der Installer-Workflow prüft im Normalfall über die GitHub-API, dass der
Workflow `Tests` für exakt denselben Commit auf `main` als erfolgreicher
Push-Lauf abgeschlossen wurde. Ein Lauf eines anderen Commits, Branches oder
Ereignisses genügt nicht. Nur bei expliziter Entwicklungsrelease-Ausnahme
wird diese CI-Prüfung übersprungen und der Grund im Workflow protokolliert.
Die vollständige Testsuite wird deshalb nicht ein zweites Mal im
Installer-Workflow ausgeführt. Die nativen Prozess-Stresstests bleiben
zusätzlich im eigenständigen Workflow `Windows-Prozess-Stresstests` isoliert.

Schlägt die Veröffentlichung des Manifests nach dem Erstellen des Releases
fehl, entfernt das Skript das unvollständige Release wieder. Es verwendet nur
die lokale, interaktive GitHub-CLI-Anmeldung des Entwicklers. Im Programm,
Installer oder öffentlichen Manifest werden keine GitHub-Tokens gespeichert.

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

## Eigenständiger und späterer Store-Build

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
- Nach erfolgreicher Prüfung wird Inno Setup still gestartet, die Anwendung
  beendet, ersetzt und anschließend neu geöffnet.

## Zusätzliche Build- und Vertriebsprüfung ab September 2026

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
[Vertriebsfreigabe](commercial_release.md).
