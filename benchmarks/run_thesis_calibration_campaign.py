#!/usr/bin/env python3
"""Prepare or run only the 23 frozen thesis capacity calibrations."""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
from pathlib import Path

from ropeway_skip_stop_optimization.benchmarking.process_supervisor import supervise
from ropeway_skip_stop_optimization.benchmarking.thesis_calibration import (
    calibration_jobs,
    result_evidence,
)
from ropeway_skip_stop_optimization.benchmarking.thesis_cases import (
    ExperimentCaseSpec,
    ThesisDemandFamily,
    ThesisDemandProfile,
    ThesisGeometry,
    ThesisObjective,
    ThesisTopology,
    prepare_experiment_case,
)
from ropeway_skip_stop_optimization.benchmarking.thesis_contract import (
    THESIS_CONTRACT_ID,
    solver_versions,
    source_digest,
)
from ropeway_skip_stop_optimization.optimization.ddd.cp_sat_certificate import atomic_json


ROOT = Path(__file__).resolve().parents[1]
JOB_SECONDS = 1800
RESERVE_SECONDS = 1800
MEMORY_BYTES = 32 * 1024**3


def parser() -> argparse.ArgumentParser:
    value = argparse.ArgumentParser(description=__doc__, allow_abbrev=False)
    value.add_argument("--output-dir", type=Path, required=True)
    value.add_argument("--resume", action="store_true")
    mode = value.add_mutually_exclusive_group()
    mode.add_argument("--run", action="store_true")
    mode.add_argument("--build-only", action="store_true")
    value.add_argument("--_worker", action="store_true", help=argparse.SUPPRESS)
    return value


def _oip_maximum_fleet() -> int:
    spec = ExperimentCaseSpec(
        ThesisTopology.T5R,
        ThesisGeometry.G500,
        ThesisDemandFamily.F0,
        ThesisDemandProfile.P0,
        ThesisObjective.UNSERVED,
        1,
        15,
        0.0,
    )
    prepared = prepare_experiment_case(spec)
    maximum = prepared.all_stop_reference_cabins
    if maximum != prepared.all_stop_unconstrained_saturation_cabins:
        raise ValueError("available fleet truncates the physical All-Stop maximum")
    return maximum


def _command(job: dict, directory: Path) -> list[str]:
    common = [
        sys.executable,
        str(ROOT / "benchmarks" / "run_thesis_experiment.py"),
        "--topology", "t5r",
        "--geometry", "g500",
        "--demand-profile", "p0",
        "--demand-family", job["family"],
        "--method", "all_stop_phase",
        "--operating-mode", "all_stop",
        "--cabins", str(job["cabins"]),
        "--demand", "20000",
        "--release-resolution-seconds", "15",
        "--maximum-wait-seconds", "0",
        "--time-limit", str(JOB_SECONDS),
        "--workers", "12",
        "--memory-limit-gib", "32",
        "--seed", "0",
        "--capacity-search",
        "--capacity-initial-demand", "500",
        "--output-dir", str(directory),
    ]
    if job["group"] == "journey":
        return [*common, "--objective", "journey_time"]
    return [
        *common,
        "--objective", "unserved",
        "--all-stop-capacity-encoding", "phase_cells",
    ]


def _write_references(output: Path, state: dict) -> None:
    evidence = []
    for job in state["jobs"]:
        if job["status"] != "complete":
            continue
        result = Path(job["attempts"][-1]["directory"]) / "result.json"
        evidence.append(result_evidence(job, result))
    atomic_json(output / "references.json", {
        "schema": "thesis_calibration_references_v1",
        "contract_id": THESIS_CONTRACT_ID,
        "campaign_id": state["campaign_id"],
        "evidence": evidence,
    })


def main() -> None:
    args = parser().parse_args()
    output = args.output_dir.resolve()
    campaign_path = output / "campaign.json"
    identity = {
        "contract_id": THESIS_CONTRACT_ID,
        "source_digest": source_digest(ROOT),
        "solver_versions": solver_versions(),
        "oip_maximum_fleet": _oip_maximum_fleet(),
    }
    if campaign_path.exists():
        if not (args.resume or args._worker):
            raise ValueError("campaign exists; use --resume")
        state = json.loads(campaign_path.read_text(encoding="utf-8"))
        if state.get("identity") != identity:
            raise ValueError("code or calibration contract changed; create a new campaign")
    else:
        if args.resume or args._worker:
            raise ValueError("no prepared calibration campaign exists")
        if output.exists() and any(output.iterdir()):
            raise ValueError("output directory is not empty")
        output.mkdir(parents=True, exist_ok=True)
        jobs = calibration_jobs(oip_cabins=identity["oip_maximum_fleet"])
        state = {
            "schema": "thesis_calibration_campaign_v1",
            "campaign_id": output.name,
            "identity": identity,
            "status": "prepared",
            "jobs": jobs,
            "execution_started_unix": None,
            "wall_limit_seconds": len(jobs) * JOB_SECONDS + RESERVE_SECONDS,
        }
        atomic_json(campaign_path, state)
        _write_references(output, state)
    if not args.run:
        print(f"Prepared {len(state['jobs'])} calibration jobs; no solver started: {campaign_path}")
        return
    if state["execution_started_unix"] is None:
        state["execution_started_unix"] = time.time()
        state["deadline_unix"] = time.time() + state["wall_limit_seconds"]
        atomic_json(campaign_path, state)
    if not args._worker:
        remaining = state["deadline_unix"] - time.time()
        if remaining <= 0:
            raise ValueError("original calibration deadline exhausted")
        monitor = output / f"supervision_{time.time_ns()}"
        monitor.mkdir()
        summary = supervise(
            [sys.executable, str(Path(__file__).resolve()), "--output-dir", str(output),
             "--run", "--resume", "--_worker"],
            monitor,
            seconds=remaining,
            memory_bytes=MEMORY_BYTES,
            system_memory_pressure_seconds=30,
        )
        if summary["supervisor_reason"] or summary["exit_code"]:
            state = json.loads(campaign_path.read_text(encoding="utf-8"))
            state.update(status="interrupted", supervisor=summary)
            atomic_json(campaign_path, state)
            _write_references(output, state)
            raise SystemExit(1)
        return

    state["status"] = "running"
    atomic_json(campaign_path, state)
    for job in state["jobs"]:
        if job["status"] == "complete":
            continue
        if time.time() + JOB_SECONDS + 5 > state["deadline_unix"]:
            state["status"] = "partial"
            break
        attempt_dir = output / "calibration" / job["group"] / job["id"] / f"attempt_{len(job['attempts']) + 1:03d}"
        command = _command(job, attempt_dir)
        attempt = {"directory": str(attempt_dir), "command": command, "started_unix": time.time()}
        job["attempts"].append(attempt)
        job["status"] = "running"
        atomic_json(campaign_path, state)
        process = subprocess.run(command, cwd=ROOT, check=False)
        attempt.update(exit_code=process.returncode, finished_unix=time.time())
        job["status"] = "complete" if process.returncode == 0 and (attempt_dir / "result.json").is_file() else "failed"
        atomic_json(campaign_path, state)
        _write_references(output, state)
    state["status"] = "complete" if all(job["status"] == "complete" for job in state["jobs"]) else "partial"
    atomic_json(campaign_path, state)
    _write_references(output, state)


if __name__ == "__main__":
    main()
