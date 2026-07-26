from __future__ import annotations

import argparse
import hashlib
import sys
from pathlib import Path
from urllib.parse import urlparse


PROJECT_ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = PROJECT_ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from cooling_tower.update import parse_update_manifest  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Prüft Signatur und optional den Installer eines Updates."
    )
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--installer", type=Path)
    arguments = parser.parse_args()
    info = parse_update_manifest(arguments.manifest.read_bytes())
    if arguments.installer is not None:
        installer = arguments.installer
        if not installer.is_file():
            raise FileNotFoundError(f"Der Installer fehlt: {installer}")
        payload = installer.read_bytes()
        if len(payload) != info.size_bytes:
            raise ValueError("Die Installergröße stimmt nicht mit dem Manifest überein.")
        if hashlib.sha256(payload).hexdigest() != info.sha256:
            raise ValueError("Der Installer-Hash stimmt nicht mit dem Manifest überein.")
        expected_name = Path(urlparse(info.installer_url).path).name
        if installer.name != expected_name:
            raise ValueError("Der Installername stimmt nicht mit dem Manifest überein.")
    print(f"Signiertes Sacrificial-Tower-Update {info.version} erfolgreich geprüft.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
