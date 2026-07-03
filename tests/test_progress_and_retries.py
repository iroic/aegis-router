from __future__ import annotations

import unittest

from aegis_router.agent import _progress_delta
from aegis_router.event_sim import EventDrivenSimulator
from aegis_router.graph import LinkMetrics, P2PGraph, generate_random_graph
from aegis_router.solvers import ShortestPathSolver

LINK = LinkMetrics(latency=0.1, bandwidth=0.8, loss=0.05, stability=0.9)


class LandmarkProgressTests(unittest.TestCase):
    def _line_graph(self) -> P2PGraph:
        g = P2PGraph()
        for a, b in [(0, 1), (1, 2), (2, 3), (3, 4)]:
            g.add_edge(a, b, LINK)
        return g

    def test_landmark_distance_is_exact_on_line_when_all_nodes_are_landmarks(self):
        g = self._line_graph()
        g.compute_landmarks(count=5, seed=1)
        self.assertEqual(g.landmark_distance(0, 4), 4.0)
        self.assertEqual(g.landmark_distance(1, 1), 0.0)
        self.assertEqual(g.landmark_distance(0, 3), g.landmark_distance(3, 0))

    def test_progress_prefers_neighbor_closer_to_destination(self):
        g = self._line_graph()
        g.compute_landmarks(count=5, seed=1)
        toward = _progress_delta(g, 1, 2, 4)
        away = _progress_delta(g, 1, 0, 4)
        self.assertGreater(toward, 0.0)
        self.assertLess(away, 0.0)

    def test_without_landmarks_falls_back_to_ring_distance(self):
        g = self._line_graph()
        self.assertIsNone(g.landmark_distance(0, 4))
        # Legacy ring formula: before=min(3, 2)=2, after(node 2)=min(2, 3)=2.
        self.assertEqual(_progress_delta(g, 1, 2, 4), 0.0)

    def test_generated_graph_computes_landmarks_by_default(self):
        g = generate_random_graph(nodes=30, degree=4, sybil_ratio=0.1, seed=9)
        self.assertIsNotNone(g.landmark_distance(0, 15))
        g_off = generate_random_graph(nodes=30, degree=4, sybil_ratio=0.1, landmarks=0, seed=9)
        self.assertIsNone(g_off.landmark_distance(0, 15))


class LinkRetriesTests(unittest.TestCase):
    def _run(self, retries: int):
        graph = generate_random_graph(nodes=40, degree=4, sybil_ratio=0.2, seed=51)
        sim = EventDrivenSimulator(graph, ShortestPathSolver(), seed=52, ttl=18, link_retries=retries)
        return sim.run(duration=5.0, traffic_rate=15.0, drain_time=5.0)

    def test_retries_break_the_loss_ceiling(self):
        base = self._run(0)
        arq = self._run(2)
        self.assertEqual(base.retransmissions, 0)
        self.assertGreater(arq.retransmissions, 0)
        self.assertGreater(arq.delivery_ratio, base.delivery_ratio)

    def test_retries_cost_latency(self):
        base = self._run(0)
        arq = self._run(2)
        self.assertGreater(arq.avg_latency, base.avg_latency * 0.9)


if __name__ == "__main__":
    unittest.main()
