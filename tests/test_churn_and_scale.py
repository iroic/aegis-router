from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from aegis_router.graph import _default_landmark_count, generate_random_graph
from aegis_router.solvers import PersistentLearningSolver


class ChurnMisattributionTests(unittest.TestCase):
    def test_node_down_penalizes_far_less_than_link_loss(self):
        with tempfile.TemporaryDirectory() as td:
            solver_down = PersistentLearningSolver(state_path=f"{td}/down.json")
            solver_loss = PersistentLearningSolver(state_path=f"{td}/loss.json")
            for _ in range(10):
                solver_down.observe_result(neighbor=1, delivered=False, dropped=True, reason="node_down")
                solver_loss.observe_result(neighbor=1, delivered=False, dropped=True, reason="link_loss")

            self.assertLess(solver_down.peer_scores[1].badness, solver_loss.peer_scores[1].badness)
            self.assertLess(solver_down.peer_risk[1], solver_loss.peer_risk[1])

    def test_node_down_does_not_inflate_generic_drop_counter(self):
        with tempfile.TemporaryDirectory() as td:
            solver = PersistentLearningSolver(state_path=f"{td}/state.json")
            solver.observe_result(neighbor=2, delivered=False, dropped=True, reason="node_down")
            self.assertEqual(solver.peer_scores[2].drops, 0)
            self.assertGreater(solver.peer_scores[2].node_down, 0)


class LandmarkScalingTests(unittest.TestCase):
    def test_landmark_count_grows_with_network_size(self):
        small = _default_landmark_count(80)
        large = _default_landmark_count(1000)
        self.assertGreater(large, small)
        # Regression guard: 24 landmarks (the old fixed constant) nearly
        # doubled hop count at 1000 nodes versus ~100 landmarks (measured).
        self.assertGreaterEqual(large, 80)

    def test_generate_random_graph_auto_scales_landmarks_by_default(self):
        g_small = generate_random_graph(nodes=80, degree=5, sybil_ratio=0.1, seed=1)
        g_large = generate_random_graph(nodes=1000, degree=5, sybil_ratio=0.1, seed=1)
        self.assertIsNotNone(g_small.landmark_distance(0, 40))
        self.assertIsNotNone(g_large.landmark_distance(0, 500))

    def test_explicit_landmark_count_overrides_auto_scaling(self):
        g = generate_random_graph(nodes=1000, degree=5, sybil_ratio=0.1, landmarks=5, seed=1)
        self.assertIsNotNone(g.landmark_distance(0, 500))
        g_off = generate_random_graph(nodes=1000, degree=5, sybil_ratio=0.1, landmarks=0, seed=1)
        self.assertIsNone(g_off.landmark_distance(0, 500))


if __name__ == "__main__":
    unittest.main()
