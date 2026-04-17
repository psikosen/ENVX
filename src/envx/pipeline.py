"""End-to-end preprocessing pipeline (§2.5.2).

    intake → classify → [LiteParse || GLM-OCR region map || GLM-OCR KIE] →
    validate → marker rules → wet-storage artifacts.

LiteParse is stubbed here; it lands in a subsequent branch. The shape of the
call site is the right one though — structural chunking and Tier B rescue
plug into the same ``ParseContext``.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .classifier import Classification, DocTypeClassifier
from .config import EnvxConfig, load_config
from .glm_ocr import GLMOCRClient, KIEResponse
from .kie import KIEValidator
from .markers import MarkerEngine
from .models import Marker, Region
from .schemas import DocSchema, SchemaLoader, SchemaNotFound
from .wet_storage import BlobRef, WetStore


@dataclass
class ParseContext:
    """Per-document state that flows through the preprocessing stages."""

    blob: BlobRef
    doc_type: Classification
    schema: DocSchema | None
    source_text: str
    page_image_paths: list[Path] = field(default_factory=list)
    regions: list[Region] = field(default_factory=list)


@dataclass
class PreprocessResult:
    blob_sha256: str
    doc_type: Classification
    kie_run_id: str | None
    kie_response: KIEResponse | None
    validation_report: dict[str, Any] | None
    markers: list[Marker]
    regions: list[Region]
    needs_review: bool


class PreprocessPipeline:
    """Glue layer. Each collaborator is injectable for testing."""

    def __init__(
        self,
        *,
        config: EnvxConfig | None = None,
        classifier: DocTypeClassifier | None = None,
        glm: GLMOCRClient | None = None,
        validator: KIEValidator | None = None,
        schema_loader: SchemaLoader | None = None,
        wet_store: WetStore | None = None,
    ) -> None:
        self.config = config or load_config()
        self.classifier = classifier or DocTypeClassifier()
        self.glm = glm or GLMOCRClient(config=self.config)
        self.validator = validator or KIEValidator(config=self.config)
        self.schema_loader = schema_loader or SchemaLoader(config=self.config)
        self.wet_store = wet_store or WetStore(
            base=self.config.wet_root,
            attestation_key_path=self.config.attestation_key_path,
        )

    def run(
        self,
        *,
        blob: BlobRef,
        filename: str,
        first_page_text: str,
        source_text: str,
        page_image_paths: list[Path],
    ) -> PreprocessResult:
        classification = self.classifier.classify(
            filename=filename, first_page_text=first_page_text
        )

        schema = self._resolve_schema(classification.doc_type)

        regions: list[Region] = []
        for i, img in enumerate(page_image_paths, start=1):
            regions.extend(self.glm.layout_regions(img, page_number=i).regions)

        if schema is None:
            return PreprocessResult(
                blob_sha256=blob.sha256,
                doc_type=classification,
                kie_run_id=None,
                kie_response=None,
                validation_report=None,
                markers=[],
                regions=regions,
                needs_review=True,
            )

        kie = self.glm.extract_kie(
            image_paths=page_image_paths,
            json_schema=schema.json_schema,
            doc_type=schema.schema_id,
        )

        if kie.parsed is None:
            # Fallback cascade: one retry, then degrade. Retry is a second
            # attempt from the live client; the stub just returns the same
            # payload. A real retry would use higher temperature or a repair
            # prompt — kept out until we wire live inference.
            kie = self.glm.extract_kie(
                image_paths=page_image_paths,
                json_schema=schema.json_schema,
                doc_type=schema.schema_id,
            )

        validation_report: dict[str, Any]
        markers: list[Marker]
        needs_review: bool
        if kie.parsed is None:
            validation_report = {
                "schema_id": schema.schema_id,
                "schema_version": schema.version,
                "schema_content_hash": schema.content_hash,
                "needs_review": True,
                "review_reasons": ["malformed_json_after_retry"],
                "parse_error": kie.parse_error,
            }
            markers = []
            needs_review = True
            run_id = self.wet_store.record_kie_run(
                ref=blob,
                schema=schema.json_schema,
                prompt=f"doc_type={schema.schema_id}",
                output={"raw": kie.raw_text},
                validation_report=validation_report,
            )
            return PreprocessResult(
                blob_sha256=blob.sha256,
                doc_type=classification,
                kie_run_id=run_id,
                kie_response=kie,
                validation_report=validation_report,
                markers=markers,
                regions=regions,
                needs_review=needs_review,
            )

        outcome = self.validator.validate(
            raw_json=kie.parsed,
            schema=schema,
            source_text=source_text,
        )
        validation_report = outcome.as_report()
        markers = MarkerEngine(schema.marker_rules).evaluate(kie.parsed)
        needs_review = outcome.result.needs_review

        run_id = self.wet_store.record_kie_run(
            ref=blob,
            schema=schema.json_schema,
            prompt=f"doc_type={schema.schema_id}",
            output=kie.parsed,
            validation_report=validation_report,
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
                        "evidence": m.evidence,
                    }
                    for m in markers
                ],
            )
        return PreprocessResult(
            blob_sha256=blob.sha256,
            doc_type=classification,
            kie_run_id=run_id,
            kie_response=kie,
            validation_report=validation_report,
            markers=markers,
            regions=regions,
            needs_review=needs_review,
        )

    def _resolve_schema(self, doc_type: str) -> DocSchema | None:
        # Our 5 starter schemas are keyed by exactly ``schema_id``, with the
        # CT property disclosure carrying a jurisdiction suffix. Handle both.
        candidates = [doc_type]
        if doc_type == "property_disclosure":
            candidates.insert(0, "property_disclosure_ct")
        for sid in candidates:
            try:
                return self.schema_loader.load_latest(sid)
            except SchemaNotFound:
                continue
        return None
