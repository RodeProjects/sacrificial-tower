from __future__ import annotations

import json
import os
from dataclasses import replace
from pathlib import Path

from cooling_tower.models.gcode_metadata import SlicerFamily
from cooling_tower.slicers.base import (
    BaseSlicerAdapter,
    environment_roots,
    existing_paths,
)
from cooling_tower.slicers.errors import SlicerProcessError
from cooling_tower.slicers.models import (
    SliceRequest,
    SlicerCandidate,
    SlicerCapability,
    SlicerDiscoverySource,
    SlicerSupportLevel,
)
from cooling_tower.slicers.prusa_adapter import PrusaSlicerAdapter
from cooling_tower.slicers.orca_family import FULL_CAPABILITIES, OrcaFamilyAdapter
from cooling_tower.slicers.orca_adapter import OrcaSlicerAdapter


class AnycubicSlicerNextAdapter(OrcaFamilyAdapter):
    adapter_id = "anycubic_slicer_next"
    detection_module_id = "anycubic_slicer_next"

    def build_slice_command(
        self,
        request: SliceRequest,
        model_path: Path,
        output_directory: Path,
        working_root: Path,
    ) -> tuple[Path, tuple[str, ...]]:
        from cooling_tower.gcode.slicer_layer_times import anycubic_timing_hooks

        executable, arguments = super().build_slice_command(
            request, model_path, output_directory, working_root
        )
        # The base adapter has already materialized these files in our own
        # working directory. Originals in the slicer's profile catalogue stay
        # read-only. Both preslice and every tower candidate receive clocks.
        settings = arguments[arguments.index("--load-settings") + 1].split(";")
        machine_copy = Path(settings[0])
        payload = json.loads(machine_copy.read_text(encoding="utf-8"))
        target = payload.get("setting", payload)
        values = dict(request.profile.effective_values)
        values.update(target)
        target.update(anycubic_timing_hooks(values))
        machine_copy.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        return executable, arguments


class BambuStudioAdapter(OrcaFamilyAdapter):
    adapter_id = "bambu_studio"
    detection_module_id = "bambu_studio"
    # Slice the exact durable project during adjustment as well as on export.
    # A direct STL assembly can produce slightly different paths after its
    # meshes and settings are serialized into the native 3MF container.
    prefer_native_joint_project = True

    def build_slice_command(
        self,
        request: SliceRequest,
        model_path: Path,
        output_directory: Path,
        working_root: Path,
    ) -> tuple[Path, tuple[str, ...]]:
        executable, arguments = super().build_slice_command(
            request, model_path, output_directory, working_root
        )
        if (
            request.purpose == "calibration"
            and request.preserve_model_positions
            and not request.use_cli_assemble_list
            and model_path.suffix.casefold() == ".3mf"
        ):
            # This self-contained candidate is also the eventual export.
            # Loading role profiles again can overwrite native project values
            # differently from a later GUI/CLI slice of that same 3MF.
            retained: list[str] = []
            index = 0
            while index < len(arguments):
                if arguments[index] in {"--load-settings", "--load-filaments"}:
                    index += 2
                else:
                    retained.append(arguments[index])
                    index += 1
            arguments = tuple(retained)
        return executable, arguments

    def prepare_joint_slice_input(
        self,
        request: SliceRequest,
        source_model_path: Path,
        tower_model_path: Path,
        destination: Path,
        *,
        occupied: object,
        placement: object,
        tower_full_infill: bool,
        tower_supports_disabled: bool = False,
        source_supports_enabled: bool = False,
    ) -> object:
        """Create only Bambu's direct fixed-position candidate assembly."""

        from cooling_tower.calibration.joint_project import (
            JointSliceInputResult,
            describe_joint_placement,
        )

        arrangement = describe_joint_placement(
            source_model_path,
            tower_model_path,
            occupied=occupied,
            placement=placement,
        )
        tower_params = (
            {
                "sparse_infill_density": "100%",
                "sparse_infill_pattern": "zig-zag",
            }
            if tower_full_infill
            else {}
        )
        if tower_supports_disabled:
            tower_params["enable_support"] = "0"
        payload = {
            "plates": [
                {
                    "plate_name": "Cooling tower calibration",
                    "need_arrange": False,
                    "objects": [
                        {
                            "path": str(Path(source_model_path).resolve()),
                            "count": 1,
                            "filaments": [
                                arrangement.source_filament_index
                            ],
                            "pos_x": [arrangement.source_translation_mm[0]],
                            "pos_y": [arrangement.source_translation_mm[1]],
                            "pos_z": [arrangement.source_translation_mm[2]],
                            **({"print_params": {"enable_support": "1"}} if source_supports_enabled else {}),
                        },
                        {
                            "path": str(Path(tower_model_path).resolve()),
                            "count": 1,
                            "filaments": [
                                arrangement.tower_filament_index
                            ],
                            "pos_x": [arrangement.tower_translation_mm[0]],
                            "pos_y": [arrangement.tower_translation_mm[1]],
                            "pos_z": [arrangement.tower_translation_mm[2]],
                            "print_params": tower_params,
                        },
                    ],
                }
            ]
        }
        destination_path = Path(destination).resolve()
        destination_path.parent.mkdir(parents=True, exist_ok=True)
        destination_path.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        return JointSliceInputResult(
            slice_input_path=destination_path,
            placement=arrangement,
            tower_full_infill=tower_full_infill,
        )

    def create_joint_project(
        self,
        request: SliceRequest,
        source_model_path: Path,
        tower_model_path: Path,
        destination: Path,
        *,
        occupied: object,
        placement: object,
        tower_full_infill: bool,
        tower_supports_disabled: bool = False,
        source_supports_enabled: bool = False,
    ) -> object:
        """Create the export 3MF plus Bambu's reliable direct joint-slice input."""

        result = super().create_joint_project(
            request,
            source_model_path,
            tower_model_path,
            destination,
            occupied=occupied,
            placement=placement,
            tower_full_infill=tower_full_infill,
            tower_supports_disabled=tower_supports_disabled,
            source_supports_enabled=source_supports_enabled,
        )
        destination_path = Path(destination).resolve()
        from cooling_tower.calibration.joint_project import (
            synchronize_bambu_project_filament_settings,
        )

        synchronized_sha256 = synchronize_bambu_project_filament_settings(
            destination_path,
            tuple(record.path for record in request.profile.filaments),
        )
        result = replace(result, sha256=synchronized_sha256)
        assembly_path = destination_path.with_name(
            f"{destination_path.stem}.bambu-assemble.json"
        )
        slice_input = self.prepare_joint_slice_input(
            request,
            source_model_path,
            tower_model_path,
            assembly_path,
            occupied=occupied,
            placement=placement,
            tower_full_infill=tower_full_infill,
            tower_supports_disabled=tower_supports_disabled,
            source_supports_enabled=source_supports_enabled,
        )
        return replace(result, slice_input_path=slice_input.slice_input_path)


class CuraAdapter(BaseSlicerAdapter):
    adapter_id = "cura"
    product_name = "UltiMaker Cura"
    family = SlicerFamily.CURA
    support_level = SlicerSupportLevel.FULL
    executable_names = ("UltiMaker-Cura.exe", "Cura.exe")
    product_markers = ("UltiMaker Cura", "Ultimaker Cura", "CuraEngine")
    probe_arguments = ()

    def known_candidates(self) -> tuple[SlicerCandidate, ...]:
        result: list[SlicerCandidate] = []
        for root in environment_roots():
            if not root.is_dir():
                continue
            for directory in root.glob("*Cura*"):
                for executable in self.executable_names:
                    path = directory / executable
                    if path.is_file():
                        result.append(
                            SlicerCandidate(
                                path,
                                SlicerDiscoverySource.KNOWN_PATH,
                                adapter_hint=self.adapter_id,
                            )
                        )
        return tuple(result)

    def engine_path_for(self, executable: Path) -> Path | None:
        candidates = (
            executable.parent / "CuraEngine.exe",
            executable.parent / "bin" / "CuraEngine.exe",
        )
        engine = next((path.resolve() for path in candidates if path.is_file()), None)
        if engine is None:
            return None
        outcome = self.runner.run(
            engine,
            ("--version",),
            working_directory=engine.parent,
            timeout_s=3.0,
        )
        text = f"{outcome.stdout}\n{outcome.stderr}".casefold()
        if (
            outcome.timed_out
            or outcome.cancelled
            or outcome.return_code != 0
            or "curaengine" not in text
        ):
            return None
        return engine

    def capabilities_for(
        self,
        engine_path: Path | None,
    ) -> frozenset[SlicerCapability]:
        values = {
            SlicerCapability.PROFILE_INVENTORY,
            SlicerCapability.CUSTOM_PROFILES,
        }
        if engine_path is not None:
            values.update(
                {
                    SlicerCapability.CLI_SLICE,
                    SlicerCapability.OUTPUT_DIRECTORY,
                    SlicerCapability.PROCESS_CANCELLATION,
                }
            )
        return frozenset(values)

    def profile_roots_for(self, executable: Path) -> tuple[Path, ...]:
        roots = [executable.parent / "share" / "cura" / "resources"]
        appdata = os.environ.get("APPDATA")
        if appdata:
            roots.append(Path(appdata) / "cura")
        return existing_paths(roots)

    def build_slice_command(
        self,
        request: SliceRequest,
        model_path: Path,
        output_directory: Path,
        working_root: Path,
    ) -> tuple[Path, tuple[str, ...]]:
        engine = request.profile.installation.engine_path
        if engine is None or not engine.is_file():
            raise SlicerProcessError("CuraEngine wurde nicht gefunden.")
        definitions = request.profile.definitions
        if not definitions:
            raise SlicerProcessError(
                "Für CuraEngine fehlt eine vollständige Maschinendefinition."
            )
        output_path = output_directory / f"{model_path.stem}.gcode"
        arguments: list[str] = ["slice"]
        for definition in definitions:
            arguments.extend(("-j", str(definition.path)))
        for key, value in sorted(request.profile.effective_values.items()):
            if isinstance(value, (bool, int, float, str)):
                arguments.extend(("-s", f"{key}={value}"))
        arguments.extend(("-l", str(model_path), "-o", str(output_path)))
        return engine, tuple(arguments)


class DetectionOnlyAdapter(BaseSlicerAdapter):
    support_level = SlicerSupportLevel.DETECTION_ONLY
    probe_arguments = ()
    capabilities = frozenset()

    def known_candidates(self) -> tuple[SlicerCandidate, ...]:
        result: list[SlicerCandidate] = []
        names = {
            self.product_name.casefold().replace(" ", ""),
            self.adapter_id.casefold().replace("_", ""),
        }
        for root in environment_roots():
            if not root.is_dir():
                continue
            try:
                directories = tuple(root.iterdir())
            except OSError:
                continue
            for directory in directories:
                if not directory.is_dir():
                    continue
                folded = directory.name.casefold().replace(" ", "")
                if not any(name in folded for name in names):
                    continue
                for executable in self.executable_names:
                    path = directory / executable
                    if path.is_file():
                        result.append(
                            SlicerCandidate(
                                path,
                                SlicerDiscoverySource.KNOWN_PATH,
                                adapter_hint=self.adapter_id,
                            )
                        )
        return tuple(result)

    def slice_model(self, request: SliceRequest):
        raise SlicerProcessError(
            f"{self.product_name} wird erkannt, ist aber noch nicht vollständig integriert."
        )


class IdeaMakerAdapter(DetectionOnlyAdapter):
    adapter_id = "ideamaker"
    product_name = "ideaMaker"
    family = SlicerFamily.IDEAMAKER
    executable_names = ("ideaMaker.exe",)
    product_markers = ("ideaMaker", "Raise3D")


class Simplify3DAdapter(DetectionOnlyAdapter):
    adapter_id = "simplify3d"
    product_name = "Simplify3D"
    family = SlicerFamily.SIMPLIFY3D
    executable_names = ("Simplify3D.exe",)
    product_markers = ("Simplify3D",)


def default_adapters():
    return (
        AnycubicSlicerNextAdapter(),
        OrcaSlicerAdapter(),
        BambuStudioAdapter(),
        PrusaSlicerAdapter(),
        CuraAdapter(),
        IdeaMakerAdapter(),
        Simplify3DAdapter(),
    )
