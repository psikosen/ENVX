# ENVX v2.1 — GLM-OCR preprocessing layer

This branch (`claude/glm-ocr-preprocessing-7iCWt`) lands §2.5 + §2.6 of the
v2.1 architecture: the GLM-OCR preprocessing layer that sits between intake
and block-level indexing. Other layers (LiteParse, hybrid retrieval,
reranker, LightRAG, ColPali, CR enrichment) are explicitly out of scope for
this branch and will arrive in follow-ups.

## What's here

```
src/envx/
├── __init__.py
├── config.py              Environment-driven runtime config.
├── models.py              Region, ExtractedField, KIEResult, Marker.
├── attestation.py         Ed25519 signing of parse/KIE run manifests.
├── wet_storage.py         Content-addressed WORM blob store (§4.1).
├── pipeline.py            End-to-end orchestration of §2.5.2.
├── db/migrations/
│   ├── 001_core.sql            documents, pages, blocks.
│   ├── 002_regions_schemas_extracted_fields.sql
│   └── 003_markers_entities.sql
├── schemas/loader.py      Versioned YAML schema loader + content-hash.
├── glm_ocr/client.py      vLLM HTTP client + deterministic stub mode.
├── kie/
│   ├── validator.py       Draft-2020-12 validation + grounding + review flags.
│   └── grounding.py       Fuzzy field-presence check vs source text.
├── classifier/doc_type.py Rule-based + LLM fallback doc-type classifier.
└── markers/rules.py       Declarative marker-rule engine (JSONPath-ish).

schemas/
├── property_disclosure_ct/v1.yml
├── environmental_report/v1.yml
├── inspection_report/v1.yml
├── insurance_claim/v1.yml
└── medical_record/v1.yml

tests/envx/                45 tests, all green in stub mode (no GPU needed).
```

## Running the tests

```
pip install -e .          # or: pip install jsonschema rapidfuzz httpx cryptography pyyaml cffi pytest
PYTHONPATH=src pytest tests/envx/
```

The test suite runs with `ENVX_GLM_OCR_STUB=1` so no GPU is required. The
stub returns deterministic per-doc-type payloads that exercise validation,
grounding, marker rules, wet storage, and attestation end-to-end.

## Running against a real GLM-OCR server

```
vllm serve zai-org/GLM-OCR \
  --port 8080 \
  --allowed-local-media-path / \
  --speculative-config '{"method": "mtp", "num_speculative_tokens": 3}' \
  --attention-backend triton \
  --speculative-draft-attention-backend triton \
  --served-model-name glm-ocr

export ENVX_GLM_OCR_URL=http://localhost:8080
export ENVX_GLM_OCR_MODEL=glm-ocr
```

Without MTP speculative decoding you lose ~2× throughput. Without the Triton
backend on Blackwell (RTX 5090) vLLM won't start cleanly. See §2.5.5.

## Environment variables

| Variable                    | Default               | Notes                                   |
|-----------------------------|-----------------------|-----------------------------------------|
| `ENVX_WET_ROOT`             | `./var/wet`           | Content-addressed blob store root.       |
| `ENVX_SCHEMAS_ROOT`         | `./schemas`           | Versioned KIE schema library.            |
| `ENVX_ATTEST_KEY`           | `./var/attest.key`    | Ed25519 private key (dev only; prod KMS).|
| `ENVX_GLM_OCR_URL`          | *(empty)*             | vLLM base URL. Empty → stub mode.        |
| `ENVX_GLM_OCR_MODEL`        | `glm-ocr`             | Served model name.                       |
| `ENVX_GLM_OCR_TIMEOUT`      | `120`                 | HTTP timeout, seconds.                   |
| `ENVX_GLM_OCR_STUB`         | `0`                   | Force stub even if URL is set (tests).   |
| `ENVX_GROUNDING_MIN_RATIO`  | `0.85`                | Minimum fuzzy ratio to accept a field.   |

## Next branches (not in this PR)

1. LiteParse Tier A integration — populates `blocks.text_raw`, quality signals.
2. `pg_search` BM25 + `pgvectorscale` DiskANN.
3. Structural chunker that consumes `regions`.
4. Contextual Retrieval enrichment using `extracted_fields` to template chunk context.
5. Reranker (BGE-v2-m3) on 5090.
6. Retrieval DSL compiler.
7. LightRAG graph layer on canonical entities.
8. ColPali visual retrieval path on high-risk doc classes.
