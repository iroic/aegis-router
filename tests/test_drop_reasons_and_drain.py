from __future__ import annotations

import unittest

from aegis_router.event_sim import EventDrivenSimulator
from aegis_router.graph import generate_random_graph
from aegis_router.solvers import ShortestPathSolver


class DropReasonsAndDrainTests(unittest.TestCase):
    def test_stats_separate_drop_reasons_and_in_flight(self):
        graph = generate_random_graph(nodes=30, degree=4, sybil_ratio=0.2, seed=101)
        stats = EventDrivenSimulator(graph, ShortestPathSolver(), seed=102, ttl=1).run(
            duration=3.0,
            traffic_rate=10.0,
            drain_time=0.0,
        )

        self.assertIsInstance(stats.drop_reasons, dict)
        self.assertGreater(sum(stats.drop_reasons.values()) + stats.in_flight, 0)
        self.assertEqual(stats.delivered + stats.dropped + stats.in_flight, stats.generated)
        self.assertIn("ttl_expired", stats.drop_reasons)

    def test_drain_window_reduces_in_flight_packets(self):
        graph = generate_random_graph(nodes=60, degree=5, sybil_ratio=0.2, seed=111)
        no_drain = EventDrivenSimulator(graph, ShortestPathSolver(), seed=112, ttl=18).run(
            duration=0.8,
            traffic_rate=20.0,
            drain_time=0.0,
        )
        with_drain = EventDrivenSimulator(graph, ShortestPathSolver(), seed=112, ttl=18).run(
            duration=0.8,
            traffic_rate=20.0,
            drain_time=8.0,
        )

        self.assertGreater(no_drain.in_flight, 0)
        self.assertLess(with_drain.in_flight, no_drain.in_flight)


if __name__ == "__main__":
    unittest.main()
