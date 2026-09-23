from __future__ import annotations


SETTING_INFO_TEXTS = {
    "layer_time_tolerance_s": (
        "Zulässige Abweichung von der gewünschten Layerzeit nach oben und unten.\n\n"
        "Bereich: 0,01 bis 3 Sekunden;\n\nStandard: 0,2 Sekunden.\n\n"
        "Eine kleinere Toleranz kann mehr Kalibrierungsdurchläufe benötigen."
    ),
    "target_layer_time_s": (
        "Kürzeste gewünschte Druckzeit je Layer. Der Kühlturm ergänzt "
        "Druckzeit, wenn das eigentliche Objekt diesen Wert unterschreitet."
    ),
    "safety_factor": (
        "Vergrößert den berechneten zusätzlichen Druckweg als Reserve. "
        "1,10 entspricht zehn Prozent Sicherheitszuschlag."
    ),
    "minimum_outer_diameter_mm": (
        "Kleinster zulässiger Außendurchmesser oberhalb des Standfußes. "
        "Entfällt der Kühlbedarf dauerhaft, endet der Turm vorzeitig."
    ),
    "maximum_outer_diameter_mm": (
        "Größter regulärer Außendurchmesser des Kühlturms. Er begrenzt den "
        "Platz- und Materialbedarf sowie die maximal erreichbare Zusatzzeit."
    ),
    "minimum_object_tower_distance_mm": (
        "Legt den kleinsten freien Abstand zwischen Objekt und Kühlturm fest. "
        "Brim und Support werden automatisch mitgerechnet."
    ),
    "manual_base_width_mm": (
        "Außendurchmesser des Standfußes bei deaktivierter Automatik. "
        "Mindestens 20 mm sind erforderlich."
    ),
    "maximum_expansion_angle_deg": (
        "Größter zulässiger Winkel, mit dem sich der Turm nach außen "
        "linear aufweiten darf, gemessen zur Vertikalen."
    ),
    "maximum_contraction_angle_deg": (
        "Größter zulässiger Winkel, mit dem sich der Turm nach innen "
        "entlang einer konkaven Kurve verjüngen darf, gemessen zur Vertikalen. "
        "Bei 100 % Turmfüllung wird diese Winkelgrenze vollständig ignoriert. "
        "Bei abrupt sinkendem Bedarf sind dann direkte Absätze nach innen möglich."
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
