"""Data loading and basic derived quantities for the mini-supermarket network.

All monetary values are EUR per year unless stated otherwise.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import numpy as np
import pandas as pd

WEEKS_PER_YEAR = 52


@dataclass(frozen=True)
class Data:
    """Immutable container for the three input files."""

    regions: pd.DataFrame
    dist: pd.DataFrame
    params: dict[str, float]
    region_ids: np.ndarray
    region_pos: dict[int, int]
    dist_km: np.ndarray

    # ------------------------------------------------------------------ helpers
    def d(self, a: int, b: int) -> float:
        """Distance in km between two region ids."""
        return float(self.dist_km[self.region_pos[a], self.region_pos[b]])

    @property
    def stores(self) -> list[int]:
        """Regions whose store margin (gross profit - store cost) is positive."""
        m = self.regions["ExpGrossProfit"] - self.regions["ExpStoreCosts"]
        return [int(i) for i in self.regions.index[m > 0]]

    def margin(self, region: int) -> float:
        r = self.regions.loc[region]
        return float(r["ExpGrossProfit"] - r["ExpStoreCosts"])

    def gross_profit(self, region: int) -> float:
        return float(self.regions.loc[region, "ExpGrossProfit"])

    def store_cost(self, region: int) -> float:
        return float(self.regions.loc[region, "ExpStoreCosts"])

    def satellite_cost(self, region: int) -> float:
        return float(self.regions.loc[region, "ExpSatelliteCosts"])

    def depot_cost(self, region: int) -> float:
        return float(self.regions.loc[region, "ExpDepotCosts"])


def load_data(base: str | Path = "Projektdateien") -> Data:
    """Load Regions.csv, DistanceMatrix.csv and Parameter.csv.

    The three files must live in *base* (default: the folder shipped with the
    assignment).  Labels are validated and aligned explicitly so that a
    reordered CSV cannot silently produce wrong distances.
    """
    base = Path(base)
    regions = pd.read_csv(base / "Regions.csv", index_col="RegionId")
    dist = pd.read_csv(base / "DistanceMatrix.csv", index_col=0)
    dist.columns = dist.columns.astype(int)
    par = pd.read_csv(base / "Parameter.csv")
    params = {str(k): float(v) for k, v in zip(par["Parameter"], par["Value"])}

    required_region_cols = {
        "Leitregion",
        "Residents",
        "Lat",
        "Long",
        "ExpGrossProfit",
        "ExpStoreCosts",
        "ExpSatelliteCosts",
        "ExpDepotCosts",
    }
    missing = required_region_cols - set(regions.columns)
    if missing:
        raise ValueError(f"Regions.csv is missing columns: {sorted(missing)}")
    if regions.index.has_duplicates:
        raise ValueError("Regions.csv contains duplicate RegionId values")
    if regions.isna().any().any():
        raise ValueError("Regions.csv contains missing values")

    required_params = {
        "lkw_lieferungen_pro_woche_pro_zwischenlager",
        "lkw_fixkosten_pro_fahrt",
        "lkw_kosten_pro_km",
        "transporter_lieferungen_pro_woche_pro_markt",
        "transporter_fixkosten_pro_route",
        "transporter_kosten_pro_km",
        "transporter_schichtdauer",
        "transporter_servicezeit_pro_markt",
        "transporter_durchschnittsgeschwindigkeit_kmh",
    }
    missing_params = required_params - set(params)
    if missing_params:
        raise ValueError(f"Parameter.csv is missing parameters: {sorted(missing_params)}")

    if dist.shape != (len(regions), len(regions)):
        raise ValueError("distance matrix does not match the regions")
    if set(dist.index) != set(regions.index) or set(dist.columns) != set(regions.index):
        raise ValueError("distance matrix labels do not match Regions.csv")
    dist = dist.loc[regions.index, regions.index]
    arr = dist.to_numpy(dtype=float)
    if np.isnan(arr).any() or (arr < 0).any():
        raise ValueError("distance matrix contains NaN or negative values")
    if not np.allclose(arr, arr.T, atol=1e-6):
        raise ValueError("distance matrix is not symmetric")
    if not np.allclose(np.diag(arr), 0.0, atol=1e-6):
        raise ValueError("distance matrix diagonal must be zero")

    region_ids = regions.index.to_numpy(dtype=int)
    region_pos = {int(r): p for p, r in enumerate(region_ids)}

    return Data(regions, dist, params, region_ids, region_pos, arr)
