from __future__ import annotations

import tempfile
import unittest

from aegis_router.graph import LinkMetrics, P2PGraph
from aegis_router.packet import Packet
from aegis_router.solvers import PersistentLearningSolver


class ReasonAwareLearningTests(unittest.TestCase):
    def test_link_loss_and_loop_reasons_have_stronger_penalties(self):
        with tempfile.TemporaryDirectory() as td:
            solver = PersistentLearningSolver(state_path=f"{td}/state.json")

            solver.observe_result(neighbor=2, delivered=False, dropped=True, touched_sybil=False, reason="link_loss")
            solver.observe_result(neighbor=3, delivered=False, dropped=True, touched_sybil=False, reason="loop")
            solver.observe_result(neighbor=4, delivered=False, dropped=True, touched_sybil=False, reason="ttl_expired")

            self.assertGreater(solver.peer_scores[2].link_losses, 0)
            self.assertGreater(solver.peer_scores[3].loops, 0)
            self.assertGreater(solver.peer_scores[2].badness, solver.peer_scores[4].badness)
            self.assertGreater(solver.peer_scores[3].badness, solver.peer_scores[4].badness)

    def test_solver_prefers_reliable_neighbor_when_loss_metrics_are_close(self):
        graph = P2PGraph()
        graph.add_node(0)
        graph.add_node(1)
        graph.add_node(2)
        graph.add_node(9)
        graph.add_edge(0, 1, LinkMetrics(latency=0.20, bandwidth=0.8, loss=0.12, stability=0.7))
        graph.add_edge(0, 2, LinkMetrics(latency=0.22, bandwidth=0.8, loss=0.11, stability=0.7))
        graph.add_edge(1, 9, LinkMetrics(latency=0.20, bandwidth=0.8, loss=0.12, stability=0.7))
        graph.add_edge(2, 9, LinkMetrics(latency=0.20, bandwidth=0.8, loss=0.11, stability=0.7))
        pkt = Packet(packet_id=1, src=0, dst=9, created_at=0.0, ttl=10)

        with tempfile.TemporaryDirectory() as td:
            solver = PersistentLearningSolver(state_path=f"{td}/state.json", learned_penalty=6.0)
            for _ in range(5):
                solver.observe_result(neighbor=1, delivered=False, dropped=True, reason="link_loss")
            for _ in range(5):
                solver.observe_result(neighbor=2, delivered=True, dropped=False)

            self.assertEqual(solver.next_hop(graph, pkt), 2)


if __name__ == "__main__":
    unittest.main()
