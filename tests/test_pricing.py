"""Tests for the exact pricing prototype (branch-and-price building block)."""
from __future__ import annotations

from itertools import combinations

import numpy as np
import pytest

from scm.data import Data, load_data
from scm.milp import solve_milp
from scm.pricing import solve_pricing
from scm.routes_pool import generate_pool
from scm.routing import feasible, route_cost, tsp_exact


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
    arr = data.dist_km[
        np.ix_(
            [data.region_pos[i] for i in ids],
            [data.region_pos[i] for i in ids],
        )
    ]
    return Data(
        regions=regions,
        dist=dist,
        params=dict(data.params),
        region_ids=np.array(ids, dtype=int),
        region_pos=pos,
        dist_km=arr,
    )


def test_pricing_matches_bruteforce(data):
    small = _small_data(data)
    depot = 379
    pool = generate_pool(small, [depot], pair_threshold_km=200)
    lp = solve_milp(
        small, pool, depot, time_limit=30, verbose=False, relax_integrality=True
    )
    assert lp.cover_duals is not None
    assert lp.link_duals is not None

    stores = [i for i in small.stores if i != depot]
    best = None
    for k in range(1, len(stores) + 1):
        for subset in combinations(stores, k):
            order = tsp_exact(small, depot, list(subset))
            if not feasible(small, depot, order):
                continue
            prize = sum(
                lp.cover_duals.get(i, 0.0)
                + lp.link_duals.get((i, depot), 0.0)
                for i in subset
            )
            value = 52.0 * route_cost(small, depot, order) + prize
            if best is None or value < best:
                best = value

    result = solve_pricing(
        small,
        depot,
        lp.cover_duals,
        lp.link_duals,
        (lp.open_duals or {}).get(depot, 0.0),
        time_limit=30,
        verbose=False,
    )
    assert result.status == "kOptimal"
    assert result.objective == pytest.approx(best, abs=1e-6)
    assert result.reduced_cost == pytest.approx(
        -result.objective - (lp.open_duals or {}).get(depot, 0.0), abs=1e-9
    )
    assert set(result.order) == set(result.stores)
    assert feasible(small, depot, list(result.order))


def test_dfj_pricing_matches_mtz(data):
    from scm.pricing import solve_pricing_dfj

    small = _small_data(data, n_stores=6)
    depot = 379
    pool = generate_pool(small, [depot], pair_threshold_km=300)
    lp = solve_milp(
        small, pool, depot, time_limit=30, verbose=False, relax_integrality=True
    )
    mtz = solve_pricing(
        small,
        depot,
        lp.cover_duals,
        lp.link_duals,
        (lp.open_duals or {}).get(depot, 0.0),
        time_limit=30,
    )
    dfj = solve_pricing_dfj(
        small,
        depot,
        lp.cover_duals,
        lp.link_duals,
        (lp.open_duals or {}).get(depot, 0.0),
        time_limit=30,
    )
    assert mtz.status == "kOptimal"
    assert dfj.status == "kOptimal"
    assert dfj.objective == pytest.approx(mtz.objective, abs=1e-6)


def test_positive_prize_pricing_matches_bruteforce(data):
    from scm.pricing import solve_pricing_positive

    small = _small_data(data, n_stores=6)
    depot = 379
    stores = [i for i in small.stores if i != depot]
    cover = {i: -10_000.0 for i in stores}
    link = {(i, depot): 0.0 for i in stores}
    result = solve_pricing_positive(
        small, depot, cover, link, 0.0, max_positive=13
    )

    best = 0.0
    for k in range(1, len(stores) + 1):
        for subset in combinations(stores, k):
            order = tsp_exact(small, depot, list(subset))
            if not feasible(small, depot, order):
                continue
            value = 52.0 * route_cost(small, depot, order) - 10_000.0 * len(subset)
            best = min(best, value)
    assert result.status == "kOptimal"
    assert result.objective == pytest.approx(best, abs=1e-6)


def test_dfs_and_scip_pricing_match_mtz(data):
    from scm.pricing import solve_pricing_dfs, solve_pricing_scip

    small = _small_data(data, n_stores=5)
    depot = 379
    pool = generate_pool(small, [depot], pair_threshold_km=300)
    lp = solve_milp(
        small, pool, depot, time_limit=30, verbose=False, relax_integrality=True
    )
    mtz = solve_pricing(
        small,
        depot,
        lp.cover_duals,
        lp.link_duals,
        (lp.open_duals or {}).get(depot, 0.0),
        time_limit=30,
    )
    dfs = solve_pricing_dfs(
        small,
        depot,
        lp.cover_duals,
        lp.link_duals,
        (lp.open_duals or {}).get(depot, 0.0),
        time_limit=30,
    )
    scip = solve_pricing_scip(
        small,
        depot,
        lp.cover_duals,
        lp.link_duals,
        (lp.open_duals or {}).get(depot, 0.0),
        time_limit=30,
    )
    assert dfs.status == "kOptimal"
    assert scip.status == "optimal"
    assert dfs.objective == pytest.approx(mtz.objective, abs=1e-6)
    assert scip.objective == pytest.approx(mtz.objective, abs=1e-6)
