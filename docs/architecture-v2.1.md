# ENVX — Legal Document Intelligence

Ingest legal documents, understand their structure and content, and make
them retrievable with evidence a lawyer can cite.

Built against architecture v2.1. This document records what is implemented,
what is stubbed, and where the original design was revised against mid-2026
research.

---

## What it does

Property disclosures, environmental site assessments, inspection reports,
insurance claim files, and exposure-related medical records go in. What
comes out is a queryable corpus where every answer traces to a page and
region of a specific, tamper-evident source document.

Representative questions it is built to answer:

- Which properties in this client's portfolio have an asbestos disclosure
  or an environmental finding?
- Did the seller disclose the water intrusion that appears in the
  inspection report?
- Which claims cite this exclusion?
- Which documents connect to entities related to ACME Housing?

---

## Pipeline

```
ingest ─ intake (content-addressed, WORM, signed)
       ─ classify doc_type            rules + LLM fallback
       ─ LiteParse Tier A             text, bboxes, quality signals
       ─ GLM-OCR region map           every page
       ─ GLM-OCR KIE                  schema-aware JSON, every doc
       ─ validate                     JSON Schema + grounding + citations
       ─ marker rules                 KIE fields -> RISK:/CLAUSE:/FINDING:
       ─ structural chunking          region boundaries, not char windows
       ─ contextual enrichment        KIE facts templated into chunk context
       ─ embed + index                BM25 + dense
       ─ entity canonicalization      cross-document identity
       ─ knowledge graph              entities, documents, risks
       ─ review triage                four states, trigger-driven

query  ─ plan (YAML DSL)
       ─ hybrid retrieve              BM25 + dense + graph + visual
       ─ RRF fusion
       ─ rerank
       ─ evidence with citations      block_id, page, region_id
```

The LLM plans and reads evidence. It never fetches.

---

## Layout

```
src/envx/
  app.py            EnvxApp — ingest() and query()
  cli.py            envx ingest|query|plan|schemas|lexicon|migrate|doctor|devserver
  devserver.py      local OpenAI-compatible embeddings + rerank endpoint
  config.py         environment-driven configuration
  pipeline.py       preprocessing-only pipeline (subset of app.ingest)

  wet_storage.py    content-addressed WORM store
  attestation.py    Ed25519 signing of parse/KIE manifests

  classifier/       doc-type classification
  liteparse/        Tier A adapter (CLI bridge + stub)
  glm_ocr/          KIE, parsing, layout regions (+ stub)
  kie/              schema validation, grounding, twin-run agreement
  schemas/          versioned schema loader
  markers/          declarative KIE-field -> marker rules
  chunking/         structural chunker
  entities/         canonicalization
  enrichment/       contextual retrieval
  embedding/        HTTP + offline hashing backends
  retrieval/        BM25, vector, RRF fusion, rerank
  graph/            knowledge graph
  visual/           late-interaction visual path
  coldstore/        LEANN-backed cold tier
  dsl/              plan compiler, executor, structured filter (Path 5)
  review/           review states, triggers, correction log
  lifecycle/        hot/warm/cold tiering, drift sampling
  lexicon/          legal-domain vocabulary
  queue/            durable job queue
  db/migrations/    001-006 Postgres DDL
  db/repository.py  Postgres persistence

schemas/            5 doc-type KIE schemas (YAML + JSON Schema + marker rules)
lexicon/hazards.yml counsel-reviewed vocabulary
tests/envx/         85 tests (7 skip without a database)
```

---

## Running it

```bash
pip install -r requirements.txt
export PYTHONPATH=src

python -m envx.cli doctor
python -m envx.cli ingest mydoc.pdf --client ACME --matter M1 --stats
python -m envx.cli query -q "asbestos pipe insulation" mydoc.pdf --client ACME
python -m envx.cli lexicon -q "asbestos"
python -m envx.cli migrate --print
pytest tests/envx
```

To exercise the HTTP-backed paths without a GPU or an API key, run the local
inference endpoint:

```bash
python -m envx.cli devserver &                 # :8099
export ENVX_EMBEDDING_URL=http://127.0.0.1:8099
export ENVX_RERANK_URL=http://127.0.0.1:8099
python -m envx.cli doctor                      # embeddings/rerank now live
```

It serves deterministic hashing vectors over the OpenAI embeddings and TEI
rerank APIs. Not a model — a stand-in that makes the *integration* real, so
those code paths are tested rather than assumed. It is also what the cold
tier points LEANN at.

With Postgres, ingest and query become independent:

```bash
export ENVX_DATABASE_URL="postgresql://user@host/envx"
python -m envx.cli migrate                     # apply DDL
python -m envx.cli ingest docs/*.pdf --client ACME --matter M1
python -m envx.cli query -q "asbestos" --client ACME   # no corpus needed
```

Everything runs offline on stub backends with no configuration. `doctor`
reports which stages are stubbed and what to set to make each one live.

**Offline results exercise the pipeline, not model quality.** The hashing
embedding is lexical, not semantic; the stub KIE returns fixed payloads.
Wire real backends before drawing conclusions about retrieval quality.

---

## Configuration

| Variable | Default | Purpose |
|---|---|---|
| `ENVX_WET_ROOT` | `./var/wet` | content-addressed blob store |
| `ENVX_SCHEMAS_ROOT` | `./schemas` | KIE schema library |
| `ENVX_LEXICON_PATH` | `./lexicon/hazards.yml` | domain vocabulary |
| `ENVX_ATTEST_KEY` | `./var/attest.key` | Ed25519 key (dev only; use KMS) |
| `ENVX_GLM_OCR_URL` | — | GLM-OCR endpoint for KIE |
| `ENVX_GLM_OCR_MODEL` | `glm-ocr` | served model name |
| `ENVX_GLM_OCR_STUB` | `0` | force stub even when a URL is set |
| `ENVX_PARSE_URL` | — | parsing endpoint (falls back to GLM-OCR) |
| `ENVX_PARSE_MODEL` | `paddleocr-vl` | parsing model |
| `ENVX_EMBEDDING_URL` | — | OpenAI-compatible `/v1/embeddings` |
| `ENVX_EMBEDDING_MODEL` | `voyage-4` | embedding model |
| `ENVX_EMBEDDING_DIM` | `1024` | must match the index |
| `ENVX_RERANK_URL` | — | `/rerank` endpoint |
| `ENVX_RERANK_MODEL` | `zerank-2` | reranker |
| `ENVX_EMBEDDING_API_KEY` | — | bearer token, if the endpoint needs one |
| `ENVX_GROUNDING_MIN_RATIO` | `0.85` | fuzzy match floor for grounding |
| `ENVX_DATABASE_URL` | — | Postgres connection string |

---

## Revisions to the v2.1 design

Verified against current sources in July 2026. All arXiv citations in the
original document resolve to real papers.

### Vector stack: drop pgvectorscale

The original called for `pgvectorscale` (StreamingDiskANN + Statistical
Binary Quantization). **pgvectorscale has had effectively no development in
2026** — one cosmetic commit since the November 2025 release. There is no
deprecation notice, but Tiger Data has visibly moved engineering to
`pg_textsearch`. Do not deploy it new.

Migrations target plain **pgvector**, with **VectorChord** documented as the
upgrade path past roughly 50M vectors.

**Security: require pgvector ≥ 0.8.3.** CVE-2026-3172 is a buffer overflow
in parallel HNSW index builds that can leak data from unrelated relations —
disqualifying in a multi-client corpus. Migration 004 warns on older
versions.

### Full-text: prefer pg_textsearch over pg_search

Both provide real BM25. `pg_search` (ParadeDB) is AGPLv3; `pg_textsearch`
(Tiger Data) is under the PostgreSQL license. For a commercial legal
product the licensing difference is the deciding factor. Migration 004
carries both index forms commented, plus an explicitly-labelled `tsvector`
fallback so search works before either extension is installed — that
fallback is **not** BM25 and must be replaced before any ranking claims.

### Parsing and KIE are now separately configurable

OmniDocBench v1.5 was retired for saturation. On **v1.6**, PaddleOCR-VL-1.6
scores 96.34 and MinerU2.5-Pro 95.75, against GLM-OCR's 95.22. The gap is
concentrated in the Hard subset — nested tables, dense formulas — which is
what legal exhibits actually look like.

GLM-OCR still leads open-weights **schema-aware KIE**, which is the more
valuable half for this system. So parsing and KIE point at separate
endpoints (`ENVX_PARSE_URL` vs `ENVX_GLM_OCR_URL`).

### Model defaults refreshed

- **Embeddings:** Voyage 4 family; Qwen3-Embedding-8B as the strongest open
  general option. `zembed-1` reports the best legal-domain NDCG@10 of the
  models surveyed and is Apache-2.0.
- **Reranker:** `zerank-2` or Qwen3-Reranker-4B. **jina-reranker-v3 is
  CC BY-NC and cannot be used commercially** — removed from consideration.
- ZeroEntropy was acquired by Notion. Weights remain Apache-2.0 on
  HuggingFace, but **their hosted API sunsets 2026-09-04.** Self-host.

### Contextual Retrieval retained

The techniques expected to replace it did not. ConTEB/InSeNT is dormant and
its authors flag regressions on standard tasks; late chunking is
corpus-dependent and jina-embeddings-v5 dropped support for it.

More importantly, arXiv 2510.06999 (NLLP 2025) names **Document-Level
Retrieval Mismatch** — near-identical contracts causing retrieval from the
*wrong document* — as the dominant legal RAG failure, and its recommended
fix is summary-augmented chunking. Templating document identity (parties,
address, parcel id, execution date) into every chunk's context is precisely
that mitigation, and it is what the enricher does.

### Graph path weighted low by default

LightRAG is healthy and MIT-licensed, but the "beats GraphRAG on legal"
claim rests on UltraDomain's Legal split, which is **college textbooks, not
statutes or contracts**, scored by LLM win-rate. GraphRAG-Bench (ICLR'26)
finds GraphRAG frequently underperforms vanilla RAG at ~2.3× latency.

The graph stays — multi-hop entity questions are genuinely hard otherwise —
but it defaults to weight 0.5 in fusion and should be justified per query
class rather than enabled by default.

### LEANN added for the cold tier

Not in the original design. §4.2 nulls the embedding column on cold
documents, which makes them **unsearchable until rehydrated** — and the
matter closed two years ago is often exactly the one a conflict check needs.
You cannot rehydrate what you cannot find.

[LEANN](https://github.com/StarTrail-org/LEANN) (MIT) stores a pruned
proximity graph and recomputes embeddings during traversal, reporting ~97%
storage reduction at comparable recall. Its latency tradeoff is inverted
from the hot tier's requirements, which is exactly why it belongs at cold:

| Tier | Backend | Property |
|---|---|---|
| hot | pgvector HNSW | vectors resident, p95 < 100ms |
| warm | pgvector HNSW | vectors resident, relaxed latency |
| cold | LEANN | ~3% storage, recompute per query |

Client and matter isolation is pushed into LEANN's metadata filters so it
applies during traversal. Optional dependency; without it the store degrades
to a null backend that reports cold as unsearchable rather than silently
returning nothing.

**Embedding backend.** Because LEANN recomputes embeddings during traversal,
it needs a model at both build and query time. Its default pulls
`facebook/contriever` from HuggingFace, which is wrong here twice over: it
adds a model download to deployment, and it embeds the cold tier with a
*different* model than the hot tier, making cold and hot scores
incomparable. ENVX instead points LEANN's `openai` embedding mode at the
same endpoint configured by `ENVX_EMBEDDING_URL`. One model, one vector
space, no model download.

### Benchmarking

Migrate all OCR numbers to **OmniDocBench v1.6**. Use **ParseBench**
(arXiv 2604.08538) as the acceptance gate — ~2,000 human-verified enterprise
pages including contracts and insurance, which is far closer to this corpus
than OmniDocBench's 6% enterprise coverage. Still run your own eval on your
actual document mix before locking in a parser.

### Structured filtering (Path 5)

`structured_filter` compiles to a parameterised query over
`extracted_fields` and narrows the corpus before retrieval runs. The
predicate language is deliberately small — plans are authored by an LLM, and
an LLM that can emit arbitrary SQL against a multi-client legal corpus is a
security problem, not a feature.

```yaml
structured_filter:
  where: "$.hazards_disclosed[*].type IN ('asbestos', 'acm')"
  or: "$.recs[*] EXISTS"
```

Operators: `= != > >= < <= IN LIKE EXISTS`. Array wildcards match if any
element satisfies the predicate. Two rejections are deliberate: mixing `AND`
and `OR` in one expression (grouping changes the meaning, and guessing wrong
on a hazard query is not an acceptable failure), and unparsed trailing
content (applying only the parseable prefix would silently narrow the filter
to something other than what was written).

---

## Implementation status

**Working:** intake and WORM storage with Ed25519 attestations; doc-type
classification; region maps; KIE with schema validation, field grounding,
twin-run agreement, and citation enforcement; marker rules; structural
chunking; entity canonicalization; contextual enrichment; BM25 + dense
retrieval with RRF and reranking; structured metadata filtering over
`extracted_fields` (Path 5); knowledge graph; visual path; retrieval DSL;
review workflow with the two-person rule; tiering; drift sampling; durable
job queue; CLI.

**Stubbed, pending real backends:** GLM-OCR inference, document parsing,
LiteParse CLI, embeddings, reranker. Each has a working HTTP client; they
need endpoints.

**Persisted to Postgres:** documents, pages, regions, blocks, extracted
fields with per-field grounding verdicts, markers, and the schema registry.
`ingest` and `query` run as separate processes; the retrieval index is
rehydrated at startup. Verified against Postgres 16 — all migrations apply,
and the two-person review CHECK, the append-only corrections trigger, and
content-addressed dedup all reject violations at the database level.

**Also persisted:** the knowledge graph, canonical entity identities, and
the review queue. Canonical ids are stable across restarts, so a restart
cannot fork one entity into two and break cross-document synthesis.
Document identity is a deterministic UUIDv5 over the content hash, making
the application id and the database primary key the same value.

**Not started:** the review dashboard UI, S3 Object Lock (local filesystem
WORM only), KMS-backed attestation keys, and GLM-OCR fine-tuning.

---

## Known limitations

- **Dense retrieval needs pgvector.** Without the extension, migration 004
  skips `block_embeddings` and warns. Vectors are recomputed into memory at
  startup, so retrieval still works — it just doesn't scale past RAM.
- **Offline mode is not a quality signal.** Stub backends validate wiring.
- **Structural chunking depends on region-map quality.** Stub regions are
  one box per page, so chunking is trivial offline; behaviour with real
  PP-DocLayoutV3 output is materially different and needs evaluation.
- **LEANN index build unverified end-to-end.** The HuggingFace dependency is
  gone, but LEANN also uses `tiktoken` to truncate inputs to the embedding
  model's token limit, and the `cl100k_base` encoding is fetched from
  `openaipublic.blob.core.windows.net` on first use — blocked by egress
  policy in the development environment. API usage is verified against the
  installed package and the degradation path is tested; a real index build
  needs either that host allowed or a pre-seeded `TIKTOKEN_CACHE_DIR`. The
  failure is diagnosed with the specific cause and fix rather than a bare
  traceback.
- **Retrieval indexes are rebuilt in memory at startup.** Fine to millions
  of chunks on one box; past that, dense retrieval needs pgvector or
  VectorChord doing the search in the database rather than in Python.
- **No incremental index update.** A re-ingest rewrites a document's rows,
  but the in-memory index is only rebuilt on process start.
