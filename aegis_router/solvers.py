from __future__ import annotations

from dataclasses import dataclass, field, asdict
from collections import defaultdict, deque
import json
from pathlib import Path
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

    def observe_result(
        self,
        *,
        neighbor: NodeId,
        delivered: bool,
        dropped: bool,
        touched_sybil: bool = False,
        reason: str | None = None,
        from_node: NodeId | None = None,
    ) -> None:
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

    risk_budget: float = 0.30
    min_budget: float = 0.15
    max_budget: float = 0.55
    adapt_step: float = 0.06
    window_size: int = 10
    drop_threshold: float = 0.35
    sybil_threshold: float = 0.5
    _recent_drops: deque[bool] = field(default_factory=deque)
    _recent_sybil: deque[bool] = field(default_factory=deque)

    def __post_init__(self) -> None:
        # Bounded windows: append auto-evicts the oldest in O(1), no list.pop(0).
        self._recent_drops = deque(self._recent_drops, maxlen=self.window_size)
        self._recent_sybil = deque(self._recent_sybil, maxlen=self.window_size)

    def observe_result(
        self,
        *,
        neighbor: NodeId,
        delivered: bool,
        dropped: bool,
        touched_sybil: bool = False,
        reason: str | None = None,
        from_node: NodeId | None = None,
    ) -> None:
        super().observe_result(neighbor=neighbor, delivered=delivered, dropped=dropped, touched_sybil=touched_sybil, reason=reason, from_node=from_node)
        self._recent_drops.append(dropped)
        self._recent_sybil.append(touched_sybil)
        if len(self._recent_drops) < self.window_size:
            return
        drop_rate = sum(self._recent_drops) / self.window_size
        sybil_rate = sum(self._recent_sybil) / self.window_size
        if drop_rate > self.drop_threshold:
            self.risk_budget = min(self.max_budget, self.risk_budget + self.adapt_step)
        elif sybil_rate > self.sybil_threshold:
            self.risk_budget = max(self.min_budget, self.risk_budget - self.adapt_step)


@dataclass
class PeerScore:
    delivered: int = 0
    drops: int = 0
    sybil_touches: int = 0
    link_losses: int = 0
    loops: int = 0
    ttl_expired: int = 0

    @property
    def badness(self) -> float:
        total = max(1, self.delivered + self.drops)
        return (
            (self.drops / total)
            + 0.7 * (self.sybil_touches / total)
            + 0.35 * (self.link_losses / total)
            + 0.5 * (self.loops / total)
            + 0.25 * (self.ttl_expired / total)
        )


@dataclass
class PersistentLearningSolver(AdaptiveRiskSolver):
    """Adaptive router with durable peer/path memory.

    It stores per-neighbor outcomes in JSON so repeated runs keep learning which
    next hops produce deliveries, drops, and Sybil exposure.
    """

    state_path: str | Path = "aegis_state.json"
    learned_penalty: float = 1.0
    peer_scores: defaultdict[NodeId, PeerScore] = field(default_factory=lambda: defaultdict(PeerScore))

    def __post_init__(self) -> None:
        super().__post_init__()
        self.state_path = Path(self.state_path)
        self.load()

    def load(self) -> None:
        if not self.state_path.exists():
            return
        data = json.loads(self.state_path.read_text())
        self.risk_budget = float(data.get("risk_budget", self.risk_budget))
        for key, value in data.get("peers", {}).items():
            node = int(key)
            self.peer_scores[node] = PeerScore(**value)
            self.peer_risk[node] = self.peer_scores[node].badness

    def save(self) -> None:
        self.state_path.parent.mkdir(parents=True, exist_ok=True)
        data = {
            "version": 1,
            "risk_budget": self.risk_budget,
            "peers": {str(k): asdict(v) for k, v in self.peer_scores.items()},
        }
        self.state_path.write_text(json.dumps(data, indent=2, sort_keys=True))

    def observe_result(
        self,
        *,
        neighbor: NodeId,
        delivered: bool,
        dropped: bool,
        touched_sybil: bool = False,
        reason: str | None = None,
        from_node: NodeId | None = None,
    ) -> None:
        super().observe_result(neighbor=neighbor, delivered=delivered, dropped=dropped, touched_sybil=touched_sybil, reason=reason, from_node=from_node)
        score = self.peer_scores[neighbor]
        if delivered:
            score.delivered += 1
        if dropped:
            score.drops += 1
        if touched_sybil:
            score.sybil_touches += 1
        if reason == "link_loss":
            score.link_losses += 1
        elif reason == "loop":
            score.loops += 1
        elif reason == "ttl_expired":
            score.ttl_expired += 1
        self.peer_risk[neighbor] = max(self.peer_risk[neighbor], score.badness)

    def _score(self, graph: P2PGraph, packet: Packet, nb: NodeId) -> float:
        return super()._score(graph, packet, nb) - (self.learned_penalty * self.peer_scores[nb].badness)


EdgeKey = tuple[NodeId, NodeId]


@dataclass
class EdgeLearningSolver(PersistentLearningSolver):
    """Persistent learner with directional edge memory.

    Neighbor-level reputation is coarse. This tracks `(from_node, to_node)` so a
    peer can be bad from one route segment and still usable from another.
    """

    edge_penalty: float = 0.7
    edge_scores: defaultdict[EdgeKey, PeerScore] = field(default_factory=lambda: defaultdict(PeerScore))

    def load(self) -> None:
        if not Path(self.state_path).exists():
            return
        data = json.loads(Path(self.state_path).read_text())
        self.risk_budget = float(data.get("risk_budget", self.risk_budget))
        for key, value in data.get("peers", {}).items():
            node = int(key)
            self.peer_scores[node] = PeerScore(**value)
            self.peer_risk[node] = self.peer_scores[node].badness
        for key, value in data.get("edges", {}).items():
            left, right = key.split("->", 1)
            self.edge_scores[(int(left), int(right))] = PeerScore(**value)

    def save(self) -> None:
        self.state_path.parent.mkdir(parents=True, exist_ok=True)
        data = {
            "version": 2,
            "risk_budget": self.risk_budget,
            "peers": {str(k): asdict(v) for k, v in self.peer_scores.items()},
            "edges": {f"{a}->{b}": asdict(v) for (a, b), v in self.edge_scores.items()},
        }
        self.state_path.write_text(json.dumps(data, indent=2, sort_keys=True))

    def observe_result(
        self,
        *,
        neighbor: NodeId,
        delivered: bool,
        dropped: bool,
        touched_sybil: bool = False,
        reason: str | None = None,
        from_node: NodeId | None = None,
    ) -> None:
        super().observe_result(
            neighbor=neighbor,
            delivered=delivered,
            dropped=dropped,
            touched_sybil=touched_sybil,
            reason=reason,
            from_node=from_node,
        )
        if from_node is None:
            return
        score = self.edge_scores[(from_node, neighbor)]
        if delivered:
            score.delivered += 1
        if dropped:
            score.drops += 1
        if touched_sybil:
            score.sybil_touches += 1
        if reason == "link_loss":
            score.link_losses += 1
        elif reason == "loop":
            score.loops += 1
        elif reason == "ttl_expired":
            score.ttl_expired += 1

    def _score(self, graph: P2PGraph, packet: Packet, nb: NodeId) -> float:
        assert packet.node is not None
        edge_badness = self.edge_scores[(packet.node, nb)].badness
        return super()._score(graph, packet, nb) - (self.edge_penalty * edge_badness)


@dataclass
class QLocalSolver:
    agent: QRoutingAgent
    train: bool = False

    def next_hop(self, graph: P2PGraph, packet: Packet) -> NodeId | None:
        assert packet.node is not None
        return self.agent.choose(graph, packet.node, packet.dst, train=self.train, visited=packet.visited)
