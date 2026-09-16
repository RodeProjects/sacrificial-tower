from __future__ import annotations

import os
import sys
import tempfile
import time
import unittest
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch


PROJECT_ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = PROJECT_ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("COOLING_TOWER_DISABLE_SLICER_DISCOVERY", "1")

from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

from cooling_tower.gui.background_jobs import JobKind
from cooling_tower.gui.main_window import MainWindow
from cooling_tower.models.source import SourceKind
from cooling_tower.slicers import (
    ProfileCatalog,
    ProfileCatalogConfirmation,
    ProfileKind,
    ProfileRecord,
    ProfileSelectionReference,
    SlicerCapability,
    SlicerDiscoveryResult,
    SlicerDiscoverySource,
    SlicerGuiState,
    SlicerInstallation,
    SlicerSupportLevel,
)


class StartupSlicerService:
    def __init__(self, result: SlicerDiscoveryResult) -> None:
        self.result = result
        self.adapter = object()
        self.discovery_calls = 0
        self.remembered_profiles: list[tuple[str, str, str]] = []
        self.profile_selections: dict[
            str, ProfileSelectionReference
        ] = {}
        self.remembered_identity_keys: list[str] = []

    def discover_installations(self, _source_slicer, *, force=False):
        self.discovery_calls += 1
        return self.result

    def adapter_for(self, _installation):
        return self.adapter

    def remember_selection(self, _identity_key) -> None:
        return None

    def remembered_profile_selections(self, identity_key):
        self.remembered_identity_keys.append(identity_key)
        return dict(self.profile_selections)

    def remember_profile_selection(
        self,
        identity_key: str,
        role: str,
        profile: ProfileRecord,
    ) -> None:
        self.remembered_profiles.append(
            (identity_key, role, str(profile.path))
        )
        self.profile_selections[role] = ProfileSelectionReference(
            profile.profile_id,
            profile.path,
        )


class StartupProfileService:
    def __init__(self, catalog: ProfileCatalog) -> None:
        self.result = catalog
        self.catalog_calls = 0
        self.prefer_active_presets: list[bool] = []

    def catalog(
        self,
        installation,
        _adapter,
        *,
        force_inventory=False,
        selected_machine=None,
        selected_profile_ids=None,
        include_all_profiles=False,
        prefer_active_presets=False,
    ):
        self.catalog_calls += 1
        self.prefer_active_presets.append(bool(prefer_active_presets))
        if installation.identity_key != self.result.execution_slicer.identity_key:
            raise ValueError("unexpected installation")
        selections = dict(selected_profile_ids or {})
        if selected_machine is not None:
            selections["machine"] = selected_machine
        return replace(
            self.result,
            selected_machine=selections.get("machine"),
            selected_process=selections.get("process"),
            selected_filament=selections.get("filament"),
        )


class StartupPreparationProgressTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        executable = self.root / "Slicer.exe"
        executable.write_bytes(b"MZ")
        self.installation = SlicerInstallation(
            adapter_id="test",
            product_name="Test Slicer",
            version="1.0",
            executable_path=executable,
            verified=True,
            capabilities=frozenset(
                {
                    SlicerCapability.CLI_SLICE,
                    SlicerCapability.PROFILE_INVENTORY,
                }
            ),
            discovery_source=SlicerDiscoverySource.KNOWN_PATH,
            support_level=SlicerSupportLevel.FULL,
        )
        self.records = {
            "machine": self._record("machine.json", ProfileKind.MACHINE),
            "process": self._record("process.json", ProfileKind.PROCESS),
            "filament": self._record("filament.json", ProfileKind.FILAMENT),
            "filament_alt": self._record(
                "filament-alt.json", ProfileKind.FILAMENT
            ),
        }
        self.catalog = ProfileCatalog(
            execution_slicer=self.installation,
            inventory_fingerprint="inventory-v1",
            machine_options=(self.records["machine"],),
            process_options=(self.records["process"],),
            filament_options=(
                self.records["filament"],
                self.records["filament_alt"],
            ),
        )

    def tearDown(self) -> None:
        self.app.processEvents()
        self.temporary.cleanup()

    def _record(self, name: str, kind: ProfileKind) -> ProfileRecord:
        path = self.root / name
        path.write_text("{}", encoding="utf-8")
        return ProfileRecord(
            adapter_id="test",
            profile_id=path.stem,
            name=path.stem,
            kind=kind,
            path=path,
            source="user",
        )

    def _wait_until(self, predicate, timeout_s: float = 5.0) -> None:
        deadline = time.monotonic() + timeout_s
        while not predicate() and time.monotonic() < deadline:
            self.app.processEvents()
            QTest.qWait(10)
        self.assertTrue(predicate())

    def test_startup_discovers_slicer_and_profiles_before_source(self) -> None:
        discovery = SlicerDiscoveryResult(
            installations=(self.installation,),
            recommended_key=self.installation.identity_key,
            gui_state=SlicerGuiState.AVAILABLE_AND_RECOMMENDED,
            message="Slicer gefunden",
        )
        slicer_service = StartupSlicerService(discovery)
        profile_service = StartupProfileService(self.catalog)
        original_profile_bytes = {
            path: path.read_bytes()
            for path in (record.path for record in self.records.values())
        }
        window = MainWindow(
            user_settings_path=self.root / "settings.json",
            slicer_service=slicer_service,
            profile_service=profile_service,
            enable_update_check=False,
            enable_startup_slicer_discovery=True,
        )
        try:
            self._wait_until(
                lambda: window.profile_catalog is not None
                and not window.background_job_manager.has_active(
                    JobKind.PROFILE_MATCH
                )
            )
            self.assertEqual(slicer_service.discovery_calls, 1)
            self.assertEqual(profile_service.catalog_calls, 1)
            self.assertEqual(profile_service.prefer_active_presets, [True])
            self.assertIsNone(window.current_source_path)
            self.assertTrue(window.slicer_progress_bar.isHidden())
            self.assertTrue(window.source_progress_bar.isHidden())
            self.assertEqual(
                window.preparation_step_selectors[1].progress_value,
                0,
            )
            self.assertEqual(window.preparation_progress_bar.value(), 0)
            self.assertTrue(
                window.preparation_step_selectors[1].property("locked")
            )
            self.assertEqual(
                window.preparation_requirement_rows["slicer_detected"][0].text(),
                "✓",
            )
            self.assertEqual(
                window.preparation_requirement_rows["profiles_loaded"][0].text(),
                "✓",
            )
            self.assertFalse(window.profile_confirm_button.isEnabled())

            window.profile_confirm_button.click()
            self.app.processEvents()
            self.assertIsNone(window.profile_catalog_confirmation)
            self.assertEqual(
                window.preparation_step_selectors[1].progress_value,
                0,
            )
            self.assertTrue(window.ready_grid.isHidden())

            alternative_index = next(
                index
                for index in range(window.filament_profile_combo.count())
                if window.filament_profile_combo.itemData(index)
                == str(self.records["filament_alt"].path)
            )
            window.filament_profile_combo.setCurrentIndex(alternative_index)
            self.app.processEvents()
            self.assertIsNone(window.profile_catalog_confirmation)
            self.assertEqual(
                window.preparation_step_selectors[1].progress_value,
                0,
            )
            self.assertFalse(window.profile_confirm_button.isEnabled())
            self.assertNotIn("filament", slicer_service.profile_selections)

            source = self.root / "accepted.stl"
            source.write_text("solid x\nendsolid x\n", encoding="ascii")
            window.current_source_path = source.resolve()
            window.current_source_kind = SourceKind.STL
            window.source_artifact = SimpleNamespace(
                original_path=source.resolve(),
                matches_current_file=lambda: True,
            )
            window.stl_validation_result = SimpleNamespace(valid=True)
            window._update_preparation_requirements()
            self.assertEqual(
                window.preparation_step_selectors[1].progress_value,
                40,
            )
            self.assertEqual(window.preparation_progress_bar.value(), 57)

            self.assertEqual(
                {
                    path: path.read_bytes()
                    for path in original_profile_bytes
                },
                original_profile_bytes,
            )
        finally:
            window.close()
            window.deleteLater()
            self.app.processEvents()

    def test_startup_preselects_last_confirmed_profiles_for_same_slicer(self) -> None:
        discovery = SlicerDiscoveryResult(
            installations=(self.installation,),
            recommended_key=self.installation.identity_key,
            gui_state=SlicerGuiState.AVAILABLE_AND_RECOMMENDED,
            message="Slicer gefunden",
        )
        slicer_service = StartupSlicerService(discovery)
        slicer_service.profile_selections = {
            role: ProfileSelectionReference(record.profile_id, record.path)
            for role, record in (
                ("machine", self.records["machine"]),
                ("process", self.records["process"]),
                ("filament", self.records["filament_alt"]),
            )
        }
        profile_service = StartupProfileService(self.catalog)
        window = MainWindow(
            user_settings_path=self.root / "restart-settings.json",
            slicer_service=slicer_service,
            profile_service=profile_service,
            enable_update_check=False,
            enable_startup_slicer_discovery=True,
        )
        try:
            self._wait_until(
                lambda: window.profile_catalog is not None
                and not window.background_job_manager.has_active(
                    JobKind.PROFILE_MATCH
                )
            )

            self.assertEqual(
                window._profile_combo_reference(
                    window.machine_profile_combo
                ).profile_id,
                self.records["machine"].profile_id,
            )
            self.assertEqual(
                window._profile_combo_reference(
                    window.process_profile_combo
                ).profile_id,
                self.records["process"].profile_id,
            )
            self.assertEqual(
                window._profile_combo_reference(
                    window.filament_profile_combo
                ).profile_id,
                self.records["filament_alt"].profile_id,
            )
            self.assertIn(
                self.installation.identity_key,
                slicer_service.remembered_identity_keys,
            )
            self.assertFalse(window.profile_confirm_button.isEnabled())
            self.assertIsNone(window.profile_catalog_confirmation)
            self.assertEqual(profile_service.prefer_active_presets, [False])
        finally:
            window.close()
            window.deleteLater()
            self.app.processEvents()

    def test_explicit_rediscovery_ignores_stale_remembered_profile_choice(self) -> None:
        discovery = SlicerDiscoveryResult(
            installations=(self.installation,),
            recommended_key=self.installation.identity_key,
            gui_state=SlicerGuiState.AVAILABLE_AND_RECOMMENDED,
            message="Slicer gefunden",
        )
        slicer_service = StartupSlicerService(discovery)
        slicer_service.profile_selections = {
            role: ProfileSelectionReference(record.profile_id, record.path)
            for role, record in (
                ("machine", self.records["machine"]),
                ("process", self.records["process"]),
                ("filament", self.records["filament_alt"]),
            )
        }
        profile_service = StartupProfileService(self.catalog)
        window = MainWindow(
            user_settings_path=self.root / "rediscovery-settings.json",
            slicer_service=slicer_service,
            profile_service=profile_service,
            enable_update_check=False,
            enable_startup_slicer_discovery=True,
        )
        try:
            self._wait_until(lambda: profile_service.catalog_calls == 1)
            self.assertEqual(profile_service.prefer_active_presets, [False])
            remembered_calls = len(slicer_service.remembered_identity_keys)

            window.start_slicer_discovery(force=True)
            self._wait_until(
                lambda: profile_service.catalog_calls == 2
                and not window.background_job_manager.has_active(
                    JobKind.PROFILE_MATCH
                )
            )

            self.assertEqual(
                profile_service.prefer_active_presets,
                [False, True],
            )
            self.assertEqual(
                len(slicer_service.remembered_identity_keys),
                remembered_calls,
            )
            self.assertEqual(
                window._profile_combo_reference(
                    window.filament_profile_combo
                ).profile_id,
                self.records["filament"].profile_id,
            )
        finally:
            window.close()
            window.deleteLater()
            self.app.processEvents()

    def test_first_incomplete_step_two_entry_retries_detection_only_once(self) -> None:
        discovery = SlicerDiscoveryResult(
            installations=(self.installation,),
            recommended_key=self.installation.identity_key,
            gui_state=SlicerGuiState.AVAILABLE_AND_RECOMMENDED,
            message="Slicer gefunden",
        )
        window = MainWindow(
            user_settings_path=self.root / "entry-retry-settings.json",
            slicer_service=StartupSlicerService(discovery),
            profile_service=StartupProfileService(self.catalog),
            enable_update_check=False,
            enable_startup_slicer_discovery=False,
        )
        source = self.root / "entry-retry.stl"
        source.write_text("solid x\nendsolid x\n", encoding="ascii")

        def make_source_ready() -> None:
            window.current_source_path = source.resolve()
            window.current_source_kind = SourceKind.STL
            window.source_artifact = SimpleNamespace(
                original_path=source.resolve(),
                matches_current_file=lambda: True,
            )
            window.stl_validation_result = SimpleNamespace(valid=True)

        try:
            self.assertEqual(
                window.slicer_refresh_button.text(),
                "Slicer und Profile erneut erkennen",
            )
            make_source_ready()
            window._startup_slicer_discovery_enabled = True
            with patch.object(window, "start_slicer_discovery") as discovery_retry:
                window.preparation_tabs.setCurrentIndex(1)
                discovery_retry.assert_called_once_with(force=True)

                window.preparation_tabs.setCurrentIndex(0)
                window.current_source_path = None
                window.current_source_kind = None
                window.source_artifact = None
                window.stl_validation_result = None
                make_source_ready()
                window.preparation_tabs.setCurrentIndex(1)
                discovery_retry.assert_called_once_with(force=True)
        finally:
            window.close()
            window.deleteLater()
            self.app.processEvents()

    def test_catalog_confirmation_rejects_path_outside_inventory(self) -> None:
        with self.assertRaises(ValueError):
            ProfileCatalogConfirmation.from_catalog(
                self.catalog,
                machine_path=self.records["machine"].path,
                process_path=self.records["process"].path,
                filament_path=self.root / "not-in-catalog.json",
            )

    def test_catalog_confirmation_uses_profile_id_for_shared_bundle_path(
        self,
    ) -> None:
        shared_path = self.root / "shared-bundle.ini"
        shared_path.write_text("[filament:A]\n[filament:B]\n", encoding="utf-8")
        first = ProfileRecord(
            adapter_id="test",
            profile_id="filament-a",
            name="Filament A",
            kind=ProfileKind.FILAMENT,
            path=shared_path,
            source="system",
        )
        second = ProfileRecord(
            adapter_id="test",
            profile_id="filament-b",
            name="Filament B",
            kind=ProfileKind.FILAMENT,
            path=shared_path,
            source="system",
        )
        catalog = ProfileCatalog(
            execution_slicer=self.installation,
            inventory_fingerprint="shared-bundle-v1",
            machine_options=(self.records["machine"],),
            process_options=(self.records["process"],),
            filament_options=(first, second),
        )
        with self.assertRaises(ValueError):
            ProfileCatalogConfirmation.from_catalog(
                catalog,
                machine_path=self.records["machine"].path,
                process_path=self.records["process"].path,
                filament_path=shared_path,
            )
        confirmation = ProfileCatalogConfirmation.from_catalog(
            catalog,
            machine_path=self.records["machine"].path,
            process_path=self.records["process"].path,
            filament_path=shared_path,
            machine_profile_id=self.records["machine"].profile_id,
            process_profile_id=self.records["process"].profile_id,
            filament_profile_id=second.profile_id,
        )
        self.assertEqual(confirmation.filament_profile_id, "filament-b")
        self.assertEqual(
            confirmation.selected_profile_ids()["filament"].profile_id,
            "filament-b",
        )


if __name__ == "__main__":
    unittest.main()
