"""Run the frozen two-hour G500 calibration and refresh its read-only frontend."""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
import math
from pathlib import Path
import shutil
import subprocess
import sys
import time

from ropeway_skip_stop_optimization.benchmarking.thesis_cases import (
    ExperimentCaseSpec,
    ThesisDemandFamily,
    ThesisDemandProfile,
    ThesisGeometry,
    ThesisObjective,
    ThesisTopology,
    prepare_experiment_case,
)
from ropeway_skip_stop_optimization.optimization.ddd.cp_sat_certificate import atomic_json
from ropeway_skip_stop_optimization.benchmarking.native_solvers import supervise


ROOT = Path(__file__).resolve().parents[1]
SINGLE = ROOT / "benchmarks/run_thesis_experiment.py"
SERIES = ROOT / "benchmarks/run_thesis_fixed_k_series.py"
EXPORT = ROOT / "benchmarks/export_thesis_frontend.py"


def _read(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _capacity(run_dir: Path) -> tuple[int, int | None, bool]:
    value = (_read(run_dir / "result.json").get("run") or {})
    return (
        int(value.get("proven_feasible_demand") or 0),
        None if value.get("proven_infeasible_demand") is None else int(value["proven_infeasible_demand"]),
        bool(value.get("capacity_proven")),
    )


def validate_reusable_reference(directory: Path, *, topology: str, objective: str,
                                cabins: int, resolution: int, maximum_demand: int) -> None:
    """A matching directory name alone is not evidence of a matching reference."""
    case = _read(directory / "case_spec.json")
    arguments = _read(directory / "arguments.json")
    result = _read(directory / "result.json")
    expected = {
        "topology": topology, "geometry": "g500", "demand_family": "f2",
        "demand_profile": "p0", "objective": objective,
        "release_resolution_seconds": resolution, "demand_total": maximum_demand,
        "maximum_wait_seconds": 1200.0,
    }
    for key, value in expected.items():
        if case.get(key) != value:
            raise ValueError(f"reused reference has incompatible {key}: {directory}")
    if arguments.get("cabins") != cabins or arguments.get("method") != "all_stop_phase":
        raise ValueError(f"reused reference has incompatible method/fleet: {directory}")
    run = result.get("run") or {}
    expected_schema = ("fixed_k_all_stop_capacity_search_v1" if objective == "journey_time"
                       else "all_stop_capacity_search_v1")
    if run.get("schema") != expected_schema or not run.get("probes"):
        raise ValueError(f"reused reference has no completed capacity probes: {directory}")
    lower, upper, exact = _capacity(directory)
    if exact and (upper != lower + 1 or run.get("capacity") != lower):
        raise ValueError(f"reused reference has inconsistent capacity proof: {directory}")
    spec = ExperimentCaseSpec(
        ThesisTopology(topology), ThesisGeometry.G500, ThesisDemandFamily.F2,
        ThesisDemandProfile.P0, ThesisObjective(objective), maximum_demand, resolution,
    )
    current = prepare_experiment_case(spec)
    if current.problem.fingerprint != result.get("problem_fingerprint"):
        raise ValueError(f"reused reference physical domain changed: {directory}")
    if objective == "unserved":
        from dataclasses import replace
        from ropeway_skip_stop_optimization.optimization.ddd.reservoir_cp_sat_certificate import read_reservoir_cp_checkpoint
        if lower > 0:
            witness = prepare_experiment_case(replace(spec, demand_total=lower))
            read_reservoir_cp_checkpoint(directory / "best.json", witness.problem)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, allow_abbrev=False)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--frontend-output", type=Path, default=ROOT / "frontend/public/generated/thesis")
    parser.add_argument("--wall-time-limit", type=float, default=7200)
    parser.add_argument("--maximum-demand", type=int, default=10000)
    parser.add_argument("--workers", type=int, default=12)
    parser.add_argument("--memory-limit-gib", type=float, default=32)
    parser.add_argument(
        "--reuse-reference-root",
        type=Path,
        help="Reuse already completed reference_* directories from this calibration root.",
    )
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--_worker", action="store_true", help=argparse.SUPPRESS)
    args = parser.parse_args()
    if not 0 < args.wall_time_limit <= 7200:
        parser.error("wall-time-limit must lie in (0, 7200]")
    if args.maximum_demand <= 0 or not 0 < args.memory_limit_gib <= 32:
        parser.error("invalid demand or memory limit")
    args.output_dir.mkdir(parents=True, exist_ok=args._worker)
    if not args._worker and not args.dry_run:
        supervision = args.output_dir / "_supervision"
        supervision.mkdir()
        outcome = supervise(
            [sys.executable, str(Path(__file__).resolve()), *sys.argv[1:], "--_worker"],
            supervision, seconds=args.wall_time_limit,
            memory_bytes=int(args.memory_limit_gib * 1024**3),
            system_memory_pressure_seconds=30.0,
        )
        if outcome["supervisor_reason"] or outcome["exit_code"]:
            campaign_path = args.output_dir / "campaign.json"
            campaign = _read(campaign_path) if campaign_path.exists() else {}
            campaign.update(status="interrupted", stopReason=outcome["supervisor_reason"] or "worker_failed")
            atomic_json(campaign_path, campaign)
            raise SystemExit(1)
        return
    started = time.monotonic()
    deadline = started + args.wall_time_limit
    manifest = {
        "schema": "thesis_g500_calibration_v2",
        "startedAt": datetime.now(timezone.utc).isoformat(),
        "status": "running",
        "wallTimeLimitSeconds": args.wall_time_limit,
        "jobs": [],
        "calibrationScope": "G500/P0/F2 sizing; other demand-family references remain pending",
    }

    def persist() -> None:
        manifest["elapsedSeconds"] = time.monotonic() - started
        atomic_json(args.output_dir / "campaign.json", manifest)

    def refresh_frontend() -> None:
        subprocess.run(
            [sys.executable, str(EXPORT), "--results-root", str(args.output_dir), "--output", str(args.frontend_output)],
            cwd=ROOT,
            check=False,
            stdout=subprocess.DEVNULL,
        )

    def run_job(name: str, budget: float, command: list[str]) -> Path | None:
        remaining = deadline - time.monotonic()
        if remaining <= 3:
            manifest["status"] = "deadline"
            manifest["stopReason"] = "global_deadline"
            persist()
            return None
        actual = min(budget, max(1.0, remaining - 2))
        target = args.output_dir / name
        full = [*command, "--output-dir", str(target)]
        # Every called runner exposes its own hard budget. Replace the requested
        # stage/global limit rather than letting a child outlive this campaign.
        if command[1] == str(SINGLE):
            full.extend(("--time-limit", str(actual)))
        entry = {"id": name, "status": "planned" if args.dry_run else "running", "budgetSeconds": actual, "command": full}
        manifest["jobs"].append(entry)
        persist()
        if args.dry_run:
            return target
        before = time.monotonic()
        completed = subprocess.run(full, cwd=ROOT, check=False)
        entry.update(
            status="complete" if completed.returncode == 0 and (target / "result.json").is_file() else "failed",
            exitCode=completed.returncode,
            wallSeconds=time.monotonic() - before,
        )
        persist()
        refresh_frontend()
        return target if entry["status"] == "complete" else None

    persist()
    # Solver-free sizing also verifies that the frozen geometry is available.
    physical = {}
    for topology in (ThesisTopology.T5R, ThesisTopology.T6R):
        spec = ExperimentCaseSpec(
            topology, ThesisGeometry.G500, ThesisDemandFamily.F2,
            ThesisDemandProfile.P0, ThesisObjective.UNSERVED, 1,
        )
        prepared = prepare_experiment_case(spec)
        physical[topology.value] = {
            "allStopCycleSeconds": prepared.all_stop_cycle_tick / 1_000_000,
            "allStopHeadwaySeconds": prepared.all_stop_headway_tick / 1_000_000,
            "allStopReferenceCabins": prepared.all_stop_reference_cabins,
            "physicalDispatchBound": prepared.physical_dispatch_bound,
        }
    manifest["physicalSizing"] = physical
    persist()
    k_as_t5 = physical["t5r"]["allStopReferenceCabins"]
    k_as_t6 = physical["t6r"]["allStopReferenceCabins"]
    k_ref = max(1, min(10, k_as_t5 // 2))
    manifest["journeyKRefCandidate"] = k_ref

    reference_dirs: dict[tuple[str, int, str], Path] = {}
    for topology, objective, cabins in (
        ("t5r", "unserved", k_as_t5),
        ("t6r", "unserved", k_as_t6),
        ("t5r", "journey_time", k_ref),
    ):
        for resolution in (30, 15):
            name = f"reference_{topology}_{objective}_r{resolution}"
            command = [
                sys.executable, str(SINGLE),
                "--topology", topology, "--geometry", "g500",
                "--demand-family", "f2", "--demand-profile", "p0",
                "--objective", objective, "--demand", str(args.maximum_demand),
                "--method", "all_stop_phase", "--capacity-search",
                "--capacity-initial-demand", "100", "--cabins", str(cabins),
                "--release-resolution-seconds", str(resolution),
                "--workers", str(args.workers), "--memory-limit-gib", str(args.memory_limit_gib),
            ]
            reusable = None if args.reuse_reference_root is None else args.reuse_reference_root / name
            if reusable is not None and (reusable / "result.json").is_file():
                validate_reusable_reference(
                    reusable, topology=topology, objective=objective, cabins=cabins,
                    resolution=resolution, maximum_demand=args.maximum_demand,
                )
                target = args.output_dir / name
                shutil.copytree(reusable, target)
                manifest["jobs"].append(
                    {
                        "id": name,
                        "status": "reused",
                        "budgetSeconds": 0,
                        "source": str(reusable),
                    }
                )
                persist()
                reference_dirs[(topology, resolution, objective)] = target
                continue
            target = run_job(name, 240, command)
            if target is None and not args.dry_run:
                continue
            reference_dirs[(topology, resolution, objective)] = target

    if args.dry_run:
        manifest["status"] = "dry_run"
        persist()
        return

    def matching_reference(topology: str, objective: str, resolution: int = 30) -> tuple[int, bool]:
        directory = reference_dirs.get((topology, resolution, objective))
        if directory is None or not (directory / "result.json").is_file():
            return 0, False
        lower, _, proven = _capacity(directory)
        return lower, proven

    # Optimizer runs use the 30 s demand instance, so their load must be derived
    # from that same reference.  A run at the All-Stop capacity cannot show a
    # capacity advantage: both methods may simply serve everybody.  The sizing
    # pilot therefore evaluates the first geometric load step above All-Stop.
    capacity_ref_t5, capacity_ref_t5_proven = matching_reference("t5r", "unserved")
    capacity_ref_t6, capacity_ref_t6_proven = matching_reference("t6r", "unserved")
    journey_ref, journey_ref_proven = matching_reference("t5r", "journey_time")
    capacity_t5 = math.ceil(1.1 * capacity_ref_t5) if capacity_ref_t5 else 0
    capacity_t6 = math.ceil(1.1 * capacity_ref_t6) if capacity_ref_t6 else 0
    journey_demand = math.floor(0.5 * journey_ref) if journey_ref else 0
    manifest["referenceDemandForSizing"] = {
        "allStopCapacityT5At30Seconds": capacity_ref_t5,
        "allStopCapacityT5Proven": capacity_ref_t5_proven,
        "allStopCapacityT6At30Seconds": capacity_ref_t6,
        "allStopCapacityT6Proven": capacity_ref_t6_proven,
        "allStopJourneyKRefCapacityAt30Seconds": journey_ref,
        "allStopJourneyKRefCapacityProven": journey_ref_proven,
        "capacityTestDemandT5": capacity_t5,
        "capacityTestDemandT6": capacity_t6,
        "journeyTestDemandT5": journey_demand,
        "rule": "capacity uses ceil(1.1 * matching 30 s All-Stop capacity); journey uses floor(0.5 * matching 30 s Kref capacity)",
    }
    persist()

    for topology, cabins, demand in (
        ("t5r", k_as_t5, capacity_t5),
        ("t6r", k_as_t6, capacity_t6),
    ):
        if demand <= 0:
            manifest["jobs"].append({"id": f"evolution_{topology}_series", "status": "skipped", "reason": "no_positive_reference_demand"})
            persist()
            continue
        values = tuple(dict.fromkeys((cabins, cabins + 1, math.ceil(1.1 * cabins))))
        remaining = deadline - time.monotonic()
        if remaining <= 3:
            manifest["status"] = "deadline"; persist(); break
        stage_seconds = min(300.0, max(1.0, (remaining - 2) / len(values)))
        command = [
            sys.executable, str(SERIES), "--method", "evolution",
            "--topology", topology, "--geometry", "g500",
            "--demand-family", "f2", "--demand-profile", "p0",
            "--demand", str(demand), "--stage-time-limit", str(stage_seconds),
            "--seed", "0", "--workers", str(args.workers),
            "--memory-limit-gib", str(args.memory_limit_gib),
        ]
        for value in values:
            command.extend(("--k", str(value)))
        # The series owns three 300 s child limits and writes campaign.json.
        target = args.output_dir / f"evolution_{topology}_series"
        entry = {"id": target.name, "status": "running", "budgetSeconds": 900, "command": [*command, "--output-dir", str(target)]}
        manifest["jobs"].append(entry); persist()
        before = time.monotonic()
        completed = subprocess.run([*command, "--output-dir", str(target)], cwd=ROOT, check=False)
        entry.update(status="complete" if completed.returncode == 0 else "failed", exitCode=completed.returncode, wallSeconds=time.monotonic()-before)
        persist(); refresh_frontend()

    arc_values = tuple(dict.fromkeys((k_ref, math.ceil(1.5 * k_ref), min(k_as_t5, math.ceil(2.25 * k_ref)))))
    if journey_demand > 0 and deadline - time.monotonic() > 3:
        remaining = deadline - time.monotonic()
        stage_seconds = min(180.0, max(1.0, (remaining - 2) / len(arc_values)))
        command = [
            sys.executable, str(SERIES), "--method", "labelled_arc_flow",
            "--topology", "t5r", "--geometry", "g500",
            "--demand-family", "f2", "--demand-profile", "p0",
            "--demand", str(journey_demand), "--stage-time-limit", str(stage_seconds),
            "--seed", "0", "--workers", str(args.workers),
            "--memory-limit-gib", str(args.memory_limit_gib),
        ]
        for value in arc_values:
            command.extend(("--k", str(value)))
        target = args.output_dir / "arc_t5r_series"
        entry = {"id": target.name, "status": "running", "budgetSeconds": 540, "command": [*command, "--output-dir", str(target)]}
        manifest["jobs"].append(entry); persist()
        before = time.monotonic(); completed = subprocess.run([*command, "--output-dir", str(target)], cwd=ROOT, check=False)
        entry.update(status="complete" if completed.returncode == 0 else "failed", exitCode=completed.returncode, wallSeconds=time.monotonic()-before)
        persist(); refresh_frontend()

        # Same fixed starts, K values, demand, and arc-flow formulation with all
        # route decisions fixed to STOP.  This is the direct Journey baseline;
        # the phase-capacity reference above answers a different question.
        remaining = deadline - time.monotonic()
        if remaining > 3:
            all_stop_stage_seconds = min(180.0, max(1.0, (remaining - 2) / len(arc_values)))
            all_stop_command = [
                sys.executable, str(SERIES), "--method", "labelled_arc_flow",
                "--operating-mode", "all_stop",
                "--topology", "t5r", "--geometry", "g500",
                "--demand-family", "f2", "--demand-profile", "p0",
                "--demand", str(journey_demand),
                "--stage-time-limit", str(all_stop_stage_seconds),
                "--seed", "0", "--workers", str(args.workers),
                "--memory-limit-gib", str(args.memory_limit_gib),
            ]
            for value in arc_values:
                all_stop_command.extend(("--k", str(value)))
            target = args.output_dir / "arc_t5r_all_stop_series"
            entry = {"id": target.name, "status": "running", "budgetSeconds": 540, "command": [*all_stop_command, "--output-dir", str(target)]}
            manifest["jobs"].append(entry); persist()
            before = time.monotonic(); completed = subprocess.run([*all_stop_command, "--output-dir", str(target)], cwd=ROOT, check=False)
            entry.update(status="complete" if completed.returncode == 0 else "failed", exitCode=completed.returncode, wallSeconds=time.monotonic()-before)
            persist(); refresh_frontend()

    # Confirmation runs begin independently and receive no plan from seed 0.
    if capacity_t6 > 0:
        for seed in (1, 2):
            run_job(
                f"evolution_t6r_k{k_as_t6+1}_seed{seed}", 600,
                [sys.executable, str(SINGLE), "--topology", "t6r", "--geometry", "g500",
                 "--demand-family", "f2", "--demand-profile", "p0", "--objective", "unserved",
                 "--demand", str(capacity_t6), "--method", "evolution", "--cabins", str(k_as_t6+1),
                 "--catalog", "od_endpoints_v1", "--seed", str(seed), "--workers", str(args.workers),
                 "--memory-limit-gib", str(args.memory_limit_gib)],
            )
    if journey_demand > 0:
        largest = max(arc_values)
        for seed in (1, 2):
            run_job(
                f"arc_t5r_k{largest}_seed{seed}", 600,
                [sys.executable, str(SINGLE), "--topology", "t5r", "--geometry", "g500",
                 "--demand-family", "f2", "--demand-profile", "p0", "--objective", "journey_time",
                 "--demand", str(journey_demand), "--method", "labelled_arc_flow", "--cabins", str(largest),
                 "--seed", str(seed), "--workers", str(args.workers),
                 "--memory-limit-gib", str(args.memory_limit_gib)],
            )

    manifest["status"] = (
        "deadline" if time.monotonic() >= deadline else
        "partial" if any(job["status"] in ("failed", "skipped") for job in manifest["jobs"])
        else "complete"
    )
    manifest["completedAt"] = datetime.now(timezone.utc).isoformat()
    persist()
    refresh_frontend()


if __name__ == "__main__":
    main()
