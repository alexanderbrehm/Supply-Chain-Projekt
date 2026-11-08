"""Joint depot and warehouse optimisation over all 671 regions.

1. Build one route pool for every region as warehouse (depot or satellite).
2. Solve the strong LP relaxation once per depot (valid upper bounds).
3. Solve the MILP for depots in descending bound order until no remaining
   bound can beat the best network.

The result is optimal over all depots and all warehouses for the route pool.

Usage:  .venv/bin/python run_depot_search.py
"""
from __future__ import annotations

import argparse
from collections import Counter
from importlib.metadata import version
from time import perf_counter

from scm.data import WEEKS_PER_YEAR, load_data
from scm.depot_search import search_depots
from scm.io import network_to_dict, save_json
from scm.routes_pool import generate_pool


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--pair-threshold", type=float, default=100.0, help="max distance for extra two-store routes")
    ap.add_argument("--time-limit", type=float, default=1800.0, help="HiGHS time limit per depot MILP")
    ap.add_argument("--threads", type=int, default=4)
    ap.add_argument("--out", default="results/milp_best.json")
    ap.add_argument("--bounds-out", default="results/depot_search.json")
    args = ap.parse_args()

    data = load_data("Projektdateien")
    regions = [int(r) for r in data.region_ids]
    t = perf_counter()
    pool = generate_pool(data, regions, pair_threshold_km=args.pair_threshold)
    pool_s = perf_counter() - t
    print(f"route pool: {len(pool)} routes for {len(regions)} warehouses ({pool_s:.1f}s)")

    res = search_depots(data, pool, regions, time_limit=args.time_limit, threads=args.threads, verbose=True)
    best = res.best
    net = best.network
    sizes = Counter(len(r) for routes in net.routes.values() for r in routes)
    n_patterns = len({(w, frozenset(r)) for w, routes in net.routes.items() for r in routes})
    profit = best.breakdown["profit"]
    above = [b for b in res.bounds if b.bound > profit + 1e-6]

    print(f"\nbest depot {net.depot}: profit={profit:,.2f} EUR, satellites={sorted(net.satellites)}")
    print(f"stores={len(net.stores)}, trips/week={best.breakdown['n_trips_per_week']}")
    print(f"depots solved exactly: {len(res.solved)}, certified over all depots: {res.certified}")
    print(f"total runtime {res.runtime_s + pool_s:.1f}s")

    summary = network_to_dict(net)
    summary.update(
        {
            "candidates": sorted({r.warehouse for r in pool}),
            "candidate_selection": {
                "method": "all regions as warehouse candidates; depot chosen by LP bounds + MILP",
                "n_total": len({r.warehouse for r in pool}),
            },
            "breakdown": best.breakdown,
            "objective": best.objective,
            "mip_gap": best.mip_gap,
            "status": best.status,
            "runtime_s": res.runtime_s + pool_s,
            "milp_runtime_s": best.runtime_s,
            "n_routes_pool": best.n_routes,
            "n_variables": best.n_variables,
            "n_constraints": best.n_constraints,
            "route_size_distribution": dict(sorted(sizes.items())),
            "n_patterns": n_patterns,
            "solver": f"HiGHS {version('highspy')} (highspy)",
            "visits_per_week": int(round(data.params["transporter_lieferungen_pro_woche_pro_markt"])),
            "weeks_per_year": WEEKS_PER_YEAR,
            "certificate": {
                "certified_over_all_depots": res.certified,
                "n_depots_bounded": len(res.bounds),
                "n_depots_solved": len(res.solved),
                "n_depots_with_bound_above_best": len(above),
                "unusable_depots": res.unusable_depots,
                "scope": "optimal for the generated route pool over all depots and warehouses",
            },
        }
    )
    save_json(args.out, summary)
    save_json(
        args.bounds_out,
        {
            "best_depot": net.depot,
            "best_profit": profit,
            "pool_size": len(pool),
            "runtime_s": res.runtime_s + pool_s,
            "solved": res.solved,
            "unusable_depots": res.unusable_depots,
            "bounds": [
                {"depot": b.depot, "lp_bound": b.bound, "n_fractional": b.n_fractional}
                for b in res.bounds
            ],
        },
    )
    print(f"saved {args.out} and {args.bounds_out}")


if __name__ == "__main__":
    main()
