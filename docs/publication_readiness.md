# Veröffentlichungsprüfung: GitHub und Microsoft Store

Stand: 21.10.2026. Ausgangspunkt: `main`, Version 0.9.18,
Commit `5abdd0b8051abe2297a963f49d1f8eda022e0a85`. Dies ist eine Bestandsaufnahme,
keine Vertriebsfreigabe. Das Hauptrepository bleibt auf Wunsch des Benutzers
bis zum letzten Veröffentlichungsschritt privat.

## Bereits vorhanden

- Apache-2.0, NOTICE, Lizenzanzeige, Export und Paketprüfungen sind eingerichtet.
  GitHub erkennt die Projektlizenz bereits als Apache License 2.0.
  Einzelheiten und die früheren 107 Tests: [Lizenzprüfung](license_review.md).
- Anbietername, Anschrift, Kontakt, USt-ID, Support-/Löschregeln und Vertriebsmodell
  sind eingetragen. Im Anbieterprofil ist allein `release_legal_review` offen.
- Drittkomponenten, Wheel-Hashes, Qt-Quellarchive und Herkunftshinweise sind
  dokumentiert; das ersetzt noch nicht die unten genannten Auslieferungsnachweise.
- Sicherheitskontakt, Issue-Vorlagen und datensparsame Diagnoseexporte sind vorhanden.
- Der vorbereitete Kanal `microsoft-store` schaltet den eigenen Updater aus.
  Die aktuelle Buildkonfiguration ist weiterhin `standalone`.

## Wichtige zusätzliche Befunde

| Befund | Erforderlicher Abschluss |
|---|---|
| Lokaler Actions-Runner bei künftig öffentlichem Repository | Vor Öffnung eine wirksame technische Trennung von fremden Pull Requests und dem Arbeitsrechner herstellen. Die Fork-Bedingungen in `tests.yml` allein reichen als Sicherheitsgrenze nicht. Sie stehen in einer durch PRs veränderbaren Workflowdatei. Risiko bei ungeschützter öffentlicher Anbindung: **hoch**. |
| Öffentliche Rechtstexte fehlen im geprüften Downloadkanal | Dort liegen derzeit nur README und `latest.json`; das neueste Release enthält nur den Installer. Aufgelöste Datenschutz-/Anbieterinformationen und Lizenzhinweise vor regulärer Auslieferung öffentlich erreichbar machen und verlinken. Der Publish-Helfer übernimmt diese Veröffentlichung derzeit nicht. |
| Zusätzliche Testmodelle: Rechtebestätigung erledigt | Der Benutzer bestätigte am 21.10.2026 Urheberschaft, erforderliche Rechte und Apache-2.0-Freigabe für alle drei unten genannten Dateien; aktuelle Hashes im zentralen Asset-Nachweis ergänzt. |
| Ausgangsstand offiziell erfolgreich geprüft | Für die SHA `5abdd0b8051abe2297a963f49d1f8eda022e0a85` sind die Tests-Läufe `39601457485` und `39605693132` erfolgreich. Der spätere umgestellte Commit benötigt seine eigenen privaten CI-/Installerabnahmen; diese sind noch offen. |
| Entwicklungsversion ist weiterhin fest eingestellt | Vor einem regulären Release `CURRENT_LICENSE_STATUS` im Über-Dialog, den Entwicklungsabschnitt der Nutzungsbedingungen und die öffentlichen Produkttexte konsistent umstellen. Das Ausfüllen des Anbieterprofils allein schaltet diese Texte nicht um. Aktuell ist die Entwicklungskennzeichnung richtig. |

### Zusätzlich bestätigte Testmodelle

Diese Dateien gehören zum Quellrepository; der vorhandene PyInstaller-Build
liefert `input/` nicht als Programmressource aus. Sie sind daher insbesondere
vor der Quellcodeveröffentlichung relevant. Die Zuordnung wurde durch die
ausdrückliche Benutzerbestätigung vom 21.10.2026 ergänzt.

| Datei unter `input/` | SHA-256 |
|---|---|
| `Test-STL Vase (manifold).stl` | `e0c7e3441bcfe5f12f09b1e24d30dc06ce7e751738c4558f9bfd659618202fba` |
| `Test-STL gemischt (manifold).stl` | `f0bb2062ebedd2a832e323b1fd920f72456f26c13ca3d140e03e9e6f128c2891` |
| `Test-STL mehrere Objekte in einer STL.stl` | `0807455bc904d274d76013346396472d287ea93130962d05f097e34bbef8a362` |

Die Dateien wurden laut Git-Verlauf nach der allgemeinen früheren Bestätigung
vom 14.09.2026 aufgenommen. Der bestehende
[Asset-Nachweis](../src/cooling_tower/gui/assets/ASSET_LICENSES.md) ist die maßgebliche
Stelle für die ergänzten Rechte und Prüfsummen. Die gesonderte WebP-Bestätigung ist erledigt.

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
   künftige Releases. Der aktuell öffentliche Installer 0.9.8 entstand vor der
   Apache-2.0-Umstellung und erhält dadurch keine neuen beigepackten Lizenztexte.

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

## Hauptrepository zuletzt öffnen

Unmittelbar vor diesem ausdrücklich beauftragten Schritt:

1. Die Runner-Sicherheitsgrenze wirksam einrichten und die dann geltenden
   GitHub-Actions-/Schutzregeln prüfen. Bis dahin keinen fremden Fork-Code auf dem
   Arbeitsrechner ausführen. Eine mögliche Lösung ist eine getrennte öffentliche
   Prüfung auf GitHub-Hardware und ein davon technisch abgeschotteter privater
   lokaler Prüfpfad; dies erfordert eine gezielte Anpassung der bisherigen CI-Regeln.
2. Den endgültigen Quellstand samt vollständiger zu veröffentlichender Historie,
   alten Issues/PRs, Anhängen, Actions-Logs und Artefakten auf sensible Inhalte und
   fremde Rechte prüfen. Die Sichtbarkeitsänderung macht auch alte Actions-Logs
   öffentlich. Bei veröffentlichten echten Zugangsdaten genügt Löschen allein
   nicht; sie wären zusätzlich zu widerrufen/erneuern.
3. Herkunft der zusätzlichen Testmodelle klären; LICENSE.md und NOTICE erhalten.
4. Öffentliche Download-/Supporttexte auf den tatsächlichen Release und die
   geplante Öffnung abstimmen. Fertige Rechtstexte können vorher im separaten
   öffentlichen Downloadrepository oder auf einer Website bereitstehen; das
   Hauptrepository muss dafür nicht vorzeitig geöffnet werden. Bis zur Öffnung
   einen tatsächlich erreichbaren Supportkontakt, etwa E-Mail, angeben.
5. Erst dann die Sichtbarkeit ändern und die öffentlichen Links kontrollieren.

## Umfang dieser Nachprüfung

Geprüft wurden Rechtstexte/Profil, Herkunftsdokumentation, Git-Dateibestand und
erreichbare Historie, Packaging-/Publishskripte, alle drei Actions-Workflows sowie
GitHub-Sichtbarkeit, aktueller CI-Nachweis und Inhalt des öffentlichen Downloadkanals.
Eine Mustersuche über 2.312 Textobjekte von 2.323 erreichbaren Git-Dateiobjekten
aus 118 Commits ergab keine Treffer für die geprüften Privatschlüssel-,
GitHub-/GitLab-/AWS-/Google-/Slack-/Stripe-Zugangsdaten- und Zugangsdaten-URL-Muster.
Binärdateien und Muster-unbekannte Geheimnisse sind dadurch nicht freigeprüft;
eine vollständige Inhaltsprüfung aller GitHub-Logs/Anhänge wurde nicht durchgeführt.
Die offiziellen Tests wurden nur ausgelesen, nicht erneut gestartet. Kein neues
Installationspaket wurde gebaut oder zertifiziert. Änderungen dieser Prüfung
betreffen ausschließlich die Dokumentation.

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
