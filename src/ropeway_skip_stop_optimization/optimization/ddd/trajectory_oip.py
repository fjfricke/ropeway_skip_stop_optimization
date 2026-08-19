from __future__ import annotations

from dataclasses import dataclass
import math

from ropeway_skip_stop_optimization.optimization.ddd.models import (
    DddMovementCore,
    DddRouteDecision,
    DddRouteOption,
)
from ropeway_skip_stop_optimization.optimization.ddd.reference import (
    DddReferenceHorizonCoverageError,
    DddReferenceResourceConflictError,
    DddReferenceResourceOccurrence,
    DddReferenceTrajectory,
    DddReferenceVisit,
    find_ddd_reference_conflicts,
)
from ropeway_skip_stop_optimization.optimization.ddd.trajectory_problem import (
    DddOptimizedInitialPlacementDomain,
    DddTrajectoryProblem,
)
from ropeway_skip_stop_optimization.optimization.ean.artifact import EanBuildArtifact
from ropeway_skip_stop_optimization.optimization.ean.fleet import (
    EanFleetPlan,
    EanInitialPlacementState,
    EanInitialPlacementStateKind,
)
from ropeway_skip_stop_optimization.optimization.ean.formulation_config import (
    EanHorizonFormulation,
)
from ropeway_skip_stop_optimization.optimization.ean.models import (
    EanFleetMode,
    HeadwayCheckpointKind,
)
from ropeway_skip_stop_optimization.optimization.ean.plan import (
    EanCabinTrajectory,
    EanCabinVisit,
    EanMovementPlan,
    EanRouteDecision,
)
from ropeway_skip_stop_optimization.optimization.ean.primal_seed import EanPrimalSeed


DDD_OIP_HORIZON_TAIL_EPSILON_SECONDS = 1e-9


def ddd_oip_covers_horizon(
    final_event_time_seconds: float,
    operational_end_seconds: float,
    *,
    tolerance_seconds: float = DDD_OIP_HORIZON_TAIL_EPSILON_SECONDS,
) -> bool:
    return final_event_time_seconds >= operational_end_seconds + tolerance_seconds


@dataclass(frozen=True)
class DddOipTrajectoryStart:
    phase_index: int
    station_start: bool
    first_switch_time_seconds: float
    previous_service: bool | None = None


def build_ddd_oip_reference_trajectory(
    *,
    problem: DddTrajectoryProblem,
    artifact: EanBuildArtifact,
    cabin_id: int,
    start: DddOipTrajectoryStart,
    route_option_ids: tuple[str, ...],
    tolerance_seconds: float = DDD_OIP_HORIZON_TAIL_EPSILON_SECONDS,
) -> DddReferenceTrajectory:
    """Materialize one continuous-offset no-wait OIP trajectory."""

    problem.validate()
    if not isinstance(problem.start_domain, DddOptimizedInitialPlacementDomain):
        raise ValueError("OIP trajectory construction requires an OIP start domain")
    domain = problem.start_domain
    if cabin_id not in domain.cabin_ids:
        raise ValueError("OIP trajectory cabin is outside the exact-K domain")
    if not 0 <= start.phase_index < len(domain.phase_state_ids):
        raise ValueError("OIP trajectory phase is outside the pattern")
    if not math.isfinite(start.first_switch_time_seconds):
        raise ValueError("OIP trajectory start offset must be finite")
    if not route_option_ids:
        raise ValueError("OIP trajectory needs a route sequence")

    core = problem.movement_core
    options_by_id = {option.id: option for option in core.route_options}
    expected_state = domain.phase_state_ids[start.phase_index]
    switch_time = start.first_switch_time_seconds
    visits: list[DddReferenceVisit] = []
    for local_index, option_id in enumerate(route_option_ids):
        option = options_by_id.get(option_id)
        if option is None or option.from_state_id != expected_state:
            raise ValueError("OIP trajectory route sequence is not a valid state path")
        visit_index = start.phase_index + local_index
        next_switch = switch_time + option.duration_seconds
        occurrences = list(
            _continuous_route_occurrences(
                cabin_id=cabin_id,
                visit_index=visit_index,
                switch_time_seconds=switch_time,
                option=option,
                operational_end_seconds=core.operational_end_seconds,
            )
        )
        boundary_resource = artifact.initial_boundary_service_resource(
            option.from_state_id
        )
        if boundary_resource is not None and option.decision is DddRouteDecision.STOP:
            rule = artifact.headway_rule_for_full_resource(boundary_resource)
            occurrences.append(
                DddReferenceResourceOccurrence(
                    resource_id=boundary_resource.id,
                    cabin_id=cabin_id,
                    visit_index=visit_index,
                    leader_clear_time_seconds=(
                        switch_time + option.exit_switch_offset_seconds
                    ),
                    follower_enter_time_seconds=(
                        switch_time + option.exit_switch_offset_seconds
                    ),
                    separation_after_seconds=rule.maximum_seconds,
                    boundary_only=True,
                    quantize_times=False,
                )
            )
        visits.append(
            DddReferenceVisit(
                cabin_id=cabin_id,
                visit_index=visit_index,
                state_id=option.from_state_id,
                route_option_id=option.id,
                decision=option.decision,
                switch_time_seconds=switch_time,
                next_switch_time_seconds=next_switch,
                resource_occurrences=tuple(occurrences),
                quantize_times=False,
            )
        )
        expected_state = option.to_state_id
        switch_time = next_switch
        if ddd_oip_covers_horizon(
            switch_time,
            core.operational_end_seconds,
            tolerance_seconds=tolerance_seconds,
        ):
            break
    if not ddd_oip_covers_horizon(
        switch_time,
        core.operational_end_seconds,
        tolerance_seconds=tolerance_seconds,
    ):
        raise DddReferenceHorizonCoverageError(
            "OIP trajectory route sequence does not cover the operational horizon"
        )
    if len(visits) > domain.maximum_visit_count - start.phase_index:
        raise ValueError("OIP trajectory exceeds the artifact visit domain")

    first_option = options_by_id[route_option_ids[0]]
    initial_state, boundary_occurrences = _build_initial_state_and_boundary(
        core=core,
        artifact=artifact,
        cabin_id=cabin_id,
        phase_index=start.phase_index,
        station_start=start.station_start,
        first_switch_time_seconds=start.first_switch_time_seconds,
        first_option=first_option,
        previous_service=start.previous_service,
        tolerance_seconds=tolerance_seconds,
    )
    result = DddReferenceTrajectory(
        cabin_id=cabin_id,
        visits=tuple(visits),
        initial_state=initial_state,
        boundary_resource_occurrences=boundary_occurrences,
    )
    validate_ddd_oip_reference_trajectory(
        problem, artifact, result, tolerance_seconds=tolerance_seconds
    )
    return result


def validate_ddd_oip_reference_trajectory(
    problem: DddTrajectoryProblem,
    artifact: EanBuildArtifact,
    trajectory: DddReferenceTrajectory,
    *,
    tolerance_seconds: float = DDD_OIP_HORIZON_TAIL_EPSILON_SECONDS,
) -> None:
    problem.validate()
    if not isinstance(problem.start_domain, DddOptimizedInitialPlacementDomain):
        raise ValueError("OIP validation requires an OIP start domain")
    domain = problem.start_domain
    state = trajectory.initial_state
    if state is None or state.cabin_id != trajectory.cabin_id:
        raise ValueError("OIP trajectory needs one matching initial state")
    if trajectory.reservoir_state is not None:
        raise ValueError("OIP trajectory cannot contain reservoir provenance")
    state.validate()
    if trajectory.cabin_id not in domain.cabin_ids or not trajectory.visits:
        raise ValueError("OIP trajectory is outside the exact-K domain")
    if not 0 <= state.visit_index < len(domain.phase_state_ids):
        raise ValueError("OIP initial phase lies outside the circulation pattern")
    if state.visit_index != trajectory.visits[0].visit_index:
        raise ValueError("OIP state and first trajectory visit differ")
    options_by_id = {
        option.id: option for option in problem.movement_core.route_options
    }
    expected_state = domain.phase_state_ids[
        state.visit_index % len(domain.phase_state_ids)
    ]
    expected_time = trajectory.visits[0].switch_time_seconds
    for local_index, visit in enumerate(trajectory.visits):
        if visit.cabin_id != trajectory.cabin_id:
            raise ValueError("OIP trajectory contains a visit for another cabin")
        if visit.visit_index != state.visit_index + local_index:
            raise ValueError("OIP trajectory visit indices must be contiguous")
        if visit.state_id != expected_state:
            raise ValueError("OIP trajectory state chain is inconsistent")
        if not math.isclose(
            visit.switch_time_seconds,
            expected_time,
            rel_tol=0.0,
            abs_tol=tolerance_seconds,
        ):
            raise ValueError("OIP trajectory event-time chain is inconsistent")
        option = options_by_id.get(visit.route_option_id)
        if option is None or option.from_state_id != visit.state_id:
            raise ValueError("OIP trajectory references an invalid route")
        if visit.decision is not option.decision:
            raise ValueError("OIP visit decision does not match its route")
        if abs(visit.wait_seconds) > tolerance_seconds:
            raise ValueError("OIP trajectory does not support waiting")
        expected_occurrences = _continuous_route_occurrences(
            cabin_id=trajectory.cabin_id,
            visit_index=visit.visit_index,
            switch_time_seconds=expected_time,
            option=option,
            operational_end_seconds=problem.movement_core.operational_end_seconds,
        )
        boundary_resource = artifact.initial_boundary_service_resource(
            option.from_state_id
        )
        if boundary_resource is not None and option.decision is DddRouteDecision.STOP:
            rule = artifact.headway_rule_for_full_resource(boundary_resource)
            expected_occurrences = (
                *expected_occurrences,
                DddReferenceResourceOccurrence(
                    resource_id=boundary_resource.id,
                    cabin_id=trajectory.cabin_id,
                    visit_index=visit.visit_index,
                    leader_clear_time_seconds=(
                        expected_time + option.exit_switch_offset_seconds
                    ),
                    follower_enter_time_seconds=(
                        expected_time + option.exit_switch_offset_seconds
                    ),
                    separation_after_seconds=rule.maximum_seconds,
                    boundary_only=True,
                    quantize_times=False,
                ),
            )
        if not _resource_occurrences_match(
            visit.resource_occurrences,
            expected_occurrences,
            tolerance_seconds=tolerance_seconds,
        ):
            raise ValueError("OIP visit resource occurrences are inconsistent")
        expected_next = expected_time + option.duration_seconds
        if not math.isclose(
            visit.next_switch_time_seconds,
            expected_next,
            rel_tol=0.0,
            abs_tol=tolerance_seconds,
        ):
            raise ValueError("OIP trajectory violates exact no-wait propagation")
        expected_state = option.to_state_id
        expected_time = expected_next
    if len(trajectory.visits) > domain.maximum_visit_count - state.visit_index:
        raise ValueError("OIP trajectory exceeds the artifact visit domain")
    first_option = options_by_id[trajectory.visits[0].route_option_id]
    expected_initial_state, expected_boundary_occurrences = (
        _build_initial_state_and_boundary(
            core=problem.movement_core,
            artifact=artifact,
            cabin_id=trajectory.cabin_id,
            phase_index=state.visit_index,
            station_start=(state.kind is not EanInitialPlacementStateKind.ROPE),
            first_switch_time_seconds=trajectory.visits[0].switch_time_seconds,
            first_option=first_option,
            previous_service=state.previous_service,
            tolerance_seconds=tolerance_seconds,
        )
    )
    if not _initial_states_match(
        state,
        expected_initial_state,
        tolerance_seconds=tolerance_seconds,
    ):
        raise ValueError("OIP initial-state provenance is inconsistent")
    if not _resource_occurrences_match(
        trajectory.boundary_resource_occurrences,
        expected_boundary_occurrences,
        tolerance_seconds=tolerance_seconds,
    ):
        raise ValueError("OIP boundary resource occurrences are inconsistent")
    if not ddd_oip_covers_horizon(
        expected_time,
        problem.movement_core.operational_end_seconds,
        tolerance_seconds=tolerance_seconds,
    ):
        raise DddReferenceHorizonCoverageError(
            "OIP trajectory ends before covering the operational horizon"
        )
    conflicts = find_ddd_reference_conflicts(
        trajectory.resource_occurrences,
        _conflict_problem_view(problem.movement_core),
        tolerance_seconds=tolerance_seconds,
    )
    if conflicts:
        raise DddReferenceResourceConflictError(
            f"DDD OIP trajectory has a self-conflict: {conflicts[0]}"
        )


def build_ean_oip_plan_and_fleet(
    *,
    problem: DddTrajectoryProblem,
    artifact: EanBuildArtifact,
    trajectories: tuple[DddReferenceTrajectory, ...],
    tolerance_seconds: float = 1e-9,
) -> tuple[EanMovementPlan, EanFleetPlan]:
    """Reconstruct the EAN movement/fleet certificate from selected OIP columns."""

    if not isinstance(problem.start_domain, DddOptimizedInitialPlacementDomain):
        raise ValueError("OIP EAN reconstruction requires an OIP start domain")
    selected_cabin_ids = tuple(item.cabin_id for item in trajectories)
    if (
        len(selected_cabin_ids) != len(problem.cabin_ids)
        or set(selected_cabin_ids) != set(problem.cabin_ids)
    ):
        raise ValueError("OIP selected columns must cover every exact-K cabin")
    ean_trajectories = []
    states = []
    for trajectory in sorted(trajectories, key=lambda item: item.cabin_id):
        validate_ddd_oip_reference_trajectory(
            problem, artifact, trajectory, tolerance_seconds=tolerance_seconds
        )
        assert trajectory.initial_state is not None
        states.append(trajectory.initial_state)
        ean_trajectories.append(
            build_ean_oip_trajectory(
                problem=problem,
                artifact=artifact,
                trajectory=trajectory,
                tolerance_seconds=tolerance_seconds,
            )
        )
    movement_plan = EanMovementPlan(
        scenario_id=artifact.scenario_id,
        horizon_seconds=artifact.config.horizon_seconds,
        model_end_seconds=artifact.config.model_end_seconds,
        trajectories=tuple(ean_trajectories),
        horizon_formulation=EanHorizonFormulation.EXACT_TIME_ACTIVATION,
        fleet_mode=EanFleetMode.OPTIMIZED_INITIAL_PLACEMENT,
    )
    movement_plan.validate()
    fleet_plan = EanFleetPlan(
        mode=EanFleetMode.OPTIMIZED_INITIAL_PLACEMENT,
        available_fleet_count=len(problem.cabin_ids),
        active_cabin_ids=problem.cabin_ids,
        inactive_cabin_ids=(),
        initial_states=tuple(states),
    )
    fleet_plan.validate()
    return movement_plan, fleet_plan


def build_ean_oip_trajectory(
    *,
    problem: DddTrajectoryProblem,
    artifact: EanBuildArtifact,
    trajectory: DddReferenceTrajectory,
    tolerance_seconds: float = 1e-9,
) -> EanCabinTrajectory:
    validate_ddd_oip_reference_trajectory(
        problem, artifact, trajectory, tolerance_seconds=tolerance_seconds
    )
    options_by_id = {
        option.id: option for option in problem.movement_core.route_options
    }
    visits = []
    for reference_visit in trajectory.visits:
        option = options_by_id[reference_visit.route_option_id]
        stopped = option.decision is DddRouteDecision.STOP
        visits.append(
            EanCabinVisit(
                cabin_id=trajectory.cabin_id,
                visit_index=reference_visit.visit_index,
                switch_id=reference_visit.state_id,
                station_id=option.station_id,
                decision=(EanRouteDecision.STOP if stopped else EanRouteDecision.SKIP),
                switch_time_seconds=reference_visit.switch_time_seconds,
                platform_entry_time_seconds=(
                    reference_visit.switch_time_seconds
                    + option.platform_entry_offset_seconds
                    if option.platform_entry_offset_seconds is not None
                    else None
                ),
                platform_exit_time_seconds=(
                    reference_visit.switch_time_seconds
                    + option.platform_exit_offset_seconds
                    if option.platform_exit_offset_seconds is not None
                    else None
                ),
                exit_switch_time_seconds=(
                    reference_visit.switch_time_seconds
                    + option.exit_switch_offset_seconds
                ),
                next_switch_time_seconds=reference_visit.next_switch_time_seconds,
                wait_seconds=0.0,
            )
        )
    result = EanCabinTrajectory(cabin_id=trajectory.cabin_id, visits=tuple(visits))
    result.validate()
    return result


def ddd_oip_trajectories_from_ean_seed(
    *,
    problem: DddTrajectoryProblem,
    artifact: EanBuildArtifact,
    seed: EanPrimalSeed,
) -> tuple[DddReferenceTrajectory, ...]:
    if seed.fleet_plan is None:
        raise ValueError("OIP seed is missing its fleet plan")
    if set(seed.fleet_plan.active_cabin_ids) != set(problem.cabin_ids):
        raise ValueError("OIP seed does not cover the requested exact K")
    state_by_cabin = {state.cabin_id: state for state in seed.fleet_plan.initial_states}
    options = {
        (option.from_state_id, option.decision): option
        for option in problem.movement_core.route_options
    }
    trajectories = []
    for ean_trajectory in sorted(
        seed.movement_plan.trajectories, key=lambda item: item.cabin_id
    ):
        if ean_trajectory.cabin_id not in problem.cabin_ids:
            continue
        state = state_by_cabin[ean_trajectory.cabin_id]
        route_option_ids = tuple(
            options[
                (
                    visit.switch_id,
                    (
                        DddRouteDecision.STOP
                        if visit.decision is EanRouteDecision.STOP
                        else DddRouteDecision.SKIP
                    ),
                )
            ].id
            for visit in ean_trajectory.visits
        )
        trajectories.append(
            build_ddd_oip_reference_trajectory(
                problem=problem,
                artifact=artifact,
                cabin_id=ean_trajectory.cabin_id,
                start=DddOipTrajectoryStart(
                    phase_index=state.visit_index,
                    station_start=(state.kind is not EanInitialPlacementStateKind.ROPE),
                    first_switch_time_seconds=ean_trajectory.visits[
                        0
                    ].switch_time_seconds,
                    previous_service=state.previous_service,
                ),
                route_option_ids=route_option_ids,
            )
        )
    if {item.cabin_id for item in trajectories} != set(problem.cabin_ids):
        raise ValueError("OIP seed movement plan does not cover exact K")
    return tuple(trajectories)


def _continuous_route_occurrences(
    *,
    cabin_id: int,
    visit_index: int,
    switch_time_seconds: float,
    option: DddRouteOption,
    operational_end_seconds: float,
) -> tuple[DddReferenceResourceOccurrence, ...]:
    return tuple(
        DddReferenceResourceOccurrence(
            resource_id=usage.resource_id,
            cabin_id=cabin_id,
            visit_index=visit_index,
            leader_clear_time_seconds=(
                switch_time_seconds + usage.leader_clear_offset_seconds
            ),
            follower_enter_time_seconds=(
                switch_time_seconds + usage.follower_enter_offset_seconds
            ),
            separation_after_seconds=usage.separation_after_seconds,
            quantize_times=False,
        )
        for usage in option.resource_usages
        if switch_time_seconds + usage.follower_enter_offset_seconds
        <= operational_end_seconds
    )


def _build_initial_state_and_boundary(
    *,
    core: DddMovementCore,
    artifact: EanBuildArtifact,
    cabin_id: int,
    phase_index: int,
    station_start: bool,
    first_switch_time_seconds: float,
    first_option: DddRouteOption,
    previous_service: bool | None,
    tolerance_seconds: float,
) -> tuple[EanInitialPlacementState, tuple[DddReferenceResourceOccurrence, ...]]:
    if station_start:
        exit_time = first_switch_time_seconds + first_option.exit_switch_offset_seconds
        if (
            first_switch_time_seconds > tolerance_seconds
            or exit_time < -tolerance_seconds
        ):
            raise ValueError("station OIP start must straddle t=0")
        if previous_service is not None:
            raise ValueError("station OIP start cannot define previous_service")
        if abs(first_switch_time_seconds) <= tolerance_seconds:
            kind = EanInitialPlacementStateKind.ENTRY_SWITCH
        elif abs(exit_time) <= tolerance_seconds:
            kind = EanInitialPlacementStateKind.EXIT_SWITCH
        elif first_option.decision is DddRouteDecision.STOP:
            kind = EanInitialPlacementStateKind.SERVICE_ROUTE
        else:
            kind = EanInitialPlacementStateKind.SKIP_ROUTE
        duration = max(exit_time - first_switch_time_seconds, tolerance_seconds)
        boundary_point = kind in (
            EanInitialPlacementStateKind.ENTRY_SWITCH,
            EanInitialPlacementStateKind.EXIT_SWITCH,
        )
        return (
            EanInitialPlacementState(
                cabin_id=cabin_id,
                kind=kind,
                switch_id=first_option.from_state_id,
                visit_index=phase_index,
                progress=(
                    0.0
                    if boundary_point
                    else min(1.0, max(0.0, -first_switch_time_seconds / duration))
                ),
                previous_event_time_seconds=(
                    0.0 if boundary_point else first_switch_time_seconds
                ),
                next_event_time_seconds=(0.0 if boundary_point else exit_time),
            ),
            (),
        )

    phase_states = artifact.circulation_state_ids
    previous_switch_id = phase_states[(phase_index - 1) % len(phase_states)]
    timing = next(
        item for item in artifact.timings if item.switch_id == previous_switch_id
    )
    rope_seconds = timing.rope_to_next_switch_seconds
    if (
        not tolerance_seconds
        < first_switch_time_seconds
        < rope_seconds - tolerance_seconds
    ):
        raise ValueError("rope OIP start must lie strictly inside its rope segment")
    previous_time = first_switch_time_seconds - rope_seconds
    exit_checkpoint = next(
        checkpoint
        for checkpoint in artifact.headway_checkpoints
        if checkpoint.switch_id == previous_switch_id
        and checkpoint.kind is HeadwayCheckpointKind.EXIT_SWITCH
    )
    exit_rule = artifact.headway_rule_for_checkpoint(exit_checkpoint)
    previous_decisions = {
        option.decision for option in core.route_options_by_state_id[previous_switch_id]
    }
    exported_previous_service = previous_service
    if previous_service is None:
        needs_behavior = artifact.initial_boundary_service_resource(previous_switch_id)
        if (
            needs_behavior is not None
            or exit_rule.minimum_seconds != exit_rule.maximum_seconds
        ):
            raise ValueError("rope OIP start requires previous_service provenance")
        behavior_service = DddRouteDecision.STOP in previous_decisions and (
            DddRouteDecision.SKIP not in previous_decisions
        )
    else:
        behavior_service = previous_service
    required_previous_decision = (
        DddRouteDecision.STOP if behavior_service else DddRouteDecision.SKIP
    )
    if required_previous_decision not in previous_decisions:
        raise ValueError("rope OIP previous behavior is unavailable at its state")
    behavior = _behavior(behavior_service)
    boundary = [
        DddReferenceResourceOccurrence(
            resource_id=exit_checkpoint.id,
            cabin_id=cabin_id,
            visit_index=phase_index - 1,
            leader_clear_time_seconds=previous_time,
            follower_enter_time_seconds=previous_time,
            separation_after_seconds=exit_rule.required_seconds(behavior, behavior),
            boundary_origin=True,
            quantize_times=False,
        )
    ]
    service_resource = artifact.initial_boundary_service_resource(previous_switch_id)
    if service_resource is not None and behavior_service:
        service_rule = artifact.headway_rule_for_full_resource(service_resource)
        boundary.append(
            DddReferenceResourceOccurrence(
                resource_id=service_resource.id,
                cabin_id=cabin_id,
                visit_index=phase_index - 1,
                leader_clear_time_seconds=previous_time,
                follower_enter_time_seconds=previous_time,
                separation_after_seconds=service_rule.maximum_seconds,
                boundary_only=True,
                boundary_origin=True,
                quantize_times=False,
            )
        )
    return (
        EanInitialPlacementState(
            cabin_id=cabin_id,
            kind=EanInitialPlacementStateKind.ROPE,
            switch_id=previous_switch_id,
            visit_index=phase_index,
            progress=min(1.0, max(0.0, -previous_time / rope_seconds)),
            previous_event_time_seconds=previous_time,
            next_event_time_seconds=first_switch_time_seconds,
            previous_service=exported_previous_service,
        ),
        tuple(boundary),
    )


def _behavior(service: bool):
    from ropeway_skip_stop_optimization.models import HeadwayRouteBehavior

    return HeadwayRouteBehavior.SERVICE if service else HeadwayRouteBehavior.BYPASS


def _initial_states_match(
    actual: EanInitialPlacementState,
    expected: EanInitialPlacementState,
    *,
    tolerance_seconds: float,
) -> bool:
    return (
        actual.cabin_id == expected.cabin_id
        and actual.kind is expected.kind
        and actual.switch_id == expected.switch_id
        and actual.visit_index == expected.visit_index
        and actual.previous_service is expected.previous_service
        and math.isclose(
            actual.progress,
            expected.progress,
            rel_tol=0.0,
            abs_tol=tolerance_seconds,
        )
        and math.isclose(
            actual.previous_event_time_seconds,
            expected.previous_event_time_seconds,
            rel_tol=0.0,
            abs_tol=tolerance_seconds,
        )
        and math.isclose(
            actual.next_event_time_seconds,
            expected.next_event_time_seconds,
            rel_tol=0.0,
            abs_tol=tolerance_seconds,
        )
    )


def _resource_occurrences_match(
    actual: tuple[DddReferenceResourceOccurrence, ...],
    expected: tuple[DddReferenceResourceOccurrence, ...],
    *,
    tolerance_seconds: float,
) -> bool:
    if len(actual) != len(expected):
        return False
    return all(
        first.resource_id == second.resource_id
        and first.cabin_id == second.cabin_id
        and first.visit_index == second.visit_index
        and first.separation_after_seconds == second.separation_after_seconds
        and first.boundary_only == second.boundary_only
        and first.boundary_origin == second.boundary_origin
        and math.isclose(
            first.leader_clear_time_seconds,
            second.leader_clear_time_seconds,
            rel_tol=0.0,
            abs_tol=tolerance_seconds,
        )
        and math.isclose(
            first.follower_enter_time_seconds,
            second.follower_enter_time_seconds,
            rel_tol=0.0,
            abs_tol=tolerance_seconds,
        )
        for first, second in zip(actual, expected, strict=True)
    )


def _conflict_problem_view(core: DddMovementCore):
    """Minimal structural view required by the shared conflict separator."""

    return core
