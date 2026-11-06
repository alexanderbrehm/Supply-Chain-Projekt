"""Compute a relaxed-route upper bound for a fixed depot and candidate set.

The route multiplicities ``lambda`` are continuous, while store, warehouse and
assignment decisions stay binary.  The resulting MIP dual bound is a valid
upper bound for the integer problem and can be tighter than the full LP bound.
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from scm.data import load_data
from scm.io import load_network
from scm.milp import solve_milp
from scm.routes_pool import generate_pool

OUT = Path(__file__).resolve().parent


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--candidates", required=True, help="result JSON with candidates")
    ap.add_argument("--depot", type=int, default=379)
    ap.add_argument("--jitter", type=int, default=0, help="randomised savings passes")
    ap.add_argument("--time-limit", type=float, default=900.0)
    ap.add_argument("--initial", default=None, help="optional warm-start network")
    ap.add_argument("--solution-file", default=None, help="optional HiGHS solution file")
    ap.add_argument("--out", default="relaxed_bound.json")
    args = ap.parse_args()

    data = load_data("Projektdateien")
    raw = json.loads(Path(args.candidates).read_text())
    candidates = [int(w) for w in raw.get("candidates", raw.get("frontier", []))]
    print(f"candidates={len(candidates)}", flush=True)

    t0 = time.perf_counter()
    pool = generate_pool(data, candidates, pair_threshold_km=100.0, jitter_runs=args.jitter, verbose=True)
    print(f"pool={len(pool)} ({time.perf_counter()-t0:.1f}s)", flush=True)

    initial = load_network(args.initial) if args.initial else None
    t0 = time.perf_counter()
    result = solve_milp(
        data,
        pool,
        args.depot,
        time_limit=args.time_limit,
        verbose=True,
        initial=initial,
        relax_lambda=True,
        solution_file=args.solution_file,
    )
    payload = {
        "candidates_file": args.candidates,
        "n_candidates": len(candidates),
        "depot": args.depot,
        "upper_bound": result.objective,
        "status": result.status,
        "mip_gap": result.mip_gap,
        "runtime_s": result.runtime_s,
        "n_routes_pool": result.n_routes,
        "n_variables": result.n_variables,
        "n_constraints": result.n_constraints,
        "bound_is_dual": result.bound_is_dual,
    }
    (OUT / args.out).write_text(json.dumps(payload, indent=2))
    print(json.dumps(payload, indent=2), flush=True)


if __name__ == "__main__":
    main()
