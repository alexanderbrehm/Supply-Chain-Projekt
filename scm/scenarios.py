"""Robustness scenarios and re-pricing of an existing route pool.

The assignment defines two scenarios:

* pessimistic: gross profit -10 %, km costs of trucks and transporters +10 %,
* optimistic:  gross profit +10 %, km costs of trucks and transporters -10 %.

Fixed costs per trip/route stay unchanged.  Because the route feasibility
(distance, speed, service time, shift length) is unaffected by the scenario,
an existing route pool can be re-priced instead of rebuilt.
"""
from __future__ import annotations

from dataclasses import dataclass

import pandas as pd

from .data import Data
from .routes_pool import Route


@dataclass(frozen=True)
class Scenario:
    name: str
    gross_multiplier: float
    km_multiplier: float

    @property
    def label(self) -> str:
        return (
            f"{self.name}: Rohertrag x{self.gross_multiplier:.2f}, "
            f"km-Kosten x{self.km_multiplier:.2f}"
        )


PESSIMISTIC = Scenario("pessimistisch", 0.90, 1.10)
OPTIMISTIC = Scenario("optimistisch", 1.10, 0.90)
SCENARIOS = (PESSIMISTIC, OPTIMISTIC)


def apply_scenario(data: Data, scenario: Scenario) -> Data:
    """Return a copy of *data* with scenario-adjusted profits and km costs."""
    if scenario.gross_multiplier <= 0 or scenario.km_multiplier <= 0:
        raise ValueError("scenario multipliers must be positive")

    regions = data.regions.copy(deep=True)
    regions["ExpGrossProfit"] = regions["ExpGrossProfit"] * scenario.gross_multiplier

    params = dict(data.params)
    params["lkw_kosten_pro_km"] = params["lkw_kosten_pro_km"] * scenario.km_multiplier
    params["transporter_kosten_pro_km"] = (
        params["transporter_kosten_pro_km"] * scenario.km_multiplier
    )

    return Data(
        regions=regions,
        dist=data.dist,
        params=params,
        region_ids=data.region_ids,
        region_pos=data.region_pos,
        dist_km=data.dist_km,
    )


def reprice_pool(data: Data, pool: list[Route]) -> list[Route]:
    """Recompute route costs for *data* while keeping the same route sets.

    ``Route.km`` is the length of the optimal (or heuristic) tour that was
    used when the route was created.  Since the scenario only changes cost
    coefficients, the same tour remains feasible and its length is unchanged.
    """
    fixed = float(data.params["transporter_fixkosten_pro_route"])
    per_km = float(data.params["transporter_kosten_pro_km"])
    return [
        Route(
            warehouse=r.warehouse,
            stores=r.stores,
            cost=fixed + per_km * r.km,
            km=r.km,
            hours=r.hours,
        )
        for r in pool
    ]
