"""Exact pricing for one warehouse (prototype for branch-and-price).

Given dual values of the set-partitioning master, the pricing problem looks
for a feasible single route with positive reduced cost.  It is formulated as a
prize-collecting TSP with a shift-length constraint and solved exactly with
HiGHS.  This is the core building block of a branch-and-price proof.
"""
from __future__ import annotations

from dataclasses import dataclass
from time import perf_counter

import highspy

from .data import Data
from .routing import feasible, route_cost, route_hours, route_km, tsp_exact

WEEKS = 52.0


@dataclass
class PricingResult:
    warehouse: int
    stores: tuple[int, ...]
    order: tuple[int, ...]
    objective: float
    reduced_cost: float
    status: str
    runtime_s: float
    mip_gap: float
    n_stores: int


def solve_pricing(
    data: Data,
    warehouse: int,
    cover_duals: dict[int, float],
    link_duals: dict[tuple[int, int], float],
    open_dual: float = 0.0,
    *,
    time_limit: float = 60.0,
    mip_gap: float = 0.0,
    attractive_only: bool = True,
    verbose: bool = False,
) -> PricingResult:
    """Find the feasible route with minimum pricing objective.

    The master reduced cost of a route is
    ``-annual_cost - sum(cover_dual) - sum(link_dual) - open_dual``.
    Minimising ``annual_cost + sum(cover_dual + link_dual)`` therefore finds
    the most attractive route.  A positive ``reduced_cost`` means that the
    route can improve the master LP.
    """
    stores = [
        i
        for i in data.stores
        if feasible(data, warehouse, [i])
        and (
            not attractive_only
            or (cover_duals.get(i, 0.0) + link_duals.get((i, warehouse), 0.0)) < -1e-9
        )
    ]
    n = len(stores)
    if n == 0:
        return PricingResult(
            warehouse, (), (), 0.0, -open_dual, "kInfeasible", 0.0, 0.0, 0
        )

    depot_node = ("w", warehouse)
    store_nodes = [("s", i) for i in stores]
    nodes = [depot_node] + store_nodes

    def node_id(node: tuple[str, int]) -> int:
        return node[1]

    h = highspy.Highs()
    h.setOptionValue("output_flag", bool(verbose))
    h.setOptionValue("time_limit", float(time_limit))
    h.setOptionValue("mip_rel_gap", float(mip_gap))
    h.setOptionValue("threads", 4)
    h.changeObjectiveSense(highspy.ObjSense.kMinimize)

    x: dict[tuple[tuple[str, int], tuple[str, int]], highspy.highs_var] = {}
    for a in nodes:
        for b in nodes:
            if a != b:
                x[(a, b)] = h.addBinary(
                    0.0, name=f"x_{a[0]}{a[1]}_{b[0]}{b[1]}"
                )
    y = {i: h.addBinary(0.0, name=f"y_{i}") for i in stores}
    u = {
        i: h.addVariable(1.0, float(n), 0.0, highspy.HighsVarType.kContinuous, f"u_{i}")
        for i in stores
    }

    obj = 200.0 * WEEKS
    for (a, b), var in x.items():
        obj += 0.55 * WEEKS * data.d(node_id(a), node_id(b)) * var
    for i, var in y.items():
        prize = cover_duals.get(i, 0.0) + link_duals.get((i, warehouse), 0.0)
        obj += prize * var
    h.setObjective(obj)

    # depot degree exactly one (non-empty route)
    h.addConstr(
        sum(x[(depot_node, node)] for node in store_nodes) == 1,
        name="depot_out",
    )
    h.addConstr(
        sum(x[(node, depot_node)] for node in store_nodes) == 1,
        name="depot_in",
    )

    for i, node in zip(stores, store_nodes):
        h.addConstr(
            sum(x[(node, other)] for other in nodes if other != node) == y[i],
            name=f"out_{i}",
        )
        h.addConstr(
            sum(x[(other, node)] for other in nodes if other != node) == y[i],
            name=f"in_{i}",
        )

    # MTZ subtour elimination on stores
    for i, ni in zip(stores, store_nodes):
        for j, nj in zip(stores, store_nodes):
            if i != j:
                h.addConstr(
                    u[i] - u[j] + n * x[(ni, nj)] <= n - 1, name=f"mtz_{i}_{j}"
                )

    # shift length: driving time + service time
    h.addConstr(
        sum(
            data.d(node_id(a), node_id(b))
            / data.params["transporter_durchschnittsgeschwindigkeit_kmh"]
            * var
            for (a, b), var in x.items()
        )
        + data.params["transporter_servicezeit_pro_markt"] / 60.0
        * sum(y.values())
        <= data.params["transporter_schichtdauer"],
        name="shift",
    )

    t0 = perf_counter()
    h.run()
    info = h.getInfo()
    status = h.getModelStatus().name
    runtime = perf_counter() - t0
    sol = h.getSolution()
    if not getattr(sol, "value_valid", False):
        return PricingResult(
            warehouse, (), (), float(info.objective_function_value), 0.0, status,
            runtime, float(info.mip_gap), n
        )

    xv = sol.col_value
    selected = tuple(sorted(i for i in stores if xv[int(y[i])] > 0.5))
    # Reconstruct the route from the depot.
    order: list[int] = []
    current = depot_node
    for _ in range(n + 1):
        nxt = [
            node
            for node in nodes
            if node != current and xv[int(x[(current, node)])] > 0.5
        ]
        if len(nxt) != 1:
            raise RuntimeError(
                f"pricing solution has {len(nxt)} successors at {current}"
            )
        current = nxt[0]
        if current == depot_node:
            break
        order.append(node_id(current))
    if tuple(order) != selected and set(order) != set(selected):
        raise RuntimeError("pricing route does not match selected stores")

    objective = float(info.objective_function_value)
    reduced_cost = -objective - open_dual
    # Sanity check: the extracted route reproduces the MIP objective.
    check_cost = route_cost(data, warehouse, order)
    expected = WEEKS * check_cost + sum(
        (cover_duals.get(i, 0.0) + link_duals.get((i, warehouse), 0.0)) for i in order
    )
    if abs(expected - objective) > 1e-5:
        raise RuntimeError(
            f"pricing objective mismatch: {expected} vs {objective}"
        )
    if not feasible(data, warehouse, order):
        raise RuntimeError("pricing returned an infeasible route")

    return PricingResult(
        warehouse=warehouse,
        stores=tuple(selected),
        order=tuple(order),
        objective=objective,
        reduced_cost=reduced_cost,
        status=status,
        runtime_s=runtime,
        mip_gap=float(info.mip_gap),
        n_stores=n,
    )


def solve_pricing_dfj(
    data: Data,
    warehouse: int,
    cover_duals: dict[int, float],
    link_duals: dict[tuple[int, int], float],
    open_dual: float = 0.0,
    *,
    time_limit: float = 60.0,
    mip_gap: float = 0.0,
    attractive_only: bool = True,
    verbose: bool = False,
) -> PricingResult:
    """Exact pricing with iterative DFJ subtour cuts.

    The compact MTZ formulation is replaced by degree constraints plus
    cutting planes for the subtours that HiGHS returns.  Every added cut is
    valid for all routes, so an optimal solution without store cycles is the
    exact pricing optimum.
    """
    stores = [
        i
        for i in data.stores
        if feasible(data, warehouse, [i])
        and (
            not attractive_only
            or (cover_duals.get(i, 0.0) + link_duals.get((i, warehouse), 0.0)) < -1e-9
        )
    ]
    n = len(stores)
    if n == 0:
        return PricingResult(
            warehouse, (), (), 0.0, -open_dual, "kInfeasible", 0.0, 0.0, 0
        )

    depot_node = ("w", warehouse)
    store_nodes = [("s", i) for i in stores]
    nodes = [depot_node] + store_nodes

    def node_id(node: tuple[str, int]) -> int:
        return node[1]

    h = highspy.Highs()
    h.setOptionValue("output_flag", bool(verbose))
    h.setOptionValue("time_limit", float(time_limit))
    h.setOptionValue("mip_rel_gap", float(mip_gap))
    h.setOptionValue("threads", 4)
    h.changeObjectiveSense(highspy.ObjSense.kMinimize)

    x: dict[tuple[tuple[str, int], tuple[str, int]], highspy.highs_var] = {}
    for a in nodes:
        for b in nodes:
            if a != b:
                x[(a, b)] = h.addBinary(
                    0.0, name=f"x_{a[0]}{a[1]}_{b[0]}{b[1]}"
                )
    y = {i: h.addBinary(0.0, name=f"y_{i}") for i in stores}

    obj = 200.0 * WEEKS
    for (a, b), var in x.items():
        obj += 0.55 * WEEKS * data.d(node_id(a), node_id(b)) * var
    for i, var in y.items():
        prize = cover_duals.get(i, 0.0) + link_duals.get((i, warehouse), 0.0)
        obj += prize * var
    h.setObjective(obj)

    h.addConstr(
        sum(x[(depot_node, node)] for node in store_nodes) == 1, name="depot_out"
    )
    h.addConstr(
        sum(x[(node, depot_node)] for node in store_nodes) == 1, name="depot_in"
    )
    for i, node in zip(stores, store_nodes):
        h.addConstr(
            sum(x[(node, other)] for other in nodes if other != node) == y[i],
            name=f"out_{i}",
        )
        h.addConstr(
            sum(x[(other, node)] for other in nodes if other != node) == y[i],
            name=f"in_{i}",
        )
    h.addConstr(
        sum(
            data.d(node_id(a), node_id(b))
            / data.params["transporter_durchschnittsgeschwindigkeit_kmh"]
            * var
            for (a, b), var in x.items()
        )
        + data.params["transporter_servicezeit_pro_markt"] / 60.0
        * sum(y.values())
        <= data.params["transporter_schichtdauer"],
        name="shift",
    )

    def cycles(selected: set[int]) -> list[set[int]]:
        """Return store-only cycles of the current selected arc set."""
        adj: dict[int, list[int]] = {i: [] for i in selected}
        for a, b in selected_arcs:
            ia, ib = node_id(a), node_id(b)
            if ia in selected and ib in selected:
                adj[ia].append(ib)
        seen: set[int] = set()
        found: list[set[int]] = []
        for start in selected:
            if start in seen:
                continue
            stack = [start]
            comp = set()
            while stack:
                u = stack.pop()
                if u in comp:
                    continue
                comp.add(u)
                seen.add(u)
                stack.extend(v for v in adj[u] if v not in comp)
            # A store-only cycle has exactly two internal incident arcs per node.
            # A depot path has endpoints with only one internal arc.
            if len(comp) >= 2:
                internal_degree = {
                    u: sum(
                        1
                        for a, b in selected_arcs
                        if node_id(a) in comp
                        and node_id(b) in comp
                        and (node_id(a) == u or node_id(b) == u)
                    )
                    for u in comp
                }
                if all(deg == 2 for deg in internal_degree.values()):
                    found.append(comp)
        return found

    total_t0 = perf_counter()
    iteration = 0
    selected_arcs: list[tuple[tuple[str, int], tuple[str, int]]] = []
    while True:
        iteration += 1
        h.run()
        status = h.getModelStatus().name
        info = h.getInfo()
        if status != "kOptimal":
            return PricingResult(
                warehouse, (), (), float(info.objective_function_value), 0.0,
                status, perf_counter() - total_t0, float(info.mip_gap), n
            )
        sol = h.getSolution()
        xv = sol.col_value
        selected_arcs = [
            (a, b) for (a, b), var in x.items() if xv[int(var)] > 0.5
        ]
        selected = {i for i in stores if xv[int(y[i])] > 0.5}
        store_cycles = cycles(selected)
        if verbose:
            print(
                f"DFJ iteration {iteration}: status={status}, objective={info.objective_function_value:.4f}, "
                f"selected={len(selected)}, cycles={[len(c) for c in store_cycles]}",
                flush=True,
            )
        if not store_cycles:
            break
        if perf_counter() - total_t0 > time_limit:
            return PricingResult(
                warehouse, (), (), float(info.objective_function_value), 0.0,
                "kTimeLimit", perf_counter() - total_t0, float(info.mip_gap), n
            )
        for cycle in store_cycles:
            # sum of arcs inside the cycle <= |S| - 1
            inside = [
                var
                for (a, b), var in x.items()
                if node_id(a) in cycle and node_id(b) in cycle
            ]
            h.addConstr(
                sum(inside) <= len(cycle) - 1,
                name=f"dfj_{iteration}_{min(cycle)}",
            )

    # Reconstruct the single depot route.
    order: list[int] = []
    current = depot_node
    for _ in range(n + 1):
        nxt = [
            node
            for node in nodes
            if node != current and xv[int(x[(current, node)])] > 0.5
        ]
        if len(nxt) != 1:
            raise RuntimeError(
                f"DFJ pricing has {len(nxt)} successors at {current}"
            )
        current = nxt[0]
        if current == depot_node:
            break
        order.append(node_id(current))
    if set(order) != {i for i in stores if xv[int(y[i])] > 0.5}:
        raise RuntimeError("DFJ route does not match selected stores")

    objective = float(info.objective_function_value)
    check_cost = route_cost(data, warehouse, order)
    expected = WEEKS * check_cost + sum(
        (cover_duals.get(i, 0.0) + link_duals.get((i, warehouse), 0.0))
        for i in order
    )
    if abs(expected - objective) > 1e-5:
        raise RuntimeError(f"DFJ pricing objective mismatch: {expected} vs {objective}")
    if not feasible(data, warehouse, order):
        raise RuntimeError("DFJ pricing returned an infeasible route")

    return PricingResult(
        warehouse=warehouse,
        stores=tuple(sorted(order)),
        order=tuple(order),
        objective=objective,
        reduced_cost=-objective - open_dual,
        status="kOptimal",
        runtime_s=perf_counter() - total_t0,
        mip_gap=float(info.mip_gap),
        n_stores=n,
    )


def solve_pricing_positive(
    data: Data,
    warehouse: int,
    cover_duals: dict[int, float],
    link_duals: dict[tuple[int, int], float],
    open_dual: float = 0.0,
    *,
    max_positive: int = 13,
    verbose: bool = False,
) -> PricingResult:
    """Exact pricing by enumerating stores with negative dual prize.

    The master reduced cost is ``-annual_cost - sum(prize) - open_dual``;
    a store lowers the pricing objective only if its prize
    ``cover_dual + link_dual`` is negative.  A store with non-negative prize
    cannot improve a route: in a metric space adding a node cannot shorten the
    tour, and the fixed route cost is unchanged.  Hence only stores with
    ``cover_dual + link_dual < 0`` can appear in an improving route.  For the
    sparse LP duals of this project that leaves only a handful of stores, so
    all subsets can be enumerated exactly.
    """
    from itertools import combinations

    t0 = perf_counter()
    prizes = {
        i: cover_duals.get(i, 0.0) + link_duals.get((i, warehouse), 0.0)
        for i in data.stores
        if feasible(data, warehouse, [i])
    }
    attractive = [i for i, p in prizes.items() if p < -1e-9]
    if len(attractive) > max_positive:
        raise ValueError(
            f"{len(attractive)} negative-prize stores exceed max_positive={max_positive}"
        )

    best_obj: float | None = None
    best_stores: tuple[int, ...] = ()
    best_order: tuple[int, ...] = ()
    for k in range(1, len(attractive) + 1):
        for subset in combinations(attractive, k):
            order = tsp_exact(data, warehouse, list(subset))
            if not feasible(data, warehouse, order):
                continue
            value = WEEKS * route_cost(data, warehouse, order) + sum(
                prizes[i] for i in subset
            )
            if best_obj is None or value < best_obj:
                best_obj = value
                best_stores = tuple(sorted(subset))
                best_order = tuple(order)

    if best_obj is None:
        return PricingResult(
            warehouse, (), (), 0.0, -open_dual, "kOptimal",
            perf_counter() - t0, 0.0, len(attractive)
        )
    return PricingResult(
        warehouse=warehouse,
        stores=best_stores,
        order=best_order,
        objective=best_obj,
        reduced_cost=-best_obj - open_dual,
        status="kOptimal",
        runtime_s=perf_counter() - t0,
        mip_gap=0.0,
        n_stores=len(attractive),
    )


def solve_pricing_dfs(
    data: Data,
    warehouse: int,
    cover_duals: dict[int, float],
    link_duals: dict[tuple[int, int], float],
    open_dual: float = 0.0,
    *,
    time_limit: float = 60.0,
    max_nodes: int = 5_000_000,
    initial_order: list[int] | None = None,
    verbose: bool = False,
) -> PricingResult:
    """Depth-first branch-and-bound pricing for one warehouse.

    Only stores with negative prize can improve the route.  The search
    maintains a valid upper bound from the sum of all remaining negative
    prizes and prunes when it cannot beat the incumbent.  This is an exact
    branch-and-bound if it terminates before the node/time limit.
    """
    t0 = perf_counter()
    speed = data.params["transporter_durchschnittsgeschwindigkeit_kmh"]
    service = data.params["transporter_servicezeit_pro_markt"] / 60.0
    horizon = data.params["transporter_schichtdauer"]
    km_cost = WEEKS * data.params["transporter_kosten_pro_km"]
    fixed = WEEKS * data.params["transporter_fixkosten_pro_route"]

    prizes = {
        i: cover_duals.get(i, 0.0) + link_duals.get((i, warehouse), 0.0)
        for i in data.stores
        if feasible(data, warehouse, [i])
    }
    candidates = [i for i, p in prizes.items() if p < -1e-9]
    # Visit attractive stores first, but keep the search deterministic.
    candidates.sort(key=lambda i: (prizes[i], data.d(warehouse, i)))
    n = len(candidates)
    if n == 0:
        return PricingResult(
            warehouse, (), (), 0.0, -open_dual, "kOptimal", 0.0, 0.0, 0
        )

    # Greedy incumbent: repeatedly take the best prize per detour that keeps
    # the direct return feasible.
    greedy: list[int] = []
    current = warehouse
    elapsed = 0.0
    remaining = set(candidates)
    while remaining:
        options = []
        for i in remaining:
            travel = data.d(current, i) / speed
            if elapsed + travel + service + data.d(i, warehouse) / speed <= horizon:
                score = (-prizes[i]) / max(travel, 1e-6)
                options.append((score, i, travel))
        if not options:
            break
        _, i, travel = max(options)
        greedy.append(i)
        remaining.remove(i)
        elapsed += travel + service
        current = i

    def route_value(order: list[int]) -> float:
        if not order:
            return 0.0
        return fixed + km_cost * route_km(data, warehouse, order) + sum(
            prizes[i] for i in order
        )

    best_order = greedy
    best_obj = route_value(greedy)
    if initial_order and set(initial_order) <= set(candidates):
        candidate_order = [i for i in initial_order if i in candidates]
        if feasible(data, warehouse, candidate_order):
            candidate_obj = route_value(candidate_order)
            if candidate_obj < best_obj:
                best_order = candidate_order
                best_obj = candidate_obj
    nodes = 0
    timed_out = False

    def dfs(current: int, elapsed: float, travel_km: float, gain: float,
            visited: int, order: list[int], remaining_gain: float) -> None:
        nonlocal best_obj, best_order, nodes, timed_out
        nodes += 1
        if nodes > max_nodes or perf_counter() - t0 > time_limit:
            timed_out = True
            return
        # Evaluate the current route with a direct return.
        current_obj = fixed + km_cost * (travel_km + data.d(current, warehouse)) - gain
        if current_obj < best_obj - 1e-9:
            best_obj = current_obj
            best_order = list(order)
        # Optimistic bound: collect every remaining negative prize, direct return.
        ub = fixed + km_cost * (travel_km + data.d(current, warehouse)) - (
            gain + remaining_gain
        )
        if ub >= best_obj - 1e-9:
            return
        for idx, i in enumerate(candidates):
            bit = 1 << idx
            if visited & bit:
                continue
            travel = data.d(current, i) / speed
            if elapsed + travel + service + data.d(i, warehouse) / speed > horizon:
                continue
            dfs(
                i,
                elapsed + travel + service,
                travel_km + data.d(current, i),
                gain - prizes[i],
                visited | bit,
                order + [i],
                remaining_gain + prizes[i] if prizes[i] < 0 else remaining_gain,
            )
            if timed_out:
                return

    dfs(
        warehouse, 0.0, 0.0, 0.0, 0, [],
        sum(-p for p in prizes.values() if p < 0),
    )
    status = "kTimeLimit" if timed_out else "kOptimal"
    return PricingResult(
        warehouse=warehouse,
        stores=tuple(sorted(best_order)),
        order=tuple(best_order),
        objective=best_obj,
        reduced_cost=-best_obj - open_dual,
        status=status,
        runtime_s=perf_counter() - t0,
        mip_gap=0.0,
        n_stores=n,
    )


def solve_pricing_scip(
    data: Data,
    warehouse: int,
    cover_duals: dict[int, float],
    link_duals: dict[tuple[int, int], float],
    open_dual: float = 0.0,
    *,
    time_limit: float = 60.0,
    mip_gap: float = 0.0,
    attractive_only: bool = True,
    verbose: bool = False,
) -> PricingResult:
    """Exact pricing as a SCIP MIP (compact MTZ formulation)."""
    from pyscipopt import Model, quicksum

    t0 = perf_counter()
    stores = [
        i
        for i in data.stores
        if feasible(data, warehouse, [i])
        and (
            not attractive_only
            or (cover_duals.get(i, 0.0) + link_duals.get((i, warehouse), 0.0)) < -1e-9
        )
    ]
    n = len(stores)
    if n == 0:
        return PricingResult(
            warehouse, (), (), 0.0, -open_dual, "kOptimal", 0.0, 0.0, 0
        )

    depot_node = ("w", warehouse)
    store_nodes = [("s", i) for i in stores]
    nodes = [depot_node] + store_nodes

    def node_id(node: tuple[str, int]) -> int:
        return node[1]

    m = Model("pricing")
    if not verbose:
        m.hideOutput()
    m.setParam("limits/time", float(time_limit))
    m.setParam("limits/gap", float(mip_gap))

    x = {}
    for a in nodes:
        for b in nodes:
            if a != b:
                x[(a, b)] = m.addVar(
                    vtype="B", name=f"x_{a[0]}{a[1]}_{b[0]}{b[1]}"
                )
    y = {i: m.addVar(vtype="B", name=f"y_{i}") for i in stores}
    u = {
        i: m.addVar(lb=1.0, ub=float(n), vtype="C", name=f"u_{i}")
        for i in stores
    }

    obj = (
        200.0 * WEEKS
        + quicksum(
            0.55 * WEEKS * data.d(node_id(a), node_id(b)) * var
            for (a, b), var in x.items()
        )
        + quicksum(
            (cover_duals.get(i, 0.0) + link_duals.get((i, warehouse), 0.0)) * y[i]
            for i in stores
        )
    )
    m.setObjective(obj, sense="minimize")

    m.addCons(quicksum(x[(depot_node, node)] for node in store_nodes) == 1)
    m.addCons(quicksum(x[(node, depot_node)] for node in store_nodes) == 1)
    for i, node in zip(stores, store_nodes):
        m.addCons(
            quicksum(x[(node, other)] for other in nodes if other != node) == y[i]
        )
        m.addCons(
            quicksum(x[(other, node)] for other in nodes if other != node) == y[i]
        )
    for i, ni in zip(stores, store_nodes):
        for j, nj in zip(stores, store_nodes):
            if i != j:
                m.addCons(u[i] - u[j] + n * x[(ni, nj)] <= n - 1)
    m.addCons(
        quicksum(
            data.d(node_id(a), node_id(b))
            / data.params["transporter_durchschnittsgeschwindigkeit_kmh"]
            * var
            for (a, b), var in x.items()
        )
        + data.params["transporter_servicezeit_pro_markt"] / 60.0
        * quicksum(y.values())
        <= data.params["transporter_schichtdauer"]
    )

    m.optimize()
    status = m.getStatus()
    runtime = perf_counter() - t0
    if m.getNSols() == 0:
        return PricingResult(
            warehouse, (), (), 0.0, 0.0, status, runtime, m.getGap(), n
        )
    sol = m.getBestSol()
    selected = tuple(
        sorted(i for i in stores if m.getSolVal(sol, y[i]) > 0.5)
    )
    order: list[int] = []
    current = depot_node
    for _ in range(n + 1):
        nxt = [
            node
            for node in nodes
            if node != current
            and (current, node) in x
            and m.getSolVal(sol, x[(current, node)]) > 0.5
        ]
        if len(nxt) != 1:
            raise RuntimeError(
                f"SCIP pricing has {len(nxt)} successors at {current}"
            )
        current = nxt[0]
        if current == depot_node:
            break
        order.append(node_id(current))
    if set(order) != set(selected):
        raise RuntimeError("SCIP route does not match selected stores")
    objective = float(m.getObjVal())
    return PricingResult(
        warehouse=warehouse,
        stores=tuple(selected),
        order=tuple(order),
        objective=objective,
        reduced_cost=-objective - open_dual,
        status=status,
        runtime_s=runtime,
        mip_gap=float(m.getGap()),
        n_stores=n,
    )
