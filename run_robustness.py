"""Evaluate the existing network and re-optimise it under both scenarios.

Usage examples
--------------
python run_robustness.py --base results/milp_104.json --candidates 104
python run_robustness.py --base results/milp_104.json --depot-search

The script writes one JSON file per scenario and a combined summary.  The
``--depot-search`` option additionally rebuilds the analytical baseline on the
scenario data and uses its depot for the MILP; this tests whether a different
central warehouse would have been better.
"""
from __future__ import annotations

import argparse
import json
import time
from pathlib import Path

from scm.analysis import scenario_breakdown
from scm.baseline import build_baseline
from scm.data import load_data
from scm.io import load_network, same_network, save_json
from scm.milp import solve_milp
from scm.network import Network
from scm.routes_pool import Route, generate_pool
from scm.scenarios import SCENARIOS, apply_scenario


def _load_scenario_network(path: str | Path) -> Network:
    """Load a scenario result as a feasible warm-start network."""
    raw = json.loads(Path(path).read_text())
    if "network" in raw:
        from scm.io import network_from_dict

        return network_from_dict(raw["network"])
    return Network(
        depot=int(raw["optimized_depot"]),
        satellites={int(s) for s in raw["optimized_satellites"]},
        stores={int(i) for i in raw["optimized_stores"]},
        assignment={
            int(k): int(v) for k, v in raw["optimized_assignment"].items()
        },
        routes={
            int(w): [[int(i) for i in r] for r in routes]
            for w, routes in raw["optimized_routes"].items()
        },
    )


def _merge_pools(*pools: list[Route]) -> list[Route]:
    """Keep the cheapest route for every (warehouse, store set) pair."""
    best: dict[tuple[int, frozenset[int]], Route] = {}
    for pool in pools:
        for route in pool:
            key = (route.warehouse, frozenset(route.stores))
            old = best.get(key)
            if old is None or route.cost < old.cost:
                best[key] = route
    return list(best.values())


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", default="results/milp_104.json", help="base result JSON")
    ap.add_argument("--candidates", type=int, default=104, help="fallback candidate count")
    ap.add_argument("--pair-threshold", type=float, default=100.0, help="max distance for extra two-store routes")
    ap.add_argument("--time-limit", type=float, default=600.0, help="HiGHS time limit per scenario")
    ap.add_argument("--mip-gap", type=float, default=0.0, help="relative MIP gap tolerance")
    ap.add_argument("--out-dir", default="results", help="output directory")
    ap.add_argument(
        "--only",
        choices=[s.name for s in SCENARIOS],
        default=None,
        help="run only one scenario (default: both)",
    )
    ap.add_argument(
        "--initial-dir",
        default=None,
        help="directory with scenario-specific warm-start result JSONs",
    )
    ap.add_argument(
        "--depot-search",
        action="store_true",
        help="rebuild the analytical baseline on the scenario data and test its depot",
    )
    args = ap.parse_args()

    data = load_data("Projektdateien")
    raw = json.loads(Path(args.base).read_text())
    base_net = load_network(args.base)
    base_candidates = [int(w) for w in raw.get("candidates", [])]
    if not base_candidates:
        from run_milp import select_candidates

        base_candidates = select_candidates(data, base_net.depot, args.candidates)

    print(f"base network: depot={base_net.depot}, satellites={sorted(base_net.satellites)}")
    print(f"base candidates: {len(base_candidates)}")
    t0 = time.perf_counter()
    print("route pool will be rebuilt for every scenario")

    summary: dict[str, dict[str, object]] = {}
    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    for scenario in SCENARIOS:
        if args.only is not None and scenario.name != args.only:
            continue
        print(f"\n=== {scenario.label} ===")
        sdata = apply_scenario(data, scenario)
        existing = scenario_breakdown(sdata, base_net)
        print(
            f"existing network: profit={existing['profit']/1e6:.4f} M EUR, "
            f"stores={existing['n_stores']:.0f}, satellites={existing['n_satellites']:.0f}"
        )

        depot = base_net.depot
        baseline_result = None
        if args.depot_search:
            t = time.perf_counter()
            baseline_net, baseline_result = build_baseline(sdata)
            depot = baseline_net.depot
            print(
                f"analytical baseline: depot={depot}, profit={baseline_result['profit']/1e6:.4f} M EUR "
                f"({time.perf_counter()-t:.1f}s)"
            )

        t = time.perf_counter()
        pool = generate_pool(
            sdata,
            sorted(set(base_candidates) | {depot}),
            pair_threshold_km=args.pair_threshold,
        )
        if depot not in {r.warehouse for r in pool}:
            pool = _merge_pools(
                pool,
                generate_pool(
                    sdata,
                    [depot],
                    pair_threshold_km=args.pair_threshold,
                ),
            )
        print(f"scenario pool: {len(pool)} routes ({time.perf_counter()-t:.1f}s)")

        initial = base_net
        initial_profit = scenario_breakdown(sdata, initial)["profit"]
        if args.initial_dir:
            warm = Path(args.initial_dir) / f"robustness_{scenario.name}.json"
            if warm.exists():
                candidate = _load_scenario_network(warm)
                candidate_profit = scenario_breakdown(sdata, candidate)["profit"]
                if candidate_profit > initial_profit:
                    initial = candidate
                    initial_profit = candidate_profit
                    print(f"warm start: {warm} ({candidate_profit/1e6:.4f} M EUR)", flush=True)
        result = solve_milp(
            sdata,
            pool,
            depot,
            time_limit=args.time_limit,
            mip_gap=args.mip_gap,
            verbose=True,
            initial=initial,
        )
        print(
            f"re-optimised: profit={result.breakdown['profit']/1e6:.4f} M EUR, "
            f"stores={len(result.network.stores)}, "
            f"satellites={sorted(result.network.satellites)}, "
            f"status={result.status}, gap={result.mip_gap:.2%}, "
            f"runtime={result.runtime_s:.1f}s"
        )
        identical = same_network(base_net, result.network)
        print(f"network identical to base: {identical}")

        payload: dict[str, object] = {
            "scenario": scenario.name,
            "gross_multiplier": scenario.gross_multiplier,
            "km_multiplier": scenario.km_multiplier,
            "existing_breakdown": existing,
            "existing_depot": base_net.depot,
            "optimized_depot": result.network.depot,
            "optimized_breakdown": result.breakdown,
            "optimized_satellites": sorted(result.network.satellites),
            "optimized_stores": sorted(result.network.stores),
            "optimized_assignment": {
                str(k): v for k, v in sorted(result.network.assignment.items())
            },
            "optimized_routes": {
                str(w): routes for w, routes in sorted(result.network.routes.items())
            },
            "network_identical": identical,
            "mip_gap": result.mip_gap,
            "status": result.status,
            "runtime_s": result.runtime_s,
            "n_routes_pool": result.n_routes,
        }
        if baseline_result is not None:
            payload["analytical_baseline_breakdown"] = baseline_result
            payload["analytical_baseline_depot"] = depot
        save_json(out_dir / f"robustness_{scenario.name}.json", payload)

        summary[scenario.name] = {
            "existing_profit": existing["profit"],
            "optimized_profit": result.breakdown["profit"],
            "delta": result.breakdown["profit"] - existing["profit"],
            "existing_stores": existing["n_stores"],
            "optimized_stores": len(result.network.stores),
            "existing_satellites": existing["n_satellites"],
            "optimized_satellites": len(result.network.satellites),
            "existing_depot": base_net.depot,
            "optimized_depot": result.network.depot,
            "network_identical": identical,
            "mip_gap": result.mip_gap,
            "status": result.status,
            "runtime_s": result.runtime_s,
            "n_routes_pool": result.n_routes,
            "candidate_count": len(base_candidates),
        }

    save_json(out_dir / "robustness_summary.json", summary)
    print(f"\nsummary saved to {out_dir / 'robustness_summary.json'}")
    print(f"total elapsed: {time.perf_counter()-t0:.1f}s")


if __name__ == "__main__":
    main()
