from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import ssl
import tempfile
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from pathlib import Path
from threading import Event
from urllib.error import HTTPError, URLError
from urllib.parse import urlparse
from urllib.request import Request, urlopen

import truststore

from cooling_tower.update_keys import UPDATE_MANIFEST_PUBLIC_KEYS
from cooling_tower.update_manifest import (
    UpdateManifestSignatureError,
    verify_update_manifest_signature,
)
from cooling_tower.diagnostic_context import record_diagnostic
from cooling_tower.version import APP_VERSION


DEFAULT_UPDATE_MANIFEST_URL = (
    "https://raw.githubusercontent.com/"
    "RodeProjects/sacrificial-tower-updates/main/latest.json"
)
MAXIMUM_MANIFEST_BYTES = 64 * 1024
MAXIMUM_INSTALLER_BYTES = 512 * 1024 * 1024
_VERSION_PATTERN = re.compile(r"^[0-9]+(?:\.[0-9]+){2}$")
_SHA256_PATTERN = re.compile(r"^[0-9a-f]{64}$")
_ALLOWED_INSTALLER_HOST = "github.com"
_ALLOWED_INSTALLER_PATH_PREFIX = (
    "/RodeProjects/sacrificial-tower-updates/releases/download/"
)


class UpdateError(RuntimeError):
    """A safe update check, download, or launch could not be completed."""

    def __init__(self, message: str, *, code: str = "update_failed") -> None:
        super().__init__(message)
        self.code = code


class UpdateCancelled(UpdateError):
    """The update download was cancelled during application shutdown."""


@dataclass(frozen=True, slots=True)
class UpdateInfo:
    version: str
    installer_url: str
    sha256: str
    size_bytes: int
    release_notes: str = ""
    signing_key_id: str = ""


def version_key(value: str) -> tuple[int, int, int]:
    """Return a comparable numeric key for the public ``x.x.x`` format."""

    normalized = str(value).strip()
    if not _VERSION_PATTERN.fullmatch(normalized):
        raise ValueError(f"Ungültige Programmversion: {value!r}")
    return tuple(int(part) for part in normalized.split("."))  # type: ignore[return-value]


def is_newer_version(candidate: str, current: str) -> bool:
    return version_key(candidate) > version_key(current)


def _reject_duplicate_json_keys(pairs):
    parsed = {}
    for key, value in pairs:
        if key in parsed:
            raise UpdateError(
                f"Das Update-Manifest enthält den Schlüssel {key!r} mehrfach."
            )
        parsed[key] = value
    return parsed


def parse_update_manifest(
    payload: bytes | str,
    *,
    public_keys: Mapping[str, str] | None = None,
) -> UpdateInfo:
    try:
        if isinstance(payload, bytes):
            payload = payload.decode("utf-8")
        raw = json.loads(payload, object_pairs_hook=_reject_duplicate_json_keys)
    except UpdateError:
        raise
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise UpdateError("Das Update-Manifest ist kein gültiges JSON.") from error
    if not isinstance(raw, dict):
        raise UpdateError("Das Update-Manifest muss ein JSON-Objekt sein.")
    try:
        verify_update_manifest_signature(
            raw,
            (
                UPDATE_MANIFEST_PUBLIC_KEYS
                if public_keys is None
                else public_keys
            ),
        )
    except UpdateManifestSignatureError as error:
        raise UpdateError(str(error), code="update_manifest_signature_invalid") from error
    if raw.get("schema_version") != 1:
        raise UpdateError("Die Version des Update-Manifests wird nicht unterstützt.")

    version = str(raw.get("version", "")).strip()
    try:
        version_key(version)
    except ValueError as error:
        raise UpdateError(str(error)) from error

    installer_url = str(raw.get("installer_url", "")).strip()
    parsed_url = urlparse(installer_url)
    if (
        parsed_url.scheme != "https"
        or parsed_url.hostname != _ALLOWED_INSTALLER_HOST
        or not parsed_url.path.startswith(_ALLOWED_INSTALLER_PATH_PREFIX)
        or not parsed_url.path.casefold().endswith(".exe")
    ):
        raise UpdateError("Das Update-Manifest enthält keine erlaubte Installer-URL.")

    sha256 = str(raw.get("sha256", "")).strip().casefold()
    if not _SHA256_PATTERN.fullmatch(sha256):
        raise UpdateError("Das Update-Manifest enthält keinen gültigen SHA-256-Wert.")
    try:
        size_bytes = int(raw.get("size_bytes", 0))
    except (TypeError, ValueError) as error:
        raise UpdateError("Das Update-Manifest enthält keine gültige Dateigröße.") from error
    if not 0 < size_bytes <= MAXIMUM_INSTALLER_BYTES:
        raise UpdateError("Die im Update-Manifest angegebene Dateigröße ist ungültig.")

    return UpdateInfo(
        version=version,
        installer_url=installer_url,
        sha256=sha256,
        size_bytes=size_bytes,
        release_notes=str(raw.get("release_notes", "")).strip(),
        signing_key_id=str(raw["signing_key_id"]),
    )


class UpdateService:
    """Check and download a credential-free installer from the public channel."""

    def __init__(
        self,
        manifest_url: str = DEFAULT_UPDATE_MANIFEST_URL,
        *,
        timeout_s: float = 5.0,
        temporary_root: str | Path | None = None,
        opener=None,
        manifest_public_keys: Mapping[str, str] | None = None,
    ) -> None:
        self.manifest_url = manifest_url
        self.timeout_s = timeout_s
        self.temporary_root = (
            Path(temporary_root).resolve() if temporary_root is not None else None
        )
        self._ssl_context = truststore.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
        self._opener = opener or self._open_with_system_trust
        self._manifest_public_keys = dict(
            UPDATE_MANIFEST_PUBLIC_KEYS
            if manifest_public_keys is None
            else manifest_public_keys
        )

    def _open_with_system_trust(self, request: Request, *, timeout: float):
        return urlopen(request, timeout=timeout, context=self._ssl_context)

    @staticmethod
    def _request(url: str, accept: str) -> Request:
        return Request(
            url,
            headers={
                "Accept": accept,
                "User-Agent": "SacrificialTower-Updater",
                "Cache-Control": "no-cache",
            },
        )

    def check_for_update(self, current_version: str) -> UpdateInfo | None:
        record_diagnostic("update_check_started", current_version=current_version)
        request = self._request(self.manifest_url, "application/json")
        try:
            with self._opener(request, timeout=self.timeout_s) as response:
                payload = response.read(MAXIMUM_MANIFEST_BYTES + 1)
        except (HTTPError, URLError, OSError, TimeoutError) as error:
            record_diagnostic("update_check_failed", error_type=type(error).__name__,
                              winerror=getattr(error, "winerror", None), errno=getattr(error, "errno", None),
                              http_status=getattr(error, "code", None), error_message=str(error), outcome="failed")
            raise UpdateError("Der Update-Kanal ist derzeit nicht erreichbar.") from error
        if len(payload) > MAXIMUM_MANIFEST_BYTES:
            raise UpdateError("Das Update-Manifest ist unerwartet groß.")
        try:
            info = parse_update_manifest(payload, public_keys=self._manifest_public_keys)
        except UpdateError as error:
            record_diagnostic("update_manifest_rejected", outcome="failed", result_code=error.code,
                              error_message=str(error))
            raise
        record_diagnostic("update_manifest_verified", target_version=info.version,
                          file_size_bytes=info.size_bytes, outcome="success")
        return info if is_newer_version(info.version, current_version) else None

    def download_installer(
        self,
        info: UpdateInfo,
        *,
        progress_callback: Callable[[int], None] | None = None,
        cancellation_event: Event | None = None,
    ) -> Path:
        record_diagnostic("update_download_started", target_version=info.version,
                          expected_size_bytes=info.size_bytes)
        temporary_directory = Path(
            tempfile.mkdtemp(
                prefix="sacrificial-tower-update-",
                dir=self.temporary_root,
            )
        )
        target = temporary_directory / f"SacrificialTowerSetup-{info.version}.exe"
        partial = target.with_suffix(".exe.part")
        request = self._request(info.installer_url, "application/octet-stream")
        digest = hashlib.sha256()
        downloaded = 0
        completed = False
        try:
            with self._opener(request, timeout=self.timeout_s) as response:
                header_size = response.headers.get("Content-Length")
                if header_size is not None and int(header_size) > MAXIMUM_INSTALLER_BYTES:
                    raise UpdateError("Der Update-Installer ist unerwartet groß.", code="update_installer_too_large")
                with partial.open("wb") as handle:
                    while True:
                        if cancellation_event is not None and cancellation_event.is_set():
                            raise UpdateCancelled("Der Update-Download wurde abgebrochen.", code="update_cancelled")
                        block = response.read(1024 * 1024)
                        if not block:
                            break
                        downloaded += len(block)
                        if downloaded > MAXIMUM_INSTALLER_BYTES:
                            raise UpdateError("Der Update-Installer ist unerwartet groß.", code="update_installer_too_large")
                        handle.write(block)
                        digest.update(block)
                        if progress_callback is not None:
                            progress_callback(min(100, downloaded * 100 // info.size_bytes))
            if downloaded != info.size_bytes:
                raise UpdateError("Der Update-Installer hat nicht die erwartete Größe.", code="update_installer_size_mismatch")
            if digest.hexdigest().casefold() != info.sha256:
                raise UpdateError("Die SHA-256-Prüfung des Updates ist fehlgeschlagen.", code="update_installer_hash_mismatch")
            os.replace(partial, target)
            if progress_callback is not None:
                progress_callback(100)
            completed = True
            record_diagnostic("update_download_verified", target_version=info.version,
                              file_size_bytes=downloaded, outcome="success")
            return target.resolve()
        except UpdateError as error:
            record_diagnostic("update_download_failed", target_version=info.version,
                              error_type=type(error).__name__, error_message=str(error),
                              result_code=error.code,
                              file_size_bytes=downloaded,
                              outcome="cancelled" if isinstance(error, UpdateCancelled) else "failed")
            raise
        except (HTTPError, URLError, OSError, TimeoutError, ValueError) as error:
            record_diagnostic("update_download_failed", target_version=info.version,
                              error_type=type(error).__name__, winerror=getattr(error, "winerror", None),
                              http_status=getattr(error, "code", None), errno=getattr(error, "errno", None),
                              error_message=str(error),
                              file_size_bytes=downloaded, outcome="failed")
            raise UpdateError("Der Update-Installer konnte nicht geladen werden.") from error
        finally:
            if not completed:
                # The directory contains no reusable state.  Removing it as a
                # unit also covers a completed rename followed by a failing
                # progress callback and avoids accumulating abandoned update
                # directories after cancellations or validation errors.
                shutil.rmtree(temporary_directory, ignore_errors=True)

    def discard_installer(self, installer_path: str | Path) -> None:
        """Remove only a verified download held in our own temporary folder."""
        installer = Path(installer_path).resolve()
        root = (self.temporary_root or Path(tempfile.gettempdir())).resolve()
        folder = installer.parent
        if (
            folder.parent == root
            and folder.name.startswith("sacrificial-tower-update-")
            and installer.name.startswith("SacrificialTowerSetup-")
            and installer.suffix.casefold() == ".exe"
        ):
            shutil.rmtree(folder, ignore_errors=True)
            record_diagnostic("update_download_discarded", success=not folder.exists())

    def start_installation(self, installer_path: str | Path, info: UpdateInfo,
                           log_root: str | Path, *, journal=None):
        from cooling_tower.update_installation import UpdateInstallationAttempt

        installer = Path(installer_path).resolve()
        if os.name != "nt" or installer.suffix.casefold() != ".exe":
            raise UpdateError("Der automatische Installer wird nur unter Windows unterstützt.")
        if version_key(info.version) < (0, 8, 14) or not is_newer_version(info.version, APP_VERSION):
            raise UpdateError("Der Installer unterstützt keine neuere, sichere Updateübergabe.")
        root = (self.temporary_root or Path(tempfile.gettempdir())).resolve()
        if (installer.parent.parent != root
                or not installer.parent.name.startswith("sacrificial-tower-update-")
                or installer.name != f"SacrificialTowerSetup-{info.version}.exe"):
            raise UpdateError("Der Installer liegt nicht im eigenen Update-Downloadordner.")
        return UpdateInstallationAttempt(installer, info, Path(log_root), journal=journal).start()
