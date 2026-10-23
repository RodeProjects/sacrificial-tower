# Datenschutzinformationen

Stand: 23. Oktober 2026.

## Verantwortlicher und Kontakt

Verantwortlich für die vom Anbieter verarbeiteten personenbezogenen Daten:
{{provider_name}}, {{provider_postal_address}}.
E-Mail für vertrauliche Datenschutzanfragen: {{provider_email}}.
Die Entwicklerkennung {{provider_brand}} ist keine eigene juristische Person.

## Lokale Verarbeitung und Speicherung

G-Code, STL, Slicerprofile, Einstellungen, Vorschauen und Berechnungen werden auf
dem verwendeten Rechner verarbeitet. Die Anwendung lädt Modelle und Profile nicht
zum Anbieter hoch und verwendet keinen Analyse-, Werbe- oder Telemetriedienst.
Ausschließlich lokale Daten kann der Anbieter nicht einsehen.

Benutzerdaten liegen standardmäßig unter
`%LOCALAPPDATA%/RodeProjects/SacrificialTower/<Instanz>/`. Ausgaben können in einen
selbst gewählten zulässigen Ordner geschrieben werden. Lokale Protokolle können
Fehlermeldungen und persönliche Angaben aus Dateipfaden oder Profilnamen enthalten;
sie werden nicht automatisch versendet. Einstellungen, Ausgaben und exportierte
Diagnosepakete bleiben lokal bis zur Löschung durch den Nutzer gespeichert.
Das technische Diagnosejournal wird größenabhängig begrenzt und rotiert;
andere Fehlerprotokolle können bis zur Nutzerlöschung bestehen bleiben.
Nach fehlgeschlagenen, abgebrochenen oder ins Zeitlimit gelaufenen
Sliceraufrufen kann die Anwendung zusätzlich lokale Fehlernachweise mit
Modell-/Projektkopien, temporären Profilkopien, Dateipfaden und Prozessausgaben
sichern. Diese Rohdaten gehören nicht automatisch zu den exportierbaren
Diagnosepaketen und werden nicht automatisch übertragen. Die Ablage hält
höchstens zehn Fälle, insgesamt 128 MiB und höchstens 32 MiB je Fall.
Ältere Fälle werden nach 14 Tagen beim nächsten Programmstart oder weiteren
Sicherungsvorgang bereinigt; Größen- und Anzahlgrenzen können früher zur
Löschung führen. Zu große Dateien können ausgelassen werden. Vor einer
gesonderten manuellen Weitergabe sind die Rohdaten auf vertrauliche Inhalte
zu prüfen.
Eine automatische Löschung sämtlicher lokaler Daten nach einer festen Zeit
findet nicht statt.

## Verbindungen für Programmaktualisierungen

Die gebaute eigenständige Windows-Fassung prüft beim Start den öffentlichen
GitHub-Updatekanal. Beteiligte GitHub-/Netzdienste erhalten technisch insbesondere
IP-Adresse, Zeitpunkt und angefragte Ressource sowie die feste Kennung
„SacrificialTower-Updater“. Modelle, Profile, Lizenzschlüssel oder eine
Benutzerkennung werden nicht mitgesendet. Nach der Nutzeraktion „Aktualisieren“
wird der Installer von GitHub heruntergeladen. Der Anbieter erhält darüber keine
individuelle Nutzungsstatistik der Anwendung.

Die Abrufe dienen aktuellen und sicheren Programmfassungen. Soweit der Anbieter
hierbei personenbezogene Daten verarbeitet, ist sein berechtigtes Interesse an
sicherer Softwarebereitstellung die Grundlage (Art. 6 Abs. 1 lit. f DSGVO).
Vor dem Start lässt sich die Prüfung mit
`COOLING_TOWER_DISABLE_UPDATE_CHECK=1` unterbinden. Python-Entwicklungsstarts und der
vorbereitete Microsoft-Store-Kanal aktivieren den eigenen Updater standardmäßig
nicht. Für spätere Store-Downloads, Updates und Konten verarbeitet Microsoft
Daten nach eigenen Bedingungen.

## Freiwillige Unterstützung und PayPal

Das Öffnen des Menüpunkts „Buy me a coffee …“, die Betragsauswahl und die Anzeige
der eigenen Rechtstexte erfolgen lokal. Der Betrag wird nur für den aktuellen
Dialog im Arbeitsspeicher gehalten und nicht in Einstellungen, Protokollen oder
Diagnosepaketen gespeichert. Die Anwendung erhebt keine Kontodaten, Passwörter,
Kartennummern oder Zahlungsbestätigungen und ordnet Zahlungen keiner Installation
oder Nutzungskennung zu.

Erst nach „Weiter zu PayPal“ wird die externe HTTPS-Seite von PayPal im
Standardbrowser aufgerufen. Der Link enthält die Empfängeradresse
{{support_paypal_email}}, den gewählten Betrag in EUR, einen festen Zahlungszweck
und technische Angaben für die Zahlungsseite (Sprache, Zeichensatz und Verzicht
auf die Anforderung einer Lieferadresse). Er enthält keine eigenen Namen oder
Kontaktdaten des Zahlenden, Modelle, Slicerprofile, Dateipfade oder Diagnosen.
Der Zahlungslink kann im Browserverlauf verbleiben; dessen Speicherung und
Löschung richten sich nach dem verwendeten Browser.

Beim Aufruf erhält PayPal technisch unter anderem IP-Adresse, Zeitpunkt,
Zahlungslink und Browser-/Geräteinformationen. Anmeldung, Cookies und eine
anschließende Zahlung unterliegen den eigenen PayPal-Hinweisen. PayPal kann je
nach gewähltem Zahlungsweg Konto-, Kontakt-, Zahlungs- und weitere erforderliche
Prüfdaten erheben. Schon der gesonderte Link „PayPal-Datenschutz“ öffnet die
PayPal-Website und übermittelt die üblichen Verbindungsdaten, jedoch keinen
ausgewählten Betrag. Es werden keine PayPal-Skripte, Bilder oder Tracker in die
Anwendung eingebettet. Allein das Öffnen des lokalen Dialogs kontaktiert PayPal nicht.

Bei einer Zahlung erhält der Anbieter von PayPal insbesondere Betrag, Währung,
Zeitpunkt, Transaktionskennung und Zahlungsstatus sowie je nach Zahlungsweg und
Kontoeinstellungen Name, E-Mail-Adresse und weitere von PayPal bereitgestellte
Kontaktdaten des Zahlenden. Diese Daten sind nicht anonym. Sie werden im
PayPal-Konto und gegebenenfalls in Zahlungsbenachrichtigungen des verwendeten
Outlook-Postfachs sowie erforderlichen Buchführungsunterlagen verarbeitet,
jedoch nicht in die Anwendung zurückübertragen.

Der Anbieter verarbeitet die notwendigen Angaben für die von Ihnen veranlasste
Zuwendung und zugehörige Rückabwicklung (Art. 6 Abs. 1 lit. b DSGVO), für
gesetzliche Buchführungs- und Aufbewahrungspflichten (Art. 6 Abs. 1 lit. c DSGVO,
insbesondere § 147 AO und, soweit anwendbar, § 257 HGB) sowie im erforderlichen
Einzelfall zur Klärung von Unregelmäßigkeiten und Durchsetzung oder Abwehr von
Ansprüchen (Art. 6 Abs. 1 lit. f DSGVO; berechtigtes Interesse an ordnungsgemäßer
Abwicklung und Rechtsverteidigung). Es erfolgt keine Verwendung für Werbung,
öffentliche Unterstützerlisten oder Nutzungsprofile.

Empfänger sind PayPal, die am gewählten Zahlungsweg beteiligten Zahlungsdienste
und Banken sowie, soweit tatsächlich erforderlich, Microsoft für E-Mail,
gesetzlich zuständige Behörden und zur Verschwiegenheit verpflichtete steuerliche
oder rechtliche Berater. PayPal handelt für seine Zahlungsdienste als eigener
Verantwortlicher. Für Deutschland ist dies PayPal (Europe) S.à r.l. et Cie, S.C.A.;
Kontaktdaten und internationale Empfänger nennt PayPal in seinen Hinweisen.
PayPal verarbeitet Daten auch außerhalb der EU/des EWR und nennt hierfür unter
anderem bindende Unternehmensregeln, Angemessenheitsbeschlüsse und
Standardvertragsklauseln. Die konkrete Grundlage richtet sich nach der jeweiligen
Übermittlung; Informationen und Bezugsmöglichkeiten zu Garantien sind bei PayPal
und für eigene Übermittlungen beim Anbieter erhältlich.

Der Anbieter bewahrt erforderliche Buchungsbelege grundsätzlich acht Jahre ab
Ende des Kalenderjahres ihrer Entstehung auf, soweit die einschlägigen Vorschriften
anwendbar sind. Für andere aufbewahrungspflichtige Unterlagen gelten je nach Art
sechs oder zehn Jahre. Gesetzliche Verlängerungen, etwa wegen laufender
Steuerverfahren, bleiben maßgeblich. Nicht erforderliche Zusatzkopien und
begleitende Korrespondenz werden nach Abschluss des Vorgangs innerhalb von
30 Tagen gelöscht, sofern keine Aufbewahrungspflicht oder konkrete
Rechtsverteidigung entgegensteht. Solange ein solcher Grund besteht, wird die
Nutzung auf diesen Zweck beschränkt und der Fortbestand mindestens jährlich
geprüft. Nach Wegfall des Grundes werden die Daten im eigenen Einflussbereich
gelöscht. PayPal und Microsoft haben zusätzlich eigene Speicherpflichten und
-fristen. Diese Aufgaben sind vom Anbieter zu erfüllen; die Anwendung erledigt
keine Löschungen im PayPal-Konto, Postfach oder in Buchführungsunterlagen.

Die Unterstützung ist freiwillig; ohne sie bleibt die Anwendung voll nutzbar.
Die für den gewählten Zahlungsweg erforderlichen Angaben werden bei PayPal
benötigt; ohne sie kann eine Zahlung unmöglich sein. Der Browseraufruf und die
Lizenzzustimmung sind keine pauschale Einwilligung in weitere Verarbeitungen.
Die unten beschriebenen Datenschutzrechte gelten auch für die eigene Verarbeitung
der Zahlungsdaten durch den Anbieter.

PayPal-Datenschutzhinweise: https://www.paypal.com/de/legalhub/paypal/privacy-full

## Diagnosepakete und freiwillige Veröffentlichung

Diagnosepakete entstehen nur auf Nutzeraktion lokal. Sie enthalten eine begrenzte
technische Diagnose, ein Inhaltsverzeichnis und eine Anleitung mit Programmversion,
Bericht-ID und Erstellungszeitpunkt. Zusammenfassung und Problembeschreibung werden
im Dialog nicht erhoben und nicht in neu erstellten Paketen gespeichert. Nutzer
beschreiben ihr Anliegen direkt im GitHub-Formular. Die Anwendung überträgt Pakete
nicht automatisch. Ältere Pakete können eigene Texte unverändert in
`problembericht.txt` enthalten; diese vor einer Weitergabe ebenfalls prüfen.
Die technische Diagnose lässt frei gewählte Namen, Pfade,
Profilinhalte, beliebige Fehlermeldungstexte und unbekannte Felder weg oder ersetzt
sie durch neutrale Angaben. Originalmodelle, Profile, Konfigurationen und Rohlogs
werden nicht beigefügt. Zustände, Anzahlen, Zeitpunkte und Versionen können trotzdem
Rückschlüsse auf einen Vorgang erlauben. Das Paket ist datensparsam gestaltet,
aber nicht garantiert anonym.

Vor Weitergabe müssen Nutzer sämtliche Dateien prüfen. Für Screenshots und andere
selbst hinzugefügte Anhänge gibt es keine automatische Bereinigung.
Bitte keine persönlichen, vertraulichen oder fremden geschützten Informationen
veröffentlichen. Sicherheitslücken und Datenschutzanfragen gehören an die
vertrauliche Kontaktadresse.
Insbesondere Gesundheitsdaten, Ausweisdaten, Zugangsdaten und personenbezogene
Angaben über andere Personen werden für gewöhnliche Fehlermeldungen nicht
benötigt. Versehentlich veröffentlichte Angaben bitte über die vertrauliche
Kontaktadresse melden, ohne sie in einer weiteren öffentlichen Meldung zu kopieren.

## GitHub Issues und vertrauliche Kontaktaufnahme

Die Themenauswahl im Supportdialog erfolgt lokal. Ein Browser wird erst durch
einen ausdrücklichen Klick auf die entsprechende Aktion geöffnet. Die Anwendung
erstellt oder versendet keine GitHub-Meldung und keinen Anhang automatisch.
Unter „Etwas anderes“ öffnet ein Klick auf die angezeigte E-Mail-Adresse das
lokale E-Mail-Programm mit der Anbieteradresse. Erst dort können Sie eine Nachricht
verfassen und selbst versenden; Diagnosepakete werden nicht automatisch angehängt.
Für Bewertungen werden derzeit nur
lokale Hinweise angezeigt; es wird kein Bewertungsdienst aufgerufen.

Freiwilliger Support erfolgt über {{support_url}}. Zum Erstellen einer Meldung
ist ein GitHub-Konto erforderlich. Das Repository und seine Issues sind öffentlich.
Benutzername, Beiträge, Antworten und Anhänge sind grundsätzlich öffentlich
zugänglich; Dateien können über separate Links
erreichbar bleiben.

Der Anbieter verarbeitet Beiträge, GitHub-Benutzernamen, freiwillige Anhänge und
gegebenenfalls per E-Mail übermittelte Kontakt-/Inhaltsdaten:

- Freiwillige Unterstützung, Fehleranalyse und nachvollziehbare Lösungsdokumentation
  erfolgen auf Grundlage berechtigter Interessen an einem funktionsfähigen und
  sicheren Programm sowie der Bearbeitung von Anfragen (Art. 6 Abs. 1 lit. f DSGVO).
- Datenschutzanfragen werden zur Erfüllung gesetzlicher Pflichten bearbeitet
  (Art. 6 Abs. 1 lit. c in Verbindung mit Art. 12 bis 22 DSGVO).
- Soweit eine Anfrage zur Erfüllung einer tatsächlich bestehenden individuellen
  Vereinbarung erforderlich ist, gilt Art. 6 Abs. 1 lit. b DSGVO.
- Eine im Einzelfall notwendige Beweissicherung oder Rechtsverteidigung beruht auf
  dem berechtigten Interesse an der Durchsetzung oder Abwehr konkreter Ansprüche
  (Art. 6 Abs. 1 lit. f DSGVO); betroffene Daten werden dafür gesondert beschränkt.

Angaben sind freiwillig; ohne erforderliche technische Informationen kann eine
Bearbeitung unmöglich sein. Werbung oder Verkauf persönlicher Daten sind kein
Bestandteil dieses Ablaufs.
Die freiwillige Veröffentlichung oder Übersendung ist keine Einwilligung in eine
beliebige weitere Verwendung und kein Verzicht auf Datenschutzrechte.

Speicherung und Löschung: {{support_retention_policy}}
Eine vollständige Entfernung bereits öffentlich kopierter Inhalte kann nicht
zugesagt werden. Berechtigte Löschanliegen werden im eigenen Einflussbereich
bearbeitet; erforderlichenfalls wird zusätzlich die Entfernung durch GitHub beantragt.

## Dienstanbieter und internationale Verarbeitung

Empfänger von Daten sind der Anbieter und die für den gewählten Kontaktweg
eingesetzten Dienste. Bei öffentlichen Issues kommen Leser der öffentlich
zugänglichen Beiträge und Anhänge hinzu. Beim Aufrufen der GitHub-Seiten gelten
zusätzlich die dortigen Regeln für Konten, Cookies und Website-Nutzung.

GitHub betreibt Konten, Issues, Anhänge und den Updatekanal. Seine Datenschutzhinweise
nennen GitHub, Inc. und GitHub B.V. als Verantwortliche für die dort beschriebenen
eigenen Verarbeitungen. Bei organisationsgebundener Nutzung kann GitHub daneben
als Auftragsverarbeiter tätig sein; maßgeblich sind die tatsächlich geltenden
Kontoverträge. GitHub ist deshalb nicht pauschal für jede Verarbeitung allein
verantwortlich. Die eigene Verarbeitung von Supportdaten bleibt Verantwortung
des Anbieters.

Für das angegebene Outlook-Postfach werden Microsoft-Dienste eingesetzt.
Microsoft benennt die jeweils verantwortlichen Unternehmen und seine eigenen
Verarbeitungszwecke in den verlinkten Datenschutzhinweisen. Die eigene
Verarbeitung eingegangener Anfragen bleibt Verantwortung des Anbieters.

GitHub und Microsoft können Daten insbesondere in den USA und weiteren Ländern
außerhalb der EU/des EWR verarbeiten. GitHub nennt hierfür das EU-US Data Privacy
Framework und Standardvertragsklauseln; Microsoft erläutert seine entsprechenden
Übermittlungsmechanismen in den Datenschutzhinweisen. Welche Grundlage eine
konkrete Übermittlung trägt, hängt vom Empfänger, der Verarbeitung und den
geltenden Vereinbarungen ab. Ein ausschließlicher Speicherort in der EU wird
nicht zugesichert. Informationen zu den jeweils anwendbaren Garantien und einer
Bezugsmöglichkeit können beim Anbieter angefragt werden. Die Hinweise der Dienste
ersetzen nicht die eigenen gesetzlichen Pflichten des Anbieters.

- GitHub: https://docs.github.com/en/site-policy/privacy-policies/github-general-privacy-statement
- Microsoft: https://privacy.microsoft.com/de-de/privacystatement

## Rechte

Soweit die gesetzlichen Voraussetzungen vorliegen, bestehen Rechte auf Auskunft,
Berichtigung, Löschung, Einschränkung und Datenübertragbarkeit. Gegen Verarbeitung
auf Grundlage berechtigter Interessen besteht aus Gründen der besonderen Situation
ein Widerspruchsrecht nach Art. 21 DSGVO. Eine etwaige Einwilligung kann für die
Zukunft widerrufen werden, soweit eine konkrete Verarbeitung darauf beruht;
die hier beschriebene gewöhnliche Supportbearbeitung stützt sich nicht auf eine
pauschale Einwilligung. Anfragen an den Anbieter können vertraulich an die
oben genannte E-Mail-Adresse gerichtet werden und müssen nicht öffentlich erfolgen.

Es besteht ein Beschwerderecht bei einer Datenschutzaufsichtsbehörde, insbesondere
am Aufenthaltsort, Arbeitsplatz oder Ort des vermuteten Verstoßes. Für den Anbieter
in Mannheim ist grundsätzlich der Landesbeauftragte für den Datenschutz und die
Informationsfreiheit Baden-Württemberg zuständig:
https://www.baden-wuerttemberg.datenschutz.de/.
Für Daten, die GitHub, Microsoft oder PayPal eigenständig verarbeiten, können Rechte auch
direkt dort geltend gemacht werden. Ausschließlich lokale Dateien kann der
Anbieter weder einsehen noch auf dem Nutzerrechner löschen.
Die Freiwilligkeit des Supports schränkt die gesetzlichen Antwortpflichten nicht
ein. Auf Anfragen zur Ausübung von Datenschutzrechten wird grundsätzlich innerhalb
eines Monats reagiert; gesetzlich zulässige Verlängerungen werden mit Begründung
innerhalb dieses Monats mitgeteilt.
