import json
from pathlib import Path

from envx.attestation import sign_manifest, verify_manifest
from envx.wet_storage import WetStore, sha256_bytes


def _store(tmp_path: Path) -> WetStore:
    return WetStore(
        base=tmp_path / "wet",
        attestation_key_path=tmp_path / "attest.key",
    )


def test_ingest_is_content_addressed_and_dedup(tmp_path):
    store = _store(tmp_path)
    data = b"pretend pdf bytes"
    ref1 = store.ingest_bytes(data, "pdf", {"client_id": "C1"})
    ref2 = store.ingest_bytes(data, "pdf", {"client_id": "C1"})
    assert ref1.sha256 == ref2.sha256 == sha256_bytes(data)
    # The directory structure matches the architecture §4.1.
    original = ref1.root / "original.pdf"
    meta = json.loads((ref1.root / "metadata.json").read_text())
    assert original.read_bytes() == data
    assert meta["sha256"] == ref1.sha256
    assert meta["client_id"] == "C1"
    assert (ref1.root / "audit.log").exists()


def test_ingest_is_worm(tmp_path):
    import os
    import stat

    store = _store(tmp_path)
    ref = store.ingest_bytes(b"abc", "pdf", {})
    original = ref.root / "original.pdf"
    mode = os.stat(original).st_mode
    # WORM: the original is chmodded read-only for everyone. (Root bypasses
    # POSIX permissions, so we assert the bits — production swaps in S3
    # Object Lock for real enforcement.)
    assert stat.S_IMODE(mode) == 0o444


def test_parse_run_persists_manifest_and_signature(tmp_path):
    store = _store(tmp_path)
    ref = store.ingest_bytes(b"abc", "pdf", {})
    run_id = store.record_parse_run(
        ref,
        parser={"name": "liteparse", "version": "0.1.0"},
        result={"pages": [{"page": 1, "text": "hello"}]},
    )
    run_dir = ref.parse_runs_dir / run_id
    assert (run_dir / "parser.json").exists()
    assert (run_dir / "result.json").exists()
    manifest = json.loads((run_dir / "manifest.json").read_text())
    signature = (run_dir / "attestation.sig").read_bytes()
    assert verify_manifest(manifest, signature, tmp_path / "attest.key") is True


def test_kie_run_persists_schema_and_report(tmp_path):
    store = _store(tmp_path)
    ref = store.ingest_bytes(b"abc", "pdf", {})
    run_id = store.record_kie_run(
        ref,
        schema={"$id": "envx://schemas/x/v1", "type": "object"},
        prompt="do the thing",
        output={"doc_type": "x"},
        validation_report={"needs_review": False, "review_reasons": []},
    )
    run_dir = ref.kie_runs_dir / run_id
    assert json.loads((run_dir / "output.json").read_text())["doc_type"] == "x"
    assert json.loads((run_dir / "validation_report.json").read_text()) == {
        "needs_review": False,
        "review_reasons": [],
    }
    sig = (run_dir / "attestation.sig").read_bytes()
    manifest = json.loads((run_dir / "manifest.json").read_text())
    assert verify_manifest(manifest, sig, tmp_path / "attest.key")


def test_append_markers_writes_jsonl(tmp_path):
    store = _store(tmp_path)
    ref = store.ingest_bytes(b"abc", "pdf", {})
    store.append_markers(
        ref,
        [
            {"code": "RISK:ASBESTOS", "confidence": 0.95},
            {"code": "RISK:LEAD", "confidence": 0.8},
        ],
    )
    lines = (ref.root / "markers.jsonl").read_text().splitlines()
    assert len(lines) == 2
    first = json.loads(lines[0])
    assert first["code"] == "RISK:ASBESTOS"
    assert "at" in first


def test_tampered_manifest_fails_verification(tmp_path):
    store = _store(tmp_path)
    ref = store.ingest_bytes(b"abc", "pdf", {})
    run_id = store.record_parse_run(ref, parser={"x": 1}, result={"y": 2})
    run_dir = ref.parse_runs_dir / run_id
    sig = (run_dir / "attestation.sig").read_bytes()
    manifest = json.loads((run_dir / "manifest.json").read_text())
    manifest["result_sha256"] = "0" * 64
    assert not verify_manifest(manifest, sig, tmp_path / "attest.key")


def test_signing_is_deterministic_for_same_manifest(tmp_path):
    # Ed25519 signatures are deterministic — reproducibility matters for audit.
    key_path = tmp_path / "attest.key"
    manifest = {"kind": "parse", "run_id": "abc", "blob_sha256": "x", "ended_at": "t"}
    s1 = sign_manifest(manifest, key_path)
    s2 = sign_manifest(manifest, key_path)
    assert s1 == s2
