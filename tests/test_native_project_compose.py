from pathlib import Path
import io
import json
import sys
import tempfile
import unittest
import zipfile
from xml.etree import ElementTree as ET
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'src'))
from native_project_fixtures import write_native,VERTICES,FACES
from cooling_tower.native_project.compose import append_tower,restore_basis,PROVENANCE
from cooling_tower.native_project.context import load_context,NativeProjectError
from cooling_tower.native_project.session import NativeProjectSession, project_bounds
from cooling_tower.protected_io import OwnedWorkspace
from cooling_tower.tower.mesh_generator import TriangleMesh

class NativeComposeTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.path=Path(self.temp.name)/'neutral.3mf';write_native(self.path)
        self.session=NativeProjectSession(self.path);self.addCleanup(self.session.close)
        self.work=OwnedWorkspace();self.addCleanup(self.work.close)
        self.mesh=TriangleMesh(VERTICES,FACES,2,4)

    def compose(self):
        return append_tower(self.session.context,'1',self.mesh,workspace=self.work,center_mm=(25,25))

    def test_append_preserves_original_mesh_bytes_settings_and_placement(self):
        composed=self.compose()
        with zipfile.ZipFile(self.path) as before,zipfile.ZipFile(composed.path) as after:
            original=before.read('3D/main.model')
            modified=after.read('3D/main.model')
            start,end=original.index(b'<object '),original.index(b'</object>')+len(b'</object>')
            self.assertIn(original[start:end],modified)
            self.assertIn(b'transform="1 0 0 0 1 0 0 0 1 100 100 0"',modified)
            self.assertEqual(before.read('Metadata/project_settings.config'),after.read('Metadata/project_settings.config'))
        snapshot=self.work.capture(composed.path,name='check.3mf')
        c=load_context(snapshot)
        self.assertEqual(len(c.graph.main.build),2)
        self.assertEqual(c.plates[0].object_count,2)

    def test_brim_is_disabled_only_on_new_tower_and_selected_material_is_retained(self):
        from dataclasses import replace
        context = replace(self.session.context, materials=('PLA', 'PETG'))
        for adapter in ('bambu_studio', 'prusa_slicer'):
            context = replace(context, adapter_id=adapter)
            composed = append_tower(context, '1', self.mesh, workspace=self.work,
                name=adapter+'.3mf', center_mm=(25,25), filament=2)
            path = 'Metadata/Slic3r_PE_model.config' if adapter == 'prusa_slicer' else 'Metadata/model_settings.config'
            with zipfile.ZipFile(composed.path) as archive, zipfile.ZipFile(self.path) as original:
                obj = ET.fromstring(archive.read(path)).findall('object')[-1]
                values = {node.get('key'): node.get('value') for node in obj.findall('metadata')}
                self.assertEqual(values['brim_type'], 'no_brim')
                self.assertEqual(values['brim_width'], '0')
                self.assertEqual(values['extruder'], '2')
                self.assertEqual(archive.read('Metadata/project_settings.config'),
                                 original.read('Metadata/project_settings.config'))

    def test_wall_count_changes_only_the_new_tower_and_is_ignored_for_full_infill(self):
        from dataclasses import replace
        for adapter in ('bambu_studio', 'prusa_slicer'):
            for full in (False, True):
                context = replace(self.session.context, adapter_id=adapter)
                before = self.path.read_bytes()
                composed = append_tower(context, '1', self.mesh, workspace=self.work,
                    name=f'{adapter}-{full}.3mf', center_mm=(25,25), full_infill=full, wall_count=4)
                config = 'Metadata/Slic3r_PE_model.config' if adapter == 'prusa_slicer' else 'Metadata/model_settings.config'
                with zipfile.ZipFile(composed.path) as archive:
                    obj = ET.fromstring(archive.read(config)).findall('object')[-1]
                    values = {node.get('key'): node.get('value') for node in obj.findall('metadata')}
                    key = 'perimeters' if adapter == 'prusa_slicer' else 'wall_loops'
                    self.assertEqual(values.get(key), None if full else '4')
                self.assertEqual(self.path.read_bytes(), before)

    def test_shell_overrides_and_supports_are_written_only_to_the_tower(self):
        from dataclasses import replace
        for adapter in ('bambu_studio', 'prusa_slicer'):
            prusa = adapter == 'prusa_slicer'
            context = replace(self.session.context, adapter_id=adapter)
            composed = append_tower(context, '1', self.mesh, workspace=self.work,
                name=f'{adapter}-shells.3mf', center_mm=(25,25), full_infill=False,
                shell_layers=(('top', 0, False), ('bottom', 12, True)))
            config = 'Metadata/Slic3r_PE_model.config' if prusa else 'Metadata/model_settings.config'
            with zipfile.ZipFile(composed.path) as archive, zipfile.ZipFile(self.path) as original:
                tower = ET.fromstring(archive.read(config)).findall('object')[-1]
                values = {node.get('key'): node.get('value') for node in tower.findall('metadata')}
                count = 'solid_layers' if prusa else 'shell_layers'
                thickness = 'solid_min_thickness' if prusa else 'shell_thickness'
                self.assertEqual(values[f'top_{count}'], '0')
                self.assertEqual(values[f'bottom_{count}'], '12')
                self.assertEqual(values[f'top_{thickness}'], '0')
                self.assertNotIn(f'bottom_{thickness}', values)
                self.assertEqual(values['support_material' if prusa else 'enable_support'], '0')
                self.assertEqual(archive.read('Metadata/project_settings.config'),
                                 original.read('Metadata/project_settings.config'))

    def test_restoration_is_exact_per_original_entry_and_prevents_tower_accumulation(self):
        composed=self.compose()
        second=NativeProjectSession(composed.path);self.addCleanup(second.close)
        self.assertEqual(len(second.context.graph.main.build),1)
        with zipfile.ZipFile(self.path) as a,zipfile.ZipFile(second.context.snapshot.path) as b:
            self.assertEqual(set(a.namelist()),set(b.namelist()))
            for name in a.namelist():self.assertEqual(a.read(name),b.read(name))

    def test_modified_own_export_is_not_silently_stripped_or_reprocessed(self):
        composed=self.compose()
        original=composed.path.read_bytes()
        with zipfile.ZipFile(composed.path,'w') as result,zipfile.ZipFile(io.BytesIO(original)) as before:
            for name in before.namelist():
                result.writestr(name,b'bogus' if name=='Metadata/project_settings.config' else before.read(name))
        with self.assertRaises(NativeProjectError):NativeProjectSession(composed.path)

    def test_repeat_uses_same_basis_and_existing_destination_is_not_truncated(self):
        first=self.compose();before=first.path.read_bytes()
        with self.assertRaises(FileExistsError):self.compose()
        self.assertEqual(first.path.read_bytes(),before)
        second=append_tower(self.session.context,'1',self.mesh,workspace=self.work,name='repeat.3mf',center_mm=(25,25))
        c=load_context(self.work.capture(second.path,name='repeat-check.3mf'))
        self.assertEqual(len(c.graph.main.build),2)

    def test_added_height_profile_and_provenance_parts_have_opc_content_types(self):
        composed=append_tower(self.session.context,'1',self.mesh,workspace=self.work,center_mm=(25,25),
                              layer_print_z=(.2,.3,.4,4.))
        with zipfile.ZipFile(composed.path) as archive:
            profile=archive.read('Metadata/layer_heights_profile.txt')
            self.assertTrue(profile.startswith(b'object_id=2|'))
            manifest=json.loads(archive.read(PROVENANCE))
            types=ET.fromstring(archive.read('[Content_Types].xml'))
            declarations={node.get('PartName'):node.get('ContentType') for node in types}
            self.assertEqual(declarations['/'+PROVENANCE],'application/json')
            self.assertEqual(declarations['/Metadata/layer_heights_profile.txt'],'text/plain')
            for _,patch in manifest['patches']:
                self.assertEqual(declarations['/'+patch],'application/octet-stream')
        restored=restore_basis(composed.path,workspace=self.work)
        with zipfile.ZipFile(self.path) as before,zipfile.ZipFile(restored) as after:
            self.assertEqual({n:before.read(n) for n in before.namelist()},
                             {n:after.read(n) for n in after.namelist()})

    def test_stale_preview_removal_preserves_native_relationship_spelling(self):
        source = self.work.child('native-thumbnails.3mf')
        config = ('<config><object id="1"/><plate><metadata key="plater_id" value="1"/>'
            '<metadata key="thumbnail_file" value="Metadata/selected.png"/>'
            '<model_instance><metadata key="object_id" value="1"/>'
            '<metadata key="instance_id" value="0"/></model_instance></plate></config>')
        write_native(source, model_config=config)
        with zipfile.ZipFile(source) as archive:
            entries = {name: archive.read(name) for name in archive.namelist()}
        original = (b'<?xml version="1.0" encoding="UTF-8"?>\n'
            b'<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">\n'
            b' <Relationship Target="/3D/main.model" Id="main" Type="http://schemas.microsoft.com/3dmanufacturing/2013/01/3dmodel"/>\n'
            b' <Relationship Target="/Metadata/selected.png" Id="selected" Type="thumbnail"/>\n'
            b' <Relationship Target="/Metadata/retained.png" Id="retained" Type="thumbnail"/>\n'
            b'</Relationships>')
        entries['_rels/.rels'] = original
        entries['Metadata/selected.png'] = b'neutral selected preview'
        entries['Metadata/retained.png'] = b'neutral retained preview'
        with zipfile.ZipFile(source, 'w') as archive:
            for name, data in entries.items():archive.writestr(name, data)
        session = NativeProjectSession(source);self.addCleanup(session.close)
        composed = append_tower(session.context, '1', self.mesh, workspace=self.work,
            name='thumbnails-combined.3mf', center_mm=(25,25))
        with zipfile.ZipFile(composed.path) as archive:
            expected = original.replace(
                b'<Relationship Target="/Metadata/selected.png" Id="selected" Type="thumbnail"/>', b'')
            self.assertEqual(archive.read('_rels/.rels'), expected)
            self.assertNotIn('Metadata/selected.png', archive.namelist())
            self.assertEqual(archive.read('Metadata/retained.png'), entries['Metadata/retained.png'])
        restored = restore_basis(composed.path, workspace=self.work)
        with zipfile.ZipFile(restored) as archive:
            self.assertEqual({n:archive.read(n) for n in archive.namelist()},entries)

    def test_constant_native_layers_do_not_gain_an_artificial_adaptive_profile(self):
        composed = append_tower(self.session.context, '1', self.mesh, workspace=self.work,
            center_mm=(25,25), layer_print_z=tuple(.2*(index+1) for index in range(20)))
        with zipfile.ZipFile(composed.path) as archive:
            self.assertNotIn('Metadata/layer_heights_profile.txt',archive.namelist())

    def test_extra_layer_extends_only_the_tower_copy_of_an_embedded_height_curve(self):
        source = self.work.child('adaptive.3mf')
        curve = b'0;0.2;0.2;0.2;1;0.12;4;0.16'
        path = 'Metadata/layer_heights_profile.txt'
        with zipfile.ZipFile(self.path) as original, zipfile.ZipFile(source, 'x') as archive:
            for name in original.namelist():
                archive.writestr(name, original.read(name))
            archive.writestr(path, b'object_id=1|'+curve+b'\n')
        session = NativeProjectSession(source)
        self.addCleanup(session.close)
        mesh = TriangleMesh(tuple((x,y,4.16 if z else 0.) for x,y,z in VERTICES), FACES, 2, 4)
        composed = append_tower(session.context, '1', mesh, workspace=self.work,
            center_mm=(25,25), layer_print_z=(.2,.32,.44,4.,4.16), extra_layer_base_z=4.,
            full_infill=False, solid_foot_top_mm=.44)
        with zipfile.ZipFile(composed.path) as archive:
            self.assertEqual(archive.read(path).splitlines(),
                [b'object_id=1|'+curve, b'object_id=2|'+curve+b';4;0.16;4.16;0.16'])

    def test_solid_foot_has_its_own_range_and_retains_requested_bottom_shells(self):
        from dataclasses import replace
        for adapter in ('bambu_studio', 'prusa_slicer'):
            prusa = adapter == 'prusa_slicer'
            context = replace(self.session.context, adapter_id=adapter)
            composed = append_tower(context, '1', self.mesh, workspace=self.work,
                name=f'{adapter}-solid-foot.3mf', center_mm=(25,25), full_infill=False,
                shell_layers=(('bottom', 1, False),), solid_foot_top_mm=2.4)
            config = 'Metadata/Slic3r_PE_model.config' if prusa else 'Metadata/model_settings.config'
            ranges = ('Metadata/Prusa_Slicer_layer_config_ranges.xml' if prusa
                      else 'Metadata/layer_config_ranges.xml')
            with zipfile.ZipFile(composed.path) as archive:
                obj = ET.fromstring(archive.read(config)).findall('object')[-1]
                values = {node.get('key'): node.get('value') for node in obj.findall('metadata')}
                self.assertEqual(values['bottom_solid_layers' if prusa else 'bottom_shell_layers'], '1')
                region = ET.fromstring(archive.read(ranges)).find('object/range')
                self.assertEqual((region.get('min_z'), region.get('max_z')), ('0', '2.4'))
                options = {node.get('opt_key'): node.text for node in region}
                self.assertEqual(options['fill_density' if prusa else 'sparse_infill_density'], '100%')
                self.assertEqual(options['layer_height'], '0.2')
                self.assertIn(f'PartName="/{ranges}"'.encode(), archive.read('[Content_Types].xml'))

    def test_native_inch_mesh_keeps_millimetre_instance_and_tower_translations(self):
        source = self.work.child('inch.3mf')
        with zipfile.ZipFile(self.path) as original, zipfile.ZipFile(source, 'x') as archive:
            for name in original.namelist():
                data = original.read(name)
                if name.endswith('.model'):
                    data = data.replace(b'<model ', b'<model unit="inch" ', 1)
                archive.writestr(name, data)
        session = NativeProjectSession(source)
        self.addCleanup(session.close)
        bounds = project_bounds(session.context, '1')
        self.assertAlmostEqual(bounds.minimum_x_mm, 100-4*25.4)
        self.assertAlmostEqual(bounds.maximum_x_mm, 100+4*25.4)
        composed = append_tower(session.context, '1', self.mesh, workspace=self.work,
                                name='inch-joint.3mf', center_mm=(25, 25))
        with zipfile.ZipFile(composed.path) as archive:
            model = ET.fromstring(archive.read('3D/main.model'))
        core = {'c': 'http://schemas.microsoft.com/3dmanufacturing/core/2015/02'}
        item = model.findall('c:build/c:item', core)[-1]
        self.assertEqual(tuple(map(float, item.get('transform').split()))[-3:], (25.,25.,0.))
        vertices = model.findall('c:resources/c:object', core)[-1].findall('c:mesh/c:vertices/c:vertex', core)
        self.assertAlmostEqual(max(float(vertex.get('z')) for vertex in vertices)*25.4, 4.)

if __name__=='__main__':unittest.main()
