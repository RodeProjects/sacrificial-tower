from __future__ import annotations

import hashlib
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch


PROJECT_ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = PROJECT_ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from cooling_tower.update import (
    UpdateError,
    UpdateInfo,
    UpdateService,
    is_newer_version,
    parse_update_manifest,
    version_key,
)


INSTALLER_URL = (
    "https://github.com/RodeProjects/sacrificial-tower-updates/"
    "releases/download/v0.4.2/SacrificialTowerSetup-0.4.2.exe"
)


class FakeResponse:
    def __init__(self, payload: bytes, *, headers: dict[str, str] | None = None):
        self.payload = payload
        self.offset = 0
        self.headers = headers or {}

    def __enter__(self):
        return self

    def __exit__(self, *_arguments) -> None:
        return None

    def read(self, size: int = -1) -> bytes:
        if size < 0:
            size = len(self.payload) - self.offset
        result = self.payload[self.offset : self.offset + size]
        self.offset += len(result)
        return result


class SequenceOpener:
    def __init__(self, *responses: FakeResponse):
        self.responses = list(responses)
        self.requests = []

    def __call__(self, request, *, timeout):
        self.requests.append((request, timeout))
        return self.responses.pop(0)


def manifest_for(payload: bytes, version: str = "0.4.2") -> bytes:
    return json.dumps(
        {
            "schema_version": 1,
            "version": version,
            "installer_url": INSTALLER_URL.replace("0.4.2", version),
            "sha256": hashlib.sha256(payload).hexdigest(),
            "size_bytes": len(payload),
            "release_notes": "Testversion",
        }
    ).encode("utf-8")


class UpdateServiceTests(unittest.TestCase):
    def test_numeric_versions_allow_a_longer_last_component(self) -> None:
        self.assertEqual(version_key("0.4.100"), (0, 4, 100))
        self.assertTrue(is_newer_version("0.4.10", "0.4.9"))
        self.assertFalse(is_newer_version("0.4.1", "0.4.1"))
        with self.assertRaises(ValueError):
            version_key("0.4")

    def test_manifest_requires_the_public_update_release_path(self) -> None:
        payload = b"installer"
        parsed = parse_update_manifest(manifest_for(payload))
        self.assertEqual(parsed.version, "0.4.2")
        self.assertEqual(parsed.installer_url, INSTALLER_URL)

        invalid = json.loads(manifest_for(payload))
        invalid["installer_url"] = "https://example.com/update.exe"
        with self.assertRaises(UpdateError):
            parse_update_manifest(json.dumps(invalid))

    def test_check_returns_only_a_newer_version(self) -> None:
        payload = b"installer"
        opener = SequenceOpener(FakeResponse(manifest_for(payload)))
        service = UpdateService(opener=opener)
        result = service.check_for_update("0.4.1")
        self.assertIsNotNone(result)
        self.assertEqual(result.version, "0.4.2")
        self.assertEqual(
            opener.requests[0][0].headers["User-agent"],
            "SacrificialTower-Updater",
        )

        current_opener = SequenceOpener(FakeResponse(manifest_for(payload)))
        current_service = UpdateService(opener=current_opener)
        self.assertIsNone(current_service.check_for_update("0.4.2"))

    def test_download_is_kept_only_after_size_and_sha256_match(self) -> None:
        payload = os.urandom(2 * 1024 * 1024 + 17)
        info = UpdateInfo(
            version="0.4.2",
            installer_url=INSTALLER_URL,
            sha256=hashlib.sha256(payload).hexdigest(),
            size_bytes=len(payload),
        )
        with tempfile.TemporaryDirectory() as temporary:
            opener = SequenceOpener(
                FakeResponse(payload, headers={"Content-Length": str(len(payload))})
            )
            progress: list[int] = []
            service = UpdateService(
                opener=opener,
                temporary_root=temporary,
            )
            installer = service.download_installer(
                info,
                progress_callback=progress.append,
            )
            self.assertEqual(installer.read_bytes(), payload)
            self.assertEqual(progress[-1], 100)
            self.assertFalse(installer.with_suffix(".exe.part").exists())

    def test_download_rejects_a_hash_mismatch(self) -> None:
        payload = b"not the expected installer"
        info = UpdateInfo(
            version="0.4.2",
            installer_url=INSTALLER_URL,
            sha256="0" * 64,
            size_bytes=len(payload),
        )
        with tempfile.TemporaryDirectory() as temporary:
            service = UpdateService(
                opener=SequenceOpener(FakeResponse(payload)),
                temporary_root=temporary,
            )
            with self.assertRaisesRegex(UpdateError, "SHA-256"):
                service.download_installer(info)
            self.assertEqual(list(Path(temporary).rglob("*.exe")), [])

    def test_launch_uses_the_silent_inno_update_switches(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            installer = Path(temporary) / "update.exe"
            installer.write_bytes(b"test")
            with (
                patch("cooling_tower.update.os.name", "nt"),
                patch("cooling_tower.update.subprocess.Popen") as popen,
            ):
                UpdateService.launch_installer(installer)
            command = popen.call_args.args[0]
            self.assertEqual(
                command,
                [
                    str(installer.resolve()),
                    "/SP-",
                    "/VERYSILENT",
                    "/SUPPRESSMSGBOXES",
                    "/NORESTART",
                    "/CURRENTUSER",
                    "/CLOSEAPPLICATIONS",
                    "/NORESTARTAPPLICATIONS",
                ],
            )


if __name__ == "__main__":
    unittest.main()
