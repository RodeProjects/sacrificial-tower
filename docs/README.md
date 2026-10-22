# Sacrificial Tower: Dokumentation für Kühltürme und Layerzeiten im 3D-Druck

Sacrificial Tower erstellt zusätzliche Kühltürme, die beim FDM-/FFF-3D-Druck
mehr Zeit zum Abkühlen zwischen den Layern schaffen. Die Turmform wird
automatisch berechnet oder manuell gestaltet und mit dem gewählten Slicer auf
ihre Layerzeiten geprüft. Beide Modi exportieren im STL-Ablauf ein gemeinsames
3MF-Projekt mit Modell und Turm sowie die zusätzliche Turm-STL.
Einstieg und Startbefehle stehen im
[Repository-README](../README.md). Diese Übersicht ist der zentrale Wegweiser.
Für die Bedienung mit [Manuellem Editor](manual_editor.md) und
[Turmgeometrie](tower_geometry.md) beginnen; für Installation und Tests mit
[Entwicklung](development.md). Ältere Messungen und Anforderungskataloge stehen
getrennt unter „Nachweise und historische Einordnung“.

| Thema | Maßgebliches Dokument |
|---|---|
| English FAQ: minimum layer time, sacrificial cooling towers, supported slicers and downloads | [FAQ](faq.md) |
| Öffentliche Projekttexte, GitHub-Metadaten und Auffindbarkeit in Such-/KI-Systemen | [Auffindbarkeit und Veröffentlichung](discoverability.md) |
| Komponenten, Verantwortlichkeiten, Datenfluss und Erweiterung | [Architektur](architecture.md) |
| Turmhöhe, lineare Verbreiterung, konkave Verjüngung und Absätze | [Turmgeometrie](tower_geometry.md) |
| Manueller Béziereditor, Slicervoraussetzungen, feste Slicerprüfung, Zustände und Abnahme | [Manueller Editor](manual_editor.md) |
| Direkte Vorschauaktionen sowie entfernte und verbleibende Einstellungen links | [Manuelle Bedienelemente](manual_controls_analysis.md) |
| Installation, Tests, Build, gezielte Testauswahl | [Entwicklung](development.md) |
| Konfiguration und Start optionaler Abnahmen mit installierten Slicern | [Slicer-Abnahmetests](slicer_acceptance_tests.md) |
| Abhängigkeiten, Versionen, Lizenzquellen und Pflichten | [Dependencies](dependencies.md) |
| Apache-2.0, kostenlose offizielle Downloads, Microsoft Store und Freigaben | [Veröffentlichung](distribution.md) |
| Nachprüfung der Lizenzumstellung, Paketnachweise und offene Freigabepunkte | [Apache-2.0-Prüfnachweis](license_review.md) |
| Aktueller Gesamtabgleich: offene GitHub-/Store-Schritte, Runner-Sicherheit und öffentliche Rechtstexte | [Veröffentlichungsprüfung](publication_readiness.md) |
| Freiwilliges Dankeschön über PayPal, Datenfluss, Gebühren und Betreiberpflichten | [Freiwillige Unterstützung](voluntary_support.md) |
| GitHub Issues, Diagnosepakete, Datenminimierung und vertraulicher Kontakt | [Support und Diagnose](support.md) |
| Offene Anbieter-/Veröffentlichungsnachweise mit Fundstellen | [Platzhaltercheckliste](missing_data.md) |
| G-Code-/STL-Prüfung, Profile, Preslice und Cache | [Quellenablauf](source_workflow.md) |
| Slicer-Erkennung und neue Adapter | [Erkennungsmodule](slicer_detection_modules.md) |
| OrcaSlicer, eigene JSON-Kataloge, Store/Portable und reale Abnahme | [OrcaSlicer](orca_slicer.md) |
| PrusaSlicer, native Projekte, Füllungsprüfung und Vorschau | [PrusaSlicer](prusa_slicer.md) |
| Prozessisolation, QProcess und Abbruch | [Slicer-Prozesse](slicer_qprocess_compatibility.md) |
| Einstellungen, Schema, Migrationen und Downgrade | [Persistenz](settings_migrations.md) |
| Python-/C++-Analyse, Parität und Fallback | [Native Analyse](native_analysis.md) |
| Signierte Programmaktualisierungen und Veröffentlichung | [Update-Kanal](update_channel.md) |
| Private gemeinsame CI, Runnertrennung und geprüfte Push-/Releasebefehle | [Private CI](private_ci.md) |
| Installation und Datenbereinigung | [Deinstallation](uninstallation.md) |

## Nachweise und historische Einordnung

- [Umsetzung der Projektprüfung September 2026](implementation_audit_2026_09.md)
- [Historische Entwicklungsphasen](history/development_phases.md): archivierter
  früherer README-Stand; keine aktuelle Bedienungsanleitung.
- [Referenzstand 0.6.5](reference_baseline_0_6_5.md): Vergleichsbasis, nicht aktuelle Version.
- [UI-Abnahmekriterien](ui_overarbeitung_abnahmekriterien.md): ursprünglicher
  Anforderungskatalog; aktuelle Umsetzung und Tests haben Vorrang.

Anbieterangaben werden nur in `config/legal_profile.json`, gemeinsame und
automatische Produktstandardwerte in `config/default_settings.json` gepflegt.
Die unabhängigen manuellen Standards stehen in `ManualSettings`;
gemeinsame Anfangswerte beziehen sich auf die unveränderlichen Produktdefaults.
Die überprüften Windows-Artefakte stehen in `requirements-windows.lock` und
`config/dependency_artifacts.json`; eine Änderung erfordert gemeinsame Aktualisierung.
