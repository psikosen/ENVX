"""ENVX application wiring.

Composes the layers into the two operations the system actually exposes:

    ingest(document)  intake -> classify -> parse -> regions -> KIE ->
                      validate -> markers -> chunk -> enrich -> embed ->
                      index -> graph -> review triage

    query(question)   plan -> hybrid retrieve -> fuse -> rerank -> evidence

Everything is injectable. With no configuration this runs fully offline on
stub backends, which is what makes the pipeline demonstrable and debuggable
without a GPU. Pointing it at real infrastructure is a config change.

The LLM is deliberately absent from the query path. It plans and it reads
evidence; it never fetches (§12).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .chunking import Chunk, StructuralChunker
from .classifier import Classification, DocTypeClassifier
from .config import EnvxConfig, load_config
from .db import DocumentRecord, PostgresRepository
from .dsl import ExecutionResult, PlanExecutor, RetrievalPlan
from .embedding import EmbeddingBackend, HashingEmbedding, HTTPEmbedding
from .enrichment import ContextualEnricher
from .entities import EntityResolver
from .glm_ocr import GLMOCRClient
from .graph import KnowledgeGraph, build_graph_from_kie
from .kie import KIEValidator
from .lexicon import Lexicon, load_lexicon
from .liteparse import LiteParseResult, StubLiteParse
from .markers import MarkerEngine
from .models import ExtractedField, Marker, Region
from .queue import JobType, SQLiteJobQueue
from .retrieval import (
    BM25Index,
    HashCrossEncoderReranker,
    HTTPReranker,
    HybridRetriever,
    IndexedChunk,
    Reranker,
    VectorIndex,
)
from .review import ReviewQueue, ReviewState, evaluate_triggers
from .schemas import DocSchema, SchemaLoader, SchemaNotFound
from .visual import StubVisualBackend, VisualRetriever
from .wet_storage import BlobRef, WetStore, doc_id_for


@dataclass
class IngestResult:
    doc_id: str
    blob_sha256: str
    classification: Classification
    schema_id: str | None
    kie_run_id: str | None
    kie_payload: dict[str, Any] = field(default_factory=dict)
    validation_report: dict[str, Any] = field(default_factory=dict)
    markers: list[Marker] = field(default_factory=list)
    regions: list[Region] = field(default_factory=list)
    chunks: list[Chunk] = field(default_factory=list)
    rescued_pages: list[int] = field(default_factory=list)
    review_state: ReviewState = ReviewState.TRUSTED
    needs_review: bool = False

    def summary(self) -> dict[str, Any]:
        return {
            "doc_id": self.doc_id,
            "sha256": self.blob_sha256[:16],
            "doc_type": self.classification.doc_type,
            "doc_type_confidence": round(self.classification.confidence, 3),
            "schema": self.schema_id,
            "regions": len(self.regions),
            "chunks": len(self.chunks),
            "markers": sorted({m.code for m in self.markers}),
            "rescued_pages": self.rescued_pages,
            "review_state": self.review_state.value,
        }


def _build_embedder(config: EnvxConfig) -> EmbeddingBackend:
    if config.embedding_url:
        return HTTPEmbedding(
            base_url=config.embedding_url,
            model=config.embedding_model,
            dim=config.embedding_dim,
            api_key=config.embedding_api_key or None,
        )
    return HashingEmbedding(dim=512)


def _build_reranker(config: EnvxConfig) -> Reranker:
    if config.rerank_url:
        return HTTPReranker(
            base_url=config.rerank_url,
            model=config.rerank_model,
            api_key=config.rerank_api_key or None,
        )
    return HashCrossEncoderReranker()


class EnvxApp:
    def __init__(
        self,
        *,
        config: EnvxConfig | None = None,
        embedder: EmbeddingBackend | None = None,
        reranker: Reranker | None = None,
        lexicon: Lexicon | None = None,
        wet_store: WetStore | None = None,
        glm: GLMOCRClient | None = None,
    ) -> None:
        self.config = config or load_config()

        self.wet_store = wet_store or WetStore(
            base=self.config.wet_root,
            attestation_key_path=self.config.attestation_key_path,
        )
        self.glm = glm or GLMOCRClient(config=self.config)
        self.classifier = DocTypeClassifier()
        self.schema_loader = SchemaLoader(config=self.config)
        self.validator = KIEValidator(config=self.config)
        self.chunker = StructuralChunker()
        self.enricher = ContextualEnricher()
        self.liteparse = StubLiteParse()

        self.embedder = embedder or _build_embedder(self.config)
        self.bm25 = BM25Index()
        self.vectors = VectorIndex(model_id=self.embedder.model_id, dim=self.embedder.dim)
        self.retriever = HybridRetriever(
            bm25=self.bm25, vector=self.vectors, embedder=self.embedder
        )
        self.reranker = reranker or _build_reranker(self.config)

        self.resolver = EntityResolver()
        self.graph = KnowledgeGraph()
        self.visual_backend = StubVisualBackend()
        self.visual = VisualRetriever(self.visual_backend)

        self.review = ReviewQueue()
        self.jobs = SQLiteJobQueue()
        self.lexicon = lexicon if lexicon is not None else load_lexicon(config=self.config)

        # Persistence is optional. Without it the app is a single-process
        # demo; with it, ingest and query can run as separate invocations.
        self._last_fields: list[ExtractedField] = []
        self.repo: PostgresRepository | None = None
        if self.config.database_url and PostgresRepository.available():
            self.repo = PostgresRepository(self.config.database_url)
            self._rehydrate()

        # Built last: _rehydrate() may replace self.graph wholesale, and the
        # executor must hold the restored instance, not the empty one.
        self.executor = PlanExecutor(
            retriever=self.retriever,
            reranker=self.reranker,
            graph=self.graph,
            visual=self.visual,
        )

    # ------------------------------------------------------------ ingest
    def ingest(
        self,
        *,
        content: bytes,
        filename: str,
        client_id: str,
        matter_id: str | None = None,
        matter_is_active: bool = False,
        extension: str = "pdf",
        page_image_paths: list[Path] | None = None,
    ) -> IngestResult:
        # 1. Intake — content-addressed, WORM, audited.
        blob = self.wet_store.ingest_bytes(
            content,
            extension,
            {"client_id": client_id, "matter_id": matter_id, "filename": filename},
        )
        doc_id = doc_id_for(blob.sha256)
        self.jobs.enqueue(
            JobType.INTAKE, {"doc_id": doc_id}, idempotency_key=blob.sha256
        )

        # 2. Tier A parse.
        text = content.decode("utf-8", errors="replace")
        parsed = self.liteparse.parse_text(text)

        # 3. Classify — needed before a KIE schema can be selected.
        first_page = parsed.pages[0].text if parsed.pages else ""
        classification = self.classifier.classify(
            filename=filename, first_page_text=first_page
        )

        # 4a. Region map on every page.
        images = page_image_paths or []
        regions: list[Region] = []
        for page in parsed.pages:
            image = images[page.page_number - 1] if page.page_number <= len(images) else Path(
                f"{doc_id}-p{page.page_number}.png"
            )
            regions.extend(self.glm.layout_regions(image, page_number=page.page_number).regions)

        # 4c. Tier B text rescue where Tier A signals say the page wasn't read.
        rescued = self._rescue(parsed, images, doc_id)

        # 4b. KIE against the doc-type schema.
        schema = self._resolve_schema(classification.doc_type)
        kie_payload: dict[str, Any] = {}
        validation_report: dict[str, Any] = {}
        markers: list[Marker] = []
        kie_run_id: str | None = None

        if schema is not None:
            kie_payload, validation_report, kie_run_id, markers = self._run_kie(
                blob=blob, schema=schema, source_text=parsed.full_text, images=images
            )

        # 5. Structural chunking off the region map.
        chunks = self.chunker.chunk(doc_id=doc_id, liteparse=parsed, regions=regions)

        # 6-8. Enrich, embed, index.
        indexed = self._index(
            chunks=chunks,
            kie_payload=kie_payload,
            doc_id=doc_id,
            client_id=client_id,
            matter_id=matter_id,
            doc_type=classification.doc_type,
            jurisdiction=kie_payload.get("jurisdiction"),
            markers=markers,
        )

        # 9. Graph over canonicalized entities.
        if kie_payload:
            build_graph_from_kie(
                doc_id=doc_id,
                kie_payload=kie_payload,
                resolver=self.resolver,
                graph=self.graph,
            )

        # 10. Review triage.
        triggers = evaluate_triggers(
            validation_report=validation_report,
            markers=[(m.code, m.confidence) for m in markers],
            parse_score=min((p.roundtrip_score for p in parsed.pages), default=1.0),
        )
        state = ReviewState.TRUSTED
        if triggers or schema is None:
            if schema is None:
                triggers = list(triggers)
            item = self.review.enqueue(
                doc_id=doc_id,
                triggers=triggers,
                matter_is_active=matter_is_active,
                notes="" if schema else f"no schema for doc_type {classification.doc_type!r}",
            )
            state = item.state if triggers else ReviewState.NEEDS_HUMAN_REVIEW

        result = IngestResult(
            doc_id=doc_id,
            blob_sha256=blob.sha256,
            classification=classification,
            schema_id=schema.schema_id if schema else None,
            kie_run_id=kie_run_id,
            kie_payload=kie_payload,
            validation_report=validation_report,
            markers=markers,
            regions=regions,
            chunks=chunks,
            rescued_pages=rescued,
            review_state=state,
            needs_review=state is not ReviewState.TRUSTED,
        )

        self._persist(
            result=result,
            indexed=indexed,
            schema=schema,
            page_count=len(parsed.pages),
            filename=filename,
            client_id=client_id,
            matter_id=matter_id,
        )
        return result

    def _rescue(
        self,
        parsed: LiteParseResult,
        images: list[Path],
        doc_id: str,
    ) -> list[int]:
        rescued: list[int] = []
        for page_number in parsed.rescue_pages:
            image = (
                images[page_number - 1]
                if page_number <= len(images)
                else Path(f"{doc_id}-p{page_number}.png")
            )
            try:
                self.glm.parse_text(image)
                rescued.append(page_number)
            except Exception:
                # Rescue is best-effort; Tier A output remains usable and the
                # page's low quality score still drives review triage.
                continue
        return rescued

    def _run_kie(
        self,
        *,
        blob: BlobRef,
        schema: DocSchema,
        source_text: str,
        images: list[Path],
    ) -> tuple[dict[str, Any], dict[str, Any], str | None, list[Marker]]:
        response = self.glm.extract_kie(
            image_paths=images or [Path("page1.png")],
            json_schema=schema.json_schema,
            doc_type=schema.schema_id,
        )
        if response.parsed is None:
            # Fallback cascade (§2.5.4): one retry, then degrade.
            response = self.glm.extract_kie(
                image_paths=images or [Path("page1.png")],
                json_schema=schema.json_schema,
                doc_type=schema.schema_id,
            )
        if response.parsed is None:
            report = {
                "schema_id": schema.schema_id,
                "schema_version": schema.version,
                "needs_review": True,
                "review_reasons": ["malformed_json_after_retry"],
                "parse_error": response.parse_error,
            }
            run_id = self.wet_store.record_kie_run(
                ref=blob,
                schema=schema.json_schema,
                prompt=f"doc_type={schema.schema_id}",
                output={"raw": response.raw_text},
                validation_report=report,
            )
            return {}, report, run_id, []

        outcome = self.validator.validate(
            raw_json=response.parsed, schema=schema, source_text=source_text
        )
        # Retained for persistence: extracted_fields rows carry the grounding
        # verdict per field, which is what a reviewer needs to adjudicate.
        self._last_fields = list(outcome.result.fields)
        report = outcome.as_report()
        markers = MarkerEngine(schema.marker_rules).evaluate(response.parsed)
        run_id = self.wet_store.record_kie_run(
            ref=blob,
            schema=schema.json_schema,
            prompt=f"doc_type={schema.schema_id}",
            output=response.parsed,
            validation_report=report,
        )
        if markers:
            self.wet_store.append_markers(
                blob,
                [
                    {
                        "code": m.code,
                        "confidence": m.confidence,
                        "source_field_path": m.source_field_path,
                        "extracted_by": m.extracted_by,
                    }
                    for m in markers
                ],
            )
        return response.parsed, report, run_id, markers

    def _index(
        self,
        *,
        chunks: list[Chunk],
        kie_payload: dict[str, Any],
        doc_id: str,
        client_id: str,
        matter_id: str | None,
        doc_type: str,
        jurisdiction: str | None,
        markers: list[Marker],
    ) -> list[IndexedChunk]:
        if not chunks:
            return []
        enrichments = {
            e.chunk_id: e.text_contextual
            for e in self.enricher.enrich(chunks, kie_payload=kie_payload)
        }
        # Document-level markers apply to every chunk of the document (§2.5.3).
        marker_codes = tuple(sorted({m.code for m in markers}))
        confidence = min((m.confidence for m in markers), default=1.0) if markers else 1.0

        indexed = [
            IndexedChunk(
                chunk_id=c.chunk_id,
                doc_id=doc_id,
                text_raw=c.text,
                text_contextual=enrichments.get(c.chunk_id, c.text),
                client_id=client_id,
                matter_id=matter_id,
                page_number=c.page_number,
                doc_type=doc_type,
                jurisdiction=jurisdiction,
                region_id=c.region_id,
                region_type=c.region_type,
                marker_array=marker_codes,
                confidence=confidence,
            )
            for c in chunks
        ]
        vectors = self.embedder.embed([c.text_contextual for c in indexed])
        for chunk, vector in zip(indexed, vectors):
            self.bm25.add(chunk)
            self.vectors.add(chunk, vector)

        # Register pages carrying visual evidence for the visual path.
        for chunk in chunks:
            if chunk.region_type in {"signature", "stamp", "figure", "form_field"}:
                self.visual_backend.index_page(
                    doc_id=doc_id,
                    page_number=chunk.page_number,
                    doc_type=doc_type,
                    visual_terms=[chunk.region_type, "signature", "seal"],
                )
        return indexed

    def _resolve_schema(self, doc_type: str) -> DocSchema | None:
        for candidate in (f"{doc_type}_ct", doc_type):
            try:
                return self.schema_loader.load_latest(candidate)
            except SchemaNotFound:
                continue
        return None

    def _rehydrate(self) -> int:
        """Rebuild the retrieval indexes from Postgres on startup.

        Embeddings are recomputed rather than read back: the stored vectors
        may have been produced by a different model version, and mixing model
        versions in one index is silent recall loss (§4.3).
        """
        if self.repo is None:
            return 0

        # Graph, canonical entities, and the review queue restore as stored
        # state; the retrieval index is rebuilt, since stored vectors may
        # come from a superseded embedding model (§4.3).
        self.graph = self.repo.load_graph()
        for entity in self.repo.load_canonical_entities():
            self.resolver.adopt(entity)
        for doc_uuid, item in self.repo.load_review_items():
            self.review.adopt(doc_uuid, item)

        rows = self.repo.load_index_rows()
        if not rows:
            return 0
        vectors = self.embedder.embed([r.text_contextual for r in rows])
        for row, vector in zip(rows, vectors):
            self.bm25.add(row)
            self.vectors.add(row, vector)
        return len(rows)

    def _persist(
        self,
        *,
        result: IngestResult,
        indexed: list[IndexedChunk],
        schema: DocSchema | None,
        page_count: int,
        filename: str,
        client_id: str,
        matter_id: str | None,
    ) -> None:
        if self.repo is None:
            return
        if schema is not None:
            self.repo.register_schema(
                schema_id=schema.schema_id,
                version=schema.version,
                json_schema=schema.json_schema,
                marker_rules=schema.marker_rules,
                content_hash=schema.content_hash,
            )
        fields = [
            {
                "field_path": f.field_path,
                "value": f.value,
                "page_cited": f.page_cited,
                "grounding_verified": f.grounding_verified,
                "verification_score": f.verification_score,
                "grounding_status": f.grounding_status.value,
            }
            for f in self._last_fields
        ]
        self.repo.save_document(
            document=DocumentRecord(
                sha256=result.blob_sha256,
                client_id=client_id,
                matter_id=matter_id,
                doc_type=result.classification.doc_type,
                doc_type_confidence=result.classification.confidence,
                page_count=page_count,
                original_filename=filename,
            ),
            chunks=result.chunks,
            indexed=indexed,
            regions=result.regions,
            markers=result.markers,
            extracted_fields=fields,
            schema_ref=(schema.schema_id, schema.version) if schema else None,
            kie_run_id=result.kie_run_id,
        )
        self.repo.save_graph(self.graph, entities=self.resolver.all())
        item = self.review.get(result.doc_id)
        if item is not None:
            self.repo.save_review_item(item, doc_uuid=result.doc_id)

    # ------------------------------------------------------------- query
    def query(self, plan: RetrievalPlan) -> ExecutionResult:
        """Execute a compiled retrieval plan, applying lexicon expansion."""
        bm25_path = plan.path("bm25")
        if bm25_path is not None and not bm25_path.query_expansions:
            expansions = self.lexicon.expand_query(bm25_path.query)
            if expansions:
                paths = tuple(
                    p if p.kind != "bm25" else type(p)(
                        kind=p.kind,
                        query=p.query,
                        weight=p.weight,
                        query_expansions=tuple(expansions),
                        model=p.model,
                        enabled=p.enabled,
                    )
                    for p in plan.paths
                )
                boosts = dict(plan.soft_boost_markers)
                for code, bump in self.lexicon.boosts_for(bm25_path.query).items():
                    boosts.setdefault(code, bump)
                plan = RetrievalPlan(
                    scope=plan.scope,
                    structured_filter=plan.structured_filter,
                    paths=paths,
                    graph=plan.graph,
                    fusion=plan.fusion,
                    top_k=plan.top_k,
                    rerank=plan.rerank,
                    response=plan.response,
                    soft_boost_markers=boosts,
                )
        return self.executor.execute(plan)

    # -------------------------------------------------------------- misc
    def stats(self) -> dict[str, Any]:
        return {
            "indexed_chunks": len(self.bm25),
            "vectors": len(self.vectors),
            "graph_nodes": len(self.graph),
            "graph_edges": len(self.graph.edges),
            "canonical_entities": len(self.resolver.all()),
            "pending_review": len(self.review.pending()),
            "jobs": self.jobs.counts(),
            "embedding_model": self.embedder.model_id,
            "offline_mode": self.config.offline,
        }
