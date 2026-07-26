from __future__ import annotations

import sys
import unittest
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = PROJECT_ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from cooling_tower.slicers.base import existing_paths
from cooling_tower.slicers.discovery import WindowsSlicerDiscovery
from cooling_tower.slicers.models import SlicerCandidate, SlicerDiscoverySource


class _IsolatedWindowsDiscovery(WindowsSlicerDiscovery):
    def _registry_uninstall_candidates(self, adapters):
        return ()

    def _app_paths_candidates(self, adapters):
        return ()

    def _start_menu_candidates(self, adapters):
        return ()


class _WorkingAdapter:
    def known_candidates(self):
        return (
            SlicerCandidate(
                Path("C:/Slicer/working.exe"),
                SlicerDiscoverySource.KNOWN_PATH,
                adapter_hint="working",
            ),
        )


class _ProtectedFolderAdapter:
    def known_candidates(self):
        raise PermissionError(5, "Zugriff verweigert")


class SlicerDiscoveryResilienceTests(unittest.TestCase):
    def test_protected_folder_does_not_discard_other_slicer_candidates(self) -> None:
        result = _IsolatedWindowsDiscovery().discover(
            (_WorkingAdapter(), _ProtectedFolderAdapter())
        )
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0].adapter_hint, "working")

    def test_protected_optional_profile_root_is_skipped(self) -> None:
        class ProtectedPath:
            def expanduser(self):
                return self

            def resolve(self):
                raise PermissionError(5, "Zugriff verweigert")

        self.assertEqual(existing_paths((ProtectedPath(),)), ())


if __name__ == "__main__":
    unittest.main()
