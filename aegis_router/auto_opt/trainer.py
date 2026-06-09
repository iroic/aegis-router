#!/usr/bin/env python
"""Optuna‑driven RL optimisation for Aegis Router.
   Uses PPO (default) or SAC, trains on a fixed 200‑node graph.
   Evaluates on 200 episodes and returns the composite score:
       delivery - 0.5*drop - 1*risk - 0.8*sybil
"""
import argparse, sys, os, random
import numpy as np, optuna
from gymnasium import Env, spaces
from stable_baselines3 import PPO, SAC
from stable_baselines3.common.vec_env import DummyVecEnv

# Add project root to import path
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
from aegis_router.graph import generate_random_graph
from aegis_router.event_sim import EventDrivenSimulator
from aegis_router.solvers import RoutingSolver
from .reward import compute_reward

# -----------------------------------------------------------------
class RouterEnv(Env):
    """Gym‑like wrapper around EventDrivenSimulator.
       Returns a flat numpy vector as observation.
    """
    metadata = {"render_modes": []}

    def __init__(self, graph, solver_factory, **sim_kwargs):
        self.graph = graph
        self.solver_factory = solver_factory
        self.sim_kwargs = sim_kwargs
        self.action_space = spaces.Discrete(32)
        self.observation_space = spaces.Box(low=-1e9, high=1e9, shape=(11,), dtype=np.float32)
        self.reset()

    def reset(self, *, seed=None, options=None):
        super().reset(seed=seed)
        self.solver = self.solver_factory()
        self.sim = EventDrivenSimulator(
            self.graph,
            self.solver,
            **self.sim_kwargs,
        )
        # generate a single packet just to obtain an initial state
        self.sim._handle_generate(time=0.0, duration=0.0, traffic_rate=0.0)
        self.current_pkt = next(iter(self.sim._packets.values()))
        self.recent_risks = []
        return self._state_from_packet(self.current_pkt), {}

    def _state_from_packet(self, pkt):
        base = np.array([
            pkt.node,
            pkt.dst,
            pkt.ttl,
            getattr(pkt, "risk_budget", 0.3),
            int(pkt.touched_sybil),
        ], dtype=np.float32)
        neighbors = list(self.graph.adj[pkt.node])
        if not neighbors:
            extra = np.zeros(5, dtype=np.float32)
        else:
            scores = np.array([
                self.solver.scorer.score(
                    self.graph,
                    node=pkt.node,
                    neighbor=n,
                    dst=pkt.dst,
                    visited=pkt.visited,
                    ttl_remaining=pkt.ttl,
                )
                for n in neighbors
            ], dtype=np.float32)
            # fallback beta loss = 0.5 if metric not present
            try:
                betas = np.array([self.graph.edge_metrics[(pkt.node, n)].loss
                                   for n in neighbors], dtype=np.float32)
            except Exception:
                betas = np.full_like(scores, 0.5)
            # hop distance via BFS (cheap for small graphs)
            from collections import deque
            q = deque([(pkt.node, 0)])
            visited = {pkt.node}
            dist = -1
            while q:
                cur, d = q.popleft()
                if cur == pkt.dst:
                    dist = d
                    break
                for nb in self.graph.adj[cur]:
                    if nb not in visited:
                        visited.add(nb)
                        q.append((nb, d+1))
            dist = float(dist if dist >= 0 else len(self.graph.nodes()))
            local_q = np.mean([p.queue_delay for p in self.sim._packets.values() if p.node == pkt.node] or [0.0])
            extra = np.array([
                float(scores.mean()), float(scores.std() if len(scores) > 1 else 0.0),
                float(betas.mean()), float(betas.std() if len(betas) > 1 else 0.0),
                dist, local_q,
            ], dtype=np.float32)
        return np.concatenate([base, extra]).astype(np.float32)

    def step(self, action):
        pkt = self.current_pkt
        neighbors = list(self.graph.adj[pkt.node])
        if not neighbors:
            reward = compute_reward(pkt, delivered=False,
                                    drop_reason="no_route",
                                    recent_risks=self.recent_risks)
            return self._state_from_packet(pkt), reward, True, False, {}
        chosen = neighbors[action % len(neighbors)]
        # ---- emulate one hop (same logic as EventDrivenSimulator._handle_arrive) ----
        if pkt.ttl <= 0 or pkt.node in pkt.visited:
            reward = compute_reward(pkt, delivered=False,
                                    drop_reason="ttl_expired",
                                    recent_risks=self.recent_risks)
            return self._state_from_packet(pkt), reward, True, False, {}
        pkt.visited.add(pkt.node)
        metrics = self.graph.metrics(pkt.node, chosen)
        extra_drop = self.sim.sybil_extra_drop if chosen in self.graph.sybil_nodes else 0.0
        eff_loss = min(0.95, metrics.loss + extra_drop)
        if self.sim.rng.random() < eff_loss:
            pkt.loss_risk = 1.0 - ((1.0 - pkt.loss_risk) * (1.0 - eff_loss))
            pkt.touched_sybil = pkt.touched_sybil or chosen in self.graph.sybil_nodes
            pkt.last_from = pkt.node
            pkt.last_neighbor = chosen
            reason = "sybil_drop" if chosen in self.graph.sybil_nodes else "link_loss"
            reward = compute_reward(pkt, delivered=False,
                                    drop_reason=reason,
                                    recent_risks=self.recent_risks)
            return self._state_from_packet(pkt), reward, True, False, {}
        # success
        key = (pkt.node, chosen)
        available = self.sim._link_available.get(key, pkt.latency)
        start = max(self.sim.rng.random() * 0.0, available)
        queue_delay = max(0.0, start - self.sim.rng.random())
        service = self.sim.queue_service_time / max(0.05, metrics.bandwidth)
        pkt.queue_delay += queue_delay
        pkt.latency += metrics.latency + queue_delay + service
        pkt.loss_risk = 1.0 - ((1.0 - pkt.loss_risk) * (1.0 - eff_loss))
        pkt.touched_sybil = pkt.touched_sybil or chosen in self.graph.sybil_nodes
        pkt.last_from = pkt.node
        pkt.node = chosen
        pkt.last_neighbor = chosen
        pkt.hops += 1
        pkt.ttl -= 1
        self.sim._link_available[key] = start + service
        self.recent_risks.append(pkt.loss_risk)
        if len(self.recent_risks) > 200:
            self.recent_risks.pop(0)
        if pkt.node == pkt.dst:
            reward = compute_reward(pkt, delivered=True,
                                    drop_reason=None,
                                    recent_risks=self.recent_risks)
            return self._state_from_packet(pkt), reward, True, False, {}
        return self._state_from_packet(pkt), 0.0, False, False, {}

# -----------------------------------------------------------------
def evaluate_policy(model, graph, n_episodes=200):
    def packet_obs(pkt):
        neighbors = list(graph.adj[pkt.node])
        base = np.array([
            pkt.node,
            pkt.dst,
            pkt.ttl,
            getattr(pkt, "risk_budget", 0.3),
            int(pkt.touched_sybil),
        ], dtype=np.float32)
        if not neighbors:
            extra = np.zeros(6, dtype=np.float32)
        else:
            from collections import deque
            scores = np.array([
                graph.metrics(pkt.node, n).latency for n in neighbors
            ], dtype=np.float32)
            betas = np.array([graph.metrics(pkt.node, n).loss for n in neighbors], dtype=np.float32)
            q = deque([(pkt.node, 0)])
            visited = {pkt.node}
            dist = -1
            while q:
                cur, d = q.popleft()
                if cur == pkt.dst:
                    dist = d
                    break
                for nb in graph.adj[cur]:
                    if nb not in visited:
                        visited.add(nb)
                        q.append((nb, d+1))
            dist = float(dist if dist >= 0 else len(graph.nodes()))
            extra = np.array([scores.mean(), scores.std() if len(scores)>1 else 0.0,
                              betas.mean(), betas.std() if len(betas)>1 else 0.0,
                              dist, 0.0], dtype=np.float32)
        return np.concatenate([base, extra]).astype(np.float32)

    class RLSolver:
        def next_hop(self, graph, packet):
            obs = packet_obs(packet)
            action, _ = model.predict(obs, deterministic=True)
            neighbors = list(graph.adj[packet.node])
            if not neighbors:
                return None
            return neighbors[int(action) % len(neighbors)]

    delivered = dropped = 0
    total_risk = total_sybil = 0.0
    for _ in range(n_episodes):
        sim = EventDrivenSimulator(
            graph,
            RLSolver(),
            seed=_,
            ttl=20,
            queue_service_time=0.025,
            sybil_extra_drop=0.12,
        )
        stats = sim.run(duration=8.0, traffic_rate=12.0)
        delivered += stats.delivered
        dropped += stats.dropped
        total_risk += stats.avg_loss_risk * stats.generated
        total_sybil += stats.sybil_touch_ratio * stats.generated
    gen = delivered + dropped
    delivery = delivered / max(1, gen) * 100
    drop = dropped / max(1, gen) * 100
    avg_risk = total_risk / max(1, gen)
    avg_sybil = total_sybil / max(1, gen)
    return delivery, drop, avg_risk, avg_sybil

# -----------------------------------------------------------------
def objective(trial):
    lr = trial.suggest_float("learning_rate", 1e-5, 5e-4, log=True)
    clip_range = trial.suggest_float("clip_range", 0.1, 0.3)
    lam_cvar = trial.suggest_float("lambda_cvar", 0.3, 2.0)
    lam_sybil = trial.suggest_float("lambda_sybil", 0.5, 5.0)
    entropy_coef = trial.suggest_float("entropy_coef", 0.0, 0.02)
    algo        = trial.suggest_categorical("algo", ["PPO"])
    seed        = trial.suggest_int("seed", 0, 9999)

    graph = generate_random_graph(nodes=200, sybil_ratio=0.20, seed=42)

    def solver_factory():
        class WrapperSolver(RoutingSolver):
            def __init__(self):
                super().__init__()
                self.lambda_cvar = lam_cvar
                self.lambda_sybil = lam_sybil
                from aegis_router.agent import HybridRoutingScorer
                self.scorer = HybridRoutingScorer()
            def next_hop(self, graph, packet):
                return None
        return WrapperSolver()

    env = DummyVecEnv([lambda: RouterEnv(
        graph,
        solver_factory,
        ttl=20,
        queue_service_time=0.025,
        sybil_extra_drop=0.12,
        seed=seed,
    )])

    if algo == "PPO":
        model = PPO(
            "MlpPolicy",
            env,
            learning_rate=lr,
            clip_range=clip_range,
            ent_coef=entropy_coef,
            verbose=0,
        )
    else:
        model = SAC(
            "MlpPolicy",
            env,
            learning_rate=lr,
            ent_coef=entropy_coef,
            verbose=0,
        )

    model.learn(total_timesteps=20000)
    delivery, drop, risk, sybil = evaluate_policy(model, graph, n_episodes=200)
    score = delivery - 0.5 * drop - 1.0 * risk - 0.8 * sybil
    return score

# -----------------------------------------------------------------
def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("-n", "--trials", type=int, default=30,
                        help="Number of Optuna trials to run")
    args = parser.parse_args()
    study = optuna.create_study(direction="maximize")
    study.optimize(objective, n_trials=args.trials)
    print("\n=== BEST RESULT ===")
    print(f"Score : {study.best_value:.2f}")
    for k, v in study.best_params.items():
        print(f"{k:>15} = {v}")
    # optional: retrain final model and save it
    #   (omitted for brevity, but you could call `objective` again with best params)

if __name__ == "__main__":
    main()
