from __future__ import annotations

import os
import sys
import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from dataclasses import FrozenInstanceError, replace
from pathlib import Path
from threading import Event
from types import SimpleNamespace
from unittest.mock import patch


PROJECT_ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = PROJECT_ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))


from cooling_tower.calibration.gcode_integration import determine_occupied_bounds
from cooling_tower.models import (
    BedBounds,
    CalibrationConfig,
    CalibrationMode,
    CalibrationState,
    GenerationSettings,
    OccupiedBounds,
    TowerPlacement,
)
from cooling_tower.preview import (
    LineSegment3D,
    OutputMode,
    Point3D,
    PreviewBuildError,
    PreviewCancelled,
    PreviewRequest,
    PreviewService,
    PreviewSourceCacheKey,
    PreviewSourceData,
    PreviewSourceDataCache,
    analyze_deposition_toolpaths,
    extract_deposition_toolpaths,
)
from cooling_tower.services import GCodeAnalysisService


def source_gcode(layer_count: int = 4, moves_per_layer: int = 4) -> str:
    lines = ["; preview source cache", "G90", "M83", "M204 S1000"]
    for layer in range(1, layer_count + 1):
        z = layer * 0.2
        lines.append(f"G1 Z{z:.2f} F600")
        x = 10.0 + layer
        y = 10.0
        for move in range(moves_per_layer):
            x += 1.0
            y += 0.5 if move % 2 else 1.0
            lines.append(f"G1 X{x:.3f} Y{y:.3f} E0.4 F900")
    return "\n".join(lines) + "\n"


class SyntheticSuccessfulCalibrator:
    def __init__(self) -> None:
        self.calls: list[dict[str, object]] = []

    def calibrate(self, _snapshot, _settings, **kwargs):
        self.calls.append(dict(kwargs))
        root = Path(kwargs["output_directory"])
        root.mkdir(parents=True, exist_ok=True)
        artifact = root / "tower.stl"
        artifact.write_text("solid tower\nendsolid tower\n", encoding="utf-8")
        return SimpleNamespace(
            state=CalibrationState.CONVERGED,
            success=True,
            has_usable_improvement=True,
            profile=SimpleNamespace(
                points=(
                    SimpleNamespace(outer_radius_mm=5.0, z_mm=0.2),
                    SimpleNamespace(outer_radius_mm=6.0, z_mm=5.0),
                )
            ),
            placement=TowerPlacement(
                80.0,
                20.0,
                6.0,
                BedBounds(0.0, 100.0, 0.0, 100.0),
                25.0,
            ),
            warnings=(),
            failures=(),
            gcode_path=None,
            stl_path=artifact,
            project_path=None,
            iterations=(),
            best_iteration=None,
        )


class PreviewSourceCacheIntegrationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.source = self.root / "source.gcode"
        self.source.write_text(source_gcode(), encoding="utf-8")
        self.analysis_service = GCodeAnalysisService()
        self.snapshot = self.analysis_service.analyze(self.source)

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def request(self, **changes) -> PreviewRequest:
        values = {
            "snapshot": self.snapshot,
            "settings": GenerationSettings(),
            "output_mode": OutputMode.STL,
            "calibration_config": CalibrationConfig(
                mode=CalibrationMode.STL,
                maximum_iterations=1,
            ),
            "effective_profile": SimpleNamespace(
                effective_values={
                    "printable_area": [
                        [0, 0],
                        [100, 0],
                        [100, 100],
                        [0, 100],
                    ]
                }
            ),
            "adapter": object(),
            "maximum_object_segments": 200,
        }
        values.update(changes)
        return PreviewRequest(**values)

    def test_reuses_source_data_across_setting_changes(self) -> None:
        calibrator = SyntheticSuccessfulCalibrator()
        service = PreviewService(calibrator)
        statuses: list[str] = []
        with patch(
            "cooling_tower.preview.service.analyze_deposition_toolpaths",
            wraps=analyze_deposition_toolpaths,
        ) as analyze:
            first = service.prepare(self.request())
            second = service.prepare(
                self.request(
                    settings=replace(
                        GenerationSettings(),
                        target_layer_time_s=16.0,
                    )
                ),
                progress_callback=lambda _percent, status: statuses.append(status),
            )

        self.assertEqual(analyze.call_count, 1)
        self.assertEqual(len(service.source_data_cache), 1)
        expected_bounds = determine_occupied_bounds(self.source)
        self.assertEqual(
            [call["precomputed_occupied_bounds"] for call in calibrator.calls],
            [expected_bounds, expected_bounds],
        )
        self.assertIs(first.scene.object_segments, second.scene.object_segments)
        self.assertTrue(any("Zwischengespeicherte" in item for item in statuses))
        first.dispose()
        second.dispose()

    def test_uses_matching_combined_analysis_without_second_parser_pass(
        self,
    ) -> None:
        analysis = analyze_deposition_toolpaths(
            self.source,
            expected_layer_count=self.snapshot.layer_count,
            maximum_segments=200,
        )
        self.assertIsNotNone(analysis.occupied_bounds)
        assert analysis.occupied_bounds is not None
        prepared = PreviewSourceData(
            key=PreviewSourceCacheKey(
                source_path=self.source,
                file_size_bytes=self.snapshot.file_size_bytes,
                file_modified_ns=self.snapshot.file_modified_ns,
                content_sha256=self.snapshot.content_sha256,
                analysis_schema_version=self.snapshot.analysis_schema_version,
                parser_version=self.snapshot.parser_version,
                expected_layer_count=self.snapshot.layer_count,
                maximum_segments=200,
            ),
            object_segments=analysis.object_segments,
            source_segment_count=analysis.source_segment_count,
            occupied_bounds=analysis.occupied_bounds,
        )
        service = PreviewService(SyntheticSuccessfulCalibrator())
        with patch(
            "cooling_tower.preview.service.analyze_deposition_toolpaths",
            side_effect=AssertionError("unexpected second parser pass"),
        ) as separate_analysis:
            result = service.prepare(
                self.request(prepared_source_data=prepared)
            )

        self.assertEqual(separate_analysis.call_count, 0)
        self.assertEqual(result.scene.object_segments, prepared.object_segments)
        self.assertEqual(
            result.scene.source_segment_count,
            prepared.source_segment_count,
        )
        result.dispose()

    def test_sampling_contract_change_creates_a_separate_entry(self) -> None:
        service = PreviewService(SyntheticSuccessfulCalibrator())
        with patch(
            "cooling_tower.preview.service.analyze_deposition_toolpaths",
            wraps=analyze_deposition_toolpaths,
        ) as analyze:
            first = service.prepare(self.request(maximum_object_segments=200))
            second = service.prepare(self.request(maximum_object_segments=300))

        self.assertEqual(analyze.call_count, 2)
        self.assertEqual(len(service.source_data_cache), 2)
        first.dispose()
        second.dispose()

    def test_changed_file_version_replaces_stale_variants_for_same_path(self) -> None:
        service = PreviewService(SyntheticSuccessfulCalibrator())
        first = service.prepare(self.request(maximum_object_segments=200))
        second = service.prepare(self.request(maximum_object_segments=300))
        self.assertEqual(len(service.source_data_cache), 2)

        self.source.write_text(source_gcode(layer_count=5), encoding="utf-8")
        self.snapshot = self.analysis_service.analyze(self.source)
        third = service.prepare(self.request(maximum_object_segments=200))

        self.assertEqual(len(service.source_data_cache), 1)
        self.assertEqual(
            service.source_data_cache.keys()[0].content_sha256,
            self.snapshot.content_sha256,
        )
        first.dispose()
        second.dispose()
        third.dispose()

    def test_same_metadata_but_changed_content_is_rejected_and_invalidated(self) -> None:
        service = PreviewService(SyntheticSuccessfulCalibrator())
        preview = service.prepare(self.request())
        preview.dispose()
        before = self.source.stat()
        original = self.source.read_text(encoding="utf-8")
        changed = original.replace("X12.000", "X92.000", 1)
        self.assertEqual(len(changed), len(original))
        self.source.write_text(changed, encoding="utf-8")
        os.utime(
            self.source,
            ns=(before.st_atime_ns, before.st_mtime_ns),
        )

        with self.assertRaisesRegex(PreviewBuildError, "Inhalt"):
            service.prepare(self.request())
        self.assertEqual(len(service.source_data_cache), 0)

    def test_analysis_cache_detects_changed_content_with_restored_metadata(self) -> None:
        first = self.snapshot
        before = self.source.stat()
        original = self.source.read_text(encoding="utf-8")
        changed = original.replace("X12.000", "X92.000", 1)
        self.source.write_text(changed, encoding="utf-8")
        os.utime(
            self.source,
            ns=(before.st_atime_ns, before.st_mtime_ns),
        )

        second = self.analysis_service.analyze(self.source)

        self.assertIsNot(first, second)
        self.assertNotEqual(first.content_sha256, second.content_sha256)

    def test_cancelled_source_calculation_is_not_cached(self) -> None:
        service = PreviewService(SyntheticSuccessfulCalibrator())
        cancellation = Event()
        cancellation.set()

        with self.assertRaises(PreviewCancelled):
            service.prepare(
                self.request(),
                cancellation_event=cancellation,
            )
        self.assertEqual(len(service.source_data_cache), 0)

    def test_failed_bounds_calculation_is_not_cached(self) -> None:
        service = PreviewService(SyntheticSuccessfulCalibrator())
        with patch(
            "cooling_tower.preview.service.analyze_deposition_toolpaths",
            side_effect=ValueError("synthetic bounds failure"),
        ):
            with self.assertRaisesRegex(ValueError, "synthetic bounds failure"):
                service.prepare(self.request())
        self.assertEqual(len(service.source_data_cache), 0)

    def test_file_change_during_source_calculation_is_not_cached(self) -> None:
        service = PreviewService(SyntheticSuccessfulCalibrator())
        original = self.source.read_text(encoding="utf-8")

        def changing_analysis(path: str | Path, **kwargs):
            result = analyze_deposition_toolpaths(path, **kwargs)
            self.source.write_text(original + "; changed\n", encoding="utf-8")
            return result

        with patch(
            "cooling_tower.preview.service.analyze_deposition_toolpaths",
            side_effect=changing_analysis,
        ):
            with self.assertRaisesRegex(PreviewBuildError, "während"):
                service.prepare(self.request())
        self.assertEqual(len(service.source_data_cache), 0)

    def test_file_removal_after_initial_validation_is_handled_and_invalidated(
        self,
    ) -> None:
        service = PreviewService(SyntheticSuccessfulCalibrator())
        preview = service.prepare(self.request())
        preview.dispose()

        original_hash = "cooling_tower.preview.service.sha256_file"
        with patch(original_hash, side_effect=FileNotFoundError("synthetic")):
            with self.assertRaisesRegex(PreviewBuildError, "gelesen"):
                service.prepare(self.request())

        self.assertEqual(len(service.source_data_cache), 0)


class PreviewSourceDataCacheTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def value(
        self,
        number: int,
        *,
        source_path: Path | None = None,
        maximum_segments: int = 100,
    ) -> PreviewSourceData:
        key = PreviewSourceCacheKey(
            source_path=source_path or self.root / f"source_{number}.gcode",
            file_size_bytes=number,
            file_modified_ns=number,
            content_sha256=f"{number:064x}",
            analysis_schema_version=1,
            parser_version=1,
            expected_layer_count=1,
            maximum_segments=maximum_segments,
        )
        segment = LineSegment3D(
            Point3D(float(number), 0.0, 0.2),
            Point3D(float(number + 1), 1.0, 0.2),
        )
        return PreviewSourceData(
            key=key,
            object_segments=(segment,),
            source_segment_count=1,
            occupied_bounds=OccupiedBounds(0.0, 1.0, 0.0, 1.0),
        )

    def test_lru_access_controls_bounded_eviction(self) -> None:
        cache = PreviewSourceDataCache(maximum_entries=2)
        first = self.value(1)
        second = self.value(2)
        third = self.value(3)
        cache.put(first)
        cache.put(second)
        self.assertIs(cache.get(first.key), first)

        cache.put(third)

        self.assertEqual(cache.keys(), (first.key, third.key))
        self.assertIsNone(cache.get(second.key))

    def test_new_file_version_prunes_all_old_sampling_variants(self) -> None:
        cache = PreviewSourceDataCache(maximum_entries=4)
        path = self.root / "same.gcode"
        first = self.value(1, source_path=path, maximum_segments=100)
        second = PreviewSourceData(
            key=replace(first.key, maximum_segments=200),
            object_segments=first.object_segments,
            source_segment_count=first.source_segment_count,
            occupied_bounds=first.occupied_bounds,
        )
        changed = self.value(2, source_path=path, maximum_segments=100)
        cache.put(first)
        cache.put(second)
        cache.put(changed)

        self.assertEqual(cache.keys(), (changed.key,))

    def test_values_are_immutable_and_contract_is_validated(self) -> None:
        value = self.value(1)
        with self.assertRaises(FrozenInstanceError):
            value.source_segment_count = 2  # type: ignore[misc]
        with self.assertRaisesRegex(ValueError, "SHA-256"):
            replace(value.key, content_sha256="invalid")
        with self.assertRaisesRegex(TypeError, "immutable tuple"):
            PreviewSourceData(
                key=value.key,
                object_segments=list(value.object_segments),  # type: ignore[arg-type]
                source_segment_count=1,
                occupied_bounds=value.occupied_bounds,
            )

    def test_parallel_access_remains_bounded_and_consistent(self) -> None:
        cache = PreviewSourceDataCache(maximum_entries=2)
        values = tuple(self.value(number) for number in range(1, 33))

        def store_and_read(value: PreviewSourceData) -> None:
            cache.put(value)
            result = cache.get(value.key)
            if result is not None:
                self.assertIs(result, value)

        with ThreadPoolExecutor(max_workers=8) as executor:
            tuple(executor.map(store_and_read, values))

        self.assertLessEqual(len(cache), 2)
        for key in cache.keys():
            self.assertIsNotNone(cache.get(key))

    def test_invalid_capacity_is_rejected(self) -> None:
        with self.assertRaisesRegex(ValueError, "at least one"):
            PreviewSourceDataCache(maximum_entries=0)


if __name__ == "__main__":
    unittest.main()
