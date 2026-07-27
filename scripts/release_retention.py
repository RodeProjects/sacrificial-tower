from __future__ import annotations

import argparse
import json
import re
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, Mapping, Sequence


_VERSION_PATTERN = re.compile(r"^v?(\d+)\.(\d+)\.(\d+)$")


@dataclass(frozen=True, slots=True)
class RetentionPolicy:
    minimum_releases: int
    maximum_total_asset_size_bytes: int
    minimum_age_days: int
    protect_zero_patch_versions: bool
    protected_versions: frozenset[str]

    @classmethod
    def from_mapping(cls, values: Mapping[str, Any]) -> "RetentionPolicy":
        minimum_releases = _positive_int(values, "minimum_releases")
        maximum_size = _positive_int(
            values,
            "maximum_total_asset_size_bytes",
        )
        minimum_age_days = _non_negative_int(values, "minimum_age_days")
        protect_zero_patch = values.get("protect_zero_patch_versions")
        if not isinstance(protect_zero_patch, bool):
            raise ValueError(
                "protect_zero_patch_versions muss ein boolescher Wert sein."
            )
        raw_protected = values.get("protected_versions", [])
        if not isinstance(raw_protected, list) or not all(
            isinstance(value, str) and _normalized_version(value) is not None
            for value in raw_protected
        ):
            raise ValueError(
                "protected_versions muss ausschließlich x.y.z-Versionen enthalten."
            )
        return cls(
            minimum_releases=minimum_releases,
            maximum_total_asset_size_bytes=maximum_size,
            minimum_age_days=minimum_age_days,
            protect_zero_patch_versions=protect_zero_patch,
            protected_versions=frozenset(
                _normalized_version(value) for value in raw_protected
            ),
        )


@dataclass(frozen=True, slots=True)
class ReleaseRecord:
    release_id: int
    tag_name: str
    published_at: datetime
    asset_size_bytes: int
    draft: bool
    immutable: bool
    normalized_version: str | None
    patch_version: int | None

    @classmethod
    def from_mapping(cls, values: Mapping[str, Any]) -> "ReleaseRecord":
        release_id = values.get("id")
        tag_name = values.get("tag_name")
        draft = values.get("draft", False)
        immutable = values.get("immutable", False)
        published_at = values.get("published_at") or values.get("created_at")
        assets = values.get("assets", [])
        if isinstance(release_id, bool) or not isinstance(release_id, int):
            raise ValueError("Ein Release enthält keine gültige ID.")
        if not isinstance(tag_name, str) or not tag_name:
            raise ValueError("Ein Release enthält keinen gültigen Tag.")
        if not isinstance(draft, bool) or not isinstance(immutable, bool):
            raise ValueError("Ein Release enthält einen ungültigen Status.")
        if not isinstance(published_at, str):
            raise ValueError(f"Release {tag_name} enthält kein gültiges Datum.")
        if not isinstance(assets, list):
            raise ValueError(f"Release {tag_name} enthält keine gültige Asset-Liste.")
        total_size = 0
        for asset in assets:
            if not isinstance(asset, Mapping):
                raise ValueError(f"Release {tag_name} enthält ein ungültiges Asset.")
            size = asset.get("size")
            if isinstance(size, bool) or not isinstance(size, int) or size < 0:
                raise ValueError(
                    f"Release {tag_name} enthält eine ungültige Asset-Größe."
                )
            total_size += size

        version_parts = _version_parts(tag_name)
        return cls(
            release_id=release_id,
            tag_name=tag_name,
            published_at=_parse_timestamp(published_at),
            asset_size_bytes=total_size,
            draft=draft,
            immutable=immutable,
            normalized_version=(
                ".".join(str(part) for part in version_parts)
                if version_parts is not None
                else None
            ),
            patch_version=version_parts[2] if version_parts is not None else None,
        )


def plan_release_cleanup(
    releases: Sequence[Mapping[str, Any]],
    policy: RetentionPolicy,
    *,
    now: datetime,
    latest_version: str | None = None,
) -> dict[str, Any]:
    if now.tzinfo is None:
        raise ValueError("Der Auswertungszeitpunkt benötigt eine Zeitzone.")
    normalized_latest = (
        _normalized_version(latest_version) if latest_version else None
    )
    if latest_version and normalized_latest is None:
        raise ValueError("Die aktuelle Version muss dem Format x.y.z entsprechen.")

    records = sorted(
        (ReleaseRecord.from_mapping(release) for release in releases),
        key=lambda release: (release.published_at, release.release_id),
        reverse=True,
    )
    published = [release for release in records if not release.draft]
    newest_ids = {
        release.release_id
        for release in published[: policy.minimum_releases]
    }

    protected_reasons: dict[int, str] = {}
    for release in records:
        reason = _protection_reason(
            release,
            policy,
            newest_ids,
            normalized_latest,
        )
        if reason is not None:
            protected_reasons[release.release_id] = reason

    cutoff = now.astimezone(UTC) - timedelta(days=policy.minimum_age_days)
    deletions: list[tuple[ReleaseRecord, str]] = []
    deleted_ids: set[int] = set()
    for release in reversed(records):
        if release.release_id in protected_reasons:
            continue
        if release.published_at <= cutoff:
            deletions.append((release, "Mindestalter erreicht"))
            deleted_ids.add(release.release_id)

    total_before = sum(release.asset_size_bytes for release in records)
    total_after = total_before - sum(
        release.asset_size_bytes for release, _reason in deletions
    )
    capacity_cleanup_triggered = (
        total_before >= policy.maximum_total_asset_size_bytes
    )
    if capacity_cleanup_triggered and total_after >= policy.maximum_total_asset_size_bytes:
        for release in reversed(records):
            if (
                release.release_id in protected_reasons
                or release.release_id in deleted_ids
            ):
                continue
            deletions.append((release, "Speichergrenze erreicht"))
            deleted_ids.add(release.release_id)
            total_after -= release.asset_size_bytes
            if total_after < policy.maximum_total_asset_size_bytes:
                break

    deletions.sort(key=lambda item: item[0].published_at)
    return {
        "minimum_releases": policy.minimum_releases,
        "minimum_age_days": policy.minimum_age_days,
        "maximum_total_asset_size_bytes": (
            policy.maximum_total_asset_size_bytes
        ),
        "release_count_before": len(records),
        "release_count_after": len(records) - len(deletions),
        "total_asset_size_bytes_before": total_before,
        "total_asset_size_bytes_after": total_after,
        "capacity_cleanup_triggered": capacity_cleanup_triggered,
        "capacity_limit_satisfied": (
            total_after < policy.maximum_total_asset_size_bytes
        ),
        "delete": [
            {
                "id": release.release_id,
                "tag_name": release.tag_name,
                "published_at": release.published_at.isoformat(),
                "asset_size_bytes": release.asset_size_bytes,
                "reason": reason,
            }
            for release, reason in deletions
        ],
        "protected": [
            {
                "id": release.release_id,
                "tag_name": release.tag_name,
                "reason": protected_reasons[release.release_id],
            }
            for release in records
            if release.release_id in protected_reasons
        ],
    }


def _protection_reason(
    release: ReleaseRecord,
    policy: RetentionPolicy,
    newest_ids: set[int],
    latest_version: str | None,
) -> str | None:
    if release.draft:
        return "Entwurf"
    if release.immutable:
        return "unveränderliches Release"
    if release.release_id in newest_ids:
        return f"eines der neuesten {policy.minimum_releases} Releases"
    if release.normalized_version is None:
        return "nicht eindeutig versionierter Tag"
    if release.normalized_version == latest_version:
        return "aktuelle veröffentlichte Version"
    if release.normalized_version in policy.protected_versions:
        return "ausdrücklich geschützte Version"
    if policy.protect_zero_patch_versions and release.patch_version == 0:
        return "geschützte x.y.0-Version"
    return None


def _version_parts(value: str) -> tuple[int, int, int] | None:
    match = _VERSION_PATTERN.fullmatch(value.strip())
    if match is None:
        return None
    return int(match.group(1)), int(match.group(2)), int(match.group(3))


def _normalized_version(value: str) -> str | None:
    parts = _version_parts(value)
    if parts is None:
        return None
    return ".".join(str(part) for part in parts)


def _parse_timestamp(value: str) -> datetime:
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as error:
        raise ValueError(f"Ungültiger Release-Zeitstempel: {value}") from error
    if parsed.tzinfo is None:
        raise ValueError(f"Release-Zeitstempel ohne Zeitzone: {value}")
    return parsed.astimezone(UTC)


def _positive_int(values: Mapping[str, Any], key: str) -> int:
    value = values.get(key)
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        raise ValueError(f"{key} muss eine positive Ganzzahl sein.")
    return value


def _non_negative_int(values: Mapping[str, Any], key: str) -> int:
    value = values.get(key)
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise ValueError(f"{key} muss eine nicht negative Ganzzahl sein.")
    return value


def _read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8-sig"))


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Plant die sichere Bereinigung alter GitHub-Releases."
    )
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--releases", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--latest-version")
    parser.add_argument("--now")
    arguments = parser.parse_args()

    raw_policy = _read_json(arguments.config)
    raw_releases = _read_json(arguments.releases)
    if not isinstance(raw_policy, Mapping):
        raise ValueError("Die Aufbewahrungskonfiguration muss ein Objekt sein.")
    if not isinstance(raw_releases, list):
        raise ValueError("Die GitHub-Releases müssen als Liste vorliegen.")
    now = _parse_timestamp(arguments.now) if arguments.now else datetime.now(UTC)
    plan = plan_release_cleanup(
        raw_releases,
        RetentionPolicy.from_mapping(raw_policy),
        now=now,
        latest_version=arguments.latest_version,
    )
    arguments.output.parent.mkdir(parents=True, exist_ok=True)
    arguments.output.write_text(
        json.dumps(plan, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
