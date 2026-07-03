#!/usr/bin/env python3
from __future__ import annotations

import argparse
import importlib.util
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

BENCH_PATH = ROOT / "scripts" / "refine_edge_multiscenario.py"
def load_benchmark():
    spec = importlib.util.spec_from_file_location("aegis_refine_benchmark", BENCH_PATH)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load {BENCH_PATH}")
    module = importlib.util.module_from_spec(spec)
    sys.modules["aegis_refine_benchmark"] = module
    spec.loader.exec_module(module)
    return module


def scenarios_for(split: str):
    bench = load_benchmark()
    if split == "dev":
        return bench.SCENARIOS[:5]
    if split == "test":
        return bench.SCENARIOS[5:]
    raise SystemExit(f"unknown split: {split}")


def seed_offsets_for(split: str) -> list[int]:
    if split == "dev":
        return [20260612, 20260613, 20260614]
    if split == "test":
        return [20270612, 20270613, 20270614]
    raise SystemExit(f"unknown split: {split}")


def load_params(profile_path: Path) -> dict[str, object]:
    payload = json.loads(profile_path.read_text())
    params = dict(payload["params"])
    params["solver"] = "edge"
    params["candidate_id"] = 1
    params["parent"] = "baseline"
    return params


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--split", choices=["dev", "test"], required=True)
    ap.add_argument("--objective", choices=["balanced", "sybil_stress", "delivery_stress"], default="sybil_stress")
    ap.add_argument("--profile", default=str(ROOT / "profiles" / "aegis-prod-edge-v1.json"))
    ap.add_argument("--workdir", default=str(Path(__file__).resolve().parent / "benchmark_state"))
    args = ap.parse_args()

    bench = load_benchmark()
    profile_path = Path(args.profile)
    params = load_params(profile_path)
    scenarios = scenarios_for(args.split)
    seed_offsets = seed_offsets_for(args.split)
    workdir = Path(args.workdir) / profile_path.stem / args.split
    workdir.mkdir(parents=True, exist_ok=True)

    result = bench.evaluate_multiscenario(
        params,
        seed_offsets,
        scenarios,
        str(workdir),
        stage=args.split,
        objective=args.objective,
    )
    print(
        json.dumps(
            {
                "score": result["robust_score"],
                "primary_score": result["robust_score"],
                "delivery": result["mean_delivery"],
                "sybil": result["mean_sybil"],
                "max_sybil": result["max_sybil"],
                "drop": result["mean_drop"],
                "latency": result["latency"] if "latency" in result else result["mean_risk"],
                "hops": result["hops"] if "hops" in result else result["mean_risk"],
                "scenario_count": result["scenario_count"],
                "seed_count": result["seed_count"],
                "objective": args.objective,
                "split": args.split,
                "profile": str(profile_path),
            },
            indent=2,
            sort_keys=True,
        )
    )


if __name__ == "__main__":
    main()
