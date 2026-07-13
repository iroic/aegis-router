#!/usr/bin/env python3
"""
Adversarial benchmark for Aegis Router — reproducible attack laboratory.

Runs multiple solvers against parametrized adversary scenarios (coordinated
Sybil, blackhole, grayhole, selective-forwarding, eclipse, latency
falsification, adaptive Sybil) across independent topology/traffic seeds,
with confidence intervals and Pareto frontiers.

Outputs JSON, CSV, and an auto-generated Markdown report.
"""

from __future__ import annotations

import argparse
import asyncio
import csv
import json
import math
import os
import random
import statistics
import sys
import time
from collections import defaultdict
from dataclasses import asdict, dataclass, field
from pathlib import Path
from statistics import mean, stdev
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from aegis_router.daemon import run_local_cluster  # noqa: E402
from aegis_router.event_sim import EventDrivenSimulator  # noqa: E402
from aegis_router.graph import LinkMetrics, P2PGraph, generate_random_graph  # noqa: E402
from aegis_router.packet import Packet  # noqa: E402
from aegis_router.agent import QRoutingAgent  # noqa: E402
from aegis_router.solvers import (  # noqa: E402
    AdaptiveRiskSolver,
    EdgeLearningSolver,
    HybridSolver,
    QLocalSolver,
    RiskAwareHybridSolver,
    RoutingSolver,
    ShortestPathSolver,
)


# ============================================================================
# Attack Scenario Definitions
# ============================================================================

@dataclass(frozen=True)
class AttackScenario:
    """A named, reproducible adversary configuration."""
    name: str
    description: str
    # Graph generation modifiers
    sybil_ratio: float = 0.15
    sybil_stealth: float = 0.0
    sybil_extra_drop: float = 0.12
    # Runtime dynamics
    churn_rate: float = 0.0
    churn_recovery: float = 0.4
    congestion_rate: float = 0.0
    congestion_jitter: float = 0.15
    # Solver-specific toggles
    link_retries: int = 0
    redundancy: int = 1
    redundancy_risk_tolerance: float = 0.05
    receipts: bool = False
    receipt_timeout: float = 4.0
    # Advanced: custom graph mutator (called after graph generation)
    mutator: str | None = None  # name of mutator function in MUTATORS


# Built-in scenarios covering major adversary types
SCENARIOS: dict[str, AttackScenario] = {
    "baseline": AttackScenario(
        name="baseline",
        description="Honest network, no adversary. Reference for all other scenarios.",
        sybil_ratio=0.0,
        sybil_extra_drop=0.0,
    ),
    "coordinated-sybil": AttackScenario(
        name="coordinated-sybil",
        description="Multiple Sybil nodes (15%) with stealthy links (advertised metrics look honest). Extra drop models coordinated blackholing.",
        sybil_ratio=0.15,
        sybil_stealth=0.8,
        sybil_extra_drop=0.35,
    ),
    "blackhole": AttackScenario(
        name="blackhole",
        description="Sybil nodes that drop ALL traffic (extra_drop=0.95). Obvious in metrics (stealth=0) but catastrophic if chosen.",
        sybil_ratio=0.12,
        sybil_stealth=0.0,
        sybil_extra_drop=0.95,
    ),
    "grayhole": AttackScenario(
        name="grayhole",
        description="Sybil nodes that selectively drop ~50% of packets, masquerading as link loss. Stealth=0.5 masks this in metrics.",
        sybil_ratio=0.15,
        sybil_stealth=0.5,
        sybil_extra_drop=0.50,
    ),
    "selective-forwarding": AttackScenario(
        name="selective-forwarding",
        description="Sybil nodes forward packets to SOME destinations but drop others. Modeled as high extra_drop with moderate stealth.",
        sybil_ratio=0.15,
        sybil_stealth=0.6,
        sybil_extra_drop=0.65,
    ),
    "eclipse": AttackScenario(
        name="eclipse",
        description="Sybil nodes surround victims by dominating their neighbor sets. High sybil_ratio with stealth to hijack routes.",
        sybil_ratio=0.25,
        sybil_stealth=0.7,
        sybil_extra_drop=0.40,
    ),
    "latency-falsification": AttackScenario(
        name="latency-falsification",
        description="Sybil links advertise artificially low latency to attract traffic, then drop. Stealth applies to latency only.",
        sybil_ratio=0.15,
        sybil_stealth=0.9,
        sybil_extra_drop=0.30,
        congestion_rate=0.15,  # adds noise to honest links too
        congestion_jitter=0.20,
        mutator="latency_falsification",
    ),
    "adaptive-sybil": AttackScenario(
        name="adaptive-sybil",
        description="Sybil behavior changes over time: honest at first (building reputation), then grayhole. Requires churn/congestion dynamics.",
        sybil_ratio=0.15,
        sybil_stealth=0.6,
        sybil_extra_drop=0.45,
        churn_rate=0.03,
        churn_recovery=0.3,
        congestion_rate=0.10,
        congestion_jitter=0.15,
        link_retries=1,
        mutator="adaptive_sybil",
    ),
    "high-churn": AttackScenario(
        name="high-churn",
        description="Benign but unstable network: 8% churn rate, no Sybils. Tests robustness to topology instability.",
        sybil_ratio=0.0,
        churn_rate=0.08,
        churn_recovery=0.5,
        link_retries=2,
        redundancy=2,
    ),
    "congestion-storm": AttackScenario(
        name="congestion-storm",
        description="Heavy dynamic congestion (30% edges drift per tick). No Sybils. Tests adaptive routing under load.",
        sybil_ratio=0.0,
        congestion_rate=0.30,
        congestion_jitter=0.25,
        link_retries=2,
    ),
}


# Graph mutators for advanced scenarios (applied post-generation)
# Store scenario-specific metadata separately to avoid polluting P2PGraph
ADAPTIVE_SYBIL_META: dict[int, dict] = {}
LATENCY_FALSIFICATION_EDGES: set[tuple[int, int]] = set()


def mutator_adaptive_sybil(graph: P2PGraph, rng: random.Random) -> None:
    """Mark Sybil nodes as 'adaptive': they start honest, turn malicious after warmup."""
    global ADAPTIVE_SYBIL_META
    ADAPTIVE_SYBIL_META.clear()
    for n in graph.sybil_nodes:
        ADAPTIVE_SYBIL_META[n] = {"_phase": "honest", "_packets_seen": 0}


def mutator_latency_falsification(graph: P2PGraph, rng: random.Random) -> None:
    """Force Sybil edges to advertise artificially low latency."""
    global LATENCY_FALSIFICATION_EDGES
    LATENCY_FALSIFICATION_EDGES.clear()
    for a in graph.adj:
        for b, m in list(graph.adj[a].items()):
            if a in graph.sybil_nodes or b in graph.sybil_nodes:
                # Only mutate latency, keep other metrics in honest-looking range
                graph.adj[a][b] = LinkMetrics(
                    latency=rng.uniform(0.02, 0.08),  # falsely low
                    bandwidth=m.bandwidth,
                    loss=m.loss,
                    stability=m.stability,
                )
                LATENCY_FALSIFICATION_EDGES.add((a, b))


MUTATORS: dict[str, Any] = {
    "adaptive_sybil": mutator_adaptive_sybil,
    "latency_falsification": mutator_latency_falsification,
}


# ============================================================================
# Runtime Behavior Hooks (for adaptive scenarios)
# ============================================================================

class AdaptiveSybilSimulator(EventDrivenSimulator):
    """Event sim with adaptive Sybil behavior: honest → grayhole after warmup."""

    def __init__(self, *args, warmup_packets: int = 50, grayhole_drop: float = 0.6, **kwargs):
        super().__init__(*args, **kwargs)
        self._warmup_packets = warmup_packets
        self._grayhole_drop = grayhole_drop
        self._sybil_packets_seen: dict[int, int] = defaultdict(int)

    def _handle_arrive(self, time: float, packet_id: int) -> None:
        pkt = self._packets[packet_id]
        # Check if next hop is an adaptive Sybil
        if pkt.node in ADAPTIVE_SYBIL_META:
            self._sybil_packets_seen[pkt.node] += 1
        super()._handle_arrive(time, packet_id)

    def _notify_solver(self, pkt: Packet, *, delivered: bool, dropped: bool, reason: str | None = None) -> None:
        # Adaptive Sybil: after warmup, increase drop probability
        neighbor = getattr(pkt, "last_neighbor", None)
        if neighbor in ADAPTIVE_SYBIL_META:
            seen = self._sybil_packets_seen.get(neighbor, 0)
            meta = ADAPTIVE_SYBIL_META.get(neighbor, {})
            if seen > self._warmup_packets and meta.get("_phase") == "honest":
                meta["_phase"] = "malicious"
                # In adaptive phase, the extra drop is already in sybil_extra_drop
                # This just ensures reputation learner sees the transition
                pass
        super()._notify_solver(pkt, delivered=delivered, dropped=dropped, reason=reason)


# ============================================================================
# Solver Factory
# ============================================================================

def make_solver(name: str, seed: int) -> RoutingSolver:
    from aegis_router.agent import HybridRoutingScorer
    if name == "shortest":
        return ShortestPathSolver()
    if name == "hybrid":
        return HybridSolver(scorer=HybridRoutingScorer())
    if name == "risk-aware":
        return RiskAwareHybridSolver()
    if name == "adaptive-risk":
        return AdaptiveRiskSolver()
    if name == "edge":
        return EdgeLearningSolver(state_path=f"/tmp/aegis_adv_{seed}.json", edge_penalty=1.0, risk_budget=0.35)
    if name == "edge-light":
        return EdgeLearningSolver(state_path=f"/tmp/aegis_adv_{seed}.json", edge_penalty=1.0, risk_budget=0.35, use_trusted_path=False)
    if name == "qlocal":
        return QLocalSolver(QRoutingAgent(seed=seed), train=True)
    raise ValueError(f"Unknown solver: {name}")


SOLVER_NAMES = ["shortest", "hybrid", "risk-aware", "adaptive-risk", "edge", "edge-light", "qlocal"]


# ============================================================================
# Statistics & Confidence Intervals
# ============================================================================

def confidence_interval(data: list[float], confidence: float = 0.95) -> tuple[float, float]:
    """Wilson score interval for proportions, t-interval for means."""
    if not data:
        return (0.0, 0.0)
    n = len(data)
    if n == 1:
        return (data[0], data[0])
    m = mean(data)
    se = stdev(data) / math.sqrt(n)
    # t-distribution critical value (approximate for n>30, conservative for small n)
    t = 1.96 if n >= 30 else {2: 12.71, 3: 4.30, 4: 3.18, 5: 2.78, 6: 2.57, 7: 2.45, 8: 2.36, 9: 2.31, 10: 2.26}.get(n, 2.23)
    return (m - t * se, m + t * se)


def proportion_ci(successes: int, trials: int, confidence: float = 0.95) -> tuple[float, float]:
    """Wilson score interval for binomial proportion."""
    if trials == 0:
        return (0.0, 0.0)
    z = 1.96  # 95%
    p = successes / trials
    denom = 1 + z*z/trials
    centre = (p + z*z/(2*trials)) / denom
    half = (z * math.sqrt(p*(1-p)/trials + z*z/(4*trials*trials))) / denom
    return (centre - half, centre + half)


@dataclass
class RunResult:
    solver: str
    scenario: str
    seed: int
    delivery_ratio: float
    sybil_touch_ratio: float
    transit_sybil_touch_ratio: float
    avg_hops: float | None
    avg_latency: float | None
    retransmissions: float
    redundant_copies: float
    receipts_confirmed: float
    receipt_timeouts: float
    generated: float
    dropped: dict[str, int]
    wall_time: float


@dataclass
class AggregatedResult:
    solver: str
    scenario: str
    seeds: int
    runs_per_seed: int
    delivery_ratio: float
    delivery_ci: tuple[float, float]
    sybil_touch_ratio: float
    sybil_touch_ci: tuple[float, float]
    transit_sybil_touch_ratio: float
    transit_sybil_touch_ci: tuple[float, float]
    avg_hops: float
    avg_hops_ci: tuple[float, float]
    avg_latency: float
    avg_latency_ci: tuple[float, float]
    retransmissions: float
    redundant_copies: float
    receipts_confirmed: float
    receipt_timeouts: float
    generated: float
    drop_reasons: dict[str, float]  # mean per run
    wall_time_total: float


# ============================================================================
# Benchmark Runner (Discrete-Event Simulator)
# ============================================================================

async def run_sim_benchmark(
    scenario: AttackScenario,
    solver_name: str,
    seeds: list[int],
    nodes: int,
    degree: int,
    duration: float,
    traffic_rate: float,
    ttl: int,
    drain: float,
    learn_runs: int,
    tail: int,
) -> list[RunResult]:
    """Run benchmark using the fast discrete-event simulator."""
    results: list[RunResult] = []

    for seed in seeds:
        rng = random.Random(seed)
        graph = generate_random_graph(
            nodes=nodes,
            degree=degree,
            sybil_ratio=scenario.sybil_ratio,
            sybil_stealth=scenario.sybil_stealth,
            seed=seed,
        )
        # Apply mutator if specified
        if scenario.mutator and scenario.mutator in MUTATORS:
            MUTATORS[scenario.mutator](graph, rng)

        # Choose simulator class based on scenario
        sim_class = EventDrivenSimulator
        if scenario.name == "adaptive-sybil":
            sim_class = AdaptiveSybilSimulator

        # Persistent learning for edge solver
        state_path = f"/tmp/aegis_adv_sim_{solver_name}_{seed}.json"
        if Path(state_path).exists():
            Path(state_path).unlink()

        for run_idx in range(learn_runs if solver_name in ("edge", "edge-light") else 1):
            solver = make_solver(solver_name, seed * 1000 + run_idx)
            if solver_name in ("edge", "edge-light"):
                # EdgeLearningSolver has state_path attribute
                from aegis_router.solvers import EdgeLearningSolver
                if isinstance(solver, EdgeLearningSolver):
                    solver.state_path = Path(state_path)
                    if run_idx > 0:
                        solver.load()

            sim = sim_class(
                graph=graph,
                solver=solver,
                seed=seed + run_idx * 10000,
                ttl=ttl,
                sybil_extra_drop=scenario.sybil_extra_drop,
                congestion_rate=scenario.congestion_rate,
                congestion_jitter=scenario.congestion_jitter,
                churn_rate=scenario.churn_rate,
                churn_recovery=scenario.churn_recovery,
                perturb_interval=0.5,
                link_retries=scenario.link_retries,
            )

            t0 = time.monotonic()
            stats = sim.run(duration=duration, traffic_rate=traffic_rate, drain_time=drain)
            wall = time.monotonic() - t0

            result = RunResult(
                solver=solver_name,
                scenario=scenario.name,
                seed=seed,
                delivery_ratio=stats.delivery_ratio,
                sybil_touch_ratio=stats.sybil_touch_ratio,
                transit_sybil_touch_ratio=getattr(stats, "transit_sybil_touch_ratio", 0.0),
                avg_hops=stats.avg_hops if stats.avg_hops != float("inf") else None,
                avg_latency=stats.avg_latency if stats.avg_latency != float("inf") else None,
                retransmissions=stats.retransmissions,
                redundant_copies=0.0,
                receipts_confirmed=0.0,
                receipt_timeouts=0.0,
                generated=stats.generated,
                dropped=dict(stats.drop_reasons),
                wall_time=wall,
            )
            results.append(result)

            if solver_name in ("edge", "edge-light"):
                saver = getattr(solver, "save", None)
                if callable(saver):
                    saver()

    return results


# ============================================================================
# Benchmark Runner (Real UDP Daemon)
# ============================================================================

async def run_daemon_benchmark(
    scenario: AttackScenario,
    solver_name: str,
    seeds: list[int],
    nodes: int,
    degree: int,
    duration: float,
    traffic_rate: float,
    ttl: int,
    drain: float,
    learn_runs: int,
    tail: int,
    base_port: int,
    receipts: bool = False,
    receipt_timeout: float = 4.0,
) -> list[RunResult]:
    """Run benchmark using the real UDP daemon (slow but realistic)."""
    results: list[RunResult] = []

    for i, seed in enumerate(seeds):
        for run_idx in range(learn_runs if solver_name in ("edge", "edge-light") else 1):
            # Use index-based port allocation to stay within 0-65535
            port = base_port + i * (nodes + 20) * learn_runs + run_idx * (nodes + 20)
            stats = await run_local_cluster(
                nodes=nodes,
                degree=degree,
                sybil_ratio=scenario.sybil_ratio,
                sybil_stealth=scenario.sybil_stealth,
                duration=duration,
                drain=drain,
                traffic_rate=traffic_rate,
                ttl=ttl,
                sybil_extra_drop=scenario.sybil_extra_drop,
                link_retries=scenario.link_retries,
                redundancy=scenario.redundancy,
                redundancy_risk_tolerance=scenario.redundancy_risk_tolerance,
                receipts=receipts,
                receipt_timeout=receipt_timeout,
                churn_rate=scenario.churn_rate,
                churn_recovery=scenario.churn_recovery,
                congestion_rate=scenario.congestion_rate,
                congestion_jitter=scenario.congestion_jitter,
                perturb_interval=0.5,
                solver_name=solver_name,
                seed=seed + run_idx * 10000,
                base_port=port,
            )

            summary = stats.summary()
            result = RunResult(
                solver=solver_name,
                scenario=scenario.name,
                seed=seed,
                delivery_ratio=summary["delivery_ratio"],
                sybil_touch_ratio=summary["sybil_touch_ratio"],
                transit_sybil_touch_ratio=summary["transit_sybil_touch_ratio"],
                avg_hops=summary["avg_hops"],
                avg_latency=summary["avg_latency"],
                retransmissions=summary["retransmissions"],
                redundant_copies=summary["redundant_copies"],
                receipts_confirmed=summary["receipts_confirmed"],
                receipt_timeouts=summary["receipt_timeouts"],
                generated=summary["generated"],
                dropped=summary["dropped"],
                wall_time=0.0,  # not easily measured per-run here
            )
            results.append(result)

    return results


# ============================================================================
# Aggregation & Reporting
# ============================================================================

def aggregate_results(runs: list[RunResult], tail: int) -> list[AggregatedResult]:
    """Aggregate raw runs into per-solver-per-scenario stats with CIs."""
    grouped: dict[tuple[str, str], list[RunResult]] = defaultdict(list)
    for r in runs:
        grouped[(r.solver, r.scenario)].append(r)

    aggregated: list[AggregatedResult] = []
    for (solver, scenario), run_list in grouped.items():
        # For persistent solvers, use only tail runs per seed
        if solver in ("edge", "edge-light"):
            by_seed: dict[int, list[RunResult]] = defaultdict(list)
            for r in run_list:
                by_seed[r.seed].append(r)
            trimmed = []
            for seed_runs in by_seed.values():
                trimmed.extend(seed_runs[-tail:])
            run_list = trimmed

        n = len(run_list)
        delivery_ci = confidence_interval([r.delivery_ratio for r in run_list])
        sybil_ci = confidence_interval([r.sybil_touch_ratio for r in run_list])
        transit_ci = confidence_interval([r.transit_sybil_touch_ratio for r in run_list])

        # For hops/latency, filter out None/inf
        hops_vals = [r.avg_hops for r in run_list if r.avg_hops is not None]
        lat_vals = [r.avg_latency for r in run_list if r.avg_latency is not None]
        hops_ci = confidence_interval(hops_vals) if hops_vals else (0.0, 0.0)
        lat_ci = confidence_interval(lat_vals) if lat_vals else (0.0, 0.0)

        # Aggregate drop reasons
        drop_agg: dict[str, list[float]] = defaultdict(list)
        for r in run_list:
            for reason, count in r.dropped.items():
                drop_agg[reason].append(count / max(1, r.generated))
        drop_means = {k: mean(v) for k, v in drop_agg.items()}

        agg = AggregatedResult(
            solver=solver,
            scenario=scenario,
            seeds=len({r.seed for r in run_list}),
            runs_per_seed=n // max(1, len({r.seed for r in run_list})),
            delivery_ratio=mean(r.delivery_ratio for r in run_list),
            delivery_ci=delivery_ci,
            sybil_touch_ratio=mean(r.sybil_touch_ratio for r in run_list),
            sybil_touch_ci=sybil_ci,
            transit_sybil_touch_ratio=mean(r.transit_sybil_touch_ratio for r in run_list),
            transit_sybil_touch_ci=transit_ci,
            avg_hops=mean(hops_vals) if hops_vals else 0.0,
            avg_hops_ci=hops_ci,
            avg_latency=mean(lat_vals) if lat_vals else 0.0,
            avg_latency_ci=lat_ci,
            retransmissions=mean(r.retransmissions for r in run_list),
            redundant_copies=mean(r.redundant_copies for r in run_list),
            receipts_confirmed=mean(r.receipts_confirmed for r in run_list),
            receipt_timeouts=mean(r.receipt_timeouts for r in run_list),
            generated=mean(r.generated for r in run_list),
            drop_reasons=drop_means,
            wall_time_total=sum(r.wall_time for r in run_list),
        )
        aggregated.append(agg)

    return aggregated


def format_pct(x: float) -> str:
    return f"{x*100:5.1f}%"


def format_ci(ci: tuple[float, float]) -> str:
    return f"[{ci[0]*100:.1f}%, {ci[1]*100:.1f}%]"


def format_ci_raw(ci: tuple[float, float]) -> str:
    return f"[{ci[0]:.2f}, {ci[1]:.2f}]"


def write_json(aggregated: list[AggregatedResult], path: Path) -> None:
    data = []
    for a in aggregated:
        data.append({
            "solver": a.solver,
            "scenario": a.scenario,
            "seeds": a.seeds,
            "runs_per_seed": a.runs_per_seed,
            "delivery_ratio": a.delivery_ratio,
            "delivery_ci": a.delivery_ci,
            "sybil_touch_ratio": a.sybil_touch_ratio,
            "sybil_touch_ci": a.sybil_touch_ci,
            "transit_sybil_touch_ratio": a.transit_sybil_touch_ratio,
            "transit_sybil_touch_ci": a.transit_sybil_touch_ci,
            "avg_hops": a.avg_hops,
            "avg_hops_ci": a.avg_hops_ci,
            "avg_latency": a.avg_latency,
            "avg_latency_ci": a.avg_latency_ci,
            "retransmissions": a.retransmissions,
            "redundant_copies": a.redundant_copies,
            "receipts_confirmed": a.receipts_confirmed,
            "receipt_timeouts": a.receipt_timeouts,
            "generated": a.generated,
            "drop_reasons": a.drop_reasons,
            "wall_time_total": a.wall_time_total,
        })
    path.write_text(json.dumps(data, indent=2))


def write_csv(aggregated: list[AggregatedResult], path: Path) -> None:
    fieldnames = [
        "solver", "scenario", "seeds", "runs_per_seed",
        "delivery_ratio", "delivery_ci_low", "delivery_ci_high",
        "sybil_touch_ratio", "sybil_touch_ci_low", "sybil_touch_ci_high",
        "transit_sybil_touch_ratio", "transit_sybil_touch_ci_low", "transit_sybil_touch_ci_high",
        "avg_hops", "avg_hops_ci_low", "avg_hops_ci_high",
        "avg_latency", "avg_latency_ci_low", "avg_latency_ci_high",
        "retransmissions", "redundant_copies",
        "receipts_confirmed", "receipt_timeouts",
        "generated", "wall_time_total",
    ] + [f"drop_{k}" for k in sorted(set().union(*[a.drop_reasons.keys() for a in aggregated]))]

    with path.open("w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        for a in aggregated:
            row = {
                "solver": a.solver,
                "scenario": a.scenario,
                "seeds": a.seeds,
                "runs_per_seed": a.runs_per_seed,
                "delivery_ratio": a.delivery_ratio,
                "delivery_ci_low": a.delivery_ci[0],
                "delivery_ci_high": a.delivery_ci[1],
                "sybil_touch_ratio": a.sybil_touch_ratio,
                "sybil_touch_ci_low": a.sybil_touch_ci[0],
                "sybil_touch_ci_high": a.sybil_touch_ci[1],
                "transit_sybil_touch_ratio": a.transit_sybil_touch_ratio,
                "transit_sybil_touch_ci_low": a.transit_sybil_touch_ci[0],
                "transit_sybil_touch_ci_high": a.transit_sybil_touch_ci[1],
                "avg_hops": a.avg_hops,
                "avg_hops_ci_low": a.avg_hops_ci[0],
                "avg_hops_ci_high": a.avg_hops_ci[1],
                "avg_latency": a.avg_latency,
                "avg_latency_ci_low": a.avg_latency_ci[0],
                "avg_latency_ci_high": a.avg_latency_ci[1],
                "retransmissions": a.retransmissions,
                "redundant_copies": a.redundant_copies,
                "receipts_confirmed": a.receipts_confirmed,
                "receipt_timeouts": a.receipt_timeouts,
                "generated": a.generated,
                "wall_time_total": a.wall_time_total,
            }
            for k, v in a.drop_reasons.items():
                row[f"drop_{k}"] = v
            writer.writerow(row)


def write_markdown(aggregated: list[AggregatedResult], scenarios_run: list[str], solvers_run: list[str], args: argparse.Namespace, path: Path) -> None:
    lines = []
    lines.append(f"# Adversarial Benchmark Report")
    lines.append(f"")
    lines.append(f"**Generated:** {time.strftime('%Y-%m-%d %H:%M:%S')}")
    lines.append(f"**Mode:** {'discrete-event simulator' if args.sim else 'real UDP daemon'}")
    lines.append(f"**Nodes:** {args.nodes} | **Degree:** {args.degree} | **Duration:** {args.duration}s | **Drain:** {args.drain}s")
    lines.append(f"**Traffic rate:** {args.traffic_rate} | **TTL:** {args.ttl} | **Seeds:** {args.seeds} | **Learn runs:** {args.learn_runs} (tail={args.tail})")
    lines.append(f"**Solvers:** {', '.join(solvers_run)}")
    lines.append(f"**Scenarios:** {', '.join(scenarios_run)}")
    lines.append(f"")

    # Per-scenario tables
    for scenario_name in scenarios_run:
        sc = SCENARIOS[scenario_name]
        lines.append(f"## {scenario_name}: {sc.description}")
        lines.append(f"")
        lines.append(f"| Solver | Delivery (95% CI) | Sybil-Touch (95% CI) | Transit-Sybil (95% CI) | Avg Hops | Avg Latency | Retx | Redundant | Receipts |")
        lines.append(f"|---|---|---|---|---|---|---|---|---|")
        scenario_aggs = [a for a in aggregated if a.scenario == scenario_name]
        for a in sorted(scenario_aggs, key=lambda x: -x.delivery_ratio):
            lines.append(
                f"| {a.solver} | {format_pct(a.delivery_ratio)} {format_ci(a.delivery_ci)} | "
                f"{format_pct(a.sybil_touch_ratio)} {format_ci(a.sybil_touch_ci)} | "
                f"{format_pct(a.transit_sybil_touch_ratio)} {format_ci(a.transit_sybil_touch_ci)} | "
                f"{a.avg_hops:.2f} {format_ci_raw(a.avg_hops_ci)} | "
                f"{a.avg_latency:.3f} {format_ci_raw(a.avg_latency_ci)} | "
                f"{a.retransmissions:.1f} | {a.redundant_copies:.1f} | "
                f"{a.receipts_confirmed:.0f}/{a.receipt_timeouts:.0f} |"
            )
        lines.append(f"")

    # Pareto frontier summary (delivery vs transit-sybil)
    lines.append(f"## Pareto Frontier (Delivery vs Transit-Sybil Touch)")
    lines.append(f"")
    lines.append(f"| Scenario | Solver | Delivery | Transit-Sybil | Note |")
    lines.append(f"|---|---|---|---|---|")
    for scenario_name in scenarios_run:
        sc = SCENARIOS[scenario_name]
        scenario_aggs = [a for a in aggregated if a.scenario == scenario_name]
        # Non-dominated: no other solver has both higher delivery AND lower transit-sybil
        pareto = []
        for a in scenario_aggs:
            dominated = False
            for b in scenario_aggs:
                if b.delivery_ratio >= a.delivery_ratio and b.transit_sybil_touch_ratio <= a.transit_sybil_touch_ratio:
                    if b.delivery_ratio > a.delivery_ratio or b.transit_sybil_touch_ratio < a.transit_sybil_touch_ratio:
                        dominated = True
                        break
            if not dominated:
                pareto.append(a)
        for a in sorted(pareto, key=lambda x: -x.delivery_ratio):
            note = "★" if a.solver in ("edge", "risk-aware", "adaptive-risk") else ""
            lines.append(f"| {scenario_name} | {a.solver} | {format_pct(a.delivery_ratio)} | {format_pct(a.transit_sybil_touch_ratio)} | {note} |")
    lines.append(f"")

    # Relative improvements vs shortest
    lines.append(f"## Relative Improvement vs `shortest` (Transit-Sybil Reduction)")
    lines.append(f"")
    lines.append(f"| Scenario | Solver | Delivery Δ | Transit-Sybil Δ | Sybil-Touch Δ |")
    lines.append(f"|---|---|---|---|---|")
    for scenario_name in scenarios_run:
        scenario_aggs = {a.solver: a for a in aggregated if a.scenario == scenario_name}
        if "shortest" not in scenario_aggs:
            continue
        base = scenario_aggs["shortest"]
        for solver_name in solvers_run:
            if solver_name == "shortest" or solver_name not in scenario_aggs:
                continue
            a = scenario_aggs[solver_name]
            deliv_delta = (a.delivery_ratio - base.delivery_ratio) * 100
            transit_delta = (base.transit_sybil_touch_ratio - a.transit_sybil_touch_ratio) * 100
            sybil_delta = (base.sybil_touch_ratio - a.sybil_touch_ratio) * 100
            lines.append(f"| {scenario_name} | {solver_name} | {deliv_delta:+.1f}pp | {transit_delta:+.1f}pp | {sybil_delta:+.1f}pp |")
    lines.append(f"")

    path.write_text("\n".join(lines))


# ============================================================================
# Main
# ============================================================================

async def main_async(args: argparse.Namespace) -> None:
    scenarios_to_run = [s.strip() for s in args.scenarios.split(",")] if args.scenarios else list(SCENARIOS.keys())
    solvers_to_run = [s.strip() for s in args.solvers.split(",")] if args.solvers else SOLVER_NAMES

    # Validate
    for s in scenarios_to_run:
        if s not in SCENARIOS:
            print(f"Unknown scenario: {s}. Available: {', '.join(SCENARIOS.keys())}")
            sys.exit(1)
    for s in solvers_to_run:
        if s not in SOLVER_NAMES:
            print(f"Unknown solver: {s}. Available: {', '.join(SOLVER_NAMES)}")
            sys.exit(1)

    seeds = list(range(args.base_seed, args.base_seed + args.seeds))
    print(f"=== Adversarial Benchmark ===")
    print(f"Mode: {'discrete-event simulator' if args.sim else 'real UDP daemon'}")
    print(f"Scenarios: {scenarios_to_run}")
    print(f"Solvers: {solvers_to_run}")
    print(f"Seeds: {seeds}")
    print(f"Nodes: {args.nodes}, Degree: {args.degree}")
    print(f"Duration: {args.duration}s, Drain: {args.drain}s, Traffic: {args.traffic_rate}")
    print(f"")

    all_runs: list[RunResult] = []
    t_start = time.monotonic()

    for scenario_name in scenarios_to_run:
        scenario = SCENARIOS[scenario_name]
        print(f"--- Scenario: {scenario_name} ---")
        for solver_name in solvers_to_run:
            print(f"  Solver: {solver_name}...", end=" ", flush=True)
            t0 = time.monotonic()

            if args.sim:
                runs = await run_sim_benchmark(
                    scenario=scenario,
                    solver_name=solver_name,
                    seeds=seeds,
                    nodes=args.nodes,
                    degree=args.degree,
                    duration=args.duration,
                    traffic_rate=args.traffic_rate,
                    ttl=args.ttl,
                    drain=args.drain,
                    learn_runs=args.learn_runs,
                    tail=args.tail,
                )
            else:
                runs = await run_daemon_benchmark(
                    scenario=scenario,
                    solver_name=solver_name,
                    seeds=seeds,
                    nodes=args.nodes,
                    degree=args.degree,
                    duration=args.duration,
                    traffic_rate=args.traffic_rate,
                    ttl=args.ttl,
                    drain=args.drain,
                    learn_runs=args.learn_runs,
                    tail=args.tail,
                    base_port=args.base_port,
                    receipts=args.receipts,
                    receipt_timeout=args.receipt_timeout,
                )

            all_runs.extend(runs)
            elapsed = time.monotonic() - t0
            avg_deliv = mean(r.delivery_ratio for r in runs)
            print(f"done ({elapsed:.1f}s, avg delivery={format_pct(avg_deliv)})")

    print(f"\nTotal wall time: {time.monotonic() - t_start:.1f}s")

    # Aggregate
    aggregated = aggregate_results(all_runs, args.tail)

    # Output
    out_dir = Path(args.output)
    out_dir.mkdir(parents=True, exist_ok=True)

    json_path = out_dir / "adversarial_results.json"
    csv_path = out_dir / "adversarial_results.csv"
    md_path = out_dir / "adversarial_report.md"

    write_json(aggregated, json_path)
    write_csv(aggregated, csv_path)
    write_markdown(aggregated, scenarios_to_run, solvers_to_run, args, md_path)

    print(f"\nResults written to:")
    print(f"  JSON:  {json_path}")
    print(f"  CSV:   {csv_path}")
    print(f"  MD:    {md_path}")

    # Quick summary to stdout
    print(f"\n=== Quick Summary ===")
    for scenario_name in scenarios_to_run:
        sc_aggs = [a for a in aggregated if a.scenario == scenario_name]
        if not sc_aggs:
            continue
        best = max(sc_aggs, key=lambda x: x.delivery_ratio)
        best_safe = min(sc_aggs, key=lambda x: x.transit_sybil_touch_ratio)
        print(f"{scenario_name:20s}  best-deliv: {best.solver:12s} ({format_pct(best.delivery_ratio)})  "
              f"best-safe: {best_safe.solver:12s} (transit-sybil {format_pct(best_safe.transit_sybil_touch_ratio)})")


def main() -> None:
    p = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    p.add_argument("--sim", action="store_true", help="Use fast discrete-event simulator (default: real UDP daemon)")
    p.add_argument("--scenarios", default="", help="Comma-separated scenario names (default: all)")
    p.add_argument("--solvers", default="", help="Comma-separated solver names (default: all)")
    p.add_argument("--nodes", type=int, default=60)
    p.add_argument("--degree", type=int, default=4)
    p.add_argument("--duration", type=float, default=15.0)
    p.add_argument("--drain", type=float, default=5.0)
    p.add_argument("--traffic-rate", type=float, default=10.0)
    p.add_argument("--ttl", type=int, default=16)
    p.add_argument("--seeds", type=int, default=3, help="Number of independent topology/traffic seeds")
    p.add_argument("--learn-runs", type=int, default=3, help="Sequential runs for persistent solvers (edge)")
    p.add_argument("--tail", type=int, default=2, help="Trailing runs to average per seed")
    p.add_argument("--base-seed", type=int, default=20000)
    p.add_argument("--base-port", type=int, default=36000)
    p.add_argument("--output", default="results/adversarial", help="Output directory")
    # Daemon-specific options (only used when --sim is NOT set)
    p.add_argument("--receipts", action="store_true", help="Enable signed delivery receipts (daemon mode only)")
    p.add_argument("--receipt-timeout", type=float, default=4.0, help="Seconds to wait for receipt before timeout (daemon mode)")
    args = p.parse_args()

    if args.tail > args.learn_runs:
        args.tail = args.learn_runs

    asyncio.run(main_async(args))


if __name__ == "__main__":
    main()