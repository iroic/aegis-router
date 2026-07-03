from __future__ import annotations

import tempfile
import unittest

from aegis_router.graph import LinkMetrics, P2PGraph
from aegis_router.packet import Packet
from aegis_router.solvers import EdgeLearningSolver


class EdgeLearningTests(unittest.TestCase):
    def test_edge_scores_are_separate_for_same_neighbor_from_different_nodes(self):
        with tempfile.TemporaryDirectory() as td:
            solver = EdgeLearningSolver(state_path=f"{td}/state.json")
            solver.observe_result(from_node=0, neighbor=7, delivered=False, dropped=True, reason="link_loss")
            solver.observe_result(from_node=3, neighbor=7, delivered=True, dropped=False)

            solver.save()
            loaded = EdgeLearningSolver(state_path=f"{td}/state.json")

            self.assertGreater(loaded.edge_scores[(0, 7)].badness, loaded.edge_scores[(3, 7)].badness)
            # Reload counts as a new run, so counters are aged by state_decay.
            self.assertAlmostEqual(loaded.edge_scores[(0, 7)].link_losses, loaded.state_decay)
            self.assertAlmostEqual(loaded.edge_scores[(3, 7)].delivered, loaded.state_decay)

    def test_solver_avoids_bad_edge_without_banning_neighbor_globally(self):
        graph = P2PGraph()
        for node in [0, 1, 2, 7, 9]:
            graph.add_node(node)
        graph.add_edge(0, 7, LinkMetrics(latency=0.20, bandwidth=0.8, loss=0.10, stability=0.7))
        graph.add_edge(0, 2, LinkMetrics(latency=0.21, bandwidth=0.8, loss=0.11, stability=0.7))
        graph.add_edge(2, 9, LinkMetrics(latency=0.20, bandwidth=0.8, loss=0.11, stability=0.7))
        graph.add_edge(7, 9, LinkMetrics(latency=0.20, bandwidth=0.8, loss=0.10, stability=0.7))
        graph.add_edge(1, 7, LinkMetrics(latency=0.20, bandwidth=0.8, loss=0.10, stability=0.7))
        graph.add_edge(1, 2, LinkMetrics(latency=0.21, bandwidth=0.8, loss=0.11, stability=0.7))

        with tempfile.TemporaryDirectory() as td:
            solver = EdgeLearningSolver(state_path=f"{td}/state.json", edge_penalty=8.0)
            for _ in range(5):
                solver.observe_result(from_node=0, neighbor=7, delivered=False, dropped=True, reason="link_loss")
            for _ in range(5):
                solver.observe_result(from_node=1, neighbor=7, delivered=True, dropped=False)

            pkt_from_0 = Packet(packet_id=1, src=0, dst=9, created_at=0.0, ttl=10)
            pkt_from_0.node = 0
            pkt_from_1 = Packet(packet_id=2, src=1, dst=9, created_at=0.0, ttl=10)
            pkt_from_1.node = 1

            self.assertEqual(solver.next_hop(graph, pkt_from_0), 2)
            self.assertEqual(solver.next_hop(graph, pkt_from_1), 7)


if __name__ == "__main__":
    unittest.main()
