from __future__ import annotations

import argparse

from .agent import HybridRoutingScorer
from .event_sim import EventStats, EventDrivenSimulator
from .graph import generate_random_graph
from .solvers import AdaptiveRiskSolver, HybridSolver, PersistentLearningSolver, RiskAwareHybridSolver, ShortestPathSolver


def fmt(s: EventStats) -> str:
    return (
        f"generated={s.generated:4d} | "
        f"delivery={s.delivery_ratio*100:5.1f}% | "
        f"drop={s.drop_ratio*100:5.1f}% | "
        f"hops={s.avg_hops:5.2f} | "
        f"latency={s.avg_latency:6.3f} | "
        f"queue={s.avg_queue_delay:6.3f} | "
        f"risk={s.avg_loss_risk:6.3f} | "
        f"sybil={s.sybil_touch_ratio*100:5.1f}%"
    )


def main() -> None:
    p = argparse.ArgumentParser(description="Aegis Router v0.3 event-driven simulation")
    p.add_argument("--nodes", type=int, default=80)
    p.add_argument("--duration", type=float, default=8.0)
    p.add_argument("--traffic-rate", type=float, default=12.0)
    p.add_argument("--sybil-ratio", type=float, default=0.2)
    p.add_argument("--ttl", type=int, default=18)
    p.add_argument("--seed", type=int, default=31)
    p.add_argument("--learn", action="store_true", help="enable persistent learning solver")
    p.add_argument("--state", default="aegis_state.json", help="persistent learning state JSON path")
    p.add_argument("--runs", type=int, default=1, help="number of repeated learning runs")
    args = p.parse_args()

    graph = generate_random_graph(nodes=args.nodes, degree=5, sybil_ratio=args.sybil_ratio, seed=args.seed)
    shortest = EventDrivenSimulator(graph, ShortestPathSolver(), seed=args.seed + 1, ttl=args.ttl).run(
        duration=args.duration,
        traffic_rate=args.traffic_rate,
    )
    hybrid = EventDrivenSimulator(
        graph,
        HybridSolver(HybridRoutingScorer(loss_weight=16.0, loop_penalty=20.0)),
        seed=args.seed + 1,
        ttl=args.ttl,
    ).run(duration=args.duration, traffic_rate=args.traffic_rate)

    risk_aware = EventDrivenSimulator(
        graph,
        RiskAwareHybridSolver(),
        seed=args.seed + 1,
        ttl=args.ttl,
    ).run(duration=args.duration, traffic_rate=args.traffic_rate)

    adaptive = EventDrivenSimulator(
        graph,
        AdaptiveRiskSolver(),
        seed=args.seed + 1,
        ttl=args.ttl,
    ).run(duration=args.duration, traffic_rate=args.traffic_rate)

    learned_runs: list[EventStats] = []
    if args.learn:
        for run in range(args.runs):
            solver = PersistentLearningSolver(state_path=args.state)
            stats = EventDrivenSimulator(
                graph,
                solver,
                seed=args.seed + 1 + run,
                ttl=args.ttl,
            ).run(duration=args.duration, traffic_rate=args.traffic_rate)
            solver.save()
            learned_runs.append(stats)

    print("Aegis Router v0.3 - event-driven P2P simulation")
    print(
        f"nodes={args.nodes} duration={args.duration:.1f}s traffic_rate={args.traffic_rate:.1f}/s "
        f"sybil_ratio={args.sybil_ratio:.2f} ttl={args.ttl}"
    )
    print("shortest-path :", fmt(shortest))
    print("hybrid v0.3   :", fmt(hybrid))
    print("risk-aware   :", fmt(risk_aware))
    print("adaptive-risk:", fmt(adaptive))
    for idx, stats in enumerate(learned_runs, start=1):
        print(f"learned #{idx:02d}  :", fmt(stats))
    if args.learn:
        print(f"state file    : {args.state}")
    print()
    print("v0.3 ajoute: trafic Poisson, files d'attente, pertes réelles, TTL, paquets comme épisodes asynchrones.")


if __name__ == "__main__":
    main()
