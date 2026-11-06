"""Spatial candidate reduction: top-k nearest depots per store.

This is a heuristic candidate generator, not a proof.  It measures how much
the route pool and the fixed-depot optimum shrink when only spatially nearby
warehouse regions are considered.  The current reference satellites and depot
are optionally forced so the comparison is against the known network.
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from scm.data import load_data
from scm.milp import solve_milp
from scm.routes_pool import generate_pool

OUT = Path(__file__).resolve().parent
DEPOT = 379
REFERENCE_SATELLITES = [84, 122, 271, 419, 574]


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--k", type=int, default=5)
    ap.add_argument("--time-limit", type=float, default=900.0)
    ap.add_argument("--force-reference", action="store_true", default=True)
    ap.add_argument("--no-force-reference", action="store_true")
    args = ap.parse_args()

    data = load_data("Projektdateien")
    regions = [int(r) for r in data.region_ids]
    stores = data.stores
    dist = np.array([[data.d(w, i) for i in stores] for w in regions])
    union: set[int] = set()
    for j in range(len(stores)):
        nearest = np.argsort(dist[:, j])[: args.k]
        union.update(regions[int(idx)] for idx in nearest)
    force_reference = args.force_reference and not args.no_force_reference
    if force_reference:
        union.add(DEPOT)
        union.update(REFERENCE_SATELLITES)
    candidates = sorted(union)
    print(f"k={args.k}, candidates={len(candidates)}", flush=True)

    pool = generate_pool(
        data, candidates, pair_threshold_km=100.0, verbose=True
    )
    print(f"pool={len(pool)}", flush=True)
    t0 = time.perf_counter()
    result = solve_milp(
        data,
        pool,
        DEPOT,
        time_limit=args.time_limit,
        verbose=True,
        relax_lambda=True,
        solution_file=str(OUT / f"spatial_k{args.k}.sol"),
    )
    payload = {
        "k": args.k,
        "force_reference": force_reference,
        "n_candidates": len(candidates),
        "n_routes_pool": len(pool),
        "upper_bound": result.objective,
        "status": result.status,
        "gap": result.mip_gap,
        "runtime_s": result.runtime_s,
        "total_elapsed_s": time.perf_counter() - t0,
        "reference_profit": json.loads(
            (ROOT / "results/milp_640.json").read_text()
        )["breakdown"]["profit"],
    }
    (OUT / f"spatial_k{args.k}.json").write_text(json.dumps(payload, indent=2))
    print(json.dumps(payload, indent=2), flush=True)


if __name__ == "__main__":
    main()
