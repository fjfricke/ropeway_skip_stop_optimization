from dataclasses import replace

from test_reservoir_hybrid import small
from ropeway_skip_stop_optimization.optimization.ddd.reservoir_cp_sat_certificate import (
    DddReservoirCpPlan,
    DddReservoirCpTrip,
    validate_reservoir_cp_plan,
)
from ropeway_skip_stop_optimization.optimization.ddd.reservoir_hybrid.repair import (
    trim_empty_tails,
)


def fixture():
    p = small(False)
    p = replace(
        p,
        available_fleet_count=2,
        movement_core=replace(p.movement_core, operational_end_seconds=10),
    )
    trips = tuple(
        DddReservoirCpTrip(
            k,
            ("A_stop", "B_stop", "A_stop", "B_stop"),
            tuple((2 * i + k) * 1000000 for i in range(4)),
            (0,) * 4,
            (8 + k) * 1000000,
        )
        for k in range(2)
    )
    ride = next(
        r
        for r in p.passenger_build.ride_candidates
        if r.cabin_id == 1 and r.board_visit_index == 0
    )
    return p, DddReservoirCpPlan(trips, {ride.id: 1})


def test_empty_trip_and_suffix_removed_without_changing_passenger_value():
    p, plan = fixture()
    trimmed = trim_empty_tails(p, plan)
    assert len(trimmed.trips) == 1
    assert trimmed.trips[0].cabin_id == 0
    assert trimmed.trips[0].return_tick == 5_000_000
    assert len(trimmed.trips[0].route_option_ids) == 2
    assert (
        validate_reservoir_cp_plan(p, plan).journey_time_tick
        == validate_reservoir_cp_plan(p, trimmed).journey_time_tick
    )
    assert trim_empty_tails(p, trimmed) == trimmed


def test_earliest_allowed_return_is_retained():
    p, plan = fixture()
    p = replace(p, return_start_seconds=6)
    trimmed = trim_empty_tails(p, plan)
    assert trimmed.trips[0].return_tick == 9_000_000
    assert len(trimmed.trips[0].route_option_ids) == 4
