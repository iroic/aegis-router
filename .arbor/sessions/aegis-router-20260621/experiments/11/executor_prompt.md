## Codebase

Working directory: /tmp/aegis-arbor-node11-cycle11-20260622

## Git Isolation

Work in the assigned experiment branch/worktree. Do not switch back to the main repository for implementation or evaluation.

## Research Idea

**ID**: 11
**Hypothesis**:
Mechanism: Sibling-relative posterior evidence with local competitive shrinkage
Hypothesis: Calibrate each directional edge against the observed evidence distribution of its currently available sibling routes, so broad regime-wide failure pressure cancels out while locally exceptional adversarial edges still receive a bounded penalty.
Observable: B_dev robust_score exceeds 0.684530 while preserving delivery and reducing mean/max Sybil exposure; gains should arise without absolute global priors or action deletion.
Conflicts: pruned [10] showed fixed global empirical priors fail under distribution shift and pruned [6] showed coarse context statistics reduce delivery; this counters via decision-local relative evidence over concrete alternatives.

## Evaluation Info

- **Evaluation command (B_dev)**: `cd /tmp/aegis-arbor-node11-cycle11-20260622 && python3 .arbor/sessions/aegis-router-20260621/benchmark_eval.py --split dev`
- **Evaluation command (B_test, do not use for routine experiments)**: `cd /tmp/aegis-arbor-node11-cycle11-20260622 && python3 .arbor/sessions/aegis-router-20260621/benchmark_eval.py --split test`
- **Dataset info**: dev: multi-scenario fixed benchmark from refine_edge_multiscenario.py (n120_d6_s08_t36, n120_d6_s10_t36, n80_d4_s10_t30, n200_d6_s08_t36, n120_d8_s10_t48) with seeds 20260612-20260614; test: held-out n120_d6_s15_t30 with seeds 20270612-20270614; objective sybil_stress; score is robust_score from benchmark_eval.py
- **Baseline score**: 0.6355613879111393
- **Current trunk score**: 0.6845301005442892

Use B_dev for final experiment scoring. Do NOT use B_test.

## Insights From Prior Experiments

- ROOT: Confidence calibration is a real B_dev improvement axis, but even conservative empirical-Bayes shrinkage failed held-out high-Sybil verification. Future work should avoid fixed global prior transfer and condition confidence on local regime or topology without using hidden labels.

## Instructions

1. Understand the code before editing.
2. Implement the idea faithfully.
3. Run quick checks to ensure the new logic is active.
4. Iterate on implementation bugs.
5. Run the B_dev evaluation when credible.
6. Report Changes, Baseline vs Result, Score, and Insight. The score must be the absolute primary metric, not a delta.

Save results to `results/11-<brief-description>/`.
