# Node 13 Report

## Idea
Surprise-gated adverse edge feedback with delivery-preserving relief.

## Changes
- Added weighted adverse evidence fields to `PeerScore`.
- Passed each hop's advertised link loss from `EventDrivenSimulator` into solver feedback.
- Added an `EdgeLearningSolver` surprise gate that discounts ordinary losses on high-advertised-loss edges and after recent clean delivery.
- Kept the existing peer reputation channel intact after the first variant regressed; the final scored variant gates only directional edge badness.

## Implementation Choices
- The final variant preserves raw peer reputation and learned peer penalties because fully gating peer feedback reduced delivery and did not improve mean Sybil exposure.
- Directional edge penalties use `surprise_adverse - delivery_relief`, plus bounded Sybil/link/loop components.
- The implementation stayed deterministic, local, and source-only inside `/tmp/aegis-arbor-node13-slim.XF4a2a`.

## Baseline vs Result
- Current trunk B_dev: `0.6845301005442892`
- First peer-plus-edge gated B_dev: `0.6781737158329136`
- Final edge-only gated B_dev: `0.6931173548326843`
- Current trunk B_test: `0.42429066273896465`
- Single authorized B_test verification: `0.42070455354319664`

## Score
`0.6931173548326843` on B_dev.

## Analysis
The edge-only surprise gate improved B_dev by preserving delivery while lowering mean Sybil exposure on the fixed dev suite. It did not transfer to the held-out high-Sybil scenario: B_test remained below the validated trunk despite slightly better delivery than several earlier rejected candidates. The mechanism appears to relieve too much directional evidence under the heavier Sybil regime, leaving max/mean Sybil exposure too high for held-out verification.

## Insights
Surprise-gating directional edge evidence is useful on fixed dev and less blunt than topology-only suppression, but it needs a regime signal before relief is allowed in high-Sybil conditions. Future variants should condition delivery relief on local Sybil pressure or scenario context rather than applying the same relief schedule everywhere.

## Validation
- `python3 -m py_compile aegis_router/solvers.py aegis_router/event_sim.py scripts/heavy_secure_search.py .arbor/sessions/aegis-router-20260621/benchmark_eval.py`
- `python3 -m unittest tests.test_edge_learning tests.test_reason_aware_learning tests.test_adaptive_risk_solver tests.test_event_sim -v`: 9 passed.
- `python3 -m unittest discover -s tests -v`: 28 non-PQ tests passed; `test_postquantum_crypto` failed to import because optional package `pqcrypto` is not installed.
- B_test was run exactly once after the B_dev win qualified the candidate; it was not used for tuning.
