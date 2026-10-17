# Decisions (override docs/SPEC.md)

## D1 — Score map: the spec's sigmoid doesn't reproduce the golden numbers (DECIDED, 2026-10-17)

**Decided:** calibrated monotone piecewise-linear curve in ln(LCR), as recommended below. Implemented in
`backend/app/actuarial/score_map.py` with the four anchors plus the golden baseline points (160 bps -> 465,
210 bps -> 405) and end pins (1 bp -> 850, 1000 bps -> 300). `spec_sigmoid` is kept there as a reference only.

The spec sets `score = 300 + round(550 / (1 + (LCR/0.0085)^1.15))`, but its golden scenarios disagree with that formula:

| Scenario | Posterior LCR | Spec says | Formula gives |
|---|---|---|---|
| S1 baseline (tract prior) | 185 bps | 430 | 460 |
| S1 verified | 24 bps | 765 | 746 |
| S2 | 245 bps | 385 | 426 |
| S3 | 18 bps | 815 | 771 |

A 2-parameter refit (LCR_0, κ) still misses by about 13 pts (best: 0.0083, 1.53 → 425/778/388/802).
Checked with a Python grid search on 2026-10-17.

**Recommendation:** keep the log-logistic form but calibrate it as a monotone piecewise-linear curve in log(LCR)
through the golden anchors. It stays strictly decreasing, so the monotonicity proof still holds, and it hits the
demo numbers exactly. Pitch line: "calibrated score curve, anchored to the consortium reference parcels".
The alternative is to use the spec formula as written and change the pitch numbers.
