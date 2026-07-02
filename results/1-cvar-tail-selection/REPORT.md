# Node 1 — CVaR tail-risk profile selection

## Idea

Use a transparent, offline CVaR-style ranking over existing development
evidence to select robust edge profiles. The ranking is separate from the
official benchmark. No benchmark, scenario list, test seed, metric formula,
source code, or test was modified.

## Evidence and leakage controls

- Sources: `stage2_results.csv` and `stage3_results.csv` from
  `runs/refine_edge_global_v1` and `runs/refine_edge_global_v2`.
- Stage 2 was processed first. The large Stage 1 files were not loaded.
- 399 unique parameter sets were parsed.
- Only these five development scenarios contributed to the offline ranking:
  `n120_d6_s08_t36`, `n120_d6_s10_t36`, `n80_d4_s10_t30`,
  `n200_d6_s08_t36`, and `n120_d8_s10_t48`.
- The reserved scenario `n120_d6_s15_t30` was excluded from selection even
  though historical CSV rows contain it.
- B_test was never executed.

## Offline ranking

For each profile, over the five permitted development scenarios:

- `CVaR_score` is the mean of the two lowest scenario scores.
- `CVaR_delivery` is the mean of the two lowest delivery rates.
- `CVaR_sybil` is the mean of the two highest Sybil exposure rates.
- `score_std` is the population standard deviation across scenario scores.

The selection-only objective was:

```text
0.50 * CVaR_score
+ 0.35 * CVaR_delivery
- 0.75 * CVaR_sybil
- 0.10 * score_std
```

Six candidates were chosen from the top 60 using a quality/diversity rule:
70% offline rank quality and 30% minimum normalized parameter-space distance
from profiles already shortlisted. The complete ranking is in
`offline_ranking.csv`; exact shortlisted parameters are in `shortlist.json`
and `candidates/`.

## Fixed B_dev results

The unchanged command was used for every candidate:

```text
python3 .arbor/sessions/aegis-router-20260621/benchmark_eval.py \
  --split dev --profile <candidate-path>
```

| Candidate | B_dev score | Delivery | Drop | Sybil | Max Sybil |
|---|---:|---:|---:|---:|---:|
| 1 | 0.674271 | 0.602430 | 0.397570 | 0.133064 | 0.155199 |
| 2 | 0.649006 | 0.588463 | 0.411537 | 0.118764 | 0.139635 |
| 3 | 0.673778 | 0.591941 | 0.408059 | 0.113976 | 0.125024 |
| 4 | 0.660359 | 0.595537 | 0.404463 | 0.122836 | 0.136586 |
| 5 | **0.695938** | **0.609398** | **0.390602** | 0.123690 | 0.139130 |
| 6 | 0.658166 | 0.602760 | 0.397240 | 0.133028 | 0.143910 |

Raw benchmark outputs are stored in `dev_outputs/`.

## Baseline vs result

- Baseline: `0.6355613879111393`
- Trunk: `0.6845301005442892`
- Best candidate: `0.6959375149744956`
- Absolute gain over trunk: `0.0114074144302064`
- Relative gain over trunk: `1.67%`

Candidate 5 beats the current trunk on the fixed B_dev benchmark. It was
materialized as `profiles/aegis-cvar-edge-v1.json`.

## Insight

The profile ranked fifth by the offline tail objective was the strongest on
the current fixed B_dev benchmark. Pure tail ranking was directionally useful,
but not perfectly aligned with the official score: the top offline candidate
did not beat trunk. A small diverse shortlist was therefore important. The
winning profile improves delivery while retaining Sybil exposure close to the
security-focused trunk range; its gain remains development-only until a
coordinator-authorized final held-out evaluation.

## Held-out verification

- Candidate B_test: `0.3405655097363942`
- Current trunk B_test: `0.42429066273896465`
- Candidate delivery: `0.48904842127602616`
- Candidate Sybil exposure: `0.21170029814801336`

The CVaR-selected candidate did not generalize to the protected scenario. It
was rejected and was not promoted to the validated trunk.
