from __future__ import annotations

from ropeway_skip_stop_optimization.examples.artificial_headway_cases import (
    ArtificialHeadwayArchitecture,
    FiveStationCircleCwFullSkipNoWaitHeadwayBExample,
    FiveStationCircleCwFullSkipWaitHeadwayBExample,
    FiveStationCircleCwHalfSkipNoWaitHeadwayBExample,
    artificial_physical_headway_examples,
    build_six_station_line_headway_scenario,
    build_six_station_ring_headway_scenario,
)
from ropeway_skip_stop_optimization.examples.circular_skip_stop import (
    build_circular_skip_stop_ean_pattern_definition,
)
from ropeway_skip_stop_optimization.examples.linear_skip_stop import (
    build_linear_skip_stop_ean_pattern_definition,
)
from ropeway_skip_stop_optimization.examples.registry import EXAMPLES
from ropeway_skip_stop_optimization.mapping import discretize_scenario
from ropeway_skip_stop_optimization.models import (
    HeadwayRouteBehavior,
    MandatoryServiceStationDesign,
)
from ropeway_skip_stop_optimization.optimization.ean.builders.network_timing_builder import (
    NetworkSkipStopTimingBuilder,
)
from ropeway_skip_stop_optimization.optimization.ean import StationWaitingMode
from ropeway_skip_stop_optimization.optimization.ean.builders.physical_network_builder import (
    PhysicalMovementNetworkBuilder,
)
from ropeway_skip_stop_optimization.optimization.headway_policy import (
    PhysicalHeadwayPolicyBuilder,
)


def test_all_artificial_headway_cases_are_registered() -> None:
    examples = artificial_physical_headway_examples()

    assert len(examples) == 9
    assert {example.metadata.id for example in examples} <= set(EXAMPLES)


def test_five_station_full_skip_headway_b_reuses_reference_case() -> None:
    example = FiveStationCircleCwFullSkipNoWaitHeadwayBExample()
    scenario = example.build_scenario()
    config = example.build_ean_config(scenario)
    artifact = example.build_ean_artifact_builder(scenario, config).build(
        scenario,
        config,
    )

    assert scenario.id == example.metadata.id
    assert len(artifact.cabin_starts) == 38
    assert artifact.headway_policy is not None
    assert artifact.headway_policy.has_leader_behavior_rules


def test_five_station_half_demand_headway_b_preserves_reference_demand() -> None:
    example = FiveStationCircleCwHalfSkipNoWaitHeadwayBExample()
    scenario = example.build_scenario()

    assert scenario.id == example.metadata.id
    assert sum(demand.count for demand in scenario.demands) == 1280
    assert example.metadata.id in EXAMPLES


def test_five_station_headway_b_waiting_case_has_explicit_ten_second_limit() -> None:
    example = FiveStationCircleCwFullSkipWaitHeadwayBExample()
    scenario = example.build_scenario()
    config = example.build_ean_config(scenario)

    assert all(
        station.waiting_mode is StationWaitingMode.END_OF_PLATFORM_WAIT
        and station.max_wait_seconds == 10.0
        for station in config.station_configs
    )
    assert example.metadata.id in EXAMPLES


def test_line_terminals_remain_identical_across_architectures() -> None:
    terminal_values: list[tuple[float, float]] = []
    for architecture in ArtificialHeadwayArchitecture:
        scenario = build_six_station_line_headway_scenario(architecture)
        policy = _policy(
            scenario,
            build_linear_skip_stop_ean_pattern_definition(scenario),
        )
        terminal_rules = tuple(
            policy.rule(f"headway_rule::service_mechanism::{state_id}")
            for state_id in ("T5_entry_lr", "T0_entry_rl")
        )
        terminal_values.append(tuple(rule.maximum_seconds for rule in terminal_rules))
        assert all(
            isinstance(assignment.design, MandatoryServiceStationDesign)
            for assignment in scenario.headway_design.station_mechanisms
            if assignment.exit_switch_id in {"T0_exit_lr", "T5_exit_rl"}
        )

    assert terminal_values == [(9.0, 9.0)] * 3


def test_ring_directions_are_separate_physical_patterns() -> None:
    clockwise = build_six_station_ring_headway_scenario(
        ArtificialHeadwayArchitecture.B,
        direction="cw",
    )
    counterclockwise = build_six_station_ring_headway_scenario(
        ArtificialHeadwayArchitecture.B,
        direction="ccw",
    )

    cw_pattern = build_circular_skip_stop_ean_pattern_definition(
        clockwise, direction="cw"
    )
    ccw_pattern = build_circular_skip_stop_ean_pattern_definition(
        counterclockwise, direction="ccw"
    )

    assert all(state_id.endswith("_cw") for state_id in cw_pattern.state_node_ids)
    assert all(state_id.endswith("_ccw") for state_id in ccw_pattern.state_node_ids)
    assert {
        segment.resource_id
        for segment in clockwise.track_segments
        if segment.resource_id and segment.resource_id.startswith("rope_")
    }.isdisjoint(
        {
            segment.resource_id
            for segment in counterclockwise.track_segments
            if segment.resource_id and segment.resource_id.startswith("rope_")
        }
    )


def test_architecture_c_uses_explicit_safety_path_geometry() -> None:
    scenario = build_six_station_ring_headway_scenario(
        ArtificialHeadwayArchitecture.C,
        direction="cw",
    )
    policy = _policy(
        scenario,
        build_circular_skip_stop_ean_pattern_definition(scenario, direction="cw"),
    )

    path_seconds = next(
        quantity.value
        for quantity in policy.derived_quantities
        if quantity.id == "safety_path_seconds::S0_entry_cw"
    )
    recovery = policy.rule("headway_rule::service_mechanism::S0_entry_cw")

    assert path_seconds == 5.0 / 6.0
    assert recovery.maximum_seconds == 6.0


def test_legacy_discretizer_explicitly_rejects_new_headway_designs() -> None:
    scenario = build_six_station_ring_headway_scenario(
        ArtificialHeadwayArchitecture.A,
        direction="cw",
    )

    try:
        discretize_scenario(scenario)
    except NotImplementedError as error:
        assert "EAN or DDD" in str(error)
    else:  # pragma: no cover - explicit regression guard
        raise AssertionError("derived headways must not enter the legacy model")


def _policy(scenario, definition):
    network = PhysicalMovementNetworkBuilder().build(scenario, definition)
    pattern = network.pattern(definition.id)
    timings = NetworkSkipStopTimingBuilder().build(scenario, network, pattern)
    policy = PhysicalHeadwayPolicyBuilder().build(scenario, network, timings, pattern)
    bypass = HeadwayRouteBehavior.BYPASS
    service = HeadwayRouteBehavior.SERVICE
    for rule in policy.rules:
        assert rule.required_seconds(bypass, service) > 0
    return policy
