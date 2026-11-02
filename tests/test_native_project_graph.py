from __future__ import annotations

from pathlib import Path
import sys
import tempfile
import unittest
import zipfile

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from cooling_tower.native_project.archive import ProjectArchive, ProjectArchiveError
from cooling_tower.native_project.graph import CORE_NAMESPACE, PRODUCTION_NAMESPACE, MODEL_RELATIONSHIP, NativeGraphError, UnsupportedProjectExtension, read_graph


MESH = '<mesh><vertices><vertex x="0" y="0" z="0"/><vertex x="1" y="0" z="0"/><vertex x="0" y="1" z="1"/></vertices><triangles><triangle v1="0" v2="1" v3="2" paint_supports="4" paint_seam="8" paint_color="8"/></triangles></mesh>'


class NativeGraphTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name) / 'neutral.3mf'

    def write(self, objects, build='<item objectid="1"/>', *, attributes='', extra=()):
        text = f'<model xmlns="{CORE_NAMESPACE}" xmlns:p="{PRODUCTION_NAMESPACE}" {attributes}><metadata name="Application">Neutral reference</metadata><resources>{objects}</resources><build>{build}</build></model>'
        with zipfile.ZipFile(self.path, 'w', zipfile.ZIP_DEFLATED) as archive:
            archive.writestr('_rels/.rels', f'<Relationships><Relationship Type="{MODEL_RELATIONSHIP}" Target="/3D/main.model"/></Relationships>')
            archive.writestr('3D/main.model', text)
            for name, data in extra:
                archive.writestr(name, data)

    def read(self):
        with ProjectArchive(self.path) as archive:
            archive.check_relationships()
            return read_graph(archive)

    def test_counts_paint_attributes_units_and_full_instance_transformation(self):
        matrix = '0 1 0 -2 0 0 0 0 1 20 30 40'
        self.write(f'<object id="1">{MESH}</object>', f'<item objectid="1" transform="{matrix}" printable="true"/>', attributes='unit="inch"')
        graph = self.read()
        obj = graph.object('3D/main.model', 1)
        self.assertEqual((obj.vertex_count, obj.triangle_count), (3, 1))
        self.assertEqual((obj.painted_support_triangles, obj.painted_seam_triangles, obj.painted_material_triangles), (1, 1, 1))
        self.assertEqual(obj.bounds_mm, (0., 0., 0., 25.4, 25.4, 25.4))
        self.assertEqual(graph.main.build[0].transform, tuple(map(float, matrix.split())))
        self.assertTrue(graph.main.build[0].printable)

    def test_internal_part_graph_preserves_instances_without_loading_external_sources(self):
        part = f'<model xmlns="{CORE_NAMESPACE}"><resources><object id="8">{MESH}</object></resources></model>'
        self.write('<object id="1"><components><component objectid="8" p:path="Objects/part.model" transform="1 0 0 0 1 0 0 0 1 5 6 7"/></components></object>', '<item objectid="1"/><item objectid="1" printable="0"/>', extra=[('3D/Objects/part.model', part)])
        graph = self.read()
        self.assertEqual(len(graph.documents), 2)
        self.assertEqual(len(graph.main.build), 2)
        self.assertEqual(graph.main.objects[0].components[0].model_path, '3D/Objects/part.model')
        self.assertEqual(graph.main.objects[0].components[0].transform[-3:], (5., 6., 7.))
        self.assertFalse(graph.main.build[1].printable)

    def test_missing_parts_cycles_duplicate_ids_and_wrong_triangle_indices_rejected(self):
        for objects in (
            '<object id="1"><components><component objectid="2"/></components></object>',
            '<object id="1"><components><component objectid="1"/></components></object>',
            f'<object id="1">{MESH}</object><object id="1">{MESH}</object>',
            f'<object id="1">{MESH.replace("v3=\"2\"", "v3=\"5\"")}</object>',
        ):
            with self.subTest(objects=objects):
                self.write(objects)
                with self.assertRaises(NativeGraphError):
                    self.read()

    def test_required_unknown_extension_has_distinct_error(self):
        self.write(f'<object id="1">{MESH}</object>', attributes='xmlns:x="urn:unknown:required" requiredextensions="x"')
        with self.assertRaises(UnsupportedProjectExtension):
            self.read()

    def test_external_part_dtd_nonfinite_values_and_invalid_transforms_rejected(self):
        cases = [
            '<object id="1"><components><component objectid="2" p:path="file:///original.stl"/></components></object>',
            f'<object id="1">{MESH.replace("x=\"1\"", "x=\"nan\"")}</object>',
        ]
        for objects in cases:
            self.write(objects)
            with self.assertRaises((NativeGraphError, ProjectArchiveError)):
                self.read()
        for matrix in ('1 2', 'nan ' * 12):
            self.write(f'<object id="1">{MESH}</object>', f'<item objectid="1" transform="{matrix}"/>')
            with self.assertRaises(NativeGraphError):
                self.read()

    def test_vendor_same_local_names_do_not_replace_core_mesh(self):
        self.write('<object id="1"><x:mesh xmlns:x="urn:vendor"/></object>')
        with self.assertRaises(NativeGraphError):
            self.read()

    def test_unfinished_huge_xml_tokens_are_rejected_during_streaming(self):
        for value in ('<!--' + 'a' * (3*1024*1024) + '-->',
                      '<object id="1" name="' + 'a' * (3*1024*1024) + '">' + MESH + '</object>'):
            self.write(value)
            with self.assertRaisesRegex(NativeGraphError, 'Ressourcengrenze'):
                self.read()


if __name__ == '__main__':
    unittest.main()
