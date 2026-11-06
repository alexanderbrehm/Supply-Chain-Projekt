"""Reproduce the candidate-complete 640-warehouse optimality certificate.

The script solves the route-pool model with continuous route multiplicities
(``lambda``) but binary store, warehouse and assignment decisions, writes the
HiGHS solution file, verifies that the optimal solution is integral, rebuilds
the network and saves the result JSON.
"""
from __future__ import annotations

import argparse
import json
from collections import Counter
from pathlib import Path

from scm.data import load_data
from scm.io import load_network, network_to_dict
from scm.milp import solve_milp
from scm.network import Network, evaluate
from scm.routes_pool import generate_pool
from scm.routing import tsp_exact, two_opt

DEPOT = 379


def read_solution(path: Path) -> dict[str, float]:
    values: dict[str, float] = {}
    in_columns = False
    for line in path.read_text().splitlines():
        if line.startswith("# Columns"):
            in_columns = True
            continue
        if line.startswith("# Rows"):
            break
        if in_columns and line.strip():
            parts = line.split()
            if len(parts) == 2:
                values[parts[0]] = float(parts[1])
    return values


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--candidates", default="results/candidates_640.json")
    ap.add_argument("--initial", default="results/milp_200.json")
    ap.add_argument("--time-limit", type=float, default=900.0)
    ap.add_argument("--solution-file", default="results/milp_640.sol")
    ap.add_argument("--out", default="results/milp_640.json")
    args = ap.parse_args()

    data = load_data("Projektdateien")
    raw = json.loads(Path(args.candidates).read_text())
    candidates = [int(w) for w in raw.get("frontier", raw.get("candidates", []))]
    if not candidates:
        raise SystemExit("candidate file contains no candidates")

    pool = generate_pool(data, candidates, pair_threshold_km=100.0, verbose=True)
    print(f"route pool: {len(pool)} routes", flush=True)
    initial = load_network(args.initial)
    result = solve_milp(
        data,
        pool,
        DEPOT,
        time_limit=args.time_limit,
        verbose=True,
        initial=initial,
        relax_lambda=True,
        solution_file=args.solution_file,
    )
    if result.status != "kOptimal" or result.mip_gap > 1e-9:
        raise SystemExit(
            f"proof run is not optimal: status={result.status}, gap={result.mip_gap}"
        )

    values = read_solution(Path(args.solution_file))
    fractional = [
        name
        for name, value in values.items()
        if name.startswith(("y_", "z_", "a_", "lam_"))
        and abs(value - round(value)) > 1e-6
    ]
    if fractional:
        raise SystemExit(
            f"optimal relaxed solution is not integral ({len(fractional)} columns)"
        )

    stores = {i for i in data.stores if values.get(f"y_{i}", 0.0) > 0.5}
    satellites = {
        w for w in candidates if w != DEPOT and values.get(f"z_{w}", 0.0) > 0.5
    }
    assignment = {}
    for i in stores:
        ws = [w for w in candidates if values.get(f"a_{i}_{w}", 0.0) > 0.5]
        if len(ws) != 1:
            raise SystemExit(f"store {i} has {len(ws)} assignments")
        assignment[i] = ws[0]

    routes: dict[int, list[list[int]]] = {w: [] for w in {DEPOT} | satellites}
    selected = 0
    for idx, route in enumerate(pool):
        mult = int(round(values.get(f"lam_{idx}", 0.0)))
        if mult <= 0:
            continue
        if route.warehouse not in routes:
            raise SystemExit(f"selected route from closed warehouse {route.warehouse}")
        order = (
            tsp_exact(data, route.warehouse, list(route.stores))
            if len(route.stores) <= 13
            else two_opt(data, route.warehouse, list(route.stores))
        )
        for _ in range(mult):
            routes[route.warehouse].append(list(order))
        selected += mult

    net = Network(
        depot=DEPOT,
        satellites=satellites,
        stores=stores,
        assignment=assignment,
        routes=routes,
    )
    breakdown = evaluate(data, net)
    if abs(breakdown["profit"] - result.objective) > 1e-5:
        raise SystemExit(
            f"extracted network does not match the bound: "
            f"{breakdown['profit']} vs {result.objective}"
        )

    sizes = dict(sorted(Counter(len(r) for rs in routes.values() for r in rs).items()))
    n_patterns = len(
        {(w, frozenset(route)) for w, rs in routes.items() for route in rs}
    )
    payload = {
        "depot": DEPOT,
        "satellites": sorted(satellites),
        "candidates": sorted(candidates),
        "candidate_selection": {
            "method": "Pareto frontier of satellite+truck cost and all store distances; dominated regions excluded with verified dominance chains",
            "n_total": len(candidates),
            "n_dominated": int(raw.get("n_dominated", 31)),
        },
        "stores": sorted(stores),
        "assignment": {str(k): v for k, v in sorted(assignment.items())},
        "routes": {str(w): rs for w, rs in sorted(routes.items())},
        "breakdown": breakdown,
        "objective": result.objective,
        "mip_gap": result.mip_gap,
        "status": result.status,
        "runtime_s": result.runtime_s,
        "n_routes_pool": result.n_routes,
        "n_variables": result.n_variables,
        "n_constraints": result.n_constraints,
        "route_size_distribution": sizes,
        "n_patterns": n_patterns,
        "solver": "HiGHS 1.15.1 (highspy)",
        "visits_per_week": 3,
        "weeks_per_year": 52,
        "certificate": (
            "The relaxed model's optimal value equals the integral extracted "
            "network; therefore this is the integer optimum for the "
            "640-candidate / route-pool model."
        ),
        "proof_model": "relax_lambda=True: binary y/z/a, continuous lambda; optimum integral",
        "source": args.solution_file,
    }
    Path(args.out).write_text(json.dumps(payload, indent=2))
    print(f"profit={breakdown['profit']:.6f} EUR", flush=True)
    print(f"stores={len(stores)}, satellites={sorted(satellites)}, trips={selected}", flush=True)
    print(f"saved {args.out}", flush=True)


if __name__ == "__main__":
    main()
