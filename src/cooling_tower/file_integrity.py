from __future__ import annotations

import hashlib
from pathlib import Path


_HASH_BLOCK_SIZE = 1024 * 1024


def sha256_file(path: str | Path) -> str:
    """Return a SHA-256 digest without loading the complete file into memory."""

    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for block in iter(lambda: handle.read(_HASH_BLOCK_SIZE), b""):
            digest.update(block)
    return digest.hexdigest()
