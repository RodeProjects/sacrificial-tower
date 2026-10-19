from __future__ import annotations

import json
import os
import sys
import tempfile
import time
import unittest
from dataclasses import replace
from pathlib import Path
from unittest.mock import Mock, patch
from types import SimpleNamespace

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from cooling_tower.slicers import (
    OrcaSlicerAdapter, ProfileCandidate, ProfileInventoryService, ProfileKind,
    ProfileMatchingService, SliceRequest, SlicerCandidate, SlicerDiscoverySource,
    read_active_presets,
)
from cooling_tower.slicers.detection.orca_slicer import OrcaSlicerDetectionModule
from cooling_tower.slicers.errors import SlicerProcessError
from cooling_tower.slicers.profile_inventory import ProfileInheritanceResolver
from cooling_tower.slicers.profile_safety import fingerprint_profile_paths


class OrcaProfileTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.appdata = self.root / "Roaming"
        self.base = self.appdata / "OrcaSlicer"
        self.system = self.base / "system" / "Vendor"
        self.user = self.base / "user" / "default"
        self.executable = self.root / "OrcaSlicer" / "orca-slicer.exe"
        self.executable.parent.mkdir()
        self.executable.write_bytes(b"test placeholder")
        self.bundle = self.executable.parent / "resources" / "profiles"
        self.write(self.system / "machine" / "base.json", name="Machine base", type="machine", instantiation="false",
                   nozzle_diameter=["0.4"], printable_area=["0x0", "200x0", "200x200", "0x200"],
                   printable_height="200", gcode_flavor="marlin", printer_model="Printer", printer_variant="0.4")
        self.write(self.system / "machine" / "printer.json", name="Printer 0.4", type="machine", inherits="Machine base", instantiation="true")
        self.write(self.system / "machine" / "printer06.json", name="Printer 0.6", type="machine", inherits="Machine base", nozzle_diameter=["0.6"], printer_variant="0.6", instantiation="true")
        self.write(self.system / "process" / "base.json", name="Process base", type="process", instantiation="false", layer_height="0.20", wall_loops="2", sparse_infill_density="15%")
        self.write(self.system / "process" / "standard.json", name="Standard 0.4", type="process", inherits="Process base", compatible_printers=["Printer 0.4"], instantiation="true")
        self.write(self.system / "process" / "standard06.json", name="Standard 0.6", type="process", inherits="Process base", compatible_printers=["Printer 0.6"], instantiation="true")
        self.write(self.system / "filament" / "base" / "pla.json", name="PLA base", type="filament", instantiation="false", filament_type=["PLA"], filament_diameter=["1.75"], nozzle_temperature=["210"])
        self.write(self.system / "filament" / "pla.json", name="PLA", type="filament", inherits="PLA base", compatible_printers=["Printer 0.4"], instantiation="true")
        self.write(self.user / "machine" / "custom.json", name="Custom Printer", inherits="Printer 0.4", from_="User", retraction_length=["0.9"])
        self.write(self.user / "process" / "custom.json", name="Custom Process", inherits="Standard 0.4", from_="User", wall_loops="4")
        self.write(self.user / "filament" / "custom.json", name="Custom PLA", inherits="PLA", from_="User", nozzle_temperature=["218"])
        self.runner = Mock()
        self.adapter = OrcaSlicerAdapter(runner=self.runner)
        self.installation = self.verify()

    def write(self, path, **payload):
        path.parent.mkdir(parents=True, exist_ok=True)
        if "from_" in payload:
            payload["from"] = payload.pop("from_")
        path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
        return path

    def verify(self):
        with patch.dict(os.environ, {"APPDATA": str(self.appdata)}):
            return self.adapter.verify_installation(SlicerCandidate(self.executable, SlicerDiscoverySource.KNOWN_PATH, adapter_hint="orca_slicer"))

    def inventory(self):
        inventory = ProfileInventoryService().load(self.adapter, self.installation)
        return inventory, ProfileInheritanceResolver(inventory, self.adapter)

    def candidate(self):
        inventory, _ = self.inventory()
        records = {r.name: r for r in inventory.records}
        return ProfileCandidate(self.installation, records["Custom Printer"], records["Custom Process"], (records["Custom PLA"],))

    def test_full_support_is_verified_without_starting_executable(self):
        self.assertTrue(self.installation.can_slice)
        self.runner.run.assert_not_called()

    def test_roots_exclude_backups_cache_logs_and_unconfigured_vendors(self):
        for name in ("user_backup-v2.4.2", "ota", "log", "cache", "printers"):
            self.write(self.base / name / "machine" / "bad.json", name="Ignored", type="machine")
        self.write(self.bundle / "Other" / "machine" / "bad.json", name="Unconfigured", type="machine")
        names = {r.name for r in self.adapter.discover_profiles(self.verify())}
        self.assertNotIn("Ignored", names)
        self.assertNotIn("Unconfigured", names)

    def test_portable_configuration_is_not_mixed_with_roaming(self):
        portable = self.executable.parent / "data_dir"
        self.write(portable / "user" / "default" / "machine" / "p.json", name="Portable", type="machine")
        roots = self.verify().profile_roots
        self.assertIn((portable / "user").resolve(), roots)
        self.assertNotIn((self.base / "user").resolve(), roots)

    def test_store_virtualized_roaming_configuration_is_found(self):
        package = self.root / "WindowsApps" / "OrcaSlicer.OrcaSlicer_2.4.3.0_x64__publisher"
        executable = package / "VFS" / "OrcaSlicer" / "orca-slicer.exe"
        local = self.root / "Local"
        virtual = local / "Packages" / "OrcaSlicer.OrcaSlicer_publisher" / "LocalCache" / "Roaming" / "OrcaSlicer"
        self.write(virtual / "user" / "default" / "machine" / "p.json", name="Store")
        self.write(virtual / "OrcaSlicer.conf", presets={"machine": "Store"})
        with patch.dict(os.environ, {"LOCALAPPDATA": str(local)}):
            roots = OrcaSlicerDetectionModule().profile_roots_for(executable, appdata_root=self.appdata)
        self.assertIn((virtual / "user").resolve(), roots)
        self.assertNotIn((self.base / "user").resolve(), roots)

    def test_data_dir_file_does_not_override_real_roaming_profiles(self):
        (self.executable.parent / "data_dir").write_bytes(b"not a directory")
        self.assertIn((self.base / "user").resolve(), self.verify().profile_roots)

    def test_nested_templates_and_user_overrides_are_resolved(self):
        candidate = self.candidate()
        effective = self.adapter.resolve_profile_bundle(candidate)
        self.assertEqual(effective.machine, candidate.machine)
        self.assertEqual(effective.effective_values["nozzle_temperature"], ["218"])
        self.assertEqual(effective.effective_values["wall_loops"], "4")
        self.assertEqual(effective.effective_values["nozzle_diameter"], ["0.4"])

    def test_active_mirror_wins_and_missing_bundled_parents_remain_available(self):
        self.write(self.bundle / "Vendor" / "machine" / "printer.json", name="Printer 0.4", type="machine", printable_height="999")
        self.write(self.bundle / "Vendor" / "filament" / "base" / "extra.json", name="Extra base", type="filament", instantiation="false")
        records = self.adapter.discover_profiles(self.verify())
        matches = [r for r in records if r.name == "Printer 0.4"]
        self.assertEqual(len(matches), 1)
        self.assertTrue(matches[0].metadata["orca_active_catalogue"])
        self.assertIn("Extra base", {r.name for r in records})

    def test_unrelated_helpers_model_descriptors_and_wrong_types_are_ignored(self):
        self.write(self.system / "machine" / "model.json", name="Model", type="machine_model")
        self.write(self.system / "process" / "wrong.json", name="Wrong", type="filament")
        self.write(self.system / "process" / "helper.json", ui_state="x")
        self.write(self.system / "manifest.json", name="Manifest", type="machine")
        names = {r.name for r in self.adapter.discover_profiles(self.installation)}
        self.assertFalse(names & {"Model", "Wrong", "Manifest", "helper"})

    def test_corrupt_oversized_and_deep_json_do_not_break_other_profiles(self):
        bad = self.system / "filament" / "bad.json"
        bad.write_text('{"broken":', encoding="utf-8")
        deep = self.system / "filament" / "deep.json"
        deep.write_text("[" * 1200 + "]" * 1200, encoding="utf-8")
        self.adapter._profile_catalog.maximum_profile_bytes = 4096
        huge = self.system / "filament" / "large.json"
        huge.write_bytes(b" " * 4097)
        self.assertIn("Custom PLA", {r.name for r in self.adapter.discover_profiles(self.installation)})

    def test_missing_and_cyclic_parents_are_not_accepted_for_slicing(self):
        path = self.user / "process" / "custom.json"
        for parent in ("Missing", "Custom Process"):
            with self.subTest(parent=parent):
                self.write(path, name="Custom Process", inherits=parent)
                with self.assertRaisesRegex(SlicerProcessError, "nicht vollständig"):
                    self.adapter.resolve_profile_bundle(self.candidate())
        self.runner.run.assert_not_called()

    def test_include_fragments_apply_before_the_user_override(self):
        self.write(self.system / "process" / "include.json", name="Speed fragment", type="process", instantiation="false", wall_loops="5", outer_wall_speed="75")
        self.write(self.user / "process" / "custom.json", name="Custom Process", inherits="Standard 0.4", include=["Speed fragment"], wall_loops="4")
        effective = self.adapter.resolve_profile_bundle(self.candidate())
        self.assertEqual(effective.effective_values["wall_loops"], "4")
        self.assertEqual(effective.effective_values["outer_wall_speed"], "75")

    def test_inventory_cache_changes_when_inherited_file_changes(self):
        service = ProfileInventoryService(self.root / "inventory.json")
        before = service.load(self.adapter, self.installation)
        self.write(self.system / "filament" / "base" / "pla.json", name="PLA base", type="filament", instantiation="false", nozzle_temperature=["230"])
        after = service.load(self.adapter, self.installation)
        self.assertNotEqual(before.fingerprint_sha256, after.fingerprint_sha256)

    def test_active_selection_supports_classic_and_machine_specific_formats(self):
        path = self.base / "OrcaSlicer.conf"
        for payload in (
            {"presets": {"machine": "Custom Printer", "process": "Custom Process", "filament": ["Custom PLA"]}},
            {"filaments": ["Wrong installed filament"], "presets": {"machine": "Custom Printer", "filaments": None},
             "orca_presets": [{"machine": "Other", "process": "Wrong", "filament": "Wrong"},
                              {"machine": "Custom Printer", "process": "Custom Process", "filament": "Custom PLA"}]},
        ):
            self.write(path, **payload)
            with path.open("a", encoding="utf-8") as stream:
                stream.write("\n# MD5 checksum abc\n")
            active = read_active_presets(self.installation)
            self.assertEqual(active.printer_ids, ("Custom Printer",))
            self.assertEqual(active.process_ids, ("Custom Process",))
            self.assertEqual(active.filament_ids, ("Custom PLA",))

    def test_unknown_machine_does_not_borrow_another_machine_selection(self):
        self.write(self.base / "OrcaSlicer.conf", filaments=["Installed library entry"], presets={"machine": "Custom Printer"}, orca_presets=[{"machine": "Other", "process": "Wrong", "filament": "Wrong"}])
        active = read_active_presets(self.installation)
        self.assertFalse(active.process_ids)
        self.assertFalse(active.filament_ids)

    def test_numbered_machine_filaments_do_not_use_the_installed_library(self):
        self.write(self.base / "OrcaSlicer.conf", filaments=["Installed library"],
                   presets={"machine": "Custom Printer", "filaments": None},
                   orca_presets=[{"machine": "Custom Printer", "process": "Custom Process",
                                  "filament_01": "Custom PLA", "filament_02": "PLA"}])
        self.assertEqual(read_active_presets(self.installation).filament_ids, ("Custom PLA", "PLA"))
        self.write(self.base / "OrcaSlicer.conf", filaments=["Installed library"],
                   presets={"machine": "Custom Printer", "filaments": None},
                   orca_presets=[{"machine": "Custom Printer", "filament": "PLA",
                                  "filament_01": "Custom PLA"}])
        self.assertEqual(read_active_presets(self.installation).filament_ids, ("PLA", "Custom PLA"))

    def test_unreadable_optional_catalogue_does_not_break_installation_detection(self):
        original = Path.iterdir
        def restricted(path):
            if path == self.base / "system":
                raise PermissionError("test access denial")
            return original(path)
        with patch.object(Path, "iterdir", restricted):
            result = self.verify()
        self.assertTrue(result.verified)
        self.assertTrue(result.can_slice)
        self.assertIn((self.base / "user").resolve(), result.profile_roots)

    def test_inheritance_stays_inside_user_account_and_vendor_scope(self):
        self.write(self.base / "system" / "Other" / "machine" / "base.json", name="Machine base", type="machine", printable_height="999")
        self.write(self.base / "user" / "cloud-account" / "process" / "base.json", name="Custom Process", inherits="Standard 0.6", wall_loops="9")
        self.write(self.user / "process" / "child.json", name="Local child", inherits="Custom Process")
        records, resolver = self.inventory_for(self.verify())
        child = next(r for r in records.records if r.name == "Local child")
        resolved = resolver.resolve(child)
        self.assertTrue(resolved.valid, resolved.errors)
        self.assertEqual(resolved.effective_values["wall_loops"], "4")
        machine = next(r for r in records.records if r.name == "Custom Printer")
        self.assertEqual(resolver.resolve(machine).effective_values["printable_height"], "200")

    def inventory_for(self, installation):
        inventory = ProfileInventoryService().load(self.adapter, installation)
        return inventory, ProfileInheritanceResolver(inventory, self.adapter)

    def test_profile_count_limit_has_a_readable_error(self):
        self.adapter._profile_catalog.maximum_profile_count = 2
        with self.assertRaisesRegex(SlicerProcessError, "Profilkatalog ist zu groß"):
            self.adapter.discover_profiles(self.installation)

    def test_catalog_filters_compatible_printer_and_hides_templates(self):
        matching = ProfileMatchingService(inventory_service=ProfileInventoryService())
        catalog = matching.catalog(self.installation, self.adapter, selected_machine="Custom Printer")
        self.assertTrue(catalog.complete, catalog.blocking_message)
        process = {r.name for r in catalog.process_options}
        self.assertIn("Custom Process", process)
        self.assertNotIn("Standard 0.6", process)
        self.assertNotIn("Process base", process)
        self.assertEqual({r.source for r in catalog.process_options}, {"user", "system"})
        unfiltered = matching.catalog(self.installation, self.adapter, include_all_profiles=True)
        self.assertIn("Standard 0.6", {r.name for r in unfiltered.process_options})
        self.assertNotIn("Process base", {r.name for r in unfiltered.process_options})

    def add_optional_filaments(self):
        self.write(self.system / "filament" / "other.json", name="Other PLA", type="filament", inherits="PLA base", compatible_printers=["Printer 0.4"], instantiation="true")
        self.write(self.system / "filament" / "other06.json", name="PLA 0.6", type="filament", inherits="PLA base", compatible_printers=["Printer 0.6"], instantiation="true")

    def filament_catalog(self, service=None, **kwargs):
        service = service or ProfileMatchingService(inventory_service=ProfileInventoryService())
        return service.catalog(self.installation, self.adapter, selected_machine="Custom Printer", **kwargs)

    def test_enabled_system_filaments_filter_visibility_without_removing_parents(self):
        self.add_optional_filaments()
        self.write(self.base / "OrcaSlicer.conf", filaments=["Other PLA"], presets={"machine": "Custom Printer", "filament": "Custom PLA"})
        paths = [p for p in self.base.rglob("*") if p.is_file()]
        before = fingerprint_profile_paths(paths)
        catalog = self.filament_catalog()
        self.assertEqual({r.name for r in catalog.filament_options}, {"Other PLA", "Custom PLA"})
        # The unselected PLA parent remains available for the user's profile.
        effective = self.adapter.resolve_profile_bundle(self.candidate())
        self.assertEqual(effective.effective_values["nozzle_temperature"], ["218"])
        self.assertIn("PLA", {r.name for r in self.adapter.discover_profiles(self.installation)})
        self.assertEqual(before, fingerprint_profile_paths(paths))
        self.assertEqual(set(paths), {p for p in self.base.rglob("*") if p.is_file()})
        self.assertIn("Filament 2/4", catalog.profile_filter_summary)

    def test_enabled_filaments_refresh_even_with_cached_inventory(self):
        self.add_optional_filaments()
        service = ProfileMatchingService(inventory_service=ProfileInventoryService())
        before = None
        for selected in (["PLA"], ["Other PLA"], []):
            with self.subTest(selected=selected):
                self.write(self.base / "OrcaSlicer.conf", filaments=selected)
                catalog = self.filament_catalog(service)
                self.assertEqual({r.name for r in catalog.filament_options if r.source == "system"}, set(selected) if selected else {"PLA", "Other PLA"})
                if before:
                    self.assertEqual(before.inventory_fingerprint, catalog.inventory_fingerprint)
                before = catalog

    def test_show_all_reveals_unselected_filaments_and_retains_compatibility_checks(self):
        self.add_optional_filaments()
        self.write(self.base / "OrcaSlicer.conf", filaments=["Other PLA"])
        filtered = self.filament_catalog()
        expanded = self.filament_catalog(include_all_profiles=True)
        self.assertEqual({r.name for r in filtered.filament_options}, {"Other PLA", "Custom PLA"})
        self.assertEqual({r.name for r in expanded.filament_options}, {"PLA", "Other PLA", "PLA 0.6", "Custom PLA"})
        self.assertNotIn("PLA base", {r.name for r in expanded.filament_options})
        self.assertEqual({r.name for r in self.filament_catalog().filament_options}, {"Other PLA", "Custom PLA"})

    def test_explicit_empty_selection_falls_back_to_all_compatible_system_filaments(self):
        from cooling_tower.gui.main_window import MainWindow
        self.add_optional_filaments()
        self.write(self.base / "OrcaSlicer.conf", filaments=[])
        catalog = self.filament_catalog()
        groups = MainWindow._profile_option_groups(catalog.filament_options)
        self.assertEqual([heading for heading, _ in groups], ["- User presets -", "- System presets -"])
        self.assertEqual({r.name for r in groups[1][1]}, {"PLA", "Other PLA"})

    def test_no_user_filaments_omits_user_group_with_or_without_enabled_selection(self):
        from cooling_tower.gui.main_window import MainWindow
        self.add_optional_filaments()
        (self.user / "filament" / "custom.json").unlink()
        for selected in ([], ["Other PLA"]):
            with self.subTest(selected=selected):
                self.write(self.base / "OrcaSlicer.conf", filaments=selected)
                groups = MainWindow._profile_option_groups(self.filament_catalog().filament_options)
                self.assertEqual([heading for heading, _ in groups], ["- System presets -"])
                self.assertEqual({r.name for r in groups[0][1]}, set(selected) if selected else {"PLA", "Other PLA"})

    def test_nonempty_unknown_or_incompatible_selection_does_not_trigger_empty_fallback(self):
        self.add_optional_filaments()
        for selected in (["Removed filament"], ["PLA 0.6"], ["PL"]):
            with self.subTest(selected=selected):
                self.write(self.base / "OrcaSlicer.conf", filaments=selected)
                self.assertEqual([r.name for r in self.filament_catalog().filament_options], ["Custom PLA"])
        (self.user / "filament" / "custom.json").unlink()
        catalog = self.filament_catalog()
        self.assertFalse(catalog.complete)
        self.assertIn("Filamentprofile", catalog.blocking_message)
        self.assertTrue(self.filament_catalog(include_all_profiles=True).complete)

    def test_same_named_user_filament_is_not_hidden_with_its_unselected_system_profile(self):
        self.add_optional_filaments()
        self.write(self.user / "filament" / "custom.json", name="PLA", inherits="PLA base")
        self.write(self.base / "OrcaSlicer.conf", filaments=["Other PLA"])
        matching = [r for r in self.filament_catalog().filament_options if r.name == "PLA"]
        self.assertEqual(len(matching), 1)
        self.assertEqual(matching[0].source, "user")

    def test_filament_selection_accepts_bom_checksum_unicode_and_exact_names(self):
        from cooling_tower.slicers.orca_filament_selection import enabled_system_filaments
        name = "Hersteller PLA Weiß @System"
        path = self.base / "OrcaSlicer.conf"
        path.write_text(json.dumps({"filaments": [name, name.lower(), "  PLA  "]}, ensure_ascii=False) + "\n# MD5 checksum abc\n", encoding="utf-8-sig")
        self.assertEqual(enabled_system_filaments(self.installation), frozenset((name.casefold(), "pla")))

    def test_missing_damaged_or_unreadable_optional_selection_keeps_profiles_available(self):
        from cooling_tower.slicers.orca_filament_selection import enabled_system_filaments
        path = self.base / "OrcaSlicer.conf"
        for content in (None, "{", "[]", "{}", '{"filaments":null}', '{"filaments":"PLA"}', '{"filaments":[null]}', '{"filaments":[""]}', '[' * 1200 + ']' * 1200, " " * (2 * 1024 * 1024 + 1)):
            with self.subTest(content=None if content is None else content[:40]):
                if content is not None:
                    path.write_text(content, encoding="utf-8")
                self.assertIsNone(enabled_system_filaments(self.installation))
                self.assertEqual({r.name for r in self.filament_catalog().filament_options}, {"PLA", "Custom PLA"})
        self.write(path, filaments=["PLA"])
        with patch.object(Path, "open", side_effect=PermissionError("test access denied")):
            self.assertIsNone(enabled_system_filaments(self.installation))

    def test_portable_and_store_selections_are_read_from_the_detected_data_root(self):
        from cooling_tower.slicers.orca_filament_selection import enabled_system_filaments
        self.write(self.base / "OrcaSlicer.conf", filaments=["Wrong Roaming material"])
        roots = (
            self.executable.parent / "data_dir",
            self.root / "Local" / "Packages" / "OrcaSlicer.OrcaSlicer_publisher" / "LocalCache" / "Roaming" / "OrcaSlicer",
        )
        for base in roots:
            with self.subTest(base=base):
                self.write(base / "OrcaSlicer.conf", filaments=["Right material"])
                (base / "user").mkdir()
                installation = replace(self.installation, profile_roots=(base / "user",))
                self.assertEqual(enabled_system_filaments(installation), frozenset(("right material",)))

    def test_matching_and_confirmation_use_visible_user_and_expanded_system_filaments(self):
        from cooling_tower.models.source import SourceArtifact
        from cooling_tower.slicers import ProfileMatchingContext, ProfileMappingStore
        self.add_optional_filaments()
        self.write(self.base / "OrcaSlicer.conf", filaments=["Other PLA"])
        source = self.root / "model.stl"
        source.write_text("matching context fixture", encoding="ascii")
        context = ProfileMatchingContext.from_stl(SourceArtifact.capture(source))
        matching = ProfileMatchingService(inventory_service=ProfileInventoryService(), mapping_store=ProfileMappingStore(self.root / "mappings.json"))
        for filament, expanded in (("Custom PLA", False), ("Other PLA", False), ("PLA", True)):
            with self.subTest(filament=filament, expanded=expanded):
                result = matching.match(context, self.installation, self.adapter, selected_profile_ids={"machine": "Custom Printer", "process": "Custom Process", "filament": filament}, include_all_profiles=expanded)
                self.assertIsNotNone(result.selected, result.message)
                self.assertEqual(result.selected.filament.name, filament)
                confirmed = matching.confirm(result)
                self.assertTrue(confirmed.can_use_stl_mode)
                self.assertTrue(confirmed.user_confirmed)
                self.assertEqual(confirmed.selected.filament.name, filament)
        hidden = matching.match(context, self.installation, self.adapter, selected_profile_ids={"machine": "Custom Printer", "process": "Custom Process", "filament": "PLA"})
        self.assertIsNone(hidden.selected)
        self.assertFalse(hidden.can_use_stl_mode)
        # Expanding the catalogue alone still proposes only enabled materials.
        (self.user / "filament" / "custom.json").unlink()
        automatic = matching.match(context, self.installation, self.adapter, selected_profile_ids={"machine": "Custom Printer", "process": "Custom Process"}, include_all_profiles=True)
        self.assertIsNotNone(automatic.selected, automatic.message)
        self.assertEqual(automatic.selected.filament.name, "Other PLA")

    def test_cli_uses_only_isolated_fully_resolved_profile_copies(self):
        effective = self.adapter.resolve_profile_bundle(self.candidate())
        paths = tuple(r.path for r in self.adapter.discover_profiles(self.installation))
        before = fingerprint_profile_paths(paths)
        model = self.root / "model.stl"
        model.write_text("fixture", encoding="ascii")
        request = SliceRequest(model, effective, self.root / "output", temporary_overrides={"sparse_infill_density": "100%"})
        prepared = self.adapter.prepare_slice(request)
        try:
            for option in ("--load-settings", "--load-filaments"):
                filenames = prepared.arguments[prepared.arguments.index(option) + 1].split(";")
                for filename in filenames:
                    path = Path(filename)
                    self.assertIn(prepared.working_root, path.parents)
                    payload = json.loads(path.read_text(encoding="utf-8"))
                    self.assertFalse(payload.get("inherits"))
                    self.assertFalse(payload.get("include"))
                    if payload["type"] == "process":
                        self.assertEqual(payload["wall_loops"], "4")
                        self.assertEqual(payload["sparse_infill_density"], "100%")
                    if payload["type"] == "filament":
                        self.assertEqual(payload["nozzle_temperature"], ["218"])
            self.assertEqual(before, fingerprint_profile_paths(paths))
        finally:
            self.adapter.cleanup_prepared_slice(prepared)
        self.assertFalse(prepared.working_root.exists())

    def test_missing_and_mismatched_roles_do_not_start_slicing(self):
        effective = self.adapter.resolve_profile_bundle(self.candidate())
        model = self.root / "model.stl"
        model.write_text("fixture", encoding="ascii")
        for invalid in (replace(effective, process=None), replace(effective, filaments=())):
            with self.assertRaisesRegex(SlicerProcessError, "ausgewählt"):
                self.adapter.slice_model(SliceRequest(model, invalid, self.root / "output"))
        self.runner.run.assert_not_called()
        for invalid in (replace(effective, process=effective.machine),
                        replace(effective, process=replace(effective.process, adapter_id="bambu_studio"))):
            with self.assertRaisesRegex(SlicerProcessError, "Profilrollen"):
                self.adapter.slice_model(SliceRequest(model, invalid, self.root / "output"))
        self.runner.run.assert_not_called()

    def test_working_and_output_paths_cannot_point_into_slicer_directories(self):
        from cooling_tower.write_policy import ProtectedWritePathError
        effective = self.adapter.resolve_profile_bundle(self.candidate())
        request = SliceRequest(self.root / "model.stl", effective, self.root / "output")
        before = fingerprint_profile_paths(r.path for r in self.adapter.discover_profiles(self.installation))
        with self.assertRaises(ProtectedWritePathError):
            self.adapter.build_slice_command(request, request.model_path, request.output_directory, self.system)
        with self.assertRaises(ProtectedWritePathError):
            self.adapter.build_slice_command(request, request.model_path, self.user / "output", self.root / "working")
        self.assertEqual(before, fingerprint_profile_paths(r.path for r in self.adapter.discover_profiles(self.installation)))

    def test_store_data_siblings_are_protected_during_final_export(self):
        from cooling_tower.write_policy import ProtectedWritePathError
        from cooling_tower.preview import PreviewExportService
        effective = self.adapter.resolve_profile_bundle(self.candidate())
        virtual = self.root / "Local" / "Packages" / "Orca_family" / "LocalCache" / "Roaming" / "OrcaSlicer"
        effective = replace(effective, installation=replace(
            self.installation, profile_roots=(virtual / "user", virtual / "system" / "Vendor"),
        ))
        request = SimpleNamespace(adapter=self.adapter, effective_profile=effective)
        for location in (virtual, virtual / "log" / "output", virtual / "OrcaSlicer.conf"):
            with self.subTest(location=location):
                with self.assertRaises(ProtectedWritePathError):
                    self.adapter.validate_output_directory(effective, location)
                # The exporter must reject before accessing preview artifacts
                # or creating a directory, in automatic and manual use alike.
                with self.assertRaises(ProtectedWritePathError):
                    PreviewExportService().export(None, request, location)
        self.assertFalse(virtual.exists())
        self.adapter.validate_output_directory(effective, self.root / "my-exports")

    def test_timeout_cancellation_crash_and_missing_output_have_readable_failures(self):
        from cooling_tower.slicers import ProcessOutcome
        effective = self.adapter.resolve_profile_bundle(self.candidate())
        model = self.root / "model.stl"
        model.write_text("fixture", encoding="ascii")
        for flags, fragment in (({"timed_out": True}, "Zeitlimit"),
                                ({"cancelled": True}, "abgebrochen"),
                                ({"crashed": True}, "abgestürzt"),
                                ({}, "keine G-Code-Datei")):
            with self.subTest(flags=flags):
                self.runner.run.return_value = ProcessOutcome(
                    command=(str(self.executable),), return_code=0,
                    stdout="", stderr="", duration_s=0.01, **flags,
                )
                result = self.adapter.slice_model(SliceRequest(
                    model, effective, self.root / "output", retain_failure_diagnostics=False,
                ))
                self.assertFalse(result.success)
                self.assertIn(fragment, result.failure_reason)
                self.assertFalse((self.root / "output").exists())

    def test_native_joint_command_uses_embedded_settings_and_fixed_positions(self):
        from cooling_tower.calibration.slice_evaluator import build_calibration_profile
        effective = self.adapter.resolve_profile_bundle(self.candidate())
        temporary, _ = build_calibration_profile(effective, self.root / "temporary")
        model = self.root / "joint.3mf"
        model.write_bytes(b"fixture")
        request = SliceRequest(model, temporary, self.root / "output", purpose="calibration", preserve_model_positions=True)
        prepared = self.adapter.prepare_slice(request)
        try:
            self.assertNotIn("--arrange", prepared.arguments)
            self.assertNotIn("--load-settings", prepared.arguments)
            self.assertNotIn("--load-filaments", prepared.arguments)
            self.assertIn("--datadir", prepared.arguments)
            self.assertEqual(Path(prepared.arguments[-1]), prepared.copied_model)
        finally:
            self.adapter.cleanup_prepared_slice(prepared)

    def test_orca_gui_groups_real_catalogue_and_closes_after_profile_error(self):
        os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
        from PySide6.QtWidgets import QApplication
        from PySide6.QtCore import QTimer
        from cooling_tower.gui.main_window import MainWindow
        from cooling_tower.slicers import SlicerDiscoveryResult, SlicerGuiState
        from gui_lifecycle import dispose_test_widget
        type(self)._app = QApplication.instance() or QApplication([])
        app = type(self)._app
        self.add_optional_filaments()
        self.write(self.base / "OrcaSlicer.conf", filaments=["PLA"], presets={"machine": "Custom Printer"})
        matching = ProfileMatchingService(inventory_service=ProfileInventoryService())
        service = SimpleNamespace(
            adapter_for=lambda _: self.adapter, remember_selection=lambda _: None,
            discover_installations=lambda *args, **kwargs: SlicerDiscoveryResult(
                installations=(self.installation,), recommended_key=self.installation.identity_key,
                gui_state=SlicerGuiState.AVAILABLE, message="OrcaSlicer erkannt"),
        )
        window = MainWindow(user_settings_path=self.root / "settings.json", slicer_service=service,
                            profile_service=matching, enable_update_check=False,
                            enable_startup_slicer_discovery=False)
        self.addCleanup(dispose_test_widget, window)
        def wait_for(condition):
            deadline = time.monotonic() + 8
            while not condition() and time.monotonic() < deadline:
                app.processEvents()
                time.sleep(0.005)
            self.assertTrue(condition())
        window.start_slicer_discovery()
        wait_for(lambda: window.profile_catalog is not None)
        wait_for(lambda: not window.background_job_manager.active_jobs())
        self.assertEqual({r.name for r in window.profile_catalog.filament_options}, {"PLA", "Custom PLA"})
        self.assertNotIn("Other PLA", [window.filament_profile_combo.itemText(i) for i in range(window.filament_profile_combo.count())])
        window.show_all_profiles_checkbox.setChecked(True)
        wait_for(lambda: window.profile_catalog is not None and len(window.profile_catalog.machine_options) > 1)
        wait_for(lambda: not window.background_job_manager.active_jobs())
        for combo in (window.machine_profile_combo, window.process_profile_combo, window.filament_profile_combo):
            labels = [combo.itemText(i) for i in range(combo.count())]
            self.assertIn("- User presets -", labels)
            self.assertIn("- System presets -", labels)
            self.assertTrue(combo.isEnabled())
        self.assertIn("Other PLA", [window.filament_profile_combo.itemText(i) for i in range(window.filament_profile_combo.count())])
        window.show_all_profiles_checkbox.setChecked(False)
        wait_for(lambda: window.profile_catalog is not None and {r.name for r in window.profile_catalog.filament_options} == {"PLA", "Custom PLA"})
        wait_for(lambda: not window.background_job_manager.active_jobs())
        self.assertNotIn("Other PLA", [window.filament_profile_combo.itemText(i) for i in range(window.filament_profile_combo.count())])
        with patch.object(matching, "catalog", side_effect=RuntimeError("internal diagnostic")):
            window.start_profile_catalog_loading(force_inventory=True)
            wait_for(lambda: window.profile_status_label.property("state") == "error")
            wait_for(lambda: not window.background_job_manager.active_jobs())
        self.assertTrue(window.profile_status_label.text().strip())
        self.assertNotIn("internal diagnostic", window.profile_status_label.text())
        self.assertFalse(window.profile_confirm_button.isEnabled())
        heartbeat = []
        QTimer.singleShot(0, lambda: heartbeat.append(True))
        wait_for(lambda: bool(heartbeat))
        started = time.monotonic()
        self.assertTrue(window.close())
        self.assertLess(time.monotonic() - started, 1.0)


if __name__ == "__main__":
    unittest.main()
