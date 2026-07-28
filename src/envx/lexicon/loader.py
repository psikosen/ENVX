"""Legal-domain lexicon (architecture §7).

Drives BM25 query expansion and supplements marker rules for hazard variants
the KIE schemas don't model. Counsel-reviewed YAML, versioned in git.

Expansion matters because the query and the document rarely share vocabulary:
a lawyer asks about "asbestos", the inspection report says "friable ACM in
pipe lagging". Dense retrieval partially bridges that; BM25 does not bridge
it at all without expansion.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable

import yaml

from ..config import EnvxConfig, load_config


@dataclass(frozen=True)
class LexiconEntry:
    key: str
    category: str  # "hazard" | "clause"
    surface_forms: tuple[str, ...]
    abbreviations: tuple[str, ...] = ()
    related: tuple[str, ...] = ()
    regulatory_refs: tuple[str, ...] = ()
    boost: float = 1.0

    @property
    def all_terms(self) -> tuple[str, ...]:
        return tuple(
            dict.fromkeys(
                [*self.surface_forms, *self.abbreviations, *self.related]
            )
        )

    @property
    def marker_code(self) -> str:
        prefix = "RISK" if self.category == "hazard" else "CLAUSE"
        return f"{prefix}:{self.key.upper()}"


@dataclass
class Lexicon:
    version: str
    entries: dict[str, LexiconEntry] = field(default_factory=dict)

    def __len__(self) -> int:
        return len(self.entries)

    def get(self, key: str) -> LexiconEntry | None:
        return self.entries.get(key.casefold())

    def matching_entries(self, query: str) -> list[LexiconEntry]:
        """Entries whose vocabulary appears in the query.

        Matching is whole-token to avoid the classic false positive where
        "Pb" or "as is" fires on a substring of an unrelated word.
        """
        tokens = set(re.findall(r"[a-z0-9]+", query.casefold()))
        normalized = re.sub(r"\s+", " ", query.casefold())
        hits: list[LexiconEntry] = []
        for entry in self.entries.values():
            for term in entry.all_terms:
                term_l = term.casefold()
                if " " in term_l or "-" in term_l:
                    if term_l in normalized:
                        hits.append(entry)
                        break
                elif term_l in tokens:
                    hits.append(entry)
                    break
        return hits

    def expand_query(self, query: str, *, max_terms: int = 24) -> list[str]:
        """Terms to OR into a BM25 query, excluding what's already there."""
        present = set(re.findall(r"[a-z0-9]+", query.casefold()))
        expansions: list[str] = []
        for entry in self.matching_entries(query):
            for term in entry.all_terms:
                low = term.casefold()
                if low in present or term in expansions:
                    continue
                expansions.append(term)
                if len(expansions) >= max_terms:
                    return expansions
        return expansions

    def boosts_for(self, query: str) -> dict[str, float]:
        """Marker soft-boosts implied by the query's vocabulary (§3.4).

        Boost values in the lexicon are multipliers around 1.0; RRF works on
        small additive increments, so we convert to a delta.
        """
        return {
            entry.marker_code: round((entry.boost - 1.0) * 0.05, 5)
            for entry in self.matching_entries(query)
            if entry.boost > 1.0
        }


def load_lexicon(
    path: Path | None = None,
    *,
    config: EnvxConfig | None = None,
) -> Lexicon:
    cfg = config or load_config()
    target = path or cfg.lexicon_path
    if not target.exists():
        return Lexicon(version="none")
    raw = yaml.safe_load(target.read_text()) or {}
    lexicon = Lexicon(version=str(raw.get("version", "unknown")))
    for category, section in (("hazard", "terms"), ("clause", "clauses")):
        for key, body in (raw.get(section) or {}).items():
            if not isinstance(body, dict):
                continue
            lexicon.entries[str(key).casefold()] = LexiconEntry(
                key=str(key),
                category=category,
                surface_forms=_strs(body.get("surface_forms")),
                abbreviations=_strs(body.get("abbreviations")),
                related=_strs(body.get("related")),
                regulatory_refs=_strs(body.get("regulatory_refs")),
                boost=float(body.get("boost", 1.0)),
            )
    return lexicon


def _strs(value: Iterable | None) -> tuple[str, ...]:
    if not value:
        return ()
    return tuple(str(v) for v in value)
