# Next ideas for Aegis Router global optimization

## Web-inspired ideas considered

1. Quality-diversity / MAP-Elites for noisy domains
   - Why: robust routing needs a portfolio of specialists, not only one global optimum.
   - Action: preserve diverse elites during stage selection: best robust score, best worst-case score, lowest max Sybil, best sparse-graph delivery, best high-traffic delivery.
   - Cost: low in the optimizer script.
   - Risk: low; only changes search selection.
   - Minimal test: smoke run with small candidates and ensure stage2 receives a diverse union.

2. Adversarial bandits / EXP3-style selection
   - Why: runtime could choose between multiple profiles based on adversarial feedback.
   - Action: later add an online profile selector between `aegis-prod-edge-v1`, `aegis-global-edge-v2`, and future stress profiles.
   - Cost: medium; needs simulator/runtime changes and tests.
   - Risk: medium.
   - Minimal test: fixed candidate portfolio, compare selector vs single profile across mixed scenarios.

3. Ant-colony / pheromone evaporation
   - Why: edge learning is already pheromone-like; stronger evaporation could adapt faster after adversarial edges change.
   - Action: explore adaptive learned/reputation decay by drop reason and scenario pressure.
   - Cost: medium; touches solver logic.
   - Risk: medium.
   - Minimal test: add unit tests for decay and compare against current edge solver.

4. Worst-case robust optimization
   - Why: `n120_d6_s15_t30` dominates failures; `max_sybil` is still too high.
   - Action: add objective modes that penalize `max_sybil`, reward `min_delivery`, and select stress specialists into later stages.
   - Cost: low in optimizer script.
   - Risk: low.
   - Minimal test: smoke run objective `sybil_stress` and verify top selection contains low max-Sybil candidates.

5. Scenario-aware curriculum
   - Why: evaluate cheap/easy scenarios first, then adversarial scenarios for survivors.
   - Action: future optimizer can stage scenario count: broad stage on 3 scenarios, stage2/3 on all + stress.
   - Cost: low-medium.
   - Risk: low.
   - Minimal test: compare wall time and final robust score with full all-scenario stage1.

## Changes applied for v2

- Add objective modes to `scripts/refine_edge_multiscenario.py`.
- Add diverse elite selection for stage2/stage3, inspired by MAP-Elites / quality-diversity.
- Add a `sybil_stress` objective for the next run to attack the high-Sybil worst case.
