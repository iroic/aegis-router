# Refine edge global v1 results

Run directory: `runs/refine_edge_global_v1` (local, ignored by git)
Profile: `profiles/aegis-global-edge-v2.json`
Top candidates: `docs/results/refine_edge_global_v1_top10.csv`

## Goal

Refine `aegis-prod-edge-v1` using local mutation across multiple scenarios to produce a more globally robust edge-routing profile.

Objective:

```text
robust_score = mean_score - 0.35*score_std + 0.25*min_score + 0.015*mean_target_hits
```

## Search setup

- Candidates: 8,192 mutations/parents
- Stage 1: 3 seeds x 6 scenarios
- Stage 2: top 160, 20 seeds x 6 scenarios
- Stage 3: top 24, 80 seeds x 6 scenarios
- CPU workers: 16

## Final best: aegis-global-edge-v2

- Candidate: 5437
- Parent: base
- Robust score: 0.509579
- Mean score: 0.418033 ± 0.074508
- Min score: 0.290494
- Mean delivery: 0.596033 ± 0.045174
- Min delivery: 0.544471
- Mean sybil: 0.151415 ± 0.032610
- Max sybil: 0.218077
- Mean PPS: 23.411334 ± 3.891502
- Min PPS: 19.252679
- Mean risk: 0.268155
- Mean target hits: 3.00 / 4

## Scenario breakdown

| Scenario | Score | Delivery | Sybil | PPS | Target hits |
| --- | ---: | ---: | ---: | ---: | ---: |
| n120_d6_s08_t36 | 0.5046 | 0.6421 | 0.1161 | 23.95 | 4 |
| n120_d6_s10_t36 | 0.4312 | 0.6083 | 0.1524 | 24.02 | 3 |
| n80_d4_s10_t30 | 0.3846 | 0.5690 | 0.1510 | 19.28 | 3 |
| n200_d6_s08_t36 | 0.3921 | 0.5497 | 0.1260 | 23.09 | 3 |
| n120_d8_s10_t48 | 0.5052 | 0.6626 | 0.1450 | 30.88 | 4 |
| n120_d6_s15_t30 | 0.2905 | 0.5445 | 0.2181 | 19.25 | 1 |

## Top 10 stage3 candidates

| Rank | Candidate | Parent | Robust | Mean score | Min score | Mean delivery | Mean/max sybil |
| ---: | ---: | --- | ---: | ---: | ---: | ---: | ---: |
| 1 | 5437 | base | 0.5096 | 0.4180 | 0.2905 | 0.5960 | 0.1514/0.2181 |
| 2 | 1688 | base | 0.5090 | 0.4193 | 0.2870 | 0.5926 | 0.1463/0.2166 |
| 3 | 7830 | top2 | 0.5010 | 0.4115 | 0.2827 | 0.5873 | 0.1483/0.2164 |
| 4 | 258 | top2 | 0.4989 | 0.4143 | 0.2787 | 0.6011 | 0.1608/0.2342 |
| 5 | 5109 | top1 | 0.4983 | 0.4142 | 0.2759 | 0.6012 | 0.1610/0.2376 |
| 6 | 2229 | top2 | 0.4981 | 0.4106 | 0.2785 | 0.5903 | 0.1525/0.2224 |
| 7 | 4065 | top1 | 0.4979 | 0.4122 | 0.2862 | 0.6016 | 0.1635/0.2367 |
| 8 | 517 | top2 | 0.4964 | 0.4094 | 0.2773 | 0.5878 | 0.1510/0.2177 |
| 9 | 6910 | top2 | 0.4963 | 0.4113 | 0.2718 | 0.5946 | 0.1566/0.2293 |
| 10 | 17 | top2 | 0.4958 | 0.4108 | 0.2799 | 0.5948 | 0.1572/0.2279 |

## Interpretation

This run found a more robust profile across six scenarios, but it also shows where the router is still weak:

- The original single-scenario profile remains stronger on the original `n120_d6_s08_t36` scenario (`score` around 0.5017 vs global-v2 scenario score 0.5046).
- The global profile is more balanced, with 80-seed validation across graph size, degree, traffic, and Sybil pressure.
- The hardest scenario is `n120_d6_s15_t30`, where sybil exposure reaches 0.2181 and score drops to 0.2905.

## Winning parameters

```json
{
  "adapt_step": 0.009933857351700494,
  "bandwidth_weight": 0.8925695382216338,
  "drop_threshold": 0.3542690662239254,
  "edge_penalty": 0.693972559052936,
  "latency_weight": 5.591050719825467,
  "learned_penalty": 10.83954174026949,
  "loop_penalty": 11.138509568563412,
  "loss_weight": 53.44067706981766,
  "low_ttl_penalty": 3.7509862111949195,
  "max_budget": 0.6529486035745646,
  "min_budget": 0.06765434232251827,
  "progress_weight": 6.62606687710675,
  "reputation_decay": 0.7781562604495869,
  "reputation_penalty": 1.0761666320530312,
  "risk_budget": 0.17813800569591307,
  "solver": "edge",
  "stability_weight": 1.346996279275258,
  "sybil_threshold": 0.26043734956038384,
  "window_size": 32
}
```

## Next improvement directions

1. Add scenario-aware scoring or adaptive risk based on observed Sybil/drop pressure.
2. Use quality-diversity/MAP-Elites to preserve specialists for low-Sybil, high-Sybil, sparse, dense, and large-graph regimes.
3. Add a worst-case/Sybil-stress objective variant to reduce `max_sybil` in the 15% Sybil scenario.
4. Try a bandit-style selector between `aegis-prod-edge-v1` and `aegis-global-edge-v2` based on online signals.
