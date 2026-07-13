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
import math
import sys
import time
from pathlib import Path
from statistics import mean, stdev

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from aegis_router.daemon import run_local_cluster  # noqa: E402


def _fmt_pct(x: float) -> str:
    return f"{x * 100:5.1f}%"


# Two-sided 95% Student t critical values, indexed by degrees of freedom.
# Keeping the table local avoids adding scipy to a benchmark that otherwise only
# needs the standard library. Above 30 degrees of freedom, 1.96 is a close and
# slightly optimistic normal approximation.
_T_CRITICAL_95 = {
    1: 12.706, 2: 4.303, 3: 3.182, 4: 2.776, 5: 2.571,
    6: 2.447, 7: 2.365, 8: 2.306, 9: 2.262, 10: 2.228,
    11: 2.201, 12: 2.179, 13: 2.160, 14: 2.145, 15: 2.131,
    16: 2.120, 17: 2.110, 18: 2.101, 19: 2.093, 20: 2.086,
    21: 2.080, 22: 2.074, 23: 2.069, 24: 2.064, 25: 2.060,
    26: 2.056, 27: 2.052, 28: 2.048, 29: 2.045, 30: 2.042,
}

_AGGREGATE_METRICS = (
    ("delivery_ratio", "delivery", 0.0, 1.0),
    ("sybil_touch_ratio", "sybil_touch", 0.0, 1.0),
    ("transit_sybil_touch_ratio", "transit_sybil_touch", 0.0, 1.0),
    ("avg_hops", "avg_hops", 0.0, None),
)


def _confidence_interval(
    values: list[float],
    *,
    lower: float | None = None,
    upper: float | None = None,
) -> tuple[float, float]:
    """Return a two-sided 95% CI for independent seed-level observations.

    Bounds are appropriate for constrained metrics: ratios cannot leave [0, 1]
    and hop counts cannot be negative. A single observation has no estimable
    between-seed variance, so its descriptive interval collapses to that value;
    callers must not treat a one-seed result as statistically significant.
    """
    finite_values = [float(value) for value in values if math.isfinite(value)]
    if not finite_values:
        raise ValueError("a confidence interval requires at least one finite value")

    centre = mean(finite_values)
    if len(finite_values) == 1:
        low = high = centre
    else:
        degrees_of_freedom = len(finite_values) - 1
        critical = _T_CRITICAL_95.get(degrees_of_freedom, 1.96)
        half_width = critical * stdev(finite_values) / math.sqrt(len(finite_values))
        low, high = centre - half_width, centre + half_width

    if lower is not None:
        low = max(lower, low)
        high = max(lower, high)
    if upper is not None:
        low = min(upper, low)
        high = min(upper, high)
    # Floating-point clipping must never move the sample mean outside its CI.
    return min(low, centre), max(high, centre)


def _finite_metric_mean(runs: list[dict], key: str) -> float | None:
    values = [
        float(run[key])
        for run in runs
        if run.get(key) is not None and math.isfinite(float(run[key]))
    ]
    return mean(values) if values else None


def _reset_edge_state(topo_seed: int, nodes: int) -> None:
    """Start each seed-level learning campaign from reproducible state.

    Sequential ``learn_runs`` for a seed still share their saved state. Only
    leftovers from an earlier benchmark invocation are removed, so rerunning a
    held-out seed cannot silently inherit evidence gathered by a previous run.
    """
    for node in range(nodes):
        state_seed = topo_seed * 1000 + node
        Path(f"/tmp/aegis_daemon_node_state_{state_seed}.json").unlink(
            missing_ok=True,
        )


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
        perturb_interval=args.perturb_interval,
        eigentrust_pretrusted=getattr(args, "eigentrust_pretrusted", None),
        eigentrust_recompute_interval=getattr(
            args, "eigentrust_recompute_interval", 0.5,
        ),
        seed=topo_seed,
    )

    results: dict[str, list[dict]] = {}
    port = base_port
    for solver_name in args.solvers:
        runs = args.learn_runs if solver_name == "edge" else 1
        if solver_name == "edge":
            _reset_edge_state(topo_seed, args.nodes)
        run_results = []
        for i in range(runs):
            stats = await run_local_cluster(**common, solver_name=solver_name, base_port=port)
            run_results.append(stats.summary())
        results[solver_name] = run_results
        port += args.nodes + 20  # headroom so back-to-back solver runs never share a port range
    return results


def _aggregate(all_seed_results: list[dict], solver_name: str, tail: int) -> dict:
    """Aggregate trailing runs within each seed, then aggregate across seeds.

    Each topology seed contributes exactly one observation regardless of how many
    learning runs it contains. This preserves paired comparisons and prevents a
    solver with more learning runs from receiving extra statistical weight.
    """
    if tail < 1:
        raise ValueError("tail must be at least 1")
    if not all_seed_results:
        raise ValueError("at least one topology seed is required")

    per_seed_means = []
    for seed_result in all_seed_results:
        if solver_name not in seed_result or not seed_result[solver_name]:
            raise ValueError(f"missing runs for solver {solver_name!r}")
        runs = seed_result[solver_name][-tail:]
        per_seed_means.append({
            "delivery_ratio": _finite_metric_mean(runs, "delivery_ratio"),
            "sybil_touch_ratio": _finite_metric_mean(runs, "sybil_touch_ratio"),
            "transit_sybil_touch_ratio": _finite_metric_mean(runs, "transit_sybil_touch_ratio"),
            "avg_hops": _finite_metric_mean(runs, "avg_hops"),
            "retransmissions": _finite_metric_mean(runs, "retransmissions"),
            "generated": _finite_metric_mean(runs, "generated"),
        })

    aggregate: dict[str, object] = {
        "n_seeds": len(per_seed_means),
        # Retained for the paired analysis below; order matches all_seed_results.
        "per_seed": per_seed_means,
    }
    for metric, output_prefix, lower, upper in _AGGREGATE_METRICS:
        values = [seed[metric] for seed in per_seed_means if seed[metric] is not None]
        if not values:
            aggregate[metric] = None
            aggregate[f"{output_prefix}_ci"] = None
            aggregate[f"{output_prefix}_spread"] = None
            continue
        aggregate[metric] = mean(values)
        aggregate[f"{output_prefix}_ci"] = _confidence_interval(
            values, lower=lower, upper=upper,
        )
        aggregate[f"{output_prefix}_spread"] = max(values) - min(values)

    for metric in ("retransmissions", "generated"):
        values = [seed[metric] for seed in per_seed_means if seed[metric] is not None]
        aggregate[metric] = mean(values) if values else None
    return aggregate


def _paired_comparison(
    all_seed_results: list[dict],
    solver_name: str,
    tail: int,
    baseline_name: str = "shortest",
) -> dict:
    """Return seed-paired improvement deltas against the baseline.

    Positive always means improvement: candidate minus baseline for delivery,
    baseline minus candidate for Sybil exposure and hops. Absolute Sybil deltas
    are therefore percentage-point reductions, not relative percentages.
    """
    candidate = _aggregate(all_seed_results, solver_name, tail)
    baseline = _aggregate(all_seed_results, baseline_name, tail)
    orientations = {
        "delivery_ratio": 1.0,
        "sybil_touch_ratio": -1.0,
        "transit_sybil_touch_ratio": -1.0,
        "avg_hops": -1.0,
    }

    metric_results = {}
    for metric, orientation in orientations.items():
        deltas = []
        for candidate_seed, baseline_seed in zip(candidate["per_seed"], baseline["per_seed"]):
            candidate_value = candidate_seed[metric]
            baseline_value = baseline_seed[metric]
            if candidate_value is None or baseline_value is None:
                continue
            deltas.append(orientation * (candidate_value - baseline_value))

        if not deltas:
            metric_results[metric] = {
                "mean": None, "ci": None, "spread": None,
                "significant": False, "n": 0,
            }
            continue
        interval = _confidence_interval(deltas)
        significant = len(deltas) >= 2 and (interval[0] > 0.0 or interval[1] < 0.0)
        metric_results[metric] = {
            "mean": mean(deltas),
            "ci": interval,
            "spread": max(deltas) - min(deltas),
            "significant": significant,
            "n": len(deltas),
        }

    return {
        "solver": solver_name,
        "baseline": baseline_name,
        "n_seeds": len(all_seed_results),
        "metrics": metric_results,
    }


def _fmt_ci(interval: tuple[float, float] | None, *, percentage_points: bool) -> str:
    if interval is None:
        return "n/a"
    scale = 100.0 if percentage_points else 1.0
    suffix = "pp" if percentage_points else ""
    return f"[{interval[0] * scale:.2f}, {interval[1] * scale:.2f}]{suffix}"


def _fmt_aggregate_metric(
    aggregate: dict,
    metric: str,
    prefix: str,
    *,
    proportion: bool,
) -> str:
    value = aggregate[metric]
    interval = aggregate[f"{prefix}_ci"]
    spread = aggregate[f"{prefix}_spread"]
    if value is None or interval is None or spread is None:
        return "n/a"
    if proportion:
        return f"{_fmt_pct(value)} CI95={_fmt_ci(interval, percentage_points=True)} spread={spread * 100:.2f}pp"
    return f"{value:.2f} CI95={_fmt_ci(interval, percentage_points=False)} spread={spread:.2f}"


def _fmt_paired_metric(metric: dict, *, percentage_points: bool) -> str:
    if metric["mean"] is None:
        return "n/a"
    scale = 100.0 if percentage_points else 1.0
    suffix = "pp" if percentage_points else ""
    if metric["significant"]:
        conclusion = "significant improvement" if metric["mean"] > 0.0 else "significant regression"
    elif metric["n"] < 2:
        conclusion = "insufficient seeds"
    else:
        conclusion = "not significant"
    return (
        f"{metric['mean'] * scale:+.2f}{suffix} CI95="
        f"{_fmt_ci(metric['ci'], percentage_points=percentage_points)}; {conclusion}; n={metric['n']}"
    )


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
            hops = "n/a" if last["avg_hops"] is None else f"{last['avg_hops']:.2f}"
            print(f"seed={topo_seed} {solver_name:14s} deliv={_fmt_pct(last['delivery_ratio'])} "
                  f"sybil={_fmt_pct(last['sybil_touch_ratio'])} transit={_fmt_pct(last['transit_sybil_touch_ratio'])} "
                  f"hops={hops} retx={last['retransmissions']} "
                  f"({len(runs)} run(s), {elapsed:.0f}s for this seed)")

    print(f"\n-- aggregated over {args.topology_seeds} topology seed(s), tail-{args.tail} mean --")
    aggs = {}
    for solver_name in args.solvers:
        agg = _aggregate(all_results, solver_name, args.tail)
        aggs[solver_name] = agg
        retransmissions = "n/a" if agg["retransmissions"] is None else f"{agg['retransmissions']:.1f}"
        generated = "n/a" if agg["generated"] is None else f"{agg['generated']:.0f}"
        print(
            f"{solver_name:14s} delivery={_fmt_aggregate_metric(agg, 'delivery_ratio', 'delivery', proportion=True)} | "
            f"raw-sybil={_fmt_aggregate_metric(agg, 'sybil_touch_ratio', 'sybil_touch', proportion=True)}"
        )
        print(
            f"{'':14s} transit-sybil={_fmt_aggregate_metric(agg, 'transit_sybil_touch_ratio', 'transit_sybil_touch', proportion=True)} | "
            f"hops={_fmt_aggregate_metric(agg, 'avg_hops', 'avg_hops', proportion=False)} | "
            f"retx/run={retransmissions} packets/run={generated}"
        )

    if "shortest" in aggs:
        print(
            "\n-- paired deltas versus shortest, by topology seed "
            "(positive = improvement; Sybil deltas are absolute reductions) --"
        )
        for solver_name in args.solvers:
            if solver_name == "shortest":
                continue
            comparison = _paired_comparison(all_results, solver_name, args.tail)
            metrics = comparison["metrics"]
            print(
                f"{solver_name:14s} delivery gain="
                f"{_fmt_paired_metric(metrics['delivery_ratio'], percentage_points=True)} | "
                f"raw-sybil reduction="
                f"{_fmt_paired_metric(metrics['sybil_touch_ratio'], percentage_points=True)}"
            )
            print(
                f"{'':14s} transit-sybil reduction="
                f"{_fmt_paired_metric(metrics['transit_sybil_touch_ratio'], percentage_points=True)} | "
                f"hops reduction="
                f"{_fmt_paired_metric(metrics['avg_hops'], percentage_points=False)}"
            )

            # Preserve the historical relative-reduction point estimates without
            # confusing them with the paired absolute-delta significance test.
            for label, key in (("raw", "sybil_touch_ratio"), ("transit", "transit_sybil_touch_ratio")):
                reference = aggs["shortest"][key]
                observed = aggs[solver_name][key]
                if reference is not None and observed is not None and reference > 0:
                    reduction = (reference - observed) / reference * 100
                    print(
                        f"{'':14s} {label} relative reduction point estimate="
                        f"{reduction:+.1f}% (descriptive only; significance uses paired deltas above)"
                    )

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
    p.add_argument("--solvers", default="shortest,edge", help="comma-separated: shortest,risk-aware,adaptive-risk,eigentrust,edge")
    p.add_argument("--eigentrust-pretrusted", default="", help="comma-separated external trust anchors; empty uses uniform pretrust")
    p.add_argument("--eigentrust-recompute-interval", type=float, default=0.5)
    p.add_argument("--topology-seeds", type=int, default=2, help="number of independent topology/traffic draws")
    p.add_argument("--learn-runs", type=int, default=3, help="sequential persistent-state runs per seed for the edge solver")
    p.add_argument("--tail", type=int, default=2, help="how many trailing learn-runs to average per seed")
    p.add_argument("--base-seed", type=int, default=10000)
    p.add_argument("--base-port", type=int, default=35000)
    args = p.parse_args()
    args.solvers = [s.strip() for s in args.solvers.split(",") if s.strip()]
    args.eigentrust_pretrusted = tuple(
        int(node) for node in args.eigentrust_pretrusted.split(",") if node.strip()
    ) or None
    args.tail = min(args.tail, args.learn_runs)

    asyncio.run(main_async(args))


if __name__ == "__main__":
    main()
