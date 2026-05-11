from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

from ropeway_skip_stop_optimization.models.scenario import Cabin, Station, StationRoute


class DiscreteArcKind(Enum):
    MOVE = "move"
    WAIT = "wait"


class DiscreteConstraintKind(Enum):
    NODE_OCCUPANCY = "node_occupancy"
    HEADWAY = "headway"
    SWITCH_OCCUPANCY = "switch_occupancy"
    SHARED_RESOURCE = "shared_resource"
    ROUTE_CONTINUITY = "route_continuity"


class DiscreteConstraintScope(Enum):
    SAME_NODE = "same_node"
    SAME_SEGMENT = "same_segment"
    CROSS_SEGMENT = "cross_segment"
    SWITCH = "switch"
    ROUTE = "route"


class DiscreteConstraintStrength(Enum):
    HARD = "hard"
    RELAXABLE = "relaxable"


@dataclass(frozen=True)
class DiscreteNode:
    id: str
    source_physical_node_id: str | None = None
    source_segment_id: str | None = None
    station_id: str | None = None
    resource_id: str | None = None
    position_m: float | None = None
    allows_waiting: bool = False
    allows_boarding: bool = False
    allows_alighting: bool = False

    def validate(self) -> None:
        if self.position_m is not None and self.position_m < 0:
            raise ValueError(f"discrete node {self.id!r} has negative position_m")
        if (self.allows_boarding or self.allows_alighting) and self.station_id is None:
            raise ValueError(f"service-capable node {self.id!r} needs a station_id")


@dataclass(frozen=True)
class DiscreteArc:
    id: str
    kind: DiscreteArcKind
    from_node_id: str
    to_node_id: str
    source_segment_id: str | None = None
    source_route_id: str | None = None

    def validate(self) -> None:
        if self.kind is DiscreteArcKind.WAIT and self.from_node_id != self.to_node_id:
            raise ValueError(f"wait arc {self.id!r} must start and end at the same node")
        if self.kind is DiscreteArcKind.MOVE and self.from_node_id == self.to_node_id:
            raise ValueError(f"move arc {self.id!r} must connect different nodes")


@dataclass(frozen=True)
class DiscreteRoute:
    id: str
    source_route_id: str
    arc_ids: tuple[str, ...]

    def validate(self, arcs_by_id: dict[str, DiscreteArc], route_ids: set[str]) -> None:
        if not self.arc_ids:
            raise ValueError(f"discrete route {self.id!r} needs at least one arc")
        if self.source_route_id not in route_ids:
            raise ValueError(f"discrete route {self.id!r} references unknown source_route_id")

        missing_arcs = set(self.arc_ids) - arcs_by_id.keys()
        if missing_arcs:
            raise ValueError(f"discrete route {self.id!r} references unknown arcs: {missing_arcs}")

        route_arcs = [arcs_by_id[arc_id] for arc_id in self.arc_ids]
        for left, right in zip(route_arcs, route_arcs[1:]):
            if left.to_node_id != right.from_node_id:
                raise ValueError(
                    f"discrete route {self.id!r} is not connected at {left.id!r} -> {right.id!r}"
                )


@dataclass(frozen=True)
class DiscreteDemand:
    time_step: int
    origin: str
    destination: str
    count: int

    def validate(self, horizon_steps: int) -> None:
        if not 0 <= self.time_step <= horizon_steps:
            raise ValueError("discrete demand time_step is outside the horizon")
        if self.origin == self.destination:
            raise ValueError("discrete demand origin and destination must differ")
        if self.count <= 0:
            raise ValueError("discrete demand count must be positive")


@dataclass(frozen=True)
class DiscreteCabinInitialState:
    cabin_id: int
    node_id: str
    available_from_step: int = 0

    def validate(self, horizon_steps: int) -> None:
        if not 0 <= self.available_from_step <= horizon_steps:
            raise ValueError("cabin available_from_step is outside the horizon")


@dataclass(frozen=True)
class DiscreteConstraint:
    id: str
    kind: DiscreteConstraintKind
    scope: DiscreteConstraintScope
    strength: DiscreteConstraintStrength = DiscreteConstraintStrength.HARD
    node_ids: tuple[str, ...] = ()
    arc_ids: tuple[str, ...] = ()
    resource_id: str | None = None
    source_segment_ids: tuple[str, ...] = ()
    source_route_ids: tuple[str, ...] = ()

    def validate(self) -> None:
        if not self.node_ids and not self.arc_ids:
            raise ValueError(f"discrete constraint {self.id!r} must reference nodes or arcs")
        if len(set(self.node_ids)) != len(self.node_ids):
            raise ValueError(f"discrete constraint {self.id!r} has duplicate node ids")
        if len(set(self.arc_ids)) != len(self.arc_ids):
            raise ValueError(f"discrete constraint {self.id!r} has duplicate arc ids")
        if self.kind is DiscreteConstraintKind.HEADWAY and len(self.node_ids) != 2:
            raise ValueError(f"headway constraint {self.id!r} must reference exactly two nodes")


@dataclass(frozen=True)
class DiscreteScenario:
    id: str
    source_scenario_id: str
    delta_seconds: float
    horizon_steps: int
    nodes: tuple[DiscreteNode, ...]
    arcs: tuple[DiscreteArc, ...]
    routes: tuple[DiscreteRoute, ...]
    constraints: tuple[DiscreteConstraint, ...]
    stations: tuple[Station, ...]
    station_routes: tuple[StationRoute, ...]
    cabins: tuple[Cabin, ...]
    cabin_initial_states: tuple[DiscreteCabinInitialState, ...]
    demands: tuple[DiscreteDemand, ...]
    cabin_capacity: int
    required_cabin_spacing_m: float

    def validate(self) -> None:
        if self.delta_seconds <= 0:
            raise ValueError("delta_seconds must be positive")
        if self.horizon_steps <= 0:
            raise ValueError("horizon_steps must be positive")
        if self.cabin_capacity <= 0:
            raise ValueError("cabin_capacity must be positive")
        if self.required_cabin_spacing_m <= 0:
            raise ValueError("required_cabin_spacing_m must be positive")

        node_ids = _unique_ids("discrete node", (node.id for node in self.nodes))
        arc_ids = _unique_ids("discrete arc", (arc.id for arc in self.arcs))
        discrete_route_ids = _unique_ids("discrete route", (route.id for route in self.routes))
        constraint_ids = _unique_ids("discrete constraint", (constraint.id for constraint in self.constraints))
        cabin_ids = _unique_ids("cabin", (cabin.id for cabin in self.cabins))
        station_ids = _unique_ids("station", (station.id for station in self.stations))
        station_route_ids = _unique_ids("station route", (route.id for route in self.station_routes))
        arcs_by_id = {arc.id: arc for arc in self.arcs}

        for node in self.nodes:
            node.validate()
            if node.station_id is not None and node.station_id not in station_ids:
                raise ValueError(f"discrete node {node.id!r} references unknown station_id")

        for arc in self.arcs:
            arc.validate()
            if arc.from_node_id not in node_ids:
                raise ValueError(f"arc {arc.id!r} references unknown from_node_id")
            if arc.to_node_id not in node_ids:
                raise ValueError(f"arc {arc.id!r} references unknown to_node_id")
            if arc.kind is DiscreteArcKind.WAIT:
                node = next(item for item in self.nodes if item.id == arc.from_node_id)
                if not node.allows_waiting:
                    raise ValueError(f"wait arc {arc.id!r} is attached to a non-waiting node")
            if arc.source_route_id is not None and arc.source_route_id not in station_route_ids:
                raise ValueError(f"arc {arc.id!r} references unknown source_route_id")

        for route in self.routes:
            route.validate(arcs_by_id, station_route_ids)

        for constraint in self.constraints:
            constraint.validate()
            for node_id in constraint.node_ids:
                if node_id not in node_ids:
                    raise ValueError(f"discrete constraint {constraint.id!r} references unknown node_id")
            for arc_id in constraint.arc_ids:
                if arc_id not in arc_ids:
                    raise ValueError(f"discrete constraint {constraint.id!r} references unknown arc_id")
            for route_id in constraint.source_route_ids:
                if route_id not in station_route_ids and route_id not in discrete_route_ids:
                    raise ValueError(f"discrete constraint {constraint.id!r} references unknown source_route_id")

        initial_state_cabin_ids = [state.cabin_id for state in self.cabin_initial_states]
        initial_state_cabin_id_set = _unique_ids("discrete cabin initial state", initial_state_cabin_ids)
        if initial_state_cabin_id_set != cabin_ids:
            missing = cabin_ids - initial_state_cabin_id_set
            extra = initial_state_cabin_id_set - cabin_ids
            raise ValueError(f"each cabin needs exactly one initial state; missing={missing}, extra={extra}")
        for state in self.cabin_initial_states:
            state.validate(self.horizon_steps)
            if state.cabin_id not in cabin_ids:
                raise ValueError(f"initial state references unknown cabin_id {state.cabin_id!r}")
            if state.node_id not in node_ids:
                raise ValueError(f"initial state references unknown node_id {state.node_id!r}")

        for demand in self.demands:
            demand.validate(self.horizon_steps)
            if demand.origin not in station_ids:
                raise ValueError(f"demand references unknown origin station {demand.origin!r}")
            if demand.destination not in station_ids:
                raise ValueError(f"demand references unknown destination station {demand.destination!r}")

        if not arc_ids:
            raise ValueError("discrete scenario needs at least one arc")
        if not constraint_ids:
            raise ValueError("discrete scenario needs at least one constraint")


def _unique_ids(label: str, ids: object) -> set:
    seen = set()
    duplicates = set()
    for item_id in ids:
        if item_id in seen:
            duplicates.add(item_id)
        seen.add(item_id)
    if duplicates:
        raise ValueError(f"duplicate {label} ids: {duplicates}")
    return seen
