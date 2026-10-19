"""Prusa-native two-object projects with durable settings and fixed placement."""
from __future__ import annotations

import math
import tempfile
import zipfile
from dataclasses import replace
from pathlib import Path
from xml.etree import ElementTree as ET

import numpy as np
import trimesh

from cooling_tower.calibration.joint_project import (
    CONTENT_TYPES_NAMESPACE, MODEL_NAMESPACE, MODEL_RELATIONSHIP_TYPE,
    RELATIONSHIP_NAMESPACE, JointProjectError, JointProjectResult,
    _append_mesh, _load_mesh, _transform_text, _translation,
)
from cooling_tower.file_integrity import sha256_file
from cooling_tower.slicers.models import SliceRequest
from cooling_tower.slicers.prusa_supports import simulated_support_settings


PRINT_CONFIG_PATH = "Metadata/Slic3r_PE.config"
MODEL_CONFIG_PATH = "Metadata/Slic3r_PE_model.config"
MODEL_PATH = "3D/3dmodel.model"


def _connected_mesh(path: Path) -> trimesh.Trimesh:
    original = _load_mesh(path)
    # STL stores each triangle separately. Prusa repairs/welds STL input,
    # but a native 3MF needs shared vertex indices already. Merge exact
    # duplicates only, preserving every coordinate and triangle.
    vertices, indices = np.unique(
        np.asarray(original.vertices), axis=0, return_inverse=True,
    )
    return trimesh.Trimesh(
        vertices=vertices, faces=indices[np.asarray(original.faces)], process=False,
    )


def build_prusa_joint_project(
    adapter, request: SliceRequest, source_model_path, tower_model_path,
    destination, *, occupied, placement, tower_full_infill: bool,
    tower_supports_disabled: bool = False, source_supports_enabled: bool = False,
) -> JointProjectResult:
    """Build our own interoperable archive; read both slicer inputs only."""
    destination = Path(destination).resolve()
    adapter.validate_output_directory(request.profile, destination)
    source_path = Path(source_model_path).resolve(strict=True)
    tower_path = Path(tower_model_path).resolve(strict=True)
    identities = (sha256_file(source_path), sha256_file(tower_path))
    meshes = (_connected_mesh(source_path), _connected_mesh(tower_path))
    source_center = ((occupied.minimum_x_mm + occupied.maximum_x_mm) / 2,
                     (occupied.minimum_y_mm + occupied.maximum_y_mm) / 2)
    translations = (_translation(meshes[0], source_center), _translation(
        meshes[1], (placement.center_x_mm, placement.center_y_mm)))
    ET.register_namespace("", MODEL_NAMESPACE)
    model = ET.Element(f"{{{MODEL_NAMESPACE}}}model", {"unit": "millimeter"})
    ET.SubElement(model, f"{{{MODEL_NAMESPACE}}}metadata", {"name": "Application"}).text = "Sacrificial Tower"
    ET.SubElement(model, f"{{{MODEL_NAMESPACE}}}metadata", {"name": "slic3rpe:Version3mf"}).text = "1"
    resources = ET.SubElement(model, f"{{{MODEL_NAMESPACE}}}resources")
    settings = ET.Element("config")
    build = ET.SubElement(model, f"{{{MODEL_NAMESPACE}}}build")
    for identifier, (mesh, translation, name) in enumerate(
        zip(meshes, translations, ("source_object", "cooling_tower")), start=1,
    ):
        _append_mesh(resources, mesh, identifier=identifier, name=name)
        ET.SubElement(build, f"{{{MODEL_NAMESPACE}}}item", {
            "objectid": str(identifier), "transform": _transform_text(translation),
            "printable": "1",
        })
        obj = ET.SubElement(settings, "object", {"id": str(identifier), "instances_count": "1"})
        def setting(key, value):
            ET.SubElement(obj, "metadata", {"type": "object", "key": key, "value": value})
        setting("name", name)
        if identifier == 1 and source_supports_enabled:
            for key, value in simulated_support_settings(request.profile.installation.version).items():
                setting(key, value)
        if identifier == 2:
            if tower_full_infill:
                setting("fill_density", "100%")
                setting("fill_pattern", "rectilinear")
            if tower_supports_disabled:
                setting("support_material", "0")
        volume = ET.SubElement(obj, "volume", {"firstid": "0", "lastid": str(len(mesh.faces) - 1)})
        ET.SubElement(volume, "metadata", {"type": "volume", "key": "name", "value": name})
        ET.SubElement(volume, "metadata", {"type": "volume", "key": "volume_type", "value": "ModelPart"})

    # Prusa's OPC reader requires unprefixed local names, even though a
    # namespace-prefixed relationship document is otherwise valid XML.
    types = ET.Element("Types", {"xmlns": CONTENT_TYPES_NAMESPACE})
    for extension, content_type in (("rels", "application/vnd.openxmlformats-package.relationships+xml"),
                                    ("model", "application/vnd.ms-package.3dmanufacturing-3dmodel+xml"),
                                    ("config", "application/octet-stream")):
        ET.SubElement(types, "Default", {"Extension": extension, "ContentType": content_type})
    relationships = ET.Element("Relationships", {"xmlns": RELATIONSHIP_NAMESPACE})
    ET.SubElement(relationships, "Relationship", {
        "Target": "/" + MODEL_PATH, "Id": "rel-model", "Type": MODEL_RELATIONSHIP_TYPE,
    })
    # Use the same serializer as ordinary CLI slices. The embedded profile is
    # complete and independent of installed GUI defaults or later preset edits.
    values = dict(request.profile.effective_values)
    values["gcode_label_objects"] = "firmware"
    embedded_request = replace(request, profile=replace(request.profile, effective_values=values))
    destination.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="prusa_project_", dir=destination.parent) as temporary:
        work = Path(temporary)
        adapter.build_slice_command(embedded_request, source_path, work, work)
        effective_ini = work / "phase14_effective_profile.ini"
        complete_ini = work / "complete_profile.ini"
        outcome = adapter.runner.run(
            request.profile.installation.executable_path,
            ("--datadir", str(work / "prusa_data"), "--load", str(effective_ini),
             "--save", str(complete_ini)),
            working_directory=work, timeout_s=request.timeout_s,
            cancellation_event=request.cancellation_event,
        )
        if outcome.cancelled:
            raise JointProjectError("Die Erstellung des gemeinsamen PrusaSlicer-Projekts wurde abgebrochen.")
        if outcome.timed_out:
            raise JointProjectError("PrusaSlicer hat die Projekteinstellungen nicht innerhalb der erlaubten Zeit bereitgestellt.")
        if outcome.crashed or outcome.return_code != 0 or not complete_ini.is_file():
            raise JointProjectError("PrusaSlicer konnte die vollständigen Projekteinstellungen nicht bereitstellen.")
        ini = complete_ini.read_text(encoding="utf-8-sig")
        project_config = "; generated by Sacrificial Tower\n" + "".join(
            "; " + line + "\n" for line in ini.splitlines()
            if line.strip() and not line.lstrip().startswith(("#", ";", "["))
        )
        staged = work / "project.3mf"
        with zipfile.ZipFile(staged, "w", zipfile.ZIP_DEFLATED) as archive:
            for path, document in (("[Content_Types].xml", types), ("_rels/.rels", relationships),
                                   (MODEL_PATH, model), (MODEL_CONFIG_PATH, settings)):
                archive.writestr(path, ET.tostring(document, encoding="utf-8", xml_declaration=True))
            archive.writestr(PRINT_CONFIG_PATH, project_config.encode("utf-8"))
        validate_prusa_joint_project(staged, tower_full_infill=tower_full_infill,
                                     tower_supports_disabled=tower_supports_disabled,
                                     source_supports_enabled=source_supports_enabled,
                                     source_support_settings=simulated_support_settings(request.profile.installation.version))
        if identities != (sha256_file(source_path), sha256_file(tower_path)):
            raise JointProjectError("Eine STL-Quelldatei wurde während des Prusa-Projektbaus verändert.")
        staged.replace(destination)
    return JointProjectResult(destination, 1, 2, *translations, tower_full_infill, sha256_file(destination))


def validate_prusa_joint_project(
    path, *, tower_full_infill: bool, tower_supports_disabled: bool = False,
    source_supports_enabled: bool = False,
    source_support_settings: dict[str, str] | None = None,
) -> tuple[int, int]:
    try:
        with zipfile.ZipFile(path) as archive:
            if archive.testzip() is not None:
                raise ValueError("Beschädigte Projektdaten")
            model = ET.fromstring(archive.read(MODEL_PATH))
            settings = ET.fromstring(archive.read(MODEL_CONFIG_PATH))
            config = archive.read(PRINT_CONFIG_PATH).decode("utf-8")
            relations_xml = archive.read("_rels/.rels")
            types_xml = archive.read("[Content_Types].xml")
        if b"<Relationships " not in relations_xml or b"<Relationship " not in relations_xml or b"<Types " not in types_xml:
            raise ValueError("Die Projektverknüpfungen entsprechen nicht dem PrusaSlicer-Format")
        relations = ET.fromstring(relations_xml)
        if not any(entry.get("Target") == "/" + MODEL_PATH
                   and entry.get("Type") == MODEL_RELATIONSHIP_TYPE for entry in relations):
            raise ValueError("Die Verknüpfung zum 3D-Modell fehlt")
        items = model.findall(f"{{{MODEL_NAMESPACE}}}build/{{{MODEL_NAMESPACE}}}item")
        ids = {item.get("objectid") for item in items}
        objects = {obj.get("id"): {entry.get("key"): entry.get("value") for entry in obj.findall("metadata")}
                   for obj in settings.findall("object")}
        if len(items) != 2 or ids != {"1", "2"} or set(objects) != ids or not config.startswith("; generated"):
            raise ValueError("Unvollständiges Objekt-/Turm-Projekt")
        for item in items:
            transform = tuple(map(float, item.get("transform", "").split()))
            if len(transform) != 12 or not all(math.isfinite(value) for value in transform):
                raise ValueError("Eine Objektposition ist ungültig")
        config_values = dict(line[2:].split(" = ", 1) for line in config.splitlines()
                             if line.startswith("; ") and " = " in line)
        layer_height = float(config_values.get("layer_height", "0"))
        if (not math.isfinite(layer_height) or layer_height <= 0
                or config_values.get("binary_gcode") != "0"
                or config_values.get("gcode_label_objects") != "firmware"):
            raise ValueError("Die eingebetteten Analyse-/Profileinstellungen sind unvollständig")
        resources = model.findall(f"{{{MODEL_NAMESPACE}}}resources/{{{MODEL_NAMESPACE}}}object")
        if len(resources) != 2 or {obj.get("id") for obj in resources} != ids:
            raise ValueError("Die zwei Objektgeometrien fehlen")
        for obj in resources:
            mesh = obj.find(f"{{{MODEL_NAMESPACE}}}mesh")
            if mesh is None:
                raise ValueError("Eine Objektgeometrie fehlt")
            vertex_count = len(mesh.findall(f"{{{MODEL_NAMESPACE}}}vertices/{{{MODEL_NAMESPACE}}}vertex"))
            triangles = mesh.findall(f"{{{MODEL_NAMESPACE}}}triangles/{{{MODEL_NAMESPACE}}}triangle")
            if vertex_count < 3 or not triangles or any(
                not 0 <= int(triangle.get(key, "-1")) < vertex_count
                for triangle in triangles for key in ("v1", "v2", "v3")
            ):
                raise ValueError("Eine Objektgeometrie enthält ungültige Dreiecke")
        if tower_full_infill and (objects["2"].get("fill_density") != "100%" or objects["2"].get("fill_pattern") != "rectilinear"):
            raise ValueError("Die 100-%-Turmfüllung fehlt")
        if tower_supports_disabled and objects["2"].get("support_material") != "0":
            raise ValueError("Die deaktivierten Turmstützen fehlen")
        if source_supports_enabled and objects["1"].get("support_material") != "1":
            raise ValueError("Die Objektstützen fehlen")
        if source_supports_enabled and any(
            objects["1"].get(key) != value for key, value in (source_support_settings or {}).items()
        ):
            raise ValueError("Die simulierte Stützenart des Originalobjekts fehlt")
    except (OSError, KeyError, ValueError, ET.ParseError, zipfile.BadZipFile) as error:
        raise JointProjectError("Das gemeinsame PrusaSlicer-3MF ist unvollständig oder ungültig: " + str(error)) from error
    return 1, 2
