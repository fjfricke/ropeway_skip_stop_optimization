"""Lift a prepared fixed-start experiment to exit waiting, keeping its snapshot."""

from dataclasses import replace

from ..examples.registry import get_example
from ..optimization.headway_resource_reduction import HeadwayResourceReductionMode
from ..optimization.ddd.artifact_adapter import EanArtifactToDddMovementProblemAdapter
from ..optimization.ddd.cp_sat_certificate import solution_from_cp_sat_payload
from ..optimization.ddd.models import DddRouteDecision
from ..optimization.ddd.trajectory_column_generation import DddTrajectoryWaitingDomain
from ..optimization.ddd.reference import DddReferenceResourceOccurrence
from ..optimization.ddd.time_ticks import ddd_seconds_to_tick, ddd_tick_to_seconds
from ..optimization.ean import SparseHeadwayPairBuilder
from ..optimization.ean.builders.passenger_builder import (
    EanPassengerCandidateBuildResult,
    build_ean_ride_candidates,
)
from ..optimization.ean.builders.fixed_start_builder import ExplicitEanCabinStartBuilder
from ..optimization.ean.fleet import EanInitialPlacementStateKind
from ..optimization.ean.models import StationWaitingMode, EanFleetConfig, EanFleetMode
from .ddd_fixed_k_arc_flow import DddPreparedFixedKArcFlowRun


def with_exit_waiting(
    prepared: DddPreparedFixedKArcFlowRun,
    *,
    maximum_seconds: float,
    step_seconds: float,
) -> DddPreparedFixedKArcFlowRun:
    """Use bounded end-of-platform waiting; never recompute an optimized layout.

    The initial pre-zero movement stays fixed. Only visits starting at or after
    the existing fixed starts get new waiting decisions.
    """
    problem = prepared.problem
    if (
        problem.resolved_trajectory_problem.waiting_policy.domain
        is not DddTrajectoryWaitingDomain.NO_WAIT
    ):
        raise ValueError("exit-wait lift requires a No-Wait snapshot")
    base = problem.trajectory_problem.structural_movement_problem
    scenario = prepared.scenario
    example = get_example(scenario.id)
    config = replace(
        problem.artifact.config,
        station_configs=tuple(
            replace(
                s,
                waiting_mode=StationWaitingMode.END_OF_PLATFORM_WAIT,
                max_wait_seconds=maximum_seconds,
                fifo_capacity=None,
            )
            for s in problem.artifact.config.station_configs
        ),
    )
    builder = replace(
        example.build_ean_artifact_builder(scenario, config),
        fleet_config=EanFleetConfig(mode=EanFleetMode.FIXED_STARTS),
        start_builder=ExplicitEanCabinStartBuilder(problem.artifact.cabin_starts),
        headway_pair_builder=SparseHeadwayPairBuilder(),
        headway_resource_reduction_mode=HeadwayResourceReductionMode.DISABLED,
    )
    artifact = builder.build(scenario, config)
    trajectory = EanArtifactToDddMovementProblemAdapter(
        waiting_step_seconds=step_seconds
    ).build_trajectory_problem(artifact)
    movement = trajectory.structural_movement_problem
    if movement.starts != base.starts:
        raise ValueError(
            "exit waiting must preserve the exact fixed starts and visit bounds"
        )
    added_resources = set(movement.resources_by_id) - set(base.resources_by_id)
    # Existing resources and base travel offsets must be identical; new wait
    # coefficients change only future STOP occupancies.
    old_options = {o.id: o for o in base.route_options}
    for option in movement.route_options:
        old = old_options[option.id]
        if (
            option.duration_tick,
            option.platform_entry_offset_seconds,
            option.platform_exit_offset_seconds,
        ) != (
            old.duration_tick,
            old.platform_entry_offset_seconds,
            old.platform_exit_offset_seconds,
        ):
            raise ValueError("exit-wait lift changed base movement timing")
        old_usages = {u.resource_id: u for u in old.resource_usages}
        for usage in option.resource_usages:
            resource = movement.resources_by_id[usage.resource_id]
            if usage.resource_id in added_resources:
                # Any older completed route ends at/before zero. Its added
                # resource must have cleared with headway before that end.
                if (
                    usage.leader_clear_offset_tick
                    + usage.separation_after_tick(resource)
                    > option.duration_tick
                ):
                    raise ValueError("exit-wait boundary needs a longer prefix history")
            else:
                prior = old_usages[usage.resource_id]
                if (
                    usage.follower_enter_offset_tick,
                    usage.leader_clear_offset_tick,
                    usage.separation_after_tick(resource),
                ) != (
                    prior.follower_enter_offset_tick,
                    prior.leader_clear_offset_tick,
                    prior.separation_after_tick(
                        base.resources_by_id[usage.resource_id]
                    ),
                ):
                    raise ValueError(
                        "exit-wait lift changed existing boundary resource timing"
                    )
    boundary = list(problem.boundary_context.resource_occurrences)
    starts = {s.cabin_id: s for s in movement.starts}
    for state in problem.boundary_context.initial_states:
        if state.kind is EanInitialPlacementStateKind.SERVICE_ROUTE:
            decision = DddRouteDecision.STOP
        elif state.kind is EanInitialPlacementStateKind.SKIP_ROUTE:
            decision = DddRouteDecision.SKIP
        elif (
            state.kind is EanInitialPlacementStateKind.ROPE
            and state.previous_service is not None
        ):
            decision = (
                DddRouteDecision.STOP
                if state.previous_service
                else DddRouteDecision.SKIP
            )
        else:
            raise ValueError("cannot reconstruct fixed prefix for exit-wait boundary")
        options = [
            o
            for o in movement.route_options
            if o.from_state_id == state.switch_id and o.decision is decision
        ]
        if len(options) != 1:
            raise ValueError("exit-wait prefix needs one known route")
        option = options[0]
        start = starts[state.cabin_id]
        if option.to_state_id != start.state_id:
            raise ValueError("exit-wait prefix does not connect to fixed start")
        previous_tick = start.time_tick - option.duration_tick
        if previous_tick > 0:
            raise ValueError("initial prefix must start before or at time zero")
        for usage in option.resource_usages:
            if usage.resource_id not in added_resources:
                continue
            resource = movement.resources_by_id[usage.resource_id]
            entry = previous_tick + usage.follower_enter_offset_tick
            clear = previous_tick + usage.leader_clear_offset_tick
            if clear + usage.separation_after_tick(resource) > 0:
                boundary.append(
                    DddReferenceResourceOccurrence(
                        resource_id=usage.resource_id,
                        cabin_id=state.cabin_id,
                        visit_index=-1,
                        leader_clear_time_seconds=ddd_tick_to_seconds(clear),
                        follower_enter_time_seconds=ddd_tick_to_seconds(entry),
                        separation_after_seconds=usage.separation_after_seconds,
                        boundary_origin=True,
                    )
                )
    lifted = replace(
        problem,
        artifact=artifact,
        trajectory_problem=trajectory,
        passenger_build=EanPassengerCandidateBuildResult(
            problem.passenger_build.demand_groups,
            build_ean_ride_candidates(problem.passenger_build.demand_groups, artifact),
        ),
        boundary_context=replace(
            problem.boundary_context, resource_occurrences=tuple(boundary)
        ),
    )
    lifted.validate()
    # Rebuild resource occurrences of the optional seed against the new core.
    seeds = ()
    if prepared.seed_trajectories:
        seeds = solution_from_cp_sat_payload(
            lifted,
            {
                "trajectory_supports": [
                    {
                        "cabin_id": t.cabin_id,
                        "route_option_ids": [v.route_option_id for v in t.visits],
                        "switch_times_tick": [
                            ddd_seconds_to_tick(v.switch_time_seconds) for v in t.visits
                        ],
                        "wait_ticks": [
                            ddd_seconds_to_tick(v.wait_seconds) for v in t.visits
                        ],
                    }
                    for t in prepared.seed_trajectories
                ]
            },
        ).trajectories
    return replace(prepared, problem=lifted, seed_trajectories=seeds)
