from __future__ import annotations

from ropeway_skip_stop_optimization.benchmarking.ddd_reservoir_arc_flow import (
    DddReservoirArcFlowRunConfig,
    prepare_ddd_reservoir_arc_flow_run,
)
from ropeway_skip_stop_optimization.optimization.ddd.trajectory_column_generation import (
    DddTrajectoryWaitingDomain,
)


EXAMPLE = "five_station_circle_cw_full_skip_no_wait_headway_b_v0"


def test_five_station_reservoir_defaults_to_one_and_a_half_all_stop_fleet() -> None:
    prepared = prepare_ddd_reservoir_arc_flow_run(
        DddReservoirArcFlowRunConfig(EXAMPLE)
    )
    assert prepared.all_stop_maximum_cabin_count == 38
    assert prepared.problem.available_fleet_count == 57
    assert prepared.problem.total_demand == 2560
    assert prepared.problem.entry_state_id == "A_entry_cw"


def test_five_station_waiting_policy_is_explicit_and_fingerprinted() -> None:
    no_wait = prepare_ddd_reservoir_arc_flow_run(
        DddReservoirArcFlowRunConfig(EXAMPLE)
    ).problem
    waiting = prepare_ddd_reservoir_arc_flow_run(
        DddReservoirArcFlowRunConfig(
            EXAMPLE,
            waiting_max_seconds=10.0,
            waiting_step_seconds=2.0,
        )
    ).problem
    assert waiting.waiting_policy.domain is DddTrajectoryWaitingDomain.BOUNDED_WAIT
    assert all(
        maximum == 10.0
        for _, maximum in waiting.waiting_policy.maximum_wait_seconds_by_station_id
    )
    assert no_wait.fingerprint != waiting.fingerprint
