from pathlib import Path
import sys
import tempfile
import unittest
import zipfile
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'src'))
from native_project_fixtures import write_native
from cooling_tower.native_project.context import load_context, NativeProjectError, ProjectProblem
from cooling_tower.native_project.session import NativeProjectSession, project_bounds
from cooling_tower.protected_io import OwnedWorkspace

class NativeContextTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.path=Path(self.temp.name)/'neutral.3mf'

    def load(self):
        lease=OwnedWorkspace();self.addCleanup(lease.close)
        return load_context(lease.capture(self.path))

    def test_content_identity_ignores_profile_and_printer_names(self):
        write_native(self.path,values={'app_full_name':'AnycubicSlicerNext','app_version':'2.0.0.3','printer_model':'Unregistered custom printer'})
        self.assertEqual(self.load().adapter_id,'anycubic_slicer_next')
        write_native(self.path,extra_metadata='<metadata name="OrcaSlicer">2.4.2</metadata>')
        self.assertEqual(self.load().adapter_id,'orca_slicer')

    def test_legacy_fork_uses_native_schema_markers(self):
        write_native(self.path,producer='BambuStudio-1.4.1.2',values={key:[] for key in (
            'fan_cooling_layer_time_BRASS','fan_cooling_layer_time_HS','nozzle_temperature_BRASS','nozzle_temperature_HS','flush_volumes_chan_multipliers')})
        self.assertEqual(self.load().adapter_id,'anycubic_slicer_next')

    def test_bindings_and_settings_are_immutable_and_option_specific(self):
        write_native(self.path)
        c=self.load();first=c.binding('1',engine_version='engine-a')
        c.settings.get('nozzle_diameter').append('9')
        self.assertEqual(c.nozzle_diameters,(.4,))
        self.assertEqual(first,c.binding('1',engine_version='engine-a'))
        self.assertNotEqual(first,c.binding('1',engine_version='engine-b'))
        self.assertNotEqual(first,c.binding('1',engine_version='engine-a',options={'test':True}))
        self.assertEqual(project_bounds(c,'1').minimum_x_mm,96)

    def test_incomplete_geometry_only_is_distinct_from_corruption(self):
        write_native(self.path)
        original=self.path.read_bytes()
        with zipfile.ZipFile(self.path,'w') as result,zipfile.ZipFile(__import__('io').BytesIO(original)) as before:
            for name in before.namelist():
                if name!='Metadata/project_settings.config':result.writestr(name,before.read(name))
        with self.assertRaises(NativeProjectError) as found:self.load()
        self.assertEqual(found.exception.problem,ProjectProblem.INCOMPLETE)
        self.path.write_bytes(b'broken')
        with self.assertRaises(NativeProjectError) as found:self.load()
        self.assertEqual(found.exception.problem,ProjectProblem.DAMAGED)

    def test_global_and_object_scripts_are_rejected_before_native_execution(self):
        for values,config in [({'post_process':['external-command']},None),({},'<config><object id="1"><metadata key="post_process" value="external-command"/></object></config>')]:
            write_native(self.path,values=values,model_config=config)
            with self.assertRaises(NativeProjectError) as found:self.load()
            self.assertEqual(found.exception.problem,ProjectProblem.UNSAFE)

    def test_import_snapshot_remains_authoritative_after_external_edit(self):
        write_native(self.path)
        session=NativeProjectSession(self.path);self.addCleanup(session.close)
        digest=session.context.snapshot.sha256
        self.path.write_bytes(b'externally replaced')
        self.assertTrue(session.original_changed())
        session.context.snapshot.verify()
        self.assertEqual(session.context.snapshot.sha256,digest)

    def test_custom_printer_without_model_identifier_keeps_its_embedded_context(self):
        write_native(self.path,values={'printer_model':'','printer_settings_id':'Neutral custom printer'})
        context=self.load()
        self.assertEqual(context.printer,'Neutral custom printer')
        self.assertEqual(context.settings.get('printer_model'),'')

    def test_prusa_percentage_uses_layer_height_and_empty_native_vector_is_safe(self):
        write_native(self.path,producer='PrusaSlicer-2.9.6')
        with zipfile.ZipFile(self.path,'a') as archive:
            archive.writestr('Metadata/Slic3r_PE.config','\n'.join((
                '; printer_model = Neutral printer','; nozzle_diameter = 0.4',
                '; filament_type = PLA','; bed_shape = 0x0,200x0,200x200,0x200',
                '; max_print_height = 200','; layer_height = 0.2',
                '; first_layer_height = 150%','; post_process = "";""')))
        context=self.load()
        self.assertAlmostEqual(context.initial_layer_height,.3)
        self.assertEqual(context.settings.get('first_layer_height'),'150%')

    def test_height_ranges_require_the_native_layer_height_even_for_wall_overrides(self):
        for options, valid in (
            ('<option opt_key="wall_loops">5</option>', False),
            ('<option opt_key="layer_height">nan</option>', False),
            ('<option opt_key="layer_height">0</option>', False),
            ('<option opt_key="layer_height">0.2</option><option opt_key="wall_loops">5</option>', True),
        ):
            with self.subTest(options=options):
                write_native(self.path)
                with zipfile.ZipFile(self.path,'a') as archive:
                    archive.writestr('Metadata/layer_config_ranges.xml',
                        '<objects><object id="1"><range min_z="1.8" max_z="2.8">'
                        + options + '</range></object></objects>')
                if valid:
                    self.assertEqual(self.load().layer_height,.2)
                else:
                    with self.assertRaises(NativeProjectError) as found: self.load()
                    self.assertEqual(found.exception.problem,ProjectProblem.INCOMPLETE)

if __name__=='__main__':unittest.main()
