from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QDialog, QLabel, QPushButton, QScrollArea, QVBoxLayout, QWidget,
)


class SupportSimulationDialog(QDialog):
    """Consent to a source-scoped retry; uses the main window's reveal policy."""

    reload_profiles_requested = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Pre-Slice: Auflagefläche und Stützen prüfen")
        self.setWindowModality(Qt.WindowModality.WindowModal)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(22, 18, 22, 18)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QScrollArea.Shape.NoFrame)
        content = QWidget()
        body = QVBoxLayout(content)
        body.setContentsMargins(9, 0, 9, 14)
        self.message = QLabel(
            '<h3 style="color:#a35417; margin-top:0">Kein G-Code erzeugt</h3>'
            '<p>Der Slicer konnte diese <b>Modell-/Profilkombination</b> nicht verarbeiten. '
            'Prüfe das Modell im gewählten Slicer: Hat die erste Schicht eine '
            '<b>druckbare Auflagefläche</b>, oder sind <b>Stützen</b> nötig? Auch eine '
            'geschlossene (manifold) STL kann auf einer zu dünnen Spitze stehen.</p>'
            '<p>Was sich dort mit denselben Profilen fehlerfrei slicen lässt, wird '
            'meist auch hier akzeptiert.</p>'
            '<h3 style="color:#1769aa">Profiländerungen speichern</h3>'
            '<p>Erkannt werden nur <b>gespeicherte Änderungen</b> an Maschinen-, '
            'Filament- und Prozessprofilen. Ungespeicherte Änderungen und '
            'objektspezifische Einstellungen werden nicht übernommen. '
            'Speichere daher auch aktivierte Stützen im gewählten Profil.</p>'
            '<h3 style="color:#23704c">Alternativ: Stützen simulieren</h3>'
            '<p>Im gewählten Prozessprofil sind <b>Stützen aktuell deaktiviert.</b></p>'
            '<p>Für diese STL werden in einer <b>temporären Profilkopie</b> die '
            '<b>Stützen aktiviert</b> und der Pre-Slice anschließend erneut versucht. '
            'Alle zu den Stützen gehörigen Einstellungen werden unverändert verwendet. '
            '<b>Deine originalen Profile bleiben dabei stets unverändert</b>.</p>'
        )
        self.message.setTextFormat(Qt.TextFormat.RichText)
        self.message.setWordWrap(True)
        self.message.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        body.addWidget(self.message)
        scroll.setWidget(content)
        layout.addWidget(scroll)
        buttons = QVBoxLayout()
        self.cancel_button = QPushButton("Abbrechen")
        self.cancel_button.setObjectName("supportSimulationCancelButton")
        self.cancel_button.clicked.connect(self.reject)
        self.reload_button = QPushButton("Ich habe die Stützen selbst aktiviert und gespeichert")
        self.reload_button.setObjectName("supportSimulationReloadButton")
        self.reload_button.clicked.connect(self._reload_profiles)
        self.simulate_button = QPushButton("Mit simulierten Stützen fortfahren")
        self.simulate_button.setObjectName("supportSimulationProceedButton")
        self.simulate_button.clicked.connect(self.accept)
        buttons.addWidget(self.cancel_button)
        buttons.addWidget(self.reload_button)
        buttons.addWidget(self.simulate_button)
        layout.addLayout(buttons)
        self.cancel_button.setDefault(True)
        self.resize(640, 571)

    def _reload_profiles(self) -> None:
        self.reject()
        self.reload_profiles_requested.emit()
