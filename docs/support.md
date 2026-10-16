# Support, Diagnosepakete und vertrauliche Anliegen

## Eine Meldung erstellen

Freiwilliger Support erfolgt über die
[GitHub-Issue-Auswahl](https://github.com/RodeProjects/sacrificial-tower/issues/new/choose).
Die Vorlagen unterscheiden Fehler, Funktionswünsche und sonstige Fragen.
Ein GitHub-Konto und Repositoryzugriff sind erforderlich. Issues sind bereits
aktiviert. Solange das Repository privat ist, können Außenstehende keine Meldung
erstellen. Die Vorlagen unter `.github/ISSUE_TEMPLATE/` müssen auf dem
Standardbranch liegen, bevor GitHub sie anbietet. Diese Dokumentation ändert weder
Sichtbarkeit noch Zugriffsrechte des Repositorys.

Bei einem öffentlichen Repository sind Texte und Anhänge öffentlich. Vertrauliche
Informationen gehören nicht in Issues. Die Datenschutzbestimmungen von GitHub
gelten zusätzlich zur [Datenschutzerklärung der Anwendung](../legal/privacy.md).
Support erfolgt nach verfügbarer Zeit ohne zugesicherte Antwortzeit oder Umsetzung;
zwingende gesetzliche Pflichten bleiben unberührt.

## Ein Diagnosepaket prüfen und freiwillig anhängen

1. In der Anwendung „Support & Diagnose“ öffnen.
2. Problem und Reproduktionsschritte ohne persönliche Daten beschreiben.
3. ZIP erstellen und über „Ordner öffnen“ aufrufen.
4. Die ZIP entpacken und **alle drei enthaltenen Dateien** prüfen.
5. Nur bei Bedarf die geprüfte ZIP manuell an ein Issue anhängen. Screenshots
   gesondert auf Namen, Pfade und vertrauliche Bildschirminhalte prüfen.

Die Anwendung sendet keine Meldung und lädt keine Datei automatisch hoch.
Ein Diagnosepaket ist keine Voraussetzung für eine allgemeine Frage oder einen
Funktionswunsch. Originalprofile, Rohlogs und Modelldateien nicht ungeprüft anhängen.

| ZIP-Datei | Inhalt und Grenzen |
|---|---|
| `problembericht.txt` | Zusammenfassung und Beschreibung unverändert; zusätzlich Programmversion und neu erzeugte Berichtsdaten. Eigene Texte werden bewusst nicht stillschweigend umgeschrieben. |
| `diagnose.log` | Nur ausdrücklich freigegebene technische Felder und Werte, Zustände, Anzahlen und begrenzte Fehlerklassifikation. |
| `manifest.json` | Inhaltsverzeichnis, Exportformat 3, neue Bericht-ID, Zeitpunkt und Hinweise zur Filterung. Keine Übertragung. |

## Technische Datenschutzgrenze

`support_report.py` liest nur begrenzte Endstücke regulärer Protokolldateien
innerhalb des eigenen Logordners. Externe Dateiverweise werden nicht verfolgt.
Pro Journaldatei werden höchstens 8 MiB, pro ergänzendem Fehlerlog 512 KiB gelesen;
überlange Journalzeilen werden verworfen. Der Export behält höchstens die letzten
zwei protokollierten Sitzungen und eine gegebenenfalls bereits begonnene aktuelle
Sitzung. Sitzungskennungen werden durch neutrale Aliase ersetzt.

`support_privacy.py` definiert die erlaubten Felder und den festen technischen
Wortschatz. Unbekannte Felder einschließlich beliebiger Wörterbuchschlüssel werden
verworfen. Frei gewählte Profilnamen werden nicht übernommen; explizite Namensfelder
erhalten die neutrale Bezeichnung „Profil 1“. Beliebige Status-/Fehlermeldungstexte
werden ausgelassen. Verschachtelung und Sammlungen sind begrenzt. Es werden keine
Objekte über `repr` oder `str` als technische Nutzdaten exportiert.

Ergänzende Fehlerlogs liefern nur bekannte Ausnahmeklassen und Zeilennummern.
Dateipfade, Quelltextzeilen, Funktionsnamen und Fehlermeldungstexte werden daraus
nicht übernommen. Betriebssystemangaben sind eingeschränkt; Versionsfelder werden
auf ein begrenztes technisches Format geprüft. Zahlen und Zeitpunkte können
trotzdem einen Vorgang charakterisieren: **Datensparsamkeit ist keine garantierte
Anonymität.** Neue Exportfelder oder Wörter benötigen eine bewusste Datenschutzprüfung.

ZIP-Dateien werden zunächst temporär geschrieben und erst nach vollständiger
Erstellung übernommen. Zieldateien werden exklusiv reserviert, damit parallele
Exporte nichts überschreiben. Bei Fehlern werden temporäre und unvollständige
Dateien entfernt. Schreibziele außerhalb eigener Benutzerdaten und bekannte
Slicer-Verzeichnisse werden abgewiesen. Die Ursprungslogs werden nicht umgeschrieben.

Exportformat 3 betrifft ausschließlich neu erzeugte, freiwillige ZIP-Dateien.
Vorhandene Pakete und persistierte Benutzereinstellungen werden nicht verändert;
es gibt deshalb keine Einstellungs-Schemamigration. Frühere ZIPs vor Veröffentlichung
erneut prüfen oder ein neues Paket erstellen.

## Vertrauliche Anliegen

Datenschutzanfragen, Sicherheitslücken und Hinweise auf versehentlich veröffentlichte
Informationen über die vertrauliche Anbieter-E-Mail melden. Die maßgebliche Adresse
steht zentral in [legal_profile.json](../config/legal_profile.json) und wird in den
Rechtstexten der Anwendung angezeigt. Das ist keine Zusage von regulärem E-Mail-Support.

Für den Betreiber gilt: Berechtigte Meldungen zeitnah prüfen, problematische Inhalte
im eigenen Einflussbereich entfernen und nötigenfalls GitHub einschalten.
Anhänge können über direkte Links auch nach Entfernung des Links erreichbar sein.
Bloßes Schließen eines Issues ist keine Löschung; auch Änderungshistorie, Downloads
und E-Mail-Benachrichtigungen berücksichtigen. Plattformkopien und fremde Kopien
lassen sich nicht pauschal rückwirkend beseitigen.

Heruntergeladene Supportpakete nach Abschluss löschen, soweit kein konkreter
rechtlicher Aufbewahrungs-/Beweissicherungsgrund besteht. Personenbezogene Inhalte
nicht in Tests, Commits oder öffentliche Beispieldateien übernehmen. Speicher- und
Löschkriterien stehen maßgeblich in `support_retention_policy` des Anbieterprofils.
Diese organisatorischen Regeln muss der Betreiber tatsächlich einhalten; sie
werden auf GitHub und im Postfach nicht durch die Anwendung automatisiert.

Die Richtlinie sieht nach Abschluss höchstens 30 Tage für heruntergeladene
Diagnosepakete und vertrauliche E-Mail-Korrespondenz vor. Auch eigene Kopien,
entpackte Dateien und nicht mehr erforderliche personenbezogene
E-Mail-Benachrichtigungen berücksichtigen. Papierkorb und „Gelöschte Elemente“
sind weiterhin eigene Kopien. Bei Abschluss eines Issues und mindestens jährlich
die weitere Erforderlichkeit personenbezogener Inhalte und Anhänge prüfen.
Für konkrete gesetzliche Aufbewahrung oder Rechtsansprüche nur die erforderlichen
Daten gesondert beschränkt aufbewahren und den Grund mindestens jährlich prüfen.

Die Freiwilligkeit betrifft gewöhnliche Hilfestellung. Für Betroffenenanfragen
gelten die gesetzlichen Antwortfristen: grundsätzlich ein Monat, bei zulässiger
Verlängerung mit begründeter Mitteilung innerhalb des ersten Monats. Eine
Issue-Prüfbestätigung oder ein freiwilliger Upload ist weder eine Freistellung
des Betreibers noch eine pauschale Einwilligung in weitere Datenverwendung.

Vor Verarbeitung personenbezogener Supportdaten die konkret geltenden Konto- und
Datenschutzverträge für GitHub und Outlook prüfen, auch bei nicht öffentlichen
Tests: Vertragspartner, Rolle als
Verantwortlicher oder Auftragsverarbeiter, gegebenenfalls Art.-28-Vereinbarung,
Übermittlungsgrundlage und Benachrichtigungs-/Löschmöglichkeiten. Ein privates
Outlook-Postfach besitzt nicht allein durch geschäftliche Nutzung einen
Geschäftskundenvertrag. Die öffentlichen Datenschutzhinweise der Plattformen
ersetzen diese Prüfung nicht. Das Ergebnis einschließlich der konkreten
Übermittlungsgarantien in den Rechtstexten nachführen und unter
`release_legal_review` belegen; bis dahin bleibt dieser Freigabenachweis offen.

## Quellen

Geprüft am 15.10.2026:
[GitHub-Issue-Formulare](https://docs.github.com/en/communities/using-templates-to-encourage-useful-issues-and-pull-requests/configuring-issue-templates-for-your-repository),
[Dateianhänge](https://docs.github.com/en/get-started/writing-on-github/working-with-advanced-formatting/attaching-files),
[Private Informationen entfernen](https://docs.github.com/en/site-policy/content-removal-policies/github-private-information-removal-policy),
[GitHub-Datenschutz](https://docs.github.com/en/site-policy/privacy-policies/github-general-privacy-statement),
[Microsoft-Datenschutz](https://privacy.microsoft.com/de-de/privacystatement),
[DSGVO](https://eur-lex.europa.eu/eli/reg/2016/679/oj).
