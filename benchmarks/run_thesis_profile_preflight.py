"""Bounded G500 resolution and profile gates; does not start the main campaign."""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
import math
from pathlib import Path
import subprocess
import sys
import time
import zipfile

from ropeway_skip_stop_optimization.benchmarking.native_solvers import supervise
from ropeway_skip_stop_optimization.optimization.ddd.cp_sat_certificate import atomic_json

ROOT = Path(__file__).resolve().parents[1]
SINGLE = ROOT / "benchmarks/run_thesis_experiment.py"


def main():
    parser = argparse.ArgumentParser(description=__doc__, allow_abbrev=False)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--wall-time-limit", type=float, default=2100)
    parser.add_argument("--_worker", action="store_true", help=argparse.SUPPRESS)
    args = parser.parse_args()
    if not 0 < args.wall_time_limit <= 2100:
        parser.error("preflight wall time must lie in (0, 2100]")
    out = args.output_dir
    out.mkdir(parents=True, exist_ok=True)
    if not args._worker:
        if (out / "preflight.json").exists():
            parser.error("preflight already exists; use a new output directory")
        monitor = out / "_supervision"
        monitor.mkdir(exist_ok=False)
        metrics = supervise(
            [sys.executable, str(Path(__file__).resolve()), *sys.argv[1:], "--_worker"],
            monitor, seconds=args.wall_time_limit, memory_bytes=32 * 1024**3,
            system_memory_pressure_seconds=30,
        )
        if metrics["supervisor_reason"] or metrics["exit_code"]:
            path = out / "preflight.json"
            manifest = json.loads(path.read_text()) if path.exists() else {}
            manifest.update(status="interrupted", stopReason=metrics["supervisor_reason"] or "worker_failed")
            atomic_json(path, manifest)
            raise SystemExit(1)
        return

    started = time.monotonic()
    deadline = time.time() + args.wall_time_limit
    manifest = {
        "schema": "thesis_g500_profile_preflight_v1",
        "startedAt": datetime.now(timezone.utc).isoformat(), "status": "running",
        "wallTimeLimitSeconds": args.wall_time_limit, "jobs": [],
        "workers": 12, "memoryLimitGiB": 32, "releaseResolutionSeconds": 15,
        "scope": "resolution sensitivity, missing F0/F3/F4 references and short fixed-K gates",
        "allStopScope": "regular common-phase reservoir capacity; fixed-start Journey capacity",
        "externalStartPlans": False,
    }
    paths = sorted({*ROOT.joinpath("src").rglob("*.py"),
                    *ROOT.joinpath("benchmarks").glob("*.py"),
                    *ROOT.joinpath("tests").glob("test_thesis*.py"),
                    *[p for p in (ROOT / "pyproject.toml", ROOT / "uv.lock") if p.is_file()]})
    with zipfile.ZipFile(out / "sources.zip", "w", zipfile.ZIP_DEFLATED) as archive:
        for path in paths:
            archive.write(path, str(path.relative_to(ROOT)))
    manifest["sourceArchiveSha256"] = hashlib.sha256((out / "sources.zip").read_bytes()).hexdigest()

    def persist():
        manifest["elapsedSeconds"] = time.monotonic() - started
        atomic_json(out / "preflight.json", manifest)

    def run(name, *, topology, family, objective, method, cabins, demand,
            seconds, resolution=15, extra=()):
        remaining = deadline - time.time()
        if remaining < 10:
            manifest["jobs"].append({"id": name, "status": "skipped", "reason": "deadline"})
            persist()
            return None
        target = out / name
        command = [sys.executable, str(SINGLE), "--topology", topology,
                   "--geometry", "g500", "--demand-family", family, "--demand-profile", "p0",
                   "--objective", objective, "--method", method, "--cabins", str(cabins),
                   "--demand", str(demand), "--release-resolution-seconds", str(resolution),
                   "--workers", "12", "--memory-limit-gib", "32", "--seed", "0",
                   "--time-limit", str(min(seconds, remaining - 5)),
                   "--output-dir", str(target), *extra]
        entry = {"id": name, "status": "running", "command": command,
                 "budgetSeconds": min(seconds, remaining - 5)}
        manifest["jobs"].append(entry)
        persist()
        before = time.monotonic()
        completed = subprocess.run(command, cwd=ROOT, check=False)
        entry.update(wallSeconds=time.monotonic() - before, exitCode=completed.returncode)
        result_path = target / "result.json"
        if completed.returncode or not result_path.exists():
            entry["status"] = "failed"
            persist()
            return None
        result = json.loads(result_path.read_text())
        native = result["run"]
        entry.update(status="complete", result=str(result_path.relative_to(out)))
        if method == "all_stop_phase":
            entry.update(capacity=native.get("capacity"),
                         provenFeasibleDemand=native.get("proven_feasible_demand"),
                         provenInfeasibleDemand=native.get("proven_infeasible_demand"),
                         capacityProven=native.get("capacity_proven"))
        elif method == "evolution":
            best = native.get("best")
            entry.update(served=None if best is None else best["passengers"]["served"],
                         unserved=None if best is None else best["passengers"]["unserved"])
        else:
            entry.update(upperBound=native.get("validated_upper_bound"),
                         lowerBound=native.get("certified_lower_bound"),
                         validation=native.get("independent_validation_status"))
        persist()
        print(json.dumps(entry), flush=True)
        return native

    persist()
    # Re-solve the old bracket; no historical number is accepted as a bound.
    for topology, cabins in (("t5r", 62), ("t6r", 75)):
        for resolution in (15, 5):
            run(f"reference_{topology}_f2_r{resolution}", topology=topology, family="f2",
                objective="unserved", method="all_stop_phase", cabins=cabins,
                demand=10000, seconds=120, resolution=resolution,
                extra=("--capacity-search", "--capacity-probe-demand", "2900",
                       "--capacity-probe-demand", "3000"))

    references = {}
    for topology, cabins in (("t5r", 62), ("t6r", 75)):
        for family in ("f0", "f3", "f4"):
            references[topology, family, "unserved"] = run(
                f"reference_{topology}_{family}_capacity_r15", topology=topology, family=family,
                objective="unserved", method="all_stop_phase", cabins=cabins,
                demand=50000, seconds=90,
                extra=("--capacity-search", "--capacity-initial-demand", "1000"))
    for family in ("f0", "f3", "f4"):
        references["t5r", family, "journey_time"] = run(
            f"reference_t5r_{family}_journey_r15", topology="t5r", family=family,
            objective="journey_time", method="all_stop_phase", cabins=10,
            demand=5000, seconds=90,
            extra=("--capacity-search", "--capacity-initial-demand", "100"))

    for topology, cabins in (("t5r", 62), ("t6r", 75)):
        for family in ("f0", "f3", "f4"):
            reference = references.get((topology, family, "unserved")) or {}
            lower = reference.get("proven_feasible_demand") or 0
            if lower <= 0:
                manifest["jobs"].append({"id": f"evolution_{topology}_{family}", "status": "skipped", "reason": "no_reference_witness"})
                persist()
                continue
            demand = math.ceil(1.1 * lower)
            run(f"evolution_{topology}_{family}_k{cabins}_r15", topology=topology, family=family,
                objective="unserved", method="evolution", cabins=cabins,
                demand=demand, seconds=45, extra=("--catalog", "od_endpoints_v1"))
            # An open reference only defines a diagnostic load, never a capacity advantage.
            manifest["jobs"][-1]["referenceCapacityProven"] = bool(reference.get("capacity_proven"))
            manifest["jobs"][-1]["referenceLowerDemand"] = lower
            persist()
    for family in ("f0", "f3", "f4"):
        reference = references.get(("t5r", family, "journey_time")) or {}
        lower = reference.get("proven_feasible_demand") or 0
        if lower <= 1:
            continue
        for mode in ("all_stop", "skip_stop"):
            run(f"journey_t5r_{family}_{mode}_k10_r15", topology="t5r", family=family,
                objective="journey_time", method="labelled_arc_flow", cabins=10,
                demand=lower // 2, seconds=45, extra=("--operating-mode", mode))
    manifest.update(status="complete" if all(j["status"] == "complete" for j in manifest["jobs"]) else "partial",
                    completedAt=datetime.now(timezone.utc).isoformat())
    persist()


if __name__ == "__main__":
    main()
