# Sacrificial-Tower-Update-Kanal

Die eigenständig installierte Windows-Anwendung prüft im Hintergrund das
öffentliche Manifest unter:

`https://raw.githubusercontent.com/RodeProjects/sacrificial-tower-updates/main/latest.json`

Das private Quellcode-Repository und persönliche GitHub-Zugangsdaten sind für
Endnutzer nicht erforderlich. Der öffentliche Kanal enthält ausschließlich den
Windows-Installer, das kryptografisch signierte Manifest und die zugehörigen
Prüfdaten.

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
3. `scripts/publish_update.ps1` im normalen Windows-Benutzerkontext ausführen.

Das Skript startet den Workflow
`Windows-Installer für Sacrificial-Tower-Update bauen`, wartet auf den
erfolgreichen Build und lädt dessen Artefakt herunter. Anschließend prüft es die
Ed25519-Signatur sowie Installergröße und SHA-256 erneut. Erst danach erstellt
es im öffentlichen Update-Repository ein Release und veröffentlicht exakt das
bereits im privaten Build signierte `latest.json`.

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
- Jede Version `x.y.0` und die ausdrücklich eingetragene Version `0.4.8` sind
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
  -LatestVersion 0.4.8 `
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
- HTTPS-Zertifikate werden über den nativen Windows-Zertifikatsspeicher
  geprüft.
- Nach erfolgreicher Prüfung wird Inno Setup still gestartet, die Anwendung
  beendet, ersetzt und anschließend neu geöffnet.
