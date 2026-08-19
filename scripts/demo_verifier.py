#!/usr/bin/env python3
"""Verifier smoke demo — runs before any of the pipeline exists.

    python scripts/demo_verifier.py                 # offline heuristic judge
    VERIFIER_BACKEND=llm python scripts/demo_verifier.py   # Grok-as-judge

Four claims are checked against one source document, one per verification label,
plus a fifth that demonstrates the grounding guardrail catching a judge that
fabricated its own supporting quote.
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

if sys.stdout.encoding and sys.stdout.encoding.lower() != "utf-8":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from veriresearch.fixtures import (  # noqa: E402
    DEMO_CLAIMS,
    DEMO_SOURCES,
    FABRICATED_JUDGE_RESPONSE,
    HALLUCINATED_QUOTE_CLAIM,
    JWST_SOURCE,
)
from veriresearch.judges import get_judge  # noqa: E402
from veriresearch.state import VerificationLabel  # noqa: E402
from veriresearch.verify import Verifier  # noqa: E402

RESET = "\033[0m"
COLOURS = {
    VerificationLabel.SUPPORTED: "\033[92m",
    VerificationLabel.PARTIALLY_SUPPORTED: "\033[93m",
    VerificationLabel.UNSUPPORTED: "\033[91m",
    VerificationLabel.CONTRADICTED: "\033[91m",
}
GLYPH = {
    VerificationLabel.SUPPORTED: "[+]",
    VerificationLabel.PARTIALLY_SUPPORTED: "[~]",
    VerificationLabel.UNSUPPORTED: "[?]",
    VerificationLabel.CONTRADICTED: "[X]",
}


def paint(label: VerificationLabel, text: str, colour: bool) -> str:
    if not colour:
        return text
    return f"{COLOURS[label]}{text}{RESET}"


def rule(char: str = "-", width: int = 78) -> str:
    return char * width


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--backend", default=None, help="heuristic | llm | auto")
    parser.add_argument("--no-colour", action="store_true")
    args = parser.parse_args()
    colour = not args.no_colour and sys.stdout.isatty()

    verifier = Verifier(judge=get_judge(args.backend))

    print(rule("="))
    print("VeriResearch — verifier smoke test")
    print(f"judge backend : {verifier.backend_name}")
    print(f"thresholds    : support>={verifier.config.support_threshold} "
          f"partial>={verifier.config.partial_threshold} "
          f"contradiction>={verifier.config.contradiction_threshold}")
    print(rule("="))
    print(f"\nSOURCE [{JWST_SOURCE.id}] {JWST_SOURCE.url}")
    print(f"  {len(JWST_SOURCE.raw_text)} chars, sha={JWST_SOURCE.content_hash}\n")

    passed = failed = 0

    for claim, expected, why in DEMO_CLAIMS:
        verification = verifier.verify_claim(claim, DEMO_SOURCES)
        ok = verification.label is expected
        passed, failed = (passed + 1, failed) if ok else (passed, failed + 1)

        print(rule())
        print(f"CLAIM   {claim.text}")
        print(f"WHY     {why}")
        badge = f"{GLYPH[verification.label]} {verification.label.value}"
        print(f"VERDICT {paint(verification.label, badge, colour)}  "
              f"confidence={verification.confidence:.2f}  "
              f"rule={verification.aggregation_rule}")
        print(f"EXPECT  {expected.value}  ->  {'PASS' if ok else 'FAIL'}")

        for j in verification.judgments:
            print(f"  judged against {j.source_id} via {j.backend}")
            print(f"    raw label   : {j.label.value} @ {j.confidence:.2f}")
            print(f"    rationale   : {j.rationale}")
            if j.quoted_span:
                shown = j.quoted_span if len(j.quoted_span) <= 200 else j.quoted_span[:197] + "..."
                mark = "grounded" if j.grounded else "NOT GROUNDED (quote not in source)"
                print(f"    checked text: \"{shown}\"")
                print(f"    grounding   : {mark}")
        print()

    # ---- grounding guardrail --------------------------------------------- #
    print(rule("="))
    print("GUARDRAIL: judge fabricates its supporting quote")
    print(rule("="))

    from veriresearch.judges.llm_judge import LLMJudge
    from veriresearch.llm import StubClient

    rigged = LLMJudge(client=StubClient(default=FABRICATED_JUDGE_RESPONSE), samples=1)
    rigged_verifier = Verifier(judge=rigged)
    claim = HALLUCINATED_QUOTE_CLAIM
    verification = rigged_verifier.verify_claim(claim, DEMO_SOURCES)
    judgment = verification.judgments[0]

    print(f"\nCLAIM   {claim.text}")
    print("JUDGE   returned SUPPORTED @ 0.95, quoting:")
    print(f"        \"{judgment.quoted_span}\"")
    print("        ...which does not appear anywhere in the source.")
    print(f"GROUNDED {judgment.grounded}")
    print(f"RESULT  confidence 0.95 -> {judgment.confidence:.2f} "
          f"(x{rigged_verifier.config.ungrounded_penalty} ungrounded penalty)")
    badge = f"{GLYPH[verification.label]} {verification.label.value}"
    print(f"VERDICT {paint(verification.label, badge, colour)} "
          f"— demoted out of SUPPORTED, so it cannot ship with a green tick")

    guardrail_ok = (
        not judgment.grounded and verification.label is not VerificationLabel.SUPPORTED
    )
    passed, failed = (passed + 1, failed) if guardrail_ok else (passed, failed + 1)
    print(f"EXPECT  not SUPPORTED  ->  {'PASS' if guardrail_ok else 'FAIL'}")

    print(f"\n{rule('=')}")
    print(f"{passed} passed, {failed} failed")
    print(rule("="))
    return 0 if failed == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
