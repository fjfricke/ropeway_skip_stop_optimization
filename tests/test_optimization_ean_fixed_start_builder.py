from __future__ import annotations

from dataclasses import replace
from datetime import time

import pytest

from ropeway_skip_stop_optimization.examples.circular_skip_stop import (
    FiveStationOptimizedInitialPlacementNoSkipNoWaitExample,
)
from ropeway_skip_stop_optimization.examples.three_station import build_three_station_scenario
from ropeway_skip_stop_optimization.examples.three_station_ean import (
    build_three_station_ean_config,
    build_three_station_ean_pattern_definition,
)
from ropeway_skip_stop_optimization.models import (
    CabinInitialState,
    PhysicalNode,
    PhysicalNodeKind,
    Scenario,
    SpeedProfile,
    SpeedProfileKind,
    TrackSegment,
    TrackSegmentKind,
)
from ropeway_skip_stop_optimization.optimization.ean import (
    ContinuousAllStopMaxCabinStartBuilder,
    DeterministicPhysicalNodeToSwitchStartBuilder,
    EarliestAllStopEanMovementPlanBuilder,
    EanCabinStartKind,
    EanCirculationPatternDefinition,
    EvenlySpacedAllStopCabinStartBuilder,
    NetworkEanBuildArtifactBuilder,
    PhysicalMovementNetworkBuilder,
    SparseHeadwayPairBuilder,
    analyze_all_stop_start_capacity,
    network_ean_builder_for_pattern,
    validate_ean_movement_plan_against_artifact,
)


def test_deterministic_physical_start_builder_maps_three_station_starts() -> None:
    scenario = build_three_station_scenario()
    config = build_three_station_ean_config(scenario)
    network, pattern = _network_and_pattern(scenario)

    starts = DeterministicPhysicalNodeToSwitchStartBuilder().build(
        scenario, config, network, pattern
    )

    starts_by_cabin = {start.cabin_id: start for start in starts}
    assert starts_by_cabin[0].first_switch_id == "M_entry_lr"
    assert starts_by_cabin[0].kind is EanCabinStartKind.FIXED
    assert starts_by_cabin[0].time_seconds == pytest.approx(3 / 2.75 + 150 / 5)

    assert starts_by_cabin[1].first_switch_id == "M_entry_rl"
    assert starts_by_cabin[1].kind is EanCabinStartKind.FIXED
    assert starts_by_cabin[1].time_seconds == pytest.approx(3 / 2.75 + 150 / 5)

    assert starts_by_cabin[2].first_switch_id == "M_entry_lr"
    assert starts_by_cabin[2].time_seconds == pytest.approx(120 + 3 / 2.75 + 150 / 5)
    assert starts_by_cabin[3].first_switch_id == "M_entry_rl"
    assert starts_by_cabin[3].time_seconds == pytest.approx(120 + 3 / 2.75 + 150 / 5)


def test_deterministic_physical_start_builder_keeps_start_on_target_switch_at_available_time() -> None:
    scenario = build_three_station_scenario()
    scenario = replace(
        scenario,
        cabin_initial_states=(
            CabinInitialState(cabin_id=0, node_id="M_entry_lr", available_from=time(8, 1)),
            *scenario.cabin_initial_states[1:],
        ),
    )
    config = build_three_station_ean_config(scenario)
    network, pattern = _network_and_pattern(scenario)

    starts = DeterministicPhysicalNodeToSwitchStartBuilder().build(
        scenario, config, network, pattern
    )

    assert starts[0].cabin_id == 0
    assert starts[0].first_switch_id == "M_entry_lr"
    assert starts[0].kind is EanCabinStartKind.FIXED
    assert starts[0].time_seconds == pytest.approx(60.0)


def test_continuous_all_stop_max_start_builder_places_maximum_three_station_cabins() -> None:
    scenario = build_three_station_scenario()
    config = build_three_station_ean_config(scenario)
    pattern_definition = build_three_station_ean_pattern_definition()
    state_ids = pattern_definition.state_node_ids
    network, pattern = _network_and_pattern(scenario, state_ids)
    builder = ContinuousAllStopMaxCabinStartBuilder()

    starts = builder.build(scenario, config, network, pattern)

    assert len(starts) == 30
    assert {start.cabin_id for start in starts} == set(range(30))
    assert {start.first_switch_id for start in starts} == set(state_ids)
    assert {start.kind for start in starts} == {EanCabinStartKind.FIXED}
    assert all(start.time_seconds >= 0 for start in starts)

    artifact = network_ean_builder_for_pattern(
        pattern_definition=pattern_definition,
        start_builder=builder,
    ).build(scenario, config)
    plan = EarliestAllStopEanMovementPlanBuilder().build(artifact)
    validate_ean_movement_plan_against_artifact(artifact, plan).raise_for_errors()


def test_continuous_all_stop_max_start_builder_rejects_foreign_pattern() -> None:
    scenario = build_three_station_scenario()
    config = build_three_station_ean_config(scenario)
    network, _ = _network_and_pattern(scenario)
    _, foreign_pattern = _network_and_pattern(
        scenario,
        pattern_id="foreign_pattern",
    )

    with pytest.raises(ValueError, match="no unique pattern"):
        ContinuousAllStopMaxCabinStartBuilder().build(
            scenario,
            config,
            network,
            foreign_pattern,
        )


def test_evenly_spaced_all_stop_builder_places_feasible_explicit_fleet() -> None:
    example = FiveStationOptimizedInitialPlacementNoSkipNoWaitExample()
    scenario = example.build_scenario()
    config = example.build_ean_config(scenario)
    optimized_builder = example.build_ean_artifact_builder(scenario, config)
    assert isinstance(optimized_builder, NetworkEanBuildArtifactBuilder)
    builder = EvenlySpacedAllStopCabinStartBuilder(cabin_count=len(scenario.cabins))

    artifact = network_ean_builder_for_pattern(
        pattern_definition=optimized_builder.pattern_definition,
        start_builder=builder,
    ).build(scenario, config)

    assert len(artifact.cabin_starts) == 8
    plan = EarliestAllStopEanMovementPlanBuilder().build(artifact)
    validate_ean_movement_plan_against_artifact(
        artifact,
        plan,
    ).raise_for_errors()


def test_evenly_spaced_all_stop_builder_rejects_fleet_above_ring_capacity() -> None:
    example = FiveStationOptimizedInitialPlacementNoSkipNoWaitExample()
    scenario = example.build_scenario()
    config = example.build_ean_config(scenario)
    optimized_builder = example.build_ean_artifact_builder(scenario, config)
    assert isinstance(optimized_builder, NetworkEanBuildArtifactBuilder)
    state_ids = optimized_builder.pattern_definition.state_node_ids
    network, pattern = _network_and_pattern(scenario, state_ids)
    maximum_starts = ContinuousAllStopMaxCabinStartBuilder().build(
        scenario,
        config,
        network,
        pattern,
    )

    with pytest.raises(ValueError, match="exceeds the circulation capacity"):
        EvenlySpacedAllStopCabinStartBuilder(
            cabin_count=len(maximum_starts) + 1,
        ).build(
            scenario,
            config,
            network,
            pattern,
        )


def test_all_stop_capacity_analysis_reports_exact_headway_slack() -> None:
    example = FiveStationOptimizedInitialPlacementNoSkipNoWaitExample()
    scenario = example.build_scenario()
    config = example.build_ean_config(scenario)
    artifact = replace(
        example.build_ean_artifact_builder(scenario, config),
        start_builder=EvenlySpacedAllStopCabinStartBuilder(1),
        headway_pair_builder=SparseHeadwayPairBuilder(),
    ).build(scenario, config)

    analysis = analyze_all_stop_start_capacity(artifact)

    assert analysis.maximum_cabin_count > 1
    assert analysis.minimum_slack_seconds(analysis.maximum_cabin_count) >= 0
    assert (
        analysis.minimum_slack_seconds(analysis.maximum_cabin_count + 1) < 0
    )


def test_physical_network_rejects_unknown_or_non_entry_pattern_states() -> None:
    scenario = build_three_station_scenario()

    with pytest.raises(ValueError, match="unknown physical node"):
        _network_and_pattern(scenario, ("unknown_switch",))

    with pytest.raises(ValueError, match="not an entry switch"):
        _network_and_pattern(scenario, ("L_platform_exit",))


def test_deterministic_physical_start_builder_rejects_branch_before_target() -> None:
    scenario = build_three_station_scenario()
    extra_node = PhysicalNode(id="branch_node", kind=PhysicalNodeKind.CONNECTOR)
    extra_segment = TrackSegment(
        id="L_platform_exit_to_branch_node",
        kind=TrackSegmentKind.CONNECTOR,
        from_node_id="L_platform_exit",
        to_node_id="branch_node",
        length_m=1.0,
        speed_profile=SpeedProfile(SpeedProfileKind.CONSTANT, speed_m_per_s=1.0),
    )
    scenario = replace(
        scenario,
        physical_nodes=(*scenario.physical_nodes, extra_node),
        track_segments=(*scenario.track_segments, extra_segment),
    )
    config = build_three_station_ean_config(scenario)
    network, pattern = _network_and_pattern(scenario)

    with pytest.raises(ValueError, match="ambiguous path"):
        DeterministicPhysicalNodeToSwitchStartBuilder().build(
            scenario, config, network, pattern
        )


def test_deterministic_physical_start_builder_rejects_cycle_before_target() -> None:
    scenario = build_three_station_scenario()
    loop_a = PhysicalNode(id="loop_a", kind=PhysicalNodeKind.CONNECTOR)
    loop_b = PhysicalNode(id="loop_b", kind=PhysicalNodeKind.CONNECTOR)
    speed = SpeedProfile(SpeedProfileKind.CONSTANT, speed_m_per_s=1.0)
    loop_segments = (
        TrackSegment(
            id="loop_a_to_loop_b",
            kind=TrackSegmentKind.CONNECTOR,
            from_node_id="loop_a",
            to_node_id="loop_b",
            length_m=1.0,
            speed_profile=speed,
        ),
        TrackSegment(
            id="loop_b_to_loop_a",
            kind=TrackSegmentKind.CONNECTOR,
            from_node_id="loop_b",
            to_node_id="loop_a",
            length_m=1.0,
            speed_profile=speed,
        ),
    )
    scenario = replace(
        scenario,
        physical_nodes=(*scenario.physical_nodes, loop_a, loop_b),
        track_segments=(*scenario.track_segments, *loop_segments),
        cabin_initial_states=(
            CabinInitialState(cabin_id=0, node_id="loop_a", available_from=time(8, 0)),
            *scenario.cabin_initial_states[1:],
        ),
    )
    config = build_three_station_ean_config(scenario)
    network, pattern = _network_and_pattern(scenario)

    with pytest.raises(ValueError, match="cycle before first EAN target switch"):
        DeterministicPhysicalNodeToSwitchStartBuilder().build(
            scenario, config, network, pattern
        )


def _network_and_pattern(
    scenario: Scenario,
    state_ids: tuple[str, ...] | None = None,
    *,
    pattern_id: str = "test_pattern",
):
    definition = EanCirculationPatternDefinition(
        id=pattern_id,
        state_node_ids=(
            state_ids
            if state_ids is not None
            else build_three_station_ean_pattern_definition().state_node_ids
        ),
    )
    network = PhysicalMovementNetworkBuilder().build(scenario, definition)
    return network, network.pattern(definition.id)
