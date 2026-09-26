from dataclasses import replace
from types import SimpleNamespace
import json
import os
from pathlib import Path
import sys
import unittest
from unittest.mock import PropertyMock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication
from cooling_tower.calibration.slice_evaluator import build_calibration_profile
from cooling_tower.gui.main_window import MainWindow
from cooling_tower.gui.preview_dialog import PreviewState
from cooling_tower.persistence import PreSliceCache
from cooling_tower.slicers import ProfileConfirmation
from cooling_tower.slicers.draft_shield import (
    draft_shield_active, draft_shield_source, with_simulated_draft_shield_disabled,
)
from cooling_tower.slicers.profile_models import stable_json_fingerprint
import test_source_preslice as preslice_tests


class DraftShieldTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.fixture = preslice_tests.SourcePreSliceServiceTests()
        self.fixture.setUp()
        f = self.fixture
        installation = replace(f.installation, adapter_id="anycubic_slicer_next")
        values = {
            **f.match.selected.effective_profile.effective_values,
            "draft_shield": "enabled",
            "skirt_loops": "3",
            "skirt_height": "99",
        }
        f.process.path.write_text(
            json.dumps({"name": "process", **values}), encoding="utf-8"
        )
        profile = replace(
            f.match.selected.effective_profile,
            installation=installation,
            effective_values=values,
        )
        bundle = replace(f.match.selected, effective_profile=profile)
        f.match = replace(
            f.match,
            execution_slicer=installation,
            selected=bundle,
            effective_profile_fingerprint=stable_json_fingerprint(values),
        )
        f.confirmation = ProfileConfirmation.from_result(
            f.match, f.validation.source_artifact
        )
        self.originals = {path: path.read_bytes() for path in profile.source_paths}

    def tearDown(self):
        for path, data in self.originals.items():
            self.assertEqual(path.read_bytes(), data)
        self.fixture.tearDown()

    def test_detects_direct_and_tall_skirt_but_not_normal_skirt(self):
        self.assertTrue(draft_shield_active({"draft_shield": "enabled"}))
        self.assertTrue(draft_shield_active({"skirt_loops": "2", "skirt_height": "4"}))
        self.assertFalse(draft_shield_active({"skirt_loops": "2", "skirt_height": "1"}))
        self.assertFalse(draft_shield_active({"skirt_loops": "0", "skirt_height": "99"}))
        source = draft_shield_source(self.fixture.match.selected.effective_profile)
        self.assertEqual((source.role, source.profile_name), ("process", "process"))
        profile = replace(
            self.fixture.match.selected.effective_profile,
            effective_values={"draft_shield": "disabled", "skirt_loops": "0"},
        )
        resolved = SimpleNamespace(
            record=self.fixture.process,
            effective_values={"draft_shield": "enabled", "skirt_loops": "2"},
        )
        self.assertEqual(
            draft_shield_source(profile, (resolved,)),
            source,
        )

    def test_preslice_and_calibration_use_isolated_disabled_profile(self):
        f = self.fixture
        f.service.cache = PreSliceCache(f.app_root / "cache")
        adapter = preslice_tests.FakeSliceAdapter()
        adapter.adapter_id = "anycubic_slicer_next"
        for simulated, cache_hit in ((False, False), (True, False), (True, True)):
            result = f.service.run(
                stl_validation=f.validation,
                profile_match=f.match,
                confirmation=f.confirmation,
                adapter=adapter,
                simulate_draft_shield=simulated,
            )
            try:
                self.assertEqual(result.cache_hit, cache_hit)
                self.assertEqual(result.draft_shield_simulated, simulated)
                if simulated and not cache_hit:
                    copied = json.loads(
                        adapter.requests[-1].profile.process.path.read_text()
                    )
                    self.assertEqual(copied["draft_shield"], "disabled")
                    self.assertEqual(copied["skirt_loops"], "0")
                    self.assertEqual(copied["skirt_height"], "99")
            finally:
                result.cleanup()
        profile = with_simulated_draft_shield_disabled(
            f.match.selected.effective_profile
        )
        copied, overrides = build_calibration_profile(
            profile, f.app_root / "calibration", resolved_profiles=()
        )
        values = json.loads(copied.process.path.read_text())
        self.assertEqual(values["draft_shield"], "disabled")
        self.assertEqual(values["skirt_loops"], "0")
        self.assertEqual(overrides["draft_shield"], "disabled")
        self.assertEqual(overrides["skirt_loops"], "0")

    def test_bambu_tall_skirt_is_disabled_without_adding_draft_shield(self):
        f = self.fixture
        original = f.process.path.read_bytes()
        try:
            f.process.path.write_text(
                json.dumps({
                    "name": "process", "skirt_loops": "2",
                    "skirt_height": "60", "skirt_distance": "8",
                }), encoding="utf-8"
            )
            profile = replace(
                f.match.selected.effective_profile,
                installation=replace(f.installation, adapter_id="bambu_studio"),
                effective_values={
                    "skirt_loops": "2", "skirt_height": "60",
                    "skirt_distance": "8",
                },
            )
            self.assertIsNotNone(draft_shield_source(profile))
            simulated = with_simulated_draft_shield_disabled(profile)
            self.assertNotIn("draft_shield", simulated.effective_values)
            copied, overrides = build_calibration_profile(
                simulated, f.app_root / "bambu_calibration",
                resolved_profiles=(),
            )
            values = json.loads(copied.process.path.read_text())
            self.assertEqual(values["skirt_loops"], "0")
            self.assertEqual(values["skirt_height"], "60")
            self.assertEqual(values["skirt_distance"], "8")
            self.assertNotIn("draft_shield", values)
            self.assertEqual(overrides, {"skirt_loops": "0"})
        finally:
            f.process.path.write_bytes(original)

    def test_dialog_simulation_is_source_scoped(self):
        f = self.fixture
        window = MainWindow(
            user_settings_path=f.app_root / "settings.json",
            enable_update_check=False,
            enable_startup_slicer_discovery=False,
        )
        try:
            window.source_artifact = f.validation.source_artifact
            window.profile_match_result = f.match
            detected = draft_shield_source(f.match.selected.effective_profile)
            with patch.object(window, "confirm_profile_selection") as confirm:
                window._show_draft_shield_dialog(f.match, detected)
                dialog = window._draft_shield_dialog
                self.assertIn("<li><b>Draft Shield</b>", dialog.message.text())
                self.assertIn("<b>Luftzug-Schutz</b>", dialog.message.text())
                self.assertIn("<li><b>Skirt-Loops</b>", dialog.message.text())
                self.assertIn("<b>Anzahl Umdrehungsringe</b>", dialog.message.text())
                self.assertIn("<b>Schürzenschlaufen</b>", dialog.message.text())
                dialog.simulate_button.click()
                self.assertTrue(window._draft_shield_simulation_requested)
                confirm.assert_called_once()
            window._discard_source_preslice("profile_selection_changed")
            self.assertFalse(window._draft_shield_simulation_requested)
        finally:
            window.close()

    def test_catalog_confirmation_cannot_auto_confirm_active_shield(self):
        f = self.fixture
        window = MainWindow(
            user_settings_path=f.app_root / "settings.json",
            enable_update_check=False,
            enable_startup_slicer_discovery=False,
        )
        try:
            pending = replace(
                f.match, requires_confirmation=True, user_confirmed=False
            )
            window.source_artifact = f.validation.source_artifact
            with (
                patch.object(
                    MainWindow, "selected_slicer_installation",
                    new_callable=PropertyMock,
                    return_value=pending.execution_slicer,
                ),
                patch.object(
                    window, "_profile_result_matches_catalog_confirmation",
                    return_value=True,
                ),
                patch.object(window.profile_service, "confirm") as confirm,
                patch.object(window, "_show_draft_shield_dialog") as show_dialog,
            ):
                window._on_profile_matching_succeeded(
                    window._profile_request_id, pending
                )
            confirm.assert_not_called()
            show_dialog.assert_called_once()
            self.assertIs(show_dialog.call_args.args[0], pending)
            self.assertEqual(show_dialog.call_args.args[1].profile_name, "process")
            self.assertTrue(window.profile_match_result.requires_confirmation)
        finally:
            window.close()

    def test_changing_preparation_discards_tower_and_preview(self):
        f = self.fixture
        window = MainWindow(
            user_settings_path=f.app_root / "settings.json",
            enable_update_check=False,
            enable_startup_slicer_discovery=False,
        )
        try:
            disposed = []
            window.current_preview = SimpleNamespace(dispose=lambda: disposed.append(True))
            window.preview_state = PreviewState.CURRENT
            window.generation_intro_label.hide()
            window.joint_generation_dialog.show()
            window._discard_source_preslice("profile_selection_changed")
            self.assertEqual(disposed, [True])
            self.assertIsNone(window.current_preview)
            self.assertEqual(window.preview_state, PreviewState.EMPTY)
            self.assertIsNone(window.preview_dialog.canvas.scene)
            self.assertFalse(window.generation_intro_label.isHidden())
            self.assertTrue(window.joint_generation_dialog.isHidden())
        finally:
            window.close()


if __name__ == "__main__":
    unittest.main()
