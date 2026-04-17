"""Prompt templates for GLM-OCR.

Two modes we care about:
    - ``extract_kie``: schema-aware structured extraction, returns JSON that
      validates against the supplied JSON Schema.
    - ``parse_text``: document-parsing mode (markdown + structured regions)
      for low-confidence text rescue.

Layout-region detection runs via PP-DocLayoutV3 and is invoked through a
separate endpoint — no prompt needed.
"""

from __future__ import annotations

import json
from typing import Any

KIE_SYSTEM_PROMPT = (
    "You are a document extraction engine. You will be shown page images of a "
    "legal or real-estate document. Extract facts that are present in the document "
    "and return a single JSON object conforming exactly to the supplied JSON Schema. "
    "Rules: (1) Do not invent facts. If a field is not present, omit it or use an "
    "empty string/array as the schema allows. (2) Every fact you extract must be "
    "citable to a page — populate the relevant page_cited fields. (3) Preserve "
    "verbatim quotes when the schema asks for them. (4) Output only JSON — no prose, "
    "no markdown fences."
)


def build_kie_prompt(json_schema: dict[str, Any], doc_type: str) -> str:
    schema_str = json.dumps(json_schema, indent=2, sort_keys=True)
    return (
        f"{KIE_SYSTEM_PROMPT}\n\n"
        f"Document type: {doc_type}\n"
        f"JSON Schema:\n{schema_str}\n\n"
        "Return only the JSON object."
    )


PARSE_PROMPT = (
    "Recognize every textual element in this page. Return markdown that preserves "
    "layout: headings, lists, tables (GitHub-flavored), and inline formulas in LaTeX. "
    "Do not summarize or rewrite. Do not include commentary."
)
