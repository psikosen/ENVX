"""Entity canonicalization (architecture §5.9).

"ACME Housing LLC" / "Acme Housing" / "ACME HOUSING L.L.C." resolve to one
canonical identity. This has to happen before the graph layer and before any
cross-document synthesis — §12 is explicit that LLMs must not synthesize
across documents without canonical entity resolution.

Resolution is two-pass:
    1. Exact match on a normalized key (casefold, strip corporate suffixes,
       drop punctuation, collapse whitespace).
    2. Fuzzy match above ``min_ratio``, recording the score as
       ``resolution_confidence`` so near-misses surface for review.

Entities bootstrap from KIE output — typed, with page provenance — rather
than fuzzy NER over noisy OCR text (§2.5.3).
"""

from __future__ import annotations

import re
import unicodedata
import uuid
from dataclasses import dataclass, field
from typing import Any

from rapidfuzz import fuzz


_CORP_SUFFIX_RE = re.compile(
    r"\b(l\.?l\.?c\.?|inc\.?|incorporated|corp\.?|corporation|co\.?|company"
    r"|ltd\.?|limited|l\.?l\.?p\.?|l\.?p\.?|p\.?c\.?|trust|associates)\b",
    re.IGNORECASE,
)
_NON_ALNUM_RE = re.compile(r"[^a-z0-9 ]+")
_WS_RE = re.compile(r"\s+")

# Entity types whose names carry corporate suffixes worth stripping.
_ORG_LIKE = {
    "organization", "party", "insurer", "seller", "buyer", "insured",
    "preparer_firm", "inspector_firm", "provider",
}

# Street-suffix normalization so "123 Elm St" == "123 Elm Street".
_STREET_ABBREV = {
    "st": "street", "ave": "avenue", "rd": "road", "blvd": "boulevard",
    "ln": "lane", "dr": "drive", "ct": "court", "pl": "place",
    "hwy": "highway", "pkwy": "parkway", "ter": "terrace",
}


def normalize_entity_key(name: str, entity_type: str) -> str:
    if not name:
        return ""
    n = unicodedata.normalize("NFKC", name).casefold()
    if entity_type in _ORG_LIKE:
        n = _CORP_SUFFIX_RE.sub(" ", n)
    n = _NON_ALNUM_RE.sub(" ", n)
    n = _WS_RE.sub(" ", n).strip()
    if entity_type == "property":
        n = " ".join(_STREET_ABBREV.get(tok, tok) for tok in n.split())
    return n


@dataclass(frozen=True)
class EntityMention:
    entity_type: str
    surface_form: str
    doc_id: str
    page_number: int | None = None
    region_id: str | None = None
    source_extraction_id: str | None = None


@dataclass
class CanonicalEntity:
    canonical_id: str
    entity_type: str
    display_name: str
    normalized_key: str
    aliases: set[str] = field(default_factory=set)
    attributes: dict[str, Any] = field(default_factory=dict)
    doc_ids: set[str] = field(default_factory=set)


@dataclass(frozen=True)
class Resolution:
    entity: CanonicalEntity
    confidence: float
    created: bool


class EntityResolver:
    """In-memory resolver. Mirrors the ``entity_canonical`` table surface."""

    def __init__(self, *, min_ratio: float = 0.92) -> None:
        self.min_ratio = min_ratio
        self._by_key: dict[tuple[str, str], CanonicalEntity] = {}

    def all(self) -> list[CanonicalEntity]:
        return list(self._by_key.values())

    def adopt(self, entity: CanonicalEntity) -> None:
        """Load a previously resolved identity into the resolver.

        Used when restoring from storage. Without this, a restart would mint
        fresh canonical ids for entities already known, silently forking one
        identity into two and breaking cross-document synthesis — the exact
        failure canonicalization exists to prevent.
        """
        self._by_key[(entity.entity_type, entity.normalized_key)] = entity

    def resolve(self, mention: EntityMention) -> Resolution:
        key = normalize_entity_key(mention.surface_form, mention.entity_type)
        if not key:
            entity = self._create(mention, key)
            return Resolution(entity=entity, confidence=0.0, created=True)

        direct = self._by_key.get((mention.entity_type, key))
        if direct is not None:
            direct.aliases.add(mention.surface_form)
            direct.doc_ids.add(mention.doc_id)
            return Resolution(entity=direct, confidence=1.0, created=False)

        best: tuple[float, CanonicalEntity] | None = None
        for (etype, existing_key), entity in self._by_key.items():
            if etype != mention.entity_type:
                continue
            score = fuzz.token_set_ratio(key, existing_key) / 100.0
            if best is None or score > best[0]:
                best = (score, entity)
        if best is not None and best[0] >= self.min_ratio:
            entity = best[1]
            entity.aliases.add(mention.surface_form)
            entity.doc_ids.add(mention.doc_id)
            return Resolution(entity=entity, confidence=best[0], created=False)

        return Resolution(entity=self._create(mention, key), confidence=1.0, created=True)

    def _create(self, mention: EntityMention, key: str) -> CanonicalEntity:
        entity = CanonicalEntity(
            canonical_id=str(uuid.uuid4()),
            entity_type=mention.entity_type,
            display_name=mention.surface_form,
            normalized_key=key,
            aliases={mention.surface_form},
            doc_ids={mention.doc_id},
        )
        self._by_key[(mention.entity_type, key)] = entity
        return entity


# KIE field path -> entity type. Only roles we can type confidently.
_ENTITY_ROLES: dict[str, str] = {
    "$.seller.name": "seller",
    "$.buyer.name": "buyer",
    "$.insured.name": "insured",
    "$.insurer.name": "insurer",
    "$.preparer_firm": "preparer_firm",
    "$.inspector.name": "inspector",
    "$.inspector.firm": "inspector_firm",
    "$.provider_name": "provider",
}

_PROPERTY_PATHS = (
    "$.property.address_street",
    "$.property.address",
    "$.property_address",
    "$.loss_location",
)


def extract_entities_from_kie(payload: dict[str, Any], *, doc_id: str) -> list[EntityMention]:
    mentions: list[EntityMention] = []
    for path, etype in _ENTITY_ROLES.items():
        value = _get_path(payload, path)
        if isinstance(value, str) and value.strip():
            mentions.append(
                EntityMention(
                    entity_type=etype,
                    surface_form=value.strip(),
                    doc_id=doc_id,
                    page_number=_page_for(payload, path),
                )
            )
    for path in _PROPERTY_PATHS:
        value = _get_path(payload, path)
        if isinstance(value, str) and value.strip():
            mentions.append(
                EntityMention(
                    entity_type="property",
                    surface_form=value.strip(),
                    doc_id=doc_id,
                    page_number=_page_for(payload, path),
                )
            )
            break
    return mentions


def _get_path(payload: Any, path: str) -> Any:
    if not path.startswith("$"):
        return None
    node = payload
    for part in path[1:].split("."):
        if not part:
            continue
        if not isinstance(node, dict):
            return None
        node = node.get(part)
        if node is None:
            return None
    return node


def _page_for(payload: dict[str, Any], path: str) -> int | None:
    parent = _get_path(payload, path.rsplit(".", 1)[0])
    if not isinstance(parent, dict):
        return None
    pc = parent.get("page_cited")
    if isinstance(pc, int):
        return pc
    if isinstance(pc, list) and pc and isinstance(pc[0], int):
        return pc[0]
    return None
