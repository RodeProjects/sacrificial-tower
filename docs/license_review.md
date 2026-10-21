# Nachprüfung der Apache-2.0-Umstellung

Stand: 21.10.2026. Geprüft ist der lokale Quellstand einschließlich der noch
nicht veröffentlichten Lizenzumstellung. Dieser Nachweis dokumentiert konkrete
Text-, Quellstands- und Paketprüfungen. Er ersetzt weder die rechtliche
Gesamtfreigabe noch die Zertifizierung eines tatsächlich erzeugten Store-Pakets.

## Ergebnisse und behobene Lücke

| Bereich | Ergebnis und Nachweis |
|---|---|
| Lizenzoriginal | LICENSE.md einschließlich Anhang erneut vollständig mit dem offiziellen Apache-Text abgeglichen; nur Leerraum normalisiert. Ein Regressionstest fixiert den SHA-256 dieses normalisierten Originaltexts. |
| Lizenzumfang | NOTICE benennt eigenen Code, Dokumentation, Konfigurationen, Buildskripte, Tests und eigene Assets. Drittkomponenten behalten ihre Lizenzen. Die bisherige kommerzielle Weitergabebeschränkung ist aus den aktuellen Rechtstexten, Anzeigen und Projektregeln entfernt. |
| Hinweise und Bedingungen | Lizenzkopie, Änderungskennzeichnung und einschlägige Herkunftshinweise sind beschrieben. NOTICE fügt keine Bedingungen hinzu. Die ergänzenden Nutzungsbedingungen beschränken die Apache-2.0-Rechte nicht. |
| Beiträge | Der untersuchte Commitverlauf weist Melandru und RodeProjects als Autoren aus. Für künftig übernommene fremde Beiträge gilt die dokumentierte Prüfung der Rechte und Apache-2.0-Einreichung; das ursprüngliche Copyright begründet kein Eigentum an fremden Beiträgen. |
| Eigene Assets | Alle sieben im Asset-Nachweis erfassten Datei-Prüfsummen stimmen. Eine Prüfsumme belegt Dateigleichheit, nicht Urheberschaft. Der Benutzer hat am 21.10.2026 zusätzlich ausdrücklich bestätigt, tower_gen_finished.webp selbst erstellt zu haben und unter Apache-2.0 einschließlich Änderung und kommerzieller Weitergabe freizugeben. Damit ist die zunächst offene WebP-Herkunftsfrage geklärt. |
| Anzeige und Export | App, Installertext und öffentliche Kopien enthalten den vollständigen Lizenztext und NOTICE jeweils einmal. Die originale LICENSE.md und NOTICE werden zusätzlich separat mitgeliefert. |
| Tatsächliches Staging | prepare_legal_material mit den vorhandenen gepinnten Wheels und Qt-Quellarchiven erfolgreich ausgeführt. LICENSE.md, NOTICE und aufgelöste Texte stimmen mit dem aktuellen Quellstand überein. Dies ist noch kein Nachweis vollständiger Qt-Quell-/Binärkorrespondenz. |
| Paketprüfung | Eine Lücke wurde nachgestellt: Alte Nutzungsbedingungen konnten bei aktuellen LICENSE-/NOTICE-Dateien akzeptiert werden, wenn ihre öffentlichen Exporte zu den alten Vorlagen passten. Jetzt werden auch Vorlagen, Austauschhinweise und Anbieterprofil mit dem Quellstand verglichen. Positive und negative Pakettests sichern das ab. |
| Git-Historie | Begrenzte Suche in allen vorhandenen Git-Referenzen nach verbreiteten GitHub-Token-/Privatschlüsselmustern und verdächtigen Schlüsseldateinamen. Der einzige Inhaltstreffer war eine erkennbare Token-Testzeichenfolge in test_support_report.py. Das ersetzt keine vollständige Geheimnis- oder Rechteprüfung. |

Der ausführbare Installer wurde bei dieser Nachprüfung nicht neu gebaut. Bereits
veröffentlichte Pakete erhalten durch Änderungen am Quellstand keine neue Lizenz.
Vor einer neuen Auslieferung sind Build und Prüfungen des konkreten Pakets erforderlich.

## Testumfang

107 unterschiedliche Tests erfolgreich:

- test_legal_documents: 13 Tests einschließlich vollständigem Originaltext,
  gültigem Paket und fehlenden, veralteten bzw. widersprüchlichen Pakettexten.
- test_project_contracts: 11 Tests.
- test_distribution_and_paths: 8 Tests einschließlich deaktiviertem eigenem
  Updater im vorbereiteten Store-Kanal.
- test_latest_gui_requirements: 47 Tests.
- test_voluntary_support: 28 Tests.

Drei Datei-/Einstellungstests waren durch Einschränkungen der Windows-Sandbox
blockiert und wurden gezielt mit isolierten temporären Projektdaten im normalen
Benutzerkontext erfolgreich nachgeprüft. Die produktive Dateilogik wurde deshalb
nicht verändert. Export, Bibliotheks-/Quell-Staging, Asset-Prüfsummen und
git diff --check wurden zusätzlich geprüft.

## Vor der Veröffentlichung noch nachzuweisen

- **GitHub:** Vor tatsächlicher Öffnung den dann vollständigen ausgehenden Stand
  einschließlich Historie und neuer Beiträge auf Geheimnisse und Rechte prüfen.
  LICENSE.md und NOTICE müssen mit veröffentlicht werden. Die Sichtbarkeit des
  Repositorys wird gesondert beauftragt.
- **Store-Paket und LGPL:** MSIX, Paketidentität, sauberer Installations-/Updatepfad,
  konkrete Qt-Quell-/Binärkorrespondenz und ein praktisch nutzbarer Weg für
  Bibliotheksänderungen einschließlich nötiger Installationsinformationen sind
  noch nicht am Store-Paket abgenommen. Das bloße Beilegen passender Archivnamen
  oder die Apache-Lizenz des eigenen Codes genügt dafür nicht.
- **Microsoft-Toolchain:** Die dokumentierte Zuordnung der tatsächlich verwendeten
  Compiler-/Runtime-Lizenzen bleibt offen; siehe [Dependencies](dependencies.md).
- **Anbieterfreigabe:** Datenschutzpraxis, ergänzende Rechtstexte und die konkrete
  CRA-Einordnung bleiben im bestehenden release_legal_review nachzuweisen.
  Dieses Feld bleibt wahrheitsgemäß offen; keine Store-Freigabe daraus ableiten.

## Offizielle Veröffentlichungsbedingungen

GitHub nennt eine unveränderte Lizenzdatei im Repository-Root und einen passenden
README-Hinweis als geeignete Grundlage für Lizenzangaben und Erkennung. Die
aktuelle Aufteilung zwischen LICENSE.md, NOTICE und Projektinformationen entspricht
diesem Aufbau. [GitHub: Repository-Lizenzierung](https://docs.github.com/en/repositories/managing-your-repositorys-settings-and-features/customizing-your-repository/licensing-a-repository)

Microsofts App Developer Agreement 8.10 behandelt FOSS ausdrücklich in Ziffer 4 c.
Die Verantwortung für Lizenzpflichten und erforderliche Vertriebsrechte bleibt beim
Anbieter. Nach Ziffer 4 i sind eigene Lizenzbedingungen bzw. deren Link für die
Store-Produktinformationen bereitzustellen; ohne eigene Angaben greifen die
Standardbedingungen. Apache-2.0 ersetzt die separaten LGPL-Pflichten nicht.
[Microsoft: App Developer Agreement](https://cdn-dynmedia-1.microsoft.com/is/content/microsoftcorp/microsoft/store/documents/legal/ada/fy26/MS.Store.ADAv8.10.EN.US.pdf)

Für den als Einzelunternehmer vorgesehenen Vertrieb ist ein Company-Konto zu
verwenden und die Geschäfts-/Kontoverifikation abzuschließen. Die Kontaktadresse
im Programm ist kein Nachweis einer bereits abgeschlossenen Kontoprüfung.
[Microsoft: Kontotyp und Einrichtung](https://learn.microsoft.com/en-us/windows/apps/publish/partner-center/open-a-developer-account)

Die geprüften Store Policies 7.20 gelten ab 22.10.2026 und sind daher für den
geplanten späteren Release relevant. Die Beschreibung muss die Abhängigkeit von
einem separat installierten Slicer bereits zu Beginn offenlegen (10.2.4).
Den externen PayPal-Weg nach 10.8.2 im Partner Center angeben und im konkreten
Store-Ablauf prüfen; Unterstützung bleibt ohne digitale Gegenleistung.
Metadaten, Altersfreigabe und Zertifizierung sind noch auszuführen. Vor Einreichung
die dann aktuellen Regeln prüfen.
[Microsoft: Store Policies](https://learn.microsoft.com/en-us/windows/apps/publish/store-policies)

Die LGPL verlangt die konkrete Erfüllung ihrer Weitergabe- und Änderungsrechte.
Die vorhandenen Quell-/Austauschhinweise sind eine technische Grundlage und keine
pauschale Bestätigung der Austauschbarkeit eines signierten MSIX-Pakets.
[Qt: LGPL-Pflichten](https://www.qt.io/development/open-source-lgpl-obligations)

Lizenzoriginal und Hinweise zur Verwendung:
[Apache-2.0](https://www.apache.org/licenses/LICENSE-2.0.txt),
[Apache-Lizenz-FAQ](https://www.apache.org/foundation/license-faq.html#Apply-My-Software).
Die allgemeine Veröffentlichungsanleitung bleibt unter
[Veröffentlichung](distribution.md), offene Anbieterangaben unter
[Checkliste](missing_data.md) maßgeblich. Wesentliche offene Rechtsfragen sind vor
regulärer Veröffentlichung fachkundig verbindlich zu beurteilen.
