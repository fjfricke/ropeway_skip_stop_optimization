"""Run the T5R/F2 full CP-SAT overload pilot with an All-Stop seed."""

from __future__ import annotations

import argparse
from dataclasses import asdict
from datetime import UTC, datetime
import hashlib
import json
import os
from pathlib import Path
from time import monotonic, time
import sys

from ropeway_skip_stop_optimization.benchmarking.native_solvers import supervise
from ropeway_skip_stop_optimization.benchmarking.thesis_full_cp_sat_overload import (
    ThesisOverloadPilotConfig,
    campaign_identity,
    detail_point,
    lexicographic_score,
    prepare_pilot,
    publish_live,
)
from ropeway_skip_stop_optimization.benchmarking.reservoir_cp_fleet_continuation import plan_diagnostics
from ropeway_skip_stop_optimization.optimization.ddd.cp_sat_certificate import atomic_json
from ropeway_skip_stop_optimization.optimization.ddd.cp_sat_integrated import DddIntegratedCpSatConfig
from ropeway_skip_stop_optimization.optimization.ddd.reservoir_cp_sat import (
    DddReservoirCpObjective,
    DddReservoirCpSatOptimizer,
    build_reservoir_cp_sat,
)
from ropeway_skip_stop_optimization.optimization.ddd.cp_sat_passenger import DddCpSatPassengerEncoding
from ropeway_skip_stop_optimization.optimization.ddd.reservoir_cp_sat_certificate import (
    reservoir_cp_plan_from_payload,
    validate_reservoir_cp_plan,
    write_reservoir_cp_checkpoint,
)


ROOT = Path(__file__).resolve().parents[1]


def parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description=__doc__, allow_abbrev=False)
    p.add_argument("--reference-dir", type=Path, required=True)
    p.add_argument("--output-dir", type=Path, required=True)
    p.add_argument("--frontend-root", type=Path)
    p.add_argument("--campaign-id", default="thesis_t5r_f2_full_cp_sat_overload_20260916")
    p.add_argument("--time-limit", type=float, default=1800)
    p.add_argument("--reference-time-limit", type=float, default=120)
    p.add_argument("--workers", type=int, default=12)
    p.add_argument("--memory-limit-gib", type=float, default=32)
    p.add_argument("--seed", type=int, default=0)
    p.add_argument("--build-only", action="store_true")
    p.add_argument("--passenger-encoding", choices=["groups", "od_inventory"], default="groups")
    p.add_argument("--_worker", action="store_true", help=argparse.SUPPRESS)
    return p


def config_from_args(a) -> ThesisOverloadPilotConfig:
    return ThesisOverloadPilotConfig(
        reference_dir=a.reference_dir.resolve(),
        output_dir=a.output_dir.resolve(),
        frontend_root=None if a.frontend_root is None else a.frontend_root.resolve(),
        campaign_id=a.campaign_id,
        total_time_limit_seconds=a.time_limit,
        reference_time_limit_seconds=a.reference_time_limit,
        workers=a.workers,
        memory_limit_gib=a.memory_limit_gib,
        seed=a.seed,
        passenger_encoding=a.passenger_encoding,
    )


def _solver_config(config, seconds: float, checkpoint: Path) -> DddIntegratedCpSatConfig:
    return DddIntegratedCpSatConfig(
        total_time_limit_seconds=max(0.1, seconds),
        num_workers=config.workers,
        seed=config.seed,
        passenger_encoding=DddCpSatPassengerEncoding(config.passenger_encoding),
        checkpoint_path=checkpoint,
        checkpoint_interval_seconds=1,
        log_search_progress=True,
    )


def _worker(config: ThesisOverloadPilotConfig, build_only: bool) -> int:
    started_unix, started = time(), monotonic()
    prepared, transferred, reference_result = prepare_pilot(config)
    problem = prepared.problem
    initial_reference = detail_point(problem, transferred, seconds=0)
    points: list[dict] = []
    publish_live(
        config,
        status="preparing_reference",
        reference=initial_reference,
        points=points,
        started_unix=started_unix,
    )
    atomic_json(config.output_dir / "domain.json", problem.manifest)
    write_reservoir_cp_checkpoint(config.output_dir / "transferred_all_stop.json", problem, transferred)

    if build_only:
        built = build_reservoir_cp_sat(
            problem,
            config=_solver_config(config, config.total_time_limit_seconds, config.output_dir / "best.json"),
            objective=DddReservoirCpObjective.SERVICE_THEN_JOURNEY,
            deadline=monotonic() + config.total_time_limit_seconds,
            lexicographic_unserved_cap=initial_reference["unserved"],
        )
        result = {"build_only": True, "model_stats": built.stats, "model_fingerprint": built.fingerprint}
        atomic_json(config.output_dir / "result.json", result)
        publish_live(config, status="complete", reference=initial_reference, points=[], started_unix=started_unix, model_stats=built.stats)
        return 0

    baseline_seconds = min(
        config.reference_time_limit_seconds,
        max(0.1, config.total_time_limit_seconds - (monotonic() - started) - 10),
    )
    with (config.output_dir / "all_stop_solver.log").open("w", encoding="utf-8") as log:
        baseline_raw = DddReservoirCpSatOptimizer(
            _solver_config(config, baseline_seconds, config.output_dir / "all_stop_reference.json"),
            DddReservoirCpObjective.SERVICE_THEN_JOURNEY,
        ).solve(
            problem,
            primal_seed=transferred,
            fixed_plan=transferred,
            log_callback=lambda line: (log.write(line if line.endswith("\n") else line + "\n"), log.flush()),
        )
    reference_plan = reservoir_cp_plan_from_payload(baseline_raw["plan"])
    validate_reservoir_cp_plan(problem, reference_plan)
    reference = detail_point(problem, reference_plan, seconds=0)
    write_reservoir_cp_checkpoint(config.output_dir / "all_stop_reference.json", problem, reference_plan)
    atomic_json(config.output_dir / "all_stop_result.json", baseline_raw)
    points.append(dict(reference))
    publish_live(config, status="running", reference=reference, points=points, started_unix=started_unix)

    full_seconds = max(0.1, config.total_time_limit_seconds - (monotonic() - started) - 10)
    latest = dict(reference)

    def emit(event: dict) -> None:
        nonlocal latest
        elapsed = monotonic() - started
        if event.get("kind") == "incumbent":
            latest = {
                "seconds": elapsed,
                "ub": int(event["objective_raw"]),
                "lb": latest.get("lb"),
                "gap_percent": None,
                "served": event.get("served", latest["served"]),
                "unserved": event.get("unserved", latest["unserved"]),
                "journey_time_seconds": (
                    event.get("journey_time_tick", round(latest["journey_time_seconds"] * 1_000_000))
                    / 1_000_000
                ),
                "used_fleet": event.get("used_fleet", latest["used_fleet"]),
            }
        if event.get("bound_raw") is not None:
            latest["lb"] = max(0, int(float(event["bound_raw"])))
        latest["seconds"] = elapsed
        latest["gap_percent"] = (
            None
            if latest.get("lb") is None
            else max(0, latest["ub"] - latest["lb"]) / max(1, abs(latest["ub"])) * 100
        )
        if not points or any(latest.get(k) != points[-1].get(k) for k in ("ub", "lb", "served", "journey_time_seconds")):
            points.append(dict(latest))
            atomic_json(config.output_dir / "native_events.json", points)
            publish_live(config, status="running", reference=reference, points=points, started_unix=started_unix)

    with (config.output_dir / "solver.log").open("w", encoding="utf-8") as log:
        raw = DddReservoirCpSatOptimizer(
            _solver_config(config, full_seconds, config.output_dir / "best.json"),
            DddReservoirCpObjective.SERVICE_THEN_JOURNEY,
        ).solve(
            problem,
            primal_seed=reference_plan,
            event_callback=emit,
            log_callback=lambda line: (log.write(line if line.endswith("\n") else line + "\n"), log.flush()),
        )
    plan = reservoir_cp_plan_from_payload(raw["plan"])
    metrics = validate_reservoir_cp_plan(problem, plan)
    final = detail_point(problem, plan, seconds=monotonic() - started, lb=raw.get("cp_lower_bound"))
    if not points or final != points[-1]:
        points.append(final)
    diagnostics = plan_diagnostics(problem, plan)
    result = {
        "schema": "thesis_full_cp_sat_overload_result_v1",
        "config": {**asdict(config), "reference_dir": str(config.reference_dir), "output_dir": str(config.output_dir), "frontend_root": None if config.frontend_root is None else str(config.frontend_root)},
        "case": prepared.manifest,
        "reference_capacity_result": reference_result,
        "reference": reference,
        "raw": raw,
        "diagnostics": diagnostics,
        "lexicographic_score": lexicographic_score(problem, plan),
        "strict_service_improvement": metrics.served > reference["served"],
        "total_wall_seconds": monotonic() - started,
    }
    atomic_json(config.output_dir / "result.json", result)
    publish_live(
        config,
        status="complete",
        reference=reference,
        points=points,
        started_unix=started_unix,
        model_stats=raw.get("model_stats"),
        termination=raw.get("termination_reason"),
    )
    return 0


def _main(config: ThesisOverloadPilotConfig, build_only: bool) -> int:
    config.validate()
    if config.output_dir.exists():
        raise ValueError("output directory already exists")
    config.output_dir.mkdir(parents=True)
    prepared, transferred, _ = prepare_pilot(config)
    initial_reference = detail_point(prepared.problem, transferred, seconds=0)
    atomic_json(
        config.output_dir / "manifest.json",
        {
            "schema": "thesis_full_cp_sat_overload_campaign_v1",
            "campaign_fingerprint": campaign_identity(config, prepared.problem),
            "started_utc": datetime.now(UTC).isoformat(),
            "source_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
            "config": {**asdict(config), "reference_dir": str(config.reference_dir), "output_dir": str(config.output_dir), "frontend_root": None if config.frontend_root is None else str(config.frontend_root)},
        },
    )
    publish_live(config, status="queued", reference=initial_reference, points=[], started_unix=time())
    command = [
        sys.executable,
        str(Path(__file__).resolve()),
        "--_worker",
        "--reference-dir", str(config.reference_dir),
        "--output-dir", str(config.output_dir),
        "--campaign-id", config.campaign_id,
        "--time-limit", str(config.total_time_limit_seconds),
        "--reference-time-limit", str(config.reference_time_limit_seconds),
        "--workers", str(config.workers),
        "--memory-limit-gib", str(config.memory_limit_gib),
        "--seed", str(config.seed),
        "--passenger-encoding", config.passenger_encoding,
    ]
    if config.frontend_root is not None:
        command.extend(("--frontend-root", str(config.frontend_root)))
    if build_only:
        command.append("--build-only")
    supervisor = supervise(
        command,
        config.output_dir,
        seconds=config.total_time_limit_seconds,
        memory_bytes=int(config.memory_limit_gib * 1024**3),
        system_memory_pressure_seconds=30,
        env=dict(os.environ),
    )
    atomic_json(config.output_dir / "supervisor.json", supervisor)
    if not (config.output_dir / "result.json").is_file():
        detail = json.loads((config.output_dir / "detail.json").read_text())
        publish_live(
            config,
            status="resource_limit" if supervisor.get("supervisor_reason") else "failed",
            reference=detail["reference"],
            points=detail.get("points", []),
            started_unix=detail["updated_unix"] - detail.get("elapsed_seconds", 0),
            termination=supervisor.get("supervisor_reason") or f"exit_{supervisor.get('exit_code')}",
        )
    return 0 if supervisor.get("exit_code") == 0 else 1


def main() -> int:
    a = parser().parse_args()
    config = config_from_args(a)
    return _worker(config, a.build_only) if a._worker else _main(config, a.build_only)


if __name__ == "__main__":
    raise SystemExit(main())
