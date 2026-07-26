# Automatischer Update-Kanal

Die installierte Windows-Anwendung prüft im Hintergrund das öffentliche
Manifest unter:

`https://raw.githubusercontent.com/RodeProjects/sacrificial-tower-updates/main/latest.json`

Das private Quellcode-Repository und persönliche GitHub-Zugangsdaten sind für
Endnutzer nicht erforderlich. Der öffentliche Kanal enthält ausschließlich den
Windows-Installer, dessen SHA-256-Wert und die aktuelle Versionsnummer.

## Veröffentlichung einer neuen Version

### Einmalige Einrichtung der Windows-Signatur

Update-Builds werden nur noch mit einer gültigen Authenticode-Signatur
veröffentlicht. Dadurch erkennen Windows und Virenschutzprogramme den
Herausgeber auch dann wieder, wenn sich der SHA-256-Wert bei einer neuen
Version ändert. Im privaten Quellcode-Repository müssen dafür diese
GitHub-Actions-Secrets hinterlegt sein:

- `WINDOWS_SIGNING_CERTIFICATE_BASE64`: ein von einer öffentlich vertrauten
  Zertifizierungsstelle ausgestelltes Code-Signing-Zertifikat samt privatem
  Schlüssel im PFX/PKCS#12-Format, vollständig Base64-kodiert.
- `WINDOWS_SIGNING_CERTIFICATE_PASSWORD`: das Kennwort der PFX-Datei.

Das Zertifikat wird nur im kurzlebigen Zertifikatsspeicher des GitHub-Runners
importiert. Der Build signiert die Programm-EXE, den Installer, dessen
temporäre Setup-Kopie und den Uninstaller mit SHA-256 und einem RFC-3161-
Zeitstempel. Fehlt ein Secret oder ist eine Signatur ungültig, bricht der
Workflow ab. Auch `publish_update.ps1` prüft Signatur und Zertifikat nochmals,
bevor ein Release oder `latest.json` verändert wird. Ein selbstsigniertes
Zertifikat reicht für verteilte Updates nicht aus.

1. `APP_VERSION` in `src/cooling_tower/version.py` erhöhen.
2. Änderungen testen, committen und auf `main` pushen.
3. Das Skript `scripts/publish_update.ps1` ausführen. Es startet den Workflow
   `Build Windows update`, wartet auf den erfolgreichen Build und veröffentlicht
   anschließend das Ergebnis.

Das Skript lädt das geprüfte Actions-Artefakt herunter, erstellt im öffentlichen
Repository ein Release und aktualisiert anschließend `latest.json`. Es verwendet
nur die lokale, interaktive GitHub-CLI-Anmeldung des Entwicklers. Im Programm,
Installer oder öffentlichen Manifest werden keine Tokens gespeichert.

## Verhalten im Programm

- Die Prüfung findet nur in der gebauten Windows-Anwendung statt.
- Netzwerkfehler oder ein nicht erreichbarer Kanal stören die normale Nutzung
  nicht.
- Der Button `Aktualisieren` erscheint nur bei einer numerisch höheren Version.
- Der Installer wird vollständig heruntergeladen und gegen Größe und SHA-256
  aus dem Manifest geprüft.
- Alle veröffentlichten Windows-EXE-Dateien sind Authenticode-signiert; ein
  unsigniertes Build kann den Update-Kanal nicht erreichen.
- HTTPS-Zertifikate werden über den nativen Windows-Zertifikatsspeicher
  geprüft.
- Nach erfolgreicher Prüfung wird Inno Setup still gestartet, die Anwendung
  beendet, ersetzt und anschließend neu geöffnet.
