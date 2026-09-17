"""Sequential per-insertion-budget comparison, with a generous safety deadline."""

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
        parser.error("another solver is active")
    out = args.output.resolve()
    out.mkdir(parents=True, exist_ok=False)
    old = ROOT / "benchmarks/output/reservoir_greedy_20260915_v1/R2"
    live_dir = ROOT / "frontend/public/generated/evolution-live"
    previous = live_dir / "manifest.json"
    if previous.exists():
        atomic_json(
            out / "previous_live_manifest.json", json.loads(previous.read_text())
        )
    entries = []
    for backend in ("cp_sat", "gurobi"):
        name = f"{out.name}_{backend}"
        snap = live_dir / f"{name}.json"
        atomic_json(
            snap,
            {
                "schema": "reservoir_greedy_live_v1",
                "label": f"Greedy · {backend} · journey_time · seed 0",
                "status": "queued",
                "objective": "journey_time",
                "representation": "greedy",
                "updated_unix": time.time(),
                "incumbents": [],
                "mixed_incumbents": [],
                "progress": {"iterations": []},
                "best": None,
            },
        )
        entries.append(
            {
                "id": name,
                "label": backend,
                "snapshot": "/generated/evolution-live/" + snap.name,
            }
        )
    live = {
        "schema": "reservoir_line_evolution_live_manifest_v1",
        "label": "R2 · Journey Time · CP-SAT → Gurobi · 30 s je Einfügung",
        "status": "running",
        "runs": entries,
    }
    atomic_json(previous, live)
    manifest = {
        "status": "RUNNING",
        "started_unix": time.time(),
        "runs": [],
        "insertion_seconds": 30,
        "retry_seconds": 60,
        "maximum_cabins": 50,
        "objective": "journey_time",
        "initial_plan": "empty",
        "all_stop": "comparison_only",
        "safety_seconds_per_backend": 4800,
    }
    atomic_json(out / "campaign.json", manifest)
    for backend, entry in zip(("cp_sat", "gurobi"), entries):
        if active_solver_jobs():
            manifest["status"] = "BLOCKED_BY_OTHER_SOLVER"
            break
        target = out / backend
        target.mkdir()
        snap = live_dir / Path(entry["snapshot"]).name
        cmd = [
            sys.executable,
            str(ROOT / "benchmarks/run_reservoir_greedy.py"),
            "--_worker",
            "--reference-checkpoint",
            str(old / "domain.json"),
            "--all-stop-reference",
            str(old / "all_stop.json"),
            "--backend",
            backend,
            "--objective",
            "journey_time",
            "--maximum-cabins",
            "50",
            "--maximum-wait-seconds",
            "60",
            "--dispatch-window-end",
            "300",
            "--insertion-time-limit",
            "30",
            "--extended-time-limit",
            "60",
            "--time-limit",
            "4800",
            "--workers",
            "12",
            "--memory-limit-gib",
            "32",
            "--seed",
            "0",
            "--output",
            str(target),
            "--live-snapshot",
            str(snap),
        ]
        run = {
            "backend": backend,
            "status": "RUNNING",
            "command": cmd,
            "started_unix": time.time(),
        }
        manifest["runs"].append(run)
        atomic_json(out / "campaign.json", manifest)
        run["supervisor"] = supervise(
            cmd,
            target,
            seconds=4800,
            memory_bytes=32 * 1024**3,
            system_memory_pressure_seconds=30,
        )
        result = target / "result.json"
        run["status"] = "COMPLETE" if result.exists() else "INTERRUPTED"
        run["result"] = json.loads(result.read_text()) if result.exists() else None
        run["finished_unix"] = time.time()
        snapshot = json.loads(snap.read_text())
        snapshot.update(
            status="complete" if result.exists() else "interrupted",
            updated_unix=time.time(),
        )
        atomic_json(snap, snapshot)
        atomic_json(out / "campaign.json", manifest)
    else:
        manifest["status"] = "COMPLETE"
    manifest["finished_unix"] = time.time()
    atomic_json(out / "campaign.json", manifest)
    live["status"] = manifest["status"].lower()
    atomic_json(previous, live)


if __name__ == "__main__":
    main()
