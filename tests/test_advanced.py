"""Tests for scenarios, serialisation, analysis and the MILP on a small instance."""
from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path

import numpy as np
import pytest

from scm.analysis import profit_bridge
from scm.data import Data, load_data
from scm.io import load_network, network_from_dict, network_to_dict, same_network
from scm.milp import solve_milp
from scm.network import Network, evaluate
from scm.routes_pool import generate_pool
from scm.routing import feasible
from scm.scenarios import OPTIMISTIC, PESSIMISTIC, apply_scenario, reprice_pool


@pytest.fixture(scope="module")
def data():
    return load_data("Projektdateien")


def _small_data(data: Data, n_stores: int = 4) -> Data:
    depot = 379
    stores = [i for i in data.stores if feasible(data, depot, [i])][:n_stores]
    ids = [depot] + [i for i in stores if i != depot]
    regions = data.regions.loc[ids].copy()
    dist = data.dist.loc[ids, ids].copy()
    pos = {int(r): k for k, r in enumerate(ids)}
    arr = data.dist_km[np.ix_([data.region_pos[i] for i in ids], [data.region_pos[i] for i in ids])]
    return Data(
        regions=regions,
        dist=dist,
        params=dict(data.params),
        region_ids=np.array(ids, dtype=int),
        region_pos=pos,
        dist_km=arr,
    )


def test_scenario_changes_only_defined_components(data):
    p = PESSIMISTIC
    s = apply_scenario(data, p)
    assert s.params["lkw_fixkosten_pro_fahrt"] == data.params["lkw_fixkosten_pro_fahrt"]
    assert s.params["transporter_fixkosten_pro_route"] == data.params[
        "transporter_fixkosten_pro_route"
    ]
    assert s.params["lkw_kosten_pro_km"] == pytest.approx(
        data.params["lkw_kosten_pro_km"] * p.km_multiplier
    )
    assert s.params["transporter_kosten_pro_km"] == pytest.approx(
        data.params["transporter_kosten_pro_km"] * p.km_multiplier
    )
    i = data.stores[0]
    assert s.gross_profit(i) == pytest.approx(data.gross_profit(i) * p.gross_multiplier)
    assert s.store_cost(i) == data.store_cost(i)


def test_reprice_pool_keeps_routes_and_updates_km_cost(data):
    small = _small_data(data)
    pool = generate_pool(small, [379], pair_threshold_km=200)
    assert pool
    scenario = replace(
        small,
        params={
            **small.params,
            "transporter_kosten_pro_km": small.params["transporter_kosten_pro_km"] * 1.1,
        },
    )
    repriced = reprice_pool(scenario, pool)
    assert len(repriced) == len(pool)
    for old, new in zip(pool, repriced):
        assert old.warehouse == new.warehouse
        assert old.stores == new.stores
        assert new.cost == pytest.approx(
            scenario.params["transporter_fixkosten_pro_route"]
            + scenario.params["transporter_kosten_pro_km"] * old.km
        )


def test_network_json_roundtrip(data):
    small = _small_data(data)
    pool = generate_pool(small, [379], pair_threshold_km=200)
    result = solve_milp(small, pool, 379, time_limit=30, verbose=False)
    raw = network_to_dict(result.network)
    again = network_from_dict(raw)
    assert same_network(result.network, again)
    assert evaluate(small, again)["profit"] == pytest.approx(
        result.breakdown["profit"], abs=1e-6
    )


def test_profit_bridge_adds_up(data):
    small = _small_data(data)
    pool = generate_pool(small, [379], pair_threshold_km=200)
    result = solve_milp(small, pool, 379, time_limit=30, verbose=False)
    empty = {
        "gross_profit": 0.0,
        "store_costs": 0.0,
        "depot_cost": 0.0,
        "satellite_costs": 0.0,
        "truck_costs": 0.0,
        "transporter_costs": 0.0,
        "profit": 0.0,
    }
    bridge = profit_bridge(empty, result.breakdown)
    assert sum(v for _, v in bridge) == pytest.approx(result.breakdown["profit"])


def test_milp_small_instance_is_feasible_and_optimal(data):
    small = _small_data(data, n_stores=4)
    pool = generate_pool(small, [379], pair_threshold_km=200)
    result = solve_milp(small, pool, 379, time_limit=30, verbose=False)
    assert result.breakdown["profit"] == pytest.approx(result.objective, abs=1e-4)
    assert result.mip_gap <= 1e-6
    again = evaluate(small, result.network)
    assert again["profit"] == pytest.approx(result.breakdown["profit"], abs=1e-6)
    assert again["n_stores"] >= 1


def test_same_network_distinguishes_route_order():
    a = Network(
        depot=379,
        satellites=set(),
        stores={18, 19},
        assignment={18: 379, 19: 379},
        routes={379: [[18, 19]]},
    )
    b = Network(
        depot=379,
        satellites=set(),
        stores={18, 19},
        assignment={18: 379, 19: 379},
        routes={379: [[19, 18]]},
    )
    assert not same_network(a, b)


def test_load_network_accepts_baseline_wrapper(tmp_path, data):
    small = _small_data(data)
    pool = generate_pool(small, [379], pair_threshold_km=200)
    result = solve_milp(small, pool, 379, time_limit=30, verbose=False)
    path = tmp_path / "baseline_like.json"
    path.write_text(json.dumps({"network": network_to_dict(result.network)}))
    loaded = load_network(path)
    assert same_network(loaded, result.network)


def test_milp_respects_configured_visit_count(data):
    small = _small_data(data, n_stores=4)
    visits = 2
    small2 = replace(
        small,
        params={
            **small.params,
            "transporter_lieferungen_pro_woche_pro_markt": float(visits),
        },
    )
    pool = generate_pool(small2, [379], pair_threshold_km=200)
    result = solve_milp(small2, pool, 379, time_limit=30, verbose=False)
    evaluated = evaluate(small2, result.network)
    assert evaluated["n_stores"] >= 1
    counts = {i: 0 for i in result.network.stores}
    for routes in result.network.routes.values():
        for route in routes:
            for i in route:
                counts[i] += 1
    assert set(counts.values()) == {visits}


def test_milp_filters_routes_with_negative_stores(data):
    small = _small_data(data, n_stores=5)
    stores = [i for i in small.stores if i != 379]
    dropped = stores[0]
    regions = small.regions.copy(deep=True)
    regions.loc[dropped, "ExpGrossProfit"] = regions.loc[dropped, "ExpStoreCosts"] - 1.0
    small_neg = replace(small, regions=regions)
    assert dropped not in small_neg.stores
    pool = generate_pool(small, [379], pair_threshold_km=200)
    assert any(dropped in route.stores for route in pool)
    result = solve_milp(small_neg, pool, 379, time_limit=30, verbose=False)
    assert dropped not in result.network.stores
    evaluate(small_neg, result.network)


def test_milp_warm_start_is_feasible(data):
    small = _small_data(data, n_stores=5)
    pool = generate_pool(small, [379], pair_threshold_km=200)
    first = solve_milp(small, pool, 379, time_limit=30, verbose=False)
    second = solve_milp(
        small,
        pool,
        379,
        time_limit=30,
        verbose=False,
        initial=first.network,
    )
    assert second.breakdown["profit"] >= first.breakdown["profit"] - 1e-6
    assert second.mip_gap <= 1e-6


def test_candidate_selection_matches_documented_counts(data):
    from run_milp import select_candidates

    candidates = select_candidates(data, 379, 200)
    assert len(candidates) == 202
    assert {379, 81, 149, 274, 419, 582} <= set(candidates)
    smaller = select_candidates(data, 379, 104)
    assert len(smaller) == 108


def test_german_number_formatting():
    from make_report import _eur, _money, _pct

    assert _money(2_400_886.572) == "2,401 Mio. EUR"
    assert _pct(0.0126408907) == "1,26 %"
    assert _eur(59_291.8456, sign=True) == "+59.292 EUR"
    assert _eur(-1234.4) == "-1.234 EUR"


def test_lp_relaxation_is_an_upper_bound(data):
    small = _small_data(data, n_stores=4)
    pool = generate_pool(small, [379], pair_threshold_km=200)
    milp = solve_milp(small, pool, 379, time_limit=30, verbose=False)
    lp = solve_milp(
        small, pool, 379, time_limit=30, verbose=False, relax_integrality=True
    )
    assert lp.objective >= milp.objective - 1e-6


def test_relaxed_route_bound_is_an_upper_bound(data):
    small = _small_data(data, n_stores=4)
    pool = generate_pool(small, [379], pair_threshold_km=200)
    milp = solve_milp(small, pool, 379, time_limit=30, verbose=False)
    relaxed = solve_milp(
        small, pool, 379, time_limit=30, verbose=False, relax_lambda=True
    )
    assert relaxed.bound_is_dual
    assert relaxed.objective >= milp.objective - 1e-6


def test_reference_640_result_is_feasible(data):
    raw = json.loads(Path("results/milp_640.json").read_text())
    net = load_network("results/milp_640.json")
    result = evaluate(data, net)
    assert result["profit"] == pytest.approx(raw["breakdown"]["profit"], abs=1e-6)
    assert len(net.stores) == 115
    assert sorted(net.satellites) == [84, 122, 271, 419, 574]
    assert result["n_trips_per_week"] == 57
    assert raw["status"] == "kOptimal" and raw["mip_gap"] == 0
