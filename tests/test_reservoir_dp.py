import json
from dataclasses import replace

import pytest
from test_optimization_ddd_reservoir_cp_sat import problem

from ropeway_skip_stop_optimization.optimization.ddd.reservoir_dp import (
    ReservoirDpConfig,
    ReservoirDpOptimizer,
    ReservoirDpSearchMode,
    ReservoirDpVariant,
    prepare_reservoir_dp,
)
from ropeway_skip_stop_optimization.optimization.ddd.trajectory_column_generation import (
    DddTrajectoryWaitingDomain,
)
from ropeway_skip_stop_optimization.optimization.ddd.trajectory_problem import (
    DddTrajectoryWaitingPolicy,
)
from ropeway_skip_stop_optimization.optimization.ean.models import EanDemandGroup


def test_preparation_is_stable_and_lossless_for_tiny_domain():
    source = problem(available_fleet_count=2)
    prepared = prepare_reservoir_dp(source)
    payload = json.loads(prepared.json)
    assert payload["source_fingerprint"] == source.fingerprint
    assert payload["available_fleet"] == 2
    assert payload["entry_state"] == 0
    assert payload["states"] == ["A", "B"]
    assert {option["id"] for option in payload["options"]} == {
        "A_skip",
        "A_stop",
        "B_skip",
        "B_stop",
    }
    assert prepare_reservoir_dp(source).fingerprint == prepared.fingerprint


def test_preparation_rejects_unmodelled_time_congruences():
    source = replace(problem(), dispatch_step_seconds=0.000002)
    with pytest.raises(ValueError, match="one-tick"):
        prepare_reservoir_dp(source)


def test_config_rejects_invalid_beam_interval():
    with pytest.raises(ValueError, match="exceeds"):
        ReservoirDpConfig(initial_beam_width=8, max_beam_width=4).validate()


def test_config_rejects_unknown_search_mode():
    with pytest.raises(ValueError, match="search mode"):
        ReservoirDpConfig(search_mode="invented").validate()


def test_native_symbolic_dp_finds_and_independently_validates_tiny_plan():
    source = problem(
        dispatch_end_seconds=0,
        available_fleet_count=1,
        movement_core=replace(
            problem().movement_core,
            passenger_service_end_seconds=5,
            operational_end_seconds=8,
        ),
        demand_groups=(EanDemandGroup("g", "A", "B", 0, 1),),
    )
    result, plan = ReservoirDpOptimizer(
        ReservoirDpConfig(time_limit_seconds=5, initial_beam_width=64)
    ).solve(source)
    assert result["has_valid_plan"], result
    assert result["metrics"]["served"] == 1
    assert plan is not None


def test_native_pattern_groups_use_same_validated_tiny_contract():
    source = problem(
        dispatch_end_seconds=0,
        available_fleet_count=1,
        movement_core=replace(
            problem().movement_core,
            passenger_service_end_seconds=5,
            operational_end_seconds=8,
        ),
        demand_groups=(EanDemandGroup("g", "A", "B", 0, 1),),
    )
    result, _ = ReservoirDpOptimizer(
        ReservoirDpConfig(
            variant=ReservoirDpVariant.PATTERN_GROUPS,
            time_limit_seconds=5,
            initial_beam_width=128,
            max_beam_width=2048,
        )
    ).solve(source)
    assert result["has_valid_plan"], result
    assert result["metrics"]["served"] == 1
    assert result["plan"]["pattern_masks"] == [3]


def test_variant_and_search_engine_are_part_of_recorded_identity():
    source = problem(
        dispatch_end_seconds=0,
        available_fleet_count=1,
        movement_core=replace(
            problem().movement_core,
            passenger_service_end_seconds=5,
            operational_end_seconds=8,
        ),
        demand_groups=(EanDemandGroup("g", "A", "B", 0, 1),),
    )
    symbolic, _ = ReservoirDpOptimizer(
        ReservoirDpConfig(time_limit_seconds=5)
    ).solve(source)
    patterns, _ = ReservoirDpOptimizer(
        ReservoirDpConfig(
            variant=ReservoirDpVariant.PATTERN_GROUPS,
            search_mode=ReservoirDpSearchMode.PRIMAL,
            time_limit_seconds=5,
        )
    ).solve(source)
    assert symbolic["model_fingerprint"] != patterns["model_fingerprint"]
    assert symbolic["native_source_hash"] == patterns["native_source_hash"]


def test_symbolic_waiting_can_hold_release_without_fixing_a_wait_value():
    source = problem(
        dispatch_end_seconds=0,
        available_fleet_count=1,
        movement_core=replace(
            problem().movement_core,
            passenger_service_end_seconds=5,
            operational_end_seconds=8,
        ),
        waiting_policy=DddTrajectoryWaitingPolicy(
            domain=DddTrajectoryWaitingDomain.BOUNDED_WAIT,
            step_seconds=0.000001,
            maximum_wait_seconds_by_station_id=(("A", 2), ("B", 2)),
            earliest_wait_time_seconds=0,
        ),
        demand_groups=(EanDemandGroup("g", "A", "B", 1, 1),),
    )
    result, plan = ReservoirDpOptimizer(
        ReservoirDpConfig(
            time_limit_seconds=5,
            initial_beam_width=128,
            max_beam_width=2048,
        )
    ).solve(source)
    assert result["has_valid_plan"], result
    assert result["metrics"]["served"] == 1
    assert plan.trips[0].wait_ticks[0] >= 500_000
