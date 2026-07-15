from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any

from ropeway_skip_stop_optimization.optimization.ean.artifact import EanBuildArtifact
from ropeway_skip_stop_optimization.optimization.ean.formulation_config import (
    HORIZON_ACTIVATION_EPSILON_SECONDS,
    EanHorizonFormulation,
    EanStopSkipTimingFormulation,
)
from ropeway_skip_stop_optimization.optimization.ean.headway_semantics import (
    PLATFORM_EXIT_WAIT_OCCUPANCY_SEMANTICS,
    POINT_HEADWAY_SEMANTICS,
    uses_platform_exit_wait_occupancy,
)
from ropeway_skip_stop_optimization.optimization.ean.horizon import (
    add_visit_horizon_activation,
    visit_is_active_in_solution,
)
from ropeway_skip_stop_optimization.optimization.ean.models import (
    EanActivationReference,
    EanCabinStartKind,
    EanTimeReference,
    HeadwayCandidate,
    HeadwayCheckpointDefinition,
    SkipStopTiming,
    StationEanConfig,
    StationWaitingMode,
    SwitchVisitDefinition,
)
from ropeway_skip_stop_optimization.optimization.ean.optimization_config import (
    EanOptimizationConfig,
)
from ropeway_skip_stop_optimization.optimization.ean.plan import (
    EanCabinTrajectory,
    EanCabinVisit,
    EanMovementPlan,
    EanRouteDecision,
)
from ropeway_skip_stop_optimization.optimization.ean.time_bounds import (
    EanModelTimeBounds,
    build_ean_model_time_bounds,
)
from ropeway_skip_stop_optimization.optimization.ean.timing_formulation import (
    add_affine_stop_skip_timing_constraint,
)


VisitKey = tuple[int, int]


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


@dataclass(frozen=True)
class EanMovementVariables:
    switch_time: dict[VisitKey, Any]
    exit_switch_time: dict[VisitKey, Any]
    wait_time: dict[VisitKey, Any]
    stop: dict[VisitKey, Any]
    visit_active: dict[VisitKey, Any]
    checkpoint_within_horizon: dict[str, Any]
    headway_order: dict[str, Any]

    def all_variables(self) -> tuple[Any, ...]:
        groups = (
            self.switch_time,
            self.exit_switch_time,
            self.wait_time,
            self.stop,
            self.visit_active,
            self.checkpoint_within_horizon,
            self.headway_order,
        )
        return tuple(variable for group in groups for variable in group.values())


@dataclass(frozen=True)
class EanMovementModel:
    model: Any
    artifact: EanBuildArtifact
    optimization_config: EanOptimizationConfig
    variables: EanMovementVariables
    visits_by_key: dict[VisitKey, SwitchVisitDefinition]
    visits_by_cabin_id: dict[int, tuple[SwitchVisitDefinition, ...]]
    timing_by_switch_id: dict[str, SkipStopTiming]
    model_time_bounds: EanModelTimeBounds
    big_m: float
    variable_count: int
    constraint_count: int
    nonzero_count: int

    def extract_plan(self) -> EanMovementPlan:
        return extract_movement_plan(self)

    def fix_to_plan(self, plan: EanMovementPlan) -> None:
        """Fix operational movement decisions to an extracted movement plan.

        Headway-order and checkpoint-activation binaries are not part of the
        public movement plan. Once visit times, route decisions, waiting, and
        visit activation are fixed, those auxiliary decisions are implied and
        can be eliminated by presolve.
        """

        fix_movement_model_to_plan(self, plan)


@dataclass(frozen=True)
class EanMovementModelBuilder:
    """Build the canonical EAN movement, timing, horizon, and headway layer."""

    def build(
        self,
        *,
        model: Any,
        binary_vtype: Any,
        artifact: EanBuildArtifact,
        optimization_config: EanOptimizationConfig,
    ) -> EanMovementModel:
        artifact.validate()
        require_supported_waiting_modes(artifact)

        timing_by_switch_id = {timing.switch_id: timing for timing in artifact.timings}
        station_config_by_id = {
            station_config.station_id: station_config
            for station_config in artifact.config.station_configs
        }
        visits_by_key = visits_by_key_for(artifact.switch_visits)
        visits_by_cabin_id = visits_by_cabin_id_for(artifact.switch_visits)
        starts_by_cabin_id = {start.cabin_id: start for start in artifact.cabin_starts}
        checkpoint_by_id = {
            checkpoint.id: checkpoint for checkpoint in artifact.headway_checkpoints
        }
        candidate_by_id = {
            candidate.id: candidate for candidate in artifact.headway_candidates
        }
        model_time_bounds = build_ean_model_time_bounds(
            artifact,
            optimization_config.formulation.time_bounds,
        )
        big_m = model_time_bounds.global_upper + max_headway_seconds(artifact) + 1.0

        switch_time: dict[VisitKey, Any] = {}
        exit_switch_time: dict[VisitKey, Any] = {}
        wait_time: dict[VisitKey, Any] = {}
        stop: dict[VisitKey, Any] = {}
        for key in visits_by_key:
            bounds = model_time_bounds.by_visit[key]
            switch_time[key] = model.addVar(
                lb=bounds.switch_lower,
                ub=bounds.switch_upper,
                name=f"t_{key[0]}_{key[1]}",
            )
            exit_switch_time[key] = model.addVar(
                lb=bounds.exit_lower,
                ub=bounds.exit_upper,
                name=f"x_{key[0]}_{key[1]}",
            )
            wait_time[key] = model.addVar(
                lb=0.0,
                ub=bounds.wait_upper,
                name=f"w_{key[0]}_{key[1]}",
            )
            stop[key] = model.addVar(
                vtype=binary_vtype,
                name=f"stop_{key[0]}_{key[1]}",
            )
        model.update()

        visit_active = add_visit_horizon_activation(
            model=model,
            binary_vtype=binary_vtype,
            artifact=artifact,
            formulation=optimization_config.formulation.horizon,
            switch_time=switch_time,
            visits_by_cabin_id=visits_by_cabin_id,
            selected_time_bounds=model_time_bounds,
            big_m=big_m,
        )
        for key, visit in visits_by_key.items():
            timing = timing_by_switch_id[visit.switch_id]
            if timing.skip_allowed:
                model.addConstr(
                    stop[key] <= visit_active[key],
                    name=f"stop_only_active_{key[0]}_{key[1]}",
                )
            else:
                model.addConstr(
                    stop[key] == visit_active[key],
                    name=f"force_stop_if_active_{key[0]}_{key[1]}",
                )

        _add_start_constraints(
            model,
            switch_time,
            starts_by_cabin_id,
            visits_by_cabin_id,
        )
        _add_timing_constraints(
            model=model,
            switch_time=switch_time,
            exit_switch_time=exit_switch_time,
            wait_time=wait_time,
            stop=stop,
            visits_by_key=visits_by_key,
            timing_by_switch_id=timing_by_switch_id,
            station_config_by_id=station_config_by_id,
            model_time_bounds=model_time_bounds,
            big_m=big_m,
            enable_tight_big_m_bounds=optimization_config.enable_tight_big_m_bounds,
            visit_active=visit_active,
            formulation=optimization_config.formulation.stop_skip_timing,
        )
        _add_chain_constraints(
            model=model,
            switch_time=switch_time,
            exit_switch_time=exit_switch_time,
            visits_by_cabin_id=visits_by_cabin_id,
            timing_by_switch_id=timing_by_switch_id,
            visit_active=visit_active,
            big_m=big_m,
        )
        checkpoint_within_horizon, headway_order = _add_headway_constraints(
            model=model,
            binary_vtype=binary_vtype,
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
            horizon_formulation=optimization_config.formulation.horizon,
        )
        model.update()
        variables = EanMovementVariables(
            switch_time=switch_time,
            exit_switch_time=exit_switch_time,
            wait_time=wait_time,
            stop=stop,
            visit_active=visit_active,
            checkpoint_within_horizon=checkpoint_within_horizon,
            headway_order=headway_order,
        )
        return EanMovementModel(
            model=model,
            artifact=artifact,
            optimization_config=optimization_config,
            variables=variables,
            visits_by_key=visits_by_key,
            visits_by_cabin_id=visits_by_cabin_id,
            timing_by_switch_id=timing_by_switch_id,
            model_time_bounds=model_time_bounds,
            big_m=big_m,
            variable_count=int(model.NumVars),
            constraint_count=int(model.NumConstrs),
            nonzero_count=int(model.NumNZs),
        )


def _add_start_constraints(
    model: Any,
    switch_time: dict[VisitKey, Any],
    starts_by_cabin_id: dict[int, Any],
    visits_by_cabin_id: dict[int, tuple[SwitchVisitDefinition, ...]],
) -> None:
    for cabin_id, visits in visits_by_cabin_id.items():
        start = starts_by_cabin_id[cabin_id]
        first_key = (cabin_id, visits[0].visit_index)
        if start.kind is EanCabinStartKind.FIXED:
            model.addConstr(
                switch_time[first_key] == start.time_seconds,
                name=f"fixed_start_{cabin_id}",
            )
        else:
            model.addConstr(
                switch_time[first_key] >= start.time_seconds,
                name=f"earliest_start_{cabin_id}",
            )


def _add_timing_constraints(
    *,
    model: Any,
    switch_time: dict[VisitKey, Any],
    exit_switch_time: dict[VisitKey, Any],
    wait_time: dict[VisitKey, Any],
    stop: dict[VisitKey, Any],
    visits_by_key: dict[VisitKey, SwitchVisitDefinition],
    timing_by_switch_id: dict[str, SkipStopTiming],
    station_config_by_id: dict[str, StationEanConfig],
    model_time_bounds: EanModelTimeBounds,
    big_m: float,
    enable_tight_big_m_bounds: bool,
    visit_active: dict[VisitKey, Any],
    formulation: EanStopSkipTimingFormulation,
) -> None:
    for key, visit in visits_by_key.items():
        timing = timing_by_switch_id[visit.switch_id]
        station_config = station_config_by_id[timing.station_id]
        bounds = model_time_bounds.by_visit[key]
        active = visit_active[key]
        service_seconds = service_entry_to_exit_switch_seconds(timing)
        skip_seconds = timing.skip_entry_to_exit_switch_seconds

        if station_config.waiting_mode is StationWaitingMode.NO_WAITING:
            model.addConstr(
                wait_time[key] == 0.0,
                name=f"no_wait_{key[0]}_{key[1]}",
            )
        elif station_config.waiting_mode is StationWaitingMode.END_OF_PLATFORM_WAIT:
            model.addConstr(
                wait_time[key] <= bounds.wait_upper * stop[key],
                name=f"wait_only_active_stop_{key[0]}_{key[1]}",
            )
        else:
            raise NotImplementedError(
                f"unsupported EAN waiting mode: {station_config.waiting_mode.value}"
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

        bounds_for_branch = stop_skip_big_m_bounds(
            timing=timing,
            station_config=station_config,
            time_upper_bound=model_time_bounds.global_upper,
            global_big_m=big_m,
            enable_tight_big_m_bounds=enable_tight_big_m_bounds,
        )
        model.addConstr(
            exit_switch_time[key] - switch_time[key] - service_seconds - wait_time[key]
            <= bounds_for_branch.service_exit_ub * (1 - stop[key])
            + big_m * (1 - active),
            name=f"service_exit_ub_{key[0]}_{key[1]}",
        )
        model.addConstr(
            exit_switch_time[key] - switch_time[key] - service_seconds - wait_time[key]
            >= -bounds_for_branch.service_exit_lb * (1 - stop[key])
            - big_m * (1 - active),
            name=f"service_exit_lb_{key[0]}_{key[1]}",
        )
        model.addConstr(
            exit_switch_time[key] - switch_time[key] - skip_seconds
            <= bounds_for_branch.skip_exit_ub * stop[key] + big_m * (1 - active),
            name=f"skip_exit_ub_{key[0]}_{key[1]}",
        )
        model.addConstr(
            exit_switch_time[key] - switch_time[key] - skip_seconds
            >= -bounds_for_branch.skip_exit_lb * stop[key] - big_m * (1 - active),
            name=f"skip_exit_lb_{key[0]}_{key[1]}",
        )


def stop_skip_big_m_bounds(
    *,
    timing: SkipStopTiming,
    station_config: StationEanConfig,
    time_upper_bound: float,
    global_big_m: float,
    enable_tight_big_m_bounds: bool,
) -> StopSkipBigMBounds:
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
            f"unsupported EAN waiting mode: {station_config.waiting_mode.value}"
        )

    service_seconds = service_entry_to_exit_switch_seconds(timing)
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
    *,
    model: Any,
    switch_time: dict[VisitKey, Any],
    exit_switch_time: dict[VisitKey, Any],
    visits_by_cabin_id: dict[int, tuple[SwitchVisitDefinition, ...]],
    timing_by_switch_id: dict[str, SkipStopTiming],
    visit_active: dict[VisitKey, Any],
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
    *,
    model: Any,
    binary_vtype: Any,
    switch_time: dict[VisitKey, Any],
    exit_switch_time: dict[VisitKey, Any],
    wait_time: dict[VisitKey, Any],
    stop: dict[VisitKey, Any],
    artifact: EanBuildArtifact,
    checkpoint_by_id: dict[str, HeadwayCheckpointDefinition],
    candidate_by_id: dict[str, HeadwayCandidate],
    station_config_by_id: dict[str, StationEanConfig],
    visits_by_key: dict[VisitKey, SwitchVisitDefinition],
    timing_by_switch_id: dict[str, SkipStopTiming],
    big_m: float,
    visit_active: dict[VisitKey, Any],
    horizon_formulation: EanHorizonFormulation,
) -> tuple[dict[str, Any], dict[str, Any]]:
    candidate_times_by_id: dict[str, HeadwayTimeExpressions] = {}
    candidate_inactive_by_id: dict[str, Any] = {}
    candidate_within_horizon: dict[str, Any] = {}
    headway_order: dict[str, Any] = {}
    for candidate in artifact.headway_candidates:
        checkpoint = checkpoint_by_id[candidate.checkpoint_id]
        station_config = station_config_by_id.get(checkpoint.station_id)
        times = headway_time_expressions(
            candidate=candidate,
            checkpoint=checkpoint,
            station_config=station_config,
            switch_time=switch_time,
            exit_switch_time=exit_switch_time,
            wait_time=wait_time,
            visits_by_key=visits_by_key,
            timing_by_switch_id=timing_by_switch_id,
        )
        path_inactive = candidate_inactive_expr(
            candidate,
            checkpoint,
            stop,
            visit_active,
        )
        candidate_times_by_id[candidate.id] = times
        candidate_inactive_by_id[candidate.id] = path_inactive
        if horizon_formulation is EanHorizonFormulation.EXACT_TIME_ACTIVATION:
            within = model.addVar(
                vtype=binary_vtype,
                name=f"checkpoint_within_horizon_{candidate.id}",
            )
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
        first_inactive = candidate_inactive_by_id[first_candidate.id]
        second_inactive = candidate_inactive_by_id[second_candidate.id]
        if horizon_formulation is EanHorizonFormulation.EXACT_TIME_ACTIVATION:
            first_inactive += 1 - candidate_within_horizon[first_candidate.id]
            second_inactive += 1 - candidate_within_horizon[second_candidate.id]
        order = model.addVar(vtype=binary_vtype, name=f"order_{pair.id}")
        headway_order[pair.id] = order
        model.addConstr(
            first_times.leader_clear_time + pair.headway_seconds
            <= second_times.follower_enter_time
            + big_m * (1 - order + first_inactive + second_inactive),
            name=f"headway_forward_{pair.id}_{first_times.semantics_label}",
        )
        model.addConstr(
            second_times.leader_clear_time + pair.headway_seconds
            <= first_times.follower_enter_time
            + big_m * (order + first_inactive + second_inactive),
            name=f"headway_reverse_{pair.id}_{first_times.semantics_label}",
        )
    return candidate_within_horizon, headway_order


def headway_time_expressions(
    *,
    candidate: HeadwayCandidate,
    checkpoint: HeadwayCheckpointDefinition,
    station_config: StationEanConfig | None,
    switch_time: dict[VisitKey, Any],
    exit_switch_time: dict[VisitKey, Any],
    wait_time: dict[VisitKey, Any],
    visits_by_key: dict[VisitKey, SwitchVisitDefinition],
    timing_by_switch_id: dict[str, SkipStopTiming],
) -> HeadwayTimeExpressions:
    if uses_platform_exit_wait_occupancy(checkpoint, station_config):
        key = (candidate.cabin_id, candidate.visit_index)
        return HeadwayTimeExpressions(
            leader_clear_time=platform_exit_time_expr(
                key,
                switch_time,
                wait_time,
                visits_by_key,
                timing_by_switch_id,
            ),
            follower_enter_time=platform_exit_wait_entry_time_expr(
                key,
                switch_time,
                visits_by_key,
                timing_by_switch_id,
            ),
            semantics_label=PLATFORM_EXIT_WAIT_OCCUPANCY_SEMANTICS,
        )
    candidate_time = candidate_time_expr(
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


def candidate_time_expr(
    candidate: HeadwayCandidate,
    switch_time: dict[VisitKey, Any],
    exit_switch_time: dict[VisitKey, Any],
    wait_time: dict[VisitKey, Any],
    visits_by_key: dict[VisitKey, SwitchVisitDefinition],
    timing_by_switch_id: dict[str, SkipStopTiming],
) -> Any:
    key = (candidate.cabin_id, candidate.visit_index)
    if candidate.time_reference is EanTimeReference.PLATFORM_ENTRY_TIME:
        return platform_entry_time_expr(
            key,
            switch_time,
            visits_by_key,
            timing_by_switch_id,
        )
    if candidate.time_reference is EanTimeReference.PLATFORM_EXIT_TIME:
        return platform_exit_time_expr(
            key,
            switch_time,
            wait_time,
            visits_by_key,
            timing_by_switch_id,
        )
    if candidate.time_reference is EanTimeReference.EXIT_SWITCH_TIME:
        return exit_switch_time[key]
    if candidate.time_reference is EanTimeReference.ENTRY_TIME:
        return switch_time[key]
    raise ValueError(f"unsupported candidate time reference: {candidate.time_reference}")


def candidate_inactive_expr(
    candidate: HeadwayCandidate,
    checkpoint: HeadwayCheckpointDefinition,
    stop: dict[VisitKey, Any],
    visit_active: dict[VisitKey, Any],
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


def platform_entry_time_expr(
    key: VisitKey,
    switch_time: dict[VisitKey, Any],
    visits_by_key: dict[VisitKey, SwitchVisitDefinition],
    timing_by_switch_id: dict[str, SkipStopTiming],
) -> Any:
    timing = timing_by_switch_id[visits_by_key[key].switch_id]
    return switch_time[key] + timing.entry_to_platform_entry_seconds


def platform_exit_time_expr(
    key: VisitKey,
    switch_time: dict[VisitKey, Any],
    wait_time: dict[VisitKey, Any],
    visits_by_key: dict[VisitKey, SwitchVisitDefinition],
    timing_by_switch_id: dict[str, SkipStopTiming],
) -> Any:
    return (
        platform_exit_wait_entry_time_expr(
            key,
            switch_time,
            visits_by_key,
            timing_by_switch_id,
        )
        + wait_time[key]
    )


def platform_exit_wait_entry_time_expr(
    key: VisitKey,
    switch_time: dict[VisitKey, Any],
    visits_by_key: dict[VisitKey, SwitchVisitDefinition],
    timing_by_switch_id: dict[str, SkipStopTiming],
) -> Any:
    timing = timing_by_switch_id[visits_by_key[key].switch_id]
    return (
        switch_time[key]
        + timing.entry_to_platform_entry_seconds
        + timing.min_platform_entry_to_platform_exit_seconds
    )


def extract_movement_plan(movement_model: EanMovementModel) -> EanMovementPlan:
    artifact = movement_model.artifact
    variables = movement_model.variables
    trajectories: list[EanCabinTrajectory] = []
    for cabin_id in sorted(movement_model.visits_by_cabin_id):
        cabin_visits: list[EanCabinVisit] = []
        active_visits = tuple(
            visit
            for visit in movement_model.visits_by_cabin_id[cabin_id]
            if visit_is_active_in_solution(
                variables.visit_active[(visit.cabin_id, visit.visit_index)]
            )
        )
        for active_index, visit in enumerate(active_visits):
            key = (visit.cabin_id, visit.visit_index)
            timing = movement_model.timing_by_switch_id[visit.switch_id]
            switch_seconds = variable_value(variables.switch_time[key])
            exit_seconds = variable_value(variables.exit_switch_time[key])
            if active_index + 1 < len(active_visits):
                next_visit = active_visits[active_index + 1]
                next_seconds = variable_value(
                    variables.switch_time[
                        (next_visit.cabin_id, next_visit.visit_index)
                    ]
                )
            else:
                next_seconds = exit_seconds + timing.rope_to_next_switch_seconds
            is_stop = variable_value(variables.stop[key]) >= 0.5
            wait_seconds = variable_value(variables.wait_time[key]) if is_stop else 0.0
            if is_stop:
                platform_entry = (
                    switch_seconds + timing.entry_to_platform_entry_seconds
                )
                platform_exit = (
                    platform_entry
                    + timing.min_platform_entry_to_platform_exit_seconds
                    + wait_seconds
                )
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
        trajectories.append(
            EanCabinTrajectory(cabin_id=cabin_id, visits=tuple(cabin_visits))
        )

    plan = EanMovementPlan(
        scenario_id=artifact.scenario_id,
        horizon_seconds=artifact.config.horizon_seconds,
        model_end_seconds=artifact.config.model_end_seconds,
        trajectories=tuple(trajectories),
        horizon_formulation=movement_model.optimization_config.formulation.horizon,
    )
    plan.validate()
    return plan


def fix_movement_model_to_plan(
    movement_model: EanMovementModel,
    plan: EanMovementPlan,
) -> None:
    plan.validate()
    artifact = movement_model.artifact
    if plan.scenario_id != artifact.scenario_id:
        raise ValueError(
            "fixed EAN movement plan scenario does not match the build "
            f"artifact: {plan.scenario_id!r} != {artifact.scenario_id!r}"
        )
    if plan.horizon_formulation is not (
        movement_model.optimization_config.formulation.horizon
    ):
        raise ValueError(
            "fixed EAN movement plan horizon formulation does not match the "
            "optimization configuration"
        )

    plan_visits = {
        (visit.cabin_id, visit.visit_index): visit
        for trajectory in plan.trajectories
        for visit in trajectory.visits
    }
    unknown_keys = set(plan_visits) - set(movement_model.visits_by_key)
    if unknown_keys:
        raise ValueError(
            "fixed EAN movement plan contains unknown visits: "
            f"{sorted(unknown_keys)}"
        )

    variables = movement_model.variables
    for key, visit_definition in movement_model.visits_by_key.items():
        plan_visit = plan_visits.get(key)
        if plan_visit is None:
            _fix_variable(variables.stop[key], 0.0, label=f"stop[{key}]")
            _fix_variable(
                variables.visit_active[key],
                0.0,
                label=f"visit_active[{key}]",
            )
            continue
        if plan_visit.switch_id != visit_definition.switch_id:
            raise ValueError(
                "fixed EAN movement plan switch does not match artifact for "
                f"visit {key}: {plan_visit.switch_id!r} != "
                f"{visit_definition.switch_id!r}"
            )
        _fix_variable(
            variables.switch_time[key],
            plan_visit.switch_time_seconds,
            label=f"switch_time[{key}]",
        )
        _fix_variable(
            variables.exit_switch_time[key],
            plan_visit.exit_switch_time_seconds,
            label=f"exit_switch_time[{key}]",
        )
        _fix_variable(
            variables.wait_time[key],
            plan_visit.wait_seconds,
            label=f"wait_time[{key}]",
        )
        _fix_variable(
            variables.stop[key],
            1.0 if plan_visit.decision is EanRouteDecision.STOP else 0.0,
            label=f"stop[{key}]",
        )
        _fix_variable(
            variables.visit_active[key],
            1.0,
            label=f"visit_active[{key}]",
        )
    movement_model.model.update()


def _fix_variable(variable: Any, value: float, *, label: str) -> None:
    if hasattr(variable, "LB") and hasattr(variable, "UB"):
        variable.LB = value
        variable.UB = value
        return
    if not math.isclose(float(variable), value, abs_tol=1e-8):
        raise ValueError(
            f"cannot fix constant {label}={float(variable)} to {value}"
        )


def visits_by_key_for(
    visits: tuple[SwitchVisitDefinition, ...],
) -> dict[VisitKey, SwitchVisitDefinition]:
    return {(visit.cabin_id, visit.visit_index): visit for visit in visits}


def visits_by_cabin_id_for(
    visits: tuple[SwitchVisitDefinition, ...],
) -> dict[int, tuple[SwitchVisitDefinition, ...]]:
    grouped: dict[int, list[SwitchVisitDefinition]] = {}
    for visit in visits:
        grouped.setdefault(visit.cabin_id, []).append(visit)
    return {
        cabin_id: tuple(sorted(cabin_visits, key=lambda visit: visit.visit_index))
        for cabin_id, cabin_visits in grouped.items()
    }


def service_entry_to_exit_switch_seconds(timing: SkipStopTiming) -> float:
    return (
        timing.entry_to_platform_entry_seconds
        + timing.min_platform_entry_to_platform_exit_seconds
        + timing.platform_exit_to_exit_switch_seconds
    )


def service_entry_to_next_switch_seconds(timing: SkipStopTiming) -> float:
    return (
        service_entry_to_exit_switch_seconds(timing)
        + timing.rope_to_next_switch_seconds
    )


def max_headway_seconds(artifact: EanBuildArtifact) -> float:
    if not artifact.headway_pairs:
        return 0.0
    return max(pair.headway_seconds for pair in artifact.headway_pairs)


def require_supported_waiting_modes(artifact: EanBuildArtifact) -> None:
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
            "EAN optimization only supports no-waiting and end-of-platform "
            f"waiting stations, got: {labels}"
        )


def variable_value(variable: Any) -> float:
    value = float(variable.X)
    if math.isclose(value, round(value), abs_tol=1e-8):
        return float(round(value))
    return value
