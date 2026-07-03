#!/usr/bin/env python3
"""Rank existing edge profiles with a transparent dev-only CVaR objective."""

from __future__ import annotations

import csv
import json
import math
from pathlib import Path
from statistics import fmean, pstdev


ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / "results" / "1-cvar-tail-selection"
DEV_SCENARIOS = {
    "n120_d6_s08_t36",
    "n120_d6_s10_t36",
    "n80_d4_s10_t30",
    "n200_d6_s08_t36",
    "n120_d8_s10_t48",
}
SOURCES = [
    ROOT / "runs" / "refine_edge_global_v1" / "stage2_results.csv",
    ROOT / "runs" / "refine_edge_global_v2" / "stage2_results.csv",
    ROOT / "runs" / "refine_edge_global_v1" / "stage3_results.csv",
    ROOT / "runs" / "refine_edge_global_v2" / "stage3_results.csv",
]


def mean_tail(values: list[float], *, high: bool) -> float:
    """Return the mean of the worst 40% (two of five dev scenarios)."""
    count = max(1, math.ceil(0.40 * len(values)))
    ordered = sorted(values, reverse=high)
    return fmean(ordered[:count])


def parse_rows() -> list[dict]:
    rows: list[dict] = []
    seen: set[str] = set()
    for source in SOURCES:
        with source.open(newline="", encoding="utf-8") as handle:
            for raw in csv.DictReader(handle):
                params = json.loads(raw["params"])
                key = json.dumps(params, sort_keys=True, separators=(",", ":"))
                if key in seen:
                    continue
                metrics = [
                    item
                    for item in json.loads(raw["scenario_metrics"])
                    if item["scenario"] in DEV_SCENARIOS
                ]
                if len(metrics) != len(DEV_SCENARIOS):
                    continue
                seen.add(key)
                scores = [float(item["score"]) for item in metrics]
                deliveries = [float(item["delivery"]) for item in metrics]
                sybils = [float(item["sybil"]) for item in metrics]
                cvar_score = mean_tail(scores, high=False)
                cvar_delivery = mean_tail(deliveries, high=False)
                cvar_sybil = mean_tail(sybils, high=True)
                score_std = pstdev(scores)
                # This is an offline selection objective, not the benchmark metric:
                # reward lower-tail score/delivery, penalize upper-tail Sybil exposure
                # and scenario instability.
                selection_score = (
                    0.50 * cvar_score
                    + 0.35 * cvar_delivery
                    - 0.75 * cvar_sybil
                    - 0.10 * score_std
                )
                rows.append(
                    {
                        "source": str(source.relative_to(ROOT)),
                        "candidate_id": int(raw["candidate_id"]),
                        "stage": raw["stage"],
                        "parent": raw["parent"],
                        "selection_score": selection_score,
                        "cvar_score_low40": cvar_score,
                        "cvar_delivery_low40": cvar_delivery,
                        "cvar_sybil_high40": cvar_sybil,
                        "dev_score_mean": fmean(scores),
                        "dev_score_std": score_std,
                        "dev_delivery_mean": fmean(deliveries),
                        "dev_sybil_mean": fmean(sybils),
                        "dev_sybil_max": max(sybils),
                        "original_robust_score": float(raw["robust_score"]),
                        "params": params,
                    }
                )
    return sorted(rows, key=lambda item: item["selection_score"], reverse=True)


def normalized_distance(left: dict, right: dict, ranges: dict[str, tuple[float, float]]) -> float:
    terms: list[float] = []
    for key, value in left.items():
        if key == "solver" or key not in right:
            continue
        if not isinstance(value, (int, float)) or not isinstance(right[key], (int, float)):
            continue
        low, high = ranges[key]
        scale = high - low
        if scale > 0:
            terms.append(((float(value) - float(right[key])) / scale) ** 2)
    return math.sqrt(fmean(terms)) if terms else 0.0


def shortlist(rows: list[dict], count: int = 6) -> list[dict]:
    numeric_keys = {
        key
        for row in rows
        for key, value in row["params"].items()
        if isinstance(value, (int, float)) and not isinstance(value, bool)
    }
    ranges = {
        key: (
            min(float(row["params"][key]) for row in rows if key in row["params"]),
            max(float(row["params"][key]) for row in rows if key in row["params"]),
        )
        for key in numeric_keys
    }

    pool = rows[:60]
    selected = [pool[0]]
    while len(selected) < count:
        best = None
        best_value = float("-inf")
        for rank, row in enumerate(pool):
            if row in selected:
                continue
            min_distance = min(
                normalized_distance(row["params"], chosen["params"], ranges)
                for chosen in selected
            )
            quality = 1.0 - rank / max(1, len(pool) - 1)
            value = 0.70 * quality + 0.30 * min_distance
            if value > best_value:
                best_value = value
                best = row
        if best is None:
            break
        selected.append(best)
    return selected


def main() -> None:
    rows = parse_rows()
    selected = shortlist(rows)
    selected_keys = {
        (item["source"], item["candidate_id"]): index + 1
        for index, item in enumerate(selected)
    }

    ranking_path = OUT / "offline_ranking.csv"
    fields = [
        "rank",
        "shortlist_slot",
        "source",
        "candidate_id",
        "stage",
        "parent",
        "selection_score",
        "cvar_score_low40",
        "cvar_delivery_low40",
        "cvar_sybil_high40",
        "dev_score_mean",
        "dev_score_std",
        "dev_delivery_mean",
        "dev_sybil_mean",
        "dev_sybil_max",
        "original_robust_score",
        "params",
    ]
    with ranking_path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        for rank, row in enumerate(rows, start=1):
            output = dict(row)
            output["rank"] = rank
            output["shortlist_slot"] = selected_keys.get(
                (row["source"], row["candidate_id"]), ""
            )
            output["params"] = json.dumps(row["params"], sort_keys=True)
            writer.writerow(output)

    shortlist_data: list[dict] = []
    for slot, row in enumerate(selected, start=1):
        profile = {
            "name": f"aegis-cvar-candidate-{slot}",
            "objective": (
                "offline dev-only CVaR selection; official B_dev remains unchanged"
            ),
            "params": row["params"],
            "source_run": row["source"],
            "source_candidate_id": row["candidate_id"],
            "selection_metrics": {
                key: row[key]
                for key in (
                    "selection_score",
                    "cvar_score_low40",
                    "cvar_delivery_low40",
                    "cvar_sybil_high40",
                    "dev_score_mean",
                    "dev_score_std",
                    "dev_delivery_mean",
                    "dev_sybil_mean",
                    "dev_sybil_max",
                )
            },
        }
        path = OUT / "candidates" / f"candidate-{slot}.json"
        path.write_text(json.dumps(profile, indent=2) + "\n", encoding="utf-8")
        shortlist_data.append(
            {
                "slot": slot,
                "profile": str(path.relative_to(ROOT)),
                **{key: value for key, value in row.items() if key != "params"},
                "params": row["params"],
            }
        )

    (OUT / "shortlist.json").write_text(
        json.dumps(shortlist_data, indent=2) + "\n", encoding="utf-8"
    )
    print(
        json.dumps(
            {
                "ranked_candidates": len(rows),
                "shortlist": shortlist_data,
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
