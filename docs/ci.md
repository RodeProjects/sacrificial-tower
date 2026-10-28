# Prüfung und Veröffentlichung

Die öffentlichen GitHub-Actions prüfen externe Beiträge auf GitHub-Hardware.
Eigene Änderungen durchlaufen zusätzlich eine getrennt verwaltete offizielle
Prüfung des konkreten Commits. Nur erfolgreiche Pflichtprüfungen erlauben die
Übernahme desselben Stands nach `main`.

Tests und Builds erhalten keine persönlichen Verwaltungs- oder Signierzugänge.
Die Freigabe bindet Quellcommit, Basis, Prüflogik und ursprüngliche Laufergebnisse.
Änderungen an diesen Daten erfordern eine neue Prüfung. Eine unveränderte,
bestätigte Vollprüfung wird bei der Veröffentlichung wiederverwendet.

## Entwicklung und Release

Lokale Entwicklung und gezielte Tests beschreibt [Entwicklung](development.md).
[Programmaktualisierungen](update_channel.md) erläutert Installer, Signaturen und
Release-Anhänge. Der Publisher erhält seine externe Verwaltungsintegration über
`-RunnerToolsRoot` oder `SACRIFICIAL_CI_TOOLS_ROOT`.

Maschinenspezifische Konfiguration, Konten, Betriebspfade und Wartungsanweisungen
werden in der getrennten privaten CI-Verwaltung gepflegt.
