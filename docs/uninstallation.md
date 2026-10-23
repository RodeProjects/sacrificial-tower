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
Dateien werden nicht über ein pauschales Platzhalter-Muster gelöscht. Nach der
Datenbereinigung werden auch leere Unterordner und der dann leere Programmordner
entfernt; Verzeichnisverknüpfungen werden dabei nicht durchsucht.

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
Deinstaller separat, ob die persönlichen Daten unwiderruflich gelöscht werden sollen;
**Nein** ist die sichere Vorauswahl.

Die ausdrückliche Löschung umfasst außerdem ältere Speicherorte innerhalb der
jeweiligen Installation: `config`, `output`, `_internal/config` und
`_internal/output`, jeweils einschließlich Sicherungen und Unterordnern.
Frühere Versionen legten dort Einstellungen, Logs und erzeugte Ausgaben ab.
Die spätere Migration kopiert Einstellungen nach AppData und bewahrt deren
Originale; deshalb reicht die alleinige Löschung des heutigen Datenordners nicht.
Ohne Löschbestätigung bleiben auch diese alten persönlichen Daten erhalten.

Die Löschung unter AppData ist absichtlich auf `standalone` begrenzt. Die Instanzen
`development`, `microsoft-store` und benutzerdefinierte Instanz-IDs werden vom
Deinstaller des eigenständigen Installers nie entfernt. Der Entwicklungsordner
des Quellcodes wird ebenfalls nicht durchsucht. Ohne eine bewusst gesetzte
Pfadumleitung verwenden Entwicklungs- und installierte Version getrennte Daten.
Frei gewählte Ausgabeziele außerhalb der Installation und des Standalone-
Datenordners bleiben erhalten; der Deinstaller verfolgt dafür keine Pfade aus
Benutzereinstellungen.

Verzeichnisverknüpfungen werden bei der Datenlöschung nur selbst entfernt,
ihre Ziele bleiben erhalten. Liegt ein Datenordner unter einem verknüpften
übergeordneten Ordner, wird er nicht rekursiv gelöscht. Nicht löschbare Daten
werden protokolliert und bei interaktiver Deinstallation mit den betroffenen
Pfaden gemeldet, ohne die Bereinigung anderer Speicherorte auszulassen.

## Stille Deinstallation

Eine stille Deinstallation bewahrt persönliche Daten ohne Rückfrage:

```powershell
& "$env:LOCALAPPDATA\Programs\SacrificialTower\unins000.exe" `
  /VERYSILENT /SUPPRESSMSGBOXES /NORESTART
```

Nur der zusätzliche, ausdrücklich gesetzte Parameter `/DELETEUSERDATA`
autorisiert auch in diesem Modus die unwiderrufliche Löschung der
`standalone`-Daten und der älteren Speicherorte innerhalb der Installation:

```powershell
& "$env:LOCALAPPDATA\Programs\SacrificialTower\unins000.exe" `
  /VERYSILENT /SUPPRESSMSGBOXES /NORESTART /DELETEUSERDATA
```

Der Datenpfad kann nicht über die Kommandozeile ersetzt werden. Dadurch kann
der Löschvorgang weder auf einen übergeordneten Ordner noch auf eine andere
Programminstanz umgelenkt werden.

## Regressionstests

`scripts/test_uninstaller.ps1` prüft mit einer eigenen Setup-Identität und
isolierten Testpfaden die Datenerhaltung, die vollständige Löschung aktueller
und älterer Daten, den Fall ohne heutigen AppData-Ordner sowie das Verschwinden
des leeren Programmordners. Fremde Dateien und eine getrennte Entwicklungsinstanz
müssen erhalten bleiben. Die Prüfung wartet auf die nachgelagerte Bereinigung
im separaten Inno-Deinstallationsprozess, bevor sie das Dateisystem bewertet.
Junctions innerhalb alter Ausgabeordner und oberhalb des heutigen Datenordners
dürfen keine Dateien im verknüpften Ziel löschen. Eine deshalb ausgelassene
Datenlöschung muss gemeldet werden; andere Speicherorte werden weiter bereinigt.
`tests/test_distribution_and_paths.py` sichert zusätzlich die getrennten
Standard-Datenpfade von Python-Entwicklung und installierter EXE ab.

Grundlagen: Inno Setup dokumentiert die zusätzliche Löschung von Laufzeitdateien
unter [UninstallDelete](https://jrsoftware.org/ishelp/topic_uninstalldeletesection.htm)
und das Verhalten bei Verzeichnisverknüpfungen unter
[DelTree](https://jrsoftware.org/ishelp/topic_isxfunc_deltree.htm).

## Programmaktualisierungen

Eine Sacrificial-Tower-Programmaktualisierung ist keine Deinstallation. Builds
mit derselben `AppId` werden über die vorhandene Installation gelegt und die
Inno-Installationshistorie wird fortgeschrieben. Die ausgelagerten,
schema-versionierten Benutzerdaten bleiben dabei erhalten und werden beim
nächsten Programmstart über die dokumentierte Migrationskette geladen.
