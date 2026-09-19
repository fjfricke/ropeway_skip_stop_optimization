from __future__ import annotations

import hashlib
import json
import re
from dataclasses import asdict, dataclass, replace
import time
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
from .passenger_candidates import oip_passenger_candidate_builder
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
    type_catalog: str | None = None
    fixed_type_counts: dict[str, int] | None = None
    passenger_evaluation_time_limit_seconds: float | None = None
    output_directory: Path | None = None
    log_to_console: bool = False
    memory_limit_gib: float | None = 32.0
    reference_directory: Path | None = None
    start_checkpoint_directory: Path | None = None
    formulation: str = "ean"
    objective: str = "lexicographic"
    stop_if_cannot_beat_reference: bool = False
    deadline_unix: float | None = None
    completion_reserve_seconds: float = 10.0

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
        if self.type_catalog not in {None, "all_stop_alternating", "all_stop_bd_ce"}:
            raise ValueError("unknown OIP cabin type catalog")
        if self.type_catalog is not None and self.fixed_stop_patterns is not None:
            raise ValueError("type catalog and fixed stop patterns are mutually exclusive")
        if self.type_catalog is not None and self.backend is not OipBackend.CP_SAT:
            raise ValueError("OIP cabin type catalogs currently require CP-SAT")
        if self.formulation not in {"ean", "nowait_templates"}:
            raise ValueError("unknown OIP formulation")
        if self.objective not in {"lexicographic", "served"}:
            raise ValueError("unknown OIP objective")
        if self.formulation == "nowait_templates" and (
            self.backend is not OipBackend.CP_SAT
            or self.type_catalog is None
            or self.movement_only
            or self.objective != "served"
        ):
            raise ValueError(
                "No-Wait templates require CP-SAT, a type catalog, passengers, and served objective"
            )
        if self.backend is not OipBackend.CP_SAT and self.objective != "lexicographic":
            raise ValueError("served-only OIP currently requires CP-SAT")
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
    if config.fixed_type_counts is not None and (config.start_checkpoint_directory is not None or config.formulation != "nowait_templates" or config.backend is not OipBackend.CP_SAT):
        raise ValueError("Fixed type counts require CP-SAT nowait_templates without a start checkpoint")
    domain.validate()
    if config.formulation == "nowait_templates" and any(
        (item.max_wait_seconds or 0.0) != 0.0
        for item in domain.artifact.config.station_configs
    ):
        raise ValueError("No-Wait templates do not support waiting")
    reference_cutoff = None
    if config.stop_if_cannot_beat_reference:
        if config.reference_directory is None or config.objective != "served" or config.backend is not OipBackend.CP_SAT:
            raise ValueError("Reference stopping requires a matching reference and CP-SAT served objective")
        reference_certificate = _read_portable_checkpoint(config.reference_directory, domain)
        reference_cutoff = validate_oip_certificate(domain, *reference_certificate).served
    live_points: list[dict[str, Any]] = []
    start = (
        _read_portable_checkpoint(
            config.start_checkpoint_directory,
            domain,
            expected_fixed_stop_patterns=config.fixed_stop_patterns,
            expected_type_catalog=config.type_catalog,
        )
        if config.start_checkpoint_directory is not None
        else None
    )
    if config.output_directory is not None:
        _write_live_files(config.output_directory, domain, config, live_points)
    if config.deadline_unix is not None:
        remaining = config.deadline_unix - time.time() - config.completion_reserve_seconds
        if remaining <= 0:
            raise TimeoutError("OIP preparation exhausted the solve budget; no feasibility conclusion")
        config = replace(config, time_limit_seconds=min(config.time_limit_seconds or remaining, remaining))
    incumbent_store = None
    if config.backend is OipBackend.CP_SAT and config.output_directory is not None and not config.build_only and not config.movement_only:
        from .incumbent_store import OipIncumbentStore
        incumbent_store = OipIncumbentStore(
            domain, config.output_directory,
            lambda directory, incumbent: _write_run(directory, domain, config, incumbent),
        )
    if config.backend is OipBackend.CP_SAT:
        result = solve_oip_cp_sat(
            domain,
            OipCpSatConfig(
                time_limit_seconds=config.time_limit_seconds,
                search_deadline_unix=(config.deadline_unix - config.completion_reserve_seconds
                                      if config.deadline_unix is not None else None),
                workers=config.workers,
                seed=config.seed,
                build_only=config.build_only,
                movement_only=config.movement_only,
                fixed_stop_patterns=config.fixed_stop_patterns,
                stop_at_reference_served=reference_cutoff,
                type_catalog=config.type_catalog,
                fixed_type_counts=config.fixed_type_counts,
                formulation=config.formulation,
                objective=config.objective,
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
                incumbent_callback=incumbent_store.submit if incumbent_store is not None else None,
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
    if (
        isinstance(result, OipCpSatResult)
        and result.movement_plan is None
        and start is not None
        and not config.build_only
    ):
        # CP-SAT can spend the whole budget without reporting the hinted point
        # as a native solution.  The independently validated portable start is
        # still a legitimate campaign incumbent, but must not be presented as
        # native search progress.
        start_metrics = validate_oip_certificate(domain, start[0], start[1], start[2])
        horizon_tick = domain.grid.upper_tick(domain.artifact.config.horizon_seconds)
        total_demand = sum(item.count for item in domain.scenario.demands)
        weight = total_demand * horizon_tick + 1
        objective = (
            start_metrics.unserved
            if config.objective == "served"
            else weight * start_metrics.unserved
                + domain.grid.lower_tick(start_metrics.journey_time_seconds)
        )
        result = OipCpSatResult(
            status="feasible",
            solver_status=f"INHERITED_START_AFTER_{result.solver_status}",
            objective_value=objective,
            best_bound=result.best_bound,
            gap=(
                None
                if result.best_bound is None
                else abs(objective - result.best_bound) / max(1, abs(objective))
            ),
            runtime_seconds=result.runtime_seconds,
            build_seconds=result.build_seconds,
            movement_plan=start[0],
            fleet_plan=start[1],
            passenger_plan=start[2],
            served_passengers=start_metrics.served,
            unserved_passengers=start_metrics.unserved,
            journey_time_seconds=start_metrics.journey_time_seconds,
            model_stats=result.model_stats,
            progress_samples=result.progress_samples,
            cabin_types={cabin_id: "all_stop" for cabin_id in start[1].active_cabin_ids},
            type_counts={"all_stop": len(start[1].active_cabin_ids)},
        )
    checked_incumbent = False
    if incumbent_store is not None:
        incumbent_store.submit(result)
        timeout = (max(0.0, config.deadline_unix - time.time() - 1.0)
                   if config.deadline_unix is not None else None)
        checked = incumbent_store.finish(timeout)
        if checked is not None:
            checked_incumbent = True
            if checked is not result:
                # Final validation may outlast the reserve. Keep an earlier checked
                # incumbent and only the conservative bound saved with that solve.
                result = replace(checked, solver_status="FEASIBLE_CHECKPOINT",
                                 termination_reason="finalization_deadline")
        elif result.movement_plan is not None:
            # Native counts without independent validation are not final results.
            result = replace(result, status="unknown", solver_status="VALIDATION_PENDING",
                             movement_plan=None, fleet_plan=None, passenger_plan=None,
                             served_passengers=None, unserved_passengers=None,
                             journey_time_seconds=None, objective_value=None, gap=None,
                             termination_reason="finalization_deadline")
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
    if not checked_incumbent and movement is not None and fleet is not None and passengers is not None:
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
    expected_type_catalog: str | None = None,
):
    manifest = json.loads((directory / "manifest.json").read_text())
    if manifest.get("domain_fingerprint") != domain.fingerprint:
        portable_all_stop = (
            manifest.get("operation") == "all_stop"
            and manifest.get("comparison_fingerprint")
            == domain.comparison_fingerprint
        )
        if not portable_all_stop:
            raise ValueError("OIP start checkpoint domain fingerprint mismatch")
    checkpoint_patterns = manifest.get("fixed_stop_patterns")
    if expected_fixed_stop_patterns is not None and checkpoint_patterns != [
        list(pattern) for pattern in expected_fixed_stop_patterns
    ]:
        raise ValueError("OIP start checkpoint fixed-pattern mismatch")
    checkpoint_catalog = manifest.get("type_catalog")
    if expected_type_catalog is not None and checkpoint_catalog not in {
        None, expected_type_catalog
    }:
        raise ValueError("OIP start checkpoint type-catalog mismatch")
    payload = json.loads((directory / "result.json").read_text())
    return decode_oip_certificate(payload, domain)


def decode_oip_certificate(payload, domain):
    """Deserialize and independently validate; domain provenance belongs to the importer."""
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
            passenger_builder=oip_passenger_candidate_builder(),
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
                "type_catalog": config.type_catalog,
        "fixed_type_counts": config.fixed_type_counts,
        "stop_if_cannot_beat_reference": config.stop_if_cannot_beat_reference,
                "formulation": config.formulation,
                "objective": config.objective,
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
        "type_catalog": config.type_catalog,
        "fixed_type_counts": config.fixed_type_counts,
        "stop_if_cannot_beat_reference": config.stop_if_cannot_beat_reference,
        "formulation": config.formulation,
        "objective": config.objective,
        "ticks_per_second": domain.grid.ticks_per_second,
        "fixed_k": domain.fixed_k,
        "k_max": domain.k_max,
        "horizon_seconds": domain.artifact.config.horizon_seconds,
        "operation_seconds": domain.artifact.config.operational_end_seconds,
        "headway_contract": (domain.scenario.experiment_metadata or {}).get("headway_contract"),
        "deadline_unix": config.deadline_unix,
        "completion_reserve_seconds": config.completion_reserve_seconds,
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
    _atomic_json(directory / "manifest.json", manifest)
    if isinstance(result, BuiltOipCpSatModel):
        payload = {
            "status": "build_only",
            "build_seconds": result.build_seconds,
            "model_stats": result.model_stats,
            "reduction_stats": result.reduction_stats,
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
    _atomic_json(directory / "result.json", payload)
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
            "type_counts": result.type_counts,
        }
        latest.update(_bound_fields(domain, config, latest))
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
                "type_counts": sample.type_counts,
            }
            for sample in result.progress_samples
        ]
        for point in points:
            point.update(_bound_fields(domain, config, point))
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
        if result.presolved_model_stats:
            presolved = _cp_model_stats(result.presolved_model_stats)
            model_stats.update(
                presolved_variables=presolved["variables"],
                presolved_constraints=presolved["constraints"],
                presolved_intervals=presolved["intervals"],
            )
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
        "headway_contract": (domain.scenario.experiment_metadata or {}).get("headway_contract"),
        "deadline_unix": config.deadline_unix,
        "completion_reserve_seconds": config.completion_reserve_seconds,
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
        "type_catalog": config.type_catalog,
        "fixed_type_counts": config.fixed_type_counts,
        "stop_if_cannot_beat_reference": config.stop_if_cannot_beat_reference,
        "type_counts": getattr(result, "type_counts", None),
        "cabin_types": getattr(result, "cabin_types", None),
        "passenger_evaluation": passenger_evaluation,
        "passenger_encoding": None if config.movement_only else config.passenger_encoding.value,
        "solve_mode": "movement_feasibility" if config.movement_only else "passenger_service",
        "termination_reason": getattr(result, "termination_reason", None),
        "reference_served_cutoff": getattr(result, "reference_served_cutoff", None),
        "native_incumbent_seen": (
            not str(getattr(result, "solver_status", "")).startswith("INHERITED_START_AFTER_")
            and (bool(points) or fleet_plan is not None)
        ),
        "inherited_start": config.start_checkpoint_directory is not None,
        "inherited_start_value": _load_start_value(config.start_checkpoint_directory),
        "reference": _load_reference(config.reference_directory, domain),
        "latest": latest,
        "points": points,
        "backend": config.backend.value,
        "formulation": config.formulation,
        "objective": _objective_id(config),
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
        "reduction_stats": getattr(result, "reduction_stats", None),
    }
    snapshot = {
        "schema_version": 1,
        "campaign_id": directory.name,
        "label": detail["title"],
        "status": status,
        "campaign_kind": "oip_comparison",
        "objective": _objective_id(config),
        "method": "optimized_initial_placement",
        "operating_mode": domain.operation.value,
        "formulation": config.formulation,
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
        "intervals": sum(int(m.group(1).replace("\'", "").replace(",", ""))
                         for m in re.finditer(r"#kInterval:\s*([0-9,']+)", text)),
    }


def _record_cp_live_sample(directory, domain, config, points, sample) -> None:
    point = {
            "seconds": sample.runtime_seconds,
            "ub": sample.objective_value,
            "lb": sample.best_bound,
            "gap_percent": 100 * sample.gap,
            "served": sample.served_passengers,
            "unserved": sample.unserved_passengers,
            "journey_time_seconds": sample.journey_time_seconds,
            "used_fleet": sample.active_fleet,
            "type_counts": sample.type_counts,
        }
    point.update(_bound_fields(domain, config, point))
    points.append(point)
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
        "type_catalog": config.type_catalog,
        "fixed_type_counts": config.fixed_type_counts,
        "stop_if_cannot_beat_reference": config.stop_if_cannot_beat_reference,
        "type_counts": latest.get("type_counts"),
    }
    snapshot = {
        "schema_version": 1,
        "campaign_id": directory.name,
        "label": detail["title"],
        "status": "running",
        "campaign_kind": "oip_comparison",
        "objective": _objective_id(config),
        "method": "optimized_initial_placement",
        "operating_mode": domain.operation.value,
        "formulation": config.formulation,
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


def _objective_id(config: OipRunConfig) -> str:
    if config.movement_only:
        return "movement_feasibility"
    return (
        "minimize_unserved"
        if config.objective == "served"
        else "lexicographic_unserved_then_journey_time"
    )


def _bound_fields(
    domain: OipDomain, config: OipRunConfig, point: dict[str, Any]
) -> dict[str, Any]:
    if config.objective == "served":
        total = sum(item.count for item in domain.scenario.demands)
        bound = point.get("lb")
        incumbent_unserved = point.get("unserved")
        return {
            "served_lower_bound": (
                None if incumbent_unserved is None else total - int(incumbent_unserved)
            ),
            "served_upper_bound": (
                None if bound is None else total - max(0, min(total, int(bound)))
            ),
            "journey_time_lower_bound": None,
        }
    return _lexicographic_bound_fields(domain, point)


def _lexicographic_bound_fields(domain: OipDomain, point: dict[str, Any]) -> dict[str, Any]:
    """Derive primary bounds; expose a journey LB only after primary closure."""
    total = sum(item.count for item in domain.scenario.demands)
    bound = point.get("lb")
    incumbent_unserved = point.get("unserved")
    if bound is None or incumbent_unserved is None:
        return {
            "served_lower_bound": None,
            "served_upper_bound": None,
            "journey_time_lower_bound": None,
        }
    horizon = domain.grid.upper_tick(domain.artifact.config.horizon_seconds)
    secondary_maximum = total * horizon
    weight = secondary_maximum + 1
    lower_unserved = max(0, min(total, (int(bound) - secondary_maximum + weight - 1) // weight))
    fields = {
        "served_lower_bound": total - int(incumbent_unserved),
        "served_upper_bound": total - lower_unserved,
        "journey_time_lower_bound": None,
    }
    if lower_unserved == int(incumbent_unserved):
        fields["journey_time_lower_bound"] = domain.grid.seconds(
            max(0, int(bound) - weight * int(incumbent_unserved))
        )
    return fields


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
