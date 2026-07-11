from __future__ import annotations

import pytest

from ropeway_skip_stop_optimization.baselines import (
    ALL_STOP_SEGMENT_IDS,
    build_all_stop_cycle_path,
    build_greedy_all_stop_circulation_plan,
    build_maximal_greedy_all_stop_circulation_plan,
    greedy_place_cabins_on_cycle,
    greedy_place_max_cabins_on_cycle,
)
from ropeway_skip_stop_optimization.examples.three_station import build_three_station_scenario
from ropeway_skip_stop_optimization.models import (
    CabinPosition,
    CabinTrajectory,
    DiscreteConstraintKind,
    MovementPlan,
)
from ropeway_skip_stop_optimization.mapping import discretize_scenario


def test_all_stop_cycle_path_is_closed_and_excludes_skips() -> None:
    discrete = discretize_scenario(build_three_station_scenario())
    path = build_all_stop_cycle_path(discrete)
    arc_by_id = {arc.id: arc for arc in discrete.arcs}
    node_by_id = {node.id: node for node in discrete.nodes}

    path.validate(discrete)

    assert len(path.arc_ids) == 432
    assert len(path.node_ids) == len(path.arc_ids)
    assert path.source_segment_ids == ALL_STOP_SEGMENT_IDS
    assert "M_lr_skip_bypass" not in path.source_segment_ids
    assert "M_rl_skip_bypass" not in path.source_segment_ids
    assert arc_by_id[path.arc_ids[-1]].to_node_id == path.node_ids[0]
    assert all(
        node_by_id[node_id].source_segment_id not in {"M_lr_skip_bypass", "M_rl_skip_bypass"}
        for node_id in path.node_ids
    )


def test_greedy_placement_places_example_cabins_without_initial_conflicts() -> None:
    scenario = build_three_station_scenario()
    discrete = discretize_scenario(scenario)
    path = build_all_stop_cycle_path(discrete)
    cabin_ids = tuple(cabin.id for cabin in scenario.cabins)
    placements = greedy_place_cabins_on_cycle(discrete, path.node_ids, cabin_ids)
    conflicts = _headway_conflicting_node_pairs(discrete)

    assert len(placements) == len(cabin_ids)
    assert len(set(placements)) == len(placements)
    for left_index, left_placement in enumerate(placements):
        for right_placement in placements[left_index + 1:]:
            left_node = path.node_ids[left_placement]
            right_node = path.node_ids[right_placement]
            assert left_node != right_node
            assert frozenset((left_node, right_node)) not in conflicts


def test_greedy_circulation_plan_validates_for_short_horizon() -> None:
    scenario = build_three_station_scenario()
    discrete = discretize_scenario(scenario)
    cabin_ids = tuple(cabin.id for cabin in scenario.cabins)

    plan = build_greedy_all_stop_circulation_plan(discrete, cabin_ids, horizon_steps=240)

    plan.validate(discrete)
    assert plan.discrete_scenario_id == discrete.id
    assert len(plan.trajectories) == len(cabin_ids)
    assert all(len(trajectory.positions) == 241 for trajectory in plan.trajectories)
    assert all(position.incoming_arc_id is None for position in (trajectory.positions[0] for trajectory in plan.trajectories))


def test_greedy_circulation_plan_validates_for_one_full_cycle() -> None:
    scenario = build_three_station_scenario()
    discrete = discretize_scenario(scenario)
    path = build_all_stop_cycle_path(discrete)
    cabin_ids = tuple(cabin.id for cabin in scenario.cabins)

    plan = build_greedy_all_stop_circulation_plan(discrete, cabin_ids, horizon_steps=len(path.arc_ids))

    plan.validate(discrete)
    first_trajectory = plan.trajectories[0]
    assert first_trajectory.positions[0].node_id == first_trajectory.positions[-1].node_id
    assert first_trajectory.positions[-1].incoming_arc_id == path.arc_ids[-1]


def test_maximal_greedy_circulation_plan_uses_all_feasible_cycle_slots() -> None:
    discrete = discretize_scenario(build_three_station_scenario())
    path = build_all_stop_cycle_path(discrete)

    placements = greedy_place_max_cabins_on_cycle(discrete, path.node_ids)
    plan = build_maximal_greedy_all_stop_circulation_plan(discrete, horizon_steps=len(path.arc_ids))

    plan.validate(discrete)
    assert len(placements) == 28
    assert len(plan.trajectories) == len(placements)
    assert tuple(trajectory.cabin_id for trajectory in plan.trajectories) == tuple(range(28))
    assert plan.paths[0].source_segment_ids == ALL_STOP_SEGMENT_IDS
    assert "M_lr_skip_bypass" not in plan.paths[0].source_segment_ids
    assert "M_rl_skip_bypass" not in plan.paths[0].source_segment_ids
    with pytest.raises(ValueError, match="could not greedily place cabin 28"):
        greedy_place_cabins_on_cycle(discrete, path.node_ids, tuple(range(29)))


def test_movement_plan_validation_rejects_conflicting_occupancy() -> None:
    discrete = discretize_scenario(build_three_station_scenario())
    node_id = discrete.nodes[0].id
    plan = MovementPlan(
        discrete_scenario_id=discrete.id,
        horizon_steps=0,
        trajectories=(
            CabinTrajectory(cabin_id=0, positions=(CabinPosition(time_step=0, node_id=node_id),)),
            CabinTrajectory(cabin_id=1, positions=(CabinPosition(time_step=0, node_id=node_id),)),
        ),
    )

    with pytest.raises(ValueError, match="occupied by multiple cabins"):
        plan.validate(discrete)


def _headway_conflicting_node_pairs(discrete) -> set[frozenset[str]]:
    return {
        frozenset(constraint.node_ids)
        for constraint in discrete.constraints
        if constraint.kind is DiscreteConstraintKind.HEADWAY and len(constraint.node_ids) == 2
    }
