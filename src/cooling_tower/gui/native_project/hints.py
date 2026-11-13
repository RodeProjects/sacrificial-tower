"""Native UI help, independently copied from equivalent STL settings."""
from html import escape
from cooling_tower.gui.iterative_hints import CONTRACTION_ANGLE_HINT, TOWER_WALL_COUNT_HINT
from cooling_tower.tower.base_calculator import BASE_WIDTH_PER_OBJECT_HEIGHT

EXPANSION_ANGLE_CAUTION = 'Vorsicht: Der aktuelle Aufweitungswinkel erzeugt einen sehr starken Überhang.'


CHART_HINTS = {
    'logarithmic_time_scale': (
        'Stellt kurze und lange Layerzeiten gemeinsam lesbar dar. Gleiche Abstände entsprechen dabei Zeitverhältnissen statt gleichen Zeitunterschieden.',
        'Abschalten zeigt eine lineare Zeitskala. Die berechneten Zeiten, Layerauswahl und der G-Code bleiben unverändert.'),
    'normalize_time_scale': (
        'Layer 1 bleibt mit seiner vollständigen Zeit in Berechnung, Layerauswahl und Zeitangabe erhalten, erhält im Diagramm aber keinen Farbbalken.',
        'Die Zeitskala richtet sich nach den übrigen Layern und der Mindest-Layerzeit. So drückt eine lange erste Schicht die übrigen Balken nicht zusammen.',
        'Zu Beginn aktiviert, wenn Layer 1 allein die längste Gesamtzeit hat. Die Option ändert weder G-Code noch berechnete Zeiten.'),
}


def chart_hint(label, name):
    bullets = '<br>'.join('&#8226; ' + escape(text) for text in CHART_HINTS[name])
    return (f'<p align="left" style="margin-top:0; margin-bottom:0px;"><b>{escape(label)}</b></p>'
        f'<p style="margin-top:0; margin-bottom:10px;">{bullets}</p>')

def _automatic_base_hint() -> tuple[str, str]:
    rate = f"{BASE_WIDTH_PER_OBJECT_HEIGHT:g}".replace(".", ",")
    html = (
        '<p align="left" style="margin-top:0; margin-bottom:0px;">'
        '<b>Automatische Standfußbreite</b></p>'
        '<p style="margin-top:0; margin-bottom:10px;">'
        f'&#8226; <b>Berechnungsgrundlage:</b> {rate} mm Breite je 1 mm '
        'Original-Objekthöhe.<br>'
        '&#8226; <b>Grenzbereich:</b> Das Ergebnis wird auf mindestens '
        '31,25 mm und höchstens 80 mm begrenzt.</p>'
        '<p align="left" style="margin-top:0; margin-bottom:0px;">'
        '<b>Manuelle Standfußbreite</b></p>'
        '<p style="margin-top:0; margin-bottom:10px;">'
        '&#8226; <b>Grenzbereich:</b> Manuell einstellbar zwischen 20 und 80mm.<br>'
        '&#8226; Ein breiterer Standfuß verbessert Druckbett-Haftung und '
        'Turmstabilität.</p>'
    )
    accessible = (
        f"Automatische Standfußbreite. Berechnungsgrundlage: {rate} "
        "Millimeter Breite je 1 Millimeter Original-Objekthöhe. "
        "Grenzbereich: Das Ergebnis wird auf mindestens 31,25 Millimeter "
        "und höchstens 80 Millimeter begrenzt. "
        "Manuelle Standfußbreite. Grenzbereich: Manuell einstellbar "
        "zwischen 20 und 80 Millimetern. Ein breiterer Standfuß verbessert "
        "Druckbett-Haftung und Turmstabilität."
    )
    return html, accessible

TOWER_SUPPORT_HINT_HTML = """
<p align="left" style="margin-top:0; margin-bottom:0px;"><b>Was bewirkt die Einstellung?</b></p>
<p style="margin-top:0; margin-bottom:10px;">Bei aktivierter Einstellung werden die Stützen für den Kühlturm objektspezifisch deaktiviert. Der Turm wird so ohne eigene Stützen berechnet; die Stützen des Druckobjekts bleiben erhalten.</p>
<p>* Die Stützen werden nur für den Kühlturm deaktiviert. Zur Generierung werden temporäre Profilkopien verwendet; im exportierten 3MF wird die Deaktivierung objektspezifisch gesetzt. Die Originalprofile bleiben unverändert.</p>
""".strip()

SETTING_INFO_TEXTS = {'layer_time_tolerance_s': '<p align="left" style="margin-top:0; '
                           'margin-bottom:0px;"><b>Layerzeit-Toleranz</b></p><p style="margin-top:0; '
                           'margin-bottom:10px;">&#8226; <b>Bedeutung:</b> Dieser Wert bestimmt, wie weit '
                           'die erreichte Layerzeit von der gewünschten Layerzeit abweichen darf, damit das '
                           'Ergebnis noch als zufriedenstellend gilt.<br>&#8226; <b>Bereich:</b> 0,1 bis 3 '
                           'Sekunden.<br>&#8226; <b>Standard:</b> 0,25 Sekunden.</p><p style="margin-top:0; '
                           'margin-bottom:0px;">* Eine kleinere Toleranz kann mehr Kalibrierungsdurchläufe '
                           'erfordern.</p>',
 'local_reference_window': 'Ungerade Anzahl benachbarter Layer für die lokale Zeitreferenz. Größere Fenster '
                           'glätten kurze Schwankungen stärker. Nach der Modellanalyse begrenzt die '
                           'Layerzahl des Objekts die Eingabe.',
 'manual_base_width_mm': 'Außendurchmesser des Standfußes bei deaktivierter Automatik. Mindestens 20 mm und '
                         'höchstens 80 mm sind zulässig.',
 'maximum_contraction_angle_deg': CONTRACTION_ANGLE_HINT,
 'tower_wall_count': TOWER_WALL_COUNT_HINT,
 'maximum_expansion_angle_deg': '<p><b>Aufweitung begrenzen</b></p><p>• Der Winkel wird zur Horizontalen '
                                '(Druckbett) gemessen.<br>• Ein kleinerer Wert erlaubt flachere Außenflächen '
                                'und mehr Aufweitung je Schicht; ein größerer Wert erzwingt steilere '
                                'Außenflächen.<br>• Bei 35° und flacheren Winkeln zur Horizontalen sind ein '
                                'gut kalibrierter Drucker und geeignete Druckeinstellungen besonders '
                                'wichtig. Ab 29° und flacher erscheint zusätzlich ein Vorsichtshinweis im '
                                'Programm.<br>• Der Bezug entspricht dem „Threshold angle“ bzw. '
                                '„Schwellenwinkel“ im Slicer. Bei nach unten gerichteten Flächen unterhalb '
                                'dieser Schwelle erkennt der Slicer einen Stützbedarf und versucht bei '
                                'aktivierten Stützen dort Stützmaterial zu erzeugen. Weitere '
                                'Stützeinstellungen beeinflussen das Ergebnis.</p>',
 'maximum_outer_diameter_mm': 'Größter regulärer Außendurchmesser des Kühlturms oberhalb des Standfußes. Der '
                              'Standfuß darf breiter sein. Diese Grenze beeinflusst den Platz- und '
                              'Materialbedarf sowie die erreichbare Zusatzzeit.',
 'minimum_outer_diameter_mm': 'Kleinster zulässiger Außendurchmesser oberhalb des Standfußes. Entfällt der '
                              'Kühlbedarf dauerhaft, endet der Turm vorzeitig.',
 'simulate_full_tower_infill': '<p align="left" style="margin-top:0; margin-bottom:0px;"><b>Was macht diese '
                               'Funktion?</b></p>\n'
                               '<p style="margin-top:0; margin-bottom:10px;">\n'
                               '&#8226; <b>Aktiviert:</b> In der temporären Slicerprofilkopie wird für den '
                               'Turm 100% Füllung eingestellt.<br>\n'
                               '&#8226; <b>Deaktiviert:</b> Für Berechnung und Slice gelten die '
                               'Füllungswerte des gewählten Slicerprofils.</p>\n'
                               '<p align="left" style="margin-top:0; margin-bottom:0px;"><b>Sollte ich diese '
                               'Einstellung aktivieren?</b></p>\n'
                               '<p style="margin-top:0; margin-bottom:10px;">Das hängt teilweise davon ab, '
                               'ob Ihr Drucker ein Bettschubser oder ein CoreXY-Drucker ist.</p>\n'
                               '<p align="left" style="margin-top:0; margin-bottom:0px;"><b>Welchen '
                               'Druckertyp habe ich?</b></p>\n'
                               '<p style="margin-top:0; margin-bottom:8px;">\n'
                               '&#8226; <b>Bettschubser:</b> Das Druckbett bewegt das Modell horizontal vor '
                               'und zurück.<br>\n'
                               '&#8226; <b>CoreXY:</b> Der Druckkopf übernimmt die horizontalen '
                               'X/Y-Bewegungen; das Bett fährt dabei nicht hin und her.</p>\n'
                               '<p align="center" style="margin-top:0; margin-bottom:0px;"><b>Vor- und '
                               'Nachteile dieser Funktion:</b></p>\n'
                               '<table width="100%" cellspacing="0" cellpadding="0" border="0" '
                               'style="margin-top:6px; margin-bottom:0px;">\n'
                               '  <tr>\n'
                               '    <th align="left" style="padding:4px 12px 4px 0;"><u>Druckertyp</u></th>\n'
                               '    <th align="left" style="padding:4px 12px;"><u>Aktiviert: Vorteil / '
                               'Nachteil</u></th>\n'
                               '    <th align="left" style="padding:4px 12px;"><u>Deaktiviert: Vorteil / '
                               'Nachteil</u></th>\n'
                               '  </tr>\n'
                               '  <tr>\n'
                               '    <td valign="top" style="padding:4px 12px 4px '
                               '0;"><b>Bettschubser</b></td>\n'
                               '    <td valign="top" style="padding:4px 12px;"><b>Aktivierung '
                               'empfohlen.</b><br>+ Schmalerer Turm<br>+ Weniger Schwingungen<br>- Mehr '
                               'Material</td>\n'
                               '    <td valign="top" style="padding:4px 12px;">+ Weniger Material<br>- '
                               'Breiterer Turm<br>- Kann stärker schwingen.</td>\n'
                               '  </tr>\n'
                               '  <tr>\n'
                               '    <td valign="top" style="padding:4px 12px 4px 0;"><b>CoreXY</b></td>\n'
                               '    <td valign="top" style="padding:4px 12px;">+ Schmalerer Turm<br/>- Mehr '
                               'Material</td>\n'
                               '    <td valign="top" style="padding:4px 12px;">+ Weniger Material<br/>- '
                               'Breiterer Turm</td>\n'
                               '  </tr>\n'
                               '</table>\n'
                               '<p>* Die 100%-Füllung gilt nur für den Kühlturm. Zur Generierung werden '
                               'temporäre Profilkopien verwendet; im exportierten 3MF wird die Füllung '
                               'objektspezifisch gesetzt. Die Originalprofile bleiben unverändert.</p>',
 'target_layer_time_s': 'Kürzeste gewünschte Druckzeit je Layer. Der Kühlturm ergänzt Druckzeit, wenn das '
                        'eigentliche Objekt diesen Wert unterschreitet. Die kürzeste Layerzeit des '
                        'Originalobjekts wird beim Pre-Slice ermittelt. Bereich: 5 bis 30 Sekunden; '
                        'Standard: 9 Sekunden.'}
SETTING_INFO_TEXTS["simulate_tower_without_supports"] = TOWER_SUPPORT_HINT_HTML
SETTING_INFO_TEXTS["manual_base_width_mm"] = _automatic_base_hint()[0]
SETTING_INFO_TEXTS['minimum_outer_diameter_mm'] = (
    'Kleinster zulässiger Außendurchmesser oberhalb des Standfußes. '
    'Der Turm folgt den Modellschichten der ausgewählten Druckplatte.')
SETTING_INFO_TEXTS['minimum_object_tower_distance_mm'] = (
    '<p align="left" style="margin-top:0; margin-bottom:0px;"><b>Modellabstand</b></p>'
    '<p style="margin-top:0; margin-bottom:10px;">'
    '&#8226; Mindestens dieser Abstand bleibt zwischen Modell und vollständigem Turmfuß frei.<br>'
    '&#8226; Größere Abstände benötigen mehr Bettfläche und längere Fahrwege.</p>')
SETTING_INFO_TEXTS['circle_segments'] = (
    '<p><b>Turm-Kreissegmente</b></p>'
    '<p>Bestimmt, aus wie vielen geraden Abschnitten der Umfang des Turms besteht. '
    'Mehr Segmente ergeben einen runderen Turm und eine größere 3MF-Projektdatei.</p>'
    '<p><b>Automatisch berechnen:</b> Mindestens 30 Segmente, danach '
    'ein Segment pro Millimeter des größten Turmdurchmessers. Das gesperrte Feld '
    'zeigt die Segmentzahl des übernommenen Turms, vorher <b>—</b>.</p>'
    '<p>Ohne Automatik sind <b>4 bis 256</b> Segmente möglich. Die Auswahl gilt '
    'für die gemeinsame Slicerprüfung, die Vorschau und den Export.</p>')
SETTING_INFO_TEXTS['maximum_expansion_angle_deg'] += (
    '<p><b>Auto</b> übernimmt den horizontalen Stützwinkel aus dem eingebetteten '
    'Prozessprofil. Ohne Auto gilt der manuell eingestellte Winkel.</p>')
for surface, location in (('top', 'Oberseiten'), ('bottom', 'Unterseiten')):
    SETTING_INFO_TEXTS[f'{surface}_shell_layers'] = (
        f'Legt fest, wie viele geschlossene Layer der Slicer an den {location} des Turms erzeugt. '
        'Manuell sind 0 bis 5 möglich. Der Standardwert ist 1. '
        'Auto übernimmt den Wert aus dem eingebetteten Prozessprofil, auch wenn er über 5 liegt.')
SETTING_INFO_TEXTS['extra_top_layer'] = (
    'Erzeugt genau einen zusätzlichen Layer auf dem Turm. Die kleinste Kappe wird mittig oder '
    'an der nächstgelegenen ausreichend gefüllten Stelle platziert. Bei zu wenig Füllung '
    'liegt der zusätzliche Layer auf der vorherigen Turmwand. '
    'Sacrificial Tower lässt diesen Layer bei der Ermittlung der Mindest-Layerzeit absichtlich '
    'aus. Der Slicer wird deshalb wahrscheinlich eine weitaus kürzere Mindest-Layerzeit anzeigen.')
SETTING_INFO_TEXTS['concave_base'] = (
    'Formt den Standfuß wie bei 100 % Turmfüllung konkav. Wo den nach innen wandernden '
    'Wänden Auflage fehlt, füllt der Slicer den Standfuß bis zum Erreichen des Verjüngungswinkels massiv.')
