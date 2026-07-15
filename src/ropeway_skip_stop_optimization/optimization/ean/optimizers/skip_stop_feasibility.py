from __future__ import annotations

import math
import logging
from dataclasses import dataclass, field
from typing import Any

from ropeway_skip_stop_optimization.optimization.ean.artifact import EanBuildArtifact
from ropeway_skip_stop_optimization.optimization.ean.formulation_config import (
    HORIZON_ACTIVATION_EPSILON_SECONDS,
    EanHorizonFormulation,
    EanStopSkipTimingFormulation,
)
from ropeway_skip_stop_optimization.optimization.ean.horizon import (
    add_visit_horizon_activation,
    visit_is_active_in_solution,
)
from ropeway_skip_stop_optimization.optimization.ean.headway_semantics import (
    PLATFORM_EXIT_WAIT_OCCUPANCY_SEMANTICS,
    POINT_HEADWAY_SEMANTICS,
    uses_platform_exit_wait_occupancy,
)
from ropeway_skip_stop_optimization.optimization.ean.models import (
    EanActivationReference,
    EanCabinStartKind,
    EanTimeReference,
    HeadwayCandidate,
    HeadwayCheckpointDefinition,
    StationEanConfig,
    StationWaitingMode,
    SwitchVisitDefinition,
)
from ropeway_skip_stop_optimization.optimization.ean.plan import (
    EanCabinTrajectory,
    EanCabinVisit,
    EanMovementPlan,
    EanRouteDecision,
)
from ropeway_skip_stop_optimization.optimization.ean.optimization_config import (
    EanOptimizationConfig,
)
from ropeway_skip_stop_optimization.optimization.ean.time_bounds import (
    EanModelTimeBounds,
    build_ean_model_time_bounds,
)
from ropeway_skip_stop_optimization.optimization.ean.timing_formulation import (
    add_affine_stop_skip_timing_constraint,
)
from ropeway_skip_stop_optimization.optimization.ean.validation import (
    validate_ean_movement_plan_against_artifact,
)


LOGGER = logging.getLogger(__name__)


@dataclass(frozen=True)
class EanSkipStopFeasibilityConfig:
    """MILP config for the first continuous EAN skip/stop feasibility model."""

    time_limit_seconds: float | None = None
    log_to_console: bool = False
    optimization_config: EanOptimizationConfig = field(default_factory=EanOptimizationConfig)

    def validate(self) -> None:
        if self.time_limit_seconds is not None and self.time_limit_seconds <= 0:
            raise ValueError("time_limit_seconds must be positive when set")


@dataclass(frozen=True)
class EanSkipStopFeasibilityMetadata:
    status: str
    objective_value: float | None
    variable_count: int
    constraint_count: int
    skipped_visit_count: int
    optimization_config: EanOptimizationConfig


@dataclass(frozen=True)
class EanSkipStopFeasibilityResult:
    movement_plan: EanMovementPlan | None
    metadata: EanSkipStopFeasibilityMetadata


@dataclass(frozen=True)
class HeadwayTimeExpressions:
    leader_clear_time: Any
    follower_enter_time: Any
    semantics_label: str


def solve_ean_skip_stop_feasibility(
    artifact: EanBuildArtifact,
    config: EanSkipStopFeasibilityConfig | None = None,
) -> EanSkipStopFeasibilityResult:
    """Solve a continuous EAN feasibility MILP with stop/skip decisions.

    v0 intentionally excludes passengers and waiting. It optimizes no business
    objective; Gurobi only has to find any schedule satisfying timing and
    headway constraints.
    """

    try:
        import gurobipy as gp
        from gurobipy import GRB
    except ImportError as error:
        raise RuntimeError("gurobipy is required for EAN MILP optimization") from error

    artifact.validate()
    config = config or EanSkipStopFeasibilityConfig()
    config.validate()
    _require_supported_waiting_modes(artifact)

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

    model = gp.Model("ean_skip_stop_feasibility")
    model.Params.OutputFlag = 1 if config.log_to_console else 0
    if config.time_limit_seconds is not None:
        model.Params.TimeLimit = config.time_limit_seconds

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
        visit_active,
        config.optimization_config.formulation.stop_skip_timing,
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
        station_config_by_id=station_config_by_id,
        visits_by_key=visits_by_key,
        timing_by_switch_id=timing_by_switch_id,
        big_m=big_m,
        visit_active=visit_active,
        horizon_formulation=config.optimization_config.formulation.horizon,
    )

    model.setObjective(0.0, GRB.MINIMIZE)
    if config.log_to_console:
        model.update()
        LOGGER.info(
            "ean_skip_stop_feasibility.optimize variables=%s constraints=%s visits=%s headway_pairs=%s waiting_modes=%s",
            model.NumVars,
            model.NumConstrs,
            len(artifact.switch_visits),
            len(artifact.headway_pairs),
            ",".join(sorted({station_config.waiting_mode.value for station_config in artifact.config.station_configs})),
        )
    model.optimize()

    status = _status_name(model.Status, GRB)
    if model.SolCount <= 0:
        return EanSkipStopFeasibilityResult(
            movement_plan=None,
            metadata=EanSkipStopFeasibilityMetadata(
                status=status,
                objective_value=None,
                variable_count=model.NumVars,
                constraint_count=model.NumConstrs,
                skipped_visit_count=0,
                optimization_config=config.optimization_config,
            ),
        )

    plan = _extract_plan(
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
        plan,
        tolerance_seconds=validation_tolerance_seconds,
    ).raise_for_errors()
    skipped_visit_count = sum(
        1
        for trajectory in plan.trajectories
        for visit in trajectory.visits
        if visit.decision is EanRouteDecision.SKIP
    )

    return EanSkipStopFeasibilityResult(
        movement_plan=plan,
        metadata=EanSkipStopFeasibilityMetadata(
            status=status,
            objective_value=float(model.ObjVal) if model.SolCount > 0 else None,
            variable_count=model.NumVars,
            constraint_count=model.NumConstrs,
            skipped_visit_count=skipped_visit_count,
            optimization_config=config.optimization_config,
        ),
    )


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
    timing_by_switch_id: dict[str, Any],
    station_config_by_id: dict[str, StationEanConfig],
    model_time_bounds: EanModelTimeBounds,
    big_m: float,
    visit_active: dict[tuple[int, int], Any],
    formulation: EanStopSkipTimingFormulation,
) -> None:
    for key, visit in visits_by_key.items():
        timing = timing_by_switch_id[visit.switch_id]
        station_config = station_config_by_id[timing.station_id]
        bounds = model_time_bounds.by_visit[key]
        active = visit_active[key]
        service_seconds = (
            timing.entry_to_platform_entry_seconds
            + timing.min_platform_entry_to_platform_exit_seconds
            + timing.platform_exit_to_exit_switch_seconds
        )
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
                f"unsupported EAN skip/stop waiting mode: {station_config.waiting_mode.value}"
            )

        if formulation is EanStopSkipTimingFormulation.AFFINE:
            add_affine_stop_skip_timing_constraint(
                model=model,
                switch_time=switch_time[key],
                exit_switch_time=exit_switch_time[key],
                wait_time=wait_time[key],
                stop=stop[key],
                active=active,
                service_seconds=service_seconds,
                skip_seconds=skip_seconds,
                name=f"affine_exit_{key[0]}_{key[1]}",
            )
            continue
        if formulation is not EanStopSkipTimingFormulation.BIG_M:
            raise ValueError(f"unsupported EAN stop/skip timing formulation: {formulation}")

        model.addConstr(
            exit_switch_time[key] - switch_time[key] - service_seconds - wait_time[key]
            <= big_m * (2 - stop[key] - active),
            name=f"service_exit_ub_{key[0]}_{key[1]}",
        )
        model.addConstr(
            exit_switch_time[key] - switch_time[key] - service_seconds - wait_time[key]
            >= -big_m * (2 - stop[key] - active),
            name=f"service_exit_lb_{key[0]}_{key[1]}",
        )
        model.addConstr(
            exit_switch_time[key] - switch_time[key] - skip_seconds
            <= big_m * (stop[key] + 1 - active),
            name=f"skip_exit_ub_{key[0]}_{key[1]}",
        )
        model.addConstr(
            exit_switch_time[key] - switch_time[key] - skip_seconds
            >= -big_m * (stop[key] + 1 - active),
            name=f"skip_exit_lb_{key[0]}_{key[1]}",
        )


def _add_chain_constraints(
    model: Any,
    switch_time: dict[tuple[int, int], Any],
    exit_switch_time: dict[tuple[int, int], Any],
    visits_by_cabin_id: dict[int, tuple[SwitchVisitDefinition, ...]],
    timing_by_switch_id: dict[str, Any],
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
    station_config_by_id: dict[str, StationEanConfig],
    visits_by_key: dict[tuple[int, int], SwitchVisitDefinition],
    timing_by_switch_id: dict[str, Any],
    big_m: float,
    visit_active: dict[tuple[int, int], Any],
    horizon_formulation: EanHorizonFormulation,
) -> None:
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
            checkpoint=checkpoint,
            stop=stop,
            visit_active=visit_active,
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
        first_key = (first_candidate.cabin_id, first_candidate.visit_index)
        second_key = (second_candidate.cabin_id, second_candidate.visit_index)
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
            name=f"headway_forward_{first_key}_{second_key}_{pair.checkpoint_id}_{semantics_label}",
        )
        model.addConstr(
            second_times.leader_clear_time + pair.headway_seconds
            <= first_times.follower_enter_time + big_m * (order + first_inactive + second_inactive),
            name=f"headway_reverse_{first_key}_{second_key}_{pair.checkpoint_id}_{semantics_label}",
        )


def _headway_time_expressions(
    candidate: HeadwayCandidate,
    checkpoint: HeadwayCheckpointDefinition,
    station_config: StationEanConfig | None,
    switch_time: dict[tuple[int, int], Any],
    exit_switch_time: dict[tuple[int, int], Any],
    wait_time: dict[tuple[int, int], Any],
    visits_by_key: dict[tuple[int, int], SwitchVisitDefinition],
    timing_by_switch_id: dict[str, Any],
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


def _candidate_time_expr(
    candidate: HeadwayCandidate,
    switch_time: dict[tuple[int, int], Any],
    exit_switch_time: dict[tuple[int, int], Any],
    wait_time: dict[tuple[int, int], Any],
    visits_by_key: dict[tuple[int, int], SwitchVisitDefinition],
    timing_by_switch_id: dict[str, Any],
) -> Any:
    key = (candidate.cabin_id, candidate.visit_index)
    if candidate.time_reference is EanTimeReference.PLATFORM_ENTRY_TIME:
        timing = timing_by_switch_id[visits_by_key[key].switch_id]
        return switch_time[key] + timing.entry_to_platform_entry_seconds
    if candidate.time_reference is EanTimeReference.PLATFORM_EXIT_TIME:
        return _platform_exit_time_expr(key, switch_time, wait_time, visits_by_key, timing_by_switch_id)
    if candidate.time_reference is EanTimeReference.EXIT_SWITCH_TIME:
        return exit_switch_time[key]
    if candidate.time_reference is EanTimeReference.ENTRY_TIME:
        return switch_time[key]
    raise ValueError(f"unsupported candidate time reference: {candidate.time_reference}")


def _platform_exit_time_expr(
    key: tuple[int, int],
    switch_time: dict[tuple[int, int], Any],
    wait_time: dict[tuple[int, int], Any],
    visits_by_key: dict[tuple[int, int], SwitchVisitDefinition],
    timing_by_switch_id: dict[str, Any],
) -> Any:
    return _platform_exit_wait_entry_time_expr(key, switch_time, visits_by_key, timing_by_switch_id) + wait_time[key]


def _platform_exit_wait_entry_time_expr(
    key: tuple[int, int],
    switch_time: dict[tuple[int, int], Any],
    visits_by_key: dict[tuple[int, int], SwitchVisitDefinition],
    timing_by_switch_id: dict[str, Any],
) -> Any:
    timing = timing_by_switch_id[visits_by_key[key].switch_id]
    return (
        switch_time[key]
        + timing.entry_to_platform_entry_seconds
        + timing.min_platform_entry_to_platform_exit_seconds
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


def _extract_plan(
    artifact: EanBuildArtifact,
    visits_by_cabin_id: dict[int, tuple[SwitchVisitDefinition, ...]],
    timing_by_switch_id: dict[str, Any],
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

            cabin_visit = EanCabinVisit(
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
            cabin_visit.validate()
            cabin_visits.append(cabin_visit)
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


def _service_entry_to_next_switch_seconds(timing: Any) -> float:
    return (
        timing.entry_to_platform_entry_seconds
        + timing.min_platform_entry_to_platform_exit_seconds
        + timing.platform_exit_to_exit_switch_seconds
        + timing.rope_to_next_switch_seconds
    )


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
            "EAN skip/stop feasibility v0 only supports no-waiting and end-of-platform waiting stations, "
            f"got: {labels}"
        )


def _value(variable: Any) -> float:
    value = float(variable.X)
    if math.isclose(value, round(value), abs_tol=1e-8):
        return float(round(value))
    return value


def _status_name(status: int, grb: Any) -> str:
    names = {
        grb.OPTIMAL: "optimal",
        grb.INFEASIBLE: "infeasible",
        grb.INF_OR_UNBD: "infeasible_or_unbounded",
        grb.UNBOUNDED: "unbounded",
        grb.TIME_LIMIT: "time_limit",
        grb.INTERRUPTED: "interrupted",
    }
    return names.get(status, f"status_{status}")
