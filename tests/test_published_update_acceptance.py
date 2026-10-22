"""The real installer acceptance must select an actual published predecessor."""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

if sys.platform == "win32":
    from test_published_update import choose_previous_release


@unittest.skipUnless(sys.platform == "win32", "Windows installer acceptance")
class PublishedPredecessorTests(unittest.TestCase):
    def test_unpublished_patch_gap_and_numeric_order(self):
        releases = [dict(tag_name="v0.9.8", immutable=True),
                    dict(tag_name="v0.9.26", immutable=True)]
        self.assertEqual(choose_previous_release(releases, "0.9.28"), "0.9.26")

    def test_current_future_draft_prerelease_and_mutable_are_excluded(self):
        releases = [dict(tag_name="v0.9.26", immutable=True),
                    dict(tag_name="v0.9.27", immutable=True, draft=True),
                    dict(tag_name="v0.9.27", immutable=True, prerelease=True),
                    dict(tag_name="v0.9.27", immutable=False),
                    dict(tag_name="v0.9.28", immutable=True),
                    dict(tag_name="v0.9.29", immutable=True),
                    dict(tag_name="unversioned", immutable=True)]
        self.assertEqual(choose_previous_release(releases, "0.9.28"), "0.9.26")

    def test_no_previous_published_installer_blocks_acceptance(self):
        with self.assertRaisesRegex(RuntimeError, "No previous"):
            choose_previous_release([dict(tag_name="v0.9.28", immutable=True)], "0.9.28")
