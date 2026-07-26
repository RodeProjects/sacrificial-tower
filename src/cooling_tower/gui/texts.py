from __future__ import annotations


SETTING_INFO_TEXTS = {
    "target_layer_time_s": (
        "Kürzeste gewünschte Druckzeit je Layer. Der Kühlturm ergänzt "
        "Druckzeit, wenn das eigentliche Objekt diesen Wert unterschreitet."
    ),
    "safety_factor": (
        "Vergrößert den berechneten zusätzlichen Druckweg als Reserve. "
        "1,10 entspricht zehn Prozent Sicherheitszuschlag."
    ),
    "minimum_outer_radius_mm": (
        "Kleinster zulässiger Außenradius des Kühlturms. Ein größerer Wert "
        "erhöht den Platzbedarf und kann zusätzliche Druckzeit erzeugen."
    ),
    "maximum_outer_radius_mm": (
        "Größter regulärer Außenradius des Kühlturms. Zusätzlicher Zeitbedarf "
        "wird danach bevorzugt über die Wandstärke ausgeglichen."
    ),
    "minimum_wall_thickness_mm": (
        "Dünnste zulässige Turmwand. Der Wert sollte zu Düse, Material und "
        "der im Slicer eingestellten Linienbreite passen."
    ),
    "maximum_wall_thickness_mm": (
        "Dickste zulässige Turmwand. Sie begrenzt, wie viel zusätzliche "
        "Druckzeit über weitere Wandlinien erzeugt werden kann."
    ),
    "wall_path_width_mm": (
        "Tatsächliche Linienbreite einer Wandbahn im Slicer. Bei einer "
        "0,4-mm-Düse liegt sie häufig etwas über dem Düsendurchmesser."
    ),
    "minimum_inner_radius_mm": (
        "Kleinster freizuhaltender Hohlraumradius. Er verhindert, dass der "
        "Kühlturm bei größerer Wandstärke vollständig massiv wird."
    ),
    "manual_base_width_mm": (
        "Außendurchmesser des Standfußes bei deaktivierter Automatik. "
        "Mindestens 20 mm sind erforderlich."
    ),
    "base_height_mm": (
        "Vertikale Höhe des verstärkten Standfußbereichs am unteren Ende "
        "des Kühlturms."
    ),
    "maximum_expansion_angle_deg": (
        "Größter zulässiger Winkel, mit dem sich der Turm nach außen "
        "aufweiten darf, gemessen zur Vertikalen."
    ),
    "maximum_contraction_angle_deg": (
        "Größter zulässiger Winkel, mit dem sich der Turm nach innen "
        "verjüngen darf, gemessen zur Vertikalen."
    ),
    "maximum_wall_change_per_mm_z": (
        "Begrenzt die Änderung der Wandstärke je Millimeter Bauhöhe. "
        "Kleinere Werte erzeugen weichere Übergänge."
    ),
    "mesh_segments": (
        "Anzahl gerader Segmente pro Kreisring im STL-Netz. Mehr Segmente "
        "erzeugen rundere Flächen, aber größere Dateien."
    ),
    "local_reference_window": (
        "Ungerade Anzahl benachbarter Layer für die lokale Zeitreferenz. "
        "Größere Fenster glätten kurze Schwankungen stärker."
    ),
}

PREDICTION_ROWS = (
    ("target", "◎", "Gewünschte Mindest-Layerzeit"),
    ("minimum", "◷", "Voraussichtlich kürzeste Layerzeit"),
    ("shortfall", "↓", "Voraussichtliche Unterschreitung"),
    ("critical", "!", "Kritische Layer"),
    ("height", "↕", "Erwartete Turmhöhe"),
)
