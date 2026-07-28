"""Contextual Retrieval enrichment (architecture §3.1).

Anthropic's technique: prepend a short, document-grounded context blurb to
each chunk before embedding and BM25 indexing. Published effect is a 35%
retrieval-failure reduction from contextual embeddings, 49% adding
contextual BM25, 67% with a reranker on top.

The v2.1 twist is that we template in KIE fields rather than asking an LLM
to summarize the document cold. A prompt that already knows the parties,
execution date, property, and hazards produces far better-grounded context
than one re-deriving them from raw text — and it costs a fraction as much.

Two writers ship here:
    ``TemplateContextWriter``  deterministic, no LLM, no network. Default.
    ``ContextWriter``          Protocol for a Claude-backed implementation
                               using prompt caching (~$0.012 per 1000-page
                               doc per §3.1).

Indexing operates on ``text_contextual``; display and quotation always use
``text_raw`` (§12).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol

from ..chunking import Chunk


@dataclass(frozen=True)
class ContextualEnrichment:
    chunk_id: str
    prefix: str
    text_contextual: str


CONTEXT_PROMPT_TEMPLATE = """\
You will be given a chunk of text from a legal document. Given these known \
facts about the document:

{facts}

...produce 1-3 sentences of context that would help a retrieval system find \
this chunk in response to queries that may use different wording. The context \
will be prepended to the chunk before embedding and BM25 indexing. Output only \
the context sentences.

<chunk>
{chunk}
</chunk>"""


def build_doc_facts(kie_payload: dict[str, Any]) -> dict[str, Any]:
    """Flatten KIE output into the fact set used for context generation.

    Empty values are dropped so generated prose never reads
    "executed  between  and  regarding property at ".
    """
    facts: dict[str, Any] = {}

    def put(key: str, value: Any) -> None:
        if value:
            facts[key] = value

    put("doc_type", kie_payload.get("doc_type"))
    put("jurisdiction", kie_payload.get("jurisdiction"))
    put(
        "execution_date",
        kie_payload.get("execution_date")
        or kie_payload.get("inspection_date")
        or kie_payload.get("date_of_loss")
        or kie_payload.get("date_of_service"),
    )

    parties: list[str] = []
    for role in ("seller", "buyer", "insured", "insurer", "inspector"):
        node = kie_payload.get(role)
        if isinstance(node, dict) and isinstance(node.get("name"), str):
            if node["name"].strip():
                parties.append(node["name"].strip())
    firm = kie_payload.get("preparer_firm")
    if isinstance(firm, str) and firm.strip():
        parties.append(firm.strip())
    put("parties", parties)

    prop = kie_payload.get("property")
    if isinstance(prop, dict):
        street = prop.get("address_street") or prop.get("address")
        parts = [
            p for p in (street, prop.get("address_city"), prop.get("address_zip"))
            if isinstance(p, str) and p.strip()
        ]
        put("property_address", ", ".join(parts))
        put("parcel_id", prop.get("parcel_id"))
    elif isinstance(kie_payload.get("property_address"), str):
        put("property_address", kie_payload["property_address"])

    findings: list[str] = []
    for hazard in kie_payload.get("hazards_disclosed") or []:
        if isinstance(hazard, dict) and isinstance(hazard.get("type"), str):
            findings.append(hazard["type"].strip())
    for obs in kie_payload.get("hazmat_observed") or []:
        if isinstance(obs, dict) and isinstance(obs.get("type"), str):
            findings.append(obs["type"].strip())
    for rec in kie_payload.get("recs") or []:
        if isinstance(rec, dict):
            cond = rec.get("condition") or rec.get("rec_type")
            if isinstance(cond, str) and cond.strip():
                findings.append(cond.strip())
    put("key_findings", [f for f in findings if f])

    for key in ("claim_number", "policy_number", "report_type", "peril"):
        put(key, kie_payload.get(key))
    return facts


def format_facts(facts: dict[str, Any]) -> str:
    lines: list[str] = []
    for key, value in facts.items():
        rendered = ", ".join(str(v) for v in value) if isinstance(value, list) else str(value)
        lines.append(f"  {key + ':':<18}{rendered}")
    return "\n".join(lines) if lines else "  (no structured facts extracted)"


class ContextWriter(Protocol):
    def write_context(self, *, chunk_text: str, doc_facts: dict[str, Any]) -> str: ...


class TemplateContextWriter:
    """Deterministic context from KIE facts alone. No LLM, no network."""

    def write_context(self, *, chunk_text: str, doc_facts: dict[str, Any]) -> str:
        clauses: list[str] = []
        if doc_facts.get("doc_type"):
            clauses.append(f"This excerpt is from a {doc_facts['doc_type'].replace('_', ' ')}")
        else:
            clauses.append("This excerpt is from a legal document")
        if doc_facts.get("report_type"):
            clauses.append(f"({str(doc_facts['report_type']).replace('_', ' ')})")
        if doc_facts.get("execution_date"):
            clauses.append(f"dated {doc_facts['execution_date']}")
        if doc_facts.get("parties"):
            clauses.append("involving " + " and ".join(doc_facts["parties"][:3]))
        if doc_facts.get("property_address"):
            clauses.append(f"concerning the property at {doc_facts['property_address']}")
        if doc_facts.get("parcel_id"):
            clauses.append(f"(parcel {doc_facts['parcel_id']})")
        if doc_facts.get("jurisdiction"):
            clauses.append(f"in {doc_facts['jurisdiction']}")

        prefix = " ".join(clauses).strip() + "."
        if doc_facts.get("claim_number"):
            prefix += f" Claim number {doc_facts['claim_number']}."
        if doc_facts.get("key_findings"):
            unique = sorted({str(f) for f in doc_facts["key_findings"]})[:6]
            prefix += f" The document records these findings: {', '.join(unique)}."
        return prefix


class ContextualEnricher:
    def __init__(self, writer: ContextWriter | None = None) -> None:
        self.writer: ContextWriter = writer or TemplateContextWriter()

    def enrich(
        self,
        chunks: list[Chunk],
        *,
        kie_payload: dict[str, Any],
    ) -> list[ContextualEnrichment]:
        facts = build_doc_facts(kie_payload)
        out: list[ContextualEnrichment] = []
        for chunk in chunks:
            prefix = self.writer.write_context(chunk_text=chunk.text, doc_facts=facts)
            out.append(
                ContextualEnrichment(
                    chunk_id=chunk.chunk_id,
                    prefix=prefix,
                    text_contextual=f"{prefix}\n\n{chunk.text}".strip(),
                )
            )
        return out
