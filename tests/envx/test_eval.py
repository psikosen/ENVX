"""Metric correctness, plus regression guards on the eval findings.

The metrics are tested against hand-computed values because a silently
wrong metric is worse than no metric — it produces confident numbers that
justify the wrong decision.
"""

import subprocess
import sys
from pathlib import Path

from envx.eval import (
    QueryResult,
    RunMetrics,
    average_precision,
    ndcg_at_k,
    recall_at_k,
    reciprocal_rank,
)

REPO = Path(__file__).resolve().parents[2]


def test_recall_at_k():
    ranked = ["a", "b", "c", "d"]
    assert recall_at_k(ranked, ["a", "z"], 1) == 0.5
    assert recall_at_k(ranked, ["a", "z"], 4) == 0.5
    assert recall_at_k(ranked, ["a", "b"], 2) == 1.0
    assert recall_at_k(ranked, [], 3) == 1.0


def test_reciprocal_rank():
    assert reciprocal_rank(["a", "b", "c"], ["a"]) == 1.0
    assert reciprocal_rank(["a", "b", "c"], ["c"]) == pytest_approx(1 / 3)
    assert reciprocal_rank(["a", "b"], ["z"]) == 0.0


def pytest_approx(value, tol=1e-9):
    class _Approx:
        def __eq__(self, other):
            return abs(other - value) < tol

        def __repr__(self):
            return f"~{value}"

    return _Approx()


def test_average_precision_hand_computed():
    # Relevant at ranks 1 and 3: (1/1 + 2/3) / 2 = 0.8333...
    assert average_precision(["a", "x", "b"], ["a", "b"]) == pytest_approx(
        (1.0 + 2 / 3) / 2
    )


def test_ndcg_rewards_higher_ranks():
    top = ndcg_at_k(["a", "x", "y"], ["a"], 3)
    bottom = ndcg_at_k(["x", "y", "a"], ["a"], 3)
    assert top == 1.0
    assert bottom < top


def test_total_failures_are_surfaced_separately():
    # A mean hides a query that returned nothing responsive, which is a
    # different class of problem from one that ranked poorly.
    run = RunMetrics(
        label="t",
        per_query=[
            QueryResult("hit", ["a"], ("a",)),
            QueryResult("miss", ["z"], ("a",)),
        ],
    )
    assert run.total_failures == ["miss"]
    assert 0 < run.aggregate()["recall@5"] < 1


def _run_eval(*extra: str) -> str:
    proc = subprocess.run(
        [sys.executable, "eval/run_eval.py", "--json", *extra],
        cwd=REPO,
        capture_output=True,
        text=True,
        env={"PYTHONPATH": "src", "PATH": "/usr/bin:/bin:/usr/local/bin"},
        timeout=600,
    )
    assert proc.returncode == 0, proc.stderr[-2000:]
    return proc.stdout


def test_eval_harness_runs_and_isolation_holds():
    """Client isolation must hold under every adversarial cross-client query.

    This is the one eval assertion that is a correctness guarantee rather
    than a quality measurement: a leak is a confidentiality breach.
    """
    import json

    output = _run_eval("--backend", "hashing")
    payload = json.loads(output[output.index("{") :])
    assert payload["isolation"]["leaks"] == []
    assert payload["isolation"]["queries_checked"] == payload["corpus"]["queries"]


def test_lexicon_expansion_improves_ranking():
    """The lexicon's whole purpose is bridging query/document vocabulary.

    If this regresses, expansion has stopped working and queries phrased
    the way a lawyer speaks will stop matching documents phrased the way an
    inspector writes.
    """
    import json

    output = _run_eval("--backend", "hashing")
    runs = json.loads(output[output.index("{") :])["runs"]
    assert runs["bm25 + lexicon"]["mrr"] > runs["bm25 only"]["mrr"]
    assert runs["bm25 + lexicon"]["recall@1"] > runs["bm25 only"]["recall@1"]


def test_preflight_reports_unreachable_endpoint():
    """A down endpoint must be diagnosed, not surfaced as a traceback.

    The usual cause is running `ollama pull` before `ollama serve` — the
    pull fails, the model is never fetched, and without a preflight the
    failure appears much later as a connection error mid-run.
    """
    proc = subprocess.run(
        [
            sys.executable, "eval/run_eval.py",
            # Port chosen to be closed.
            "--embedding-url", "http://127.0.0.1:9",
            "--embedding-model", "bge-m3",
            "--embedding-dim", "1024",
        ],
        cwd=REPO,
        capture_output=True,
        text=True,
        env={"PYTHONPATH": "src", "PATH": "/usr/bin:/bin:/usr/local/bin"},
        timeout=300,
    )
    assert proc.returncode == 2
    assert "preflight failed" in proc.stderr
    assert "ollama serve" in proc.stderr


def test_preflight_catches_dimension_mismatch():
    """A dim mismatch must fail before ingesting, with the right value."""
    from envx.devserver import dev_embedding_server

    with dev_embedding_server(dim=512) as url:
        proc = subprocess.run(
            [
                sys.executable, "eval/run_eval.py",
                "--embedding-url", url,
                "--embedding-model", "envx-dev-embedding",
                "--embedding-dim", "1024",
            ],
            cwd=REPO,
            capture_output=True,
            text=True,
            env={"PYTHONPATH": "src", "PATH": "/usr/bin:/bin:/usr/local/bin"},
            timeout=300,
        )
    assert proc.returncode == 2
    assert "returns dim 512" in proc.stderr
    assert "ENVX_EMBEDDING_DIM=512" in proc.stderr


def test_eval_runs_against_a_live_http_endpoint():
    """The whole harness over HTTP, the way a real model would be used."""
    import json

    from envx.devserver import dev_embedding_server

    with dev_embedding_server(dim=512) as url:
        proc = subprocess.run(
            [
                sys.executable, "eval/run_eval.py", "--json",
                "--embedding-url", url,
                "--embedding-model", "envx-dev-embedding",
                "--embedding-dim", "512",
            ],
            cwd=REPO,
            capture_output=True,
            text=True,
            env={"PYTHONPATH": "src", "PATH": "/usr/bin:/bin:/usr/local/bin"},
            timeout=600,
        )
    assert proc.returncode == 0, proc.stderr[-2000:]
    payload = json.loads(proc.stdout[proc.stdout.index("{") :])
    assert payload["isolation"]["leaks"] == []
    assert payload["runs"]["hybrid + lexicon"]["recall@5"] > 0.5
