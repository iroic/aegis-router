from __future__ import annotations

from collections import defaultdict
import random
from typing import Dict, List, Tuple

from .graph import LinkMetrics, NodeId, P2PGraph


State = tuple[int, ...]
Action = NodeId


class QRoutingAgent:
    """Small local Q-learning router.

    It deliberately observes only local link buckets. No IP, payload, sender identity,
    or global topology is used.
    """

    def __init__(self, *, alpha: float = 0.2, gamma: float = 0.88, epsilon: float = 0.18, seed: int | None = None):
        self.alpha = alpha
        self.gamma = gamma
        self.epsilon = epsilon
        self.rng = random.Random(seed)
        self.q: Dict[tuple[NodeId, State, Action], float] = defaultdict(float)

    def state(self, graph: P2PGraph, node: NodeId, dst: NodeId) -> State:
        # Destination is bucketed by ring distance only for simulation. In a real onion/P2P
        # deployment this becomes an opaque route/session hint, never an identity.
        n = max(1, len(graph.adj))
        dist_bucket = min(7, abs(dst - node) * 8 // n)
        neigh = graph.neighbors(node)
        if not neigh:
            return (dist_bucket, 0, 0, 0, 0)
        avg_latency = sum(graph.metrics(node, nb).latency for nb in neigh) / len(neigh)
        avg_loss = sum(graph.metrics(node, nb).loss for nb in neigh) / len(neigh)
        avg_stability = sum(graph.metrics(node, nb).stability for nb in neigh) / len(neigh)
        return (
            dist_bucket,
            _bucket(avg_latency),
            _bucket(avg_loss),
            _bucket(avg_stability),
            min(7, len(neigh)),
        )

    def choose(self, graph: P2PGraph, node: NodeId, dst: NodeId, *, train: bool = True, visited: set[NodeId] | None = None) -> NodeId | None:
        neighbors = graph.neighbors(node)
        if not neighbors:
            return None
        if visited:
            unvisited = [n for n in neighbors if n not in visited]
            if unvisited:
                neighbors = unvisited
        s = self.state(graph, node, dst)
        if train and self.rng.random() < self.epsilon:
            return self.rng.choice(neighbors)
        return max(neighbors, key=lambda nb: self.q[(node, s, nb)] + _link_prior(graph.metrics(node, nb)) + _progress_prior(graph, node, nb, dst))

    def update(self, graph: P2PGraph, node: NodeId, dst: NodeId, action: NodeId, reward: float, next_node: NodeId) -> None:
        s = self.state(graph, node, dst)
        ns = self.state(graph, next_node, dst)
        future = 0.0
        next_neighbors = graph.neighbors(next_node)
        if next_neighbors:
            future = max(self.q[(next_node, ns, nb)] for nb in next_neighbors)
        key = (node, s, action)
        self.q[key] = (1 - self.alpha) * self.q[key] + self.alpha * (reward + self.gamma * future)


def reward_for_link(metrics: LinkMetrics, *, delivered: bool, looped: bool = False) -> float:
    reward = 0.0
    reward -= 0.55  # hop budget pressure: avoid wandering routes
    reward -= 1.4 * metrics.latency
    reward -= 14.0 * metrics.loss
    reward += 0.35 * metrics.bandwidth
    reward += 1.0 * metrics.stability
    if delivered:
        reward += 22.0
    if looped:
        reward -= 8.0
    return reward


def _bucket(v: float) -> int:
    return max(0, min(7, int(v * 8)))


def _link_prior(m: LinkMetrics) -> float:
    # Prior avoids learning from zero with completely random behavior.
    return -2.4 * m.latency - (14.0 * m.loss) + (0.25 * m.bandwidth) + (1.0 * m.stability)


def _progress_prior(graph: P2PGraph, node: NodeId, nb: NodeId, dst: NodeId) -> float:
    """Small simulated destination progress signal.

    In production this is replaced by an opaque route/session hint or rendezvous
    distance bucket, not by an IP or account identity.
    """
    n = max(1, len(graph.adj))
    before = min(abs(dst - node), n - abs(dst - node))
    after = min(abs(dst - nb), n - abs(dst - nb))
    return 2.0 if after < before else -1.2
