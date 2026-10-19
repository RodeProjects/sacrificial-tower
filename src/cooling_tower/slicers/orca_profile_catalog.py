"""Bounded, read-only Orca JSON catalogue, independent of other integrations."""
from __future__ import annotations

import json
from collections.abc import Iterator
from pathlib import Path
from typing import Any

from cooling_tower.slicers.errors import SlicerProcessError
from cooling_tower.slicers.models import ProfileKind, ProfileRecord, SlicerInstallation


class OrcaProfileCatalog:
    maximum_profile_bytes = 8 * 1024 * 1024
    maximum_profile_count = 50000

    def __init__(self) -> None:
        self._values: dict[Path, tuple[int, int, dict[str, Any]]] = {}

    def values(self, path: Path) -> dict[str, Any]:
        try:
            stat = path.stat()
            if stat.st_size > self.maximum_profile_bytes:
                return {}
            cached = self._values.get(path)
            if cached is not None and cached[:2] == (stat.st_size, stat.st_mtime_ns):
                return dict(cached[2])
            with path.open("rb") as handle:
                raw = handle.read(self.maximum_profile_bytes + 1)
            if len(raw) > self.maximum_profile_bytes:
                return {}
            payload = json.loads(raw.decode("utf-8-sig"))
            if not isinstance(payload, dict):
                return {}
            if len(self._values) >= self.maximum_profile_count:
                self._values.clear()
            self._values[path] = (stat.st_size, stat.st_mtime_ns, payload)
            return dict(payload)
        except (OSError, UnicodeError, ValueError, RecursionError):
            return {}

    def discover_profiles(self, installation: SlicerInstallation) -> list[ProfileRecord]:
        records: list[ProfileRecord] = []
        seen: set[Path] = set()
        for root in installation.profile_roots:
            try:
                root = root.resolve()
                exists = root.is_dir()
            except OSError:
                continue
            if not exists:
                continue
            for resolved in self._paths(root):
                path = resolved
                if resolved in seen:
                    continue
                seen.add(resolved)
                if len(seen) > self.maximum_profile_count:
                    raise SlicerProcessError(
                        "Der OrcaSlicer-Profilkatalog ist zu groß. "
                        "Bitte die Profilverzeichnisse prüfen."
                    )
                relative = resolved.relative_to(root)
                roles = [
                    part.casefold() for part in relative.parts[:-1]
                    if part.casefold() in {"machine", "process", "filament"}
                ]
                if len(roles) != 1:
                    continue
                kind = ProfileKind(roles[0])
                payload = self.values(resolved)
                if not payload:
                    continue
                declared = str(payload.get("type", "")).casefold()
                # Model descriptors, manifests and unrelated helper files do
                # not become presets merely because they are JSON.
                if declared and declared != kind.value:
                    continue
                if not declared and "name" not in payload and "inherits" not in payload:
                    continue
                name = payload.get("name", path.stem)
                if not isinstance(name, str) or not name.strip():
                    continue
                inherits = payload.get("inherits", ())
                if isinstance(inherits, str):
                    inherits = (inherits,) if inherits.strip() else ()
                if not isinstance(inherits, (tuple, list)) or any(
                    not isinstance(p, str) for p in inherits
                ):
                    continue
                user = root.name.casefold() == "user" or "user" in (
                    p.casefold() for p in relative.parts[:-2]
                )
                vendor = root.name if not user else ""
                metadata = {key: value for key, value in payload.items() if key in {
                    "type", "from", "version", "instantiation", "setting_id",
                    "printer_settings_id", "print_settings_id", "filament_settings_id",
                    "printer_model", "printer_variant", "printer_technology", "nozzle_diameter",
                    "gcode_flavor", "compatible_printers", "compatible_printers_condition",
                    "printable_area", "printable_height", "minimum_slicer_version", "maximum_slicer_version",
                }}
                metadata.update(
                    orca_vendor=vendor,
                    orca_active_catalogue=root.parent.name.casefold() == "system",
                )
                records.append(ProfileRecord(
                    adapter_id="orca_slicer", profile_id=name, name=name, kind=kind,
                    path=resolved, source="user" if user else "system",
                    inherits=tuple(inherits), metadata=metadata,
                ))
        # Prefer individual active-system presets; bundled missing parents
        # remain available. Distinct user presets never collapse by name.
        active_keys = {
            self._mirror_key(record) for record in records
            if record.metadata["orca_active_catalogue"]
        }
        return sorted(
            (record for record in records if record.source == "user"
             or record.metadata["orca_active_catalogue"]
             or self._mirror_key(record) not in active_keys),
            key=lambda record: (
                record.kind.value, record.name.casefold(), str(record.path)
            ),
        )

    @staticmethod
    def _paths(root: Path) -> Iterator[Path]:
        try:
            for path in root.rglob("*.json"):
                try:
                    resolved = path.resolve()
                except OSError:
                    continue
                if root in resolved.parents:
                    yield resolved
        except OSError:
            return

    @staticmethod
    def _mirror_key(record: ProfileRecord) -> tuple[str, ProfileKind, str]:
        return (
            str(record.metadata.get("orca_vendor", "")).casefold(),
            record.kind, record.name.casefold(),
        )

    @staticmethod
    def select_parents(
        candidates: tuple[ProfileRecord, ...], child: ProfileRecord,
    ) -> tuple[ProfileRecord, ...]:
        vendor = str(child.metadata.get("orca_vendor", "")).casefold()
        scoped = tuple(
            p for p in candidates
            if vendor and str(p.metadata.get("orca_vendor", "")).casefold() == vendor
        )
        if scoped:
            return scoped
        if child.source == "user":
            def account(path: Path) -> Path | None:
                return next(
                    (p for p in path.parents if p.parent.name.casefold() == "user"),
                    None,
                )
            own_account = account(child.path)
            same_account = tuple(
                p for p in candidates if own_account is not None
                and p.source == "user" and account(p.path) == own_account
            )
            if same_account:
                return same_account
            system = tuple(p for p in candidates if p.source == "system")
            if system:
                return system
        return candidates
