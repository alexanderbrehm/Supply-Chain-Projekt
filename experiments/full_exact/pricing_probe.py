"""Phase 1 probe: solve the 640-candidate master LP and test exact pricing."""
from __future__ import annotations

import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from scm.data import load_data
from scm.milp import solve_milp
from scm.pricing import solve_pricing_dfj
from scm.routes_pool import generate_pool

OUT = Path(__file__).resolve().parent
WAREHOUSES = [149, 122, 575, 84, 419, 271, 379]


def main() -> None:
    data = load_data("Projektdateien")
    raw = json.loads((ROOT / "results/milp_640.json").read_text())
    candidates = [int(w) for w in raw["candidates"]]

    t0 = time.perf_counter()
    pool = generate_pool(data, candidates, pair_threshold_km=100.0, verbose=True)
    print(f"pool={len(pool)} ({time.perf_counter()-t0:.1f}s)", flush=True)

    lp = solve_milp(
        data, pool, 379, time_limit=900, verbose=True, relax_integrality=True
    )
    print(
        f"LP={lp.objective:.6f}, runtime={lp.runtime_s:.1f}s, "
        f"duals={len(lp.cover_duals or {})}/{len(lp.link_duals or {})}",
        flush=True,
    )

    results = []
    for w in WAREHOUSES:
        print(f"pricing start {w}", flush=True)
        res = solve_pricing_dfj(
            data,
            w,
            lp.cover_duals or {},
            lp.link_duals or {},
            (lp.open_duals or {}).get(w, 0.0),
            time_limit=60.0,
            verbose=False,
        )
        item = {
            "warehouse": w,
            "status": res.status,
            "reduced_cost": res.reduced_cost,
            "objective": res.objective,
            "n_stores": res.n_stores,
            "n_selected": len(res.stores),
            "stores": list(res.stores),
            "order": list(res.order),
            "runtime_s": res.runtime_s,
            "mip_gap": res.mip_gap,
        }
        results.append(item)
        print(
            f"pricing {w}: {res.status}, rc={res.reduced_cost:.4f}, "
            f"selected={len(res.stores)}, runtime={res.runtime_s:.1f}s",
            flush=True,
        )

    payload = {
        "lp_bound": lp.objective,
        "lp_runtime_s": lp.runtime_s,
        "n_routes_pool": len(pool),
        "warehouses": results,
    }
    (OUT / "pricing_probe.json").write_text(json.dumps(payload, indent=2))
    print(f"saved {OUT/'pricing_probe.json'}", flush=True)


if __name__ == "__main__":
    main()
