from __future__ import annotations

import tempfile
import unittest

from aegis_router.agent import HybridRoutingScorer, QRoutingAgent
from aegis_router.event_sim import EventDrivenSimulator
from aegis_router.graph import LinkMetrics, P2PGraph, generate_random_graph
from aegis_router.packet import Packet
from aegis_router.solvers import EdgeLearningSolver, RiskAwareHybridSolver, ShortestPathSolver

LINK = LinkMetrics(latency=0.1, bandwidth=0.8, loss=0.05, stability=0.9)


def diamond_graph() -> P2PGraph:
    """0 -> {1, 2} -> 3, so 1 and 2 are alternative next hops toward 3."""
    g = P2PGraph()
    g.add_edge(0, 1, LINK)
    g.add_edge(0, 2, LINK)
    g.add_edge(1, 3, LINK)
    g.add_edge(2, 3, LINK)
    return g


class ReachableNeighborsTests(unittest.TestCase):
    def test_reachable_neighbors_excludes_offline_nodes(self):
        g = diamond_graph()
        g.offline_nodes.add(1)
        self.assertEqual(set(g.reachable_neighbors(0)), {2})
        self.assertEqual(set(g.neighbors(0)), {1, 2})  # raw topology unaffected

    def test_shortest_path_avoids_offline_next_hop(self):
        g = diamond_graph()
        g.offline_nodes.add(1)
        self.assertEqual(g.shortest_path_next_hop(0, 3), 2)

    def test_shortest_path_returns_none_when_only_route_is_offline(self):
        g = P2PGraph()
        g.add_edge(0, 1, LINK)
        g.add_edge(1, 2, LINK)
        g.offline_nodes.add(1)
        self.assertIsNone(g.shortest_path_next_hop(0, 2))


class SolverLivenessTests(unittest.TestCase):
    def test_hybrid_scorer_avoids_offline_neighbor(self):
        g = diamond_graph()
        g.offline_nodes.add(1)
        scorer = HybridRoutingScorer()
        chosen = scorer.choose(g, node=0, dst=3, visited=set(), ttl_remaining=10)
        self.assertEqual(chosen, 2)

    def test_q_agent_avoids_offline_neighbor(self):
        g = diamond_graph()
        g.offline_nodes.add(1)
        agent = QRoutingAgent(seed=1)
        chosen = agent.choose(g, 0, 3, train=False)
        self.assertEqual(chosen, 2)

    def test_risk_aware_solver_avoids_offline_neighbor(self):
        g = diamond_graph()
        g.offline_nodes.add(1)
        solver = RiskAwareHybridSolver()
        pkt = Packet(packet_id=1, src=0, dst=3, created_at=0.0, ttl=8, node=0)
        self.assertEqual(solver.next_hop(g, pkt), 2)

    def test_edge_learning_trusted_path_skips_offline_intermediary(self):
        g = diamond_graph()
        g.offline_nodes.add(1)
        with tempfile.TemporaryDirectory() as td:
            solver = EdgeLearningSolver(state_path=f"{td}/state.json")
            # Prime reputation so find_trusted_path's data requirements are met.
            solver.observe_result(from_node=0, neighbor=2, delivered=True, dropped=False)
            solver.observe_result(from_node=2, neighbor=3, delivered=True, dropped=False)
            pkt = Packet(packet_id=1, src=0, dst=3, created_at=0.0, ttl=8, node=0)
            self.assertEqual(solver.next_hop(g, pkt), 2)

    def test_edge_learning_returns_none_for_offline_destination(self):
        g = diamond_graph()
        g.offline_nodes.add(3)
        with tempfile.TemporaryDirectory() as td:
            solver = EdgeLearningSolver(state_path=f"{td}/state.json")
            pkt = Packet(packet_id=1, src=0, dst=3, created_at=0.0, ttl=8, node=0)
            self.assertIsNone(solver.find_trusted_path(g, pkt))


class SimulatorSyncTests(unittest.TestCase):
    def test_graph_offline_nodes_reflects_live_churn_state(self):
        graph = generate_random_graph(nodes=40, degree=4, sybil_ratio=0.1, seed=5)
        sim = EventDrivenSimulator(graph, ShortestPathSolver(), seed=6, ttl=18, churn_rate=1.0, churn_recovery=0.0, perturb_interval=0.1)
        sim.run(duration=0.5, traffic_rate=1.0)
        # churn_rate=1.0, recovery=0.0: every node has gone down at least once
        # and the graph's own offline_nodes must reflect it (same object).
        self.assertTrue(len(graph.offline_nodes) > 0)
        self.assertIs(graph.offline_nodes, sim._down_nodes)


if __name__ == "__main__":
    unittest.main()
