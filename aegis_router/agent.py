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


class HybridRoutingScorer:
    """v0.2 deterministic scorer for runtime routing.

    It is intentionally tiny: no heavy ML dependency, no global topology, and no
    payload metadata. It combines link quality, anonymous progress hint, TTL
    pressure, and anti-loop penalty. The later DQN/GNN model can learn/replace
    these weights while keeping the same interface.
    """

    def __init__(
        self,
        *,
        latency_weight: float = 2.4,
        loss_weight: float = 24.0,
        bandwidth_weight: float = 0.35,
        stability_weight: float = 1.5,
        progress_weight: float = 4.0,
        loop_penalty: float = 8.0,
        low_ttl_penalty: float = 0.7,
    ) -> None:
        self.latency_weight = latency_weight
        self.loss_weight = loss_weight
        self.bandwidth_weight = bandwidth_weight
        self.stability_weight = stability_weight
        self.progress_weight = progress_weight
        self.loop_penalty = loop_penalty
        self.low_ttl_penalty = low_ttl_penalty

    def choose(
        self,
        graph: P2PGraph,
        *,
        node: NodeId,
        dst: NodeId,
        visited: set[NodeId],
        ttl_remaining: int,
    ) -> NodeId | None:
        neighbors = graph.neighbors(node)
        if not neighbors:
            return None
        return max(
            neighbors,
            key=lambda nb: self.score(
                graph,
                node=node,
                neighbor=nb,
                dst=dst,
                visited=visited,
                ttl_remaining=ttl_remaining,
            ),
        )

    def score(
        self,
        graph: P2PGraph,
        *,
        node: NodeId,
        neighbor: NodeId,
        dst: NodeId,
        visited: set[NodeId],
        ttl_remaining: int,
    ) -> float:
        m = graph.metrics(node, neighbor)
        score = 0.0
        score -= self.latency_weight * m.latency
        score -= self.loss_weight * m.loss
        score += self.bandwidth_weight * m.bandwidth
        score += self.stability_weight * m.stability
        score += self.progress_weight * _progress_delta(graph, node, neighbor, dst)
        if neighbor in visited:
            score -= self.loop_penalty
        if ttl_remaining <= 4:
            score -= self.low_ttl_penalty * (4 - ttl_remaining + 1)
        return score


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
    return 2.0 if _progress_delta(graph, node, nb, dst) > 0 else -1.2


def _progress_delta(graph: P2PGraph, node: NodeId, nb: NodeId, dst: NodeId) -> float:
    """Anonymous progress hint toward the destination.

    Prefers landmark hop-distance vectors (see P2PGraph.compute_landmarks),
    which track real topology. Falls back to the legacy ring-distance formula
    — a node-numbering artifact — when landmarks are absent.
    """
    est_before = graph.landmark_distance(node, dst)
    est_after = graph.landmark_distance(nb, dst)
    if est_before is not None and est_after is not None:
        if est_before <= 0:
            return 1.0
        # Absolute delta in hop units, not normalized: relative progress
        # under-weights steps taken far from the destination and measurably
        # lengthens routes (hybrid hops 4.7 vs 3.7 on the same scenario).
        return est_before - est_after
    n = max(1, len(graph.adj))
    before = min(abs(dst - node), n - abs(dst - node))
    after = min(abs(dst - nb), n - abs(dst - nb))
    if before == 0:
        return 1.0
    return (before - after) / before
