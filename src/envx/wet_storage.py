"""Content-addressed wet storage layout.

Implements the directory structure from architecture-v2.1 §4.1:

    evidence_blobs/{sha256}/
      original.{ext}
      metadata.json
      parse_runs/{run_uuid}/{parser.json, result.json, attestation.sig, ...}
      kie_runs/{run_uuid}/{schema.json, prompt.txt, output.json, validation_report.json, attestation.sig}
      markers.jsonl
      audit.log

In dev this is a local filesystem. Production swaps the backend for S3 with
Object Lock; the method surface is kept minimal so that swap is mechanical.

Writes are append-only. Originals and run artifacts are written once and
never overwritten — the store raises if a caller tries.
"""

from __future__ import annotations

import hashlib
import json
import os
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .attestation import sign_manifest


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fp:
        for chunk in iter(lambda: fp.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _utcnow() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="microseconds")


@dataclass(frozen=True)
class BlobRef:
    sha256: str
    root: Path

    @property
    def parse_runs_dir(self) -> Path:
        return self.root / "parse_runs"

    @property
    def kie_runs_dir(self) -> Path:
        return self.root / "kie_runs"

    @property
    def audit_log(self) -> Path:
        return self.root / "audit.log"


class WetStore:
    def __init__(self, base: Path, attestation_key_path: Path) -> None:
        self.base = base
        self.attestation_key_path = attestation_key_path
        self.base.mkdir(parents=True, exist_ok=True)

    def _blob_dir(self, sha256: str) -> Path:
        return self.base / "evidence_blobs" / sha256

    def ingest_bytes(
        self,
        data: bytes,
        extension: str,
        metadata: dict[str, Any],
    ) -> BlobRef:
        digest = sha256_bytes(data)
        blob_dir = self._blob_dir(digest)
        original = blob_dir / f"original.{extension.lstrip('.')}"
        if original.exists():
            # WORM: identical content already ingested — dedupe, don't overwrite.
            self._append_audit(blob_dir, "ingest_duplicate", {"sha256": digest})
            return BlobRef(sha256=digest, root=blob_dir)
        blob_dir.mkdir(parents=True, exist_ok=True)
        tmp = original.with_suffix(original.suffix + ".part")
        tmp.write_bytes(data)
        os.replace(tmp, original)
        try:
            original.chmod(0o444)
        except PermissionError:
            pass
        meta = {
            "sha256": digest,
            "extension": extension,
            "ingested_at": _utcnow(),
            **metadata,
        }
        (blob_dir / "metadata.json").write_text(json.dumps(meta, indent=2, sort_keys=True))
        self._append_audit(blob_dir, "ingest", {"sha256": digest, "extension": extension})
        return BlobRef(sha256=digest, root=blob_dir)

    def record_parse_run(
        self,
        ref: BlobRef,
        parser: dict[str, Any],
        result: dict[str, Any],
    ) -> str:
        run_id = str(uuid.uuid4())
        run_dir = ref.parse_runs_dir / run_id
        return self._write_run(run_dir, parser, result, run_kind="parse", run_id=run_id, ref=ref)

    def record_kie_run(
        self,
        ref: BlobRef,
        schema: dict[str, Any],
        prompt: str,
        output: dict[str, Any],
        validation_report: dict[str, Any],
    ) -> str:
        run_id = str(uuid.uuid4())
        run_dir = ref.kie_runs_dir / run_id
        run_dir.mkdir(parents=True, exist_ok=False)
        (run_dir / "schema.json").write_text(json.dumps(schema, sort_keys=True, indent=2))
        (run_dir / "prompt.txt").write_text(prompt)
        (run_dir / "output.json").write_text(json.dumps(output, sort_keys=True, indent=2))
        (run_dir / "validation_report.json").write_text(
            json.dumps(validation_report, sort_keys=True, indent=2)
        )
        manifest = {
            "kind": "kie",
            "run_id": run_id,
            "blob_sha256": ref.sha256,
            "schema_sha256": sha256_bytes(
                json.dumps(schema, sort_keys=True, separators=(",", ":")).encode()
            ),
            "output_sha256": sha256_bytes(
                json.dumps(output, sort_keys=True, separators=(",", ":")).encode()
            ),
            "ended_at": _utcnow(),
        }
        (run_dir / "manifest.json").write_text(json.dumps(manifest, sort_keys=True, indent=2))
        signature = sign_manifest(manifest, self.attestation_key_path)
        (run_dir / "attestation.sig").write_bytes(signature)
        self._append_audit(ref.root, "kie_run", {"run_id": run_id, "schema": schema.get("$id", "")})
        return run_id

    def append_markers(self, ref: BlobRef, markers: list[dict[str, Any]]) -> None:
        path = ref.root / "markers.jsonl"
        with path.open("a") as fp:
            for m in markers:
                fp.write(json.dumps({"at": _utcnow(), **m}, sort_keys=True) + "\n")
        self._append_audit(ref.root, "markers_appended", {"count": len(markers)})

    def _write_run(
        self,
        run_dir: Path,
        parser: dict[str, Any],
        result: dict[str, Any],
        *,
        run_kind: str,
        run_id: str,
        ref: BlobRef,
    ) -> str:
        run_dir.mkdir(parents=True, exist_ok=False)
        (run_dir / "parser.json").write_text(json.dumps(parser, sort_keys=True, indent=2))
        (run_dir / "result.json").write_text(json.dumps(result, sort_keys=True, indent=2))
        manifest = {
            "kind": run_kind,
            "run_id": run_id,
            "blob_sha256": ref.sha256,
            "parser_sha256": sha256_bytes(
                json.dumps(parser, sort_keys=True, separators=(",", ":")).encode()
            ),
            "result_sha256": sha256_bytes(
                json.dumps(result, sort_keys=True, separators=(",", ":")).encode()
            ),
            "ended_at": _utcnow(),
        }
        (run_dir / "manifest.json").write_text(json.dumps(manifest, sort_keys=True, indent=2))
        signature = sign_manifest(manifest, self.attestation_key_path)
        (run_dir / "attestation.sig").write_bytes(signature)
        self._append_audit(ref.root, f"{run_kind}_run", {"run_id": run_id})
        return run_id

    def _append_audit(self, blob_dir: Path, event: str, detail: dict[str, Any]) -> None:
        blob_dir.mkdir(parents=True, exist_ok=True)
        line = json.dumps({"at": _utcnow(), "event": event, **detail}, sort_keys=True) + "\n"
        with (blob_dir / "audit.log").open("a") as fp:
            fp.write(line)
