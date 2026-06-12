#!/usr/bin/env python3
"""Refine the best Aegis edge profile across multiple scenarios.

This is a mutation-based optimizer around profiles/aegis-prod-edge-v1.json.
It optimizes for robust global performance, not just one lucky scenario.
"""
from __future__ import annotations

import argparse
import csv
import importlib.util
import json
import math
import os
import random
import statistics
import sys
import time
from concurrent.futures import ProcessPoolExecutor, as_completed
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
HEAVY_PATH = ROOT / "scripts" / "heavy_secure_search.py"
spec = importlib.util.spec_from_file_location("heavy_secure_search", HEAVY_PATH)
if spec is None or spec.loader is None:
    raise RuntimeError(f"cannot load {HEAVY_PATH}")
heavy = importlib.util.module_from_spec(spec)
sys.modules["heavy_secure_search"] = heavy
spec.loader.exec_module(heavy)

TARGET = heavy.TARGET
composite = heavy.composite
stats_mean = heavy.stats_mean
eval_one_seed = heavy.eval_one_seed

SCENARIOS: list[dict[str, Any]] = [
    # Original winning domain.
    {"name": "n120_d6_s08_t36", "nodes": 120, "degree": 6, "sybil_ratio": 0.08, "ttl": 26, "queue_service_time": 0.012, "sybil_extra_drop": 0.10, "train_duration": 20.0, "train_traffic_rate": 32.0, "eval_duration": 20.0, "eval_traffic_rate": 36.0, "drain": 10.0, "learn_runs": 10},
    # Slightly higher Sybil pressure.
    {"name": "n120_d6_s10_t36", "nodes": 120, "degree": 6, "sybil_ratio": 0.10, "ttl": 26, "queue_service_time": 0.012, "sybil_extra_drop": 0.12, "train_duration": 20.0, "train_traffic_rate": 32.0, "eval_duration": 20.0, "eval_traffic_rate": 36.0, "drain": 10.0, "learn_runs": 10},
    # Smaller/sparser graph, harder routing choices.
    {"name": "n80_d4_s10_t30", "nodes": 80, "degree": 4, "sybil_ratio": 0.10, "ttl": 24, "queue_service_time": 0.014, "sybil_extra_drop": 0.12, "train_duration": 18.0, "train_traffic_rate": 28.0, "eval_duration": 18.0, "eval_traffic_rate": 30.0, "drain": 10.0, "learn_runs": 9},
    # Larger graph.
    {"name": "n200_d6_s08_t36", "nodes": 200, "degree": 6, "sybil_ratio": 0.08, "ttl": 32, "queue_service_time": 0.012, "sybil_extra_drop": 0.10, "train_duration": 18.0, "train_traffic_rate": 32.0, "eval_duration": 18.0, "eval_traffic_rate": 36.0, "drain": 10.0, "learn_runs": 9},
    # Denser graph + heavy traffic.
    {"name": "n120_d8_s10_t48", "nodes": 120, "degree": 8, "sybil_ratio": 0.10, "ttl": 26, "queue_service_time": 0.010, "sybil_extra_drop": 0.12, "train_duration": 18.0, "train_traffic_rate": 42.0, "eval_duration": 18.0, "eval_traffic_rate": 48.0, "drain": 10.0, "learn_runs": 9},
    # Security stress scenario. This is weighted lighter because the target Sybil threshold is harder.
    {"name": "n120_d6_s15_t30", "nodes": 120, "degree": 6, "sybil_ratio": 0.15, "ttl": 26, "queue_service_time": 0.014, "sybil_extra_drop": 0.16, "train_duration": 18.0, "train_traffic_rate": 28.0, "eval_duration": 18.0, "eval_traffic_rate": 30.0, "drain": 10.0, "learn_runs": 9},
]

FIELDS = [
    "candidate_id", "parent", "stage", "robust_score", "mean_score", "score_std", "min_score",
    "mean_delivery", "delivery_std", "min_delivery", "mean_sybil", "sybil_std", "max_sybil",
    "mean_pps", "pps_std", "min_pps", "mean_drop", "mean_risk", "target_hits_mean",
    "scenario_count", "seed_count", "params", "scenario_metrics",
]


def clamp(x: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, x))


def log_mut(rng: random.Random, x: float, sigma: float, lo: float, hi: float) -> float:
    return clamp(x * math.exp(rng.gauss(0.0, sigma)), lo, hi)


def lin_mut(rng: random.Random, x: float, sigma: float, lo: float, hi: float) -> float:
    return clamp(x + rng.gauss(0.0, sigma), lo, hi)


def load_base_profile(path: Path) -> dict[str, Any]:
    data = json.loads(path.read_text())
    params = data["params"].copy()
    params["solver"] = "edge"
    return params


def load_parent_profiles(paths: list[Path], base_params: dict[str, Any]) -> list[tuple[str, dict[str, Any]]]:
    parents = [("base", base_params)]
    for path in paths:
        if not path.exists():
            continue
        with path.open() as f:
            rows = list(csv.DictReader(f))
        for i, row in enumerate(rows[:20], start=1):
            try:
                params = json.loads(row["params"])
            except Exception:
                continue
            if params.get("solver") == "edge":
                parents.append((f"top{i}", params))
    return parents


def mutate_edge(parent: dict[str, Any], rng: random.Random, cid: int, parent_name: str, radius: float) -> dict[str, Any]:
    p = dict(parent)
    p["candidate_id"] = cid
    p["solver"] = "edge"
    p["parent"] = parent_name
    # Local mutation. Radius 1.0 is moderate; >1 explores wider.
    p["latency_weight"] = log_mut(rng, float(p["latency_weight"]), 0.22 * radius, 0.2, 6.0)
    p["loss_weight"] = log_mut(rng, float(p["loss_weight"]), 0.25 * radius, 8.0, 120.0)
    p["bandwidth_weight"] = lin_mut(rng, float(p["bandwidth_weight"]), 0.20 * radius, 0.0, 1.8)
    p["stability_weight"] = lin_mut(rng, float(p["stability_weight"]), 0.45 * radius, 0.0, 5.0)
    p["progress_weight"] = lin_mut(rng, float(p["progress_weight"]), 1.10 * radius, 1.0, 12.0)
    p["loop_penalty"] = log_mut(rng, float(p["loop_penalty"]), 0.22 * radius, 4.0, 45.0)
    p["low_ttl_penalty"] = lin_mut(rng, float(p["low_ttl_penalty"]), 0.60 * radius, 0.0, 7.0)
    p["risk_budget"] = lin_mut(rng, float(p["risk_budget"]), 0.035 * radius, 0.05, 0.36)
    p["min_budget"] = lin_mut(rng, float(p["min_budget"]), 0.020 * radius, 0.03, 0.18)
    p["max_budget"] = lin_mut(rng, float(p["max_budget"]), 0.050 * radius, 0.32, 0.78)
    if p["max_budget"] < p["min_budget"] + 0.08:
        p["max_budget"] = p["min_budget"] + 0.08
    p["adapt_step"] = log_mut(rng, float(p["adapt_step"]), 0.45 * radius, 0.004, 0.14)
    p["window_size"] = int(rng.choice([5, 8, 10, 12, 16, 24, 32, 48])) if rng.random() < 0.25 * radius else int(p["window_size"])
    p["drop_threshold"] = lin_mut(rng, float(p["drop_threshold"]), 0.055 * radius, 0.18, 0.68)
    p["sybil_threshold"] = lin_mut(rng, float(p["sybil_threshold"]), 0.055 * radius, 0.08, 0.52)
    p["reputation_penalty"] = log_mut(rng, float(p["reputation_penalty"]), 0.40 * radius, 0.1, 24.0)
    p["reputation_decay"] = lin_mut(rng, float(p["reputation_decay"]), 0.035 * radius, 0.62, 0.99)
    p["learned_penalty"] = log_mut(rng, float(p["learned_penalty"]), 0.28 * radius, 1.0, 26.0)
    p["edge_penalty"] = log_mut(rng, float(p["edge_penalty"]), 0.45 * radius, 0.1, 26.0)
    return p


def make_candidates(base: dict[str, Any], parents: list[tuple[str, dict[str, Any]]], count: int, seed: int) -> list[dict[str, Any]]:
    rng = random.Random(seed)
    candidates: list[dict[str, Any]] = []
    # include exact parents first
    cid = 1
    seen = set()
    for name, p in parents:
        q = dict(p)
        q["candidate_id"] = cid
        q["solver"] = "edge"
        q["parent"] = name
        candidates.append(q)
        cid += 1
    while len(candidates) < count:
        name, parent = rng.choice(parents)
        # mostly local, sometimes wider to avoid local optimum.
        radius = rng.choices([0.55, 0.85, 1.20, 1.80], weights=[0.35, 0.35, 0.20, 0.10], k=1)[0]
        q = mutate_edge(parent, rng, cid, name, radius)
        key = tuple(round(float(q[k]), 6) if isinstance(q[k], float) else q[k] for k in sorted(q) if k not in {"candidate_id", "parent"})
        if key in seen:
            continue
        seen.add(key)
        candidates.append(q)
        cid += 1
    return candidates


def scenario_score(row: dict[str, float]) -> int:
    return int(row["score"] > TARGET["score"]) + int(row["delivery"] > TARGET["delivery"]) + int(row["sybil"] < TARGET["sybil"]) + int(row["pps"] > TARGET["pps"])


def compute_robust_score(
    *,
    mean_score: float,
    score_std: float,
    min_score: float,
    mean_delivery: float,
    min_delivery: float,
    mean_sybil: float,
    max_sybil: float,
    target_hits_mean: float,
    objective: str,
) -> float:
    """Scalar objective for noisy multi-scenario routing search.

    `balanced` keeps the original v1 objective. `sybil_stress` is a
    worst-case/security-heavy variant inspired by robust optimization: it
    rewards the worst scenario and explicitly penalizes high Sybil exposure.
    `delivery_stress` keeps high-throughput/delivery specialists alive.
    """
    base = mean_score - 0.35 * score_std + 0.25 * min_score + 0.015 * target_hits_mean
    if objective == "balanced":
        return base
    if objective == "sybil_stress":
        sybil_excess = max(0.0, max_sybil - TARGET["sybil"])
        return base + 0.16 * min_score + 0.08 * min_delivery - 0.55 * sybil_excess - 0.08 * mean_sybil
    if objective == "delivery_stress":
        return base + 0.18 * mean_delivery + 0.10 * min_delivery - 0.10 * max(0.0, max_sybil - 0.24)
    raise ValueError(f"unknown objective: {objective}")


def evaluate_multiscenario(params: dict[str, Any], seed_offsets: list[int], scenarios: list[dict[str, Any]], workdir: str, stage: str, objective: str) -> dict[str, Any]:
    per: list[dict[str, Any]] = []
    scores=[]; deliveries=[]; sybils=[]; ppss=[]; drops=[]; risks=[]; hits=[]
    for si, sc in enumerate(scenarios):
        vals={k:[] for k in ["score","delivery","drop","sybil","risk","hops","latency","generated","pps","wall_pps"]}
        for off in seed_offsets:
            seed = off + si * 1000003 + int(params["candidate_id"]) * 17
            r = eval_one_seed(params, seed, sc, workdir)
            for k, v in r.items():
                vals[k].append(float(v))
        agg={"scenario": sc["name"]}
        for k, xs in vals.items():
            m, sd = stats_mean(xs)
            agg[k]=m; agg[k+"_std"]=sd
        agg["target_hits"] = scenario_score(agg)  # type: ignore[arg-type]
        per.append(agg)
        scores.append(float(agg["score"])); deliveries.append(float(agg["delivery"])); sybils.append(float(agg["sybil"])); ppss.append(float(agg["pps"])); drops.append(float(agg["drop"])); risks.append(float(agg["risk"])); hits.append(float(agg["target_hits"]))
    mean_score, score_std = stats_mean(scores)
    mean_delivery, delivery_std = stats_mean(deliveries)
    mean_sybil, sybil_std = stats_mean(sybils)
    mean_pps, pps_std = stats_mean(ppss)
    target_hits_mean = statistics.mean(hits)
    robust_score = compute_robust_score(
        mean_score=mean_score,
        score_std=score_std,
        min_score=min(scores),
        mean_delivery=mean_delivery,
        min_delivery=min(deliveries),
        mean_sybil=mean_sybil,
        max_sybil=max(sybils),
        target_hits_mean=target_hits_mean,
        objective=objective,
    )
    out: dict[str, Any] = {
        "candidate_id": params["candidate_id"],
        "parent": params.get("parent", "unknown"),
        "stage": stage,
        "robust_score": robust_score,
        "mean_score": mean_score,
        "score_std": score_std,
        "min_score": min(scores),
        "mean_delivery": mean_delivery,
        "delivery_std": delivery_std,
        "min_delivery": min(deliveries),
        "mean_sybil": mean_sybil,
        "sybil_std": sybil_std,
        "max_sybil": max(sybils),
        "mean_pps": mean_pps,
        "pps_std": pps_std,
        "min_pps": min(ppss),
        "mean_drop": statistics.mean(drops),
        "mean_risk": statistics.mean(risks),
        "target_hits_mean": target_hits_mean,
        "scenario_count": len(scenarios),
        "seed_count": len(seed_offsets),
        "params": json.dumps({k:v for k,v in params.items() if k not in {"candidate_id", "parent"}}, sort_keys=True),
        "scenario_metrics": json.dumps(per, sort_keys=True),
    }
    return out


def write_row(path: Path, row: dict[str, Any]) -> None:
    exists = path.exists()
    with path.open("a", newline="") as f:
        w = csv.DictWriter(f, fieldnames=FIELDS, extrasaction="ignore")
        if not exists:
            w.writeheader()
        w.writerow(row)


def best_key(r: dict[str, Any]) -> tuple[float, float, float, float]:
    return (float(r["robust_score"]), float(r["min_score"]), -float(r["max_sybil"]), float(r["mean_delivery"]))


def diverse_elite_ids(rows: list[dict[str, Any]], limit: int) -> list[int]:
    """Quality-diversity style survivor selection.

    Instead of forwarding only the single scalar objective, keep elites from
    complementary niches: robust all-rounders, worst-case survivors, low-Sybil
    profiles, delivery specialists, and high target-hit profiles. This is a
    lightweight MAP-Elites approximation over existing CSV metrics.
    """
    selectors = [
        lambda r: (float(r["robust_score"]), float(r["min_score"]), -float(r["max_sybil"])),
        lambda r: (float(r["min_score"]), float(r["robust_score"]), -float(r["max_sybil"])),
        lambda r: (-float(r["max_sybil"]), float(r["min_score"]), float(r["robust_score"])),
        lambda r: (float(r["mean_delivery"]), float(r["min_delivery"]), -float(r["max_sybil"])),
        lambda r: (float(r["target_hits_mean"]), float(r["robust_score"]), float(r["min_score"])),
        lambda r: (float(r["mean_score"]), float(r["score_std"]) * -1.0, float(r["min_score"])),
    ]
    selected: list[int] = []
    seen: set[int] = set()
    quota = max(1, math.ceil(limit / len(selectors)))
    for key in selectors:
        for row in sorted(rows, key=key, reverse=True):
            cid = int(row["candidate_id"])
            if cid in seen:
                continue
            selected.append(cid)
            seen.add(cid)
            if len(selected) >= limit or len(selected) % quota == 0:
                break
        if len(selected) >= limit:
            break
    for row in sorted(rows, key=best_key, reverse=True):
        cid = int(row["candidate_id"])
        if cid not in seen:
            selected.append(cid)
            seen.add(cid)
        if len(selected) >= limit:
            break
    return selected


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--base-profile", default="profiles/aegis-prod-edge-v1.json")
    ap.add_argument("--parent-top10", default="docs/results/heavy_score_max_top10.csv")
    ap.add_argument("--candidates", type=int, default=8192)
    ap.add_argument("--stage1-seeds", type=int, default=3)
    ap.add_argument("--stage2-seeds", type=int, default=20)
    ap.add_argument("--stage3-seeds", type=int, default=80)
    ap.add_argument("--top-k", type=int, default=160)
    ap.add_argument("--final-k", type=int, default=24)
    ap.add_argument("--workers", type=int, default=max(1, os.cpu_count() or 1))
    ap.add_argument("--outdir", default="runs/refine_edge_global_v1")
    ap.add_argument("--seed", type=int, default=20260612)
    ap.add_argument("--scenario-limit", type=int, default=0, help="for smoke tests only")
    ap.add_argument("--objective", choices=["balanced", "sybil_stress", "delivery_stress"], default="balanced")
    ap.add_argument("--selection", choices=["scalar", "diverse"], default="diverse")
    args = ap.parse_args()
    outdir=Path(args.outdir); outdir.mkdir(parents=True, exist_ok=True)
    state_dir=outdir/"states"; state_dir.mkdir(exist_ok=True)
    scenarios = SCENARIOS[:args.scenario_limit] if args.scenario_limit else SCENARIOS
    base=load_base_profile(Path(args.base_profile))
    parents=load_parent_profiles([Path(args.parent_top10)], base)
    candidates=make_candidates(base, parents, args.candidates, args.seed)
    meta={"started_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"), "target": TARGET, "args": vars(args), "scenarios": scenarios, "parent_count": len(parents), "candidate_count": len(candidates)}
    (outdir/"meta.json").write_text(json.dumps(meta, indent=2, sort_keys=True))
    print(f"REFINE_EDGE_GLOBAL start candidates={len(candidates)} scenarios={len(scenarios)} workers={args.workers}", flush=True)
    print(f"objective={args.objective} selection={args.selection}", flush=True)
    stage1_path=outdir/"stage1_results.csv"; stage2_path=outdir/"stage2_results.csv"; stage3_path=outdir/"stage3_results.csv"; best_path=outdir/"best.json"
    stage1_seeds=list(range(args.seed, args.seed+args.stage1_seeds))
    stage1=[]
    with ProcessPoolExecutor(max_workers=args.workers) as ex:
        futs=[ex.submit(evaluate_multiscenario, c, stage1_seeds, scenarios, str(state_dir), "stage1", args.objective) for c in candidates]
        for i,fut in enumerate(as_completed(futs), start=1):
            row=fut.result(); stage1.append(row); write_row(stage1_path,row)
            if i % 25 == 0 or float(row["target_hits_mean"]) >= 3.5:
                best=max(stage1, key=best_key)
                best_path.write_text(json.dumps(best, indent=2, sort_keys=True))
                print(f"stage1 {i}/{len(candidates)} best id={best['candidate_id']} robust={best['robust_score']:.4f} mean={best['mean_score']:.4f} min={best['min_score']:.4f} delivery={best['mean_delivery']:.4f} sybil={best['mean_sybil']:.4f}/{best['max_sybil']:.4f} pps={best['mean_pps']:.1f}", flush=True)
    s1=sorted(stage1, key=best_key, reverse=True)
    by_id={c["candidate_id"]:c for c in candidates}
    top_ids = diverse_elite_ids(stage1, args.top_k) if args.selection == "diverse" else [int(r["candidate_id"]) for r in s1[:args.top_k]]
    top=[by_id[i] for i in top_ids]
    print(f"STAGE2 validating top {len(top)} on {args.stage2_seeds} seeds x {len(scenarios)} scenarios", flush=True)
    stage2_seeds=list(range(args.seed+100000, args.seed+100000+args.stage2_seeds))
    stage2=[]
    with ProcessPoolExecutor(max_workers=args.workers) as ex:
        futs=[ex.submit(evaluate_multiscenario, c, stage2_seeds, scenarios, str(state_dir), "stage2", args.objective) for c in top]
        for i,fut in enumerate(as_completed(futs), start=1):
            row=fut.result(); stage2.append(row); write_row(stage2_path,row)
            best=max(stage2, key=best_key)
            best_path.write_text(json.dumps(best, indent=2, sort_keys=True))
            print(f"stage2 {i}/{len(top)} best id={best['candidate_id']} robust={best['robust_score']:.4f} mean={best['mean_score']:.4f} min={best['min_score']:.4f} delivery={best['mean_delivery']:.4f} sybil={best['mean_sybil']:.4f}/{best['max_sybil']:.4f} pps={best['mean_pps']:.1f}", flush=True)
    s2=sorted(stage2, key=best_key, reverse=True)
    final_ids = diverse_elite_ids(stage2, args.final_k) if args.selection == "diverse" else [int(r["candidate_id"]) for r in s2[:args.final_k]]
    top3=[by_id[i] for i in final_ids]
    print(f"STAGE3 validating final {len(top3)} on {args.stage3_seeds} seeds x {len(scenarios)} scenarios", flush=True)
    stage3_seeds=list(range(args.seed+200000, args.seed+200000+args.stage3_seeds))
    stage3=[]
    with ProcessPoolExecutor(max_workers=args.workers) as ex:
        futs=[ex.submit(evaluate_multiscenario, c, stage3_seeds, scenarios, str(state_dir), "stage3", args.objective) for c in top3]
        for i,fut in enumerate(as_completed(futs), start=1):
            row=fut.result(); stage3.append(row); write_row(stage3_path,row)
            best=max(stage3, key=best_key)
            best_path.write_text(json.dumps(best, indent=2, sort_keys=True))
            print(f"stage3 {i}/{len(top3)} best id={best['candidate_id']} robust={best['robust_score']:.4f} mean={best['mean_score']:.4f} min={best['min_score']:.4f} delivery={best['mean_delivery']:.4f} sybil={best['mean_sybil']:.4f}/{best['max_sybil']:.4f} pps={best['mean_pps']:.1f}", flush=True)
    final=max(stage3 or stage2 or stage1, key=best_key)
    final["finished_at"] = time.strftime("%Y-%m-%dT%H:%M:%S%z")
    best_path.write_text(json.dumps(final, indent=2, sort_keys=True))
    print("=== FINAL GLOBAL BEST ===", flush=True)
    print(json.dumps(final, indent=2, sort_keys=True), flush=True)


if __name__ == "__main__":
    main()
