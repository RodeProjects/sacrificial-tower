from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping

from cooling_tower.models.gcode_metadata import SlicerFamily
from cooling_tower.slicers.profile_models import (
    PROFILE_MAPPING_SCHEMA_VERSION,
    ConfirmedProfileMapping,
    ProfileBundleMatch,
    ProfileMatchResult,
    stable_json_fingerprint,
)


def compatible_version_range(version: str | None) -> str:
    components = re.findall(r"\d+", version or "")
    if len(components) >= 2:
        return f"{components[0]}.{components[1]}.*"
    if components:
        return f"{components[0]}.*"
    return "unknown"


def profile_mapping_key(
    family: SlicerFamily,
    version: str | None,
    source_profile_fingerprint: str | None,
    source_critical_fingerprint: str,
) -> str:
    return stable_json_fingerprint(
        {
            "family": family.value,
            "version_compatibility": compatible_version_range(version),
            "source_profile_fingerprint": source_profile_fingerprint,
            "source_critical_fingerprint": source_critical_fingerprint,
        }
    )


class ProfileMappingStore:
    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)

    def confirm(self, result: ProfileMatchResult) -> ConfirmedProfileMapping:
        if result.selected is None:
            raise ValueError("Es ist keine Profilkombination ausgewählt.")
        selected = result.selected
        mapping_key = profile_mapping_key(
            result.execution_slicer.family,
            result.execution_slicer.version,
            result.source_profile_fingerprint,
            result.source_critical_fingerprint or "",
        )
        mapping = ConfirmedProfileMapping(
            mapping_key=mapping_key,
            slicer_family=result.execution_slicer.family,
            version_compatibility=compatible_version_range(
                result.execution_slicer.version
            ),
            source_profile_fingerprint=result.source_profile_fingerprint,
            source_critical_fingerprint=(
                result.source_critical_fingerprint or ""
            ),
            machine_profile_id=(
                selected.machine.profile_id if selected.machine else None
            ),
            process_profile_id=(
                selected.process.profile_id if selected.process else None
            ),
            filament_profile_ids=tuple(
                item.profile_id
                for item in selected.effective_profile.filaments
            ),
            confirmed_utc=datetime.now(timezone.utc).isoformat(),
        )
        payload = self._read()
        mappings = payload.setdefault("mappings", {})
        mappings[mapping.mapping_key] = mapping.to_dict()
        self._write(payload)
        return mapping

    def find(
        self,
        *,
        family: SlicerFamily,
        version: str | None,
        source_profile_fingerprint: str | None,
        source_critical_fingerprint: str,
    ) -> ConfirmedProfileMapping | None:
        key = profile_mapping_key(
            family,
            version,
            source_profile_fingerprint,
            source_critical_fingerprint,
        )
        payload = self._read()
        raw = payload.get("mappings", {}).get(key)
        if not isinstance(raw, Mapping):
            return None
        try:
            return ConfirmedProfileMapping(
                mapping_key=str(raw["mapping_key"]),
                slicer_family=SlicerFamily(str(raw["slicer_family"])),
                version_compatibility=str(raw["version_compatibility"]),
                source_profile_fingerprint=(
                    str(raw["source_profile_fingerprint"])
                    if raw.get("source_profile_fingerprint") is not None
                    else None
                ),
                source_critical_fingerprint=str(
                    raw["source_critical_fingerprint"]
                ),
                machine_profile_id=(
                    str(raw["machine_profile_id"])
                    if raw.get("machine_profile_id") is not None
                    else None
                ),
                process_profile_id=(
                    str(raw["process_profile_id"])
                    if raw.get("process_profile_id") is not None
                    else None
                ),
                filament_profile_ids=tuple(
                    str(item) for item in raw.get("filament_profile_ids", ())
                ),
                confirmed_utc=str(raw["confirmed_utc"]),
            )
        except (KeyError, TypeError, ValueError):
            return None

    @staticmethod
    def bundle_matches_mapping(
        bundle: ProfileBundleMatch,
        mapping: ConfirmedProfileMapping,
    ) -> bool:
        machine_id = bundle.machine.profile_id if bundle.machine else None
        process_id = bundle.process.profile_id if bundle.process else None
        filament_ids = tuple(
            item.profile_id for item in bundle.effective_profile.filaments
        )
        return (
            machine_id == mapping.machine_profile_id
            and process_id == mapping.process_profile_id
            and filament_ids == mapping.filament_profile_ids
        )

    def _read(self) -> dict[str, Any]:
        if not self.path.is_file():
            return {
                "schema_version": PROFILE_MAPPING_SCHEMA_VERSION,
                "mappings": {},
            }
        try:
            payload = json.loads(self.path.read_text(encoding="utf-8"))
            if (
                not isinstance(payload, dict)
                or int(payload.get("schema_version", 0))
                != PROFILE_MAPPING_SCHEMA_VERSION
            ):
                raise ValueError("Das Zuordnungsschema wird nicht unterstützt.")
            if not isinstance(payload.get("mappings"), dict):
                payload["mappings"] = {}
            return payload
        except (OSError, ValueError, TypeError, json.JSONDecodeError):
            return {
                "schema_version": PROFILE_MAPPING_SCHEMA_VERSION,
                "mappings": {},
            }

    def _write(self, payload: Mapping[str, Any]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.path.with_suffix(self.path.suffix + ".tmp")
        temporary.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        temporary.replace(self.path)
