# Sichere Deinstallation

Der Windows-Installer registriert den integrierten Inno-Setup-Deinstaller in
Windows unter **Einstellungen > Apps > Installierte Apps**. Zusätzlich wird im
Startmenü der Eintrag **Sacrificial Tower deinstallieren** angelegt. Beide Wege
verwenden denselben Deinstaller und dieselbe Installationshistorie.

## Was standardmäßig entfernt wird

Der Deinstaller entfernt die vom Installer protokollierten Programmdateien,
die Startmenüeinträge, eine gegebenenfalls angelegte Desktop-Verknüpfung und
den Windows-Deinstallationseintrag. Der Programmordner wird nur entfernt, wenn
er anschließend leer ist. Fremde oder nachträglich manuell dort abgelegte
Dateien werden nicht über ein pauschales Platzhalter-Muster gelöscht.

Die installierte Anwendung hält während ihrer gesamten Laufzeit einen
Windows-Mutex. Der Deinstaller prüft diesen vor jeder Änderung und bricht ab,
solange Sacrificial Tower noch läuft. Bei einer interaktiven Deinstallation
fordert er verständlich zum Schließen des Programms auf. Dadurch beginnt die
Entfernung erst, wenn die Programmdateien nicht mehr aktiv verwendet werden.

## Persönliche Daten

Die Daten der installierten Variante liegen unter:

`%LOCALAPPDATA%\RodeProjects\SacrificialTower\standalone`

Sie bleiben standardmäßig erhalten. Damit bleiben Einstellungen,
Profilzuordnungen, Logs und erzeugte Standardausgaben für eine spätere
Neuinstallation verfügbar. Bei einer interaktiven Deinstallation fragt der
Deinstaller separat, ob dieser Ordner unwiderruflich gelöscht werden soll;
**Nein** ist die sichere Vorauswahl.

Die Löschung ist absichtlich auf `standalone` begrenzt. Die Instanzen
`development`, `microsoft-store` und benutzerdefinierte Instanz-IDs werden vom
Deinstaller des eigenständigen Installers nie entfernt.

## Stille Deinstallation

Eine stille Deinstallation bewahrt persönliche Daten ohne Rückfrage:

```powershell
& "$env:LOCALAPPDATA\Programs\SacrificialTower\unins000.exe" `
  /VERYSILENT /SUPPRESSMSGBOXES /NORESTART
```

Nur der zusätzliche, ausdrücklich gesetzte Parameter `/DELETEUSERDATA`
autorisiert auch in diesem Modus die unwiderrufliche Löschung der
`standalone`-Daten:

```powershell
& "$env:LOCALAPPDATA\Programs\SacrificialTower\unins000.exe" `
  /VERYSILENT /SUPPRESSMSGBOXES /NORESTART /DELETEUSERDATA
```

Der Datenpfad kann nicht über die Kommandozeile ersetzt werden. Dadurch kann
der Löschvorgang weder auf einen übergeordneten Ordner noch auf eine andere
Programminstanz umgelenkt werden.

## Programmaktualisierungen

Eine Sacrificial-Tower-Programmaktualisierung ist keine Deinstallation. Builds
mit derselben `AppId` werden über die vorhandene Installation gelegt und die
Inno-Installationshistorie wird fortgeschrieben. Die ausgelagerten,
schema-versionierten Benutzerdaten bleiben dabei erhalten und werden beim
nächsten Programmstart über die dokumentierte Migrationskette geladen.
