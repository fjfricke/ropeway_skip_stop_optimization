from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

from ropeway_skip_stop_optimization.optimization.ean.formulation_config import (
    EanHorizonFormulation,
)


class EanRouteDecision(Enum):
    STOP = "stop"
    SKIP = "skip"


@dataclass(frozen=True)
class EanCabinVisit:
    cabin_id: int
    visit_index: int
    switch_id: str
    station_id: str
    decision: EanRouteDecision
    switch_time_seconds: float
    platform_entry_time_seconds: float | None
    platform_exit_time_seconds: float | None
    exit_switch_time_seconds: float
    next_switch_time_seconds: float
    wait_seconds: float

    def validate(self) -> None:
        _require_nonnegative_int("EAN cabin visit cabin_id", self.cabin_id)
        _require_nonnegative_int("EAN cabin visit visit_index", self.visit_index)
        _require_id("EAN cabin visit switch_id", self.switch_id)
        _require_id("EAN cabin visit station_id", self.station_id)
        _require_nonnegative("EAN cabin visit switch_time_seconds", self.switch_time_seconds)
        _require_nonnegative("EAN cabin visit exit_switch_time_seconds", self.exit_switch_time_seconds)
        _require_nonnegative("EAN cabin visit next_switch_time_seconds", self.next_switch_time_seconds)
        _require_nonnegative("EAN cabin visit wait_seconds", self.wait_seconds)

        if self.decision is EanRouteDecision.STOP:
            if self.platform_entry_time_seconds is None or self.platform_exit_time_seconds is None:
                raise ValueError("STOP visits need platform entry and exit times")
            _require_nonnegative("EAN cabin visit platform_entry_time_seconds", self.platform_entry_time_seconds)
            _require_nonnegative("EAN cabin visit platform_exit_time_seconds", self.platform_exit_time_seconds)
            if not (
                self.switch_time_seconds
                <= self.platform_entry_time_seconds
                <= self.platform_exit_time_seconds
                <= self.exit_switch_time_seconds
                <= self.next_switch_time_seconds
            ):
                raise ValueError("STOP visit times must be monotonic")
            return

        if self.decision is EanRouteDecision.SKIP:
            if self.platform_entry_time_seconds is not None or self.platform_exit_time_seconds is not None:
                raise ValueError("SKIP visits must not set platform times")
            if self.wait_seconds != 0:
                raise ValueError("SKIP visits must not wait")
            if not self.switch_time_seconds <= self.exit_switch_time_seconds <= self.next_switch_time_seconds:
                raise ValueError("SKIP visit times must be monotonic")
            return

        raise ValueError(f"unsupported EAN route decision: {self.decision}")


@dataclass(frozen=True)
class EanCabinTrajectory:
    cabin_id: int
    visits: tuple[EanCabinVisit, ...]

    def validate(self) -> None:
        _require_nonnegative_int("EAN cabin trajectory cabin_id", self.cabin_id)

        expected_visit_indices = tuple(range(len(self.visits)))
        actual_visit_indices = tuple(visit.visit_index for visit in self.visits)
        if actual_visit_indices != expected_visit_indices:
            raise ValueError("EAN cabin trajectory visits must be contiguous and ordered from visit_index 0")

        previous_visit: EanCabinVisit | None = None
        for visit in self.visits:
            visit.validate()
            if visit.cabin_id != self.cabin_id:
                raise ValueError("EAN cabin trajectory contains a visit for another cabin")
            if previous_visit is not None and previous_visit.next_switch_time_seconds > visit.switch_time_seconds:
                raise ValueError("EAN cabin trajectory visit times must be monotonic")
            previous_visit = visit


@dataclass(frozen=True)
class EanMovementPlan:
    """Extracted EAN movement prefix and its finite-horizon interpretation."""

    scenario_id: str
    horizon_seconds: float
    model_end_seconds: float
    trajectories: tuple[EanCabinTrajectory, ...]
    horizon_formulation: EanHorizonFormulation = EanHorizonFormulation.LEGACY

    def validate(self) -> None:
        _require_id("EAN movement plan scenario_id", self.scenario_id)
        _require_positive("EAN movement plan horizon_seconds", self.horizon_seconds)
        _require_positive("EAN movement plan model_end_seconds", self.model_end_seconds)
        if self.model_end_seconds < self.horizon_seconds:
            raise ValueError("EAN movement plan model_end_seconds must be at least horizon_seconds")
        if not self.trajectories:
            raise ValueError("EAN movement plan needs at least one trajectory")

        cabin_ids: list[int] = []
        for trajectory in self.trajectories:
            trajectory.validate()
            if (
                not trajectory.visits
                and self.horizon_formulation
                is not EanHorizonFormulation.EXACT_TIME_ACTIVATION
            ):
                raise ValueError(
                    "empty EAN cabin trajectories require exact horizon activation"
                )
            cabin_ids.append(trajectory.cabin_id)

        duplicate_cabin_ids = _duplicates(cabin_ids)
        if duplicate_cabin_ids:
            raise ValueError(f"EAN movement plan has duplicate cabin trajectories: {duplicate_cabin_ids}")


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


def _duplicates(values: list[int]) -> set[int]:
    seen = set()
    duplicates = set()
    for value in values:
        if value in seen:
            duplicates.add(value)
        seen.add(value)
    return duplicates
