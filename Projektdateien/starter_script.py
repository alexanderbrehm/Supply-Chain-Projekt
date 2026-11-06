"""
Starter script: mini-supermarket network

What it does
  1. Loads the three data files from the same folder as this script
       Regions.csv, DistanceMatrix.csv, Parameter.csv
  2. Checks them and prints a short overview
  3. Evaluates ONE tiny example network (depot and one store), so you can check
     your own profit calculation against a known case

What it does NOT do: build a good network or general routes. That is your task.

Run:  python starter.py
"""
from pathlib import Path

import matplotlib.pyplot as plt
import pandas as pd

WEEKS_PER_YEAR = 52


def load(name, **kwargs):
    path = Path(__file__).parent / name
    if not path.exists():
        raise SystemExit(f"Missing file {path}. Copy the data files from Stud.IP into the same folder as this script.")
    return pd.read_csv(path, **kwargs)


# ---------------------------------------------------------------- 1. load and check
regions = load("Regions.csv", index_col="RegionId")   # one row per region
dist = load("DistanceMatrix.csv", index_col=0)         # km between region centroids
dist.columns = dist.columns.astype(int)                # header cells are read as text

par = load("Parameter.csv")
params = dict(zip(par["Parameter"], par["Value"]))      # e.g. params["lkw_kosten_pro_km"]

assert dist.shape == (len(regions), len(regions)), "distance matrix does not match the regions"
assert (dist - dist.T).abs().max().max() < 1e-6, "distance matrix is not symmetric"

# gross profit minus store costs, before any logistics costs
regions["StoreMargin"] = regions["ExpGrossProfit"] - regions["ExpStoreCosts"]

# ---------------------------------------------------------------- 2. overview
print(f"Regions: {len(regions)}, with positive margin: {(regions['StoreMargin'] > 0).sum()}")
print(f"Largest distance: {dist.to_numpy().max():.0f} km")
print("\nTop 5 regions by margin:")
print(regions.nlargest(5, "StoreMargin")[["Leitregion", "ExpGrossProfit", "ExpStoreCosts", "StoreMargin"]])


# ---------------------------------------------------------------- 3. a tiny example
def van_route_hours(round_trip_km, stops):
    """Duration of one van route: driving time + service time."""
    driving = round_trip_km / params["transporter_durchschnittsgeschwindigkeit_kmh"]
    service = stops * params["transporter_servicezeit_pro_markt"] / 60
    return driving + service


# Smallest possible network: the depot and ONE store in the same region, no satellite.
region = regions["StoreMargin"].idxmax()
km = dist.loc[region, region]                          # 0 km: same region
routes = WEEKS_PER_YEAR * params["transporter_lieferungen_pro_woche_pro_markt"]
van_costs = routes * (params["transporter_fixkosten_pro_route"]
                      + params["transporter_kosten_pro_km"] * 2 * km)
profit = (regions.loc[region, "ExpGrossProfit"] - regions.loc[region, "ExpStoreCosts"]
          - regions.loc[region, "ExpDepotCosts"] - van_costs)

print(f"\nExample: depot and one store in region {region}")
print(f"  route duration  {van_route_hours(2 * km, 1):.1f} h (limit {params['transporter_schichtdauer']:.0f} h)")
print(f"  van costs       {van_costs:.0f} EUR  ({routes:.0f} routes/year)")
print(f"  annual profit   {profit:.0f} EUR")

# %% 4. a first simple chart
# Run this cell (VS Code: "Run Cell" / Shift+Enter) to see it directly in VS Code.
plt.scatter(regions["ExpStoreCosts"], regions["ExpGrossProfit"])
plt.xlabel("ExpStoreCosts")
plt.ylabel("ExpGrossProfit")
plt.title("Profit vs. costs by region")
plt.show()

# TODO (Task 1): write your own function that computes the annual profit of ANY network
# (depot, satellites, which warehouse serves which store, routes) and check it against
# the example above.
# %%
