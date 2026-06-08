from __future__ import annotations

from dataclasses import dataclass
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
class QLocalSolver:
    agent: QRoutingAgent
    train: bool = False

    def next_hop(self, graph: P2PGraph, packet: Packet) -> NodeId | None:
        assert packet.node is not None
        return self.agent.choose(graph, packet.node, packet.dst, train=self.train, visited=packet.visited)
