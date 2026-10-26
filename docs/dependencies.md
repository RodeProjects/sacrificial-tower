# Abhängigkeiten und Lizenznachweise

Letzte Prüfung aller folgenden Einträge: **14.09.2026**. Maßgeblich für den
Windows-x64-Build mit Python 3.13 (lokale Prüfung: 3.13.2) sind [requirements-windows.lock](../requirements-windows.lock)
und [dependency_artifacts.json](../config/dependency_artifacts.json). Die Hashes
binden die Aussagen an konkrete Wheels. Die Lizenzdateien der tatsächlich
installierten Artefakte wurden zusätzlich zu ihren Paketmetadaten geprüft und
werden beim Build automatisch gesammelt. Unveränderte Einträge nicht bei jedem
Arbeitsauftrag erneut recherchieren; bei Versions-/Lizenz-/Distributionsänderung
erneut prüfen und diesen Nachweis aktualisieren.

Der eigene Quellstand ist seit 21.10.2026 unter Apache-2.0 lizenziert; die offiziellen
Downloads des Anbieters bleiben kostenlos. Umfang, NOTICE und Lizenzquelle stehen
unter [Rechte und Nutzungsmodell](distribution.md#rechte-und-nutzungsmodell).
Der Lizenzwechsel verändert keine der nachfolgend dokumentierten Drittlizenzen.
Die folgenden Aussagen über kommerzielle Nutzungsrechte beschreiben die Rechte an
Drittkomponenten; sie sind kein Verkaufsmodell der Anwendung. Kostenlosigkeit hebt
Drittanbieterpflichten nicht auf. Der Store-Vertriebsweg benötigt eine zusätzliche
LGPL-/Paketierungsprüfung, siehe [Veröffentlichung](distribution.md).

## Laufzeit

| Komponente / geprüfte Version | Lizenz und belastbare Quelle | Proprietär/kommerziell, Pflichten und Kosten |
|---|---|---|
| CPython 3.13.2 | PSF License Agreement und eingebettete Dritttexte; [CPython-Lizenz](https://github.com/python/cpython/blob/v3.13.2/LICENSE) | Zulässig, keine Lizenzgebühr/Umsatzschwelle; vollständige Runtime-Lizenz beilegen, Dritttexte erhalten. |
| PySide6-Essentials / Shiboken6 / Qt 6.11.1 | LGPL-3.0-only gewählt aus Mehrfachlizenz; [Qt-Lizenzmodell](https://doc.qt.io/qt-6/licensing.html), [PySide-Quellen](https://download.qt.io/official_releases/QtForPython/pyside6/PySide6-6.11.1-src/) | Proprietär grundsätzlich möglich bei erfüllter LGPL; dynamischer Austausch, LGPL-/GPL-Texte, korrespondierende Quellen/Buildinformationen und erforderliche Rechte. Keine Zahlung oder Umsatzschwelle bei LGPL-Nutzung. Konkrete Freigabe noch offen, siehe unten. |
| NumPy 2.5.1 | BSD-3-Clause, eingebettete Komponenten 0BSD/MIT/Zlib/CC0 u. a.; [NumPy-Quelle](https://github.com/numpy/numpy), maßgeblich `numpy-2.5.1.dist-info/licenses/` im geprüften Wheel | Zulässig ohne Lizenzkosten/Umsatzschwelle. Gesamten Lizenzbaum beilegen, nicht nur die kurze Projekt-BSD. Wheel enthält zusätzlich OpenBLAS (BSD-3-Clause), LAPACK (BSD-3-Clause-Open-MPI) und GCC-Runtime (GPL-3.0-or-later WITH GCC-exception-3.1). Die Runtime-Ausnahme erlaubt die unabhängige proprietäre Anwendung; vollständige Ausnahme und Texte mitführen. |
| trimesh 4.12.2 | MIT; [Projektlizenz](https://github.com/mikedh/trimesh/blob/main/LICENSE.md), geprüftes Wheel `licenses/LICENSE.md` | Zulässig, Copyright und Lizenz beilegen; keine Gebühren/Umsatzschwelle. Keine optionalen Extras eingeführt. |
| truststore 0.10.4 | MIT; [Projektlizenz](https://github.com/sethmlarson/truststore/blob/main/LICENSE) | Zulässig, Lizenz/Copyright beilegen; keine Gebühren/Umsatzschwelle. Verwendet Windows-Zertifikatsspeicher für TLS. |
| cryptography 49.0.0 | Apache-2.0 OR BSD-3-Clause; [Projektlizenz](https://github.com/pyca/cryptography/blob/main/LICENSE), alle Wheel-Lizenztexte | Zulässig, Lizenz-/Copyright-/gegebenenfalls NOTICE-Texte beilegen; keine Lizenzgebühr/Umsatzschwelle. Gebündelte OpenSSL-/Rust-Komponenten müssen im konkreten Wheel-Nachweis berücksichtigt werden. |
| cffi 2.1.0 | **MIT-0** laut dieser Version, [Projektquelle](https://github.com/python-cffi/cffi), Wheel `licenses/LICENSE` | Zulässig ohne Gebühr/Umsatzschwelle; MIT-0 verlangt keine Attribution, Text wird dennoch mitgesammelt. Historische CFFI-Versionen nicht pauschal gleich behandeln. |
| pycparser 3.0 | BSD-3-Clause; [Projektlizenz](https://github.com/eliben/pycparser/blob/main/LICENSE) | Zulässig, Lizenz/Copyright beilegen; keine Gebühren/Umsatzschwelle. Transitiv erfasst. |

## Build und Tests

| Komponente / geprüfte Version | Lizenzquelle | Kommerzielle Einordnung und Pflichten |
|---|---|---|
| PyInstaller 6.21.0 | GPL-2.0-or-later **mit besonderer Bootloader-/Bundling-Ausnahme**; [offizielle Lizenz](https://pyinstaller.org/en/stable/license.html), Wheel `COPYING.txt` | Nichtfreie/kommerzielle Anwendungen sind durch die Ausnahme ausdrücklich vorgesehen. Keine Gebühr/Umsatzschwelle. Ausnahme und Lizenz mitführen; eigene Änderungen an PyInstaller separat bewerten. |
| pyinstaller-hooks-contrib 2026.6 | [Lizenz](https://github.com/pyinstaller/pyinstaller-hooks-contrib/blob/master/LICENSE) | Build-Hooks GPL-2.0-or-later, ausgelieferte Runtime-Hooks Apache-2.0. Unterschied beibehalten; kein pauschales GPL-Verbot für das gebaute Produkt. Keine Gebühren/Umsatzschwelle. |
| altgraph 0.17.5 | MIT; [Quelle](https://github.com/ronaldoussoren/altgraph), Wheel `LICENSE` | Frei kommerziell; Lizenz/Copyright erhalten. |
| py-spy 0.4.1 (optionale, temporäre Testdiagnose) | MIT; [versionierter Lizenztext](https://github.com/benfred/py-spy/blob/v0.4.1/LICENSE), Wheel `py_spy-0.4.1.dist-info/licenses/LICENSE`; geprüft 2026-10-04 | Keine Laufzeit-/Build-Abhängigkeit der Anwendung und kein Bestandteil des Installers. Nur zum Lesen des Stacks eigener Testprozesse in `.tmp/` verwendet. Kommerzielle Nutzung ohne Gebühren oder Umsatzschwelle; bei einer Weitergabe Lizenz/Copyright und das vollständige Inventar des konkreten Binärartefakts prüfen und erhalten. |
| packaging 26.2 | Apache-2.0 OR BSD-2-Clause; [Lizenz](https://github.com/pypa/packaging/blob/main/LICENSE) | Frei kommerziell; Lizenztexte einschließlich nötiger Hinweise erhalten. |
| pefile 2024.8.26 | MIT; [Lizenz](https://github.com/erocarrera/pefile/blob/master/LICENSE) | Frei kommerziell; Lizenz/Copyright erhalten. |
| pywin32-ctypes 0.2.3 | BSD-3-Clause; [Quelle](https://github.com/enthought/pywin32-ctypes), Wheel `LICENSE.txt` | Frei kommerziell; Lizenz/Copyright erhalten. |
| setuptools 83.0.0 | MIT und permissive vendorte Werkzeuge; [Lizenz](https://github.com/pypa/setuptools/blob/main/LICENSE), Wheel-Lizenzbaum | Frei kommerziell; vendorte Lizenzen nicht weglassen. Buildwerkzeug; keine zusätzliche Testbibliothek eingeführt. |
| Inno Setup 6.7.3 | Eigene permissive Lizenz; [versionierter Text](https://github.com/jrsoftware/issrc/blob/is-6_7_3/license.txt), Kopie unter `legal/licenses/InnoSetup.txt` | Kommerzielle Nutzung laut Lizenz erlaubt. Kauf wird für kommerzielle Nutzer erbeten, ist in diesem Lizenztext keine verpflichtende Zahlung. Keine Umsatzschwelle; Hinweise erhalten. Bei Versionswechsel erneut prüfen. |
| MSVC Build Tools / Windows SDK; lokal MSVC 14.29.30133, SDK 10.0.19041.0 | Proprietäre Microsoft-Entwicklerwerkzeuge; [Build-Tools-2019-Lizenz](https://visualstudio.microsoft.com/license-terms/mlt031519/), Lizenz-/REDIST-Dateien der konkret installierten Version | Keine pauschal unbeschränkte kostenlose Nutzung zusagen. Berechtigung für eigenen Anwendungscode und Runtime-Redistribution vor Freigabe nachweisen; siehe nachfolgenden Abschnitt. Keine Toolchain selbst mitliefern. |

### Microsoft-Toolchain: noch offener Berechtigungsnachweis

Microsoft verlangt für die aktuellen Build Tools grundsätzlich eine gültige
Visual-Studio-Lizenz; eine Ausnahme betrifft das Bauen von Open-Source-Abhängigkeiten.
Diese Ausnahme ist keine pauschale Erlaubnis zur eigenen Entwicklung und zum Testen
dieser Komponenten. Die Umstellung des eigenen C++-Codes auf Apache-2.0 ersetzt
daher weder den Nachweis für die konkret verwendete Toolchain noch die Prüfung
der Runtime-Weitergabe. Das Repository ist seit 22.10.2026 öffentlich; die
Sichtbarkeit ersetzt diesen Berechtigungsnachweis ebenfalls nicht.
Die vorhandene Installation ist kein Nachweis dieser Berechtigung.
[Microsoft-Downloadbedingungen](https://visualstudio.microsoft.com/downloads/),
[Lizenzierungs-Whitepaper, Open Source Dependencies (April 2025)](https://visualstudio.microsoft.com/wp-content/uploads/2025/04/Visual-Studio-Licensing-Whitepaper-April2025.pdf).
Auswirkungen des eigenen Lizenzwechsels am 21.10.2026 anhand dieser Quellen geprüft;
die konkrete Lizenz-/REDIST-Zuordnung bleibt offen.

Für individuelle Entwickler eigener kostenloser oder kostenpflichtiger Apps bietet
Community eine kostenfreie Möglichkeit. Für Organisationen gelten zusätzliche
Grenzen: höchstens fünf Nutzer außerhalb der Enterprise-Kategorie; Microsoft nennt
hier mehr als 250 PCs oder mehr als 1 Mio. US-Dollar Jahresumsatz als Enterprise.
Am Grenzwert und bei verbundenen Unternehmen ist der genaue Lizenztext der
gewählten Version maßgeblich. Bei Wegfall der Berechtigung gibt es keine automatische
Umsatzbeteiligung, sondern es wird eine andere gültige Lizenz oder Toolchain benötigt;
eine kostenpflichtige Umstellung ist hier nicht beauftragt.
[Microsoft: Community-Nutzung](https://visualstudio.microsoft.com/vs/community/),
[Lizenzbedingungen](https://visualstudio.microsoft.com/license-terms/).

Vor Vertrieb im Feld `release_legal_review` die konkret verwendete Edition/Version,
Nutzer-/Organisationsberechtigung und erlaubte Runtime-Weitergabe mit Beleg festhalten.
Das gilt für lokale und CI-Builds. Risiko bis zur Klärung: **mittel**.
Die bestehende MSVC-Toolchain wurde nicht neu eingeführt. Ein alternativer Compiler
würde eine eigene ABI-/Build-/Lizenzprüfung benötigen und wird nicht als bereits
validierter Ersatz ausgegeben.

Lokaler Bestandsnachweis vom 15.10.2026 mit `vswhere`: Visual Studio Community 2022
17.13.3 und Build Tools 2019 16.11.45 sind installiert. Der Anbieter hat die
Tätigkeit als alleiniger Einzelunternehmer bestätigt. Das grenzt die mögliche
Community-Berechtigung ein; es bestätigt noch nicht die Lizenz-/REDIST-Zuordnung
der tatsächlich ausgewählten 2019-Toolchain oder eines späteren Store-Pakets.

Ergänzung vom 21.10.2026 für die private CI: Der tatsächliche offizielle Buildlog
belegt Build Tools 2019, MSVC 14.29.30133 und Windows SDK 10.0.19041.0. `vswhere`
bestätigt zusätzlich Community 2022 17.13.35828.75, jedoch ohne eigenen
C++-Toolset. Der konkrete [2019-Lizenztext](https://visualstudio.microsoft.com/wp-content/uploads/2019/03/VS_2019_DiagnosticBuildTools_ENU.1033.docx)
erlaubt Entwicklung/Test nur zusammen mit Visual Studio Community, Professional
oder Enterprise und beschreibt das Kompilieren/Bauen/Prüfen auf eigenen
Buildgeräten. Dies ist keine allgemeine Lizenzfreiheit der Build Tools.
Die bestätigte Einzelunternehmertätigkeit und vorhandene Community-Edition
sind die dokumentierte Grundlage; eine pauschale abgeschlossene
Toolchain-/Runtime-Vertriebsprüfung wird daraus nicht behauptet. Keine neue
Toolchain und kein kostenpflichtiges SDK wurden eingeführt. Die datierte
Gesamtzuordnung und konkrete Weitergabeprüfung bleiben Teil von
`release_legal_review`, insbesondere für den späteren Store-Vertrieb.

Für die permissiven Python-Buildwerkzeuge sind keine Lizenzzahlungen oder
Umsatzschwellen vorgesehen. Die Standardsuite verwendet `unittest` und QtTest aus
Essentials. Git und GitHub Actions sind Entwicklungswerkzeuge, keine eingebauten
Programmbibliotheken. CI-Dienstkontingente sind von der Softwarelizenz getrennt:
keine kostenpflichtigen Konten, Abonnements oder Nutzungserweiterungen wurden
gebucht. Bei Überschreiten kostenloser Dienstkontingente lokale Builds verwenden
oder vor kostenpflichtiger Nutzung eine eigene Entscheidung treffen.

## Tatsächlicher Qt-Lieferumfang und Quellmaterial

Die Anwendung importiert QtCore, QtGui, QtWidgets und QtSvgWidgets; QtNetwork,
QtSvg und QtOpenGL dürfen als dynamische Abhängigkeiten mitkommen. Die genaue Positivliste
für DLLs und Plattform-/Bild-/TLS-Plugins ist ausschließlich in
`scripts/distribution_compliance.py` definiert. QtVirtualKeyboard, QtPdf,
QtQuick/Qml und die nicht benötigte Software-OpenGL-DLL werden entfernt. Damit
wird auch der zuvor im lokalen Alt-Build enthaltene VirtualKeyboard-Lieferumfang
nicht weitergeführt. Ein unbekanntes Qt-Modul benötigt eine erneute Prüfung.

QtSvgWidgets gehört zum bereits erfassten Qt-SVG-Modul und zeichnet die
anwendungseigenen Ladeanimationen nativ. Die Erweiterung wurde am 25.10.2026
gegen die [offizielle Qt-SVG-Lizenzangabe](https://doc.qt.io/qt-6/qtsvg-index.html#licenses-and-attributions)
geprüft: weiterhin LGPLv3 ohne Lizenzgebühr oder Umsatzschwelle, mit denselben
Austausch-, Hinweis- und Quellbereitstellungspflichten. Das bereits fixierte
Qt-SVG-Quellarchiv umfasst auch den Widget-Teil. Es wird kein QtQuick/Qml ergänzt.

Die Qt-Wheel-Metadaten enthalten allein keinen vollständigen LGPL-Nachweis; die
vorhandene kommerzielle Referenzdatei im Wheel ist keine erworbene kommerzielle
Lizenz. Deshalb liegen die gewählten LGPL-/GPL-Texte zusätzlich unter `legal/licenses/Qt`.
`config/qt_sources.json` fixiert die offiziellen Qt-Base-/SVG-/PySide-Quellarchive
6.11.1 einschließlich Prüfsummen. `prepare_qt_sources.py` sammelt deren Lizenz-
und Attributionstexte. Archive und Texte werden mit dem Paket ausgeliefert.
[Qt-Quellen](https://download.qt.io/official_releases/qt/6.11/6.11.1/submodules/),
[Qt-Drittkomponenten](https://doc.qt.io/qt-6/licenses-used-in-qt.html).

Der Build verwirft die geerbten DLL-Suchpfade anderer Programme. Jede Qt-DLL muss
aus dem fixierten PySide-Wheel stammen; `legal/binary-origins.json` protokolliert
alle Binärquellen relativ zu Umgebung, Python, Windows oder eigenem Quellbaum.
Damit werden beispielsweise fremde Qt-/ICU-/OpenSSL-Dateien aus einer anderen
Werkzeuginstallation nicht versehentlich übernommen.

Das Build-Inventar ist ein Datei-/Dependency-Nachweis, **kein vollständiges SPDX-
oder CycloneDX-SBOM und kein Lizenzfreigabezertifikat**. Besonders die vollständige
Zuordnung statisch eingebetteter Qt-, OpenSSL-, NumPy- und Compiler-Bestandteile
muss zur konkreten Distribution bestätigt werden. Der offene Eintrag
`release_legal_review` erfasst diese Prüfung. Bis dahin blockiert der reguläre
Publish-Einstieg. Details unter [Kostenlose Veröffentlichung](distribution.md).

## Slicer, Dienste und eigene Inhalte

Slicer werden ausschließlich als separat installierte externe Programme
angesprochen und nicht mitgeliefert. Profile werden gelesen und in eigenen
Arbeitsordnern isoliert verarbeitet. Das Kopieren von Profilen in exportierte
Projekte kann deren eigene Rechte berühren; Benutzer müssen passende Rechte an
ihren Eingaben besitzen. Eine externe Prozessschnittstelle ist keine pauschale
Freigabe für jede Form der Bündelung oder jeden Drittinhalt. Vor einer späteren
Mitlieferung eines Slicers ist dessen konkrete Version/Lizenz gesondert zu prüfen.
Produktnamen bezeichnen Kompatibilität, keine Partnerschaft.

GitHub dient dem bestehenden öffentlichen Updatekanal. Es gibt keinen neu
eingeführten kostenpflichtigen API-Dienst; Verbindungsdaten und Abschaltmöglichkeit
sind in den [Datenschutzinformationen](../legal/privacy.md) beschrieben.
Logo, Icons und Test-STL haben einen [eigenen Herkunftsnachweis](../src/cooling_tower/gui/assets/ASSET_LICENSES.md).
Windows-Systemfonts werden verwendet, keine neue Schriftdatei wird mitgeliefert.

### PayPal als freiwilliger externer Zahlungsweg (geprüft 17.10.2026)

Kein SDK und keine neue Bibliothek: Der Unterstützungsdialog öffnet ausschließlich
einen HTTPS-Link zu PayPal Payments Standard im externen Browser. Keine PayPal-
oder Buy-Me-a-Coffee-Logos, Skripte oder fremden Assets werden übernommen; das
Kaffeetassen-SVG ist eine eigene geometrische Liniengrafik. „Buy me a coffee“
bezeichnet hier den Menüpunkt, keine Anbindung an die gleichnamige Plattform.

Maßgeblich sind die [PayPal-Nutzungsbedingungen](https://www.paypal.com/de/legalhub/paypal/useragreement-full),
[Datenschutzhinweise](https://www.paypal.com/de/legalhub/paypal/privacy-full) und
[Transaktionsgebühren](https://www.paypal.com/de/business/paypal-business-fees).
Keine zusätzliche Softwarelizenz, Attribution, Monatsgebühr oder Umsatzbeteiligung
für diesen Link eingeführt; **Zahlungsempfang ist grundsätzlich gebührenpflichtig**.
Standard für Inlandsspenden am Prüftag: 2,49 % + 0,35 EUR; internationale Zahlungen,
Währungswechsel und andere Zahlungswege können abweichen. Keine Gemeinnützigkeit
oder Berechtigung für Sondertarife angenommen. Diese zahlungsabhängigen Gebühren
sind Bestandteil des ausdrücklich beauftragten PayPal-Zahlungswegs.
Kontoeignung und steuerliche Behandlung sind gesonderte Betreiberpflichten:
[Umsetzung und Nachweise](voluntary_support.md).

Python-Patchpflege: Am Prüftag nennt die [offizielle Downloadübersicht](https://www.python.org/downloads/)
3.13.15 als aktuellen 3.13-Stand. Die lokale Projektumgebung 3.13.2 wurde für die
Tests unverändert verwendet. CI bleibt auf der gepflegten Reihe 3.13; der alte
lokale Patch wird ausdrücklich nicht für künftige Releases vorgeschrieben.
