# Running ENVX fully open source

ENVX has no hard dependency on any commercial API. Every inference component
speaks a documented HTTP protocol, so swapping a hosted model for a
self-hosted one is configuration, not code.

This matters beyond preference. A legal corpus is client-confidential; for
many matters, sending document text to a third-party API is a conflict with
the engagement terms. Self-hosting is often the only admissible option.

---

## What ENVX actually requires

| Component | Protocol it speaks | Config |
|---|---|---|
| Embeddings | `POST /v1/embeddings` (OpenAI-compatible) | `ENVX_EMBEDDING_URL` |
| Reranker | `POST /rerank` (TEI or Cohere envelope) | `ENVX_RERANK_URL` |
| KIE / parsing | `POST /v1/chat/completions` with image parts | `ENVX_GLM_OCR_URL`, `ENVX_PARSE_URL` |
| Cold tier | reuses `ENVX_EMBEDDING_URL` | — |
| Database | PostgreSQL | `ENVX_DATABASE_URL` |

The reranker client parses all three response envelopes servers emit in
practice — a bare list, `{"results": [...]}`, and `{"data": [...]}` — so it
works against TEI, Infinity, vLLM, and Cohere-compatible endpoints without
per-vendor branching.

---

## A fully open-source stack

Every piece below is open weights or open source.

### Embeddings

**Ollama** — simplest to operate.

```bash
ollama pull bge-m3            # MIT, 8k context, multilingual
ollama serve
export ENVX_EMBEDDING_URL=http://127.0.0.1:11434
export ENVX_EMBEDDING_MODEL=bge-m3
export ENVX_EMBEDDING_DIM=1024
```

**text-embeddings-inference** (HuggingFace, Apache-2.0) — faster, batches well.

```bash
docker run --gpus all -p 8080:80 \
  ghcr.io/huggingface/text-embeddings-inference:latest \
  --model-id Qwen/Qwen3-Embedding-8B
export ENVX_EMBEDDING_URL=http://127.0.0.1:8080
export ENVX_EMBEDDING_MODEL=Qwen3-Embedding-8B
export ENVX_EMBEDDING_DIM=4096
```

**Model choices**, in rough order of preference for this corpus:

- `zembed-1` (ZeroEntropy, Apache-2.0) — reports the strongest legal-domain
  NDCG@10 of the models surveyed; Matryoshka dims and binary quantization.
  Note their hosted API sunsets 2026-09-04; use the weights, not the API.
- `Qwen3-Embedding-8B` (Apache-2.0) — strongest open general-purpose,
  MTEB ~70.6, 32k context.
- `bge-m3` (MIT) — smaller, well-understood, good multilingual coverage.
- `nomic-embed-text-v2` (Apache-2.0) — cheap and fast where quality is
  less critical.

### Reranker

**Infinity** (MIT) or TEI both serve rerankers over `/rerank`:

```bash
docker run -p 7997:7997 michaelf34/infinity:latest \
  v2 --model-id Qwen/Qwen3-Reranker-4B
export ENVX_RERANK_URL=http://127.0.0.1:7997
export ENVX_RERANK_MODEL=Qwen3-Reranker-4B
```

- `Qwen3-Reranker-4B/8B` (Apache-2.0) — the safe institutional default.
- `zerank-2` (Apache-2.0 after the Notion acquisition) — tops public
  reranker leaderboards, emits calibrated scores.
- `bge-reranker-v2-m3` (MIT) — legacy baseline, still fine, cheapest.

Avoid `jina-reranker-v3`: **CC BY-NC**, so it cannot be used commercially.

### KIE and document parsing

Both are vLLM-served vision models with OpenAI-compatible APIs.

```bash
# KIE — schema-aware extraction
vllm serve zai-org/GLM-OCR --port 8081 \
  --allowed-local-media-path / \
  --speculative-config '{"method": "mtp", "num_speculative_tokens": 3}' \
  --attention-backend triton \
  --speculative-draft-attention-backend triton \
  --served-model-name glm-ocr
export ENVX_GLM_OCR_URL=http://127.0.0.1:8081

# Parsing — PaddleOCR-VL leads OmniDocBench v1.6
vllm serve PaddlePaddle/PaddleOCR-VL-1.6 --port 8082 \
  --served-model-name paddleocr-vl
export ENVX_PARSE_URL=http://127.0.0.1:8082
```

GLM-OCR is MIT (model) / Apache-2.0 (SDK); PaddleOCR-VL is Apache-2.0.

Without MTP speculative decoding you lose roughly half your throughput.
Without the Triton attention backend, vLLM will not start cleanly on
Blackwell (RTX 5090).

### Database

PostgreSQL with `pgvector` (PostgreSQL licence) — require **≥ 0.8.3** for
CVE-2026-3172. For full-text, prefer `pg_textsearch` (PostgreSQL licence)
over `pg_search` (AGPLv3) in a commercial product. Past roughly 50M vectors,
`VectorChord` replaces pgvector's index.

### Cold tier

`LEANN` (MIT) reuses whatever `ENVX_EMBEDDING_URL` points at, so the cold
tier shares the hot tier's model and vector space. It additionally needs
`tiktoken`'s `cl100k_base` encoding, which downloads once from
`openaipublic.blob.core.windows.net`; on an air-gapped host, pre-seed it and
set `TIKTOKEN_CACHE_DIR`.

---

## Verifying without a GPU

`envx devserver` implements the same embeddings and rerank protocols with
deterministic hashing vectors:

```bash
python -m envx.cli devserver &
export ENVX_EMBEDDING_URL=http://127.0.0.1:8099
export ENVX_RERANK_URL=http://127.0.0.1:8099
python -m envx.cli doctor
```

This exercises the integration — request shapes, response parsing, error
handling — without exercising model quality. It is how the HTTP client paths
are tested in CI, and it is a reasonable smoke test for a new deployment
before pointing at real models.

**It is not a model.** Retrieval quality numbers from the dev server are
meaningless.

---

## Licence summary

| Component | Licence | Commercial use |
|---|---|---|
| ENVX | project licence | — |
| GLM-OCR | MIT / Apache-2.0 | yes |
| PaddleOCR-VL | Apache-2.0 | yes |
| Qwen3-Embedding / Reranker | Apache-2.0 | yes |
| bge-m3 / bge-reranker-v2-m3 | MIT | yes |
| zembed-1 / zerank-2 | Apache-2.0 | yes |
| jina-reranker-v3 | CC BY-NC | **no** |
| LEANN | MIT | yes |
| LightRAG | MIT | yes |
| pgvector / pg_textsearch | PostgreSQL | yes |
| pg_search (ParadeDB) | AGPLv3 | copyleft — review first |
| Ollama / TEI / Infinity / vLLM | MIT / Apache-2.0 | yes |

The two to watch are `pg_search` (AGPLv3 — obligations attach to a hosted
service) and `jina-reranker-v3` (non-commercial, disqualifying). Both have
permissive alternatives listed above, which is why the defaults avoid them.
