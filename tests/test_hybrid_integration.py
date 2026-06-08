from __future__ import annotations

import unittest

from aegis_router.agent import HybridRoutingScorer
from aegis_router.graph import generate_random_graph
from aegis_router.sim import evaluate, route_hybrid_scorer, route_shortest_path


class HybridRoutingIntegrationTests(unittest.TestCase):
    def test_hybrid_reduces_sybil_exposure_without_destroying_delivery(self):
        g = generate_random_graph(nodes=80, degree=5, sybil_ratio=0.2, seed=11)
        scorer = HybridRoutingScorer()
        packets = 300
        shortest = evaluate(g, lambda s, d: route_shortest_path(g, s, d), packets=packets, seed=12)
        hybrid = evaluate(g, lambda s, d: route_hybrid_scorer(g, scorer, s, d), packets=packets, seed=12)

        self.assertGreaterEqual(hybrid.delivered_ratio, 0.95)
        self.assertLessEqual(hybrid.avg_hops, shortest.avg_hops * 2.5)
        self.assertLess(hybrid.sybil_touch_ratio, shortest.sybil_touch_ratio)


if __name__ == "__main__":
    unittest.main()
