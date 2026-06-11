#!/usr/bin/env python3
from __future__ import annotations

import argparse
import csv
import itertools
import json
import math
import os
import random
import statistics
import time
from concurrent.futures import ProcessPoolExecutor, as_completed
from dataclasses import asdict
from pathlib import Path
from typing import Any

from aegis_router.agent import HybridRoutingScorer
from aegis_router.event_sim import EventDrivenSimulator
from aegis_router.graph import generate_random_graph
from aegis_router.solvers import AdaptiveRiskSolver, EdgeLearningSolver, HybridSolver, RiskAwareHybridSolver

TARGET = {
    "score": 0.3484,
    "delivery": 0.6284,
    "sybil": 0.1599,  # stricter than old 0.1699, from secure run8
    "pps": 14.2,
}

# Score reverse-engineered from the user's reference: roughly
# score ~= delivery - sybil - 0.1 * drop, with a tiny throughput bonus.
def composite(delivery: float, sybil: float, drop: float, pps: float) -> float:
    pps_bonus = min(0.03, max(0.0, (pps - 9.6) / 1000.0))
    return delivery - sybil - 0.10 * drop + pps_bonus


def stats_mean(xs: list[float]) -> tuple[float, float]:
    if not xs:
        return 0.0, 0.0
    if len(xs) == 1:
        return xs[0], 0.0
    return statistics.mean(xs), statistics.pstdev(xs)


def make_solver(params: dict[str, Any], state_path: str | None = None):
    scorer = HybridRoutingScorer(
        latency_weight=params["latency_weight"],
        loss_weight=params["loss_weight"],
        bandwidth_weight=params["bandwidth_weight"],
        stability_weight=params["stability_weight"],
        progress_weight=params["progress_weight"],
        loop_penalty=params["loop_penalty"],
        low_ttl_penalty=params["low_ttl_penalty"],
    )
    kind = params["solver"]
    if kind == "hybrid":
        return HybridSolver(scorer)
    if kind == "risk":
        return RiskAwareHybridSolver(
            scorer=scorer,
            risk_budget=params["risk_budget"],
            reputation_penalty=params["reputation_penalty"],
            reputation_decay=params["reputation_decay"],
        )
    if kind == "adaptive":
        return AdaptiveRiskSolver(
            scorer=scorer,
            risk_budget=params["risk_budget"],
            min_budget=params["min_budget"],
            max_budget=params["max_budget"],
            adapt_step=params["adapt_step"],
            window_size=params["window_size"],
            drop_threshold=params["drop_threshold"],
            sybil_threshold=params["sybil_threshold"],
            reputation_penalty=params["reputation_penalty"],
            reputation_decay=params["reputation_decay"],
        )
    if kind == "edge":
        assert state_path is not None
        return EdgeLearningSolver(
            state_path=state_path,
            scorer=scorer,
            risk_budget=params["risk_budget"],
            min_budget=params["min_budget"],
            max_budget=params["max_budget"],
            adapt_step=params["adapt_step"],
            window_size=params["window_size"],
            drop_threshold=params["drop_threshold"],
            sybil_threshold=params["sybil_threshold"],
            reputation_penalty=params["reputation_penalty"],
            reputation_decay=params["reputation_decay"],
            learned_penalty=params["learned_penalty"],
            edge_penalty=params["edge_penalty"],
        )
    raise ValueError(kind)


def eval_one_seed(params: dict[str, Any], seed: int, args: dict[str, Any], workdir: str) -> dict[str, float]:
    graph = generate_random_graph(nodes=args["nodes"], degree=args["degree"], sybil_ratio=args["sybil_ratio"], seed=seed)
    start = time.perf_counter()
    solver_kind = params["solver"]
    state_path = None
    if solver_kind == "edge":
        state_path = str(Path(workdir) / f"state_c{params['candidate_id']}_s{seed}.json")
        try:
            Path(state_path).unlink()
        except FileNotFoundError:
            pass
        # Warm-up / learning phase on the same topology with independent RNG streams.
        for run in range(args["learn_runs"]):
            solver = make_solver(params, state_path)
            sim = EventDrivenSimulator(
                graph,
                solver,
                seed=seed * 1000 + 17 + run,
                ttl=args["ttl"],
                queue_service_time=args["queue_service_time"],
                sybil_extra_drop=args["sybil_extra_drop"],
            )
            sim.run(duration=args["train_duration"], traffic_rate=args["train_traffic_rate"], drain_time=args["drain"])
            save = getattr(solver, "save", None)
            if save is not None:
                save()
    solver = make_solver(params, state_path)
    sim = EventDrivenSimulator(
        graph,
        solver,
        seed=seed * 1000 + 999,
        ttl=args["ttl"],
        queue_service_time=args["queue_service_time"],
        sybil_extra_drop=args["sybil_extra_drop"],
    )
    st = sim.run(duration=args["eval_duration"], traffic_rate=args["eval_traffic_rate"], drain_time=args["drain"])
    wall = max(1e-9, time.perf_counter() - start)
    duration_pps = st.generated / max(1e-9, args["eval_duration"] + args["drain"])
    wall_pps = st.generated / wall
    pps = duration_pps
    delivery = st.delivery_ratio
    drop = st.drop_ratio
    sybil = st.sybil_touch_ratio
    return {
        "score": composite(delivery, sybil, drop, pps),
        "delivery": delivery,
        "drop": drop,
        "sybil": sybil,
        "risk": st.avg_loss_risk,
        "hops": st.avg_hops if math.isfinite(st.avg_hops) else 999.0,
        "latency": st.avg_latency if math.isfinite(st.avg_latency) else 999.0,
        "generated": float(st.generated),
        "pps": pps,
        "wall_pps": wall_pps,
    }


def evaluate_candidate(params: dict[str, Any], seeds: list[int], args: dict[str, Any], workdir: str) -> dict[str, Any]:
    vals: dict[str, list[float]] = {k: [] for k in ["score", "delivery", "drop", "sybil", "risk", "hops", "latency", "generated", "pps", "wall_pps"]}
    for seed in seeds:
        r = eval_one_seed(params, seed, args, workdir)
        for k, v in r.items():
            vals[k].append(float(v))
    out: dict[str, Any] = {"candidate_id": params["candidate_id"], "solver": params["solver"]}
    for k, xs in vals.items():
        mean, sd = stats_mean(xs)
        out[k] = mean
        out[k + "_std"] = sd
    out["beats_score"] = out["score"] > TARGET["score"]
    out["beats_delivery"] = out["delivery"] > TARGET["delivery"]
    out["beats_sybil"] = out["sybil"] < TARGET["sybil"]
    out["beats_pps"] = out["pps"] > TARGET["pps"]
    out["target_hits"] = sum(bool(out[k]) for k in ["beats_score", "beats_delivery", "beats_sybil", "beats_pps"])
    out["params"] = json.dumps({k: v for k, v in params.items() if k != "candidate_id"}, sort_keys=True)
    return out


def sample_candidate(rng: random.Random, candidate_id: int) -> dict[str, Any]:
    solver = rng.choices(["edge", "adaptive", "risk", "hybrid"], weights=[0.55, 0.25, 0.15, 0.05], k=1)[0]
    # Mix broad random search with priors that favor sybil avoidance without killing delivery.
    return {
        "candidate_id": candidate_id,
        "solver": solver,
        "latency_weight": rng.uniform(0.2, 5.5),
        "loss_weight": 10 ** rng.uniform(math.log10(4.0), math.log10(90.0)),
        "bandwidth_weight": rng.uniform(0.0, 1.2),
        "stability_weight": rng.uniform(0.0, 4.0),
        "progress_weight": rng.uniform(1.0, 10.0),
        "loop_penalty": rng.uniform(4.0, 40.0),
        "low_ttl_penalty": rng.uniform(0.0, 5.0),
        "risk_budget": rng.uniform(0.08, 0.48),
        "min_budget": rng.uniform(0.04, 0.18),
        "max_budget": rng.uniform(0.25, 0.70),
        "adapt_step": rng.uniform(0.01, 0.12),
        "window_size": rng.choice([5, 8, 10, 12, 16, 24, 32]),
        "drop_threshold": rng.uniform(0.20, 0.65),
        "sybil_threshold": rng.uniform(0.10, 0.55),
        "reputation_penalty": rng.uniform(0.0, 18.0),
        "reputation_decay": rng.uniform(0.70, 0.98),
        "learned_penalty": rng.uniform(0.0, 16.0),
        "edge_penalty": rng.uniform(0.0, 20.0),
    }


def seed_baselines() -> list[dict[str, Any]]:
    candidates = []
    cid = 0
    for solver in ["edge", "adaptive", "risk", "hybrid"]:
        for loss_weight in [16, 24, 36, 48, 64]:
            for risk_budget in [0.10, 0.14, 0.18, 0.22, 0.30, 0.38]:
                cid += 1
                candidates.append({
                    "candidate_id": cid,
                    "solver": solver,
                    "latency_weight": 2.0,
                    "loss_weight": float(loss_weight),
                    "bandwidth_weight": 0.35,
                    "stability_weight": 1.5,
                    "progress_weight": 4.0,
                    "loop_penalty": 20.0,
                    "low_ttl_penalty": 0.7,
                    "risk_budget": risk_budget,
                    "min_budget": 0.08,
                    "max_budget": 0.55,
                    "adapt_step": 0.04,
                    "window_size": 12,
                    "drop_threshold": 0.40,
                    "sybil_threshold": 0.25,
                    "reputation_penalty": 6.0,
                    "reputation_decay": 0.88,
                    "learned_penalty": 6.0,
                    "edge_penalty": 8.0,
                })
    return candidates


def write_row(path: Path, row: dict[str, Any]) -> None:
    fields = [
        "candidate_id", "solver", "score", "delivery", "drop", "sybil", "risk", "pps", "wall_pps", "hops", "latency",
        "target_hits", "beats_score", "beats_delivery", "beats_sybil", "beats_pps", "params",
    ]
    exists = path.exists()
    with path.open("a", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fields, extrasaction="ignore")
        if not exists:
            w.writeheader()
        w.writerow(row)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--candidates", type=int, default=2000)
    ap.add_argument("--stage1-seeds", type=int, default=8)
    ap.add_argument("--stage2-seeds", type=int, default=50)
    ap.add_argument("--top-k", type=int, default=48)
    ap.add_argument("--workers", type=int, default=max(1, os.cpu_count() or 1))
    ap.add_argument("--outdir", default="runs/heavy_secure")
    ap.add_argument("--seed", type=int, default=20260611)
    ap.add_argument("--nodes", type=int, default=120)
    ap.add_argument("--degree", type=int, default=6)
    ap.add_argument("--sybil-ratio", type=float, default=0.20)
    ap.add_argument("--ttl", type=int, default=22)
    ap.add_argument("--queue-service-time", type=float, default=0.018)
    ap.add_argument("--sybil-extra-drop", type=float, default=0.22)
    ap.add_argument("--train-duration", type=float, default=18.0)
    ap.add_argument("--train-traffic-rate", type=float, default=26.0)
    ap.add_argument("--eval-duration", type=float, default=20.0)
    ap.add_argument("--eval-traffic-rate", type=float, default=30.0)
    ap.add_argument("--drain", type=float, default=12.0)
    ap.add_argument("--learn-runs", type=int, default=8)
    args_ns = ap.parse_args()
    args = vars(args_ns)
    outdir = Path(args_ns.outdir)
    outdir.mkdir(parents=True, exist_ok=True)
    state_dir = outdir / "states"
    state_dir.mkdir(parents=True, exist_ok=True)
    stage1_path = outdir / "stage1_results.csv"
    stage2_path = outdir / "stage2_50seed_results.csv"
    best_path = outdir / "best.json"
    meta = {"target": TARGET, "args": args, "started_at": time.strftime("%Y-%m-%dT%H:%M:%S%z")}
    (outdir / "meta.json").write_text(json.dumps(meta, indent=2, sort_keys=True))

    rng = random.Random(args_ns.seed)
    candidates = seed_baselines()
    next_id = max(c["candidate_id"] for c in candidates) + 1
    while len(candidates) < args_ns.candidates:
        candidates.append(sample_candidate(rng, next_id))
        next_id += 1

    print(f"HEAVY_SECURE_SEARCH start candidates={len(candidates)} workers={args_ns.workers}", flush=True)
    print(f"target score>{TARGET['score']} delivery>{TARGET['delivery']} sybil<{TARGET['sybil']} pps>{TARGET['pps']}", flush=True)

    stage1_seeds = list(range(args_ns.seed, args_ns.seed + args_ns.stage1_seeds))
    stage1 = []
    with ProcessPoolExecutor(max_workers=args_ns.workers) as ex:
        futs = [ex.submit(evaluate_candidate, c, stage1_seeds, args, str(state_dir)) for c in candidates]
        for i, fut in enumerate(as_completed(futs), start=1):
            row = fut.result()
            stage1.append(row)
            write_row(stage1_path, row)
            if i % 25 == 0 or row["target_hits"] >= 3:
                best = max(stage1, key=lambda r: (r["target_hits"], r["score"], -r["sybil"], r["delivery"]))
                print(f"stage1 {i}/{len(candidates)} best id={best['candidate_id']} hits={best['target_hits']} score={best['score']:.4f} delivery={best['delivery']:.4f} sybil={best['sybil']:.4f} pps={best['pps']:.1f}", flush=True)
                best_path.write_text(json.dumps(best, indent=2, sort_keys=True))

    stage1_sorted = sorted(stage1, key=lambda r: (r["target_hits"], r["score"], -r["sybil"], r["delivery"]), reverse=True)
    top_ids = {r["candidate_id"] for r in stage1_sorted[: args_ns.top_k]}
    by_id = {c["candidate_id"]: c for c in candidates}
    top_candidates = [by_id[i] for i in top_ids]
    print(f"STAGE2 validating top {len(top_candidates)} on {args_ns.stage2_seeds} seeds", flush=True)
    stage2_seeds = list(range(args_ns.seed + 100000, args_ns.seed + 100000 + args_ns.stage2_seeds))
    stage2 = []
    with ProcessPoolExecutor(max_workers=args_ns.workers) as ex:
        futs = [ex.submit(evaluate_candidate, c, stage2_seeds, args, str(state_dir)) for c in top_candidates]
        for i, fut in enumerate(as_completed(futs), start=1):
            row = fut.result()
            stage2.append(row)
            write_row(stage2_path, row)
            best = max(stage2, key=lambda r: (r["target_hits"], r["score"], -r["sybil"], r["delivery"]))
            print(f"stage2 {i}/{len(top_candidates)} best id={best['candidate_id']} hits={best['target_hits']} score={best['score']:.4f} delivery={best['delivery']:.4f} sybil={best['sybil']:.4f} pps={best['pps']:.1f}", flush=True)
            best_path.write_text(json.dumps(best, indent=2, sort_keys=True))

    final = max(stage2, key=lambda r: (r["target_hits"], r["score"], -r["sybil"], r["delivery"])) if stage2 else stage1_sorted[0]
    final["finished_at"] = time.strftime("%Y-%m-%dT%H:%M:%S%z")
    best_path.write_text(json.dumps(final, indent=2, sort_keys=True))
    print("=== FINAL BEST ===", flush=True)
    print(json.dumps(final, indent=2, sort_keys=True), flush=True)


if __name__ == "__main__":
    main()
