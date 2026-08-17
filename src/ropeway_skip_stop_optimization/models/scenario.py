from __future__ import annotations

from dataclasses import dataclass
from datetime import time
from enum import Enum

from ropeway_skip_stop_optimization.models.headway import HeadwayDesign


class StationKind(Enum):
    SERVICE = "service"
    TERMINAL = "terminal"
    STORAGE = "storage"


class PhysicalNodeKind(Enum):
    ENTRY_SWITCH = "entry_switch"
    EXIT_SWITCH = "exit_switch"
    PLATFORM = "platform"
    HOLD = "hold"
    DEPOT = "depot"
    CONNECTOR = "connector"


class TrackSegmentKind(Enum):
    ROPE = "rope"
    STATION = "station"
    CONNECTOR = "connector"
    SKIP = "skip"


class SpeedProfileKind(Enum):
    CONSTANT = "constant"
    LINEAR = "linear"


class StationRouteKind(Enum):
    SERVICE = "service"
    SKIP = "skip"


@dataclass(frozen=True)
class SpeedProfile:
    kind: SpeedProfileKind
    speed_m_per_s: float | None = None
    start_speed_m_per_s: float | None = None
    end_speed_m_per_s: float | None = None

    def validate(self) -> None:
        if self.kind is SpeedProfileKind.CONSTANT:
            if self.speed_m_per_s is None or self.speed_m_per_s <= 0:
                raise ValueError("constant speed profiles need a positive speed_m_per_s")
            if self.start_speed_m_per_s is not None or self.end_speed_m_per_s is not None:
                raise ValueError("constant speed profiles must not set start/end speeds")
            return

        if self.kind is SpeedProfileKind.LINEAR:
            if self.start_speed_m_per_s is None or self.start_speed_m_per_s <= 0:
                raise ValueError("linear speed profiles need a positive start_speed_m_per_s")
            if self.end_speed_m_per_s is None or self.end_speed_m_per_s <= 0:
                raise ValueError("linear speed profiles need a positive end_speed_m_per_s")
            if self.speed_m_per_s is not None:
                raise ValueError("linear speed profiles must not set speed_m_per_s")
            return

        raise ValueError(f"unsupported speed profile kind: {self.kind}")


@dataclass(frozen=True)
class PhysicalNode:
    id: str
    kind: PhysicalNodeKind
    station_id: str | None = None
    allows_waiting: bool = False


@dataclass(frozen=True)
class TrackSegment:
    id: str
    kind: TrackSegmentKind
    from_node_id: str
    to_node_id: str
    length_m: float
    speed_profile: SpeedProfile | None = None
    resource_id: str | None = None

    def validate(self) -> None:
        if self.length_m <= 0:
            raise ValueError(f"track segment {self.id!r} needs a positive length_m")
        if self.speed_profile is not None:
            self.speed_profile.validate()


@dataclass(frozen=True)
class StationRoute:
    id: str
    station_id: str
    kind: StationRouteKind
    segment_ids: tuple[str, ...]
    allows_boarding: bool
    allows_alighting: bool

    def validate(self) -> None:
        if not self.segment_ids:
            raise ValueError(f"station route {self.id!r} needs at least one segment")
        if self.kind is StationRouteKind.SKIP and (self.allows_boarding or self.allows_alighting):
            raise ValueError(f"skip route {self.id!r} must not allow boarding or alighting")


@dataclass(frozen=True)
class Station:
    id: str
    kind: StationKind = StationKind.SERVICE
    name: str | None = None
    route_ids: tuple[str, ...] = ()


@dataclass(frozen=True)
class Cabin:
    id: int

    def validate(self) -> None:
        if self.id < 0:
            raise ValueError("cabin ids must be nonnegative")


@dataclass(frozen=True)
class CabinInitialState:
    cabin_id: int
    node_id: str
    available_from: time


@dataclass(frozen=True)
class Demand:
    arrival_time: time
    origin: str
    destination: str
    count: int

    def validate(self) -> None:
        if self.origin == self.destination:
            raise ValueError("demand origin and destination must differ")
        if self.count <= 0:
            raise ValueError("demand count must be positive")


@dataclass(frozen=True)
class OperatingParameters:
    rope_speed_m_per_s: float
    station_speed_m_per_s: float
    cabin_capacity: int
    cabin_length_m: float
    min_clearance_m: float

    @property
    def required_cabin_spacing_m(self) -> float:
        return self.cabin_length_m + self.min_clearance_m

    def validate(self) -> None:
        if self.rope_speed_m_per_s <= 0:
            raise ValueError("rope_speed_m_per_s must be positive")
        if self.station_speed_m_per_s <= 0:
            raise ValueError("station_speed_m_per_s must be positive")
        if self.cabin_capacity <= 0:
            raise ValueError("cabin_capacity must be positive")
        if self.cabin_length_m <= 0:
            raise ValueError("cabin_length_m must be positive")
        if self.min_clearance_m < 0:
            raise ValueError("min_clearance_m must be nonnegative")


@dataclass(frozen=True)
class Scenario:
    id: str
    service_start_time: time
    service_end_time: time
    stations: tuple[Station, ...]
    physical_nodes: tuple[PhysicalNode, ...]
    track_segments: tuple[TrackSegment, ...]
    station_routes: tuple[StationRoute, ...]
    cabins: tuple[Cabin, ...]
    cabin_initial_states: tuple[CabinInitialState, ...]
    demands: tuple[Demand, ...]
    operating: OperatingParameters
    headway_design: HeadwayDesign | None = None

    def validate(self) -> None:
        if self.service_end_time <= self.service_start_time:
            raise ValueError("service_end_time must be after service_start_time")
        if self.headway_design is not None:
            self.headway_design.validate()

        station_ids = _unique_ids("station", (station.id for station in self.stations))
        node_ids = _unique_ids("physical node", (node.id for node in self.physical_nodes))
        segment_ids = _unique_ids("track segment", (segment.id for segment in self.track_segments))
        route_ids = _unique_ids("station route", (route.id for route in self.station_routes))
        cabin_ids = _unique_ids("cabin", (cabin.id for cabin in self.cabins))

        self.operating.validate()

        demand_station_ids = {
            station.id
            for station in self.stations
            if station.kind in {StationKind.SERVICE, StationKind.TERMINAL}
        }

        for station in self.stations:
            missing_routes = set(station.route_ids) - route_ids
            if missing_routes:
                raise ValueError(f"station {station.id!r} references unknown routes: {missing_routes}")

        for segment in self.track_segments:
            segment.validate()
            if segment.from_node_id not in node_ids:
                raise ValueError(f"segment {segment.id!r} references unknown from_node_id")
            if segment.to_node_id not in node_ids:
                raise ValueError(f"segment {segment.id!r} references unknown to_node_id")

        for route in self.station_routes:
            route.validate()
            if route.station_id not in station_ids:
                raise ValueError(f"route {route.id!r} references unknown station_id")
            missing_segments = set(route.segment_ids) - segment_ids
            if missing_segments:
                raise ValueError(f"route {route.id!r} references unknown segments: {missing_segments}")
            _validate_route_connectivity(route, self.track_segments)

        for cabin in self.cabins:
            cabin.validate()

        initial_state_cabin_ids = [state.cabin_id for state in self.cabin_initial_states]
        initial_state_cabin_id_set = _unique_ids("cabin initial state", initial_state_cabin_ids)
        if initial_state_cabin_id_set != cabin_ids:
            missing = cabin_ids - initial_state_cabin_id_set
            extra = initial_state_cabin_id_set - cabin_ids
            raise ValueError(f"each cabin needs exactly one initial state; missing={missing}, extra={extra}")
        for state in self.cabin_initial_states:
            if state.cabin_id not in cabin_ids:
                raise ValueError(f"initial state references unknown cabin_id {state.cabin_id!r}")
            if state.node_id not in node_ids:
                raise ValueError(f"initial state for cabin {state.cabin_id!r} references unknown node")
            if not self.service_start_time <= state.available_from <= self.service_end_time:
                raise ValueError(f"initial state for cabin {state.cabin_id!r} is outside service window")

        for demand in self.demands:
            demand.validate()
            if demand.origin not in demand_station_ids:
                raise ValueError(f"demand references non-passenger or unknown origin {demand.origin!r}")
            if demand.destination not in demand_station_ids:
                raise ValueError(f"demand references non-passenger or unknown destination {demand.destination!r}")
            if not self.service_start_time <= demand.arrival_time <= self.service_end_time:
                raise ValueError("demand arrival_time is outside service window")


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


def _validate_route_connectivity(route: StationRoute, segments: tuple[TrackSegment, ...]) -> None:
    segments_by_id = {segment.id: segment for segment in segments}
    route_segments = [segments_by_id[segment_id] for segment_id in route.segment_ids]
    for left, right in zip(route_segments, route_segments[1:]):
        if left.to_node_id != right.from_node_id:
            raise ValueError(
                f"route {route.id!r} is not connected at {left.id!r} -> {right.id!r}"
            )
