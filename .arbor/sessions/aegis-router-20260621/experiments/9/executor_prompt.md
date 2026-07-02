## Codebase

Working directory: /tmp/aegis-arbor-node9-cycle9-20260622

## Git Isolation

Work in the assigned experiment branch/worktree. Do not switch back to the main repository for implementation or evaluation.

## Research Idea

**ID**: 9
**Hypothesis**:
Mechanism: Cause-specific feedback router with competing delivery and adversary evidence channels
Hypothesis: Separate congestion, link-loss, loop, and observed-Sybil evidence before updating edge preferences, because the shared badness signal currently confuses recoverable congestion with adversarial risk and suppresses useful delivery routes.
Observable: B_dev robust_score and delivery improve together, with fewer repeated Sybil touches and no regression in congested low-Sybil scenarios.
Conflicts: pruned [5] said uniform path credit assigns terminal signals too broadly; this counters by factorizing feedback by observable failure cause before any routing penalty is applied.

## Evaluation Info

- **Evaluation command (B_dev)**: `cd /tmp/aegis-arbor-node9-cycle9-20260622 && python3 .arbor/sessions/aegis-router-20260621/benchmark_eval.py --split dev`
- **Evaluation command (B_test, do not use for routine experiments)**: `cd /tmp/aegis-arbor-node9-cycle9-20260622 && python3 .arbor/sessions/aegis-router-20260621/benchmark_eval.py --split test`
- **Dataset info**: dev: multi-scenario fixed benchmark from refine_edge_multiscenario.py (n120_d6_s08_t36, n120_d6_s10_t36, n80_d4_s10_t30, n200_d6_s08_t36, n120_d8_s10_t48) with seeds 20260612-20260614; test: held-out n120_d6_s15_t30 with seeds 20270612-20270614; objective sybil_stress; score is robust_score from benchmark_eval.py
- **Baseline score**: 0.6355613879111393
- **Current trunk score**: 0.6845301005442892

Use B_dev for final experiment scoring. Do NOT use B_test.

## Insights From Prior Experiments

- ROOT: Across eight experiments, hard or global action suppression repeatedly trades away too much delivery. Viability gating prevents catastrophic filtering but does not improve trunk when it deletes actions. The remaining pending direction is to factor feedback by observable cause and preserve actions through bounded reranking rather than binary exclusion.

## Additional Context

Implement in the isolated copy only. Preserve APIs and protected benchmark/test/profile assets. Focus on a minimal optional cause-specific bounded reranking mechanism in EdgeLearningSolver; do not hard-filter actions. Use B_dev only. The active checkout has unrelated user changes and must not be edited. Run focused tests, existing tests, and the injected full dev benchmark when credible. Save any candidate profile/results within the isolated copy and report exact absolute score and metrics.

## Instructions

1. Understand the code before editing.
2. Implement the idea faithfully.
3. Run quick checks to ensure the new logic is active.
4. Iterate on implementation bugs.
5. Run the B_dev evaluation when credible.
6. Report Changes, Baseline vs Result, Score, and Insight. The score must be the absolute primary metric, not a delta.

Save results to `results/9-<brief-description>/`.
