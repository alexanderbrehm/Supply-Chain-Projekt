"""Core correctness tests for data, evaluation, routing and baseline."""
from __future__ import annotations

from dataclasses import replace
from itertools import permutations
import random

import pytest

from scm.baseline import build_baseline
from scm.data import load_data
from scm.network import Network, evaluate, route_distance, route_hours
from scm.routing import (
    feasible,
    optimize_routes,
    repeat_round,
    route_km,
    savings_routes,
    tsp_exact,
)


@pytest.fixture(scope="module")
def data():
    return load_data("Projektdateien")


def test_data_shape(data):
    assert len(data.regions) == 671
    assert len(data.stores) == 150
    assert data.dist_km.shape == (671, 671)
    assert abs(data.dist_km - data.dist_km.T).max() < 1e-6
    assert (data.dist_km.diagonal() == 0).all()


def test_starter_example(data):
    """Replicate the known one-store example from starter_script.py."""
    region = max(data.stores, key=data.margin)
    p = data.params
    trips = 52 * int(round(p["transporter_lieferungen_pro_woche_pro_markt"]))
    van_costs = trips * (p["transporter_fixkosten_pro_route"] + p["transporter_kosten_pro_km"] * 0.0)
    profit = data.gross_profit(region) - data.store_cost(region) - data.depot_cost(region) - van_costs

    net = Network(
        depot=region,
        satellites=set(),
        stores={region},
        assignment={region: region},
        routes={region: repeat_round([[region]], int(round(p["transporter_lieferungen_pro_woche_pro_markt"])))},
    )
    result = evaluate(data, net)
    assert result["profit"] == pytest.approx(profit, abs=1e-6)
    assert result["n_trips_per_week"] == 3


def test_satellite_and_truck_costs(data):
    depot, sat, store = 379, 274, 275
    assert feasible(data, sat, [store])
    p = data.params
    net = Network(
        depot=depot,
        satellites={sat},
        stores={store},
        assignment={store: sat},
        routes={depot: [], sat: repeat_round([[store]], 3)},
    )
    result = evaluate(data, net)
    expected_truck = 52 * p["lkw_lieferungen_pro_woche_pro_zwischenlager"] * (
        p["lkw_fixkosten_pro_fahrt"] + p["lkw_kosten_pro_km"] * 2 * data.d(depot, sat)
    )
    expected_transport = 52 * 3 * (
        p["transporter_fixkosten_pro_route"] + p["transporter_kosten_pro_km"] * 2 * data.d(sat, store)
    )
    assert result["truck_costs"] == pytest.approx(expected_truck)
    assert result["transporter_costs"] == pytest.approx(expected_transport)


def test_lkw_frequency_parameter(data):
    depot, sat, store = 379, 274, 275
    p2 = dict(data.params)
    p2["lkw_lieferungen_pro_woche_pro_zwischenlager"] = 2
    data2 = replace(data, params=p2)
    net = Network(
        depot=depot,
        satellites={sat},
        stores={store},
        assignment={store: sat},
        routes={depot: [], sat: repeat_round([[store]], 3)},
    )
    r1 = evaluate(data, net)
    r2 = evaluate(data2, net)
    assert r2["truck_costs"] == pytest.approx(2 * r1["truck_costs"])


def test_route_km_and_annual_km(data):
    depot, store = 379, 275
    net = Network(
        depot=depot,
        satellites=set(),
        stores={store},
        assignment={store: depot},
        routes={depot: repeat_round([[store]], 3)},
    )
    result = evaluate(data, net)
    expected_weekly = 3 * 2 * data.d(depot, store)
    assert result["route_km_per_week"] == pytest.approx(expected_weekly)
    assert result["annual_route_km"] == pytest.approx(52 * expected_weekly)
    assert result["n_trips_per_week"] == 3


def test_route_distance_and_hours(data):
    w = 223
    route = [1, 2, 3]
    expected = data.d(w, 1) + data.d(1, 2) + data.d(2, 3) + data.d(3, w)
    assert route_distance(data, w, route) == pytest.approx(expected)
    assert route_hours(data, w, route) == pytest.approx(expected / 50 + 3 * 0.5)


def test_validation_rejects_wrong_visit_count(data):
    depot, store = 379, 275
    net = Network(
        depot=depot,
        satellites=set(),
        stores={store},
        assignment={store: depot},
        routes={depot: [[store]]},  # only one visit instead of three
    )
    with pytest.raises(ValueError, match="exactly 3"):
        evaluate(data, net)


def test_validation_rejects_infeasible_route(data):
    w = 223
    far = max(data.stores, key=lambda i: data.d(w, i))
    net = Network(
        depot=w,
        satellites=set(),
        stores={far},
        assignment={far: w},
        routes={w: repeat_round([[far]], 3)},
    )
    with pytest.raises(ValueError, match="exceeds shift"):
        evaluate(data, net)


def test_validation_rejects_duplicate_store_in_route(data):
    depot, store = 379, 275
    net = Network(
        depot=depot,
        satellites=set(),
        stores={store},
        assignment={store: depot},
        routes={depot: repeat_round([[store, store]], 3)},
    )
    with pytest.raises(ValueError, match="more than once"):
        evaluate(data, net)


def test_tsp_matches_bruteforce(data):
    rng = random.Random(7)
    for n in range(1, 7):
        for _ in range(8):
            w = int(rng.choice(data.region_ids))
            stores = rng.sample([int(x) for x in data.region_ids], n)
            order = tsp_exact(data, w, stores)
            got = route_km(data, w, order)
            best = min(route_km(data, w, list(p)) for p in permutations(stores))
            assert got == pytest.approx(best, abs=1e-6)
            assert set(order) == set(stores)


def test_tsp_handles_store_in_warehouse_region(data):
    w = 403
    stores = [w, 1, 2, 3]
    order = tsp_exact(data, w, stores)
    assert set(order) == set(stores)
    assert len(order) == len(stores)


def test_optimize_routes_covers_all_stores(data):
    w = 223
    stores = [i for i in data.stores if feasible(data, w, [i])]
    routes = optimize_routes(data, w, stores)
    flat = [i for r in routes for i in r]
    assert sorted(flat) == sorted(stores)
    for r in routes:
        assert feasible(data, w, r)


def test_optimize_routes_rejects_unreachable_store(data):
    w = 223
    far = max(data.stores, key=lambda i: data.d(w, i))
    assert not feasible(data, w, [far])
    with pytest.raises(ValueError, match="cannot be served"):
        optimize_routes(data, w, [far])


def test_savings_merges_known_pair(data):
    w = 379
    # pick two stores that are close to each other and reachable from w
    candidates = [i for i in data.stores if feasible(data, w, [i])]
    pair = min(
        ((a, b) for a in candidates for b in candidates if a < b),
        key=lambda ab: data.d(ab[0], ab[1]) + data.d(w, ab[0]) + data.d(w, ab[1]),
    )
    routes = savings_routes(data, w, list(pair))
    assert len(routes) == 1


def test_baseline_is_feasible_and_profitable(data):
    net, result = build_baseline(data)
    assert result["profit"] > 0
    assert result["n_stores"] > 1
    assert len(net.satellites) >= 1
    again = evaluate(data, net)
    assert again["profit"] == pytest.approx(result["profit"])
