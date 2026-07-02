# Node 8 — Viability-shielded routing

## Idea

Add a deterministic control-barrier action filter to `EdgeLearningSolver`.
Directional edges with extreme learned risk are removed only when at least one
alternative preserves destination progress, advertised bandwidth headroom,
bounded projected loss, and loop avoidance. If no such alternative exists,
the solver uses the original candidate set and ranking unchanged.

## Changes

- Added optional viability-shield controls in an isolated executor copy.
- Used directional edge evidence for the hard barrier.
- Added focused tests for filtering, fallback, disablement, and compatibility.
- Evaluated the validated `profiles/aegis-global-edge-v3.json` profile on B_dev.
- Did not modify the active checkout or protected benchmark assets.

## Validation

- 11 focused tests passed.
- Python compilation passed.
- Full discovery passed 31 tests; one unrelated optional `pqcrypto` import
  remained unavailable.
- B_test was not inspected or run.

## B_dev result

- Current trunk: `0.6845301005442892`
- Candidate: `0.6828301562815761`
- Delta: `-0.001699944262713137`
- Delivery: `0.6025623468997969`
- Mean Sybil exposure: `0.12354440776161507`
- Maximum Sybil exposure: `0.14414398441575874`

An initial broad barrier scored `0.49076651727913917`, showing that frequent
hard filtering recreates the delivery collapse seen with unconditional
penalties. Conservative gating recovered delivery but did not beat trunk.

## Decision

Pruned without B_test. Candidate code remains only in the isolated executor
copy at `/tmp/aegis-arbor-node8-20260622`; no candidate changes were applied
to the active checkout.

## Insight

A local viability proof prevents catastrophic over-filtering, but hard edge
deletion has a narrow useful range. Sparse gating nearly reproduces trunk;
broader gating loses more delivery than the reduced exposure repays. A future
mechanism should use viability-gated bounded reranking rather than deleting
actions.
