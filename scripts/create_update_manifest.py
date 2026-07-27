from __future__ import annotations

import argparse
import json
import os
import re
import sys
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = PROJECT_ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from cooling_tower.update_keys import (  # noqa: E402
    CURRENT_UPDATE_SIGNING_KEY_ID,
    UPDATE_MANIFEST_PUBLIC_KEYS,
)
from cooling_tower.update_manifest import (  # noqa: E402
    sign_update_manifest,
    verify_update_manifest_signature,
)


_VERSION_PATTERN = re.compile(r"^[0-9]+(?:\.[0-9]+){2}$")
_SHA256_PATTERN = re.compile(r"^[0-9a-f]{64}$")
DEFAULT_PRIVATE_KEY_ENV = "UPDATE_MANIFEST_SIGNING_KEY_BASE64"


def create_manifest(
    metadata_path: Path,
    *,
    update_repository: str,
    release_notes: str,
    private_key_base64: str,
    key_id: str,
) -> dict[str, object]:
    metadata = json.loads(metadata_path.read_text(encoding="utf-8-sig"))
    if not isinstance(metadata, dict):
        raise ValueError("Die Update-Metadaten müssen ein JSON-Objekt sein.")
    version = str(metadata.get("version", "")).strip()
    installer_name = str(metadata.get("installer_name", "")).strip()
    sha256 = str(metadata.get("sha256", "")).strip().casefold()
    try:
        size_bytes = int(metadata.get("size_bytes", 0))
    except (TypeError, ValueError) as error:
        raise ValueError("Die Installergröße ist ungültig.") from error
    if not _VERSION_PATTERN.fullmatch(version):
        raise ValueError("Die Update-Version ist ungültig.")
    if installer_name != f"SacrificialTowerSetup-{version}.exe":
        raise ValueError("Der Installername stimmt nicht mit der Version überein.")
    if not _SHA256_PATTERN.fullmatch(sha256):
        raise ValueError("Der Installer-Hash ist ungültig.")
    if size_bytes <= 0:
        raise ValueError("Die Installergröße ist ungültig.")

    unsigned = {
        "schema_version": 1,
        "version": version,
        "installer_url": (
            f"https://github.com/{update_repository}/releases/download/"
            f"v{version}/{installer_name}"
        ),
        "sha256": sha256,
        "size_bytes": size_bytes,
        "release_notes": release_notes,
    }
    signed = sign_update_manifest(
        unsigned,
        private_key_base64=private_key_base64,
        key_id=key_id,
    )
    verify_update_manifest_signature(signed, UPDATE_MANIFEST_PUBLIC_KEYS)
    return signed


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Erzeugt das signierte Sacrificial-Tower-Update-Manifest."
    )
    parser.add_argument("--metadata", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument(
        "--update-repository",
        default="RodeProjects/sacrificial-tower-updates",
    )
    parser.add_argument("--release-notes", required=True)
    parser.add_argument("--key-id", default=CURRENT_UPDATE_SIGNING_KEY_ID)
    parser.add_argument("--private-key-env", default=DEFAULT_PRIVATE_KEY_ENV)
    arguments = parser.parse_args()
    private_key = os.environ.get(arguments.private_key_env, "")
    if not private_key.strip():
        raise RuntimeError(
            f"Das GitHub-Secret {arguments.private_key_env} fehlt."
        )
    manifest = create_manifest(
        arguments.metadata,
        update_repository=arguments.update_repository,
        release_notes=arguments.release_notes,
        private_key_base64=private_key,
        key_id=arguments.key_id,
    )
    arguments.output.parent.mkdir(parents=True, exist_ok=True)
    arguments.output.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
        newline="\n",
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
