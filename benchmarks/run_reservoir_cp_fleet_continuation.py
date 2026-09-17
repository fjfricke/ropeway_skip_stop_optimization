"""Progressively enlarge the full reservoir CP-SAT fleet cap with free reoptimization."""

from __future__ import annotations

import argparse
from dataclasses import asdict
from datetime import UTC, datetime
import hashlib
from importlib.metadata import PackageNotFoundError, version
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import time

from ropeway_skip_stop_optimization.benchmarking.process_supervisor import supervise
from ropeway_skip_stop_optimization.benchmarking.optimization_events import OptimizationEventKind
from ropeway_skip_stop_optimization.benchmarking.optimization_live_store import (
    OptimizationLivePaths,
    OptimizationLiveStore,
)
from ropeway_skip_stop_optimization.benchmarking.reservoir_cp_fleet_continuation import (
    FleetContinuationBudget,
    FleetContinuationConfig,
    campaign_identity,
    export_frontend_detail,
    load_frozen_r2_problem,
    objective_seconds,
    plan_diagnostics,
    publish,
    run_stage,
    stage_problem,
)
from ropeway_skip_stop_optimization.optimization.ddd.cp_sat_certificate import atomic_json
from ropeway_skip_stop_optimization.optimization.ddd.reservoir_cp_sat_certificate import (
    DddReservoirCpPlan,
    read_reservoir_cp_checkpoint_for_fleet_resize,
    validate_reservoir_cp_plan,
    write_reservoir_cp_checkpoint,
)


ROOT = Path(__file__).resolve().parents[1]


def parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description=__doc__, allow_abbrev=False)
    p.add_argument("--case-file", type=Path, required=True)
    p.add_argument("--output-dir", type=Path, required=True)
    p.add_argument("--frontend-root", type=Path)
    p.add_argument("--campaign-id", default="reservoir_cp_fleet_continuation_r2")
    p.add_argument("--first-k", type=int, default=1)
    p.add_argument("--last-k", type=int, default=50)
    p.add_argument("--total-time-limit", type=float, default=7200)
    p.add_argument("--workers", type=int, default=12)
    p.add_argument("--memory-limit-gib", type=float, default=32)
    p.add_argument("--seed", type=int, default=0)
    p.add_argument("--resume", action="store_true")
    p.add_argument("--build-only", action="store_true")
    p.add_argument("--skip-correctness-gate", action="store_true")
    p.add_argument("--_worker", action="store_true", help=argparse.SUPPRESS)
    p.add_argument("--_fleet-cap", type=int, help=argparse.SUPPRESS)
    p.add_argument("--_stage-time-limit", type=float, help=argparse.SUPPRESS)
    p.add_argument("--_seed-checkpoint", type=Path, help=argparse.SUPPRESS)
    return p


def _config(a) -> FleetContinuationConfig:
    return FleetContinuationConfig(
        case_file=a.case_file.resolve(),
        output_dir=a.output_dir.resolve(),
        budget=FleetContinuationBudget(a.first_k, a.last_k),
        total_time_limit_seconds=a.total_time_limit,
        workers=a.workers,
        memory_limit_gib=a.memory_limit_gib,
        seed=a.seed,
        frontend_root=None if a.frontend_root is None else a.frontend_root.resolve(),
        campaign_id=a.campaign_id,
    )


def _worker(a) -> int:
    if a._fleet_cap is None or a._stage_time_limit is None:
        raise ValueError("worker requires a fleet cap and stage time limit")
    problem = load_frozen_r2_problem(a.case_file)
    a.output_dir.mkdir(parents=True, exist_ok=True)
    events = a.output_dir / "native_events.jsonl"
    with events.open("w", encoding="utf-8") as stream:
        def emit(item: dict) -> None:
            stream.write(json.dumps(item, sort_keys=True) + "\n")
            stream.flush()

        run_stage(
            problem,
            k=a._fleet_cap,
            time_limit_seconds=a._stage_time_limit,
            workers=a.workers,
            seed=a.seed,
            output_dir=a.output_dir,
            seed_checkpoint=a._seed_checkpoint,
            build_only=a.build_only,
            event_callback=emit,
        )
    return 0


def _versions() -> dict:
    result = {"python": sys.version}
    for package in ("ortools", "psutil"):
        try:
            result[package] = version(package)
        except PackageNotFoundError:
            result[package] = None
    return result


def _source_hashes() -> dict[str, str]:
    paths = [
        Path(__file__),
        ROOT / "src/ropeway_skip_stop_optimization/benchmarking/reservoir_cp_fleet_continuation.py",
        ROOT / "src/ropeway_skip_stop_optimization/optimization/ddd/reservoir_cp_sat.py",
        ROOT / "src/ropeway_skip_stop_optimization/optimization/ddd/reservoir_cp_sat_movement.py",
        ROOT / "src/ropeway_skip_stop_optimization/optimization/ddd/cp_sat_passenger.py",
    ]
    return {
        str(path.relative_to(ROOT)): hashlib.sha256(path.read_bytes()).hexdigest()
        for path in paths
    }


def _run_correctness_gate(output: Path) -> None:
    tests = (
        "tests/test_reservoir_cp_fleet_continuation.py",
        "tests/test_optimization_ddd_reservoir_cp_sat.py",
        "tests/test_reservoir_boundary.py",
    )
    with (output / "correctness.log").open("w", encoding="utf-8") as log:
        completed = subprocess.run(
            [sys.executable, "-m", "pytest", *tests, "-q"],
            cwd=ROOT,
            stdout=log,
            stderr=subprocess.STDOUT,
            check=False,
        )
    if completed.returncode:
        raise RuntimeError("correctness gate failed; campaign was not started")


def _completed_caps(store: OptimizationLiveStore) -> set[int]:
    events = store.read_events()
    return {
        event.available_fleet_count
        for event in events
        if event.kind is OptimizationEventKind.TRIAL_COMPLETED
        and event.available_fleet_count is not None
    }


def _last_checkpoint(output: Path, caps: set[int]) -> Path | None:
    for k in sorted(caps, reverse=True):
        candidates = sorted(
            (output / "stages" / f"k{k:02d}").glob("attempt*/artifact/best.json")
        )
        if candidates:
            return candidates[-1]
    return None


def _publish_live(store: OptimizationLiveStore, config: FleetContinuationConfig) -> dict:
    snapshot = publish(store)
    if config.frontend_root is not None:
        export_frontend_detail(
            config.output_dir,
            config.frontend_root / config.campaign_id,
        )
    return snapshot


def _next_attempt(stage_root: Path) -> Path:
    stage_root.mkdir(parents=True, exist_ok=True)
    numbers = [
        int(path.name.removeprefix("attempt"))
        for path in stage_root.glob("attempt[0-9][0-9][0-9]")
        if path.name.removeprefix("attempt").isdigit()
    ]
    return stage_root / f"attempt{max(numbers, default=0) + 1:03d}"


def _main(a) -> int:
    config = _config(a)
    config.validate()
    frozen = load_frozen_r2_problem(config.case_file)
    identity = campaign_identity(config, frozen)
    output = config.output_dir
    if a.resume:
        if not output.is_dir():
            raise ValueError("resume output directory does not exist")
        manifest = json.loads((output / "manifest.json").read_text(encoding="utf-8"))
        if manifest.get("campaign_fingerprint") != identity:
            raise ValueError("resume configuration differs from the frozen campaign")
    else:
        output.mkdir(parents=True, exist_ok=False)
        shutil.copy2(config.case_file, output / "frozen_case.json")
        atomic_json(
            output / "manifest.json",
            {
                "schema": "reservoir_cp_fleet_continuation_campaign_v1",
                "campaign_fingerprint": identity,
                "campaign_id": config.campaign_id,
                "started_utc": datetime.now(UTC).isoformat(),
                "config": {**asdict(config), "case_file": str(config.case_file), "output_dir": str(output), "frontend_root": None if config.frontend_root is None else str(config.frontend_root)},
                "frozen_problem_fingerprint": frozen.fingerprint,
                "case_sha256": hashlib.sha256(config.case_file.read_bytes()).hexdigest(),
                "versions": _versions(),
                "source_sha256": _source_hashes(),
                "consumed_wall_seconds": 0.0,
            },
        )
        if not a.skip_correctness_gate:
            _run_correctness_gate(output)

    store = OptimizationLiveStore(
        OptimizationLivePaths(output, config.frontend_root)
    )
    campaign_payload = {
        "label": "R2 · progressive full CP-SAT fleet continuation",
        "campaign_kind": "reservoir_cp_fleet_continuation",
        "method": "full_reservoir_cp_sat",
        "formulation": "legacy_product",
        "objective": "journey_time",
        "operating_mode": "skip_stop",
        "minimum_k": config.budget.first_k,
        "maximum_k": config.budget.last_k,
        "trial_count": config.budget.last_k - config.budget.first_k + 1,
        "case_fingerprint": frozen.fingerprint,
    }
    existing_events = store.read_events()
    if not existing_events:
        store.append_new(
            OptimizationEventKind.CAMPAIGN_STARTED,
            config.campaign_id,
            payload=campaign_payload,
        )
        for k in range(config.budget.first_k, config.budget.last_k + 1):
            store.append_new(
                OptimizationEventKind.TRIAL_QUEUED,
                config.campaign_id,
                policy_id="continuation",
                available_fleet_count=k,
                payload={"budget_seconds": config.budget.seconds_for(k)},
            )
        _publish_live(store, config)
    elif a.resume and existing_events[-1].kind is OptimizationEventKind.CAMPAIGN_COMPLETED:
        store.append_new(
            OptimizationEventKind.CAMPAIGN_STARTED,
            config.campaign_id,
            payload=campaign_payload,
        )
        _publish_live(store, config)

    completed = _completed_caps(store)
    checkpoint = _last_checkpoint(output, completed)
    manifest_path = output / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    consumed = float(manifest.get("consumed_wall_seconds", 0.0))
    remaining_campaign_seconds = max(0.0, config.total_time_limit_seconds - consumed)
    started_civil, started_awake = time.time(), time.monotonic()
    global_deadline = started_civil + remaining_campaign_seconds
    for k in range(config.budget.first_k, config.budget.last_k + 1):
        if k in completed:
            continue
        if time.time() >= global_deadline - 5:
            break
        budget = min(config.budget.seconds_for(k), global_deadline - time.time() - 2)
        if budget <= 2:
            break
        problem = stage_problem(frozen, k)
        seed_plan = (
            read_reservoir_cp_checkpoint_for_fleet_resize(checkpoint, problem)
            if checkpoint is not None
            else DddReservoirCpPlan((), {})
        )
        stage_root = output / "stages" / f"k{k:02d}"
        # A valid checkpoint from an interrupted attempt is retained and may
        # improve the completed previous-K seed. It remains only a hint.
        for recovered in sorted(stage_root.glob("attempt*/artifact/best.json")):
            candidate = read_reservoir_cp_checkpoint_for_fleet_resize(recovered, problem)
            if validate_reservoir_cp_plan(problem, candidate).journey_time_tick < validate_reservoir_cp_plan(problem, seed_plan).journey_time_tick:
                seed_plan, checkpoint = candidate, recovered
        stage = _next_attempt(stage_root)
        stage.mkdir(exist_ok=False)
        seed_diag = plan_diagnostics(problem, seed_plan)
        input_checkpoint = stage / "input_seed.json"
        write_reservoir_cp_checkpoint(input_checkpoint, problem, seed_plan)
        store.append_new(
            OptimizationEventKind.TRIAL_STARTED,
            config.campaign_id,
            policy_id="continuation",
            available_fleet_count=k,
            stage="full_cp_sat",
            elapsed_seconds=time.monotonic() - started_awake,
            payload={
                "budget_seconds": budget,
                "seed_provenance": "empty" if checkpoint is None else str(checkpoint.relative_to(output)),
                "seed_objective_seconds": seed_diag["journey_objective_seconds"],
                "seed_served": seed_diag["served"],
                "seed_used_fleet": seed_diag["used_fleet"],
            },
        )
        _publish_live(store, config)
        last_live_objective = [None]

        def checkpoint_callback(path: Path, elapsed: float) -> None:
            plan = read_reservoir_cp_checkpoint_for_fleet_resize(path, problem)
            diag = plan_diagnostics(problem, plan)
            objective = diag["journey_objective_seconds"]
            if last_live_objective[0] == objective:
                return
            last_live_objective[0] = objective
            store.append_new(
                OptimizationEventKind.INCUMBENT_VALIDATED,
                config.campaign_id,
                policy_id="continuation",
                available_fleet_count=k,
                stage="full_cp_sat",
                local_solver_incumbent=objective,
                elapsed_seconds=time.monotonic() - started_awake,
                payload={
                    "stage_elapsed_seconds": elapsed,
                    "served": diag["served"],
                    "unserved": diag["unserved"],
                    "dispatched_fleet_count": diag["used_fleet"],
                    "passenger_carrying_skip_count": diag["passenger_carrying_skip_count"],
                    "strict_improvement_over_seed": diag["journey_time_tick"] < seed_diag["journey_time_tick"],
                },
            )
            _publish_live(store, config)

        command = [
            sys.executable,
            str(Path(__file__).resolve()),
            "--_worker",
            "--case-file", str(config.case_file),
            "--output-dir", str(stage / "artifact"),
            "--_fleet-cap", str(k),
            "--_stage-time-limit", str(max(0.1, budget - 2)),
            "--_seed-checkpoint", str(input_checkpoint),
            "--workers", str(config.workers),
            "--memory-limit-gib", str(config.memory_limit_gib),
            "--seed", str(config.seed),
        ]
        if a.build_only:
            command.append("--build-only")
        artifact = stage / "artifact"
        artifact.mkdir()
        supervisor = supervise(
            command,
            artifact,
            seconds=budget,
            memory_bytes=int(config.memory_limit_gib * 1024**3),
            global_deadline=global_deadline,
            checkpoint_callback=checkpoint_callback,
            system_memory_pressure_seconds=30,
            env=dict(os.environ),
        )
        consumed += float(supervisor["civil_wall_seconds"])
        manifest["consumed_wall_seconds"] = consumed
        manifest["last_updated_utc"] = datetime.now(UTC).isoformat()
        atomic_json(manifest_path, manifest)
        result_path = artifact / "result.json"
        result = json.loads(result_path.read_text(encoding="utf-8")) if result_path.is_file() else {}
        candidate_path = artifact / "best.json"
        if candidate_path.is_file():
            candidate = read_reservoir_cp_checkpoint_for_fleet_resize(candidate_path, problem)
        else:
            candidate = seed_plan
            write_reservoir_cp_checkpoint(candidate_path, problem, candidate)
        diagnostics = plan_diagnostics(problem, candidate)
        checkpoint = candidate_path
        model_stats = result.get("model_stats", {})
        status = result.get("solver_status", supervisor.get("supervisor_reason") or "NO_RESULT")
        store.append_new(
            OptimizationEventKind.TRIAL_COMPLETED,
            config.campaign_id,
            policy_id="continuation",
            available_fleet_count=k,
            stage="full_cp_sat",
            local_solver_incumbent=diagnostics["journey_objective_seconds"],
            local_solver_bound=result.get("cp_lower_bound"),
            local_solver_gap=result.get("relative_gap"),
            elapsed_seconds=time.monotonic() - started_awake,
            payload={
                "status": status,
                "termination": result.get("termination_reason", supervisor.get("supervisor_reason")),
                "validated_upper_bound": diagnostics["journey_objective_seconds"],
                "certified_lower_bound": result.get("cp_lower_bound"),
                "relative_gap": result.get("relative_gap"),
                "served": diagnostics["served"],
                "unserved": diagnostics["unserved"],
                "dispatched_fleet_count": diagnostics["used_fleet"],
                "peak_active_fleet_count": diagnostics["peak_active_fleet"],
                "mean_served_journey_seconds": diagnostics["mean_served_journey_seconds"],
                "stop_count": diagnostics["stop_count"],
                "skip_count": diagnostics["skip_count"],
                "passenger_carrying_skip_count": diagnostics["passenger_carrying_skip_count"],
                "seed_objective_seconds": seed_diag["journey_objective_seconds"],
                "native_strict_improvement": diagnostics["journey_time_tick"] < seed_diag["journey_time_tick"],
                "movement_variable_count": model_stats.get("movement_variables"),
                "passenger_variable_count": model_stats.get("passenger_variables"),
                "linear_constraint_count": model_stats.get("constraints"),
                "model_variable_count": model_stats.get("variables"),
                "build_seconds": result.get("build_seconds"),
                "solve_seconds": result.get("solve_seconds"),
                "peak_rss_bytes": supervisor.get("peak_process_tree_rss_bytes"),
                "worker_exit_code": supervisor.get("exit_code"),
            },
        )
        _publish_live(store, config)
        if a.build_only:
            break
    final_status = "complete" if len(_completed_caps(store)) == config.budget.last_k - config.budget.first_k + 1 else "deadline"
    store.append_new(
        OptimizationEventKind.CAMPAIGN_COMPLETED,
        config.campaign_id,
        elapsed_seconds=time.monotonic() - started_awake,
        payload={"status": final_status},
    )
    snapshot = _publish_live(store, config)
    atomic_json(output / "summary.json", snapshot)
    manifest["consumed_wall_seconds"] = consumed
    manifest["last_status"] = final_status
    manifest["last_updated_utc"] = datetime.now(UTC).isoformat()
    atomic_json(manifest_path, manifest)
    return 0


def main() -> int:
    a = parser().parse_args()
    return _worker(a) if a._worker else _main(a)


if __name__ == "__main__":
    raise SystemExit(main())
