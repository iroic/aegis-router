from __future__ import annotations

import unittest

from aegis_router.agent import HybridRoutingScorer
from aegis_router.graph import LinkMetrics, P2PGraph


class HybridScorerTests(unittest.TestCase):
    def test_prefers_progress_when_links_are_similar(self):
        g = P2PGraph()
        for n in [0, 1, 9, 10]:
            g.add_node(n)
        same = LinkMetrics(latency=0.2, bandwidth=0.8, loss=0.02, stability=0.9)
        g.add_edge(0, 1, same)
        g.add_edge(0, 9, same)

        scorer = HybridRoutingScorer()
        chosen = scorer.choose(g, node=0, dst=10, visited=set(), ttl_remaining=16)

        self.assertEqual(chosen, 9)

    def test_penalizes_visited_neighbor_to_prevent_loops(self):
        g = P2PGraph()
        for n in [0, 1, 9, 10]:
            g.add_node(n)
        excellent = LinkMetrics(latency=0.01, bandwidth=1.0, loss=0.0, stability=1.0)
        decent = LinkMetrics(latency=0.3, bandwidth=0.7, loss=0.03, stability=0.8)
        g.add_edge(0, 1, excellent)
        g.add_edge(0, 9, decent)

        scorer = HybridRoutingScorer(loop_penalty=50.0)
        chosen = scorer.choose(g, node=0, dst=10, visited={1}, ttl_remaining=16)

        self.assertEqual(chosen, 9)

    def test_penalizes_sybil_like_bad_link_metrics(self):
        g = P2PGraph()
        for n in [0, 1, 9, 10]:
            g.add_node(n)
        bad_progress = LinkMetrics(latency=0.95, bandwidth=0.1, loss=0.4, stability=0.2)
        good_less_direct = LinkMetrics(latency=0.2, bandwidth=0.8, loss=0.02, stability=0.9)
        g.add_edge(0, 9, bad_progress)
        g.add_edge(0, 1, good_less_direct)

        scorer = HybridRoutingScorer()
        chosen = scorer.choose(g, node=0, dst=10, visited=set(), ttl_remaining=16)

        self.assertEqual(chosen, 1)


if __name__ == "__main__":
    unittest.main()
