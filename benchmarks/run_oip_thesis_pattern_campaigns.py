#!/usr/bin/env python3
"""Run the three frozen short-horizon OIP thesis pattern campaigns."""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import subprocess
import sys
from typing import Any

from ropeway_skip_stop_optimization.optimization.ddd.cp_sat_certificate import (
    atomic_json,
)


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_FRONTEND_ROOT = ROOT / "frontend" / "public" / "generated" / "optimization"

# These are imported thesis stress loads. They are deliberately not described
# as capacities of the shorter optimized-initial-placement contract.
THESIS_CASES = (
    ("f2", 3_210, "110pct_regular_all_stop_profile"),
    ("f3", 7_869, "110pct_regular_all_stop_profile"),
    ("f0", 9_781, "proved_regular_all_stop_lower_bound_profile"),
)


def main() -> None:
    args = parse_args()
    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=True)
    suite_path = output / "suite.json"
    if suite_path.exists():
        if not args.resume:
            raise ValueError("suite already exists; use --resume")
        suite = json.loads(suite_path.read_text())
    else:
        suite = {
            "schema_version": 1,
            "suite_id": output.name,
            "label": "T5R/G500 short-horizon OIP pattern thesis campaigns",
            "status": "prepared",
            "headway_contract": "architecture_b_stop_leader_entry_and_exit",
            "demand_window_cycles": 2,
            "completion_seconds": 900,
            "continuation_seconds": 300,
            "cases": [
                {
                    "family": family,
                    "demand_total": demand_total,
                    "demand_provenance": provenance,
                    "status": "planned",
                    "directory": f"{output.name}__{family}",
                }
                for family, demand_total, provenance in THESIS_CASES
            ],
            "created_at_utc": _now(),
        }
    suite["status"] = "running"
    suite["updated_at_utc"] = _now()
    atomic_json(suite_path, suite)

    for case in suite["cases"]:
        if case["status"] == "complete":
            continue
        case_output = output / case["directory"]
        command = [
            sys.executable,
            str(ROOT / "benchmarks" / "run_oip_pattern_screening.py"),
            "--family", case["family"],
            "--demand-total", str(case["demand_total"]),
            "--k-values", "40", "50", "62",
            "--trial-time-limit-seconds", "60",
            "--passenger-evaluation-time-limit-seconds", "30",
            "--refinement-candidates-per-k", "2",
            "--refinement-time-limit-seconds", "180",
            "--wall-limit-seconds", "3600",
            "--seed", "0",
            "--workers", str(args.workers),
            "--memory-limit-gib", str(args.memory_limit_gib),
            "--output", str(case_output),
            "--frontend-root", str(args.frontend_root.resolve()),
        ]
        if args.build_only:
            command.append("--build-only")
        elif (case_output / "campaign.json").is_file():
            command.append("--resume")
        case["status"] = "running"
        case["command"] = command
        case["started_at_utc"] = _now()
        atomic_json(suite_path, suite)
        completed = subprocess.run(
            command,
            cwd=ROOT,
            check=False,
            env={**os.environ, "PYTHONPATH": str(ROOT / "src")},
        )
        case["exit_code"] = completed.returncode
        case["finished_at_utc"] = _now()
        campaign_path = case_output / "campaign.json"
        if campaign_path.is_file():
            campaign = json.loads(campaign_path.read_text())
            case["campaign_status"] = campaign.get("status")
            case["completed_screenings"] = campaign.get("completed_trial_count")
            case["screening_count"] = campaign.get("trial_count")
            case["completed_refinements"] = campaign.get(
                "completed_refinement_count"
            )
            case["refinement_count"] = campaign.get("refinement_count")
        case["status"] = (
            "prepared"
            if args.build_only
            and completed.returncode == 0
            and case.get("campaign_status") == "prepared"
            else "complete"
            if completed.returncode == 0
            and case.get("campaign_status") == "complete"
            else "partial"
        )
        suite["updated_at_utc"] = _now()
        atomic_json(suite_path, suite)
        if completed.returncode != 0:
            break

    suite["status"] = (
        "prepared"
        if args.build_only
        and all(case["status"] == "prepared" for case in suite["cases"])
        else "complete"
        if all(case["status"] == "complete" for case in suite["cases"])
        else "partial"
    )
    suite["updated_at_utc"] = _now()
    atomic_json(suite_path, suite)
    print(
        f"OIP thesis suite {suite['status']}: "
        f"{sum(case['status'] == 'complete' for case in suite['cases'])}/"
        f"{len(suite['cases'])} campaigns"
    )


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--frontend-root", type=Path, default=DEFAULT_FRONTEND_ROOT)
    parser.add_argument("--workers", type=int, default=12)
    parser.add_argument("--memory-limit-gib", type=float, default=32)
    parser.add_argument("--build-only", action="store_true")
    parser.add_argument("--resume", action="store_true")
    args = parser.parse_args()
    if args.workers <= 0:
        parser.error("workers must be positive")
    if not 0 < args.memory_limit_gib <= 32:
        parser.error("memory limit must lie in (0, 32] GiB")
    return args


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


if __name__ == "__main__":
    main()
