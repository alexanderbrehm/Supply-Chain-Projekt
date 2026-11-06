"""Build a provably candidate-complete warehouse set for a fixed depot.

A potential satellite ``w`` is *dominated* by ``w'`` if

* ``satellite_cost(w') + truck_cost(depot, w') <= satellite_cost(w) + truck_cost(depot, w)``
  and
* ``d(w', i) <= d(w, i)`` for every potential store ``i``.

Then any route from ``w`` can be driven from ``w'`` with no larger distance,
and opening ``w'`` is no more expensive than opening ``w``.  Replacing a
dominated warehouse therefore never worsens the objective.  The Pareto
frontier of this relation is candidate-complete: every excluded warehouse has
a chain of dominators ending in the frontier.

The script writes ``candidates_640.json`` and verifies the chain property.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from scm.data import WEEKS_PER_YEAR, load_data

OUT = Path(__file__).resolve().parent
DEPOT = 379


def build() -> dict:
    data = load_data("Projektdateien")
    regions = [int(w) for w in data.region_ids]
    stores = data.stores
    p = data.params

    distances = np.array(
        [[data.d(w, i) for i in stores] for w in regions], dtype=float
    )
    satellite = np.array([data.satellite_cost(w) for w in regions], dtype=float)
    truck = WEEKS_PER_YEAR * p["lkw_lieferungen_pro_woche_pro_zwischenlager"] * (
        p["lkw_fixkosten_pro_fahrt"]
        + p["lkw_kosten_pro_km"] * 2.0 * np.array([data.d(DEPOT, w) for w in regions])
    )
    fixed = satellite + truck

    dominated = np.zeros(len(regions), dtype=bool)
    dominator = np.full(len(regions), -1, dtype=int)
    for v in range(len(regions)):
        candidates = np.where(fixed <= fixed[v] + 1e-9)[0]
        candidates = candidates[candidates != v]
        if len(candidates) == 0:
            continue
        no_farther = np.all(distances[candidates] <= distances[v] + 1e-9, axis=1)
        strict = (
            np.any(distances[candidates] < distances[v] - 1e-9, axis=1)
            | (fixed[candidates] < fixed[v] - 1e-9)
        )
        valid = candidates[no_farther & strict]
        if len(valid):
            dominated[v] = True
            dominator[v] = int(valid[np.argmin(fixed[valid])])

    frontier = [regions[i] for i in range(len(regions)) if not dominated[i]]
    frontier_set = set(frontier)

    # Verify that every dominated region has a dominance chain into the frontier.
    def chain_ends_in_frontier(start: int, limit: int = 100) -> bool:
        seen = set()
        v = start
        for _ in range(limit):
            if regions[v] in frontier_set:
                return True
            if dominator[v] < 0 or v in seen:
                return False
            seen.add(v)
            v = int(dominator[v])
        return False

    bad = [
        regions[i]
        for i in range(len(regions))
        if dominated[i] and not chain_ends_in_frontier(i)
    ]
    if bad:
        raise RuntimeError(f"dominance chains do not reach the frontier: {bad}")

    payload = {
        "depot": DEPOT,
        "method": (
            "Pareto frontier over (satellite+truck fixed cost, distances to all stores); "
            "every excluded warehouse has a dominance chain into this set."
        ),
        "n_regions": len(regions),
        "n_dominated": int(dominated.sum()),
        "n_frontier": len(frontier),
        "frontier": sorted(frontier),
        "dominated_examples": {
            str(regions[i]): regions[int(dominator[i])]
            for i in range(len(regions))
            if dominated[i]
        },
    }
    (OUT / "candidates_640.json").write_text(json.dumps(payload, indent=2))
    print(
        f"regions={len(regions)}, dominated={int(dominated.sum())}, "
        f"frontier={len(frontier)}, all chains verified"
    )
    return payload


if __name__ == "__main__":
    build()
