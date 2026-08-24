from __future__ import annotations

import csv
import math
import re
from dataclasses import dataclass
from pathlib import Path

from cooling_tower.gcode.parser import ParsedGCodeLine
from cooling_tower.models.gcode_metadata import (
    ConfigValueItem,
    GCodeMetadata,
    MetadataSourceKind,
    MetadataValue,
    SlicerDetectionConfidence,
    SlicerFamily,
    SlicerIdentity,
    TypedConfigValue,
    build_profile_fingerprint,
)
from cooling_tower.models.timing import TimingEvidence


_CONFIG_ENTRY_PATTERN = re.compile(
    r"^\s*(?P<key>[A-Za-z_][A-Za-z0-9_.-]*)\s*"
    r"(?P<separator>=|:)\s*(?P<value>.*)\s*$",
    re.ASCII,
)
_NUMBER_WITH_UNIT_PATTERN = re.compile(
    r"^(?P<number>[+-]?(?:\d+(?:\.\d*)?|\.\d+)"
    r"(?:[eE][+-]?\d+)?)\s*"
    r"(?P<unit>%|mm(?:/s(?:\^?2|²)?)?|mm(?:3|³)/s|s|°C)?$",
    re.IGNORECASE,
)
_EXPLICIT_GENERATOR_PATTERN = re.compile(
    r"(?:generated\s+(?:by|with)|sliced\s+by)",
    re.IGNORECASE,
)
_VERSION_PATTERN = re.compile(
    r"(?:\s+version\s+|\s+v|[-\s]+)"
    r"(?P<version>\d+(?:[._-]\d+)+(?:[+A-Za-z0-9._-]*)?)",
    re.IGNORECASE,
)


@dataclass(frozen=True, slots=True)
class _SlicerPattern:
    expression: re.Pattern[str]
    product_name: str
    family: SlicerFamily
    adapter_id: str


_SLICER_PATTERNS = (
    _SlicerPattern(
        re.compile(r"AnycubicSlicerNext", re.IGNORECASE),
        "AnycubicSlicerNext",
        SlicerFamily.ORCA_BAMBU_ANYCUBIC,
        "anycubic_slicer_next",
    ),
    _SlicerPattern(
        re.compile(r"AnycubicSlicer", re.IGNORECASE),
        "AnycubicSlicer",
        SlicerFamily.ORCA_BAMBU_ANYCUBIC,
        "anycubic_slicer",
    ),
    _SlicerPattern(
        re.compile(r"OrcaSlicer", re.IGNORECASE),
        "OrcaSlicer",
        SlicerFamily.ORCA_BAMBU_ANYCUBIC,
        "orca_slicer",
    ),
    _SlicerPattern(
        re.compile(r"Bambu\s*Studio", re.IGNORECASE),
        "Bambu Studio",
        SlicerFamily.ORCA_BAMBU_ANYCUBIC,
        "bambu_studio",
    ),
    _SlicerPattern(
        re.compile(r"PrusaSlicer", re.IGNORECASE),
        "PrusaSlicer",
        SlicerFamily.PRUSA_SLIC3R,
        "prusa_slicer",
    ),
    _SlicerPattern(
        re.compile(r"SuperSlicer", re.IGNORECASE),
        "SuperSlicer",
        SlicerFamily.PRUSA_SLIC3R,
        "super_slicer",
    ),
    _SlicerPattern(
        re.compile(r"Slic3r", re.IGNORECASE),
        "Slic3r",
        SlicerFamily.PRUSA_SLIC3R,
        "slic3r",
    ),
    _SlicerPattern(
        re.compile(r"Cura(?:_SteamEngine|Engine)?", re.IGNORECASE),
        "Cura",
        SlicerFamily.CURA,
        "cura",
    ),
    _SlicerPattern(
        re.compile(r"ideaMaker", re.IGNORECASE),
        "ideaMaker",
        SlicerFamily.IDEAMAKER,
        "ideamaker",
    ),
    _SlicerPattern(
        re.compile(r"Simplify3D(?:\(R\))?", re.IGNORECASE),
        "Simplify3D",
        SlicerFamily.SIMPLIFY3D,
        "simplify3d",
    ),
)

_RECOGNIZED_STANDALONE_CONFIG_KEYS = {
    "bed_shape",
    "extruder_count",
    "extrusion_multiplier",
    "filament_diameter",
    "filament_flow_ratio",
    "filament_settings_id",
    "filament_type",
    "flavor",
    "gcode_flavor",
    "layer_height",
    "max_print_height",
    "max_volumetric_speed",
    "nozzle_diameter",
    "print_settings_id",
    "printable_area",
    "printer_model",
    "printer_settings_id",
    "printer_technology",
    "printer_variant",
}
_KNOWN_STRING_LIST_KEYS = {
    "bed_shape",
    "compatible_printers",
    "filament_settings_id",
    "inherits_group",
    "printable_area",
}
_FEATURE_SPEED_KEYS = {
    "inner_wall_speed",
    "outer_wall_speed",
    "small_perimeter_speed",
    "sparse_infill_speed",
    "support_speed",
    "top_surface_speed",
    "travel_speed",
}
_COOLING_KEYS = {
    "fan_cooling_layer_time",
    "min_print_speed",
    "slow_down_for_layer_cooling",
    "slow_down_layer_time",
    "slow_down_min_speed",
    "slowdown_below_layer_time",
}


def _confidence_rank(confidence: SlicerDetectionConfidence) -> int:
    return {
        SlicerDetectionConfidence.UNKNOWN: 0,
        SlicerDetectionConfidence.WEAK_SIGNATURE: 1,
        SlicerDetectionConfidence.STRONG_SIGNATURE: 2,
        SlicerDetectionConfidence.EXPLICIT: 3,
    }[confidence]


def _strip_matching_quotes(value: str) -> tuple[str, bool]:
    stripped = value.strip()
    if (
        len(stripped) >= 2
        and stripped[0] == stripped[-1]
        and stripped[0] in {'"', "'"}
    ):
        return stripped[1:-1], True
    return stripped, False


def _parse_config_atom(value: str) -> ConfigValueItem:
    stripped, quoted = _strip_matching_quotes(value)
    if quoted:
        return ConfigValueItem(stripped, quoted=True)
    lowered = stripped.lower()
    if lowered == "true":
        return ConfigValueItem(True)
    if lowered == "false":
        return ConfigValueItem(False)
    numeric = _NUMBER_WITH_UNIT_PATTERN.fullmatch(stripped)
    if numeric is None:
        return ConfigValueItem(stripped)
    number_text = numeric.group("number")
    unit = numeric.group("unit")
    number: int | float
    if (
        "." not in number_text
        and "e" not in number_text.lower()
    ):
        number = int(number_text)
    else:
        number = float(number_text)
        if not math.isfinite(number):
            raise ValueError("Numeric configuration value must be finite.")
    return ConfigValueItem(number, unit=unit)


def _csv_split(raw_value: str, delimiter: str) -> list[str]:
    # Validate quoting with the standard parser first. The conservative split
    # below deliberately retains quote characters so a quoted numeric ID such
    # as "001" cannot silently become the integer 1.
    next(
        csv.reader(
            [raw_value],
            delimiter=delimiter,
            quotechar='"',
            skipinitialspace=False,
            strict=True,
        )
    )
    tokens: list[str] = []
    token: list[str] = []
    in_quotes = False
    index = 0
    while index < len(raw_value):
        character = raw_value[index]
        if character == '"':
            token.append(character)
            if (
                in_quotes
                and index + 1 < len(raw_value)
                and raw_value[index + 1] == '"'
            ):
                token.append(raw_value[index + 1])
                index += 2
                continue
            in_quotes = not in_quotes
        elif character == delimiter and not in_quotes:
            tokens.append("".join(token))
            token = []
        else:
            token.append(character)
        index += 1
    tokens.append("".join(token))
    return tokens


def parse_typed_config_value(
    key: str,
    raw_value: str,
    *,
    source_line: int | None,
) -> TypedConfigValue:
    """Conservatively type a slicer value while preserving its raw text."""
    normalized_key = key.strip().lower()
    try:
        if ";" in raw_value:
            tokens = _csv_split(raw_value, ";")
            return TypedConfigValue(
                key=normalized_key,
                raw_value=raw_value,
                items=tuple(_parse_config_atom(token) for token in tokens),
                source_line=source_line,
                separator=";",
            )

        if "," in raw_value:
            tokens = _csv_split(raw_value, ",")
            parsed = tuple(_parse_config_atom(token) for token in tokens)
            is_typed_list = all(
                not isinstance(item.value, str) for item in parsed
            )
            if is_typed_list or normalized_key in _KNOWN_STRING_LIST_KEYS:
                return TypedConfigValue(
                    key=normalized_key,
                    raw_value=raw_value,
                    items=parsed,
                    source_line=source_line,
                    separator=",",
                )

        return TypedConfigValue(
            key=normalized_key,
            raw_value=raw_value,
            items=(_parse_config_atom(raw_value),),
            source_line=source_line,
        )
    except (csv.Error, ValueError) as error:
        return TypedConfigValue(
            key=normalized_key,
            raw_value=raw_value,
            items=(ConfigValueItem(raw_value),),
            source_line=source_line,
            valid=False,
            error=str(error),
        )


def _slicer_from_text(
    text: str,
    *,
    line_number: int | None,
    confidence: SlicerDetectionConfidence,
) -> SlicerIdentity | None:
    for pattern in _SLICER_PATTERNS:
        match = pattern.expression.search(text)
        if match is None:
            continue
        version_match = _VERSION_PATTERN.search(text, match.end())
        return SlicerIdentity(
            product_name=pattern.product_name,
            version=(
                version_match.group("version")
                if version_match is not None
                else None
            ),
            family=pattern.family,
            adapter_id=pattern.adapter_id,
            confidence=confidence,
            source_line=line_number,
        )
    return None


class GCodeMetadataCollector:
    """Streaming metadata and timing-evidence collector."""

    def __init__(self, source_path: str | Path) -> None:
        self.source_path = Path(source_path)
        self._values: list[MetadataValue] = []
        self._typed_config: list[TypedConfigValue] = []
        self._captured_standalone_config_keys: set[str] = set()
        self._captured_block_config_keys: set[str] = set()
        self._slicer = SlicerIdentity()
        self._in_config_block = False
        self._acceleration_commands_seen = False
        self._firmware_limits_seen = False
        self._junction_model_known = False
        self._machine_hints_seen: set[str] = set()

        filename_identity = _slicer_from_text(
            self.source_path.stem,
            line_number=None,
            confidence=SlicerDetectionConfidence.WEAK_SIGNATURE,
        )
        if filename_identity is not None:
            self._consider_slicer(filename_identity)
            self._values.append(
                MetadataValue(
                    key="slicer_filename_hint",
                    value=filename_identity.product_name or "unknown",
                    source_kind=MetadataSourceKind.FILENAME_HINT,
                    source_line=None,
                    explicit=False,
                )
            )

    def consume(self, parsed_line: ParsedGCodeLine) -> None:
        self._consume_command(parsed_line)
        comment = parsed_line.comment
        if not comment:
            return

        explicit_confidence = (
            SlicerDetectionConfidence.EXPLICIT
            if _EXPLICIT_GENERATOR_PATTERN.search(comment)
            else SlicerDetectionConfidence.STRONG_SIGNATURE
        )
        identity = _slicer_from_text(
            comment,
            line_number=parsed_line.number,
            confidence=explicit_confidence,
        )
        if identity is not None:
            self._consider_slicer(identity)
            source_kind = (
                MetadataSourceKind.HEADER_COMMENT
                if explicit_confidence
                is SlicerDetectionConfidence.EXPLICIT
                else MetadataSourceKind.BEHAVIORAL_SIGNATURE
            )
            self._append_unique_value(
                MetadataValue(
                    key="generator_name",
                    value=identity.product_name or "unknown",
                    source_kind=source_kind,
                    source_line=parsed_line.number,
                    explicit=(
                        explicit_confidence
                        is SlicerDetectionConfidence.EXPLICIT
                    ),
                )
            )
            if identity.version is not None:
                self._append_unique_value(
                    MetadataValue(
                        key="generator_version",
                        value=identity.version,
                        source_kind=source_kind,
                        source_line=parsed_line.number,
                        explicit=(
                            explicit_confidence
                            is SlicerDetectionConfidence.EXPLICIT
                        ),
                    )
                )

        config_match = _CONFIG_ENTRY_PATTERN.fullmatch(comment)
        if config_match is None:
            return
        key = config_match.group("key")
        normalized_key = key.lower()
        raw_value = config_match.group("value").strip()
        lowered_value = raw_value.lower()

        if normalized_key == "config_block_start":
            self._in_config_block = True
            return
        if normalized_key == "config_block_end":
            self._in_config_block = False
            return
        if normalized_key.endswith("slicer_config"):
            if lowered_value == "begin":
                self._in_config_block = True
            elif lowered_value == "end":
                self._in_config_block = False
            return

        should_capture = (
            self._in_config_block
            or normalized_key in _RECOGNIZED_STANDALONE_CONFIG_KEYS
        )
        if not should_capture:
            return

        if self._in_config_block:
            # A delimited slicer configuration is authoritative. It may occur
            # after a short standalone header, so block values must still be
            # allowed to supersede an earlier declaration.
            self._captured_block_config_keys.add(normalized_key)
        else:
            # Standalone keys are header metadata, not a stream of runtime
            # telemetry. Bambu Studio repeats ``LAYER_HEIGHT`` at every layer
            # and its accumulated Z arithmetic can render values such as
            # 0.179993 or 0.180008 for a nominal 0.18 mm profile. Retaining
            # those repetitions would replace the exact profile value and
            # corrupt both matching and the post-slice safety check.
            if (
                normalized_key in self._captured_standalone_config_keys
                or normalized_key in self._captured_block_config_keys
            ):
                return
            self._captured_standalone_config_keys.add(normalized_key)

        source_kind = (
            MetadataSourceKind.FOOTER_CONFIG
            if self._in_config_block
            else MetadataSourceKind.HEADER_COMMENT
        )
        typed = parse_typed_config_value(
            normalized_key,
            raw_value,
            source_line=parsed_line.number,
        )
        self._typed_config.append(typed)
        self._values.append(
            MetadataValue(
                key=normalized_key,
                value=raw_value,
                source_kind=source_kind,
                source_line=parsed_line.number,
                explicit=True,
            )
        )

    def _consume_command(self, parsed_line: ParsedGCodeLine) -> None:
        command = (parsed_line.command or "").upper()
        if command == "M201":
            self._firmware_limits_seen = True
            self._append_machine_hint(command, parsed_line.number)
        elif command == "M204":
            self._acceleration_commands_seen = True
            self._append_machine_hint(command, parsed_line.number)
        elif command == "M205":
            self._junction_model_known = True
            self._append_machine_hint(command, parsed_line.number)
        elif command == "SET_VELOCITY_LIMIT":
            if "ACCEL" in parsed_line.parameters:
                self._acceleration_commands_seen = True
            if "SQUARE_CORNER_VELOCITY" in parsed_line.parameters:
                self._junction_model_known = True
            self._append_machine_hint(command, parsed_line.number)

    def _append_machine_hint(self, command: str, line_number: int) -> None:
        if command in self._machine_hints_seen:
            return
        self._machine_hints_seen.add(command)
        self._values.append(
            MetadataValue(
                key="machine_command",
                value=command,
                source_kind=MetadataSourceKind.MACHINE_COMMAND,
                source_line=line_number,
                explicit=False,
            )
        )

    def _append_unique_value(self, value: MetadataValue) -> None:
        for current in self._values:
            if current.key == value.key and current.value == value.value:
                return
        self._values.append(value)

    def _consider_slicer(self, identity: SlicerIdentity) -> None:
        if _confidence_rank(identity.confidence) > _confidence_rank(
            self._slicer.confidence
        ):
            self._slicer = identity

    def finish(self) -> tuple[GCodeMetadata, TimingEvidence]:
        normalized_keys = {
            config.key.lower() for config in self._typed_config
        }
        firmware_limits = self._firmware_limits_seen or any(
            key.startswith("machine_max_acceleration")
            for key in normalized_keys
        )
        feature_speeds = bool(normalized_keys & _FEATURE_SPEED_KEYS)
        cooling_known = bool(normalized_keys & _COOLING_KEYS) or any(
            key.startswith("slow_down_layer_time")
            or key.startswith("fan_cooling_layer_time")
            for key in normalized_keys
        )
        metadata = GCodeMetadata(
            values=tuple(self._values),
            typed_config=tuple(self._typed_config),
            slicer=self._slicer,
            profile_fingerprint=build_profile_fingerprint(
                self._typed_config
            ),
        )
        evidence = TimingEvidence.from_flags(
            acceleration_commands_seen=self._acceleration_commands_seen,
            firmware_limits_seen=firmware_limits,
            junction_model_known=self._junction_model_known,
            slicer_feature_speeds_known=feature_speeds,
            cooling_slowdown_known=cooling_known,
        )
        return metadata, evidence


def parse_gcode_metadata(
    parsed_lines: list[ParsedGCodeLine] | tuple[ParsedGCodeLine, ...],
    *,
    source_path: str | Path = "input.gcode",
) -> tuple[GCodeMetadata, TimingEvidence]:
    """Convenience wrapper for tests and already parsed short inputs."""
    collector = GCodeMetadataCollector(source_path)
    for parsed_line in parsed_lines:
        collector.consume(parsed_line)
    return collector.finish()
