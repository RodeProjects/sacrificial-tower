# Qt-Quellmaterial und Bibliotheksaustausch

Diese Distribution verwendet dynamisch geladene Qt-/PySide-/Shiboken-Bibliotheken.
Im Unterordner `sources/` liegen die unveränderten Upstream-Archive für Qt Base,
Qt SVG und PySide/ Shiboken 6.11.1 sowie `qt_sources.json` mit Downloadquellen und
SHA-256. Die Qt-Base-Archive enthalten auch die darin eingebetteten Drittquellen.
Unter `licenses/Qt-source-notices/` liegen zusätzlich Herkunfts- und Lizenzdateien
aus diesen Archiven. Diese Referenzsammlung umfasst auch Quellteile, die nicht
im Laufzeitpaket eingebaut sind; der tatsächliche DLL-Lieferumfang steht im
Build-Inventar. Die einzelne Lizenz gilt jeweils für ihren bezeichneten Inhalt.

Die Anwendung modifiziert diese Bibliotheken nicht. Das Paket wird aus den
offiziellen Windows-Wheels der Python-Projekte zusammengestellt. Die zugehörigen
Wheelnamen und Prüfsummen stehen in `dependency-artifacts.json`. Die Anwendung
selbst benötigt keinen Qt-Quellbuild. Für eigene Bibliotheksänderungen gelten die
im jeweiligen Archiv enthaltenen Bauanleitungen, Konfigurationsdateien und
Lizenzhinweise sowie die offiziellen Anleitungen:

- Qt für Windows: https://doc.qt.io/qt-6/windows-building.html
- PySide/Shiboken: https://doc.qt.io/qtforpython-6/building_from_source/index.html

Ein Ersatz muss Windows x64, CPython 3.13 und die ABI der verwendeten Qt-/PySide-
Version berücksichtigen. Bei beendetem Programm zunächst den Programmordner
sichern, dann kompatible DLLs und Python-Erweiterungen unter `_internal/PySide6`
und `_internal/shiboken6` austauschen. Das Programm erzwingt beim Laden keine
Prüfsummen dieser Bibliotheken. Der Integritätscheck des Updaters betrifft das
heruntergeladene Installationspaket; eine Neuinstallation kann eigene Änderungen
ersetzen. Automatische Updateprüfungen lassen sich vor dem Start mit
`COOLING_TOWER_DISABLE_UPDATE_CHECK=1` abschalten.

Ein Versionsetikett allein beweist keine vollständige Binär-/Quellzuordnung.
Vor einer Vertriebsfreigabe sind etwaige Upstream-Wheel-Patches, Buildwerkzeuge,
Konfigurationen und eingebettete Drittkomponenten anhand der konkreten Artefakte
zu prüfen und gegebenenfalls zu ergänzen. Dieser Stand dokumentiert die
vorbereitete Quellbereitstellung; er behauptet keinen bitidentischen Qt-Neubau.
