from __future__ import annotations

import hashlib
import json
import sys
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = PROJECT_ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from cooling_tower.config import SETTINGS_SCHEMA_VERSION
from cooling_tower.gui.settings_store import UserSettingsStore
from cooling_tower.models import GenerationSettings
from cooling_tower.settings_compatibility import (
    SETTING_COMPATIBILITY_CATALOG,
    merge_compatible_setting_changes,
)


DEFAULTS_PATH = PROJECT_ROOT / "config" / "default_settings.json"


def current_payload(**generation_changes: object) -> dict[str, object]:
    generation = GenerationSettings().to_dict()
    generation.update(generation_changes)
    return {
        "settings_schema_version": SETTINGS_SCHEMA_VERSION,
        "generation": generation,
        "output_root": "output",
        "preview_quality": "balanced",
        "setting_compatibility": dict(SETTING_COMPATIBILITY_CATALOG),
    }


class CompatibilityRuleTests(unittest.TestCase):
    def test_valid_value_with_same_semantics_is_accepted(self) -> None:
        result = merge_compatible_setting_changes(
            current_payload(),
            {
                "generation.target_layer_time_s": {
                    "token": "duration-seconds-v1",
                    "value": 17.5,
                }
            },
        )

        self.assertEqual(
            result.payload["generation"]["target_layer_time_s"],
            17.5,
        )
        self.assertEqual(
            result.accepted_ids,
            ("generation.target_layer_time_s",),
        )

    def test_value_above_target_maximum_is_rejected_not_clamped(self) -> None:
        result = merge_compatible_setting_changes(
            current_payload(maximum_expansion_angle_deg=10.0),
            {
                "generation.maximum_expansion_angle_deg": {
                    "token": "expansion-angle-degrees-v1",
                    "value": 20.0,
                }
            },
        )

        self.assertEqual(
            result.payload["generation"]["maximum_expansion_angle_deg"],
            20.0,
        )
        self.assertEqual(
            result.accepted_ids,
            ("generation.maximum_expansion_angle_deg",),
        )

        rejected = merge_compatible_setting_changes(
            current_payload(maximum_expansion_angle_deg=10.0),
            {
                "generation.maximum_expansion_angle_deg": {
                    "token": "expansion-angle-degrees-v1",
                    "value": 80.0,
                }
            },
        )
        self.assertEqual(
            rejected.payload["generation"]["maximum_expansion_angle_deg"],
            10.0,
        )
        self.assertEqual(
            rejected.rejected_ids,
            ("generation.maximum_expansion_angle_deg",),
        )

    def test_wrong_type_and_changed_unit_token_are_rejected(self) -> None:
        result = merge_compatible_setting_changes(
            current_payload(),
            {
                "generation.mesh_segments": {
                    "token": "circle-segment-count-v1",
                    "value": 32.5,
                },
                "generation.target_layer_time_s": {
                    "token": "duration-milliseconds-v1",
                    "value": 5000.0,
                },
            },
        )

        self.assertEqual(
            result.payload["generation"]["mesh_segments"],
            GenerationSettings().mesh_segments,
        )
        self.assertEqual(
            result.payload["generation"]["target_layer_time_s"],
            GenerationSettings().target_layer_time_s,
        )
        self.assertEqual(
            set(result.rejected_ids),
            {
                "generation.mesh_segments",
                "generation.target_layer_time_s",
            },
        )

    def test_value_below_target_minimum_is_rejected(self) -> None:
        result = merge_compatible_setting_changes(
            current_payload(target_layer_time_s=10.0),
            {
                "generation.target_layer_time_s": {
                    "token": "duration-seconds-v1",
                    "value": 0.0,
                }
            },
        )

        self.assertEqual(
            result.payload["generation"]["target_layer_time_s"],
            10.0,
        )
        self.assertEqual(
            result.rejected_ids,
            ("generation.target_layer_time_s",),
        )

    def test_dependent_geometry_group_is_applied_atomically(self) -> None:
        result = merge_compatible_setting_changes(
            current_payload(),
            {
                "generation.minimum_outer_radius_mm": {
                    "token": "outer-radius-mm-v1",
                    "value": 40.0,
                },
                "generation.maximum_outer_radius_mm": {
                    "token": "outer-radius-mm-v1",
                    "value": 30.0,
                },
            },
        )

        self.assertEqual(
            result.payload["generation"]["minimum_outer_radius_mm"],
            GenerationSettings().minimum_outer_radius_mm,
        )
        self.assertEqual(
            result.payload["generation"]["maximum_outer_radius_mm"],
            GenerationSettings().maximum_outer_radius_mm,
        )
        self.assertEqual(
            set(result.rejected_ids),
            {
                "generation.minimum_outer_radius_mm",
                "generation.maximum_outer_radius_mm",
            },
        )


class DowngradeJournalIntegrationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.user_path = self.root / "user_settings.json"

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def test_downgrade_keeps_newer_file_and_records_valid_changes(self) -> None:
        future = current_payload(target_layer_time_s=13.0)
        future["settings_schema_version"] = SETTINGS_SCHEMA_VERSION + 1
        future["future_only_setting"] = {"value": "bleibt erhalten"}
        self.user_path.write_text(
            json.dumps(future, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        original = self.user_path.read_bytes()
        store = UserSettingsStore(self.user_path, DEFAULTS_PATH)

        settings, _state = store.load()
        self.assertEqual(settings.target_layer_time_s, 13.0)
        self.assertIsNone(store.write_blocked_reason)

        journal_path = store.save(
            replace(settings, target_layer_time_s=18.0),
            output_root="output",
            window_width=900,
            window_height=700,
        )

        self.assertEqual(self.user_path.read_bytes(), original)
        journal = json.loads(journal_path.read_text(encoding="utf-8"))
        change = journal["changes"]["generation.target_layer_time_s"]
        self.assertEqual(change["value"], 18.0)
        self.assertEqual(change["token"], "duration-seconds-v1")
        self.assertEqual(journal["status"], "active")

    def test_returning_version_merges_safe_change_and_marks_journal_applied(self) -> None:
        initial_store = UserSettingsStore(self.user_path, DEFAULTS_PATH)
        initial_store.save(
            GenerationSettings(target_layer_time_s=13.0),
            output_root="output",
            window_width=900,
            window_height=700,
        )
        original = self.user_path.read_bytes()
        journal_path = self.user_path.with_name(
            f"{self.user_path.name}.downgrade-changes.json"
        )
        journal_path.write_text(
            json.dumps(
                {
                    "downgrade_journal_schema_version": 1,
                    "protected_sha256": hashlib.sha256(original).hexdigest(),
                    "protected_settings_schema_version": SETTINGS_SCHEMA_VERSION,
                    "next_revision": 2,
                    "status": "active",
                    "changes": {
                        "generation.target_layer_time_s": {
                            "token": "duration-seconds-v1",
                            "revision": 1,
                            "value": 18.0,
                        }
                    },
                },
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )

        returning_store = UserSettingsStore(self.user_path, DEFAULTS_PATH)
        settings, _state = returning_store.load()

        self.assertEqual(settings.target_layer_time_s, 18.0)
        persisted = json.loads(self.user_path.read_text(encoding="utf-8"))
        self.assertEqual(
            persisted["generation"]["target_layer_time_s"],
            18.0,
        )
        journal = json.loads(journal_path.read_text(encoding="utf-8"))
        self.assertEqual(journal["status"], "applied")
        self.assertEqual(
            journal["accepted_ids"],
            ["generation.target_layer_time_s"],
        )

    def test_returning_version_rejects_out_of_range_change(self) -> None:
        initial_store = UserSettingsStore(self.user_path, DEFAULTS_PATH)
        initial_store.save(
            GenerationSettings(maximum_expansion_angle_deg=10.0),
            output_root="output",
            window_width=900,
            window_height=700,
        )
        original = self.user_path.read_bytes()
        journal_path = self.user_path.with_name(
            f"{self.user_path.name}.downgrade-changes.json"
        )
        journal_path.write_text(
            json.dumps(
                {
                    "downgrade_journal_schema_version": 1,
                    "protected_sha256": hashlib.sha256(original).hexdigest(),
                    "protected_settings_schema_version": SETTINGS_SCHEMA_VERSION,
                    "next_revision": 2,
                    "status": "active",
                    "changes": {
                        "generation.maximum_expansion_angle_deg": {
                            "token": "expansion-angle-degrees-v1",
                            "revision": 1,
                            "value": 80.0,
                        }
                    },
                }
            ),
            encoding="utf-8",
        )

        returning_store = UserSettingsStore(self.user_path, DEFAULTS_PATH)
        settings, _state = returning_store.load()

        self.assertEqual(settings.maximum_expansion_angle_deg, 10.0)
        self.assertIn("nicht kompatible", returning_store.last_load_warning)
        journal = json.loads(journal_path.read_text(encoding="utf-8"))
        self.assertEqual(
            journal["rejected_ids"],
            ["generation.maximum_expansion_angle_deg"],
        )

    def test_changed_primary_file_prevents_automatic_journal_merge(self) -> None:
        initial_store = UserSettingsStore(self.user_path, DEFAULTS_PATH)
        initial_store.save(
            GenerationSettings(target_layer_time_s=13.0),
            output_root="output",
            window_width=900,
            window_height=700,
        )
        original = self.user_path.read_bytes()
        journal_path = self.user_path.with_name(
            f"{self.user_path.name}.downgrade-changes.json"
        )
        journal_path.write_text(
            json.dumps(
                {
                    "downgrade_journal_schema_version": 1,
                    "protected_sha256": hashlib.sha256(original).hexdigest(),
                    "protected_settings_schema_version": SETTINGS_SCHEMA_VERSION,
                    "next_revision": 2,
                    "status": "active",
                    "changes": {
                        "generation.target_layer_time_s": {
                            "token": "duration-seconds-v1",
                            "revision": 1,
                            "value": 18.0,
                        }
                    },
                }
            ),
            encoding="utf-8",
        )
        changed = json.loads(self.user_path.read_text(encoding="utf-8"))
        changed["generation"]["target_layer_time_s"] = 14.0
        self.user_path.write_text(json.dumps(changed), encoding="utf-8")

        returning_store = UserSettingsStore(self.user_path, DEFAULTS_PATH)
        settings, _state = returning_store.load()

        self.assertEqual(settings.target_layer_time_s, 14.0)
        self.assertIn("zwischenzeitlich geändert", returning_store.last_load_warning)
        journal = json.loads(journal_path.read_text(encoding="utf-8"))
        self.assertEqual(journal["status"], "active")


if __name__ == "__main__":
    unittest.main()
