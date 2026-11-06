"""Branch-and-price node for the fixed assignment of the 640er reference.

The open warehouses and store assignments are fixed.  The master is a small
set-partitioning LP over routes for those warehouses; exact pricing adds
routes with negative reduced cost.  When no such route exists and the LP
solution is integral, the routing of the fixed network is proven optimal.
"""
from __future__ import annotations

import json
import sys
import time
from pathlib import Path

import highspy

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from scm.data import load_data
from scm.pricing import PricingResult, solve_pricing_dfs, solve_pricing_scip
from scm.routes_pool import Route, generate_pool
from scm.routing import route_cost, route_hours, route_km

OUT = Path(__file__).resolve().parent
WEEKS = 52.0
DEPOT = 379


def build_initial_pool(data, routes, assignment, open_ws):
    pool = []
    seen = set()
    for r in routes:
        if r.warehouse not in open_ws:
            continue
        if any(assignment.get(i) != r.warehouse for i in r.stores):
            continue
        key = (r.warehouse, frozenset(r.stores))
        if key in seen:
            continue
        seen.add(key)
        pool.append(r)
    return pool


def solve_master(data, pool, assignment, time_limit=120):
    stores = sorted(assignment)
    h = highspy.Highs()
    h.setOptionValue("output_flag", False)
    h.setOptionValue("time_limit", float(time_limit))
    h.changeObjectiveSense(highspy.ObjSense.kMinimize)
    lam = [
        h.addVariable(0.0, highspy.kHighsInf, WEEKS * r.cost, highspy.HighsVarType.kContinuous, f"lam_{idx}")
        for idx, r in enumerate(pool)
    ]
    rows = {}
    for i in stores:
        idxs = [idx for idx, r in enumerate(pool) if i in r.stores]
        con = h.addConstr(sum((lam[idx] for idx in idxs), start=0) == 3)
        rows[i] = int(con.index)
    h.run()
    status = h.getModelStatus().name
    if status != "kOptimal":
        raise RuntimeError(f"master LP status {status}")
    info = h.getInfo()
    sol = h.getSolution()
    dual = {i: float(sol.row_dual[idx]) for i, idx in rows.items()}
    values = [float(sol.col_value[int(lam[idx])]) for idx in range(len(pool))]
    return float(info.objective_function_value), dual, values


def main() -> None:
    data = load_data("Projektdateien")
    raw = json.loads((ROOT / "results/milp_640.json").read_text())
    assignment = {int(k): int(v) for k, v in raw["assignment"].items()}
    open_ws = {DEPOT} | {int(w) for w in raw["satellites"]}
    candidates = [int(w) for w in raw["candidates"]]
    all_routes = generate_pool(data, candidates, pair_threshold_km=100.0, verbose=False)
    pool = build_initial_pool(data, all_routes, assignment, open_ws)
    print(f"initial fixed-network pool: {len(pool)} routes", flush=True)

    new_routes: list[tuple[int, tuple[int, ...], float]] = []
    iteration = 0
    while True:
        iteration += 1
        t0 = time.perf_counter()
        master_obj, dual, values = solve_master(data, pool, assignment)
        print(
            f"iteration {iteration}: master={master_obj:.4f}, "
            f"pool={len(pool)}, time={time.perf_counter()-t0:.1f}s",
            flush=True,
        )
        added = 0
        for w in sorted(open_ws):
            allowed = {i: dual[i] for i in assignment if assignment[i] == w}
            # Use SCIP on medium sets, DFS on the small depot / small sets.
            if len(allowed) <= 5:
                res = solve_pricing_dfs(
                    data, w, allowed, {}, 0.0, time_limit=120,
                    max_nodes=5_000_000,
                )
            else:
                res = solve_pricing_scip(
                    data, w, allowed, {}, 0.0, time_limit=180,
                    attractive_only=True,
                )
            print(
                f"  w={w}: {res.status}, rc={res.reduced_cost:.4f}, "
                f"n={res.n_stores}, sel={len(res.stores)}, time={res.runtime_s:.1f}s",
                flush=True,
            )
            if res.reduced_cost > 1e-6 and res.order:
                key = (w, frozenset(res.stores))
                if all((r.warehouse, frozenset(r.stores)) != key for r in pool):
                    pool.append(
                        Route(
                            warehouse=w,
                            stores=tuple(sorted(res.stores)),
                            cost=route_cost(data, w, list(res.order)),
                            km=route_km(data, w, list(res.order)),
                            hours=route_hours(data, w, list(res.order)),
                        )
                    )
                    new_routes.append((w, tuple(res.order), res.reduced_cost))
                    added += 1
        if added == 0:
            print("no negative-reduced-cost route found", flush=True)
            break
        if iteration >= 5:
            print("iteration limit reached", flush=True)
            break

    master_obj, dual, values = solve_master(data, pool, assignment)
    fractional = sum(1 for v in values if abs(v - round(v)) > 1e-6)
    print(f"final master={master_obj:.4f}, fractional lambda={fractional}", flush=True)
    payload = {
        "iteration_count": iteration,
        "initial_routes": len(pool) - len(new_routes),
        "new_routes": [
            {"warehouse": w, "order": list(o), "rc": rc} for w, o, rc in new_routes
        ],
        "final_routes": len(pool),
        "final_master_objective": master_obj,
        "fractional_lambda": fractional,
        "current_transporter_cost": raw["breakdown"]["transporter_costs"],
    }
    (OUT / "fixed_network_bp.json").write_text(json.dumps(payload, indent=2))
    print(f"saved {OUT/'fixed_network_bp.json'}", flush=True)


if __name__ == "__main__":
    main()
