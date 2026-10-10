import sys
import json
import unittest
from dataclasses import replace
from pathlib import Path
from threading import Event
from unittest.mock import patch
import trimesh
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/"src"))

import test_phase16 as fixture
from cooling_tower.models import GenerationSettings,CalibrationConfig,SourceArtifact
from cooling_tower.preview import OutputMode,PreviewCancelled,StalePreviewError
from cooling_tower.manual.service import ManualGenerationService,ManualExportService,ManualRequest
from cooling_tower.manual.geometry import ManualSettings,initial_draft,move_point,insert_point
from cooling_tower.manual.context import overhang_default,ManualContext
from cooling_tower.services import GCodeAnalysisService
from cooling_tower.calibration.joint_project import build_joint_project
from cooling_tower.file_integrity import sha256_file


class JointAdapter(fixture.FakeAdapter):
    prefer_native_joint_project = True
    def create_joint_project(self,request,source,tower,destination,**kwargs):
        self.project_request=request
        self.tower_hash=sha256_file(tower)
        return build_joint_project(source,tower,destination,**kwargs)


def create_fixture(test,*,joint=False,count=100):
    f=fixture.Phase16Tests("test_01_config_rejects_unbounded_values"); f.setUp()
    test.addCleanup(f.tearDown)
    f.source.write_text(fixture.tower_gcode(layer_count=count,path_size=10,feed=600),encoding="utf-8")
    f.snapshot=GCodeAnalysisService().analyze(f.source)
    artifact=None
    if joint:
        stl=f.root/"source.stl"
        box=trimesh.creation.box(extents=(10,10,count*.2)); box.apply_translation((5,5,count*.1)); box.export(stl)
        artifact=SourceArtifact.capture(stl)
    adapter=(JointAdapter if joint else fixture.FakeAdapter)(fixture.tower_gcode(layer_count=count,feed=600))
    request=ManualRequest(snapshot=f.snapshot,settings=GenerationSettings(),output_mode=OutputMode.STL,
                          calibration_config=CalibrationConfig(maximum_iterations=1),effective_profile=f.profile,
                          adapter=adapter,source_artifact=artifact)
    service=ManualGenerationService(workspace_parent=f.root)
    reference=service.prepare_reference(request)
    d=initial_draft(ManualSettings(),f.snapshot.layers,reference.context.maximum_height_mm,reference.context.key)
    request=replace(request,draft=d,context=reference.context,profile_source_hashes=reference.profile_source_hashes,
                    settings=GenerationSettings(target_layer_time_s=d.settings.target_layer_time_s,layer_time_tolerance_s=d.settings.layer_time_tolerance_s))
    return f,service,reference,request,adapter


class ManualGenerationTests(unittest.TestCase):
    def test_reference_cross_sections_stop_when_cancelled(self):
        f,service,reference,request,adapter=create_fixture(self,joint=True)
        event=Event()
        observed=[]
        def interrupted_reader(source,layers):
            iterator=iter(layers)
            observed.append(next(iterator))
            event.set()
            next(iterator)
            self.fail("Cancelled layer iteration must not continue")
        with patch("cooling_tower.manual.service.load_layer_silhouette",side_effect=interrupted_reader):
            with self.assertRaises(PreviewCancelled):
                service.prepare_reference(request,cancellation_event=event)
        self.assertEqual(len(observed),1)
        self.assertTrue(request.original_source_is_current())

    def test_fixed_geometry_no_automatic_calibration_or_need_shortening(self):
        f,service,reference,request,adapter=create_fixture(self)
        before=request.draft.artifact_payload()
        with patch("cooling_tower.calibration.calibration_service.CalibrationService.calibrate",side_effect=AssertionError("automatic pipeline")):
            result=service.prepare(request)
        self.addCleanup(result.dispose)
        self.assertEqual(len(adapter.requests),1)
        self.assertEqual(request.draft.artifact_payload(),before)
        self.assertEqual(result.scene.tower_height_mm,f.snapshot.maximum_print_z_mm)
        self.assertFalse(result.joint_sliced)
        self.assertFalse(result.manual_evaluation.target_reached)
        self.assertTrue(result.manual_evaluation.layer_times)
        exported=ManualExportService().export(result,request,f.root/"exports")
        self.assertEqual(len(adapter.requests),1)
        self.assertEqual(sha256_file(exported.output_path),result.artifact_sha256)
        report=json.loads(exported.report_path.read_text(encoding="utf-8"))
        self.assertFalse(report["calibrated"])
        self.assertFalse(report["summary"]["calibration_attempted"])
        self.assertEqual(report["manual_evaluation"]["slice_count"],1)
        self.assertIn("Prognose",exported.user_report_path.read_text(encoding="utf-8"))
        self.assertTrue((exported.run_directory/"verification.gcode").is_file())

    def test_native_joint_slice_and_export_preserve_mesh_profile_and_source(self):
        f,service,ref,request,adapter=create_fixture(self,joint=True)
        hashes={p:sha256_file(p) for p in (*f.profile.source_paths,f.source,request.source_artifact.original_path)}
        result=service.prepare(request); self.addCleanup(result.dispose)
        self.assertEqual(len(adapter.requests),1)
        self.assertIsNotNone(result.project_path)
        self.assertTrue(adapter.requests[0].model_path.samefile(result.project_path))
        self.assertTrue(adapter.requests[0].preserve_model_positions)
        self.assertEqual(adapter.requests[0].purpose,"calibration")
        self.assertEqual(adapter.tower_hash,result.artifact_sha256)
        self.assertTrue(result.joint_sliced)
        measured=GCodeAnalysisService().analyze(result.manual_evaluation.gcode_path)
        self.assertAlmostEqual(result.minimum_verified_layer_time_s,measured.minimum_layer_time_s)
        exported=ManualExportService().export(result,request,f.root/"exports")
        self.assertEqual(sha256_file(exported.project_path),result.project_sha256)
        self.assertEqual({p:sha256_file(p) for p in hashes},hashes)
        self.assertIn("Ein gemeinsamer Slice",exported.user_report_path.read_text(encoding="utf-8"))

    def test_shorter_tower_still_evaluates_original_layers_above_it(self):
        f,service,ref,request,adapter=create_fixture(self)
        shorter=move_point(request.draft,"top",z_mm=10)
        request=replace(request,draft=shorter)
        adapter.gcode=fixture.tower_gcode(layer_count=50,feed=600)
        result=service.prepare(request); self.addCleanup(result.dispose)
        self.assertEqual(len(result.manual_evaluation.layer_times),100)
        self.assertAlmostEqual(result.manual_evaluation.layer_times[-1][2],f.snapshot.layers[-1].total_time_s)
        self.assertGreater(result.manual_evaluation.layer_times[-1][3],0)

    def test_unsafe_layer_matching_fails_instead_of_claiming_verification(self):
        f,service,ref,request,adapter=create_fixture(self)
        adapter.gcode=adapter.gcode.replace("G1 Z0.2 ","G1 Z0.3 ")
        with self.assertRaisesRegex(ValueError,"nicht sicher zugeordnet"):service.prepare(request)
        self.assertFalse(list(f.root.glob("manual_tower_*")))

    def test_failure_and_cancellation_leave_no_incomplete_artifacts(self):
        f,service,ref,request,adapter=create_fixture(self)
        adapter.fail=True
        with self.assertRaises(ValueError):service.prepare(request)
        self.assertFalse(list(f.root.glob("manual_tower_*")))
        failure=list(f.root.glob("manual_failed_*/diagnostics/manual_slice.json"))
        self.assertEqual(len(failure),1)
        self.assertFalse(json.loads(failure[0].read_text())["success"])
        self.assertFalse(list(failure[0].parent.rglob("*.stl")))
        event=Event()
        def cancel(request):event.set(); return fixture.FakeAdapter(fixture.tower_gcode()).slice_model(request)
        adapter.slice_model=cancel
        with self.assertRaises(PreviewCancelled):service.prepare(request,cancellation_event=event)
        self.assertFalse(list(f.root.glob("manual_tower_*")))

    def test_profile_or_artifact_tampering_blocks_export(self):
        f,service,ref,request,adapter=create_fixture(self)
        result=service.prepare(request);self.addCleanup(result.dispose)
        f.process.write_text("changed")
        with self.assertRaisesRegex(ValueError,"Slicerprofile"):ManualExportService().export(result,request,f.root/"exports")
        self.assertFalse((f.root/"exports").exists())

    def test_export_previous_request_and_exact_restore_identity(self):
        f,service,ref,request,adapter=create_fixture(self)
        result=service.prepare(request);self.addCleanup(result.dispose)
        changed=replace(request,draft=move_point(request.draft,"base",diameter_mm=8))
        with self.assertRaises(StalePreviewError):ManualExportService().export(result,changed,f.root/"exports")
        restored=replace(changed,draft=request.draft)
        self.assertEqual(restored.signature(),result.request_signature)
        exported=ManualExportService().export(result,request,f.root/"exports")
        self.assertEqual(exported.output_sha256,result.artifact_sha256)

    def test_visuals_and_validation_limits_do_not_require_new_slice(self):
        f,service,ref,request,adapter=create_fixture(self)
        settings=replace(request.draft.settings,overhang_enabled=True,critical_layers_enabled=True,expansion_angle_deg=65)
        changed=replace(request,draft=replace(request.draft,settings=settings),maximum_object_segments=1000)
        self.assertEqual(request.signature(),changed.signature())
        self.assertNotEqual(request.signature(),replace(request,draft=replace(request.draft,settings=replace(settings,circle_segments=48))).signature())

    def test_profile_overhang_default_without_supports_and_zero_fallback(self):
        f,service,ref,request,adapter=create_fixture(self)
        for enabled in ("0","1"):
            profile=replace(f.profile,effective_values={"enable_support":enabled,"support_threshold_angle":["30"]})
            self.assertEqual(overhang_default(profile)[0],60)
        profile=replace(f.profile,effective_values={"support_threshold_angle":"0"})
        self.assertEqual(overhang_default(profile)[0],45)
        self.assertIn("Fallback",overhang_default(profile)[1])

    def test_technical_bed_and_brim_limits_are_independent_of_user_diameters(self):
        f,service,ref,request,adapter=create_fixture(self)
        profile=replace(f.profile,effective_values={**f.profile.effective_values,"printable_height":"15","brim_type":"outer_only","brim_width":"4"})
        context=ManualContext.from_request(replace(request,effective_profile=profile),ref.source_data,"limit")
        self.assertEqual(context.maximum_height_mm,15)
        self.assertEqual(context.brim_width_mm,4)
        d=initial_draft(ManualSettings(),f.snapshot.layers,15,"limit")
        p=context.validate(d)
        self.assertAlmostEqual(p.radius_mm,d.maximum_radius_mm+4)


if __name__ == "__main__":unittest.main()
