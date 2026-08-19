#!/usr/bin/env python3
"""The before/after comparison: the headline metric.

For each golden topic, runs the SAME planner/researcher/writer output through
two arms:

    before  mode="baseline" — planner -> researcher -> writer -> verifier,
            verifier in measure-only mode (nothing gets dropped or flagged).
            This is what a planner+researcher+writer system would have
            shipped, before a verifier existed to check it. "before_rate" is
            the fraction of everything it drafted that an independent audit
            confirms SUPPORTED.
    after   mode="full" — the same pipeline, but the verifier enforces:
            UNSUPPORTED/CONTRADICTED claims are dropped, PARTIALLY_SUPPORTED
            ones are flagged, before anything publishes. "after_rate" is the
            fraction of what actually gets PUBLISHED that is SUPPORTED, and
            "caught_rate" is the fraction of the original draft that would
            have shipped wrong and got caught instead.

Runs fully offline by default (heuristic judge + the bundled local corpus /
honest placeholder — see nodes/local_corpus.py): no API keys required, though
the corpus-backed topics are what makes the offline numbers meaningful. Set
GROK_API_KEY / TAVILY_API_KEY for a live-search, LLM-written, LLM-judged
run instead.

Usage:
    python scripts/compare_before_after.py                # all golden topics
    python scripts/compare_before_after.py --limit 4       # quick smoke run
"""

from __future__ import annotations

import argparse
import sys
import time
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from veriresearch.eval.golden_topics import GOLDEN_TOPICS  # noqa: E402
from veriresearch.graph import run  # noqa: E402

# Colours from the project's validated categorical palette (see dataviz skill):
# slot 1 (blue) / slot 6 (green) — validated as a CVD-safe pair for exactly
# this two-series comparison; status green/red reserved for the caught-claims
# panel, matching state.py's SUPPORTED/CONTRADICTED colour convention.
COLOR_BEFORE = "#2a78d6"
COLOR_AFTER = "#008300"
COLOR_GOOD = "#0ca30c"
COLOR_CRITICAL = "#d03b3b"
INK_PRIMARY = "#0b0b0b"
INK_SECONDARY = "#52514e"
INK_MUTED = "#898781"
GRIDLINE = "#e1e0d9"
SURFACE = "#fcfcfb"


@dataclass
class TopicResult:
    topic: str
    claims_checked: int
    before_supported_rate: float
    before_publishable_rate: float
    after_published: int
    after_supported_of_published: float
    caught_rate: float
    dropped: int
    flagged: int
    has_real_content: bool


def _safe_div(a: float, b: float) -> float:
    return a / b if b else 0.0


def evaluate_topic(topic: str) -> TopicResult:
    baseline = run(topic, mode="baseline")
    full = run(topic, mode="full")

    before_summary = baseline["verification_summary"]
    full_summary = full["verification_summary"]
    claims_checked = full_summary.get("claims_checked", 0)

    dropped = len(full["report"].dropped_claim_ids) if full["report"] else 0
    flagged = len(full["report"].flagged_claim_ids) if full["report"] else 0
    after_published = claims_checked - dropped
    after_supported_count = full_summary.get("label_counts", {}).get("SUPPORTED", 0)

    # Did the researcher actually find anything to check, or is every source the
    # honest "no search backend configured" placeholder (nodes/researcher.py)?
    # This — not claims_checked — is what separates a real signal from a topic
    # where there was nothing offline to say anything about.
    has_real_content = any(
        s.url != "offline://no-search-backend" for s in full.get("sources", {}).values()
    )

    return TopicResult(
        topic=topic,
        claims_checked=claims_checked,
        before_supported_rate=before_summary.get("supported_rate", 0.0),
        before_publishable_rate=before_summary.get("publishable_rate", 0.0),
        after_published=after_published,
        after_supported_of_published=_safe_div(after_supported_count, after_published),
        caught_rate=_safe_div(dropped, claims_checked),
        dropped=dropped,
        flagged=flagged,
        has_real_content=has_real_content,
    )


def write_markdown(results: list[TopicResult], out_path: Path) -> None:
    n = len(results)
    # Topics where every source is the honest "no search backend configured"
    # placeholder (no offline corpus match, no TAVILY_API_KEY) have no real content
    # to check — the writer doesn't draft claims from that boilerplate (see
    # nodes/writer.py), so before/after are both 0% by construction. Averaging
    # those in as "0% supported" would misrepresent the metric as "the system
    # failed on this topic" when really "there was nothing offline to say." They're
    # still listed per-topic, just excluded from the aggregate.
    informative = [r for r in results if r.has_real_content]
    degenerate = [r for r in results if not r.has_real_content]
    m = len(informative) or 1
    mean_before = sum(r.before_supported_rate for r in informative) / m
    mean_after = sum(r.after_supported_of_published for r in informative) / m
    total_claims = sum(r.claims_checked for r in results)
    total_dropped = sum(r.dropped for r in results)
    total_flagged = sum(r.flagged for r in results)

    lines = [
        "# Before / after: verifying the verifier",
        "",
        f"Golden set: {n} topics (`src/veriresearch/eval/golden_topics.py`).",
        "",
        "**Before** = `mode=\"baseline\"` — planner+researcher+writer, verifier "
        "measuring only (nothing enforced). Fraction of every claim drafted that an "
        "independent audit confirms SUPPORTED.",
        "",
        "**After** = `mode=\"full\"` — same pipeline, verifier enforces. Fraction of "
        "what actually gets *published* that is SUPPORTED, after UNSUPPORTED/"
        "CONTRADICTED claims are dropped.",
        "",
        f"Mean is over the **{len(informative)} topics with claims to check** "
        f"({len(degenerate)} had none — see note below).",
        "",
        f"| Metric | Before | After |",
        f"|---|---|---|",
        f"| Mean SUPPORTED rate | {mean_before:.1%} | {mean_after:.1%} |",
        f"| Total claims drafted | {total_claims} | — |",
        f"| Claims caught (dropped before publish) | — | {total_dropped} ({_safe_div(total_dropped, total_claims):.1%}) |",
        f"| Claims flagged (published, PARTIALLY_SUPPORTED) | — | {total_flagged} |",
        "",
        "## Per-topic",
        "",
        "| Topic | Claims | Before SUPPORTED | After SUPPORTED (of published) | Caught |",
        "|---|---|---|---|---|",
    ]
    for r in results:
        if not r.has_real_content:
            note = f"{r.claims_checked} uncited, all caught" if r.claims_checked else "0"
            lines.append(f"| {r.topic} | {note} | — *(no offline content)* | — | — |")
        else:
            lines.append(
                f"| {r.topic} | {r.claims_checked} | {r.before_supported_rate:.1%} | "
                f"{r.after_supported_of_published:.1%} | {r.dropped} ({r.caught_rate:.1%}) |"
            )
    lines.append("")
    if degenerate:
        lines.append(
            f"*{len(degenerate)} topics matched none of the "
            "bundled local corpus entries (`nodes/local_corpus.py`) and no "
            "`TAVILY_API_KEY` was set, so the researcher had no real content to hand the "
            "writer, and the honest offline placeholder isn't drafted into claims (see "
            "`nodes/writer.py`). Set `TAVILY_API_KEY` for real search coverage on these.*"
        )
        lines.append("")
    out_path.write_text("\n".join(lines), encoding="utf-8")


def render_chart(results: list[TopicResult], out_path: Path) -> None:
    try:
        import matplotlib

        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
        import matplotlib.ticker as mticker
    except ImportError:
        print("matplotlib not installed (pip install -e '.[eval]') — skipping chart.")
        return

    # Topics with no real content (no offline corpus match, no live search) have
    # nothing to plot — see write_markdown's `degenerate` note. Charting them as 0%
    # bars would read as "the system failed here" rather than "nothing to check."
    plotted = [r for r in results if r.has_real_content] or results

    topics = [r.topic if len(r.topic) <= 28 else r.topic[:25] + "..." for r in plotted]
    before = [r.before_supported_rate * 100 for r in plotted]
    after = [r.after_supported_of_published * 100 for r in plotted]

    fig, ax = plt.subplots(figsize=(11, max(4, 0.5 * len(plotted) + 1)))
    fig.patch.set_facecolor(SURFACE)
    ax.set_facecolor(SURFACE)

    y = range(len(plotted))
    bar_h = 0.34
    ax.barh([i + bar_h / 2 for i in y], before, height=bar_h, color=COLOR_BEFORE, label="Before (verifier measures only)")
    ax.barh([i - bar_h / 2 for i in y], after, height=bar_h, color=COLOR_AFTER, label="After (verifier enforces)")

    ax.set_yticks(list(y))
    ax.set_yticklabels(topics, color=INK_PRIMARY, fontsize=9)
    ax.invert_yaxis()
    ax.set_xlim(0, 100)
    ax.xaxis.set_major_formatter(mticker.PercentFormatter())
    ax.set_xlabel("% of claims SUPPORTED", color=INK_SECONDARY)
    ax.tick_params(colors=INK_SECONDARY)
    ax.grid(axis="x", color=GRIDLINE, linewidth=0.8, zorder=0)
    ax.set_axisbelow(True)
    for spine in ("top", "right", "left"):
        ax.spines[spine].set_visible(False)
    ax.spines["bottom"].set_color(INK_MUTED)

    ax.set_title(
        "VeriResearch: independently-verified SUPPORTED rate, before vs after the Verifier",
        color=INK_PRIMARY,
        fontsize=12,
        loc="left",
        pad=14,
    )
    # Below the axes, not inside the plot area — bars run edge-to-edge at 100%,
    # so any in-plot legend position risks sitting on top of a bar.
    legend = ax.legend(
        loc="upper center",
        bbox_to_anchor=(0.5, -0.14),
        ncol=2,
        frameon=False,
        fontsize=9,
    )
    for text in legend.get_texts():
        text.set_color(INK_SECONDARY)

    fig.tight_layout()
    fig.savefig(out_path, dpi=150, facecolor=SURFACE, bbox_inches="tight")
    plt.close(fig)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--limit", type=int, default=None, help="only run the first N golden topics")
    parser.add_argument("--out-dir", default=str(ROOT / "eval"))
    args = parser.parse_args()

    topics = GOLDEN_TOPICS[: args.limit] if args.limit else GOLDEN_TOPICS
    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    print(f"Running {len(topics)} topics through baseline + full graphs...")
    results: list[TopicResult] = []
    t0 = time.perf_counter()
    for i, topic in enumerate(topics, 1):
        print(f"  [{i}/{len(topics)}] {topic}")
        results.append(evaluate_topic(topic))
    elapsed = time.perf_counter() - t0

    md_path = out_dir / "before_after.md"
    png_path = out_dir / "before_after.png"
    write_markdown(results, md_path)
    render_chart(results, png_path)

    informative = [r for r in results if r.has_real_content]
    m = len(informative) or 1
    mean_before = sum(r.before_supported_rate for r in informative) / m
    mean_after = sum(r.after_supported_of_published for r in informative) / m
    print(f"\nDone in {elapsed:.1f}s.")
    print(
        f"Mean SUPPORTED rate over {len(informative)}/{len(results)} topics with real "
        f"content — before: {mean_before:.1%}  after: {mean_after:.1%}"
    )
    print(f"Wrote {md_path}")
    print(f"Wrote {png_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
