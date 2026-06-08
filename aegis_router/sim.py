from __future__ import annotations

from dataclasses import dataclass
import random
from statistics import mean

from .agent import QRoutingAgent, reward_for_link
from .graph import NodeId, P2PGraph, generate_random_graph


@dataclass
class RouteResult:
    delivered: bool
    hops: int
    latency: float
    loss_risk: float
    touched_sybil: bool


@dataclass
class EvalStats:
    delivered_ratio: float
    avg_hops: float
    avg_latency: float
    avg_loss_risk: float
    sybil_touch_ratio: float


def route_with_agent(graph: P2PGraph, agent: QRoutingAgent, src: NodeId, dst: NodeId, *, train: bool, max_hops: int = 80) -> RouteResult:
    node = src
    total_latency = 0.0
    total_loss = 0.0
    touched_sybil = node in graph.sybil_nodes
    visited: set[NodeId] = set()
    for hop in range(max_hops):
        if node == dst:
            return RouteResult(True, hop, total_latency, total_loss, touched_sybil)
        visited.add(node)
        nxt = agent.choose(graph, node, dst, train=train, visited=visited)
        if nxt is None:
            return RouteResult(False, hop, total_latency, total_loss + 1.0, touched_sybil)
        m = graph.metrics(node, nxt)
        looped = nxt in visited
        delivered = nxt == dst
        reward = reward_for_link(m, delivered=delivered, looped=looped)
        if train:
            agent.update(graph, node, dst, nxt, reward, nxt)
        total_latency += m.latency
        # Approximate cumulative failure probability.
        total_loss = 1.0 - ((1.0 - total_loss) * (1.0 - m.loss))
        touched_sybil = touched_sybil or nxt in graph.sybil_nodes
        node = nxt
    return RouteResult(False, max_hops, total_latency, min(1.0, total_loss + 0.2), touched_sybil)


def route_shortest_path(graph: P2PGraph, src: NodeId, dst: NodeId, *, max_hops: int = 32) -> RouteResult:
    node = src
    total_latency = 0.0
    total_loss = 0.0
    touched_sybil = node in graph.sybil_nodes
    seen: set[NodeId] = set()
    for hop in range(max_hops):
        if node == dst:
            return RouteResult(True, hop, total_latency, total_loss, touched_sybil)
        if node in seen:
            return RouteResult(False, hop, total_latency, min(1.0, total_loss + 0.2), touched_sybil)
        seen.add(node)
        nxt = graph.shortest_path_next_hop(node, dst)
        if nxt is None:
            return RouteResult(False, hop, total_latency, 1.0, touched_sybil)
        m = graph.metrics(node, nxt)
        total_latency += m.latency
        total_loss = 1.0 - ((1.0 - total_loss) * (1.0 - m.loss))
        touched_sybil = touched_sybil or nxt in graph.sybil_nodes
        node = nxt
    return RouteResult(False, max_hops, total_latency, min(1.0, total_loss + 0.2), touched_sybil)


def train_agent(graph: P2PGraph, *, episodes: int, seed: int | None = None) -> QRoutingAgent:
    rng = random.Random(seed)
    agent = QRoutingAgent(seed=seed)
    nodes = graph.nodes()
    for _ in range(episodes):
        src, dst = rng.sample(nodes, 2)
        route_with_agent(graph, agent, src, dst, train=True)
        # Slow epsilon decay.
        agent.epsilon = max(0.03, agent.epsilon * 0.997)
    return agent


def evaluate(graph: P2PGraph, router, *, packets: int, seed: int | None = None) -> EvalStats:
    rng = random.Random(seed)
    nodes = graph.nodes()
    results: list[RouteResult] = []
    for _ in range(packets):
        src, dst = rng.sample(nodes, 2)
        results.append(router(src, dst))
    delivered = [r for r in results if r.delivered]
    denom = max(1, len(results))
    return EvalStats(
        delivered_ratio=len(delivered) / denom,
        avg_hops=mean([r.hops for r in delivered]) if delivered else float("inf"),
        avg_latency=mean([r.latency for r in delivered]) if delivered else float("inf"),
        avg_loss_risk=mean([r.loss_risk for r in results]),
        sybil_touch_ratio=sum(1 for r in results if r.touched_sybil) / denom,
    )


def run_experiment(*, nodes: int = 80, episodes: int = 300, packets: int = 250, sybil_ratio: float = 0.15, seed: int = 7) -> tuple[EvalStats, EvalStats]:
    graph = generate_random_graph(nodes=nodes, degree=5, sybil_ratio=sybil_ratio, seed=seed)
    agent = train_agent(graph, episodes=episodes, seed=seed + 1)
    shortest = evaluate(graph, lambda s, d: route_shortest_path(graph, s, d), packets=packets, seed=seed + 2)
    learned = evaluate(graph, lambda s, d: route_with_agent(graph, agent, s, d, train=False), packets=packets, seed=seed + 2)
    return shortest, learned
