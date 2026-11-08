"""Tests for the strong linking constraints and the depot search."""
from __future__ import annotations

import numpy as np
import pytest

from scm.data import Data, load_data
from scm.depot_search import depot_lp_bounds, search_depots
from scm.milp import solve_milp
from scm.network import evaluate
from scm.routes_pool import generate_pool
from scm.routing import feasible


@pytest.fixture(scope="module")
def data():
    return load_data("Projektdateien")


def _subset(data: Data, ids: list[int]) -> Data:
    pos = {int(r): k for k, r in enumerate(ids)}
    idx = [data.region_pos[i] for i in ids]
    return Data(
        regions=data.regions.loc[ids].copy(),
        dist=data.dist.loc[ids, ids].copy(),
        params=dict(data.params),
        region_ids=np.array(ids, dtype=int),
        region_pos=pos,
        dist_km=data.dist_km[np.ix_(idx, idx)],
    )


@pytest.fixture(scope="module")
def medium(data):
    """Ten stores around region 379 plus four further warehouse candidates."""
    stores = sorted(
        (i for i in data.stores if feasible(data, 379, [i])), key=lambda i: data.d(379, i)
    )[:10]
    extra = [w for w in (122, 271, 419, 664) if w not in stores and w != 379]
    return _subset(data, [379] + [i for i in stores if i != 379] + extra)


def test_strong_linking_keeps_optimum_and_tightens_lp(medium):
    whs = [int(w) for w in medium.region_ids]
    pool = generate_pool(medium, whs, pair_threshold_km=100)
    weak = solve_milp(medium, pool, 379, time_limit=60, verbose=False, strong_linking=False)
    strong = solve_milp(medium, pool, 379, time_limit=60, verbose=False)
    assert strong.breakdown["profit"] == pytest.approx(weak.breakdown["profit"], abs=1e-4)
    lp_weak = solve_milp(
        medium, pool, 379, verbose=False, relax_integrality=True, strong_linking=False
    )
    lp_strong = solve_milp(medium, pool, 379, verbose=False, relax_integrality=True)
    assert strong.breakdown["profit"] <= lp_strong.objective + 1e-4
    assert lp_strong.objective <= lp_weak.objective + 1e-4


def test_depot_lp_bounds_are_upper_bounds(medium):
    whs = [int(w) for w in medium.region_ids]
    pool = generate_pool(medium, whs, pair_threshold_km=100)
    bounds, _ = depot_lp_bounds(medium, pool, whs)
    assert [b.bound for b in bounds] == sorted((b.bound for b in bounds), reverse=True)
    for b in bounds[:4]:
        res = solve_milp(medium, pool, b.depot, time_limit=60, verbose=False)
        assert res.breakdown["profit"] <= b.bound + 1e-4


def test_search_depots_matches_enumeration(medium):
    whs = [int(w) for w in medium.region_ids]
    pool = generate_pool(medium, whs, pair_threshold_km=100)
    result = search_depots(medium, pool, whs, time_limit=60)
    usable = sorted({r.warehouse for r in pool})
    best = max(
        solve_milp(medium, pool, d, time_limit=60, verbose=False).breakdown["profit"]
        for d in usable
    )
    assert result.best.breakdown["profit"] == pytest.approx(best, abs=1e-4)
    assert result.certified
    assert evaluate(medium, result.best.network)["profit"] == pytest.approx(best, abs=1e-4)
