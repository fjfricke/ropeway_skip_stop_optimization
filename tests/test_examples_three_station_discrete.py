from __future__ import annotations

from ropeway_skip_stop_optimization.examples.discrete import DiscreteScenarioExample
from ropeway_skip_stop_optimization.examples.three_station import (
    ThreeStationExample,
    build_three_station_scenario,
)


def test_three_station_example_supports_discrete_exports() -> None:
    example = ThreeStationExample()

    assert isinstance(example, DiscreteScenarioExample)


def test_three_station_discretization_config_uses_default_dt() -> None:
    scenario = build_three_station_scenario()
    config = ThreeStationExample().build_discretization_config(scenario)

    assert config.delta_seconds == 0.5
    assert config.rounding_policy.value == "ceil"
