from __future__ import annotations

import base64
import binascii
import json
from collections.abc import Mapping
from typing import Any

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import (
    Ed25519PrivateKey,
    Ed25519PublicKey,
)


SIGNATURE_ALGORITHM = "Ed25519"


class UpdateManifestSignatureError(ValueError):
    """The manifest does not carry a valid trusted update signature."""


def canonical_manifest_bytes(manifest: Mapping[str, Any]) -> bytes:
    """Return the deterministic byte representation covered by the signature."""

    unsigned = dict(manifest)
    unsigned.pop("signature", None)
    try:
        serialized = json.dumps(
            unsigned,
            ensure_ascii=False,
            allow_nan=False,
            sort_keys=True,
            separators=(",", ":"),
        )
    except (TypeError, ValueError) as error:
        raise UpdateManifestSignatureError(
            "Das Update-Manifest kann nicht eindeutig serialisiert werden."
        ) from error
    return serialized.encode("utf-8")


def _decode_base64(value: object, *, label: str, expected_size: int) -> bytes:
    if not isinstance(value, str) or not value.strip():
        raise UpdateManifestSignatureError(f"{label} fehlt.")
    try:
        decoded = base64.b64decode(value.strip(), validate=True)
    except (ValueError, binascii.Error) as error:
        raise UpdateManifestSignatureError(
            f"{label} ist nicht gültig Base64-kodiert."
        ) from error
    if len(decoded) != expected_size:
        raise UpdateManifestSignatureError(
            f"{label} besitzt eine unerwartete Länge."
        )
    return decoded


def sign_update_manifest(
    manifest: Mapping[str, Any],
    *,
    private_key_base64: str,
    key_id: str,
) -> dict[str, Any]:
    """Sign a manifest without ever persisting the private key to disk."""

    private_bytes = _decode_base64(
        private_key_base64,
        label="Der private Updateschlüssel",
        expected_size=32,
    )
    signed = dict(manifest)
    signed["signature_algorithm"] = SIGNATURE_ALGORITHM
    signed["signing_key_id"] = str(key_id)
    signed.pop("signature", None)
    signature = Ed25519PrivateKey.from_private_bytes(private_bytes).sign(
        canonical_manifest_bytes(signed)
    )
    signed["signature"] = base64.b64encode(signature).decode("ascii")
    return signed


def verify_update_manifest_signature(
    manifest: Mapping[str, Any],
    public_keys: Mapping[str, str],
) -> None:
    """Verify that a manifest was signed by an embedded trusted key."""

    if manifest.get("signature_algorithm") != SIGNATURE_ALGORITHM:
        raise UpdateManifestSignatureError(
            "Das Update-Manifest verwendet kein unterstütztes Signaturverfahren."
        )
    key_id = manifest.get("signing_key_id")
    if not isinstance(key_id, str) or key_id not in public_keys:
        raise UpdateManifestSignatureError(
            "Das Update-Manifest verwendet keinen vertrauenswürdigen Schlüssel."
        )
    public_bytes = _decode_base64(
        public_keys[key_id],
        label="Der öffentliche Updateschlüssel",
        expected_size=32,
    )
    signature = _decode_base64(
        manifest.get("signature"),
        label="Die Update-Manifest-Signatur",
        expected_size=64,
    )
    try:
        Ed25519PublicKey.from_public_bytes(public_bytes).verify(
            signature,
            canonical_manifest_bytes(manifest),
        )
    except InvalidSignature as error:
        raise UpdateManifestSignatureError(
            "Die Signatur des Update-Manifests ist ungültig."
        ) from error
