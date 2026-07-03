from __future__ import annotations

import asyncio
import json
import random
import tempfile
import unittest
from pathlib import Path

from aegis_router.daemon import ClusterStats, _perturb_loop, run_local_cluster
from aegis_router.graph import generate_random_graph
from aegis_router.packet import Packet
from aegis_router.postquantum_crypto import PostQuantumIdentity, sign_packet, verify_packet


async def _run_perturb_briefly(graph, node_ids, **kwargs):
    task = asyncio.create_task(_perturb_loop(graph, node_ids, **kwargs))
    await asyncio.sleep(0.12)
    task.cancel()
    try:
        await task
    except asyncio.CancelledError:
        pass


class DaemonLocalClusterTests(unittest.TestCase):
    def test_real_sockets_deliver_packets_with_valid_signatures(self):
        stats = asyncio.run(run_local_cluster(
            nodes=8, degree=3, sybil_ratio=0.2, duration=2.0, drain=1.5,
            traffic_rate=4.0, ttl=10, solver_name="shortest", seed=101, base_port=19300,
        ))
        self.assertGreater(stats.generated, 0)
        self.assertGreater(len(stats.delivered), 0)
        # bad_signature would only appear if verification failed for a
        # legitimately-delivered packet -- proves the real sign/verify path
        # (not just the standalone crypto unit tests) works end-to-end.
        self.assertNotIn("bad_signature", stats.dropped)

    def test_real_sockets_work_with_the_learned_solver_too(self):
        stats = asyncio.run(run_local_cluster(
            nodes=8, degree=3, sybil_ratio=0.2, duration=2.0, drain=1.5,
            traffic_rate=4.0, ttl=10, solver_name="edge", seed=102, base_port=19320,
        ))
        self.assertGreater(stats.generated, 0)
        self.assertNotIn("bad_signature", stats.dropped)

    def test_edge_solver_persists_learned_state_to_disk(self):
        # Regression guard: run_local_cluster must call solver.save() at the
        # end, or "learning across repeated runs" is a no-op even though a
        # state file path exists (EdgeLearningSolver only loads on construction).
        seed = 9001
        state_path = Path(f"/tmp/aegis_daemon_node_state_{seed * 1000 + 0}.json")
        state_path.unlink(missing_ok=True)
        asyncio.run(run_local_cluster(
            nodes=6, degree=3, sybil_ratio=0.2, duration=2.0, drain=1.0,
            traffic_rate=5.0, ttl=10, solver_name="edge", seed=seed, base_port=19340,
        ))
        self.assertTrue(state_path.exists())
        data = json.loads(state_path.read_text())
        self.assertIn("risk_budget", data)
        # Regression guard for the companion bug: forwarding must call
        # observe_result() on the local solver, or every edge stays at all
        # zeros forever and .save() just re-writes an untouched state.
        totals = sum(v["delivered"] + v["drops"] for v in data["edges"].values())
        self.assertGreater(totals, 0)

    def test_link_retries_reduce_link_loss_drops(self):
        common = dict(
            nodes=20, degree=4, sybil_ratio=0.1, duration=3.0, drain=1.5,
            traffic_rate=8.0, ttl=12, solver_name="shortest", seed=303,
        )
        baseline = asyncio.run(run_local_cluster(**common, link_retries=0, base_port=19400))
        with_arq = asyncio.run(run_local_cluster(**common, link_retries=2, base_port=19450))

        self.assertEqual(baseline.retransmissions, 0)
        self.assertGreater(with_arq.retransmissions, 0)
        self.assertGreaterEqual(with_arq.delivery_ratio, baseline.delivery_ratio)

    def test_sybil_touch_ratio_counts_packets_dropped_by_a_sybil(self):
        # Regression guard: touched_sybil must be set BEFORE the drop branch
        # in _forward, not only on the success path -- a packet killed by a
        # sybil hop is the clearest possible case of "touched a sybil".
        stats = asyncio.run(run_local_cluster(
            nodes=20, degree=4, sybil_ratio=0.3, sybil_extra_drop=0.9,
            duration=3.0, drain=1.5, traffic_rate=8.0, ttl=12,
            solver_name="shortest", seed=404, base_port=19460,
        ))
        self.assertGreater(stats.dropped.get("sybil_drop", 0), 0)
        self.assertGreaterEqual(stats.sybil_touched, stats.dropped["sybil_drop"])
        self.assertGreater(stats.sybil_touch_ratio, 0.0)

    def test_churn_flips_nodes_offline(self):
        graph = generate_random_graph(nodes=10, degree=3, sybil_ratio=0.0, seed=1)
        asyncio.run(_run_perturb_briefly(
            graph, graph.nodes(), perturb_interval=0.02,
            congestion_rate=0.0, congestion_jitter=0.0,
            churn_rate=1.0, churn_recovery=0.0, rng=random.Random(1),
        ))
        # churn_rate=1.0, recovery=0.0: every node flips down on its first
        # tick and never recovers.
        self.assertEqual(len(graph.offline_nodes), 10)

    def test_congestion_drifts_link_metrics(self):
        graph = generate_random_graph(nodes=10, degree=3, sybil_ratio=0.0, seed=2)
        original = {(a, b): graph.metrics(a, b) for a in graph.adj for b in graph.adj[a] if a < b}
        asyncio.run(_run_perturb_briefly(
            graph, graph.nodes(), perturb_interval=0.02,
            congestion_rate=1.0, congestion_jitter=0.3,
            churn_rate=0.0, churn_recovery=0.0, rng=random.Random(2),
        ))
        changed = sum(1 for (a, b), m in original.items() if graph.metrics(a, b) != m)
        self.assertGreater(changed, 0)

    def test_real_sockets_produce_node_down_drops_under_churn(self):
        # End-to-end: churn must actually reach the real forwarding path,
        # not just mutate graph.offline_nodes in isolation.
        stats = asyncio.run(run_local_cluster(
            nodes=15, degree=4, sybil_ratio=0.1, duration=4.0, drain=2.0,
            traffic_rate=6.0, ttl=12, solver_name="shortest", seed=505,
            base_port=19500, churn_rate=0.3, churn_recovery=0.3, perturb_interval=0.2,
        ))
        self.assertGreater(stats.generated, 0)
        self.assertIn("node_down", stats.dropped)

    def test_tampered_signature_is_actually_rejected(self):
        # Negative control: proves verify_packet's rejection path is live,
        # not a check that always silently passes.
        identity = PostQuantumIdentity.generate()
        other_identity = PostQuantumIdentity.generate()
        pkt = Packet(packet_id=1, src=1, dst=2, created_at=0.0, ttl=8)
        sign_packet(pkt, identity.signing_secret_key)

        self.assertTrue(verify_packet(pkt, identity.signing_public_key))
        self.assertFalse(verify_packet(pkt, other_identity.signing_public_key))


if __name__ == "__main__":
    unittest.main()
