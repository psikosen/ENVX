"""ENVX command line.

    envx ingest   DOC...             ingest documents
    envx query    -q TEXT            run a retrieval query
    envx plan     PLAN.yml           execute a retrieval plan file
    envx schemas                     list the KIE schema library
    envx lexicon  -q TEXT            show query expansion for a phrase
    envx migrate  [--print]          show/apply DDL migrations
    envx doctor                      report backend availability

Runs offline by default. ``envx doctor`` shows which stages are on stub
backends and what to set to make them real.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from .app import EnvxApp
from .config import load_config
from .dsl import plan_from_yaml
from .dsl.plan import (
    RerankSpec,
    RetrievalPath,
    RetrievalPlan,
    Scope,
)
from .lexicon import load_lexicon
from .schemas import SchemaLoader


MIGRATIONS_DIR = Path(__file__).parent / "db" / "migrations"


def _app() -> EnvxApp:
    return EnvxApp()


def cmd_ingest(args: argparse.Namespace) -> int:
    app = _app()
    results = []
    for raw_path in args.paths:
        path = Path(raw_path)
        if not path.exists():
            print(f"error: {path} does not exist", file=sys.stderr)
            return 1
        result = app.ingest(
            content=path.read_bytes(),
            filename=path.name,
            client_id=args.client,
            matter_id=args.matter,
            matter_is_active=args.active_matter,
            extension=path.suffix.lstrip(".") or "pdf",
        )
        results.append(result.summary())
    print(json.dumps(results if len(results) > 1 else results[0], indent=2))
    if args.stats:
        print(json.dumps(app.stats(), indent=2), file=sys.stderr)
    return 0


def cmd_query(args: argparse.Namespace) -> int:
    """Query the corpus.

    With ENVX_DATABASE_URL set, the index is rehydrated from Postgres at
    startup and no corpus argument is needed. Without it, everything is
    in-memory, so any documents to search must be passed on the command line
    and are ingested first.
    """
    app = _app()
    for raw_path in args.corpus:
        path = Path(raw_path)
        if path.exists():
            app.ingest(
                content=path.read_bytes(),
                filename=path.name,
                client_id=args.client,
                matter_id=args.matter,
                extension=path.suffix.lstrip(".") or "pdf",
            )
    if not len(app.bm25):
        hint = (
            "no documents in scope"
            if app.repo is not None
            else "no corpus given and no ENVX_DATABASE_URL set"
        )
        print(json.dumps({"query": args.query, "evidence": [], "note": hint}, indent=2))
        return 0

    plan = RetrievalPlan(
        scope=Scope(
            client_id=args.client,
            matter_id=args.matter,
            doc_types=tuple(args.doc_type) if args.doc_type else None,
        ),
        paths=(
            RetrievalPath(kind="bm25", query=args.query),
            RetrievalPath(kind="dense", query=args.query),
        ),
        top_k=args.top_k,
        rerank=RerankSpec(model=load_config().rerank_model, top_k=args.limit),
    )
    result = app.query(plan)
    payload = {
        "query": args.query,
        "paths": result.path_hit_counts,
        "reranked": result.reranked,
        "evidence": [
            {
                "block_id": e.chunk_id,
                "doc_id": e.doc_id,
                "page": e.page_number,
                "region_id": e.region_id,
                "score": round(e.score, 5),
                "markers": list(e.markers),
                "text": e.text_raw[:280],
            }
            for e in result.evidence
        ],
    }
    print(json.dumps(payload, indent=2))
    return 0


def cmd_plan(args: argparse.Namespace) -> int:
    app = _app()
    for raw_path in args.corpus:
        path = Path(raw_path)
        if path.exists():
            app.ingest(
                content=path.read_bytes(),
                filename=path.name,
                client_id=args.client,
                matter_id=args.matter,
                extension=path.suffix.lstrip(".") or "pdf",
            )
    plan = plan_from_yaml(Path(args.plan).read_text())
    result = app.query(plan)
    print(
        json.dumps(
            {
                "paths": result.path_hit_counts,
                "reranked": result.reranked,
                "dropped_low_confidence": result.dropped_low_confidence,
                "dropped_missing_provenance": result.dropped_missing_provenance,
                "citations": result.citations,
            },
            indent=2,
        )
    )
    return 0


def cmd_schemas(args: argparse.Namespace) -> int:
    loader = SchemaLoader()
    rows = []
    for schema_id in loader.list_ids():
        for version in loader.list_versions(schema_id):
            schema = loader.load(schema_id, version)
            rows.append(
                {
                    "schema_id": schema.schema_id,
                    "version": schema.version,
                    "marker_rules": len(schema.marker_rules),
                    "phi_tier": schema.phi_tier,
                    "content_hash": schema.content_hash[:16],
                }
            )
    print(json.dumps(rows, indent=2))
    return 0


def cmd_lexicon(args: argparse.Namespace) -> int:
    lexicon = load_lexicon()
    print(
        json.dumps(
            {
                "version": lexicon.version,
                "entries": len(lexicon),
                "matched": [e.key for e in lexicon.matching_entries(args.query)],
                "expansions": lexicon.expand_query(args.query),
                "marker_boosts": lexicon.boosts_for(args.query),
            },
            indent=2,
        )
    )
    return 0


def cmd_migrate(args: argparse.Namespace) -> int:
    files = sorted(MIGRATIONS_DIR.glob("*.sql"))
    if args.print_only or not load_config().database_url:
        if not args.print_only:
            print(
                "ENVX_DATABASE_URL is not set; printing migrations instead.",
                file=sys.stderr,
            )
        for path in files:
            print(f"-- ==== {path.name} ====")
            print(path.read_text())
        return 0
    try:
        import psycopg  # type: ignore
    except ImportError:
        print(
            "psycopg is required to apply migrations: pip install 'psycopg[binary]'",
            file=sys.stderr,
        )
        return 1
    with psycopg.connect(load_config().database_url) as conn:  # pragma: no cover
        for path in files:
            print(f"applying {path.name}", file=sys.stderr)
            conn.execute(path.read_text())
        conn.commit()
    return 0


def cmd_doctor(args: argparse.Namespace) -> int:
    from .coldstore import leann_available
    from .liteparse import liteparse_on_path

    config = load_config()
    checks = [
        ("GLM-OCR (KIE)", bool(config.glm_ocr_url), "ENVX_GLM_OCR_URL", "stub payloads"),
        (
            "Document parsing",
            bool(config.effective_parse_url),
            "ENVX_PARSE_URL",
            "stub markdown",
        ),
        ("LiteParse Tier A", liteparse_on_path(), "install liteparse CLI", "text stub"),
        ("Embeddings", bool(config.embedding_url), "ENVX_EMBEDDING_URL", "hashing stub"),
        ("Reranker", bool(config.rerank_url), "ENVX_RERANK_URL", "lexical stub"),
        ("Cold tier (LEANN)", leann_available(), "pip install leann", "null store"),
        ("Postgres", bool(config.database_url), "ENVX_DATABASE_URL", "in-memory only"),
    ]
    width = max(len(name) for name, *_ in checks)
    print("ENVX backend status\n")
    for name, ok, how, fallback in checks:
        status = "live" if ok else "stub"
        detail = "" if ok else f"  (using {fallback}; set {how})"
        print(f"  [{status}] {name.ljust(width)}{detail}")
    print(f"\nschemas:  {len(SchemaLoader().list_ids())} doc types")
    print(f"lexicon:  {len(load_lexicon())} entries")
    print(f"wet root: {config.wet_root}")
    if config.offline:
        print("\nRunning fully offline. Results exercise the pipeline, not model quality.")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="envx", description=__doc__.split("\n")[0])
    sub = parser.add_subparsers(dest="command", required=True)

    def add_scope(p: argparse.ArgumentParser) -> None:
        p.add_argument("--client", default="DEFAULT", help="client id for scoping")
        p.add_argument("--matter", default=None, help="matter id for scoping")

    p_ingest = sub.add_parser("ingest", help="ingest documents")
    p_ingest.add_argument("paths", nargs="+")
    add_scope(p_ingest)
    p_ingest.add_argument("--active-matter", action="store_true")
    p_ingest.add_argument("--stats", action="store_true", help="print stats to stderr")
    p_ingest.set_defaults(func=cmd_ingest)

    p_query = sub.add_parser("query", help="ingest a corpus and query it")
    p_query.add_argument("-q", "--query", required=True)
    p_query.add_argument("corpus", nargs="*", help="documents to ingest first")
    add_scope(p_query)
    p_query.add_argument("--doc-type", action="append")
    p_query.add_argument("--top-k", type=int, default=50)
    p_query.add_argument("--limit", type=int, default=5)
    p_query.set_defaults(func=cmd_query)

    p_plan = sub.add_parser("plan", help="execute a retrieval plan file")
    p_plan.add_argument("plan")
    p_plan.add_argument("corpus", nargs="*")
    add_scope(p_plan)
    p_plan.set_defaults(func=cmd_plan)

    p_schemas = sub.add_parser("schemas", help="list the KIE schema library")
    p_schemas.set_defaults(func=cmd_schemas)

    p_lex = sub.add_parser("lexicon", help="show query expansion")
    p_lex.add_argument("-q", "--query", required=True)
    p_lex.set_defaults(func=cmd_lexicon)

    p_mig = sub.add_parser("migrate", help="show or apply DDL migrations")
    p_mig.add_argument("--print", dest="print_only", action="store_true")
    p_mig.set_defaults(func=cmd_migrate)

    p_doc = sub.add_parser("doctor", help="report backend availability")
    p_doc.set_defaults(func=cmd_doctor)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    return int(args.func(args))


if __name__ == "__main__":
    raise SystemExit(main())
