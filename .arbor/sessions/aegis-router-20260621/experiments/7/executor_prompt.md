## Codebase

Working directory: /home/ghost/projects/aegis-router

## Git Isolation

Work in the assigned experiment branch/worktree. Do not switch back to the main repository for implementation or evaluation.

## Research Idea

**ID**: 7
**Hypothesis**:
Mechanism: Concentration-aware route diversification with local structural suspicion
Hypothesis: penalize repeated dependence on the same transit nodes and edges while using only observable local topology and outcome history to spread traffic across structurally independent routes, reducing the chance that one deceptive Sybil hub captures many packets.
Observable: lower B_dev max_sybil and route concentration without materially increasing hops, latency, or packet loss.
Conflicts: pruned [2] used a latent hazard belief and regressed; this counters via explicit route concentration and observable structural diversity rather than hidden-risk inference.

## Evaluation Info

- **Evaluation command (B_dev)**: `cd /home/ghost/projects/aegis-router && python3 .arbor/sessions/aegis-router-20260621/benchmark_eval.py --split dev`
- **Evaluation command (B_test, do not use for routine experiments)**: `cd /home/ghost/projects/aegis-router && python3 .arbor/sessions/aegis-router-20260621/benchmark_eval.py --split test`
- **Dataset info**: dev: multi-scenario fixed benchmark from refine_edge_multiscenario.py (n120_d6_s08_t36, n120_d6_s10_t36, n80_d4_s10_t30, n200_d6_s08_t36, n120_d8_s10_t48) with seeds 20260612-20260614; test: held-out n120_d6_s15_t30 with seeds 20270612-20270614; objective sybil_stress; score is robust_score from benchmark_eval.py
- **Baseline score**: 0.6355613879111393
- **Current trunk score**: 0.6845301005442892

Use B_dev for final experiment scoring. Do NOT use B_test.

## Insights From Prior Experiments

- ROOT: Children findings: [1, pruned, score=0.6959] La sélection CVaR sur dev trouve un profil performant localement, mais son score held-out chute fortement; les cinq scénarios dev ne couvrent pas assez le régime Sybil à 15%. [Pruned: Surapprentissage dev: B_test 0.340566 très inférieur au trunk validé 0.424291.] | [2, pruned] [Pruned: Regression on the fixed dev/test benchmark: robust score dropped from 0.6356 to 0.5855 on dev and from 0.3000 to 0.2866 on test, so the latent-hazard formulation is not a net win in its current form.] | [3, pruned, score=0.6875] Une faible mémoire positive d'arêtes avec répulsion courte améliore légèrement B_dev, mais le gain ne généralise pas au held-out; la rétroaction limitée au dernier saut réduit probablement la qualité du crédit causal. [Pruned: Le gain dev ne se généralise pas: B_test 0.422692 inférieur au trunk 0.424291.] | [4, pruned, score=0.667] Le sélecteur contextuel à deux profils améliore le baseline mais ne dépasse pas le profil sécurité fixe; le coût d'apprentissage et les commutations n'apportent pas de gain robuste sur ce dev fixe. [Pruned: Dev score 0.666974 inférieur au trunk 0.684530; pas de justification pour exposer B_test ou fus...

## Instructions

1. Understand the code before editing.
2. Implement the idea faithfully.
3. Run quick checks to ensure the new logic is active.
4. Iterate on implementation bugs.
5. Run the B_dev evaluation when credible.
6. Report Changes, Baseline vs Result, Score, and Insight. The score must be the absolute primary metric, not a delta.

Save results to `results/7-<brief-description>/`.
