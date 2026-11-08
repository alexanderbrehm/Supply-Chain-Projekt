"""Depot selection over all regions with LP bounds (exact for a route pool).

The route pool does not depend on the depot: a route belongs to a warehouse,
and the depot is just the one warehouse that is always open, has depot instead
of satellite costs and needs no truck shuttle.  One pool for *all* warehouses
therefore serves every depot, and only the objective coefficients and bounds
of the warehouse variables change between depots.

``depot_lp_bounds`` solves the LP relaxation of the strong set-partitioning
model (see ``scm.milp``) once per depot by re-using one HiGHS model.  Each LP
value is a valid upper bound on the profit of any network with that depot
whose routes are in the pool.  ``search_depots`` then solves the MILP for the
depots in descending bound order and stops as soon as the next bound cannot
beat the best network found.  The result is optimal over **all depots and all
warehouses** for the given route pool.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from time import perf_counter

import highspy
import numpy as np

from .data import Data, WEEKS_PER_YEAR
from .milp import MilpResult, solve_milp
from .routes_pool import Route


@dataclass
class DepotBound:
    depot: int
    bound: float
    n_fractional: int


@dataclass
class DepotSearchResult:
    best: MilpResult
    bounds: list[DepotBound]
    solved: list[dict[str, float]] = field(default_factory=list)
    unusable_depots: list[int] = field(default_factory=list)
    runtime_s: float = 0.0

    @property
    def certified(self) -> bool:
        """True if no unsolved depot has a bound above the best profit."""
        solved = {int(s["depot"]) for s in self.solved}
        best = self.best.breakdown["profit"]
        return self.best.mip_gap <= 1e-9 and all(
            b.bound <= best + 1e-6 or b.depot in solved for b in self.bounds
        ) and all(s["mip_gap"] <= 1e-9 for s in self.solved)


def truck_cost(data: Data, depot: int, warehouse: int) -> float:
    """Annual truck shuttle cost depot <-> satellite."""
    p = data.params
    return WEEKS_PER_YEAR * p["lkw_lieferungen_pro_woche_pro_zwischenlager"] * (
        p["lkw_fixkosten_pro_fahrt"] + p["lkw_kosten_pro_km"] * 2.0 * data.d(depot, warehouse)
    )


def depot_lp_bounds(
    data: Data,
    pool: list[Route],
    depots: list[int] | None = None,
    *,
    threads: int = 4,
    verbose: bool = False,
) -> tuple[list[DepotBound], list[int]]:
    """LP bound of the strong model for every depot.

    Returns the bounds (sorted descending) and the depots that have no route
    in the pool (they cannot serve any store and are never optimal unless no
    store is opened at all).
    """
    visits = int(round(data.params["transporter_lieferungen_pro_woche_pro_markt"]))
    stores = data.stores
    store_set = set(stores)
    pool = [r for r in pool if set(r.stores) <= store_set]
    warehouses = sorted({r.warehouse for r in pool})
    if depots is None:
        depots = [int(d) for d in data.region_ids]
    unusable = [d for d in depots if d not in set(warehouses)]
    depots = [d for d in depots if d in set(warehouses)]

    by_store: dict[int, list[int]] = {i: [] for i in stores}
    by_wh: dict[int, list[int]] = {w: [] for w in warehouses}
    by_store_wh: dict[tuple[int, int], list[int]] = {}
    for k, r in enumerate(pool):
        by_wh[r.warehouse].append(k)
        for i in r.stores:
            by_store[i].append(k)
            by_store_wh.setdefault((i, r.warehouse), []).append(k)

    h = highspy.Highs()
    h.setOptionValue("output_flag", False)
    h.setOptionValue("threads", int(threads))
    h.changeObjectiveSense(highspy.ObjSense.kMaximize)
    cont = highspy.HighsVarType.kContinuous
    y = {i: h.addVariable(0.0, 1.0, float(data.margin(i)), cont) for i in stores}
    z = {w: h.addVariable(0.0, 1.0, 0.0, cont) for w in warehouses}
    lam = [
        h.addVariable(0.0, float(visits), -WEEKS_PER_YEAR * r.cost, cont) for r in pool
    ]
    a = {key: h.addVariable(0.0, 1.0, 0.0, cont) for key in by_store_wh}
    whs_for_store: dict[int, list[int]] = {i: [] for i in stores}
    for i, w in by_store_wh:
        whs_for_store[i].append(w)

    for i in stores:
        h.addConstr(sum((lam[k] for k in by_store[i]), start=0) - visits * y[i] == 0)
        h.addConstr(sum((a[(i, w)] for w in whs_for_store[i]), start=0) - y[i] == 0)
    for (i, w), ks in by_store_wh.items():
        h.addConstr(sum((lam[k] for k in ks), start=0) - visits * a[(i, w)] <= 0)
        h.addConstr(a[(i, w)] - z[w] <= 0)
    for w in warehouses:
        m_w = visits * len({i for k in by_wh[w] for i in pool[k].stores})
        h.addConstr(sum((lam[k] for k in by_wh[w]), start=0) - m_w * z[w] <= 0)

    z_idx = np.array([int(z[w]) for w in warehouses], dtype=np.int32)
    sat_cost = np.array([data.satellite_cost(w) for w in warehouses], dtype=float)
    pos = {w: n for n, w in enumerate(warehouses)}

    bounds: list[DepotBound] = []
    t0 = perf_counter()
    for n, d in enumerate(depots):
        cost = -(sat_cost + np.array([truck_cost(data, d, w) for w in warehouses]))
        cost[pos[d]] = 0.0
        lower = np.zeros(len(warehouses))
        lower[pos[d]] = 1.0
        h.changeColsCost(len(z_idx), z_idx, cost)
        h.changeColsBounds(len(z_idx), z_idx, lower, np.ones(len(warehouses)))
        h.run()
        status = h.getModelStatus()
        if status != highspy.HighsModelStatus.kOptimal:
            raise RuntimeError(f"LP for depot {d} not optimal: {status.name}")
        value = float(h.getInfo().objective_function_value) - data.depot_cost(d)
        x = np.asarray(h.getSolution().col_value)
        n_frac = int(np.sum(np.abs(x - np.round(x)) > 1e-6))
        bounds.append(DepotBound(depot=int(d), bound=value, n_fractional=n_frac))
        if verbose and (n + 1) % 50 == 0:
            print(f"  LP bounds: {n+1}/{len(depots)} depots ({perf_counter()-t0:.0f}s)", flush=True)

    bounds.sort(key=lambda b: -b.bound)
    return bounds, unusable


def search_depots(
    data: Data,
    pool: list[Route],
    depots: list[int] | None = None,
    *,
    time_limit: float = 1800.0,
    threads: int = 4,
    verbose: bool = False,
) -> DepotSearchResult:
    """Find the best depot for *pool* with a bound-and-solve loop."""
    t0 = perf_counter()
    bounds, unusable = depot_lp_bounds(data, pool, depots, threads=threads, verbose=verbose)
    best: MilpResult | None = None
    solved: list[dict[str, float]] = []
    for b in bounds:
        if best is not None and b.bound <= best.breakdown["profit"] + 1e-6:
            break
        res = solve_milp(
            data, pool, b.depot, time_limit=time_limit, threads=threads, verbose=False
        )
        assert isinstance(res, MilpResult)
        solved.append(
            {
                "depot": b.depot,
                "lp_bound": b.bound,
                "profit": res.breakdown["profit"],
                "status": res.status,
                "mip_gap": res.mip_gap,
                "runtime_s": res.runtime_s,
            }
        )
        if verbose:
            print(
                f"  MILP depot {b.depot}: bound={b.bound:,.2f}, "
                f"profit={res.breakdown['profit']:,.2f}, {res.status}, {res.runtime_s:.1f}s",
                flush=True,
            )
        if best is None or res.breakdown["profit"] > best.breakdown["profit"]:
            best = res
    if best is None:
        raise RuntimeError("no usable depot")
    return DepotSearchResult(
        best=best,
        bounds=bounds,
        solved=solved,
        unusable_depots=unusable,
        runtime_s=perf_counter() - t0,
    )
