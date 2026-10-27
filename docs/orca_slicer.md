# OrcaSlicer-Integration

OrcaSlicer verwendet dieselbe Oberfläche für Auswahl, System-/User-Gruppen,
Kompatibilitätsfilter und Bestätigung wie die übrigen unterstützten Slicer.
Bestätigte Profile werden im Vorslice, in iterativer und manueller Erstellung,
Vorschau und Export weiterverwendet. Die gemeinsamen Grenzen für Zeitlimits,
Abbruch, Prozessisolation und Programmende gelten unverändert; siehe
[Erkennungsmodule](slicer_detection_modules.md).

## Zuständigkeiten

- `slicers/detection/orca_slicer.py`: Installationsmerkmale, Profilwurzeln und
  aktive Auswahl einschließlich der druckerbezogenen Orca-2.4-Konfiguration.
- `slicers/orca_profile_catalog.py`: begrenztes lesendes JSON-Inventar,
  Herkunft, verschachtelte Vorlagen, Katalogspiegel und Hersteller-/Kontobezug.
- `slicers/orca_filament_selection.py`: gespeicherte Auswahl der aktivierten
  Systemfilamente und deren Sichtbarkeit im Filamentmenü.
- `slicers/orca_adapter.py`: vollständige Profilauflösung, Rollenprüfung,
  temporäre CLI-Konfiguration und unverändertes Wiederslicen nativer Projekte.
- `slicers/orca_family.py`: gemeinsame bisherige CLI-/3MF-Basis. Der Code von
  `OrcaFamilyAdapter` wurde hierher verschoben, ohne sein Verhalten oder die
  Adapterimplementierungen von Anycubic und Bambu zu verändern.

Die übrigen Integrationen behalten ihre eigenen Erkennungsmodule. Die gemeinsame
JSON-Auswahllesefunktion bietet lediglich einen Modulhook zur Normalisierung;
standardmäßig verändert dieser keine Eingaben.

## Installation und Profilkatalog

Die bestehende Windows-Erkennung berücksichtigt bekannte Pfade, Registry,
Startmenü und registrierte MSIX-/Store-Pakete. Während der Erkennung wird Orca
nicht gestartet. Neben dem üblichen Roaming-Verzeichnis berücksichtigt das
Orca-Modul die zum konkreten Store-Paket gehörige virtualisierte
`LocalCache/Roaming`-Ablage. Bei mehreren vorhandenen Ablagen entscheidet die
zuletzt gespeicherte Hauptkonfiguration. Ein vorhandenes portables `data_dir`
neben der EXE hat Vorrang; dessen Benutzerprofile werden nicht mit Roaming gemischt.
Ein beliebiger, ausschließlich per eigenem Startparameter gesetzter `--datadir`
außerhalb dieser bekannten Ablagen lässt sich aus dem Programmpfad allein nicht
ermitteln.

Gelesen werden `user/<Konto>/{machine,process,filament}`, aktive
`system/<Hersteller>`-Kataloge und die zugehörigen gebündelten Profile. Fehlende
Vorlagen können aus dem gebündelten Katalog ergänzt werden; für gleichnamige
Systemprofile hat der aktive Katalog Vorrang. Die gemeinsame Filamentbibliothek
und `Custom` bleiben als mögliche Eltern verfügbar. Ohne eingerichteten
Systemkatalog dient die gebündelte Herstellerliste als Ausgangspunkt.
`ota`, Backups, Logs, Druckerverbindungen und sonstige Hilfsdaten werden nicht
rekursiv als Profilkatalog durchsucht.

Der Katalog erkennt auch verschachtelte Bibliotheksverzeichnisse, beispielsweise
`filament/base` und herstellerspezifische Materialordner. Modelldeskriptoren,
Manifeste und widersprüchliche Rollen werden nicht als Presets angeboten.
Abstrakte `instantiation=false`-Vorlagen stehen nur der Vererbung zur Verfügung.
System-/User-Herkunft folgt dem tatsächlichen Ablageort. Gleichnamige echte
Benutzerprofile werden nicht pauschal zusammengelegt.

Vererbung und `include` werden über den vorhandenen indizierten Resolver
aufgelöst. Systemeltern werden nach Hersteller, Benutzereltern nach Konto
eingegrenzt. Fehlende, zyklische oder verbleibend mehrdeutige Eltern verhindern
die Verwendung des betreffenden Profils. Fehlerhafte Einzeldateien verdrängen
keine anderen gültigen Profile. JSON wird auf 8 MiB je Datei begrenzt, die
Inventarsuche auf 50.000 Dateien. Gelesene Werte werden anhand von Pfad, Größe
und Änderungszeit zwischengespeichert; der Inventarcache überwacht auch Eltern.

## Aktive Profile und tatsächliche Verwendung

Ältere Konfigurationen enthalten aktive Rollen in `presets`. Orca 2.4 speichert
Prozess und Filamente zusätzlich in `orca_presets` je Maschine. Verwendet wird
nur die eindeutig zur aktiven Maschine gehörende Zeile, einschließlich nummerierter
Filamente. Die oberste Liste `filaments` beschreibt installierte Materialien
und darf nicht als aktive Auswahl gelten. Fehlende oder mehrdeutige Zeilen
übernehmen keine Auswahl eines anderen Druckers. Orcas Kommentar mit MD5-Prüfsumme
nach dem JSON wird durch den bestehenden Konfigurationsleser unterstützt.

Die oberste Liste `filaments` steuert dagegen die Sichtbarkeit von
Systemfilamenten: Standardmäßig erscheinen nur die dort in Orca ausgewählten
Materialien, zusätzlich zum bestehenden Drucker-/Kompatibilitätsfilter. Eigene
Filamentprofile bleiben davon unabhängig unter `- User presets -` sichtbar;
`- System presets -` folgt darunter. Leere Gruppen werden ausgeblendet.
„Filter deaktivieren / alle Profile anzeigen“ zeigt auch nicht ausgewählte
Systemfilamente. Eine dort ausdrücklich gewählte, kompatible Kombination kann
normal bestätigt und verwendet werden; das bloße Erweitern des Menüs ändert
den automatischen Profilvorschlag nicht.

Ist die gespeicherte Liste tatsächlich leer, erscheinen als Rückfall alle zum
Drucker passenden Systemfilamente. Eine nichtleere Liste ohne passende Treffer
gilt nicht als leere Auswahl. Fehlt die optionale Liste oder ist sie nicht
lesbar/gültig, bleibt der bisherige kompatible Katalog verfügbar. Die begrenzte
Konfigurationslesung erfolgt bei jeder Katalog-/Matching-Anforderung neu, auch
bei unverändertem Inventarcache. Nicht ausgewählte Profile bleiben im Inventar
und Resolver erhalten, damit Benutzerprofile ihre Systemeltern weiter erben.
Die gemeinsame Filterlogik stellt dafür einen optionalen Adapterhook bereit;
nur OrcaSlicer verwendet ihn, die Regeln anderer Slicer bleiben unverändert.

Jeder Slice erhält ein eigenes Arbeitsverzeichnis, einen eigenen `--datadir`
und typisierte, vollständig aufgelöste Rollenprofile. Der ausgewählte eigene
Drucker bleibt fachlich erhalten; eine nötige Kompatibilitätskennung wird nur in
den temporären Kopien harmonisiert. Laufbezogene Prozessüberschreibungen werden
erst nach der Vererbung angewandt. Originale bleiben ausschließlich lesend.
Auch direkte Aufrufe des Orca-Commandbuilders weisen Arbeits- und Ausgabeorte
innerhalb geschützter Slicerverzeichnisse ab. Der endgültige Export der iterativen
und der manuellen Methode ruft dieselbe Orca-eigene Prüfung auf. Sie schützt vollständige
Datenwurzeln, auch etwaige Log-/Cache-Geschwister neben `user` und `system` in
virtualisierten Store-Ablagen, ohne sie als Profilkatalog durchsuchen zu müssen.

Gemeinsame Objekt-/Turm-Slices verwenden das tatsächlich exportierbare native
3MF mit festen Positionen. Beim Wiederslicen dieses Projekts werden keine
externen Rollenprofile über dessen eingebettete Einstellungen geladen.
Volle Turmfüllung und simulierte Stützen bleiben objektspezifisch; die gespeicherte
Füllung des Originalobjekts wird dadurch nicht global geändert. Die normale
Prüfung der Füllungsübernahme bleibt aktiv.

Orca benennt das Projektobjekt im G-Code als `Cooling tower`. Die Füllungsprüfung
in Python und C++ sowie die Vorschau erkennen sowohl diese Form als auch
`cooling_tower`. Dadurch wird der Turm korrekt geprüft und aus den Werkzeugpfaden
des Originalobjekts ausgeschlossen. Ein Test auf erreichbare Zielzeit ist von der
technischen Sliceprüfung getrennt: Ein kleines Iterationsbudget darf weiterhin
einen wahrheitsgemäß gekennzeichneten, geprüften Zwischenstand ergeben.

## Prüfungen und Umfang des Nachweises

Die Orca-eigene Zeitlogik berücksichtigt Maschinenlimits, Junction Deviation
bei Marlin 2, Übergänge zwischen unterschiedlichen Geschwindigkeiten und
Orcas begrenzten Rückwärts-/Vorwärtsdurchlauf. Der bisherige generische
Zeitpfad unterschätzte insbesondere `M205 J`-Dateien erheblich. Die getrennten
Python-/C++-Implementierungen und die Cache-Verwerfung sind im
[Analysevertrag](native_analysis.md#unabhängige-orca--und-prusa-zeitpolitiken)
beschrieben. Bambu und Anycubic verwenden ihre bisherigen Zeitpolitiken.

`test_user_slicer_regressions` prüft zusätzlich die bereitgestellte vollständige
98-mm-STL mit 490 Layern, sechs isolierten und mindestens drei gemeinsamen
Slices, erst danach zulässiger Übernahme, laufender Seitenvorschau sowie
erneutem Slicen des tatsächlich exportierten 3MF. Der Test benötigt keine
Bildschirmsteuerung. Seine Eingabedatei wird explizit über
`COOLING_TOWER_REGRESSION_STL` und die Freischaltung über
`COOLING_TOWER_RUN_USER_SLICER_REGRESSION=1` angegeben.

Der konkrete gemeldete Orca-Fall wurde aus dem damaligen exportierten Projekt
erneut geslict. Die frühere Berechnung von 11,839778 s ergibt mit der eigenen
Orca-Zeitpolitik 14,302294 s; die unabhängige Anzeige im bereitgestellten
Screenshot betrug 14,4 s. Der Regressionstest erlaubt hierfür 0,15 s Abstand,
keine behauptete bitgenaue Übereinstimmung mit einer gerundeten Anzeige.
Die berechnete Gesamtzeit liegt im selben Fall weniger als 1 % von Orcas
eingebetteter nativer Zeitschätzung entfernt. Dieser zusätzliche opt-in
Nachweis verwendet `COOLING_TOWER_ORCA_REFERENCE_GCODE`. Ein erneuter
GUI-Eingriff ist dafür nicht nötig.

Reproduzierbare Fixturetests: `test_orca_profiles`. Sie prüfen unter anderem
Store/Portable, aktive Profile, Spiegel, Vererbung/Include, Filter, Cachewechsel,
beschädigte Daten, sichere CLI-Kopien, Rollen, Schutzpfade, Fehlermeldungen,
System-/User-Gruppierung, aktivierte Systemfilamente, leere/fehlende Auswahllisten,
Filterumschaltung, Bestätigung zuvor ausgeblendeter Filamente und Schließen nach
einem Profilfehler. Die bestehenden
Prozess-, GUI-, Prusa-, Bambu- und Anycubic-Regressionen bleiben Teil der Gesamtsuite.
`test_native_gcode_analysis`, `test_joint_project` und
`test_profile_and_preview_refinements` sichern die Orca-Objektkennzeichnungen ab.

Der zusätzliche Test mit der lokalen Installation ist ausdrücklich opt-in:

```powershell
$env:COOLING_TOWER_RUN_INSTALLED_ORCA_INTEGRATION_TEST = '1'
.\.venv\Scripts\python.exe -m unittest discover -s tests -p test_orca_slicer_integration.py -v
```

Die lokale Abnahme verwendet das Store-Paket 2.4.3.0, dessen CLI sich als 2.4.2
meldet, und die eingerichteten Anker-M5-Profile einschließlich eigener Maschinen-,
Filament- und Prozessprofile. Sie prüft Bestätigung, Vorslice, iterative
Kalibrierung/Vorschau, STL-/G-Code-/3MF-Export, manuelle Erstellung/Export,
angebotene Stützensimulationen, Legacy-/QProcess-Parität und erneutes Slicen des
exportierten 3MF mit identischer minimaler Schichtzeit. Inhalt, Größe,
Änderungszeit und Bestand der verwendeten Slicer-Quelldateien werden verglichen.
Dies ist ein konkreter Versions-/Profilnachweis, keine Zusicherung für jede
zukünftige Orca-Version oder jede denkbare Druckerkonfiguration.

Grundlagen: [offizielle CLI-Dokumentation](https://github.com/OrcaSlicer/OrcaSlicer/wiki/cli_mode),
[CLI-Datenverzeichnis](https://github.com/OrcaSlicer/OrcaSlicer/wiki/cli_misc)
und [Konfigurationsformat](https://github.com/OrcaSlicer/OrcaSlicer/blob/main/src/libslic3r/AppConfig.cpp).
Es wird ausschließlich eigener Integrationscode verwendet; kein Orca-Quellcode
und keine neue Laufzeitbibliothek wurden übernommen. Der Slicer bleibt ein separat
installiertes externes Programm; die [bestehenden Lizenzgrenzen](dependencies.md#slicer-dienste-und-eigene-inhalte)
gelten weiterhin.
