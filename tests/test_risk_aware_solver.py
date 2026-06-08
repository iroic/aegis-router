from __future__ import annotations

import unittest

from aegis_router.graph import LinkMetrics, P2PGraph, generate_random_graph
from aegis_router.event_sim import EventDrivenSimulator
from aegis_router.solvers import RiskAwareHybridSolver, ShortestPathSolver


class RiskAwareSolverTests(unittest.TestCase):
    def test_respects_packet_risk_budget_when_alternative_exists(self):
        g = P2PGraph()
        for n in [0, 1, 2, 9, 10]:
            g.add_node(n)
        risky_direct = LinkMetrics(latency=0.05, bandwidth=1.0, loss=0.45, stability=0.4)
        safe_detour = LinkMetrics(latency=0.25, bandwidth=0.7, loss=0.02, stability=0.9)
        g.add_edge(0, 9, risky_direct)
        g.add_edge(0, 1, safe_detour)
        g.add_edge(1, 10, safe_detour)
        g.add_edge(9, 10, risky_direct)

        solver = RiskAwareHybridSolver(risk_budget=0.15)
        from aegis_router.packet import Packet
        pkt = Packet(packet_id=1, src=0, dst=10, created_at=0.0, ttl=8, node=0)

        self.assertEqual(solver.next_hop(g, pkt), 1)

    def test_peer_reputation_penalizes_neighbor_after_drop(self):
        g = P2PGraph()
        for n in [0, 1, 2, 10]:
            g.add_node(n)
        same = LinkMetrics(latency=0.2, bandwidth=0.8, loss=0.02, stability=0.9)
        g.add_edge(0, 1, same)
        g.add_edge(0, 2, same)
        solver = RiskAwareHybridSolver(reputation_penalty=10.0)
        from aegis_router.packet import Packet
        pkt = Packet(packet_id=1, src=0, dst=10, created_at=0.0, ttl=8, node=0)

        before = solver.next_hop(g, pkt)
        solver.observe_result(neighbor=before, delivered=False, dropped=True)
        after = solver.next_hop(g, pkt)

        self.assertNotEqual(after, before)

    def test_risk_aware_event_sim_reduces_risk_vs_shortest_path(self):
        graph = generate_random_graph(nodes=80, degree=5, sybil_ratio=0.2, seed=41)
        shortest = EventDrivenSimulator(graph, ShortestPathSolver(), seed=42, ttl=18)
        risk_aware = EventDrivenSimulator(graph, RiskAwareHybridSolver(), seed=42, ttl=18)

        shortest_stats = shortest.run(duration=8.0, traffic_rate=12.0)
        risk_stats = risk_aware.run(duration=8.0, traffic_rate=12.0)

        self.assertLessEqual(risk_stats.avg_loss_risk, shortest_stats.avg_loss_risk)
        self.assertLess(risk_stats.sybil_touch_ratio, shortest_stats.sybil_touch_ratio)
        self.assertGreaterEqual(risk_stats.delivery_ratio, shortest_stats.delivery_ratio * 0.8)


if __name__ == "__main__":
    unittest.main()
