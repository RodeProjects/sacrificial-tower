from __future__ import annotations

import hashlib
from copy import deepcopy
from pathlib import Path
from typing import Any, Mapping

from cooling_tower.persistence.versioned_json import VersionedJsonStore
from cooling_tower.settings_compatibility import (
    RULE_BY_ID,
    SettingMergeResult,
    compatible_changes_between,
    merge_compatible_setting_changes,
    setting_value,
)


DOWNGRADE_JOURNAL_SCHEMA_VERSION = 1


def _normalize_journal(payload: dict[str, Any]) -> dict[str, Any]:
    protected_sha256 = payload.get("protected_sha256")
    if (
        not isinstance(protected_sha256, str)
        or len(protected_sha256) != 64
        or any(character not in "0123456789abcdef" for character in protected_sha256)
    ):
        raise ValueError("Das Downgrade-Journal enthält keinen gültigen Datei-Hash.")

    protected_schema = payload.get("protected_settings_schema_version")
    if (
        isinstance(protected_schema, bool)
        or not isinstance(protected_schema, int)
        or protected_schema < 1
    ):
        raise ValueError("Das Downgrade-Journal enthält keine gültige Schema-Version.")

    next_revision = payload.get("next_revision", 1)
    if isinstance(next_revision, bool) or not isinstance(next_revision, int) or next_revision < 1:
        raise ValueError("Das Downgrade-Journal enthält keine gültige Revision.")

    status = payload.get("status", "active")
    if status not in {"active", "applied"}:
        raise ValueError("Das Downgrade-Journal enthält keinen gültigen Status.")

    raw_changes = payload.get("changes", {})
    if not isinstance(raw_changes, Mapping):
        raise ValueError("Das Downgrade-Journal enthält keine gültigen Änderungen.")
    changes: dict[str, dict[str, object]] = {}
    for stable_id, raw_entry in raw_changes.items():
        if not isinstance(stable_id, str) or not isinstance(raw_entry, Mapping):
            raise ValueError("Das Downgrade-Journal enthält eine ungültige Änderung.")
        token = raw_entry.get("token")
        revision = raw_entry.get("revision")
        if (
            not isinstance(token, str)
            or not token
            or isinstance(revision, bool)
            or not isinstance(revision, int)
            or revision < 1
            or "value" not in raw_entry
        ):
            raise ValueError("Das Downgrade-Journal enthält eine ungültige Änderung.")
        changes[stable_id] = {
            "token": token,
            "revision": revision,
            "value": deepcopy(raw_entry["value"]),
        }

    normalized: dict[str, Any] = {
        "downgrade_journal_schema_version": DOWNGRADE_JOURNAL_SCHEMA_VERSION,
        "protected_sha256": protected_sha256,
        "protected_settings_schema_version": protected_schema,
        "next_revision": next_revision,
        "status": status,
        "changes": changes,
    }
    applied_schema = payload.get("applied_settings_schema_version")
    if (
        status == "applied"
        and isinstance(applied_schema, int)
        and not isinstance(applied_schema, bool)
        and applied_schema >= 1
    ):
        normalized["applied_settings_schema_version"] = applied_schema
        normalized["accepted_ids"] = sorted(
            value for value in payload.get("accepted_ids", []) if isinstance(value, str)
        )
        normalized["rejected_ids"] = sorted(
            value for value in payload.get("rejected_ids", []) if isinstance(value, str)
        )
    return normalized


class DowngradeSettingsJournal:
    """Persist safe setting changes while a newer settings file is protected."""

    def __init__(self, settings_path: str | Path) -> None:
        source = Path(settings_path)
        self.path = source.with_name(f"{source.name}.downgrade-changes.json")
        self._store = VersionedJsonStore(
            self.path,
            schema_key="downgrade_journal_schema_version",
            current_version=DOWNGRADE_JOURNAL_SCHEMA_VERSION,
            normalizer=_normalize_journal,
            document_name="Das Downgrade-Änderungsjournal",
        )
        self._payload: dict[str, Any] | None = None

    @staticmethod
    def source_hash(source_bytes: bytes) -> str:
        return hashlib.sha256(source_bytes).hexdigest()

    def load(self) -> dict[str, Any] | None:
        if not self.path.is_file():
            self._payload = None
            return None
        self._payload = self._store.load().payload
        return deepcopy(self._payload)

    def prepare(
        self,
        source_bytes: bytes,
        source_schema_version: int,
    ) -> dict[str, Any]:
        digest = self.source_hash(source_bytes)
        existing = self.load()
        if (
            existing is not None
            and existing.get("status") == "active"
            and existing.get("protected_sha256") == digest
            and existing.get("protected_settings_schema_version")
            == source_schema_version
        ):
            return existing

        initial = {
            "downgrade_journal_schema_version": DOWNGRADE_JOURNAL_SCHEMA_VERSION,
            "protected_sha256": digest,
            "protected_settings_schema_version": source_schema_version,
            "next_revision": 1,
            "status": "active",
            "changes": {},
        }
        if self.path.is_file():
            self._store.replace_with_recovery(initial)
        else:
            self._store.save(initial)
        self._payload = _normalize_journal(initial)
        return deepcopy(self._payload)

    def matches_source(self, source_bytes: bytes, *, active_only: bool = True) -> bool:
        payload = self._payload if self._payload is not None else self.load()
        if payload is None:
            return False
        if active_only and payload.get("status") != "active":
            return False
        return payload.get("protected_sha256") == self.source_hash(source_bytes)

    def apply_to(self, baseline_payload: Mapping[str, Any]) -> SettingMergeResult:
        payload = self._payload if self._payload is not None else self.load()
        changes = payload.get("changes", {}) if payload is not None else {}
        return merge_compatible_setting_changes(baseline_payload, changes)

    def record_changes(
        self,
        baseline_payload: Mapping[str, Any],
        candidate_payload: Mapping[str, Any],
    ) -> SettingMergeResult:
        if self._payload is None or self._payload.get("status") != "active":
            raise OSError("Das Downgrade-Änderungsjournal ist nicht aktiv.")

        desired = compatible_changes_between(baseline_payload, candidate_payload)
        desired_ids = set(desired.accepted_ids)
        existing = self._payload.get("changes", {})
        next_changes = {
            stable_id: deepcopy(entry)
            for stable_id, entry in existing.items()
            if stable_id not in RULE_BY_ID
        }
        next_revision = int(self._payload.get("next_revision", 1))

        for stable_id, rule in RULE_BY_ID.items():
            previous = existing.get(stable_id)
            if stable_id not in desired_ids:
                if isinstance(previous, Mapping) and previous.get("token") != rule.token:
                    next_changes[stable_id] = deepcopy(dict(previous))
                continue

            value = setting_value(desired.payload, stable_id)
            if (
                isinstance(previous, Mapping)
                and previous.get("token") == rule.token
                and previous.get("value") == value
            ):
                next_changes[stable_id] = deepcopy(dict(previous))
                continue
            next_changes[stable_id] = {
                "token": rule.token,
                "revision": next_revision,
                "value": deepcopy(value),
            }
            next_revision += 1

        updated = dict(self._payload)
        updated["changes"] = next_changes
        updated["next_revision"] = next_revision
        self._store.save(updated)
        self._payload = _normalize_journal(updated)
        return self.apply_to(baseline_payload)

    def mark_applied(
        self,
        *,
        target_schema_version: int,
        accepted_ids: tuple[str, ...],
        rejected_ids: tuple[str, ...],
    ) -> None:
        if self._payload is None:
            raise OSError("Das Downgrade-Änderungsjournal wurde nicht geladen.")
        updated = dict(self._payload)
        updated.update(
            {
                "status": "applied",
                "applied_settings_schema_version": target_schema_version,
                "accepted_ids": list(accepted_ids),
                "rejected_ids": list(rejected_ids),
            }
        )
        self._store.save(updated)
        self._payload = _normalize_journal(updated)
