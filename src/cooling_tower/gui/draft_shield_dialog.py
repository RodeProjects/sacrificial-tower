"""Decision dialog for a draft shield found in confirmed slicer profiles."""

from html import escape

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import QDialog, QLabel, QPushButton, QScrollArea, QVBoxLayout, QWidget


class DraftShieldDialog(QDialog):
    reload_profiles_requested = Signal()

    def __init__(self, role: str, profile_name: str, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Draft Shield in Slicerprofil erkannt")
        self.setWindowModality(Qt.WindowModality.WindowModal)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(22, 18, 22, 18)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QScrollArea.Shape.NoFrame)
        content = QWidget()
        body = QVBoxLayout(content)
        body.setContentsMargins(9, 0, 9, 14)
        profile_role = "Filamentprofil" if role == "filament" else "Prozessprofil"
        self.message = QLabel(
            '<h3 style="color:#a35417; margin-top:0">Draft Shield erkannt</h3>'
            f'<p>Im {profile_role} <b>{escape(profile_name)}</b> ist '
            '<b>Draft Shield</b> und/oder <b>Skirt-Loops</b> aktiviert.<br/>'
            'Diese Einstellungen können eine Kühlturmgenerierung verfälschen oder vollständig verhindern.</p>'
            '<h3 style="color:#1769aa">Option 1: Im Slicer selbst deaktivieren</h3>'
            '<p>Deaktiviere über den Slicer die folgenden Einstellungen '
            '(falls vorhanden) im genannten Profil:<br/>'
            '<i>Die Bezeichnungen können je nach Slicer und gewählter Sprache variieren.</i></p>'
            '<ul>'
            '<li><b>Draft Shield</b> (auf Deutsch meist <b>Luftzug-Schutz</b>)</li>'
            '<li><b>Skirt-Loops</b> (auf Deutsch meist <b>Anzahl Umdrehungsringe</b> '
            'oder <b>Schürzenschlaufen</b><br/>'
            '(Skirt-loops auf 0 zu setzen entspricht einer Deaktivierung)</li>'
            '</ul>'
            'Speichere anschließend das Profil und lies es dann hier erneut ein.</p>'
            '<h3 style="color:#23704c">Option 2: Deaktivierung simulieren</h3>'
            '<p>Für den Pre-Slice und die exportierte 3MF wird in einer '
            '<b>temporären Profilkopie</b> das Draft Shield deaktiviert und '
            'die Anzahl der Skirt-Loops auf <b>0</b> gesetzt.<br> '
            '<b>Die originalen Slicerprofile bleiben unverändert.</b></p>'
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
        self.reload_button = QPushButton("Ich habe die Einstellungen im Profil selbst deaktiviert und gespeichert")
        self.reload_button.setObjectName("supportSimulationReloadButton")
        self.reload_button.clicked.connect(self._reload_profiles)
        self.simulate_button = QPushButton("Mit simuliert deaktiviertem Draft Shield & Skirt-Loops fortfahren")
        self.simulate_button.setObjectName("supportSimulationProceedButton")
        self.simulate_button.clicked.connect(self.accept)
        for button in (self.cancel_button, self.reload_button, self.simulate_button):
            buttons.addWidget(button)
        layout.addLayout(buttons)
        self.cancel_button.setDefault(True)
        self.resize(640, 571)

    def _reload_profiles(self) -> None:
        self.reject()
        self.reload_profiles_requested.emit()
