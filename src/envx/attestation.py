"""Ed25519 signing of parse/KIE run manifests.

A parse run's manifest (blob_hash, parser manifest, result hash, timestamps)
is signed so that downstream consumers can verify a run wasn't tampered with
without re-reading the full result from wet storage.

Keys are generated on first use and persisted to disk. Production should
replace this with KMS-backed keys; this is the local-dev path.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import (
    Ed25519PrivateKey,
    Ed25519PublicKey,
)


def _load_or_create_key(path: Path) -> Ed25519PrivateKey:
    if path.exists():
        return serialization.load_pem_private_key(path.read_bytes(), password=None)  # type: ignore[return-value]
    path.parent.mkdir(parents=True, exist_ok=True)
    key = Ed25519PrivateKey.generate()
    path.write_bytes(
        key.private_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PrivateFormat.PKCS8,
            encryption_algorithm=serialization.NoEncryption(),
        )
    )
    path.chmod(0o600)
    return key


def canonical_manifest_bytes(manifest: dict[str, Any]) -> bytes:
    """Deterministic JSON encoding so signatures are reproducible."""
    return json.dumps(manifest, sort_keys=True, separators=(",", ":")).encode("utf-8")


def sign_manifest(manifest: dict[str, Any], key_path: Path) -> bytes:
    key = _load_or_create_key(key_path)
    return key.sign(canonical_manifest_bytes(manifest))


def verify_manifest(manifest: dict[str, Any], signature: bytes, key_path: Path) -> bool:
    key = _load_or_create_key(key_path)
    pub: Ed25519PublicKey = key.public_key()
    try:
        pub.verify(signature, canonical_manifest_bytes(manifest))
        return True
    except Exception:
        return False
