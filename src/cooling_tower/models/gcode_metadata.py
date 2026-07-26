from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Iterable, Mapping


METADATA_SCHEMA_VERSION = 1
PROFILE_FINGERPRINT_SCHEMA_VERSION = 1


class UnsupportedMetadataSchemaError(ValueError):
    """Raised when metadata was written by an unsupported newer schema."""


class MetadataSourceKind(str, Enum):
    HEADER_COMMENT = "header_comment"
    FOOTER_CONFIG = "footer_config"
    MACHINE_COMMAND = "machine_command"
    FILENAME_HINT = "filename_hint"
    BEHAVIORAL_SIGNATURE = "behavioral_signature"
    USER_CONFIRMATION = "user_confirmation"
    UNKNOWN = "unknown"


class SlicerFamily(str, Enum):
    PRUSA_SLIC3R = "prusa_slic3r"
    ORCA_BAMBU_ANYCUBIC = "orca_bambu_anycubic"
    CURA = "cura"
    IDEAMAKER = "ideamaker"
    SIMPLIFY3D = "simplify3d"
    OTHER = "other"
    UNKNOWN = "unknown"


class SlicerDetectionConfidence(str, Enum):
    EXPLICIT = "explicit"
    STRONG_SIGNATURE = "strong_signature"
    WEAK_SIGNATURE = "weak_signature"
    UNKNOWN = "unknown"


ConfigPrimitive = bool | int | float | str


@dataclass(frozen=True, slots=True)
class MetadataValue:
    """One G-code metadata value together with its exact provenance."""

    key: str
    value: str
    source_kind: MetadataSourceKind
    source_line: int | None
    explicit: bool

    def to_dict(self) -> dict[str, Any]:
        return {
            "key": self.key,
            "value": self.value,
            "source_kind": self.source_kind.value,
            "source_line": self.source_line,
            "explicit": self.explicit,
        }

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> "MetadataValue":
        source = payload.get("source_kind", MetadataSourceKind.UNKNOWN.value)
        try:
            source_kind = MetadataSourceKind(str(source))
        except ValueError:
            source_kind = MetadataSourceKind.UNKNOWN
        source_line = payload.get("source_line")
        return cls(
            key=str(payload.get("key", "unknown")),
            value=str(payload.get("value", "")),
            source_kind=source_kind,
            source_line=(
                int(source_line) if source_line is not None else None
            ),
            explicit=bool(payload.get("explicit", False)),
        )


@dataclass(frozen=True, slots=True)
class ConfigValueItem:
    """One typed scalar from a scalar or list-valued slicer setting."""

    value: ConfigPrimitive
    unit: str | None = None
    quoted: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "value": self.value,
            "unit": self.unit,
            "quoted": self.quoted,
        }

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> "ConfigValueItem":
        value = payload.get("value", "")
        if not isinstance(value, (bool, int, float, str)):
            value = str(value)
        unit = payload.get("unit")
        return cls(
            value=value,
            unit=str(unit) if unit is not None else None,
            quoted=bool(payload.get("quoted", False)),
        )


@dataclass(frozen=True, slots=True)
class TypedConfigValue:
    """A lossless raw slicer value plus its conservative typed form."""

    key: str
    raw_value: str
    items: tuple[ConfigValueItem, ...]
    source_line: int | None
    separator: str | None = None
    valid: bool = True
    error: str | None = None

    @property
    def value(self) -> ConfigPrimitive | tuple[ConfigPrimitive, ...]:
        values = tuple(item.value for item in self.items)
        if self.separator is None and len(values) == 1:
            return values[0]
        return values

    @property
    def units(self) -> str | None | tuple[str | None, ...]:
        units = tuple(item.unit for item in self.items)
        if self.separator is None and len(units) == 1:
            return units[0]
        return units

    def canonical_value(self) -> str:
        payload = {
            "items": [item.to_dict() for item in self.items],
            "separator": self.separator,
            "valid": self.valid,
        }
        return json.dumps(
            payload,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "key": self.key,
            "raw_value": self.raw_value,
            "items": [item.to_dict() for item in self.items],
            "source_line": self.source_line,
            "separator": self.separator,
            "valid": self.valid,
            "error": self.error,
        }

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> "TypedConfigValue":
        raw_items = payload.get("items", ())
        items = tuple(
            ConfigValueItem.from_dict(item)
            for item in raw_items
            if isinstance(item, Mapping)
        )
        if not items:
            raw_value = str(payload.get("raw_value", ""))
            items = (ConfigValueItem(raw_value),)
        source_line = payload.get("source_line")
        separator = payload.get("separator")
        error = payload.get("error")
        return cls(
            key=str(payload.get("key", "unknown")),
            raw_value=str(payload.get("raw_value", "")),
            items=items,
            source_line=(
                int(source_line) if source_line is not None else None
            ),
            separator=(
                str(separator) if separator is not None else None
            ),
            valid=bool(payload.get("valid", True)),
            error=str(error) if error is not None else None,
        )


@dataclass(frozen=True, slots=True)
class SlicerIdentity:
    """Reported or inferred source-slicer identity."""

    product_name: str | None = None
    version: str | None = None
    family: SlicerFamily = SlicerFamily.UNKNOWN
    adapter_id: str | None = None
    confidence: SlicerDetectionConfidence = (
        SlicerDetectionConfidence.UNKNOWN
    )
    source_line: int | None = None

    @property
    def is_explicit(self) -> bool:
        return self.confidence is SlicerDetectionConfidence.EXPLICIT

    def to_dict(self) -> dict[str, Any]:
        return {
            "product_name": self.product_name,
            "version": self.version,
            "family": self.family.value,
            "adapter_id": self.adapter_id,
            "confidence": self.confidence.value,
            "source_line": self.source_line,
        }

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> "SlicerIdentity":
        try:
            family = SlicerFamily(
                str(payload.get("family", SlicerFamily.UNKNOWN.value))
            )
        except ValueError:
            family = SlicerFamily.UNKNOWN
        try:
            confidence = SlicerDetectionConfidence(
                str(
                    payload.get(
                        "confidence",
                        SlicerDetectionConfidence.UNKNOWN.value,
                    )
                )
            )
        except ValueError:
            confidence = SlicerDetectionConfidence.UNKNOWN
        source_line = payload.get("source_line")
        return cls(
            product_name=(
                str(payload["product_name"])
                if payload.get("product_name") is not None
                else None
            ),
            version=(
                str(payload["version"])
                if payload.get("version") is not None
                else None
            ),
            family=family,
            adapter_id=(
                str(payload["adapter_id"])
                if payload.get("adapter_id") is not None
                else None
            ),
            confidence=confidence,
            source_line=(
                int(source_line) if source_line is not None else None
            ),
        )


@dataclass(frozen=True, slots=True)
class ProfileFingerprint:
    """Stable hash over effective timing-relevant profile values."""

    schema_version: int = PROFILE_FINGERPRINT_SCHEMA_VERSION
    digest_sha256: str | None = None
    values: tuple[tuple[str, str], ...] = ()

    @property
    def is_empty(self) -> bool:
        return not self.values

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "digest_sha256": self.digest_sha256,
            "values": [
                {"key": key, "canonical_value": value}
                for key, value in self.values
            ],
        }

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> "ProfileFingerprint":
        schema_version = int(
            payload.get(
                "schema_version",
                PROFILE_FINGERPRINT_SCHEMA_VERSION,
            )
        )
        if schema_version > PROFILE_FINGERPRINT_SCHEMA_VERSION:
            raise UnsupportedMetadataSchemaError(
                "Unsupported profile fingerprint schema version "
                f"{schema_version}; maximum supported version is "
                f"{PROFILE_FINGERPRINT_SCHEMA_VERSION}."
            )
        raw_values = payload.get("values", ())
        values: list[tuple[str, str]] = []
        for item in raw_values:
            if isinstance(item, Mapping):
                values.append(
                    (
                        str(item.get("key", "")),
                        str(item.get("canonical_value", "")),
                    )
                )
            elif isinstance(item, (list, tuple)) and len(item) == 2:
                values.append((str(item[0]), str(item[1])))
        return cls(
            schema_version=schema_version,
            digest_sha256=(
                str(payload["digest_sha256"])
                if payload.get("digest_sha256") is not None
                else None
            ),
            values=tuple(sorted(values)),
        )


_FINGERPRINT_EXACT_KEYS = {
    "bed_shape",
    "extruder_count",
    "extrusion_multiplier",
    "filament_diameter",
    "filament_flow_ratio",
    "gcode_flavor",
    "layer_height",
    "max_layer_height",
    "max_print_height",
    "max_volumetric_speed",
    "nozzle_diameter",
    "printable_area",
    "printer_model",
    "printer_technology",
    "printer_variant",
    "slow_down_layer_time",
    "slowdown_below_layer_time",
}
_FINGERPRINT_KEY_FRAGMENTS = (
    "acceleration",
    "jerk",
    "line_width",
    "min_print_speed",
    "speed",
    "volumetric",
)


def is_fingerprint_key(key: str) -> bool:
    normalized = key.strip().lower()
    return normalized in _FINGERPRINT_EXACT_KEYS or any(
        fragment in normalized
        for fragment in _FINGERPRINT_KEY_FRAGMENTS
    )


def build_profile_fingerprint(
    config_values: Iterable[TypedConfigValue],
) -> ProfileFingerprint:
    latest: dict[str, TypedConfigValue] = {}
    for config in config_values:
        normalized = config.key.strip().lower()
        if config.valid and is_fingerprint_key(normalized):
            latest[normalized] = config
    values = tuple(
        sorted(
            (
                key,
                config.canonical_value(),
            )
            for key, config in latest.items()
        )
    )
    if not values:
        return ProfileFingerprint()
    canonical = json.dumps(
        values,
        ensure_ascii=False,
        separators=(",", ":"),
    ).encode("utf-8")
    return ProfileFingerprint(
        digest_sha256=hashlib.sha256(canonical).hexdigest(),
        values=values,
    )


@dataclass(frozen=True, slots=True)
class GCodeMetadata:
    """Versioned metadata collected without claiming inferred facts."""

    schema_version: int = METADATA_SCHEMA_VERSION
    values: tuple[MetadataValue, ...] = ()
    typed_config: tuple[TypedConfigValue, ...] = ()
    slicer: SlicerIdentity = field(default_factory=SlicerIdentity)
    profile_fingerprint: ProfileFingerprint = field(
        default_factory=ProfileFingerprint
    )

    def values_for(self, key: str) -> tuple[MetadataValue, ...]:
        normalized = key.strip().lower()
        return tuple(
            item for item in self.values
            if item.key.strip().lower() == normalized
        )

    def config_for(self, key: str) -> TypedConfigValue | None:
        normalized = key.strip().lower()
        for item in reversed(self.typed_config):
            if item.key.strip().lower() == normalized:
                return item
        return None

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "values": [value.to_dict() for value in self.values],
            "typed_config": [
                value.to_dict() for value in self.typed_config
            ],
            "slicer": self.slicer.to_dict(),
            "profile_fingerprint": self.profile_fingerprint.to_dict(),
        }

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> "GCodeMetadata":
        version = int(payload.get("schema_version", 0))
        if version > METADATA_SCHEMA_VERSION:
            raise UnsupportedMetadataSchemaError(
                "Unsupported G-code metadata schema version "
                f"{version}; maximum supported version is "
                f"{METADATA_SCHEMA_VERSION}."
            )
        if version == 0:
            return cls._from_legacy_dict(payload)

        values = tuple(
            MetadataValue.from_dict(item)
            for item in payload.get("values", ())
            if isinstance(item, Mapping)
        )
        typed = tuple(
            TypedConfigValue.from_dict(item)
            for item in payload.get("typed_config", ())
            if isinstance(item, Mapping)
        )
        raw_slicer = payload.get("slicer", {})
        slicer = (
            SlicerIdentity.from_dict(raw_slicer)
            if isinstance(raw_slicer, Mapping)
            else SlicerIdentity()
        )
        raw_fingerprint = payload.get("profile_fingerprint", {})
        fingerprint = (
            ProfileFingerprint.from_dict(raw_fingerprint)
            if isinstance(raw_fingerprint, Mapping)
            else build_profile_fingerprint(typed)
        )
        if fingerprint.is_empty and typed:
            fingerprint = build_profile_fingerprint(typed)
        return cls(
            values=values,
            typed_config=typed,
            slicer=slicer,
            profile_fingerprint=fingerprint,
        )

    @classmethod
    def _from_legacy_dict(
        cls,
        payload: Mapping[str, Any],
    ) -> "GCodeMetadata":
        values: list[MetadataValue] = []
        for legacy_key in (
            "generator_name",
            "generator_version",
            "printer_model",
            "printer_settings_id",
            "print_settings_id",
            "filament_settings_id",
        ):
            if payload.get(legacy_key) is not None:
                values.append(
                    MetadataValue(
                        key=legacy_key,
                        value=str(payload[legacy_key]),
                        source_kind=MetadataSourceKind.UNKNOWN,
                        source_line=None,
                        explicit=False,
                    )
                )

        typed: list[TypedConfigValue] = []
        legacy_config = payload.get("configuration", {})
        if isinstance(legacy_config, Mapping):
            for key, value in legacy_config.items():
                raw_value = str(value)
                typed.append(
                    TypedConfigValue(
                        key=str(key),
                        raw_value=raw_value,
                        items=(ConfigValueItem(raw_value),),
                        source_line=None,
                    )
                )

        product = payload.get("generator_name")
        version = payload.get("generator_version")
        slicer = SlicerIdentity(
            product_name=str(product) if product is not None else None,
            version=str(version) if version is not None else None,
            confidence=SlicerDetectionConfidence.UNKNOWN,
        )
        return cls(
            values=tuple(values),
            typed_config=tuple(typed),
            slicer=slicer,
            profile_fingerprint=build_profile_fingerprint(typed),
        )
