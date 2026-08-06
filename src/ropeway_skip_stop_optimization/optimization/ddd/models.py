from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
import math

from ropeway_skip_stop_optimization.optimization.ddd.time_ticks import (
    DddTimeTick,
    ddd_quantize_time_seconds,
    ddd_seconds_to_tick,
)


class DddRouteDecision(StrEnum):
    STOP = "stop"
    SKIP = "skip"


@dataclass(frozen=True)
class DddMovementState:
    id: str

    def validate(self) -> None:
        _require_id("DDD movement state id", self.id)


@dataclass(frozen=True)
class DddFixedStart:
    cabin_id: int
    state_id: str
    time_seconds: float
    max_visit_count: int

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "time_seconds",
            ddd_quantize_time_seconds(self.time_seconds),
        )

    @property
    def time_tick(self) -> DddTimeTick:
        return ddd_seconds_to_tick(self.time_seconds)

    def validate(self) -> None:
        _require_nonnegative_int("DDD fixed start cabin_id", self.cabin_id)
        _require_id("DDD fixed start state_id", self.state_id)
        _require_finite_nonnegative("DDD fixed start time_seconds", self.time_seconds)
        if self.max_visit_count <= 0:
            raise ValueError("DDD fixed start max_visit_count must be positive")


@dataclass(frozen=True)
class DddResource:
    id: str
    headway_seconds: float

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "headway_seconds",
            ddd_quantize_time_seconds(self.headway_seconds),
        )

    @property
    def headway_tick(self) -> DddTimeTick:
        return ddd_seconds_to_tick(self.headway_seconds)

    def validate(self) -> None:
        _require_id("DDD resource id", self.id)
        _require_finite_positive("DDD resource headway_seconds", self.headway_seconds)
        if self.headway_tick <= 0:
            raise ValueError("DDD resource headway must occupy at least one time tick")


@dataclass(frozen=True)
class DddResourceUsage:
    resource_id: str
    leader_clear_offset_seconds: float
    follower_enter_offset_seconds: float

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "leader_clear_offset_seconds",
            ddd_quantize_time_seconds(self.leader_clear_offset_seconds),
        )
        object.__setattr__(
            self,
            "follower_enter_offset_seconds",
            ddd_quantize_time_seconds(self.follower_enter_offset_seconds),
        )

    @property
    def leader_clear_offset_tick(self) -> DddTimeTick:
        return ddd_seconds_to_tick(self.leader_clear_offset_seconds)

    @property
    def follower_enter_offset_tick(self) -> DddTimeTick:
        return ddd_seconds_to_tick(self.follower_enter_offset_seconds)

    def validate(self) -> None:
        _require_id("DDD resource usage resource_id", self.resource_id)
        _require_finite_nonnegative(
            "DDD resource usage leader_clear_offset_seconds",
            self.leader_clear_offset_seconds,
        )
        _require_finite_nonnegative(
            "DDD resource usage follower_enter_offset_seconds",
            self.follower_enter_offset_seconds,
        )


@dataclass(frozen=True)
class DddRouteOption:
    id: str
    from_state_id: str
    to_state_id: str
    station_id: str
    decision: DddRouteDecision
    duration_seconds: float
    platform_entry_offset_seconds: float | None
    platform_exit_offset_seconds: float | None
    exit_switch_offset_seconds: float
    resource_usages: tuple[DddResourceUsage, ...]

    def __post_init__(self) -> None:
        for name in (
            "duration_seconds",
            "platform_entry_offset_seconds",
            "platform_exit_offset_seconds",
            "exit_switch_offset_seconds",
        ):
            value = getattr(self, name)
            if value is not None:
                object.__setattr__(
                    self,
                    name,
                    ddd_quantize_time_seconds(value),
                )

    @property
    def duration_tick(self) -> DddTimeTick:
        return ddd_seconds_to_tick(self.duration_seconds)

    @property
    def exit_switch_offset_tick(self) -> DddTimeTick:
        return ddd_seconds_to_tick(self.exit_switch_offset_seconds)

    def validate(self) -> None:
        for label, value in (
            ("DDD route option id", self.id),
            ("DDD route option from_state_id", self.from_state_id),
            ("DDD route option to_state_id", self.to_state_id),
            ("DDD route option station_id", self.station_id),
        ):
            _require_id(label, value)
        if not isinstance(self.decision, DddRouteDecision):
            raise ValueError("DDD route option needs a valid decision")
        _require_finite_positive("DDD route option duration_seconds", self.duration_seconds)
        _require_finite_nonnegative(
            "DDD route option exit_switch_offset_seconds",
            self.exit_switch_offset_seconds,
        )
        if self.duration_tick <= 0:
            raise ValueError("DDD route duration must occupy at least one time tick")
        if self.exit_switch_offset_tick > self.duration_tick:
            raise ValueError("DDD route option exit switch must not follow its arrival")
        if self.decision is DddRouteDecision.STOP:
            if (
                self.platform_entry_offset_seconds is None
                or self.platform_exit_offset_seconds is None
            ):
                raise ValueError("DDD STOP route needs platform offsets")
            _require_finite_nonnegative(
                "DDD route option platform_entry_offset_seconds",
                self.platform_entry_offset_seconds,
            )
            _require_finite_nonnegative(
                "DDD route option platform_exit_offset_seconds",
                self.platform_exit_offset_seconds,
            )
            if not (
                self.platform_entry_offset_seconds
                <= self.platform_exit_offset_seconds
                <= self.exit_switch_offset_seconds
            ):
                raise ValueError("DDD STOP route offsets must be monotone")
        elif (
            self.platform_entry_offset_seconds is not None
            or self.platform_exit_offset_seconds is not None
        ):
            raise ValueError("DDD SKIP route must not define platform offsets")
        for usage in self.resource_usages:
            usage.validate()
            if max(
                usage.leader_clear_offset_seconds,
                usage.follower_enter_offset_seconds,
            ) > self.duration_seconds:
                raise ValueError("DDD resource usage must lie within its route")


@dataclass(frozen=True)
class DddMovementProblem:
    scenario_id: str
    passenger_service_end_seconds: float
    operational_end_seconds: float
    states: tuple[DddMovementState, ...]
    starts: tuple[DddFixedStart, ...]
    route_options: tuple[DddRouteOption, ...]
    resources: tuple[DddResource, ...]

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "passenger_service_end_seconds",
            ddd_quantize_time_seconds(self.passenger_service_end_seconds),
        )
        object.__setattr__(
            self,
            "operational_end_seconds",
            ddd_quantize_time_seconds(self.operational_end_seconds),
        )

    @property
    def passenger_service_end_tick(self) -> DddTimeTick:
        return ddd_seconds_to_tick(self.passenger_service_end_seconds)

    @property
    def operational_end_tick(self) -> DddTimeTick:
        return ddd_seconds_to_tick(self.operational_end_seconds)

    def validate(self) -> None:
        _require_id("DDD movement problem scenario_id", self.scenario_id)
        _require_finite_positive(
            "DDD passenger_service_end_seconds",
            self.passenger_service_end_seconds,
        )
        _require_finite_positive(
            "DDD operational_end_seconds",
            self.operational_end_seconds,
        )
        if self.passenger_service_end_tick <= 0 or self.operational_end_tick <= 0:
            raise ValueError("DDD horizons must occupy at least one time tick")
        if self.operational_end_tick < self.passenger_service_end_tick:
            raise ValueError("DDD operational horizon must include passenger service")
        if not self.states or not self.starts or not self.route_options:
            raise ValueError("DDD movement problem needs states, starts, and route options")

        state_ids = _validate_unique_ids("DDD movement state", self.states)
        resource_ids = _validate_unique_ids("DDD resource", self.resources)
        option_ids = _validate_unique_ids("DDD route option", self.route_options)
        if not option_ids:
            raise ValueError("DDD movement problem needs route options")
        cabin_ids: set[int] = set()
        for state in self.states:
            state.validate()
        for resource in self.resources:
            resource.validate()
        for start in self.starts:
            start.validate()
            if start.cabin_id in cabin_ids:
                raise ValueError(f"duplicate DDD cabin start id: {start.cabin_id}")
            cabin_ids.add(start.cabin_id)
            if start.state_id not in state_ids:
                raise ValueError("DDD fixed start references an unknown state")
            if start.time_tick > self.operational_end_tick:
                raise ValueError("DDD fixed start lies after the operational horizon")
        outgoing_state_ids: set[str] = set()
        for option in self.route_options:
            option.validate()
            if option.from_state_id not in state_ids or option.to_state_id not in state_ids:
                raise ValueError("DDD route option references an unknown state")
            unknown_resources = {
                usage.resource_id for usage in option.resource_usages
            } - resource_ids
            if unknown_resources:
                raise ValueError(
                    f"DDD route option references unknown resources: {unknown_resources}"
                )
            outgoing_state_ids.add(option.from_state_id)
        reachable_start_states = {start.state_id for start in self.starts}
        if reachable_start_states - outgoing_state_ids:
            raise ValueError("DDD fixed start state has no outgoing route option")

    @property
    def route_options_by_state_id(self) -> dict[str, tuple[DddRouteOption, ...]]:
        grouped: dict[str, list[DddRouteOption]] = {}
        for option in self.route_options:
            grouped.setdefault(option.from_state_id, []).append(option)
        return {
            state_id: tuple(sorted(options, key=lambda option: option.id))
            for state_id, options in grouped.items()
        }

    @property
    def resources_by_id(self) -> dict[str, DddResource]:
        return {resource.id: resource for resource in self.resources}


def _validate_unique_ids(label: str, values: tuple[object, ...]) -> set[str]:
    ids = [getattr(value, "id") for value in values]
    if len(ids) != len(set(ids)):
        raise ValueError(f"duplicate {label} ids")
    return set(ids)


def _require_id(label: str, value: str) -> None:
    if not value.strip():
        raise ValueError(f"{label} must be nonempty")


def _require_nonnegative_int(label: str, value: int) -> None:
    if value < 0:
        raise ValueError(f"{label} must be nonnegative")


def _require_finite_nonnegative(label: str, value: float) -> None:
    if not math.isfinite(value) or value < 0:
        raise ValueError(f"{label} must be finite and nonnegative")


def _require_finite_positive(label: str, value: float) -> None:
    if not math.isfinite(value) or value <= 0:
        raise ValueError(f"{label} must be finite and positive")
