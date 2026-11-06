"""Run the route-pool MILP and save the result."""
from __future__ import annotations

import argparse
import json
from collections import Counter
from importlib.metadata import version
from pathlib import Path

from scm.data import load_data, WEEKS_PER_YEAR
from scm.io import load_network
from scm.milp import solve_milp
from scm.routes_pool import generate_pool


def select_candidates(data, depot: int, n: int = 200) -> list[int]:
    """Heuristic candidate list: regions with many nearby stores and low cost."""
    p = data.params
    scored = []
    for w in data.region_ids:
        w = int(w)
        near = [i for i in data.stores if data.d(w, i) <= 100.0]
        if not near:
            continue
        truck = WEEKS_PER_YEAR * p["lkw_lieferungen_pro_woche_pro_zwischenlager"] * (
            p["lkw_fixkosten_pro_fahrt"] + p["lkw_kosten_pro_km"] * 2.0 * data.d(depot, w)
        )
        score = sum(data.margin(i) for i in near) - data.satellite_cost(w) - truck
        scored.append((score, w))
    scored.sort(reverse=True)
    selected = [w for _, w in scored[:n]]
    for w in (depot, 81, 149, 274, 419, 582):
        if w not in selected:
            selected.append(w)
    return selected


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--depot", type=int, default=379, help="fixed depot region")
    ap.add_argument("--candidates", type=int, default=200, help="number of scored warehouse candidates")
    ap.add_argument("--time-limit", type=float, default=1800.0, help="HiGHS time limit in seconds")
    ap.add_argument("--pair-threshold", type=float, default=100.0, help="max distance for extra two-store routes")
    ap.add_argument("--jitter", type=int, default=0, help="number of randomised savings passes")
    ap.add_argument("--initial", default=None, help="JSON result/network for a MIP warm start")
    ap.add_argument("--out", default="results/milp", help="output path without suffix")
    args = ap.parse_args()

    data = load_data("Projektdateien")
    candidates = select_candidates(data, args.depot, args.candidates)
    print(f"depot={args.depot}, candidate warehouses={len(candidates)}")
    pool = generate_pool(
        data,
        candidates,
        pair_threshold_km=args.pair_threshold,
        jitter_runs=args.jitter,
        verbose=True,
    )
    print(f"route pool: {len(pool)} routes")
    initial = load_network(args.initial) if args.initial else None
    result = solve_milp(
        data,
        pool,
        args.depot,
        time_limit=args.time_limit,
        verbose=True,
        initial=initial,
    )
    net = result.network
    sizes = Counter(len(r) for routes in net.routes.values() for r in routes)
    print(f"profit={result.breakdown['profit']/1e6:.4f} M EUR")
    print(f"stores={len(net.stores)}, satellites={sorted(net.satellites)}")
    print(f"route size distribution: {dict(sorted(sizes.items()))}")

    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    summary = {
        "depot": net.depot,
        "satellites": sorted(net.satellites),
        "candidates": sorted(int(w) for w in candidates),
        "candidate_selection": {
            "top_n": args.candidates,
            "forced": [args.depot, 81, 149, 274, 419, 582],
            "n_total": len(candidates),
        },
        "stores": sorted(net.stores),
        "assignment": {str(k): v for k, v in sorted(net.assignment.items())},
        "routes": {str(w): routes for w, routes in sorted(net.routes.items())},
        "breakdown": result.breakdown,
        "objective": result.objective,
        "mip_gap": result.mip_gap,
        "status": result.status,
        "runtime_s": result.runtime_s,
        "n_routes_pool": result.n_routes,
        "n_variables": result.n_variables,
        "n_constraints": result.n_constraints,
        "route_size_distribution": dict(sorted(sizes.items())),
        "solver": f"HiGHS {version('highspy')} (highspy)",
        "visits_per_week": int(round(data.params["transporter_lieferungen_pro_woche_pro_markt"])),
        "weeks_per_year": WEEKS_PER_YEAR,
    }
    out.with_suffix(".json").write_text(json.dumps(summary, indent=2))
    print(f"saved {out.with_suffix('.json')}")


if __name__ == "__main__":
    main()
