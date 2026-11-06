"""Branch-and-price for the fixed open six-warehouse set (no z/open duals)."""
from __future__ import annotations

import json
import sys
import time
from pathlib import Path

import highspy
import numpy as np

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from scm.data import WEEKS_PER_YEAR, load_data
from scm.pricing import solve_pricing_dfs, solve_pricing_scip
from scm.routes_pool import Route, generate_pool
from scm.routing import route_cost, route_hours, route_km

OUT = Path(__file__).resolve().parent
DEPOT = 379
WEEKS = 52.0


def add_route(pool, data, w, order):
    key = (w, frozenset(order))
    if any((r.warehouse, frozenset(r.stores)) == key for r in pool):
        return False
    pool.append(
        Route(
            warehouse=w,
            stores=tuple(sorted(order)),
            cost=route_cost(data, w, list(order)),
            km=route_km(data, w, list(order)),
            hours=route_hours(data, w, list(order)),
        )
    )
    return True


def fixed_costs(data, open_ws):
    p = data.params
    total = data.depot_cost(DEPOT)
    for w in open_ws:
        if w == DEPOT:
            continue
        truck = WEEKS_PER_YEAR * p["lkw_lieferungen_pro_woche_pro_zwischenlager"] * (
            p["lkw_fixkosten_pro_fahrt"]
            + p["lkw_kosten_pro_km"] * 2.0 * data.d(DEPOT, w)
        )
        total += data.satellite_cost(w) + truck
    return total


def solve_master(data, pool, open_ws, *, integer=False, time_limit=300):
    stores = data.stores
    h = highspy.Highs()
    h.setOptionValue("output_flag", False)
    h.setOptionValue("time_limit", float(time_limit))
    h.changeObjectiveSense(highspy.ObjSense.kMaximize)
    y = {i: h.addBinary(float(data.margin(i)), name=f"y_{i}") for i in stores}
    a = {
        (i, w): h.addBinary(0.0, name=f"a_{i}_{w}")
        for i in stores
        for w in open_ws
    }
    lam = {
        idx: h.addIntegral(0.0, 3.0, -WEEKS * r.cost, f"lam_{idx}")
        for idx, r in enumerate(pool)
    }
    cover_rows = {}
    assign_rows = {}
    link_rows = {}
    for i in stores:
        idxs = [idx for idx, r in enumerate(pool) if i in r.stores]
        con = h.addConstr(sum((lam[idx] for idx in idxs), start=0) - 3 * y[i] == 0)
        cover_rows[i] = int(con.index)
        con = h.addConstr(sum(a[(i, w)] for w in open_ws) - y[i] == 0)
        assign_rows[i] = int(con.index)
    for i in stores:
        for w in open_ws:
            idxs = [
                idx
                for idx, r in enumerate(pool)
                if r.warehouse == w and i in r.stores
            ]
            con = h.addConstr(
                sum((lam[idx] for idx in idxs), start=0) - 3 * a[(i, w)] <= 0
            )
            link_rows[(i, w)] = int(con.index)
    if integer:
        h.setOptionValue("mip_rel_gap", 0.0)
    else:
        # Relax y/a/lambda to continuous after construction.
        n = h.getNumCol()
        h.changeColsIntegrality(
            n,
            np.arange(n, dtype=np.int32),
            np.full(n, int(highspy.HighsVarType.kContinuous), dtype=np.uint8),
        )
    h.run()
    status = h.getModelStatus().name
    sol = h.getSolution()
    info = h.getInfo()
    if not getattr(sol, "value_valid", False):
        raise RuntimeError(f"fixed-open master status {status}")
    duals = None
    if not integer:
        duals = {
            "cover": {i: float(sol.row_dual[idx]) for i, idx in cover_rows.items()},
            "assign": {i: float(sol.row_dual[idx]) for i, idx in assign_rows.items()},
            "link": {k: float(sol.row_dual[idx]) for k, idx in link_rows.items()},
        }
    values = {
        "lambda": {idx: float(sol.col_value[int(lam[idx])]) for idx in range(len(pool))},
        "y": {i: float(sol.col_value[int(y[i])]) for i in stores},
        "a": {(i, w): float(sol.col_value[int(a[(i, w)])]) for i in stores for w in open_ws},
    }
    return float(info.objective_function_value), status, float(info.mip_gap), duals, values


def main() -> None:
    data = load_data("Projektdateien")
    raw = json.loads((ROOT / "results/milp_640.json").read_text())
    open_ws = [int(raw["depot"])] + [int(w) for w in raw["satellites"]]
    pool = generate_pool(data, open_ws, pair_threshold_km=100.0, verbose=False)
    print(f"fixed open set={open_ws}, pool={len(pool)}", flush=True)

    added_total = 0
    for iteration in range(1, 11):
        t0 = time.perf_counter()
        obj, status, gap, duals, values = solve_master(data, pool, open_ws)
        print(
            f"iteration {iteration}: LP={obj:.4f}, status={status}, "
            f"pool={len(pool)}, time={time.perf_counter()-t0:.1f}s",
            flush=True,
        )
        assert duals is not None
        added = 0
        for w in open_ws:
            if w == DEPOT:
                res = solve_pricing_dfs(
                    data, w, duals["cover"], duals["link"], 0.0,
                    time_limit=120, max_nodes=10_000_000,
                )
            else:
                res = solve_pricing_scip(
                    data, w, duals["cover"], duals["link"], 0.0,
                    time_limit=180, attractive_only=True,
                )
            print(
                f"  w={w}: {res.status}, rc={res.reduced_cost:.4f}, "
                f"sel={len(res.stores)}, time={res.runtime_s:.1f}s",
                flush=True,
            )
            if res.reduced_cost > 1e-6 and res.order:
                if add_route(pool, data, w, res.order):
                    added += 1
        added_total += added
        if added == 0:
            print("no improving route found", flush=True)
            break

    obj, status, gap, duals, values = solve_master(data, pool, open_ws)
    frac = sum(
        1 for v in values["lambda"].values() if abs(v - round(v)) > 1e-6
    ) + sum(
        1 for v in values["y"].values() if abs(v - round(v)) > 1e-6
    ) + sum(
        1 for v in values["a"].values() if abs(v - round(v)) > 1e-6
    )
    fixed = fixed_costs(data, open_ws)
    print(f"final LP={obj:.4f}, fixed={fixed:.4f}, profit={obj-fixed:.4f}, frac={frac}", flush=True)
    payload = {
        "open_warehouses": open_ws,
        "added_routes": added_total,
        "final_pool": len(pool),
        "lp_objective": obj,
        "fixed_costs": fixed,
        "profit_lp": obj - fixed,
        "fractional_columns": frac,
        "current_profit": raw["breakdown"]["profit"],
    }
    (OUT / "fixed_open_bp.json").write_text(json.dumps(payload, indent=2))
    print(f"saved {OUT/'fixed_open_bp.json'}", flush=True)


if __name__ == "__main__":
    main()
