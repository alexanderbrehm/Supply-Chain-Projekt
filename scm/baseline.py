"""Analytical baseline network.

The baseline is deliberately explainable:
1. evaluate every possible depot with a savings routing heuristic,
2. remove stores whose marginal contribution is negative,
3. greedily add satellites that improve the annual profit.

It is a strong feasible solution, but it is *not* claimed to be optimal.
"""
from __future__ import annotations

from .data import Data, WEEKS_PER_YEAR
from .network import Network, evaluate
from .routing import feasible, optimize_routes, repeat_round


def _visits(data: Data) -> int:
    return int(round(data.params["transporter_lieferungen_pro_woche_pro_markt"]))


def _depot_network(data: Data, depot: int, stores: list[int]) -> Network:
    routes = optimize_routes(data, depot, stores)
    return Network(
        depot=depot,
        satellites=set(),
        stores=set(stores),
        assignment={i: depot for i in stores},
        routes={depot: repeat_round(routes, _visits(data))},
    )


def _reoptimise_warehouse(data: Data, net: Network, warehouse: int) -> None:
    stores = [i for i in net.stores if net.assignment[i] == warehouse]
    round_routes = optimize_routes(data, warehouse, stores)
    net.routes[warehouse] = repeat_round(round_routes, _visits(data))


def _drop_worst_store(data: Data, net: Network) -> tuple[Network, dict[str, float]]:
    """Remove the store with the largest positive profit delta, if any."""
    base = evaluate(data, net)
    best_net: Network | None = None
    best_result: dict[str, float] | None = None

    for store in sorted(net.stores):
        cand = Network(
            depot=net.depot,
            satellites=set(net.satellites),
            stores=set(net.stores) - {store},
            assignment={i: w for i, w in net.assignment.items() if i != store},
            routes={w: [list(r) for r in routes] for w, routes in net.routes.items()},
        )
        wh = net.assignment[store]
        # remove the store from all weekly routes
        cand.routes[wh] = [[i for i in r if i != store] for r in cand.routes[wh]]
        cand.routes[wh] = [r for r in cand.routes[wh] if r]
        # if a satellite became empty, close it
        if wh != cand.depot and not any(i for i in cand.stores if cand.assignment[i] == wh):
            cand.satellites.discard(wh)
            cand.routes.pop(wh, None)
        _reoptimise_warehouse(data, cand, cand.depot)
        if wh != cand.depot and wh in cand.satellites:
            _reoptimise_warehouse(data, cand, wh)
        result = evaluate(data, cand)
        if result["profit"] > base["profit"] + 1e-6:
            if best_result is None or result["profit"] > best_result["profit"]:
                best_net, best_result = cand, result

    if best_net is None or best_result is None:
        return net, base
    return best_net, best_result


def _add_best_satellite(data: Data, net: Network) -> tuple[Network, dict[str, float]]:
    """Try promising satellites and add the best profitable one.

    A satellite may serve (a) stores currently assigned to the depot that are
    closer to the satellite, and (b) stores that are currently unserved but
    reachable from the satellite.  Candidates are screened by potential margin
    so that the baseline stays fast.
    """
    base = evaluate(data, net)
    depot = net.depot
    depot_stores = [i for i in net.stores if net.assignment[i] == depot]
    unserved = [i for i in data.stores if i not in net.stores]

    p = data.params
    screened: list[tuple[float, int, list[int], list[int]]] = []
    for sat in data.region_ids:
        sat = int(sat)
        if sat == depot or sat in net.satellites:
            continue
        moved = [
            i
            for i in depot_stores
            if data.d(sat, i) < data.d(depot, i) and feasible(data, sat, [i])
        ]
        new = [i for i in unserved if feasible(data, sat, [i])]
        if len(moved) + len(new) < 2:
            continue
        truck = WEEKS_PER_YEAR * p["lkw_lieferungen_pro_woche_pro_zwischenlager"] * (
            p["lkw_fixkosten_pro_fahrt"] + p["lkw_kosten_pro_km"] * 2 * data.d(depot, sat)
        )
        score = sum(data.margin(i) for i in moved + new) - data.satellite_cost(sat) - truck
        screened.append((score, sat, moved, new))

    screened.sort(reverse=True)
    best_net: Network | None = None
    best_result: dict[str, float] | None = None

    for _, sat, moved, new in screened[:60]:
        cand = Network(
            depot=depot,
            satellites=set(net.satellites) | {sat},
            stores=set(net.stores) | set(new),
            assignment={
                i: (sat if i in moved or i in new else net.assignment[i])
                for i in set(net.stores) | set(new)
            },
            routes={w: [list(r) for r in routes] for w, routes in net.routes.items()},
        )
        cand.routes[sat] = []
        _reoptimise_warehouse(data, cand, sat)
        _reoptimise_warehouse(data, cand, depot)
        result = evaluate(data, cand)
        if result["profit"] > base["profit"] + 1e-6:
            if best_result is None or result["profit"] > best_result["profit"]:
                best_net, best_result = cand, result

    if best_net is None or best_result is None:
        return net, base
    return best_net, best_result


def build_baseline(data: Data, *, verbose: bool = False) -> tuple[Network, dict[str, float]]:
    """Build the analytical baseline and return it with its profit breakdown."""
    all_stores = data.stores
    if not all_stores:
        raise RuntimeError("no store with positive margin")

    best: tuple[Network, dict[str, float]] | None = None
    for depot in data.region_ids:
        depot = int(depot)
        stores = [i for i in all_stores if feasible(data, depot, [i])]
        if not stores:
            continue
        net = _depot_network(data, depot, stores)
        result = evaluate(data, net)
        if verbose:
            print(
                f"  depot {depot:>3}: profit {result['profit']/1e6:8.3f} M EUR, "
                f"{len(stores):3d} stores, {result['n_routes']:3d} trips/week"
            )
        if best is None or result["profit"] > best[1]["profit"]:
            best = (net, result)

    if best is None:
        raise RuntimeError("no depot can serve any store")

    net, result = best
    # local search: drop stores and add satellites until no improvement
    while True:
        improved = False
        net2, result2 = _drop_worst_store(data, net)
        if result2["profit"] > result["profit"] + 1e-6:
            net, result = net2, result2
            improved = True
        net2, result2 = _add_best_satellite(data, net)
        if result2["profit"] > result["profit"] + 1e-6:
            net, result = net2, result2
            improved = True
        if not improved:
            break

    return net, result
