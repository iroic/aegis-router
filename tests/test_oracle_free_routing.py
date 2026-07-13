from __future__ import annotations

import asyncio
import random
import tempfile
import unittest
from pathlib import Path

from aegis_router.daemon import ClusterStats, LocalNodeProtocol
from aegis_router.graph import LinkMetrics, P2PGraph
from aegis_router.packet import Packet
from aegis_router.postquantum_crypto import PostQuantumIdentity
from aegis_router.solvers import EdgeLearningSolver, PersistentLearningSolver


class _RecordingSolver:
    def __init__(self):
        self.observations = []

    def next_hop(self, graph, packet):
        return None

    def observe_result(self, **kwargs):
        self.observations.append(kwargs)


class OracleFreeRoutingTests(unittest.TestCase):
    def test_persistent_and_edge_scores_ignore_touched_sybil(self):
        with tempfile.TemporaryDirectory() as td:
            plain = PersistentLearningSolver(state_path=Path(td) / "plain.json")
            labelled = PersistentLearningSolver(state_path=Path(td) / "labelled.json")
            for solver, touched in ((plain, False), (labelled, True)):
                solver.observe_result(
                    neighbor=7, delivered=False, dropped=True,
                    touched_sybil=touched, reason="link_loss",
                )
            self.assertEqual(plain.peer_scores[7].badness, labelled.peer_scores[7].badness)
            self.assertEqual(labelled.peer_scores[7].sybil_touches, 0)

            edge_plain = EdgeLearningSolver(state_path=Path(td) / "edge-plain.json")
            edge_labelled = EdgeLearningSolver(state_path=Path(td) / "edge-labelled.json")
            for solver, touched in ((edge_plain, False), (edge_labelled, True)):
                solver.observe_result(
                    from_node=0, neighbor=7, delivered=False, dropped=True,
                    touched_sybil=touched, reason="link_loss",
                )
            self.assertEqual(
                edge_plain.edge_scores[(0, 7)].badness,
                edge_labelled.edge_scores[(0, 7)].badness,
            )
            self.assertEqual(edge_labelled.edge_scores[(0, 7)].sybil_touches, 0)

    def test_daemon_keeps_sybil_labels_out_of_solver_observations(self):
        async def scenario():
            graph = P2PGraph()
            graph.add_node(0)
            graph.add_node(1, sybil=True)
            graph.add_edge(0, 1, LinkMetrics(0.01, 0.8, 0.0, 0.9))
            solver = _RecordingSolver()
            protocol = LocalNodeProtocol(
                0, graph, solver, {}, {}, PostQuantumIdentity.generate(),
                ClusterStats(), random.Random(1), 0.0, 8, 0, 1, 0.05,
                False, 1.0, asyncio.get_running_loop(),
            )
            protocol._observe_own_link(1, success=False)
            return solver.observations

        observations = asyncio.run(scenario())
        self.assertEqual(len(observations), 1)
        self.assertFalse(observations[0]["touched_sybil"])
        self.assertEqual(observations[0]["reason"], "link_loss")

    def test_oracle_label_does_not_change_next_hop(self):
        graph = P2PGraph()
        link = LinkMetrics(0.1, 1.0, 0.01, 0.9)
        for node in (0, 1, 2, 9):
            graph.add_node(node)
        graph.add_edge(0, 1, link)
        graph.add_edge(0, 2, link)
        graph.add_edge(1, 9, link)
        graph.add_edge(2, 9, link)

        with tempfile.TemporaryDirectory() as td:
            plain = PersistentLearningSolver(state_path=Path(td) / "plain.json")
            labelled = PersistentLearningSolver(state_path=Path(td) / "labelled.json")
            for solver, touched in ((plain, False), (labelled, True)):
                for _ in range(4):
                    solver.observe_result(
                        neighbor=1, delivered=False, dropped=True,
                        touched_sybil=touched, reason="link_loss",
                    )
            packet = Packet(packet_id=1, src=0, dst=9, created_at=0.0, ttl=8, node=0)
            self.assertEqual(plain.next_hop(graph, packet), labelled.next_hop(graph, packet))


if __name__ == "__main__":
    unittest.main()
