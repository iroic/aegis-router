from __future__ import annotations

import unittest

from aegis_router.daemon import _make_solver
from aegis_router.graph import LinkMetrics, P2PGraph
from aegis_router.packet import Packet
from aegis_router.solvers import EigenTrustSolver, GlobalTrustLedger, ShortestPathSolver


def _evidence_ledger() -> GlobalTrustLedger:
    ledger = GlobalTrustLedger((0, 1, 2, 3), tolerance=1e-12)
    for _ in range(8):
        ledger.observe(0, 1, delivered=True, dropped=False)
        ledger.observe(0, 2, delivered=False, dropped=True)
        ledger.observe(1, 3, delivered=True, dropped=False)
        ledger.observe(2, 3, delivered=True, dropped=False)
        ledger.observe(3, 1, delivered=True, dropped=False)
    return ledger


class GlobalTrustLedgerTests(unittest.TestCase):
    def test_power_iteration_is_normalized_stable_and_deterministic(self):
        ledger = _evidence_ledger()

        first = ledger.recompute()
        second = ledger.recompute()
        clone = _evidence_ledger().recompute()

        self.assertTrue(ledger.converged)
        self.assertAlmostEqual(sum(first.values()), 1.0)
        self.assertEqual(first, second)
        self.assertEqual(first, clone)
        self.assertGreater(first[1], first[2])

    def test_default_pretrust_is_uniform_and_does_not_use_sybil_labels(self):
        graph = P2PGraph()
        graph.add_node(0)
        graph.add_node(1, sybil=True)
        graph.add_node(2)

        ledger = GlobalTrustLedger(graph.nodes())

        self.assertEqual(ledger.pretrust, {0: 1 / 3, 1: 1 / 3, 2: 1 / 3})
        self.assertEqual(ledger.diagnostics()["pretrust_mode"], "uniform")

    def test_explicit_pretrust_anchors_are_validated(self):
        ledger = GlobalTrustLedger((0, 1, 2), pretrusted_nodes=(0, 2))

        self.assertEqual(ledger.pretrust, {0: 0.5, 1: 0.0, 2: 0.5})
        with self.assertRaisesRegex(ValueError, "unknown pretrusted"):
            GlobalTrustLedger((0, 1, 2), pretrusted_nodes=(9,))

    def test_node_down_is_not_recorded_as_reputation_evidence(self):
        ledger = GlobalTrustLedger((0, 1))

        ledger.observe(
            0, 1, delivered=False, dropped=True, reason="node_down",
        )

        self.assertEqual(dict(ledger.drops), {})


class EigenTrustSolverTests(unittest.TestCase):
    def setUp(self):
        self.graph = P2PGraph()
        link = LinkMetrics(
            latency=0.01, bandwidth=0.8, loss=0.0, stability=0.9,
        )
        self.graph.add_edge(0, 1, link)
        self.graph.add_edge(0, 2, link)
        self.graph.add_edge(1, 3, link)
        self.graph.add_edge(2, 3, link)
        self.graph.compute_landmarks(count=4, seed=1)

        self.ledger = GlobalTrustLedger((0, 1, 2, 3))
        for source in (0, 1, 3):
            self.ledger.observe(source, 2, delivered=True, dropped=False)
        self.ledger.observe(2, 3, delivered=True, dropped=False)
        self.ledger.recompute()
        self.solver = EigenTrustSolver(self.ledger)

    def test_routes_by_global_trust_then_respects_reachability(self):
        packet = Packet(
            packet_id=1, src=0, dst=3, created_at=0.0, ttl=8, node=0,
        )
        self.assertEqual(self.solver.next_hop(self.graph, packet), 2)

        self.graph.offline_nodes.add(2)
        self.assertEqual(self.solver.next_hop(self.graph, packet), 1)

    def test_direct_destination_wins_over_trust_score(self):
        packet = Packet(
            packet_id=2, src=1, dst=3, created_at=0.0, ttl=8, node=1,
        )
        self.assertEqual(self.solver.next_hop(self.graph, packet), 3)

    def test_factory_requires_and_reuses_the_shared_ledger(self):
        with self.assertRaisesRegex(ValueError, "shared GlobalTrustLedger"):
            _make_solver("eigentrust", seed=1)

        first = _make_solver("eigentrust", seed=1, trust_ledger=self.ledger)
        second = _make_solver("eigentrust", seed=2, trust_ledger=self.ledger)
        self.assertIs(first.ledger, self.ledger)
        self.assertIs(second.ledger, self.ledger)

        # The feature remains opt-in: unrelated solver construction is unchanged.
        self.assertIsInstance(_make_solver("shortest", seed=3), ShortestPathSolver)


if __name__ == "__main__":
    unittest.main()
