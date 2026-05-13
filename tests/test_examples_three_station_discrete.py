from __future__ import annotations

from ropeway_skip_stop_optimization.examples.discrete import DiscreteScenarioExample
from ropeway_skip_stop_optimization.examples.three_station import (
    ThreeStationExample,
    ThreeStationFullNoSkipNoWaitExample,
    ThreeStationHalfNoSkipNoWaitExample,
    build_three_station_no_skip_no_wait_scenario,
    build_three_station_scenario,
)
from ropeway_skip_stop_optimization.examples.registry import EXAMPLES, get_example


def test_three_station_example_supports_discrete_exports() -> None:
    example = ThreeStationExample()

    assert isinstance(example, DiscreteScenarioExample)


def test_three_station_discretization_config_uses_default_dt() -> None:
    scenario = build_three_station_scenario()
    config = ThreeStationExample().build_discretization_config(scenario)

    assert config.delta_seconds == 0.5
    assert config.rounding_policy.value == "ceil"


def test_three_station_no_skip_no_wait_scenario_removes_skip_routes_and_segments() -> None:
    scenario = build_three_station_no_skip_no_wait_scenario("three_station_test_no_skip_no_wait")
    middle_station = next(station for station in scenario.stations if station.id == "M")

    assert scenario.id == "three_station_test_no_skip_no_wait"
    assert set(middle_station.route_ids) == {"M_service_lr", "M_service_rl"}
    assert not {route.id for route in scenario.station_routes if route.kind.value == "skip"}
    assert not {segment.id for segment in scenario.track_segments if segment.kind.value == "skip"}


def test_three_station_family_variants_are_registered() -> None:
    assert isinstance(get_example("three_station_v0"), ThreeStationExample)
    assert isinstance(get_example("three_station_full_no_skip_no_wait_v0"), ThreeStationFullNoSkipNoWaitExample)
    assert isinstance(get_example("three_station_half_no_skip_no_wait_v0"), ThreeStationHalfNoSkipNoWaitExample)
    assert {
        example_id
        for example_id, example in EXAMPLES.items()
        if example.metadata.family_id == "three_station_ring"
    } == {
        "three_station_v0",
        "three_station_full_no_skip_no_wait_v0",
        "three_station_half_no_skip_no_wait_v0",
    }
