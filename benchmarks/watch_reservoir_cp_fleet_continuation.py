"""Continuously publish portable live detail for a fleet-continuation campaign."""

from __future__ import annotations

import argparse
from pathlib import Path
import time

from ropeway_skip_stop_optimization.benchmarking.reservoir_cp_fleet_continuation import (
    export_frontend_detail,
)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--campaign-dir", type=Path, required=True)
    parser.add_argument("--frontend-root", type=Path, required=True)
    parser.add_argument("--interval", type=float, default=1.0)
    args = parser.parse_args()
    while True:
        detail = export_frontend_detail(
            args.campaign_dir,
            args.frontend_root / args.campaign_dir.name,
        )
        if detail.get("status") in {"complete", "failed", "deadline"}:
            return
        time.sleep(args.interval)


if __name__ == "__main__":
    main()
