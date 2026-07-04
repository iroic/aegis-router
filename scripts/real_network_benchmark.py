"""Statistically solid real-network benchmark for aegis_router.daemon.

Everything under `aegis_router.event_sim` is a discrete-event simulator: no
socket, no wall-clock cost, virtual time compresses to milliseconds. This
script exercises the same solvers over *real* asyncio UDP sockets, real
per-packet JSON serialization, and real ML-DSA-44 signing/verification
(aegis_router.daemon), across multiple independent topology seeds so a
single lucky/unlucky draw can't be mistaken for a real effect -- the same
lesson learned the hard way with 20-42 packet single-run comparisons
earlier in this project's history.

Real time actually elapses here (no simulated-time shortcut is possible
once real sockets and real timers are involved): a default run takes a few
minutes. Scale --topology-seeds / --learn-runs / --duration up for a more
rigorous check, or down for a quick smoke test.

Usage:
    .venv/bin/python3 scripts/real_network_benchmark.py
    .venv/bin/python3 scripts/real_network_benchmark.py --nodes 80 --topology-seeds 3 \
        --learn-runs 5 --churn-rate 0.04 --congestion-rate 0.1 --sybil-stealth 0.8 \
        --link-retries 2 --duration 60 --drain 8

Requires the `pqcrypto` package (present in .venv/.venv311, not the system
python) for aegis_router.postquantum_crypto's real ML-DSA-44 signing.
"""
from __future__ import annotations

import argparse
import asyncio
import sys
import time
from pathlib import Path
from statistics import mean

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from aegis_router.daemon import run_local_cluster  # noqa: E402


def _fmt_pct(x: float) -> str:
    return f"{x * 100:5.1f}%"


async def _run_seed(args, topo_seed: int, base_port: int) -> dict:
    common = dict(
        nodes=args.nodes, degree=args.degree, sybil_ratio=args.sybil_ratio,
        sybil_stealth=args.sybil_stealth, sybil_extra_drop=args.sybil_extra_drop,
        duration=args.duration, drain=args.drain,
        traffic_rate=args.traffic_rate, ttl=args.ttl, link_retries=args.link_retries,
        redundancy=args.redundancy, redundancy_risk_tolerance=args.redundancy_risk_tolerance,
        receipts=args.receipts, receipt_timeout=args.receipt_timeout,
        churn_rate=args.churn_rate, churn_recovery=args.churn_recovery,
        congestion_rate=args.congestion_rate, congestion_jitter=args.congestion_jitter,
        perturb_interval=args.perturb_interval, seed=topo_seed,
    )

    results: dict[str, list[dict]] = {}
    port = base_port
    for solver_name in args.solvers:
        runs = args.learn_runs if solver_name == "edge" else 1
        run_results = []
        for i in range(runs):
            stats = await run_local_cluster(**common, solver_name=solver_name, base_port=port)
            run_results.append(stats.summary())
        results[solver_name] = run_results
        port += args.nodes + 20  # headroom so back-to-back solver runs never share a port range
    return results


def _aggregate(all_seed_results: list[dict], solver_name: str, tail: int) -> dict:
    per_seed_means = []
    for seed_result in all_seed_results:
        runs = seed_result[solver_name][-tail:]
        per_seed_means.append({
            "delivery_ratio": mean(r["delivery_ratio"] for r in runs),
            "sybil_touch_ratio": mean(r["sybil_touch_ratio"] for r in runs),
            "transit_sybil_touch_ratio": mean(r["transit_sybil_touch_ratio"] for r in runs),
            "avg_hops": mean(r["avg_hops"] for r in runs if r["avg_hops"] is not None),
            "retransmissions": mean(r["retransmissions"] for r in runs),
            "generated": mean(r["generated"] for r in runs),
        })
    agg = {k: mean(m[k] for m in per_seed_means) for k in per_seed_means[0]}
    agg["delivery_spread"] = max(m["delivery_ratio"] for m in per_seed_means) - min(m["delivery_ratio"] for m in per_seed_means)
    return agg


async def main_async(args) -> None:
    print(f"=== Real-socket benchmark: {args.nodes} nodes, {args.topology_seeds} topology seed(s), "
          f"{args.learn_runs} learn run(s)/seed ===")
    print(f"sybil_ratio={args.sybil_ratio} sybil_stealth={args.sybil_stealth} sybil_extra_drop={args.sybil_extra_drop} "
          f"churn_rate={args.churn_rate} congestion_rate={args.congestion_rate} "
          f"link_retries={args.link_retries} redundancy={args.redundancy} receipts={args.receipts} "
          f"duration={args.duration}s drain={args.drain}s\n")

    all_results = []
    t_start = time.monotonic()
    for i, topo_seed in enumerate(range(args.base_seed, args.base_seed + args.topology_seeds)):
        t0 = time.monotonic()
        seed_result = await _run_seed(args, topo_seed, args.base_port + i * (args.nodes + 20) * len(args.solvers))
        all_results.append(seed_result)
        elapsed = time.monotonic() - t0
        for solver_name, runs in seed_result.items():
            last = runs[-1]
            print(f"seed={topo_seed} {solver_name:14s} deliv={_fmt_pct(last['delivery_ratio'])} "
                  f"sybil={_fmt_pct(last['sybil_touch_ratio'])} transit={_fmt_pct(last['transit_sybil_touch_ratio'])} "
                  f"hops={last['avg_hops']:.2f} retx={last['retransmissions']} "
                  f"({len(runs)} run(s), {elapsed:.0f}s for this seed)")

    print(f"\n-- aggregated over {args.topology_seeds} topology seed(s), tail-{args.tail} mean --")
    aggs = {}
    for solver_name in args.solvers:
        agg = _aggregate(all_results, solver_name, args.tail)
        aggs[solver_name] = agg
        print(f"{solver_name:14s} deliv={_fmt_pct(agg['delivery_ratio'])} "
              f"(spread {agg['delivery_spread']*100:.1f}pp) sybil={_fmt_pct(agg['sybil_touch_ratio'])} "
              f"transit={_fmt_pct(agg['transit_sybil_touch_ratio'])} "
              f"hops={agg['avg_hops']:.2f} retx/run={agg['retransmissions']:.1f} "
              f"packets/run={agg['generated']:.0f}")

    if "shortest" in aggs and "edge" in aggs:
        for label, key in (("raw", "sybil_touch_ratio"), ("transit", "transit_sybil_touch_ratio")):
            ref = aggs["shortest"][key]
            got = aggs["edge"][key]
            if ref > 0:
                reduction = (ref - got) / ref * 100
                print(f"sybil-touch relative reduction, {label} (edge vs shortest): {reduction:.1f}%"
                      + (" (OPTIMIZATION.md v0.2 target: >= 30%)" if label == "transit" else " -- includes the sybil-ratio floor from packets addressed TO a sybil, which no router can avoid"))

    print(f"\ntotal wall clock: {time.monotonic() - t_start:.0f}s")


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--nodes", type=int, default=40)
    p.add_argument("--degree", type=int, default=4)
    p.add_argument("--sybil-ratio", type=float, default=0.15)
    p.add_argument("--sybil-stealth", type=float, default=0.0)
    p.add_argument("--sybil-extra-drop", type=float, default=0.12, help="extra loss added on top of a sybil edge's advertised loss -- 0.12 models a barely-there dropper masked by ARQ, 0.6+ models a deliberate blackholer")
    p.add_argument("--duration", type=float, default=20.0)
    p.add_argument("--drain", type=float, default=5.0)
    p.add_argument("--traffic-rate", type=float, default=12.0)
    p.add_argument("--ttl", type=int, default=16)
    p.add_argument("--link-retries", type=int, default=0)
    p.add_argument("--redundancy", type=int, default=1, help="source-path redundancy: disjoint-first-hop copies per packet")
    p.add_argument("--redundancy-risk-tolerance", type=float, default=0.05)
    p.add_argument("--receipts", action="store_true")
    p.add_argument("--receipt-timeout", type=float, default=4.0)
    p.add_argument("--churn-rate", type=float, default=0.0)
    p.add_argument("--churn-recovery", type=float, default=0.4)
    p.add_argument("--congestion-rate", type=float, default=0.0)
    p.add_argument("--congestion-jitter", type=float, default=0.15)
    p.add_argument("--perturb-interval", type=float, default=0.5)
    p.add_argument("--solvers", default="shortest,edge", help="comma-separated: shortest,risk-aware,adaptive-risk,edge")
    p.add_argument("--topology-seeds", type=int, default=2, help="number of independent topology/traffic draws")
    p.add_argument("--learn-runs", type=int, default=3, help="sequential persistent-state runs per seed for the edge solver")
    p.add_argument("--tail", type=int, default=2, help="how many trailing learn-runs to average per seed")
    p.add_argument("--base-seed", type=int, default=10000)
    p.add_argument("--base-port", type=int, default=35000)
    args = p.parse_args()
    args.solvers = [s.strip() for s in args.solvers.split(",") if s.strip()]
    args.tail = min(args.tail, args.learn_runs)

    asyncio.run(main_async(args))


if __name__ == "__main__":
    main()
