"""Opt-in fixed-form acceptance using installed adapters and real source data."""
import json
import os
import sys
import subprocess
import time
import unittest
from dataclasses import replace
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/"src"))
sys.path.insert(0,str(Path(__file__).resolve().parent))
os.environ.setdefault("QT_QPA_PLATFORM","offscreen")

from PySide6.QtWidgets import QApplication
from PySide6.QtCore import QObject,Slot
from PySide6.QtGui import QFont,QFontDatabase
from cooling_tower.slicers import (BambuStudioAdapter,AnycubicSlicerNextAdapter,
                                  ProfileMatchingService,ProfileMatchingContext,ProfileInventoryService,ProfileMappingStore,ProfileConfirmation)
from cooling_tower.services import GCodeAnalysisService,StlValidationService,SourcePreSliceService
from cooling_tower.models import GenerationSettings,CalibrationConfig
from cooling_tower.preview import PreviewService,OutputMode
from cooling_tower.manual.service import ManualRequest,ManualGenerationService,ManualExportService
from cooling_tower.manual.geometry import ManualSettings,initial_draft,insert_point,move_point
from cooling_tower.gui.main_window import MainWindow
from cooling_tower.gui.generation_session import GenerationMode
from cooling_tower.gui.background_jobs import BackgroundJobManager,JobKind
from cooling_tower.gui.manual_worker import ManualWorker
from cooling_tower.file_integrity import sha256_file
from slicer_acceptance_support import require_slicer_installation

ROOT=Path(__file__).resolve().parents[1]


class AcceptanceSignals(QObject):
    """Receive real worker results on the GUI thread, like the controller."""
    def __init__(self,name):
        super().__init__()
        self.name,self.result,self.error=name,None,""

    @Slot(int,object)
    def succeeded(self,request_id,result):self.result=result

    @Slot(int,str,str)
    def failed(self,request_id,message,details):self.error=message+"\n"+details

    @Slot(int,int,str)
    def progress(self,request_id,percent,status):print(f"{self.name}: {percent}% {status}",flush=True)


@unittest.skipUnless(os.environ.get("COOLING_TOWER_RUN_REAL_SLICER_TESTS")=="1","Real manual slicer acceptance is opt-in.")
class RealManualGenerationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        if not os.environ.get("COOLING_TOWER_MANUAL_ACCEPTANCE_CHILD"):
            return
        cls.app=QApplication.instance() or QApplication([])
        # This class opens/closes windows between synchronous CLI runs. Keep
        # the shared Qt dispatcher alive for the next QProcess transport.
        cls.app.setQuitOnLastWindowClosed(False)
        # Windows' offscreen platform does not enumerate system fonts.
        QFontDatabase.addApplicationFont(r"C:\Windows\Fonts\segoeui.ttf")
        QFontDatabase.addApplicationFont(r"C:\Windows\Fonts\seguisym.ttf")
        cls.app.setFont(QFont("Segoe UI",10))

    def run_isolated_adapter(self,adapter,name,test_name):
        """Give each installed product a fresh Python/Qt process; never retry."""
        installation=require_slicer_installation(adapter)
        if os.environ.get("COOLING_TOWER_MANUAL_ACCEPTANCE_CHILD")==name:
            return self.run_adapter(adapter,installation,name)
        environment=dict(os.environ,COOLING_TOWER_MANUAL_ACCEPTANCE_CHILD=name,PYTHONIOENCODING="utf-8")
        outcome=subprocess.run((sys.executable,str(Path(__file__).resolve()),f"RealManualGenerationTests.{test_name}","-q"),
                               cwd=ROOT,env=environment,capture_output=True,text=True,encoding="utf-8",errors="replace",timeout=420)
        print(outcome.stdout,flush=True)
        self.assertEqual(outcome.returncode,0,outcome.stderr+outcome.stdout[-5000:])

    def run_adapter(self,adapter,installation,name):
        executable=installation.executable_path
        root=ROOT/".tmp"/f"manual_acceptance_{name}"
        root.mkdir(parents=True,exist_ok=True)
        source=ROOT/"input"/"Test-STL (manifold).stl"
        validation=StlValidationService().validate(source)
        self.assertTrue(validation.valid,validation.technical_summary)
        matching=ProfileMatchingService(inventory_service=ProfileInventoryService(root/"inventory.json"),mapping_store=ProfileMappingStore(root/"mappings.json"))
        match=matching.match(ProfileMatchingContext.from_stl(validation.source_artifact),installation,adapter,force_inventory=True)
        self.assertIsNotNone(match.selected,match.message)
        confirmation=ProfileConfirmation.from_result(match,validation.source_artifact)
        confirmed=matching.confirm(match)
        profile=confirmed.selected.effective_profile
        hashes={path:sha256_file(path) for path in (*profile.source_paths,source)}
        analysis=GCodeAnalysisService()
        preslice=SourcePreSliceService(analysis_service=analysis,workspace_parent=root/"preslice",diagnostics_root=root/"preslice_diagnostics").run(
            stl_validation=validation,profile_match=confirmed,confirmation=confirmation,adapter=adapter)
        self.addCleanup(preslice.cleanup)
        request=ManualRequest(snapshot=preslice.analysis_snapshot,settings=GenerationSettings(),output_mode=OutputMode.STL,
                              calibration_config=CalibrationConfig(maximum_iterations=1),adapter=adapter,effective_profile=profile,
                              source_artifact=validation.source_artifact,prepared_analysis_source=preslice.prepared_source,
                              prepared_source_data=preslice.preview_source_data,profile_fingerprint=preslice.prepared_source.effective_profile_fingerprint,
                              slicer_identity_key=installation.identity_key)
        service=ManualGenerationService(PreviewService(),root/"generation",analysis)
        reference=service.prepare_reference(request)
        draft=initial_draft(ManualSettings(),request.snapshot.layers,reference.context.maximum_height_mm,reference.context.key)
        # Multiple deliberately authored widenings and contractions.
        lower=draft.points[1].position.z_mm
        span=draft.height_mm-lower
        for fraction,width in ((.12,12),(.24,6),(.38,18),(.53,7),(.67,15),(.82,6)):
            draft,identity=insert_point(draft,lower+span*fraction)
            draft=move_point(draft,identity,diameter_mm=width)
        request=replace(request,draft=draft,context=reference.context,profile_source_hashes=reference.profile_source_hashes)
        before=request.draft.artifact_payload()
        # Exercise the production GUI transport, including the worker-owned
        # Qt dispatcher and Event, rather than slicing inside the GUI thread.
        receiver=AcceptanceSignals(name)
        manager=BackgroundJobManager(self.app)
        self.addCleanup(manager.shutdown)
        worker=ManualWorker(-1,request,service)
        worker.progress.connect(receiver.progress)
        worker.succeeded.connect(receiver.succeeded)
        worker.failed.connect(receiver.failed)
        manager.start_job(kind=JobKind.PREVIEW,request_id=-1,worker=worker)
        deadline=time.monotonic()+400
        while manager.active_jobs() and time.monotonic()<deadline:
            self.app.processEvents();time.sleep(.01)
        self.assertFalse(manager.active_jobs(),"Real manual worker was not released")
        self.assertFalse(receiver.error,receiver.error)
        result=receiver.result
        self.assertIsNotNone(result,"No complete real manual result")
        self.addCleanup(result.dispose)
        self.assertTrue(result.joint_sliced)
        self.assertIsNotNone(result.project_path)
        self.assertEqual(request.draft.artifact_payload(),before)
        exported=ManualExportService().export(result,request,root/"exports")
        self.assertEqual(exported.output_sha256,result.artifact_sha256)
        self.assertEqual(sha256_file(exported.project_path),result.project_sha256)
        self.assertEqual({p:sha256_file(p) for p in hashes},hashes)
        window=MainWindow(user_data_root=root/"editor_app",enable_update_check=False,enable_startup_slicer_discovery=False)
        self.addCleanup(window.close)
        window.analysis_snapshot=request.snapshot
        window.source_artifact=request.source_artifact
        window.prepared_analysis_source=preslice.prepared_source
        window.source_preslice_result=preslice
        window.profile_match_result=confirmed
        window.slicer_service.adapter_for=lambda _:adapter
        controller=window.manual_controller
        bound=controller.build_request()
        controller.reference=replace(reference,context=replace(reference.context,key=bound.signature()))
        controller._reference_request=bound
        panel=window.manual_generation_panel
        panel.initialize(controller.reference)
        panel.commit(replace(draft,context_key=bound.signature()))
        window.output_root_edit.setText(str(root/"exports"))
        window.workflow.set_slicer_step_visible(True)
        window.workflow.source_validation_succeeded(str(source),analysis_complete=True)
        window.workflow.slicer_succeeded(adapter.product_name)
        window.workflow.complete_preparation()
        window.select_generation_mode(GenerationMode.MANUAL)
        window.resize(1450,1000);window.show()
        for _ in range(8):self.app.processEvents()
        frames=[]
        for i in range(30):
            start=time.perf_counter()
            panel.move("base",5+(i%10)*.1,lower)
            panel.canvas.grab()
            frames.append((time.perf_counter()-start)*1000)
        spatial_start=time.perf_counter()
        panel.canvas.set_view("three_quarter");panel.canvas.grab()
        spatial_ms=(time.perf_counter()-spatial_start)*1000
        deadline=time.monotonic()+20
        while (panel.canvas._render_proxy or panel.canvas._render_job is not None or panel.canvas._render_timer.isActive()) and time.monotonic()<deadline:
            self.app.processEvents();time.sleep(.01)
        self.assertFalse(panel.canvas._render_proxy)
        spatial_ready_ms=(time.perf_counter()-spatial_start)*1000
        panel.canvas.set_view("side")
        self.assertTrue(window.grab().save(str(root/"editor_side.png")))
        panel.canvas.set_view("front");self.app.processEvents()
        self.assertTrue(window.grab().save(str(root/"editor_front.png")))
        panel.canvas.set_view("three_quarter");self.app.processEvents()
        panel.canvas.grab()
        deadline=time.monotonic()+20
        while (panel.canvas._render_proxy or panel.canvas._render_job is not None or panel.canvas._render_timer.isActive()) and time.monotonic()<deadline:
            self.app.processEvents();time.sleep(.01)
        self.assertTrue(window.grab().save(str(root/"editor_three_quarter.png")))
        panel.canvas.set_view("side");window.resize(720,1100)
        for _ in range(8):self.app.processEvents()
        window.settings_scroll.verticalScrollBar().setValue(window.settings_scroll.verticalScrollBar().maximum())
        self.app.processEvents()
        self.assertTrue(window.grab().save(str(root/"editor_small.png")))
        self.assertEqual({p:sha256_file(p) for p in hashes},hashes)
        record={"adapter":name,"object_layers":request.snapshot.layer_count,"original_preview_segments":len(reference.source_data.object_segments),
                "profile_points":len(draft.points),"frames":len(frames),"mean_ms":sum(frames)/len(frames),"maximum_ms":max(frames),
                "first_spatial_frame_ms":spatial_ms,
                "complete_spatial_image_ready_ms":spatial_ready_ms,
                "minimum_verified_time_s":result.minimum_verified_layer_time_s,
                "export_directory":str(exported.run_directory)}
        (root/"acceptance.json").write_text(json.dumps(record,indent=2),encoding="utf-8")
        print(json.dumps(record),flush=True)

    def test_bambu_fixed_joint_form(self):
        self.run_isolated_adapter(BambuStudioAdapter(),"bambu",self._testMethodName)

    def test_anycubic_fixed_joint_form(self):
        self.run_isolated_adapter(AnycubicSlicerNextAdapter(),"anycubic",self._testMethodName)


if __name__=="__main__":unittest.main()
