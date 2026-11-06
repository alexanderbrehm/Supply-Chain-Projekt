"""Routing heuristics and exact small TSPs.

The assignment has no vehicle capacities, but a route must fit into an 8-hour
shift (driving + 30 min service per stop).  For a fixed warehouse and a fixed
set of stores, ``optimize_routes`` builds one feasible delivery round in which
every store is visited exactly once.  The weekly schedule can repeat this
round, or mix different rounds (the latter is handled by the MILP).
"""
from __future__ import annotations

from functools import lru_cache

from .data import Data

EPS = 1e-9


def route_km(data: Data, warehouse: int, route: list[int]) -> float:
    if not route:
        return 0.0
    total = data.d(warehouse, route[0])
    for a, b in zip(route, route[1:]):
        total += data.d(a, b)
    total += data.d(route[-1], warehouse)
    return float(total)


def route_hours(data: Data, warehouse: int, route: list[int]) -> float:
    p = data.params
    return (
        route_km(data, warehouse, route) / p["transporter_durchschnittsgeschwindigkeit_kmh"]
        + len(route) * p["transporter_servicezeit_pro_markt"] / 60.0
    )


def route_cost(data: Data, warehouse: int, route: list[int]) -> float:
    """Cost of one trip (not annualised)."""
    if not route:
        return 0.0
    p = data.params
    return p["transporter_fixkosten_pro_route"] + p["transporter_kosten_pro_km"] * route_km(
        data, warehouse, route
    )


def feasible(data: Data, warehouse: int, route: list[int]) -> bool:
    return route_hours(data, warehouse, route) <= data.params["transporter_schichtdauer"] + EPS


def two_opt(data: Data, warehouse: int, route: list[int]) -> list[int]:
    """Improve a single route with 2-opt until no improving move exists."""
    if len(route) < 3:
        return list(route)
    best = list(route)
    improved = True
    while improved:
        improved = False
        n = len(best)
        for i in range(n - 1):
            for j in range(i + 1, n):
                cand = best[:i] + list(reversed(best[i : j + 1])) + best[j + 1 :]
                if route_km(data, warehouse, cand) + EPS < route_km(data, warehouse, best):
                    best = cand
                    improved = True
    return best


def tsp_exact(data: Data, warehouse: int, stores: list[int], limit: int = 13) -> list[int]:
    """Held-Karp TSP for a small set of stores (<= *limit*).

    Node 0 is the warehouse, nodes 1..n are the stores.  Store ids may equal
    the warehouse id (a market in the warehouse region), so reconstruction
    works with node indices rather than ids.  For larger sets a 2-opt
    heuristic is returned instead of an exact tour.
    """
    n = len(stores)
    if n <= 1:
        return list(stores)
    if n > limit:
        return two_opt(data, warehouse, list(stores))

    nodes = [warehouse] + list(stores)
    m = len(nodes)
    d = [[data.d(a, b) for b in nodes] for a in nodes]

    @lru_cache(maxsize=None)
    def dp(mask: int, last: int) -> float:
        if mask == 1:
            return 0.0
        prev_mask = mask ^ (1 << last)
        if prev_mask == 1:
            return d[0][last]
        best = float("inf")
        mm = prev_mask
        while mm:
            bit = mm & -mm
            j = bit.bit_length() - 1
            if j != 0:
                val = dp(prev_mask, j) + d[j][last]
                if val < best:
                    best = val
            mm ^= bit
        return best

    full = (1 << m) - 1
    best_val = float("inf")
    best_last = -1
    for last in range(1, m):
        val = dp(full, last) + d[last][0]
        if val < best_val:
            best_val = val
            best_last = last

    order: list[int] = []
    mask = full
    last = best_last
    while mask != 1:
        order.append(last)
        prev_mask = mask ^ (1 << last)
        best_j = -1
        best_prev = float("inf")
        if prev_mask == 1:
            best_j = 0
        else:
            mm = prev_mask
            while mm:
                bit = mm & -mm
                j = bit.bit_length() - 1
                if j != 0:
                    val = dp(prev_mask, j) + d[j][last]
                    if val < best_prev:
                        best_prev = val
                        best_j = j
                mm ^= bit
        mask = prev_mask
        last = best_j
    order.reverse()
    return [stores[idx - 1] for idx in order]


def _check_stores(data: Data, warehouse: int, stores: list[int]) -> list[int]:
    if len(stores) != len(set(stores)):
        raise ValueError("store list contains duplicates")
    bad = [i for i in stores if not feasible(data, warehouse, [i])]
    if bad:
        raise ValueError(
            f"stores {bad} cannot be served from warehouse {warehouse} within "
            f"{data.params['transporter_schichtdauer']:.0f} h"
        )
    return list(stores)


def savings_routes(data: Data, warehouse: int, stores: list[int]) -> list[list[int]]:
    """Clarke-Wright savings heuristic with the 8-hour route constraint."""
    p = data.params
    stores = _check_stores(data, warehouse, stores)
    if not stores:
        return []
    routes: list[list[int]] = [[i] for i in stores]
    where = {i: k for k, r in enumerate(routes) for i in r}

    savings = []
    for a in range(len(stores)):
        i = stores[a]
        for b in range(a + 1, len(stores)):
            j = stores[b]
            s = data.d(warehouse, i) + data.d(warehouse, j) - data.d(i, j)
            if p["transporter_fixkosten_pro_route"] + p["transporter_kosten_pro_km"] * s > 0:
                savings.append((s, i, j))
    savings.sort(reverse=True)

    for _, i, j in savings:
        ri, rj = where.get(i), where.get(j)
        if ri is None or rj is None or ri == rj:
            continue
        A, B = routes[ri], routes[rj]
        if i not in (A[0], A[-1]) or j not in (B[0], B[-1]):
            continue

        candidates: list[list[int]] = []
        if A[-1] == i and B[0] == j:
            candidates.append(A + B)
        if A[-1] == i and B[-1] == j:
            candidates.append(A + list(reversed(B)))
        if A[0] == i and B[0] == j:
            candidates.append(list(reversed(A)) + B)
        if A[0] == i and B[-1] == j:
            candidates.append(B + A)

        feasible_candidates = [c for c in candidates if feasible(data, warehouse, c)]
        if not feasible_candidates:
            continue
        merged = min(feasible_candidates, key=lambda c: route_km(data, warehouse, c))

        routes[ri] = merged
        routes.pop(rj)
        where = {x: k for k, r in enumerate(routes) for x in r}

    return routes


def optimize_routes(data: Data, warehouse: int, stores: list[int]) -> list[list[int]]:
    """Build one good feasible delivery round for one warehouse.

    Every store is visited exactly once across the returned routes.
    """
    stores = _check_stores(data, warehouse, stores)
    routes = savings_routes(data, warehouse, stores)
    out: list[list[int]] = []
    for r in routes:
        r = two_opt(data, warehouse, r)
        if len(r) <= 13:
            r = tsp_exact(data, warehouse, r)
        if not feasible(data, warehouse, r):
            raise RuntimeError(f"internal error: infeasible route after optimisation: {r}")
        out.append(r)
    return out


def repeat_round(routes: list[list[int]], visits: int = 3) -> list[list[int]]:
    """Repeat one delivery round to build a weekly schedule."""
    if visits < 1:
        raise ValueError("visits must be >= 1")
    return [list(r) for _ in range(visits) for r in routes]
