"""Run the bounded long timing confirmation for the assignment pilot."""

import argparse
from datetime import datetime
import json
from pathlib import Path
import subprocess
import sys
import time

from ropeway_skip_stop_optimization.optimization.ddd.cp_sat_certificate import atomic_json


def main():
    p = argparse.ArgumentParser(description=__doc__, allow_abbrev=False)
    p.add_argument("--reference-checkpoint", required=True, type=Path)
    p.add_argument("--assignment-input", required=True, type=Path)
    p.add_argument("--output", required=True, type=Path)
    p.add_argument("--threads", type=int, default=12)
    p.add_argument("--case-seconds", type=float, default=6800)
    p.add_argument("--total-seconds", type=float, default=21600)
    a = p.parse_args()
    a.output.mkdir(parents=True, exist_ok=False)
    started = time.monotonic()
    deadline = started + a.total_seconds
    report = {
        "schema": "reservoir_assignment_timing_overnight_v1",
        "started_at": datetime.now().astimezone().isoformat(),
        "reference_checkpoint": str(a.reference_checkpoint.resolve()),
        "assignment_input": str(a.assignment_input.resolve()),
        "threads": a.threads,
        "case_seconds": a.case_seconds,
        "total_seconds": a.total_seconds,
        "cases": [],
    }
    cases = (
        ("free_routes_no_hints_seed1", 1, False),
        ("free_routes_no_hints_seed2", 2, False),
        ("free_routes_hints_seed1", 1, True),
    )
    runner = Path(__file__).with_name("run_reservoir_assignment_timing.py")
    for name, seed, hints in cases:
        remaining = deadline - time.monotonic()
        if remaining <= 300:
            report.setdefault("pending", []).append(name)
            continue
        budget = min(a.case_seconds, remaining - 300)
        case_output = a.output / name
        command = [
            sys.executable,
            str(runner),
            "--stage",
            "timing",
            "--reference-checkpoint",
            str(a.reference_checkpoint),
            "--assignment-input",
            str(a.assignment_input),
            "--output",
            str(case_output),
            "--timing-seconds",
            str(budget),
            "--threads",
            str(a.threads),
            "--seed",
            str(seed),
            "--free-nonservice-routes",
        ]
        if not hints:
            command.append("--no-witness-hints")
        entry = {
            "name": name,
            "seed": seed,
            "witness_hints": hints,
            "budget_seconds": budget,
            "started_at": datetime.now().astimezone().isoformat(),
        }
        report["active_case"] = name
        atomic_json(a.output / "campaign.json", report)
        case_started = time.monotonic()
        with (a.output / f"{name}.log").open("w") as log:
            completed = subprocess.run(
                command,
                stdout=log,
                stderr=subprocess.STDOUT,
                check=False,
            )
        entry["return_code"] = completed.returncode
        entry["wall_seconds"] = time.monotonic() - case_started
        result_path = case_output / "result.json"
        if result_path.exists():
            result = json.loads(result_path.read_text())
            entry["result"] = {
                key: result.get(key)
                for key in (
                    "status",
                    "proved_infeasible",
                    "has_valid_plan",
                    "metrics",
                    "build_seconds",
                    "solve_seconds",
                    "total_seconds",
                )
            }
        report["cases"].append(entry)
        report.pop("active_case", None)
        report["elapsed_seconds"] = time.monotonic() - started
        atomic_json(a.output / "campaign.json", report)
    report["finished_at"] = datetime.now().astimezone().isoformat()
    report["elapsed_seconds"] = time.monotonic() - started
    atomic_json(a.output / "campaign.json", report)


if __name__ == "__main__":
    main()
