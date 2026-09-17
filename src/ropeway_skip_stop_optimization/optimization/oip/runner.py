from __future__ import annotations

import hashlib
import json
import re
from dataclasses import asdict, dataclass
from datetime import UTC
from pathlib import Path
from typing import Any

from ropeway_skip_stop_optimization.optimization.ean.fleet import (
    EanFleetPlan,
    EanInitialPlacementState,
    EanInitialPlacementStateKind,
)
from ropeway_skip_stop_optimization.optimization.ean.formulation_config import (
    EanFormulationConfig,
    EanHorizonFormulation,
    EanTimeBoundFormulation,
)
from ropeway_skip_stop_optimization.optimization.ean.models import EanFleetMode
from ropeway_skip_stop_optimization.optimization.ean.optimization_config import (
    EanOptimizationConfig,
)
from ropeway_skip_stop_optimization.optimization.ean.optimizers.passenger_model import (
    EanPassengerEncoding,
)
from ropeway_skip_stop_optimization.optimization.ean.optimizers.solver import (
    EanFixedMovementPassengerProblem,
    EanMipStartStrategy,
    EanMovementFeasibilityProblem,
    EanOptimizer,
    EanPassengerServiceProblem,
    EanSolveConfig,
)
from ropeway_skip_stop_optimization.optimization.ean.optimizers.solver_policy import (
    GurobiSolverPolicy,
)
from ropeway_skip_stop_optimization.optimization.ean.passenger_objective import (
    EanPassengerObjective,
)
from ropeway_skip_stop_optimization.optimization.ean.passenger_plan import (
    EanPassengerServicePlan,
    EanServedRideGroup,
)
from ropeway_skip_stop_optimization.optimization.ean.plan import (
    EanCabinTrajectory,
    EanCabinVisit,
    EanMovementPlan,
    EanRouteDecision,
)
from ropeway_skip_stop_optimization.optimization.solver_progress import (
    GurobiMipProgressRecorder,
)

from ...benchmarking.frontend_results import update_campaign_index
from .cp_sat import BuiltOipCpSatModel, OipCpSatConfig, OipCpSatResult, solve_oip_cp_sat
from .domain import OipBackend, OipDomain, OipPassengerEncoding
from .validation import validate_oip_certificate, validate_oip_movement_certificate


@dataclass(frozen=True)
class OipRunConfig:
    backend: OipBackend = OipBackend.CP_SAT
    passenger_encoding: OipPassengerEncoding = OipPassengerEncoding.OD_INVENTORY
    time_limit_seconds: float | None = None
    seed: int = 0
    workers: int = 1
    mip_gap: float | None = None
    build_only: bool = False
    movement_only: bool = False
    fixed_stop_patterns: tuple[tuple[str, ...], ...] | None = None
    passenger_evaluation_time_limit_seconds: float | None = None
    output_directory: Path | None = None
    log_to_console: bool = False
    memory_limit_gib: float | None = 32.0
    reference_directory: Path | None = None
    start_checkpoint_directory: Path | None = None

    def validate(self) -> None:
        if self.time_limit_seconds is not None and self.time_limit_seconds <= 0:
            raise ValueError("OIP run time limit must be positive")
        if self.workers <= 0:
            raise ValueError("OIP run worker count must be positive")
        if self.mip_gap is not None and not 0 <= self.mip_gap <= 1:
            raise ValueError("OIP run MIP gap must lie in [0, 1]")
        if self.memory_limit_gib is not None and self.memory_limit_gib <= 0:
            raise ValueError("OIP run memory limit must be positive")
        if (
            self.passenger_evaluation_time_limit_seconds is not None
            and self.passenger_evaluation_time_limit_seconds <= 0
        ):
            raise ValueError("passenger evaluation time limit must be positive")
        if (
            self.start_checkpoint_directory is not None
            and not self.start_checkpoint_directory.is_dir()
        ):
            raise ValueError("OIP start checkpoint directory does not exist")
        if self.movement_only and self.start_checkpoint_directory is not None:
            raise ValueError("movement-only runner does not yet import checkpoints")
        if (
            self.fixed_stop_patterns is not None
            and not self.movement_only
            and self.backend is not OipBackend.CP_SAT
        ):
            raise ValueError(
                "integrated fixed stop patterns are currently supported only by CP-SAT"
            )
        allowed = {
            OipBackend.CP_SAT: {
                OipPassengerEncoding.OD_INVENTORY,
                OipPassengerEncoding.GROUPS,
            },
            OipBackend.GUROBI: {
                OipPassengerEncoding.RIDE_COUNTS,
                OipPassengerEncoding.SLOTS,
            },
        }
        if not self.movement_only and self.passenger_encoding not in allowed[self.backend]:
            raise ValueError(
                f"{self.backend.value} does not support passenger encoding "
                f"{self.passenger_encoding.value}"
            )


def run_oip(domain: OipDomain, config: OipRunConfig) -> Any:
    """Run one comparable OIP solve and persist a portable manifest."""

    config.validate()
    domain.validate()
    live_points: list[dict[str, Any]] = []
    start = (
        _read_portable_checkpoint(
            config.start_checkpoint_directory,
            domain,
            expected_fixed_stop_patterns=config.fixed_stop_patterns,
        )
        if config.start_checkpoint_directory is not None
        else None
    )
    if config.output_directory is not None:
        _write_live_files(config.output_directory, domain, config, live_points)
    if config.backend is OipBackend.CP_SAT:
        result = solve_oip_cp_sat(
            domain,
            OipCpSatConfig(
                time_limit_seconds=config.time_limit_seconds,
                workers=config.workers,
                seed=config.seed,
                build_only=config.build_only,
                movement_only=config.movement_only,
                fixed_stop_patterns=config.fixed_stop_patterns,
                memory_limit_gib=config.memory_limit_gib,
                passenger_encoding=config.passenger_encoding.value,
                progress_callback=(
                    lambda sample: _record_cp_live_sample(
                        config.output_directory,
                        domain,
                        config,
                        live_points,
                        sample,
                    )
                    if config.output_directory is not None
                    else None
                ),
                initial_movement_plan=start[0] if start else None,
                initial_fleet_plan=start[1] if start else None,
                initial_passenger_plan=start[2] if start else None,
            ),
        )
    else:
        encoding = (
            EanPassengerEncoding.RIDE_COUNTS
            if config.passenger_encoding is OipPassengerEncoding.RIDE_COUNTS
            else EanPassengerEncoding.SLOTS
        )
        progress = GurobiMipProgressRecorder(
            on_sample=(
                lambda sample: _record_gurobi_live_sample(
                    config.output_directory,
                    domain,
                    config,
                    live_points,
                    sample,
                )
                if config.output_directory is not None
                else None
            )
        )
        optimizer = EanOptimizer(
            EanSolveConfig(
                solver_policy=GurobiSolverPolicy(
                    mip_gap=config.mip_gap,
                    time_limit_seconds=config.time_limit_seconds,
                    threads=config.workers,
                    soft_memory_limit_gib=config.memory_limit_gib,
                    seed=config.seed,
                ),
                optimization_config=EanOptimizationConfig(
                    formulation=EanFormulationConfig(
                        horizon=EanHorizonFormulation.EXACT_TIME_ACTIVATION,
                        time_bounds=EanTimeBoundFormulation.INITIAL_PLACEMENT_SAFE,
                    ),
                    enable_oip_full_initial_state_symmetry=(
                        config.fixed_stop_patterns is None
                    ),
                    enable_oip_initial_headway_precedence=(
                        config.fixed_stop_patterns is None
                    ),
                ),
                log_to_console=config.log_to_console,
                build_only=config.build_only,
                total_time_limit_seconds=config.time_limit_seconds,
                time_grid_ticks_per_second=domain.grid.ticks_per_second,
                progress_recorder=progress,
            )
        )
        result = optimizer.solve(
            EanMovementFeasibilityProblem(
                artifact=domain.artifact,
                fixed_stop_patterns=config.fixed_stop_patterns,
            )
            if config.movement_only else EanPassengerServiceProblem(
                scenario=domain.scenario,
                artifact=domain.artifact,
                objective=EanPassengerObjective.JOURNEY_TIME,
                mip_start_strategy=EanMipStartStrategy.NONE,
                passenger_encoding=encoding,
                initial_movement_plan=start[0] if start else None,
                initial_fleet_plan=start[1] if start else None,
                initial_passenger_plan=start[2] if start else None,
            )
        )
    movement = getattr(result, "movement_plan", None)
    fleet = getattr(result, "fleet_plan", None)
    passengers = getattr(result, "passenger_plan", None)
    if config.movement_only and movement is not None and fleet is not None:
        validate_oip_movement_certificate(domain, movement, fleet)
        if config.output_directory is not None:
            config.output_directory.mkdir(parents=True, exist_ok=True)
            (config.output_directory / "movement_certificate.json").write_text(
                json.dumps(
                    {
                        "movement_plan": asdict(movement),
                        "fleet_plan": asdict(fleet),
                    },
                    indent=2,
                    sort_keys=True,
                    default=str,
                )
                + "\n"
            )
    passenger_evaluation = None
    if (
        config.movement_only
        and movement is not None
        and fleet is not None
        and config.passenger_evaluation_time_limit_seconds is not None
        and not config.build_only
    ):
        passenger_evaluation = _evaluate_fixed_movement_passengers(
            domain,
            movement,
            fleet,
            time_limit_seconds=config.passenger_evaluation_time_limit_seconds,
            memory_limit_gib=config.memory_limit_gib,
        )
    if movement is not None and fleet is not None and passengers is not None:
        metrics = validate_oip_certificate(domain, movement, fleet, passengers)
        native_served = getattr(result, "served_passengers", None)
        if native_served is None and hasattr(result, "metadata"):
            native_served = result.metadata.served_passenger_count
        if native_served is not None and native_served != metrics.served:
            raise ValueError("native and independently validated OIP service differ")
        native_journey = getattr(result, "journey_time_seconds", None)
        if native_journey is None and hasattr(result, "metadata"):
            native_journey = result.metadata.objective_value_seconds
        tolerance = max(1e-6, metrics.served / domain.grid.ticks_per_second)
        if (
            native_journey is not None
            and abs(native_journey - metrics.journey_time_seconds) > tolerance
        ):
            raise ValueError(
                "native and independently validated OIP journey time differ"
            )
    if config.output_directory is not None:
        _write_run(
            config.output_directory,
            domain,
            config,
            result,
            passenger_evaluation=passenger_evaluation,
        )
    return result


def _read_portable_checkpoint(
    directory: Path,
    domain: OipDomain,
    *,
    expected_fixed_stop_patterns: tuple[tuple[str, ...], ...] | None = None,
):
    manifest = json.loads((directory / "manifest.json").read_text())
    if manifest.get("domain_fingerprint") != domain.fingerprint:
        raise ValueError("OIP start checkpoint domain fingerprint mismatch")
    checkpoint_patterns = manifest.get("fixed_stop_patterns")
    if expected_fixed_stop_patterns is not None and checkpoint_patterns != [
        list(pattern) for pattern in expected_fixed_stop_patterns
    ]:
        raise ValueError("OIP start checkpoint fixed-pattern mismatch")
    payload = json.loads((directory / "result.json").read_text())
    movement_data = payload.get("movement_plan")
    fleet_data = payload.get("fleet_plan")
    passenger_data = payload.get("passenger_plan")
    if passenger_data is None:
        passenger_data = (payload.get("passenger_evaluation") or {}).get(
            "passenger_plan"
        )
    if not all((movement_data, fleet_data, passenger_data)):
        raise ValueError("OIP start checkpoint has no complete validated certificate")
    trajectories = tuple(
        EanCabinTrajectory(
            cabin_id=item["cabin_id"],
            visits=tuple(
                EanCabinVisit(
                    **{
                        **visit,
                        "decision": EanRouteDecision(
                            str(visit["decision"]).split(".")[-1].lower()
                        ),
                    }
                )
                for visit in item["visits"]
            ),
        )
        for item in movement_data["trajectories"]
    )
    movement = EanMovementPlan(
        **{
            **movement_data,
            "trajectories": trajectories,
            "horizon_formulation": EanHorizonFormulation(
                movement_data["horizon_formulation"]
            ),
            "fleet_mode": EanFleetMode(movement_data["fleet_mode"]),
        }
    )
    fleet = EanFleetPlan(
        **{
            **fleet_data,
            "active_cabin_ids": tuple(fleet_data["active_cabin_ids"]),
            "inactive_cabin_ids": tuple(fleet_data["inactive_cabin_ids"]),
            "initial_states": tuple(
                EanInitialPlacementState(
                    **{
                        **state,
                        "kind": EanInitialPlacementStateKind(state["kind"]),
                    }
                )
                for state in fleet_data["initial_states"]
            ),
            "mode": EanFleetMode(fleet_data["mode"]),
        }
    )
    passengers = EanPassengerServicePlan(
        **{
            **passenger_data,
            "served_rides": tuple(
                EanServedRideGroup(**ride) for ride in passenger_data["served_rides"]
            ),
        }
    )
    validate_oip_certificate(domain, movement, fleet, passengers)
    return movement, fleet, passengers


def _evaluate_fixed_movement_passengers(
    domain: OipDomain,
    movement: EanMovementPlan,
    fleet: EanFleetPlan,
    *,
    time_limit_seconds: float,
    memory_limit_gib: float | None,
) -> dict[str, Any]:
    evaluated = EanOptimizer(
        EanSolveConfig(
            solver_policy=GurobiSolverPolicy(
                mip_gap=0.0,
                time_limit_seconds=time_limit_seconds,
                threads=1,
                soft_memory_limit_gib=memory_limit_gib,
            ),
            total_time_limit_seconds=time_limit_seconds,
            time_grid_ticks_per_second=domain.grid.ticks_per_second,
        )
    ).solve(
        EanFixedMovementPassengerProblem(
            scenario=domain.scenario,
            artifact=domain.artifact,
            movement_plan=movement,
            objective=EanPassengerObjective.JOURNEY_TIME,
            lexicographic_unserved_first=True,
        )
    )
    payload: dict[str, Any] = {
        "status": evaluated.metadata.status,
        "solver_status": evaluated.metadata.solver_status,
        "best_bound": evaluated.metadata.best_bound,
        "mip_gap": evaluated.metadata.mip_gap,
        "runtime_seconds": evaluated.metadata.runtime_seconds,
        "build_seconds": evaluated.metadata.model_setup_runtime_seconds,
        "variable_count": evaluated.metadata.variable_count,
        "constraint_count": evaluated.metadata.constraint_count,
        "passenger_plan": (
            asdict(evaluated.passenger_plan)
            if evaluated.passenger_plan is not None
            else None
        ),
    }
    if evaluated.passenger_plan is not None:
        metrics = validate_oip_certificate(
            domain, movement, fleet, evaluated.passenger_plan
        )
        payload.update(
            served_passengers=metrics.served,
            unserved_passengers=metrics.unserved,
            journey_time_seconds=metrics.journey_time_seconds,
        )
    else:
        payload.update(
            served_passengers=None,
            unserved_passengers=None,
            journey_time_seconds=None,
        )
    return payload


def _write_run(
    directory: Path,
    domain: OipDomain,
    config: OipRunConfig,
    result: Any,
    *,
    passenger_evaluation: dict[str, Any] | None = None,
) -> None:
    directory.mkdir(parents=True, exist_ok=True)
    model_identity = hashlib.sha256(
        json.dumps(
            {
                "domain": domain.fingerprint,
                "backend": config.backend.value,
                "movement_only": config.movement_only,
                "passenger_encoding": config.passenger_encoding.value,
                "fixed_stop_patterns": config.fixed_stop_patterns,
            },
            sort_keys=True,
            separators=(",", ":"),
        ).encode()
    ).hexdigest()
    manifest = {
        "schema_version": 1,
        "domain_fingerprint": domain.fingerprint,
        "comparison_fingerprint": domain.comparison_fingerprint,
        "model_fingerprint": model_identity,
        "backend": config.backend.value,
        "operation": domain.operation.value,
        "passenger_encoding": None if config.movement_only else config.passenger_encoding.value,
        "solve_mode": "movement_feasibility" if config.movement_only else "passenger_service",
        "fixed_stop_patterns": config.fixed_stop_patterns,
        "ticks_per_second": domain.grid.ticks_per_second,
        "fixed_k": domain.fixed_k,
        "k_max": domain.k_max,
        "horizon_seconds": domain.artifact.config.horizon_seconds,
        "operation_seconds": domain.artifact.config.operational_end_seconds,
        "maximum_wait_seconds": max(
            (item.max_wait_seconds or 0.0)
            for item in domain.artifact.config.station_configs
        ),
        "passenger_evaluation_time_limit_seconds": (
            config.passenger_evaluation_time_limit_seconds
        ),
        "start_checkpoint": (
            config.start_checkpoint_directory.as_posix()
            if config.start_checkpoint_directory is not None
            else None
        ),
        "quantization": [
            {
                "name": name,
                "source_seconds": seconds,
                "ticks": ticks,
                "delta_seconds": delta,
            }
            for name, seconds, ticks, delta in domain.quantization_manifest
        ],
    }
    (directory / "manifest.json").write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n"
    )
    if isinstance(result, BuiltOipCpSatModel):
        payload = {
            "status": "build_only",
            "build_seconds": result.build_seconds,
            "model_stats": result.model_stats,
            "resource_interval_count": result.resource_interval_count,
        }
    elif isinstance(result, OipCpSatResult):
        payload = asdict(result)
    else:
        payload = {
            "status": result.metadata.status,
            "metadata": result.metadata.passenger_export_dict(),
            "fleet_plan": asdict(result.fleet_plan) if result.fleet_plan is not None else None,
            "movement_plan": asdict(result.movement_plan) if result.movement_plan is not None else None,
            "passenger_plan": asdict(result.passenger_plan) if result.passenger_plan is not None else None,
        }
    movement_plan = getattr(result, "movement_plan", None)
    movement_visits = tuple(
        visit
        for trajectory in (movement_plan.trajectories if movement_plan else ())
        for visit in trajectory.visits
    )
    payload["maximum_used_wait_seconds"] = max(
        (visit.wait_seconds for visit in movement_visits), default=0.0
    )
    payload["total_used_wait_seconds"] = sum(
        visit.wait_seconds for visit in movement_visits
    )
    payload["passenger_evaluation"] = passenger_evaluation
    (directory / "result.json").write_text(
        json.dumps(payload, indent=2, sort_keys=True, default=str) + "\n"
    )
    _write_frontend_snapshot(
        directory, domain, config, result,
        passenger_evaluation=passenger_evaluation,
    )


def _write_frontend_snapshot(
    directory: Path,
    domain: OipDomain,
    config: OipRunConfig,
    result: Any,
    *,
    passenger_evaluation: dict[str, Any] | None = None,
) -> None:
    from datetime import datetime

    now = datetime.now(UTC).isoformat()
    demand_total = sum(demand.count for demand in domain.scenario.demands)
    if isinstance(result, BuiltOipCpSatModel):
        status = "build_only"
        latest = {
            "seconds": 0.0,
            "ub": None,
            "lb": None,
            "gap_percent": None,
            "served": None,
            "unserved": None,
            "journey_time_seconds": None,
            "used_fleet": None,
        }
        points: list[dict[str, Any]] = []
        build_seconds = result.build_seconds
        search_seconds = 0.0
        stop_count = skip_count = 0
        active_fleet = 0
        peak_rss_gb = None
        model_stats = _cp_model_stats(result.model_stats)
    elif isinstance(result, OipCpSatResult):
        status = result.status
        latest = {
            "seconds": result.runtime_seconds,
            "ub": result.objective_value,
            "lb": result.best_bound,
            "gap_percent": None if result.gap is None else 100 * result.gap,
            "served": result.served_passengers,
            "unserved": result.unserved_passengers,
            "journey_time_seconds": result.journey_time_seconds,
            "used_fleet": len(result.fleet_plan.active_cabin_ids) if result.fleet_plan else None,
        }
        points = [
            {
                "seconds": sample.runtime_seconds,
                "ub": sample.objective_value,
                "lb": sample.best_bound,
                "gap_percent": 100 * sample.gap,
                "served": sample.served_passengers,
                "unserved": sample.unserved_passengers,
                "journey_time_seconds": sample.journey_time_seconds,
                "used_fleet": sample.active_fleet,
            }
            for sample in result.progress_samples
        ]
        if result.objective_value is not None and not points:
            points = [latest]
        build_seconds = result.build_seconds
        search_seconds = result.runtime_seconds
        visits = (
            tuple(visit for trajectory in result.movement_plan.trajectories for visit in trajectory.visits)
            if result.movement_plan is not None
            else ()
        )
        stop_count = sum(visit.decision.value == "stop" for visit in visits)
        skip_count = sum(visit.decision.value == "skip" for visit in visits)
        active_fleet = latest["used_fleet"]
        peak_rss_gb = None
        model_stats = _cp_model_stats(result.model_stats)
    else:
        metadata = result.metadata
        status = metadata.status
        has_solution = bool(metadata.solution_count)
        unserved = metadata.unserved_passenger_count if has_solution else None
        served = metadata.served_passenger_count if has_solution else None
        ticks = domain.grid.ticks_per_second
        weight = demand_total * domain.artifact.config.horizon_seconds * ticks + 1.0
        objective = (
            weight * unserved + ticks * (metadata.objective_value_seconds or 0.0)
            if has_solution and unserved is not None
            else None
        )
        points = [
            {
                "seconds": sample.runtime_seconds,
                "ub": sample.incumbent_objective,
                "lb": sample.best_bound,
                "gap_percent": None if sample.mip_gap is None else 100 * sample.mip_gap,
                "served": None,
                "unserved": None,
                "journey_time_seconds": None,
                "used_fleet": None,
            }
            for sample in metadata.progress_samples
            if sample.incumbent_objective is not None
        ]
        latest = {
            "seconds": metadata.runtime_seconds or 0.0,
            "ub": objective,
            "lb": metadata.best_bound,
            "gap_percent": None if metadata.mip_gap is None else 100 * metadata.mip_gap,
            "served": served,
            "unserved": unserved,
            "journey_time_seconds": metadata.objective_value_seconds if has_solution else None,
            "used_fleet": len(result.fleet_plan.active_cabin_ids) if result.fleet_plan else None,
        }
        if points and points[-1]["ub"] is not None:
            latest["ub"] = points[-1]["ub"]
        if metadata.solution_count:
            points.append(latest)
        build_seconds = metadata.model_setup_runtime_seconds
        search_seconds = metadata.runtime_seconds or 0.0
        stop_count = sum(
            visit.decision.value == "stop"
            for trajectory in (result.movement_plan.trajectories if result.movement_plan else ())
            for visit in trajectory.visits
        )
        skip_count = metadata.skipped_visit_count
        active_fleet = latest["used_fleet"]
        peak_rss_gb = (
            metadata.solve_phase_metrics.peak_memory_gb
            if metadata.solve_phase_metrics is not None
            else None
        )
        model_stats = {
            "variables": metadata.variable_count,
            "constraints": metadata.constraint_count,
            "nonzeros": metadata.model_nonzero_count,
            "ride_candidates": metadata.ride_candidate_count,
        }
    if config.movement_only:
        for point in [latest, *points]:
            for field in ("ub", "lb", "gap_percent", "served", "unserved", "journey_time_seconds"):
                point[field] = None
        if passenger_evaluation is not None:
            latest["served"] = passenger_evaluation.get("served_passengers")
            latest["unserved"] = passenger_evaluation.get("unserved_passengers")
            latest["journey_time_seconds"] = passenger_evaluation.get(
                "journey_time_seconds"
            )
            if latest["served"] is not None:
                points.append(dict(latest))
    initial_placement = None
    initial_states: list[dict[str, Any]] = []
    fleet_plan = getattr(result, "fleet_plan", None)
    movement_plan = getattr(result, "movement_plan", None)
    movement_visits = tuple(
        visit
        for trajectory in (movement_plan.trajectories if movement_plan else ())
        for visit in trajectory.visits
    )
    if fleet_plan is not None:
        by_kind: dict[str, int] = {}
        for state in fleet_plan.initial_states:
            by_kind[state.kind.value] = by_kind.get(state.kind.value, 0) + 1
        initial_placement = ", ".join(
            f"{count}× {kind.replace('_', ' ')}" for kind, count in sorted(by_kind.items())
        )
        initial_states = [
            {
                "cabin_id": state.cabin_id,
                "kind": state.kind.value,
                "switch_id": state.switch_id,
                "visit_index": state.visit_index,
                "progress": state.progress,
                "previous_event_time_seconds": state.previous_event_time_seconds,
                "next_event_time_seconds": state.next_event_time_seconds,
            }
            for state in fleet_plan.initial_states
        ]
    detail = {
        "eyebrow": "Optimierte Anfangsaufstellung · gemeinsamer 1-ms-Vertrag",
        "title": f"{config.backend.value.upper()} · {domain.operation.value.replace('_', ' ')}",
        "subtitle": (
            f"K{'=' if domain.exact_k else '≤'}{domain.k_max} · "
            f"{'Bewegungsmachbarkeit' if config.movement_only else config.passenger_encoding.value} · "
            f"Waiting≤{max((item.max_wait_seconds or 0.0) for item in domain.artifact.config.station_configs):g}s"
        ),
        "status": status,
        "elapsed_seconds": latest["seconds"],
        "demand_total": demand_total,
        "fleet_cap": domain.k_max,
        "all_stop_capacity": 0,
        "maximum_wait_seconds": max(
            (item.max_wait_seconds or 0.0)
            for item in domain.artifact.config.station_configs
        ),
        "maximum_used_wait_seconds": max(
            (visit.wait_seconds for visit in movement_visits), default=0.0
        ),
        "total_used_wait_seconds": sum(
            visit.wait_seconds for visit in movement_visits
        ),
        "passenger_horizon_seconds": domain.artifact.config.horizon_seconds,
        "operation_seconds": domain.artifact.config.operational_end_seconds,
        "pattern_composition": (
            {
                "+".join(pattern): config.fixed_stop_patterns.count(pattern)
                for pattern in set(config.fixed_stop_patterns)
            }
            if config.fixed_stop_patterns is not None
            else None
        ),
        "passenger_evaluation": passenger_evaluation,
        "passenger_encoding": None if config.movement_only else config.passenger_encoding.value,
        "solve_mode": "movement_feasibility" if config.movement_only else "passenger_service",
        "native_incumbent_seen": bool(points) or (config.movement_only and fleet_plan is not None),
        "inherited_start": config.start_checkpoint_directory is not None,
        "inherited_start_value": _load_start_value(config.start_checkpoint_directory),
        "reference": _load_reference(config.reference_directory, domain),
        "latest": latest,
        "points": points,
        "backend": config.backend.value,
        "operation": domain.operation.value,
        "active_fleet": active_fleet,
        "initial_placement": initial_placement,
        "initial_states": initial_states,
        "stop_count": stop_count,
        "skip_count": skip_count,
        "build_seconds": build_seconds,
        "search_seconds": search_seconds,
        "peak_rss_gb": peak_rss_gb,
        "model_stats": model_stats,
    }
    snapshot = {
        "schema_version": 1,
        "campaign_id": directory.name,
        "label": detail["title"],
        "status": status,
        "campaign_kind": "oip_comparison",
        "objective": "movement_feasibility" if config.movement_only else "lexicographic_unserved_then_journey_time",
        "method": "optimized_initial_placement",
        "operating_mode": domain.operation.value,
        "formulation": "common_1ms_oip",
        "sequence": 1,
        "trial_count": 1,
        "completed_trial_count": int(status not in {"running", "build_only"}),
        "trials": [],
        "events": [],
        "updated_at_utc": now,
    }
    _atomic_json(directory / "detail.json", detail)
    _atomic_json(directory / "snapshot.json", snapshot)
    _update_frontend_index(directory, snapshot)


def _load_reference(directory: Path | None, domain: OipDomain) -> dict[str, Any] | None:
    if directory is None:
        return None
    manifest_path = directory / "manifest.json"
    detail_path = directory / "detail.json"
    if not manifest_path.exists() or not detail_path.exists():
        raise ValueError("OIP reference directory needs manifest.json and detail.json")
    manifest = json.loads(manifest_path.read_text())
    if manifest.get("comparison_fingerprint") != domain.comparison_fingerprint:
        raise ValueError("all-stop reference does not use the same OIP domain fingerprint")
    if manifest.get("operation") != "all_stop":
        raise ValueError("OIP reference must come from the all-stop operation")
    detail = json.loads(detail_path.read_text())
    reference = detail.get("latest")
    if not isinstance(reference, dict):
        raise TypeError("OIP reference has no validated latest point")
    return reference


def _cp_model_stats(text: str) -> dict[str, int]:
    variables = re.search(r"#Variables:\s*([0-9,']+)", text)
    constraints = sum(
        int(match.group(1).replace(",", "").replace("'", ""))
        for match in re.finditer(r"#k[^:]+:\s*([0-9,']+)", text)
    )
    return {
        "variables": (
            int(variables.group(1).replace(",", "").replace("'", ""))
            if variables
            else 0
        ),
        "constraints": constraints,
    }


def _record_cp_live_sample(directory, domain, config, points, sample) -> None:
    points.append(
        {
            "seconds": sample.runtime_seconds,
            "ub": sample.objective_value,
            "lb": sample.best_bound,
            "gap_percent": 100 * sample.gap,
            "served": sample.served_passengers,
            "unserved": sample.unserved_passengers,
            "journey_time_seconds": sample.journey_time_seconds,
            "used_fleet": sample.active_fleet,
        }
    )
    _write_live_files(directory, domain, config, points)


def _record_gurobi_live_sample(directory, domain, config, points, sample) -> None:
    if config.movement_only or sample.incumbent_objective is None:
        return
    points.append(
        {
            "seconds": sample.runtime_seconds,
            "ub": sample.incumbent_objective,
            "lb": sample.best_bound,
            "gap_percent": None if sample.mip_gap is None else 100 * sample.mip_gap,
            "served": None,
            "unserved": None,
            "journey_time_seconds": None,
            "used_fleet": None,
        }
    )
    _write_live_files(directory, domain, config, points)


def _write_live_files(directory, domain, config, points) -> None:
    from datetime import datetime

    directory.mkdir(parents=True, exist_ok=True)
    demand_total = sum(demand.count for demand in domain.scenario.demands)
    maximum_wait_seconds = max(
        (item.max_wait_seconds or 0.0)
        for item in domain.artifact.config.station_configs
    )
    latest = points[-1] if points else {
        "seconds": 0.0,
        "ub": None,
        "lb": None,
        "gap_percent": None,
        "served": None,
        "unserved": None,
        "journey_time_seconds": None,
        "used_fleet": None,
    }
    detail = {
        "eyebrow": "Optimierte Anfangsaufstellung · gemeinsamer 1-ms-Vertrag",
        "title": f"{config.backend.value.upper()} · {domain.operation.value.replace('_', ' ')}",
        "subtitle": (
            f"K{'=' if domain.exact_k else '≤'}{domain.k_max} · "
            f"{'Bewegungsmachbarkeit' if config.movement_only else config.passenger_encoding.value} · "
            f"{'No-Wait' if maximum_wait_seconds == 0 else f'Waiting≤{maximum_wait_seconds:g}s'}"
        ),
        "status": "running",
        "elapsed_seconds": latest["seconds"],
        "demand_total": demand_total,
        "fleet_cap": domain.k_max,
        "all_stop_capacity": 0,
        "maximum_wait_seconds": maximum_wait_seconds,
        "passenger_encoding": None if config.movement_only else config.passenger_encoding.value,
        "solve_mode": "movement_feasibility" if config.movement_only else "passenger_service",
        "native_incumbent_seen": bool(points),
        "inherited_start": config.start_checkpoint_directory is not None,
        "inherited_start_value": _load_start_value(config.start_checkpoint_directory),
        "reference": _load_reference(config.reference_directory, domain),
        "latest": latest,
        "points": points,
        "backend": config.backend.value,
        "operation": domain.operation.value,
    }
    snapshot = {
        "schema_version": 1,
        "campaign_id": directory.name,
        "label": detail["title"],
        "status": "running",
        "campaign_kind": "oip_comparison",
        "objective": "movement_feasibility" if config.movement_only else "lexicographic_unserved_then_journey_time",
        "method": "optimized_initial_placement",
        "operating_mode": domain.operation.value,
        "formulation": "common_1ms_oip",
        "sequence": len(points),
        "trial_count": 1,
        "completed_trial_count": 0,
        "trials": [],
        "events": [],
        "updated_at_utc": datetime.now(UTC).isoformat(),
    }
    _atomic_json(directory / "detail.json", detail)
    _atomic_json(directory / "snapshot.json", snapshot)
    _update_frontend_index(directory, snapshot)


def _atomic_json(path: Path, payload: dict[str, Any]) -> None:
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(payload, indent=2, sort_keys=True, default=str) + "\n")
    temporary.replace(path)


def _load_start_value(directory: Path | None) -> dict[str, Any] | None:
    if directory is None:
        return None
    detail_path = directory / "detail.json"
    if not detail_path.exists():
        return None
    return json.loads(detail_path.read_text()).get("latest")


def _update_frontend_index(directory: Path, snapshot: dict[str, Any]) -> None:
    if directory.parent.name != "optimization":
        return
    update_campaign_index(directory.parent, snapshot)
