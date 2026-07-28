# Retrieval evaluation

The architecture makes claims — hybrid beats single-path, lexicon expansion
bridges vocabulary gaps, contextual enrichment fixes near-duplicate
confusion, reranking improves top-1. This measures them.

```bash
PYTHONPATH=src python -m envx.cli eval --tags
```

## What the corpus is

24 short documents across the five supported doc types, 16 queries, 38
relevance pairs, two client ids. Built to exercise the failure modes that
matter rather than to be easy:

- **Vocabulary mismatch** — queries use lawyer phrasing, documents use
  inspector phrasing. "asbestos" against "friable ACM in pipe lagging",
  "chrysotile", "thermal wrap".
- **Near-duplicates** — several disclosures differ only in party and
  address. This is Document-Level Retrieval Mismatch (arXiv 2510.06999),
  the dominant legal RAG failure.
- **Distractors** — documents sharing query vocabulary but not responsive
  (an inspection saying the roof *was replaced* against a query about roofs
  at end of life).
- **Two clients** — so isolation failures surface as measurable errors.

It is a smoke test, not a benchmark. **Treat the comparisons between
configurations as meaningful and the absolute numbers as not.**

## Results

Local LSA backend (TF-IDF + SVD), no GPU, `top_k=10`:

| configuration | recall@1 | recall@5 | MRR | nDCG@10 |
|---|---|---|---|---|
| bm25 only | 0.459 | 0.893 | 0.875 | 0.884 |
| bm25 + lexicon | **0.584** | 0.893 | **0.938** | 0.930 |
| dense only | 0.459 | 0.919 | 0.875 | 0.893 |
| hybrid (no lexicon/CR) | 0.459 | 0.914 | 0.875 | 0.889 |
| hybrid + lexicon | **0.584** | 0.914 | **0.938** | **0.935** |
| hybrid + lexicon + CR | **0.584** | **0.929** | **0.938** | 0.934 |
| hybrid + lexicon + CR + rerank | 0.500 | 0.888 | 0.854 | 0.886 |

Client isolation: **16 adversarial cross-client queries, 0 leaks.**

## What this validates

**Lexicon expansion is the largest single win.** recall@1 0.459 → 0.584
(+27% relative), MRR 0.875 → 0.938. This is the clearest confirmation of a
design decision in the whole system: legal queries and legal documents
genuinely do use different vocabulary, and expanding "asbestos" to ACM,
friable, and pipe lagging is what closes the gap. It holds identically
across both embedding backends.

**Client isolation holds.** Every query run against the wrong client
returns nothing. This is the one eval assertion that is a correctness
guarantee rather than a quality measurement — a leak here is a
confidentiality breach — so it is enforced as a test that fails the build.

**Contextual enrichment helps modestly.** recall@5 0.914 → 0.929 (LSA),
0.919 → 0.950 (hashing). Directionally right, small enough at this corpus
size that it should not be considered settled.

**Embedding quality propagates.** LSA beats token-hashing on dense-only
retrieval (recall@5 0.919 vs 0.888, MRR 0.875 vs 0.854), which is the
expected result and confirms that swapping in a real neural model is worth
doing.

## What this does not validate

**Hybrid fusion barely beats single-path here.** Dense alone reaches
recall@5 0.919; hybrid reaches 0.914 — slightly *worse*. At 24 documents
RRF has little to arbitrate between, and both paths are largely retrieving
the same set. This is not evidence against hybrid retrieval; it is evidence
that this corpus is too small to demonstrate it. Re-run at corpus scale
before treating fusion weights as tuned.

**Reranking makes things worse.** recall@1 0.584 → 0.500, MRR 0.938 →
0.854, consistently across both backends. The offline reranker is a lexical
similarity stand-in, not a cross-encoder, and it is discarding a better
ordering that fusion already produced. This is a measurement of the stub,
not of reranking — but it is a useful demonstration that the harness
detects a component actively hurting, which is exactly what an eval is for.
Do not enable reranking until a real cross-encoder is wired.

## Reading the per-tag breakdown

```
address          recall@5=0.455
lexicon          recall@5=0.583
vocabulary       recall@5=0.938
clause           recall@5=1.000
near_duplicate   recall@5=1.000
semantic         recall@5=1.000
negation         recall@5=1.000
```

`address` looks like a failure and is not: that query has 11 relevant
documents, so recall@5 cannot exceed 5/11 = 0.455. It is at ceiling. This
is why recall@k needs its k read alongside it.

`lexicon` at 0.583 is the honest weak spot — those queries have 3–4
relevant documents each and the tail is genuinely being missed.

## Running against a real model

The harness takes any OpenAI-compatible endpoint, so a real measurement is
one command away:

```bash
./scripts/eval_with_ollama.sh            # defaults to bge-m3
./scripts/eval_with_ollama.sh nomic-embed-text
```

The script starts Ollama only if it is not already running (on macOS the
desktop app runs it, so a bare `ollama serve` exits 1 — that is success, not
failure), pulls the model if missing, and **detects the embedding dimension
rather than assuming it**. A wrong `ENVX_EMBEDDING_DIM` is the most common
setup failure and the value differs per model: bge-m3 and mxbai-embed-large
are 1024, nomic-embed-text is 768.

The equivalent by hand:

```bash
# Skip `ollama serve` if it is already running as a service.
ollama serve &
until curl -sf http://127.0.0.1:11434/api/tags >/dev/null; do sleep 1; done
ollama pull bge-m3

export ENVX_EMBEDDING_URL=http://127.0.0.1:11434
export ENVX_EMBEDDING_MODEL=bge-m3
export ENVX_EMBEDDING_DIM=1024
PYTHONPATH=src python -m envx.cli eval --tags
```

The harness preflights the endpoint before ingesting anything, so a
server that is down or a model that was never pulled fails immediately with
the cause rather than a connection traceback partway through the run. A
dimension mismatch is reported with the value to set.

Add a real cross-encoder to test the reranking claim properly:

```bash
docker run -p 7997:7997 michaelf34/infinity:latest \
  v2 --model-id Qwen/Qwen3-Reranker-4B
export ENVX_RERANK_URL=http://127.0.0.1:7997
export ENVX_RERANK_MODEL=Qwen3-Reranker-4B
```

## Honest limits

- 24 documents and 16 queries is small. Differences under roughly 0.05 are
  noise at this size.
- Relevance labels are the corpus author's judgement, not adjudicated by
  counsel.
- KIE runs on stub payloads, so marker-based boosting is not meaningfully
  exercised.
- Everything here measures *retrieval*. Extraction accuracy — whether KIE
  reads the right hazard off the right page — needs a separate labelled set
  and has not been measured at all.
