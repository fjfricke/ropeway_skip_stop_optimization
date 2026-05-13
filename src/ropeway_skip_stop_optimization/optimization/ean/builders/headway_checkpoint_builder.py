from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass

from ropeway_skip_stop_optimization.optimization.ean.models import (
    HeadwayCheckpointDefinition,
    HeadwayCheckpointKind,
    SkipStopTiming,
    StationEanConfig,
    StationWaitingMode,
)


class HeadwayCheckpointBuilder(ABC):
    @abstractmethod
    def build(
        self,
        timings: tuple[SkipStopTiming, ...],
        station_configs: tuple[StationEanConfig, ...],
    ) -> tuple[HeadwayCheckpointDefinition, ...]:
        """Build physical headway checkpoint definitions."""


@dataclass(frozen=True)
class SkipStopHeadwayCheckpointBuilder(HeadwayCheckpointBuilder):
    station_headway_seconds_by_station_id: dict[str, float]
    exit_switch_headway_seconds_by_switch_id: dict[str, float]

    def build(
        self,
        timings: tuple[SkipStopTiming, ...],
        station_configs: tuple[StationEanConfig, ...],
    ) -> tuple[HeadwayCheckpointDefinition, ...]:
        timings_by_switch_id = _timings_by_switch_id(timings)
        station_configs_by_id = _station_configs_by_id(station_configs)
        _validate_headway_seconds("station headway", self.station_headway_seconds_by_station_id)
        _validate_headway_seconds("exit switch headway", self.exit_switch_headway_seconds_by_switch_id)

        checkpoints: list[HeadwayCheckpointDefinition] = []
        for timing in timings_by_switch_id.values():
            if timing.station_id not in station_configs_by_id:
                raise ValueError(f"timing references station without EAN config: {timing.station_id!r}")
            if timing.station_id not in self.station_headway_seconds_by_station_id:
                raise ValueError(f"missing station headway for station_id: {timing.station_id!r}")
            if timing.switch_id not in self.exit_switch_headway_seconds_by_switch_id:
                raise ValueError(f"missing exit switch headway for switch_id: {timing.switch_id!r}")

            station_config = station_configs_by_id[timing.station_id]
            waiting_modes = (station_config.waiting_mode,)
            station_headway_seconds = self.station_headway_seconds_by_station_id[timing.station_id]
            exit_switch_headway_seconds = self.exit_switch_headway_seconds_by_switch_id[timing.switch_id]

            checkpoints.append(
                HeadwayCheckpointDefinition(
                    id=f"platform_entry::{timing.switch_id}",
                    kind=HeadwayCheckpointKind.PLATFORM_ENTRY,
                    switch_id=timing.switch_id,
                    station_id=timing.station_id,
                    headway_seconds=station_headway_seconds,
                    applies_to_serve=True,
                    applies_to_skip=False,
                    waiting_modes=waiting_modes,
                )
            )

            if station_config.waiting_mode in {
                StationWaitingMode.END_OF_PLATFORM_WAIT,
                StationWaitingMode.STATION_FIFO_BUFFER,
            }:
                checkpoints.append(
                    HeadwayCheckpointDefinition(
                        id=f"platform_exit::{timing.switch_id}",
                        kind=HeadwayCheckpointKind.PLATFORM_EXIT,
                        switch_id=timing.switch_id,
                        station_id=timing.station_id,
                        headway_seconds=station_headway_seconds,
                        applies_to_serve=True,
                        applies_to_skip=False,
                        waiting_modes=waiting_modes,
                    )
                )

            checkpoints.append(
                HeadwayCheckpointDefinition(
                    id=f"exit_switch::{timing.switch_id}",
                    kind=HeadwayCheckpointKind.EXIT_SWITCH,
                    switch_id=timing.switch_id,
                    station_id=timing.station_id,
                    headway_seconds=exit_switch_headway_seconds,
                    applies_to_serve=True,
                    applies_to_skip=timing.skip_allowed,
                    waiting_modes=waiting_modes,
                )
            )

        checkpoint_ids = [checkpoint.id for checkpoint in checkpoints]
        duplicate_checkpoint_ids = _duplicates(checkpoint_ids)
        if duplicate_checkpoint_ids:
            raise ValueError(f"duplicate headway checkpoint ids: {duplicate_checkpoint_ids}")
        for checkpoint in checkpoints:
            checkpoint.validate()
        return tuple(checkpoints)


def _timings_by_switch_id(timings: tuple[SkipStopTiming, ...]) -> dict[str, SkipStopTiming]:
    if not timings:
        raise ValueError("headway checkpoint builder needs at least one skip/stop timing")
    result: dict[str, SkipStopTiming] = {}
    duplicates = set()
    for timing in timings:
        timing.validate()
        if timing.switch_id in result:
            duplicates.add(timing.switch_id)
        result[timing.switch_id] = timing
    if duplicates:
        raise ValueError(f"duplicate skip/stop timing switch ids: {duplicates}")
    return result


def _station_configs_by_id(station_configs: tuple[StationEanConfig, ...]) -> dict[str, StationEanConfig]:
    if not station_configs:
        raise ValueError("headway checkpoint builder needs at least one station config")
    result: dict[str, StationEanConfig] = {}
    duplicates = set()
    for station_config in station_configs:
        station_config.validate()
        if station_config.station_id in result:
            duplicates.add(station_config.station_id)
        result[station_config.station_id] = station_config
    if duplicates:
        raise ValueError(f"duplicate station EAN config ids: {duplicates}")
    return result


def _validate_headway_seconds(label: str, values_by_id: dict[str, float]) -> None:
    if not values_by_id:
        raise ValueError(f"{label} map must not be empty")
    for item_id, seconds in values_by_id.items():
        if not item_id:
            raise ValueError(f"{label} ids must be nonempty")
        if seconds <= 0:
            raise ValueError(f"{label} seconds must be positive")


def _duplicates(values: list[str]) -> set[str]:
    seen = set()
    duplicates = set()
    for value in values:
        if value in seen:
            duplicates.add(value)
        seen.add(value)
    return duplicates
