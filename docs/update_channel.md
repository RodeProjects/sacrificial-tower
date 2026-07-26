# Automatischer Update-Kanal

Die installierte Windows-Anwendung prüft im Hintergrund das öffentliche
Manifest unter:

`https://raw.githubusercontent.com/RodeProjects/sacrificial-tower-updates/main/latest.json`

Das private Quellcode-Repository und persönliche GitHub-Zugangsdaten sind für
Endnutzer nicht erforderlich. Der öffentliche Kanal enthält ausschließlich den
Windows-Installer, dessen SHA-256-Wert und die aktuelle Versionsnummer.

## Veröffentlichung einer neuen Version

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
- HTTPS-Zertifikate werden über den nativen Windows-Zertifikatsspeicher
  geprüft.
- Nach erfolgreicher Prüfung wird Inno Setup still gestartet, die Anwendung
  beendet, ersetzt und anschließend neu geöffnet.
