# Node 6 — Adversarial domain-randomized learning curriculum

## Idea

Warm persistent `EdgeLearningSolver` state on a small deterministic curriculum
covering graph size and density, Sybil pressure and stealth, churn, and
congestion drift. Official scoring remains the unchanged five-scenario B_dev
benchmark with seeds `20260612..20260614`. B_test was not run.

## Implementation

- Added deterministic auxiliary environment generation from the explicit seed
  `6106001`.
- Added five short curriculum environments spanning 64–160 nodes, degree 4–8,
  Sybil pressure up to 26%, stealth up to 100%, churn, and congestion drift.
- Added persistent context priors to `EdgeLearningSolver`.
- Added optional curriculum construction to the existing edge evaluation path.
- Added a curriculum profile and an identical no-curriculum control profile.
- Added focused tests for determinism, coverage, persistence, identity cleanup,
  and transfer to unseen node IDs.

## Transfer assumption

Raw `(node_id, edge_id)` memories cannot transfer between independently
generated graphs. The curriculum therefore learns coarse, ID-independent
context statistics based only on observable link metrics and local neighbor
degree. After every auxiliary environment, peer reputation, raw edge scores,
recent adaptive windows, and edge-to-context bindings are cleared. Only the
context statistics and global risk budget remain persistent.

This is a deliberately limited transfer model. It can generalize recurring
observable risk patterns, but it cannot identify a stealth Sybil whose metrics
and local structure are indistinguishable from honest peers until behavioral
feedback arrives.

## B_dev results

| Variant | Robust score | Delivery | Drop | Mean Sybil | Max Sybil | Latency | Hops |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| Same solver, no curriculum | 0.642764 | 0.592006 | 0.407994 | 0.130604 | 0.161257 | 1.855291 | 6.071755 |
| Curriculum, penalty 0.10 | 0.664944 | 0.600966 | 0.399034 | 0.126744 | 0.151627 | 1.894187 | 6.188296 |
| Curriculum, penalty 0.20 | 0.669992 | 0.598004 | 0.401996 | 0.124541 | 0.139642 | 1.876881 | 6.180363 |
| **Curriculum, penalty 0.35** | **0.674405** | **0.594432** | **0.405568** | **0.119427** | **0.136534** | **1.841021** | **6.041305** |
| Curriculum, penalty 0.50 | 0.657282 | 0.592106 | 0.407894 | 0.121282 | 0.136310 | 1.854403 | 6.081771 |
| Current trunk | 0.684530 | — | — | — | — | — | — |

The selected curriculum improves its exact no-curriculum control by
`+0.031641` robust score, lowers mean Sybil exposure by `0.011177`, lowers
maximum Sybil exposure by `0.024723`, and slightly improves latency and route
length. Its absolute score remains `0.010125` below the current trunk
(`-1.48%`), so the node does not justify promotion.

## Validation

- `python3 -m py_compile` passed for all changed Python files.
- 10 focused tests passed:
  - `tests.test_domain_randomized_curriculum`
  - `tests.test_edge_learning`
  - `tests.test_dynamics`
- Full B_dev was run for the control and four curriculum penalties.
- B_test was never executed.

## Insight

Domain randomization produces a real transfer effect when graph-specific
identities are removed: the selected curriculum materially improves its
matched control and reduces worst-case Sybil exposure. The transferable
context representation is still too coarse to beat the trunk; stronger
structure-aware features or cause-specific feedback would be needed without
reintroducing graph identity leakage.
