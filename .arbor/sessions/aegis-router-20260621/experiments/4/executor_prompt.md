## Codebase

Working directory: /home/ghost/projects/aegis-router

## Git Isolation

Work in the assigned experiment branch/worktree. Do not switch back to the main repository for implementation or evaluation.

## Research Idea

**ID**: 4
**Hypothesis**:
Mechanism: Two-profile bandit selector over edge routing policies
Hypothesis: switch between the delivery-heavy and security-heavy edge profiles using recent packet outcomes and local churn/sybil pressure so mixed scenarios can get the best of both behaviors instead of averaging them away.
Observable: higher robust_score on the fixed dev suite and lower max_sybil on the held-out stress scenario without changing any benchmark code.
Conflicts: none - attacks runtime policy selection rather than per-edge scoring.

## Evaluation Info

- **Evaluation command (B_dev)**: `cd /home/ghost/projects/aegis-router && python3 .arbor/sessions/aegis-router-20260621/benchmark_eval.py --split dev`
- **Evaluation command (B_test, do not use for routine experiments)**: `cd /home/ghost/projects/aegis-router && python3 .arbor/sessions/aegis-router-20260621/benchmark_eval.py --split test`
- **Dataset info**: dev: multi-scenario fixed benchmark from refine_edge_multiscenario.py (n120_d6_s08_t36, n120_d6_s10_t36, n80_d4_s10_t30, n200_d6_s08_t36, n120_d8_s10_t48) with seeds 20260612-20260614; test: held-out n120_d6_s15_t30 with seeds 20270612-20270614; objective sybil_stress; score is robust_score from benchmark_eval.py
- **Baseline score**: 0.6355613879111393
- **Current trunk score**: 0.6845301005442892

Use B_dev for final experiment scoring. Do NOT use B_test.

## Instructions

1. Understand the code before editing.
2. Implement the idea faithfully.
3. Run quick checks to ensure the new logic is active.
4. Iterate on implementation bugs.
5. Run the B_dev evaluation when credible.
6. Report Changes, Baseline vs Result, Score, and Insight. The score must be the absolute primary metric, not a delta.

Save results to `results/4-<brief-description>/`.
