"""Shared help for iterative STL and native-project controls."""

TOWER_WALL_COUNT_HINT = (
    '<b>Was macht diese Einstellung?</b><p>&#8226; Legt die Anzahl der Turm-Wandlinien fest<br>'
    '&#8226; Die Slicerprüfung berechnet ihre Druckzeit mit den Linienbreiten, Layerhöhen und Geschwindigkeiten des gewählten Profils<br>'
    '&#8226; Bei aktiver 100-%-Turmfüllung zeigt die gesperrte, ausgegraute Box „solid“; dann gelten die Wandvorgaben des Profils</p>'
)

CONTRACTION_ANGLE_HINT = (
    '<b>Was macht diese Einstellung?</b><p>&#8226; Begrenzt die Verjüngung des Turms; der Winkel wird zur Horizontalen gemessen<br>'
    '&#8226; Auto verwendet die automatische Verjüngung; bei 100-%-Turmfüllung einschließlich der dafür vorgesehenen Übergänge<br>'
    '&#8226; Ohne Auto gilt der manuelle Winkel auch bei 100-%-Turmfüllung. Kleinere Werte erlauben flachere Übergänge<br>'
    '&#8226; Der manuelle Wert bleibt beim Umschalten erhalten</p>'
)
