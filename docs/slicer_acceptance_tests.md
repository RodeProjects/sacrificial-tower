# Optionale Abnahmen mit installierten Slicern

Die normalen Tests mit simulierten Slicern und temporären Profilen benötigen
keine lokale Konfiguration. Reale Slicer-Abnahmen bleiben ausdrücklich opt-in;
die normale Testsuche startet keine installierten Slicer.

## Lokale Konfiguration

`tests/slicer_acceptance.example.json` ist eine Vorlage. Für lokale Abnahmen
kopieren und anpassen:

```powershell
Copy-Item tests/slicer_acceptance.example.json tests/slicer_acceptance.local.json
```

Die Vorlage erklärt Zweck, automatische Erkennung, kompatible
Profilkombinationen und erwartete Angaben direkt in `_comment`-Feldern.
`_examples` zeigt Beispielpfade und beispielhafte Profilnamen. Beide dienen nur
als Erklärung und werden nicht als Testeinstellungen ausgewertet; die Datei
bleibt gültiges JSON. Beispiele bei Bedarf in die passenden Einstellungsfelder
übertragen und an die eigene Installation anpassen.

Die lokale Datei ist durch `.gitignore` ausgeschlossen. Alternativ kann ein
anderer Konfigurationspfad über `COOLING_TOWER_SLICER_ACCEPTANCE_CONFIG`
angegeben werden. In `slicers.<adapter_id>.executable` kann der Programmpfad
optional überschrieben werden. Ohne Überschreibung versucht die gemeinsame
Slicer-Erkennung eine passende Installation zu finden. Fehlt sie oder lässt sie
sich nicht verifizieren, wird nur der betroffene optionale Test mit einer
konkreten Skip-Meldung übersprungen.

Profilnamen werden je Test unter
`tests.<test_key>.<adapter_id>.profiles` eingetragen. Maßgeblich ist der Name,
den der installierte Slicer bei der Profilinventur anzeigt. Jeder Test kann
eigene Werte haben; unvollständige Angaben überspringen nur diesen Test. Die
Profile bleiben in den Slicer-Verzeichnissen unverändert. Wo der Test temporäre
Profilkopien benötigt, werden diese in einem eigenen Arbeitsverzeichnis erzeugt.

Die Vorlage enthält unter anderem diese Abnahmen:

| Schlüssel | Verwendet für |
|---|---|
| `source_support_regressions` | Benutzerprofile für simulierte Orca-/Prusa-Stützen |
| `orca_unselected_system_filament` | Orca-Maschine, Prozess und Systemfilament |
| `orca_confirmation_preslice` | Orca-Benutzerprofile und Preslice |
| `prusa_confirmation_preslice` | Prusa-Benutzerprofile und Preslice |
| `preprocessor_acceptance` | Vollständiger Präprozessorablauf für alle vier Slicer mit eigenen Profilkombinationen |
| `phase14_anycubic_base_slice` | Anycubic-Systemprofile für einen realen STL-Slice |
| `phase16_sparse_user_profile` | Anycubic-Systemmaschine und Benutzerprofile für die Sparse-Profilprüfung |
| `phase16_system_profile_slice` | Anycubic-Systemprofile für eine Kalibrierungsprüfung |
| `real_source_preslice_reference` | Anycubic-Systemprofile für den kontrollierten Preslice |
| `real_source_preslice_user_presets` | lokale Anycubic-Benutzerprofile für GUI-Regressionsfälle |
| `user_slicer_regressions` | lokale Prusa-/Orca-Profile sowie die persönlichen Eingabedateien |

Bei `user_slicer_regressions` werden `source_stl` und optional
`orca_slicer.reference_gcode` im gleichen Abschnitt eingetragen. Relative Pfade
beziehen sich auf den Projektordner. Die Regression erwartet weiterhin die
jeweilige bewusst ausgewählte STL; insbesondere sind `Test-STL (manifold).stl`
und `Test-STL (non-manifold).stl` unterschiedliche Testdaten.

## Abnahmen starten

Die Konfiguration aktiviert keine reale Abnahme von selbst. Zusätzlich muss der
jeweilige Opt-in-Schalter gesetzt sein:

| Testgruppe | Opt-in-Schalter |
|---|---|
| Support-Regressionsläufe | `COOLING_TOWER_RUN_SUPPORT_REGRESSION=1` |
| Orca-Integration | `COOLING_TOWER_RUN_INSTALLED_ORCA_INTEGRATION_TEST=1` |
| Prusa-Integration | `COOLING_TOWER_RUN_INSTALLED_PRUSA_INTEGRATION_TEST=1` |
| Reale Bambu-/Anycubic-Abnahmen und Präprozessor-Vier-Slicer-Abnahme | `COOLING_TOWER_RUN_REAL_SLICER_TESTS=1` |
| Benutzer-Slicer-Regressionen | `COOLING_TOWER_RUN_USER_SLICER_REGRESSION=1` |
| Microsoft-Store-Slicer-Erkennung | `COOLING_TOWER_RUN_INSTALLED_STORE_SLICER_TEST=1` |

Ohne passenden Store-Slicer wird die Store-Prüfung mit einem verständlichen
Grund übersprungen. Eine fehlerhafte JSON-Konfiguration wird dagegen als
Konfigurationsfehler gemeldet, damit ungültige lokale Angaben nicht still
übersehen werden.

Die vollständige Präprozessor-Abnahme wird mit den vier Profilkombinationen
unter `tests.preprocessor_acceptance` gestartet:

```powershell
$env:COOLING_TOWER_RUN_REAL_SLICER_TESTS='1'
.\.venv\Scripts\python.exe -m unittest discover -s tests -p test_preprocessor_real_slicers.py -v
```

Sie verwendet eigene STL-Testkörper: einen kleinen Quader, einen 35 mm hohen
schmalen Körper und getrennte Modellbereiche mit unterschiedlichen Höhen.
Sie prüft die Schichtzeiten
des fertigen G-Codes, eine Neuberechnung aus demselben Pre-Slice und die
Unverändertheit der ausgewählten Originalprofile. Zusätzlich werden die
automatische Profilübernahme und ein eigener Durchlauf mit absichtlich
entfernten Druckkopf-Freihüllen geprüft. Dieser muss Ersatzhülle, Hinweis,
Sicherheitshub, erreichbare Turm-/Wartepositionen und geprüfte Fahrwege liefern.
Zusätzliche synthetische Präprozessorfälle untersuchen wechselnde Schichthöhen,
lange aufgeteilte Wartebefehle, Erstschichtgeschwindigkeit und Extrusionsvolumen,
positive/negative Wiederanlaufmengen, Flussfaktoren, vollständige Kreisbögen und
den Erhalt des Originalzustands. Die räumliche Vorauswahl wird außerdem mit
umfangreicheren Bahnlisten und nach Entfernen der eingelesenen Testdatei geprüft.
Diese Softwareprüfungen ersetzen keine Druckerprobung für Haftung, Turmstabilität,
Wiederanlaufqualität oder die reale Maschinengeometrie.
Fehlende lokale Konfiguration
ist ein Skip und ersetzt keine tatsächlich ausgeführte Slicer-Abnahme.
