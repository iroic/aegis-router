from __future__ import annotations

import unittest

from aegis_router.agent import HybridRoutingScorer, QRoutingAgent
from aegis_router.graph import LinkMetrics, P2PGraph
from aegis_router.packet import Packet
from aegis_router.solvers import RiskAwareHybridSolver

GOOD = LinkMetrics(latency=0.05, bandwidth=1.0, loss=0.0, stability=1.0)
POOR = LinkMetrics(latency=0.4, bandwidth=0.3, loss=0.1, stability=0.4)


def revisit_trap_graph() -> P2PGraph:
    """0's best-scoring neighbor (1) is already visited; 2 is unvisited but
    scores worse on every raw metric. A soft loop_penalty can still lose this
    contest; only a hard exclude of visited nodes reliably avoids the loop."""
    g = P2PGraph()
    g.add_edge(0, 1, GOOD)
    g.add_edge(0, 2, POOR)
    g.add_edge(1, 3, GOOD)
    g.add_edge(2, 3, GOOD)
    return g


class HardVisitedExclusionTests(unittest.TestCase):
    def test_hybrid_scorer_never_revisits_when_an_alternative_exists(self):
        g = revisit_trap_graph()
        # A tiny loop_penalty: if exclusion were only a soft penalty, node 1's
        # much better metrics would still win the score comparison.
        scorer = HybridRoutingScorer(loop_penalty=0.01)
        chosen = scorer.choose(g, node=0, dst=3, visited={1}, ttl_remaining=10)
        self.assertEqual(chosen, 2)

    def test_risk_aware_solver_never_revisits_when_an_alternative_exists(self):
        g = revisit_trap_graph()
        solver = RiskAwareHybridSolver()
        solver.scorer.loop_penalty = 0.01
        pkt = Packet(packet_id=1, src=0, dst=3, created_at=0.0, ttl=8, node=0)
        pkt.visited.add(1)
        self.assertEqual(solver.next_hop(g, pkt), 2)

    def test_falls_back_to_a_visited_node_when_it_is_the_only_option(self):
        g = P2PGraph()
        g.add_edge(0, 1, GOOD)
        scorer = HybridRoutingScorer()
        chosen = scorer.choose(g, node=0, dst=9, visited={1}, ttl_remaining=10)
        self.assertEqual(chosen, 1)

    def test_q_agent_already_hard_excludes_visited_neighbors(self):
        g = revisit_trap_graph()
        agent = QRoutingAgent(seed=1)
        chosen = agent.choose(g, 0, 3, train=False, visited={1})
        self.assertEqual(chosen, 2)


if __name__ == "__main__":
    unittest.main()
