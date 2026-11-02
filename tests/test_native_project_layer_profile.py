from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace
import sys
import tempfile
import unittest
import zipfile

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
from native_project_fixtures import write_native
from cooling_tower.native_project.layer_profile import encode_tower_profile, inherited_tower_profile, inherited_height_inputs, tower_geometry_height, tower_model_index, uses_embedded_layer_schedule, object_print_layer_indices, object_geometry_layers
from cooling_tower.native_project.session import NativeProjectSession


class NativeLayerProfileTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        path = Path(temporary.name) / 'neutral.3mf'
        write_native(path)
        session = NativeProjectSession(path)
        self.addCleanup(session.close)
        self.context = session.context

    def test_native_steps_keep_first_height_and_independent_variable_layers(self):
        data = encode_tower_profile(self.context, (.2, .3, .45, .55), .55)
        self.assertTrue(data.startswith(b'object_id=2|'))
        pairs = list(zip(*[iter(map(float, data.decode().split('|')[1].split(';')))] * 2))
        self.assertEqual(pairs[0], (0., .2))
        self.assertEqual(pairs[-1], (.55, .1))
        # Native interpolation inside each interval must yield that interval's
        # requested height. A slope between neighbouring layers would not.
        for left, right in zip(pairs[::2], pairs[1::2]):
            self.assertEqual(left[1], right[1])
            self.assertAlmostEqual(right[0] - left[0], left[1])

    def test_profile_index_counts_objects_instead_of_resource_ids_or_instances(self):
        main = self.context.graph.main
        obj = replace(main.objects[0], object_id=42)
        instances = tuple(replace(main.build[0], object_id=42) for _ in range(3))
        main = replace(main, objects=(obj,), resource_ids=(42,), build=instances)
        graph = replace(self.context.graph, documents=(main,))
        context = replace(self.context, graph=graph)
        self.assertEqual(tower_model_index(context), 2)
        self.assertEqual(tower_model_index(replace(context, adapter_id='prusa_slicer')), 2)

    def test_nonfinite_duplicate_or_descending_layers_are_rejected(self):
        for values in ((), (.2, .2), (.2, .1), (.2, float('nan')), (.2, 1.1)):
            with self.subTest(values=values), self.assertRaises(ValueError):
                encode_tower_profile(self.context, values, 1.)

    def test_single_layer_remains_readable_by_native_profile_reader(self):
        data = encode_tower_profile(self.context, (.2,), .2)
        self.assertEqual(len(data.decode().split('|')[1].split(';')), 6)

    def test_prusa_reuses_exact_selected_native_curve_for_wipe_tower(self):
        context = replace(self.context, adapter_id='prusa_slicer')
        curve = b'0;0.200000;0.2;0.2;2;0.1;4;0.15'
        self.assertEqual(inherited_tower_profile(context, '1', b'object_id=1|' + curve, 4.),
                         b'object_id=2|' + curve + b'\n')
        for profile, top in ((b'object_id=3|' + curve, 4.),
                             (b'object_id=1|' + curve, 5.),
                             (b'object_id=1|0;0.2;nan;0.2;4;0.1', 4.)):
            with self.subTest(profile=profile, top=top):
                self.assertIsNone(inherited_tower_profile(context, '1', profile, top))
        self.assertEqual(inherited_tower_profile(self.context, '1', b'object_id=1|' + curve, 4.),
                         b'object_id=2|' + curve + b'\n')

    def test_embedded_first_and_regular_heights_need_no_adaptive_override(self):
        context = replace(self.context, initial_layer_height=.25, layer_height=.18)
        self.assertTrue(uses_embedded_layer_schedule(context, (.25,.43,.61,.79)))
        for values in ((), (.25,.43,.60,.79), (.2,.38,.56), (.25,float('nan'))):
            with self.subTest(values=values):
                self.assertFalse(uses_embedded_layer_schedule(context,values))

    def test_native_model_top_can_exceed_last_rounded_print_height(self):
        path = self.context.snapshot.path.parent / 'adaptive.3mf'
        write_native(path)
        with zipfile.ZipFile(path, 'a') as archive:
            archive.writestr('Metadata/layer_heights_profile.txt',
                            b'object_id=1|0;0.2;0.2;0.2;2;0.1;4;0.2\n')
        session = NativeProjectSession(path)
        self.addCleanup(session.close)
        layer = SimpleNamespace(z_mm=3.93383, height_mm=.1948)
        self.assertEqual(tower_geometry_height(session.context, '1', (layer,)), 4.)
        layer = SimpleNamespace(z_mm=3.5, height_mm=.2)
        self.assertEqual(tower_geometry_height(session.context, '1', (layer,)), 3.5)

    def test_prime_tower_inherits_heights_without_original_wall_or_material_overrides(self):
        from cooling_tower.native_project.context import NativeSettings
        from cooling_tower.native_project.archive import parse_xml
        config = b'<config><object id="1"><metadata key="layer_height" value="0.1"/><metadata key="wall_loops" value="5"/></object></config>'
        ranges = b'<objects><object id="1"><range min_z="1" max_z="3"><option opt_key="layer_height">0.1</option><option opt_key="extruder">2</option><option opt_key="wall_loops">5</option></range></object></objects>'
        for adapter, key in (('prusa_slicer', 'wipe_tower'), ('bambu_studio', 'enable_prime_tower')):
            context = replace(self.context, adapter_id=adapter,
                              settings=NativeSettings(((key, 'true'),)))
            values, fragment = inherited_height_inputs(context, '1', config, ranges)
            self.assertEqual(values, {'layer_height': '0.1'})
            obj = parse_xml(fragment)
            self.assertEqual(obj.get('id'), '2')
            self.assertEqual(obj.find('range').attrib, {'min_z': '1', 'max_z': '3'})
            self.assertEqual({node.get('opt_key'): node.text for node in obj.findall('.//option')},
                             {'layer_height': '0.1', 'extruder': '0'})
            context = replace(context, settings=NativeSettings(((key, 'false'),)))
            self.assertEqual(inherited_height_inputs(context, '1', config, ranges), ({}, b''))

    def test_independent_support_heights_do_not_become_object_layers(self):
        path = self.context.snapshot.path.parent / 'support-grid.gcode'
        path.write_text('G90\nM83\n; FEATURE: Outer wall\nG1 Z0.2\nG1 X1 E1 F600\n'
                        '; FEATURE: Support interface\nG1 Z0.273077\nG1 X2 E1\n'
                        '; TYPE:External perimeter\nG1 Z0.4\nG1 X3 E1\n')
        layers = tuple(SimpleNamespace(index=i, first_deposition_line=start, end_line=end)
                       for i,start,end in ((1,5,5),(2,8,8),(3,11,11)))
        self.assertEqual(object_print_layer_indices(path, layers), frozenset((1,3)))

    def test_raft_lift_uses_object_height_after_interface_height_in_same_interval(self):
        from test_phase2 import make_layer
        path = self.context.snapshot.path.parent / 'raft-grid.gcode'
        path.write_text('G90\nM83\n;HEIGHT:0.2\n;TYPE:Prime tower\nG1 Z0.2\nG1 X1 E1 F600\n'
                        ';LAYER_CHANGE\n;Z:1.1\n;HEIGHT:0.3\n;TYPE:Support interface\nG1 Z1.1\nG1 X2 E1\n'
                        ';HEIGHT:0.2\n;TYPE:Outer wall\nG1 X3 E1\n;LAYER_CHANGE\n;Z:1.3\n;HEIGHT:0.2\nG1 Z1.3\nG1 X4 E1\n')
        layers = tuple(replace(make_layer(i, total_time_s=2., deposition_time_s=1., deposition_path_mm=10.),
                               z_mm=z, first_deposition_line=first, end_line=end)
                       for i,z,first,end in ((1,.2,6,6),(2,1.1,12,15),(3,1.3,20,20)))
        result = object_geometry_layers(SimpleNamespace(settings={'raft_layers':'3'}),path,layers)
        self.assertEqual(tuple(layer.index for layer in result),(2,3))
        for layer,z in zip(result,(.2,.4)):
            self.assertAlmostEqual(layer.z_mm,z)
            self.assertAlmostEqual(layer.height_mm,.2)
        self.assertEqual(layers[1].z_mm,1.1)

    def test_prusa_machine_z_offset_does_not_increase_model_height(self):
        from test_phase2 import make_layer
        path = self.context.snapshot.path.parent / 'prusa-offset.gcode'
        path.write_text('G90\nM83\n;TYPE:External perimeter\n;HEIGHT:0.2\n'
                        'G1 Z0.3 F600\nG1 X1 E1\nG1 Z0.5\nG1 X2 E1\n')
        layers = tuple(replace(make_layer(i,total_time_s=2.,deposition_time_s=1.,deposition_path_mm=10.),
                               z_mm=z,first_deposition_line=line,end_line=line)
                       for i,z,line in ((1,.3,6),(2,.5,8)))
        context = SimpleNamespace(adapter_id='prusa_slicer',settings={'z_offset':'0.1'})
        result = object_geometry_layers(context,path,layers)
        self.assertAlmostEqual(result[-1].z_mm,.4)


if __name__ == '__main__':
    unittest.main()
