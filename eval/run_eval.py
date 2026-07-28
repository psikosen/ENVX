"""Retrieval evaluation harness.

Measures the architectural claims the design rests on, rather than model
quality:

    Does hybrid retrieval beat either path alone?
    Does lexicon query expansion help on vocabulary mismatch?
    Does contextual enrichment help on near-duplicate documents?
    Does reranking improve top-1?
    Does client isolation hold under adversarial queries?

Run it::

    PYTHONPATH=src python eval/run_eval.py
    PYTHONPATH=src python eval/run_eval.py --embedding-url http://localhost:11434

With no endpoint it uses local backends (LSA, then hashing). Absolute
numbers from those are not meaningful; the comparisons between
configurations are, because every configuration sees the same backend.
"""

from __future__ import annotations

import argparse
import json
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "src"))
sys.path.insert(0, str(REPO / "eval"))

from corpus import DOCS, QUERIES, corpus_stats  # noqa: E402

from envx.app import EnvxApp  # noqa: E402
from envx.config import EnvxConfig  # noqa: E402
from envx.dsl.plan import RerankSpec, RetrievalPath, RetrievalPlan, Scope  # noqa: E402
from envx.embedding import HashingEmbedding, HTTPEmbedding  # noqa: E402
from envx.eval import QueryResult, RunMetrics, summarize  # noqa: E402
from envx.lexicon import Lexicon  # noqa: E402


@dataclass
class Config:
    label: str
    use_bm25: bool = True
    use_dense: bool = True
    use_lexicon: bool = True
    use_rerank: bool = False
    use_enrichment: bool = True


CONFIGURATIONS = [
    Config("bm25 only", use_dense=False, use_lexicon=False, use_enrichment=False),
    Config("bm25 + lexicon", use_dense=False, use_enrichment=False),
    Config("dense only", use_bm25=False, use_lexicon=False, use_enrichment=False),
    Config("hybrid (no lexicon/CR)", use_lexicon=False, use_enrichment=False),
    Config("hybrid + lexicon", use_enrichment=False),
    Config("hybrid + lexicon + CR", use_enrichment=True),
    Config("hybrid + lexicon + CR + rerank", use_enrichment=True, use_rerank=True),
]


def build_app(cfg: Config, args: argparse.Namespace) -> EnvxApp:
    tmp = Path(tempfile.mkdtemp())
    config = EnvxConfig(
        wet_root=tmp / "wet",
        schemas_root=REPO / "schemas",
        lexicon_path=REPO / "lexicon" / "hazards.yml",
        attestation_key_path=tmp / "attest.key",
        glm_ocr_stub=True,
        embedding_url=args.embedding_url or "",
        embedding_model=args.embedding_model,
        embedding_dim=args.embedding_dim,
        rerank_url=args.rerank_url or "",
        rerank_model=args.rerank_model,
    )

    embedder = None
    if not args.embedding_url:
        embedder = _local_embedder(args)

    # Disabling the lexicon means handing the app an empty one, which is
    # cleaner than special-casing the query path.
    lexicon = None if cfg.use_lexicon else Lexicon(version="disabled")

    app = EnvxApp(config=config, embedder=embedder, lexicon=lexicon)
    if not cfg.use_enrichment:
        # Index text_raw instead of the enriched text.
        app.enricher = _NullEnricher()
    return app


class _NullEnricher:
    """Contextual enrichment disabled — index the raw chunk text."""

    def enrich(self, chunks, *, kie_payload):
        from envx.enrichment import ContextualEnrichment

        return [
            ContextualEnrichment(chunk_id=c.chunk_id, prefix="", text_contextual=c.text)
            for c in chunks
        ]


def _local_embedder(args: argparse.Namespace):
    if args.backend == "hashing":
        return HashingEmbedding(dim=512)
    try:
        from envx.embedding.local import LSAEmbedding
    except ImportError:
        print("scikit-learn not installed; falling back to hashing", file=sys.stderr)
        return HashingEmbedding(dim=512)
    # LSA derives its space from the corpus, so fit on the documents that
    # will be indexed.
    return LSAEmbedding(dim=args.embedding_dim).fit([d.text for d in DOCS])


def ingest_corpus(app: EnvxApp) -> dict[str, str]:
    """Ingest the eval corpus. Returns doc_id -> doc_key."""
    mapping: dict[str, str] = {}
    for doc in DOCS:
        result = app.ingest(
            content=doc.text.encode(),
            filename=doc.filename,
            client_id=doc.client_id,
            matter_id=doc.matter_id,
        )
        mapping[result.doc_id] = doc.doc_key
    return mapping


def run_configuration(cfg: Config, args: argparse.Namespace) -> RunMetrics:
    app = build_app(cfg, args)
    id_to_key = ingest_corpus(app)

    run = RunMetrics(label=cfg.label)
    for query in QUERIES:
        paths = []
        if cfg.use_bm25:
            paths.append(RetrievalPath(kind="bm25", query=query.text))
        if cfg.use_dense:
            paths.append(RetrievalPath(kind="dense", query=query.text))

        plan = RetrievalPlan(
            scope=Scope(client_id=query.client_id),
            paths=tuple(paths),
            top_k=args.top_k,
            rerank=RerankSpec(model="eval", top_k=args.top_k) if cfg.use_rerank else None,
        )
        result = app.query(plan)

        # Collapse chunks to documents, preserving first-appearance order:
        # two chunks from one document are a single answer.
        ranked: list[str] = []
        for item in result.evidence:
            key = id_to_key.get(item.doc_id)
            if key and key not in ranked:
                ranked.append(key)

        run.per_query.append(
            QueryResult(
                query_id=query.query_id,
                ranked=ranked,
                relevant=query.relevant,
                tags=query.tags,
            )
        )
    return run


def check_isolation(args: argparse.Namespace) -> dict[str, object]:
    """Adversarial isolation check.

    Runs every query against the wrong client and asserts nothing comes
    back. A leak here is a confidentiality breach, not a ranking problem,
    so it is reported separately from the metrics.
    """
    app = build_app(Config("isolation"), args)
    id_to_key = ingest_corpus(app)
    other_client = {"ACME": "BRIDGEPORT", "BRIDGEPORT": "ACME"}
    leaks: list[dict[str, str]] = []

    for query in QUERIES:
        wrong = other_client[query.client_id]
        result = app.query(
            RetrievalPlan(
                scope=Scope(client_id=wrong),
                paths=(
                    RetrievalPath(kind="bm25", query=query.text),
                    RetrievalPath(kind="dense", query=query.text),
                ),
                top_k=args.top_k,
            )
        )
        for item in result.evidence:
            key = id_to_key.get(item.doc_id, "")
            if key in query.relevant:
                leaks.append({"query": query.query_id, "leaked": key, "scope": wrong})
    return {"queries_checked": len(QUERIES), "leaks": leaks}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--embedding-url", default=None)
    parser.add_argument("--embedding-model", default="envx-eval")
    parser.add_argument("--embedding-dim", type=int, default=256)
    parser.add_argument("--rerank-url", default=None)
    parser.add_argument("--rerank-model", default="envx-eval-rerank")
    parser.add_argument("--backend", choices=("lsa", "hashing"), default="lsa")
    parser.add_argument("--top-k", type=int, default=10)
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--tags", action="store_true", help="break results down by tag")
    args = parser.parse_args(argv)

    stats = corpus_stats()
    backend = args.embedding_url or f"local:{args.backend}"
    print(f"corpus:   {stats['documents']} docs, {stats['queries']} queries, "
          f"{stats['relevance_pairs']} relevance pairs, {stats['clients']} clients")
    print(f"embedder: {backend}")
    print()

    runs = [run_configuration(cfg, args) for cfg in CONFIGURATIONS]
    print(summarize(runs))

    isolation = check_isolation(args)
    print()
    print(f"client isolation: {isolation['queries_checked']} cross-client queries, "
          f"{len(isolation['leaks'])} leaks")
    if isolation["leaks"]:
        print("  LEAKS:", json.dumps(isolation["leaks"], indent=2))

    if args.tags:
        print()
        best = runs[-1]
        print(f"per-tag recall@5 for '{best.label}':")
        for tag, metrics in best.by_tag((5,)).items():
            print(f"   {tag:16s} recall@5={metrics['recall@5']:.3f}")

    if args.json:
        print()
        print(json.dumps(
            {
                "backend": backend,
                "corpus": stats,
                "runs": {r.label: r.aggregate() for r in runs},
                "total_failures": {r.label: r.total_failures for r in runs},
                "isolation": isolation,
            },
            indent=2,
        ))

    # Isolation failure is the only condition that fails the run outright.
    return 1 if isolation["leaks"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
