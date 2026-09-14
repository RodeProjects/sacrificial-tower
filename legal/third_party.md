# Drittanbieter-Lizenzen

Sacrificial Tower verwendet Qt/PySide6 und Shiboken unter der LGPLv3 sowie
Python, NumPy, trimesh, truststore, cryptography und weitere separat dokumentierte
Komponenten unter ihren jeweiligen Lizenzen. Die proprietäre Lizenz der Anwendung
ersetzt diese Lizenzen nicht.

Die mitgelieferten vollständigen Lizenztexte liegen im Unterordner „licenses“
dieses Rechtsverzeichnisses. Der Buildnachweis nennt konkrete Versionen und
Datei-Hashes. Quellmaterial und Lizenzpflichten der tatsächlich eingebundenen
Unterkomponenten werden im Release-Nachweis geprüft.

## Qt/PySide6 austauschen

Die Windows-Anwendung verwendet dynamische Bibliotheken im Verzeichnis
_internal/PySide6 und _internal/shiboken6. Eine Sicherung der Installation anlegen,
das Programm schließen und die betroffenen Bibliotheken durch ABI-kompatible
eigene Builds derselben Versionsreihe ersetzen. Python-ABI, Architektur (x64),
Qt-Plugins und zugehörige Bindings müssen zusammenpassen. Anschließend die lokale
Kopie starten und insbesondere Fenster, Dateiauswahl, SVG-Icons und Slicer-Aufrufe
prüfen. Es gibt keine Integritätsprüfung, die ausgetauschte Qt-Bibliotheken beim
Programmstart zurückweist. Ein Programmupdate kann eigene Änderungen ersetzen;
für eine bearbeitete Kopie lässt sich die automatische Updateprüfung deaktivieren.

Änderungen an diesen Bibliotheken und das hierfür erforderliche Reverse Engineering
zur Fehlerbehebung sind erlaubt. Die zugehörigen LGPL-/GPL-Lizenztexte beschreiben
die Rechte vollständig. Der Quellcode der eigenen Anwendung muss allein aufgrund
der zulässigen LGPL-Nutzung nicht offengelegt werden.

Die Bereitstellung des korrespondierenden Bibliotheksquellcodes samt erforderlichen
Buildinformationen wird vor öffentlicher Distribution im Release-Nachweis verifiziert.
Ein bloßer Verweis auf eine allgemeine Hersteller-Startseite genügt diesem Prozess
nicht. Noch offene Freigabe: {{release_legal_review}}.

Slicer werden nicht mitgeliefert. Die separat installierten Programme unterliegen
den Bedingungen ihrer jeweiligen Anbieter. Die Verwendung ihrer Produktnamen
beschreibt Kompatibilität und behauptet keine Unterstützung oder Partnerschaft.
