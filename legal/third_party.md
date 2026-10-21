# Drittanbieter-Lizenzen

Sacrificial Tower verwendet Qt/PySide6 und Shiboken unter der LGPLv3 sowie
Python, NumPy, trimesh, truststore, cryptography und weitere separat dokumentierte
Komponenten unter ihren jeweiligen Lizenzen. Eigener Anwendungscode, eigene
Dokumentation und eigene Assets stehen grundsätzlich unter Apache-2.0 gemäß
„LICENSE.md“ und „NOTICE“. Diese Lizenzierung und die kostenlose Bereitstellung
durch den Anbieter ändern die Drittlizenzen nicht. Bei Weitergabe des Gesamtpakets
sind neben Apache-2.0 auch die jeweiligen Bedingungen der Drittkomponenten zu erfüllen.

Copyright an der eigenen Anwendung: © 2026 {{provider_name}}.
Die Rechte an Drittkomponenten verbleiben bei deren jeweiligen Rechteinhabern.
Zu den Rechteinhabern von Qt/PySide6 und Shiboken gehören The Qt Company Ltd.
und die weiteren in den mitgelieferten Originalhinweisen genannten Urheber.

Die vollständigen Lizenztexte und Urheberrechtshinweise der mitgelieferten
Komponenten werden mit der Anwendung im Unterordner „licenses“ des
Rechtsverzeichnisses ausgeliefert. „Lizenz- und Quellverzeichnis öffnen“ führt
in der Anwendung dorthin. „notice-index.json“ ordnet die Hinweise ihren
Komponenten und ursprünglichen Fundstellen zu; „dependency-artifacts.json“
nennt die beim Build verwendeten Paketversionen.
Die jeweiligen Lizenzen bestimmen die Nutzungs- und Weitergaberechte.

## Qt/PySide6 und Shiboken (LGPLv3)

Diese Bibliotheken werden dynamisch eingebunden. Sie dürfen entsprechend der
LGPLv3 geändert und durch kompatible Versionen ersetzt werden. Das hierfür
erforderliche Reverse Engineering zur Fehlerbehebung an solchen Änderungen ist
zulässig. Ein Austausch ist für die normale Benutzung der Anwendung nicht nötig.

Die LGPLv3 und die zugehörige GPLv3 liegen unter „licenses/Qt“. Quellarchive
befinden sich im mitgelieferten Ordner „sources“. Technische Hinweise für Nutzer,
die Bibliotheken selbst ändern möchten, stehen in „source_build_notes.md“ im
selben Rechtsverzeichnis. Diese Hinweise ändern weder die LGPLv3 noch ersetzen
sie die vollständigen Lizenz- und Urheberrechtstexte. Für eine abweichende
Paketierung sind die Austauschbarkeit und gegebenenfalls erforderliche
Installationsinformationen erneut sicherzustellen.

## Externe Slicer

Slicer werden nicht mitgeliefert. Die separat installierten Programme unterliegen
den Bedingungen ihrer jeweiligen Anbieter. Die Verwendung ihrer Produktnamen
beschreibt Kompatibilität und behauptet keine Unterstützung oder Partnerschaft.
