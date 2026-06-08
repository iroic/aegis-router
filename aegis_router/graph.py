from __future__ import annotations

from dataclasses import dataclass
import heapq
import random
from typing import Dict, Iterable, List, Tuple


NodeId = int


@dataclass(frozen=True)
class LinkMetrics:
    latency: float      # lower is better, milliseconds-ish normalized
    bandwidth: float    # higher is better
    loss: float         # probability [0, 1]
    stability: float    # [0, 1]

    def cost(self) -> float:
        return self.latency + (8.0 * self.loss) + (1.0 - self.stability) - (0.15 * self.bandwidth)


class P2PGraph:
    def __init__(self) -> None:
        self.adj: Dict[NodeId, Dict[NodeId, LinkMetrics]] = {}
        self.sybil_nodes: set[NodeId] = set()

    def add_node(self, node: NodeId, *, sybil: bool = False) -> None:
        self.adj.setdefault(node, {})
        if sybil:
            self.sybil_nodes.add(node)

    def add_edge(self, a: NodeId, b: NodeId, metrics: LinkMetrics) -> None:
        self.add_node(a)
        self.add_node(b)
        self.adj[a][b] = metrics
        self.adj[b][a] = metrics

    def nodes(self) -> List[NodeId]:
        return list(self.adj.keys())

    def neighbors(self, node: NodeId) -> List[NodeId]:
        return list(self.adj.get(node, {}).keys())

    def metrics(self, a: NodeId, b: NodeId) -> LinkMetrics:
        return self.adj[a][b]

    def shortest_path_next_hop(self, src: NodeId, dst: NodeId) -> NodeId | None:
        """Classic shortest path by hop-count only.

        This intentionally ignores quality metrics, modelling the naive router that
        attackers can exploit by offering many apparently-short links.
        """
        if src == dst:
            return dst
        queue: list[tuple[int, NodeId, NodeId | None]] = [(0, src, None)]
        seen: set[NodeId] = set()
        while queue:
            hops, node, first = heapq.heappop(queue)
            if node in seen:
                continue
            seen.add(node)
            if node == dst:
                return first
            for nb in self.adj[node]:
                if nb in seen:
                    continue
                hop = nb if first is None else first
                heapq.heappush(queue, (hops + 1, nb, hop))
        return None

    def quality_path_next_hop(self, src: NodeId, dst: NodeId) -> NodeId | None:
        """Oracle-like path by link metrics, used only as a training/eval helper."""
        if src == dst:
            return dst
        queue: list[tuple[float, NodeId, NodeId | None]] = [(0.0, src, None)]
        seen: set[NodeId] = set()
        while queue:
            cost, node, first = heapq.heappop(queue)
            if node in seen:
                continue
            seen.add(node)
            if node == dst:
                return first
            for nb, m in self.adj[node].items():
                if nb in seen:
                    continue
                hop = nb if first is None else first
                heapq.heappush(queue, (cost + max(0.001, m.cost()), nb, hop))
        return None


def generate_random_graph(
    *,
    nodes: int,
    degree: int = 4,
    sybil_ratio: float = 0.1,
    seed: int | None = None,
) -> P2PGraph:
    rng = random.Random(seed)
    g = P2PGraph()
    sybil_count = int(nodes * sybil_ratio)
    sybils = set(rng.sample(range(nodes), sybil_count)) if sybil_count else set()
    for n in range(nodes):
        g.add_node(n, sybil=n in sybils)

    # Ring for guaranteed connectivity.
    for n in range(nodes):
        _add_random_edge(g, n, (n + 1) % nodes, rng)

    # Random extra links until approximate degree is reached.
    target_edges = nodes * degree // 2
    attempts = 0
    while sum(len(v) for v in g.adj.values()) // 2 < target_edges and attempts < target_edges * 20:
        a, b = rng.sample(range(nodes), 2)
        if b not in g.adj[a]:
            _add_random_edge(g, a, b, rng)
        attempts += 1
    return g


def _add_random_edge(g: P2PGraph, a: NodeId, b: NodeId, rng: random.Random) -> None:
    sybil_edge = a in g.sybil_nodes or b in g.sybil_nodes
    if sybil_edge:
        metrics = LinkMetrics(
            latency=rng.uniform(0.45, 1.0),
            bandwidth=rng.uniform(0.05, 0.45),
            loss=rng.uniform(0.12, 0.45),
            stability=rng.uniform(0.15, 0.65),
        )
    else:
        metrics = LinkMetrics(
            latency=rng.uniform(0.03, 0.55),
            bandwidth=rng.uniform(0.45, 1.0),
            loss=rng.uniform(0.0, 0.12),
            stability=rng.uniform(0.55, 1.0),
        )
    g.add_edge(a, b, metrics)
