"""Network representation and exact annual-profit evaluation.

A ``Network`` stores the **weekly** delivery schedule: every route in
``routes[w]`` is driven once per week.  A store may appear in different routes
on different days, but at most once in the same route and exactly
``transporter_lieferungen_pro_woche_pro_markt`` times in total.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from .data import Data, WEEKS_PER_YEAR


@dataclass
class Network:
    """A complete weekly distribution network.

    Attributes
    ----------
    depot:
        Region id of the central warehouse.
    satellites:
        Region ids of open satellite warehouses.
    stores:
        Region ids of open mini-supermarkets.
    assignment:
        Mapping store region -> warehouse region (depot or satellite).
    routes:
        Mapping warehouse region -> list of weekly routes.  A route is an
        ordered list of store regions and is driven once per week.
    """

    depot: int
    satellites: set[int] = field(default_factory=set)
    stores: set[int] = field(default_factory=set)
    assignment: dict[int, int] = field(default_factory=dict)
    routes: dict[int, list[list[int]]] = field(default_factory=dict)

    def warehouses(self) -> set[int]:
        return {self.depot} | set(self.satellites)


def route_distance(data: Data, warehouse: int, route: list[int]) -> float:
    """Length of the round trip warehouse -> route[0] -> ... -> warehouse."""
    if not route:
        return 0.0
    total = data.d(warehouse, route[0])
    for a, b in zip(route, route[1:]):
        total += data.d(a, b)
    total += data.d(route[-1], warehouse)
    return float(total)


def route_hours(data: Data, warehouse: int, route: list[int]) -> float:
    """Driving time plus service time of one route."""
    p = data.params
    driving = route_distance(data, warehouse, route) / p["transporter_durchschnittsgeschwindigkeit_kmh"]
    service = len(route) * p["transporter_servicezeit_pro_markt"] / 60.0
    return float(driving + service)


def route_cost(data: Data, warehouse: int, route: list[int]) -> float:
    """Cost of one weekly trip (fixed + km)."""
    if not route:
        return 0.0
    p = data.params
    return p["transporter_fixkosten_pro_route"] + p["transporter_kosten_pro_km"] * route_distance(
        data, warehouse, route
    )


def evaluate(data: Data, net: Network, *, validate: bool = True) -> dict[str, float]:
    """Return a full annual profit breakdown for *net*.

    The function is deliberately strict: a network that violates an assumption
    of the assignment raises ``ValueError`` instead of silently producing a
    number.
    """
    p = data.params
    if validate:
        _validate(data, net)

    gross = sum(data.gross_profit(i) for i in net.stores)
    store_costs = sum(data.store_cost(i) for i in net.stores)
    depot_cost = data.depot_cost(net.depot)
    satellite_costs = sum(data.satellite_cost(s) for s in net.satellites)

    truck_costs = 0.0
    lkw_freq = p["lkw_lieferungen_pro_woche_pro_zwischenlager"]
    for s in net.satellites:
        km = data.d(net.depot, s)
        truck_costs += WEEKS_PER_YEAR * lkw_freq * (
            p["lkw_fixkosten_pro_fahrt"] + p["lkw_kosten_pro_km"] * 2.0 * km
        )

    transporter_costs = 0.0
    weekly_route_km = 0.0
    n_routes = 0
    for w, routes in net.routes.items():
        for route in routes:
            km = route_distance(data, w, route)
            weekly_route_km += km
            n_routes += 1
            transporter_costs += WEEKS_PER_YEAR * (
                p["transporter_fixkosten_pro_route"] + p["transporter_kosten_pro_km"] * km
            )

    profit = gross - store_costs - depot_cost - satellite_costs - truck_costs - transporter_costs

    return {
        "gross_profit": float(gross),
        "store_costs": float(store_costs),
        "depot_cost": float(depot_cost),
        "satellite_costs": float(satellite_costs),
        "truck_costs": float(truck_costs),
        "transporter_costs": float(transporter_costs),
        "profit": float(profit),
        "n_stores": int(len(net.stores)),
        "n_satellites": int(len(net.satellites)),
        "n_routes": int(n_routes),
        "n_trips_per_week": int(n_routes),
        "route_km_per_week": float(weekly_route_km),
        "annual_route_km": float(weekly_route_km * WEEKS_PER_YEAR),
    }


def _validate(data: Data, net: Network) -> None:
    p = data.params
    if net.depot not in data.region_pos:
        raise ValueError(f"unknown depot region {net.depot}")
    if net.depot in net.satellites:
        raise ValueError("depot region cannot also be a satellite")
    for s in net.satellites:
        if s not in data.region_pos:
            raise ValueError(f"unknown satellite region {s}")
    if set(net.assignment) != net.stores:
        raise ValueError("assignment keys must equal the set of open stores")
    for store, wh in net.assignment.items():
        if store not in data.region_pos:
            raise ValueError(f"unknown store region {store}")
        if wh not in net.warehouses():
            raise ValueError(f"store {store} assigned to closed warehouse {wh}")

    if set(net.routes) != net.warehouses():
        raise ValueError("routes must be provided for every open warehouse (possibly empty)")

    required_visits = int(round(p["transporter_lieferungen_pro_woche_pro_markt"]))
    visits: dict[int, int] = {i: 0 for i in net.stores}

    for w, routes in net.routes.items():
        for route in routes:
            if not route:
                raise ValueError(f"empty route at warehouse {w}")
            if len(route) != len(set(route)):
                raise ValueError(f"route at {w} visits a store more than once: {route}")
            for store in route:
                if store not in net.stores:
                    raise ValueError(f"route at {w} contains closed store {store}")
                if net.assignment[store] != w:
                    raise ValueError(
                        f"store {store} routed from {w} but assigned to {net.assignment[store]}"
                    )
                visits[store] += 1
            hours = route_hours(data, w, route)
            if hours > p["transporter_schichtdauer"] + 1e-9:
                raise ValueError(
                    f"route at {w} exceeds shift: {hours:.2f} h > {p['transporter_schichtdauer']:.1f} h"
                )

    wrong = {i: v for i, v in visits.items() if v != required_visits}
    if wrong:
        raise ValueError(
            f"each store must be visited exactly {required_visits} times per week; "
            f"violations: {wrong}"
        )
