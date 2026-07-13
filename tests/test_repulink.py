from __future__ import annotations

import unittest

from aegis_router.daemon import _make_solver, parse_endorsements
from aegis_router.graph import LinkMetrics, P2PGraph
from aegis_router.packet import Packet
from aegis_router.postquantum_crypto import PostQuantumIdentity, sign_endorsement
from aegis_router.repulink import RepuLinkLedger, RepuLinkSolver, SignedEndorsement
from aegis_router.solvers import ShortestPathSolver


class RepuLinkLedgerTests(unittest.TestCase):
    def test_cold_start_is_normalized_deterministic_and_uses_explicit_endorsements(self):
        endorsements = ((0, 2, 1.0), (1, 3, 1.0))
        first = RepuLinkLedger((0, 1, 2, 3), endorsements=endorsements)
        second = RepuLinkLedger((0, 1, 2, 3), endorsements=endorsements)

        self.assertEqual(first.cold_start(), second.cold_start())
        self.assertAlmostEqual(sum(first.cold_start().values()), 1.0)
        self.assertGreater(first.cold_start()[2], first.cold_start()[0])
        self.assertGreater(first.cold_start()[3], first.cold_start()[1])

    def test_backward_accountability_penalizes_endorsers_and_rewards_delivery(self):
        ledger = RepuLinkLedger(
            (0, 1, 2, 3),
            endorsements=((0, 1, 1.0), (1, 2, 1.0), (0, 3, 1.0)),
        )
        for _ in range(8):
            ledger.observe(3, 2, delivered=False, dropped=True)
            ledger.observe(3, 3, delivered=True, dropped=False)

        reputation = ledger.recompute()
        accountability = ledger.accountability()

        self.assertAlmostEqual(sum(reputation.values()), 1.0)
        self.assertTrue(ledger.converged)
        self.assertGreater(accountability[1]["penalty"], 0.0)
        self.assertGreater(accountability[0]["penalty"], 0.0)
        self.assertGreater(accountability[1]["penalty"], accountability[0]["penalty"])
        self.assertGreater(accountability[0]["reward"], 0.0)

    def test_drops_lower_reputation_relative_to_an_equally_endorsed_delivery_target(self):
        ledger = RepuLinkLedger(
            (0, 1, 2, 3),
            endorsements=((0, 1, 0.5), (0, 2, 0.5)),
        )
        for _ in range(4):
            ledger.observe(3, 1, delivered=True, dropped=False)
            ledger.observe(3, 2, delivered=False, dropped=True)

        first = ledger.recompute()
        second = ledger.recompute()

        self.assertEqual(first, second)
        self.assertAlmostEqual(sum(first.values()), 1.0)
        self.assertGreater(first[1], first[2])

    def test_node_down_is_not_reputation_evidence_and_endorsements_are_validated(self):
        ledger = RepuLinkLedger((0, 1, 2), endorsements=((0, 1, 0.8),))
        ledger.observe(0, 1, delivered=False, dropped=True, reason="node_down")

        self.assertEqual(dict(ledger.drops), {})
        with self.assertRaisesRegex(ValueError, "duplicate endorsement"):
            ledger.add_endorsement(0, 1, 0.5)
        with self.assertRaisesRegex(ValueError, "self-endorsements"):
            ledger.add_endorsement(1, 1, 0.5)
        with self.assertRaisesRegex(ValueError, "unknown node"):
            ledger.add_endorsement(1, 9, 0.5)

    def test_signed_endorsement_requires_anchor_validity_and_authenticity(self):
        anchor = PostQuantumIdentity.generate()
        untrusted = PostQuantumIdentity.generate()
        ledger = RepuLinkLedger((0, 1, 2), trusted_endorsers=(0,))
        signed = SignedEndorsement(
            endorser=0,
            endorsee=2,
            confidence=0.8,
            issued_at=100.0,
            expires_at=200.0,
            signature=sign_endorsement(
                0, 2, 0.8, 100.0, 200.0, anchor.signing_secret_key,
            ),
        )

        ledger.add_signed_endorsement(
            signed, public_keys={0: anchor.signing_public_key}, now=150.0,
        )
        self.assertEqual(ledger.endorsement_edges, {(0, 2): 0.8})
        self.assertEqual(ledger.diagnostics()["signed_endorsements_accepted"], 1)

        forged = SignedEndorsement(
            endorser=0, endorsee=1, confidence=0.8, issued_at=100.0,
            expires_at=200.0,
            signature=sign_endorsement(
                0, 1, 0.8, 100.0, 200.0, untrusted.signing_secret_key,
            ),
        )
        with self.assertRaisesRegex(ValueError, "invalid endorsement signature"):
            ledger.add_signed_endorsement(
                forged, public_keys={0: anchor.signing_public_key}, now=150.0,
            )
        with self.assertRaisesRegex(ValueError, "not currently valid"):
            ledger.add_signed_endorsement(
                signed, public_keys={0: anchor.signing_public_key}, now=201.0,
            )

        non_anchor = SignedEndorsement(
            endorser=1, endorsee=2, confidence=0.8, issued_at=100.0,
            expires_at=200.0,
            signature=sign_endorsement(
                1, 2, 0.8, 100.0, 200.0, untrusted.signing_secret_key,
            ),
        )
        with self.assertRaisesRegex(ValueError, "not a configured trust anchor"):
            ledger.add_signed_endorsement(
                non_anchor, public_keys={1: untrusted.signing_public_key}, now=150.0,
            )


class RepuLinkSolverTests(unittest.TestCase):
    def setUp(self):
        self.graph = P2PGraph()
        link = LinkMetrics(latency=0.01, bandwidth=0.8, loss=0.0, stability=0.9)
        self.graph.add_edge(0, 1, link)
        self.graph.add_edge(0, 2, link)
        self.graph.add_edge(1, 3, link)
        self.graph.add_edge(2, 3, link)
        self.graph.compute_landmarks(count=4, seed=1)
        self.ledger = RepuLinkLedger((0, 1, 2, 3), endorsements=((0, 2, 1.0),))
        self.solver = RepuLinkSolver(self.ledger)

    def test_routes_by_reputation_then_reachability_and_direct_destination(self):
        packet = Packet(packet_id=1, src=0, dst=3, created_at=0.0, ttl=8, node=0)
        self.assertEqual(self.solver.next_hop(self.graph, packet), 2)

        self.graph.offline_nodes.add(2)
        self.assertEqual(self.solver.next_hop(self.graph, packet), 1)

        direct = Packet(packet_id=2, src=1, dst=3, created_at=0.0, ttl=8, node=1)
        self.assertEqual(self.solver.next_hop(self.graph, direct), 3)

    def test_factory_reuses_shared_ledger_and_default_solver_is_unchanged(self):
        with self.assertRaisesRegex(ValueError, "shared RepuLinkLedger"):
            _make_solver("repulink", seed=1)

        first = _make_solver("repulink", seed=1, repulink_ledger=self.ledger)
        second = _make_solver("repulink", seed=2, repulink_ledger=self.ledger)
        self.assertIs(first.ledger, self.ledger)
        self.assertIs(second.ledger, self.ledger)
        self.assertIsInstance(_make_solver("shortest", seed=3), ShortestPathSolver)


class RepuLinkCliTests(unittest.TestCase):
    def test_parse_endorsements_requires_explicit_well_formed_edges(self):
        self.assertEqual(parse_endorsements("0:2:0.75, 1:3:1"), ((0, 2, 0.75), (1, 3, 1.0)))
        self.assertEqual(parse_endorsements(""), ())
        with self.assertRaisesRegex(ValueError, "endorser:endorsee:confidence"):
            parse_endorsements("0:1")
        with self.assertRaisesRegex(ValueError, "invalid endorsement"):
            parse_endorsements("a:1:0.5")


if __name__ == "__main__":
    unittest.main()
