from __future__ import annotations

import argparse
import json
from pathlib import Path
import subprocess
import sys


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Run the two-stage no-wait then bounded-wait reservoir campaign."
    )
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--progress", action="store_true")
    parser.add_argument("--frontend-live", action="store_true")
    parser.add_argument("--gurobi-output", action="store_true")
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path("benchmarks/output/ddd_reservoir_arc_flow"),
    )
    args = parser.parse_args()
    config = dict(json.loads(args.config.read_text(encoding="utf-8")))
    campaign = str(config["campaign_id"])
    base = [
        sys.executable,
        str(Path(__file__).with_name("run_ddd_reservoir_arc_flow.py")),
        "--config",
        str(args.config),
        "--output-dir",
        str(args.output_dir),
    ]
    flags = []
    if args.progress:
        flags.append("--progress")
    if args.frontend_live:
        flags.append("--frontend-live")
    if args.gurobi_output:
        flags.append("--gurobi-output")
    no_wait_id = f"{campaign}_no_wait_2h"
    no_wait = [
        *base,
        "--campaign-id",
        no_wait_id,
        "--waiting-max",
        "0",
        "--time-limit",
        str(config.get("no_wait_time_limit_seconds", 7200.0)),
        *flags,
    ]
    subprocess.run(no_wait, check=True)
    checkpoint = args.output_dir / no_wait_id / "incumbent.json"
    if not checkpoint.exists():
        raise RuntimeError("no-wait stage produced no validated incumbent checkpoint")
    waiting_id = f"{campaign}_wait_10s_8h"
    waiting = [
        *base,
        "--campaign-id",
        waiting_id,
        "--waiting-max",
        "10",
        "--waiting-step",
        str(config.get("waiting_step_seconds", 1.0)),
        "--time-limit",
        str(config.get("waiting_time_limit_seconds", 28800.0)),
        "--import-incumbent",
        str(checkpoint),
        *flags,
    ]
    subprocess.run(waiting, check=True)
    print(
        "night campaign complete: "
        f"{args.output_dir / no_wait_id} and {args.output_dir / waiting_id}"
    )


if __name__ == "__main__":
    main()
