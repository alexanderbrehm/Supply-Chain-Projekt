"""Small serialisation helpers for networks and result files."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .network import Network


def network_to_dict(net: Network) -> dict[str, Any]:
    return {
        "depot": int(net.depot),
        "satellites": sorted(int(s) for s in net.satellites),
        "stores": sorted(int(i) for i in net.stores),
        "assignment": {str(int(k)): int(v) for k, v in sorted(net.assignment.items())},
        "routes": {
            str(int(w)): [[int(i) for i in route] for route in routes]
            for w, routes in sorted(net.routes.items())
        },
    }


def network_from_dict(raw: dict[str, Any]) -> Network:
    return Network(
        depot=int(raw["depot"]),
        satellites={int(s) for s in raw["satellites"]},
        stores={int(i) for i in raw["stores"]},
        assignment={int(k): int(v) for k, v in raw["assignment"].items()},
        routes={
            int(w): [[int(i) for i in route] for route in routes]
            for w, routes in raw["routes"].items()
        },
    )


def load_network(path: str | Path) -> Network:
    raw = json.loads(Path(path).read_text())
    if "network" in raw:
        raw = raw["network"]
    return network_from_dict(raw)


def save_json(path: str | Path, payload: dict[str, Any]) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False))


def network_signature(net: Network) -> dict[str, Any]:
    """Canonical representation used to decide whether two networks differ."""
    return {
        "depot": int(net.depot),
        "satellites": sorted(int(s) for s in net.satellites),
        "stores": sorted(int(i) for i in net.stores),
        "assignment": {str(int(k)): int(v) for k, v in sorted(net.assignment.items())},
        "routes": {
            str(int(w)): sorted(tuple(int(i) for i in r) for r in routes)
            for w, routes in sorted(net.routes.items())
        },
    }


def same_network(a: Network, b: Network) -> bool:
    return network_signature(a) == network_signature(b)
