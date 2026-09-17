"""Run full reservoir CP-SAT at the proven All-Stop demand.

The phase-optimised All-Stop certificate is transferred into a fresh problem
with the requested waiting limit.  It supplies a validated incumbent and
cutoff and, unless explicitly disabled, a primal hint. Dispatches, routes,
waiting, fleet activation and passengers remain free in the full solve.
"""

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

from ropeway_skip_stop_optimization.benchmarking.process_supervisor import supervise
from ropeway_skip_stop_optimization.benchmarking.optimization_live_store import (
    OptimizationLivePaths,
    OptimizationLiveStore,
)
from ropeway_skip_stop_optimization.benchmarking.reservoir_cp_fleet_continuation import (
    plan_diagnostics,
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
from ropeway_skip_stop_optimization.benchmarking.thesis_full_cp_sat_overload import (
    detail_point,
    lexicographic_score,
)
from ropeway_skip_stop_optimization.optimization.ddd.cp_sat_certificate import (
    atomic_json,
    stable_fingerprint,
)
from ropeway_skip_stop_optimization.optimization.ddd.cp_sat_integrated import (
    DddIntegratedCpSatConfig,
)
from ropeway_skip_stop_optimization.optimization.ddd.cp_sat_passenger import (
    DddCpSatPassengerEncoding,
)
from ropeway_skip_stop_optimization.optimization.ddd.reservoir_cp_sat import (
    DddReservoirCpObjective,
    DddReservoirCpSatOptimizer,
    build_reservoir_cp_sat,
)
from ropeway_skip_stop_optimization.optimization.ddd.reservoir_cp_sat_certificate import (
    DddReservoirCpPlan,
    reservoir_cp_plan_from_payload,
    validate_reservoir_cp_plan,
    write_reservoir_cp_checkpoint,
)
from ropeway_skip_stop_optimization.optimization.ddd.time_ticks import (
    DDD_TIME_TICKS_PER_SECOND,
    ddd_seconds_to_tick,
)
from ropeway_skip_stop_optimization.optimization.ddd.reservoir_hybrid.domain import (
    load_reference,
)


TERMINAL_STATUSES = {"complete", "failed", "resource_limit", "interrupted"}


def parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description=__doc__, allow_abbrev=False)
    p.add_argument("--reference-dir", type=Path, required=True)
    p.add_argument("--output-dir", type=Path, required=True)
    p.add_argument("--frontend-root", type=Path)
    p.add_argument(
        "--campaign-id",
        default="thesis_t5r_f2_all_stop_n_wait120_cp_sat_20260916",
    )
    p.add_argument("--time-limit", type=float, default=1800.0)
    p.add_argument("--maximum-wait-seconds", type=float, default=120.0)
    p.add_argument("--workers", type=int, default=12)
    p.add_argument("--fixed-k", type=int)
    p.add_argument("--memory-limit-gib", type=float, default=32.0)
    p.add_argument("--seed", type=int, default=0)
    p.add_argument("--passenger-encoding", choices=["groups", "od_inventory"], default="od_inventory")
    p.add_argument(
        "--time-ticks-per-second",
        type=int,
        default=DDD_TIME_TICKS_PER_SECOND,
    )
    p.add_argument("--route-search-priority", action="store_true")
    p.add_argument(
        "--no-primal-hint",
        action="store_true",
        help="Keep the validated cutoff but do not hint the All-Stop solution to CP-SAT.",
    )
    p.add_argument(
        "--no-primal-reference",
        action="store_true",
        help="Use All-Stop only for reporting: no hint, cutoff, or unserved cap.",
    )
    p.add_argument("--build-only", action="store_true")
    p.add_argument("--_worker", action="store_true", help=argparse.SUPPRESS)
    return p


def _spec(maximum_wait_seconds: float) -> ExperimentCaseSpec:
    return ExperimentCaseSpec(
        topology=ThesisTopology.T5R,
        geometry=ThesisGeometry.G500,
        demand_family=ThesisDemandFamily.F2,
        demand_profile=ThesisDemandProfile.P0,
        objective=ThesisObjective.UNSERVED,
        demand_total=2918,
        release_resolution_seconds=15,
        maximum_wait_seconds=maximum_wait_seconds,
    )


def _prepare(a):
    if not (a.reference_dir / "best.json").is_file() or not (a.reference_dir / "result.json").is_file():
        raise ValueError("All-Stop reference directory is incomplete")
    reference_result = json.loads((a.reference_dir / "result.json").read_text())
    run = reference_result.get("run", {})
    if (
        reference_result.get("method") != "all_stop_phase"
        or run.get("capacity") != 2918
        or run.get("capacity_proven") is not True
        or run.get("proof_scope")
        != "REGULAR_NO_WAIT_ALL_STOP_COMMON_PHASE_AND_NESTED_DEMAND"
    ):
        raise ValueError("reference is not the proven T5R/F2 All-Stop capacity")
    prepared = prepare_experiment_case(_spec(a.maximum_wait_seconds), fleet_cap=62)
    if a.no_primal_reference:
        return prepared, None, reference_result
    source_domain, source_plan = load_reference(a.reference_dir / "best.json")
    source_manifest = source_domain.problem.manifest
    target_manifest = prepared.problem.manifest
    excluded = {
        "available_fleet_count",
        "derived_visit_count",
        "operating_mode",
        "waiting_policy",
    }
    if ({k: v for k, v in source_manifest.items() if k not in excluded}
            != {k: v for k, v in target_manifest.items() if k not in excluded}):
        raise ValueError("All-Stop reference and target differ beyond the waiting limit")
    transferred = DddReservoirCpPlan(source_plan.trips, dict(source_plan.ride_counts))
    metrics = validate_reservoir_cp_plan(prepared.problem, transferred)
    if metrics.served != 2918 or metrics.unserved != 0 or metrics.used_fleet != 62:
        raise ValueError("transferred All-Stop plan does not preserve the reference")
    return prepared, transferred, reference_result


def _reference_point(problem, seed_plan, reference_result):
    if seed_plan is not None:
        return detail_point(problem, seed_plan, seconds=0)
    capacity = reference_result["run"]["capacity"]
    probe = next(
        item
        for item in reference_result["run"]["probes"]
        if item.get("demand") == capacity and item.get("outcome") == "feasible"
    )
    metrics = probe["solve"]["metrics"]
    source_ticks = reference_result.get("time_ticks_per_second", 1_000_000)
    journey_seconds = metrics["journey_time_tick"] / source_ticks
    return {
        "seconds": 0,
        "ub": round(journey_seconds * DDD_TIME_TICKS_PER_SECOND),
        "lb": None,
        "gap_percent": None,
        "served": capacity,
        "unserved": 0,
        "journey_time_seconds": journey_seconds,
        "used_fleet": metrics.get("used_fleet", metrics.get("peak_active_fleet")),
    }


def _solver_config(a, seconds: float, checkpoint: Path) -> DddIntegratedCpSatConfig:
    return DddIntegratedCpSatConfig(
        total_time_limit_seconds=max(0.1, seconds),
        num_workers=a.workers,
        seed=a.seed,
        passenger_encoding=DddCpSatPassengerEncoding(a.passenger_encoding),
        checkpoint_path=checkpoint,
        checkpoint_interval_seconds=1,
        log_search_progress=True,
        route_search_priority=a.route_search_priority,
    )


def _publish(a, *, status: str, reference: dict, points: list[dict], started_unix: float,
             model_stats: dict | None = None, termination: str | None = None) -> None:
    latest = points[-1] if points else reference
    payload = {
        "schema": "thesis_all_stop_n_cp_sat_frontend_v1",
        "campaign_id": a.campaign_id,
        "title": (
            f"All-Stop-N · K={a.fixed_k} fix · "
            f"{'No-Wait' if a.maximum_wait_seconds == 0 else f'Waiting ≤ {a.maximum_wait_seconds:g} s'} · "
            "STOP/SKIP-Priorität · referenzfreie Suche"
            if a.route_search_priority and a.no_primal_reference and a.fixed_k is not None
            else "All-Stop-N · STOP/SKIP-Priorität · referenzfreie Suche"
            if a.route_search_priority and a.no_primal_reference
            else "All-Stop-N · STOP/SKIP-Priorität · ohne Start-Hint"
            if a.route_search_priority and a.no_primal_hint
            else "All-Stop-N · STOP/SKIP-priorisierte Suche"
            if a.route_search_priority
            else "All-Stop-N · freie Skip-Stop-Suche"
        ),
        "subtitle": (
            "T5R · G500 · F2 · P0 · "
            f"{DDD_TIME_TICKS_PER_SECOND:,} Ticks/s · "
            "lexikografisch: Bedienung, dann Journey Time"
        ),
        "reference_label": "All-Stop · N=2.918",
        "status": status,
        "updated_unix": time(),
        "elapsed_seconds": max(0.0, time() - started_unix),
        "demand_total": 2918,
        "fleet_cap": 62,
        "fixed_k": a.fixed_k,
        "all_stop_capacity": 2918,
        "maximum_wait_seconds": a.maximum_wait_seconds,
        "time_ticks_per_second": DDD_TIME_TICKS_PER_SECOND,
        "objective": DddReservoirCpObjective.SERVICE_THEN_JOURNEY.value,
        "passenger_encoding": a.passenger_encoding,
        "route_search_priority": a.route_search_priority,
        "primal_hint_enabled": not (a.no_primal_hint or a.no_primal_reference),
        "primal_cutoff_enabled": not a.no_primal_reference,
        "primal_lexicographic_cap_enabled": not a.no_primal_reference,
        "native_incumbent_seen": bool(points),
        "reference": reference,
        "points": points,
        "latest": latest,
        "model_stats": model_stats or {},
        "termination": termination,
    }
    atomic_json(a.output_dir / "detail.json", payload)
    if a.frontend_root is not None:
        atomic_json(a.frontend_root / a.campaign_id / "detail.json", payload)
    snapshot = {
        "schema_version": 1,
        "campaign_id": a.campaign_id,
        "label": (
            f"T5R/F2 · full CP-SAT · fixed K={a.fixed_k} · STOP/SKIP priority · "
            f"no reference · {'no wait' if a.maximum_wait_seconds == 0 else f'wait ≤ {a.maximum_wait_seconds:g} s'}"
            if a.route_search_priority and a.no_primal_reference and a.fixed_k is not None
            else "T5R/F2 · full CP-SAT · STOP/SKIP priority · no reference · wait 120 s"
            if a.route_search_priority and a.no_primal_reference
            else "T5R/F2 · full CP-SAT · STOP/SKIP priority · no hint · wait 120 s"
            if a.route_search_priority and a.no_primal_hint
            else "T5R/F2 · full CP-SAT · STOP/SKIP priority · wait 120 s"
            if a.route_search_priority
            else "T5R/F2 · full CP-SAT at All-Stop N · wait 120 s"
        ),
        "status": status,
        "objective": "service_then_journey",
        "method": "full_reservoir_cp_sat",
        "formulation": "od_inventory",
        "campaign_kind": "thesis_full_cp_sat_overload",
        "operating_mode": "skip_stop",
        "updated_at_utc": datetime.now(UTC).isoformat(),
        "trials": [],
        "events": [],
        "trial_count": 1,
        "completed_trial_count": int(status in TERMINAL_STATUSES),
    }
    OptimizationLiveStore(OptimizationLivePaths(a.output_dir, a.frontend_root)).publish(snapshot)


def _worker(a) -> int:
    started_unix, started = time(), monotonic()
    prepared, seed_plan, reference_result = _prepare(a)
    problem = prepared.problem
    reference = _reference_point(problem, seed_plan, reference_result)
    points = [] if a.no_primal_reference else [dict(reference)]
    _publish(a, status="building", reference=reference, points=points, started_unix=started_unix)
    atomic_json(a.output_dir / "domain.json", problem.manifest)
    if seed_plan is not None:
        write_reservoir_cp_checkpoint(
            a.output_dir / "all_stop_reference.json", problem, seed_plan
        )

    if a.build_only:
        built = build_reservoir_cp_sat(
            problem,
            config=_solver_config(a, a.time_limit, a.output_dir / "best.json"),
            objective=DddReservoirCpObjective.SERVICE_THEN_JOURNEY,
            deadline=monotonic() + a.time_limit,
            lexicographic_unserved_cap=None if a.no_primal_reference else 0,
            minimum_active_fleet=0 if a.fixed_k is None else a.fixed_k,
        )
        atomic_json(a.output_dir / "result.json", {"build_only": True, "model_stats": built.stats})
        _publish(a, status="complete", reference=reference, points=points,
                 started_unix=started_unix, model_stats=built.stats)
        return 0

    latest = dict(reference)
    native_incumbent_seen = False

    def emit(event: dict) -> None:
        nonlocal latest, native_incumbent_seen
        elapsed = monotonic() - started
        if event.get("kind") == "incumbent":
            native_incumbent_seen = True
            latest = {
                "seconds": elapsed,
                "ub": int(event["objective_raw"]),
                "lb": latest.get("lb"),
                "gap_percent": None,
                "served": event.get("served", latest["served"]),
                "unserved": event.get("unserved", latest["unserved"]),
                "journey_time_seconds": event.get(
                    "journey_time_tick",
                    round(
                        latest["journey_time_seconds"]
                        * DDD_TIME_TICKS_PER_SECOND
                    ),
                ) / DDD_TIME_TICKS_PER_SECOND,
                "used_fleet": event.get("used_fleet", latest["used_fleet"]),
            }
        if event.get("bound_raw") is not None:
            latest["lb"] = max(0, int(float(event["bound_raw"])))
        latest["seconds"] = elapsed
        latest["gap_percent"] = (
            None if latest.get("lb") is None
            else max(0, latest["ub"] - latest["lb"]) / max(1, abs(latest["ub"])) * 100
        )
        if native_incumbent_seen and (not points or any(
            latest.get(key) != points[-1].get(key)
            for key in ("ub", "lb", "served", "journey_time_seconds")
        )):
            points.append(dict(latest))
            atomic_json(a.output_dir / "native_events.json", points)
            _publish(a, status="running", reference=reference, points=points, started_unix=started_unix)

    remaining = max(0.1, a.time_limit - (monotonic() - started) - 5.0)
    _publish(a, status="running", reference=reference, points=points, started_unix=started_unix)
    with (a.output_dir / "solver.log").open("w", encoding="utf-8") as log:
        write_log = lambda line: (
            log.write(line if line.endswith("\n") else line + "\n"),
            log.flush(),
        )
        if a.no_primal_reference and DDD_TIME_TICKS_PER_SECOND <= 1_000:
            write_log(
                "=== Single phase: reference-free lexicographic service and journey ==="
            )
            raw = DddReservoirCpSatOptimizer(
                _solver_config(a, remaining, a.output_dir / "best.json"),
                DddReservoirCpObjective.SERVICE_THEN_JOURNEY,
            ).solve(
                problem,
                use_primal_hint=False,
                use_primal_cutoff=False,
                use_primal_lexicographic_cap=False,
                minimum_active_fleet=0 if a.fixed_k is None else a.fixed_k,
                event_callback=emit,
                log_callback=write_log,
            )
            raw["reference_free_lexicographic_mode"] = "single_phase"
        elif a.no_primal_reference:
            horizon = problem.movement.passenger_service_end_tick
            lex_weight = 1 + sum(
                group.count
                * max(0, horizon - ddd_seconds_to_tick(group.release_time_seconds))
                for group in problem.demand_groups
            )

            def emit_service(event: dict) -> None:
                translated = dict(event)
                if event.get("unserved") is not None:
                    translated["objective_raw"] = (
                        int(lex_weight) * int(event["unserved"])
                        + int(event["journey_time_tick"])
                    )
                if event.get("bound_raw") is not None:
                    translated["bound_raw"] = (
                        max(0, int(float(event["bound_raw"]))) * int(lex_weight)
                    )
                emit(translated)

            write_log("=== Phase 1: minimize unserved without external reference ===")
            phase_one = DddReservoirCpSatOptimizer(
                _solver_config(a, remaining, a.output_dir / "best.json"),
                DddReservoirCpObjective.UNSERVED,
            ).solve(
                problem,
                use_primal_hint=False,
                use_primal_cutoff=False,
                use_primal_lexicographic_cap=False,
                minimum_active_fleet=0 if a.fixed_k is None else a.fixed_k,
                event_callback=emit_service,
                log_callback=write_log,
            )
            raw = phase_one
            phase_one_summary = {
                key: phase_one.get(key)
                for key in (
                    "solver_status", "termination_reason", "proven_optimal",
                    "validated_upper_bound", "cp_lower_bound", "metrics",
                    "build_seconds", "solve_seconds", "total_wall_seconds",
                )
            }
            remaining = max(0.0, a.time_limit - (monotonic() - started) - 5.0)
            if phase_one["metrics"]["unserved"] == 0 and remaining > 1:
                native_seed = reservoir_cp_plan_from_payload(phase_one["plan"])
                write_log("=== Phase 2: minimize journey time at native full service ===")
                raw = DddReservoirCpSatOptimizer(
                    _solver_config(a, remaining, a.output_dir / "best.json"),
                    DddReservoirCpObjective.SERVICE_THEN_JOURNEY,
                ).solve(
                    problem,
                    primal_seed=native_seed,
                    minimum_active_fleet=0 if a.fixed_k is None else a.fixed_k,
                    event_callback=emit,
                    log_callback=write_log,
                )
            raw["reference_free_service_phase"] = phase_one_summary
            raw["reference_free_lexicographic_mode"] = "two_phase"
        else:
            raw = DddReservoirCpSatOptimizer(
                _solver_config(a, remaining, a.output_dir / "best.json"),
                DddReservoirCpObjective.SERVICE_THEN_JOURNEY,
            ).solve(
                problem,
                primal_seed=seed_plan,
                use_primal_hint=not a.no_primal_hint,
                minimum_active_fleet=0 if a.fixed_k is None else a.fixed_k,
                event_callback=emit,
                log_callback=write_log,
            )
    plan = reservoir_cp_plan_from_payload(raw["plan"])
    validate_reservoir_cp_plan(problem, plan)
    final_lb = raw.get("cp_lower_bound")
    if raw.get("objective") == DddReservoirCpObjective.UNSERVED.value and final_lb is not None:
        final_lb = int(final_lb) * int(lex_weight)
    final = detail_point(problem, plan, seconds=monotonic() - started, lb=final_lb)
    if raw.get("cp_objective_raw") is not None and (not points or final != points[-1]):
        points.append(final)
    result = {
        "schema": "thesis_all_stop_n_cp_sat_result_v1",
        "case": prepared.manifest,
        "reference_capacity_result": reference_result,
        "reference": reference,
        "raw": raw,
        "diagnostics": plan_diagnostics(problem, plan),
        "lexicographic_score": lexicographic_score(problem, plan),
        "total_wall_seconds": monotonic() - started,
    }
    atomic_json(a.output_dir / "result.json", result)
    _publish(a, status="complete", reference=reference, points=points,
             started_unix=started_unix, model_stats=raw.get("model_stats"),
             termination=raw.get("termination_reason"))
    return 0


def _main(a) -> int:
    if a.time_limit <= 10 or a.maximum_wait_seconds < 0 or a.workers <= 0:
        raise ValueError("invalid solve configuration")
    if a.time_ticks_per_second != DDD_TIME_TICKS_PER_SECOND:
        raise ValueError(
            "--time-ticks-per-second must match "
            "ROPEWAY_DDD_TIME_TICKS_PER_SECOND at process start"
        )
    if not 0 < a.memory_limit_gib <= 32:
        raise ValueError("memory limit must be in (0, 32] GiB")
    if a.fixed_k is not None and not 1 <= a.fixed_k <= 62:
        raise ValueError("fixed K must lie in [1, 62]")
    if a.output_dir.exists():
        raise ValueError("output directory already exists")
    a.output_dir.mkdir(parents=True)
    prepared, seed_plan, _ = _prepare(a)
    reference_result = json.loads((a.reference_dir / "result.json").read_text())
    reference = _reference_point(prepared.problem, seed_plan, reference_result)
    manifest_config = {
        key: str(value) if isinstance(value, Path) else value
        for key, value in vars(a).items() if key != "_worker"
    }
    atomic_json(a.output_dir / "manifest.json", {
        "schema": "thesis_all_stop_n_cp_sat_campaign_v1",
        "started_utc": datetime.now(UTC).isoformat(),
        "source_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        "config": manifest_config,
        "campaign_fingerprint": stable_fingerprint({
            "config": manifest_config,
            "problem": prepared.problem.manifest,
        }),
    })
    _publish(a, status="queued", reference=reference, points=[], started_unix=time())
    command = [
        sys.executable, str(Path(__file__).resolve()), "--_worker",
        "--reference-dir", str(a.reference_dir),
        "--output-dir", str(a.output_dir),
        "--campaign-id", a.campaign_id,
        "--time-limit", str(a.time_limit),
        "--maximum-wait-seconds", str(a.maximum_wait_seconds),
        "--workers", str(a.workers),
        "--memory-limit-gib", str(a.memory_limit_gib),
        "--seed", str(a.seed),
        "--passenger-encoding", a.passenger_encoding,
        "--time-ticks-per-second", str(a.time_ticks_per_second),
    ]
    if a.fixed_k is not None:
        command.extend(("--fixed-k", str(a.fixed_k)))
    if a.route_search_priority:
        command.append("--route-search-priority")
    if a.no_primal_hint:
        command.append("--no-primal-hint")
    if a.no_primal_reference:
        command.append("--no-primal-reference")
    if a.frontend_root is not None:
        command.extend(("--frontend-root", str(a.frontend_root)))
    if a.build_only:
        command.append("--build-only")
    supervisor = supervise(
        command,
        a.output_dir,
        seconds=a.time_limit,
        memory_bytes=int(a.memory_limit_gib * 1024**3),
        system_memory_pressure_seconds=30,
        env=dict(os.environ),
    )
    atomic_json(a.output_dir / "supervisor.json", supervisor)
    if not (a.output_dir / "result.json").is_file():
        detail = json.loads((a.output_dir / "detail.json").read_text())
        _publish(
            a,
            status="resource_limit" if supervisor.get("supervisor_reason") else "failed",
            reference=detail["reference"],
            points=detail.get("points", []),
            started_unix=detail["updated_unix"] - detail.get("elapsed_seconds", 0),
            termination=supervisor.get("supervisor_reason") or f"exit_{supervisor.get('exit_code')}",
        )
    return 0 if supervisor.get("exit_code") == 0 else 1


def main() -> int:
    a = parser().parse_args()
    a.reference_dir = a.reference_dir.resolve()
    a.output_dir = a.output_dir.resolve()
    a.frontend_root = None if a.frontend_root is None else a.frontend_root.resolve()
    return _worker(a) if a._worker else _main(a)


if __name__ == "__main__":
    raise SystemExit(main())
