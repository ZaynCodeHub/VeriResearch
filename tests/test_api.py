"""FastAPI backend, hermetic (heuristic judge, offline corpus — no network, no keys)."""

import time

import pytest

fastapi = pytest.importorskip("fastapi")
from fastapi.testclient import TestClient  # noqa: E402

from veriresearch.api.app import app  # noqa: E402

client = TestClient(app)


def _wait_for_completion(run_id: str, timeout_s: float = 5.0) -> dict:
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        data = client.get(f"/runs/{run_id}").json()
        if data["status"] in ("done", "error"):
            return data
        time.sleep(0.05)
    raise TimeoutError(f"run {run_id} did not finish in {timeout_s}s")


def test_health():
    assert client.get("/health").json() == {"status": "ok"}


def test_create_run_rejects_bad_mode():
    response = client.post("/runs", json={"topic": "x", "mode": "not-a-mode"})
    assert response.status_code == 400


def test_create_run_rejects_empty_topic():
    response = client.post("/runs", json={"topic": "   "})
    assert response.status_code == 400


def test_unknown_run_is_404():
    assert client.get("/runs/does-not-exist").status_code == 404


def test_full_run_lifecycle_and_claim_evidence_lookup():
    created = client.post("/runs", json={"topic": "the James Webb Space Telescope", "mode": "full"})
    assert created.status_code == 200
    run_id = created.json()["run_id"]

    data = _wait_for_completion(run_id)
    assert data["status"] == "done"
    assert data["verification_summary"]["claims_checked"] > 0
    assert len(data["claims"]) > 0

    supported_claim = next(c for c in data["claims"] if c["label"] == "SUPPORTED")
    detail = client.get(f"/runs/{run_id}/claims/{supported_claim['id']}").json()

    assert detail["verification"]["label"] == "SUPPORTED"
    assert detail["evidence"], "a SUPPORTED claim must carry a grounded evidence span"
    span = detail["evidence"][0]
    # The auditability requirement: the exact checked text must be a real
    # substring of the full source text, both returned by this one endpoint.
    assert span["source_raw_text"] is not None
    assert span["text"] == span["source_raw_text"][span["char_start"] : span["char_end"]]
