# Before / after: verifying the verifier

Golden set: 4 topics (`src/veriresearch/eval/golden_topics.py`).

**Before** = `mode="baseline"` — planner+researcher+writer, verifier measuring only (nothing enforced). Fraction of every claim drafted that an independent audit confirms SUPPORTED.

**After** = `mode="full"` — same pipeline, verifier enforces. Fraction of what actually gets *published* that is SUPPORTED, after UNSUPPORTED/CONTRADICTED claims are dropped.

Mean is over the **4 topics with claims to check** (0 had none — see note below).

| Metric | Before | After |
|---|---|---|
| Mean SUPPORTED rate | 82.5% | 100.0% |
| Total claims drafted | 138 | — |
| Claims caught (dropped before publish) | — | 6 (4.3%) |
| Claims flagged (published, PARTIALLY_SUPPORTED) | — | 0 |

## Per-topic

| Topic | Claims | Before SUPPORTED | After SUPPORTED (of published) | Caught |
|---|---|---|---|---|
| the James Webb Space Telescope | 36 | 83.3% | 100.0% | 0 (0.0%) |
| the Great Wall of China | 36 | 83.3% | 100.0% | 6 (16.7%) |
| Marie Curie's scientific legacy | 30 | 80.0% | 100.0% | 0 (0.0%) |
| the Wright brothers' first flight | 36 | 83.3% | 100.0% | 0 (0.0%) |
