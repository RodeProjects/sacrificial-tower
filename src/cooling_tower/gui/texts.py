from __future__ import annotations


SETTING_INFO_TEXTS = {
    "layer_time_tolerance_s": (
        '<p align="left" style="margin-top:0; margin-bottom:0px;">'
        '<b>Layerzeit-Toleranz</b></p>'
        '<p style="margin-top:0; margin-bottom:10px;">'
        '&#8226; <b>Bedeutung:</b> Dieser Wert bestimmt, wie weit die erreichte '
        'Layerzeit von der gewünschten Layerzeit abweichen darf, damit das '
        'Ergebnis noch als zufriedenstellend gilt.<br>'
        '&#8226; <b>Bereich:</b> 0,1 bis 3 Sekunden.<br>'
        '&#8226; <b>Standard:</b> 0,25 Sekunden.</p>'
        '<p style="margin-top:0; margin-bottom:0px;">'
        '* Eine kleinere Toleranz kann mehr Kalibrierungsdurchläufe '
        'erfordern.</p>'
    ),
    "target_layer_time_s": (
        "Kürzeste gewünschte Druckzeit je Layer. Der Kühlturm ergänzt "
        "Druckzeit, wenn das eigentliche Objekt diesen Wert unterschreitet. "
        "Die kürzeste Layerzeit des Originalobjekts wird beim Pre-Slice "
        "ermittelt. Bereich: 5 bis 30 Sekunden; Standard: 10 Sekunden."
    ),
    "minimum_outer_diameter_mm": (
        "Kleinster zulässiger Außendurchmesser oberhalb des Standfußes. "
        "Entfällt der Kühlbedarf dauerhaft, endet der Turm vorzeitig."
    ),
    "maximum_outer_diameter_mm": (
        "Größter regulärer Außendurchmesser des Kühlturms oberhalb des "
        "Standfußes. Der Standfuß darf breiter sein. Diese Grenze beeinflusst "
        "den Platz- und Materialbedarf sowie die erreichbare Zusatzzeit."
    ),
    "manual_base_width_mm": (
        "Außendurchmesser des Standfußes bei deaktivierter Automatik. "
        "Mindestens 20 mm und höchstens 80 mm sind zulässig."
    ),
    "maximum_expansion_angle_deg": (
        "Größter zulässiger Winkel, mit dem sich der Turm nach außen "
        "linear aufweiten darf, gemessen zur Vertikalen."
    ),
    "maximum_contraction_angle_deg": (
        "Größter zulässiger Winkel, mit dem sich der Turm nach innen "
        "entlang einer konkaven Kurve verjüngen darf, gemessen zur Vertikalen. "
        "Bei 100 % Turmfüllung wird diese Winkelgrenze vollständig ignoriert. "
        "Direkte Absätze nach innen sind dann nur vor einem Objektlayer "
        "mit ausreichender eigener Layerzeit möglich."
    ),
    "local_reference_window": (
        "Ungerade Anzahl benachbarter Layer für die lokale Zeitreferenz. "
        "Größere Fenster glätten kurze Schwankungen stärker. Nach der "
        "Modellanalyse begrenzt die Layerzahl des Objekts die Eingabe."
    ),
}

PREDICTION_ROWS = (
    ("target", "◎", "Gewünschte Mindest-Layerzeit"),
    ("minimum", "◷", "Voraussichtlich kürzeste Layerzeit"),
    ("shortfall", "↓", "Voraussichtliche Unterschreitung"),
    ("critical", "!", "Kritische Layer"),
    ("height", "↕", "Erwartete Turmhöhe"),
)
