# Node 7 — Concentration-aware route diversification

## Outcome

Recovered an interrupted executor from the active checkout and validated its
existing artifacts. The implementation added bounded decayed node/edge usage,
light concentration penalties, optional local structural suspicion, persistent
state, parameter wiring, a profile, and focused tests.

## Validation

- Focused tests: 5 passed.
- Full unittest discovery: 33 tests passed; one import error because the
  optional `pqcrypto` package is not installed.
- B_dev score: `0.6870040996217148`.
- Current trunk B_dev: `0.6845301005442892`.
- B_test score: `0.38720314578550286`.
- Current trunk B_test: `0.42429066273896465`.

## Decision

Pruned. The small B_dev improvement did not generalize and B_test regressed by
`0.03708751695346179`. Candidate code was removed from the active checkout.
The original detailed executor evidence remains under
`results/7-route-diversification/`.

## Insight

Light route concentration penalties can improve the fixed dev mix and reduce
its worst-scenario Sybil exposure, but they over-diversify in the held-out
high-Sybil regime and materially reduce delivery. Future diversity mechanisms
need a stronger local gate tied to route viability or congestion, rather than
an unconditional global usage penalty.
