"""Independently constructed, neutral native archive examples for unit tests."""
import json
import zipfile
from cooling_tower.native_project.graph import CORE_NAMESPACE, MODEL_RELATIONSHIP

VERTICES = ((-4,-4,0),(4,-4,0),(4,4,0),(-4,4,0),(-4,-4,4),(4,-4,4),(4,4,4),(-4,4,4))
FACES = ((0,2,1),(0,3,2),(0,1,5),(0,5,4),(1,2,6),(1,6,5),(2,3,7),(2,7,6),(3,0,4),(3,4,7),(4,5,6),(4,6,7))
MESH = '<mesh><vertices>'+''.join('<vertex x="%s" y="%s" z="%s"/>'%v for v in VERTICES)+'</vertices><triangles>'+''.join('<triangle v1="%s" v2="%s" v3="%s" paint_seam="4"/>'%f for f in FACES)+'</triangles></mesh>'

def write_native(path, *, producer='BambuStudio-02.08.02.61', extra_metadata='', values=None, model_config=None):
    settings = {'version':'02.08.02.61','printer_model':'Neutral printer','printer_technology':'FFF',
        'nozzle_diameter':['0.4'],'filament_type':['PLA'],'printable_area':['0x0','200x0','200x200','0x200'],
        'printable_height':'200','layer_height':'0.2','initial_layer_print_height':'0.2','post_process':[],
        'print_sequence':'by layer'}
    settings.update(values or {})
    with zipfile.ZipFile(path,'w',zipfile.ZIP_DEFLATED) as archive:
        archive.writestr('_rels/.rels',f'<Relationships><Relationship Type="{MODEL_RELATIONSHIP}" Target="/3D/main.model"/></Relationships>')
        archive.writestr('3D/main.model',f'<model xmlns="{CORE_NAMESPACE}"><metadata name="Application">{producer}</metadata>{extra_metadata}<resources><object id="1" type="model">{MESH}</object></resources><build><item objectid="1" transform="1 0 0 0 1 0 0 0 1 100 100 0"/></build></model>')
        archive.writestr('Metadata/project_settings.config',json.dumps(settings))
        if model_config is not None:
            archive.writestr('Metadata/model_settings.config',model_config)
    return settings
