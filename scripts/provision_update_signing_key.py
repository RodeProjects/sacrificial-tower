from __future__ import annotations

import argparse
import base64
import shutil
import subprocess
from pathlib import Path

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey


DEFAULT_REPOSITORY = "RodeProjects/sacrificial-tower"
DEFAULT_SECRET_NAME = "UPDATE_MANIFEST_SIGNING_KEY_BASE64"


def _github_cli() -> str:
    discovered = shutil.which("gh")
    if discovered:
        return discovered
    fallback = Path(r"C:\Program Files\GitHub CLI\gh.exe")
    if fallback.is_file():
        return str(fallback)
    raise RuntimeError("GitHub CLI wurde nicht gefunden.")


def provision(repository: str, secret_name: str) -> str:
    """Create an Ed25519 key and send only its private half to GitHub."""

    private_key = Ed25519PrivateKey.generate()
    private_bytes = private_key.private_bytes(
        encoding=serialization.Encoding.Raw,
        format=serialization.PrivateFormat.Raw,
        encryption_algorithm=serialization.NoEncryption(),
    )
    public_bytes = private_key.public_key().public_bytes(
        encoding=serialization.Encoding.Raw,
        format=serialization.PublicFormat.Raw,
    )
    private_base64 = base64.b64encode(private_bytes).decode("ascii")
    subprocess.run(
        [
            _github_cli(),
            "secret",
            "set",
            secret_name,
            "--repo",
            repository,
        ],
        input=private_base64 + "\n",
        text=True,
        check=True,
    )
    return base64.b64encode(public_bytes).decode("ascii")


def main() -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Erzeugt einen Ed25519-Schlüssel, speichert ausschließlich den "
            "privaten Anteil als GitHub-Secret und gibt den öffentlichen "
            "Anteil aus."
        )
    )
    parser.add_argument("--repository", default=DEFAULT_REPOSITORY)
    parser.add_argument("--secret-name", default=DEFAULT_SECRET_NAME)
    arguments = parser.parse_args()
    public_key = provision(arguments.repository, arguments.secret_name)
    print(f"Öffentlicher Ed25519-Schlüssel (Base64): {public_key}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
