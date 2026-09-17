#!/usr/bin/env python3
"""Run the frozen 3 x 2 x 2 OIP fixed-pattern waiting comparison."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import sys
import time

from ropeway_skip_stop_optimization.benchmarking.native_solvers import supervise


ROOT = Path(__file__).resolve().parents[1]


def main() -> None:
    args = parse_args()
    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=True)
    started = time.time()
    deadline = started + args.wall_limit_seconds
    manifest = {
        "schema": "oip_pattern_waiting_campaign_v1",
        "status": "RUNNING",
        "started_unix": started,
        "deadline_unix": deadline,
        "technical_test_load": 3210,
        "runs": [],
    }

    def save() -> None:
        (output / "campaign.json").write_text(
            json.dumps(manifest, indent=2, sort_keys=True) + "\n"
        )

    save()
    for waiting in (0, 120):
        for mix in ("all_stop", "f2_direct", "mixed"):
            for backend in ("cp_sat", "gurobi"):
                run_id = f"{mix}__w{waiting}__{backend}"
                run_dir = output / run_id
                run_dir.mkdir(exist_ok=True)
                entry = {
                    "run_id": run_id,
                    "pattern_mix": mix,
                    "maximum_wait_seconds": waiting,
                    "backend": backend,
                    "status": "PLANNED",
                }
                manifest["runs"].append(entry)
                if time.time() + 2 >= deadline:
                    entry["status"] = "NOT_STARTED_DEADLINE"
                    save()
                    continue
                command = [
                    sys.executable,
                    str(ROOT / "benchmarks" / "run_oip.py"),
                    "--thesis-f2-pilot",
                    "--backend", backend,
                    "--movement-only",
                    "--pattern-mix", mix,
                    "--maximum-wait-seconds", str(waiting),
                    "--time-limit", str(args.trial_time_limit_seconds),
                    "--passenger-evaluation-time-limit",
                    str(args.passenger_evaluation_time_limit_seconds),
                    "--workers", str(args.workers),
                    "--memory-limit-gib", str(args.memory_limit_gib),
                    "--seed", "0",
                    "--output", str(run_dir),
                ]
                entry.update(status="RUNNING", command=command)
                save()
                trial_started = time.time()
                guard = supervise(
                    command,
                    run_dir,
                    seconds=(
                        args.trial_time_limit_seconds
                        + args.passenger_evaluation_time_limit_seconds
                        + 5
                    ),
                    memory_bytes=int(args.memory_limit_gib * 1024**3),
                    global_deadline=deadline,
                    env={**os.environ, "PYTHONPATH": str(ROOT / "src")},
                    system_memory_pressure_seconds=30,
                )
                entry["supervisor"] = guard
                entry["wall_seconds"] = time.time() - trial_started
                result_file = run_dir / "result.json"
                if result_file.is_file():
                    entry["result"] = json.loads(result_file.read_text())
                    entry["status"] = "COMPLETE"
                else:
                    entry["status"] = "INCOMPLETE"
                save()
    manifest["status"] = (
        "COMPLETE"
        if all(item["status"] == "COMPLETE" for item in manifest["runs"])
        else "PARTIAL"
    )
    manifest["finished_unix"] = time.time()
    save()


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--trial-time-limit-seconds", type=float, default=60)
    parser.add_argument("--passenger-evaluation-time-limit-seconds", type=float, default=30)
    parser.add_argument("--wall-limit-seconds", type=float, default=1200)
    parser.add_argument("--workers", type=int, default=12)
    parser.add_argument("--memory-limit-gib", type=float, default=32)
    args = parser.parse_args()
    if args.wall_limit_seconds > 1200:
        parser.error("the frozen pilot is capped at 20 minutes")
    if not 0 < args.memory_limit_gib <= 32:
        parser.error("memory limit must lie in (0, 32] GiB")
    return args


if __name__ == "__main__":
    main()
