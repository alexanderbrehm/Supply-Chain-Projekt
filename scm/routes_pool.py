"""Generation of a diverse pool of feasible weekly routes.

The pool is used by the set-partitioning MILP.  It is not a complete route
enumeration; it contains savings routes, singleton routes, short routes and
routes from local-search variants.  The MILP is exact *with respect to this
pool*; a pricing step can add routes later.
"""
from __future__ import annotations

from dataclasses import dataclass
from itertools import combinations
import random

from .data import Data
from .routing import feasible, optimize_routes, route_cost, route_hours, route_km, tsp_exact, two_opt


@dataclass(frozen=True)
class Route:
    warehouse: int
    stores: tuple[int, ...]
    cost: float
    km: float
    hours: float


def _make_route(data: Data, warehouse: int, stores: tuple[int, ...]) -> Route | None:
    if not stores or len(stores) != len(set(stores)):
        return None
    if not feasible(data, warehouse, list(stores)):
        return None
    order = tsp_exact(data, warehouse, list(stores)) if len(stores) <= 13 else two_opt(
        data, warehouse, list(stores)
    )
    if not feasible(data, warehouse, order):
        return None
    return Route(
        warehouse=warehouse,
        stores=tuple(sorted(stores)),
        cost=route_cost(data, warehouse, order),
        km=route_km(data, warehouse, order),
        hours=route_hours(data, warehouse, order),
    )


def generate_pool(
    data: Data,
    warehouses: list[int] | None = None,
    *,
    pair_threshold_km: float = 100.0,
    jitter_runs: int = 0,
    seed: int = 0,
    verbose: bool = False,
) -> list[Route]:
    """Build a route pool for the given warehouses (default: all regions)."""
    if warehouses is None:
        warehouses = [int(w) for w in data.region_ids]
    rng = random.Random(seed)
    pool: dict[tuple[int, frozenset[int]], Route] = {}

    def add(route: Route | None) -> None:
        if route is None:
            return
        key = (route.warehouse, frozenset(route.stores))
        old = pool.get(key)
        if old is None or route.cost < old.cost:
            pool[key] = route

    for idx, w in enumerate(warehouses):
        w = int(w)
        reachable = [i for i in data.stores if feasible(data, w, [i])]
        if not reachable:
            continue

        # singleton routes
        for i in reachable:
            add(_make_route(data, w, (i,)))

        # one complete savings round
        for r in optimize_routes(data, w, reachable):
            add(_make_route(data, w, tuple(r)))

        # short routes: pairs of nearby stores
        for i, j in combinations(reachable, 2):
            if data.d(i, j) <= pair_threshold_km:
                add(_make_route(data, w, (i, j)))

        # randomized savings variants
        for _ in range(jitter_runs):
            routes = _jittered_savings(data, w, reachable, rng)
            for r in routes:
                add(_make_route(data, w, tuple(r)))

        if verbose and (idx + 1) % 100 == 0:
            print(f"  pool: {idx+1}/{len(warehouses)} warehouses, {len(pool)} routes")

    return list(pool.values())


def _jittered_savings(data: Data, warehouse: int, stores: list[int], rng: random.Random) -> list[list[int]]:
    """Clarke-Wright with random tie-breaking; returns feasible routes."""
    p = data.params
    routes: list[list[int]] = [[i] for i in stores]
    where = {i: k for k, r in enumerate(routes) for i in r}
    savings = []
    for a in range(len(stores)):
        i = stores[a]
        for b in range(a + 1, len(stores)):
            j = stores[b]
            s = data.d(warehouse, i) + data.d(warehouse, j) - data.d(i, j)
            if p["transporter_fixkosten_pro_route"] + p["transporter_kosten_pro_km"] * s > 0:
                savings.append((s + rng.uniform(-30.0, 30.0), i, j))
    savings.sort(reverse=True)
    for _, i, j in savings:
        ri, rj = where.get(i), where.get(j)
        if ri is None or rj is None or ri == rj:
            continue
        A, B = routes[ri], routes[rj]
        if i not in (A[0], A[-1]) or j not in (B[0], B[-1]):
            continue
        candidates = []
        if A[-1] == i and B[0] == j:
            candidates.append(A + B)
        if A[-1] == i and B[-1] == j:
            candidates.append(A + list(reversed(B)))
        if A[0] == i and B[0] == j:
            candidates.append(list(reversed(A)) + B)
        if A[0] == i and B[-1] == j:
            candidates.append(B + A)
        good = [c for c in candidates if feasible(data, warehouse, c)]
        if not good:
            continue
        merged = min(good, key=lambda c: route_km(data, warehouse, c))
        routes[ri] = merged
        routes.pop(rj)
        where = {x: k for k, r in enumerate(routes) for x in r}
    return routes
