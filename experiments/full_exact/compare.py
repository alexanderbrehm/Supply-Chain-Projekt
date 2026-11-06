"""Compare the expanded 640-candidate run with the 202-candidate reference."""
from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def main() -> None:
    ref = json.loads((ROOT / "results/milp_200.json").read_text())
    exp_path = ROOT / "experiments/full_exact/milp_640_integer_timeout.json"
    if not exp_path.exists():
        raise SystemExit("milp_640_integer_timeout.json is not available yet")
    exp = json.loads(exp_path.read_text())
    rp = ref["breakdown"]["profit"]
    ep = exp["breakdown"]["profit"]
    print(f"202 candidates: {rp:,.3f} EUR, gap={ref['mip_gap']:.4%}, status={ref['status']}")
    print(f"640 candidates: {ep:,.3f} EUR, gap={exp['mip_gap']:.4%}, status={exp['status']}")
    print(f"delta: {ep-rp:+,.3f} EUR")
    print(f"stores: {len(ref['stores'])} -> {len(exp['network']['stores'])}")
    print(f"satellites: {ref['satellites']} -> {exp['network']['satellites']}")
    print(f"trips: {sum(len(v) for v in ref['routes'].values())} -> "
          f"{sum(len(v) for v in exp['network']['routes'].values())}")
    if exp["mip_gap"] == 0 and exp["status"] == "kOptimal":
        print("The expanded model is solved to proven optimality for its route pool.")


if __name__ == "__main__":
    main()
