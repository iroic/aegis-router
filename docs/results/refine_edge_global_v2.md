# Refine edge global v2 results

Run directory: `runs/refine_edge_global_v2` (local, ignored by git)
Profile: `profiles/aegis-global-edge-v3.json`
Top candidates: `docs/results/refine_edge_global_v2_top10.csv`

## Goal

Improve the global profile with a security-heavy objective after `aegis-global-edge-v2` showed high Sybil exposure in the 15% Sybil stress scenario.

## Search setup

- Base profile: `profiles/aegis-global-edge-v2.json`
- Parent elites: `docs/results/refine_edge_global_v1_top10.csv`
- Candidates: 12,288 mutations
- Objective: `sybil_stress`
- Selection: `diverse` quality-diversity survivor selection
- Stage 1: 3 seeds x 6 scenarios
- Stage 2: top 240, 24 seeds x 6 scenarios
- Stage 3: top 36, 96 seeds x 6 scenarios
- CPU workers: 16

## Final best: aegis-global-edge-v3

- Candidate: 11285
- Parent: top2
- Robust score: 0.563356
- Mean score: 0.415941 ± 0.074452
- Min score: 0.293450
- Mean delivery: 0.580297 ± 0.046637
- Min delivery: 0.528459
- Mean sybil: 0.136223 ± 0.030252
- Max sybil: 0.197573
- Mean PPS: 23.437562 ± 3.865101
- Min PPS: 19.318452
- Mean risk: 0.260268
- Mean target hits: 2.83 / 4

## Comparison vs aegis-global-edge-v2

| Metric | global-edge-v2 | global-edge-v3 | Delta |
| --- | ---: | ---: | ---: |
| robust_score | 0.509579 | 0.563356 | +0.053777 |
| mean_score | 0.418033 | 0.415941 | -0.002092 |
| min_score | 0.290494 | 0.293450 | +0.002956 |
| mean_delivery | 0.596033 | 0.580297 | -0.015736 |
| mean_sybil | 0.151415 | 0.136223 | -0.015192 |
| max_sybil | 0.218077 | 0.197573 | -0.020504 |
| mean_pps | 23.411334 | 23.437562 | +0.026228 |
| target_hits_mean | 3.000000 | 2.833333 | -0.166667 |

## Scenario breakdown

| Scenario | Score | Delivery | Sybil | PPS | Target hits |
| --- | ---: | ---: | ---: | ---: | ---: |
| n120_d6_s08_t36 | 0.5009 | 0.6261 | 0.1022 | 23.99 | 3 |
| n120_d6_s10_t36 | 0.4342 | 0.5966 | 0.1365 | 24.04 | 3 |
| n80_d4_s10_t30 | 0.3715 | 0.5451 | 0.1378 | 19.35 | 3 |
| n200_d6_s08_t36 | 0.3899 | 0.5360 | 0.1132 | 23.07 | 3 |
| n120_d8_s10_t48 | 0.5057 | 0.6496 | 0.1301 | 30.87 | 4 |
| n120_d6_s15_t30 | 0.2935 | 0.5285 | 0.1976 | 19.32 | 1 |

## Top 10 stage3 candidates

| Rank | Candidate | Parent | Robust | Mean score | Min score | Mean delivery | Mean/max sybil |
| ---: | ---: | --- | ---: | ---: | ---: | ---: | ---: |
| 1 | 11285 | top2 | 0.5634 | 0.4159 | 0.2935 | 0.5803 | 0.1362/0.1976 |
| 2 | 11094 | top1 | 0.5628 | 0.4184 | 0.2898 | 0.5826 | 0.1363/0.2031 |
| 3 | 11728 | top2 | 0.5626 | 0.4119 | 0.2881 | 0.5690 | 0.1279/0.1866 |
| 4 | 9588 | base | 0.5583 | 0.4176 | 0.2872 | 0.5834 | 0.1380/0.2034 |
| 5 | 5611 | top7 | 0.5577 | 0.4174 | 0.2906 | 0.5904 | 0.1459/0.2125 |
| 6 | 4679 | base | 0.5575 | 0.4152 | 0.2874 | 0.5820 | 0.1388/0.2010 |
| 7 | 8344 | base | 0.5566 | 0.4179 | 0.2867 | 0.5875 | 0.1422/0.2107 |
| 8 | 8311 | base | 0.5557 | 0.4176 | 0.2845 | 0.5861 | 0.1410/0.2095 |
| 9 | 3811 | top2 | 0.5533 | 0.4194 | 0.2873 | 0.5965 | 0.1506/0.2211 |
| 10 | 9412 | top2 | 0.5517 | 0.4104 | 0.2823 | 0.5754 | 0.1364/0.1967 |

## Interpretation

The v2 search achieved its intended security tradeoff:

- `robust_score` improved strongly under the `sybil_stress` objective.
- `mean_sybil` and `max_sybil` both dropped versus `aegis-global-edge-v2`.
- Delivery dropped, so `aegis-global-edge-v3` is better as a secure/global profile, while `aegis-prod-edge-v1` remains the best single-scenario/high-delivery profile.

## Winning parameters

```json
{
  "adapt_step": 0.004,
  "bandwidth_weight": 1.0833963887382254,
  "drop_threshold": 0.3850051196808128,
  "edge_penalty": 0.5125733970107129,
  "latency_weight": 5.044474396831799,
  "learned_penalty": 10.314713435311118,
  "loop_penalty": 10.920705962346915,
  "loss_weight": 73.46609575166937,
  "low_ttl_penalty": 3.2067152782058885,
  "max_budget": 0.6458961566667539,
  "min_budget": 0.16502772906506055,
  "progress_weight": 6.723975654046898,
  "reputation_decay": 0.9398518881235585,
  "reputation_penalty": 0.5802282580642248,
  "risk_budget": 0.25460464077525524,
  "solver": "edge",
  "stability_weight": 2.5375440145332515,
  "sybil_threshold": 0.2172563905536011,
  "window_size": 16
}
```
