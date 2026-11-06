"""One column-generation iteration: price selected warehouses and re-solve LP."""
from __future__ import annotations

import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from scm.data import load_data
from scm.milp import solve_milp
from scm.pricing import solve_pricing, solve_pricing_dfs, solve_pricing_scip
from scm.routes_pool import Route, generate_pool
from scm.routing import route_cost, route_hours, route_km

OUT = Path(__file__).resolve().parent
WAREHOUSES = [122, 575, 84, 419, 271, 379]


def main() -> None:
    data = load_data("Projektdateien")
    raw = json.loads((ROOT / "results/milp_640.json").read_text())
    candidates = [int(w) for w in raw["candidates"]]
    duals = json.loads((OUT / "duals_640.json").read_text())
    cover = {int(k): v for k, v in duals["cover"].items()}
    link = {tuple(map(int, k.split(","))): v for k, v in duals["link"].items()}
    open_ = {int(k): v for k, v in duals["open"].items()}

    pool = generate_pool(data, candidates, pair_threshold_km=100.0, verbose=False)
    print(f"initial pool={len(pool)}", flush=True)

    new_routes: list[tuple[int, tuple[int, ...], float, str, float]] = []
    for w in WAREHOUSES:
        if w == 379:
            res = solve_pricing_dfs(
                data, w, cover, link, open_.get(w, 0.0), time_limit=60
            )
        elif w == 271:
            res = solve_pricing_scip(
                data, w, cover, link, open_.get(w, 0.0), time_limit=300
            )
        else:
            res = solve_pricing_scip(
                data, w, cover, link, open_.get(w, 0.0), time_limit=90
            )
        print(
            f"{w}: {res.status}, rc={res.reduced_cost:.4f}, "
            f"stores={res.stores}, order={res.order}, time={res.runtime_s:.1f}s",
            flush=True,
        )
        if res.order and res.reduced_cost > 1e-6:
            new_routes.append(
                (w, tuple(res.order), res.reduced_cost, res.status, res.runtime_s)
            )

    keys = {(r.warehouse, frozenset(r.stores)) for r in pool}
    for w, order, rc, status, runtime in new_routes:
        key = (w, frozenset(order))
        if key in keys:
            continue
        pool.append(
            Route(
                warehouse=w,
                stores=tuple(sorted(order)),
                cost=route_cost(data, w, list(order)),
                km=route_km(data, w, list(order)),
                hours=route_hours(data, w, list(order)),
            )
        )
        keys.add(key)
    print(f"pool after adding={len(pool)} (added {len(pool)-159060})", flush=True)

    t0 = time.perf_counter()
    lp = solve_milp(
        data, pool, 379, time_limit=900, verbose=False, relax_integrality=True
    )
    print(
        f"LP={lp.objective:.6f}, runtime={lp.runtime_s:.1f}s, "
        f"total={time.perf_counter()-t0:.1f}s",
        flush=True,
    )
    (OUT / "column_gen_probe.json").write_text(
        json.dumps(
            {
                "new_routes": [
                    {"warehouse": w, "order": list(o), "rc": rc, "status": s, "runtime": t}
                    for w, o, rc, s, t in new_routes
                ],
                "pool_size": len(pool),
                "lp_objective": lp.objective,
                "lp_runtime_s": lp.runtime_s,
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
