# Kostenlose Veröffentlichung und rechtliche Voraussetzungen

Stand: 17.10.2026. Sacrificial Tower wird kostenlos angeboten. Vorgesehen sind
der Microsoft Store und öffentlich einsehbarer Quellcode auf GitHub. Das
Quellcode-Repository bleibt bis zu einer ausdrücklichen Veröffentlichung privat.
Eine Versionsnummer oder ausgefüllte Checkliste ist keine Freigabe oder
Store-Zertifizierung.

## Rechte und Nutzungsmodell

Die [Projektlizenz](../LICENSE.md) ist maßgeblich für den eigenen Code, eigene
Dokumentation und eigene Assets. Sie erlaubt Nutzung auch im Gewerbe, Klonen,
Forks, Änderungen und kostenlose Weitergabe unter ihren Bedingungen.
Kommerzielle Weiterverbreitung einschließlich abgeleiteter Fassungen ist
untersagt. Copyright und ursprüngliche Entwicklerhinweise bleiben erhalten;
Bearbeiter dürfen eigene Hinweise ergänzen. Eigene Ergebnisse wie Kühltürme
dürfen kommerziell genutzt und verkauft werden, soweit Rechte an Eingaben bestehen.
Die Lizenz gewährt Rechte unmittelbar an jeden rechtmäßigen Empfänger und ohne
zeitliche Befristung unter ihren Bedingungen. Eine spätere Lizenzänderung wirkt
nicht rückwirkend. Freiwillige Zuwendungen ohne Software-Gegenleistung und
gesonderte Beratung, Schulung oder Installationshilfe sind nach der genauen
Abgrenzung in `LICENSE.md` zulässig; sie dürfen keine verdeckte Softwarebezahlung sein.
Der Menüpunkt „Buy me a coffee …“ setzt genau diese gegenleistungsfreie
Unterstützung um. Zahlungsweg, Datenschutz, PayPal-Kontovoraussetzungen,
Gebühren und steuerliche Prüfungen stehen unter [Freiwillige Unterstützung](voluntary_support.md).

Bei Beiträgen Dritter sicherstellen, dass die Einreichenden die erforderlichen
Rechte besitzen und ihre übernommenen Beiträge unter der Projektlizenz stehen.
Ihr eigenes Urheberrecht bleibt erhalten. Das Copyright des ursprünglichen
Entwicklers begründet kein Alleineigentum an späteren fremden Beiträgen.

Das Modell ist „Source Available“ und keine Open-Source-Lizenz im Sinne der
[Open Source Definition](https://opensource.org/osd). Unabhängige Drittkomponenten
behalten ihre eigenen Rechte und Lizenzbedingungen; siehe [Dependencies](dependencies.md).
Die Rechte an eigenen Grafiken und Testmodellen sind im
[Asset-Nachweis](../src/cooling_tower/gui/assets/ASSET_LICENSES.md) dokumentiert.

## Anbieter, Datenschutz und Support

Rechtlicher Anbieter ist der Einzelunternehmer Wolfgang Florian Rode.
„RodeProjects“ ist eine Entwicklerkennung, keine eigenständige Firmierung.
Name, Anschrift, erreichbare Kontakt-E-Mail und USt-ID stehen ausschließlich im
[Anbieterprofil](../config/legal_profile.json). Die Steuernummer wird nicht
veröffentlicht; die vorhandene USt-ID wird für die einschlägige Kennzeichnung
verwendet. Keine zusätzlichen Register- oder Rechtsformdaten werden erfunden.
Grundlage: [§ 5 DDG](https://www.gesetze-im-internet.de/ddg/__5.html).

Die Anwendung zeigt [Nutzungsbedingungen](../legal/terms.md),
[Datenschutzinformationen](../legal/privacy.md) und
[Drittanbieter-Lizenzen](../legal/third_party.md) offline an. Vorlagen werden aus
dem Anbieterprofil aufgelöst; interne Freigaben gehören nicht in die Nutzungsoberfläche.

Freiwilliger gewöhnlicher Support läuft über GitHub Issues. Vertrauliche Rechts-,
Datenschutz- und Sicherheitsanliegen bleiben per E-Mail möglich.
[Support und Diagnosepakete](support.md) erklärt Sichtbarkeit, Filterung, Betreiberpflichten
und Löschung. GitHub regelt seine Plattformverarbeitung; die eigene Nutzung
übermittelter Daten bleibt eigenständig zu beurteilen.
Für geschäftlich genutzte GitHub-/Microsoft-Konten sind passende Vertragsbedingungen,
gegebenenfalls Auftragsverarbeitung, internationale Übermittlung und tatsächliche
Benachrichtigungs-/Löschpraxis vor entsprechender personenbezogener Verarbeitung
zu prüfen. Das gilt auch bei nicht öffentlichen Tests.
Die kostenlose Abgabe beseitigt diese Pflichten nicht.

## LGPL und konkreter Lieferumfang

Qt/PySide bleiben dynamisch austauschbar. LGPL/GPL-Texte, vollständige Wheel-Lizenzen,
versionsgebundene Qt-/PySide-Quellarchive mit Hashes sowie
[Quellbuild- und Austauschhinweise](../legal/source_build_notes.md) werden mitgeliefert.
Nicht benötigte GPL-only-/QML-/Quick-/PDF-Module sind ausgeschlossen;
`scripts/distribution_compliance.py` prüft den tatsächlichen Lieferumfang.

Vor regulärer Veröffentlichung sind Quell-/Binärkorrespondenz einschließlich
Upstream-Patches, Buildkonfiguration und eingebetteter Bestandteile zu belegen.
Gleich benannte Quellarchive allein genügen nicht. Das gilt unabhängig vom Preis.
Der Store-Vertrieb benötigt einen konkreten Nachweis, dass Bibliotheksaustausch und
erforderliche Installationsinformationen trotz Signierung/Paketierung möglich bleiben.
[Qt: LGPL-Pflichten](https://www.qt.io/development/open-source-lgpl-obligations).

Die vorhandenen Microsoft-Buildwerkzeuge benötigen weiterhin eine gültige
Nutzungs- und Runtime-Redistributionsberechtigung. Kostenlosigkeit und öffentlich
einsehbarer Code sind allein kein Berechtigungsnachweis.
Details und die kostenfreie Community-Option stehen in [Dependencies](dependencies.md).

## Microsoft Store

Der Kanal `microsoft-store` ist im Programm vorbereitet und deaktiviert den eigenen
GitHub-Updater. Ein fertiges MSIX-Paket, Store-Eintrag und Store-Abnahme sind damit
noch nicht vorhanden. Der eigenständige Inno-Setup-Installer ist derzeit ohne
öffentlich vertrauenswürdige Authenticode-Signatur; die signierte Update-Manifestdatei
ersetzt keine Store-Code-Signierung.

Für einen möglichst kostenfreien Store-Weg ist MSIX zu prüfen: Microsoft bietet
dafür Store-Signierung und Hosting. Vor Abgabe müssen Paketidentität,
Herausgeberkonto, zulässiger Lieferumfang und LGPL-Austausch konkret geprüft sein.
[Microsoft: Einreichung und Paketformate](https://learn.microsoft.com/en-us/windows/apps/publish/faq/submit-your-app).

Eine öffentlich erreichbare, vollständig aufgelöste Datenschutzerklärung und die
eigene Projektlizenz müssen passend zur Einreichung bereitgestellt werden;
nicht ausgefüllte Markdown-Vorlagen sind keine fertigen Store-Rechtstexte.
Microsofts eigene Plattformverarbeitung wird dadurch nicht zur Anwendungstelemetrie.

Mit `python scripts/export_legal_documents.py` entstehen unter `build/legal-public/`
vollständig aufgelöste Markdown-Texte und ein UTF-8-Installertext. Das Skript
veröffentlicht nichts. Die Buildpipeline erzeugt dieselben Dokumente zusätzlich
unter `legal/published` im Anwendungspaket. Der eigenständige Installer zeigt
Nutzungsbedingungen einschließlich Projektlizenz vor der interaktiven Installation
zur Zustimmung an. „Zustimmen und weiter“ wird bei interaktiver Installation erst
nach Erreichen des Textendes freigeschaltet; der anschließende Klick gilt als
ausdrückliche Zustimmung. Eine zusätzliche Auswahl per Radiobutton entfällt.
Das Erreichen des Endes ist kein Nachweis, dass ein Nutzer den Inhalt tatsächlich
gelesen hat.
Die Datenschutzinformationen werden getrennt bereitgestellt;
eine Lizenzzustimmung ist keine pauschale datenschutzrechtliche Einwilligung.

Vor einem öffentlichen Download müssen die aufgelösten Texte erreichbar sein,
insbesondere bevor die eigenständige Fassung erstmals den Updatekanal aufruft.
Bei der Store-Einreichung eigene Lizenz und Datenschutzhinweise im Partner Center
angeben; bei fehlender eigener Lizenz greifen Microsofts Standardbedingungen.
Die Nutzungsrechte müssen mindestens die anwendbaren Microsoft Usage Rules erfüllen.
Eine bloße Anzeige nach der Installation ersetzt keine erforderliche Einbeziehung
vor Vertragsschluss. Bei inhaltlich geänderten Bedingungen nicht auf eine
unbeaufsichtigte Programmaktualisierung als Zustimmung vertrauen; bereits erteilte
Rechte bleiben nach ihrer bisherigen Lizenz erhalten.
[§ 305 BGB](https://www.gesetze-im-internet.de/bgb/__305.html),
[Microsoft App Developer Agreement, Ziffer 5 i](https://cdn-dynmedia-1.microsoft.com/is/content/microsoftcorp/microsoft/store/documents/legal/ada/fy26/MS.Store.ADAv8.10.EN.US.pdf).

## Sicherheits- und Freigabenachweise

Die Bereitstellung im Rahmen eines Einzelunternehmens ist trotz Preis null auf
anwendbare Produktsicherheitsregeln zu prüfen. Die Vertriebsbeschränkung ist keine
FOSS-Lizenz; eine FOSS-Ausnahme vom Cyber Resilience Act wird nicht angenommen.
Sein Begriff der Marktbereitstellung umfasst im Rahmen wirtschaftlicher Tätigkeit
auch kostenlose Abgabe. Meldepflichten gelten ab 11.09.2026, wesentliche weitere
Pflichten ab 11.12.2027; die konkrete Anwendbarkeit und ein geeigneter Prozess für
Sicherheitsmeldungen, Bewertung und Behebung sind zu klären.
[EU-Kommission: CRA](https://digital-strategy.ec.europa.eu/en/policies/cra-summary),
[Umsetzung](https://digital-strategy.ec.europa.eu/en/policies/cyber-resilience-act).

Die [Checkliste](missing_data.md) hält tatsächliche offene Angaben fest.
`release_legal_review` erst mit Datum und belastbaren Nachweisen zu Rechtstexten,
Datenschutzkonten, Toolchain, LGPL und Sicherheitsregeln ausfüllen. Eine individuelle
Lizenz ist kein gerichtlich bestätigter Vertrag; wesentliche verbleibende
Unsicherheiten fachkundig prüfen lassen.

## Veröffentlichen und prüfen

1. Anbieterprofil und zugehörige Rechtstexte vollständig und wahrheitsgemäß halten.
2. Relevante Tests, aktuellen Python-Patchstand und frischen Build prüfen;
   Quellen, Lizenzen, Binärherkunft und Inventar archivieren.
3. Reguläre kostenlose Veröffentlichung mit
   `python scripts/check_release_readiness.py --release` prüfen.
4. Bei einem ausdrücklich beauftragten Entwicklungsrelease gilt
   `scripts/publish_update.ps1 -DevelopmentRelease`; offene Nachweise bleiben sichtbar
   dokumentiert. Vollständige technische Lieferumfangspflichten gelten weiterhin.
5. Für reguläre kostenlose Standalone-Releases `scripts/publish_update.ps1` verwenden.
   Im Workflow heißt diese Veröffentlichungsart `free`.
   Versions-, Push-, CI-, Signatur- und Installerregeln bleiben verbindlich.

Details zur Veröffentlichung und zum öffentlichen Updatekanal:
[Update-Kanal](update_channel.md). Dieser Text veröffentlicht kein Repository,
keinen Store-Eintrag und kein Programm.
