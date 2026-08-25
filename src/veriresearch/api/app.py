"""FastAPI backend: kick off a run, poll it, and inspect any claim's evidence.

`GET /runs/{run_id}/claims/{claim_id}` is the endpoint that makes "click a
claim, see exactly what text it was checked against" a lookup rather than a
re-derivation: it returns each evidence span's char offsets *and* the full
`source_raw_text` they index into, plus every judge's rationale and quoted
span, straight out of the data model in `state.py` — nothing here recomputes
or re-verifies anything.

Run persistence lives behind `RunStore` (see `store.py`): an in-memory dict by
default (what every test uses), or a Postgres-backed store when `DATABASE_URL`
is set. Swapping backends doesn't change anything about the graph, the
verifier, or this API's shape.
"""

from __future__ import annotations

import logging
import os
import uuid
from typing import Any

from fastapi import BackgroundTasks, FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from ..graph import run as run_graph
from ..store import RunRecord, build_run_store

logger = logging.getLogger("veriresearch.api")

app = FastAPI(title="VeriResearch API", version="0.1.0")

_DEFAULT_ORIGINS = ["http://localhost:5173", "http://127.0.0.1:5173"]
_cors_env = os.getenv("CORS_ORIGINS", "")
_allow_origins = [o.strip() for o in _cors_env.split(",") if o.strip()] or _DEFAULT_ORIGINS

app.add_middleware(
    CORSMiddleware,
    allow_origins=_allow_origins,
    allow_methods=["*"],
    allow_headers=["*"],
)

_STORE = build_run_store()

# Cap on runs that are queued or actively running at once. Each run drives an
# LLM-graph traversal (or, offline, still real CPU work), and this API has no
# auth — an unbounded /runs endpoint on a public deploy is a resource
# exhaustion vector. 429 past this cap rather than queueing unboundedly.
_MAX_CONCURRENT_RUNS = int(os.getenv("MAX_CONCURRENT_RUNS", "5"))


class CreateRunRequest(BaseModel):
    topic: str
    mode: str = "full"


class CreateRunResponse(BaseModel):
    run_id: str
    status: str


def _execute(run_id: str) -> None:
    _STORE.mark_running(run_id)
    record = _require_run(run_id)
    try:
        state = run_graph(record.topic, mode=record.mode, thread_id=run_id)
        _STORE.mark_done(run_id, state)
    except Exception as exc:  # noqa: BLE001 — surfaced via GET /runs/{id}, not raised here
        logger.exception("run %s failed", run_id)
        _STORE.mark_error(run_id, str(exc))


def _require_run(run_id: str) -> RunRecord:
    record = _STORE.get(run_id)
    if record is None:
        raise HTTPException(404, f"no such run: {run_id}")
    return record


@app.post("/runs", response_model=CreateRunResponse)
def create_run(req: CreateRunRequest, background_tasks: BackgroundTasks) -> CreateRunResponse:
    if req.mode not in ("full", "baseline"):
        raise HTTPException(400, "mode must be 'full' or 'baseline'")
    if not req.topic.strip():
        raise HTTPException(400, "topic must not be empty")
    if _STORE.count_in_flight() >= _MAX_CONCURRENT_RUNS:
        raise HTTPException(429, "too many runs in flight, try again shortly")

    run_id = f"run_{uuid.uuid4().hex[:12]}"
    _STORE.create(run_id, req.topic, req.mode)
    background_tasks.add_task(_execute, run_id)
    return CreateRunResponse(run_id=run_id, status="queued")


@app.get("/runs")
def list_runs() -> list[dict[str, Any]]:
    records = _STORE.list()
    return [
        {"run_id": r.run_id, "topic": r.topic, "mode": r.mode, "status": r.status, "created_at": r.created_at}
        for r in sorted(records, key=lambda r: r.created_at, reverse=True)
    ]


@app.get("/runs/{run_id}")
def get_run(run_id: str) -> dict[str, Any]:
    record = _require_run(run_id)
    payload: dict[str, Any] = {
        "run_id": record.run_id,
        "topic": record.topic,
        "mode": record.mode,
        "status": record.status,
        "error": record.error,
    }
    if record.state is None:
        return payload

    report = record.state.get("report")
    claims = record.state.get("claims", {})
    payload["verification_summary"] = record.state.get("verification_summary")
    payload["revision_count"] = record.state.get("revision_count")

    if report is not None:
        payload["report"] = {
            "title": report.title,
            "summary": report.summary,
            "markdown": report.markdown,
            "sections": [
                {"heading": s.heading, "claim_ids": s.claim_ids, "prose": s.prose} for s in report.sections
            ],
            "references": [
                {"number": r.number, "source_id": r.source_id, "title": r.title, "url": r.url}
                for r in report.references
            ],
            "dropped_claim_ids": report.dropped_claim_ids,
            "flagged_claim_ids": report.flagged_claim_ids,
        }
        published_ids = {cid for s in report.sections for cid in s.claim_ids}
        payload["claims"] = [
            {
                "id": c.id,
                "text": c.text,
                "section": c.section,
                "label": c.verification.label.value if c.verification else None,
                "confidence": c.verification.confidence if c.verification else None,
                "color": c.verification.label.ui_color if c.verification else "red",
                "published": c.id in published_ids,
            }
            for c in claims.values()
        ]

    return payload


@app.get("/runs/{run_id}/claims/{claim_id}")
def get_claim(run_id: str, claim_id: str) -> dict[str, Any]:
    record = _require_run(run_id)
    if record.state is None:
        raise HTTPException(409, "run has not produced any claims yet")

    claim = record.state.get("claims", {}).get(claim_id)
    if claim is None:
        raise HTTPException(404, f"no such claim: {claim_id}")
    sources = record.state.get("sources", {})

    evidence = []
    for span in claim.evidence:
        source = sources.get(span.source_id)
        evidence.append(
            {
                "source_id": span.source_id,
                "char_start": span.char_start,
                "char_end": span.char_end,
                "text": span.text,
                "locator": span.locator,
                "source_url": source.url if source else None,
                "source_title": source.title if source else None,
                # The full document — this is what makes "see exactly what text
                # it was checked against" a lookup instead of a re-fetch.
                "source_raw_text": source.raw_text if source else None,
            }
        )

    judgments = []
    if claim.verification:
        for j in claim.verification.judgments:
            judgments.append(
                {
                    "source_id": j.source_id,
                    "label": j.label.value,
                    "confidence": j.confidence,
                    "rationale": j.rationale,
                    "quoted_span": j.quoted_span,
                    "grounded": j.grounded,
                    "backend": j.backend,
                }
            )

    return {
        "id": claim.id,
        "text": claim.text,
        "section": claim.section,
        "verification": (
            {
                "label": claim.verification.label.value,
                "confidence": claim.verification.confidence,
                "aggregation_rule": claim.verification.aggregation_rule,
                "decisive_source_id": claim.verification.decisive_source_id,
                "color": claim.verification.label.ui_color,
            }
            if claim.verification
            else None
        ),
        "judgments": judgments,
        "evidence": evidence,
    }


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}
