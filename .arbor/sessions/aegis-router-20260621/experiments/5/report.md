# Node 5 — Path-level eligibility traces

## Idea

Track each packet's actual directed path and propagate observed terminal
delivery, drop, loop, and Sybil feedback backward over preceding edges with a
geometrically decaying eligibility trace.

## Changes

- Added directed path tracking to `Packet` and `EventDrivenSimulator`.
- Added optional `observe_path_result` dispatch with legacy fallback.
- Added persistent, directional trace risk to `EdgeLearningSolver`.
- Kept the final edge on the existing `observe_result` path exactly once;
  eligibility updates apply only to earlier edges.
- Added profile `aegis-path-eligibility-v1`, based on
  `aegis-global-edge-v3`.
- Added focused tests for path capture, geometric credit assignment, final-edge
  non-duplication, and disabled-trace compatibility.

## Validation

- `py_compile`: passed.
- 11 focused unit tests: passed.
- B_test: not run.

## B_dev result

Best of three bounded trace configurations:

- Absolute robust score: `0.6816484915899128`
- Delivery: `0.6015539838723201`
- Drop: `0.39844601612768`
- Mean Sybil touch: `0.12264524626028629`
- Maximum Sybil touch: `0.14404045942518526`
- Reported hops: `0.25520037289296676`
- Reported latency: `0.25520037289296676`

Current trunk score: `0.6845301005442892`.

Delta versus trunk: `-0.0028816089543764` (`-0.42%`).

## Insight

Path-level feedback is operational and preserves legacy behavior when disabled,
but the best bounded configuration did not beat the fixed security trunk.
Longer-lived traces retained delivery better; faster forgetting reduced Sybil
exposure but cost enough delivery to lower the robust score. The useful signal
appears to require outcome-specific or confidence-gated attribution rather
than applying the same terminal Sybil flag across every preceding edge.
