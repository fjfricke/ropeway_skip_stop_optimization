from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class BoardingPolicyKind(Enum):
    GREEDY_FIFO_NEXT_COMPATIBLE_CABIN = "greedy_fifo_next_compatible_cabin"


@dataclass(frozen=True)
class DemandArrivalEvent:
    demand_index: int
    time_step: int
    origin: str
    destination: str
    count: int

    def validate(self) -> None:
        if self.demand_index < 0:
            raise ValueError("demand_index must be nonnegative")
        if self.time_step < 0:
            raise ValueError("demand arrival event time_step must be nonnegative")
        if self.origin == self.destination:
            raise ValueError("demand arrival event origin and destination must differ")
        if self.count <= 0:
            raise ValueError("demand arrival event count must be positive")


@dataclass(frozen=True)
class PassengerQueueState:
    time_step: int
    station_id: str
    destination: str
    waiting_count: int

    def validate(self) -> None:
        if self.time_step < 0:
            raise ValueError("passenger queue state time_step must be nonnegative")
        if self.station_id == self.destination:
            raise ValueError("passenger queue state station_id and destination must differ")
        if self.waiting_count < 0:
            raise ValueError("waiting_count must be nonnegative")


@dataclass(frozen=True)
class PassengerBatch:
    batch_id: str
    demand_index: int
    origin: str
    destination: str
    arrival_step: int
    count: int

    def validate(self) -> None:
        if not self.batch_id:
            raise ValueError("passenger batch needs a batch_id")
        if self.demand_index < 0:
            raise ValueError("passenger batch demand_index must be nonnegative")
        if self.origin == self.destination:
            raise ValueError("passenger batch origin and destination must differ")
        if self.arrival_step < 0:
            raise ValueError("passenger batch arrival_step must be nonnegative")
        if self.count <= 0:
            raise ValueError("passenger batch count must be positive")


@dataclass(frozen=True)
class QueueItem:
    batch_id: str
    demand_index: int
    origin: str
    destination: str
    arrival_step: int
    remaining_count: int

    def validate(self) -> None:
        if not self.batch_id:
            raise ValueError("queue item needs a batch_id")
        if self.demand_index < 0:
            raise ValueError("queue item demand_index must be nonnegative")
        if self.origin == self.destination:
            raise ValueError("queue item origin and destination must differ")
        if self.arrival_step < 0:
            raise ValueError("queue item arrival_step must be nonnegative")
        if self.remaining_count <= 0:
            raise ValueError("queue item remaining_count must be positive")


@dataclass(frozen=True)
class OnboardPassengerGroup:
    batch_id: str
    demand_index: int
    origin: str
    destination: str
    arrival_step: int
    boarded_step: int
    count: int

    def validate(self) -> None:
        if not self.batch_id:
            raise ValueError("onboard passenger group needs a batch_id")
        if self.demand_index < 0:
            raise ValueError("onboard passenger group demand_index must be nonnegative")
        if self.origin == self.destination:
            raise ValueError("onboard passenger group origin and destination must differ")
        if self.arrival_step < 0:
            raise ValueError("onboard passenger group arrival_step must be nonnegative")
        if self.boarded_step < self.arrival_step:
            raise ValueError("onboard passenger group boarded before arrival")
        if self.count <= 0:
            raise ValueError("onboard passenger group count must be positive")


@dataclass(frozen=True)
class CabinLoadState:
    time_step: int
    cabin_id: int
    node_id: str
    onboard_groups: tuple[OnboardPassengerGroup, ...]

    @property
    def load_count(self) -> int:
        return sum(group.count for group in self.onboard_groups)

    def validate(self, cabin_capacity: int | None = None) -> None:
        if self.time_step < 0:
            raise ValueError("cabin load state time_step must be nonnegative")
        if self.cabin_id < 0:
            raise ValueError("cabin load state cabin_id must be nonnegative")
        if not self.node_id:
            raise ValueError("cabin load state needs a node_id")
        for group in self.onboard_groups:
            group.validate()
        if cabin_capacity is not None and self.load_count > cabin_capacity:
            raise ValueError("cabin load exceeds cabin capacity")


@dataclass(frozen=True)
class BoardingEvent:
    time_step: int
    cabin_id: int
    station_id: str
    destination: str
    batch_id: str
    count: int
    waiting_steps: int

    def validate(self) -> None:
        if self.time_step < 0:
            raise ValueError("boarding event time_step must be nonnegative")
        if self.cabin_id < 0:
            raise ValueError("boarding event cabin_id must be nonnegative")
        if self.station_id == self.destination:
            raise ValueError("boarding event station_id and destination must differ")
        if not self.batch_id:
            raise ValueError("boarding event needs a batch_id")
        if self.count <= 0:
            raise ValueError("boarding event count must be positive")
        if self.waiting_steps < 0:
            raise ValueError("boarding event waiting_steps must be nonnegative")


@dataclass(frozen=True)
class AlightingEvent:
    time_step: int
    cabin_id: int
    station_id: str
    batch_id: str
    count: int
    onboard_steps: int

    def validate(self) -> None:
        if self.time_step < 0:
            raise ValueError("alighting event time_step must be nonnegative")
        if self.cabin_id < 0:
            raise ValueError("alighting event cabin_id must be nonnegative")
        if not self.station_id:
            raise ValueError("alighting event needs a station_id")
        if not self.batch_id:
            raise ValueError("alighting event needs a batch_id")
        if self.count <= 0:
            raise ValueError("alighting event count must be positive")
        if self.onboard_steps < 0:
            raise ValueError("alighting event onboard_steps must be nonnegative")


@dataclass(frozen=True)
class ReplayStepState:
    time_step: int
    queue_states: tuple[PassengerQueueState, ...]
    cabin_loads: tuple[CabinLoadState, ...]
    boarding_events: tuple[BoardingEvent, ...]
    alighting_events: tuple[AlightingEvent, ...]

    def validate(self, cabin_capacity: int | None = None) -> None:
        if self.time_step < 0:
            raise ValueError("replay step state time_step must be nonnegative")
        for state in self.queue_states:
            state.validate()
        for state in self.cabin_loads:
            state.validate(cabin_capacity)
        for event in self.boarding_events:
            event.validate()
        for event in self.alighting_events:
            event.validate()


@dataclass(frozen=True)
class ReplaySummary:
    arrived_passengers: int
    boarded_passengers: int
    served_passengers: int
    unserved_passengers: int
    onboard_passengers: int
    total_waiting_steps: int
    max_waiting_steps: int

    def validate(self) -> None:
        values = (
            self.arrived_passengers,
            self.boarded_passengers,
            self.served_passengers,
            self.unserved_passengers,
            self.onboard_passengers,
            self.total_waiting_steps,
            self.max_waiting_steps,
        )
        if any(value < 0 for value in values):
            raise ValueError("replay summary counts must be nonnegative")
        if self.arrived_passengers != self.served_passengers + self.unserved_passengers + self.onboard_passengers:
            raise ValueError("replay summary passenger accounting does not balance")


@dataclass(frozen=True)
class ReplayResult:
    discrete_scenario_id: str
    movement_plan_horizon_steps: int
    boarding_policy: BoardingPolicyKind
    steps: tuple[ReplayStepState, ...]
    boarding_events: tuple[BoardingEvent, ...]
    alighting_events: tuple[AlightingEvent, ...]
    final_queue_states: tuple[PassengerQueueState, ...]
    final_cabin_loads: tuple[CabinLoadState, ...]
    summary: ReplaySummary

    def validate(self, cabin_capacity: int | None = None) -> None:
        if not self.discrete_scenario_id:
            raise ValueError("replay result needs a discrete_scenario_id")
        if self.movement_plan_horizon_steps < 0:
            raise ValueError("replay result movement_plan_horizon_steps must be nonnegative")
        for step in self.steps:
            step.validate(cabin_capacity)
        for event in self.boarding_events:
            event.validate()
        for event in self.alighting_events:
            event.validate()
        for state in self.final_queue_states:
            state.validate()
        for state in self.final_cabin_loads:
            state.validate(cabin_capacity)
        self.summary.validate()


@dataclass(frozen=True)
class PassengerStationMetric:
    station_id: str
    count: int

    def validate(self) -> None:
        if not self.station_id:
            raise ValueError("passenger station metric needs a station_id")
        if self.count < 0:
            raise ValueError("passenger station metric count must be nonnegative")


@dataclass(frozen=True)
class PassengerOdMetric:
    origin: str
    destination: str
    count: int

    def validate(self) -> None:
        if not self.origin or not self.destination:
            raise ValueError("passenger OD metric needs origin and destination")
        if self.origin == self.destination:
            raise ValueError("passenger OD metric origin and destination must differ")
        if self.count < 0:
            raise ValueError("passenger OD metric count must be nonnegative")


@dataclass(frozen=True)
class ReplayMetricsStep:
    time_step: int
    arrivals_count: int
    boarding_count: int
    alighting_count: int
    waiting_count: int
    onboard_count: int
    cumulative_waiting_passenger_hours: float
    waiting_by_station: tuple[PassengerStationMetric, ...]
    onboard_by_od: tuple[PassengerOdMetric, ...]

    def validate(self) -> None:
        values = (
            self.time_step,
            self.arrivals_count,
            self.boarding_count,
            self.alighting_count,
            self.waiting_count,
            self.onboard_count,
        )
        if any(value < 0 for value in values):
            raise ValueError("replay metrics step counts must be nonnegative")
        if self.cumulative_waiting_passenger_hours < 0:
            raise ValueError("cumulative_waiting_passenger_hours must be nonnegative")
        for metric in self.waiting_by_station:
            metric.validate()
        for metric in self.onboard_by_od:
            metric.validate()
        if sum(metric.count for metric in self.waiting_by_station) != self.waiting_count:
            raise ValueError("waiting_by_station does not sum to waiting_count")
        if sum(metric.count for metric in self.onboard_by_od) != self.onboard_count:
            raise ValueError("onboard_by_od does not sum to onboard_count")


@dataclass(frozen=True)
class ReplayMetrics:
    discrete_scenario_id: str
    movement_plan_horizon_steps: int
    delta_seconds: float
    steps: tuple[ReplayMetricsStep, ...]

    def validate(self) -> None:
        if not self.discrete_scenario_id:
            raise ValueError("replay metrics needs a discrete_scenario_id")
        if self.movement_plan_horizon_steps < 0:
            raise ValueError("movement_plan_horizon_steps must be nonnegative")
        if self.delta_seconds <= 0:
            raise ValueError("delta_seconds must be positive")
        if len(self.steps) != self.movement_plan_horizon_steps + 1:
            raise ValueError("replay metrics needs horizon_steps + 1 steps")
        previous_cumulative = 0.0
        for expected_step, step in enumerate(self.steps):
            step.validate()
            if step.time_step != expected_step:
                raise ValueError("replay metrics steps must be ordered by time_step")
            if step.cumulative_waiting_passenger_hours < previous_cumulative:
                raise ValueError("cumulative_waiting_passenger_hours must be monotonic")
            previous_cumulative = step.cumulative_waiting_passenger_hours
