from dataclasses import replace

import pytest

from ropeway_skip_stop_optimization.benchmarking.ddd_ring_demand_case import (
    DddRingDemandCase,
    RingDemandFamily,
    RingDemandTiming,
)
from ropeway_skip_stop_optimization.benchmarking.ddd_fixed_k_arc_flow import (
    DddFixedKArcFlowRunConfig,
    prepare_ddd_fixed_k_arc_flow_run,
    run_ddd_fixed_k_arc_flow,
)
from ropeway_skip_stop_optimization.optimization.ddd.fixed_k import (
    DddFixedKOperatingMode,
    DddFixedKStartPolicy,
)

STATIONS = ("A", "B", "C", "D", "E")
EXAMPLE = "five_station_circle_cw_half_skip_no_wait_headway_b_v0"


@pytest.mark.parametrize("family", list(RingDemandFamily))
@pytest.mark.parametrize("timing", list(RingDemandTiming))
def test_demand_total_direction_and_release_contract(family, timing):
    case = DddRingDemandCase(family, timing)
    groups = case.groups(STATIONS)
    assert sum(g.count for g in groups) == 1280
    assert groups == case.groups(STATIONS)
    assert set(g.release_time_seconds for g in groups) == (
        {0.0} if timing is RingDemandTiming.BATCH else {0.0, 200.0, 400.0, 600.0}
    )
    distances = {
        (STATIONS.index(g.destination_station_id) - STATIONS.index(g.origin_station_id))
        % 5
        for g in groups
    }
    assert (
        distances
        == {
            RingDemandFamily.DIFFUSE: {1, 2, 3, 4},
            RingDemandFamily.LOCAL: {1},
            RingDemandFamily.EXPRESS: {3, 4},
        }[family]
    )
    assert len({g.id for g in groups}) == len(groups)
    assert all(type(g.count) is int and g.count > 0 for g in groups)


def test_non_divisible_small_demand_is_deterministic():
    groups = DddRingDemandCase(
        RingDemandFamily.DIFFUSE, RingDemandTiming.DISTRIBUTED, 7
    ).groups(STATIONS)
    assert len(groups) == 7
    assert sum(g.count for g in groups) == 7


def test_profile_replaces_only_passengers_and_survives_full_runner():
    config = DddFixedKArcFlowRunConfig(
        EXAMPLE,
        1,
        DddFixedKOperatingMode.SKIP_STOP,
        start_policy=DddFixedKStartPolicy.BALANCED_REFERENCE,
        total_time_limit_seconds=20,
        cp_seed_time_limit_seconds=0,
        solver_threads=1,
    )
    original = prepare_ddd_fixed_k_arc_flow_run(config)
    case = DddRingDemandCase(RingDemandFamily.LOCAL, RingDemandTiming.DISTRIBUTED, 20)
    changed = case.apply(original)
    assert changed.problem.trajectory_problem is original.problem.trajectory_problem
    assert changed.problem.artifact is original.problem.artifact
    assert changed.problem.boundary_context == original.problem.boundary_context
    assert changed.seed_trajectories == original.seed_trajectories
    assert changed.problem.fingerprint != original.problem.fingerprint
    config = replace(config, operating_mode=DddFixedKOperatingMode.ALL_STOP)
    changed = replace(
        changed, problem=replace(changed.problem, operating_mode=config.operating_mode)
    )
    result = run_ddd_fixed_k_arc_flow(config, prepared_run=changed)
    assert result.independent_validation_status == "feasible"
    assert result.solve_result.validated_upper_bound == pytest.approx(
        result.independent_validation_objective
    )
    assert result.solve_result.validated_upper_bound < sum(
        g.count * (1200 - g.release_time_seconds)
        for g in changed.problem.passenger_build.demand_groups
    )


def test_waiting_transformation_preserves_custom_passenger_profile():
    from ropeway_skip_stop_optimization.benchmarking.ddd_cp_sat_waiting import (
        with_exit_waiting,
    )

    config = DddFixedKArcFlowRunConfig(
        EXAMPLE,
        1,
        DddFixedKOperatingMode.SKIP_STOP,
        start_policy=DddFixedKStartPolicy.BALANCED_REFERENCE,
    )
    original = prepare_ddd_fixed_k_arc_flow_run(config)
    changed = DddRingDemandCase(
        RingDemandFamily.LOCAL, RingDemandTiming.DISTRIBUTED, 20
    ).apply(original)
    waiting = with_exit_waiting(changed, maximum_seconds=1, step_seconds=1)
    assert (
        waiting.problem.passenger_build.demand_groups
        == changed.problem.passenger_build.demand_groups
    )
    assert sum(g.count for g in waiting.problem.passenger_build.demand_groups) == 20
    assert {
        q.demand_group_id for q in waiting.problem.passenger_build.ride_candidates
    } <= {g.id for g in changed.problem.passenger_build.demand_groups}
