"""Publish only read-only, portable summaries of the active preflight."""
import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import time

from ropeway_skip_stop_optimization.optimization.ddd.cp_sat_certificate import atomic_json


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--watch-seconds", type=float, default=0)
    args = parser.parse_args()
    deadline = time.monotonic() + args.watch_seconds
    allowed = {"id", "status", "wallSeconds", "capacity", "provenFeasibleDemand",
               "provenInfeasibleDemand", "served", "unserved", "upperBound",
               "lowerBound", "validation"}
    while True:
        raw = json.loads(args.input.read_text())
        view = {
            "schema": "thesis_preflight_view_v1", "status": raw["status"],
            "startedAt": raw["startedAt"], "generatedAt": datetime.now(timezone.utc).isoformat(),
            "plannedJobs": 25,
            "jobs": [{k: v for k, v in job.items() if k in allowed} for job in raw["jobs"]],
        }
        atomic_json(args.output, view)
        if raw["status"] != "running" or time.monotonic() >= deadline:
            break
        time.sleep(min(3, max(0, deadline - time.monotonic())))


if __name__ == "__main__":
    main()
