"""Prepare or explicitly execute fresh five-step Journey comparisons.

Default is preparation only. Execution requires --run; no dated reference
directory is reused. Previous results retain their original physical contract.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import time

from ropeway_skip_stop_optimization.benchmarking.native_solvers import supervise
from ropeway_skip_stop_optimization.benchmarking.thesis_contract import (
    THESIS_CONTRACT_ID, solver_versions, source_digest,
)
from ropeway_skip_stop_optimization.benchmarking.thesis_reruns import (
    exact_reference_capacity, journey_jobs, study_definition,
)
from ropeway_skip_stop_optimization.optimization.ddd.cp_sat_certificate import atomic_json

ROOT = Path(__file__).resolve().parents[1]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--resume", action="store_true")
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--run", action="store_true")
    mode.add_argument("--build-only", action="store_true")
    parser.add_argument("--_worker", action="store_true", help=argparse.SUPPRESS)
    args = parser.parse_args()
    output = args.output_dir.resolve()
    path = output / "campaign.json"
    identity = dict(contract_id=THESIS_CONTRACT_ID, source_digest=source_digest(ROOT),
                    solver_versions=solver_versions())
    if path.exists():
        if not (args.resume or args._worker):
            parser.error("campaign exists; use --resume")
        state = json.loads(path.read_text())
        if state.get("identity") != identity:
            parser.error("code or physical contract changed; create a new campaign")
    else:
        if args.resume or args._worker:
            parser.error("no prepared campaign exists")
        if output.exists() and any(output.iterdir()):
            parser.error("output directory is not empty")
        state = dict(
            schema=2, campaign_id=output.name, identity=identity, status="prepared",
            study=study_definition(),
            jobs=journey_jobs(), execution_started_unix=None,
            wall_limit_seconds=len(journey_jobs()) * 1800 + 1800,
        )
        atomic_json(path, state)
    if not args.run:
        print(f"Prepared {len(state['jobs'])} jobs; no solver started: {path}")
        return
    if state["execution_started_unix"] is None:
        state["execution_started_unix"] = time.time()
        state["deadline_unix"] = time.time() + state["wall_limit_seconds"]
        atomic_json(path, state)
    if not args._worker:
        remaining = state["deadline_unix"] - time.time()
        if remaining <= 0:
            parser.error("original execution deadline exhausted")
        monitor = output / f"supervision_{time.time_ns()}"
        monitor.mkdir()
        summary = supervise(
            [sys.executable, str(Path(__file__).resolve()), "--output-dir", str(output),
             "--run", "--_worker"], monitor, seconds=remaining,
            memory_bytes=32 * 1024**3, system_memory_pressure_seconds=30,
        )
        if summary["supervisor_reason"] or summary["exit_code"]:
            state = json.loads(path.read_text())
            state.update(status="interrupted", supervisor=summary)
            atomic_json(path, state)
            raise SystemExit(1)
        return
    state["status"] = "running"
    atomic_json(path, state)
    by_id = {job["id"]: job for job in state["jobs"]}
    for job in state["jobs"]:
        if job["status"] == "complete":
            continue
        if time.time() + 1805 > state["deadline_unix"]:
            state["status"] = "partial"
            break
        if job["kind"] != "reference":
            reference = by_id[job["reference_id"]]
            if reference["status"] != "complete":
                job["status"] = "pending_reference"
                continue
            ref_path = Path(reference["attempts"][-1]["directory"]) / "result.json"
            try:
                capacity = exact_reference_capacity(
                    json.loads(ref_path.read_text()), k=job["reference_k"],
                )
            except ValueError as error:
                job.update(status="pending_reference", reason=str(error))
                continue
            job["demand"] = capacity * job["percent"] // 100
            if job["demand"] < 1:
                job.update(status="pending_reference", reason="scaled demand is zero")
                continue
            job["reference_sha256"] = hashlib.sha256(ref_path.read_bytes()).hexdigest()
        directory = output / "runs" / job["id"] / f"attempt_{len(job['attempts']) + 1:03d}"
        command = [
            sys.executable, str(ROOT / "benchmarks/run_thesis_experiment.py"),
            "--topology", "t5r", "--geometry", "g500", "--demand-profile", "p0",
            "--demand-family", job["family"], "--objective", "journey_time",
            "--method", "all_stop_phase" if job["kind"] == "reference" else "labelled_arc_flow",
            "--operating-mode", job["mode"], "--cabins", str(job["k"]),
            "--demand", str(job["demand"]), "--release-resolution-seconds", "15",
            "--maximum-wait-seconds", "0", "--time-limit", "1800", "--workers", "12",
            "--memory-limit-gib", "32", "--seed", "0", "--output-dir", str(directory),
        ]
        command += ["--capacity-search", "--capacity-initial-demand", "500"] if job["kind"] == "reference" else ["--mip-gap", "0.01"]
        attempt = dict(directory=str(directory), command=command, started_unix=time.time())
        job["attempts"].append(attempt)
        job["status"] = "running"
        atomic_json(path, state)
        process = subprocess.run(command, cwd=ROOT, check=False)
        attempt.update(exit_code=process.returncode, finished_unix=time.time())
        job["status"] = "complete" if process.returncode == 0 and (directory / "result.json").is_file() else "failed"
        atomic_json(path, state)
    state["status"] = "complete" if all(j["status"] == "complete" for j in state["jobs"]) else "partial"
    atomic_json(path, state)


if __name__ == "__main__":
    main()
