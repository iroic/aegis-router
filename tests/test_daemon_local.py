from __future__ import annotations

import asyncio
import json
import tempfile
import unittest
from pathlib import Path

from aegis_router.daemon import ClusterStats, run_local_cluster
from aegis_router.packet import Packet
from aegis_router.postquantum_crypto import PostQuantumIdentity, sign_packet, verify_packet


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
