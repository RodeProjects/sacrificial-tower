from __future__ import annotations

import hashlib
import base64
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from threading import Event
from unittest.mock import patch

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey


PROJECT_ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = PROJECT_ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from cooling_tower.update import (
    UpdateCancelled,
    UpdateError,
    UpdateInfo,
    UpdateService,
    is_newer_version,
    parse_update_manifest,
    version_key,
)
from cooling_tower.update_manifest import sign_update_manifest
from cooling_tower.diagnostic_context import diagnostic_scope


INSTALLER_URL = (
    "https://github.com/RodeProjects/sacrificial-tower-updates/"
    "releases/download/v0.4.2/SacrificialTowerSetup-0.4.2.exe"
)
TEST_KEY_ID = "test-key"
TEST_PRIVATE_KEY = Ed25519PrivateKey.from_private_bytes(bytes(range(32)))
TEST_PRIVATE_KEY_BASE64 = base64.b64encode(bytes(range(32))).decode("ascii")
TEST_PUBLIC_KEY_BASE64 = base64.b64encode(
    TEST_PRIVATE_KEY.public_key().public_bytes(
        encoding=serialization.Encoding.Raw,
        format=serialization.PublicFormat.Raw,
    )
).decode("ascii")
TEST_PUBLIC_KEYS = {TEST_KEY_ID: TEST_PUBLIC_KEY_BASE64}


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
    signed = sign_update_manifest(
        {
            "schema_version": 1,
            "version": version,
            "installer_url": INSTALLER_URL.replace("0.4.2", version),
            "sha256": hashlib.sha256(payload).hexdigest(),
            "size_bytes": len(payload),
            "release_notes": "Testversion",
        },
        private_key_base64=TEST_PRIVATE_KEY_BASE64,
        key_id=TEST_KEY_ID,
    )
    return json.dumps(signed).encode("utf-8")


class UpdateServiceTests(unittest.TestCase):
    def test_download_diagnostics_explain_integrity_failures_with_stable_code(self):
        info = UpdateInfo("9.9.9", INSTALLER_URL, "0" * 64, 9)
        events = []
        with tempfile.TemporaryDirectory() as temporary:
            service = UpdateService(temporary_root=temporary, opener=SequenceOpener(FakeResponse(b"installer")))
            with diagnostic_scope(lambda event, **fields: events.append((event, fields))):
                with self.assertRaises(UpdateError):
                    service.download_installer(info)
        failure = next(fields for event, fields in events if event == "update_download_failed")
        self.assertEqual(failure["result_code"], "update_installer_hash_mismatch")
        self.assertEqual(failure["file_size_bytes"], 9)
        self.assertEqual(failure["target_version"], "9.9.9")

    def test_numeric_versions_allow_a_longer_last_component(self) -> None:
        self.assertEqual(version_key("0.4.100"), (0, 4, 100))
        self.assertTrue(is_newer_version("0.4.10", "0.4.9"))
        self.assertFalse(is_newer_version("0.4.1", "0.4.1"))
        with self.assertRaises(ValueError):
            version_key("0.4")

    def test_manifest_requires_the_public_update_release_path(self) -> None:
        payload = b"installer"
        parsed = parse_update_manifest(
            manifest_for(payload),
            public_keys=TEST_PUBLIC_KEYS,
        )
        self.assertEqual(parsed.version, "0.4.2")
        self.assertEqual(parsed.installer_url, INSTALLER_URL)

        invalid = json.loads(manifest_for(payload))
        invalid["installer_url"] = "https://example.com/update.exe"
        with self.assertRaises(UpdateError):
            parse_update_manifest(
                json.dumps(invalid),
                public_keys=TEST_PUBLIC_KEYS,
            )

    def test_manifest_signature_rejects_every_tampered_field(self) -> None:
        payload = b"installer"
        tampered = json.loads(manifest_for(payload))
        tampered["release_notes"] = "Manipuliert"

        with self.assertRaisesRegex(UpdateError, "Signatur"):
            parse_update_manifest(
                json.dumps(tampered),
                public_keys=TEST_PUBLIC_KEYS,
            )

    def test_manifest_requires_a_known_key_and_signature(self) -> None:
        payload = b"installer"
        unknown = json.loads(manifest_for(payload))
        unknown["signing_key_id"] = "unknown"
        with self.assertRaisesRegex(UpdateError, "vertrauenswürdigen Schlüssel"):
            parse_update_manifest(
                json.dumps(unknown),
                public_keys=TEST_PUBLIC_KEYS,
            )

        unsigned = json.loads(manifest_for(payload))
        unsigned.pop("signature")
        with self.assertRaisesRegex(UpdateError, "Signatur"):
            parse_update_manifest(
                json.dumps(unsigned),
                public_keys=TEST_PUBLIC_KEYS,
            )

    def test_manifest_rejects_duplicate_json_keys(self) -> None:
        with self.assertRaisesRegex(UpdateError, "mehrfach"):
            parse_update_manifest(
                '{"schema_version":1,"schema_version":1}',
                public_keys=TEST_PUBLIC_KEYS,
            )

    def test_check_returns_only_a_newer_version(self) -> None:
        payload = b"installer"
        opener = SequenceOpener(FakeResponse(manifest_for(payload)))
        service = UpdateService(
            opener=opener,
            manifest_public_keys=TEST_PUBLIC_KEYS,
        )
        result = service.check_for_update("0.4.1")
        self.assertIsNotNone(result)
        self.assertEqual(result.version, "0.4.2")
        self.assertEqual(
            opener.requests[0][0].headers["User-agent"],
            "SacrificialTower-Updater",
        )

        current_opener = SequenceOpener(FakeResponse(manifest_for(payload)))
        current_service = UpdateService(
            opener=current_opener,
            manifest_public_keys=TEST_PUBLIC_KEYS,
        )
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
            self.assertEqual(list(Path(temporary).iterdir()), [])

    def test_cancelled_download_removes_its_temporary_directory(self) -> None:
        payload = b"installer"
        info = UpdateInfo(
            version="0.4.2",
            installer_url=INSTALLER_URL,
            sha256=hashlib.sha256(payload).hexdigest(),
            size_bytes=len(payload),
        )
        cancellation = Event()
        cancellation.set()
        with tempfile.TemporaryDirectory() as temporary:
            service = UpdateService(
                opener=SequenceOpener(FakeResponse(payload)),
                temporary_root=temporary,
            )
            with self.assertRaises(UpdateCancelled):
                service.download_installer(
                    info,
                    cancellation_event=cancellation,
                )
            self.assertEqual(list(Path(temporary).iterdir()), [])

    def test_discard_installer_removes_only_own_download(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            service = UpdateService(temporary_root=root)
            own = root / 'sacrificial-tower-update-test' / 'SacrificialTowerSetup-1.2.3.exe'
            own.parent.mkdir()
            own.write_bytes(b'installer')
            external = root / 'unrelated' / own.name
            external.parent.mkdir()
            external.write_bytes(b'keep')
            service.discard_installer(external)
            self.assertTrue(external.exists())
            service.discard_installer(own)
            self.assertFalse(own.parent.exists())

    def test_failing_progress_callback_removes_completed_download(self) -> None:
        payload = b"installer"
        info = UpdateInfo(
            version="0.4.2",
            installer_url=INSTALLER_URL,
            sha256=hashlib.sha256(payload).hexdigest(),
            size_bytes=len(payload),
        )

        def fail_progress(_value: int) -> None:
            raise RuntimeError("callback failed")

        with tempfile.TemporaryDirectory() as temporary:
            service = UpdateService(
                opener=SequenceOpener(FakeResponse(payload)),
                temporary_root=temporary,
            )
            with self.assertRaisesRegex(RuntimeError, "callback failed"):
                service.download_installer(
                    info,
                    progress_callback=fail_progress,
                )
            self.assertEqual(list(Path(temporary).iterdir()), [])

    def test_launch_uses_the_silent_inno_update_switches(self) -> None:
        from cooling_tower.update_installation import installer_command
        with tempfile.TemporaryDirectory() as temporary:
            installer = Path(temporary) / "update.exe"
            installer.write_bytes(b"test")
            command = installer_command(installer.resolve(), "test", Path(temporary) / "log", Path(temporary) / "status")
            self.assertEqual(
                command,
                [
                    str(installer.resolve()),
                    "/SP-",
                    "/VERYSILENT",
                    "/SUPPRESSMSGBOXES",
                    "/NORESTART",
                    "/CURRENTUSER",
                    "/NOCLOSEAPPLICATIONS",
                    "/NORESTARTAPPLICATIONS",
                    "/RESTARTEXITCODE=3010",
                    "/SACRIFICIALTOWERUPDATE",
                    "/STUPDATEHANDOFF=test",
                    f"/STUPDATEPARENT={os.getpid()}",
                    f"/STUPDATESTATUS={Path(temporary) / 'status'}",
                    f"/LOG={Path(temporary) / 'log'}",
                ],
            )


if __name__ == "__main__":
    unittest.main()
