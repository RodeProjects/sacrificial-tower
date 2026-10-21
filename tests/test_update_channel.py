from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "scripts"))

from cooling_tower.update import UpdateError, UpdateService, parse_update_manifest
from cooling_tower.update_manifest import sign_update_manifest
from create_update_manifest import create_manifest
from test_update import (
    TEST_KEY_ID,
    TEST_PRIVATE_KEY_BASE64,
    TEST_PUBLIC_KEYS,
    manifest_for,
)


class MainRepositoryUpdateChannelTests(unittest.TestCase):
    def test_default_client_fetches_latest_release_manifest(self):
        self.assertEqual(
            UpdateService().manifest_url,
            "https://github.com/RodeProjects/sacrificial-tower/releases/latest/download/latest.json",
        )

    def test_even_validly_signed_legacy_channel_is_rejected(self):
        manifest = json.loads(manifest_for(b"installer"))
        manifest["installer_url"] = manifest["installer_url"].replace(
            "/sacrificial-tower/", "/sacrificial-tower-updates/"
        )
        self.assert_invalid_release_location(manifest)

    def test_signed_installer_must_belong_to_manifest_version(self):
        manifest = json.loads(manifest_for(b"installer"))
        manifest["version"] = "0.4.3"
        self.assert_invalid_release_location(manifest)

    def assert_invalid_release_location(self, manifest):
        signed = sign_update_manifest(
            manifest, private_key_base64=TEST_PRIVATE_KEY_BASE64, key_id=TEST_KEY_ID
        )
        with self.assertRaisesRegex(UpdateError, "Installer-URL"):
            parse_update_manifest(json.dumps(signed), public_keys=TEST_PUBLIC_KEYS)

    def test_publisher_rejects_legacy_destination_before_reading_metadata(self):
        with self.assertRaisesRegex(ValueError, "Hauptrepository"):
            create_manifest(
                Path("unused-metadata.json"),
                update_repository="RodeProjects/sacrificial-tower-updates",
                release_notes="Test",
                private_key_base64=TEST_PRIVATE_KEY_BASE64,
                key_id=TEST_KEY_ID,
            )
