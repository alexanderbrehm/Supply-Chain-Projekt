"""Run the candidate-complete relaxed-route proof for an arbitrary depot."""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from scm.data import WEEKS_PER_YEAR, load_data
from scm.io import load_network
from scm.milp import solve_milp
from scm.routes_pool import generate_pool

OUT = Path(__file__).resolve().parent


def frontier(data, depot):
    regions = [int(w) for w in data.region_ids]
    stores = data.stores
    p = data.params
    distances = np.array([[data.d(w, i) for i in stores] for w in regions])
    satellite = np.array([data.satellite_cost(w) for w in regions])
    truck = WEEKS_PER_YEAR * p["lkw_lieferungen_pro_woche_pro_zwischenlager"] * (
        p["lkw_fixkosten_pro_fahrt"]
        + p["lkw_kosten_pro_km"] * 2.0 * np.array([data.d(depot, w) for w in regions])
    )
    fixed = satellite + truck
    dominated = np.zeros(len(regions), dtype=bool)
    for v in range(len(regions)):
        cand = np.where(fixed <= fixed[v] + 1e-9)[0]
        cand = cand[cand != v]
        if len(cand) == 0:
            continue
        le = np.all(distances[cand] <= distances[v] + 1e-9, axis=1)
        strict = (
            np.any(distances[cand] < distances[v] - 1e-9, axis=1)
            | (fixed[cand] < fixed[v] - 1e-9)
        )
        if np.any(le & strict):
            dominated[v] = True
    return [regions[i] for i in range(len(regions)) if not dominated[i]]


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--depot", type=int, required=True)
    ap.add_argument("--time-limit", type=float, default=900.0)
    ap.add_argument("--out", default=None)
    ap.add_argument("--initial", default=None)
    ap.add_argument("--jitter", type=int, default=0)
    args = ap.parse_args()
    data = load_data("Projektdateien")
    cands = frontier(data, args.depot)
    print(f"depot={args.depot}, frontier={len(cands)}", flush=True)
    pool = generate_pool(data, cands, pair_threshold_km=100.0, jitter_runs=args.jitter, verbose=True)
    print(f"pool={len(pool)}", flush=True)
    t0 = time.perf_counter()
    initial = load_network(args.initial) if args.initial else None
    result = solve_milp(
        data,
        pool,
        args.depot,
        time_limit=args.time_limit,
        verbose=True,
        initial=initial,
        relax_lambda=True,
        solution_file=str(OUT / f"depot_{args.depot}_long.sol"),
    )
    payload = {
        "depot": args.depot,
        "n_candidates": len(cands),
        "n_routes_pool": len(pool),
        "upper_bound": result.objective,
        "status": result.status,
        "gap": result.mip_gap,
        "runtime_s": result.runtime_s,
        "total_elapsed_s": time.perf_counter() - t0,
    }
    out = args.out or str(OUT / f"depot_{args.depot}.json")
    Path(out).write_text(json.dumps(payload, indent=2))
    print(json.dumps(payload, indent=2), flush=True)


if __name__ == "__main__":
    main()
