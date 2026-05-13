from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass

from ropeway_skip_stop_optimization.models import Scenario
from ropeway_skip_stop_optimization.optimization.ean.models import SkipStopTiming


@dataclass(frozen=True)
class HeadwayDurations:
    station_headway_seconds_by_station_id: dict[str, float]
    exit_switch_headway_seconds_by_switch_id: dict[str, float]

    def validate(self) -> None:
        _validate_positive_seconds_by_id("station headway", self.station_headway_seconds_by_station_id)
        _validate_positive_seconds_by_id("exit switch headway", self.exit_switch_headway_seconds_by_switch_id)


class HeadwayDurationBuilder(ABC):
    @abstractmethod
    def build(
        self,
        scenario: Scenario,
        timings: tuple[SkipStopTiming, ...],
    ) -> HeadwayDurations:
        """Derive headway durations used to create EAN headway checkpoints."""


@dataclass(frozen=True)
class OperatingSpeedHeadwayDurationBuilder(HeadwayDurationBuilder):
    def build(
        self,
        scenario: Scenario,
        timings: tuple[SkipStopTiming, ...],
    ) -> HeadwayDurations:
        scenario.validate()
        _validate_timings(timings)

        required_spacing_m = scenario.operating.required_cabin_spacing_m
        station_headway_seconds = required_spacing_m / scenario.operating.station_speed_m_per_s
        exit_switch_headway_seconds = required_spacing_m / scenario.operating.rope_speed_m_per_s

        durations = HeadwayDurations(
            station_headway_seconds_by_station_id={
                timing.station_id: station_headway_seconds
                for timing in timings
            },
            exit_switch_headway_seconds_by_switch_id={
                timing.switch_id: exit_switch_headway_seconds
                for timing in timings
            },
        )
        durations.validate()
        return durations


def _validate_timings(timings: tuple[SkipStopTiming, ...]) -> None:
    if not timings:
        raise ValueError("headway duration builder needs at least one timing")
    seen_switch_ids: set[str] = set()
    duplicate_switch_ids: set[str] = set()
    for timing in timings:
        timing.validate()
        if timing.switch_id in seen_switch_ids:
            duplicate_switch_ids.add(timing.switch_id)
        seen_switch_ids.add(timing.switch_id)
    if duplicate_switch_ids:
        raise ValueError(f"duplicate timing switch ids: {duplicate_switch_ids}")


def _validate_positive_seconds_by_id(label: str, values_by_id: dict[str, float]) -> None:
    if not values_by_id:
        raise ValueError(f"{label} map must not be empty")
    for item_id, seconds in values_by_id.items():
        if not item_id:
            raise ValueError(f"{label} ids must be nonempty")
        if seconds <= 0:
            raise ValueError(f"{label} seconds must be positive")
