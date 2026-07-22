from __future__ import annotations

import math
from dataclasses import dataclass, replace

from ropeway_skip_stop_optimization.optimization.ean.artifact import (
    EanBuildArtifact,
)
from ropeway_skip_stop_optimization.optimization.ean.capacity_preparation import (
    canonical_all_stop_fleet_count,
)
from ropeway_skip_stop_optimization.optimization.ean.baselines import (
    EarliestAllStopEanMovementPlanBuilder,
)
from ropeway_skip_stop_optimization.optimization.ean.fleet import (
    EanFleetPlan,
    EanInitialPlacementState,
    EanInitialPlacementStateKind,
)
from ropeway_skip_stop_optimization.optimization.ean.formulation_config import (
    EanHorizonFormulation,
    EanTimeBoundFormulation,
)
from ropeway_skip_stop_optimization.optimization.ean.models import (
    EanFleetMode,
    HeadwayCheckpointKind,
    SkipStopTiming,
    SwitchVisitDefinition,
)
from ropeway_skip_stop_optimization.optimization.ean.plan import (
    EanCabinTrajectory,
    EanCabinVisit,
    EanMovementPlan,
    EanRouteDecision,
)
from ropeway_skip_stop_optimization.optimization.ean.primal_seed import EanPrimalSeed
from ropeway_skip_stop_optimization.optimization.ean.periodic_route import (
    EanPeriodicRouteCapacityBound,
    EanPeriodicRouteCapacityBoundBuilder,
)
from ropeway_skip_stop_optimization.optimization.ean.time_bounds import (
    build_ean_model_time_bounds,
)


_TIME_TOLERANCE_SECONDS = 1e-9


# Compatibility alias for callers that still use the route-specific old name.
EanAllStopMipStartSeed = EanPrimalSeed


@dataclass(frozen=True)
class _ProjectedAllStopPhase:
    state: EanInitialPlacementState
    first_visit_index: int
    first_switch_time: float
    phase_seconds: float


@dataclass(frozen=True)
class EanAllStopMipStartSeedBuilder:
    """Build the shared deterministic all-stop reference for both fleet modes."""

    def build(
        self,
        artifact: EanBuildArtifact,
        horizon_formulation: EanHorizonFormulation,
    ) -> EanAllStopMipStartSeed:
        if artifact.fleet_mode is EanFleetMode.FIXED_STARTS:
            return EanPrimalSeed(
                fleet_plan=None,
                movement_plan=_fixed_start_all_stop_plan(
                    artifact,
                    horizon_formulation,
                ),
            )
        if artifact.fleet_mode is EanFleetMode.OPTIMIZED_INITIAL_PLACEMENT:
            return _build_initial_placement_seed(
                artifact,
                horizon_formulation,
            )
        raise ValueError(f"unsupported EAN fleet mode: {artifact.fleet_mode}")


@dataclass(frozen=True)
class EanPeriodicRouteMipStartSeedBuilder:
    """Project a certified homogeneous periodic route onto OIP boundary states."""

    route_bound_builder: EanPeriodicRouteCapacityBoundBuilder = (
        EanPeriodicRouteCapacityBoundBuilder()
    )

    def build(
        self,
        artifact: EanBuildArtifact,
        horizon_formulation: EanHorizonFormulation,
        route_bound: EanPeriodicRouteCapacityBound | None = None,
    ) -> EanAllStopMipStartSeed:
        if artifact.fleet_mode is not EanFleetMode.OPTIMIZED_INITIAL_PLACEMENT:
            raise ValueError("periodic route seed requires optimized initial placement")
        bound = route_bound or self.route_bound_builder.build(artifact)
        bound.validate_for_artifact(artifact)
        return _build_initial_placement_seed(
            artifact,
            horizon_formulation,
            decisions_by_switch_id=bound.decisions_by_switch_id,
            route_capacity=bound.fleet_lower_bound,
        )


def _fixed_start_all_stop_plan(
    artifact: EanBuildArtifact,
    horizon_formulation: EanHorizonFormulation,
) -> EanMovementPlan:
    plan = EarliestAllStopEanMovementPlanBuilder().build(artifact)
    if horizon_formulation is EanHorizonFormulation.LEGACY:
        return plan

    if horizon_formulation is EanHorizonFormulation.CONSERVATIVE_FREE_SUFFIX:
        bounds = build_ean_model_time_bounds(
            artifact,
            EanTimeBoundFormulation.DERIVED_VISIT_BOUNDS,
        )
        active_keys = {
            key
            for key, visit_bounds in bounds.by_visit.items()
            if visit_bounds.switch_lower <= artifact.config.operational_end_seconds
        }
    elif horizon_formulation is EanHorizonFormulation.EXACT_TIME_ACTIVATION:
        active_keys = {
            (visit.cabin_id, visit.visit_index)
            for trajectory in plan.trajectories
            for visit in trajectory.visits
            if visit.switch_time_seconds <= artifact.config.operational_end_seconds
        }
    else:
        raise ValueError(f"unsupported EAN horizon formulation: {horizon_formulation}")

    return replace(
        plan,
        trajectories=tuple(
            EanCabinTrajectory(
                cabin_id=trajectory.cabin_id,
                visits=tuple(
                    visit
                    for visit in trajectory.visits
                    if (visit.cabin_id, visit.visit_index) in active_keys
                ),
            )
            for trajectory in plan.trajectories
        ),
        horizon_formulation=horizon_formulation,
    )


def _build_initial_placement_seed(
    artifact: EanBuildArtifact,
    horizon_formulation: EanHorizonFormulation,
    *,
    decisions_by_switch_id: dict[str, EanRouteDecision] | None = None,
    route_capacity: int | None = None,
) -> EanAllStopMipStartSeed:
    parameters = artifact.initial_placement_parameters
    if parameters is None:
        raise ValueError("optimized initial placement seed needs fleet parameters")
    if horizon_formulation is not EanHorizonFormulation.EXACT_TIME_ACTIVATION:
        raise ValueError(
            "optimized initial placement seed requires exact-time activation"
        )

    timing_by_switch_id = {timing.switch_id: timing for timing in artifact.timings}
    decisions = decisions_by_switch_id or {
        switch_id: EanRouteDecision.STOP
        for switch_id in artifact.circulation_state_ids
    }
    if set(decisions) != set(artifact.circulation_state_ids):
        raise ValueError("periodic seed decisions must cover the ring exactly")
    route_seconds = {
        switch_id: (
            timing.entry_to_platform_entry_seconds
            + timing.min_platform_entry_to_platform_exit_seconds
            + timing.platform_exit_to_exit_switch_seconds
            if decisions[switch_id] is EanRouteDecision.STOP
            else timing.skip_entry_to_exit_switch_seconds
        )
        for switch_id, timing in timing_by_switch_id.items()
    }
    if any(
        decisions[switch_id] is EanRouteDecision.SKIP
        and not timing_by_switch_id[switch_id].skip_allowed
        for switch_id in artifact.circulation_state_ids
    ):
        raise ValueError("periodic seed selects an unavailable skip route")
    transition_seconds = {
        switch_id: (
            route_seconds[switch_id]
            + timing_by_switch_id[switch_id].rope_to_next_switch_seconds
        )
        for switch_id in artifact.circulation_state_ids
    }
    cycle_seconds = sum(transition_seconds.values())
    canonical_capacity = route_capacity or canonical_all_stop_fleet_count(artifact)
    active_count = min(
        parameters.available_fleet_count,
        canonical_capacity,
    )

    boundaries = [0.0]
    for switch_id in artifact.circulation_state_ids:
        boundaries.append(boundaries[-1] + transition_seconds[switch_id])

    visits_by_cabin_id = _visits_by_cabin_id(artifact)
    phase_spacing = cycle_seconds / active_count
    projected_phases: list[_ProjectedAllStopPhase] = []
    for phase_slot in range(active_count):
        phase_seconds = phase_slot * phase_spacing
        state, first_visit_index, first_switch_time = _project_phase_to_boundary(
            artifact=artifact,
            cabin_id=phase_slot,
            phase_seconds=phase_seconds,
            boundaries=tuple(boundaries),
            route_seconds=route_seconds,
            decisions_by_switch_id=decisions,
            timing_by_switch_id=timing_by_switch_id,
        )
        projected_phases.append(
            _ProjectedAllStopPhase(
                state=state,
                first_visit_index=first_visit_index,
                first_switch_time=first_switch_time,
                phase_seconds=phase_seconds,
            )
        )

    # Fleet symmetry orders cabin IDs first by the selected discrete phase and,
    # on one rope, by the chronological exit from its preceding switch. Assign
    # labels only after projection so the cyclic phase-0 wrap follows that same
    # convention instead of invalidating an otherwise physical all-stop seed.
    projected_phases.sort(
        key=lambda projected: (
            projected.first_visit_index,
            projected.first_switch_time,
            projected.phase_seconds,
        )
    )

    trajectories: list[EanCabinTrajectory] = []
    initial_states: list[EanInitialPlacementState] = []
    for cabin_id, projected in enumerate(projected_phases):
        initial_states.append(replace(projected.state, cabin_id=cabin_id))
        trajectories.append(
            EanCabinTrajectory(
                cabin_id=cabin_id,
                visits=_build_projected_route_visits(
                    artifact=artifact,
                    visits=visits_by_cabin_id[cabin_id],
                    first_visit_index=projected.first_visit_index,
                    first_switch_time=projected.first_switch_time,
                    timing_by_switch_id=timing_by_switch_id,
                    decisions_by_switch_id=decisions,
                ),
            )
        )
    trajectories.extend(
        EanCabinTrajectory(cabin_id=cabin_id, visits=())
        for cabin_id in range(active_count, parameters.available_fleet_count)
    )

    active_ids = tuple(range(active_count))
    fleet_plan = EanFleetPlan(
        mode=EanFleetMode.OPTIMIZED_INITIAL_PLACEMENT,
        available_fleet_count=parameters.available_fleet_count,
        active_cabin_ids=active_ids,
        inactive_cabin_ids=tuple(range(active_count, parameters.available_fleet_count)),
        initial_states=tuple(initial_states),
    )
    fleet_plan.validate()
    movement_plan = EanMovementPlan(
        scenario_id=artifact.scenario_id,
        horizon_seconds=artifact.config.horizon_seconds,
        model_end_seconds=artifact.config.model_end_seconds,
        trajectories=tuple(trajectories),
        horizon_formulation=horizon_formulation,
        fleet_mode=EanFleetMode.OPTIMIZED_INITIAL_PLACEMENT,
    )
    movement_plan.validate()
    _validate_initial_placement_seed_order(artifact, fleet_plan)
    return EanPrimalSeed(
        fleet_plan=fleet_plan,
        movement_plan=movement_plan,
    )


def _validate_initial_placement_seed_order(
    artifact: EanBuildArtifact,
    fleet_plan: EanFleetPlan,
) -> None:
    """Check seed values governed by fleet-label symmetry constraints."""

    states = tuple(sorted(fleet_plan.initial_states, key=lambda state: state.cabin_id))
    phase_indices = tuple(state.visit_index for state in states)
    if phase_indices != tuple(sorted(phase_indices)):
        raise ValueError("initial-placement seed violates phase-index symmetry")

    exit_headway_by_switch_id = {
        checkpoint.switch_id: checkpoint.headway_seconds
        for checkpoint in artifact.headway_checkpoints
        if checkpoint.kind is HeadwayCheckpointKind.EXIT_SWITCH
    }
    rope_states_by_visit_index: dict[int, list[EanInitialPlacementState]] = {}
    for state in states:
        if state.kind is EanInitialPlacementStateKind.ROPE:
            rope_states_by_visit_index.setdefault(state.visit_index, []).append(state)
    for rope_states in rope_states_by_visit_index.values():
        for leader, follower in zip(rope_states, rope_states[1:]):
            headway_seconds = exit_headway_by_switch_id[leader.switch_id]
            if (
                leader.previous_event_time_seconds + headway_seconds
                > follower.previous_event_time_seconds + _TIME_TOLERANCE_SECONDS
            ):
                raise ValueError(
                    "initial-placement seed violates initial rope headway for "
                    f"cabins {leader.cabin_id}/{follower.cabin_id}"
                )


def _project_phase_to_boundary(
    *,
    artifact: EanBuildArtifact,
    cabin_id: int,
    phase_seconds: float,
    boundaries: tuple[float, ...],
    route_seconds: dict[str, float],
    decisions_by_switch_id: dict[str, EanRouteDecision],
    timing_by_switch_id: dict[str, SkipStopTiming],
) -> tuple[EanInitialPlacementState, int, float]:
    cycle_length = len(artifact.circulation_state_ids)
    boundary_index = next(
        (
            index
            for index, boundary in enumerate(boundaries[:-1])
            if math.isclose(
                phase_seconds,
                boundary,
                abs_tol=_TIME_TOLERANCE_SECONDS,
            )
        ),
        None,
    )
    if boundary_index is not None:
        switch_id = artifact.circulation_state_ids[boundary_index]
        return (
            EanInitialPlacementState(
                cabin_id=cabin_id,
                kind=EanInitialPlacementStateKind.ENTRY_SWITCH,
                switch_id=switch_id,
                visit_index=boundary_index,
                progress=0.0,
                previous_event_time_seconds=0.0,
                next_event_time_seconds=0.0,
            ),
            boundary_index,
            0.0,
        )

    next_index = next(
        index
        for index, boundary in enumerate(boundaries[1:], start=1)
        if phase_seconds < boundary - _TIME_TOLERANCE_SECONDS
    )
    next_phase_index = next_index % cycle_length
    previous_phase_index = (next_phase_index - 1) % cycle_length
    previous_switch_id = artifact.circulation_state_ids[previous_phase_index]
    next_switch_time = boundaries[next_index] - phase_seconds
    rope_seconds = timing_by_switch_id[previous_switch_id].rope_to_next_switch_seconds
    previous_exit_time = next_switch_time - rope_seconds
    previous_entry_time = previous_exit_time - route_seconds[previous_switch_id]

    if previous_exit_time >= -_TIME_TOLERANCE_SECONDS:
        exit_time = max(0.0, previous_exit_time)
        if math.isclose(exit_time, 0.0, abs_tol=_TIME_TOLERANCE_SECONDS):
            kind = EanInitialPlacementStateKind.EXIT_SWITCH
            progress = 0.0
        else:
            kind = (
                EanInitialPlacementStateKind.SERVICE_ROUTE
                if decisions_by_switch_id[previous_switch_id] is EanRouteDecision.STOP
                else EanInitialPlacementStateKind.SKIP_ROUTE
            )
            progress = min(
                1.0,
                max(
                    0.0,
                    -previous_entry_time / (exit_time - previous_entry_time),
                ),
            )
        return (
            EanInitialPlacementState(
                cabin_id=cabin_id,
                kind=kind,
                switch_id=previous_switch_id,
                visit_index=previous_phase_index,
                progress=progress,
                previous_event_time_seconds=previous_entry_time,
                next_event_time_seconds=exit_time,
            ),
            previous_phase_index,
            previous_entry_time,
        )

    return (
        EanInitialPlacementState(
            cabin_id=cabin_id,
            kind=EanInitialPlacementStateKind.ROPE,
            switch_id=previous_switch_id,
            visit_index=next_phase_index,
            progress=min(1.0, max(0.0, -previous_exit_time / rope_seconds)),
            previous_event_time_seconds=previous_exit_time,
            next_event_time_seconds=next_switch_time,
        ),
        next_phase_index,
        next_switch_time,
    )


def _build_projected_route_visits(
    *,
    artifact: EanBuildArtifact,
    visits: tuple[SwitchVisitDefinition, ...],
    first_visit_index: int,
    first_switch_time: float,
    timing_by_switch_id: dict[str, SkipStopTiming],
    decisions_by_switch_id: dict[str, EanRouteDecision],
) -> tuple[EanCabinVisit, ...]:
    result: list[EanCabinVisit] = []
    switch_time = first_switch_time
    for visit in visits[first_visit_index:]:
        if switch_time > artifact.config.operational_end_seconds:
            break
        timing = timing_by_switch_id[visit.switch_id]
        decision = decisions_by_switch_id[visit.switch_id]
        if decision is EanRouteDecision.STOP:
            platform_entry = switch_time + timing.entry_to_platform_entry_seconds
            platform_exit = (
                platform_entry + timing.min_platform_entry_to_platform_exit_seconds
            )
            exit_switch = platform_exit + timing.platform_exit_to_exit_switch_seconds
        else:
            platform_entry = None
            platform_exit = None
            exit_switch = switch_time + timing.skip_entry_to_exit_switch_seconds
        next_switch = exit_switch + timing.rope_to_next_switch_seconds
        result.append(
            EanCabinVisit(
                cabin_id=visit.cabin_id,
                visit_index=visit.visit_index,
                switch_id=visit.switch_id,
                station_id=timing.station_id,
                decision=decision,
                switch_time_seconds=switch_time,
                platform_entry_time_seconds=platform_entry,
                platform_exit_time_seconds=platform_exit,
                exit_switch_time_seconds=exit_switch,
                next_switch_time_seconds=next_switch,
                wait_seconds=0.0,
            )
        )
        switch_time = next_switch
    return tuple(result)


def _visits_by_cabin_id(
    artifact: EanBuildArtifact,
) -> dict[int, tuple[SwitchVisitDefinition, ...]]:
    grouped: dict[int, list[SwitchVisitDefinition]] = {}
    for visit in artifact.switch_visits:
        grouped.setdefault(visit.cabin_id, []).append(visit)
    return {
        cabin_id: tuple(sorted(cabin_visits, key=lambda visit: visit.visit_index))
        for cabin_id, cabin_visits in grouped.items()
    }
