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


FULL_INFILL_HINT_HTML = """
<p align="left" style="margin-top:0; margin-bottom:0px;"><b>Was macht diese Funktion?</b></p>
<p style="margin-top:0; margin-bottom:10px;">
&#8226; <b>Aktiviert:</b> In der temporären Slicerprofilkopie wird für den Turm 100% Füllung eingestellt.<br>
&#8226; <b>Deaktiviert:</b> Für Berechnung und Slice gelten die Füllungswerte des gewählten Slicerprofils.</p>
<p align="left" style="margin-top:0; margin-bottom:0px;"><b>Sollte ich diese Einstellung aktivieren?</b></p>
<p style="margin-top:0; margin-bottom:10px;">Das hängt teilweise davon ab, ob Ihr Drucker ein Bettschubser oder ein CoreXY-Drucker ist.</p>
<p align="left" style="margin-top:0; margin-bottom:0px;"><b>Welchen Druckertyp habe ich?</b></p>
<p style="margin-top:0; margin-bottom:8px;">
&#8226; <b>Bettschubser:</b> Das Druckbett bewegt das Modell horizontal vor und zurück.<br>
&#8226; <b>CoreXY:</b> Der Druckkopf übernimmt die horizontalen X/Y-Bewegungen; das Bett fährt dabei nicht hin und her.</p>
<p align="center" style="margin-top:0; margin-bottom:0px;"><b>Vor- und Nachteile dieser Funktion:</b></p>
<table width="100%" cellspacing="0" cellpadding="0" border="0" style="margin-top:6px; margin-bottom:0px;">
  <tr>
    <th align="left" style="padding:4px 12px 4px 0;"><u>Druckertyp</u></th>
    <th align="left" style="padding:4px 12px;"><u>Aktiviert: Vorteil / Nachteil</u></th>
    <th align="left" style="padding:4px 12px;"><u>Deaktiviert: Vorteil / Nachteil</u></th>
  </tr>
  <tr>
    <td valign="top" style="padding:4px 12px 4px 0;"><b>Bettschubser</b></td>
    <td valign="top" style="padding:4px 12px;"><b>Aktivierung empfohlen.</b><br>+ Schmalerer Turm<br>+ Weniger Schwingungen<br>- Mehr Material</td>
    <td valign="top" style="padding:4px 12px;">+ Weniger Material<br>- Breiterer Turm<br>- Kann stärker schwingen.</td>
  </tr>
  <tr>
    <td valign="top" style="padding:4px 12px 4px 0;"><b>CoreXY</b></td>
    <td valign="top" style="padding:4px 12px;">+ Schmalerer Turm<br/>- Mehr Material</td>
    <td valign="top" style="padding:4px 12px;">+ Weniger Material<br/>- Breiterer Turm</td>
  </tr>
</table>
<p>* Die 100%-Füllung gilt nur für den Kühlturm. Zur Generierung werden temporäre Profilkopien verwendet; im exportierten 3MF wird die Füllung objektspezifisch gesetzt. Die Originalprofile bleiben unverändert.</p>
""".strip()

FULL_INFILL_HINT_ACCESSIBLE = (
    "Sollte ich diese Einstellung aktivieren? Das hängt vom Druckertyp ab. "
    "Beim Bettschubser bewegt das Bett das Modell horizontal; die Aktivierung "
    "ist empfohlen, weil der Turm gleich breit bleibt oder schmaler und "
    "stabiler wird und weniger schwingt. "
    "Sie benötigt etwas mehr Material. Bei CoreXY bewegt der Druckkopf sich "
    "horizontal; die Aktivierung ist meist optional. Deaktiviert braucht der "
    "Turm meist weniger Material, kann aber breiter sein. Die volle Füllung "
    "betrifft nur den Kühlturm."
)

SOURCE_SUPPORT_HINT_HTML = """
<p style="margin-top:0; margin-bottom:8px;"><b>Im Prozessprofil sind globale Stützen deaktiviert.</b></p>
<p style="margin-top:0; margin-bottom:8px;">Bei aktivierter Einstellung werden die Stützen objektspezifisch für das übergebene STL-Objekt simuliert. Sie werden bei der Turmgenerierung und beim gemeinsamen Prüfslice berücksichtigt und im exportierten 3MF für das Originalobjekt aktiviert.</p>
<p style="margin-top:0; margin-bottom:0;">Die Originalprofile bleiben unverändert. Die Vorschauen bleiben gleich; nur die gemeinsam geslicte automatische Vorschau zeigt die simulierten Stützen.</p>
""".strip()
