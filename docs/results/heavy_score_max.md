# Aegis Router heavy optimization results

Run directory: `runs/heavy_score_max` (local, ignored by git)
Committed profile: `profiles/aegis-prod-edge-v1.json`
Search script: `scripts/heavy_secure_search.py`
Top-10 validation summary: `docs/results/heavy_score_max_top10.csv`

## Search setup

- Candidates: 16,384
- Stage 1 validation: 10 seeds per candidate
- Stage 2 validation: top 256 candidates on 100 seeds
- Workers: 16 CPU workers
- Scenario: 120 nodes, degree 6, sybil ratio 0.08, TTL 26
- Traffic: train 32 pps for 24s; eval 36 pps for 24s; drain 12s

## Best profile: aegis-prod-edge-v1

- Candidate: 13271
- Solver: edge
- Score: 0.501683 ± 0.035946
- Delivery: 0.660952 ± 0.024288
- Sybil touch: 0.139904 ± 0.018802
- PPS: 24.139167 ± 0.830593
- Drop: 0.339048 ± 0.024288
- Risk: 0.257196 ± 0.011284
- Hops: 5.418189 ± 0.199891
- Latency: 1.680093 ± 0.085529

## Comparison

| Profile | Score | Delivery | Sybil | PPS |
| --- | ---: | ---: | ---: | ---: |
| Previous `aegis-prod-robust` | 0.3484 | 0.6284 | 0.1699 | 9.6 |
| Previous `secure run8` | 0.3301 | 0.6036 | 0.1599 | 14.2 |
| New `aegis-prod-edge-v1` | 0.5017 | 0.6610 | 0.1399 | 24.1 |

Delta vs `aegis-prod-robust`:

- Score: +0.1533
- Delivery: +0.0326
- Sybil: -0.0300 (lower is better)
- PPS: +14.54

Delta vs `secure run8`:

- Score: +0.1716
- Delivery: +0.0574
- Sybil: -0.0200 (lower is better)
- PPS: +9.94

## Winning parameters

```json
{
  "adapt_step": 0.010204244463024276,
  "bandwidth_weight": 0.8649147245855077,
  "drop_threshold": 0.4024939773452399,
  "edge_penalty": 0.9426328530110251,
  "latency_weight": 3.989544326491113,
  "learned_penalty": 11.39313901657422,
  "loop_penalty": 13.778482123149029,
  "loss_weight": 41.735606649808666,
  "low_ttl_penalty": 3.980265305724756,
  "max_budget": 0.6381638365997522,
  "min_budget": 0.08271301843548931,
  "progress_weight": 8.168483995886461,
  "reputation_decay": 0.7800973795086404,
  "reputation_penalty": 1.5764732991373933,
  "risk_budget": 0.1793488993395137,
  "solver": "edge",
  "stability_weight": 1.4540034315719663,
  "sybil_threshold": 0.22346466584821906,
  "window_size": 32
}
```

## Notes

The winning profile uses the `edge` solver: directional edge memory plus an optimized risk/scoring profile. It beats all four target metrics in the validated scenario. The full local run artifacts are intentionally not committed because they are large generated outputs.
