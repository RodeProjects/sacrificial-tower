"""Small stateful reader for firmware object names, without executing G-code."""
from __future__ import annotations
import math


class FirmwareObjectLabels:
    def __init__(self):
        self.names: dict[int, str] = {}
        self.active_index: int | None = None

    @property
    def active_name(self):
        return self.names.get(self.active_index)

    def consume(self, parsed) -> bool:
        if parsed.command != "M486":
            return False
        if "S" in parsed.parameters:
            index = parsed.parameters["S"]
            self.active_index = (int(index) if math.isfinite(index)
                                 and 0 <= index <= 2**31-1 and index == int(index) else None)
        _, marker, value = parsed.code_text.partition(" A")
        if marker and self.active_index is not None:
            self.names[self.active_index] = value.strip().strip('"')
        return True
