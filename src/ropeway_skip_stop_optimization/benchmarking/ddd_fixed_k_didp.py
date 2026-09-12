"""Frozen input construction for the separate Fixed-K DIDP pilot."""

from dataclasses import replace
from .ddd_fixed_k_arc_flow import (
    DddFixedKArcFlowRunConfig,
    prepare_ddd_fixed_k_arc_flow_run,
)
from .ddd_cp_sat_waiting import with_exit_waiting
from ..optimization.ddd.fixed_k import (
    DddFixedKOperatingMode,
    DddFixedKStartPolicy,
    DddFixedKTrajectoryProblem,
)
from ..optimization.ddd.fixed_timetable_capacity import NestedDemand

EXAMPLE = "five_station_circle_cw_half_skip_no_wait_headway_b_v0"


def prepare_large(
    k,
    *,
    example=EXAMPLE,
    waiting=1200,
    step=1e-6,
    demand=3074,
    start_policy=DddFixedKStartPolicy.BALANCED_REFERENCE,
):
    prepared = prepare_ddd_fixed_k_arc_flow_run(
        DddFixedKArcFlowRunConfig(
            example,
            k,
            DddFixedKOperatingMode.SKIP_STOP,
            start_policy=start_policy,
            cp_seed_time_limit_seconds=0,
        )
    )
    if waiting:
        prepared = with_exit_waiting(
            prepared, maximum_seconds=waiting, step_seconds=step
        )
    problem = prepared.problem
    if demand is not None:
        problem = NestedDemand(problem.passenger_build.demand_groups).apply(
            problem, demand
        )
    return prepared.scenario, problem


def prepare_small(k, *, waiting=0, step=1e-6, horizon=130, capacity=2, groups=None):
    from ..examples.registry import get_example
    from ..optimization.ean import EanPassengerObjective, SparseHeadwayPairBuilder
    from ..optimization.ean.models import (
        EanCabinStart,
        EanCabinStartKind,
        EanDemandGroup,
        StationWaitingMode,
    )
    from ..optimization.ean.builders.fixed_start_builder import (
        ExplicitEanCabinStartBuilder,
    )
    from ..optimization.ean.builders.passenger_builder import (
        EanPassengerCandidateBuildResult,
        build_ean_ride_candidates,
    )
    from ..optimization.ddd.artifact_adapter import (
        EanArtifactToDddMovementProblemAdapter,
    )

    example = get_example(EXAMPLE)
    scenario = example.build_scenario()
    config = replace(
        example.build_ean_config(scenario),
        horizon_seconds=horizon,
        tail_seconds=0,
        cabin_capacity=capacity,
    )
    if waiting:
        config = replace(
            config,
            station_configs=tuple(
                replace(
                    s,
                    waiting_mode=StationWaitingMode.END_OF_PLATFORM_WAIT,
                    max_wait_seconds=waiting,
                    fifo_capacity=None,
                )
                for s in config.station_configs
            ),
        )
    builder = replace(
        example.build_ean_artifact_builder(scenario, config),
        start_builder=ExplicitEanCabinStartBuilder(
            tuple(
                EanCabinStart(i, "A_entry_cw", EanCabinStartKind.FIXED, 8.0 * i)
                for i in range(k)
            )
        ),
        headway_pair_builder=SparseHeadwayPairBuilder(),
    )
    artifact = builder.build(scenario, config)
    if groups is None:
        groups = (
            EanDemandGroup("ab", "A", "B", 0, 3 * k),
            EanDemandGroup("ac", "A", "C", 0, 2 * k),
            EanDemandGroup("bc", "B", "C", 0, 2 * k),
        )
    passengers = EanPassengerCandidateBuildResult(
        groups, build_ean_ride_candidates(groups, artifact)
    )
    problem = DddFixedKTrajectoryProblem(
        EanArtifactToDddMovementProblemAdapter(
            waiting_step_seconds=step
        ).build_trajectory_problem(artifact),
        artifact,
        passengers,
        EanPassengerObjective.JOURNEY_TIME,
        DddFixedKOperatingMode.SKIP_STOP,
        DddFixedKStartPolicy.LEGACY,
    )
    return scenario, problem
