from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = PROJECT_ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))


from cooling_tower.gcode.block_cache import (
    BlockCachePolicy,
    ExactGCodeBlockCache,
)
from cooling_tower.gcode.parser import (
    GCodeLine,
    MachineStateTracker,
    parse_gcode_line,
)
from cooling_tower.preview.toolpath import (
    DepositionToolpathCollector,
    analyze_deposition_toolpaths,
)
from cooling_tower.services.analysis_service import GCodeAnalysisService


def representative_gcode(
    *,
    layer_count: int = 12,
    moves_per_layer: int = 160,
) -> str:
    lines = ["; generated optimization regression", "G90", "M83", "M204 S1000"]
    for layer in range(1, layer_count + 1):
        z = layer * 0.2
        lines.append(f";LAYER:{layer - 1}")
        lines.append(f"G1 Z{z:.3f} F900")
        for move in range(moves_per_layer):
            x = 10.0 + (move % 32) * 0.35 + layer * 0.01
            y = 15.0 + ((move * 7) % 29) * 0.27
            lines.append(f"G1 X{x:.4f} Y{y:.4f} E0.025 F2400")
    return "\n".join(lines) + "\n"


class ExactBlockCachePolicyTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.source = self.root / "representative.gcode"
        self.source.write_text(representative_gcode(), encoding="utf-8")

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def test_forced_cache_and_bypass_produce_identical_snapshots(self) -> None:
        enabled_service = GCodeAnalysisService(
            block_cache_policy=BlockCachePolicy.ENABLED
        )
        bypassed_service = GCodeAnalysisService(
            block_cache_policy=BlockCachePolicy.BYPASSED
        )

        enabled = enabled_service.analyze(self.source, force=True)
        bypassed = bypassed_service.analyze(self.source, force=True)

        self.assertEqual(enabled, bypassed)
        self.assertEqual(
            enabled_service.exact_block_cache_info["last_effective_policy"],
            "enabled",
        )
        self.assertEqual(
            bypassed_service.exact_block_cache_info["last_effective_policy"],
            "bypassed",
        )
        self.assertGreater(
            bypassed_service.exact_block_cache_info["last_avoided_insertions"],
            0,
        )

    def test_sequential_thrash_is_learned_without_disabling_small_hits(self) -> None:
        cache = ExactGCodeBlockCache(
            maximum_bytes=1024 * 1024,
            minimum_lines=4,
            average_lines=8,
            maximum_lines=16,
            policy=BlockCachePolicy.AUTO,
        )

        def parsed_lines(count: int):
            for number in range(1, count + 1):
                yield parse_gcode_line(
                    GCodeLine(
                        number,
                        f"G1 X{number * 0.01:.3f} Y{number % 37:.3f} "
                        "E0.02 F2400",
                    )
                )

        tuple(
            cache.iter_events(
                parsed_lines(3_000),
                MachineStateTracker(),
                workload_bytes=2 * 1024 * 1024,
            )
        )
        first = cache.last_analysis_stats()
        self.assertIsNotNone(first)
        assert first is not None
        self.assertEqual(first.bypass_reason, "sequential_scan_thrash")
        self.assertEqual(first.occupied_bytes_after, 0)
        self.assertGreater(first.avoided_insertions, 0)

        tuple(
            cache.iter_events(
                parsed_lines(3_000),
                MachineStateTracker(),
                workload_bytes=2 * 1024 * 1024,
            )
        )
        second = cache.last_analysis_stats()
        self.assertIsNotNone(second)
        assert second is not None
        self.assertEqual(
            second.bypass_reason,
            "previous_comparable_scan_thrashed",
        )
        self.assertEqual(second.misses, 0)

        small = tuple(parse_gcode_line(GCodeLine(index, line)) for index, line in enumerate(
            representative_gcode(layer_count=2, moves_per_layer=20).splitlines(),
            start=1,
        ))
        tuple(
            cache.iter_events(
                small,
                MachineStateTracker(),
                workload_bytes=32 * 1024,
            )
        )
        tuple(
            cache.iter_events(
                small,
                MachineStateTracker(),
                workload_bytes=32 * 1024,
            )
        )
        small_repeat = cache.last_analysis_stats()
        self.assertIsNotNone(small_repeat)
        assert small_repeat is not None
        self.assertEqual(small_repeat.effective_policy, BlockCachePolicy.ENABLED)
        self.assertGreater(small_repeat.hits, 0)


class CombinedSourceAnalysisTests(unittest.TestCase):
    def test_combined_event_collector_is_bit_identical_to_separate_preview_pass(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            source = Path(temporary) / "combined.gcode"
            source.write_text(representative_gcode(), encoding="utf-8")
            reference_snapshot = GCodeAnalysisService().analyze(
                source,
                force=True,
            )
            reference_preview = analyze_deposition_toolpaths(
                source,
                expected_layer_count=reference_snapshot.layer_count,
                maximum_segments=600,
            )
            collector = DepositionToolpathCollector(maximum_segments=600)
            combined_snapshot = GCodeAnalysisService().analyze(
                source,
                force=True,
                event_observers=(collector.consume,),
            )
            combined_preview = collector.finish(
                expected_layer_count=combined_snapshot.layer_count
            )

        self.assertEqual(combined_snapshot, reference_snapshot)
        self.assertEqual(combined_preview, reference_preview)
        self.assertLessEqual(len(combined_preview.object_segments), 600)


if __name__ == "__main__":
    unittest.main()
