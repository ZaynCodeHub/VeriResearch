#!/usr/bin/env python3
"""Ragas evaluation CLI: faithfulness + answer relevancy over the golden set.

    python scripts/run_eval.py                 # all golden topics, mode=full
    python scripts/run_eval.py --limit 5

Requires GROK_API_KEY (Ragas' own LLM-as-judge) and `pip install -e
".[eval]"`. Without a key, writes a report explaining what's missing instead
of failing — see eval/ragas_harness.py.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from veriresearch.eval.golden_topics import GOLDEN_TOPICS  # noqa: E402
from veriresearch.eval.ragas_harness import run_ragas_eval  # noqa: E402


def write_report(result: dict, out_path: Path) -> None:
    lines = ["# Ragas evaluation report", ""]

    if result["status"] == "skipped":
        lines += [
            "**Skipped.**",
            "",
            result["reason"],
            "",
            "This is expected in a zero-config environment — see the project README's "
            "\"runs with no API keys\" quickstart. Set `GROK_API_KEY` (and run "
            "`pip install -e \".[eval]\"`) for a live evaluation.",
        ]
    else:
        lines += [
            f"Samples evaluated: {result['n_samples']}",
            "",
            "| Metric | Mean |",
            "|---|---|",
            f"| Faithfulness | {result['mean_faithfulness']:.3f} |",
            f"| Answer relevancy | {result['mean_answer_relevancy']:.3f} |",
            "",
            "Faithfulness is Ragas's own LLM-as-judge check of the report text "
            "against retrieved context — an external cross-check against this "
            "project's own Verifier (`verify/verifier.py`), computed with no shared "
            "code path. Persistent disagreement between the two is worth digging into.",
            "",
            "## Per-sample",
            "",
            "| Topic | Faithfulness | Answer relevancy |",
            "|---|---|---|",
        ]
        for row in result["per_sample"]:
            topic = row.get("user_input", "")
            lines.append(f"| {topic} | {row.get('faithfulness', float('nan')):.3f} | {row.get('answer_relevancy', float('nan')):.3f} |")

    out_path.write_text("\n".join(lines), encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument("--out", default=str(ROOT / "eval" / "ragas_report.md"))
    args = parser.parse_args()

    topics = GOLDEN_TOPICS[: args.limit] if args.limit else GOLDEN_TOPICS
    print(f"Running Ragas evaluation over {len(topics)} topics...")
    result = run_ragas_eval(topics)

    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    write_report(result, out_path)

    if result["status"] == "skipped":
        print(f"Skipped: {result['reason']}")
    else:
        print(f"Faithfulness: {result['mean_faithfulness']:.3f}  Answer relevancy: {result['mean_answer_relevancy']:.3f}")
    print(f"Wrote {out_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
