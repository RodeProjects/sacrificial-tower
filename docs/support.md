# Support, Diagnosepakete und vertrauliche Anliegen

Lebensdauer, Größenbegrenzung und Bereinigung lokaler Hintergrundlogs,
Slicer-Fehlernachweise und Vorschau-Caches stehen unter
[Lokale Daten und Speichergrenzen](local_storage.md). Das begrenzte lokale
Slicer-Fehlerarchiv enthält Rohdaten und gehört nicht automatisch zu den hier
beschriebenen datensparsamen Diagnosepaketen.

## Eine Meldung erstellen

Freiwilliger Support erfolgt über die
[GitHub-Issue-Auswahl](https://github.com/RodeProjects/sacrificial-tower/issues/new/choose).
Die Vorlagen unterscheiden Fehler, Funktionswünsche und sonstige Fragen.
Ihre konfigurierbaren Anzeigenamen sind bereits deutsch: „Fehler melden“,
„Funktion vorschlagen“ und „Sonstige Frage“. GitHubs feste Bedienelemente wie
„Report a security vulnerability“ werden nicht durch diese Vorlagen übersetzt.
Das Repository und seine aktivierten Issues sind öffentlich. Zum Erstellen einer
Meldung ist ein GitHub-Konto erforderlich. Die Vorlagen unter
`.github/ISSUE_TEMPLATE/` liegen auf dem Standardbranch und sind über die
Issue-Auswahl erreichbar.

Texte und Anhänge der Issues sind öffentlich. Vertrauliche
Informationen gehören nicht in Issues. Die Datenschutzbestimmungen von GitHub
gelten zusätzlich zur [Datenschutzerklärung der Anwendung](../legal/privacy.md).
Support erfolgt nach verfügbarer Zeit ohne zugesicherte Antwortzeit oder Umsetzung;
zwingende gesetzliche Pflichten bleiben unberührt.

## Passenden Supportweg auswählen

„Hilfe & Feedback“ startet mit sechs direkt sichtbaren Auswahlkarten unter
„Was möchten Sie tun?“. Links stehen „Fehler melden“, „Frage stellen“ und
„Funktion vorschlagen“, rechts „Bewertung abgeben“, „Entwickler unterstützen“
und „Etwas anderes“. Beide Spalten sind gleich breit. Ein Klick öffnet
direkt den passenden Bereich; „Entwickler unterstützen“ öffnet stattdessen direkt
den bestehenden „Buy me a coffee“-Dialog ohne Seitenwechsel. Ein zusätzlicher „Weiter“-Button entfällt. Die
Auswahl selbst öffnet keinen Browser und erstellt kein Diagnosepaket.

| Anliegen | Zugehöriger Ablauf |
|---|---|
| Fehler melden | Freiwilliges Diagnosepaket erstellen, prüfen und manuell an das Fehlerformular anhängen; „Ohne Diagnosepaket fortfahren“ öffnet dasselbe Formular direkt. |
| Frage stellen | Kurze Hilfe zur Beschreibung und direkter Link zum Fragenformular; kein Diagnosepaket. |
| Funktion vorschlagen | Anwendungsfall und Nutzen beschreiben, danach direkt zum Wunschformular; kein Diagnosepaket. |
| Bewertung abgeben | Lokal angezeigter Platzhalter, solange keine Bewertungsplattformen eingerichtet sind; keine erfundenen oder inaktiven Bewertungslinks. |
| Entwickler unterstützen | Schließt zuerst „Support & Diagnose“ und öffnet danach den bestehenden lokalen „Buy me a coffee“-Betragsdialog; keine Zwischenseite und keine Animation. Dessen Zahlungsablauf bleibt unverändert. |
| Etwas anderes | Kontakt für andere oder vertrauliche Anliegen. Ein Hinweis verweist Fehler, Fragen und Funktionswünsche auf ihre jeweiligen GitHub-Formulare. Die zentrierte, klickbare E-Mail-Adresse mit Briefsymbol öffnet das E-Mail-Programm; es wird nichts automatisch gesendet oder angehängt. |

Die Formularlinks verwenden `issues/new?template=01-bug.yml`, `02-feature.yml`
beziehungsweise `03-question.yml` am konfigurierten Supportziel. Es erfolgt keine
zweite Themenauswahl auf GitHub und keine automatische Übernahme freier Texte.
Die Buttons nennen das konkrete Ziel: „Fehler auf GitHub melden“, „Frage auf
GitHub stellen“ und „Funktion auf GitHub vorschlagen“.
„Zurück“ erhält Auswahl und ein bereits erstelltes Paket. Ein anderer Supportweg
erstellt keine neue ZIP und löscht keine bestehende. Nach dem Schließen startet
der Dialog beim nächsten Öffnen wieder auf der Vorauswahl; ein bereits erstelltes
Diagnosepaket bleibt in der laufenden Sitzung verfügbar. Das gilt auch beim
Schließen mit Escape oder während einer Animation.

Vorwärts und zurück blendet die bisherige Seite zunächst aus und die neue Seite
danach ein: insgesamt 400 ms, je 200 ms pro Phase mit `InOutCubic`, ohne seitliche
Verschiebung oder gleichzeitige Überblendung. Die Vorbereitung behält ihre
Schiebeanimation; beide Varianten verwenden dieselbe Snapshot- und Aufräumlogik. Während
des Übergangs sind weitere Navigationsklicks gesperrt. Nach Größenänderung oder
Schließen werden temporäre Animationsansichten freigegeben; der Dialog bleibt
manuell skalierbar. Jede Seite wird entsprechend ihrem aktuellen Inhalt und dem
verfügbaren Bildschirmplatz bemessen. Die anfängliche obere Fensterkante entspricht
der Position eines anhand der höchsten enthaltenen Seite zentrierten Fensters.
Angezeigt wird trotzdem nur die Höhe des aktuellen Inhalts. Bei Seitenwechseln,
Erfolgsmeldungen und Fehlern bleibt die obere Kante an ihrer Position; das Fenster
wächst oder schrumpft ausschließlich nach unten und behält seine Breite. Auch eine
manuell gewählte Position bleibt dabei erhalten. Reicht der Platz unterhalb der
oberen Kante bis zum Bildschirmrand nicht aus, scrollt der Inhalt.

Der vertrauliche Kontakt ist unter „Etwas anderes“, in den Rechtstexten
und der GitHub-Sicherheitsrichtlinie erreichbar. Der Bewertungsplatzhalter zeigt
fünf kleine Sterne ohne Bewertungsfunktion. Details zum Zahlungsweg stehen unter
[freiwilliger Unterstützung](voluntary_support.md).

## Ein Diagnosepaket prüfen und freiwillig anhängen

1. Im Burgermenü der Anwendung „Hilfe & Feedback“ öffnen.
2. Auf „Fehler melden“ klicken. In Schritt 1 ein freiwilliges
   technisches Diagnosepaket erstellen. Eine
   Zusammenfassung oder Problembeschreibung wird hier nicht abgefragt.
3. In Schritt 2 die ZIP über „Ordner öffnen“ aufrufen.
4. Das erstellte Diagnosepaket als ZIP öffnen und **alle drei enthaltenen Dateien**
   prüfen. Nur entpacken, falls das ZIP-Programm dies zum Lesen verlangt.
5. In Schritt 3 über die GitHub-Schaltfläche das Fehlerformular öffnen und das Anliegen
   direkt im GitHub-Formular beschreiben. Bei Bedarf die geprüfte ZIP in das
   Textfeld ziehen oder dort als Datei anhängen und die Meldung anschließend
   absenden. Screenshots gesondert
   auf Namen, Pfade und vertrauliche Bildschirminhalte prüfen.

Der Dialog erklärt diese Schritte und weist nach dem Erstellen ausdrücklich
darauf hin, dass das Paket noch nicht gesendet wurde. Die Erfolgsmeldung nennt
das Öffnen des Ordners und Prüfen in Schritt 2 als nächsten Schritt; der Dateiname
ist darin fett hervorgehoben. Der Ordnerbutton
wird nach erfolgreicher Erstellung verfügbar; GitHub bleibt auch ohne Paket
erreichbar. Die drei Schritte stehen in einem gemeinsamen Bereich in ihrer
Bearbeitungsreihenfolge: Texte links, zugehörige Buttons rechts. Die kurzen Texte
beschreiben Erstellen, Prüfen und manuelles Anhängen. Der Status erscheint erst
bei einem Erstellversuch. Unter „ZIP prüfen“ bleibt „Nicht garantiert anonym.“
sichtbar; daneben öffnet das Info-Symbol die Details zu ausgeschlossenen Daten,
selbst hinzugefügten Inhalten und dem Lesen der ZIP. Es ist per Maus und Tastatur
bedienbar; seine zugängliche Beschreibung enthält denselben Hinweistext.
Beim Verlassen der Rubrik oder Schließen des Dialogs wird der Hinweis ausgeblendet.
Die öffentliche Sichtbarkeit von Meldungen und Anhängen sowie die Kontoanforderung
bleiben direkt bei der GitHub-Aktion sichtbar. Die vollständigen
[Datenschutzinformationen](../legal/privacy.md) werden dadurch nicht ersetzt.
Diese ergänzende Darstellung orientiert sich am
[Mehrebenen-Ansatz der Transparenzleitlinien, Ziffern 35–37](https://dsb.gv.at/sites/site0344/media/downloads/leitlinien_fuer_transparenz_gemaess_der_verordnung_2016-679.pdf#page=23);
sie ist keine eigenständige vollständige Datenschutzerklärung oder juristische Freigabe.
Die Anfangshöhe richtet
sich beim Öffnen nach dem gesamten aktuellen Inhalt und dem Bildschirmplatz. Nach
der Paketerstellung passt der Dialog seine Höhe für die Erfolgsmeldung erneut an,
behält dabei aber die gewählte Fensterbreite. Bei wenig
Platz scrollt der Inhalt innerhalb des vergrößerbaren Dialogs; die Schließen-Aktion
bleibt erreichbar. Mehr Platz blendet den Scrollbalken automatisch wieder aus.

Die Anwendung sendet keine Meldung und lädt keine Datei automatisch hoch.
Ein Diagnosepaket ist keine Voraussetzung für eine allgemeine Frage oder einen
Funktionswunsch. Originalprofile, Rohlogs und Modelldateien nicht ungeprüft anhängen.

| ZIP-Datei | Inhalt und Grenzen |
|---|---|
| `hinweise.txt` | Programmversion, neue Bericht-ID, Zeitpunkt sowie Anleitung zum Prüfen und manuellen Anhängen. Keine eingegebene Zusammenfassung oder Problembeschreibung. |
| `diagnose.log` | Nur ausdrücklich freigegebene technische Felder und Werte, Zustände, Anzahlen und begrenzte Fehlerklassifikation. |
| `manifest.json` | Inhaltsverzeichnis, Exportformat 4, neue Bericht-ID, Zeitpunkt und Hinweise zur Filterung. `user_text_included: false`; keine Übertragung. |

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

Updateereignisse behalten zusätzlich die geprüfte Zielversion, feste Updatephasen
und verfügbare technische Windows-/HTTP-/Prozessfehlernummern. Freie Fehlertexte,
Versuch-Kennungen und lokale Setup-Pfade werden weiterhin ausgelassen. Die nativen
Dateien unter `logs/updates/` sind lokale Rohlogs und kein automatischer Bestandteil
eines Supportpakets. Ablauf und Grenzen stehen unter
[Update-Diagnose](update_channel.md#update-diagnose).

Der beim nächsten Start angebotene Bericht über einen unerwarteten Abbruch verwendet
beim Kopieren in die Zwischenablage denselben technischen Wortschatz. Die lokale
Detailanzeige und die Ursprungslogs behalten ihre vollständigen Diagnosedaten;
solche Rohansichten vor einer manuellen Weitergabe gesondert prüfen.

ZIP-Dateien werden zunächst temporär geschrieben und erst nach vollständiger
Erstellung übernommen. Zieldateien werden exklusiv reserviert, damit parallele
Exporte nichts überschreiben. Bei Fehlern werden temporäre und unvollständige
Dateien entfernt. Schreibziele außerhalb eigener Benutzerdaten und bekannte
Slicer-Verzeichnisse werden abgewiesen. Die Ursprungslogs werden nicht umgeschrieben.

Exportformat 4 löst Format 3 für neu erzeugte ZIPs ab: `hinweise.txt` ersetzt den
bisherigen `problembericht.txt`; eigene Texte werden nicht mehr erhoben oder
exportiert. Der Manifest-Schlüssel `user_text_stored_verbatim` entfällt zugunsten
von `user_text_included: false`. Die Dateien heißen jetzt
`SacrificialTower_Diagnosepaket_<Zeitpunkt>.zip`; gleichzeitige Exporte behalten
unterschiedliche Dateinamen und Bericht-IDs.
Vorhandene Pakete und persistierte Benutzereinstellungen werden nicht verändert;
es gibt deshalb keine Einstellungs-Schemamigration. Frühere ZIPs, insbesondere deren
unverändert gespeicherte eigene Texte in `problembericht.txt`, vor Veröffentlichung
erneut prüfen oder ein neues Paket erstellen.

## Vertrauliche Anliegen

Datenschutzanfragen, Sicherheitslücken und Hinweise auf versehentlich veröffentlichte
Informationen über die vertrauliche Anbieter-E-Mail melden. Die maßgebliche Adresse
steht zentral in [legal_profile.json](../config/legal_profile.json) und wird in den
Rechtstexten der Anwendung angezeigt. Das ist keine Zusage von regulärem E-Mail-Support.
Die GitHub-Sicherheitsrichtlinie nennt den Kontakt zusätzlich direkt als
E-Mail-Link; ihre Datenschutzverknüpfung verwendet eine vollständige URL zum
Standardbranch, damit GitHubs Darstellung unter `security/policy` sie korrekt auflöst.
Bei einer späteren Änderung der zentralen Adresse den Kontakt in `.github/SECURITY.md`
mit aktualisieren; der Regressionstest prüft beide Angaben auf Übereinstimmung.

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
