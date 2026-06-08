from __future__ import annotations

from dataclasses import dataclass, field
from collections import defaultdict
from typing import Protocol

from .agent import HybridRoutingScorer, QRoutingAgent
from .graph import NodeId, P2PGraph
from .packet import Packet


class RoutingSolver(Protocol):
    def next_hop(self, graph: P2PGraph, packet: Packet) -> NodeId | None:
        ...


@dataclass
class ShortestPathSolver:
    def next_hop(self, graph: P2PGraph, packet: Packet) -> NodeId | None:
        assert packet.node is not None
        return graph.shortest_path_next_hop(packet.node, packet.dst)


@dataclass
class HybridSolver:
    scorer: HybridRoutingScorer

    def next_hop(self, graph: P2PGraph, packet: Packet) -> NodeId | None:
        assert packet.node is not None
        return self.scorer.choose(
            graph,
            node=packet.node,
            dst=packet.dst,
            visited=packet.visited,
            ttl_remaining=packet.ttl,
        )


@dataclass
class RiskAwareHybridSolver:
    """Hybrid router with risk budget and online peer reputation.

    Inspired by risk-aware MARL: avoid actions whose one-step loss would exceed
    a packet risk budget, then score remaining neighbors with a reputation
    penalty learned from observed drops.
    """

    scorer: HybridRoutingScorer = field(default_factory=lambda: HybridRoutingScorer(loss_weight=16.0, loop_penalty=20.0))
    risk_budget: float = 0.35
    reputation_penalty: float = 4.0
    reputation_decay: float = 0.92
    peer_risk: defaultdict[NodeId, float] = field(default_factory=lambda: defaultdict(float))

    def next_hop(self, graph: P2PGraph, packet: Packet) -> NodeId | None:
        assert packet.node is not None
        neighbors = graph.neighbors(packet.node)
        if not neighbors:
            return None
        viable = []
        for nb in neighbors:
            m = graph.metrics(packet.node, nb)
            projected = 1.0 - ((1.0 - packet.loss_risk) * (1.0 - m.loss))
            if projected <= self.risk_budget or nb == packet.dst:
                viable.append(nb)
        candidates = viable or neighbors
        return max(candidates, key=lambda nb: self._score(graph, packet, nb))

    def observe_result(self, *, neighbor: NodeId, delivered: bool, dropped: bool, touched_sybil: bool = False) -> None:
        old = self.peer_risk[neighbor] * self.reputation_decay
        signal = 1.0 if dropped else (-0.15 if delivered else 0.0)
        self.peer_risk[neighbor] = max(0.0, min(1.0, old + signal))

    def _score(self, graph: P2PGraph, packet: Packet, nb: NodeId) -> float:
        assert packet.node is not None
        return self.scorer.score(
            graph,
            node=packet.node,
            neighbor=nb,
            dst=packet.dst,
            visited=packet.visited,
            ttl_remaining=packet.ttl,
        ) - (self.reputation_penalty * self.peer_risk[nb])


@dataclass
class AdaptiveRiskSolver(RiskAwareHybridSolver):
    """Risk-aware solver that adapts its budget from recent outcomes.

    Drops mean we are too conservative / failing to find viable paths, so the
    budget relaxes. Sybil touches mean we are accepting suspicious routes, so
    the budget tightens. This keeps risk low without killing delivery.
    """

    risk_budget: float = 0.35
    min_budget: float = 0.15
    max_budget: float = 0.55
    adapt_step: float = 0.06
    window_size: int = 10
    drop_threshold: float = 0.35
    sybil_threshold: float = 0.5
    _recent_drops: list[bool] = field(default_factory=list)
    _recent_sybil: list[bool] = field(default_factory=list)

    def observe_result(self, *, neighbor: NodeId, delivered: bool, dropped: bool, touched_sybil: bool = False) -> None:
        super().observe_result(neighbor=neighbor, delivered=delivered, dropped=dropped, touched_sybil=touched_sybil)
        self._recent_drops.append(dropped)
        self._recent_sybil.append(touched_sybil)
        if len(self._recent_drops) > self.window_size:
            self._recent_drops.pop(0)
            self._recent_sybil.pop(0)
        if len(self._recent_drops) < self.window_size:
            return
        drop_rate = sum(self._recent_drops) / self.window_size
        sybil_rate = sum(self._recent_sybil) / self.window_size
        if drop_rate > self.drop_threshold:
            self.risk_budget = min(self.max_budget, self.risk_budget + self.adapt_step)
        elif sybil_rate > self.sybil_threshold:
            self.risk_budget = max(self.min_budget, self.risk_budget - self.adapt_step)


@dataclass
class QLocalSolver:
    agent: QRoutingAgent
    train: bool = False

    def next_hop(self, graph: P2PGraph, packet: Packet) -> NodeId | None:
        assert packet.node is not None
        return self.agent.choose(graph, packet.node, packet.dst, train=self.train, visited=packet.visited)
