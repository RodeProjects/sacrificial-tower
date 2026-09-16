# QProcess-Kompatibilitäts- und Freigabematrix

Die Prozessumstellung betrifft nur isolierte Sacrificial-Tower-Aufträge. Sie
ändert weder installierte Slicer noch deren echte Benutzerprofile. Die
maschinenlesbare Fassung dieser Matrix liegt in
`cooling_tower.slicers.compatibility.SLICER_COMPATIBILITY_MATRIX`.

| Adapter | Programm | Argumentvertrag | Profile und Arbeitsverzeichnis | Erwartete Ausgabe | GUI und Unterprozesse |
|---|---|---|---|---|---|
| Anycubic Slicer Next | `AnycubicSlicerNext.exe` | getrennte Argumente für `--datadir`, `--load-settings`, optional `--load-filaments`, Anordnung, Slicing und Ausgabeverzeichnis | temporäre Profilkopien, eigenes Datenverzeichnis und eigener Auftragsordner | G-Code, optional Metadaten | unabhängig von offener GUI; konkreter Prozessbaum im Windows Job Object |
| OrcaSlicer | `orca-slicer.exe` / `OrcaSlicer.exe` | wie Anycubic | temporäre Profilkopien, eigenes Datenverzeichnis und eigener Auftragsordner | G-Code, optional Metadaten | unabhängig von offener GUI; konkreter Prozessbaum im Windows Job Object |
| Bambu Studio | `bambu-studio.exe` / `BambuStudio.exe` | wie Anycubic | temporäre Profilkopien, eigenes Datenverzeichnis und eigener Auftragsordner | G-Code, optional Metadaten | unabhängig von offener GUI; konkreter Prozessbaum im Windows Job Object |
| PrusaSlicer | `prusa-slicer.exe` / `PrusaSlicer.exe` | `--load`, temporäre INI, `--output`, Ziel, Modell | effektive Werte als temporäre INI, eigener Auftragsordner | G-Code | eigener CLI-Auftrag; Unterprozesse gehören zum Job Object |
| Cura | `CuraEngine.exe` | `slice`, Definitionen mit `-j`, Skalare mit `-s`, Modell mit `-l`, Ziel mit `-o` | Definitionen und effektive Einstellungen, eigener Auftragsordner | G-Code | Engine ist von der Cura-GUI unabhängig; Unterprozesse gehören zum Job Object |
| ideaMaker | `ideaMaker.exe` | nur Erkennung | kein automatisches Slicing | keine | eine laufende GUI wird nicht beendet |
| Simplify3D | `Simplify3D.exe` | nur Erkennung | kein automatisches Slicing | keine | eine laufende GUI wird nicht beendet |

Für alle slicefähigen Adapter gilt: Exitcode `0` ist nur zusammen mit einer
lesbaren G-Code-Ausgabe erfolgreich. Jeder andere Exitcode, `CrashExit`,
Timeout oder Abbruch ist ein Fehlschlag. Standardausgabe und Standardfehler
bleiben getrennt, werden fehlertolerant als UTF-8 dekodiert und im Speicher
jeweils auf 1 MiB begrenzt. Bei Überschreitung bleibt der letzte relevante
Teil im Ergebnis; die vollständigen Bytes werden in einer `.binlog`-Datei im
Diagnoseverzeichnis archiviert.

Negative Anwendungs-Exitcodes sind keine Windows-Abstürze. Insbesondere
Anycubics `-100` (`0xFFFFFF9C`) bezeichnet einen Slicing-/Exportfehler.
`windows_process_status` prüft auch das reservierte NTSTATUS-Bit 28;
gewöhnliche negative Exitcodes fallen dadurch nicht in die Absturzdiagnose.
Die Fehlerübersetzung normalisiert vorzeichenlose DWORD-Werte des alten
Prozess-Backends und vorzeichenbehaftete QProcess-Werte auf dieselbe Meldung.
Echte Windows-Fehler wie `0xC0000142` bleiben als solche erkennbar.
Bitbelegung: [Microsoft NTSTATUS-Dokumentation](https://learn.microsoft.com/en-us/windows-hardware/drivers/kernel/defining-new-ntstatus-values).

## Interne Freigabeschalter

- `COOLING_TOWER_SLICER_PROCESS_BACKEND=qprocess|legacy` wählt den allgemeinen
  Standard. QProcess ist der Programmstandard; `legacy` bleibt als Rückfallweg.
- `COOLING_TOWER_QPROCESS_ADAPTERS=orca_slicer,bambu_studio` schaltet nur die
  aufgelisteten Adapter auf QProcess und lässt alle anderen auf dem alten Weg.
- `COOLING_TOWER_LEGACY_SLICER_ADAPTERS=cura` erzwingt für einzelne Adapter den
  Rückfall. `*` ist bei beiden Adapterlisten zulässig.

Die kontrollierte Doppelprüfung erfolgt pro Adapter mit
`adapter.validate_process_backends(request, report_path=...)`. Beide Backends
laufen nacheinander mit demselben Modell und Profil, aber in getrennten
Arbeits-, Ausgabe-, Diagnose- und Slicer-Umgebungen. Verglichen werden Status,
Rückgabeverhalten, Dateitypen, G-Code-Lesbarkeit, Slicer-Metadaten,
Layeranzahl, maximale Modellhöhe sowie Zeit- und Materialmetadaten. Zeitstempel
oder zufällige Kennungen werden nicht byteweise verglichen.

## Freigabereihenfolge

1. Fake-Slicer- und Stresstests für beide Backends.
2. Doppelprüfung eines kleinen Modells je installiertem Adapter.
3. Adapterweise QProcess-Freigabe über den internen Schalter.
4. QProcess als Standard mit weiter verfügbarem Legacy-Fallback.
5. Entfernung des alten Runners erst in einer späteren, ausdrücklichen Aufgabe
   nach Beobachtung mindestens einer stabilen Programmversion.
