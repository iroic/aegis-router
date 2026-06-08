from __future__ import annotations

import unittest

from aegis_router.graph import generate_random_graph
from aegis_router.sim import route_shortest_path, route_with_agent, train_agent


class AegisRouterTests(unittest.TestCase):
    def test_generated_graph_is_connected_enough_for_ring_route(self):
        g = generate_random_graph(nodes=20, degree=4, sybil_ratio=0.1, seed=1)
        for src in range(20):
            dst = (src + 7) % 20
            res = route_shortest_path(g, src, dst, max_hops=40)
            self.assertTrue(res.delivered)

    def test_agent_can_route_after_training(self):
        g = generate_random_graph(nodes=35, degree=5, sybil_ratio=0.15, seed=2)
        agent = train_agent(g, episodes=120, seed=3)
        successes = 0
        for src in range(10):
            dst = (src * 3 + 11) % 35
            res = route_with_agent(g, agent, src, dst, train=False, max_hops=32)
            successes += int(res.delivered)
        self.assertGreaterEqual(successes, 7)


if __name__ == "__main__":
    unittest.main()
