# Freiwillige Unterstützung über PayPal

Stand: 21.10.2026. Der Menüpunkt „Buy me a coffee …“ bietet ein freiwilliges,
einmaliges Dankeschön ohne Gegenleistung. Keine Verbindung zur Plattform
Buy Me a Coffee, kein SDK, kein Zahlungsbackend und kein Abonnement.

## Bedienung und Datenfluss

Der Dialog ist außerdem über „Support Diagnose …“ → „Entwickler unterstützen“
erreichbar. Diese Auswahl öffnet direkt denselben lokalen „Buy me a coffee“-
Betragsdialog wie der Menüpunkt, ohne Zwischenseite oder Schiebeanimation.
Das Fenster „Support & Diagnose“ wird davor geschlossen.
Die Auswahl öffnet weder PayPal noch ein anderes externes Ziel; es gibt keinen
zweiten Zahlungsablauf.

Der lokale Dialog bietet 3,50 €, 5 €, 10 €, 15 € und 20 € sowie eine freie Eingabe
von 2,50 bis 50,00 EUR pro Zahlung. Beim erstmaligen Öffnen sind 5 EUR als
unverbindlicher, frei änderbarer Vorschlag vorausgewählt und sichtbar markiert.
Komma und Punkt sind
als Dezimaltrenner erlaubt, maximal zwei Nachkommastellen; Gruppierungszeichen,
Exponenten, negative Werte und Rundung sind ausgeschlossen. Die Obergrenze ist
eine lokale Eingabegrenze, keine Zusage einer PayPal-Zahlungsgrenze. Die Grenzen
gelten für den durch die Anwendung vorbereiteten Zahlungslink; nachträglich
außerhalb der Anwendung geänderte Beträge kontrolliert sie nicht.
Die Untergrenze von 2,50 EUR lässt beim am 17.10.2026 geprüften Inlandsspendentarif
von 2,49 % + 0,35 EUR rechnerisch etwa 2,09 EUR nach Gebühren übrig. Abweichende
Kontotarife, Auslands- und Währungsgebühren können den Nettobetrag ändern; die Anwendung
ermittelt keine kontospezifischen Gebühren und garantiert keinen universellen
Nettoerlös. Quelle und Gebührenstand: [Dependencies](dependencies.md#paypal-als-freiwilliger-externer-zahlungsweg-geprüft-17102026).
Das Eingabefeld weist Buchstaben, Sonderzeichen, mehr als einen Dezimaltrenner,
zusätzliche Nachkommastellen und Beträge oberhalb dieser Grenze bereits beim
Tippen oder Einfügen zurück. Eine ungültige eingefügte Zeichenfolge wird vollständig
abgewiesen und nicht zu einem anderen Betrag gekürzt. Leere, noch unfertige
Eingaben wie `0,` oder Beträge unter dem Mindestbetrag bleiben zum Bearbeiten
möglich; „Weiter zu PayPal“ ist dabei
gesperrt. Die unabhängige Betragsprüfung vor der Browserübergabe bleibt bestehen.

Festbetragsauswahl und eigene Eingabe sind getrennte Zustände: Bei einem festen
Betrag bleibt „Eigener Betrag“ leer und zeigt seinen Platzhalter. Die PayPal-
Übergabe verwendet den markierten Festbetrag. Eine eigene Eingabe hebt diese
Auswahl auf, auch wenn ihr Wert einem Festbetrag entspricht. Ein Klick auf einen
Festbetrag leert die eigene Eingabe. Ungültige oder anschließend gelöschte eigene
Eingaben sperren die Übergabe; es gibt keinen stillen Rückfall auf den vorigen
Festbetrag. Beim erneuten Öffnen innerhalb derselben Programmsitzung bleibt die
aktuelle Auswahl beziehungsweise eigene Eingabe erhalten und wird nicht erneut
durch den 5-EUR-Vorschlag ersetzt.

Die integrierten Hoch-/Runter-Pfeile ändern den Betrag mit `Decimal` um jeweils
0,50 EUR und begrenzen das Ergebnis auf 2,50 bis 50,00 EUR. Die Feldbreite bleibt
unverändert. Ausgangspunkt ist die aktuelle eigene Eingabe oder der ausgewählte
Festbetrag; der Klick erzeugt eine eigene Eingabe und hebt die Festbetragsauswahl
auf. Ist keine Auswahl und kein eigener Betrag vorhanden, beginnt der erste
Aufwärtsklick bei 2,50 EUR. Gedrückthalten wiederholt den Schritt alle 250 ms
(vier Schritte pro Sekunde); Loslassen oder Erreichen der Grenze beendet die
Wiederholung. Nicht ausführbare Schritte an den Grenzen sind deaktiviert und
grau dargestellt. Die Pfeile öffnen keinen Browser und lösen keine Zahlung aus.

`voluntary_support.py` validiert den Betrag mit `Decimal` und baut einen festen,
URL-kodierten HTTPS-Link zu `www.paypal.com/cgi-bin/webscr` mit `cmd=_donations`.
Das ist eine von PayPal noch unterstützte Legacy-Schnittstelle. Die
[offizielle Parameterreferenz](https://developer.paypal.com/api/nvp-soap/paypal-payments-standard/integration-guide/Appx-websitestandard-htmlvariables/?mark=handling_cart)
belegt Betrag, bestätigte Empfänger-E-Mail, Währung und `no_shipping=1`.
Die Empfängeradresse kommt ausschließlich aus `support_paypal_email` im
`config/legal_profile.json`; sie ist nicht vom Zahlenden editierbar. Beim
Öffnen wird dieselbe Adresse angezeigt und verwendet. Die Empfängerzeile zeigt
nur die E-Mail-Adresse. `provider_name` bleibt für die rechtlichen
Anbieterangaben maßgeblich; persönliche Angaben werden nicht zusätzlich in der
technischen Dokumentation wiederholt.

`VoluntarySupportDialog` öffnet PayPal nur nach einem ausdrücklichen Klick auf
„Weiter zu PayPal“. Das Drücken der Eingabetaste startet keine Zahlung und
öffnet keinen Zahlungslink. Die endgültige Prüfung und Bestätigung erfolgen
bei PayPal. Der feste Zweck benennt die Unterstützung ohne Gegenleistung.
Keine Zahlerdaten, Dateien, freien Texte, Installationskennung, Telemetrie,
Rücksprungadresse oder Webhooks werden mitgegeben. Die App erkennt keine
Zahlung und bestätigt keinen Erfolg; eine erfolgreiche Browserübergabe bedeutet
lediglich, dass das Betriebssystem den Link angenommen hat.

Beträge bleiben nur im Dialogspeicher bis zum Programmende; es gibt weder neue
Einstellungsdaten noch eine Schemaänderung. Der Browser kann den Link im Verlauf
speichern. PayPal und gegebenenfalls E-Mail/Buchführung enthalten die tatsächlichen
Zahlungsdaten. Dezente Links öffnen die bestehenden eigenen Rechtstexte offline
unter „Über“; es gibt keine zweite Dokumentansicht im Unterstützungsdialog.
Der ausdrücklich gekennzeichnete PayPal-Datenschutzlink öffnet dessen Website.

Der Dialog bleibt auf 560 × 592 logische Pixel begrenzt und wird bei kleineren
Arbeitsflächen weiter verkleinert. Die normale Fenstergröße wird nach dem nativen
Anzeigen und bei erneutem Öffnen vor der Freigabe der Anzeige wiederhergestellt;
ein maximiertes Hauptfenster vergrößert ihn nicht. In der Normalansicht passt der
Inhalt vollständig. Sichtbare Scrollleisten gibt es nicht; bei sehr wenig Platz
bleibt der Inhalt per Mausrad erreichbar, die Zahlungsaktion bleibt sichtbar.
Beträge brechen bei größeren
Schriften in mehrere Reihen um; die aktuelle Auswahl wird farbig markiert.
Die Rechtstext-Links stehen bei ausreichender Breite mittig im verbleibenden
Platz der letzten Hinweiszeile; bei wenig Platz wechseln sie in eine eigene Zeile.
Kurzhinweise und direkte Links ersetzen die früheren langen Erläuterungen und
dominanten Dokumentbuttons. Grundlage für den leicht zugänglichen Datenschutz:
[Art. 12 DSGVO](https://eur-lex.europa.eu/legal-content/DE/ALL/?uri=celex:32016R0679).

## Rechtliche Einordnung und verbleibende Betreiberaufgaben

Die [Apache-2.0-Projektlizenz](../LICENSE.md) erlaubt auch kommerzielle Nutzung und
Weitergabe. Die hier angebotene freiwillige Unterstützung ist unabhängig von
diesen Lizenzrechten und bleibt ohne Gegenleistung; eine Zahlung ist keine
Voraussetzung für deren Ausübung.
[Nutzungsbedingungen](../legal/terms.md), [Datenschutzinformationen](../legal/privacy.md)
und das zentrale Vertriebsprofil beschreiben die konkrete Funktion. Die gemeinsame
Exportpipeline übernimmt den neuen Abschnitt automatisch in den Installertext;
keine zweite Lizenzkopie oder Zahlung während der Installation hinzufügen.

### Prüfung der Betragsvorauswahl (aktualisiert am 21.10.2026)

Ergebnis der konkreten Gestaltungseinschätzung: Die sichtbare 5-EUR-Vorauswahl
ist unter den nachfolgenden Bedingungen vertretbar; das zusätzliche Risiko wird
als **niedrig** eingeschätzt. Das ist eine begründete Anwendung der geprüften
Quellen auf diesen Ablauf, keine gesetzliche Sondererlaubnis und keine
gerichtliche oder anwaltliche Einzelfallfreigabe.

- [§ 312a Abs. 3 BGB](https://www.gesetze-im-internet.de/bgb/__312a.html)
  untersagt das Herbeiführen von Vereinbarungen über zusätzliche Zahlungen durch
  Voreinstellungen im elektronischen Geschäftsverkehr. Die
  [Kommissionsleitlinien 2021/C 525/01, Abschnitt 10](https://eur-lex.europa.eu/legal-content/DE/TXT/HTML/?uri=CELEX%3A52021XC1229%2804%29)
  erläutern Artikel 22 anhand zusätzlicher Leistungen bei einem Hauptgeschäft.
  Die Vorauswahl einer Zusatzversicherung bei einer Flugbuchung wurde auch vom
  [EuGH, C-112/11](https://curia.europa.eu/site/upload/docs/application/pdf/2012-07/cp120105en.pdf)
  verworfen. Diese Konstellationen sind keine Freigabe für Spendenformulare;
  entscheidend bleibt, ob eine zusätzliche Zahlung ohne ausdrückliche Entscheidung
  zustande kommen soll.
- Hier wird der Unterstützungsdialog gezielt über einen eigenen Menüpunkt
  geöffnet. Es gibt weder einen Kaufabschluss noch einen kostenpflichtigen
  Zusatzposten; Nutzung, Updates und gewöhnlicher Support bleiben unabhängig.
  Für die Zuwendung wird keine Gegenleistung versprochen. Das spricht für eine
  eigenständige unentgeltliche Zuwendung im Sinne von
  [§ 516 BGB](https://www.gesetze-im-internet.de/bgb/__516.html), nicht für ein
  durch Voreinstellung vereinbartes Zusatzentgelt. Allein die Beschriftung
  „Unterstützung“ würde diese Abgrenzung nicht gewährleisten.
- Auch außerhalb eines Zusatzentgelts darf die Gestaltung nicht irreführen
  oder erheblichen Druck ausüben:
  [§ 4a UWG](https://www.gesetze-im-internet.de/uwg_2004/__4a.html),
  [§ 5 UWG](https://www.gesetze-im-internet.de/uwg_2004/__5.html) und die
  [Kommissionsleitlinien 2021/C 526/01, Abschnitt 4.2.7](https://eur-lex.europa.eu/legal-content/EN/ALL/?uri=CELEX%3A52021XC1229%2805%29)
  zu manipulativen Benutzeroberflächen wurden berücksichtigt. Deshalb bleiben
  Vorschlagsbetrag und Auswahl sichtbar, sämtliche Beträge frei änderbar und
  „Vielleicht später“ sowie Schließen ohne Hürde verfügbar. Kein automatisches
  Öffnen, wiederholtes Drängen oder Zurücksetzen einer eigenen Wahl.
- PayPal dokumentiert technisch sowohl
  [vorgegebene als auch frei wählbare Spendenbeträge](https://developer.paypal.com/community/blog/how-to-add-donations-to-your-website-with-paypals-donate-sdk/)
  sowie den optionalen
  [`amount`-Parameter für Donate-Links](https://developer.paypal.com/api/nvp-soap/paypal-payments-standard/integration-guide/Appx-websitestandard-htmlvariables/?mark=handling_cart).
  Das belegt die technische Möglichkeit, keine deutsche Rechtsfreigabe oder
  kontospezifische Empfangsberechtigung. Die App verwendet die Vorauswahl nicht
  als Zahlungseinwilligung: Erst der ausdrückliche Klick auf „Weiter zu PayPal“
  öffnet den Browser, die Zahlung muss anschließend bei PayPal bestätigt werden.

Eine spätere Kopplung an Kauf, Freischaltung, Zusatzfunktionen oder verpflichtende
Zahlungen erfordert eine neue Bewertung. Für eine verbindliche Beurteilung ist
fachkundige Rechtsberatung erforderlich. Die folgenden offenen Betreiberaufgaben
und `release_legal_review` werden durch diese Prüfung nicht erledigt.

### Verbleibende Betreiberaufgaben

- **Kein steuerbegünstigter Spendenempfänger:** Die Zuwendung geht an den
  Entwickler. Keine Spendenbescheinigung oder Abzugsfähigkeit
  zusagen. Grundlage für begünstigte Zuwendungen: [§ 10b EStG](https://www.gesetze-im-internet.de/estg/__10b.html).
  Die Bezeichnung allein macht Einnahmen nicht steuerfrei. Die konkrete
  ertrag-/umsatzsteuerliche Behandlung im Einzelunternehmen fachkundig klären;
  keine automatisierte Aussage über Steuerfreiheit treffen. Risiko bis zur
  individuellen Klärung: **mittel**.
- **PayPal-Kontoeignung:** Aus der Empfängeradresse sind weder deren Bestätigung
  noch Kontoempfang, Kontolimits oder die Eignung für regelmäßige
  entwicklungsbezogene Zuwendungen verifizierbar. Vor öffentlichem Einsatz im
  eigenen Konto prüfen und nötigenfalls mit PayPal klären. Laut
  [PayPal-Bedingungen](https://www.paypal.com/de/legalhub/paypal/useragreement-full)
  sind Geschäftskonten für hauptsächlich empfangene Verkaufs-/Spendenzahlungen
  vorgesehen. Das Privatkonto nicht pauschal als unzulässig oder freigegeben
  darstellen; keine Zahlung als „Freunde und Familie“ anfordern. Risiko einer
  ungeklärten Kontoeignung: **mittel**.
- **Gebühren:** Empfangsgebühren mindern grundsätzlich den eingehenden Betrag;
  die Anwendung schlägt sie nicht auf. Die nach Zahlungsweg geltenden Konditionen
  sind bei PayPal zu prüfen. Zentraler Dienst-/Gebührennachweis:
  [Dependencies](dependencies.md#paypal-als-freiwilliger-externer-zahlungsweg-geprüft-17102026).
- **Datenschutz:** Eigenständige Verarbeitung eingehender Zahlungsdaten durch den
  Anbieter bleibt dessen Verantwortung. Zweckgebundene Abwicklung (Art. 6 Abs. 1
  lit. b), gesetzliche Pflichten (lit. c) und konkrete Rechtsverteidigung (lit. f)
  sind keine pauschale Einwilligung. Maßgeblich: [DSGVO](https://eur-lex.europa.eu/legal-content/DE/TXT/?uri=CELEX:32016R0679).
  Konto-/E-Mail-Zugriff beschränken; Zahlungsdaten nicht als Telemetrie, Werbung
  oder öffentliche Unterstützerliste verwenden. PayPals eigene Zwecke und
  Drittlandübermittlungen stehen in den [PayPal-Hinweisen](https://www.paypal.com/de/legalhub/paypal/privacy-full).
- **Aufbewahrung:** Die in der Datenschutzerklärung beschriebene Fristen-/Löschpraxis
  tatsächlich in Konto, E-Mail und Buchführung umsetzen. Buchungsbelege grundsätzlich
  acht, andere einschlägige Unterlagen sechs oder zehn Jahre ab Jahresende;
  Verlängerungen berücksichtigen. Quellen: [§ 147 AO](https://www.gesetze-im-internet.de/ao_1977/__147.html),
  [§ 257 HGB](https://www.gesetze-im-internet.de/hgb/__257.html).
- **Microsoft Store:** Noch keine Store-Zertifizierung. Vor Einreichung den
  externen PayPal-Weg im Partner Center angeben und die konkrete Zahlungsführung
  nach [Store Policies 10.8.2](https://learn.microsoft.com/en-us/windows/apps/publish/store-policies#108-financial-transactions)
  abnehmen; Microsoft ist kein Veranstalter/Sponsor. Keine Zusatzfunktionen oder
  andere digitalen Gegenleistungen an Zuwendungen knüpfen. Browserweiterleitung
  erst nach Installation; Authentifizierung und Bestätigung erfolgen bei PayPal.

`release_legal_review` bleibt wahrheitsgemäß offen. Technische Prüfungen und diese
Quellenprüfung bestätigen keine rechtlich risikofreie Freigabe. Die genannten
wesentlichen Restfragen benötigen für eine verbindliche Beurteilung fachkundige
Rechts-/Steuerberatung und gegebenenfalls Bestätigung durch PayPal.

## Prüfung

`test_voluntary_support` prüft Betragsvalidierung, URL-Positivliste, Empfänger,
Menüanbindung, unverbindliche 5-EUR-Vorauswahl, getrennte Festbetrags-/Eigenbetrags-
Auswahl, explizite Browserübergabe, Fehlerfälle, kompakte Fenstergröße bei
maximiertem Hauptfenster, Auswahlmarkierung und Verweise auf die vorhandenen
Rechtstexte. `test_legal_documents` prüft insbesondere, dass Installer und Anwendung
dieselben aufgelösten Bedingungen enthalten. Ein echter Zahlungseingang wurde
nicht ausgelöst oder vorgetäuscht. Der kontospezifische Live-Checkout ist zusätzlich
im PayPal-Konto zu prüfen.
