"""Reporting helpers: profit bridge, network map and scenario charts."""
from __future__ import annotations

from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
from matplotlib.ticker import FuncFormatter

from .data import Data
from .network import Network, evaluate

# German labels for the profit components.
COMPONENTS = (
    ("gross_profit", "Rohertrag"),
    ("store_costs", "Marktkosten"),
    ("depot_cost", "Depotkosten"),
    ("satellite_costs", "Satellitenkosten"),
    ("truck_costs", "Lkw-Kosten"),
    ("transporter_costs", "Transporterkosten"),
)


def _de(value: float, digits: int = 3, sign: bool = False) -> str:
    """Format a number with a German decimal comma."""
    spec = f"{'+' if sign else ''}.{digits}f"
    return format(value, spec).replace(".", ",")


def _comma_axis(ax: plt.Axes) -> None:
    ax.yaxis.set_major_formatter(
        FuncFormatter(lambda value, _pos: _de(value, 1))
    )


def profit_bridge(
    baseline: dict[str, float], optimized: dict[str, float]
) -> list[tuple[str, float]]:
    """Return signed contributions that sum to the profit difference.

    Profit = gross - store - depot - satellite - truck - transporter, so a
    positive delta in a cost component contributes negatively.
    """
    bridge: list[tuple[str, float]] = []
    for key, label in COMPONENTS:
        delta = optimized[key] - baseline[key]
        value = -delta if key != "gross_profit" else delta
        bridge.append((label, 0.0 if abs(value) < 1e-9 else value))
    total = optimized["profit"] - baseline["profit"]
    if abs(sum(v for _, v in bridge) - total) > 1e-6:
        raise ValueError("profit bridge does not add up")
    return bridge


def plot_profit_bridge(
    baseline: dict[str, float],
    optimized: dict[str, float],
    path: str | Path,
    *,
    title: str = "Gewinnbrücke: Baseline → Optimierung",
) -> None:
    bridge = profit_bridge(baseline, optimized)
    labels = ["Baseline"] + [label for label, _ in bridge] + ["Optimiert"]
    values = [baseline["profit"] / 1e6] + [v / 1e6 for _, v in bridge] + [
        optimized["profit"] / 1e6
    ]

    fig, ax = plt.subplots(figsize=(11, 5.2))
    running = baseline["profit"] / 1e6
    ax.bar(0, running, color="#4c72b0", width=0.62)
    ax.text(0, running + 0.02, f"{_de(running)}", ha="center", va="bottom", fontsize=9)

    for i, (label, value) in enumerate(bridge, start=1):
        delta = value / 1e6
        bottom = running if delta >= 0 else running + delta
        color = "#55a868" if delta >= 0 else "#c44e52"
        ax.bar(i, abs(delta), bottom=bottom, color=color, width=0.62)
        ax.text(
            i,
            max(running, running + delta) + 0.015,
            f"{_de(delta, sign=True)}" if abs(delta) >= 0.0005 else "0,000",
            ha="center",
            va="bottom",
            fontsize=8,
        )
        running += delta

    ax.bar(len(labels) - 1, optimized["profit"] / 1e6, color="#4c72b0", width=0.62)
    ax.text(
        len(labels) - 1,
        optimized["profit"] / 1e6 + 0.02,
        f"{_de(optimized['profit']/1e6)}",
        ha="center",
        va="bottom",
        fontsize=9,
    )
    ax.set_xticks(range(len(labels)))
    ax.set_xticklabels(labels, rotation=25, ha="right", fontsize=9)
    ax.set_ylabel("Jahresgewinn in Mio. EUR")
    ax.set_title(title)
    ax.grid(axis="y", alpha=0.25)
    _comma_axis(ax)
    ax.set_ylim(0, max(values + [baseline["profit"] / 1e6]) * 1.18)
    fig.tight_layout()
    fig.savefig(path, dpi=200)
    plt.close(fig)


def plot_network(
    data: Data,
    net: Network,
    path: str | Path,
    *,
    title: str | None = None,
) -> None:
    """Draw the regions, the opened stores/warehouses and the weekly routes."""
    regions = data.regions
    fig, ax = plt.subplots(figsize=(8.2, 9.4))

    ax.scatter(
        regions["Long"],
        regions["Lat"],
        s=5,
        c="#d9d9d9",
        linewidths=0,
        label="Regionen",
        zorder=1,
    )

    # routes first, so that markers stay visible
    for warehouse, routes in net.routes.items():
        wx, wy = _xy(data, warehouse)
        for route in routes:
            xs = [wx] + [_xy(data, i)[0] for i in route] + [wx]
            ys = [wy] + [_xy(data, i)[1] for i in route] + [wy]
            ax.plot(xs, ys, color="#7f7f7f", linewidth=0.55, alpha=0.45, zorder=2)

    store_x = [regions.loc[i, "Long"] for i in sorted(net.stores)]
    store_y = [regions.loc[i, "Lat"] for i in sorted(net.stores)]
    ax.scatter(
        store_x,
        store_y,
        s=24,
        c="#2ca02c",
        edgecolors="white",
        linewidths=0.4,
        label=f"Märkte ({len(net.stores)})",
        zorder=3,
    )

    if net.satellites:
        sx = [regions.loc[i, "Long"] for i in sorted(net.satellites)]
        sy = [regions.loc[i, "Lat"] for i in sorted(net.satellites)]
        ax.scatter(
            sx,
            sy,
            s=95,
            c="#ff7f0e",
            marker="s",
            edgecolors="black",
            linewidths=0.6,
            label=f"Satelliten ({len(net.satellites)})",
            zorder=4,
        )
        for i in sorted(net.satellites):
            ax.annotate(
                str(i),
                (regions.loc[i, "Long"], regions.loc[i, "Lat"]),
                xytext=(4, 4),
                textcoords="offset points",
                fontsize=7,
                zorder=5,
            )

    dx, dy = _xy(data, net.depot)
    ax.scatter(
        [dx],
        [dy],
        s=150,
        c="#d62728",
        marker="*",
        edgecolors="black",
        linewidths=0.6,
        label="Depot",
        zorder=6,
    )
    ax.annotate(
        f"Depot {net.depot}",
        (dx, dy),
        xytext=(6, 6),
        textcoords="offset points",
        fontsize=8,
        fontweight="bold",
        zorder=7,
    )

    ax.set_xlabel("Längengrad")
    ax.set_ylabel("Breitengrad")
    ax.set_title(title or "Netzwerk: Depot, Satelliten, Märkte und Wochenrouten")
    ax.legend(loc="lower left", fontsize=8, framealpha=0.9)
    ax.grid(alpha=0.2)
    fig.tight_layout()
    fig.savefig(path, dpi=200)
    plt.close(fig)


def _xy(data: Data, region: int) -> tuple[float, float]:
    row = data.regions.loc[region]
    return float(row["Long"]), float(row["Lat"])


def plot_scenario_bars(
    summary: dict[str, dict[str, float]],
    path: str | Path,
    *,
    title: str = "Robustheit: Gewinn je Szenario",
) -> None:
    """Bar chart comparing the existing network with the re-optimised network."""
    names = list(summary)
    existing = [summary[n]["existing_profit"] / 1e6 for n in names]
    optimized = [summary[n]["optimized_profit"] / 1e6 for n in names]
    x = np.arange(len(names))
    width = 0.36

    fig, ax = plt.subplots(figsize=(9, 4.8))
    ax.bar(x - width / 2, existing, width, label="Bestehendes Netz", color="#4c72b0")
    ax.bar(x + width / 2, optimized, width, label="Neu optimiert", color="#55a868")
    for i, (a, b) in enumerate(zip(existing, optimized)):
        ax.text(i - width / 2, a + 0.02, f"{_de(a)}", ha="center", va="bottom", fontsize=8)
        ax.text(i + width / 2, b + 0.02, f"{_de(b)}", ha="center", va="bottom", fontsize=8)
    ax.set_xticks(x)
    ax.set_xticklabels(names)
    ax.set_ylabel("Jahresgewinn in Mio. EUR")
    ax.set_title(title)
    ax.legend(fontsize=8)
    ax.grid(axis="y", alpha=0.25)
    _comma_axis(ax)
    fig.tight_layout()
    fig.savefig(path, dpi=200)
    plt.close(fig)


def scenario_breakdown(data: Data, net: Network) -> dict[str, float]:
    """Evaluate *net* under the (already adjusted) *data*."""
    return evaluate(data, net)
