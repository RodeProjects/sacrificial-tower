from __future__ import annotations

import json
import sys
import unittest
from datetime import UTC, datetime, timedelta
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = PROJECT_ROOT / "src"
SCRIPTS_ROOT = PROJECT_ROOT / "scripts"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))
if str(SCRIPTS_ROOT) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_ROOT))

from release_retention import RetentionPolicy, plan_release_cleanup


NOW = datetime(2026, 7, 27, 12, 0, tzinfo=UTC)


def release(
    release_id: int,
    tag: str,
    *,
    age_days: int,
    size: int = 40 * 1024 * 1024,
    draft: bool = False,
    immutable: bool = False,
) -> dict[str, object]:
    published = NOW - timedelta(days=age_days)
    return {
        "id": release_id,
        "tag_name": tag,
        "published_at": published.isoformat().replace("+00:00", "Z"),
        "draft": draft,
        "immutable": immutable,
        "assets": [{"name": f"setup-{tag}.exe", "size": size}],
    }


def policy(
    *,
    minimum_releases: int = 100,
    maximum_size: int = 10 * 1024**3,
    minimum_age_days: int = 90,
) -> RetentionPolicy:
    return RetentionPolicy(
        minimum_releases=minimum_releases,
        maximum_total_asset_size_bytes=maximum_size,
        minimum_age_days=minimum_age_days,
        protect_zero_patch_versions=True,
        protected_versions=frozenset({"0.4.8"}),
    )


class ReleaseRetentionTests(unittest.TestCase):
    def test_repository_configuration_matches_requested_limits(self) -> None:
        values = json.loads(
            (PROJECT_ROOT / "config" / "release_retention.json").read_text(
                encoding="utf-8"
            )
        )
        configured = RetentionPolicy.from_mapping(values)

        self.assertEqual(configured.minimum_releases, 100)
        self.assertEqual(configured.maximum_total_asset_size_bytes, 10 * 1024**3)
        self.assertEqual(configured.minimum_age_days, 90)
        self.assertTrue(configured.protect_zero_patch_versions)
        self.assertIn("0.4.8", configured.protected_versions)

    def test_old_releases_beyond_newest_hundred_are_removed(self) -> None:
        releases = [
            release(index + 1, f"v1.2.{index + 1}", age_days=index)
            for index in range(103)
        ]
        releases.extend(
            (
                release(104, "v0.4.8", age_days=103),
                release(105, "v0.3.0", age_days=104),
            )
        )

        plan = plan_release_cleanup(
            releases,
            policy(),
            now=NOW,
            latest_version="1.2.1",
        )

        self.assertEqual(
            [item["tag_name"] for item in plan["delete"]],
            ["v1.2.103", "v1.2.102", "v1.2.101"],
        )
        self.assertEqual(plan["release_count_after"], 102)
        protected = {item["tag_name"] for item in plan["protected"]}
        self.assertIn("v0.4.8", protected)
        self.assertIn("v0.3.0", protected)

    def test_newest_hundred_are_never_deleted_due_to_age(self) -> None:
        releases = [
            release(index + 1, f"v2.1.{index + 1}", age_days=365 + index)
            for index in range(100)
        ]

        plan = plan_release_cleanup(releases, policy(), now=NOW)

        self.assertEqual(plan["delete"], [])
        self.assertEqual(plan["release_count_after"], 100)

    def test_size_limit_removes_oldest_eligible_release_without_waiting(self) -> None:
        releases = [
            release(index + 1, f"v3.1.{index + 1}", age_days=index, size=10)
            for index in range(101)
        ]

        plan = plan_release_cleanup(
            releases,
            policy(maximum_size=1010, minimum_age_days=1000),
            now=NOW,
        )

        self.assertTrue(plan["capacity_cleanup_triggered"])
        self.assertTrue(plan["capacity_limit_satisfied"])
        self.assertEqual(
            [(item["tag_name"], item["reason"]) for item in plan["delete"]],
            [("v3.1.101", "Speichergrenze erreicht")],
        )
        self.assertEqual(plan["total_asset_size_bytes_after"], 1000)

    def test_minimum_and_protected_releases_take_priority_over_size_limit(self) -> None:
        releases = [
            release(index + 1, f"v4.1.{index + 1}", age_days=index, size=10)
            for index in range(100)
        ]
        releases.append(release(101, "v0.4.8", age_days=200, size=10))
        releases.append(release(102, "v4.0.0", age_days=300, size=10))

        plan = plan_release_cleanup(
            releases,
            policy(maximum_size=1000),
            now=NOW,
        )

        self.assertEqual(plan["delete"], [])
        self.assertFalse(plan["capacity_limit_satisfied"])

    def test_unknown_tags_drafts_and_immutable_releases_are_protected(self) -> None:
        releases = [
            release(1, "nightly", age_days=500),
            release(2, "v1.1.1", age_days=500, draft=True),
            release(3, "v1.1.2", age_days=500, immutable=True),
        ]

        plan = plan_release_cleanup(
            releases,
            policy(minimum_releases=1, maximum_size=1),
            now=NOW,
        )

        self.assertEqual(plan["delete"], [])
        self.assertFalse(plan["capacity_limit_satisfied"])


class ReleaseRetentionIntegrationTests(unittest.TestCase):
    def test_publication_runs_cleanup_only_after_manifest_publish(self) -> None:
        script = (PROJECT_ROOT / "scripts" / "publish_update.ps1").read_text(
            encoding="utf-8"
        )

        manifest_position = script.index("$manifestPublished = $true")
        cleanup_position = script.index("cleanup_releases.ps1")
        self.assertGreater(cleanup_position, manifest_position)
        self.assertIn("-Repository $UpdateRepository", script)
        self.assertIn("-LatestVersion $version", script)

    def test_cleanup_deletes_release_without_deleting_git_tag(self) -> None:
        script = (PROJECT_ROOT / "scripts" / "cleanup_releases.ps1").read_text(
            encoding="utf-8"
        )

        self.assertIn("--method DELETE", script)
        self.assertIn("repos/$Repository/releases/$($release.id)", script)
        self.assertNotIn("--cleanup-tag", script)
        self.assertIn("[switch]$DryRun", script)


if __name__ == "__main__":
    unittest.main()
