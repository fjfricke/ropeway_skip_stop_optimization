"""Bounded sequential journey comparison using independently validated archives."""

import argparse
import json
import sys
import time
from pathlib import Path

from run_reservoir_greedy import ROOT, active_solver_jobs

from ropeway_skip_stop_optimization.benchmarking.native_solvers import supervise
from ropeway_skip_stop_optimization.optimization.ddd.cp_sat_certificate import (
    atomic_json,
)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if active_solver_jobs():
        parser.error("another solver is active; start after it completes")
    out = args.output.resolve()
    out.mkdir(parents=True, exist_ok=False)
    old = ROOT / "benchmarks/output/reservoir_greedy_20260915_v1"
    live_dir = ROOT / "frontend/public/generated/evolution-live"
    live = {
        "schema": "reservoir_line_evolution_live_manifest_v1",
        "label": "R2 · Free STOP/SKIP · Capacity vs Journey Time",
        "status": "running",
        "runs": [],
    }
    started = time.time()
    deadline = started + 600
    manifest = {
        "status": "RUNNING",
        "started_unix": started,
        "runs": [],
        "baseline_archive": str(old),
        "objectives": ["unserved", "journey_time"],
        "deadline_unix": deadline,
    }
    for seed in (0, 1):
        for objective in (
            ("unserved", "journey_time") if seed == 0 else ("journey_time", "unserved")
        ):
            backend = "cp_sat"
            name = f"construct_R2_{objective}_{backend}_s{seed}"
            if active_solver_jobs() or time.time() + 122 > deadline:
                manifest["runs"].append({"name": name, "status": "PENDING"})
                continue
            target = out / name
            target.mkdir()
            snap = live_dir / f"journey_{name}.json"
            live["runs"].append(
                {
                    "id": name,
                    "label": name,
                    "snapshot": "/generated/evolution-live/" + snap.name,
                }
            )
            atomic_json(live_dir / "manifest.json", live)
            cmd = [
                sys.executable,
                str(ROOT / "benchmarks/run_reservoir_greedy.py"),
                "--_worker",
                "--reference-checkpoint",
                str(old / "R2/domain.json"),
                "--all-stop-reference",
                str(old / "R2/all_stop.json"),
                "--objective",
                objective,
                "--backend",
                backend,
                "--seed",
                str(seed),
                "--time-limit",
                "120",
                "--workers",
                "12",
                "--output",
                str(target),
                "--live-snapshot",
                str(snap),
            ]
            entry = {"name": name, "status": "RUNNING", "command": cmd}
            manifest["runs"].append(entry)
            atomic_json(out / "campaign.json", manifest)
            entry["supervisor"] = supervise(
                cmd,
                target,
                seconds=120,
                memory_bytes=32 * 1024**3,
                global_deadline=deadline,
                system_memory_pressure_seconds=30,
            )
            path = target / "result.json"
            entry["status"] = "FINISHED" if path.exists() else "INCOMPLETE"
            entry["result"] = json.loads(path.read_text()) if path.exists() else None
            entry["historical_comparison_excluded"] = (
                "Previous run restricted to ALL_STOP by inherited operating_mode"
            )
            atomic_json(out / "campaign.json", manifest)
    manifest.update(status="COMPLETE", total_wall_seconds=time.time() - started)
    atomic_json(out / "campaign.json", manifest)
    live["status"] = "complete"
    atomic_json(live_dir / "manifest.json", live)


if __name__ == "__main__":
    main()
