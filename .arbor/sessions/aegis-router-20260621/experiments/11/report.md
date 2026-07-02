# Node 11 — Sibling-relative posterior evidence

## Idea

Calibrate directional edge evidence against the currently available sibling
routes at each decision. Each edge is shrunk toward its siblings' observed
adverse-evidence rate, only positive posterior excess is penalized, sparse
evidence is confidence-gated, and the final penalty is bounded. Uniform
regime-wide failure pressure therefore cancels instead of producing a global
absolute penalty.

## Changes

- Added observation-count and weighted-adverse-evidence helpers to `PeerScore`
  without changing its legacy `badness` value.
- Added an opt-in sibling-relative mode to `EdgeLearningSolver`.
- Preserved the existing risk viability set and compared only routes that were
  available to the current decision.
- Kept the legacy `next_hop` and absolute edge-badness behavior when
  `sibling_relative_strength` is zero.
- Wired optional settings through `scripts/heavy_secure_search.py`.
- Added `profiles/aegis-sibling-relative-edge-v1.json`, which preserves every
  original v3 parameter and adds only the sibling-relative controls.
- Added focused tests for competitive cancellation, sparse shrinkage, bounded
  penalties, single-route safety, route selection, and default compatibility.

## Selected configuration

- `sibling_relative_strength`: `2.0`
- `sibling_prior_strength`: `2.0`
- `sibling_confidence_scale`: `1.0`
- `sibling_relative_margin`: `0.0`
- `sibling_penalty_cap`: `1.0`

This setting won a six-point deterministic calibration on a small synthetic
scenario using three fixed seeds. The calibration did not use B_test or alter
an official benchmark scenario.

## Baseline vs Result

| Metric | Validated trunk | Node 11 | Change |
| --- | ---: | ---: | ---: |
| B_dev robust score | 0.6845301005442892 | 0.6732324563179362 | -0.011297644226353 |
| Delivery | 0.6034386334033215 | 0.5956960188748307 | -0.0077426145284908 |
| Drop | 0.3965613665966785 | 0.4043039811251693 | +0.0077426145284908 |
| Mean Sybil exposure | 0.12270596925994205 | 0.12238000314729325 | -0.0003259661126488 |
| Maximum Sybil exposure | 0.14121545069491892 | 0.14179548302856596 | +0.00058003233364704 |

The unchanged benchmark harness does not expose valid aggregate latency and
hop values in its JSON output: those two fields fall back to mean risk. They
are therefore intentionally omitted from the official comparison rather than
reported as route metrics.

## Validation

- `python3 -m py_compile aegis_router/solvers.py scripts/heavy_secure_search.py tests/test_sibling_relative_evidence.py`
- `python3 -m unittest tests.test_sibling_relative_evidence tests.test_edge_learning tests.test_reason_aware_learning -v`
  - 10 tests passed.
- `python3 -m unittest discover -s tests -v`
  - 34 functional tests passed.
  - One pre-existing import error remains because optional package `pqcrypto`
    is not installed; no package installation was attempted.
- Exact equality check passed for every original v3 profile parameter.
- `git diff --check` passed.
- B_test was not run.

## Score

`0.6732324563179362`

## Analysis

The local comparison behaves as designed in focused tests and slightly lowers
mean Sybil exposure, but it reduces delivery and increases worst-case Sybil
exposure on B_dev. Replacing the absolute directional edge signal with only
positive sibling-relative excess removes too much useful evidence when all
available alternatives are degraded or unevenly observed.

## Insight

Decision-local centering solves the global-prior transfer problem
mechanistically, but pure relative evidence is not sufficient: local sibling
sets can share correlated risk while still differing in absolute safety.
Future work should retain a weak, topology-conditioned absolute floor or gate
relative centering on sibling observation coverage instead of fully replacing
the absolute edge channel.

## Decision

Reject. The candidate does not beat the validated B_dev trunk, so B_test is
not authorized and the code must not be merged into the active trunk.
