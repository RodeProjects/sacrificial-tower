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
    "minimum_outer_diameter_mm": (
        "Kleinster zulässiger Außendurchmesser des Kühlturms. Der Turm "
        "beginnt mit dieser Breite und wächst nur bei zusätzlichem Zeitbedarf."
    ),
    "maximum_outer_diameter_mm": (
        "Größter regulärer Außendurchmesser des Kühlturms. Er begrenzt den "
        "Platz- und Materialbedarf sowie die maximal erreichbare Zusatzzeit."
    ),
    "minimum_object_tower_distance_mm": (
        "Kleinster Abstand zwischen den belegten Außenkanten von Druckobjekt "
        "und Kühlturm. Der voranalysierte Brim und Support des Objekts sowie "
        "Standfuß und Brim des Turms werden dabei berücksichtigt."
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
