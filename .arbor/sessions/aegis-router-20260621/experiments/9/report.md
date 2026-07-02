# Node 9: cause-specific bounded reranking

## Idea

Add an optional `EdgeLearningSolver` reranker that separates delivery,
link-loss/congestion, loop, TTL-expiry, and observed-Sybil evidence. The
combined cause signal is bounded before changing the route score, and no
candidate action is filtered.

## Changes

- Numeric `edge_penalty` retains the existing aggregate-badness behavior.
- An object-form `edge_penalty` opts into cause-specific bounded reranking.
- The candidate profile is an exact copy of
  `profiles/aegis-global-edge-v3.json` parameters except for that object-form
  field. Its `base` equals the original v3 `edge_penalty`.

## Deterministic calibration

All channel weights were fixed at delivery `0.2`, link loss `0.12`, loop
`0.7`, TTL `0.3`, and Sybil `1.0`. Only the cap varied:

- Cap `0.5`: score `0.6557615800994795`
- Cap `1.0`: score `0.666964541596115`
- Cap `1.5`: score `0.6564553415637633`

The final profile uses cap `1.0`.

## Valid baseline vs result

- Validated v3 B_dev: `0.6845301005442892`
- Candidate B_dev: `0.666964541596115`
- Absolute score change: `-0.017565558948174242`
- Delivery: `0.5962540842188314`
- Drop: `0.4037459157811686`
- Mean Sybil touch: `0.1196079581772471`
- Max Sybil touch: `0.13873117251209668`
- Mean risk: `0.25469409617981764`
- Scenarios/seeds: `5 / 3`

## Analysis and insight

The factorized bounded reranker substantially reduces Sybil exposure, but its
delivery loss outweighs that security gain under the B_dev robust objective.
With exact v3 parameters, the tested cause-specific reranker does not improve
the validated trunk.

## Validation

- Candidate-v3 equality assertion passed for every parameter except
  object-form `edge_penalty`; its `base` matches v3 exactly.
- Focused reranking and edge-learning tests: 7 passed.
- B_test was not run.
