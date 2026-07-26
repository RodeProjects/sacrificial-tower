from __future__ import annotations

import json
import os
from enum import Enum
from pathlib import Path

from cooling_tower.runtime_paths import RESOURCE_ROOT


class DistributionChannel(str, Enum):
    STANDALONE = "standalone"
    MICROSOFT_STORE = "microsoft-store"

    @property
    def uses_sacrificial_tower_updates(self) -> bool:
        return self is DistributionChannel.STANDALONE


def detect_distribution_channel(
    *,
    resource_root: str | Path = RESOURCE_ROOT,
    environment: dict[str, str] | None = None,
) -> DistributionChannel:
    """Read immutable build metadata with an explicit test override."""

    values = os.environ if environment is None else environment
    override = values.get("COOLING_TOWER_DISTRIBUTION_CHANNEL", "").strip()
    raw_channel = override
    if not raw_channel:
        metadata_path = Path(resource_root) / "config" / "distribution.json"
        try:
            payload = json.loads(metadata_path.read_text(encoding="utf-8"))
            raw_channel = str(payload.get("channel", "")).strip()
        except (OSError, ValueError, TypeError, json.JSONDecodeError):
            raw_channel = ""
    try:
        return DistributionChannel(raw_channel or DistributionChannel.STANDALONE)
    except ValueError:
        return DistributionChannel.STANDALONE
