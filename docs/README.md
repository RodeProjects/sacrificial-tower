# Projektdokumentation

Sacrificial Tower analysiert lokale G-Code-/STL-Daten und erzeugt einen
druckzeitabhängigen Hilfskörper. Einstieg und Startbefehle stehen im
[Repository-README](../README.md). Diese Übersicht ist der zentrale Wegweiser;
bei Änderungen zuerst das zuständige Thema lesen.

| Thema | Maßgebliches Dokument |
|---|---|
| Komponenten, Verantwortlichkeiten, Datenfluss und Erweiterung | [Architektur](architecture.md) |
| Installation, Tests, Build, gezielte Testauswahl | [Entwicklung](development.md) |
| Abhängigkeiten, Versionen, Lizenzquellen und Pflichten | [Dependencies](dependencies.md) |
| Proprietäre Distribution, Rechtstexte, Freigaben | [Kommerzieller Vertrieb](commercial_release.md) |
| Fehlende Anbieter-/Vertriebsangaben mit Fundstellen | [Platzhaltercheckliste](missing_data.md) |
| G-Code-/STL-Prüfung, Profile, Preslice und Cache | [Quellenablauf](source_workflow.md) |
| Slicer-Erkennung und neue Adapter | [Erkennungsmodule](slicer_detection_modules.md) |
| Prozessisolation, QProcess und Abbruch | [Slicer-Prozesse](slicer_qprocess_compatibility.md) |
| Einstellungen, Schema, Migrationen und Downgrade | [Persistenz](settings_migrations.md) |
| Python-/C++-Analyse, Parität und Fallback | [Native Analyse](native_analysis.md) |
| Signierte Programmaktualisierungen und Veröffentlichung | [Update-Kanal](update_channel.md) |
| Installation und Datenbereinigung | [Deinstallation](uninstallation.md) |

## Nachweise und historische Einordnung

- [Umsetzung der Projektprüfung September 2026](implementation_audit_2026_09.md)
- [Historische Entwicklungsphasen](history/development_phases.md): archivierter
  früherer README-Stand; keine aktuelle Bedienungsanleitung.
- [Referenzstand 0.6.5](reference_baseline_0_6_5.md): Vergleichsbasis, nicht aktuelle Version.
- [UI-Abnahmekriterien](ui_overarbeitung_abnahmekriterien.md): ursprünglicher
  Anforderungskatalog; aktuelle Umsetzung und Tests haben Vorrang.

Anbieterangaben werden nur in `config/legal_profile.json`, aktuelle
Produktstandardwerte nur in `config/default_settings.json` gepflegt.
Die überprüften Windows-Artefakte stehen in `requirements-windows.lock` und
`config/dependency_artifacts.json`; eine Änderung erfordert gemeinsame Aktualisierung.
