"""Post-optimize one fresh Evo witness in the unrestricted reservoir CP-SAT model."""
from __future__ import annotations

import argparse
from dataclasses import asdict
from datetime import UTC, datetime
import hashlib
import json
import os
from pathlib import Path
import sys
from time import monotonic

from ropeway_skip_stop_optimization.benchmarking.process_supervisor import supervise
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
from ropeway_skip_stop_optimization.optimization.ddd.cp_sat_integrated import DddIntegratedCpSatConfig
from ropeway_skip_stop_optimization.optimization.ddd.cp_sat_passenger import DddCpSatPassengerEncoding
from ropeway_skip_stop_optimization.optimization.ddd.reservoir_cp_sat import (
    DddReservoirCpObjective,
    DddReservoirCpSatOptimizer,
)
from ropeway_skip_stop_optimization.optimization.ddd.reservoir_cp_sat_certificate import (
    DddReservoirCpPlan,
    validate_reservoir_cp_plan,
    write_reservoir_cp_checkpoint,
)
from ropeway_skip_stop_optimization.optimization.ddd.reservoir_hybrid.domain import load_reference


def parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description=__doc__, allow_abbrev=False)
    p.add_argument("--reference-checkpoint", type=Path, required=True)
    p.add_argument("--output-dir", type=Path, required=True)
    p.add_argument("--maximum-wait-seconds", type=float, required=True)
    p.add_argument("--time-limit", type=float, default=1800)
    p.add_argument("--workers", type=int, default=12)
    p.add_argument("--memory-limit-gib", type=float, default=32)
    p.add_argument("--seed", type=int, default=0)
    p.add_argument("--_worker", action="store_true", help=argparse.SUPPRESS)
    return p


def _prepare(a):
    spec = ExperimentCaseSpec(
        topology=ThesisTopology.T5R,
        geometry=ThesisGeometry.G500,
        demand_family=ThesisDemandFamily.F2,
        demand_profile=ThesisDemandProfile.P0,
        objective=ThesisObjective.UNSERVED,
        demand_total=3210,
        release_resolution_seconds=15,
        maximum_wait_seconds=a.maximum_wait_seconds,
    )
    prepared = prepare_experiment_case(spec, fleet_cap=62)
    source_domain, source = load_reference(a.reference_checkpoint)
    source_metrics = validate_reservoir_cp_plan(source_domain.problem, source)
    target = DddReservoirCpPlan(source.trips, dict(source.ride_counts))
    target_metrics = validate_reservoir_cp_plan(prepared.problem, target)
    if (source_metrics.served, source_metrics.unserved, source_metrics.used_fleet) != (
        target_metrics.served, target_metrics.unserved, target_metrics.used_fleet
    ):
        raise ValueError("Evo witness changed while transferring the waiting policy")
    if target_metrics.used_fleet > 62:
        raise ValueError("Evo witness exceeds the post-optimization fleet bound")
    return prepared, target, target_metrics


def _worker(a) -> int:
    started = monotonic()
    prepared, seed_plan, seed_metrics = _prepare(a)
    out = a.output_dir
    atomic_json(out / "domain.json", prepared.problem.manifest)
    write_reservoir_cp_checkpoint(out / "transferred_seed.json", prepared.problem, seed_plan)
    events = []

    def emit(event):
        events.append(event)
        with (out / "events.jsonl").open("a", encoding="utf-8") as stream:
            stream.write(json.dumps(event, sort_keys=True) + "\n")

    reserve = 10.0
    config = DddIntegratedCpSatConfig(
        total_time_limit_seconds=max(0.1, a.time_limit - (monotonic() - started) - reserve),
        num_workers=a.workers,
        seed=a.seed,
        passenger_encoding=DddCpSatPassengerEncoding.OD_INVENTORY,
        checkpoint_path=out / "best.json",
        checkpoint_interval_seconds=1,
        log_search_progress=True,
    )
    with (out / "solver.log").open("w", encoding="utf-8") as log:
        raw = DddReservoirCpSatOptimizer(
            config, DddReservoirCpObjective.SERVICE_THEN_JOURNEY
        ).solve(
            prepared.problem,
            primal_seed=seed_plan,
            minimum_active_fleet=0,
            event_callback=emit,
            log_callback=lambda line: (
                log.write(line if line.endswith("\n") else line + "\n"), log.flush()
            ),
        )
    # The optimizer already validates every exported incumbent and writes the
    # canonical checkpoint. Re-read that checkpoint for an independent final check.
    _, checked = load_reference(out / "best.json")
    final_metrics = validate_reservoir_cp_plan(prepared.problem, checked)
    result = {
        "schema": "thesis_capacity_postoptimization_v1",
        "waiting_max_seconds": a.maximum_wait_seconds,
        "seed_metrics": asdict(seed_metrics),
        "final_metrics": asdict(final_metrics),
        "raw": raw,
        "total_wall_seconds": monotonic() - started,
        "lifecycle": "first_complete_return_at_or_after_service_deadline",
    }
    atomic_json(out / "result.json", result)
    return 0


def main() -> int:
    a = parser().parse_args()
    if a._worker:
        return _worker(a)
    if a.output_dir.exists():
        raise ValueError("output directory already exists")
    a.output_dir.mkdir(parents=True)
    prepared, seed, metrics = _prepare(a)
    atomic_json(a.output_dir / "manifest.json", {
        "schema": "thesis_capacity_postoptimization_manifest_v1",
        "started_utc": datetime.now(UTC).isoformat(),
        "source_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        "reference_checkpoint": str(a.reference_checkpoint.resolve()),
        "problem_fingerprint": prepared.problem.fingerprint,
        "seed_metrics": asdict(metrics),
        "maximum_wait_seconds": a.maximum_wait_seconds,
        "time_limit_seconds": a.time_limit,
        "workers": a.workers,
        "memory_limit_gib": a.memory_limit_gib,
        "seed": a.seed,
        "objective": "service_then_journey",
        "passenger_encoding": "od_inventory",
        "maximum_active_fleet": 62,
        "minimum_active_fleet": 0,
        "lifecycle": "first_complete_return_at_or_after_service_deadline",
    })
    command = [
        sys.executable, str(Path(__file__).resolve()), "--_worker",
        "--reference-checkpoint", str(a.reference_checkpoint),
        "--output-dir", str(a.output_dir),
        "--maximum-wait-seconds", str(a.maximum_wait_seconds),
        "--time-limit", str(a.time_limit),
        "--workers", str(a.workers),
        "--memory-limit-gib", str(a.memory_limit_gib),
        "--seed", str(a.seed),
    ]
    supervision = supervise(
        command, a.output_dir, seconds=a.time_limit,
        memory_bytes=int(a.memory_limit_gib * 1024**3),
        system_memory_pressure_seconds=30, env=dict(os.environ),
    )
    atomic_json(a.output_dir / "supervisor.json", supervision)
    return 0 if supervision.get("exit_code") == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
