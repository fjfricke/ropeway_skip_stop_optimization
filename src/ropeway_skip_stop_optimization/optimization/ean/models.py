from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class StationWaitingMode(Enum):
    NO_WAITING = "no_waiting"
    END_OF_PLATFORM_WAIT = "end_of_platform_wait"
    STATION_FIFO_BUFFER = "station_fifo_buffer"


class EanCabinStartKind(Enum):
    FIXED = "fixed"
    EARLIEST = "earliest"


class HeadwayCheckpointKind(Enum):
    PLATFORM_ENTRY = "platform_entry"
    PLATFORM_EXIT = "platform_exit"
    EXIT_SWITCH = "exit_switch"


class EanTimeReference(Enum):
    ENTRY_TIME = "entry_time"
    PLATFORM_ENTRY_TIME = "platform_entry_time"
    PLATFORM_EXIT_TIME = "platform_exit_time"
    EXIT_SWITCH_TIME = "exit_switch_time"


class EanActivationReference(Enum):
    ACTIVE = "active"
    SERVE = "serve"
    SKIP = "skip"


@dataclass(frozen=True)
class SkipStopTiming:
    switch_id: str
    station_id: str
    entry_to_platform_entry_seconds: float
    min_platform_entry_to_platform_exit_seconds: float
    platform_exit_to_exit_switch_seconds: float
    skip_entry_to_exit_switch_seconds: float
    rope_to_next_switch_seconds: float

    def validate(self) -> None:
        _require_id("skip/stop timing switch_id", self.switch_id)
        _require_id("skip/stop timing station_id", self.station_id)
        _require_positive("entry_to_platform_entry_seconds", self.entry_to_platform_entry_seconds)
        _require_positive(
            "min_platform_entry_to_platform_exit_seconds",
            self.min_platform_entry_to_platform_exit_seconds,
        )
        _require_positive(
            "platform_exit_to_exit_switch_seconds",
            self.platform_exit_to_exit_switch_seconds,
        )
        _require_positive("skip_entry_to_exit_switch_seconds", self.skip_entry_to_exit_switch_seconds)
        _require_positive("rope_to_next_switch_seconds", self.rope_to_next_switch_seconds)


@dataclass(frozen=True)
class StationEanConfig:
    station_id: str
    waiting_mode: StationWaitingMode
    fifo_capacity: int | None = None

    def validate(self) -> None:
        _require_id("station EAN config station_id", self.station_id)
        if self.waiting_mode is StationWaitingMode.STATION_FIFO_BUFFER:
            if self.fifo_capacity is None or self.fifo_capacity <= 0:
                raise ValueError("STATION_FIFO_BUFFER stations need a positive fifo_capacity")
            return

        if self.fifo_capacity is not None:
            raise ValueError("fifo_capacity is only valid for STATION_FIFO_BUFFER stations")


@dataclass(frozen=True)
class EanConfig:
    horizon_seconds: float
    tail_seconds: float
    cabin_capacity: int
    station_configs: tuple[StationEanConfig, ...]

    @property
    def model_end_seconds(self) -> float:
        return self.horizon_seconds + self.tail_seconds

    def validate(self) -> None:
        _require_positive("horizon_seconds", self.horizon_seconds)
        _require_nonnegative("tail_seconds", self.tail_seconds)
        if self.cabin_capacity <= 0:
            raise ValueError("EAN config cabin_capacity must be positive")
        if not self.station_configs:
            raise ValueError("EAN config needs at least one station config")

        station_ids = [config.station_id for config in self.station_configs]
        _require_unique("station EAN config", station_ids)
        for config in self.station_configs:
            config.validate()


@dataclass(frozen=True)
class EanCabinStart:
    cabin_id: int
    first_switch_id: str
    kind: EanCabinStartKind
    time_seconds: float

    def validate(self) -> None:
        _require_nonnegative_int("EAN cabin start cabin_id", self.cabin_id)
        _require_id("EAN cabin start first_switch_id", self.first_switch_id)
        _require_nonnegative("EAN cabin start time_seconds", self.time_seconds)


@dataclass(frozen=True)
class SwitchVisitDefinition:
    cabin_id: int
    visit_index: int
    switch_id: str

    def validate(self) -> None:
        _require_nonnegative_int("switch visit cabin_id", self.cabin_id)
        _require_nonnegative_int("switch visit visit_index", self.visit_index)
        _require_id("switch visit switch_id", self.switch_id)


@dataclass(frozen=True)
class SwitchTransition:
    from_switch_id: str
    to_switch_id: str
    min_seconds: float
    max_seconds: float

    def validate(self) -> None:
        _require_id("switch transition from_switch_id", self.from_switch_id)
        _require_id("switch transition to_switch_id", self.to_switch_id)
        _require_positive("switch transition min_seconds", self.min_seconds)
        _require_positive("switch transition max_seconds", self.max_seconds)
        if self.max_seconds < self.min_seconds:
            raise ValueError("switch transition max_seconds must be at least min_seconds")


@dataclass(frozen=True)
class SwitchVisitBuildResult:
    visits: tuple[SwitchVisitDefinition, ...]
    transitions: tuple[SwitchTransition, ...]

    def validate(self) -> None:
        for visit in self.visits:
            visit.validate()
        for transition in self.transitions:
            transition.validate()


@dataclass(frozen=True)
class HeadwayCheckpointDefinition:
    id: str
    kind: HeadwayCheckpointKind
    switch_id: str
    station_id: str
    headway_seconds: float
    applies_to_serve: bool
    applies_to_skip: bool
    waiting_modes: tuple[StationWaitingMode, ...]

    def validate(self) -> None:
        _require_id("headway checkpoint id", self.id)
        _require_id("headway checkpoint switch_id", self.switch_id)
        _require_id("headway checkpoint station_id", self.station_id)
        _require_positive("headway checkpoint headway_seconds", self.headway_seconds)
        if not (self.applies_to_serve or self.applies_to_skip):
            raise ValueError("headway checkpoint must apply to serve and/or skip")
        if not self.waiting_modes:
            raise ValueError("headway checkpoint needs at least one waiting mode")


@dataclass(frozen=True)
class HeadwayCandidate:
    id: str
    checkpoint_id: str
    cabin_id: int
    visit_index: int
    time_reference: EanTimeReference
    activation_reference: EanActivationReference

    def validate(self) -> None:
        _require_id("headway candidate id", self.id)
        _require_id("headway candidate checkpoint_id", self.checkpoint_id)
        _require_nonnegative_int("headway candidate cabin_id", self.cabin_id)
        _require_nonnegative_int("headway candidate visit_index", self.visit_index)


@dataclass(frozen=True)
class HeadwayPair:
    id: str
    checkpoint_id: str
    first_candidate_id: str
    second_candidate_id: str
    headway_seconds: float

    def validate(self) -> None:
        _require_id("headway pair id", self.id)
        _require_id("headway pair checkpoint_id", self.checkpoint_id)
        _require_id("headway pair first_candidate_id", self.first_candidate_id)
        _require_id("headway pair second_candidate_id", self.second_candidate_id)
        if self.first_candidate_id == self.second_candidate_id:
            raise ValueError("headway pair candidate ids must differ")
        _require_positive("headway pair headway_seconds", self.headway_seconds)


@dataclass(frozen=True)
class Passenger:
    id: str
    origin_station_id: str
    destination_station_id: str
    release_time_seconds: float

    def validate(self) -> None:
        _require_id("passenger id", self.id)
        _require_id("passenger origin_station_id", self.origin_station_id)
        _require_id("passenger destination_station_id", self.destination_station_id)
        if self.origin_station_id == self.destination_station_id:
            raise ValueError("passenger origin and destination must differ")
        _require_nonnegative("passenger release_time_seconds", self.release_time_seconds)


@dataclass(frozen=True)
class RideCandidate:
    id: str
    passenger_id: str
    cabin_id: int
    board_visit_index: int
    alight_visit_index: int

    def validate(self) -> None:
        _require_id("ride candidate id", self.id)
        _require_id("ride candidate passenger_id", self.passenger_id)
        _require_nonnegative_int("ride candidate cabin_id", self.cabin_id)
        _require_nonnegative_int("ride candidate board_visit_index", self.board_visit_index)
        _require_nonnegative_int("ride candidate alight_visit_index", self.alight_visit_index)
        if self.board_visit_index >= self.alight_visit_index:
            raise ValueError("ride candidate board_visit_index must be before alight_visit_index")


def _require_id(label: str, value: str) -> None:
    if not value:
        raise ValueError(f"{label} must be nonempty")


def _require_positive(label: str, value: float) -> None:
    if value <= 0:
        raise ValueError(f"{label} must be positive")


def _require_nonnegative(label: str, value: float) -> None:
    if value < 0:
        raise ValueError(f"{label} must be nonnegative")


def _require_nonnegative_int(label: str, value: int) -> None:
    if value < 0:
        raise ValueError(f"{label} must be nonnegative")


def _require_unique(label: str, values: list[str]) -> None:
    seen = set()
    duplicates = set()
    for value in values:
        if value in seen:
            duplicates.add(value)
        seen.add(value)
    if duplicates:
        raise ValueError(f"duplicate {label} ids: {duplicates}")
