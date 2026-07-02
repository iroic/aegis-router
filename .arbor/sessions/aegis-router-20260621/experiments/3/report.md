# Node 3 — Pheromone-repulsion memory with fast decay

## Idea

Add a lightweight, bounded memory to `EdgeLearningSolver` that reinforces
successful directed edges, rapidly decays prior evidence, reverses edge
reinforcement after observed drops or Sybil touches, and creates a short-lived
local repulsion field around recently bad nodes.

## Changes

- Added an optional pheromone mode to `EdgeLearningSolver`.
- Persisted bounded directed-edge pheromones and node repulsion values.
- Added profile-driven construction in `scripts/heavy_secure_search.py`.
- Added `profiles/aegis-pheromone-repulsion-v1.json`, based on
  `profiles/aegis-global-edge-v3.json`.
- Added focused tests for reinforcement, reversal, decay, bounded state,
  routing behavior, and persistence.

## Implementation choices

- The mode is disabled by default, preserving existing APIs and behavior.
- Decisions use only `observe_result` outcomes. `next_hop` does not inspect
  ground-truth Sybil identities.
- Every observed terminal result decays both memories.
- A clean delivery adds positive directed-edge pheromone.
- A drop or observed Sybil touch rapidly shrinks existing positive evidence,
  then applies negative pheromone and node repulsion.
- Repulsion includes a weak one-hop spillover around recently bad nodes.
- Both memories are capped and limited to 4096 entries.

## Baseline vs result

- Original baseline: `0.6355613879111393`
- Current trunk (`aegis-global-edge-v3`): `0.6845301005442892`
- Node 3 B_dev: `0.6874925765035899`

## B_dev metrics

- Delivery: `0.601536025815964`
- Drop: `0.398463974184036`
- Mean Sybil touch ratio: `0.12057434229948809`
- Maximum scenario Sybil touch ratio: `0.1477629172474903`
- Scenarios: `5`
- Seeds per scenario: `3`

The benchmark helper currently emits its `mean_risk` fallback in the `latency`
and `hops` JSON fields because the aggregate result does not expose aggregate
latency/hops. Those two emitted values (`0.2526625159408607`) are therefore not
reported as actual latency or route length.

## Validation

- `python3 -m py_compile aegis_router/solvers.py scripts/heavy_secure_search.py tests/test_pheromone_repulsion.py`
- `python3 -m unittest tests.test_pheromone_repulsion tests.test_edge_learning tests.test_reason_aware_learning -v`
- Result: 8 focused tests passed.
- Final evaluation used B_dev only. B_test was not executed.

## Held-out verification

- B_test score: `0.42269150871029015`
- Current trunk B_test score: `0.42429066273896465`

The small B_dev gain did not generalize to the protected held-out scenario, so
the candidate was rejected and not merged.

## Insight

Strong local repulsion reduced Sybil exposure but damaged delivery. The useful
configuration keeps repulsion weak and short-lived while giving more weight to
positive directed-edge reinforcement. This narrowly beats the fixed security
trunk on B_dev, but the simulator attributes terminal feedback only to the last
hop, which limits how precisely delayed route failures can update earlier path
segments.
