"""Shared discovery helpers for opt-in tests using installed slicers."""
from __future__ import annotations

import json
import os
import sys
import unittest
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = PROJECT_ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from cooling_tower.slicers import (
    SlicerAdapter,
    SlicerCandidate,
    SlicerDiscoveryService,
    SlicerDiscoverySource,
    SlicerInstallation,
    ProfileRecord,
    SlicerError,
)


from cooling_tower.legacy_method_ids import LEGACY_POSTPROCESSOR_ID


CONFIG_PATH = PROJECT_ROOT / "tests" / "slicer_acceptance.local.json"
CONFIG_ENV_VAR = "COOLING_TOWER_SLICER_ACCEPTANCE_CONFIG"


def acceptance_config_path() -> Path:
    configured_path = os.environ.get(CONFIG_ENV_VAR)
    path = Path(configured_path).expanduser() if configured_path else CONFIG_PATH
    if not path.is_absolute():
        path = PROJECT_ROOT / path
    return path


def load_acceptance_config() -> dict[str, object]:
    path = acceptance_config_path()
    if not path.is_file():
        return {}
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise RuntimeError(f"Slicer-Abnahmekonfiguration ungültig ({path}): {error}") from error
    if not isinstance(value, dict):
        raise RuntimeError(f"Slicer-Abnahmekonfiguration muss ein JSON-Objekt sein: {path}")
    return value


def _test_config(test_key: str, adapter_id: str) -> dict[str, object]:
    config = load_acceptance_config()
    tests = config.get("tests", {})
    if not isinstance(tests, dict):
        return {}
    test = tests.get(test_key, tests.get(LEGACY_POSTPROCESSOR_ID+"_acceptance", {}) if test_key == "postprocessor_acceptance" else {})
    if not isinstance(test, dict):
        return {}
    slicer = test.get(adapter_id, {})
    return slicer if isinstance(slicer, dict) else {}


def require_test_path(
    testcase: unittest.TestCase,
    *,
    test_key: str,
    field: str,
    adapter_id: str | None = None,
) -> Path:
    config = load_acceptance_config()
    tests = config.get("tests", {})
    test = tests.get(test_key, tests.get(LEGACY_POSTPROCESSOR_ID+"_acceptance", {}) if test_key == "postprocessor_acceptance" else {}) if isinstance(tests, dict) else {}
    if not isinstance(test, dict):
        test = {}
    section = test.get(adapter_id, {}) if adapter_id else test
    value = section.get(field) if isinstance(section, dict) else None
    if not value:
        testcase.skipTest(
            f"Für die optionale Abnahme {test_key} fehlt '{field}'. "
            f"Lokale Konfiguration: {acceptance_config_path()}; Vorlage: "
            "tests/slicer_acceptance.example.json."
        )
    path = Path(os.path.expandvars(str(value))).expanduser()
    if not path.is_absolute():
        path = PROJECT_ROOT / path
    if not path.is_file():
        testcase.skipTest(
            f"Konfigurierter Pfad für {test_key} existiert nicht: {path}. "
            f"Bitte {acceptance_config_path()} anpassen."
        )
    return path


def require_profile_records(
    testcase: unittest.TestCase,
    *,
    test_key: str,
    adapter: SlicerAdapter,
    installation: SlicerInstallation,
    roles: tuple[str, ...],
    expected_sources: dict[str, str] | None = None,
) -> dict[str, ProfileRecord]:
    """Read named profile selections from the ignored local JSON config."""
    section = _test_config(test_key, adapter.adapter_id)
    profiles = section.get("profiles", {})
    if not isinstance(profiles, dict):
        profiles = {}
    missing = [role for role in roles if not profiles.get(role)]
    if missing:
        testcase.skipTest(
            f"Für die optionale Abnahme {test_key} fehlen Profile ({', '.join(missing)}). "
            f"Lokale Konfiguration: {acceptance_config_path()}; Vorlage: "
            "tests/slicer_acceptance.example.json."
        )
    available = adapter.discover_profiles(installation)
    selected: dict[str, ProfileRecord | None] = {}
    for role in roles:
        matches = [record for record in available if record.name == str(profiles[role])]
        expected_source = (expected_sources or {}).get(role)
        selected[role] = next(
            (record for record in matches if record.source == expected_source),
            matches[0] if matches else None,
        )
    absent = [str(profiles[role]) for role, record in selected.items() if record is None]
    if absent:
        testcase.skipTest(
            f"Konfigurierte Profile für {test_key} fehlen in {adapter.product_name}: "
            f"{', '.join(absent)}. Bitte {acceptance_config_path()} anpassen."
        )
    wrong_source = [
        f"{role}={selected[role].source} (erwartet {expected})"
        for role, expected in (expected_sources or {}).items()
        if role in selected and selected[role].source != expected
    ]
    if wrong_source:
        testcase.skipTest(
            f"Die konfigurierten Profile für {test_key} passen nicht zur "
            f"Abnahme: {', '.join(wrong_source)}. Bitte "
            f"{acceptance_config_path()} anpassen."
        )
    return selected


def require_slicer_installation(adapter: SlicerAdapter) -> SlicerInstallation:
    """Find one verified installation or skip the optional real-slicer test."""
    config = load_acceptance_config()
    slicers = config.get("slicers", {})
    if isinstance(slicers, dict):
        slicer_config = slicers.get(adapter.adapter_id, {})
        executable_value = (
            slicer_config.get("executable")
            if isinstance(slicer_config, dict)
            else None
        )
        if executable_value:
            executable = Path(os.path.expandvars(str(executable_value))).expanduser()
            if not executable.is_absolute():
                executable = PROJECT_ROOT / executable
            try:
                return adapter.verify_installation(
                    SlicerCandidate(
                        executable,
                        SlicerDiscoverySource.MANUAL,
                        adapter_hint=adapter.adapter_id,
                    )
                )
            except (OSError, SlicerError, ValueError) as error:
                raise unittest.SkipTest(
                    f"Konfigurierter {adapter.product_name} kann nicht verwendet "
                    f"werden ({executable}): {error}"
                ) from error

    result = SlicerDiscoveryService(adapters=(adapter,)).discover_installations(
        force=True
    )
    installation = next(
        (
            item
            for item in result.installations
            if item.adapter_id == adapter.adapter_id
        ),
        None,
    )
    if installation is None:
        details = "; ".join(result.diagnostics[:3])
        message = (
            f"{adapter.product_name} wurde nicht gefunden oder konnte nicht "
            "verifiziert werden; optionale reale Slicer-Abnahme übersprungen."
        )
        if details:
            message += f" Details: {details}"
        raise unittest.SkipTest(message)
    return installation
