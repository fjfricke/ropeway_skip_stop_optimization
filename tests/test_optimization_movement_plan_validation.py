from __future__ import annotations

from dataclasses import replace

from ropeway_skip_stop_optimization.baselines import build_maximal_greedy_all_stop_circulation_plan
from ropeway_skip_stop_optimization.examples.three_station import build_three_station_scenario
from ropeway_skip_stop_optimization.models import CabinPosition, CabinTrajectory, MovementPlan
from ropeway_skip_stop_optimization.optimization.discrete_time import (
    FixedCabinStart,
    validate_optimized_movement_plan,
)
from ropeway_skip_stop_optimization.mapping import discretize_scenario


def test_validate_optimized_movement_plan_accepts_greedy_baseline() -> None:
    discrete = discretize_scenario(build_three_station_scenario())
    plan = build_maximal_greedy_all_stop_circulation_plan(discrete, horizon_steps=20)
    fixed_starts = tuple(
        FixedCabinStart(cabin_id=trajectory.cabin_id, node_id=trajectory.positions[0].node_id)
        for trajectory in plan.trajectories
    )

    result = validate_optimized_movement_plan(discrete, plan, fixed_starts=fixed_starts)

    assert result.is_valid


def test_validate_optimized_movement_plan_rejects_bad_transition() -> None:
    discrete = discretize_scenario(build_three_station_scenario())
    plan = build_maximal_greedy_all_stop_circulation_plan(discrete, horizon_steps=2)
    trajectory = plan.trajectories[0]
    bad_position = replace(
        trajectory.positions[1],
        node_id=trajectory.positions[0].node_id,
        incoming_arc_id=trajectory.positions[1].incoming_arc_id,
    )
    bad_trajectory = replace(
        trajectory,
        positions=(trajectory.positions[0], bad_position, trajectory.positions[2]),
    )
    bad_plan = replace(plan, trajectories=(bad_trajectory, *plan.trajectories[1:]))

    result = validate_optimized_movement_plan(discrete, bad_plan)

    assert not result.is_valid
    assert "invalid_transition" in _issue_codes(result)


def test_validate_optimized_movement_plan_rejects_initial_mismatch() -> None:
    discrete = discretize_scenario(build_three_station_scenario())
    plan = build_maximal_greedy_all_stop_circulation_plan(discrete, horizon_steps=1)
    trajectory = plan.trajectories[0]
    fixed_starts = (
        FixedCabinStart(
            cabin_id=trajectory.cabin_id,
            node_id=trajectory.positions[1].node_id,
        ),
    )

    result = validate_optimized_movement_plan(discrete, plan, fixed_starts=fixed_starts)

    assert not result.is_valid
    assert "initial_position_mismatch" in _issue_codes(result)


def test_validate_optimized_movement_plan_rejects_node_occupancy_violation() -> None:
    discrete = discretize_scenario(build_three_station_scenario())
    node_id = discrete.nodes[0].id
    bad_plan = MovementPlan(
        discrete_scenario_id=discrete.id,
        horizon_steps=0,
        trajectories=(
            CabinTrajectory(cabin_id=0, positions=(CabinPosition(time_step=0, node_id=node_id),)),
            CabinTrajectory(cabin_id=1, positions=(CabinPosition(time_step=0, node_id=node_id),)),
        ),
    )

    result = validate_optimized_movement_plan(discrete, bad_plan)

    assert not result.is_valid
    assert "node_occupancy_violation" in _issue_codes(result)


def test_validate_optimized_movement_plan_rejects_conflict_violation() -> None:
    discrete = discretize_scenario(build_three_station_scenario())
    constraint = next(constraint for constraint in discrete.constraints if len(constraint.node_ids) == 2)
    left_node_id, right_node_id = constraint.node_ids
    bad_plan = MovementPlan(
        discrete_scenario_id=discrete.id,
        horizon_steps=0,
        trajectories=(
            CabinTrajectory(cabin_id=0, positions=(CabinPosition(time_step=0, node_id=left_node_id),)),
            CabinTrajectory(cabin_id=1, positions=(CabinPosition(time_step=0, node_id=right_node_id),)),
        ),
    )

    result = validate_optimized_movement_plan(discrete, bad_plan)

    assert not result.is_valid
    assert "discrete_conflict_violation" in _issue_codes(result)


def _issue_codes(result) -> set[str]:
    return {issue.code for issue in result.issues}
