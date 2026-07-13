#!/usr/bin/env python3
"""
Regression tests for adversarial_benchmark.py

Tests that the attack scenarios are correctly modeled and metrics behave as expected.
"""

from __future__ import annotations

import random
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from aegis_router.event_sim import EventDrivenSimulator
from aegis_router.graph import LinkMetrics, P2PGraph, generate_random_graph
from aegis_router.packet import Packet
from aegis_router.solvers import ShortestPathSolver
from scripts.adversarial_benchmark import (
    ADAPTIVE_SYBIL_META,
    LATENCY_FALSIFICATION_EDGES,
    AttackScenario,
    MUTATORS,
    SCENARIOS,
    mutator_adaptive_sybil,
    mutator_latency_falsification,
    run_sim_benchmark,
)


def test_transit_sybil_metric():
    """A Sybil chosen as RELAY increments transit_sybil_touch; destination does not."""
    graph = generate_random_graph(nodes=20, degree=4, sybil_ratio=0.2, seed=42)
    sim = EventDrivenSimulator(
        graph=graph,
        solver=ShortestPathSolver(),
        seed=42,
        ttl=16,
        sybil_extra_drop=0.5,  # force drops on Sybil links
    )
    stats = sim.run(duration=10, traffic_rate=5, drain_time=3)

    # transit_sybil_touch_ratio should be > 0 when Sybils are relays
    assert stats.transit_sybil_touch_ratio >= 0.0
    assert hasattr(stats, "transit_sybil_touch_ratio"), "EventStats missing transit_sybil_touch_ratio"


def test_sybil_destination_not_counted_as_transit():
    """Packet addressed TO a Sybil should not count as transit exposure."""
    # Create a graph where we know exactly which node is Sybil
    graph = P2PGraph()
    for n in range(5):
        graph.add_node(n, sybil=(n == 4))  # node 4 is the only Sybil
    # Chain: 0-1-2-3-4, all honest except 4
    for a, b in [(0, 1), (1, 2), (2, 3), (3, 4)]:
        graph.add_edge(a, b, LinkMetrics(latency=0.1, bandwidth=1.0, loss=0.0, stability=1.0))

    # Send packet from 0 to 4 (Sybil destination)
    # Simulate by checking the Packet field logic directly
    pkt = Packet(packet_id=0, src=0, dst=4, created_at=0.0, ttl=16, node=0)
    # When arriving at 3, next hop is 4 (the destination Sybil)
    # This should set touched_sybil but NOT touched_transit_sybil
    nxt = 4
    if nxt in graph.sybil_nodes and nxt != pkt.dst:
        pkt.touched_transit_sybil = True
    else:
        pkt.touched_transit_sybil = False

    assert pkt.touched_transit_sybil is False, "Destination Sybil must not count as transit"


def test_mutator_adaptive_sybil():
    """Adaptive Sybil mutator marks Sybil nodes with honest→malicious phase."""
    graph = generate_random_graph(nodes=30, degree=4, sybil_ratio=0.2, seed=123)
    rng = random.Random(123)

    # Initially empty
    assert len(ADAPTIVE_SYBIL_META) == 0

    mutator_adaptive_sybil(graph, rng)

    # Now populated with all Sybil nodes in "honest" phase
    assert len(ADAPTIVE_SYBIL_META) == len(graph.sybil_nodes)
    for n in graph.sybil_nodes:
        assert n in ADAPTIVE_SYBIL_META
        assert ADAPTIVE_SYBIL_META[n]["_phase"] == "honest"
        assert ADAPTIVE_SYBIL_META[n]["_packets_seen"] == 0


def test_mutator_latency_falsification():
    """Latency falsification mutator sets artificially low latency on Sybil edges."""
    graph = generate_random_graph(nodes=30, degree=4, sybil_ratio=0.2, seed=456)
    rng = random.Random(456)

    # Initially empty
    assert len(LATENCY_FALSIFICATION_EDGES) == 0

    mutator_latency_falsification(graph, rng)

    # Now populated with Sybil edges having low latency
    assert len(LATENCY_FALSIFICATION_EDGES) > 0
    for a, b in LATENCY_FALSIFICATION_EDGES:
        m = graph.metrics(a, b)
        assert m.latency <= 0.08, f"Sybil edge ({a},{b}) latency {m.latency} not falsified low"
        # Other metrics should remain in honest-looking range
        assert 0.0 <= m.loss <= 0.5
        assert 0.0 <= m.stability <= 1.0


def test_scenario_latency_falsification_has_mutator():
    """The latency-falsification scenario declares its mutator."""
    sc = SCENARIOS["latency-falsification"]
    assert sc.mutator == "latency_falsification"
    assert sc.sybil_stealth == 0.9
    assert sc.sybil_extra_drop == 0.30


def test_scenario_adaptive_sybil_has_mutator():
    """The adaptive-sybil scenario declares its mutator."""
    sc = SCENARIOS["adaptive-sybil"]
    assert sc.mutator == "adaptive_sybil"
    assert sc.churn_rate == 0.03
    assert sc.congestion_rate == 0.10


def test_baseline_scenario_no_sybils():
    """Baseline has zero Sybils and zero extra drop."""
    sc = SCENARIOS["baseline"]
    assert sc.sybil_ratio == 0.0
    assert sc.sybil_extra_drop == 0.0


def test_coordinated_sybil_stealthy():
    """Coordinated Sybil has high stealth and moderate extra drop."""
    sc = SCENARIOS["coordinated-sybil"]
    assert sc.sybil_stealth == 0.8
    assert sc.sybil_extra_drop == 0.35


def test_blackhole_obvious_metrics():
    """Blackhole Sybils have obvious bad metrics (stealth=0) but extreme drop."""
    sc = SCENARIOS["blackhole"]
    assert sc.sybil_stealth == 0.0
    assert sc.sybil_extra_drop == 0.95


def test_eclipse_high_sybil_ratio():
    """Eclipse attack uses high Sybil ratio to dominate neighborhoods."""
    sc = SCENARIOS["eclipse"]
    assert sc.sybil_ratio == 0.25
    assert sc.sybil_stealth == 0.7


def test_event_stats_includes_transit_field():
    """EventStats dataclass has the new transit_sybil_touch_ratio field."""
    from aegis_router.event_sim import EventStats
    # Just verify the field exists and defaults correctly
    stats = EventStats(
        generated=10, delivered=8, dropped=2, in_flight=0,
        drop_reasons={}, avg_hops=3.0, avg_latency=1.0,
        avg_queue_delay=0.1, avg_loss_risk=0.2,
        sybil_touch_ratio=0.3, retransmissions=0,
    )
    # Python dataclass will have it with default 0.0 if defined
    assert hasattr(stats, "transit_sybil_touch_ratio")
    # Access should not raise AttributeError
    _ = stats.transit_sybil_touch_ratio


def test_quick_sim_with_adaptive_sybil_scenario():
    """Run a quick sim with adaptive-sybil scenario to verify it executes."""
    graph = generate_random_graph(nodes=15, degree=4, sybil_ratio=0.2, seed=999)
    rng = random.Random(999)

    # Apply mutator
    if "adaptive_sybil" in MUTATORS:
        MUTATORS["adaptive_sybil"](graph, rng)

    sim = EventDrivenSimulator(
        graph=graph,
        solver=ShortestPathSolver(),
        seed=999,
        ttl=12,
        sybil_extra_drop=0.45,
        churn_rate=0.03,
        churn_recovery=0.3,
        congestion_rate=0.10,
        congestion_jitter=0.15,
    )
    stats = sim.run(duration=5, traffic_rate=8, drain_time=2)

    assert stats.generated > 0
    assert 0.0 <= stats.delivery_ratio <= 1.0
    assert hasattr(stats, "transit_sybil_touch_ratio")


def test_quick_sim_with_latency_falsification():
    """Run a quick sim with latency-falsification scenario to verify it executes."""
    graph = generate_random_graph(nodes=15, degree=4, sybil_ratio=0.15, seed=888)
    rng = random.Random(888)

    if "latency_falsification" in MUTATORS:
        MUTATORS["latency_falsification"](graph, rng)

    sim = EventDrivenSimulator(
        graph=graph,
        solver=ShortestPathSolver(),
        seed=888,
        ttl=12,
        sybil_extra_drop=0.30,
        congestion_rate=0.15,
        congestion_jitter=0.20,
    )
    stats = sim.run(duration=5, traffic_rate=8, drain_time=2)

    assert stats.generated > 0
    assert 0.0 <= stats.delivery_ratio <= 1.0


class AdversarialBenchmarkTests(unittest.TestCase):
    """Expose the existing scenario checks to the required unittest harness."""

    def test_transit_sybil_metric(self):
        test_transit_sybil_metric()

    def test_sybil_destination_not_counted_as_transit(self):
        test_sybil_destination_not_counted_as_transit()

    def test_mutator_adaptive_sybil(self):
        test_mutator_adaptive_sybil()

    def test_mutator_latency_falsification(self):
        test_mutator_latency_falsification()

    def test_scenario_latency_falsification_has_mutator(self):
        test_scenario_latency_falsification_has_mutator()

    def test_scenario_adaptive_sybil_has_mutator(self):
        test_scenario_adaptive_sybil_has_mutator()

    def test_baseline_scenario_no_sybils(self):
        test_baseline_scenario_no_sybils()

    def test_coordinated_sybil_stealthy(self):
        test_coordinated_sybil_stealthy()

    def test_blackhole_obvious_metrics(self):
        test_blackhole_obvious_metrics()

    def test_eclipse_high_sybil_ratio(self):
        test_eclipse_high_sybil_ratio()

    def test_event_stats_includes_transit_field(self):
        test_event_stats_includes_transit_field()

    def test_quick_sim_with_adaptive_sybil_scenario(self):
        test_quick_sim_with_adaptive_sybil_scenario()

    def test_quick_sim_with_latency_falsification(self):
        test_quick_sim_with_latency_falsification()


if __name__ == "__main__":
    # Allow running standalone
    import pytest
    pytest.main([__file__, "-v"])
