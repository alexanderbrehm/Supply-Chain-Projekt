"""Branch-and-price for the fixed six-warehouse set of the 640er network."""
from __future__ import annotations

import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from scm.data import load_data
from scm.milp import solve_milp
from scm.pricing import solve_pricing_dfs, solve_pricing_scip
from scm.routes_pool import Route, generate_pool
from scm.routing import route_cost, route_hours, route_km

OUT = Path(__file__).resolve().parent


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


def main() -> None:
    data = load_data("Projektdateien")
    raw = json.loads((ROOT / "results/milp_640.json").read_text())
    open_ws = [int(raw["depot"])] + [int(w) for w in raw["satellites"]]
    pool = generate_pool(data, open_ws, pair_threshold_km=100.0, verbose=False)
    print(f"fixed set={open_ws}, initial pool={len(pool)}", flush=True)

    added_total = 0
    for iteration in range(1, 11):
        t0 = time.perf_counter()
        lp = solve_milp(
            data, pool, 379, time_limit=300, verbose=False, relax_integrality=True
        )
        print(
            f"iteration {iteration}: LP={lp.objective:.4f}, pool={len(pool)}, "
            f"time={time.perf_counter()-t0:.1f}s",
            flush=True,
        )
        added = 0
        for w in open_ws:
            if w == 379:
                res = solve_pricing_dfs(
                    data, w, lp.cover_duals or {}, lp.link_duals or {},
                    (lp.open_duals or {}).get(w, 0.0),
                    time_limit=120, max_nodes=10_000_000,
                )
            else:
                res = solve_pricing_scip(
                    data, w, lp.cover_duals or {}, lp.link_duals or {},
                    (lp.open_duals or {}).get(w, 0.0),
                    time_limit=180, attractive_only=True,
                )
            print(
                f"  w={w}: {res.status}, rc={res.reduced_cost:.4f}, "
                f"sel={len(res.stores)}, order={res.order}, time={res.runtime_s:.1f}s",
                flush=True,
            )
            if res.reduced_cost > 1e-6 and res.order:
                if add_route(pool, data, w, res.order):
                    added += 1
        added_total += added
        if added == 0:
            print("no improving route found", flush=True)
            break

    t0 = time.perf_counter()
    integer = solve_milp(data, pool, 379, time_limit=600, verbose=False)
    print(
        f"integer: profit={integer.breakdown['profit']:.4f}, status={integer.status}, "
        f"gap={integer.mip_gap:.4%}, time={integer.runtime_s:.1f}s",
        flush=True,
    )
    payload = {
        "open_warehouses": open_ws,
        "added_routes": added_total,
        "final_pool": len(pool),
        "integer_profit": integer.breakdown["profit"],
        "integer_status": integer.status,
        "integer_gap": integer.mip_gap,
        "integer_runtime_s": integer.runtime_s,
        "integer_stores": sorted(integer.network.stores),
        "integer_satellites": sorted(integer.network.satellites),
        "integer_routes": {
            str(w): rs for w, rs in sorted(integer.network.routes.items())
        },
    }
    (OUT / "fixed_warehouse_bp.json").write_text(json.dumps(payload, indent=2))
    print(f"saved {OUT/'fixed_warehouse_bp.json'}", flush=True)


if __name__ == "__main__":
    main()
