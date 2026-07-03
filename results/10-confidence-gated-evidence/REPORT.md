# Node 10 — Confidence-gated edge evidence

## Idea

Add an optional empirical-Bayes calibration layer to directional edge
evidence. Sparse failures are shrunk toward a neutral prior and edge penalties
are multiplied by posterior confidence. Repeated adverse outcomes still
approach the full learned penalty, while subsequent clean deliveries reduce
the posterior instead of leaving an early stochastic drop permanently
decisive.

## Changes

- Added observation and weighted-adverse-evidence helpers to `PeerScore`.
- Added an opt-in confidence-gated evidence mode to `EdgeLearningSolver`.
- Maintained a persisted pooled directional-edge statistic for the empirical
  prior.
- Kept peer reputation and all default scoring behavior unchanged.
- Preserved the version-2 state format when the mode is disabled; enabled
  profiles use version 3 with the pooled statistic.
- Wired optional parameters through `scripts/heavy_secure_search.py`.
- Added `profiles/aegis-confidence-gated-edge-v1.json`, an exact v3 parameter
  copy plus the five evidence controls.
- Added focused tests for sparse shrinkage, confidence growth, reversal after
  clean delivery, persistence, default compatibility, and peer-channel
  isolation.

## Selected configuration

- `evidence_prior_strength`: `4.0`
- `evidence_confidence_scale`: `3.0`
- `evidence_neutral_badness`: `0.0`
- `evidence_pool_weight`: `0.001`
- `evidence_gate_peer`: `false`

The pooled weight is deliberately small. Larger pooled priors penalized
previously clean edges and caused nonlinear route-selection regressions.

## Deterministic bounded calibration

Six directional-edge configurations were evaluated on the fixed B_dev suite.
No B_test command was run. Full trial metrics are in `calibration.json`.

| Trial | Prior | Confidence | Pool weight | B_dev |
| --- | ---: | ---: | ---: | ---: |
| edge-p4-c3-w05 | 4.0 | 3.0 | 0.5 | 0.6553856466930241 |
| edge-p4-c3-w0 | 4.0 | 3.0 | 0.0 | 0.6907971754473833 |
| edge-p2-c1-w0 | 2.0 | 1.0 | 0.0 | 0.6551698665907838 |
| edge-p4-c3-w005 | 4.0 | 3.0 | 0.05 | 0.6544249932756959 |
| edge-p4-c4-w0 | 4.0 | 4.0 | 0.0 | 0.6736226512979068 |
| **edge-p4-c3-w0001** | **4.0** | **3.0** | **0.001** | **0.6933176702330417** |

## B_dev result

| Metric | Trunk v3 | Node 10 | Change |
| --- | ---: | ---: | ---: |
| Robust score | 0.6845301005442892 | 0.6933176702330417 | +0.0087875696887525 |
| Delivery | 0.6034386334033215 | 0.6049261852559059 | +0.0014875518525844 |
| Drop | 0.3965613665966785 | 0.3950738147440941 | -0.0014875518525844 |
| Mean Sybil exposure | 0.12270596925994205 | 0.12244518295905275 | -0.0002607863008893 |
| Maximum Sybil exposure | 0.14121545069491892 | 0.13839219272417505 | -0.00282325797074387 |
| Mean latency | 1.8677421621665435 | 1.8488508970488782 | -0.01889126511766537 |
| Mean hops | 6.1127610281512155 | 6.059211965918315 | -0.05354906223290046 |
| Mean loss risk | 0.2560795343086617 | 0.2571760438790296 | +0.0010965095703679 |

The candidate beats the validated trunk by `0.0087875696887525` absolute
(`1.2837%`) while improving delivery, drop rate, mean/max Sybil exposure,
latency, and route length. Mean loss risk increases slightly.

## Validation

- `python3 -m py_compile aegis_router/solvers.py scripts/heavy_secure_search.py tests/test_confidence_gated_evidence.py`
- `python3 -m unittest tests.test_confidence_gated_evidence tests.test_edge_learning tests.test_reason_aware_learning -v`
  - 10 tests passed.
- `python3 -m unittest discover -s tests -v`
  - 34 functional tests passed.
  - One pre-existing import error remains because optional package `pqcrypto`
    is not installed; no package installation was attempted.
- Exact base-profile equality assertion passed for every original v3
  parameter.
- B_test was run once by the coordinator after the B_dev win qualified the
  candidate for merge verification.

## B_test merge verification

- Candidate: `0.4151347276777513`
- Validated trunk: `0.42429066273896465`
- Delta: `-0.009155935061213338`
- Delivery: `0.5099696513115667`
- Mean/max Sybil exposure: `0.19190640163024494`
- Drop: `0.49003034868843337`
- Mean latency: `1.8581712648708641`
- Mean hops: `5.949832962874758`

The candidate failed held-out verification and was rejected without merge.

## Insight

The useful operating point is highly conservative: most of the prior must
remain neutral, with only a tiny empirical pooled component. Strong pooled
priors make clean edges inherit network-wide failure evidence and destabilize
route selection. Confidence-gating directional evidence alone is sufficient
to improve delivery and Sybil robustness without changing the coarse peer
reputation channel.

Held-out verification shows that this fixed global prior still does not
transfer to the high-Sybil regime. Future confidence mechanisms should be
conditioned on observable local regime or topology.
