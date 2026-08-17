from __future__ import annotations

from dataclasses import dataclass
from enum import Enum, StrEnum


class StationWaitingMode(Enum):
    NO_WAITING = "no_waiting"
    END_OF_PLATFORM_WAIT = "end_of_platform_wait"
    STATION_FIFO_BUFFER = "station_fifo_buffer"


class EanCabinStartKind(Enum):
    FIXED = "fixed"
    EARLIEST = "earliest"


class EanFleetMode(StrEnum):
    FIXED_STARTS = "fixed_starts"
    OPTIMIZED_INITIAL_PLACEMENT = "optimized_initial_placement"


class EanFleetCardinalityMode(StrEnum):
    """Whether optimized initial placement may deactivate candidate cabins."""

    UP_TO_AVAILABLE = "up_to_available"
    EXACT = "exact"


class EanHeadwayPairScope(StrEnum):
    """Whether an artifact contains every candidate pair or only a subset."""

    COMPLETE = "complete"
    SPARSE = "sparse"


@dataclass(frozen=True)
class EanFleetConfig:
    mode: EanFleetMode = EanFleetMode.FIXED_STARTS
    available_fleet_count: int | None = None
    cardinality_mode: EanFleetCardinalityMode = (
        EanFleetCardinalityMode.UP_TO_AVAILABLE
    )

    def validate(self) -> None:
        if self.available_fleet_count is not None and self.available_fleet_count <= 0:
            raise ValueError("available_fleet_count must be positive when set")
        if self.mode is EanFleetMode.FIXED_STARTS:
            if self.available_fleet_count is not None:
                raise ValueError("fixed-start fleet config must not define a fleet limit")
            if self.cardinality_mode is not EanFleetCardinalityMode.UP_TO_AVAILABLE:
                raise ValueError("fixed-start fleet config must use up_to_available cardinality")
            return
        if self.mode is not EanFleetMode.OPTIMIZED_INITIAL_PLACEMENT:
            raise ValueError(f"unsupported EAN fleet mode: {self.mode}")
        if self.available_fleet_count is None:
            raise ValueError("optimized initial placement requires available_fleet_count")


class HeadwayCheckpointKind(Enum):
    PLATFORM_ENTRY = "platform_entry"
    PLATFORM_EXIT = "platform_exit"
    EXIT_SWITCH = "exit_switch"
    SERVICE_MECHANISM = "service_mechanism"


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
    skip_allowed: bool = True
    exit_switch_id: str | None = None

    def validate(self) -> None:
        _require_id("skip/stop timing switch_id", self.switch_id)
        _require_id("skip/stop timing station_id", self.station_id)
        if self.exit_switch_id is not None:
            _require_id("skip/stop timing exit_switch_id", self.exit_switch_id)
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
    """EAN station behavior.

    `max_wait_seconds` is a physical per-visit limit for
    `END_OF_PLATFORM_WAIT`. When it is omitted, finite-horizon formulations may
    use the operational horizon as a conservative terminal waiting cap. It is
    not used by the legacy time-bound formulation.
    """

    station_id: str
    waiting_mode: StationWaitingMode
    fifo_capacity: int | None = None
    max_wait_seconds: float | None = None

    def validate(self) -> None:
        _require_id("station EAN config station_id", self.station_id)
        if self.waiting_mode is StationWaitingMode.STATION_FIFO_BUFFER:
            if self.fifo_capacity is None or self.fifo_capacity <= 0:
                raise ValueError("STATION_FIFO_BUFFER stations need a positive fifo_capacity")
            if self.max_wait_seconds is not None:
                raise ValueError("max_wait_seconds is only valid for END_OF_PLATFORM_WAIT stations")
            return

        if self.fifo_capacity is not None:
            raise ValueError("fifo_capacity is only valid for STATION_FIFO_BUFFER stations")
        if self.waiting_mode is StationWaitingMode.NO_WAITING:
            if self.max_wait_seconds is not None:
                raise ValueError("max_wait_seconds is only valid for END_OF_PLATFORM_WAIT stations")
            return
        if self.max_wait_seconds is not None:
            _require_positive("station EAN config max_wait_seconds", self.max_wait_seconds)


@dataclass(frozen=True)
class EanConfig:
    """Physical and finite-horizon EAN configuration.

    `horizon_seconds` is the passenger service cutoff `T`. `tail_seconds`
    extends physical operation without allowing later passenger service. The
    resulting `model_end_seconds` is the operational certification horizon `H`.
    """

    horizon_seconds: float
    tail_seconds: float
    cabin_capacity: int
    station_configs: tuple[StationEanConfig, ...]

    @property
    def model_end_seconds(self) -> float:
        return self.horizon_seconds + self.tail_seconds

    @property
    def passenger_service_end_seconds(self) -> float:
        """Passenger boarding and alighting cutoff `T`."""
        return self.horizon_seconds

    @property
    def operational_end_seconds(self) -> float:
        """Finite physical-operation certification horizon `H`."""
        return self.model_end_seconds

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
    headway_rule_id: str | None = None

    def validate(self) -> None:
        _require_id("headway checkpoint id", self.id)
        _require_id("headway checkpoint switch_id", self.switch_id)
        _require_id("headway checkpoint station_id", self.station_id)
        _require_positive("headway checkpoint headway_seconds", self.headway_seconds)
        if self.headway_rule_id is not None:
            _require_id("headway checkpoint headway_rule_id", self.headway_rule_id)
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


@dataclass(frozen=True)
class EanDemandGroup:
    id: str
    origin_station_id: str
    destination_station_id: str
    release_time_seconds: float
    count: int

    def validate(self) -> None:
        _require_id("EAN demand group id", self.id)
        _require_id("EAN demand group origin_station_id", self.origin_station_id)
        _require_id("EAN demand group destination_station_id", self.destination_station_id)
        if self.origin_station_id == self.destination_station_id:
            raise ValueError("EAN demand group origin and destination must differ")
        _require_nonnegative("EAN demand group release_time_seconds", self.release_time_seconds)
        if self.count <= 0:
            raise ValueError("EAN demand group count must be positive")


@dataclass(frozen=True)
class EanRideCandidate:
    id: str
    demand_group_id: str
    cabin_id: int
    board_visit_index: int
    alight_visit_index: int

    def validate(self) -> None:
        _require_id("EAN ride candidate id", self.id)
        _require_id("EAN ride candidate demand_group_id", self.demand_group_id)
        _require_nonnegative_int("EAN ride candidate cabin_id", self.cabin_id)
        _require_nonnegative_int("EAN ride candidate board_visit_index", self.board_visit_index)
        _require_nonnegative_int("EAN ride candidate alight_visit_index", self.alight_visit_index)
        if self.board_visit_index >= self.alight_visit_index:
            raise ValueError("EAN ride candidate board_visit_index must be before alight_visit_index")


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
