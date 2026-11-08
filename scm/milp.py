"""Set-partitioning MILP for the location-routing problem (HiGHS).

The model is exact with respect to the supplied route pool.  It chooses
stores, satellites, store-to-warehouse assignments and weekly routes for a
**fixed depot**.  Every open store must be visited exactly
``transporter_lieferungen_pro_woche_pro_markt`` times per week; routes may
differ between visits.  The depot itself is selected in a preceding
enumeration step (see ``scm.baseline``), not inside this MILP.
"""
from __future__ import annotations

from dataclasses import dataclass
from time import perf_counter

import highspy
import numpy as np

from .data import Data, WEEKS_PER_YEAR
from .network import Network, evaluate
from .routes_pool import Route
from .routing import route_cost, route_hours, route_km, tsp_exact, two_opt


@dataclass
class MilpResult:
    network: Network
    breakdown: dict[str, float]
    objective: float
    mip_gap: float
    status: str
    runtime_s: float
    n_routes: int
    n_variables: int
    n_constraints: int


@dataclass
class LpResult:
    """LP relaxation or relaxed MIP bound (upper bound for maximisation)."""

    objective: float
    status: str
    runtime_s: float
    n_routes: int
    n_variables: int
    n_constraints: int
    mip_gap: float = 0.0
    bound_is_dual: bool = False
    cover_duals: dict[int, float] | None = None
    assign_duals: dict[int, float] | None = None
    link_duals: dict[tuple[int, int], float] | None = None
    open_duals: dict[int, float] | None = None


def solve_milp(
    data: Data,
    pool: list[Route],
    depot: int,
    *,
    time_limit: float = 1800.0,
    mip_gap: float = 0.0,
    threads: int = 4,
    verbose: bool = True,
    initial: Network | None = None,
    relax_integrality: bool = False,
    relax_lambda: bool = False,
    solution_file: str | None = None,
    strong_linking: bool = True,
) -> MilpResult | LpResult:
    """Solve the route-pool MILP for a fixed depot.

    With ``relax_integrality=True`` the same model is solved as an LP.  Its
    optimal value is a valid upper bound for the integer problem and is used
    for exact optimality certificates.  ``relax_lambda=True`` relaxes only the
    route multiplicities; the resulting MIP dual bound is also a valid upper
    bound, but usually much tighter than the full LP bound.

    If *initial* is a feasible network for the same depot, it is passed to
    HiGHS as a MIP start.  This is useful when a larger route pool contains an
    already known good solution.

    ``strong_linking=True`` (default) adds the disaggregated opening
    constraints ``a[i,w] <= z[w]``.  They are implied by the integer model and
    cut off no integer solution, but they replace the weak big-M link
    ``sum(lambda) <= M_w z[w]`` in the LP relaxation: the LP bound drops from
    about 3.16 to 2.40 M EUR on the 202-candidate pool, which equals the
    integer optimum.  ``False`` reproduces the original (weak) formulation.
    """
    t0 = perf_counter()
    stores = data.stores
    # A scenario can turn stores negative, so the pool may contain routes with
    # stores that are no longer part of the model.  Such routes can never be
    # used and are removed before the model is built.
    store_set = set(stores)
    pool = [r for r in pool if set(r.stores) <= store_set]
    visits = int(round(data.params["transporter_lieferungen_pro_woche_pro_markt"]))
    if visits < 1:
        raise ValueError("transporter_lieferungen_pro_woche_pro_markt must be positive")
    if initial is not None and initial.depot != depot:
        initial = None
    if initial is not None and not set(initial.stores) <= set(stores):
        # A scenario may turn some stores negative; the MILP then does not
        # contain them, so the warm start is not directly usable.
        initial = None
    if initial is not None and not relax_integrality:
        pool = _with_initial_routes(data, pool, initial)
    warehouses = sorted({r.warehouse for r in pool})
    if depot not in warehouses:
        raise ValueError(f"depot {depot} has no routes in the pool")

    routes_by_store: dict[int, list[tuple[int, Route]]] = {i: [] for i in stores}
    routes_by_warehouse: dict[int, list[tuple[int, Route]]] = {w: [] for w in warehouses}
    routes_by_store_wh: dict[tuple[int, int], list[tuple[int, Route]]] = {}
    for idx, r in enumerate(pool):
        routes_by_warehouse[r.warehouse].append((idx, r))
        for i in r.stores:
            routes_by_store[i].append((idx, r))
            routes_by_store_wh.setdefault((i, r.warehouse), []).append((idx, r))

    h = highspy.Highs()
    h.setOptionValue("output_flag", bool(verbose))
    h.setOptionValue("time_limit", float(time_limit))
    h.setOptionValue("mip_rel_gap", float(mip_gap))
    h.setOptionValue("threads", int(threads))
    h.setOptionValue("presolve", "on")
    if solution_file:
        h.setOptionValue("solution_file", str(solution_file))
    h.changeObjectiveSense(highspy.ObjSense.kMaximize)

    # ---------------------------------------------------------------- variables
    y = {i: h.addBinary(float(data.margin(i)), name=f"y_{i}") for i in stores}
    z: dict[int, highspy.highs_var] = {}
    for w in warehouses:
        if w == depot:
            z[w] = h.addVariable(1.0, 1.0, 0.0, highspy.HighsVarType.kInteger, f"z_{w}")
        else:
            p = data.params
            truck = WEEKS_PER_YEAR * p["lkw_lieferungen_pro_woche_pro_zwischenlager"] * (
                p["lkw_fixkosten_pro_fahrt"] + p["lkw_kosten_pro_km"] * 2.0 * data.d(depot, w)
            )
            z[w] = h.addBinary(-(data.satellite_cost(w) + truck), name=f"z_{w}")

    lam = {}
    for idx, r in enumerate(pool):
        obj = -WEEKS_PER_YEAR * r.cost
        if relax_lambda:
            lam[idx] = h.addVariable(
                0.0, float(visits), obj, highspy.HighsVarType.kContinuous, f"lam_{idx}"
            )
        else:
            lam[idx] = h.addIntegral(0.0, float(visits), obj, f"lam_{idx}")
    a: dict[tuple[int, int], highspy.highs_var] = {}
    whs_for_store: dict[int, list[int]] = {i: [] for i in stores}
    for i in stores:
        whs = sorted({w for (ii, w) in routes_by_store_wh if ii == i})
        whs_for_store[i] = whs
        for w in whs:
            a[(i, w)] = h.addBinary(0.0, name=f"a_{i}_{w}")

    # ---------------------------------------------------------------- constraints
    n_cons = 0
    cover_rows: dict[int, int] = {}
    assign_rows: dict[int, int] = {}
    link_rows: dict[tuple[int, int], int] = {}
    open_rows: dict[int, int] = {}

    # each open store is visited exactly ``visits`` times per week
    for i in stores:
        expr = sum((lam[idx] for idx, _ in routes_by_store[i]), start=0)
        con = h.addConstr(expr - visits * y[i] == 0, name=f"cover_{i}")
        cover_rows[i] = int(con.index)
        n_cons += 1

    # each store is assigned to exactly one warehouse
    for i in stores:
        whs = whs_for_store[i]
        if not whs:
            con = h.addConstr(y[i] == 0, name=f"no_route_{i}")
            assign_rows[i] = int(con.index)
            n_cons += 1
            continue
        con = h.addConstr(
            sum((a[(i, w)] for w in whs), start=0) - y[i] == 0, name=f"assign_{i}"
        )
        assign_rows[i] = int(con.index)
        n_cons += 1

    # a route may only cover stores assigned to its warehouse
    for (i, w), rs in routes_by_store_wh.items():
        expr = sum((lam[idx] for idx, _ in rs), start=0)
        con = h.addConstr(expr - visits * a[(i, w)] <= 0, name=f"link_{i}_{w}")
        link_rows[(i, w)] = int(con.index)
        n_cons += 1
        if strong_linking and w != depot:
            # a store can only be assigned to an open warehouse
            h.addConstr(a[(i, w)] - z[w] <= 0, name=f"open_link_{i}_{w}")
            n_cons += 1

    # routes only from open warehouses
    for w in warehouses:
        rs = routes_by_warehouse[w]
        if not rs:
            continue
        max_routes = visits * len({i for _, r in rs for i in r.stores})
        expr = sum((lam[idx] for idx, _ in rs), start=0)
        con = h.addConstr(expr - max_routes * z[w] <= 0, name=f"open_{w}")
        open_rows[w] = int(con.index)
        n_cons += 1

    if verbose:
        print(
            f"MILP: {len(stores)} stores, {len(warehouses)} warehouses, "
            f"{len(pool)} routes, {len(a)} assignment vars, {n_cons} constraints"
        )

    if initial is not None and not relax_integrality:
        initial_profit = evaluate(data, initial)["profit"]
        pool_index = {
            (r.warehouse, frozenset(r.stores)): idx for idx, r in enumerate(pool)
        }
        x0 = np.zeros(h.getNumCol(), dtype=float)
        for i in stores:
            x0[int(y[i])] = 1.0 if i in initial.stores else 0.0
        for w in warehouses:
            x0[int(z[w])] = 1.0 if (w == depot or w in initial.satellites) else 0.0
        for (i, w), var in a.items():
            x0[int(var)] = 1.0 if initial.assignment.get(i) == w else 0.0
        for w, routes in initial.routes.items():
            for route in routes:
                key = (w, frozenset(route))
                idx = pool_index.get(key)
                if idx is None:
                    raise RuntimeError(f"warm-start route not in pool: {key}")
                x0[int(lam[idx])] += 1.0
                if x0[int(lam[idx])] > visits + 1e-9:
                    raise RuntimeError("warm-start route multiplicity exceeds visits")
        status = h.setSolution(
            len(x0),
            np.arange(len(x0), dtype=np.int32),
            x0,
        )
        if status != highspy.HighsStatus.kOk:
            raise RuntimeError(f"HiGHS rejected the MIP start: {status}")
        if verbose:
            print(f"warm start: profit={initial_profit/1e6:.4f} M EUR")

    if relax_integrality:
        n_cols = h.getNumCol()
        st = h.changeColsIntegrality(
            n_cols,
            np.arange(n_cols, dtype=np.int32),
            np.full(n_cols, int(highspy.HighsVarType.kContinuous), dtype=np.uint8),
        )
        if st != highspy.HighsStatus.kOk:
            raise RuntimeError(f"HiGHS could not relax integrality: {st}")

    h.run()
    info = h.getInfo()
    status = h.getModelStatus().name
    runtime = perf_counter() - t0

    if relax_integrality:
        sol = h.getSolution()
        cover_duals = assign_duals = link_duals = open_duals = None
        if getattr(sol, "dual_valid", False):
            row_dual = sol.row_dual
            cover_duals = {i: float(row_dual[idx]) for i, idx in cover_rows.items()}
            assign_duals = {i: float(row_dual[idx]) for i, idx in assign_rows.items()}
            link_duals = {
                key: float(row_dual[idx]) for key, idx in link_rows.items()
            }
            open_duals = {w: float(row_dual[idx]) for w, idx in open_rows.items()}
        if verbose:
            print(
                f"LP bound: {float(info.objective_function_value)/1e6:.6f} M, "
                f"status={status}, runtime={runtime:.1f}s"
            )
        return LpResult(
            objective=float(info.objective_function_value) - data.depot_cost(depot),
            status=status,
            runtime_s=runtime,
            n_routes=len(pool),
            n_variables=len(y) + len(z) + len(lam) + len(a),
            n_constraints=n_cons,
            cover_duals=cover_duals,
            assign_duals=assign_duals,
            link_duals=link_duals,
            open_duals=open_duals,
        )

    if relax_lambda:
        bound = float(info.mip_dual_bound) - data.depot_cost(depot)
        if verbose:
            print(
                f"relaxed-route bound: {bound/1e6:.6f} M, status={status}, "
                f"gap={info.mip_gap:.4%}, runtime={runtime:.1f}s"
            )
        return LpResult(
            objective=bound,
            status=status,
            runtime_s=runtime,
            n_routes=len(pool),
            n_variables=len(y) + len(z) + len(lam) + len(a),
            n_constraints=n_cons,
            mip_gap=float(info.mip_gap),
            bound_is_dual=True,
        )

    sol = h.getSolution()
    if not getattr(sol, "value_valid", True):
        raise RuntimeError(f"MILP has no valid solution (status {status})")

    # ---------------------------------------------------------------- extract
    x = sol.col_value

    def val(v: highspy.highs_var) -> float:
        return float(x[int(v)])

    open_stores = {i for i in stores if val(y[i]) > 0.5}
    open_sats = {w for w in warehouses if w != depot and val(z[w]) > 0.5}
    assignment: dict[int, int] = {}
    for i in open_stores:
        whs = [w for w in whs_for_store[i] if val(a[(i, w)]) > 0.5]
        if len(whs) != 1:
            raise RuntimeError(f"store {i} has {len(whs)} assigned warehouses")
        assignment[i] = whs[0]

    routes: dict[int, list[list[int]]] = {w: [] for w in {depot} | open_sats}
    for idx, r in enumerate(pool):
        mult = int(round(val(lam[idx])))
        if mult <= 0:
            continue
        if r.warehouse not in routes:
            raise RuntimeError(f"route from closed warehouse {r.warehouse} selected")
        order = (
            tsp_exact(data, r.warehouse, list(r.stores))
            if len(r.stores) <= 13
            else two_opt(data, r.warehouse, list(r.stores))
        )
        for _ in range(mult):
            routes[r.warehouse].append(list(order))

    net = Network(
        depot=depot,
        satellites=open_sats,
        stores=open_stores,
        assignment=assignment,
        routes=routes,
    )
    breakdown = evaluate(data, net)
    objective = float(info.objective_function_value) - data.depot_cost(depot)
    if verbose:
        print(
            f"status={status}, objective={objective/1e6:.4f} M, "
            f"profit={breakdown['profit']/1e6:.4f} M, gap={info.mip_gap:.4%}, "
            f"runtime={runtime:.1f}s"
        )

    return MilpResult(
        network=net,
        breakdown=breakdown,
        objective=objective,
        mip_gap=float(info.mip_gap),
        status=status,
        runtime_s=runtime,
        n_routes=len(pool),
        n_variables=len(y) + len(z) + len(lam) + len(a),
        n_constraints=n_cons,
    )


def _with_initial_routes(data: Data, pool: list[Route], net: Network) -> list[Route]:
    """Add route sets of *net* that are missing from *pool* (re-priced for data)."""
    keys = {(r.warehouse, frozenset(r.stores)) for r in pool}
    extra: list[Route] = []
    for w, routes in net.routes.items():
        for route in routes:
            key = (w, frozenset(route))
            if key in keys:
                continue
            order = (
                tsp_exact(data, w, list(route))
                if len(route) <= 13
                else two_opt(data, w, list(route))
            )
            extra.append(
                Route(
                    warehouse=w,
                    stores=tuple(sorted(route)),
                    cost=route_cost(data, w, order),
                    km=route_km(data, w, order),
                    hours=route_hours(data, w, order),
                )
            )
            keys.add(key)
    return pool + extra
