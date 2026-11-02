"""Read a native 3MF resource graph without rebuilding or reindexing meshes."""
from __future__ import annotations

from dataclasses import dataclass
import math
from xml.parsers import expat

from cooling_tower.native_project.archive import ProjectArchive, ProjectArchiveError


CORE_NAMESPACE = "http://schemas.microsoft.com/3dmanufacturing/core/2015/02"
PRODUCTION_NAMESPACE = "http://schemas.microsoft.com/3dmanufacturing/production/2015/06"
MODEL_RELATIONSHIP = "http://schemas.microsoft.com/3dmanufacturing/2013/01/3dmodel"
IDENTITY_TRANSFORM = (1.0, 0.0, 0.0, 0.0, 1.0, 0.0, 0.0, 0.0, 1.0, 0.0, 0.0, 0.0)
UNIT_SCALE_MM = {"micron": .001, "millimeter": 1., "centimeter": 10., "inch": 25.4, "foot": 304.8, "meter": 1000.}
_REQUIRED_EXTENSIONS = frozenset({CORE_NAMESPACE, PRODUCTION_NAMESPACE,
    "http://schemas.microsoft.com/3dmanufacturing/material/2015/02"})
_PRODUCER_METADATA = frozenset({"Application", "OrcaSlicer", "BambuStudio:3mfVersion",
                               "slic3rpe:Version3mf", "AnycubicSlicerNext"})


class NativeGraphError(ValueError):
    pass


class UnsupportedProjectExtension(NativeGraphError):
    pass


def _tag(value: str) -> str:
    return value.rsplit("}", 1)[-1]


def _identifier(value: str | None) -> int:
    if value is None or not value.isascii() or not value.isdecimal() or len(value) > 20:
        raise NativeGraphError("Eine native Objektkennung ist ungültig.")
    return int(value)


def transform(value: str | None) -> tuple[float, ...]:
    if value is None:
        return IDENTITY_TRANSFORM
    try:
        values = tuple(float(part) for part in value.split())
    except ValueError as error:
        raise NativeGraphError("Eine Objekttransformation enthält ungültige Zahlen.") from error
    if len(values) != 12 or not all(math.isfinite(part) for part in values):
        raise NativeGraphError("Eine Objekttransformation ist unvollständig oder nicht endlich.")
    return values


@dataclass(frozen=True, slots=True)
class Component:
    model_path: str
    object_id: int
    transform: tuple[float, ...]
    attributes: tuple[tuple[str, str], ...] = ()


@dataclass(frozen=True, slots=True)
class ModelObject:
    model_path: str
    object_id: int
    attributes: tuple[tuple[str, str], ...]
    components: tuple[Component, ...]
    vertex_count: int
    triangle_count: int
    painted_support_triangles: int
    painted_seam_triangles: int
    painted_material_triangles: int
    bounds_mm: tuple[float, ...] | None


@dataclass(frozen=True, slots=True)
class BuildItem:
    object_id: int
    transform: tuple[float, ...]
    printable: bool
    attributes: tuple[tuple[str, str], ...]


@dataclass(frozen=True, slots=True)
class ModelDocument:
    path: str
    unit: str
    root_attributes: tuple[tuple[str, str], ...]
    metadata: tuple[tuple[str, str], ...]
    namespaces: tuple[tuple[str, str], ...]
    resource_ids: tuple[int, ...]
    objects: tuple[ModelObject, ...]
    build: tuple[BuildItem, ...]


@dataclass(frozen=True, slots=True)
class ProjectGraph:
    main_path: str
    documents: tuple[ModelDocument, ...]

    @property
    def main(self) -> ModelDocument:
        return next(document for document in self.documents if document.path == self.main_path)

    def object(self, model_path: str, object_id: int) -> ModelObject:
        for document in self.documents:
            if document.path == model_path:
                for obj in document.objects:
                    if obj.object_id == object_id:
                        return obj
        raise NativeGraphError("Ein referenziertes Objekt oder Bauteil fehlt im nativen Projekt.")


class _ModelReader:
    """Expat retains only graph records and counts, never triangle arrays."""

    def __init__(self, archive: ProjectArchive, path: str) -> None:
        self.archive, self.path = archive, path
        self.stack: list[str] = []
        self.namespaces: dict[str, str] = {}
        self.root_namespaces: tuple[tuple[str, str], ...] = ()
        self.root_attributes: tuple[tuple[str, str], ...] = ()
        self.unit = "millimeter"
        self.resource_ids: set[int] = set()
        self.objects: list[ModelObject] = []
        self.build: list[BuildItem] = []
        self.metadata: list[tuple[str, str]] = []
        self.current = None
        self.metadata_key: str | None = None
        self.text: list[str] = []
        self.saw_resources = False
        self.saw_build = False
        self.graph_records = 0
        self.text_size = 0

    def read(self) -> ModelDocument:
        parser = expat.ParserCreate(namespace_separator="}")
        parser.StartElementHandler = self.start
        parser.EndElementHandler = self.end
        parser.CharacterDataHandler = self.characters
        parser.StartNamespaceDeclHandler = lambda prefix, uri: self.namespaces.__setitem__(prefix or "", uri)
        parser.StartDoctypeDeclHandler = self.doctype
        parser.ExternalEntityRefHandler = self.external_entity
        try:
            supplied = 0
            for block in self.archive.iter_bytes(self.path):
                parser.Parse(block, False)
                supplied += len(block)
                # Expat can defer an unfinished token. Bound that buffer as
                # well as the expanded member, including comments and CDATA.
                if supplied - parser.CurrentByteIndex > 1024 * 1024:
                    raise NativeGraphError('Eine einzelne XML-Modellstruktur überschreitet die Ressourcengrenze.')
            parser.Parse(b"", True)
        except expat.ExpatError as error:
            raise NativeGraphError("Eine native Modelldatei enthält beschädigtes XML.") from error
        if not self.saw_resources:
            raise NativeGraphError("Die Ressourcenstruktur des nativen Modells fehlt.")
        return ModelDocument(self.path, self.unit, self.root_attributes, tuple(self.metadata),
            self.root_namespaces, tuple(sorted(self.resource_ids)), tuple(self.objects), tuple(self.build))

    @staticmethod
    def doctype(*_: object) -> None:
        raise ProjectArchiveError("XML-Dokumenttypen und externe Entitäten sind nicht zulässig.")

    @staticmethod
    def external_entity(*_: object) -> int:
        raise ProjectArchiveError("Externe Modellressourcen sind nicht zulässig.")

    def start(self, qualified: str, attributes: dict[str, str]) -> None:
        if len(attributes) > 4096 or sum(len(key) + len(value) for key, value in attributes.items()) > 1024 * 1024:
            raise NativeGraphError('Die XML-Modellattribute überschreiten die Ressourcengrenze.')
        # Optional vendor elements may use the same local names as core tags.
        # They must never replace core geometry or create invented objects.
        name = qualified[len(CORE_NAMESPACE) + 1:] if qualified.startswith(CORE_NAMESPACE + "}") else qualified
        parent = self.stack[-1] if self.stack else None
        if len(self.stack) > 128:
            raise NativeGraphError("Die native Modellstruktur ist zu tief verschachtelt.")
        if not self.stack:
            if qualified != CORE_NAMESPACE + "}model":
                raise NativeGraphError("Die Projektdatei enthält kein 3MF-Kernmodell.")
            self.unit = attributes.get("unit", "millimeter")
            if self.unit not in UNIT_SCALE_MM:
                raise UnsupportedProjectExtension("Die Modelleinheit wird vom nativen Ablauf nicht unterstützt.")
            self.root_attributes = tuple(attributes.items())
            self.root_namespaces = tuple(self.namespaces.items())
            for prefix in attributes.get("requiredextensions", "").split():
                uri = self.namespaces.get(prefix)
                if uri not in _REQUIRED_EXTENSIONS:
                    raise UnsupportedProjectExtension(f"Das Modell benötigt die nicht unterstützte 3MF-Erweiterung {uri or prefix}.")
        elif name == "resources" and parent == "model":
            self.saw_resources = True
        elif parent == "resources" and "id" in attributes:
            self._record()
            identifier = _identifier(attributes["id"])
            if identifier in self.resource_ids:
                raise NativeGraphError("Eine Ressourcenkennung ist innerhalb einer Modelldatei doppelt vergeben.")
            self.resource_ids.add(identifier)
            if name == "object":
                self.current = {"id": identifier, "attributes": tuple(attributes.items()), "components": [],
                    "vertices": 0, "triangles": 0, "support": 0, "seam": 0, "material": 0, "mesh": False, "bounds": None}
        elif name == "mesh" and parent == "object" and self.current is not None:
            if self.current["mesh"]:
                raise NativeGraphError("Ein Objekt enthält mehrere nicht zuordenbare Mesh-Strukturen.")
            self.current["mesh"] = True
        elif name == "vertex" and parent == "vertices" and self.current is not None:
            try:
                coords = tuple(float(attributes[key]) for key in ("x", "y", "z"))
            except (KeyError, ValueError) as error:
                raise NativeGraphError("Eine Mesh-Koordinate ist ungültig.") from error
            if not all(math.isfinite(value) for value in coords):
                raise NativeGraphError("Ein Mesh enthält nicht endliche Koordinaten.")
            bounds = self.current["bounds"]
            self.current["bounds"] = [*coords, *coords] if bounds is None else [
                *(min(bounds[i], coords[i]) for i in range(3)),
                *(max(bounds[i + 3], coords[i]) for i in range(3))]
            self.current["vertices"] += 1
        elif name == "triangle" and parent == "triangles" and self.current is not None:
            for key in ("v1", "v2", "v3"):
                index = _identifier(attributes.get(key))
                if index >= self.current["vertices"]:
                    raise NativeGraphError("Ein Dreieck verweist auf einen fehlenden Mesh-Punkt.")
            self.current["triangles"] += 1
            keys = {_tag(key).casefold() for key in attributes}
            self.current["support"] += any("support" in key for key in keys)
            self.current["seam"] += any("seam" in key for key in keys)
            self.current["material"] += any("paint_color" in key or "mmu_segmentation" in key for key in keys)
        elif name == "component" and parent == "components" and self.current is not None:
            self._record()
            target = attributes.get(PRODUCTION_NAMESPACE + "}path")
            path = self.archive.relationship_target(self.path, target) if target else self.path
            self.current["components"].append(Component(path, _identifier(attributes.get("objectid")),
                transform(attributes.get("transform")), tuple(attributes.items())))
        elif name == "build" and parent == "model":
            self.saw_build = True
        elif name == "item" and parent == "build":
            self._record()
            printable = attributes.get("printable", "1")
            if printable not in {"0", "1", "true", "false"}:
                raise NativeGraphError("Die Druckbarkeitsangabe einer Instanz ist ungültig.")
            self.build.append(BuildItem(_identifier(attributes.get("objectid")), transform(attributes.get("transform")),
                printable in {"1", "true"}, tuple(attributes.items())))
        elif name == "metadata" and parent == "model":
            key = attributes.get("name", "")
            if key in _PRODUCER_METADATA:
                self.metadata_key, self.text = key, []
                self.text_size = 0
        self.stack.append(name)

    def characters(self, value: str) -> None:
        if self.metadata_key is not None:
            self.text.append(value)
            self.text_size += len(value)
            if self.text_size > 4096:
                raise NativeGraphError("Eine native Formatkennung ist zu lang.")

    def _record(self) -> None:
        self.graph_records += 1
        if self.graph_records > 250_000:
            raise NativeGraphError("Die native Objektstruktur überschreitet die Ressourcengrenze.")

    def end(self, qualified: str) -> None:
        name = qualified[len(CORE_NAMESPACE) + 1:] if qualified.startswith(CORE_NAMESPACE + "}") else qualified
        if name == "metadata" and self.metadata_key is not None:
            self.metadata.append((self.metadata_key, "".join(self.text)))
            self.metadata_key, self.text = None, []
        elif name == "object" and self.current is not None:
            value = self.current
            if value["components"] and value["mesh"]:
                raise NativeGraphError("Ein Objekt enthält zugleich Mesh und Komponenten.")
            if value["mesh"] and (value["vertices"] == 0 or value["triangles"] == 0):
                raise NativeGraphError("Ein natives Mesh besitzt keine vollständige Geometrie.")
            if not value["mesh"] and not value["components"]:
                raise NativeGraphError("Ein natives Objekt besitzt weder Geometrie noch Bauteilverweise.")
            self.objects.append(ModelObject(self.path, value["id"], value["attributes"], tuple(value["components"]),
                value["vertices"], value["triangles"], value["support"], value["seam"], value["material"],
                tuple(v * UNIT_SCALE_MM[self.unit] for v in value["bounds"]) if value["bounds"] else None))
            self.current = None
        self.stack.pop()


def read_graph(archive: ProjectArchive) -> ProjectGraph:
    relationships = archive.xml("_rels/.rels")
    targets = [archive.relationship_target("_rels/.rels", relation.get("Target", "")) for relation in relationships
               if relation.get("Type") == MODEL_RELATIONSHIP]
    if len(targets) != 1:
        raise NativeGraphError("Das Projekt enthält keine eindeutige native Hauptmodell-Zuordnung.")
    pending = [targets[0]]
    documents: dict[str, ModelDocument] = {}
    records = 0
    while pending:
        path = pending.pop()
        if path in documents:
            continue
        document = _ModelReader(archive, path).read()
        records += len(document.resource_ids) + len(document.build) + sum(len(obj.components) for obj in document.objects)
        if records > 250_000:
            raise NativeGraphError('Die gesamte native Objektstruktur überschreitet die Ressourcengrenze.')
        documents[path] = document
        for obj in document.objects:
            pending.extend(component.model_path for component in obj.components if component.model_path not in documents)
    graph = ProjectGraph(targets[0], tuple(documents.values()))
    index = {(obj.model_path, obj.object_id): obj for document in graph.documents for obj in document.objects}
    visited, active = set(), set()

    def visit(key: tuple[str, int]) -> None:
        if key in active:
            raise NativeGraphError("Die Bauteilstruktur enthält einen zyklischen Verweis.")
        if key in visited:
            return
        if key not in index:
            raise NativeGraphError("Ein referenziertes Bauteil fehlt im Projekt.")
        if len(active) > 128:
            raise NativeGraphError("Die native Bauteilstruktur ist zu tief verschachtelt.")
        active.add(key)
        for component in index[key].components:
            visit((component.model_path, component.object_id))
        active.remove(key)
        visited.add(key)

    for key in index:
        visit(key)
    for item in graph.main.build:
        visit((graph.main_path, item.object_id))
    return graph
