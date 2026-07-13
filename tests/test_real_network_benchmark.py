from __future__ import annotations

import asyncio
import io
import unittest
from argparse import Namespace
from contextlib import redirect_stdout
from unittest.mock import AsyncMock, patch

from scripts.real_network_benchmark import (
    _aggregate,
    _paired_comparison,
    _reset_edge_state,
    _run_seed,
    main_async,
)


def _run(
    delivery: float,
    raw_sybil: float,
    transit_sybil: float,
    hops: float | None,
    *,
    retransmissions: int = 0,
    generated: int = 100,
) -> dict:
    return {
        "delivery_ratio": delivery,
        "sybil_touch_ratio": raw_sybil,
        "transit_sybil_touch_ratio": transit_sybil,
        "avg_hops": hops,
        "retransmissions": retransmissions,
        "generated": generated,
    }


class RealNetworkBenchmarkStatisticsTests(unittest.TestCase):
    def test_edge_state_is_reset_once_before_sequential_learning_runs(self):
        args = Namespace(
            nodes=3,
            degree=2,
            sybil_ratio=0.0,
            sybil_stealth=0.0,
            sybil_extra_drop=0.0,
            duration=1.0,
            drain=0.0,
            traffic_rate=1.0,
            ttl=8,
            link_retries=0,
            redundancy=1,
            redundancy_risk_tolerance=0.05,
            receipts=False,
            receipt_timeout=1.0,
            churn_rate=0.0,
            churn_recovery=0.4,
            congestion_rate=0.0,
            congestion_jitter=0.15,
            perturb_interval=0.5,
            solvers=["edge"],
            learn_runs=3,
        )

        class FakeStats:
            @staticmethod
            def summary():
                return _run(0.6, 0.3, 0.2, 4.0)

        runner = AsyncMock(return_value=FakeStats())
        with patch(
            "scripts.real_network_benchmark._reset_edge_state",
        ) as reset:
            with patch(
                "scripts.real_network_benchmark.run_local_cluster", runner,
            ):
                result = asyncio.run(
                    _run_seed(args, topo_seed=30000, base_port=45000),
                )

        reset.assert_called_once_with(30000, 3)
        self.assertEqual(runner.await_count, 3)
        self.assertEqual(len(result["edge"]), 3)

    def test_edge_state_reset_targets_only_the_current_seed(self):
        with patch("pathlib.Path.unlink", autospec=True) as unlink:
            _reset_edge_state(topo_seed=30000, nodes=2)

        paths = [str(call.args[0]) for call in unlink.call_args_list]
        self.assertEqual(paths, [
            "/tmp/aegis_daemon_node_state_30000000.json",
            "/tmp/aegis_daemon_node_state_30000001.json",
        ])
        for call in unlink.call_args_list:
            self.assertTrue(call.kwargs["missing_ok"])

    def test_run_seed_passes_shared_trust_configuration_once(self):
        args = Namespace(
            nodes=10,
            degree=3,
            sybil_ratio=0.15,
            sybil_stealth=0.5,
            sybil_extra_drop=0.65,
            duration=1.0,
            drain=0.0,
            traffic_rate=1.0,
            ttl=8,
            link_retries=0,
            redundancy=1,
            redundancy_risk_tolerance=0.05,
            receipts=False,
            receipt_timeout=1.0,
            churn_rate=0.0,
            churn_recovery=0.4,
            congestion_rate=0.0,
            congestion_jitter=0.15,
            perturb_interval=0.5,
            solvers=["eigentrust"],
            eigentrust_pretrusted=(0, 4),
            eigentrust_recompute_interval=0.25,
            learn_runs=4,
        )

        class FakeStats:
            @staticmethod
            def summary():
                return _run(0.6, 0.3, 0.2, 4.0)

        runner = AsyncMock(return_value=FakeStats())
        with patch("scripts.real_network_benchmark.run_local_cluster", runner):
            result = asyncio.run(_run_seed(args, topo_seed=30000, base_port=45000))

        runner.assert_awaited_once()
        call = runner.await_args.kwargs
        self.assertEqual(call["solver_name"], "eigentrust")
        self.assertEqual(call["eigentrust_pretrusted"], (0, 4))
        self.assertEqual(call["eigentrust_recompute_interval"], 0.25)
        self.assertEqual(len(result["eigentrust"]), 1)

    def test_aggregate_returns_bounded_coherent_intervals_and_all_spreads(self):
        results = [
            {"edge": [_run(0.02, 0.95, 0.80, 1.0)]},
            {"edge": [_run(0.50, 0.45, 0.35, 4.0)]},
            {"edge": [_run(0.98, 0.05, 0.01, 9.0)]},
        ]

        aggregate = _aggregate(results, "edge", tail=1)

        self.assertEqual(aggregate["n_seeds"], 3)
        for metric, ci_key in (
            ("delivery_ratio", "delivery_ci"),
            ("sybil_touch_ratio", "sybil_touch_ci"),
            ("transit_sybil_touch_ratio", "transit_sybil_touch_ci"),
        ):
            low, high = aggregate[ci_key]
            self.assertGreaterEqual(low, 0.0)
            self.assertLessEqual(high, 1.0)
            self.assertLessEqual(low, aggregate[metric])
            self.assertGreaterEqual(high, aggregate[metric])

        hops_low, hops_high = aggregate["avg_hops_ci"]
        self.assertGreaterEqual(hops_low, 0.0)
        self.assertLessEqual(hops_low, aggregate["avg_hops"])
        self.assertGreaterEqual(hops_high, aggregate["avg_hops"])
        self.assertAlmostEqual(aggregate["delivery_spread"], 0.96)
        self.assertAlmostEqual(aggregate["sybil_touch_spread"], 0.90)
        self.assertAlmostEqual(aggregate["transit_sybil_touch_spread"], 0.79)
        self.assertAlmostEqual(aggregate["avg_hops_spread"], 8.0)

    def test_aggregate_gives_each_seed_one_observation_and_uses_tail(self):
        results = [
            {"edge": [
                _run(0.20, 0.80, 0.70, 8.0),
            ]},
            {"edge": [
                _run(0.00, 1.00, 1.00, 10.0),
                _run(0.80, 0.20, 0.10, 2.0),
                _run(1.00, 0.00, 0.00, 1.0),
            ]},
        ]

        aggregate = _aggregate(results, "edge", tail=2)

        # Seed means are 0.20 and 0.90. The overall mean is therefore 0.55;
        # pooling the three selected runs would incorrectly produce 0.67.
        self.assertAlmostEqual(aggregate["delivery_ratio"], 0.55)
        self.assertAlmostEqual(aggregate["per_seed"][0]["delivery_ratio"], 0.20)
        self.assertAlmostEqual(aggregate["per_seed"][1]["delivery_ratio"], 0.90)
        self.assertEqual(len(aggregate["per_seed"]), 2)

    def test_paired_comparison_reports_positive_reductions_and_significance(self):
        results = []
        for offset in (0.00, 0.02, -0.01, 0.01):
            results.append({
                "shortest": [_run(0.60 + offset, 0.50, 0.30, 5.0)],
                "edge": [_run(0.70 + offset, 0.40, 0.20, 4.5)],
            })

        comparison = _paired_comparison(results, "edge", tail=1)
        metrics = comparison["metrics"]

        self.assertAlmostEqual(metrics["delivery_ratio"]["mean"], 0.10)
        self.assertAlmostEqual(metrics["sybil_touch_ratio"]["mean"], 0.10)
        self.assertAlmostEqual(metrics["transit_sybil_touch_ratio"]["mean"], 0.10)
        self.assertAlmostEqual(metrics["avg_hops"]["mean"], 0.50)
        for metric in metrics.values():
            self.assertTrue(metric["significant"])
            self.assertGreater(metric["ci"][0], 0.0)
            self.assertEqual(metric["n"], 4)

    def test_one_seed_is_never_called_significant(self):
        results = [{
            "shortest": [_run(0.50, 0.50, 0.30, 5.0)],
            "edge": [_run(0.80, 0.20, 0.10, 4.0)],
        }]

        comparison = _paired_comparison(results, "edge", tail=1)

        for metric in comparison["metrics"].values():
            self.assertFalse(metric["significant"])

    def test_report_places_all_metrics_and_paired_deltas_side_by_side(self):
        args = Namespace(
            nodes=10,
            degree=3,
            sybil_ratio=0.15,
            sybil_stealth=0.5,
            sybil_extra_drop=0.65,
            duration=1.0,
            drain=0.0,
            traffic_rate=1.0,
            ttl=8,
            link_retries=0,
            redundancy=1,
            redundancy_risk_tolerance=0.05,
            receipts=False,
            receipt_timeout=1.0,
            churn_rate=0.0,
            churn_recovery=0.4,
            congestion_rate=0.0,
            congestion_jitter=0.15,
            perturb_interval=0.5,
            solvers=["shortest", "edge"],
            topology_seeds=2,
            learn_runs=1,
            tail=1,
            base_seed=30000,
            base_port=45000,
        )
        seed_results = [
            {
                "shortest": [_run(0.60, 0.50, 0.30, 5.0)],
                "edge": [_run(0.70, 0.40, 0.20, 4.5)],
            },
            {
                "shortest": [_run(0.62, 0.52, 0.32, 5.2)],
                "edge": [_run(0.72, 0.42, 0.22, 4.7)],
            },
        ]

        async def fake_run_seed(_args, topo_seed, _base_port):
            return seed_results[topo_seed - args.base_seed]

        output = io.StringIO()
        with patch("scripts.real_network_benchmark._run_seed", side_effect=fake_run_seed):
            with redirect_stdout(output):
                asyncio.run(main_async(args))

        report = output.getvalue()
        self.assertIn("delivery=", report)
        self.assertIn("raw-sybil=", report)
        self.assertIn("transit-sybil=", report)
        self.assertIn("hops=", report)
        self.assertIn("paired deltas versus shortest", report)
        self.assertIn("transit-sybil reduction=", report)
        self.assertIn("CI95=", report)
        self.assertIn("spread=", report)


if __name__ == "__main__":
    unittest.main()
