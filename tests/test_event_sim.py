from __future__ import annotations

import unittest

from aegis_router.agent import HybridRoutingScorer
from aegis_router.event_sim import EventDrivenSimulator
from aegis_router.graph import generate_random_graph
from aegis_router.solvers import HybridSolver, ShortestPathSolver


class EventDrivenSimulatorTests(unittest.TestCase):
    def test_generates_packets_and_records_queue_delay_and_drops(self):
        graph = generate_random_graph(nodes=30, degree=4, sybil_ratio=0.2, seed=21)
        sim = EventDrivenSimulator(graph, ShortestPathSolver(), seed=22, ttl=10, queue_service_time=0.05)

        stats = sim.run(duration=3.0, traffic_rate=8.0)

        self.assertGreater(stats.generated, 0)
        self.assertEqual(stats.generated, stats.delivered + stats.dropped + stats.in_flight)
        self.assertGreaterEqual(stats.avg_queue_delay, 0.0)
        self.assertGreaterEqual(stats.drop_ratio, 0.0)
        self.assertLessEqual(stats.drop_ratio, 1.0)

    def test_hybrid_solver_reduces_sybil_exposure_vs_shortest_path(self):
        graph = generate_random_graph(nodes=80, degree=5, sybil_ratio=0.2, seed=31)
        shortest = EventDrivenSimulator(graph, ShortestPathSolver(), seed=32, ttl=18)
        hybrid = EventDrivenSimulator(
            graph,
            HybridSolver(HybridRoutingScorer(loss_weight=16.0, loop_penalty=20.0)),
            seed=32,
            ttl=18,
        )

        shortest_stats = shortest.run(duration=8.0, traffic_rate=12.0)
        hybrid_stats = hybrid.run(duration=8.0, traffic_rate=12.0)

        self.assertGreaterEqual(hybrid_stats.delivery_ratio, shortest_stats.delivery_ratio * 0.9)
        self.assertLess(hybrid_stats.sybil_touch_ratio, shortest_stats.sybil_touch_ratio)
        self.assertLessEqual(hybrid_stats.avg_hops, shortest_stats.avg_hops * 2.8)


if __name__ == "__main__":
    unittest.main()
