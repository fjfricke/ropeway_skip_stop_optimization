from __future__ import annotations

import math
import logging
from dataclasses import dataclass, field
from enum import StrEnum
from pathlib import Path
from typing import Any

from ropeway_skip_stop_optimization.models import Scenario
from ropeway_skip_stop_optimization.optimization.ean.artifact import EanBuildArtifact
from ropeway_skip_stop_optimization.optimization.ean.baselines import (
    EarliestAllStopEanMovementPlanBuilder,
)
from ropeway_skip_stop_optimization.optimization.ean.builders.passenger_builder import (
    EanPassengerCandidateBuildResult,
    EanPassengerCandidateBuilder,
)
from ropeway_skip_stop_optimization.optimization.ean.models import (
    EanActivationReference,
    EanCabinStartKind,
    EanDemandGroup,
    EanRideCandidate,
    EanTimeReference,
    HeadwayCandidate,
    HeadwayCheckpointDefinition,
    SkipStopTiming,
    StationEanConfig,
    StationWaitingMode,
    SwitchVisitDefinition,
)
from ropeway_skip_stop_optimization.optimization.ean.headway_semantics import (
    PLATFORM_EXIT_WAIT_OCCUPANCY_SEMANTICS,
    POINT_HEADWAY_SEMANTICS,
    uses_platform_exit_wait_occupancy,
)
from ropeway_skip_stop_optimization.optimization.ean.formulation_config import (
    HORIZON_ACTIVATION_EPSILON_SECONDS,
    EanHorizonFormulation,
)
from ropeway_skip_stop_optimization.optimization.ean.horizon import (
    add_visit_horizon_activation,
    visit_is_active_in_solution,
)
from ropeway_skip_stop_optimization.optimization.ean.optimization_config import EanOptimizationConfig
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
from ropeway_skip_stop_optimization.optimization.ean.validation import (
    validate_ean_movement_plan_against_artifact,
)
from ropeway_skip_stop_optimization.optimization.ean.optimizers.solver_policy import (
    GurobiSolverPolicy,
    apply_gurobi_solver_policy,
)
from ropeway_skip_stop_optimization.optimization.ean.time_bounds import (
    EanModelTimeBounds,
    build_ean_model_time_bounds,
)
from ropeway_skip_stop_optimization.optimization.solver_progress import GurobiMipProgressSample


LOGGER = logging.getLogger(__name__)


class EanPassengerServiceObjective(StrEnum):
    """Passenger objective for EAN service optimization."""

    WAITING_TIME = "waiting_time"
    JOURNEY_TIME = "journey_time"


@dataclass(frozen=True)
class EanPassengerServiceCheckpointConfig:
    """Filesystem checkpoints for EAN passenger-service MIP starts.

    This is a solver warm-start optimization, not a persisted branch-and-bound
    tree. Gurobi writes incumbent solution files while solving, and a later run
    can load one as a MIP start before optimization begins.
    """

    read_solution_path: Path | None = None
    solution_file_prefix: Path | None = None
    final_solution_path: Path | None = None

    def validate(self) -> None:
        if self.read_solution_path is not None and not self.read_solution_path.exists():
            raise ValueError(f"checkpoint read solution does not exist: {self.read_solution_path}")
        if self.solution_file_prefix is not None and not self.solution_file_prefix.name:
            raise ValueError("checkpoint solution file prefix must include a filename prefix")
        if self.final_solution_path is not None and self.final_solution_path.suffix.lower() not in {".mst", ".sol"}:
            raise ValueError("checkpoint final solution path must end in .mst or .sol")


@dataclass(frozen=True)
class EanPassengerServiceConfig:
    """Config for continuous EAN passenger-service optimization."""

    objective: EanPassengerServiceObjective = EanPassengerServiceObjective.WAITING_TIME
    solver_policy: GurobiSolverPolicy = field(default_factory=GurobiSolverPolicy)
    log_to_console: bool = False
    use_all_stop_mip_start: bool = True
    checkpoint: EanPassengerServiceCheckpointConfig | None = None
    optimization_config: EanOptimizationConfig = field(default_factory=EanOptimizationConfig)
    progress_recorder: Any | None = None
    progress_sample_interval_seconds: float = 5.0

    def validate(self) -> None:
        self.solver_policy.validate()
        if self.checkpoint is not None:
            self.checkpoint.validate()
        if self.progress_sample_interval_seconds <= 0:
            raise ValueError("progress_sample_interval_seconds must be positive")


@dataclass(frozen=True)
class EanPassengerServiceMetadata:
    status: str
    solver_status: str
    objective_kind: EanPassengerServiceObjective
    objective_value_seconds: float | None
    objective_passenger_hours: float | None
    best_bound: float | None
    mip_gap: float | None
    runtime_seconds: float | None
    node_count: float | None
    solution_count: int
    mip_gap_target: float | None
    time_limit_seconds: float | None
    demand_group_count: int
    ride_candidate_count: int
    slot_variable_count: int
    served_passenger_count: int
    unserved_passenger_count: int
    variable_count: int
    constraint_count: int
    skipped_visit_count: int
    visible_skipped_visit_count: int
    checkpoint_read_path: str | None
    checkpoint_solution_file_prefix: str | None
    checkpoint_final_solution_path: str | None
    optimization_config: EanOptimizationConfig
    progress_samples: tuple[GurobiMipProgressSample, ...] = ()


@dataclass(frozen=True)
class EanPassengerServiceResult:
    movement_plan: EanMovementPlan | None
    passenger_plan: EanPassengerServicePlan | None
    metadata: EanPassengerServiceMetadata


@dataclass(frozen=True)
class StopSkipBigMBounds:
    service_exit_ub: float
    service_exit_lb: float
    skip_exit_ub: float
    skip_exit_lb: float


@dataclass(frozen=True)
class HeadwayTimeExpressions:
    leader_clear_time: Any
    follower_enter_time: Any
    semantics_label: str


def solve_ean_passenger_service(
    scenario: Scenario,
    artifact: EanBuildArtifact,
    config: EanPassengerServiceConfig | None = None,
    passenger_builder: EanPassengerCandidateBuilder | None = None,
) -> EanPassengerServiceResult:
    """Solve continuous EAN skip/stop movement with passenger waiting objective.

    Passenger demand is kept grouped at the input/output boundary. Internally,
    each feasible ride candidate gets up to `cabin_capacity` binary passenger
    slots. This keeps the model linear while avoiding one binary variable per
    passenger for each ride candidate.
    """

    try:
        import gurobipy as gp
        from gurobipy import GRB
    except ImportError as error:
        raise RuntimeError("gurobipy is required for EAN passenger optimization") from error

    artifact.validate()
    config = config or EanPassengerServiceConfig()
    config.validate()
    _require_supported_waiting_modes(artifact)

    passenger_build = (
        passenger_builder
        or EanPassengerCandidateBuilder(optimization_config=config.optimization_config)
    ).build(scenario, artifact)
    group_by_id = {group.id: group for group in passenger_build.demand_groups}
    timing_by_switch_id = {timing.switch_id: timing for timing in artifact.timings}
    station_config_by_id = {station_config.station_id: station_config for station_config in artifact.config.station_configs}
    visits_by_key = _visits_by_key(artifact.switch_visits)
    visits_by_cabin_id = _visits_by_cabin_id(artifact.switch_visits)
    starts_by_cabin_id = {start.cabin_id: start for start in artifact.cabin_starts}
    checkpoint_by_id = {checkpoint.id: checkpoint for checkpoint in artifact.headway_checkpoints}
    candidate_by_id = {candidate.id: candidate for candidate in artifact.headway_candidates}
    model_time_bounds = build_ean_model_time_bounds(
        artifact,
        config.optimization_config.formulation.time_bounds,
    )
    time_upper_bound = model_time_bounds.global_upper
    big_m = time_upper_bound + _max_headway_seconds(artifact) + 1.0

    model = gp.Model("ean_passenger_service")
    model.Params.OutputFlag = 1 if config.log_to_console else 0
    apply_gurobi_solver_policy(model, config.solver_policy)

    switch_time: dict[tuple[int, int], Any] = {}
    exit_switch_time: dict[tuple[int, int], Any] = {}
    wait_time: dict[tuple[int, int], Any] = {}
    stop: dict[tuple[int, int], Any] = {}

    for key, visit in visits_by_key.items():
        bounds = model_time_bounds.by_visit[key]
        switch_time[key] = model.addVar(
            lb=bounds.switch_lower,
            ub=bounds.switch_upper,
            vtype=GRB.CONTINUOUS,
            name=f"t_{key[0]}_{key[1]}",
        )
        exit_switch_time[key] = model.addVar(
            lb=bounds.exit_lower,
            ub=bounds.exit_upper,
            vtype=GRB.CONTINUOUS,
            name=f"x_{key[0]}_{key[1]}",
        )
        wait_time[key] = model.addVar(
            lb=0.0,
            ub=bounds.wait_upper,
            vtype=GRB.CONTINUOUS,
            name=f"w_{key[0]}_{key[1]}",
        )
        stop[key] = model.addVar(vtype=GRB.BINARY, name=f"stop_{key[0]}_{key[1]}")

    slot: dict[tuple[str, int], Any] = {}
    slot_board_time: dict[tuple[str, int], Any] = {}
    slot_alight_time: dict[tuple[str, int], Any] | None = (
        {} if config.objective is EanPassengerServiceObjective.JOURNEY_TIME else None
    )
    for ride_candidate in passenger_build.ride_candidates:
        group = group_by_id[ride_candidate.demand_group_id]
        slot_count = min(group.count, artifact.config.cabin_capacity)
        for slot_index in range(slot_count):
            key = (ride_candidate.id, slot_index)
            slot[key] = model.addVar(vtype=GRB.BINARY, name=f"slot_{_var_id(ride_candidate.id)}_{slot_index}")
            slot_board_time[key] = model.addVar(
                lb=0.0,
                ub=time_upper_bound,
                vtype=GRB.CONTINUOUS,
                name=f"slot_board_time_{_var_id(ride_candidate.id)}_{slot_index}",
            )
            if slot_alight_time is not None:
                slot_alight_time[key] = model.addVar(
                    lb=0.0,
                    ub=time_upper_bound,
                    vtype=GRB.CONTINUOUS,
                    name=f"slot_alight_time_{_var_id(ride_candidate.id)}_{slot_index}",
                )

    unserved: dict[str, Any] = {
        group.id: model.addVar(lb=0.0, ub=group.count, vtype=GRB.INTEGER, name=f"unserved_{_var_id(group.id)}")
        for group in passenger_build.demand_groups
    }

    model.update()

    visit_active = add_visit_horizon_activation(
        model=model,
        binary_vtype=GRB.BINARY,
        artifact=artifact,
        formulation=config.optimization_config.formulation.horizon,
        switch_time=switch_time,
        visits_by_cabin_id=visits_by_cabin_id,
        selected_time_bounds=model_time_bounds,
        big_m=big_m,
    )
    for key, visit in visits_by_key.items():
        timing = timing_by_switch_id[visit.switch_id]
        if timing.skip_allowed:
            model.addConstr(stop[key] <= visit_active[key], name=f"stop_only_active_{key[0]}_{key[1]}")
        else:
            model.addConstr(stop[key] == visit_active[key], name=f"force_stop_if_active_{key[0]}_{key[1]}")

    _add_start_constraints(model, switch_time, starts_by_cabin_id, visits_by_cabin_id)
    _add_timing_constraints(
        model,
        switch_time,
        exit_switch_time,
        wait_time,
        stop,
        visits_by_key,
        timing_by_switch_id,
        station_config_by_id,
        model_time_bounds,
        big_m,
        config.optimization_config.enable_tight_big_m_bounds,
        visit_active,
    )
    _add_chain_constraints(
        model,
        switch_time,
        exit_switch_time,
        visits_by_cabin_id,
        timing_by_switch_id,
        visit_active,
        big_m,
    )
    _add_headway_constraints(
        model=model,
        switch_time=switch_time,
        exit_switch_time=exit_switch_time,
        wait_time=wait_time,
        stop=stop,
        artifact=artifact,
        checkpoint_by_id=checkpoint_by_id,
        candidate_by_id=candidate_by_id,
        visits_by_key=visits_by_key,
        timing_by_switch_id=timing_by_switch_id,
        big_m=big_m,
        visit_active=visit_active,
        horizon_formulation=config.optimization_config.formulation.horizon,
    )
    _add_passenger_constraints(
        model=model,
        passenger_build=passenger_build,
        group_by_id=group_by_id,
        switch_time=switch_time,
        wait_time=wait_time,
        stop=stop,
        slot=slot,
        slot_board_time=slot_board_time,
        slot_alight_time=slot_alight_time,
        unserved=unserved,
        visits_by_key=visits_by_key,
        timing_by_switch_id=timing_by_switch_id,
        cabin_capacity=artifact.config.cabin_capacity,
        horizon_seconds=artifact.config.horizon_seconds,
        time_upper_bound=time_upper_bound,
        big_m=big_m,
        enable_slot_time_relaxation_strengthening=(
            config.optimization_config.enable_slot_time_relaxation_strengthening
        ),
        enable_tight_big_m_bounds=config.optimization_config.enable_tight_big_m_bounds,
    )

    if (
        config.use_all_stop_mip_start
        and (config.checkpoint is None or config.checkpoint.read_solution_path is None)
    ):
        _set_all_stop_mip_start(
            artifact=artifact,
            passenger_build=passenger_build,
            group_by_id=group_by_id,
            switch_time=switch_time,
            exit_switch_time=exit_switch_time,
            wait_time=wait_time,
            stop=stop,
            slot=slot,
            slot_board_time=slot_board_time,
            slot_alight_time=slot_alight_time,
            unserved=unserved,
            visit_active=visit_active,
        )

    objective = _passenger_service_objective(
        objective=config.objective,
        passenger_build=passenger_build,
        group_by_id=group_by_id,
        slot=slot,
        slot_board_time=slot_board_time,
        slot_alight_time=slot_alight_time,
        unserved=unserved,
        horizon_seconds=artifact.config.horizon_seconds,
        gp=gp,
    )
    model.setObjective(objective, GRB.MINIMIZE)
    _configure_gurobi_checkpoints(model, config.checkpoint)
    if config.log_to_console:
        model.update()
        LOGGER.info(
            "ean_passenger_service.optimize objective=%s variables=%s constraints=%s "
            "demand_groups=%s ride_candidates=%s slots=%s solver_policy=%s waiting_modes=%s",
            config.objective.value,
            model.NumVars,
            model.NumConstrs,
            len(passenger_build.demand_groups),
            len(passenger_build.ride_candidates),
            len(slot),
            config.solver_policy,
            ",".join(sorted({station_config.waiting_mode.value for station_config in artifact.config.station_configs})),
        )
    progress_sample_start = 0
    if config.progress_recorder is None:
        model.optimize()
    else:
        begin_run = getattr(config.progress_recorder, "begin_run", None)
        if callable(begin_run):
            progress_sample_start = int(begin_run())
        else:
            progress_sample_start = len(config.progress_recorder.samples)
        model.optimize(
            lambda callback_model, where: config.progress_recorder.record_callback(
                callback_model,
                GRB,
                where,
                sample_interval_seconds=config.progress_sample_interval_seconds,
            )
        )
        config.progress_recorder.record_final(model, GRB)
    _write_final_gurobi_checkpoint(model, config.checkpoint)

    solver_diagnostics = _solver_diagnostics(model, GRB, config.solver_policy)
    checkpoint_diagnostics = _checkpoint_diagnostics(config.checkpoint)
    progress_samples = (
        tuple(config.progress_recorder.samples[progress_sample_start:])
        if config.progress_recorder is not None
        else ()
    )
    if model.SolCount <= 0:
        return EanPassengerServiceResult(
            movement_plan=None,
            passenger_plan=None,
            metadata=EanPassengerServiceMetadata(
                **solver_diagnostics,
                objective_kind=config.objective,
                objective_value_seconds=None,
                objective_passenger_hours=None,
                demand_group_count=len(passenger_build.demand_groups),
                ride_candidate_count=len(passenger_build.ride_candidates),
                slot_variable_count=len(slot),
                served_passenger_count=0,
                unserved_passenger_count=0,
                variable_count=model.NumVars,
                constraint_count=model.NumConstrs,
                skipped_visit_count=0,
                visible_skipped_visit_count=0,
                **checkpoint_diagnostics,
                optimization_config=config.optimization_config,
                progress_samples=progress_samples,
            ),
        )

    movement_plan = _extract_movement_plan(
        artifact=artifact,
        visits_by_cabin_id=visits_by_cabin_id,
        timing_by_switch_id=timing_by_switch_id,
        switch_time=switch_time,
        exit_switch_time=exit_switch_time,
        wait_time=wait_time,
        stop=stop,
        visit_active=visit_active,
        horizon_formulation=config.optimization_config.formulation.horizon,
    )
    validation_tolerance_seconds = (
        1e-5
        if config.optimization_config.formulation.horizon
        is EanHorizonFormulation.EXACT_TIME_ACTIVATION
        else 1e-6
    )
    validate_ean_movement_plan_against_artifact(
        artifact,
        movement_plan,
        tolerance_seconds=validation_tolerance_seconds,
    ).raise_for_errors()
    passenger_plan = _extract_passenger_plan(
        artifact=artifact,
        passenger_build=passenger_build,
        group_by_id=group_by_id,
        switch_time=switch_time,
        wait_time=wait_time,
        slot=slot,
        unserved=unserved,
        visits_by_key=visits_by_key,
        timing_by_switch_id=timing_by_switch_id,
    )
    served_passenger_count = sum(ride.count for ride in passenger_plan.served_rides)
    unserved_passenger_count = sum(passenger_plan.unserved_counts_by_demand_group_id.values())
    skipped_visit_count = sum(
        1
        for trajectory in movement_plan.trajectories
        for visit in trajectory.visits
        if visit.decision is EanRouteDecision.SKIP
    )
    visible_skipped_visit_count = sum(
        1
        for trajectory in movement_plan.trajectories
        for visit in trajectory.visits
        if visit.decision is EanRouteDecision.SKIP
        and visit.switch_time_seconds <= artifact.config.horizon_seconds
    )

    return EanPassengerServiceResult(
        movement_plan=movement_plan,
        passenger_plan=passenger_plan,
        metadata=EanPassengerServiceMetadata(
            **solver_diagnostics,
            objective_kind=config.objective,
            objective_value_seconds=float(model.ObjVal),
            objective_passenger_hours=float(model.ObjVal) / 3600.0,
            demand_group_count=len(passenger_build.demand_groups),
            ride_candidate_count=len(passenger_build.ride_candidates),
            slot_variable_count=len(slot),
            served_passenger_count=served_passenger_count,
            unserved_passenger_count=unserved_passenger_count,
            variable_count=model.NumVars,
            constraint_count=model.NumConstrs,
            skipped_visit_count=skipped_visit_count,
            visible_skipped_visit_count=visible_skipped_visit_count,
            **checkpoint_diagnostics,
            optimization_config=config.optimization_config,
            progress_samples=progress_samples,
        ),
    )


def _configure_gurobi_checkpoints(model: Any, checkpoint: EanPassengerServiceCheckpointConfig | None) -> None:
    if checkpoint is None:
        return
    if checkpoint.solution_file_prefix is not None:
        checkpoint.solution_file_prefix.parent.mkdir(parents=True, exist_ok=True)
        model.Params.SolFiles = str(checkpoint.solution_file_prefix)
    if checkpoint.read_solution_path is not None:
        model.update()
        LOGGER.info("Loading EAN passenger-service checkpoint MIP start from %s", checkpoint.read_solution_path)
        model.read(str(checkpoint.read_solution_path))


def _write_final_gurobi_checkpoint(model: Any, checkpoint: EanPassengerServiceCheckpointConfig | None) -> None:
    if checkpoint is None or checkpoint.final_solution_path is None or _safe_int_attr(model, "SolCount") == 0:
        return
    checkpoint.final_solution_path.parent.mkdir(parents=True, exist_ok=True)
    model.write(str(checkpoint.final_solution_path))


def _checkpoint_diagnostics(checkpoint: EanPassengerServiceCheckpointConfig | None) -> dict[str, str | None]:
    if checkpoint is None:
        return {
            "checkpoint_read_path": None,
            "checkpoint_solution_file_prefix": None,
            "checkpoint_final_solution_path": None,
        }
    return {
        "checkpoint_read_path": (
            checkpoint.read_solution_path.as_posix() if checkpoint.read_solution_path is not None else None
        ),
        "checkpoint_solution_file_prefix": (
            checkpoint.solution_file_prefix.as_posix() if checkpoint.solution_file_prefix is not None else None
        ),
        "checkpoint_final_solution_path": (
            checkpoint.final_solution_path.as_posix() if checkpoint.final_solution_path is not None else None
        ),
    }


def _add_start_constraints(
    model: Any,
    switch_time: dict[tuple[int, int], Any],
    starts_by_cabin_id: dict[int, Any],
    visits_by_cabin_id: dict[int, tuple[SwitchVisitDefinition, ...]],
) -> None:
    for cabin_id, visits in visits_by_cabin_id.items():
        start = starts_by_cabin_id[cabin_id]
        first_key = (cabin_id, visits[0].visit_index)
        if start.kind is EanCabinStartKind.FIXED:
            model.addConstr(switch_time[first_key] == start.time_seconds, name=f"fixed_start_{cabin_id}")
        else:
            model.addConstr(switch_time[first_key] >= start.time_seconds, name=f"earliest_start_{cabin_id}")


def _add_timing_constraints(
    model: Any,
    switch_time: dict[tuple[int, int], Any],
    exit_switch_time: dict[tuple[int, int], Any],
    wait_time: dict[tuple[int, int], Any],
    stop: dict[tuple[int, int], Any],
    visits_by_key: dict[tuple[int, int], SwitchVisitDefinition],
    timing_by_switch_id: dict[str, SkipStopTiming],
    station_config_by_id: dict[str, StationEanConfig],
    model_time_bounds: EanModelTimeBounds,
    big_m: float,
    enable_tight_big_m_bounds: bool,
    visit_active: dict[tuple[int, int], Any],
) -> None:
    for key, visit in visits_by_key.items():
        timing = timing_by_switch_id[visit.switch_id]
        station_config = station_config_by_id[timing.station_id]
        bounds = model_time_bounds.by_visit[key]
        active = visit_active[key]
        service_seconds = _service_entry_to_exit_switch_seconds(timing)
        skip_seconds = timing.skip_entry_to_exit_switch_seconds

        if station_config.waiting_mode is StationWaitingMode.NO_WAITING:
            model.addConstr(wait_time[key] == 0.0, name=f"no_wait_{key[0]}_{key[1]}")
        elif station_config.waiting_mode is StationWaitingMode.END_OF_PLATFORM_WAIT:
            model.addConstr(
                wait_time[key] <= bounds.wait_upper * stop[key],
                name=f"wait_only_active_stop_{key[0]}_{key[1]}",
            )
        else:
            raise NotImplementedError(
                f"unsupported EAN passenger-service waiting mode: {station_config.waiting_mode.value}"
            )

        big_m_bounds = _stop_skip_big_m_bounds(
            timing=timing,
            station_config=station_config,
            time_upper_bound=model_time_bounds.global_upper,
            global_big_m=big_m,
            enable_tight_big_m_bounds=enable_tight_big_m_bounds,
        )
        model.addConstr(
            exit_switch_time[key] - switch_time[key] - service_seconds - wait_time[key]
            <= big_m_bounds.service_exit_ub * (1 - stop[key])
            + big_m * (1 - active),
            name=f"service_exit_ub_{key[0]}_{key[1]}",
        )
        model.addConstr(
            exit_switch_time[key] - switch_time[key] - service_seconds - wait_time[key]
            >= -big_m_bounds.service_exit_lb * (1 - stop[key])
            - big_m * (1 - active),
            name=f"service_exit_lb_{key[0]}_{key[1]}",
        )
        model.addConstr(
            exit_switch_time[key] - switch_time[key] - skip_seconds
            <= big_m_bounds.skip_exit_ub * stop[key]
            + big_m * (1 - active),
            name=f"skip_exit_ub_{key[0]}_{key[1]}",
        )
        model.addConstr(
            exit_switch_time[key] - switch_time[key] - skip_seconds
            >= -big_m_bounds.skip_exit_lb * stop[key]
            - big_m * (1 - active),
            name=f"skip_exit_lb_{key[0]}_{key[1]}",
        )


def _stop_skip_big_m_bounds(
    timing: SkipStopTiming,
    station_config: StationEanConfig,
    time_upper_bound: float,
    global_big_m: float,
    enable_tight_big_m_bounds: bool,
) -> StopSkipBigMBounds:
    """Return Big-M bounds for stop/skip timing implications.

    The tight bounds are derived from the opposite active binary branch. For
    example, service timing constraints are inactive only when skip timing and
    zero waiting are active. This preserves all integer-feasible solutions while
    reducing slack in the LP relaxation.
    """

    if not enable_tight_big_m_bounds:
        return StopSkipBigMBounds(
            service_exit_ub=global_big_m,
            service_exit_lb=global_big_m,
            skip_exit_ub=global_big_m,
            skip_exit_lb=global_big_m,
        )

    if station_config.waiting_mode is StationWaitingMode.NO_WAITING:
        wait_upper_bound = 0.0
    elif station_config.waiting_mode is StationWaitingMode.END_OF_PLATFORM_WAIT:
        wait_upper_bound = time_upper_bound
    else:
        raise NotImplementedError(
            f"unsupported EAN passenger-service waiting mode: {station_config.waiting_mode.value}"
        )

    service_seconds = _service_entry_to_exit_switch_seconds(timing)
    skip_seconds = timing.skip_entry_to_exit_switch_seconds

    return StopSkipBigMBounds(
        service_exit_ub=max(0.0, skip_seconds - service_seconds),
        service_exit_lb=max(0.0, service_seconds - skip_seconds),
        skip_exit_ub=max(
            0.0,
            min(
                service_seconds + wait_upper_bound - skip_seconds,
                time_upper_bound - skip_seconds,
            ),
        ),
        skip_exit_lb=max(0.0, skip_seconds - service_seconds),
    )


def _add_chain_constraints(
    model: Any,
    switch_time: dict[tuple[int, int], Any],
    exit_switch_time: dict[tuple[int, int], Any],
    visits_by_cabin_id: dict[int, tuple[SwitchVisitDefinition, ...]],
    timing_by_switch_id: dict[str, SkipStopTiming],
    visit_active: dict[tuple[int, int], Any],
    big_m: float,
) -> None:
    for cabin_id, visits in visits_by_cabin_id.items():
        for previous, current in zip(visits, visits[1:]):
            previous_key = (cabin_id, previous.visit_index)
            current_key = (cabin_id, current.visit_index)
            timing = timing_by_switch_id[previous.switch_id]
            difference = (
                switch_time[current_key]
                - exit_switch_time[previous_key]
                - timing.rope_to_next_switch_seconds
            )
            model.addConstr(
                difference <= big_m * (1 - visit_active[previous_key]),
                name=f"chain_ub_{cabin_id}_{previous.visit_index}_{current.visit_index}",
            )
            model.addConstr(
                difference >= -big_m * (1 - visit_active[previous_key]),
                name=f"chain_lb_{cabin_id}_{previous.visit_index}_{current.visit_index}",
            )


def _add_headway_constraints(
    model: Any,
    switch_time: dict[tuple[int, int], Any],
    exit_switch_time: dict[tuple[int, int], Any],
    wait_time: dict[tuple[int, int], Any],
    stop: dict[tuple[int, int], Any],
    artifact: EanBuildArtifact,
    checkpoint_by_id: dict[str, HeadwayCheckpointDefinition],
    candidate_by_id: dict[str, HeadwayCandidate],
    visits_by_key: dict[tuple[int, int], SwitchVisitDefinition],
    timing_by_switch_id: dict[str, SkipStopTiming],
    big_m: float,
    visit_active: dict[tuple[int, int], Any],
    horizon_formulation: EanHorizonFormulation,
) -> None:
    station_config_by_id = {
        station_config.station_id: station_config
        for station_config in artifact.config.station_configs
    }
    candidate_times_by_id: dict[str, HeadwayTimeExpressions] = {}
    candidate_inactive_by_id: dict[str, Any] = {}
    candidate_within_horizon: dict[str, Any] = {}
    for candidate in artifact.headway_candidates:
        checkpoint = checkpoint_by_id[candidate.checkpoint_id]
        station_config = station_config_by_id.get(checkpoint.station_id)
        times = _headway_time_expressions(
            candidate=candidate,
            checkpoint=checkpoint,
            station_config=station_config,
            switch_time=switch_time,
            exit_switch_time=exit_switch_time,
            wait_time=wait_time,
            visits_by_key=visits_by_key,
            timing_by_switch_id=timing_by_switch_id,
        )
        path_inactive = _candidate_inactive_expr(
            candidate,
            checkpoint,
            stop,
            visit_active,
        )
        candidate_times_by_id[candidate.id] = times
        candidate_inactive_by_id[candidate.id] = path_inactive
        if horizon_formulation is EanHorizonFormulation.EXACT_TIME_ACTIVATION:
            within = model.addVar(vtype="B", name=f"checkpoint_within_horizon_{candidate.id}")
            candidate_within_horizon[candidate.id] = within
            model.addConstr(
                within <= 1 - path_inactive,
                name=f"checkpoint_within_requires_active_path_{candidate.id}",
            )
            model.addConstr(
                times.follower_enter_time
                <= artifact.config.operational_end_seconds + big_m * (1 - within),
                name=f"checkpoint_before_horizon_if_active_{candidate.id}",
            )
            model.addConstr(
                times.follower_enter_time
                >= artifact.config.operational_end_seconds
                + HORIZON_ACTIVATION_EPSILON_SECONDS
                - big_m * (within + path_inactive),
                name=f"checkpoint_after_horizon_if_inactive_{candidate.id}",
            )

    for pair in artifact.headway_pairs:
        first_candidate = candidate_by_id[pair.first_candidate_id]
        second_candidate = candidate_by_id[pair.second_candidate_id]
        first_times = candidate_times_by_id[first_candidate.id]
        second_times = candidate_times_by_id[second_candidate.id]
        semantics_label = first_times.semantics_label
        first_inactive = candidate_inactive_by_id[first_candidate.id]
        second_inactive = candidate_inactive_by_id[second_candidate.id]
        if horizon_formulation is EanHorizonFormulation.EXACT_TIME_ACTIVATION:
            first_inactive += 1 - candidate_within_horizon[first_candidate.id]
            second_inactive += 1 - candidate_within_horizon[second_candidate.id]
        order = model.addVar(vtype="B", name=f"order_{pair.id}")

        model.addConstr(
            first_times.leader_clear_time + pair.headway_seconds
            <= second_times.follower_enter_time + big_m * (1 - order + first_inactive + second_inactive),
            name=f"headway_forward_{pair.id}_{semantics_label}",
        )
        model.addConstr(
            second_times.leader_clear_time + pair.headway_seconds
            <= first_times.follower_enter_time + big_m * (order + first_inactive + second_inactive),
            name=f"headway_reverse_{pair.id}_{semantics_label}",
        )


def _add_passenger_constraints(
    model: Any,
    passenger_build: EanPassengerCandidateBuildResult,
    group_by_id: dict[str, EanDemandGroup],
    switch_time: dict[tuple[int, int], Any],
    wait_time: dict[tuple[int, int], Any],
    stop: dict[tuple[int, int], Any],
    slot: dict[tuple[str, int], Any],
    slot_board_time: dict[tuple[str, int], Any],
    slot_alight_time: dict[tuple[str, int], Any] | None,
    unserved: dict[str, Any],
    visits_by_key: dict[tuple[int, int], SwitchVisitDefinition],
    timing_by_switch_id: dict[str, SkipStopTiming],
    cabin_capacity: int,
    horizon_seconds: float,
    time_upper_bound: float,
    big_m: float,
    enable_slot_time_relaxation_strengthening: bool,
    enable_tight_big_m_bounds: bool,
) -> None:
    ride_by_group_id: dict[str, list[EanRideCandidate]] = {group.id: [] for group in passenger_build.demand_groups}
    for ride_candidate in passenger_build.ride_candidates:
        ride_by_group_id[ride_candidate.demand_group_id].append(ride_candidate)
        _add_ride_slot_constraints(
            model=model,
            ride_candidate=ride_candidate,
            group=group_by_id[ride_candidate.demand_group_id],
            switch_time=switch_time,
            wait_time=wait_time,
            stop=stop,
            slot=slot,
            slot_board_time=slot_board_time,
            slot_alight_time=slot_alight_time,
            visits_by_key=visits_by_key,
            timing_by_switch_id=timing_by_switch_id,
            horizon_seconds=horizon_seconds,
            time_upper_bound=time_upper_bound,
            big_m=big_m,
            cabin_capacity=cabin_capacity,
            enable_slot_time_relaxation_strengthening=enable_slot_time_relaxation_strengthening,
            enable_tight_big_m_bounds=enable_tight_big_m_bounds,
        )

    for group in passenger_build.demand_groups:
        terms = []
        for ride_candidate in ride_by_group_id[group.id]:
            for slot_index in range(min(group.count, cabin_capacity)):
                terms.append(slot[ride_candidate.id, slot_index])
        model.addConstr(sum(terms) + unserved[group.id] == group.count, name=f"demand_balance_{_var_id(group.id)}")

    visits_by_cabin_id = _visits_by_cabin_id(tuple(visits_by_key.values()))
    ride_candidates_by_cabin_id: dict[int, list[EanRideCandidate]] = {}
    for ride_candidate in passenger_build.ride_candidates:
        ride_candidates_by_cabin_id.setdefault(ride_candidate.cabin_id, []).append(ride_candidate)

    for cabin_id, visits in visits_by_cabin_id.items():
        cabin_ride_candidates = ride_candidates_by_cabin_id.get(cabin_id, [])
        for visit in visits:
            onboard_terms = []
            interval_index = visit.visit_index
            for ride_candidate in cabin_ride_candidates:
                if ride_candidate.board_visit_index <= interval_index < ride_candidate.alight_visit_index:
                    group = group_by_id[ride_candidate.demand_group_id]
                    for slot_index in range(min(group.count, cabin_capacity)):
                        onboard_terms.append(slot[ride_candidate.id, slot_index])
            if onboard_terms:
                model.addConstr(
                    sum(onboard_terms) <= cabin_capacity,
                    name=f"capacity_cabin_{cabin_id}_interval_{interval_index}",
                )


def _add_ride_slot_constraints(
    model: Any,
    ride_candidate: EanRideCandidate,
    group: EanDemandGroup,
    switch_time: dict[tuple[int, int], Any],
    wait_time: dict[tuple[int, int], Any],
    stop: dict[tuple[int, int], Any],
    slot: dict[tuple[str, int], Any],
    slot_board_time: dict[tuple[str, int], Any],
    slot_alight_time: dict[tuple[str, int], Any] | None,
    visits_by_key: dict[tuple[int, int], SwitchVisitDefinition],
    timing_by_switch_id: dict[str, SkipStopTiming],
    horizon_seconds: float,
    time_upper_bound: float,
    big_m: float,
    cabin_capacity: int,
    enable_slot_time_relaxation_strengthening: bool,
    enable_tight_big_m_bounds: bool,
) -> None:
    board_key = (ride_candidate.cabin_id, ride_candidate.board_visit_index)
    alight_key = (ride_candidate.cabin_id, ride_candidate.alight_visit_index)
    board_time = _platform_exit_time_expr(board_key, switch_time, wait_time, visits_by_key, timing_by_switch_id)
    alight_time = _platform_entry_time_expr(alight_key, switch_time, visits_by_key, timing_by_switch_id)
    slot_count = min(group.count, cabin_capacity)
    release_big_m = _slot_release_big_m(
        group=group,
        global_big_m=big_m,
        enable_tight_big_m_bounds=enable_tight_big_m_bounds,
    )

    previous_slot_var = None
    for slot_index in range(slot_count):
        key = (ride_candidate.id, slot_index)
        slot_var = slot[key]
        slot_time = slot_board_time[key]
        model.addConstr(slot_var <= stop[board_key], name=f"slot_board_stop_{_var_id(ride_candidate.id)}_{slot_index}")
        model.addConstr(slot_var <= stop[alight_key], name=f"slot_alight_stop_{_var_id(ride_candidate.id)}_{slot_index}")
        model.addConstr(
            board_time >= group.release_time_seconds - release_big_m * (1 - slot_var),
            name=f"slot_release_{_var_id(ride_candidate.id)}_{slot_index}",
        )
        model.addConstr(
            board_time <= horizon_seconds + big_m * (1 - slot_var),
            name=f"slot_board_horizon_{_var_id(ride_candidate.id)}_{slot_index}",
        )
        model.addConstr(
            alight_time <= horizon_seconds + big_m * (1 - slot_var),
            name=f"slot_alight_horizon_{_var_id(ride_candidate.id)}_{slot_index}",
        )
        model.addConstr(slot_time <= time_upper_bound * slot_var, name=f"slot_time_active_{_var_id(ride_candidate.id)}_{slot_index}")
        model.addConstr(slot_time <= board_time, name=f"slot_time_board_ub_{_var_id(ride_candidate.id)}_{slot_index}")
        model.addConstr(
            slot_time >= board_time - time_upper_bound * (1 - slot_var),
            name=f"slot_time_board_lb_{_var_id(ride_candidate.id)}_{slot_index}",
        )
        if slot_alight_time is not None:
            alight_slot_time = slot_alight_time[key]
            model.addConstr(
                alight_slot_time <= time_upper_bound * slot_var,
                name=f"slot_alight_time_active_{_var_id(ride_candidate.id)}_{slot_index}",
            )
            model.addConstr(
                alight_slot_time <= alight_time,
                name=f"slot_time_alight_ub_{_var_id(ride_candidate.id)}_{slot_index}",
            )
            model.addConstr(
                alight_slot_time >= alight_time - time_upper_bound * (1 - slot_var),
                name=f"slot_time_alight_lb_{_var_id(ride_candidate.id)}_{slot_index}",
            )
        if enable_slot_time_relaxation_strengthening:
            _add_slot_time_relaxation_strengthening_constraints(
                model=model,
                ride_candidate=ride_candidate,
                group=group,
                slot_index=slot_index,
                slot_var=slot_var,
                slot_board_time=slot_time,
                slot_alight_time=slot_alight_time[key] if slot_alight_time is not None else None,
                visits_by_key=visits_by_key,
                timing_by_switch_id=timing_by_switch_id,
            )
        if previous_slot_var is not None:
            model.addConstr(slot_var <= previous_slot_var, name=f"slot_symmetry_{_var_id(ride_candidate.id)}_{slot_index}")
        previous_slot_var = slot_var


def _slot_release_big_m(
    group: EanDemandGroup,
    global_big_m: float,
    enable_tight_big_m_bounds: bool,
) -> float:
    """Return Big-M for the inactive passenger release-time constraint.

    For `slot = 0`, using `M = release_time` relaxes
    `board_time >= release_time - M * (1 - slot)` to `board_time >= 0`.
    That is safe because board-time expressions are built from nonnegative
    switch/wait variables and nonnegative timing constants. Other slot-time
    horizon constraints stay on the conservative global Big-M until we have
    proven expression-specific upper bounds.
    """

    if not enable_tight_big_m_bounds:
        return global_big_m
    return group.release_time_seconds


def _add_slot_time_relaxation_strengthening_constraints(
    model: Any,
    ride_candidate: EanRideCandidate,
    group: EanDemandGroup,
    slot_index: int,
    slot_var: Any,
    slot_board_time: Any,
    slot_alight_time: Any | None,
    visits_by_key: dict[tuple[int, int], SwitchVisitDefinition],
    timing_by_switch_id: dict[str, SkipStopTiming],
) -> None:
    """Add slot-time relaxation strengthening constraints.

    These are valid lower bounds for the existing slot-time linearization:
    active slots cannot board before demand release, and journey-time slots
    cannot alight earlier than the minimum physical trip time. They preserve the
    integer feasible set but make fractional slot assignments less artificially
    cheap in the LP relaxation.
    """

    variable_id = _var_id(ride_candidate.id)
    model.addConstr(
        slot_board_time >= group.release_time_seconds * slot_var,
        name=f"slot_board_release_lb_{variable_id}_{slot_index}",
    )

    if slot_alight_time is None:
        return

    min_trip_time = _min_candidate_trip_time_seconds(
        ride_candidate=ride_candidate,
        visits_by_key=visits_by_key,
        timing_by_switch_id=timing_by_switch_id,
    )
    model.addConstr(
        slot_alight_time >= (group.release_time_seconds + min_trip_time) * slot_var,
        name=f"slot_alight_earliest_lb_{variable_id}_{slot_index}",
    )
    model.addConstr(
        slot_alight_time - slot_board_time >= min_trip_time * slot_var,
        name=f"slot_trip_duration_lb_{variable_id}_{slot_index}",
    )


def _passenger_service_objective(
    objective: EanPassengerServiceObjective,
    passenger_build: EanPassengerCandidateBuildResult,
    group_by_id: dict[str, EanDemandGroup],
    slot: dict[tuple[str, int], Any],
    slot_board_time: dict[tuple[str, int], Any],
    slot_alight_time: dict[tuple[str, int], Any] | None,
    unserved: dict[str, Any],
    horizon_seconds: float,
    gp: Any,
) -> Any:
    if objective is EanPassengerServiceObjective.WAITING_TIME:
        return _served_time_minus_release_objective(
            passenger_build=passenger_build,
            group_by_id=group_by_id,
            slot=slot,
            slot_time=slot_board_time,
            unserved=unserved,
            horizon_seconds=horizon_seconds,
            gp=gp,
        )
    if objective is EanPassengerServiceObjective.JOURNEY_TIME:
        if slot_alight_time is None:
            raise ValueError("slot_alight_time is required for journey-time objective")
        return _served_time_minus_release_objective(
            passenger_build=passenger_build,
            group_by_id=group_by_id,
            slot=slot,
            slot_time=slot_alight_time,
            unserved=unserved,
            horizon_seconds=horizon_seconds,
            gp=gp,
        )
    raise ValueError(f"unsupported EAN passenger service objective: {objective}")


def _set_all_stop_mip_start(
    artifact: EanBuildArtifact,
    passenger_build: EanPassengerCandidateBuildResult,
    group_by_id: dict[str, EanDemandGroup],
    switch_time: dict[tuple[int, int], Any],
    exit_switch_time: dict[tuple[int, int], Any],
    wait_time: dict[tuple[int, int], Any],
    stop: dict[tuple[int, int], Any],
    slot: dict[tuple[str, int], Any],
    slot_board_time: dict[tuple[str, int], Any],
    slot_alight_time: dict[tuple[str, int], Any] | None,
    unserved: dict[str, Any],
    visit_active: dict[tuple[int, int], Any],
) -> None:
    all_stop_plan = EarliestAllStopEanMovementPlanBuilder().build(artifact)
    visit_start_by_key = {
        (visit.cabin_id, visit.visit_index): visit
        for trajectory in all_stop_plan.trajectories
        for visit in trajectory.visits
    }

    for key, variable in switch_time.items():
        visit = visit_start_by_key[key]
        active_start = float(
            visit.switch_time_seconds <= artifact.config.operational_end_seconds
        )
        if not isinstance(visit_active[key], int | float):
            visit_active[key].Start = active_start
            route_active_start = active_start
        else:
            route_active_start = float(visit_active[key])
        variable.Start = visit.switch_time_seconds
        exit_switch_time[key].Start = visit.exit_switch_time_seconds
        wait_time[key].Start = 0.0
        stop[key].Start = route_active_start

    for key, variable in slot.items():
        variable.Start = 0.0
        slot_board_time[key].Start = 0.0
        if slot_alight_time is not None:
            slot_alight_time[key].Start = 0.0
    for variable in unserved.values():
        variable.Start = 0.0

    remaining_by_group_id = {
        group.id: group.count
        for group in passenger_build.demand_groups
    }
    load_by_interval: dict[tuple[int, int], int] = {}
    served_slot_keys: set[tuple[str, int]] = set()

    for ride_candidate in _all_stop_mip_start_candidate_order(
        passenger_build.ride_candidates,
        group_by_id,
        visit_start_by_key,
        artifact.config.horizon_seconds,
    ):
        group = group_by_id[ride_candidate.demand_group_id]
        remaining = remaining_by_group_id[group.id]
        if remaining <= 0:
            continue

        interval_keys = tuple(
            (ride_candidate.cabin_id, interval_index)
            for interval_index in range(ride_candidate.board_visit_index, ride_candidate.alight_visit_index)
        )
        free_capacity = min(
            artifact.config.cabin_capacity - load_by_interval.get(interval_key, 0)
            for interval_key in interval_keys
        )
        if free_capacity <= 0:
            continue

        slot_count = min(group.count, artifact.config.cabin_capacity)
        assign_count = min(remaining, free_capacity, slot_count)
        board_time = _all_stop_platform_exit_time(
            ride_candidate.cabin_id,
            ride_candidate.board_visit_index,
            visit_start_by_key,
        )
        alight_time = _all_stop_platform_entry_time(
            ride_candidate.cabin_id,
            ride_candidate.alight_visit_index,
            visit_start_by_key,
        )
        for slot_index in range(assign_count):
            slot_key = (ride_candidate.id, slot_index)
            slot[slot_key].Start = 1.0
            slot_board_time[slot_key].Start = board_time
            if slot_alight_time is not None:
                slot_alight_time[slot_key].Start = alight_time
            served_slot_keys.add(slot_key)

        for interval_key in interval_keys:
            load_by_interval[interval_key] = load_by_interval.get(interval_key, 0) + assign_count
        remaining_by_group_id[group.id] -= assign_count

    for group_id, remaining in remaining_by_group_id.items():
        unserved[group_id].Start = remaining

    for key, variable in slot.items():
        if key in served_slot_keys:
            continue
        variable.Start = 0.0
        slot_board_time[key].Start = 0.0
        if slot_alight_time is not None:
            slot_alight_time[key].Start = 0.0


def _all_stop_mip_start_candidate_order(
    ride_candidates: tuple[EanRideCandidate, ...],
    group_by_id: dict[str, EanDemandGroup],
    visit_start_by_key: dict[tuple[int, int], EanCabinVisit],
    horizon_seconds: float,
) -> tuple[EanRideCandidate, ...]:
    candidates_with_times: list[tuple[float, float, int, int, str, EanRideCandidate]] = []
    for ride_candidate in ride_candidates:
        group = group_by_id[ride_candidate.demand_group_id]
        board_key = (ride_candidate.cabin_id, ride_candidate.board_visit_index)
        alight_key = (ride_candidate.cabin_id, ride_candidate.alight_visit_index)
        if board_key not in visit_start_by_key or alight_key not in visit_start_by_key:
            continue
        if not _all_stop_visit_is_stop_at_station(board_key, group.origin_station_id, visit_start_by_key):
            continue
        if not _all_stop_visit_is_stop_at_station(alight_key, group.destination_station_id, visit_start_by_key):
            continue
        board_time = _all_stop_platform_exit_time(ride_candidate.cabin_id, ride_candidate.board_visit_index, visit_start_by_key)
        alight_time = _all_stop_platform_entry_time(ride_candidate.cabin_id, ride_candidate.alight_visit_index, visit_start_by_key)
        if board_time < group.release_time_seconds or board_time > horizon_seconds or alight_time > horizon_seconds:
            continue
        candidates_with_times.append(
            (
                group.release_time_seconds,
                board_time,
                ride_candidate.cabin_id,
                ride_candidate.board_visit_index,
                ride_candidate.id,
                ride_candidate,
            )
        )
    return tuple(item[-1] for item in sorted(candidates_with_times))


def _all_stop_visit_is_stop_at_station(
    key: tuple[int, int],
    station_id: str,
    visit_start_by_key: dict[tuple[int, int], EanCabinVisit],
) -> bool:
    visit = visit_start_by_key[key]
    return visit.decision is EanRouteDecision.STOP and visit.station_id == station_id


def _all_stop_platform_entry_time(
    cabin_id: int,
    visit_index: int,
    visit_start_by_key: dict[tuple[int, int], EanCabinVisit],
) -> float:
    time_seconds = visit_start_by_key[cabin_id, visit_index].platform_entry_time_seconds
    if time_seconds is None:
        raise ValueError("all-stop MIP start needs platform entry times")
    return time_seconds


def _all_stop_platform_exit_time(
    cabin_id: int,
    visit_index: int,
    visit_start_by_key: dict[tuple[int, int], EanCabinVisit],
) -> float:
    time_seconds = visit_start_by_key[cabin_id, visit_index].platform_exit_time_seconds
    if time_seconds is None:
        raise ValueError("all-stop MIP start needs platform exit times")
    return time_seconds


def _waiting_time_objective(
    passenger_build: EanPassengerCandidateBuildResult,
    group_by_id: dict[str, EanDemandGroup],
    slot: dict[tuple[str, int], Any],
    slot_board_time: dict[tuple[str, int], Any],
    unserved: dict[str, Any],
    horizon_seconds: float,
    gp: Any,
) -> Any:
    return _served_time_minus_release_objective(
        passenger_build=passenger_build,
        group_by_id=group_by_id,
        slot=slot,
        slot_time=slot_board_time,
        unserved=unserved,
        horizon_seconds=horizon_seconds,
        gp=gp,
    )


def _served_time_minus_release_objective(
    passenger_build: EanPassengerCandidateBuildResult,
    group_by_id: dict[str, EanDemandGroup],
    slot: dict[tuple[str, int], Any],
    slot_time: dict[tuple[str, int], Any],
    unserved: dict[str, Any],
    horizon_seconds: float,
    gp: Any,
) -> Any:
    candidate_by_id = {candidate.id: candidate for candidate in passenger_build.ride_candidates}
    served_terms = []
    for key, slot_var in slot.items():
        ride_candidate = candidate_by_id[key[0]]
        group = group_by_id[ride_candidate.demand_group_id]
        served_terms.append(slot_time[key] - group.release_time_seconds * slot_var)

    unserved_terms = [
        max(0.0, horizon_seconds - group.release_time_seconds) * unserved[group.id]
        for group in passenger_build.demand_groups
    ]
    return gp.quicksum(served_terms + unserved_terms)


def _extract_movement_plan(
    artifact: EanBuildArtifact,
    visits_by_cabin_id: dict[int, tuple[SwitchVisitDefinition, ...]],
    timing_by_switch_id: dict[str, SkipStopTiming],
    switch_time: dict[tuple[int, int], Any],
    exit_switch_time: dict[tuple[int, int], Any],
    wait_time: dict[tuple[int, int], Any],
    stop: dict[tuple[int, int], Any],
    visit_active: dict[tuple[int, int], Any],
    horizon_formulation: EanHorizonFormulation,
) -> EanMovementPlan:
    trajectories: list[EanCabinTrajectory] = []
    for cabin_id in sorted(visits_by_cabin_id):
        cabin_visits: list[EanCabinVisit] = []
        active_visits = tuple(
            visit
            for visit in visits_by_cabin_id[cabin_id]
            if visit_is_active_in_solution(
                visit_active[(visit.cabin_id, visit.visit_index)]
            )
        )
        for active_index, visit in enumerate(active_visits):
            key = (visit.cabin_id, visit.visit_index)
            timing = timing_by_switch_id[visit.switch_id]
            switch_seconds = _value(switch_time[key])
            exit_seconds = _value(exit_switch_time[key])
            if active_index + 1 < len(active_visits):
                next_visit = active_visits[active_index + 1]
                next_seconds = _value(
                    switch_time[(next_visit.cabin_id, next_visit.visit_index)]
                )
            else:
                next_seconds = exit_seconds + timing.rope_to_next_switch_seconds
            is_stop = _value(stop[key]) >= 0.5
            wait_seconds = _value(wait_time[key]) if is_stop else 0.0

            if is_stop:
                platform_entry = switch_seconds + timing.entry_to_platform_entry_seconds
                platform_exit = platform_entry + timing.min_platform_entry_to_platform_exit_seconds + wait_seconds
                decision = EanRouteDecision.STOP
            else:
                platform_entry = None
                platform_exit = None
                decision = EanRouteDecision.SKIP

            cabin_visits.append(
                EanCabinVisit(
                    cabin_id=visit.cabin_id,
                    visit_index=visit.visit_index,
                    switch_id=visit.switch_id,
                    station_id=timing.station_id,
                    decision=decision,
                    switch_time_seconds=switch_seconds,
                    platform_entry_time_seconds=platform_entry,
                    platform_exit_time_seconds=platform_exit,
                    exit_switch_time_seconds=exit_seconds,
                    next_switch_time_seconds=next_seconds,
                    wait_seconds=wait_seconds,
                )
            )
        trajectories.append(EanCabinTrajectory(cabin_id=cabin_id, visits=tuple(cabin_visits)))

    plan = EanMovementPlan(
        scenario_id=artifact.scenario_id,
        horizon_seconds=artifact.config.horizon_seconds,
        model_end_seconds=artifact.config.model_end_seconds,
        trajectories=tuple(trajectories),
        horizon_formulation=horizon_formulation,
    )
    plan.validate()
    return plan


def _extract_passenger_plan(
    artifact: EanBuildArtifact,
    passenger_build: EanPassengerCandidateBuildResult,
    group_by_id: dict[str, EanDemandGroup],
    switch_time: dict[tuple[int, int], Any],
    wait_time: dict[tuple[int, int], Any],
    slot: dict[tuple[str, int], Any],
    unserved: dict[str, Any],
    visits_by_key: dict[tuple[int, int], SwitchVisitDefinition],
    timing_by_switch_id: dict[str, SkipStopTiming],
) -> EanPassengerServicePlan:
    served_rides: list[EanServedRideGroup] = []
    served_count_by_candidate_id: dict[str, int] = {}
    for key, variable in slot.items():
        if _value(variable) >= 0.5:
            served_count_by_candidate_id[key[0]] = served_count_by_candidate_id.get(key[0], 0) + 1

    for ride_candidate in passenger_build.ride_candidates:
        count = served_count_by_candidate_id.get(ride_candidate.id, 0)
        if count == 0:
            continue
        board_key = (ride_candidate.cabin_id, ride_candidate.board_visit_index)
        alight_key = (ride_candidate.cabin_id, ride_candidate.alight_visit_index)
        served_rides.append(
            EanServedRideGroup(
                demand_group_id=ride_candidate.demand_group_id,
                cabin_id=ride_candidate.cabin_id,
                board_visit_index=ride_candidate.board_visit_index,
                alight_visit_index=ride_candidate.alight_visit_index,
                count=count,
                boarding_time_seconds=_expr_value(
                    _platform_exit_time_expr(board_key, switch_time, wait_time, visits_by_key, timing_by_switch_id)
                ),
                alighting_time_seconds=_expr_value(
                    _platform_entry_time_expr(alight_key, switch_time, visits_by_key, timing_by_switch_id)
                ),
            )
        )

    unserved_counts = {
        group_id: int(round(_value(variable)))
        for group_id, variable in unserved.items()
    }
    plan = EanPassengerServicePlan(
        scenario_id=artifact.scenario_id,
        horizon_seconds=artifact.config.horizon_seconds,
        served_rides=tuple(served_rides),
        unserved_counts_by_demand_group_id=unserved_counts,
    )
    plan.validate()
    _validate_passenger_accounting(group_by_id, plan)
    return plan


def _validate_passenger_accounting(
    group_by_id: dict[str, EanDemandGroup],
    plan: EanPassengerServicePlan,
) -> None:
    served_by_group_id: dict[str, int] = {group_id: 0 for group_id in group_by_id}
    for ride in plan.served_rides:
        served_by_group_id[ride.demand_group_id] = served_by_group_id.get(ride.demand_group_id, 0) + ride.count
    for group_id, group in group_by_id.items():
        if served_by_group_id[group_id] + plan.unserved_counts_by_demand_group_id[group_id] != group.count:
            raise ValueError(f"EAN passenger accounting mismatch for demand group {group_id!r}")


def _candidate_time_expr(
    candidate: HeadwayCandidate,
    switch_time: dict[tuple[int, int], Any],
    exit_switch_time: dict[tuple[int, int], Any],
    wait_time: dict[tuple[int, int], Any],
    visits_by_key: dict[tuple[int, int], SwitchVisitDefinition],
    timing_by_switch_id: dict[str, SkipStopTiming],
) -> Any:
    key = (candidate.cabin_id, candidate.visit_index)
    if candidate.time_reference is EanTimeReference.PLATFORM_ENTRY_TIME:
        return _platform_entry_time_expr(key, switch_time, visits_by_key, timing_by_switch_id)
    if candidate.time_reference is EanTimeReference.PLATFORM_EXIT_TIME:
        return _platform_exit_time_expr(key, switch_time, wait_time, visits_by_key, timing_by_switch_id)
    if candidate.time_reference is EanTimeReference.EXIT_SWITCH_TIME:
        return exit_switch_time[key]
    if candidate.time_reference is EanTimeReference.ENTRY_TIME:
        return switch_time[key]
    raise ValueError(f"unsupported candidate time reference: {candidate.time_reference}")


def _headway_time_expressions(
    candidate: HeadwayCandidate,
    checkpoint: HeadwayCheckpointDefinition,
    station_config: StationEanConfig | None,
    switch_time: dict[tuple[int, int], Any],
    exit_switch_time: dict[tuple[int, int], Any],
    wait_time: dict[tuple[int, int], Any],
    visits_by_key: dict[tuple[int, int], SwitchVisitDefinition],
    timing_by_switch_id: dict[str, SkipStopTiming],
) -> HeadwayTimeExpressions:
    if uses_platform_exit_wait_occupancy(checkpoint, station_config):
        key = (candidate.cabin_id, candidate.visit_index)
        return HeadwayTimeExpressions(
            leader_clear_time=_platform_exit_time_expr(
                key,
                switch_time,
                wait_time,
                visits_by_key,
                timing_by_switch_id,
            ),
            follower_enter_time=_platform_exit_wait_entry_time_expr(
                key,
                switch_time,
                visits_by_key,
                timing_by_switch_id,
            ),
            semantics_label=PLATFORM_EXIT_WAIT_OCCUPANCY_SEMANTICS,
        )
    candidate_time = _candidate_time_expr(
        candidate,
        switch_time,
        exit_switch_time,
        wait_time,
        visits_by_key,
        timing_by_switch_id,
    )
    return HeadwayTimeExpressions(
        leader_clear_time=candidate_time,
        follower_enter_time=candidate_time,
        semantics_label=POINT_HEADWAY_SEMANTICS,
    )


def _candidate_inactive_expr(
    candidate: HeadwayCandidate,
    checkpoint: HeadwayCheckpointDefinition,
    stop: dict[tuple[int, int], Any],
    visit_active: dict[tuple[int, int], Any],
) -> Any:
    key = (candidate.cabin_id, candidate.visit_index)
    if candidate.activation_reference is EanActivationReference.SERVE:
        return 1 - stop[key]
    if candidate.activation_reference is EanActivationReference.SKIP:
        return stop[key] + 1 - visit_active[key]
    if candidate.activation_reference is EanActivationReference.ACTIVE:
        if checkpoint.applies_to_serve and checkpoint.applies_to_skip:
            return 1 - visit_active[key]
        if checkpoint.applies_to_serve:
            return 1 - stop[key]
        if checkpoint.applies_to_skip:
            return stop[key] + 1 - visit_active[key]
    raise ValueError(f"unsupported candidate activation reference: {candidate.activation_reference}")


def _platform_entry_time_expr(
    key: tuple[int, int],
    switch_time: dict[tuple[int, int], Any],
    visits_by_key: dict[tuple[int, int], SwitchVisitDefinition],
    timing_by_switch_id: dict[str, SkipStopTiming],
) -> Any:
    timing = timing_by_switch_id[visits_by_key[key].switch_id]
    return switch_time[key] + timing.entry_to_platform_entry_seconds


def _platform_exit_time_expr(
    key: tuple[int, int],
    switch_time: dict[tuple[int, int], Any],
    wait_time: dict[tuple[int, int], Any],
    visits_by_key: dict[tuple[int, int], SwitchVisitDefinition],
    timing_by_switch_id: dict[str, SkipStopTiming],
) -> Any:
    timing = timing_by_switch_id[visits_by_key[key].switch_id]
    return (
        switch_time[key]
        + timing.entry_to_platform_entry_seconds
        + timing.min_platform_entry_to_platform_exit_seconds
        + wait_time[key]
    )


def _platform_exit_wait_entry_time_expr(
    key: tuple[int, int],
    switch_time: dict[tuple[int, int], Any],
    visits_by_key: dict[tuple[int, int], SwitchVisitDefinition],
    timing_by_switch_id: dict[str, SkipStopTiming],
) -> Any:
    timing = timing_by_switch_id[visits_by_key[key].switch_id]
    return (
        switch_time[key]
        + timing.entry_to_platform_entry_seconds
        + timing.min_platform_entry_to_platform_exit_seconds
    )


def _min_candidate_trip_time_seconds(
    ride_candidate: EanRideCandidate,
    visits_by_key: dict[tuple[int, int], SwitchVisitDefinition],
    timing_by_switch_id: dict[str, SkipStopTiming],
) -> float:
    if ride_candidate.alight_visit_index <= ride_candidate.board_visit_index:
        raise ValueError("ride candidate alight visit must be after board visit")

    board_key = (ride_candidate.cabin_id, ride_candidate.board_visit_index)
    alight_key = (ride_candidate.cabin_id, ride_candidate.alight_visit_index)
    if board_key not in visits_by_key:
        raise ValueError(f"ride candidate board visit is not in EAN visits: {board_key!r}")
    if alight_key not in visits_by_key:
        raise ValueError(f"ride candidate alight visit is not in EAN visits: {alight_key!r}")

    board_timing = timing_by_switch_id[visits_by_key[board_key].switch_id]
    alight_timing = timing_by_switch_id[visits_by_key[alight_key].switch_id]
    elapsed = board_timing.platform_exit_to_exit_switch_seconds + board_timing.rope_to_next_switch_seconds

    for visit_index in range(ride_candidate.board_visit_index + 1, ride_candidate.alight_visit_index):
        key = (ride_candidate.cabin_id, visit_index)
        if key not in visits_by_key:
            raise ValueError(f"ride candidate intermediate visit is not in EAN visits: {key!r}")
        timing = timing_by_switch_id[visits_by_key[key].switch_id]
        elapsed += _min_entry_to_next_switch_seconds(timing)

    return elapsed + alight_timing.entry_to_platform_entry_seconds


def _min_entry_to_next_switch_seconds(timing: SkipStopTiming) -> float:
    service_seconds = _service_entry_to_next_switch_seconds(timing)
    if not timing.skip_allowed:
        return service_seconds
    return min(service_seconds, timing.skip_entry_to_exit_switch_seconds + timing.rope_to_next_switch_seconds)


def _visits_by_key(visits: tuple[SwitchVisitDefinition, ...]) -> dict[tuple[int, int], SwitchVisitDefinition]:
    return {(visit.cabin_id, visit.visit_index): visit for visit in visits}


def _visits_by_cabin_id(
    visits: tuple[SwitchVisitDefinition, ...],
) -> dict[int, tuple[SwitchVisitDefinition, ...]]:
    grouped: dict[int, list[SwitchVisitDefinition]] = {}
    for visit in visits:
        grouped.setdefault(visit.cabin_id, []).append(visit)
    return {
        cabin_id: tuple(sorted(cabin_visits, key=lambda visit: visit.visit_index))
        for cabin_id, cabin_visits in grouped.items()
    }


def _time_upper_bound(artifact: EanBuildArtifact) -> float:
    starts_by_cabin_id = {start.cabin_id: start for start in artifact.cabin_starts}
    timings_by_switch_id = {timing.switch_id: timing for timing in artifact.timings}
    visits_by_cabin_id = _visits_by_cabin_id(artifact.switch_visits)
    max_time = artifact.config.model_end_seconds
    for cabin_id, visits in visits_by_cabin_id.items():
        elapsed = starts_by_cabin_id[cabin_id].time_seconds
        for visit in visits:
            timing = timings_by_switch_id[visit.switch_id]
            elapsed += max(
                _service_entry_to_next_switch_seconds(timing),
                timing.skip_entry_to_exit_switch_seconds + timing.rope_to_next_switch_seconds,
            )
        max_time = max(max_time, elapsed)
    return max_time + 10.0


def _service_entry_to_exit_switch_seconds(timing: SkipStopTiming) -> float:
    return (
        timing.entry_to_platform_entry_seconds
        + timing.min_platform_entry_to_platform_exit_seconds
        + timing.platform_exit_to_exit_switch_seconds
    )


def _service_entry_to_next_switch_seconds(timing: SkipStopTiming) -> float:
    return _service_entry_to_exit_switch_seconds(timing) + timing.rope_to_next_switch_seconds


def _max_headway_seconds(artifact: EanBuildArtifact) -> float:
    if not artifact.headway_pairs:
        return 0.0
    return max(pair.headway_seconds for pair in artifact.headway_pairs)


def _require_supported_waiting_modes(artifact: EanBuildArtifact) -> None:
    unsupported_modes = {
        station_config.waiting_mode
        for station_config in artifact.config.station_configs
        if station_config.waiting_mode
        not in {
            StationWaitingMode.NO_WAITING,
            StationWaitingMode.END_OF_PLATFORM_WAIT,
        }
    }
    if unsupported_modes:
        labels = ", ".join(sorted(mode.value for mode in unsupported_modes))
        raise NotImplementedError(
            "EAN passenger service v0 only supports no-waiting and end-of-platform waiting stations, "
            f"got: {labels}"
        )


def _value(variable: Any) -> float:
    value = float(variable.X)
    if math.isclose(value, round(value), abs_tol=1e-8):
        return float(round(value))
    return value


def _expr_value(expression: Any) -> float:
    if hasattr(expression, "getValue"):
        value = float(expression.getValue())
    else:
        value = float(expression.X)
    if math.isclose(value, round(value), abs_tol=1e-8):
        return float(round(value))
    return value


def _status_name(status: int, grb: Any) -> str:
    return _solver_status_name(status, grb).lower()


def _solver_status_name(status: int, grb: Any) -> str:
    names = {
        grb.OPTIMAL: "OPTIMAL",
        grb.INFEASIBLE: "INFEASIBLE",
        grb.INF_OR_UNBD: "INF_OR_UNBD",
        grb.UNBOUNDED: "UNBOUNDED",
        grb.TIME_LIMIT: "TIME_LIMIT",
        grb.INTERRUPTED: "INTERRUPTED",
    }
    return names.get(status, f"STATUS_{status}")


def _solver_diagnostics(model: Any, grb: Any, policy: GurobiSolverPolicy) -> dict[str, Any]:
    """Collect Gurobi solve diagnostics for export metadata.

    These fields are observational only: they do not affect the optimization
    model or incumbent extraction, but they make performance comparisons and
    frontend status reporting possible without parsing solver logs.
    """

    solver_status = _solver_status_name(int(model.Status), grb)
    solution_count = _safe_int_attr(model, "SolCount") or 0
    return {
        "status": solver_status.lower(),
        "solver_status": solver_status,
        "best_bound": _safe_finite_float_attr(model, "ObjBound"),
        "mip_gap": _safe_finite_float_attr(model, "MIPGap") if solution_count > 0 else None,
        "runtime_seconds": _safe_finite_float_attr(model, "Runtime"),
        "node_count": _safe_finite_float_attr(model, "NodeCount"),
        "solution_count": solution_count,
        "mip_gap_target": policy.mip_gap,
        "time_limit_seconds": policy.time_limit_seconds,
    }


def _safe_finite_float_attr(model: Any, name: str) -> float | None:
    try:
        value = float(getattr(model, name))
    except Exception:
        return None
    if not math.isfinite(value):
        return None
    return value


def _safe_int_attr(model: Any, name: str) -> int | None:
    try:
        return int(getattr(model, name))
    except Exception:
        return None


def _var_id(value: str) -> str:
    return value.replace("::", "_").replace(":", "_").replace("-", "_")
