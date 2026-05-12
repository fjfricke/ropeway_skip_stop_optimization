from __future__ import annotations

from collections.abc import Mapping

from ropeway_skip_stop_optimization.models import (
    DiscreteScenario,
    DiscreteConstraintStrength,
    MovementPlan,
)
from ropeway_skip_stop_optimization.optimization.discrete_time.graph_index import build_discrete_graph_index
from ropeway_skip_stop_optimization.optimization.discrete_time.models import (
    FixedCabinStart,
    MovementPlanValidationIssue,
    MovementPlanValidationResult,
)


def validate_optimized_movement_plan(
    discrete_scenario: DiscreteScenario,
    movement_plan: MovementPlan,
    fixed_starts: tuple[FixedCabinStart, ...] = (),
    selected_arc_ids_by_cabin: Mapping[int, tuple[str, ...]] | None = None,
) -> MovementPlanValidationResult:
    index = build_discrete_graph_index(discrete_scenario)
    issues: list[MovementPlanValidationIssue] = []

    if movement_plan.discrete_scenario_id != discrete_scenario.id:
        issues.append(
            MovementPlanValidationIssue(
                code="scenario_id_mismatch",
                message="movement plan discrete_scenario_id does not match discrete scenario id",
            )
        )
    if movement_plan.horizon_steps < 0:
        issues.append(
            MovementPlanValidationIssue(
                code="negative_horizon",
                message="movement plan horizon_steps must be nonnegative",
            )
        )
    if movement_plan.horizon_steps > discrete_scenario.horizon_steps:
        issues.append(
            MovementPlanValidationIssue(
                code="horizon_exceeds_scenario",
                message="movement plan horizon exceeds discrete scenario horizon",
            )
        )

    fixed_start_by_cabin = {start.cabin_id: start.node_id for start in fixed_starts}
    if len(fixed_start_by_cabin) != len(fixed_starts):
        issues.append(
            MovementPlanValidationIssue(
                code="duplicate_fixed_start",
                message="fixed starts contain duplicate cabin ids",
            )
        )

    trajectory_by_cabin = {}
    for trajectory in movement_plan.trajectories:
        if trajectory.cabin_id in trajectory_by_cabin:
            issues.append(
                MovementPlanValidationIssue(
                    code="duplicate_trajectory",
                    message=f"cabin {trajectory.cabin_id!r} has multiple trajectories",
                    cabin_id=trajectory.cabin_id,
                )
            )
        trajectory_by_cabin[trajectory.cabin_id] = trajectory

    occupancy_by_time: dict[int, dict[str, list[int]]] = {}
    for trajectory in movement_plan.trajectories:
        expected_time_steps = tuple(range(movement_plan.horizon_steps + 1))
        actual_time_steps = tuple(position.time_step for position in trajectory.positions)
        if actual_time_steps != expected_time_steps:
            issues.append(
                MovementPlanValidationIssue(
                    code="invalid_trajectory_shape",
                    message=(
                        f"cabin {trajectory.cabin_id!r} must contain contiguous positions "
                        f"from t=0 to t={movement_plan.horizon_steps}"
                    ),
                    cabin_id=trajectory.cabin_id,
                )
            )
            continue

        if trajectory.cabin_id in fixed_start_by_cabin:
            start_node_id = trajectory.positions[0].node_id
            expected_start_node_id = fixed_start_by_cabin[trajectory.cabin_id]
            if start_node_id != expected_start_node_id:
                issues.append(
                    MovementPlanValidationIssue(
                        code="initial_position_mismatch",
                        message=(
                            f"cabin {trajectory.cabin_id!r} starts at {start_node_id!r}, "
                            f"expected {expected_start_node_id!r}"
                        ),
                        time_step=0,
                        cabin_id=trajectory.cabin_id,
                        node_id=start_node_id,
                    )
                )

        selected_arc_ids = selected_arc_ids_by_cabin.get(trajectory.cabin_id) if selected_arc_ids_by_cabin else None
        if selected_arc_ids is not None and len(selected_arc_ids) != movement_plan.horizon_steps:
            issues.append(
                MovementPlanValidationIssue(
                    code="selected_arc_length_mismatch",
                    message=f"selected arcs for cabin {trajectory.cabin_id!r} must have length horizon_steps",
                    cabin_id=trajectory.cabin_id,
                )
            )

        for position in trajectory.positions:
            if position.node_id not in index.nodes_by_id:
                issues.append(
                    MovementPlanValidationIssue(
                        code="unknown_node",
                        message=f"cabin {trajectory.cabin_id!r} references unknown node {position.node_id!r}",
                        time_step=position.time_step,
                        cabin_id=trajectory.cabin_id,
                        node_id=position.node_id,
                    )
                )
                continue
            if position.time_step == 0 and position.incoming_arc_id is not None:
                issues.append(
                    MovementPlanValidationIssue(
                        code="unexpected_initial_incoming_arc",
                        message=f"cabin {trajectory.cabin_id!r} must not have an incoming arc at t=0",
                        time_step=0,
                        cabin_id=trajectory.cabin_id,
                        arc_id=position.incoming_arc_id,
                    )
                )
            if position.time_step > 0 and position.incoming_arc_id is None:
                issues.append(
                    MovementPlanValidationIssue(
                        code="missing_incoming_arc",
                        message=f"cabin {trajectory.cabin_id!r} needs an incoming arc at t={position.time_step}",
                        time_step=position.time_step,
                        cabin_id=trajectory.cabin_id,
                        node_id=position.node_id,
                    )
                )
            if position.incoming_arc_id is not None and position.incoming_arc_id not in index.arcs_by_id:
                issues.append(
                    MovementPlanValidationIssue(
                        code="unknown_incoming_arc",
                        message=(
                            f"cabin {trajectory.cabin_id!r} references unknown incoming arc "
                            f"{position.incoming_arc_id!r}"
                        ),
                        time_step=position.time_step,
                        cabin_id=trajectory.cabin_id,
                        arc_id=position.incoming_arc_id,
                    )
                )
            occupancy_by_time.setdefault(position.time_step, {}).setdefault(position.node_id, []).append(
                trajectory.cabin_id
            )

        for previous_position, position in zip(trajectory.positions, trajectory.positions[1:]):
            endpoint_arc_ids = index.arc_ids_by_endpoints.get((previous_position.node_id, position.node_id), ())
            if not endpoint_arc_ids:
                issues.append(
                    MovementPlanValidationIssue(
                        code="invalid_transition",
                        message=(
                            f"cabin {trajectory.cabin_id!r} has invalid transition "
                            f"{previous_position.node_id!r} -> {position.node_id!r}"
                        ),
                        time_step=position.time_step,
                        cabin_id=trajectory.cabin_id,
                        node_id=position.node_id,
                    )
                )
                continue
            if position.incoming_arc_id is not None and position.incoming_arc_id not in endpoint_arc_ids:
                issues.append(
                    MovementPlanValidationIssue(
                        code="incoming_arc_mismatch",
                        message=(
                            f"cabin {trajectory.cabin_id!r} incoming arc {position.incoming_arc_id!r} "
                            f"does not connect {previous_position.node_id!r} -> {position.node_id!r}"
                        ),
                        time_step=position.time_step,
                        cabin_id=trajectory.cabin_id,
                        arc_id=position.incoming_arc_id,
                    )
                )
            if selected_arc_ids is not None and previous_position.time_step < len(selected_arc_ids):
                selected_arc_id = selected_arc_ids[previous_position.time_step]
                if selected_arc_id not in endpoint_arc_ids:
                    issues.append(
                        MovementPlanValidationIssue(
                            code="selected_arc_mismatch",
                            message=(
                                f"selected arc {selected_arc_id!r} for cabin {trajectory.cabin_id!r} "
                                f"does not connect {previous_position.node_id!r} -> {position.node_id!r}"
                            ),
                            time_step=previous_position.time_step,
                            cabin_id=trajectory.cabin_id,
                            arc_id=selected_arc_id,
                        )
                    )

    issues.extend(_occupancy_issues(discrete_scenario, occupancy_by_time))
    return MovementPlanValidationResult(issues=tuple(issues))


def _occupancy_issues(
    discrete_scenario: DiscreteScenario,
    occupancy_by_time: dict[int, dict[str, list[int]]],
) -> list[MovementPlanValidationIssue]:
    issues: list[MovementPlanValidationIssue] = []
    for time_step, cabin_ids_by_node_id in occupancy_by_time.items():
        for node_id, cabin_ids in cabin_ids_by_node_id.items():
            if len(cabin_ids) <= 1:
                continue
            issues.append(
                MovementPlanValidationIssue(
                    code="node_occupancy_violation",
                    message=f"node {node_id!r} is occupied by cabins {tuple(cabin_ids)!r} at t={time_step}",
                    time_step=time_step,
                    node_id=node_id,
                )
            )

        occupied_node_ids = set(cabin_ids_by_node_id)
        for constraint in discrete_scenario.constraints:
            if constraint.strength is not DiscreteConstraintStrength.HARD:
                continue
            if not constraint.node_ids:
                continue
            occupied_constraint_node_ids = tuple(
                node_id for node_id in constraint.node_ids if node_id in occupied_node_ids
            )
            if len(occupied_constraint_node_ids) <= 1:
                continue
            involved_cabins = tuple(
                cabin_id
                for node_id in occupied_constraint_node_ids
                for cabin_id in cabin_ids_by_node_id[node_id]
            )
            issues.append(
                MovementPlanValidationIssue(
                    code="discrete_conflict_violation",
                    message=(
                        f"constraint {constraint.id!r} is violated at t={time_step}: "
                        f"nodes={occupied_constraint_node_ids!r}, cabins={involved_cabins!r}"
                    ),
                    time_step=time_step,
                    constraint_id=constraint.id,
                )
            )
    return issues
