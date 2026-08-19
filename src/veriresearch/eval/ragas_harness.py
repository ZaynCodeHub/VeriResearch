"""Ragas evaluation over the golden topic set: faithfulness + answer relevancy.

Faithfulness answers a different question than our own Verifier does, and
that's the point of running both: faithfulness scores the *final report text*
against the *retrieved context* using Ragas's own LLM-as-judge, an external
check that doesn't share any code path with `verify/verifier.py`. Agreement
between the two is evidence the in-house verifier isn't just grading its own
homework; disagreement is worth investigating on its own.

Requires `GROK_API_KEY` (Ragas needs an LLM to judge with) and, for
answer_relevancy specifically, an embedding model — a local
`sentence-transformers` model by default, so no second API key is needed.
Without a key, `run_ragas_eval` returns a `status="skipped"` result rather
than raising, consistent with the rest of the project running with zero
configuration; `pytest` never imports `ragas` at all.
"""

from __future__ import annotations

from typing import Any

from ..config import SETTINGS
from ..graph import run
from .golden_topics import GOLDEN_TOPICS

EMBEDDING_MODEL = "sentence-transformers/all-MiniLM-L6-v2"


def _report_context(result: dict) -> tuple[str, list[str]]:
    """(answer, contexts) for one graph run: the published report text, and the
    raw text of every source cited by a claim that made it into the report."""
    report = result.get("report")
    answer = report.markdown if report else ""

    claims = result.get("claims", {})
    sources = result.get("sources", {})
    published_ids = set()
    if report:
        published_ids = {cid for section in report.sections for cid in section.claim_ids}

    contexts: list[str] = []
    seen_source_ids: set[str] = set()
    for claim in claims.values():
        if claim.id not in published_ids:
            continue
        for source_id in claim.source_ids:
            if source_id in seen_source_ids or source_id not in sources:
                continue
            seen_source_ids.add(source_id)
            contexts.append(sources[source_id].raw_text)

    return answer, contexts


def build_dataset(topics: list[str], mode: str = "full") -> list[dict[str, Any]]:
    samples = []
    for topic in topics:
        result = run(topic, mode=mode)
        answer, contexts = _report_context(result)
        if not answer.strip() or not contexts:
            continue  # nothing published for this topic — Ragas needs both
        samples.append({"user_input": topic, "response": answer, "retrieved_contexts": contexts})
    return samples


def run_ragas_eval(topics: list[str] | None = None, mode: str = "full") -> dict[str, Any]:
    topics = topics or GOLDEN_TOPICS

    if not SETTINGS.planner.has_llm:
        return {
            "status": "skipped",
            "reason": "GROK_API_KEY is not set — Ragas needs an LLM to judge "
            "faithfulness and answer relevancy. Set it and re-run.",
        }

    try:
        from langchain_xai import ChatXAI
        from ragas import EvaluationDataset, evaluate
        from ragas.embeddings import LangchainEmbeddingsWrapper
        from ragas.llms import LangchainLLMWrapper
        from ragas.metrics import answer_relevancy, faithfulness
    except ImportError as exc:
        if "vertexai" in str(exc).lower():
            # Known upstream conflict as of ragas 0.4.3: it imports
            # langchain_community.chat_models.vertexai unconditionally at module
            # load time, which that package now splits out into the separate
            # langchain-google-vertexai integration. Meanwhile ragas's langchain/
            # langchain-community deps want langchain-core<1.0, and this project's
            # langgraph>=1.2 + langchain-xai>=1.3 need langchain-core>=1.4 — the
            # two can't be pinned to mutually compatible versions in one venv today.
            # Not a missing-install; re-running pip install won't fix it. Run the
            # Ragas eval from a separate virtualenv against the same golden set
            # until upstream reconciles these, or track the ragas issue tracker.
            reason = (
                f"Ragas has a known dependency conflict with this project's LangGraph "
                f"stack, not a missing install ({exc}). See the comment in "
                "eval/ragas_harness.py for details; run the Ragas eval from a separate "
                "virtualenv in the meantime."
            )
        else:
            reason = f"Ragas eval dependencies not installed ({exc}). Run `pip install -e '.[eval]'`."
        return {"status": "skipped", "reason": reason}

    samples = build_dataset(topics, mode=mode)
    if not samples:
        return {
            "status": "skipped",
            "reason": "No topic produced a publishable report with cited sources — "
            "nothing for Ragas to score. Set TAVILY_API_KEY for live search coverage.",
        }

    try:
        from langchain_huggingface import HuggingFaceEmbeddings

        embeddings = LangchainEmbeddingsWrapper(HuggingFaceEmbeddings(model_name=EMBEDDING_MODEL))
    except ImportError:
        return {
            "status": "skipped",
            "reason": "sentence-transformers not installed (needed for answer_relevancy's "
            "embedding step). Run `pip install -e '.[eval]'`.",
            "samples_attempted": len(samples),
        }

    # ChatXAI defaults to reading XAI_API_KEY; pass this project's GROK_API_KEY
    # explicitly so a single env var covers both the pipeline and this eval.
    llm = LangchainLLMWrapper(
        ChatXAI(model=SETTINGS.verifier.llm_model, api_key=SETTINGS.planner.grok_api_key)
    )
    dataset = EvaluationDataset.from_list(samples)

    result = evaluate(
        dataset=dataset,
        metrics=[faithfulness, answer_relevancy],
        llm=llm,
        embeddings=embeddings,
    )

    scores_df = result.to_pandas()
    return {
        "status": "ok",
        "n_samples": len(samples),
        "mean_faithfulness": float(scores_df["faithfulness"].mean()),
        "mean_answer_relevancy": float(scores_df["answer_relevancy"].mean()),
        "per_sample": scores_df.to_dict(orient="records"),
    }
