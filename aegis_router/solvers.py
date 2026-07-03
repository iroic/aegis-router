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
        neighbors = graph.reachable_neighbors(packet.node)
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
        if reason == "node_down":
            # Transient churn, not misbehaviour: a mild, fast-forgotten signal
            # so we avoid retrying an already-known-down node this run, but it
            # does not accumulate into lasting distrust.
            signal = 0.15
        elif dropped:
            signal = 1.0
        elif delivered:
            signal = -0.15
        else:
            signal = 0.0
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


# Beta-style smoothing prior: with few observations badness stays near 0, so a
# handful of unlucky stochastic link losses cannot blacklist a peer. Grid-tuned
# on 3 topology seeds x 30 runs: 8.0 beat 2/4/12/16 on delivery, hops and sybil.
BADNESS_CONFIDENCE_PRIOR = 8.0


# node_down (churn) is transient network state, not a property of the peer:
# the node is very likely back up by the next run. Weighting it like a real
# drop lets churn alone convict most of the network (measured at 1000 nodes,
# churn=0.04: learned solver fell to 22% delivery vs 52% for shortest-path,
# almost entirely from node_down drops accumulating as if they were malice).
NODE_DOWN_WEIGHT = 0.05


@dataclass
class PeerScore:
    delivered: float = 0.0
    drops: float = 0.0
    sybil_touches: float = 0.0
    link_losses: float = 0.0
    loops: float = 0.0
    ttl_expired: float = 0.0
    node_down: float = 0.0

    @property
    def badness(self) -> float:
        total = self.delivered + self.drops
        weighted = (
            self.drops
            + 0.7 * self.sybil_touches
            + 0.35 * self.link_losses
            + 0.5 * self.loops
            + 0.25 * self.ttl_expired
            + NODE_DOWN_WEIGHT * self.node_down
        )
        return min(1.0, weighted / (total + BADNESS_CONFIDENCE_PRIOR))

    def decay(self, factor: float) -> None:
        self.delivered *= factor
        self.drops *= factor
        self.sybil_touches *= factor
        self.link_losses *= factor
        self.loops *= factor
        self.ttl_expired *= factor
        self.node_down *= factor


@dataclass
class PersistentLearningSolver(AdaptiveRiskSolver):
    """Adaptive router with durable peer/path memory.

    It stores per-neighbor outcomes in JSON so repeated runs keep learning which
    next hops produce deliveries, drops, and Sybil exposure.
    """

    state_path: str | Path = "aegis_state.json"
    learned_penalty: float = 1.0
    # Per-run aging of persisted evidence: without it counters only accumulate
    # and, since link loss is stochastic, every peer eventually looks bad.
    state_decay: float = 0.90
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
            self.peer_scores[node].decay(self.state_decay)
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
        if reason == "node_down":
            score.node_down += 1
        elif dropped:
            score.drops += 1
        if touched_sybil:
            score.sybil_touches += 1
        if reason == "link_loss":
            score.link_losses += 1
        elif reason == "loop":
            score.loops += 1
        elif reason == "ttl_expired":
            score.ttl_expired += 1
        # Blend the fast in-run EWMA (already updated by super()) with durable
        # evidence. A max() here would be a ratchet: risk could only rise, and
        # a peer could never rehabilitate across runs.
        self.peer_risk[neighbor] = 0.5 * (self.peer_risk[neighbor] + score.badness)

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
    # Weight of the Beta-smoothed per-edge delivery probability in the score.
    # 0.0 disables the term entirely.
    success_weight: float = 0.0
    # Route through pre-computed trusted 2-3 hop paths before scored routing.
    use_trusted_path: bool = True
    edge_scores: defaultdict[EdgeKey, PeerScore] = field(default_factory=lambda: defaultdict(PeerScore))
    # Parameters for reputation-based path routing
    NODE_RISK_THRESHOLD: float = 0.5
    EDGE_BADNESS_THRESHOLD: float = 0.5
    
    def find_trusted_path(self, graph: P2PGraph, packet: Packet) -> list[NodeId] | None:
        """
        Build 2-3 hop paths using reputation scores to avoid high-risk nodes.
        Prioritizes paths that avoid nodes with high sybil_touch history.
        """
        if packet.node is None or packet.ttl < 2:
            return None

        current = packet.node
        dest = packet.dst

        # An offline destination cannot accept a connection regardless of path.
        if dest in graph.offline_nodes:
            return None

        # Directly return destination if it's a neighbor
        if graph.has_edge(current, dest):
            return [current, dest]

        # Find trusted intermediaries using reputation scores
        candidates = []

        # 2-hop paths
        for n1 in graph.neighbors(current):
            if (n1 in packet.visited or
                n1 in graph.offline_nodes or
                self.peer_risk[n1] > self.NODE_RISK_THRESHOLD or
                not graph.has_edge(n1, dest)):
                continue
                
            # Check if we have reputation data for both edges
            edge1 = (current, n1)
            edge2 = (n1, dest)
            
            if edge1 not in self.edge_scores or edge2 not in self.edge_scores:
                continue
                
            if (self.edge_scores[edge1].badness > self.EDGE_BADNESS_THRESHOLD or
                self.edge_scores[edge2].badness > self.EDGE_BADNESS_THRESHOLD or
                self.peer_scores[n1].sybil_touches > self.NODE_RISK_THRESHOLD):
                continue
            
            candidates.append([current, n1, dest])
        
        # 3-hop paths
        for n1 in graph.neighbors(current):
            if (n1 in packet.visited or
                n1 in graph.offline_nodes or
                self.peer_risk[n1] > self.NODE_RISK_THRESHOLD):
                continue

            edge1 = (current, n1)

            for n2 in graph.neighbors(n1):
                if (n2 == current or n2 in packet.visited or
                    n2 in graph.offline_nodes or
                    self.peer_risk[n2] > self.NODE_RISK_THRESHOLD or
                    not graph.has_edge(n2, dest)):
                    continue
                
                edge2 = (n1, n2)
                edge3 = (n2, dest)
                
                if any(edge not in self.edge_scores for edge in (edge1, edge2, edge3)):
                    continue
                    
                if any(self.edge_scores[edge].badness > self.EDGE_BADNESS_THRESHOLD for edge in (edge1, edge2, edge3)):
                    continue
                    
                if (self.peer_scores[n1].sybil_touches > self.NODE_RISK_THRESHOLD or 
                    self.peer_scores[n2].sybil_touches > self.NODE_RISK_THRESHOLD):
                    continue
                    
                candidates.append([current, n1, n2, dest])
        
        # Select best candidate path (if any)
        if not candidates:
            return None

        # Prioritize shorter paths. Ranking by cumulative edge badness instead
        # was measured slightly worse (candidates are already badness-filtered).
        return min(candidates, key=len)

    def next_hop(self, graph: P2PGraph, packet: Packet) -> NodeId | None:
        """
        Overridden to use multi-hop trusted paths when available.
        Prioritizes trusted paths over direct routing when possible.
        """
        assert packet.node is not None

        # Try to find a trusted multi-hop path
        if self.use_trusted_path and (trusted_path := self.find_trusted_path(graph, packet)):
            # Skip current node and return the first hop
            if len(trusted_path) >= 2 and trusted_path[0] == packet.node:
                return trusted_path[1]
        
        # Fall back to direct routing
        return super().next_hop(graph, packet)

    def load(self) -> None:
        if not Path(self.state_path).exists():
            return
        data = json.loads(Path(self.state_path).read_text())
        self.risk_budget = float(data.get("risk_budget", self.risk_budget))
        for key, value in data.get("peers", {}).items():
            node = int(key)
            self.peer_scores[node] = PeerScore(**value)
            self.peer_scores[node].decay(self.state_decay)
            self.peer_risk[node] = self.peer_scores[node].badness
        for key, value in data.get("edges", {}).items():
            left, right = key.split("->", 1)
            edge_score = PeerScore(**value)
            edge_score.decay(self.state_decay)
            self.edge_scores[(int(left), int(right))] = edge_score

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
        if reason == "node_down":
            score.node_down += 1
        elif dropped:
            score.drops += 1
        if touched_sybil:
            score.sybil_touches += 1
        if reason == "link_loss":
            score.link_losses += 1
        elif reason == "loop":
            score.loops += 1
        elif reason == "ttl_expired":
            score.ttl_expired += 1

    def _edge_success(self, key: EdgeKey) -> float:
        """Beta-smoothed delivery probability for a directed edge.

        Beta(delivered + 1, drops + 1) posterior mean: unseen edges start at a
        neutral 0.5 instead of being either trusted or blacklisted outright.
        """
        s = self.edge_scores[key]
        return (s.delivered + 1.0) / (s.delivered + s.drops + 2.0)

    def _score(self, graph: P2PGraph, packet: Packet, nb: NodeId) -> float:
        assert packet.node is not None
        key = (packet.node, nb)
        edge_badness = self.edge_scores[key].badness
        score = super()._score(graph, packet, nb) - (self.edge_penalty * edge_badness)
        if self.success_weight > 0.0:
            score += self.success_weight * (self._edge_success(key) - 0.5)
        return score


@dataclass
class QLocalSolver:
    agent: QRoutingAgent
    train: bool = False

    def next_hop(self, graph: P2PGraph, packet: Packet) -> NodeId | None:
        assert packet.node is not None
        return self.agent.choose(graph, packet.node, packet.dst, train=self.train, visited=packet.visited)
