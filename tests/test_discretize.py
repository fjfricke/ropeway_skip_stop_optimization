from __future__ import annotations

import pytest

from ropeway_skip_stop_optimization.examples import build_three_station_scenario
from ropeway_skip_stop_optimization.models import (
    DiscreteArc,
    DiscreteArcKind,
    DiscreteConstraintKind,
    DiscreteConstraintScope,
)
from ropeway_skip_stop_optimization.preprocessing.discretize import (
    DiscretizationConfig,
    RoundingPolicy,
    discretize_scenario,
    duration_steps_for_segment,
    position_m_at_step,
)


def test_three_station_scenario_discretizes_and_validates() -> None:
    scenario = build_three_station_scenario()

    discrete = discretize_scenario(scenario)

    discrete.validate()
    assert discrete.source_scenario_id == "three_station_v0"
    assert discrete.delta_seconds == 0.5
    assert discrete.horizon_steps == 2400


def test_v0_does_not_map_cabins_or_cabin_initial_states() -> None:
    discrete = discretize_scenario(build_three_station_scenario())

    assert discrete.cabins == ()
    assert discrete.cabin_initial_states == ()


def test_expected_segment_duration_steps() -> None:
    scenario = build_three_station_scenario()
    config = DiscretizationConfig(delta_seconds=0.5, rounding_policy=RoundingPolicy.CEIL)
    steps_by_segment_id = {
        segment.id: duration_steps_for_segment(segment, config)
        for segment in scenario.track_segments
    }

    assert steps_by_segment_id["L_exit_lr_to_M_entry_lr"] == 60
    assert steps_by_segment_id["M_exit_lr_to_R_entry_lr"] == 60
    assert steps_by_segment_id["R_exit_rl_to_M_entry_rl"] == 60
    assert steps_by_segment_id["M_exit_rl_to_L_entry_rl"] == 60
    assert steps_by_segment_id["L_turnaround_platform"] == 20
    assert steps_by_segment_id["R_turnaround_platform"] == 20
    assert steps_by_segment_id["M_lr_approach_fast"] == 2
    assert steps_by_segment_id["M_lr_brake"] == 3
    assert steps_by_segment_id["M_lr_accelerate"] == 3
    assert steps_by_segment_id["M_lr_depart_fast"] == 2
    assert steps_by_segment_id["M_lr_skip_bypass"] == 28
    assert steps_by_segment_id["M_rl_skip_bypass"] == 28


def test_segment_duration_steps_match_movement_arc_counts() -> None:
    scenario = build_three_station_scenario()
    discrete = discretize_scenario(scenario)
    config = DiscretizationConfig()
    move_arcs_by_segment_id = _move_arcs_by_segment_id(discrete.arcs)

    for segment in scenario.track_segments:
        assert len(move_arcs_by_segment_id[segment.id]) == duration_steps_for_segment(segment, config)


def test_linear_speed_profile_positions_use_integrated_distance() -> None:
    scenario = build_three_station_scenario()
    config = DiscretizationConfig(delta_seconds=0.5, rounding_policy=RoundingPolicy.CEIL)
    segment_by_id = {segment.id: segment for segment in scenario.track_segments}
    brake = segment_by_id["M_lr_brake"]
    accelerate = segment_by_id["M_lr_accelerate"]

    brake_steps = duration_steps_for_segment(brake, config)
    accelerate_steps = duration_steps_for_segment(accelerate, config)

    assert [
        position_m_at_step(brake, step, brake_steps, config)
        for step in range(brake_steps + 1)
    ] == pytest.approx([0.0, 1.984375, 2.9375, 3.0])
    assert [
        position_m_at_step(accelerate, step, accelerate_steps, config)
        for step in range(accelerate_steps + 1)
    ] == pytest.approx([0.0, 0.765625, 2.5625, 3.0])


def test_discrete_nodes_keep_integrated_linear_speed_positions() -> None:
    discrete = discretize_scenario(build_three_station_scenario())
    node_by_id = {node.id: node for node in discrete.nodes}

    assert node_by_id["seg::M_lr_brake::1"].position_m == pytest.approx(1.984375)
    assert node_by_id["seg::M_lr_brake::2"].position_m == pytest.approx(2.9375)
    assert node_by_id["seg::M_lr_accelerate::1"].position_m == pytest.approx(0.765625)
    assert node_by_id["seg::M_lr_accelerate::2"].position_m == pytest.approx(2.5625)


def test_demand_times_convert_exactly() -> None:
    discrete = discretize_scenario(build_three_station_scenario())
    demand_steps = [(demand.origin, demand.destination, demand.count, demand.time_step) for demand in discrete.demands]

    assert demand_steps == [
        ("L", "R", 20, 120),
        ("L", "M", 4, 240),
        ("M", "R", 5, 360),
        ("R", "L", 6, 480),
        ("R", "M", 3, 600),
        ("M", "L", 4, 720),
        ("L", "R", 5, 960),
        ("R", "L", 5, 1080),
    ]


def test_waiting_arcs_exist_only_at_waiting_physical_nodes() -> None:
    scenario = build_three_station_scenario()
    discrete = discretize_scenario(scenario)
    allowed_wait_nodes = {
        f"pn::{node.id}"
        for node in scenario.physical_nodes
        if node.allows_waiting
    }
    wait_arcs = [arc for arc in discrete.arcs if arc.kind is DiscreteArcKind.WAIT]

    assert {arc.from_node_id for arc in wait_arcs} == allowed_wait_nodes
    assert all(arc.from_node_id == arc.to_node_id for arc in wait_arcs)


def test_station_route_arcs_are_annotated() -> None:
    discrete = discretize_scenario(build_three_station_scenario())
    move_arcs_by_segment_id = _move_arcs_by_segment_id(discrete.arcs)

    assert {arc.source_route_id for arc in move_arcs_by_segment_id["M_lr_skip_bypass"]} == {"M_skip_lr"}
    assert {arc.source_route_id for arc in move_arcs_by_segment_id["M_lr_platform"]} == {"M_service_lr"}
    assert {arc.source_route_id for arc in move_arcs_by_segment_id["L_exit_lr_to_M_entry_lr"]} == {None}


def test_all_stop_service_cycle_is_connected_and_closed() -> None:
    scenario = build_three_station_scenario()
    discrete = discretize_scenario(scenario)
    move_arcs_by_segment_id = _move_arcs_by_segment_id(discrete.arcs)
    route_segments = {route.id: route.segment_ids for route in scenario.station_routes}
    all_stop_segments = [
        "L_exit_lr_to_M_entry_lr",
        *route_segments["M_service_lr"],
        "M_exit_lr_to_R_entry_lr",
        *route_segments["R_service_turnaround"],
        "R_exit_rl_to_M_entry_rl",
        *route_segments["M_service_rl"],
        "M_exit_rl_to_L_entry_rl",
        *route_segments["L_service_turnaround"],
    ]

    segment_start_end = {
        segment_id: (arcs[0].from_node_id, arcs[-1].to_node_id)
        for segment_id, arcs in move_arcs_by_segment_id.items()
    }

    for left_segment_id, right_segment_id in zip(all_stop_segments, all_stop_segments[1:]):
        assert segment_start_end[left_segment_id][1] == segment_start_end[right_segment_id][0]
    assert segment_start_end[all_stop_segments[-1]][1] == segment_start_end[all_stop_segments[0]][0]


def test_discrete_routes_are_generated_for_station_routes() -> None:
    scenario = build_three_station_scenario()
    discrete = discretize_scenario(scenario)
    discrete_route_by_source_id = {route.source_route_id: route for route in discrete.routes}

    assert set(discrete_route_by_source_id) == {route.id for route in scenario.station_routes}
    assert len(discrete_route_by_source_id["M_service_lr"].arc_ids) == 30
    assert len(discrete_route_by_source_id["M_skip_lr"].arc_ids) == 28
    assert len(discrete_route_by_source_id["L_service_turnaround"].arc_ids) == 26


def test_discrete_route_arc_sequences_are_connected() -> None:
    discrete = discretize_scenario(build_three_station_scenario())
    arc_by_id = {arc.id: arc for arc in discrete.arcs}

    for route in discrete.routes:
        route_arcs = [arc_by_id[arc_id] for arc_id in route.arc_ids]
        for left_arc, right_arc in zip(route_arcs, route_arcs[1:]):
            assert left_arc.to_node_id == right_arc.from_node_id


def test_same_segment_headway_constraints_are_generated() -> None:
    discrete = discretize_scenario(build_three_station_scenario())

    assert any(
        constraint.kind is DiscreteConstraintKind.HEADWAY
        and constraint.scope is DiscreteConstraintScope.SAME_SEGMENT
        for constraint in discrete.constraints
    )
    assert _has_constraint(
        discrete,
        "seg::L_turnaround_platform::1",
        "seg::L_turnaround_platform::2",
        scope=DiscreteConstraintScope.SAME_SEGMENT,
    )


def test_physical_segment_endpoints_are_included_in_headway_constraints() -> None:
    discrete = discretize_scenario(build_three_station_scenario())

    assert _has_constraint(
        discrete,
        "pn::L_exit_lr",
        "seg::L_turnaround_accelerate::2",
        scope=DiscreteConstraintScope.SAME_SEGMENT,
    )
    assert _has_constraint(
        discrete,
        "pn::L_exit_lr",
        "seg::L_exit_lr_to_M_entry_lr::1",
        scope=DiscreteConstraintScope.SAME_SEGMENT,
    )


def test_non_waiting_switch_node_conflicts_with_adjacent_segment_positions() -> None:
    discrete = discretize_scenario(build_three_station_scenario())

    assert _has_constraint(
        discrete,
        "pn::M_entry_lr",
        "seg::L_exit_lr_to_M_entry_lr::59",
        scope=DiscreteConstraintScope.SAME_SEGMENT,
    )
    assert _has_constraint(
        discrete,
        "pn::M_entry_lr",
        "seg::M_lr_approach_fast::1",
        scope=DiscreteConstraintScope.SAME_SEGMENT,
    )
    assert _has_constraint(
        discrete,
        "pn::M_entry_lr",
        "seg::M_lr_skip_bypass::1",
        scope=DiscreteConstraintScope.SAME_SEGMENT,
    )


def test_waiting_physical_node_conflicts_with_nearby_segment_positions() -> None:
    discrete = discretize_scenario(build_three_station_scenario())

    assert _has_constraint(
        discrete,
        "pn::L_platform_exit",
        "seg::L_turnaround_accelerate::1",
        scope=DiscreteConstraintScope.SAME_SEGMENT,
    )


def test_headway_constraints_have_no_duplicates_or_self_pairs() -> None:
    discrete = discretize_scenario(build_three_station_scenario())
    pairs = [
        tuple(sorted(constraint.node_ids))
        for constraint in discrete.constraints
        if constraint.kind is DiscreteConstraintKind.HEADWAY
    ]

    assert len(pairs) == len(set(pairs))
    assert all(left != right for left, right in pairs)


def test_cross_segment_constraints_increase_total_constraint_count() -> None:
    discrete = discretize_scenario(build_three_station_scenario())
    cross_constraints = [
        constraint
        for constraint in discrete.constraints
        if constraint.kind is DiscreteConstraintKind.HEADWAY
        and constraint.scope is DiscreteConstraintScope.CROSS_SEGMENT
    ]
    same_segment_constraints = [
        constraint
        for constraint in discrete.constraints
        if constraint.kind is DiscreteConstraintKind.HEADWAY
        and constraint.scope is DiscreteConstraintScope.SAME_SEGMENT
    ]

    assert cross_constraints
    assert len(discrete.constraints) > len(same_segment_constraints)


def _move_arcs_by_segment_id(arcs: tuple[DiscreteArc, ...]) -> dict[str, list[DiscreteArc]]:
    grouped: dict[str, list[DiscreteArc]] = {}
    for arc in arcs:
        if arc.kind is DiscreteArcKind.MOVE:
            assert arc.source_segment_id is not None
            grouped.setdefault(arc.source_segment_id, []).append(arc)

    return {
        segment_id: sorted(segment_arcs, key=lambda arc: int(arc.id.rsplit("::", 1)[1]))
        for segment_id, segment_arcs in grouped.items()
    }


def _has_constraint(
    discrete,
    node_a_id: str,
    node_b_id: str,
    *,
    scope: DiscreteConstraintScope,
) -> bool:
    expected = tuple(sorted((node_a_id, node_b_id)))
    return any(
        constraint.kind is DiscreteConstraintKind.HEADWAY
        and constraint.scope is scope
        and tuple(sorted(constraint.node_ids)) == expected
        for constraint in discrete.constraints
    )
