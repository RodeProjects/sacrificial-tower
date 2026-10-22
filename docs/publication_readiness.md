# Veröffentlichungsprüfung: Quellcode, Entwicklungsreleases und Microsoft Store

Stand: 22.10.2026. Die Quellcodeveröffentlichung und die technische Umstellung sind
ausdrücklich beauftragt. Eine reguläre Binär-/Storefreigabe ist davon getrennt.
Der aktuelle Nachweis zum öffentlichen Installerübergang steht in der Beschreibung
des [neuesten Releases](https://github.com/RodeProjects/sacrificial-tower/releases/latest).
Die maschinenbezogenen Originalnachweise bleiben im privaten Verwaltungsbereich.

Das Hauptrepository ist seit der geprüften Öffnung öffentlich. Beide tatsächlichen
Entwicklungsreleases 0.9.26 und 0.9.28 besitzen unveränderliche Quellcode-Tags und
Anhänge. Der öffentliche Versionsübergang bestand in privatem Actions-Lauf
`39711833966` unter einem eigenen GitHub-Standardkonto; die Entwicklerinstallation
wurde nicht verwendet. Anonyme Downloads, Signaturen und Hashes sind bestätigt.
Der alte Kanal ist archiviert und seine Actions sind deaktiviert. Haupt- und
Alt-Repository besitzen weiterhin keinen lokalen Runner; die gemeinsame CI bleibt
privat. Die nachfolgenden reinen Dokumentationsstände 0.9.29/0.9.30 sind keine neuen Installer.

## Erreichte Voraussetzungen

- Nur `RodeProjects/project-ci` besitzt `FLO-PC-private`; Haupt- und altes
  Update-Repository besitzen serverseitig keinen Runner. Persönliches Benutzerkonto,
  geschützte Verwaltungsdateien und getrenntes Runner-Standardkonto sind praktisch
  geprüft. Öffentliche Workflows verwenden nur GitHub-Hardware und besitzen keine
  privilegierte Brücke zur privaten CI. Details: [Private CI](private_ci.md).
- Phase 1 wurde mit echter Prüfbranch-Übernahme, ursprünglicher Vollprüfung,
  gehosteter GUI-Pflichtprüfung, tatsächlichem lokalem Buildfallback, Dateiübernahme,
  Signaturprüfung und negativen Sicherheitsfällen vollständig abgenommen.
- Der neue Updatekanal ist die einzige Kanaldefinition. Version 0.9.26 wurde mit
  Installer, signiertem `latest.json` und aufgelösten Rechtstexten im Hauptrepository
  unveränderlich veröffentlicht. Der Publisher bestätigt die wirklich veröffentlichten
  Dateien vor der Öffnung mit Verwaltungszugang. Kein Geheimnis gelangt in Buildjobs.
- Eigener Code, Dokumentation und eigene Assets stehen unter Apache-2.0; NOTICE und
  Dritttexte bleiben erhalten. Benutzerbestätigte Herkunft einschließlich der drei
  zusätzlichen STL-Modelle steht maßgeblich im
  [Asset-Nachweis](../src/cooling_tower/gui/assets/ASSET_LICENSES.md).
- Anbieter-/Kontakt-/Supportangaben sind zentral eingetragen. Das allein noch offene
  `release_legal_review` bleibt wahrheitsgemäß offen. Entwicklungsversionen werden
  sichtbar gekennzeichnet; die bestehende technische Entwicklungsfreigabe gilt
  weiterhin. Daraus folgt keine reguläre Vertriebs- oder Storefreigabe.

## Prüfung der zu veröffentlichenden Inhalte

Die Prüfung am 21.10.2026 umfasste den erreichbaren Bestand bis zum Kanalcommit
`03439c63ce731aae755032b9672c799be4da7c15` einschließlich aller damaligen Refs:
2.387 Dateiobjekte (2.377 Textobjekte, zehn Binärobjekte), 129 Commits und alle
178 verfügbaren Actions-Logarchive. Alle sechs noch vorhandenen Buildartefakte
wurden tatsächlich heruntergeladen und ihr Dateibestand geprüft. Die Installer
sind anhand Größe und SHA-256 bytegleich mit den bereits öffentlichen historischen
Releases. Die zusätzlichen Dateien sind Manifeste, Metadaten und Buildinventare;
keine Schlüssel-, Profil- oder Credentialdateien. Alle elf PR-Beschreibungen sowie
Kommentar-/Reviewinventare wurden einbezogen. Es gab keine zusätzlichen Issues,
Kommentare, Deployments, Umgebungen, Variablen oder Webhooks als Veröffentlichungsfläche.

Mehrere Prüfwege wurden kombiniert:

- Suchmuster für private Schlüssel, verbreitete Zugangsdaten und Credential-URLs
  ergaben keine ungeklärten Treffer. Eine zweite Prüfung erfasste auch literale
  Geheimniszuweisungen ohne bekannte Tokenpräfixe. Ihre drei Kandidaten waren der
  reine Variablenname `UPDATE_MANIFEST_SIGNING_KEY_BASE64`, kein Schlüsselwert.
- Historische Signier-/Provisionierungs-/Publishpfade und ihre Workflowvarianten
  wurden inhaltlich geprüft: private Werte aus Jobumgebung wurden weder als
  Programmressource noch in den konfigurierten Artefaktpfaden gespeichert.
  294 relevante Ausgabevorkommen waren leer oder maskiert; maskierte Basic-Header
  wurden gesondert eingeordnet. Das alte Signiergeheimnis ist entfernt; der neue
  Schlüssel liegt ausschließlich DPAPI-verschlüsselt außerhalb des Repositorys.
- Historische Konfigurationen, entfernte Hilfsskripte und aktuelle Verpackung wurden
  geprüft. Der ehemals versehentlich eingecheckte SSH-Einrichtungshelfer erzeugte
  Schlüssel lokal und enthielt keinen Schlüssel. Persönliche Laufzeitprofile,
  Anmeldedateien und Nutzermodelle werden nicht versioniert.
- Die zehn Binärobjekte sind eigene STL-/PNG-/ICO-/WebP-Assets mit Herkunftsnachweis.
  Die vorhandenen PNG-XMP-Daten enthalten nur Bildtechnik, Bearbeitungssoftware und
  Datumsangaben, keine Kontakt-/Autor-/GPS-/Pfadfelder. Keine unnötige Assetänderung.
- LICENSE, NOTICE, Assetrechte, Rechtstexte, Qt-Quellmaterial und der vorhandene
  Verpackungsnachweis wurden abgeglichen. Öffentlich beabsichtigte Anbieter- und
  Git-Autorenangaben sind von Geheimnissen unterschieden; frühere Lizenzfassungen
  und bereits veröffentlichte Binärdateien werden nicht rückwirkend umgeschrieben.

Die Grenzen bleiben ausdrücklich bestehen: Mustersuche beweist keine Abwesenheit
unbekannter oder verschleierter Geheimnisse. Die Inhalts-/Datenflussprüfung und
Herkunftsnachweise ergänzen sie; dies ist keine vollständige Malwareanalyse
historischer Binärdateien und keine juristische Zertifizierung. Zum Öffnungszeitpunkt
werden der spätere kleine Dokumentations-/Versionsdiff und neu hinzugekommene
Metadaten/Logs nochmals gesondert abgeglichen. Private CI-Logs werden nicht durch die
Öffnung des Hauptrepositorys öffentlich.

## Vor einer regulären Binärveröffentlichung

1. **Auslieferungsrechte belegen:** Die konkreten Qt-/PySide-/Shiboken-Binärdateien
   ihren vollständigen zugehörigen Quellen, Patches, Buildangaben und eingebetteten
   Drittbestandteilen zuordnen. Microsoft-Compiler-/Runtime-Nutzung und erlaubte
   Weitergabe für den tatsächlichen lokalen oder gehosteten Build dokumentieren.
   Maßgeblich: [Dependencies](dependencies.md) und [Veröffentlichung](distribution.md).
2. **Betreiberpraxis prüfen:** GitHub-/Mail-Vertrags- und Datenschutzgrundlagen,
   tatsächliche Löschpraxis, PayPal-Kontoeignung/Checkout und steuerliche Behandlung
   sowie die konkrete CRA-Einordnung einschließlich freiwilliger Unterstützung
   abschließen. Die vorhandenen Texte beweisen keine abgeschlossene Kontoprüfung.
3. **Freigabe dokumentieren:** Erst danach den datierten, belegten Nachweis in
   `config/legal_profile.json` unter `release_legal_review` eintragen. Dies ist
   die interne Freigabesperre des Projekts; ein ausgefülltes Feld ist keine
   behördliche oder juristische Genehmigung. Wesentliche verbleibende Rechtsfragen
   fachkundig verbindlich beurteilen lassen.
4. **Frischen Release bauen und prüfen:** Gepflegten Python-Patchstand verwenden,
   konkrete Werkzeug-/Runtime-Versionen und Inventar archivieren, offizielle
   Actions sowie die Prüfungen des tatsächlich erzeugten Pakets abschließen.
   Die lokale `.venv` verwendet weiterhin Python 3.13.2; das ist keine Vorgabe für
   künftige Releases. Historische Installer bis 0.9.8 entstanden vor der
   Apache-2.0-Umstellung und erhalten dadurch keine neuen beigepackten Lizenztexte.
   Neue Entwicklungsreleases enthalten die aktuellen aufgelösten Texte und Quellen.

`check_release_readiness.py --release` endet gegenwärtig korrekt mit Exitcode 1
wegen `release_legal_review`. `--development-release` endet mit Exitcode 0;
das erlaubt ausschließlich den dokumentierten Entwicklungsreleasepfad und
bestätigt keine Erfüllung sämtlicher Lizenz-/Store-Pflichten.

## Zusätzlich für den Microsoft Store

| Bereich | Noch erforderlich |
|---|---|
| Entwicklerkonto und Produktidentität | Company-Konto für den vorgesehenen Vertrieb als Einzelunternehmer verifizieren, Produktname reservieren und die tatsächliche Paket-/Publisher-Identität aus Partner Center übernehmen. Der Kontostatus ist durch das Repository nicht nachgewiesen. |
| Store-Paket | MSIX-Manifest, Paketressourcen, unterstützte Windows-Versionen, erforderliche Berechtigungen und reproduzierbaren Paketbau einrichten. Im Projekt wurde kein entsprechendes Manifest und kein MSIX-Build gefunden. Alternativ müsste der vorhandene EXE-Weg einschließlich aller betroffenen PE-Dateien die geforderte vertrauenswürdige Code-Signierung erfüllen. |
| Store-Verhalten | Kanal im konkreten Paket auf `microsoft-store` setzen. Installation, Start, Slicer-Erkennung/-Aufrufe, eigene Datenverzeichnisse, Update, Deinstallation und Übergang von Standalone auf einem sauberen Windows-System abnehmen. Der vorbereitete Schalter allein ist kein Paketnachweis. |
| LGPL bei Paketierung | Praktisch nutzbaren Weg für Bibliotheksänderungen und gegebenenfalls erforderliche Installationsinformationen am konkreten Paket nachweisen. Die Hinweise zum Austausch im frei beschreibbaren Standalone-Ordner belegen dies für ein signiertes MSIX nicht. |
| Öffentliche Angaben | Erreichbare Datenschutz-URL, eigene Lizenzangaben, Supportkontakt, Beschreibung, Screenshots, Symbole, Kategorie, Altersfreigabe, Zielmärkte und Prüferhinweise eintragen. Die separate Slicer-Abhängigkeit muss an den Anfang der Beschreibung. Nur tatsächlich unterstützte Plattformen/Sprachen angeben. |
| PayPal und Zertifizierung | Den externen Zahlungsweg in Partner Center angeben und prüfen; weiterhin ohne digitale Gegenleistung. Windows App Certification Kit und anschließende Store-Zertifizierung des fertigen Pakets ausführen. |

Für MSIX/AppX übernimmt Microsoft nach erfolgreicher Zertifizierung die
Store-Signierung; dafür ist kein gekauftes CA-Code-Signing-Zertifikat erforderlich.
Die Manifest-Signatur des bestehenden Updaters ist keine Authenticode-Signatur.

## Öffnung und unmittelbar anschließende Abnahme

Vor der Sichtbarkeitsänderung müssen die ursprünglichen privaten Pflichtprüfungen
und unveränderlichen Releases vorliegen. Serverseitig Runnerzuordnung, Rechte,
Actions-Token, offizielle gepinnte Actions und Ausschluss öffentlicher Dispatch-
Brücken nochmals prüfen. Die CI-Steuerung bleibt privat. Eine Rückkehr auf privat
kann bereits öffentlich gewordene Kopien/Forks nicht zurückholen.

Anonyme Release-URLs eines privaten Repositorys sind absichtlich nicht erreichbar.
Alle vorher möglichen Prüfungen werden daher privat abgeschlossen; die ausdrücklich
beauftragte Öffnung wird nicht dafür vorgezogen. Unmittelbar danach werden ohne
Anmeldung README-Downloadlink, Manifest, Rechtstexte, Release-Anhänge, Signaturen,
Hashes und Quelltag geprüft. Die feste private Operation `update-acceptance.yml`
nimmt den echten veröffentlichten Versionsübergang 0.9.26 → 0.9.28 im getrennten
Standardkonto ab. Details und die präzise Testgrenze stehen unter
[Updatekanal](update_channel.md#abnahme-des-veröffentlichten-versionsübergangs).
Die Entwicklerinstallation und deren Daten werden nicht verwendet.

Nach erfolgreichem öffentlichen Kanaltest wird das alte Update-Repository in
Beschreibung und Projektlink eindeutig als abgelöst gekennzeichnet und archiviert.
Historische Releases bleiben erhalten. Abschließend die Runnertrennung erneut
serverseitig bestätigen. Erst bei Erfolg aller Kriterien gilt die Gesamtaufgabe
als abgeschlossen. Der datierte Abschlussbericht in der neuesten Releasebeschreibung
und die geschützten Originalnachweise dokumentieren das tatsächliche Ergebnis.

## Maßgebliche externe Quellen

Am 21.10.2026 geprüft:

- [GitHub: Risiken selbst gehosteter Runner](https://docs.github.com/en/actions/reference/security/secure-use#hardening-for-self-hosted-runners)
- [GitHub: Folgen einer Sichtbarkeitsänderung](https://docs.github.com/en/repositories/managing-your-repositorys-settings-and-features/managing-repository-settings/setting-repository-visibility)
- [Microsoft: Store Policies](https://learn.microsoft.com/en-us/windows/apps/publish/store-policies),
  Version 7.20, gültig ab 22.10.2026; insbesondere 10.2.4, 10.2.9, 10.5.1,
  10.8.2 und 10.14. Für die spätere Einreichung die dann geltende Fassung prüfen.
- [Microsoft: Entwicklerkonto](https://learn.microsoft.com/en-us/windows/apps/publish/partner-center/open-a-developer-account)
- [Microsoft: Paket- und Signieranforderungen](https://learn.microsoft.com/en-us/windows/apps/publish/publish-your-app/msix/app-package-requirements)
- [EU-Kommission: CRA und Open Source](https://digital-strategy.ec.europa.eu/en/policies/cra-open-source)
- [Python: gepflegte Veröffentlichungen](https://www.python.org/downloads/)

Die bestehenden Lizenzquellen und fachlichen Nachweise bleiben unter
[Dependencies](dependencies.md), [Veröffentlichung](distribution.md) und
[freiwilliger Unterstützung](voluntary_support.md) maßgeblich.
