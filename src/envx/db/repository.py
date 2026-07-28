"""Postgres persistence.

Binds the in-memory pipeline objects to the DDL in ``migrations/``. Without
this, indexes die with the process — which is why ``envx query`` had to
re-ingest its corpus.

Design notes:

    - Writes are one transaction per document. A half-persisted document is
      worse than an unpersisted one: it would be retrievable but missing
      markers or provenance, which is precisely the failure mode that makes
      an answer uncitable.

    - Content-addressed identity. ``documents.sha256`` is unique, so
      re-ingesting the same bytes updates rather than duplicating.

    - ``load_index_rows`` rehydrates the retrieval indexes on startup,
      applying the tier filter so cold documents don't consume hot memory.

psycopg is an optional dependency; ``PostgresRepository.available()`` reports
whether persistence can be used at all.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, Iterable, Sequence

from ..chunking import Chunk
from ..entities import CanonicalEntity
from ..graph import GraphEdge, GraphNode, KnowledgeGraph
from ..models import Marker, Region
from ..retrieval import IndexedChunk
from ..review import Correction, ReviewItem, ReviewState, ReviewTrigger
from ..wet_storage import doc_id_for


def psycopg_available() -> bool:
    try:
        import psycopg  # noqa: F401
    except ImportError:
        return False
    return True


@dataclass(frozen=True)
class DocumentRecord:
    sha256: str
    client_id: str
    matter_id: str | None
    doc_type: str | None
    doc_type_confidence: float | None
    page_count: int
    original_filename: str | None = None
    language: str | None = None


class PostgresRepository:
    """Thin, explicit data-access layer. No ORM, no lazy loading."""

    def __init__(self, dsn: str) -> None:
        if not psycopg_available():
            raise ImportError("psycopg is required: pip install 'psycopg[binary]'")
        self.dsn = dsn

    @staticmethod
    def available() -> bool:
        return psycopg_available()

    def _connect(self):
        import psycopg

        return psycopg.connect(self.dsn)

    # ------------------------------------------------------------- schema
    def register_schema(
        self,
        *,
        schema_id: str,
        version: str,
        json_schema: dict[str, Any],
        marker_rules: list[dict[str, Any]],
        content_hash: str,
    ) -> None:
        """Pin the exact schema a KIE run used.

        ``extracted_fields`` rows reference (schema_id, version), so the
        schema must exist before any extraction referencing it. Reproducing
        an extraction in court requires the exact schema content.
        """
        with self._connect() as conn:
            conn.execute(
                "INSERT INTO doc_schemas (schema_id, version, json_schema,"
                " marker_rules, content_hash) VALUES (%s,%s,%s,%s,%s)"
                " ON CONFLICT (schema_id, version) DO UPDATE"
                " SET json_schema = EXCLUDED.json_schema,"
                "     marker_rules = EXCLUDED.marker_rules,"
                "     content_hash = EXCLUDED.content_hash",
                (
                    schema_id,
                    version,
                    json.dumps(json_schema),
                    json.dumps(marker_rules),
                    bytes.fromhex(content_hash),
                ),
            )
            conn.commit()

    # ------------------------------------------------------------ persist
    def save_document(
        self,
        *,
        document: DocumentRecord,
        chunks: Sequence[Chunk],
        indexed: Sequence[IndexedChunk],
        regions: Sequence[Region] = (),
        markers: Sequence[Marker] = (),
        extracted_fields: Sequence[dict[str, Any]] = (),
        schema_ref: tuple[str, str] | None = None,
        kie_run_id: str | None = None,
    ) -> str:
        """Persist one document and everything derived from it, atomically."""
        by_id = {c.chunk_id: c for c in indexed}
        with self._connect() as conn:
            with conn.transaction():
                doc_id = self._upsert_document(conn, document)
                self._replace_pages(conn, doc_id, chunks, regions)
                region_ids = self._replace_regions(conn, doc_id, regions)
                self._replace_blocks(conn, doc_id, chunks, by_id, region_ids)
                if schema_ref and kie_run_id:
                    self._replace_extracted_fields(
                        conn, doc_id, extracted_fields, schema_ref, kie_run_id
                    )
                self._replace_markers(conn, doc_id, markers)
        return doc_id

    def _upsert_document(self, conn, doc: DocumentRecord) -> str:
        row = conn.execute(
            "INSERT INTO documents (doc_id, sha256, client_id, matter_id, doc_type,"
            " doc_type_confidence, page_count, original_filename, language)"
            " VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s)"
            " ON CONFLICT (sha256) DO UPDATE SET"
            "   client_id = EXCLUDED.client_id,"
            "   matter_id = EXCLUDED.matter_id,"
            "   doc_type = EXCLUDED.doc_type,"
            "   doc_type_confidence = EXCLUDED.doc_type_confidence,"
            "   page_count = EXCLUDED.page_count"
            " RETURNING doc_id",
            (
                doc_id_for(doc.sha256),
                bytes.fromhex(doc.sha256),
                doc.client_id,
                doc.matter_id,
                doc.doc_type,
                doc.doc_type_confidence,
                doc.page_count,
                doc.original_filename,
                doc.language,
            ),
        ).fetchone()
        return str(row[0])

    def _replace_pages(
        self,
        conn,
        doc_id: str,
        chunks: Sequence[Chunk],
        regions: Sequence[Region],
    ) -> None:
        pages = sorted({c.page_number for c in chunks} | {r.page_number for r in regions})
        region_counts: dict[int, int] = {}
        flags: dict[int, set[str]] = {}
        for region in regions:
            region_counts[region.page_number] = region_counts.get(region.page_number, 0) + 1
            flags.setdefault(region.page_number, set()).add(region.region_type.value)
        for page in pages:
            present = flags.get(page, set())
            conn.execute(
                "INSERT INTO pages (doc_id, page_number, region_count,"
                " has_signature, has_stamp) VALUES (%s,%s,%s,%s,%s)"
                " ON CONFLICT (doc_id, page_number) DO UPDATE SET"
                "   region_count = EXCLUDED.region_count,"
                "   has_signature = EXCLUDED.has_signature,"
                "   has_stamp = EXCLUDED.has_stamp",
                (
                    doc_id,
                    page,
                    region_counts.get(page, 0),
                    "signature" in present,
                    "stamp" in present,
                ),
            )

    def _replace_regions(
        self,
        conn,
        doc_id: str,
        regions: Sequence[Region],
    ) -> dict[str, str]:
        # Regions are derived output; a re-parse replaces them wholesale.
        conn.execute("DELETE FROM regions WHERE doc_id = %s", (doc_id,))
        mapping: dict[str, str] = {}
        for region in regions:
            row = conn.execute(
                "INSERT INTO regions (doc_id, page_number, bbox, region_type,"
                " label_confidence) VALUES (%s,%s,%s,%s,%s) RETURNING region_id",
                (
                    doc_id,
                    region.page_number,
                    list(region.bbox),
                    region.region_type.value,
                    region.label_confidence,
                ),
            ).fetchone()
            if region.region_id:
                mapping[region.region_id] = str(row[0])
        return mapping

    def _replace_blocks(
        self,
        conn,
        doc_id: str,
        chunks: Sequence[Chunk],
        indexed: dict[str, IndexedChunk],
        region_ids: dict[str, str],
    ) -> None:
        conn.execute("DELETE FROM blocks WHERE doc_id = %s", (doc_id,))
        for chunk in chunks:
            meta = indexed.get(chunk.chunk_id)
            if meta is None:
                continue
            conn.execute(
                "INSERT INTO blocks (doc_id, page_number, content_hash, text_raw,"
                " text_contextual, region_id, region_type, client_id, matter_id,"
                " storage_tier, marker_array)"
                " VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)"
                " ON CONFLICT (doc_id, content_hash) DO NOTHING",
                (
                    doc_id,
                    chunk.page_number,
                    bytes.fromhex(chunk.content_hash),
                    chunk.text,
                    meta.text_contextual,
                    region_ids.get(chunk.region_id or "", None),
                    chunk.region_type,
                    meta.client_id,
                    meta.matter_id,
                    meta.storage_tier,
                    list(meta.marker_array),
                ),
            )

    def _replace_extracted_fields(
        self,
        conn,
        doc_id: str,
        fields: Sequence[dict[str, Any]],
        schema_ref: tuple[str, str],
        kie_run_id: str,
    ) -> None:
        conn.execute("DELETE FROM extracted_fields WHERE doc_id = %s", (doc_id,))
        schema_id, schema_version = schema_ref
        for field in fields:
            value = field.get("value")
            conn.execute(
                "INSERT INTO extracted_fields (doc_id, schema_id, schema_version,"
                " kie_run_id, field_path, field_value_text, field_value_num,"
                " page_cited, grounding_verified, verification_score,"
                " grounding_status)"
                " VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)",
                (
                    doc_id,
                    schema_id,
                    schema_version,
                    kie_run_id,
                    field["field_path"],
                    str(value) if isinstance(value, str) else None,
                    value if isinstance(value, (int, float)) and not isinstance(value, bool) else None,
                    field.get("page_cited"),
                    bool(field.get("grounding_verified", False)),
                    field.get("verification_score"),
                    field.get("grounding_status", "not_applicable"),
                ),
            )

    def _replace_markers(self, conn, doc_id: str, markers: Sequence[Marker]) -> None:
        conn.execute("DELETE FROM markers WHERE doc_id = %s", (doc_id,))
        for marker in markers:
            conn.execute(
                "INSERT INTO markers (doc_id, code, confidence, extracted_by, evidence)"
                " VALUES (%s,%s,%s,%s,%s)",
                (
                    doc_id,
                    marker.code,
                    marker.confidence,
                    marker.extracted_by,
                    json.dumps(marker.evidence or {}),
                ),
            )

    # --------------------------------------------------------------- read
    def load_index_rows(
        self,
        *,
        client_id: str | None = None,
        storage_tiers: Iterable[str] = ("hot", "warm"),
    ) -> list[IndexedChunk]:
        """Rehydrate retrieval rows.

        Cold documents are excluded by default so they don't consume hot-tier
        memory — they're served by the LEANN cold store instead.
        """
        sql = [
            "SELECT b.block_id, b.doc_id, b.text_raw, b.text_contextual,",
            "       b.client_id, b.matter_id, b.page_number, b.region_id,",
            "       b.region_type, b.storage_tier, b.marker_array, d.doc_type",
            "  FROM blocks b JOIN documents d ON d.doc_id = b.doc_id",
            " WHERE b.storage_tier = ANY(%s)",
        ]
        params: list[Any] = [list(storage_tiers)]
        if client_id is not None:
            sql.append("   AND b.client_id = %s")
            params.append(client_id)

        with self._connect() as conn:
            rows = conn.execute("\n".join(sql), params).fetchall()

        return [
            IndexedChunk(
                chunk_id=str(r[0]),
                doc_id=str(r[1]),
                text_raw=r[2] or "",
                text_contextual=r[3] or r[2] or "",
                client_id=r[4],
                matter_id=r[5],
                page_number=r[6] or 1,
                region_id=str(r[7]) if r[7] else None,
                region_type=r[8],
                storage_tier=r[9] or "hot",
                marker_array=tuple(r[10] or ()),
                doc_type=r[11],
            )
            for r in rows
        ]

    def document_count(self) -> int:
        with self._connect() as conn:
            return int(conn.execute("SELECT count(*) FROM documents").fetchone()[0])

    def markers_for(self, doc_id: str) -> dict[str, float]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT code, confidence FROM markers"
                " WHERE doc_id = %s AND retracted_at IS NULL",
                (doc_id,),
            ).fetchall()
        return {r[0]: float(r[1]) for r in rows}

    # -------------------------------------------------------------- graph
    def save_graph(
        self,
        graph: KnowledgeGraph,
        *,
        entities: Sequence[CanonicalEntity] = (),
    ) -> None:
        """Upsert the whole graph.

        The graph is an accumulator over every document, so this is an upsert
        of the current state rather than a per-document delta. Edges carry
        their justifying doc_id and are uniquely keyed on
        (source, target, relation, doc_id), so re-ingesting a document
        rewrites its own edges without disturbing anyone else's.
        """
        with self._connect() as conn:
            with conn.transaction():
                for node in graph.nodes:
                    conn.execute(
                        "INSERT INTO graph_nodes (node_id, node_type, label, attributes)"
                        " VALUES (%s,%s,%s,%s)"
                        " ON CONFLICT (node_id) DO UPDATE SET"
                        "   label = EXCLUDED.label,"
                        "   attributes = EXCLUDED.attributes,"
                        "   updated_at = now()",
                        (
                            node.node_id,
                            node.node_type,
                            node.label,
                            json.dumps(_jsonable(node.attributes)),
                        ),
                    )
                for edge in graph.edges:
                    conn.execute(
                        "INSERT INTO graph_edges (source_id, target_id, relation, doc_id)"
                        " VALUES (%s,%s,%s,%s)"
                        " ON CONFLICT (source_id, target_id, relation, doc_id) DO NOTHING",
                        (edge.source, edge.target, edge.relation, edge.doc_id),
                    )
                for entity in entities:
                    conn.execute(
                        "INSERT INTO entity_canonical (canonical_id, entity_type,"
                        " display_name, aliases, normalized_key, attributes, graph_node_id)"
                        " VALUES (%s,%s,%s,%s,%s,%s,%s)"
                        " ON CONFLICT (entity_type, normalized_key) DO UPDATE SET"
                        "   display_name = EXCLUDED.display_name,"
                        "   aliases = EXCLUDED.aliases,"
                        "   graph_node_id = EXCLUDED.graph_node_id",
                        (
                            entity.canonical_id,
                            entity.entity_type,
                            entity.display_name,
                            sorted(entity.aliases),
                            entity.normalized_key,
                            json.dumps(_jsonable(entity.attributes)),
                            f"entity:{entity.canonical_id}",
                        ),
                    )

    def load_graph(self) -> KnowledgeGraph:
        graph = KnowledgeGraph()
        with self._connect() as conn:
            nodes = conn.execute(
                "SELECT node_id, node_type, label, attributes FROM graph_nodes"
            ).fetchall()
            edges = conn.execute(
                "SELECT source_id, target_id, relation, doc_id FROM graph_edges"
            ).fetchall()
        for node_id, node_type, label, attributes in nodes:
            graph.add_node(
                GraphNode(
                    node_id=node_id,
                    node_type=node_type,
                    label=label,
                    attributes=attributes or {},
                )
            )
        for source, target, relation, doc_id in edges:
            # Skip dangling edges rather than raising: a node deleted by a
            # cascade should degrade the graph, not block startup.
            if graph.node(source) is None or graph.node(target) is None:
                continue
            graph.add_edge(
                GraphEdge(
                    source=source,
                    target=target,
                    relation=relation,
                    doc_id=str(doc_id),
                )
            )
        return graph

    def load_canonical_entities(self) -> list[CanonicalEntity]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT canonical_id, entity_type, display_name, aliases,"
                " normalized_key, attributes FROM entity_canonical"
            ).fetchall()
        return [
            CanonicalEntity(
                canonical_id=str(r[0]),
                entity_type=r[1],
                display_name=r[2],
                aliases=set(r[3] or ()),
                normalized_key=r[4],
                attributes=r[5] or {},
            )
            for r in rows
        ]

    # ------------------------------------------------------------- review
    def save_review_item(self, item: ReviewItem, *, doc_uuid: str) -> None:
        """Upsert the open review item for a document.

        A partial unique index keeps at most one unresolved item per
        document, so re-ingesting refreshes the reviewer's queue rather than
        stacking duplicates of the same problem.
        """
        with self._connect() as conn:
            conn.execute(
                "INSERT INTO review_items (doc_id, state, triggers, matter_active, notes)"
                " VALUES (%s,%s,%s,%s,%s)"
                " ON CONFLICT (doc_id) WHERE resolved_at IS NULL DO UPDATE SET"
                "   state = EXCLUDED.state,"
                "   triggers = EXCLUDED.triggers,"
                "   matter_active = EXCLUDED.matter_active,"
                "   notes = EXCLUDED.notes",
                (
                    doc_uuid,
                    item.state.value,
                    [t.value for t in item.triggers],
                    item.matter_is_active,
                    item.notes or None,
                ),
            )
            conn.commit()

    def load_review_items(self, *, open_only: bool = True) -> list[tuple[str, ReviewItem]]:
        sql = (
            "SELECT doc_id, state, triggers, matter_active, notes, resolved_by"
            "  FROM review_items"
        )
        if open_only:
            sql += " WHERE resolved_at IS NULL"
        with self._connect() as conn:
            rows = conn.execute(sql).fetchall()
        out: list[tuple[str, ReviewItem]] = []
        for doc_id, state, triggers, matter_active, notes, resolved_by in rows:
            out.append(
                (
                    str(doc_id),
                    ReviewItem(
                        doc_id=str(doc_id),
                        state=ReviewState(state),
                        triggers=tuple(_safe_triggers(triggers)),
                        matter_is_active=bool(matter_active),
                        notes=notes or "",
                        resolved_by=resolved_by,
                    ),
                )
            )
        return out

    def save_correction(self, correction: Correction, *, doc_uuid: str) -> None:
        """Append a correction.

        The two-person CHECK and the append-only trigger live in the
        database, so an invalid correction is rejected here even if the
        application layer were bypassed entirely.
        """
        with self._connect() as conn:
            conn.execute(
                "INSERT INTO corrections (correction_id, doc_id, field_path,"
                " old_value, new_value, reason, corrected_by, approved_by,"
                " affects_high_severity, supersedes)"
                " VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)",
                (
                    correction.correction_id,
                    doc_uuid,
                    correction.field_path,
                    json.dumps(_jsonable(correction.old_value)),
                    json.dumps(_jsonable(correction.new_value)),
                    correction.reason,
                    correction.corrected_by,
                    correction.approved_by,
                    correction.affects_high_severity,
                    correction.supersedes,
                ),
            )
            conn.commit()

    def corrections_for(self, doc_uuid: str) -> list[dict[str, Any]]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT correction_id, field_path, old_value, new_value, reason,"
                " corrected_by, approved_by, affects_high_severity, created_at"
                "  FROM corrections WHERE doc_id = %s ORDER BY created_at",
                (doc_uuid,),
            ).fetchall()
        return [
            {
                "correction_id": str(r[0]),
                "field_path": r[1],
                "old_value": r[2],
                "new_value": r[3],
                "reason": r[4],
                "corrected_by": r[5],
                "approved_by": r[6],
                "affects_high_severity": r[7],
                "created_at": r[8].isoformat() if r[8] else None,
            }
            for r in rows
        ]

    def doc_uuid_for_sha(self, sha256: str) -> str | None:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT doc_id FROM documents WHERE sha256 = %s",
                (bytes.fromhex(sha256),),
            ).fetchone()
        return str(row[0]) if row else None

    def apply_migrations(self, migration_dir) -> list[str]:
        from pathlib import Path

        applied: list[str] = []
        with self._connect() as conn:
            for path in sorted(Path(migration_dir).glob("*.sql")):
                conn.execute(path.read_text())
                applied.append(path.name)
            conn.commit()
        return applied


def _jsonable(value: Any) -> Any:
    """Coerce dataclass/enum leftovers into something json.dumps accepts."""
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, dict):
        return {str(k): _jsonable(v) for k, v in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [_jsonable(v) for v in value]
    return str(value)


def _safe_triggers(values: Any) -> list[ReviewTrigger]:
    """Ignore trigger names this build no longer knows about.

    Trigger vocabulary evolves; a row written by a newer build must not stop
    an older one from reading its own review queue.
    """
    out: list[ReviewTrigger] = []
    for value in values or ():
        try:
            out.append(ReviewTrigger(value))
        except ValueError:
            continue
    return out
