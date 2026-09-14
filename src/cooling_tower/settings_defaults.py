"""Current product defaults, shared by GUI, CLI and domain constructors.

Historical migrations retain explicit historical values. This module only
defines defaults for a newly constructed current configuration.
"""
from __future__ import annotations

import json
from types import MappingProxyType
from cooling_tower.runtime_paths import RESOURCE_ROOT


_payload = json.loads((RESOURCE_ROOT / "config" / "default_settings.json").read_text(encoding="utf-8"))
GENERATION_DEFAULTS = MappingProxyType({
    key: value for key, value in _payload.items()
    if key not in {"settings_schema_version", "default_output_root", "setting_compatibility"}
})
