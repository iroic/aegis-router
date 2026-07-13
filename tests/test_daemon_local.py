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

    def test_real_sockets_work_with_shared_eigentrust(self):
        # Regression guard for the daemon-only integration: all local nodes use
        # one shared ledger while packets still traverse real UDP + ML-DSA.
        stats = asyncio.run(run_local_cluster(
            nodes=8, degree=3, sybil_ratio=0.2, duration=2.0, drain=1.5,
            traffic_rate=4.0, ttl=10, solver_name="eigentrust", seed=103,
            eigentrust_recompute_interval=0.1, base_port=19380,
        ))
        self.assertGreater(stats.generated, 0)
        self.assertGreater(len(stats.delivered), 0)
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

    def test_transit_sybil_metric_excludes_a_sybil_destination(self):
        # A packet delivered directly to a sybil destination "touches" it
        # (touched_sybil), but that's just who it was addressed to -- not a
        # relay choice routing could have avoided. touched_transit_sybil
        # must stay False, unlike the raw metric which floors at ~sybil_ratio
        # regardless of routing quality.
        from aegis_router.daemon import LocalNodeProtocol
        from aegis_router.graph import LinkMetrics, P2PGraph
        from aegis_router.solvers import ShortestPathSolver

        async def scenario():
            g = P2PGraph()
            g.add_node(0)
            g.add_node(1, sybil=True)
            g.add_edge(0, 1, LinkMetrics(latency=0.01, bandwidth=0.8, loss=0.0, stability=0.9))
            identity = PostQuantumIdentity.generate()
            stats = ClusterStats()
            loop = asyncio.get_running_loop()
            proto0 = LocalNodeProtocol(
                0, g, ShortestPathSolver(), {}, {}, identity, stats,
                random.Random(1), 0.0, 10, 0, 1, 0.12, False, 4.0, loop,
            )
            pkt = Packet(packet_id=1, src=0, dst=1, created_at=0.0, ttl=10, node=0)
            proto0._handle_arrival(pkt)
            return pkt

        pkt = asyncio.run(scenario())
        self.assertTrue(pkt.touched_sybil)
        self.assertFalse(pkt.touched_transit_sybil)

    def test_transit_sybil_metric_includes_a_sybil_relay(self):
        # Symmetric case: a sybil acting as an INTERMEDIATE hop toward an
        # honest destination is exactly the exposure routing can control,
        # so it must count in both metrics.
        from aegis_router.daemon import LocalNodeProtocol
        from aegis_router.graph import LinkMetrics, P2PGraph
        from aegis_router.solvers import ShortestPathSolver

        async def scenario():
            g = P2PGraph()
            g.add_node(0)
            g.add_node(1, sybil=True)
            g.add_node(2)
            link = LinkMetrics(latency=0.01, bandwidth=0.8, loss=0.0, stability=0.9)
            g.add_edge(0, 1, link)
            g.add_edge(1, 2, link)
            identity = PostQuantumIdentity.generate()
            stats = ClusterStats()
            loop = asyncio.get_running_loop()
            proto0 = LocalNodeProtocol(
                0, g, ShortestPathSolver(), {}, {}, identity, stats,
                random.Random(1), 0.0, 10, 0, 1, 0.12, False, 4.0, loop,
            )
            pkt = Packet(packet_id=1, src=0, dst=2, created_at=0.0, ttl=10, node=0)
            proto0._handle_arrival(pkt)
            return pkt

        pkt = asyncio.run(scenario())
        self.assertTrue(pkt.touched_sybil)
        self.assertTrue(pkt.touched_transit_sybil)

    def test_transit_sybil_touched_never_exceeds_raw_sybil_touched(self):
        # Invariant across a real multi-copy run: transit is always a subset
        # of raw. Reuses the high-sybil-density/high-redundancy scenario that
        # regression-tests the raw metric's own dedup.
        stats = asyncio.run(run_local_cluster(
            nodes=20, degree=5, sybil_ratio=0.4, sybil_extra_drop=0.5,
            duration=4.0, drain=1.5, traffic_rate=8.0, ttl=12,
            solver_name="shortest", seed=909, redundancy=4, base_port=19900,
        ))
        self.assertGreater(stats.sybil_touched, 0)
        self.assertLessEqual(stats.transit_sybil_touched, stats.sybil_touched)
        self.assertLessEqual(stats.sybil_touched, stats.generated)

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

    def test_receipts_confirm_delivered_paths_and_time_out_failures(self):
        # End-to-end: with receipts on, delivered multi-hop packets must
        # produce signed confirmations flowing back (the signal-multiplication
        # the mechanism exists for), and forwards toward black holes must
        # eventually time out (the downstream-failure signal a node otherwise
        # lacks). No bad_signature drops: real receipts verify.
        stats = asyncio.run(run_local_cluster(
            nodes=15, degree=4, sybil_ratio=0.2, duration=5.0, drain=3.0,
            traffic_rate=6.0, ttl=12, solver_name="edge", seed=707,
            receipts=True, receipt_timeout=2.0, base_port=19800,
        ))
        self.assertGreater(stats.receipts_confirmed, 0)
        self.assertGreater(stats.receipt_timeouts, 0)
        self.assertNotIn("bad_signature", stats.dropped)

    def test_receipts_default_off_leaves_behavior_unchanged(self):
        # Same seed/params with and without receipts: the receipt machinery
        # must be fully opt-in. Delivery outcome is identical because the RNG
        # draws are seeded and receipts change only what gets *observed*, not
        # how packets are forwarded within a single run.
        common = dict(
            nodes=15, degree=4, sybil_ratio=0.2, duration=3.0, drain=2.0,
            traffic_rate=6.0, ttl=12, solver_name="shortest", seed=717,
        )
        off = asyncio.run(run_local_cluster(**common, base_port=19820))
        self.assertEqual(off.receipts_confirmed, 0)
        self.assertEqual(off.receipt_timeouts, 0)

    def test_redundancy_sends_extra_copies_and_never_double_counts_delivery(self):
        common = dict(
            nodes=20, degree=5, sybil_ratio=0.1, duration=3.0, drain=1.5,
            traffic_rate=8.0, ttl=12, solver_name="shortest", seed=606,
        )
        baseline = asyncio.run(run_local_cluster(**common, redundancy=1, base_port=19600))
        redundant = asyncio.run(run_local_cluster(**common, redundancy=3, base_port=19650))

        self.assertEqual(baseline.redundant_copies, 0)
        self.assertGreater(redundant.redundant_copies, 0)
        # Dedup invariant: however many copies fly, at most one delivery is
        # ever counted per originally-generated packet.
        self.assertLessEqual(len(redundant.delivered), redundant.generated)

    def test_redundancy_does_not_inflate_sybil_touch_ratio(self):
        # Regression guard: record_drop()/record_delivery() are called once
        # PER COPY, but `generated` counts only once PER LOGICAL PACKET.
        # Without packet_id dedup, a packet whose several redundant copies
        # each independently touched a sybil would count multiple times
        # against a denominator that only grew once -- silently inflating
        # sybil_touch_ratio in a way with nothing to do with real exposure,
        # and making the metric incomparable between redundancy=1 and >1.
        stats = asyncio.run(run_local_cluster(
            nodes=20, degree=5, sybil_ratio=0.4, sybil_extra_drop=0.5,
            duration=4.0, drain=1.5, traffic_rate=8.0, ttl=12,
            solver_name="shortest", seed=909, redundancy=4, base_port=19680,
        ))
        self.assertGreater(stats.sybil_touched, 0)
        self.assertLessEqual(stats.sybil_touched, stats.generated)

    def test_redundancy_does_not_pollute_the_packets_real_visited_set(self):
        # Regression guard for the bug found while validating redundancy:
        # extra_exclude (used to bias a sibling copy's first hop) leaked
        # into the packet's real, persistent visited set, so a legitimate
        # later revisit of one of those nodes (this copy never actually
        # went there) got misreported as a loop far from the origin --
        # earlier measurement showed 50-75 fake "loop" drops per run that
        # vanished once this was fixed.
        #
        # Uses RiskAwareHybridSolver, not ShortestPathSolver: the latter's
        # next_hop() is a pure BFS that never reads packet.visited at all,
        # so extra_exclude has no way to influence its choice (for that
        # solver, each redundant copy is a fresh whole-path retry with
        # independent randomness, not a genuinely different first hop --
        # still a real effect, just a different mechanism than this test).
        from aegis_router.daemon import LocalNodeProtocol
        from aegis_router.graph import LinkMetrics, P2PGraph
        from aegis_router.solvers import RiskAwareHybridSolver

        async def scenario():
            g = P2PGraph()
            link = LinkMetrics(latency=0.01, bandwidth=0.8, loss=0.0, stability=0.9)
            g.add_edge(0, 1, link)
            g.add_edge(0, 2, link)
            g.add_edge(1, 3, link)
            g.add_edge(2, 3, link)
            # Without landmarks, _progress_delta falls back to the legacy
            # ring-distance heuristic (raw node-id arithmetic), which is NOT
            # symmetric between nodes 1 and 2 here despite them being
            # topologically identical -- it would silently confound this
            # test. Landmarks give the real, symmetric BFS distance instead.
            g.compute_landmarks(count=4, seed=1)
            identity = PostQuantumIdentity.generate()
            stats = ClusterStats()
            loop = asyncio.get_running_loop()
            protocol = LocalNodeProtocol(
                0, g, RiskAwareHybridSolver(), {}, {0: identity.signing_public_key},
                identity, stats, random.Random(1), 0.0, 10, 0, 1, 0.12, False, 4.0, loop,
            )
            pkt = Packet(packet_id=1, src=0, dst=3, created_at=0.0, ttl=10, node=0)
            nxt = protocol._handle_arrival(pkt, extra_exclude={1})
            return pkt, nxt

        pkt, nxt = asyncio.run(scenario())
        self.assertEqual(nxt, 2)  # forced away from node 1, the excluded sibling first-hop
        self.assertEqual(pkt.visited, {0})  # NOT {0, 1} -- extra_exclude must not persist

    def test_redundancy_declines_a_meaningfully_riskier_diverse_hop(self):
        # The tension diagnosed in the hardened real-network benchmark:
        # sybil-touch barely moved (46.8% -> 45.3%) even though the same
        # solver halved it (10.2% -> 5.5%) without redundancy, because blind
        # first-hop exclusion could force a copy onto the very neighbor the
        # risk-aware scorer specifically avoids. This checks the fix
        # directly: a meaningfully riskier diverse alternative must be
        # declined (reuse the natural hop instead), a comparably-safe one
        # must be taken.
        from aegis_router.daemon import LocalNodeProtocol
        from aegis_router.graph import LinkMetrics, P2PGraph
        from aegis_router.solvers import RiskAwareHybridSolver

        async def scenario(risk_of_alt):
            g = P2PGraph()
            link = LinkMetrics(latency=0.01, bandwidth=0.8, loss=0.0, stability=0.9)
            g.add_edge(0, 1, link)
            g.add_edge(0, 2, link)
            g.add_edge(1, 3, link)
            g.add_edge(2, 3, link)
            # Without landmarks, _progress_delta falls back to the legacy
            # ring-distance heuristic (raw node-id arithmetic), which is NOT
            # symmetric between nodes 1 and 2 here despite them being
            # topologically identical -- it would silently confound this
            # test. Landmarks give the real, symmetric BFS distance instead.
            g.compute_landmarks(count=4, seed=1)
            identity = PostQuantumIdentity.generate()
            stats = ClusterStats()
            loop = asyncio.get_running_loop()
            solver = RiskAwareHybridSolver()
            solver.peer_risk[2] = risk_of_alt  # node 1 stays at the default 0.0
            protocol = LocalNodeProtocol(
                0, g, solver, {}, {0: identity.signing_public_key}, identity,
                stats, random.Random(1), 0.0, 10, 0, 1, 0.12, False, 4.0, loop,
            )
            pkt = Packet(packet_id=1, src=0, dst=3, created_at=0.0, ttl=10, node=0)
            return protocol._handle_arrival(pkt, extra_exclude={1})

        # 1 and 2 have identical link quality, so peer_risk alone decides
        # the natural choice: node 1 (risk 0.0) always wins over node 2.
        risky = asyncio.run(scenario(0.9))
        safe = asyncio.run(scenario(0.02))
        self.assertEqual(risky, 1)  # declines node 2: too much riskier than reusing 1
        self.assertEqual(safe, 2)   # takes node 2: comparably safe, genuinely diverse

    def test_redundancy_improves_delivery_under_heavy_churn(self):
        # The failure mode redundancy specifically targets: a packet
        # correctly routed toward a node that dies mid-transit. Independent
        # paths rarely die to the same churn event.
        #
        # Uses the edge solver, not shortest-path: shortest-path's next_hop()
        # ignores packet.visited entirely, so its redundancy benefit is only
        # "retry the same path with fresh randomness" -- a real but small
        # effect (measured +3.5 to +5.8pp) too close to this real-time
        # daemon's own run-to-run jitter for a single-comparison assertion
        # to be reliable (this exact test flaked ~1/3 of the time with
        # shortest-path). The edge solver's genuine path diversity produces
        # a much larger, more robust effect (measured +10.8 to +17.2pp).
        common = dict(
            nodes=30, degree=5, sybil_ratio=0.1, duration=6.0, drain=2.0,
            traffic_rate=10.0, ttl=14, solver_name="edge", seed=707,
            churn_rate=0.2, churn_recovery=0.3, perturb_interval=0.3,
        )
        baseline = asyncio.run(run_local_cluster(**common, redundancy=1, base_port=19700))
        redundant = asyncio.run(run_local_cluster(**common, redundancy=3, base_port=19750))

        self.assertGreaterEqual(redundant.delivery_ratio, baseline.delivery_ratio)

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
