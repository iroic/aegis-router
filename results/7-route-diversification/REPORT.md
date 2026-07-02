# Node 7 — Concentration-aware route diversification

## Idea

Track bounded, decayed usage of observable transit nodes and directed edges.
Penalize repeatedly dominant choices while retaining the existing edge quality,
risk, and reputation scoring. An optional local hub/bridge suspicion signal was
implemented without reading hidden Sybil labels.

## Changes

- Added optional concentration memory to `EdgeLearningSolver`.
- Added deterministic tie-breaking.
- Persisted bounded node/edge usage alongside existing learning state.
- Added outcome-aware drop boost and delivery relief controls.
- Added optional local structural suspicion from degree excess and neighborhood
  overlap.
- Wired all new parameters through solver construction.
- Added one profile based on `aegis-global-edge-v3`.
- Added focused tests for diversification, persistence, bounds, destination
  handling, default-off compatibility, and structural suspicion.

## Validation

- `python3 -m py_compile ...`: passed.
- 12 focused and adjacent unit tests: passed.
- B_test: not executed.

## B_dev result

Selected bounded setting:

- concentration decay: `0.9995`
- node concentration penalty: `0.03`
- directed-edge concentration penalty: `0.08`
- structural suspicion: disabled
- terminal outcome modifiers: disabled

Absolute metrics:

- robust score: `0.6870040996217148`
- delivery: `0.6043672163158552`
- drop: `0.39563278368414484`
- mean Sybil touch: `0.12432946652153383`
- maximum scenario Sybil touch: `0.1393671851494942`
- mean loss risk: `0.25546439910306673`
- mean latency: `1.8405381562057492`
- mean hops: `6.030300008247972`

Trunk score: `0.6845301005442892`.

Absolute gain: `+0.002473999077425626` (`+0.3614%`).

## Insight

Light simultaneous node and edge diversification beats the trunk on B_dev and
reduces worst-scenario Sybil exposure. Edge-only diversification lowers average
Sybil exposure but creates a much worse concentration tail, while aggressive
or structurally biased diversification harms delivery. The useful regime is a
small penalty that breaks repeated dependence without forcing broad route
exploration.
