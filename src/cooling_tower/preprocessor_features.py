"""Slicer-viewer comments, isolated from the printer's modal machine state."""
from dataclasses import dataclass


@dataclass
class FeatureComments:
    adapter: str
    native: bool = False
    role: str = "Custom"
    width: str = "0"
    height: str = "0"
    wiping: bool = False

    @classmethod
    def for_adapter(cls, adapter):
        return cls(adapter, native=adapter == "bambu_studio")

    def observe(self, line):
        comment = line.partition(";")[2].strip()
        for tag, field, native in (("TYPE:", "role", False), ("FEATURE:", "role", True),
                ("WIDTH:", "width", False), ("LINE_WIDTH:", "width", True),
                ("HEIGHT:", "height", False), ("LAYER_HEIGHT:", "height", True)):
            if comment.startswith(tag):
                setattr(self, field, comment[len(tag):].strip())
                if field == "role":
                    self.native = native
                return
        if comment == "WIPE_START":
            self.wiping = True
        elif comment == "WIPE_END":
            self.wiping = False

    def wipe(self, active):
        return ";"+(" " if self.native else "")+("WIPE_START" if active else "WIPE_END")

    def describe(self, feature, width, height):
        roles = ({"outer": "External perimeter", "inner": "Perimeter", "bottom": "Solid infill",
            "solid": "Solid infill", "brim": "Skirt/Brim"} if self.adapter == "prusa_slicer" else
            {"outer": "Outer wall", "inner": "Inner wall", "bottom": "Bottom surface",
                "solid": "Internal solid infill", "brim": "Brim"})
        return self._tags(roles[feature], f"{width:.6f}", f"{height:.6f}")

    def _tags(self, role, width, height):
        prefixes = ("; FEATURE: ", "; LINE_WIDTH: ", "; LAYER_HEIGHT: ") if self.native else (";TYPE:", ";WIDTH:", ";HEIGHT:")
        return [prefix+value for prefix, value in zip(prefixes, (role, width, height))]

    def restore(self):
        return self._tags(self.role, self.width, self.height)+[self.wipe(self.wiping)]
