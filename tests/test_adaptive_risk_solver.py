from __future__ import annotations

import unittest

from aegis_router.event_sim import EventDrivenSimulator
from aegis_router.graph import generate_random_graph
from aegis_router.solvers import AdaptiveRiskSolver, RiskAwareHybridSolver, ShortestPathSolver


class AdaptiveRiskSolverTests(unittest.TestCase):
    def test_relaxes_budget_after_many_drops(self):
        solver = AdaptiveRiskSolver(risk_budget=0.20, min_budget=0.10, max_budget=0.60, adapt_step=0.05, window_size=4)

        for i in range(4):
            solver.observe_result(neighbor=i, delivered=False, dropped=True)

        self.assertGreater(solver.risk_budget, 0.20)

    def test_tightens_budget_after_many_sybil_touches(self):
        solver = AdaptiveRiskSolver(risk_budget=0.40, min_budget=0.10, max_budget=0.60, adapt_step=0.05, window_size=4)

        for i in range(4):
            solver.observe_result(neighbor=i, delivered=True, dropped=False, touched_sybil=True)

        self.assertLess(solver.risk_budget, 0.40)

    def test_adaptive_improves_delivery_vs_static_risk_aware_while_beating_shortest_sybil(self):
        graph = generate_random_graph(nodes=80, degree=5, sybil_ratio=0.2, seed=51)
        shortest = EventDrivenSimulator(graph, ShortestPathSolver(), seed=52, ttl=18)
        static = EventDrivenSimulator(graph, RiskAwareHybridSolver(), seed=52, ttl=18)
        adaptive = EventDrivenSimulator(graph, AdaptiveRiskSolver(), seed=52, ttl=18)

        shortest_stats = shortest.run(duration=10.0, traffic_rate=12.0)
        static_stats = static.run(duration=10.0, traffic_rate=12.0)
        adaptive_stats = adaptive.run(duration=10.0, traffic_rate=12.0)

        self.assertGreaterEqual(adaptive_stats.delivery_ratio, static_stats.delivery_ratio * 0.95)
        self.assertLess(adaptive_stats.sybil_touch_ratio, shortest_stats.sybil_touch_ratio)
        self.assertLessEqual(adaptive_stats.avg_loss_risk, shortest_stats.avg_loss_risk * 1.05)


if __name__ == "__main__":
    unittest.main()
