from pathlib import Path
import json
import sys
import tempfile
import unittest
import zipfile
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'src'))
from native_project_fixtures import write_native
from cooling_tower.native_project.compatibility import freeze_plate_name,execution_project,_decode_scalar,_encode_scalar,_freeze_value
from cooling_tower.native_project.session import NativeProjectSession
from cooling_tower.protected_io import OwnedWorkspace
from cooling_tower.native_project.compose import append_tower
from cooling_tower.tower.mesh_generator import TriangleMesh
from native_project_fixtures import VERTICES, FACES


class NativeCompatibilityTests(unittest.TestCase):
    def test_isolated_slice_disables_original_instances_only_in_the_execution_copy(self):
        from xml.etree import ElementTree as ET
        with tempfile.TemporaryDirectory() as temporary, OwnedWorkspace() as work:
            source = Path(temporary)/'neutral.3mf'
            write_native(source)
            session = NativeProjectSession(source)
            self.addCleanup(session.close)
            mesh = TriangleMesh(VERTICES, FACES, 2, 4)
            composed = append_tower(session.context, '1', mesh, workspace=work, center_mm=(25,25))
            execution = execution_project(session.context, composed.path, work, plate_id='1', tower_only=True)
            with zipfile.ZipFile(composed.path) as joint, zipfile.ZipFile(execution) as isolated:
                entries = joint.namelist()
                self.assertEqual(set(entries), set(isolated.namelist()))
                path = '3D/main.model'
                for name in entries:
                    if name != path:
                        self.assertEqual(isolated.read(name), joint.read(name))
                joint_items = ET.fromstring(joint.read(path)).findall('{*}build/{*}item')
                isolated_items = ET.fromstring(isolated.read(path)).findall('{*}build/{*}item')
                self.assertEqual([item.attrib for item in isolated_items],
                    [dict(joint_items[0].attrib, printable='0'), joint_items[1].attrib])
            self.assertFalse(session.original_changed())

    def test_only_native_placeholder_tokens_are_specialized(self):
        template='M117 plate_name\nM117 {plate_name}\n{if plate_name=="plate_name"}MATCH{endif}\n{my_plate_name}\n'
        specialized=freeze_plate_name(template,'Neutral name')
        self.assertEqual(specialized,'M117 plate_name\nM117 {"Neutral name"}\n{if "Neutral name"=="plate_name"}MATCH{endif}\n{my_plate_name}\n')

    def test_legacy_and_special_characters_remain_string_values(self):
        name='Named {macro} [value] "quoted" \\ path'
        specialized=freeze_plate_name('M117 [plate_name]\nM117 {plate_name}',name)
        literal=json.dumps(name,ensure_ascii=False)
        self.assertEqual(specialized,'M117 {'+literal+'}\nM117 {'+literal+'}')
        self.assertEqual(freeze_plate_name('{"plate_name"}',name),'{"plate_name"}')

    def test_native_scalar_and_vector_encodings_preserve_the_same_macro_value(self):
        name='Neutral {literal} "Q" \\ path'
        logical='M117 {plate_name}\n{if plate_name == '+json.dumps(name)+'}MATCH{endif}'
        stored=_encode_scalar(logical)
        scalar=_freeze_value(stored,name)
        vector=_freeze_value([logical],name)[0]
        self.assertEqual(_decode_scalar(scalar),vector)
        self.assertIn(json.dumps(name),vector)
        self.assertIn(json.dumps(name),_decode_scalar(scalar))

    def test_execution_copy_preserves_originals_and_freezes_project_only_macro(self):
        with tempfile.TemporaryDirectory() as temporary,OwnedWorkspace() as work:
            source=Path(temporary)/'neutral.3mf'
            values={'app_full_name':'AnycubicSlicerNext','app_version':'2.0.0.3','machine_start_gcode':'M117 {plate_name}\nM117 [plate_name]'}
            config='<config><plate><metadata key="plater_id" value="1"/><metadata key="plater_name" value="Neutral name"/><model_instance><metadata key="object_id" value="1"/><metadata key="instance_id" value="0"/></model_instance></plate></config>'
            write_native(source,values=values,model_config=config)
            original=source.read_bytes()
            session=NativeProjectSession(source)
            try:
                result=execution_project(session.context,session.context.snapshot.path,work,plate_id='1')
                self.assertNotEqual(result,session.context.snapshot.path)
                with zipfile.ZipFile(result) as archive:
                    settings=json.loads(archive.read('Metadata/project_settings.config'))
                    self.assertEqual(_decode_scalar(settings['machine_start_gcode']),'M117 {"Neutral name"}\nM117 {"Neutral name"}')
                    self.assertIn(b'key="plater_name" value=""',archive.read('Metadata/model_settings.config'))
                    with zipfile.ZipFile(source) as before:
                        self.assertEqual(archive.read('3D/main.model'),before.read('3D/main.model'))
                self.assertEqual(source.read_bytes(),original)
                self.assertEqual(dict(session.context.plates[0].metadata)['plater_name'],'Neutral name')
            finally:session.close()


if __name__=='__main__':unittest.main()
