"""GLM-OCR HTTP client.

Talks to a vLLM-hosted GLM-OCR endpoint (OpenAI-compatible chat completions
with image content parts). Three operations:

    - ``extract_kie``      schema-aware structured extraction, one call per doc
    - ``parse_text``       document-parsing mode, one call per page
    - ``layout_regions``   PP-DocLayoutV3 bbox inference, one call per page

When ``ENVX_GLM_OCR_STUB=1`` (or no URL is configured), a deterministic stub
is used so the rest of the preprocessing layer is runnable without a GPU.
Tests and CI rely on this path.
"""

from __future__ import annotations

import base64
import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Sequence

import httpx

from ..config import EnvxConfig, load_config
from ..models import Region, RegionType
from .prompts import PARSE_PROMPT, build_kie_prompt


class GLMOCRError(RuntimeError):
    pass


@dataclass(frozen=True)
class KIEResponse:
    raw_text: str
    parsed: dict[str, Any] | None
    parse_error: str | None


@dataclass(frozen=True)
class ParseResponse:
    markdown: str


@dataclass(frozen=True)
class LayoutResponse:
    regions: list[Region]


def _b64_image(image_path: Path) -> str:
    return base64.b64encode(image_path.read_bytes()).decode("ascii")


def _image_content(image_path: Path) -> dict[str, Any]:
    suffix = image_path.suffix.lower().lstrip(".") or "png"
    return {
        "type": "image_url",
        "image_url": {"url": f"data:image/{suffix};base64,{_b64_image(image_path)}"},
    }


_JSON_FENCE_RE = re.compile(r"```(?:json)?\s*(.*?)```", re.DOTALL)


def _best_effort_json(text: str) -> tuple[dict[str, Any] | None, str | None]:
    candidate = text.strip()
    m = _JSON_FENCE_RE.search(candidate)
    if m:
        candidate = m.group(1).strip()
    try:
        obj = json.loads(candidate)
        if not isinstance(obj, dict):
            return None, "top-level JSON is not an object"
        return obj, None
    except json.JSONDecodeError as exc:
        return None, f"invalid JSON: {exc.msg} at pos {exc.pos}"


class GLMOCRClient:
    def __init__(self, config: EnvxConfig | None = None) -> None:
        self.config = config or load_config()
        self._stub = self.config.glm_ocr_stub or not self.config.glm_ocr_url
        self._http: httpx.Client | None = None

    def close(self) -> None:
        if self._http is not None:
            self._http.close()
            self._http = None

    def __enter__(self) -> "GLMOCRClient":
        return self

    def __exit__(self, *_: Any) -> None:
        self.close()

    @property
    def is_stub(self) -> bool:
        return self._stub

    def _client(self) -> httpx.Client:
        if self._http is None:
            self._http = httpx.Client(
                base_url=self.config.glm_ocr_url.rstrip("/"),
                timeout=self.config.glm_ocr_timeout_s,
            )
        return self._http

    def extract_kie(
        self,
        image_paths: Sequence[Path],
        json_schema: dict[str, Any],
        doc_type: str,
    ) -> KIEResponse:
        prompt = build_kie_prompt(json_schema, doc_type)
        if self._stub:
            raw = _stub_kie_payload(doc_type)
            parsed, err = _best_effort_json(raw)
            return KIEResponse(raw_text=raw, parsed=parsed, parse_error=err)
        content: list[dict[str, Any]] = [{"type": "text", "text": prompt}]
        for p in image_paths:
            content.append(_image_content(p))
        body = {
            "model": self.config.glm_ocr_model,
            "messages": [{"role": "user", "content": content}],
            "temperature": 0.0,
        }
        resp = self._client().post("/v1/chat/completions", json=body)
        if resp.status_code >= 400:
            raise GLMOCRError(f"GLM-OCR KIE failed: {resp.status_code} {resp.text[:256]}")
        raw = resp.json()["choices"][0]["message"]["content"]
        parsed, err = _best_effort_json(raw)
        return KIEResponse(raw_text=raw, parsed=parsed, parse_error=err)

    def parse_text(self, image_path: Path) -> ParseResponse:
        if self._stub:
            return ParseResponse(markdown=f"# stub parse of {image_path.name}\n")
        body = {
            "model": self.config.glm_ocr_model,
            "messages": [
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": PARSE_PROMPT},
                        _image_content(image_path),
                    ],
                }
            ],
            "temperature": 0.0,
        }
        resp = self._client().post("/v1/chat/completions", json=body)
        if resp.status_code >= 400:
            raise GLMOCRError(f"GLM-OCR parse failed: {resp.status_code} {resp.text[:256]}")
        return ParseResponse(markdown=resp.json()["choices"][0]["message"]["content"])

    def layout_regions(self, image_path: Path, page_number: int) -> LayoutResponse:
        if self._stub:
            return LayoutResponse(
                regions=[
                    Region(
                        page_number=page_number,
                        bbox=(0, 0, 100, 100),
                        region_type=RegionType.PARAGRAPH,
                        label_confidence=0.5,
                    )
                ]
            )
        # The layout endpoint is a thin wrapper over PP-DocLayoutV3 hosted alongside
        # the vLLM server; it returns JSON with labeled boxes.
        resp = self._client().post(
            "/v1/layout",
            json={"image_b64": _b64_image(image_path), "page_number": page_number},
        )
        if resp.status_code >= 400:
            raise GLMOCRError(f"GLM-OCR layout failed: {resp.status_code} {resp.text[:256]}")
        payload = resp.json()
        regions: list[Region] = []
        for r in payload.get("regions", []):
            try:
                rt = RegionType(r["region_type"])
            except (KeyError, ValueError):
                continue
            bbox = r.get("bbox") or []
            if len(bbox) != 4:
                continue
            regions.append(
                Region(
                    page_number=page_number,
                    bbox=(int(bbox[0]), int(bbox[1]), int(bbox[2]), int(bbox[3])),
                    region_type=rt,
                    label_confidence=float(r.get("confidence", 0.0)),
                )
            )
        return LayoutResponse(regions=regions)


# Stub payloads per doc_type. Just enough structure for the validator
# and grounding stages to exercise real code paths in tests.
_STUB_KIE = {
    "property_disclosure_ct": {
        "doc_type": "property_disclosure",
        "jurisdiction": "CT",
        "property": {
            "address_street": "123 Elm St",
            "address_city": "Hartford",
            "address_zip": "06103",
        },
        "seller": {"name": "Jane Roe"},
        "buyer": {"name": "John Doe"},
        "hazards_disclosed": [
            {"type": "asbestos", "severity": "known", "page_cited": 3}
        ],
    },
    "property_disclosure": {
        "doc_type": "property_disclosure",
        "jurisdiction": "CT",
        "property": {
            "address_street": "123 Elm St",
            "address_city": "Hartford",
            "address_zip": "06103",
        },
        "seller": {"name": "Jane Roe"},
        "buyer": {"name": "John Doe"},
        "hazards_disclosed": [
            {"type": "asbestos", "severity": "known", "page_cited": 3}
        ],
    },
    "environmental_report": {
        "doc_type": "environmental_report",
        "report_type": "phase_i",
        "property": {"address": "123 Elm St"},
        "conclusions": {"has_recs": False, "requires_phase_ii": False},
    },
    "inspection_report": {
        "doc_type": "inspection_report",
        "inspector": {"name": "ACME Inspections"},
        "inspection_date": "2025-01-15",
        "property_address": "123 Elm St",
        "systems_evaluated": [
            {"system": "roof", "condition_rating": "satisfactory"}
        ],
    },
    "insurance_claim": {
        "doc_type": "insurance_claim",
        "claim_number": "CLM-1",
        "policy_number": "POL-1",
        "insured": {"name": "ACME LLC"},
        "insurer": {"name": "Example Mutual"},
        "date_of_loss": "2025-01-01",
    },
    "medical_record": {
        "doc_type": "medical_record",
        "date_of_service": "2025-01-01",
    },
}


def _stub_kie_payload(doc_type: str) -> str:
    return json.dumps(_STUB_KIE.get(doc_type, {"doc_type": doc_type}))
