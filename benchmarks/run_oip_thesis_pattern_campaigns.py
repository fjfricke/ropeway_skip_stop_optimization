#!/usr/bin/env python3
"""Run the three frozen short-horizon OIP thesis pattern campaigns."""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
from typing import Any

from ropeway_skip_stop_optimization.benchmarking.thesis_contract import (
    HEADWAY_CONTRACT, THESIS_CONTRACT_ID, solver_versions, source_digest,
)

from ropeway_skip_stop_optimization.optimization.ddd.cp_sat_certificate import (
    atomic_json,
)


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_FRONTEND_ROOT = ROOT / "frontend" / "public" / "generated" / "optimization"

THESIS_FAMILIES = ("f2", "f3", "f0")
REFERENCE_KIND = "regular_all_stop_free_common_phase"


def calibrated_cases(path: Path | None) -> list[dict]:
    """Load an explicitly selected, traceable new-contract demand definition.

    This checks provenance, not mathematical proof. The calibration process
    must independently validate its certificates before exporting this index.
    No old 45-minute load or unproved capacity becomes a default here.
    """
    if path is None:
        return [dict(family=family, demand_total=None,
                     demand_provenance="pending_short_contract_calibration")
                for family in THESIS_FAMILIES]
    payload = json.loads(path.read_text())
    if (payload.get("contract_id") != THESIS_CONTRACT_ID
            or payload.get("reference_kind") != REFERENCE_KIND):
        raise ValueError("calibration must use the new short regular All-Stop contract")
    rows = payload.get("cases", [])
    if len(rows) != 3 or {row["family"] for row in rows} != set(THESIS_FAMILIES):
        raise ValueError("calibration must define F0, F2 and F3 exactly once")
    for row in rows:
        if type(row.get("demand_total")) is not int or row["demand_total"] < 1:
            raise ValueError("calibrated demand must be a positive integer")
        reference = (path.parent / row["reference_result"]).resolve()
        if hashlib.sha256(reference.read_bytes()).hexdigest() != row["reference_sha256"]:
            raise ValueError("calibration reference content has changed")
        evidence = json.loads(reference.read_text())
        if (evidence.get("contract_id") != THESIS_CONTRACT_ID
                or evidence.get("reference_kind") != REFERENCE_KIND
                or evidence.get("family") != row["family"]
                or evidence.get("capacity_proven") is not True):
            raise ValueError("matching proven regular All-Stop calibration is required")
        n = evidence.get("proven_feasible_demand")
        if type(n) is not int or n < 1 or evidence.get("proven_infeasible_demand") != n + 1:
            raise ValueError("reference must report an exact N/N+1 capacity bracket")
        numerator, denominator = row.get("load_numerator"), row.get("load_denominator")
        if (type(numerator) is not int or type(denominator) is not int
                or numerator < 1 or denominator < 1
                or row["demand_total"] != (n * numerator + denominator - 1) // denominator):
            raise ValueError("demand must be ceil(reference capacity * declared load ratio)")
        row["demand_provenance"] = REFERENCE_KIND
        row["reference_result"] = str(reference)
    return sorted(rows, key=lambda row: THESIS_FAMILIES.index(row["family"]))


def main() -> None:
    args = parse_args()
    cases = calibrated_cases(args.calibrated_cases)
    identity = {
        "contract_id": THESIS_CONTRACT_ID,
        "source_digest": source_digest(ROOT),
        "solver_versions": solver_versions(),
        "cases": cases,
        "workers": args.workers,
        "memory_limit_gib": args.memory_limit_gib,
    }
    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=True)
    suite_path = output / "suite.json"
    if suite_path.exists():
        if not args.resume:
            raise ValueError("suite already exists; use --resume")
        suite = json.loads(suite_path.read_text())
        if suite.get("identity") != identity:
            raise ValueError("suite contract, calibration or code changed; create a new suite")
    else:
        suite = {
            "schema_version": 2,
            "identity": identity,
            "suite_id": output.name,
            "label": "T5R/G500 short-horizon OIP pattern thesis campaigns",
            "status": "prepared",
            "headway_contract": HEADWAY_CONTRACT,
            "contract_id": THESIS_CONTRACT_ID,
            "reference_kind": REFERENCE_KIND,
            "demand_window_cycles": 2,
            "completion_seconds": 900,
            "continuation_seconds": 300,
            "cases": [
                {
                    **case,
                    "status": "planned",
                    "directory": f"{output.name}__{case['family']}",
                }
                for case in cases
            ],
            "created_at_utc": _now(),
        }
    if any(case["demand_total"] is None for case in cases):
        suite["status"] = "pending_calibration"
        suite["updated_at_utc"] = _now()
        atomic_json(suite_path, suite)
        if not args.build_only:
            raise ValueError("new short-contract calibration is missing; no solver started")
        print(f"Prepared suite with pending calibration: {suite_path}")
        return
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
    parser.add_argument("--calibrated-cases", type=Path,
                        help="New-contract reference index; required to start thesis runs")
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
