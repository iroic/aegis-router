## Codebase

Working directory: /tmp/aegis-arbor-node8-20260622

## Git Isolation

Work in the assigned experiment branch/worktree. Do not switch back to the main repository for implementation or evaluation.

## Research Idea

**ID**: 8
**Hypothesis**:
Mechanism: Viability-shielded routing with a control-barrier action filter
Hypothesis: Filter high-risk neighbors only when at least one locally viable alternative preserves destination progress, queue headroom, and bounded projected loss, so security pressure cannot remove the last delivery-capable action as unconditional penalties did.
Observable: B_dev robust_score exceeds 0.684530 while delivery stays near trunk and max Sybil exposure falls without materially increasing hops or latency.
Conflicts: pruned [7] said unconditional concentration penalties over-diversify and pruned [6] said coarse risk penalties reduce delivery; this counters via a per-decision viability shield that leaves baseline ranking unchanged when no safe alternative exists.

## Evaluation Info

- **Evaluation command (B_dev)**: `cd /tmp/aegis-arbor-node8-20260622 && python3 .arbor/sessions/aegis-router-20260621/benchmark_eval.py --split dev`
- **Evaluation command (B_test, do not use for routine experiments)**: `cd /tmp/aegis-arbor-node8-20260622 && python3 .arbor/sessions/aegis-router-20260621/benchmark_eval.py --split test`
- **Dataset info**: dev: multi-scenario fixed benchmark from refine_edge_multiscenario.py (n120_d6_s08_t36, n120_d6_s10_t36, n80_d4_s10_t30, n200_d6_s08_t36, n120_d8_s10_t48) with seeds 20260612-20260614; test: held-out n120_d6_s15_t30 with seeds 20270612-20270614; objective sybil_stress; score is robust_score from benchmark_eval.py
- **Baseline score**: 0.6355613879111393
- **Current trunk score**: 0.6845301005442892

Use B_dev for final experiment scoring. Do NOT use B_test.

## Insights From Prior Experiments

- ROOT: Across seven experiments, fixed-dev gains from tail selection, pheromone memory, and route diversification repeatedly failed held-out high-Sybil verification. Domain randomization transferred risk reduction but lost delivery. The next cycle should prioritize locally gated, delivery-preserving mechanisms rather than unconditional global penalties or fixed-dev profile selection.

## Additional Context

Use the current validated profile profiles/aegis-global-edge-v3.json as the baseline. Implement a lightweight deterministic mechanism behind optional profile parameters, preserve default APIs, add focused tests, run B_dev only, and write a detailed report plus raw metrics. Do not inspect or run B_test. Do not modify benchmark_eval.py, existing tests, seeds, scenarios, or metric formulas. This is an isolated copy because git refs are read-only.

## Instructions

1. Understand the code before editing.
2. Implement the idea faithfully.
3. Run quick checks to ensure the new logic is active.
4. Iterate on implementation bugs.
5. Run the B_dev evaluation when credible.
6. Report Changes, Baseline vs Result, Score, and Insight. The score must be the absolute primary metric, not a delta.

Save results to `results/8-<brief-description>/`.
