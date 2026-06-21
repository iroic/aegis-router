from __future__ import annotations

import unittest

from aegis_router.event_sim import EventDrivenSimulator
from aegis_router.graph import generate_random_graph
from aegis_router.solvers import ShortestPathSolver


def _undirected_edges(g):
    return [(a, b) for a in g.adj for b in g.adj[a] if a < b]


def _mean_sybil_loss(g) -> float:
    losses = [
        g.metrics(a, b).loss
        for a, b in _undirected_edges(g)
        if a in g.sybil_nodes or b in g.sybil_nodes
    ]
    return sum(losses) / max(1, len(losses))


class StealthSybilTests(unittest.TestCase):
    def test_stealth_sybil_links_advertise_honest_metrics(self):
        obvious = generate_random_graph(nodes=60, degree=5, sybil_ratio=0.25, sybil_stealth=0.0, seed=7)
        stealth = generate_random_graph(nodes=60, degree=5, sybil_ratio=0.25, sybil_stealth=1.0, seed=7)

        # Obvious Sybil links are visibly lossy; stealth ones hide inside the
        # honest loss range so a metric-only scorer cannot flag them.
        self.assertGreater(_mean_sybil_loss(obvious), 0.12)
        self.assertLess(_mean_sybil_loss(stealth), 0.12)
        self.assertLess(_mean_sybil_loss(stealth), _mean_sybil_loss(obvious))

    def test_stealth_preserves_topology(self):
        obvious = generate_random_graph(nodes=50, degree=4, sybil_ratio=0.2, sybil_stealth=0.0, seed=3)
        stealth = generate_random_graph(nodes=50, degree=4, sybil_ratio=0.2, sybil_stealth=1.0, seed=3)
        # Same seed → same node/edge structure and same Sybil set, only metrics differ.
        self.assertEqual(set(_undirected_edges(obvious)), set(_undirected_edges(stealth)))
        self.assertEqual(obvious.sybil_nodes, stealth.sybil_nodes)


class CongestionDriftTests(unittest.TestCase):
    def test_congestion_drift_mutates_link_metrics(self):
        g = generate_random_graph(nodes=40, degree=4, sybil_ratio=0.1, seed=5)
        before = {e: g.metrics(*e) for e in _undirected_edges(g)}
        EventDrivenSimulator(
            g, ShortestPathSolver(), seed=6, congestion_rate=1.0, perturb_interval=0.2
        ).run(duration=3.0, traffic_rate=6.0)
        after = {e: g.metrics(*e) for e in _undirected_edges(g)}
        changed = sum(1 for e in before if before[e] != after[e])
        self.assertGreater(changed, 0)

    def test_defaults_leave_network_static(self):
        g = generate_random_graph(nodes=40, degree=4, sybil_ratio=0.1, seed=5)
        before = {e: g.metrics(*e) for e in _undirected_edges(g)}
        EventDrivenSimulator(g, ShortestPathSolver(), seed=6).run(duration=3.0, traffic_rate=6.0)
        after = {e: g.metrics(*e) for e in _undirected_edges(g)}
        self.assertEqual(before, after)


class ChurnTests(unittest.TestCase):
    def test_churn_produces_node_down_drops(self):
        g = generate_random_graph(nodes=40, degree=4, sybil_ratio=0.1, seed=8)
        stats = EventDrivenSimulator(
            g, ShortestPathSolver(), seed=9, churn_rate=0.3, churn_recovery=0.2, perturb_interval=0.2
        ).run(duration=4.0, traffic_rate=10.0)
        self.assertIn("node_down", stats.drop_reasons)
        # Accounting invariant must still hold under churn.
        self.assertEqual(stats.generated, stats.delivered + stats.dropped + stats.in_flight)


if __name__ == "__main__":
    unittest.main()
