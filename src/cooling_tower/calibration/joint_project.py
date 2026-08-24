from __future__ import annotations

import io
import math
import re
import zipfile
from dataclasses import dataclass
from pathlib import Path
from xml.etree import ElementTree

import numpy as np
import trimesh

from cooling_tower.file_integrity import sha256_file
from cooling_tower.models import OccupiedBounds, TowerPlacement


MODEL_NAMESPACE = "http://schemas.microsoft.com/3dmanufacturing/core/2015/02"
MODEL_RELATIONSHIP_TYPE = (
    "http://schemas.microsoft.com/3dmanufacturing/2013/01/3dmodel"
)
MODEL_SETTINGS_PATH = "Metadata/model_settings.config"
TOWER_INFILL_KEY = "sparse_infill_density"
TOWER_INFILL_PATTERN_KEY = "sparse_infill_pattern"
TOWER_FULL_INFILL_PATTERN = "zig-zag"
RELATIONSHIP_NAMESPACE = (
    "http://schemas.openxmlformats.org/package/2006/relationships"
)
CONTENT_TYPES_NAMESPACE = (
    "http://schemas.openxmlformats.org/package/2006/content-types"
)
PRODUCTION_NAMESPACE = (
    "http://schemas.microsoft.com/3dmanufacturing/production/2015/06"
)
BAMBU_STUDIO_NAMESPACE = "http://schemas.bambulab.com/package/2021"


class JointProjectError(RuntimeError):
    """Raised when a fixed-position joint 3MF cannot be built or verified."""


@dataclass(frozen=True, slots=True)
class JointProjectResult:
    path: Path
    source_object_id: int
    tower_object_id: int
    source_translation_mm: tuple[float, float, float]
    tower_translation_mm: tuple[float, float, float]
    tower_full_infill: bool
    sha256: str
    slice_input_path: Path | None = None


def _load_mesh(path: Path) -> trimesh.Trimesh:
    loaded = trimesh.load(path, file_type="stl", force="mesh", process=False)
    if not isinstance(loaded, trimesh.Trimesh):
        raise JointProjectError(f"{path.name} enthält kein verwendbares STL-Mesh.")
    if loaded.vertices.size == 0 or loaded.faces.size == 0:
        raise JointProjectError(f"{path.name} enthält keine druckbare Geometrie.")
    if not np.isfinite(loaded.vertices).all():
        raise JointProjectError(f"{path.name} enthält ungültige Koordinaten.")
    return loaded


def _translation(
    mesh: trimesh.Trimesh,
    center_xy: tuple[float, float],
) -> tuple[float, float, float]:
    bounds = np.asarray(mesh.bounds, dtype=float)
    center = (bounds[0] + bounds[1]) / 2.0
    values = (
        float(center_xy[0] - center[0]),
        float(center_xy[1] - center[1]),
        float(-bounds[0, 2]),
    )
    if not all(math.isfinite(value) for value in values):
        raise JointProjectError("Die Objekttransformation ist nicht endlich.")
    return values


def _matrix(translation: tuple[float, float, float]) -> np.ndarray:
    matrix = np.eye(4, dtype=float)
    matrix[:3, 3] = translation
    return matrix


def _model_path(archive: zipfile.ZipFile) -> str:
    if "3D/3dmodel.model" in archive.namelist():
        return "3D/3dmodel.model"
    paths = tuple(
        name for name in archive.namelist()
        if name.casefold().endswith(".model")
    )
    if len(paths) != 1:
        raise JointProjectError("Das 3MF muss genau ein Hauptmodell enthalten.")
    return paths[0]


def _object_ids(model_xml: bytes) -> tuple[int, int]:
    root = ElementTree.fromstring(model_xml)
    namespace = {"m": MODEL_NAMESPACE}
    objects = root.findall("m:resources/m:object", namespace)
    if len(objects) != 2:
        raise JointProjectError("Das gemeinsame 3MF muss genau zwei Objekte enthalten.")
    names = {
        str(item.get("name", "")).casefold(): int(str(item.get("id")))
        for item in objects
    }
    source_id = next(
        (identifier for name, identifier in names.items() if "source" in name),
        int(str(objects[0].get("id"))),
    )
    tower_id = next(
        (identifier for name, identifier in names.items() if "tower" in name),
        int(str(objects[1].get("id"))),
    )
    if source_id == tower_id:
        raise JointProjectError("Quellobjekt und Kühlturm sind im 3MF nicht getrennt.")
    build_items = root.findall("m:build/m:item", namespace)
    if len(build_items) != 2:
        raise JointProjectError("Das gemeinsame 3MF benötigt zwei Build-Instanzen.")
    referenced = {int(str(item.get("objectid"))) for item in build_items}
    if referenced != {source_id, tower_id}:
        raise JointProjectError("Die Build-Instanzen referenzieren nicht beide Objekte.")
    if any(not str(item.get("transform", "")).strip() for item in build_items):
        raise JointProjectError("Die festen Objektpositionen fehlen im 3MF.")
    return source_id, tower_id


def _settings_xml(
    source_id: int,
    tower_id: int,
    *,
    tower_full_infill: bool,
) -> bytes:
    root = ElementTree.Element("config")
    source = ElementTree.SubElement(root, "object", {"id": str(source_id)})
    ElementTree.SubElement(
        source,
        "metadata",
        {"key": "name", "value": "Source object"},
    )
    ElementTree.SubElement(
        source, "metadata", {"key": "extruder", "value": "1"}
    )
    source_part = ElementTree.SubElement(
        source,
        "part",
        {"id": str(source_id - 1), "subtype": "normal_part"},
    )
    _append_part_metadata(source_part, "Source object")
    tower = ElementTree.SubElement(root, "object", {"id": str(tower_id)})
    ElementTree.SubElement(
        tower,
        "metadata",
        {"key": "name", "value": "Cooling tower"},
    )
    ElementTree.SubElement(
        tower, "metadata", {"key": "extruder", "value": "1"}
    )
    if tower_full_infill:
        for key, value in (
            (TOWER_INFILL_KEY, "100%"),
            (TOWER_INFILL_PATTERN_KEY, TOWER_FULL_INFILL_PATTERN),
        ):
            ElementTree.SubElement(
                tower,
                "metadata",
                {"key": key, "value": value},
            )
    tower_part = ElementTree.SubElement(
        tower,
        "part",
        {"id": str(tower_id - 1), "subtype": "normal_part"},
    )
    _append_part_metadata(tower_part, "Cooling tower")
    plate = ElementTree.SubElement(root, "plate")
    for key, value in (
        ("plater_id", "1"),
        ("plater_name", ""),
        ("locked", "false"),
        ("gcode_file", ""),
    ):
        ElementTree.SubElement(
            plate,
            "metadata",
            {"key": key, "value": value},
        )
    for identifier, identify_id in ((source_id, 1), (tower_id, 2)):
        instance = ElementTree.SubElement(plate, "model_instance")
        for key, value in (
            ("object_id", str(identifier)),
            ("instance_id", "0"),
            ("identify_id", str(identify_id)),
        ):
            ElementTree.SubElement(
                instance,
                "metadata",
                {"key": key, "value": value},
            )
    ElementTree.SubElement(root, "assemble")
    return ElementTree.tostring(root, encoding="utf-8", xml_declaration=True)


def _append_part_metadata(part: ElementTree.Element, name: str) -> None:
    values = (
        ("name", name),
        ("matrix", "1 0 0 0 0 1 0 0 0 0 1 0 0 0 0 1"),
        ("source_file", f"{name}.stl"),
        ("source_object_id", "0"),
        ("source_volume_id", "0"),
        ("source_offset_x", "0"),
        ("source_offset_y", "0"),
        ("source_offset_z", "0"),
    )
    for key, value in values:
        ElementTree.SubElement(
            part,
            "metadata",
            {"key": key, "value": value},
        )
    ElementTree.SubElement(
        part,
        "mesh_stat",
        {
            "edges_fixed": "0",
            "degenerate_facets": "0",
            "facets_removed": "0",
            "facets_reversed": "0",
            "backwards_edges": "0",
        },
    )


def _format_number(value: float) -> str:
    rendered = f"{float(value):.9f}".rstrip("0").rstrip(".")
    return rendered if rendered not in {"", "-0"} else "0"


def _transform_text(translation: tuple[float, float, float]) -> str:
    x, y, z = translation
    return " ".join(
        (
            "1", "0", "0",
            "0", "1", "0",
            "0", "0", "1",
            _format_number(x), _format_number(y), _format_number(z),
        )
    )


def _append_mesh(
    resources: ElementTree.Element,
    mesh: trimesh.Trimesh,
    *,
    identifier: int,
    name: str,
    object_uuid: str | None = None,
) -> None:
    attributes = {"id": str(identifier), "type": "model", "name": name}
    if object_uuid is not None:
        attributes[f"{{{PRODUCTION_NAMESPACE}}}UUID"] = object_uuid
    object_element = ElementTree.SubElement(
        resources,
        f"{{{MODEL_NAMESPACE}}}object",
        attributes,
    )
    mesh_element = ElementTree.SubElement(
        object_element,
        f"{{{MODEL_NAMESPACE}}}mesh",
    )
    vertices = ElementTree.SubElement(
        mesh_element,
        f"{{{MODEL_NAMESPACE}}}vertices",
    )
    for x, y, z in np.asarray(mesh.vertices, dtype=float):
        ElementTree.SubElement(
            vertices,
            f"{{{MODEL_NAMESPACE}}}vertex",
            {"x": _format_number(x), "y": _format_number(y), "z": _format_number(z)},
        )
    triangles = ElementTree.SubElement(
        mesh_element,
        f"{{{MODEL_NAMESPACE}}}triangles",
    )
    for v1, v2, v3 in np.asarray(mesh.faces, dtype=int):
        ElementTree.SubElement(
            triangles,
            f"{{{MODEL_NAMESPACE}}}triangle",
            {"v1": str(v1), "v2": str(v2), "v3": str(v3)},
        )


def _standard_3mf(
    source_mesh: trimesh.Trimesh,
    tower_mesh: trimesh.Trimesh,
    source_translation: tuple[float, float, float],
    tower_translation: tuple[float, float, float],
) -> bytes:
    ElementTree.register_namespace("", MODEL_NAMESPACE)
    ElementTree.register_namespace("p", PRODUCTION_NAMESPACE)
    model = ElementTree.Element(
        f"{{{MODEL_NAMESPACE}}}model",
        {
            "unit": "millimeter",
            "{http://www.w3.org/XML/1998/namespace}lang": "de-DE",
            "requiredextensions": "p",
        },
    )
    ElementTree.SubElement(
        model,
        f"{{{MODEL_NAMESPACE}}}metadata",
        {"name": "Application"},
    ).text = "Sacrificial Tower"
    resources = ElementTree.SubElement(model, f"{{{MODEL_NAMESPACE}}}resources")
    for root_id, mesh_id, name, path, object_uuid, component_uuid in (
        (
            2,
            1,
            "source_object",
            "/3D/Objects/source_object.model",
            "00000001-61cb-4c03-9d28-80fed5dfa1dc",
            "00010000-b206-40ff-9872-83e8017abed1",
        ),
        (
            4,
            3,
            "cooling_tower",
            "/3D/Objects/cooling_tower.model",
            "00000002-61cb-4c03-9d28-80fed5dfa1dc",
            "00020000-b206-40ff-9872-83e8017abed1",
        ),
    ):
        object_element = ElementTree.SubElement(
            resources,
            f"{{{MODEL_NAMESPACE}}}object",
            {
                "id": str(root_id),
                "type": "model",
                "name": name,
                f"{{{PRODUCTION_NAMESPACE}}}UUID": object_uuid,
            },
        )
        components = ElementTree.SubElement(
            object_element,
            f"{{{MODEL_NAMESPACE}}}components",
        )
        ElementTree.SubElement(
            components,
            f"{{{MODEL_NAMESPACE}}}component",
            {
                "objectid": str(mesh_id),
                f"{{{PRODUCTION_NAMESPACE}}}path": path,
                f"{{{PRODUCTION_NAMESPACE}}}UUID": component_uuid,
                "transform": "1 0 0 0 1 0 0 0 1 0 0 0",
            },
        )
    build = ElementTree.SubElement(model, f"{{{MODEL_NAMESPACE}}}build")
    ElementTree.SubElement(
        build,
        f"{{{MODEL_NAMESPACE}}}item",
        {
            "objectid": "2",
            "transform": _transform_text(source_translation),
            "printable": "1",
            f"{{{PRODUCTION_NAMESPACE}}}UUID": (
                "00000002-b1ec-4553-aec9-835e5b724bb4"
            ),
        },
    )
    ElementTree.SubElement(
        build,
        f"{{{MODEL_NAMESPACE}}}item",
        {
            "objectid": "4",
            "transform": _transform_text(tower_translation),
            "printable": "1",
            f"{{{PRODUCTION_NAMESPACE}}}UUID": (
                "00000004-b1ec-4553-aec9-835e5b724bb4"
            ),
        },
    )
    model_xml = ElementTree.tostring(model, encoding="utf-8", xml_declaration=True)

    def mesh_model(
        mesh: trimesh.Trimesh,
        identifier: int,
        name: str,
        object_uuid: str,
    ) -> bytes:
        ElementTree.register_namespace("", MODEL_NAMESPACE)
        ElementTree.register_namespace("p", PRODUCTION_NAMESPACE)
        root = ElementTree.Element(
            f"{{{MODEL_NAMESPACE}}}model",
            {
                "unit": "millimeter",
                "{http://www.w3.org/XML/1998/namespace}lang": "de-DE",
                "requiredextensions": "p",
            },
        )
        sub_resources = ElementTree.SubElement(
            root, f"{{{MODEL_NAMESPACE}}}resources"
        )
        _append_mesh(
            sub_resources,
            mesh,
            identifier=identifier,
            name=name,
            object_uuid=object_uuid,
        )
        ElementTree.SubElement(root, f"{{{MODEL_NAMESPACE}}}build")
        return ElementTree.tostring(root, encoding="utf-8", xml_declaration=True)

    source_model_xml = mesh_model(
        source_mesh,
        1,
        "source_object",
        "00010000-81cb-4c03-9d28-80fed5dfa1dc",
    )
    tower_model_xml = mesh_model(
        tower_mesh,
        3,
        "cooling_tower",
        "00020000-81cb-4c03-9d28-80fed5dfa1dc",
    )

    ElementTree.register_namespace("", RELATIONSHIP_NAMESPACE)
    relationships = ElementTree.Element(f"{{{RELATIONSHIP_NAMESPACE}}}Relationships")
    ElementTree.SubElement(
        relationships,
        f"{{{RELATIONSHIP_NAMESPACE}}}Relationship",
        {"Target": "/3D/3dmodel.model", "Id": "rel0", "Type": MODEL_RELATIONSHIP_TYPE},
    )
    relationships_xml = ElementTree.tostring(
        relationships, encoding="utf-8", xml_declaration=True
    )
    model_relationships = ElementTree.Element(
        f"{{{RELATIONSHIP_NAMESPACE}}}Relationships"
    )
    for identifier, target in (
        ("rel-1", "/3D/Objects/source_object.model"),
        ("rel-2", "/3D/Objects/cooling_tower.model"),
    ):
        ElementTree.SubElement(
            model_relationships,
            f"{{{RELATIONSHIP_NAMESPACE}}}Relationship",
            {"Target": target, "Id": identifier, "Type": MODEL_RELATIONSHIP_TYPE},
        )
    model_relationships_xml = ElementTree.tostring(
        model_relationships, encoding="utf-8", xml_declaration=True
    )

    ElementTree.register_namespace("", CONTENT_TYPES_NAMESPACE)
    content_types = ElementTree.Element(f"{{{CONTENT_TYPES_NAMESPACE}}}Types")
    ElementTree.SubElement(
        content_types,
        f"{{{CONTENT_TYPES_NAMESPACE}}}Default",
        {
            "Extension": "rels",
            "ContentType": "application/vnd.openxmlformats-package.relationships+xml",
        },
    )
    ElementTree.SubElement(
        content_types,
        f"{{{CONTENT_TYPES_NAMESPACE}}}Default",
        {
            "Extension": "model",
            "ContentType": "application/vnd.ms-package.3dmanufacturing-3dmodel+xml",
        },
    )
    content_types_xml = ElementTree.tostring(
        content_types, encoding="utf-8", xml_declaration=True
    )
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("[Content_Types].xml", content_types_xml)
        archive.writestr("_rels/.rels", relationships_xml)
        archive.writestr("3D/3dmodel.model", model_xml)
        archive.writestr("3D/_rels/3dmodel.model.rels", model_relationships_xml)
        archive.writestr("3D/Objects/source_object.model", source_model_xml)
        archive.writestr("3D/Objects/cooling_tower.model", tower_model_xml)
    return buffer.getvalue()


def _rewrite_archive(
    standard_3mf: bytes,
    destination: Path,
    settings_xml: bytes,
) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    with (
        zipfile.ZipFile(io.BytesIO(standard_3mf), "r") as source,
        zipfile.ZipFile(destination, "w", zipfile.ZIP_DEFLATED) as target,
    ):
        for item in source.infolist():
            if item.filename == MODEL_SETTINGS_PATH:
                continue
            target.writestr(item, source.read(item.filename))
        target.writestr(MODEL_SETTINGS_PATH, settings_xml)


def validate_joint_project(
    path: str | Path,
    *,
    tower_full_infill: bool,
) -> tuple[int, int]:
    candidate = Path(path).resolve()
    try:
        with zipfile.ZipFile(candidate, "r") as archive:
            bad = archive.testzip()
            if bad is not None:
                raise JointProjectError(f"Beschädigter 3MF-Eintrag: {bad}")
            model = archive.read(_model_path(archive))
            first_id, second_id = _object_ids(model)
            metadata = ElementTree.fromstring(archive.read(MODEL_SETTINGS_PATH))
    except (OSError, KeyError, zipfile.BadZipFile, ElementTree.ParseError) as error:
        raise JointProjectError("Das gemeinsame 3MF ist nicht gültig.") from error
    overrides: dict[int, list[tuple[str, str]]] = {}
    for object_element in metadata.findall("object"):
        identifier = int(str(object_element.get("id")))
        overrides[identifier] = [
            (str(item.get("key")), str(item.get("value")))
            for item in object_element.findall("metadata")
        ]
    expected_ids = {first_id, second_id}
    source_id = next(
        (
            identifier
            for identifier, values in overrides.items()
            if identifier in expected_ids
            and dict(values).get("name", "").casefold() == "source object"
        ),
        None,
    )
    tower_id = next(
        (
            identifier
            for identifier, values in overrides.items()
            if identifier in expected_ids
            and dict(values).get("name", "").casefold() == "cooling tower"
        ),
        None,
    )
    if source_id is None or tower_id is None or source_id == tower_id:
        raise JointProjectError(
            "Quellobjekt und Kühlturm sind in den 3MF-Metadaten nicht eindeutig."
        )
    source_values = dict(overrides.get(source_id, ()))
    tower_values = dict(overrides.get(tower_id, ()))
    if TOWER_INFILL_KEY in source_values:
        raise JointProjectError("Die Objektfüllung darf nicht überschrieben werden.")
    expected = "100%" if tower_full_infill else None
    if tower_values.get(TOWER_INFILL_KEY) != expected:
        raise JointProjectError(
            "Die objektspezifische Turmfüllung wurde nicht korrekt übernommen."
        )
    expected_pattern = TOWER_FULL_INFILL_PATTERN if tower_full_infill else None
    if tower_values.get(TOWER_INFILL_PATTERN_KEY) != expected_pattern:
        raise JointProjectError(
            "Das mit vollständiger Turmfüllung kompatible Füllmuster wurde "
            "nicht korrekt übernommen."
        )
    return source_id, tower_id


def build_joint_project(
    source_stl: str | Path,
    tower_stl: str | Path,
    destination: str | Path,
    *,
    occupied: OccupiedBounds,
    placement: TowerPlacement,
    tower_full_infill: bool,
) -> JointProjectResult:
    """Create a fixed-position two-object 3MF without altering either STL."""

    source_path = Path(source_stl).resolve(strict=True)
    tower_path = Path(tower_stl).resolve(strict=True)
    destination_path = Path(destination).resolve()
    source_before = sha256_file(source_path)
    tower_before = sha256_file(tower_path)
    source_mesh = _load_mesh(source_path)
    tower_mesh = _load_mesh(tower_path)
    source_center = (
        (occupied.minimum_x_mm + occupied.maximum_x_mm) / 2.0,
        (occupied.minimum_y_mm + occupied.maximum_y_mm) / 2.0,
    )
    source_translation = _translation(source_mesh, source_center)
    tower_translation = _translation(
        tower_mesh,
        (placement.center_x_mm, placement.center_y_mm),
    )
    standard_3mf = _standard_3mf(
        source_mesh,
        tower_mesh,
        source_translation,
        tower_translation,
    )
    with zipfile.ZipFile(io.BytesIO(standard_3mf), "r") as archive:
        source_id, tower_id = _object_ids(archive.read(_model_path(archive)))
    _rewrite_archive(
        standard_3mf,
        destination_path,
        _settings_xml(
            source_id,
            tower_id,
            tower_full_infill=tower_full_infill,
        ),
    )
    validated_source, validated_tower = validate_joint_project(
        destination_path,
        tower_full_infill=tower_full_infill,
    )
    if source_before != sha256_file(source_path) or tower_before != sha256_file(tower_path):
        raise JointProjectError("Eine STL-Quelldatei wurde unerwartet verändert.")
    return JointProjectResult(
        path=destination_path,
        source_object_id=validated_source,
        tower_object_id=validated_tower,
        source_translation_mm=source_translation,
        tower_translation_mm=tower_translation,
        tower_full_infill=tower_full_infill,
        sha256=sha256_file(destination_path),
    )


def finalize_slicer_project(
    template_3mf: str | Path,
    source_stl: str | Path,
    tower_stl: str | Path,
    destination: str | Path,
    *,
    occupied: OccupiedBounds,
    placement: TowerPlacement,
    tower_full_infill: bool,
) -> JointProjectResult:
    """Apply verified positions and tower settings to a slicer-native 3MF."""

    template_path = Path(template_3mf).resolve(strict=True)
    source_path = Path(source_stl).resolve(strict=True)
    tower_path = Path(tower_stl).resolve(strict=True)
    destination_path = Path(destination).resolve()
    source_before = sha256_file(source_path)
    tower_before = sha256_file(tower_path)
    source_mesh = _load_mesh(source_path)
    tower_mesh = _load_mesh(tower_path)
    source_center = (
        (occupied.minimum_x_mm + occupied.maximum_x_mm) / 2.0,
        (occupied.minimum_y_mm + occupied.maximum_y_mm) / 2.0,
    )
    source_translation = _translation(source_mesh, source_center)
    tower_translation = _translation(
        tower_mesh,
        (placement.center_x_mm, placement.center_y_mm),
    )
    try:
        with zipfile.ZipFile(template_path, "r") as archive:
            entries = {
                item.filename: (item, archive.read(item.filename))
                for item in archive.infolist()
            }
            model_name = _model_path(archive)
        original_model_xml = entries[model_name][1]
        model = ElementTree.fromstring(original_model_xml)
        namespace = {"m": MODEL_NAMESPACE}
        model_ids = set(_object_ids(entries[model_name][1]))
        settings = ElementTree.fromstring(entries[MODEL_SETTINGS_PATH][1])
        settings_by_id = {
            int(str(item.get("id"))): item
            for item in settings.findall("object")
        }

        def object_name(object_element: ElementTree.Element) -> str:
            return next(
                (
                    str(item.get("value", ""))
                    for item in object_element.findall("metadata")
                    if item.get("key") == "name"
                ),
                "",
            )

        source_id = next(
            (
                identifier
                for identifier, item in settings_by_id.items()
                if identifier in model_ids
                and object_name(item).casefold() in {
                    source_path.name.casefold(), "source object"
                }
            ),
            None,
        )
        tower_id = next(
            (
                identifier
                for identifier, item in settings_by_id.items()
                if identifier in model_ids
                and object_name(item).casefold() in {
                    tower_path.name.casefold(), "cooling tower"
                }
            ),
            None,
        )
        if source_id is None or tower_id is None or source_id == tower_id:
            raise JointProjectError(
                "Der Slicer hat Quellobjekt und Kühlturm nicht eindeutig benannt."
            )
        transforms = {
            source_id: _transform_text(source_translation),
            tower_id: _transform_text(tower_translation),
        }
        for item in model.findall("m:build/m:item", namespace):
            identifier = int(str(item.get("objectid")))
            if identifier in transforms:
                item.set("transform", transforms[identifier])
                item.set("printable", "1")
        if source_id not in settings_by_id or tower_id not in settings_by_id:
            raise JointProjectError(
                "Die slicereigenen Objektmetadaten sind unvollständig."
            )
        for identifier, object_element in settings_by_id.items():
            for metadata in tuple(object_element.findall("metadata")):
                if metadata.get("key") == TOWER_INFILL_KEY:
                    object_element.remove(metadata)
                elif (
                    metadata.get("key") == TOWER_INFILL_PATTERN_KEY
                    and identifier == tower_id
                ):
                    object_element.remove(metadata)
                elif metadata.get("key") == "name" and identifier in {
                    source_id, tower_id
                }:
                    metadata.set(
                        "value",
                        "Source object"
                        if identifier == source_id else "Cooling tower",
                    )
            if identifier == tower_id and tower_full_infill:
                for key, value in (
                    (TOWER_INFILL_KEY, "100%"),
                    (TOWER_INFILL_PATTERN_KEY, TOWER_FULL_INFILL_PATTERN),
                ):
                    ElementTree.SubElement(
                        object_element,
                        "metadata",
                        {"key": key, "value": value},
                    )
        ElementTree.register_namespace("", MODEL_NAMESPACE)
        ElementTree.register_namespace("p", PRODUCTION_NAMESPACE)
        ElementTree.register_namespace("BambuStudio", BAMBU_STUDIO_NAMESPACE)
        model_xml = ElementTree.tostring(
            model, encoding="utf-8", xml_declaration=True
        )
        # ElementTree drops namespace declarations that are only referenced in
        # metadata values. Bambu Studio nevertheless uses this declaration to
        # recognize its native project metadata. Without it, reopening the
        # finalized project can abort with "No valid nozzle found" even though
        # the same profiles sliced the native template successfully.
        if (
            b"xmlns:BambuStudio=" in original_model_xml
            and b"xmlns:BambuStudio=" not in model_xml
        ):
            model.set("xmlns:BambuStudio", BAMBU_STUDIO_NAMESPACE)
            model_xml = ElementTree.tostring(
                model, encoding="utf-8", xml_declaration=True
            )
        settings_xml = ElementTree.tostring(
            settings, encoding="utf-8", xml_declaration=True
        )
    except (
        OSError,
        KeyError,
        ValueError,
        zipfile.BadZipFile,
        ElementTree.ParseError,
    ) as error:
        if isinstance(error, JointProjectError):
            raise
        raise JointProjectError(
            "Das slicereigene 3MF konnte nicht sicher finalisiert werden."
        ) from error
    destination_path.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(destination_path, "w", zipfile.ZIP_DEFLATED) as target:
        for name, (item, data) in entries.items():
            if name == model_name:
                data = model_xml
            elif name == MODEL_SETTINGS_PATH:
                data = settings_xml
            target.writestr(item, data)
    validated_source, validated_tower = validate_joint_project(
        destination_path,
        tower_full_infill=tower_full_infill,
    )
    if source_before != sha256_file(source_path) or tower_before != sha256_file(tower_path):
        raise JointProjectError("Eine STL-Quelldatei wurde unerwartet verändert.")
    return JointProjectResult(
        path=destination_path,
        source_object_id=validated_source,
        tower_object_id=validated_tower,
        source_translation_mm=source_translation,
        tower_translation_mm=tower_translation,
        tower_full_infill=tower_full_infill,
        sha256=sha256_file(destination_path),
    )


def validate_tower_infill_adoption(
    gcode_path: str | Path,
    *,
    tower_center_xy_mm: tuple[float, float] | None = None,
) -> None:
    """Verify Orca-family G-code retains a recognizable full-infill tower."""

    path = Path(gcode_path).resolve(strict=True)
    inside_tower = False
    tower_block_count = 0
    sparse_tower_infill = False
    bambu_object_block = False
    active_label: int | None = None
    label_bounds: dict[int, list[float]] = {}
    sparse_labels: set[int] = set()
    try:
        with path.open("r", encoding="utf-8", errors="replace") as handle:
            for raw_line in handle:
                line = raw_line.strip()
                folded = line.casefold()
                if folded.startswith("exclude_object_start"):
                    bambu_object_block = False
                    inside_tower = "cooling_tower" in folded
                    if inside_tower:
                        tower_block_count += 1
                    continue
                if folded.startswith("exclude_object_end"):
                    inside_tower = False
                    continue
                if folded.startswith("; printing object "):
                    bambu_object_block = True
                    inside_tower = "cooling_tower" in folded
                    if inside_tower:
                        tower_block_count += 1
                    continue
                label_match = re.match(
                    r";\s*start printing object, unique label id:\s*(\d+)",
                    folded,
                )
                if label_match:
                    active_label = int(label_match.group(1))
                    bambu_object_block = True
                    continue
                if folded.startswith("; stop printing object"):
                    inside_tower = False
                    bambu_object_block = False
                    active_label = None
                    continue
                if active_label is not None:
                    if folded == ";type:sparse infill":
                        sparse_labels.add(active_label)
                    x_match = re.search(
                        r"(?:^|\s)X(-?\d+(?:\.\d+)?)", line, re.IGNORECASE
                    )
                    y_match = re.search(
                        r"(?:^|\s)Y(-?\d+(?:\.\d+)?)", line, re.IGNORECASE
                    )
                    if x_match and y_match:
                        x_value = float(x_match.group(1))
                        y_value = float(y_match.group(1))
                        bounds = label_bounds.setdefault(
                            active_label,
                            [x_value, x_value, y_value, y_value],
                        )
                        bounds[0] = min(bounds[0], x_value)
                        bounds[1] = max(bounds[1], x_value)
                        bounds[2] = min(bounds[2], y_value)
                        bounds[3] = max(bounds[3], y_value)
                if inside_tower and folded == ";type:sparse infill":
                    sparse_tower_infill = True
                    break
                # Bambu Studio labels even a 100-% zig-zag fill as
                # ``FEATURE: Sparse infill``.  The successful slice of the
                # already validated object override is therefore the usable
                # adoption evidence; treating that label like Orca's
                # ``TYPE:Sparse infill`` would reject a genuinely solid tower.
                if (
                    inside_tower
                    and not bambu_object_block
                    and folded == "; feature: sparse infill"
                ):
                    sparse_tower_infill = True
                    break
    except OSError as error:
        raise JointProjectError(
            "Der gemeinsame G-Code konnte nicht auf die Turmfüllung geprüft werden."
        ) from error
    if tower_block_count == 0 and tower_center_xy_mm is not None and label_bounds:
        center_x, center_y = tower_center_xy_mm

        def distance_to_bounds(bounds: list[float]) -> float:
            delta_x = max(bounds[0] - center_x, 0.0, center_x - bounds[1])
            delta_y = max(bounds[2] - center_y, 0.0, center_y - bounds[3])
            return math.hypot(delta_x, delta_y)

        ranked = sorted(
            (distance_to_bounds(bounds), label)
            for label, bounds in label_bounds.items()
        )
        if len(ranked) == 1 or ranked[0][0] + 1.0 < ranked[1][0]:
            tower_label = ranked[0][1]
            tower_block_count = 1
            sparse_tower_infill = tower_label in sparse_labels
    if tower_block_count == 0:
        raise JointProjectError(
            "Der Slicer hat den Kühlturm im gemeinsamen G-Code nicht eindeutig "
            "gekennzeichnet; die objektspezifische Füllung ist nicht nachweisbar."
        )
    if sparse_tower_infill:
        raise JointProjectError(
            "Der Slicer hat die objektspezifische 100-%-Turmfüllung nicht "
            "übernommen und erzeugte weiterhin Sparse Infill."
        )
