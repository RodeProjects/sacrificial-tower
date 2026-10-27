from __future__ import annotations

from html import escape


SUPPORT_DIAGNOSE_MENU_LABEL = "Support Diagnose …"


def slicer_support_hint_html() -> str:
    """List active integrations from the same registry as runtime support."""
    from cooling_tower.slicers.detection.registry import detection_modules

    products = "".join(
        f"<li>{escape(module.product_name)}</li>"
        for module in detection_modules() if module.implemented
    )
    return (
        "<p><b>Aktuell unterstützte Slicer</b></p>"
        f"<ul>{products}</ul>"
        '<p style="font-size:8pt;">Dieses Programm ist eine 1-Personen-Entwicklung. '
        "Ich bitte um Verständnis, falls ein Drucker nicht korrekt erkannt wird "
        "oder seine Einstellungen nicht vollständig kompatibel sind. Slicer und "
        "ihre unterstützten Drucker unterscheiden sich teilweise stark. Alle "
        "Kombinationen fehlerfrei abzudecken, ist schwer möglich – ich gebe "
        "stets mein Bestes.<br><br>"
        "Bei Problemen mit einem Slicer oder Drucker kannst du gerne ein "
        "GitHub-Issue eröffnen. Nutze dazu den Menüpunkt "
        f"„{SUPPORT_DIAGNOSE_MENU_LABEL}“ im Burgermenü.</p>"
    )


EXPANSION_ANGLE_CAUTION = (
    "Vorsicht: Der aktuelle Aufweitungswinkel erzeugt einen sehr starken Überhang."
)


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
        "ermittelt. Bereich: 5 bis 30 Sekunden; Standard: 9 Sekunden."
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
        "<p><b>Aufweitung begrenzen</b></p>"
        "<p>• Der Winkel wird zur Horizontalen (Druckbett) gemessen.<br>"
        "• Ein kleinerer Wert erlaubt flachere Außenflächen und mehr Aufweitung "
        "je Schicht; ein größerer Wert erzwingt steilere Außenflächen.<br>"
        "• Bei 35° und flacheren Winkeln zur Horizontalen sind ein gut kalibrierter "
        "Drucker und geeignete Druckeinstellungen besonders wichtig. Ab 29° und "
        "flacher erscheint zusätzlich ein Vorsichtshinweis im Programm.<br>"
        "• Der Bezug entspricht dem „Threshold angle“ bzw. „Schwellenwinkel“ im Slicer. "
        "Bei nach unten gerichteten Flächen unterhalb dieser Schwelle erkennt der "
        "Slicer einen Stützbedarf und versucht bei aktivierten Stützen dort "
        "Stützmaterial zu erzeugen. Weitere Stützeinstellungen beeinflussen das Ergebnis.</p>"
    ),
    "maximum_contraction_angle_deg": (
        "<p><b>Verjüngung begrenzen</b></p>"
        "<p>• Der Winkel wird zur Horizontalen (Druckbett) gemessen.<br>"
        "• Ein kleinerer Wert erlaubt eine flachere, stärkere Verjüngung je Schicht; "
        "ein größerer Wert erzwingt steilere Übergänge.<br>"
        "• Bei 100 % Turmfüllung bestimmt das Programm die Verjüngung nach eigenen Regeln. "
        "Das Feld ist dann gesperrt und zeigt „auto“. Der manuell eingestellte Winkel "
        "wird dabei nicht verwendet, bleibt aber erhalten und ist nach dem Ausschalten "
        "der Füllungssimulation wieder einstellbar.<br>"
        "• Direkte Absätze nach innen sind bei 100 % Turmfüllung nur vor einem Objektlayer "
        "mit ausreichender eigener Layerzeit möglich.</p>"
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
<p align="left" style="margin-top:0; margin-bottom:0px;"><b>Stützen simulieren</b></p>
<p style="margin-top:0; margin-bottom:8px;">&#8226; Wenn verfügbar, werden für die Simulation Baumstützen aktiviert (OrcaSlicer: „Baum (automatisch)“; PrusaSlicer ab Version 2.6: Stil „Organisch“). Die übrigen Stützparameter des gewählten Prozessprofils bleiben unverändert erhalten.</p>
<p align="left" style="margin-top:0; margin-bottom:0px;"><b>Stützen anpassen</b></p>
<p style="margin-top:0; margin-bottom:8px;">&#8226; Wenn die Stützen deinen Anforderungen nicht entsprechen, passe sie im Slicer direkt im gewählten Prozessprofil an. Speichere das Profil und lies die Profile im Kühlturm-Generator erneut ein. Die angepassten Stützparameter werden dann für die Simulation übernommen; soweit verfügbar, bleibt der Baumstützenstil aktiv.</p>
<p align="left" style="margin-top:0; margin-bottom:0px;"><b>Vorschau und Export</b></p>
<p style="margin-top:0; margin-bottom:0;">&#8226; Die Stützen werden bei der Turmgenerierung und beim gemeinsamen Prüfslice berücksichtigt und im exportierten 3MF für das Originalobjekt aktiviert. Die Originalprofile bleiben unverändert. Nur die gemeinsam geslicte Vorschau der iterativen Methode zeigt die simulierten Stützen.</p>
""".strip()
