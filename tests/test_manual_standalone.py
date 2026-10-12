import json
import math
import sys
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path
from threading import Event
from unittest.mock import Mock

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/"src"))
from cooling_tower.calibration.gcode_integration import _circle_fits_bed
from cooling_tower.manual.geometry import ManualSettings, GeometryError, initial_draft, move_point, create_mesh
from cooling_tower.manual.placement import largest_tower_envelope, maximum_foot_diameter, available_radius
from cooling_tower.manual.service import ManualGenerationService, ManualExportService
from cooling_tower.manual.standalone import StandaloneContext, StandaloneRequest
from cooling_tower.models.calibration import BedBounds, BedGeometry, OccupiedBounds
from cooling_tower.preview import PreviewCancelled
from cooling_tower.file_integrity import sha256_file


class ManualPlacementTests(unittest.TestCase):
    def bed(self,polygon=None,excluded=()):
        polygon=polygon or ((0,0),(220,0),(220,220),(0,220))
        return BedGeometry(BedBounds(min(p[0] for p in polygon),max(p[0] for p in polygon),
                                    min(p[1] for p in polygon),max(p[1] for p in polygon)),polygon,excluded)

    def test_maximum_uses_free_corners_and_exact_object_gap(self):
        bed=self.bed();occupied=OccupiedBounds(90,130,90,130)
        radius,x,y=largest_tower_envelope(bed,occupied)
        optimum=(90*math.sqrt(2)-.3)/(1+math.sqrt(2))
        self.assertAlmostEqual(radius,optimum,delta=.0021)
        self.assertTrue(_circle_fits_bed((x,y),radius,0,bed))
        distance=math.hypot(max(90-x,0,x-130),max(90-y,0,y-130))
        self.assertGreaterEqual(distance-radius,.3-1e-9)
        self.assertEqual(maximum_foot_diameter(bed,occupied,3),math.floor((radius-3)*200)/100)

    def test_polygon_and_exclusions_remain_hard_limits(self):
        bed=self.bed(((0,0),(180,0),(180,80),(100,80),(100,180),(0,180)),
                     (((0,0),(40,0),(40,65),(0,65)),))
        occupied=OccupiedBounds(65,95,100,140)
        radius,x,y=largest_tower_envelope(bed,occupied)
        self.assertTrue(_circle_fits_bed((x,y),radius,0,bed))
        for gx in range(0,181,10):
            for gy in range(0,181,10):
                self.assertGreaterEqual(radius+.0021,available_radius(bed,occupied,gx,gy))

    def test_no_space_and_brim_return_no_positive_diameter(self):
        bed=self.bed()
        self.assertEqual(maximum_foot_diameter(bed,OccupiedBounds(0,220,0,220),0),0)
        self.assertEqual(maximum_foot_diameter(bed,OccupiedBounds(0,10,0,10),111),0)

    def test_object_outside_center_leaves_full_bed_circle(self):
        self.assertEqual(maximum_foot_diameter(self.bed(),OccupiedBounds(0,10,0,10),0),220)

    def test_polygon_search_is_cancelable_and_does_not_cache_partial_results(self):
        from cooling_tower.manual import placement
        bed=self.bed(((0,0),(180,0),(180,80),(100,80),(100,180),(0,180)))
        occupied=OccupiedBounds(66,96,101,141)
        event=Mock();event.is_set.side_effect=[False,True]
        with self.assertRaises(PreviewCancelled):largest_tower_envelope(bed,occupied,event)
        self.assertNotIn((bed,occupied),placement._envelopes)


class StandaloneTowerTests(unittest.TestCase):
    def setUp(self):
        self.owner=tempfile.TemporaryDirectory();self.addCleanup(self.owner.cleanup)
        self.root=Path(self.owner.name)
        self.context=StandaloneContext("free-test")
        self.draft=initial_draft(replace(ManualSettings(),maximum_foot_diameter_mm=250,
                    layer_snap_enabled=False,critical_layers_enabled=False),self.context.layers,500,self.context.key,standalone=True)
        self.preview_service=Mock()
        self.preview_service._source_data.side_effect=AssertionError("Standalone must not read original data")
        self.service=ManualGenerationService(self.preview_service,self.root)

    def test_extreme_geometry_export_has_only_stl_and_truthful_reports_without_slice(self):
        draft=move_point(self.draft,"top",z_mm=500)
        draft=move_point(draft,"foot",diameter_mm=250)
        request=StandaloneRequest(draft,self.context)
        preview=self.service.prepare(request);self.addCleanup(preview.dispose)
        self.preview_service._source_data.assert_not_called()
        self.assertIsNone(preview.manual_evaluation)
        self.assertEqual(preview.scene.object_segments,())
        self.assertEqual(preview.scene.tower_center_xy_mm,(0,0))
        self.assertIsNone(preview.project_path)
        self.assertIsNone(preview.minimum_verified_layer_time_s)
        result=ManualExportService().export(preview,request,self.root/"exports")
        self.assertEqual({p.name for p in result.run_directory.iterdir()},
                         {"tower.stl","export_report.json","export_summary.txt"})
        self.assertEqual(sha256_file(result.output_path),preview.artifact_sha256)
        report=json.loads(result.report_path.read_text(encoding="utf-8"))
        self.assertFalse(report["slicing_performed"])
        self.assertFalse(report["printer_constraints_checked"])
        self.assertEqual(report["slice_count"],0)
        self.assertIn("keine 3MF",result.user_report_path.read_text(encoding="utf-8"))
        # STL triangles are exactly those of the drawn domain mesh, without smoothing.
        import trimesh
        mesh=trimesh.load(result.output_path,force="mesh",process=False)
        self.assertEqual(len(mesh.faces),len(create_mesh(draft).faces))
        self.assertAlmostEqual(mesh.bounds[1,2],500)
        self.assertFalse((mesh.area_faces<=0).any())

    def test_free_limits_reject_oversize_and_wrong_context(self):
        for setting in ("minimum_diameter_mm","maximum_diameter_mm","maximum_foot_diameter_mm"):
            with self.subTest(setting=setting),self.assertRaises(GeometryError):
                self.context.validate(replace(self.draft,settings=replace(self.draft.settings,**{setting:251})))
        with self.assertRaises(GeometryError):move_point(self.draft,"top",z_mm=501)
        with self.assertRaises(GeometryError):replace(self.context,key="wrong").validate(self.draft)

    def test_stale_or_modified_stl_cannot_export(self):
        request=StandaloneRequest(self.draft,self.context)
        preview=self.service.prepare(request);self.addCleanup(preview.dispose)
        with self.assertRaises(ValueError):
            ManualExportService().export(preview,replace(request,draft=move_point(self.draft,"top",z_mm=200)),self.root/"exports")
        preview.artifact_path.write_bytes(b"corrupted")
        with self.assertRaises(ValueError):ManualExportService().export(preview,request,self.root/"exports")
        self.assertFalse((self.root/"exports").exists())

    def test_cancelled_generation_creates_no_artifacts(self):
        event=Event();event.set()
        with self.assertRaises(PreviewCancelled):
            self.service.prepare(StandaloneRequest(self.draft,self.context),cancellation_event=event)
        self.assertEqual(list(self.root.iterdir()),[])


if __name__=="__main__":unittest.main()
