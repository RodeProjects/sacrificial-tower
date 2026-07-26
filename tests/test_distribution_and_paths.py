from __future__ import annotations

import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch


os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
PROJECT_ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = PROJECT_ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from PySide6.QtWidgets import QApplication

from cooling_tower.distribution import (
    DistributionChannel,
    detect_distribution_channel,
)
from cooling_tower.gui.main_window import MainWindow
from cooling_tower.persistence import (
    VersionedDocumentWriteBlockedError,
    copy_legacy_file_if_absent,
)
from cooling_tower.runtime_paths import resolve_user_data_root
from cooling_tower.slicers import ProfileMappingStore, SlicerPreferenceStore
from cooling_tower.update import UpdateService


class DistributionAndPathTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.application = QApplication.instance() or QApplication([])

    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def test_user_data_root_is_independent_from_installation(self) -> None:
        root = resolve_user_data_root(
            {"LOCALAPPDATA": str(self.root / "LocalAppData")}
        )
        self.assertEqual(
            root,
            (
                self.root
                / "LocalAppData"
                / "RodeProjects"
                / "SacrificialTower"
                / "development"
            ).resolve(),
        )
        explicit = resolve_user_data_root(
            {"COOLING_TOWER_USER_DATA_ROOT": str(self.root / "custom")}
        )
        self.assertEqual(explicit, (self.root / "custom").resolve())
        isolated = resolve_user_data_root(
            {
                "LOCALAPPDATA": str(self.root / "LocalAppData"),
                "COOLING_TOWER_INSTANCE_ID": "test-0.4.5",
            }
        )
        self.assertEqual(isolated.name, "test-0.4.5")
        with self.assertRaises(ValueError):
            resolve_user_data_root(
                {
                    "LOCALAPPDATA": str(self.root / "LocalAppData"),
                    "COOLING_TOWER_INSTANCE_ID": "../escape",
                }
            )

    def test_distribution_metadata_and_override_are_deterministic(self) -> None:
        config = self.root / "config"
        config.mkdir()
        (config / "distribution.json").write_text(
            json.dumps({"channel": "microsoft-store"}),
            encoding="utf-8",
        )
        self.assertEqual(
            detect_distribution_channel(
                resource_root=self.root,
                environment={},
            ),
            DistributionChannel.MICROSOFT_STORE,
        )
        self.assertEqual(
            detect_distribution_channel(
                resource_root=self.root,
                environment={"COOLING_TOWER_DISTRIBUTION_CHANNEL": "standalone"},
            ),
            DistributionChannel.STANDALONE,
        )

    def test_legacy_copy_preserves_source_and_never_overwrites_target(self) -> None:
        source = self.root / "legacy" / "settings.json"
        target = self.root / "current" / "settings.json"
        source.parent.mkdir()
        source.write_bytes(b'{"legacy": true}\n')

        first = copy_legacy_file_if_absent(source, target)
        self.assertTrue(first.copied)
        self.assertEqual(target.read_bytes(), source.read_bytes())
        self.assertTrue(source.is_file())

        target.write_bytes(b'{"current": true}\n')
        second = copy_legacy_file_if_absent(source, target)
        self.assertFalse(second.copied)
        self.assertEqual(target.read_bytes(), b'{"current": true}\n')
        self.assertEqual(list(target.parent.glob(".*.tmp")), [])

    def test_python_variant_imports_its_legacy_configuration_once(self) -> None:
        legacy_root = self.root / "legacy_install"
        legacy_config = legacy_root / "config"
        legacy_config.mkdir(parents=True)
        legacy_settings = legacy_config / "user_settings.json"
        legacy_settings.write_text(
            json.dumps({"target_layer_time_s": 17.0}),
            encoding="utf-8",
        )
        current_root = self.root / "current_data"
        with (
            patch.dict(
                os.environ,
                {"COOLING_TOWER_USER_DATA_ROOT": str(current_root)},
            ),
            patch("cooling_tower.gui.main_window.INSTALL_ROOT", legacy_root),
        ):
            window = MainWindow(enable_update_check=False)
        try:
            migrated = current_root / "config" / "user_settings.json"
            self.assertTrue(migrated.is_file())
            self.assertTrue(legacy_settings.is_file())
            self.assertEqual(window.target_time_spin.value(), 17.0)
        finally:
            window.close()

    def test_default_runtime_files_use_writable_user_root(self) -> None:
        window = MainWindow(
            user_data_root=self.root,
            enable_update_check=False,
        )
        try:
            self.assertEqual(
                window.settings_store.user_path,
                self.root / "config" / "user_settings.json",
            )
            self.assertEqual(window.default_output_root, self.root / "output")
            self.assertEqual(
                window.slicer_service.preference_store.path,
                self.root / "config" / "slicer_settings.json",
            )
            self.assertEqual(
                window.profile_service.inventory_service.cache_path,
                self.root / "config" / "profile_inventory_cache.json",
            )
            self.assertEqual(
                window.profile_service.mapping_store.path,
                self.root / "config" / "profile_mappings.json",
            )
        finally:
            window.close()

    def test_store_build_cannot_start_the_standalone_updater(self) -> None:
        window = MainWindow(
            user_data_root=self.root,
            update_service=UpdateService(opener=lambda *_args, **_kwargs: None),
            enable_update_check=True,
            distribution_channel=DistributionChannel.MICROSOFT_STORE,
        )
        try:
            self.assertFalse(window._update_check_enabled)
        finally:
            window.close()

    def test_slicer_preferences_migrate_and_protect_the_original(self) -> None:
        path = self.root / "slicer_settings.json"
        executable = self.root / "slicer.exe"
        path.write_text(
            json.dumps(
                {
                    "confirmed_paths": [str(executable)],
                    "last_selected_key": "adapter|path",
                }
            ),
            encoding="utf-8",
        )
        store = SlicerPreferenceStore(path)

        loaded = store.load()

        self.assertEqual(loaded.confirmed_paths, (executable,))
        self.assertIsNotNone(store.last_migration_backup)
        self.assertEqual(
            json.loads(path.read_text(encoding="utf-8"))["schema_version"],
            1,
        )

        corrupt_path = self.root / "corrupt_slicer_settings.json"
        corrupt_path.write_bytes(b"not json")
        corrupt_store = SlicerPreferenceStore(corrupt_path)
        self.assertFalse(corrupt_store.load().confirmed_paths)
        with self.assertRaises(VersionedDocumentWriteBlockedError):
            corrupt_store.confirm_path(executable)
        self.assertEqual(corrupt_path.read_bytes(), b"not json")

    def test_profile_mappings_migrate_and_block_future_schema_writes(self) -> None:
        path = self.root / "profile_mappings.json"
        path.write_text(json.dumps({"mappings": {}}), encoding="utf-8")
        store = ProfileMappingStore(path)

        self.assertEqual(store._read()["schema_version"], 1)
        self.assertIsNotNone(store.last_migration_backup)

        future_path = self.root / "future_profile_mappings.json"
        original = b'{"schema_version": 99, "mappings": {}}'
        future_path.write_bytes(original)
        future_store = ProfileMappingStore(future_path)
        self.assertEqual(future_store._read()["mappings"], {})
        with self.assertRaises(VersionedDocumentWriteBlockedError):
            future_store._write({"schema_version": 1, "mappings": {}})
        self.assertEqual(future_path.read_bytes(), original)


if __name__ == "__main__":
    unittest.main()
