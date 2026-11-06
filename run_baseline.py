"""Run the analytical baseline and print a profit breakdown."""
from __future__ import annotations

import time

from scm.baseline import build_baseline
from scm.data import load_data
from scm.io import network_to_dict, save_json


def main() -> None:
    t0 = time.perf_counter()
    data = load_data("Projektdateien")
    total_margin = sum(data.margin(i) for i in data.stores)
    print(f"Loaded {len(data.regions)} regions; {len(data.stores)} stores with positive margin.")
    print(f"Total positive store margin: {total_margin/1e6:.3f} M EUR/year\n")

    net, result = build_baseline(data, verbose=False)
    unserved = set(data.stores) - net.stores
    unserved_margin = sum(data.margin(i) for i in unserved)

    print("Baseline network")
    print(f"  depot:            {net.depot}")
    print(f"  satellites:       {sorted(net.satellites)}")
    print(f"  stores opened:    {result['n_stores']} of {len(data.stores)}")
    print(f"  stores unserved:  {len(unserved)}  (margin {unserved_margin/1e6:.3f} M EUR)")
    print(f"  trips per week:   {result['n_trips_per_week']}")
    print(f"  route km / week:  {result['route_km_per_week']:.0f}")
    print(f"  annual profit:    {result['profit']/1e6:.3f} M EUR")
    print("\nBreakdown")
    for k in (
        "gross_profit",
        "store_costs",
        "depot_cost",
        "satellite_costs",
        "truck_costs",
        "transporter_costs",
        "profit",
    ):
        print(f"  {k:20s} {result[k]/1e6:10.3f} M EUR")
    print(f"\nElapsed: {time.perf_counter()-t0:.1f} s")

    save_json(
        "results/baseline.json",
        {
            "network": network_to_dict(net),
            "breakdown": result,
            "runtime_s": time.perf_counter() - t0,
        },
    )
    print("saved results/baseline.json")


if __name__ == "__main__":
    main()
