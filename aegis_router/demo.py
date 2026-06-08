from __future__ import annotations

import argparse

from .sim import EvalStats, run_experiment


def fmt(s: EvalStats) -> str:
    return (
        f"livraison={s.delivered_ratio*100:5.1f}% | "
        f"hops={s.avg_hops:5.2f} | "
        f"latence={s.avg_latency:6.3f} | "
        f"risque_perte={s.avg_loss_risk:6.3f} | "
        f"touch_sybil={s.sybil_touch_ratio*100:5.1f}%"
    )


def main() -> None:
    p = argparse.ArgumentParser(description="Aegis Router DRL/MARL prototype demo")
    p.add_argument("--nodes", type=int, default=80)
    p.add_argument("--episodes", type=int, default=300)
    p.add_argument("--packets", type=int, default=250)
    p.add_argument("--sybil-ratio", type=float, default=0.15)
    p.add_argument("--seed", type=int, default=7)
    args = p.parse_args()

    shortest, learned, hybrid = run_experiment(
        nodes=args.nodes,
        episodes=args.episodes,
        packets=args.packets,
        sybil_ratio=args.sybil_ratio,
        seed=args.seed,
    )
    print("Aegis Router - simulation P2P anonyme")
    print(f"noeuds={args.nodes} episodes={args.episodes} paquets_eval={args.packets} sybil_ratio={args.sybil_ratio:.2f}")
    print("shortest-path :", fmt(shortest))
    print("agent Q-local :", fmt(learned))
    print("hybrid v0.2   :", fmt(hybrid))
    print()
    print("Interpretation: plus le risque_perte et touch_sybil sont bas, plus le routage contourne les liens suspects.")


if __name__ == "__main__":
    main()
