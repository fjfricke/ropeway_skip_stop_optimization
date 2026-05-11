from __future__ import annotations

from collections.abc import Iterable

from ropeway_skip_stop_optimization.models import (
    CabinPosition,
    CabinTrajectory,
    DiscreteArc,
    DiscreteArcKind,
    DiscreteConstraintKind,
    DiscretePath,
    DiscreteScenario,
    MovementPlan,
    validate_movement_plan,
)

ALL_STOP_SEGMENT_IDS: tuple[str, ...] = (
    "L_exit_lr_to_M_entry_lr",
    "M_lr_approach_fast",
    "M_lr_brake",
    "M_lr_platform",
    "M_lr_accelerate",
    "M_lr_depart_fast",
    "M_exit_lr_to_R_entry_lr",
    "R_turnaround_decelerate",
    "R_turnaround_platform",
    "R_turnaround_accelerate",
    "R_exit_rl_to_M_entry_rl",
    "M_rl_approach_fast",
    "M_rl_brake",
    "M_rl_platform",
    "M_rl_accelerate",
    "M_rl_depart_fast",
    "M_exit_rl_to_L_entry_rl",
    "L_turnaround_decelerate",
    "L_turnaround_platform",
    "L_turnaround_accelerate",
)


def build_greedy_all_stop_circulation_plan(
    discrete_scenario: DiscreteScenario,
    cabin_ids: tuple[int, ...],
    horizon_steps: int,
    *,
    segment_ids: tuple[str, ...] = ALL_STOP_SEGMENT_IDS,
) -> MovementPlan:
    path = build_all_stop_cycle_path(discrete_scenario, segment_ids=segment_ids)
    start_indices = greedy_place_cabins_on_cycle(discrete_scenario, path.node_ids, cabin_ids)
    trajectories = tuple(
        _cycle_trajectory(cabin_id, start_index, path, horizon_steps)
        for cabin_id, start_index in zip(cabin_ids, start_indices)
    )
    plan = MovementPlan(
        discrete_scenario_id=discrete_scenario.id,
        horizon_steps=horizon_steps,
        trajectories=trajectories,
        paths=(path,),
    )
    validate_movement_plan(plan, discrete_scenario)
    return plan


def build_maximal_greedy_all_stop_circulation_plan(
    discrete_scenario: DiscreteScenario,
    horizon_steps: int,
    *,
    segment_ids: tuple[str, ...] = ALL_STOP_SEGMENT_IDS,
) -> MovementPlan:
    path = build_all_stop_cycle_path(discrete_scenario, segment_ids=segment_ids)
    start_indices = greedy_place_max_cabins_on_cycle(discrete_scenario, path.node_ids)
    trajectories = tuple(
        _cycle_trajectory(cabin_id, start_index, path, horizon_steps)
        for cabin_id, start_index in enumerate(start_indices)
    )
    plan = MovementPlan(
        discrete_scenario_id=discrete_scenario.id,
        horizon_steps=horizon_steps,
        trajectories=trajectories,
        paths=(path,),
    )
    validate_movement_plan(plan, discrete_scenario)
    return plan


def build_all_stop_cycle_path(
    discrete_scenario: DiscreteScenario,
    *,
    segment_ids: tuple[str, ...] = ALL_STOP_SEGMENT_IDS,
) -> DiscretePath:
    move_arcs_by_segment_id = _move_arcs_by_segment_id(discrete_scenario.arcs)
    missing_segment_ids = [segment_id for segment_id in segment_ids if segment_id not in move_arcs_by_segment_id]
    if missing_segment_ids:
        raise ValueError(f"all-stop cycle references segments without move arcs: {missing_segment_ids}")

    cycle_arcs = tuple(
        arc
        for segment_id in segment_ids
        for arc in move_arcs_by_segment_id[segment_id]
    )
    if not cycle_arcs:
        raise ValueError("all-stop cycle needs at least one move arc")

    for left, right in zip(cycle_arcs, cycle_arcs[1:]):
        if left.to_node_id != right.from_node_id:
            raise ValueError(f"all-stop cycle is disconnected at {left.id!r} -> {right.id!r}")
    if cycle_arcs[-1].to_node_id != cycle_arcs[0].from_node_id:
        raise ValueError("all-stop cycle is not closed")

    node_ids_with_closure = (cycle_arcs[0].from_node_id, *(arc.to_node_id for arc in cycle_arcs))
    path = DiscretePath(
        id="all_stop_cycle",
        arc_ids=tuple(arc.id for arc in cycle_arcs),
        node_ids=node_ids_with_closure[:-1],
        source_segment_ids=segment_ids,
        source_route_ids=_source_route_ids(cycle_arcs),
    )
    path.validate(discrete_scenario)
    return path


def greedy_place_max_cabins_on_cycle(
    discrete_scenario: DiscreteScenario,
    cycle_node_ids: tuple[str, ...],
) -> tuple[int, ...]:
    if not cycle_node_ids:
        raise ValueError("cycle_node_ids must not be empty")

    conflicts = _headway_conflicting_node_pairs(discrete_scenario)
    placed_indices: list[int] = []
    for candidate_index in range(len(cycle_node_ids)):
        if _is_feasible_cycle_offset(candidate_index, placed_indices, cycle_node_ids, conflicts):
            placed_indices.append(candidate_index)

    return tuple(placed_indices)


def greedy_place_cabins_on_cycle(
    discrete_scenario: DiscreteScenario,
    cycle_node_ids: tuple[str, ...],
    cabin_ids: tuple[int, ...],
) -> tuple[int, ...]:
    if not cycle_node_ids:
        raise ValueError("cycle_node_ids must not be empty")
    if len(cabin_ids) != len(set(cabin_ids)):
        raise ValueError("cabin_ids must be unique")

    conflicts = _headway_conflicting_node_pairs(discrete_scenario)
    placed_indices: list[int] = []
    for cabin_id in cabin_ids:
        for candidate_index in range(len(cycle_node_ids)):
            if _is_feasible_cycle_offset(candidate_index, placed_indices, cycle_node_ids, conflicts):
                placed_indices.append(candidate_index)
                break
        else:
            raise ValueError(f"could not greedily place cabin {cabin_id!r} on the all-stop cycle")

    return tuple(placed_indices)


def _cycle_trajectory(
    cabin_id: int,
    start_index: int,
    path: DiscretePath,
    horizon_steps: int,
) -> CabinTrajectory:
    cycle_length = len(path.node_ids)
    positions: list[CabinPosition] = []
    for time_step in range(horizon_steps + 1):
        node_index = (start_index + time_step) % cycle_length
        incoming_arc_id = None
        if time_step > 0:
            incoming_arc_id = path.arc_ids[(start_index + time_step - 1) % cycle_length]
        positions.append(
            CabinPosition(
                time_step=time_step,
                node_id=path.node_ids[node_index],
                incoming_arc_id=incoming_arc_id,
            )
        )
    return CabinTrajectory(cabin_id=cabin_id, positions=tuple(positions))


def _is_feasible_cycle_offset(
    candidate_index: int,
    placed_indices: Iterable[int],
    cycle_node_ids: tuple[str, ...],
    conflicts: set[frozenset[str]],
) -> bool:
    cycle_length = len(cycle_node_ids)
    for placed_index in placed_indices:
        for offset in range(cycle_length):
            candidate_node_id = cycle_node_ids[(candidate_index + offset) % cycle_length]
            placed_node_id = cycle_node_ids[(placed_index + offset) % cycle_length]
            if candidate_node_id == placed_node_id:
                return False
            if frozenset((candidate_node_id, placed_node_id)) in conflicts:
                return False
    return True


def _move_arcs_by_segment_id(arcs: tuple[DiscreteArc, ...]) -> dict[str, tuple[DiscreteArc, ...]]:
    grouped: dict[str, list[DiscreteArc]] = {}
    for arc in arcs:
        if arc.kind is not DiscreteArcKind.MOVE:
            continue
        if arc.source_segment_id is None:
            continue
        grouped.setdefault(arc.source_segment_id, []).append(arc)

    return {
        segment_id: tuple(sorted(segment_arcs, key=_move_arc_step))
        for segment_id, segment_arcs in grouped.items()
    }


def _move_arc_step(arc: DiscreteArc) -> int:
    return int(arc.id.rsplit("::", 1)[1])


def _source_route_ids(arcs: tuple[DiscreteArc, ...]) -> tuple[str, ...]:
    return tuple(
        dict.fromkeys(
            arc.source_route_id
            for arc in arcs
            if arc.source_route_id is not None
        )
    )


def _headway_conflicting_node_pairs(scenario: DiscreteScenario) -> set[frozenset[str]]:
    return {
        frozenset(constraint.node_ids)
        for constraint in scenario.constraints
        if constraint.kind is DiscreteConstraintKind.HEADWAY and len(constraint.node_ids) == 2
    }
