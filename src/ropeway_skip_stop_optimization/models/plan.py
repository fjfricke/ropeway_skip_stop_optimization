from __future__ import annotations

from dataclasses import dataclass

from ropeway_skip_stop_optimization.models.discrete_scenario import (
    DiscreteArc,
    DiscreteConstraintKind,
    DiscreteScenario,
)


@dataclass(frozen=True)
class DiscretePath:
    id: str
    arc_ids: tuple[str, ...]
    node_ids: tuple[str, ...]
    source_segment_ids: tuple[str, ...] = ()
    source_route_ids: tuple[str, ...] = ()

    def validate(self, scenario: DiscreteScenario) -> None:
        arcs_by_id = {arc.id: arc for arc in scenario.arcs}
        node_ids = {node.id for node in scenario.nodes}
        station_route_ids = {route.id for route in scenario.station_routes}

        if not self.arc_ids:
            raise ValueError(f"discrete path {self.id!r} needs at least one arc")
        if not self.node_ids:
            raise ValueError(f"discrete path {self.id!r} needs at least one node")

        for node_id in self.node_ids:
            if node_id not in node_ids:
                raise ValueError(f"discrete path {self.id!r} references unknown node_id {node_id!r}")

        missing_arc_ids = set(self.arc_ids) - arcs_by_id.keys()
        if missing_arc_ids:
            raise ValueError(f"discrete path {self.id!r} references unknown arcs: {missing_arc_ids}")

        for route_id in self.source_route_ids:
            if route_id not in station_route_ids:
                raise ValueError(f"discrete path {self.id!r} references unknown source_route_id {route_id!r}")

        path_arcs = tuple(arcs_by_id[arc_id] for arc_id in self.arc_ids)
        if len(self.node_ids) == len(path_arcs):
            self._validate_closed_arc_chain(path_arcs)
            return
        if len(self.node_ids) == len(path_arcs) + 1:
            self._validate_open_arc_chain(path_arcs)
            return
        raise ValueError(
            f"discrete path {self.id!r} must have either len(arc_ids) or len(arc_ids)+1 node ids"
        )

    def _validate_closed_arc_chain(self, path_arcs: tuple[DiscreteArc, ...]) -> None:
        for index, arc in enumerate(path_arcs):
            expected_from = self.node_ids[index]
            expected_to = self.node_ids[(index + 1) % len(self.node_ids)]
            if arc.from_node_id != expected_from or arc.to_node_id != expected_to:
                raise ValueError(
                    f"closed discrete path {self.id!r} is disconnected at arc {arc.id!r}"
                )

    def _validate_open_arc_chain(self, path_arcs: tuple[DiscreteArc, ...]) -> None:
        for index, arc in enumerate(path_arcs):
            expected_from = self.node_ids[index]
            expected_to = self.node_ids[index + 1]
            if arc.from_node_id != expected_from or arc.to_node_id != expected_to:
                raise ValueError(
                    f"open discrete path {self.id!r} is disconnected at arc {arc.id!r}"
                )


@dataclass(frozen=True)
class CabinPosition:
    time_step: int
    node_id: str
    incoming_arc_id: str | None = None


@dataclass(frozen=True)
class CabinTrajectory:
    cabin_id: int
    positions: tuple[CabinPosition, ...]


@dataclass(frozen=True)
class MovementPlan:
    discrete_scenario_id: str
    horizon_steps: int
    trajectories: tuple[CabinTrajectory, ...]
    paths: tuple[DiscretePath, ...] = ()

    def validate(self, scenario: DiscreteScenario) -> None:
        validate_movement_plan(self, scenario)


def validate_movement_plan(plan: MovementPlan, scenario: DiscreteScenario) -> None:
    if plan.discrete_scenario_id != scenario.id:
        raise ValueError("movement plan discrete_scenario_id does not match discrete scenario id")
    if plan.horizon_steps < 0:
        raise ValueError("movement plan horizon_steps must be non-negative")
    if plan.horizon_steps > scenario.horizon_steps:
        raise ValueError("movement plan horizon_steps exceeds discrete scenario horizon")

    for path in plan.paths:
        path.validate(scenario)

    cabin_ids = [trajectory.cabin_id for trajectory in plan.trajectories]
    if len(cabin_ids) != len(set(cabin_ids)):
        raise ValueError("movement plan has duplicate cabin trajectories")

    scenario_cabin_ids = {cabin.id for cabin in scenario.cabins}
    if scenario_cabin_ids:
        unknown_cabin_ids = set(cabin_ids) - scenario_cabin_ids
        if unknown_cabin_ids:
            raise ValueError(f"movement plan references unknown cabin ids: {unknown_cabin_ids}")

    arcs_by_id = {arc.id: arc for arc in scenario.arcs}
    nodes_by_id = {node.id: node for node in scenario.nodes}
    outgoing_arcs_by_nodes = {
        (arc.from_node_id, arc.to_node_id): arc
        for arc in scenario.arcs
    }
    conflicting_node_pairs = _headway_conflicting_node_pairs(scenario)
    occupancy_by_time: dict[int, dict[int, str]] = {}

    for trajectory in plan.trajectories:
        _validate_trajectory_shape(trajectory, plan.horizon_steps)
        previous_position: CabinPosition | None = None
        for position in trajectory.positions:
            if position.node_id not in nodes_by_id:
                raise ValueError(
                    f"trajectory for cabin {trajectory.cabin_id!r} references unknown node_id {position.node_id!r}"
                )
            if position.incoming_arc_id is not None and position.incoming_arc_id not in arcs_by_id:
                raise ValueError(
                    f"trajectory for cabin {trajectory.cabin_id!r} references unknown incoming_arc_id "
                    f"{position.incoming_arc_id!r}"
                )
            if position.time_step == 0 and position.incoming_arc_id is not None:
                raise ValueError(f"cabin {trajectory.cabin_id!r} must not have an incoming arc at t=0")
            if position.time_step > 0 and position.incoming_arc_id is None:
                raise ValueError(f"cabin {trajectory.cabin_id!r} needs an incoming arc at t={position.time_step}")

            if previous_position is not None:
                transition = outgoing_arcs_by_nodes.get((previous_position.node_id, position.node_id))
                if transition is None:
                    raise ValueError(
                        f"cabin {trajectory.cabin_id!r} has invalid transition "
                        f"{previous_position.node_id!r} -> {position.node_id!r}"
                    )
                if position.incoming_arc_id != transition.id:
                    raise ValueError(
                        f"cabin {trajectory.cabin_id!r} incoming arc {position.incoming_arc_id!r} does not "
                        f"match transition {transition.id!r}"
                    )

            occupancy_by_time.setdefault(position.time_step, {})[trajectory.cabin_id] = position.node_id
            previous_position = position

    _validate_node_occupancy(occupancy_by_time, conflicting_node_pairs)


def _validate_trajectory_shape(trajectory: CabinTrajectory, horizon_steps: int) -> None:
    expected_time_steps = tuple(range(horizon_steps + 1))
    actual_time_steps = tuple(position.time_step for position in trajectory.positions)
    if actual_time_steps != expected_time_steps:
        raise ValueError(
            f"trajectory for cabin {trajectory.cabin_id!r} must contain contiguous positions "
            f"from t=0 to t={horizon_steps}"
        )


def _headway_conflicting_node_pairs(scenario: DiscreteScenario) -> set[frozenset[str]]:
    return {
        frozenset(constraint.node_ids)
        for constraint in scenario.constraints
        if constraint.kind is DiscreteConstraintKind.HEADWAY and len(constraint.node_ids) == 2
    }


def _validate_node_occupancy(
    occupancy_by_time: dict[int, dict[int, str]],
    conflicting_node_pairs: set[frozenset[str]],
) -> None:
    for time_step, occupied_by_cabin in occupancy_by_time.items():
        node_to_cabins: dict[str, list[int]] = {}
        for cabin_id, node_id in occupied_by_cabin.items():
            node_to_cabins.setdefault(node_id, []).append(cabin_id)

        for node_id, cabin_ids in node_to_cabins.items():
            if len(cabin_ids) > 1:
                raise ValueError(f"node {node_id!r} is occupied by multiple cabins at t={time_step}")

        occupied_items = list(occupied_by_cabin.items())
        for index, (left_cabin, left_node) in enumerate(occupied_items):
            for right_cabin, right_node in occupied_items[index + 1 :]:
                if frozenset((left_node, right_node)) in conflicting_node_pairs:
                    raise ValueError(
                        "conflicting node occupancy at "
                        f"t={time_step}: cabin {left_cabin!r} on {left_node!r}, "
                        f"cabin {right_cabin!r} on {right_node!r}"
                    )


@dataclass(frozen=True)
class CabinArcStep:
    cabin_id: int
    time_step: int
    arc_id: str


@dataclass(frozen=True)
class Plan:
    id: str
    scenario_id: str
    cabin_steps: tuple[CabinArcStep, ...]

    def validate(self, scenario: DiscreteScenario) -> None:
        if self.scenario_id != scenario.id:
            raise ValueError("plan scenario_id does not match discrete scenario id")

        cabin_ids = {cabin.id for cabin in scenario.cabins}
        arcs_by_id = {arc.id: arc for arc in scenario.arcs}
        nodes_by_id = {node.id: node for node in scenario.nodes}
        initial_state_by_cabin = {state.cabin_id: state for state in scenario.cabin_initial_states}
        conflicting_node_pairs = {
            frozenset(constraint.node_ids)
            for constraint in scenario.constraints
            if constraint.kind is DiscreteConstraintKind.HEADWAY and len(constraint.node_ids) == 2
        }

        steps_by_cabin_time: dict[tuple[int, int], CabinArcStep] = {}
        steps_by_cabin: dict[int, list[CabinArcStep]] = {}
        for step in self.cabin_steps:
            if step.cabin_id not in cabin_ids:
                raise ValueError(f"plan references unknown cabin_id {step.cabin_id!r}")
            if step.arc_id not in arcs_by_id:
                raise ValueError(f"plan references unknown arc_id {step.arc_id!r}")
            if not 0 <= step.time_step < scenario.horizon_steps:
                raise ValueError(f"plan step {step!r} is outside the horizon")

            key = (step.cabin_id, step.time_step)
            if key in steps_by_cabin_time:
                raise ValueError(f"cabin {step.cabin_id!r} has multiple arcs at t={step.time_step}")
            steps_by_cabin_time[key] = step
            steps_by_cabin.setdefault(step.cabin_id, []).append(step)

        for cabin_id, cabin_steps in steps_by_cabin.items():
            cabin_steps.sort(key=lambda item: item.time_step)
            initial_state = initial_state_by_cabin.get(cabin_id)
            if initial_state is None:
                raise ValueError(f"cabin {cabin_id!r} has no initial state")

            first_step = cabin_steps[0]
            first_arc = arcs_by_id[first_step.arc_id]
            if first_step.time_step < initial_state.available_from_step:
                raise ValueError(f"cabin {cabin_id!r} moves before it is available")
            if first_arc.from_node_id != initial_state.node_id:
                raise ValueError(f"cabin {cabin_id!r} first arc does not start at initial node")

            for left, right in zip(cabin_steps, cabin_steps[1:]):
                if right.time_step != left.time_step + 1:
                    raise ValueError(f"cabin {cabin_id!r} has a gap in its arc sequence")
                left_arc = arcs_by_id[left.arc_id]
                right_arc = arcs_by_id[right.arc_id]
                if left_arc.to_node_id != right_arc.from_node_id:
                    raise ValueError(f"cabin {cabin_id!r} has disconnected consecutive arcs")

        self._validate_occupancy(arcs_by_id, nodes_by_id, conflicting_node_pairs)

    def _validate_occupancy(self, arcs_by_id, nodes_by_id, conflicts) -> None:
        occupied_nodes_by_time: dict[int, dict[str, int]] = {}
        for step in self.cabin_steps:
            arc = arcs_by_id[step.arc_id]
            occupied_nodes_by_time.setdefault(step.time_step + 1, {})[step.cabin_id] = arc.to_node_id

        for time_step, occupied_by_cabin in occupied_nodes_by_time.items():
            node_to_cabins: dict[str, list[int]] = {}
            for cabin_id, node_id in occupied_by_cabin.items():
                if node_id not in nodes_by_id:
                    raise ValueError(f"occupancy references unknown node {node_id!r}")
                node_to_cabins.setdefault(node_id, []).append(cabin_id)

            for node_id, cabin_ids in node_to_cabins.items():
                if len(cabin_ids) > 1:
                    raise ValueError(f"node {node_id!r} is occupied by multiple cabins at t={time_step}")

            occupied_items = list(occupied_by_cabin.items())
            for index, (left_cabin, left_node) in enumerate(occupied_items):
                for right_cabin, right_node in occupied_items[index + 1 :]:
                    if frozenset((left_node, right_node)) in conflicts:
                        raise ValueError(
                            "conflicting node occupancy at "
                            f"t={time_step}: cabin {left_cabin!r} on {left_node!r}, "
                            f"cabin {right_cabin!r} on {right_node!r}"
                        )
