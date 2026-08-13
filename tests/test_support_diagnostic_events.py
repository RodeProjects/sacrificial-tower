from __future__ import annotations

import json
import os
import sys
import tempfile
import unittest
import zipfile
from pathlib import Path
from types import SimpleNamespace


PROJECT_ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = PROJECT_ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from cooling_tower.application import _record_unhandled_exception
from cooling_tower.diagnostics import (
    DiagnosticJournal,
    set_current_diagnostic_journal,
)
from cooling_tower.gui.preview_worker import PreviewWorker
from cooling_tower.gui.profile_worker import ProfileMatchingWorker
from cooling_tower.gui.slicer_worker import SlicerDiscoveryWorker
from cooling_tower.support_report import SupportReportService


class _DiagnosticCapture:
    def __init__(self) -> None:
        self.events: list[tuple[str, dict[str, object]]] = []

    def __call__(self, event: str, **details: object) -> None:
        self.events.append((event, details))

    def details(self, event: str) -> dict[str, object]:
        return next(details for name, details in self.events if name == event)


class SupportDiagnosticEventTests(unittest.TestCase):
    def test_slicer_and_profile_regular_results_are_explicit(self) -> None:
        slicer_result = SimpleNamespace(
            installations=(),
            recommended=None,
            gui_state=SimpleNamespace(value="not_found"),
            diagnostics=("candidate rejected",),
        )
        slicer_service = SimpleNamespace(
            discover_installations=lambda _source, force=False: slicer_result
        )
        slicer_capture = _DiagnosticCapture()
        slicer_worker = SlicerDiscoveryWorker(1, slicer_service, None)
        slicer_worker.set_diagnostic_callback(slicer_capture)
        slicer_worker.run()

        slicer_finished = slicer_capture.details("slicer_discovery_finished")
        self.assertEqual(slicer_finished["outcome"], "success")
        self.assertEqual(slicer_finished["result_code"], "slicer_not_found")
        self.assertEqual(slicer_finished["installation_count"], 0)
        self.assertEqual(slicer_finished["diagnostic_count"], 1)

        exclusion = SimpleNamespace(code=SimpleNamespace(value="nozzle_mismatch"))
        profile_result = SimpleNamespace(
            state=SimpleNamespace(value="unavailable"),
            selected=None,
            candidates=(SimpleNamespace(exclusions=(exclusion,)),),
            machine_options=(object(),),
            process_options=(),
            filament_options=(object(), object()),
            requires_confirmation=False,
            user_confirmed=False,
            can_use_stl_mode=False,
            can_use_gcode_mode=False,
            profiles_filtered=True,
        )
        profile_service = SimpleNamespace(
            match=lambda *_args, **_kwargs: profile_result
        )
        profile_capture = _DiagnosticCapture()
        profile_worker = ProfileMatchingWorker(
            2,
            profile_service,
            object(),
            object(),
            object(),
        )
        profile_worker.set_diagnostic_callback(profile_capture)
        profile_worker.run()

        profile_finished = profile_capture.details("profile_matching_finished")
        self.assertEqual(profile_finished["outcome"], "success")
        self.assertEqual(profile_finished["result_code"], "profile_unavailable")
        self.assertEqual(profile_finished["machine_profile_status"], "available")
        self.assertEqual(profile_finished["process_profile_status"], "unavailable")
        self.assertEqual(profile_finished["filament_profile_status"], "available")
        self.assertEqual(
            profile_finished["profile_exclusion_codes"],
            ["nozzle_mismatch"],
        )

    def test_preview_success_includes_useful_counts(self) -> None:
        failure = SimpleNamespace(code=SimpleNamespace(value="iteration_limit"))
        calibration = SimpleNamespace(
            state=SimpleNamespace(value="limit_reached"),
            iterations=(object(), object()),
            failures=(failure,),
        )
        preview_result = SimpleNamespace(
            output_mode=SimpleNamespace(value="stl"),
            calibrated=True,
            generation_kind="slicer_calibrated",
            slicer_optimized=True,
            scene=SimpleNamespace(
                displayed_segment_count=900,
                source_segment_count=1500,
            ),
            warnings=("technical warning",),
            calibration=calibration,
        )
        preview_request = SimpleNamespace(
            output_mode=SimpleNamespace(value="stl"),
            calibration_config=SimpleNamespace(
                mode=SimpleNamespace(value="stl"),
                maximum_iterations=5,
            ),
            adapter=object(),
            effective_profile=object(),
        )
        preview_service = SimpleNamespace(
            prepare=lambda *_args, **_kwargs: preview_result
        )
        preview_capture = _DiagnosticCapture()
        preview_worker = PreviewWorker(
            4,
            preview_request,
            preview_service,
        )
        preview_worker.set_diagnostic_callback(preview_capture)
        preview_worker.run()
        preview_finished = preview_capture.details("preview_generation_finished")
        self.assertEqual(preview_finished["outcome"], "success")
        self.assertEqual(
            preview_finished["result_code"],
            "preview_generation_succeeded",
        )
        self.assertEqual(preview_finished["displayed_segment_count"], 900)
        self.assertEqual(preview_finished["calibration_state"], "limit_reached")
        self.assertEqual(
            preview_finished["calibration_failure_codes"],
            ["iteration_limit"],
        )

    def test_new_event_fields_reach_sanitized_bundle(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            journal = DiagnosticJournal(root / "logs" / "background_jobs.jsonl")
            journal.start_session()
            journal.record(
                "profile_matching_finished",
                diagnostic_event_schema_version=1,
                outcome="success",
                result_code="profile_matched",
                profile_state="matched",
                machine_profile_status="selected",
                process_profile_status="selected",
                filament_profile_status="selected",
                source_path="C:\\Private\\customer.gcode",
            )
            service = SupportReportService(root, diagnostic_journal=journal)
            bundle = service.create_bundle(
                title="Profilproblem",
                description="Beschreibung",
            )

            with zipfile.ZipFile(bundle.path) as archive:
                diagnostics = archive.read("diagnose.log").decode("utf-8")

        self.assertIn('"result_code": "profile_matched"', diagnostics)
        self.assertIn('"machine_profile_status": "selected"', diagnostics)
        self.assertIn('"outcome": "success"', diagnostics)
        self.assertNotIn("source_path", diagnostics)
        self.assertNotIn("customer.gcode", diagnostics)

    def test_unhandled_exception_records_only_safe_classification(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            journal = DiagnosticJournal(root / "logs" / "background_jobs.jsonl")
            journal.start_session()
            set_current_diagnostic_journal(journal)
            try:
                _record_unhandled_exception(
                    "main_thread_exception",
                    PermissionError("C:\\Private\\customer.gcode"),
                )
            finally:
                set_current_diagnostic_journal(None)
            entries = [
                json.loads(line)
                for line in journal.log_path.read_text(
                    encoding="utf-8"
                ).splitlines()
            ]

        failure = next(
            entry
            for entry in entries
            if entry["event"] == "unhandled_python_exception"
        )
        self.assertEqual(failure["outcome"], "failed")
        self.assertEqual(
            failure["error_code"],
            "main_thread_exception_access_denied",
        )
        self.assertEqual(failure["error_type"], "PermissionError")
        self.assertNotIn("customer", json.dumps(failure).casefold())


if __name__ == "__main__":
    unittest.main()
