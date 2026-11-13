from pathlib import Path
from contextlib import contextmanager, nullcontext
from dataclasses import replace
from threading import Event
import sys
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
from test_phase2 import make_layer
from cooling_tower.native_project.adjust import adjust_radius_profile, joint_radius_scale
from cooling_tower.native_project.options import NativeCalibrationOptions
from cooling_tower.native_project.automatic import (
    NativeAutomaticService, NativeAutomaticState, _shell_overrides, _solid_foot_layers,
)
from cooling_tower.native_project.session import NativeOperationCancelled, NativeSliceError, check_cancel
from cooling_tower.native_project.settings import NativeGenerationSettings, effective_generation_settings
from cooling_tower.native_project.top_layer import SupportFootprint, TopLayerShape, extend_mesh
from cooling_tower.tower.profile import TowerProfileConfig, build_tower_radius_profile


class NativeJointFeedbackTests(unittest.TestCase):
    def test_native_wide_foot_preserves_regular_diameter_limit_and_stl_default(self):
        from cooling_tower.tower.solid_profile import build_solid_tower_profile, ProfileFeasibilityError
        from cooling_tower.tower.mesh_generator import generate_solid_tower_mesh, TowerMeshConfig
        from cooling_tower.tower.mesh_validator import validate_triangle_mesh
        layers = tuple(make_layer(i,total_time_s=20.,deposition_time_s=10.,deposition_path_mm=100.) for i in range(1,1001))
        settings = NativeGenerationSettings(simulate_full_tower_infill=True)
        profile = build_tower_radius_profile(layers,TowerProfileConfig(9.,2.5,20.,5,frozenset()))
        with self.assertRaises(ProfileFeasibilityError):
            build_solid_tower_profile(profile,settings,object_height_mm=200.)
        solid = build_solid_tower_profile(profile,settings,object_height_mm=200.,allow_wide_base=True)
        self.assertAlmostEqual(solid.base_outer_radius_mm,26.25)
        self.assertGreater(solid.base_outer_radius_mm,settings.maximum_outer_radius_mm)
        self.assertTrue(all(point.radius_mm<=settings.maximum_outer_radius_mm for point in solid.points if point.z_mm>100.))
        mesh = generate_solid_tower_mesh(solid,TowerMeshConfig(60))
        self.assertTrue(validate_triangle_mesh(mesh).is_valid)

    def test_profile_threshold_uses_embedded_adapter_value_without_mutating_manual_setting(self):
        from types import SimpleNamespace
        manual = NativeGenerationSettings(maximum_expansion_angle_deg=50.)
        for adapter,key in (('prusa_slicer','support_material_threshold'),
                            ('bambu_studio','support_threshold_angle'),
                            ('anycubic_slicer_next','support_threshold_angle'),
                            ('orca_slicer','support_threshold_angle')):
            with self.subTest(adapter=adapter):
                context = SimpleNamespace(adapter_id=adapter,settings={key:'25.5'})
                resolved = effective_generation_settings(manual,context)
                self.assertEqual(resolved.maximum_expansion_angle_deg,64.5)
                self.assertEqual(manual.maximum_expansion_angle_deg,50.)
                free = NativeGenerationSettings(limit_expansion_to_profile=False)
                self.assertIs(effective_generation_settings(free,context),free)
                context.settings[key] = '0'
                self.assertEqual(effective_generation_settings(manual,context).maximum_expansion_angle_deg,60.)
                context.settings[key] = 'nan'
                self.assertIs(effective_generation_settings(manual,context),manual)

    def test_cooling_replan_corrects_actual_radius_and_preserves_excluded_layers(self):
        layers = tuple(make_layer(i, total_time_s=20., deposition_time_s=10.,
                                  deposition_path_mm=100.) for i in (1, 2))
        profile = build_tower_radius_profile(layers, TowerProfileConfig(
            12., 2.5, 40., 5, frozenset((2,))))
        options = NativeCalibrationOptions()
        combined = {1: 10., 2: 10.}
        scale = joint_radius_scale({1: combined[1]}, target_time_s=12., config=options)
        adjusted, _ = adjust_radius_profile(profile, layers, {1: 0., 2: 0.},
            target_time_s=12., realized_outer_radii_mm={1: 10., 2: 10.},
            combined_layer_times_s=combined, coupled_radius_scale=scale, config=options)
        # The source alone exceeded the target; a changed joint cooling plan
        # must still enlarge the actual deficient cross-section.
        self.assertGreater(adjusted.layers[0].radius_mm, 10.)
        self.assertLessEqual(adjusted.layers[0].radius_mm, 40.)
        self.assertEqual(adjusted.layers[1].radius_mm, 2.5)

    @contextmanager
    def _measured_slices(self, measurements, *, placement_error=None):
        context = SimpleNamespace(adapter_id='bambu_studio', settings=Mock(), nozzle_diameters=(.4,))
        context.settings.get.return_value = None
        def result(seconds):
            layers = tuple(make_layer(i, total_time_s=seconds, deposition_time_s=1.,
                deposition_path_mm=1.) for i in range(1, 31))
            return SimpleNamespace(context=context, plate_id='1', composed=None, installation=object(),
                analysis=SimpleNamespace(layers=layers, layer_count=len(layers)),
                verify=Mock(), close=Mock(), gcode_path=None, toolpaths=object())
        source = result(4.)
        candidates = [result(value) if isinstance(value, (int, float)) else value for value in measurements]
        pending = iter(candidates)

        def slice_candidate(*_, cancellation_event, **_kwargs):
            candidate = next(pending)
            if isinstance(candidate, Exception):
                raise candidate
            if callable(candidate):
                return candidate(cancellation_event)
            return candidate

        session = SimpleNamespace(context=context, slice=Mock(side_effect=slice_candidate))
        center = SimpleNamespace(center_x_mm=50., center_y_mm=50.)
        place = Mock(return_value=center, side_effect=(center, placement_error) if placement_error else None)
        space = SimpleNamespace(place=place, filament=1)
        compose = Mock()
        with patch.multiple('cooling_tower.native_project.automatic',
                object_geometry_layers=Mock(return_value=source.analysis.layers),
                tower_geometry_height=Mock(return_value=6.), parse_bed_geometry=Mock(return_value=object()),
                NativePrintSpace=SimpleNamespace(capture=Mock(return_value=space)),
                OwnedWorkspace=Mock(return_value=nullcontext()),
                append_tower=compose, _tower_paths=Mock(return_value=(set(range(1,31)), {}))):
            yield session, source, candidates, compose

    def _run_measured_slices(self, measurements):
        previews, statuses = [], []
        with self._measured_slices(measurements) as (session, source, candidates, _):
            outcome = NativeAutomaticService().run(session, source, NativeGenerationSettings(),
                options=NativeCalibrationOptions(maximum_separate_iterations=2, maximum_iterations=3),
                progress=lambda *entry: statuses.append(entry), preview=previews.append)
        phases = [call.kwargs['tower_only'] for call in session.slice.call_args_list]
        return outcome, candidates, phases, previews, statuses

    def test_separate_and_joint_slices_continue_until_the_measured_target(self):
        outcome, candidates, phases, previews, statuses = self._run_measured_slices((1., 2., 6., 10., 9.))
        self.assertEqual(phases, [True, True, False, False, False])
        self.assertEqual([preview.tower_only for preview in previews], [True, True, False, False, False])
        self.assertEqual(previews[1].estimated_times, (6.,)*30)
        self.assertEqual([item.minimum_combined_time_s for item in outcome.iterations], [6., 10., 9.])
        self.assertEqual(outcome.state, NativeAutomaticState.CONVERGED)
        self.assertIn((3, 3, 'Turm wird ergänzt und gemeinsam geslict'), statuses)
        for candidate in candidates[:-1]:
            candidate.close.assert_called_once()
        candidates[-1].close.assert_not_called()
        outcome.close()
        candidates[-1].close.assert_called_once()
        self.assertLess(joint_radius_scale({1: 10., 2: 15.}, target_time_s=9.,
                                          config=NativeCalibrationOptions()), 1.)

        failure = NativeSliceError('Ein weiterer Test-Slice ist fehlgeschlagen.')
        outcome, candidates, phases, previews, _ = self._run_measured_slices((1., 2., 6., failure))
        self.assertEqual(phases, [True, True, False, False])
        self.assertEqual(len(previews), 3)
        self.assertEqual(outcome.state, NativeAutomaticState.LIMIT_REACHED)
        self.assertIn(str(failure), outcome.message)
        self.assertIs(outcome.prepared, candidates[2])
        candidates[2].close.assert_not_called()
        outcome.close()

    def test_best_survives_worse_slices_and_repeated_pause_and_resume(self):
        acceptance = Event()

        def interrupt(stop):
            acceptance.set()
            check_cancel(stop)

        histories = []

        def refine(profile, _layers, _added, *, measurement_history=None, **_kwargs):
            if measurement_history:
                histories.append(tuple(measurement_history[1]))
            radius = 7. + len(histories)*.8
            return replace(profile, layers=tuple(replace(layer, radius_mm=radius, calculated_radius_mm=radius)
                                                 for layer in profile.layers)), .5

        service = NativeAutomaticService()
        settings = NativeGenerationSettings(target_layer_time_s=11.)
        options = NativeCalibrationOptions(maximum_separate_iterations=2, maximum_iterations=50, time_tolerance_s=.01)
        previews, starts = [], []

        def progress(number, _maximum, message):
            if message == 'Turm wird ergänzt und gemeinsam geslict':
                starts.append(number)

        measurements = (1., 2., 11.44, 10.96, 11.32, interrupt, 11.30, interrupt, 11.25) + (11.18,) * 45
        with self._measured_slices(measurements) as (
                session, source, candidates, compose), patch(
                'cooling_tower.native_project.automatic.adjust_radius_profile', side_effect=refine):
            arguments = dict(options=options, preview=previews.append, progress=progress, acceptance_event=acceptance)
            first = service.run(session, source, settings, **arguments)
            self.assertEqual(first.state, NativeAutomaticState.PAUSED)
            self.assertIs(first.prepared, candidates[3])
            self.assertEqual(first.best_candidate.minimum_layer_time_s, 10.96)
            self.assertEqual(len(first.iterations), 3)
            self.assertEqual(first.separate_iterations, 2)

            acceptance.clear()
            second = service.run(session, source, settings, resume=first, **arguments)
            self.assertEqual(second.state, NativeAutomaticState.PAUSED)
            self.assertIs(second.prepared, candidates[3])
            self.assertEqual(len(second.iterations), 4)

            acceptance.clear()
            final = service.run(session, source, settings, resume=second, **arguments)
            self.assertEqual(final.state, NativeAutomaticState.LIMIT_REACHED)
            self.assertIsNone(final.continuation)
            self.assertIs(final.prepared, candidates[3])
            self.assertEqual(final.best_iteration, 2)
            self.assertEqual([item.minimum_combined_time_s for item in final.iterations],
                             [11.44, 10.96, 11.32, 11.30, 11.25] + [11.18] * 45)
            self.assertEqual(starts, [1, 2, 3, 4, 4, 5, 5] + list(range(6, 51)))
            self.assertEqual([preview.best_candidate.number for preview in previews if not preview.tower_only],
                             [1] + [2] * 49)
            self.assertEqual([len(history) for history in histories], list(range(1, 51)))
            self.assertEqual([call.kwargs['tower_only'] for call in session.slice.call_args_list],
                             [True, True] + [False] * 52)
            meshes = [hash(call.args[2].vertices) for call in compose.call_args_list]
            self.assertNotEqual(meshes[4], meshes[5])
            self.assertEqual(meshes[5], meshes[6])
            self.assertEqual(meshes[7], meshes[8])
            candidates[3].close.assert_not_called()
            final.close()
        for candidate in candidates:
            if not callable(candidate):
                candidate.close.assert_called_once()

    def test_cancellation_takes_priority_over_acceptance(self):
        acceptance, cancellation = Event(), Event()

        def interrupt(stop):
            acceptance.set()
            cancellation.set()
            check_cancel(stop)

        with self._measured_slices((6., interrupt)) as (session, source, candidates, _):
            with self.assertRaises(NativeOperationCancelled):
                NativeAutomaticService().run(session, source, NativeGenerationSettings(),
                    options=NativeCalibrationOptions(maximum_separate_iterations=0),
                    acceptance_event=acceptance, cancellation_event=cancellation)
        candidates[0].close.assert_called_once()

    def test_unplaceable_following_candidate_keeps_verified_best(self):
        error = ValueError('Kein Platz für die nächste Turmgeometrie.')
        with self._measured_slices((6.,), placement_error=error) as (session, source, candidates, _):
            result = NativeAutomaticService().run(session, source, NativeGenerationSettings(),
                options=NativeCalibrationOptions(maximum_separate_iterations=0))
        self.assertIs(result.prepared, candidates[0])
        self.assertEqual(result.best_iteration, 1)
        self.assertIn(str(error), result.message)
        candidates[0].close.assert_not_called()
        result.close()

    def test_shell_profile_values_and_local_solid_foot(self):
        from cooling_tower.tower.solid_profile import build_solid_tower_profile
        layers = tuple(make_layer(i, total_time_s=20., deposition_time_s=10.,
            deposition_path_mm=100.) for i in range(1, 301))
        settings = NativeGenerationSettings(concave_base=True, automatic_base_width=False,
            manual_base_width_mm=80., tower_wall_count=1, automatic_top_shell_layers=True, bottom_shell_layers=0)
        profile = build_tower_radius_profile(layers, TowerProfileConfig(9., 2.5, 20., 5, frozenset()))
        solid = build_solid_tower_profile(profile, settings, allow_wide_base=True, concave_base=True)
        full = build_solid_tower_profile(profile, NativeGenerationSettings(simulate_full_tower_infill=True,
            automatic_base_width=False, manual_base_width_mm=80.), allow_wide_base=True)
        self.assertGreater(solid.base_taper_end_z_mm, 0.)
        self.assertEqual(tuple(point for point in solid.points if point.z_mm < solid.base_taper_end_z_mm),
                         tuple(point for point in full.points if point.z_mm < solid.base_taper_end_z_mm))
        for adapter, suffix in (('bambu_studio', 'shell_layers'), ('prusa_slicer', 'solid_layers')):
            context = SimpleNamespace(adapter_id=adapter, settings={f'top_{suffix}': '12'}, nozzle_diameters=(.4,))
            top, bottom = tuple(_shell_overrides(settings, context))
            self.assertEqual(top, ('top', 12, True))
            self.assertEqual(bottom, ('bottom', 0, False))
            dense_layers = _solid_foot_layers(solid, settings, .4)
            self.assertGreater(dense_layers, 5)
            self.assertLess(dense_layers, len(layers))
        with self.assertRaises(ValueError):
            NativeGenerationSettings(top_shell_layers=6)

    def test_top_layer_support_prefers_center_then_nearest_filled_region(self):
        def footprint(x0, x1):
            lines = tuple(((x0, row*.1), (x1, row*.1), .4) for row in range(-15, 16))
            return SupportFootprint(lines, (0., 0.), 6., .4)
        self.assertEqual(footprint(-2., 2.).nearest_disk(1., 6., 32, .4), (0.,0.))
        shift = footprint(1.5, 4.).nearest_disk(1., 6., 32, .4)
        self.assertGreater(shift[0], 1.5)
        self.assertLess(shift[0], 2.5)
        self.assertAlmostEqual(shift[1], 0.)
        wall = SupportFootprint((((-5., -1.), (-5., 1.), .4),), (0.,0.), 6., .4)
        self.assertIsNone(wall.nearest_disk(1., 6., 32, .4))
        self.assertTrue(wall.supports((((-5., -.8), (-5., .8), .4),)))
        self.assertFalse(wall.supports((((-5., 0.), (0., 0.), .4),)))

    def test_centered_offset_and_wall_top_meshes_are_closed(self):
        from cooling_tower.tower.mesh_generator import generate_solid_tower_mesh, TowerMeshConfig
        from cooling_tower.tower.mesh_validator import validate_triangle_mesh
        from cooling_tower.tower.solid_profile import SolidTowerPoint, SolidTowerProfile
        points = (SolidTowerPoint(0., 6., 'base', None), SolidTowerPoint(.2, 6., 'layer', 1))
        mesh = generate_solid_tower_mesh(SolidTowerProfile(NativeGenerationSettings(), points, (),
            (), .2, 6., .2), TowerMeshConfig(32))
        for shape in (TopLayerShape(2.5), TopLayerShape(2.5, (2.,0.)), TopLayerShape(6., inner_radius=5.2)):
            with self.subTest(shape=shape):
                extended = extend_mesh(mesh, shape, .4)
                self.assertTrue(validate_triangle_mesh(extended).is_valid)
                self.assertEqual(max(point[2] for point in extended.vertices), .4)

if __name__ == '__main__':
    unittest.main()
