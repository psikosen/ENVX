"""Versioned KIE schema loader.

Schemas live under ``schemas/{schema_id}/{version}.yml`` and carry both a
JSON Schema (Draft 2020-12) and a list of ``marker_rules``. The loader
content-hashes the canonical JSON encoding so any schema row persisted in
Postgres can be verified against the on-disk source at any time.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

from ..config import EnvxConfig, load_config


def canonical_schema_bytes(schema: dict[str, Any]) -> bytes:
    return json.dumps(schema, sort_keys=True, separators=(",", ":")).encode("utf-8")


class SchemaNotFound(KeyError):
    pass


@dataclass(frozen=True)
class DocSchema:
    schema_id: str
    version: str
    json_schema: dict[str, Any]
    marker_rules: list[dict[str, Any]]
    description: str
    phi_tier: bool
    content_hash: str
    source_path: Path

    def as_db_row(self) -> dict[str, Any]:
        return {
            "schema_id": self.schema_id,
            "version": self.version,
            "json_schema": self.json_schema,
            "marker_rules": self.marker_rules,
            "content_hash": bytes.fromhex(self.content_hash),
        }


class SchemaLoader:
    def __init__(self, root: Path | None = None, config: EnvxConfig | None = None) -> None:
        cfg = config or load_config()
        self.root = (root or cfg.schemas_root).resolve()

    def list_ids(self) -> list[str]:
        if not self.root.exists():
            return []
        return sorted(p.name for p in self.root.iterdir() if p.is_dir())

    def list_versions(self, schema_id: str) -> list[str]:
        d = self.root / schema_id
        if not d.exists():
            return []
        return sorted(p.stem for p in d.glob("*.yml"))

    def load(self, schema_id: str, version: str) -> DocSchema:
        path = self.root / schema_id / f"{version}.yml"
        if not path.exists():
            raise SchemaNotFound(f"{schema_id}/{version}")
        data = yaml.safe_load(path.read_text())
        if not isinstance(data, dict):
            raise ValueError(f"{path} is not a YAML mapping")
        if data.get("schema_id") != schema_id:
            raise ValueError(f"{path} schema_id={data.get('schema_id')!r} != {schema_id!r}")
        if data.get("version") != version:
            raise ValueError(f"{path} version={data.get('version')!r} != {version!r}")
        json_schema = data.get("json_schema")
        if not isinstance(json_schema, dict):
            raise ValueError(f"{path} missing 'json_schema'")
        marker_rules = data.get("marker_rules") or []
        if not isinstance(marker_rules, list):
            raise ValueError(f"{path} 'marker_rules' must be a list")
        content_hash = hashlib.sha256(canonical_schema_bytes(json_schema)).hexdigest()
        return DocSchema(
            schema_id=schema_id,
            version=version,
            json_schema=json_schema,
            marker_rules=list(marker_rules),
            description=str(data.get("description", "")).strip(),
            phi_tier=bool(data.get("phi_tier", False)),
            content_hash=content_hash,
            source_path=path,
        )

    def load_latest(self, schema_id: str) -> DocSchema:
        versions = self.list_versions(schema_id)
        if not versions:
            raise SchemaNotFound(schema_id)
        return self.load(schema_id, versions[-1])


def load_default_library(config: EnvxConfig | None = None) -> dict[str, DocSchema]:
    loader = SchemaLoader(config=config)
    out: dict[str, DocSchema] = {}
    for sid in loader.list_ids():
        for ver in loader.list_versions(sid):
            out[f"{sid}/{ver}"] = loader.load(sid, ver)
    return out
