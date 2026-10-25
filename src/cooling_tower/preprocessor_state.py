"""Physical flow state for inserted paths without changing timing dialects."""
from cooling_tower.gcode.parser import MachineStateTracker


class PreprocessorStateTracker(MachineStateTracker):
    def __init__(self, adapter_id):
        super().__init__()
        self.adapter_id = adapter_id

    def process_line(self, parsed):
        event = super().process_line(parsed)
        if parsed.command == "M221" and "S" in parsed.parameters:
            # Bambu uses M221 T... for soft endstops. A plain S command is
            # flow on every supported slicer; Marlin also permits tool T0.
            tool = parsed.parameters.get("T")
            if tool is None or tool == 0 and self.adapter_id == "prusa_slicer":
                self.state.extrusion_factor = parsed.parameters["S"] / 100.0
        return event
