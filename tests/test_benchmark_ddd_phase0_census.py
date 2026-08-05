from __future__ import annotations

import pytest

from ropeway_skip_stop_optimization.benchmarking.ddd_census import (
    build_example_census,
    estimate_uniform_grid,
)


def test_uniform_grid_estimate_includes_explicit_horizon_boundary() -> None:
    estimate = estimate_uniform_grid(
        horizon_seconds=10.1,
        quantum_seconds=1.0,
        state_count=3,
        route_option_count=5,
        holding_state_count=2,
        resource_count=4,
        cabin_count=7,
    )

    assert estimate.time_point_count == 12
    assert estimate.timed_state_node_count == 36
    assert estimate.route_departure_copy_count == 60
    assert estimate.unit_holding_arc_count == 22
    assert estimate.anonymous_cabin_arc_count == 82
    assert estimate.labeled_cabin_arc_count == 574
    assert estimate.resource_slot_row_count == 48


@pytest.mark.parametrize("quantum", (0.0, -1.0))
def test_uniform_grid_estimate_rejects_nonpositive_quantum(quantum: float) -> None:
    with pytest.raises(ValueError, match="quantum_seconds must be positive"):
        estimate_uniform_grid(
            horizon_seconds=10.0,
            quantum_seconds=quantum,
            state_count=1,
            route_option_count=1,
            holding_state_count=0,
            resource_count=1,
            cabin_count=1,
        )


def test_phase0_census_uses_sparse_artifact_and_counts_full_pair_universe() -> None:
    census = build_example_census(
        "three_station_half_no_skip_no_wait_v0",
        quanta_seconds=(1.0,),
    )

    assert census["fleet_mode"] == "fixed_starts"
    assert census["materialized_headway_pair_count"] == 0
    assert census["complete_headway_pair_universe_count"] > 0
    assert census["ean_candidate_count"] > 0
    assert len(census["uniform_grid_estimates"]) == 1
