from __future__ import annotations

from dataclasses import replace
from datetime import time

import pytest

from ropeway_skip_stop_optimization.examples.three_station import build_three_station_scenario
from ropeway_skip_stop_optimization.examples.three_station_ean import (
    build_three_station_ean_config,
    build_three_station_ean_ring_switch_order,
)
from ropeway_skip_stop_optimization.models import (
    CabinInitialState,
    PhysicalNode,
    PhysicalNodeKind,
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
    RingEanBuildArtifactBuilder,
    validate_ean_movement_plan_against_artifact,
)


def test_deterministic_physical_start_builder_maps_three_station_starts() -> None:
    scenario = build_three_station_scenario()
    config = build_three_station_ean_config(scenario)
    target_switch_ids = frozenset(build_three_station_ean_ring_switch_order(scenario))

    starts = DeterministicPhysicalNodeToSwitchStartBuilder().build(scenario, config, target_switch_ids)

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
    target_switch_ids = frozenset(build_three_station_ean_ring_switch_order(scenario))

    starts = DeterministicPhysicalNodeToSwitchStartBuilder().build(scenario, config, target_switch_ids)

    assert starts[0].cabin_id == 0
    assert starts[0].first_switch_id == "M_entry_lr"
    assert starts[0].kind is EanCabinStartKind.FIXED
    assert starts[0].time_seconds == pytest.approx(60.0)


def test_continuous_all_stop_max_start_builder_places_maximum_three_station_cabins() -> None:
    scenario = build_three_station_scenario()
    config = build_three_station_ean_config(scenario)
    switch_cycle = build_three_station_ean_ring_switch_order(scenario)
    builder = ContinuousAllStopMaxCabinStartBuilder(switch_cycle=switch_cycle)

    starts = builder.build(scenario, config, frozenset(switch_cycle))

    assert len(starts) == 30
    assert {start.cabin_id for start in starts} == set(range(30))
    assert {start.first_switch_id for start in starts} == set(switch_cycle)
    assert {start.kind for start in starts} == {EanCabinStartKind.FIXED}
    assert all(start.time_seconds >= 0 for start in starts)

    artifact = RingEanBuildArtifactBuilder(
        switch_cycle=switch_cycle,
        start_builder=builder,
    ).build(scenario, config)
    plan = EarliestAllStopEanMovementPlanBuilder().build(artifact)
    validate_ean_movement_plan_against_artifact(artifact, plan).raise_for_errors()


def test_continuous_all_stop_max_start_builder_rejects_mismatched_targets() -> None:
    scenario = build_three_station_scenario()
    config = build_three_station_ean_config(scenario)
    switch_cycle = build_three_station_ean_ring_switch_order(scenario)

    with pytest.raises(ValueError, match="target exactly"):
        ContinuousAllStopMaxCabinStartBuilder(switch_cycle=switch_cycle).build(
            scenario,
            config,
            frozenset({"M_entry_lr"}),
        )


def test_deterministic_physical_start_builder_rejects_unknown_or_non_entry_targets() -> None:
    scenario = build_three_station_scenario()
    config = build_three_station_ean_config(scenario)

    with pytest.raises(ValueError, match="unknown physical node"):
        DeterministicPhysicalNodeToSwitchStartBuilder().build(
            scenario,
            config,
            frozenset({"unknown_switch"}),
        )

    with pytest.raises(ValueError, match="not an entry switch"):
        DeterministicPhysicalNodeToSwitchStartBuilder().build(
            scenario,
            config,
            frozenset({"L_platform_exit"}),
        )


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
    target_switch_ids = frozenset(build_three_station_ean_ring_switch_order(scenario))

    with pytest.raises(ValueError, match="ambiguous path"):
        DeterministicPhysicalNodeToSwitchStartBuilder().build(scenario, config, target_switch_ids)


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
    target_switch_ids = frozenset(build_three_station_ean_ring_switch_order(scenario))

    with pytest.raises(ValueError, match="cycle before first EAN target switch"):
        DeterministicPhysicalNodeToSwitchStartBuilder().build(scenario, config, target_switch_ids)
