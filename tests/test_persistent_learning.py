from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from aegis_router.graph import LinkMetrics, P2PGraph, generate_random_graph
from aegis_router.packet import Packet
from aegis_router.event_sim import EventDrivenSimulator
from aegis_router.solvers import PersistentLearningSolver, ShortestPathSolver


class PersistentLearningTests(unittest.TestCase):
    def test_saves_and_loads_neighbor_scores(self):
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "state.json"
            solver = PersistentLearningSolver(state_path=path)
            solver.observe_result(neighbor=7, delivered=False, dropped=True, touched_sybil=True)
            solver.save()

            loaded = PersistentLearningSolver(state_path=path)
            self.assertGreater(loaded.peer_scores[7].drops, 0)
            self.assertGreater(loaded.peer_scores[7].sybil_touches, 0)

    def test_learns_to_avoid_bad_neighbor_across_restarts(self):
        g = P2PGraph()
        for n in [0, 1, 2, 10]:
            g.add_node(n)
        g.add_edge(0, 1, LinkMetrics(latency=0.1, bandwidth=1.0, loss=0.01, stability=0.9))
        g.add_edge(0, 2, LinkMetrics(latency=0.1, bandwidth=1.0, loss=0.01, stability=0.9))

        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "state.json"
            solver = PersistentLearningSolver(state_path=path, learned_penalty=20.0)
            pkt = Packet(packet_id=1, src=0, dst=10, created_at=0.0, ttl=8, node=0)
            bad = solver.next_hop(g, pkt)
            for _ in range(3):
                solver.observe_result(neighbor=bad, delivered=False, dropped=True, touched_sybil=True)
            solver.save()

            loaded = PersistentLearningSolver(state_path=path, learned_penalty=20.0)
            pkt2 = Packet(packet_id=2, src=0, dst=10, created_at=0.0, ttl=8, node=0)
            self.assertNotEqual(loaded.next_hop(g, pkt2), bad)

    def test_repeated_learning_runs_improve_over_fresh_solver(self):
        graph = generate_random_graph(nodes=80, degree=5, sybil_ratio=0.2, seed=71)
        with tempfile.TemporaryDirectory() as td:
            state = Path(td) / "aegis_state.json"
            baseline = EventDrivenSimulator(graph, ShortestPathSolver(), seed=72, ttl=18).run(duration=8.0, traffic_rate=12.0)
            first_solver = PersistentLearningSolver(state_path=state)
            first = EventDrivenSimulator(graph, first_solver, seed=72, ttl=18).run(duration=8.0, traffic_rate=12.0)
            first_solver.save()
            second_solver = PersistentLearningSolver(state_path=state)
            second = EventDrivenSimulator(graph, second_solver, seed=73, ttl=18).run(duration=8.0, traffic_rate=12.0)
            second_solver.save()

            self.assertLess(second.sybil_touch_ratio, baseline.sybil_touch_ratio)
            self.assertLessEqual(second.avg_loss_risk, baseline.avg_loss_risk * 1.2)
            self.assertGreaterEqual(second.delivery_ratio, first.delivery_ratio * 0.65)


if __name__ == "__main__":
    unittest.main()
