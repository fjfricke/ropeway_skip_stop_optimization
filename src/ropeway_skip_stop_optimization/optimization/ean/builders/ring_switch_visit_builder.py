from __future__ import annotations

import math
from dataclasses import dataclass

from ropeway_skip_stop_optimization.optimization.ean.builders.switch_visit_builder import (
    SwitchVisitBuilder,
)
from ropeway_skip_stop_optimization.optimization.ean.models import (
    EanCabinStart,
    EanConfig,
    SkipStopTiming,
    StationEanConfig,
    StationWaitingMode,
    SwitchTransition,
    SwitchVisitBuildResult,
    SwitchVisitDefinition,
)


@dataclass(frozen=True)
class RingSwitchVisitBuilder(SwitchVisitBuilder):
    """Build switch visits for a fixed directed ring of skip/stop switches.

    This v0 builder assumes a single immutable switch cycle. Each switch has
    exactly one next switch in switch_cycle, and the MILP only decides whether
    an active visit serves or skips the station. It does not model branch
    choices, alternate lines, or arbitrary directed switch graphs.

    The visit bound is computed from minimum switch-to-next-switch travel
    times, full minimum-time ring rotations, and a final partial rotation up to
    config.model_end_seconds.
    """

    switch_cycle: tuple[str, ...]
    safety_visit_margin: int = 1
    selectable_initial_phase_count: int = 0

    def build(
        self,
        config: EanConfig,
        cabin_starts: tuple[EanCabinStart, ...],
        timings: tuple[SkipStopTiming, ...],
    ) -> SwitchVisitBuildResult:
        config.validate()
        _validate_cabin_starts(cabin_starts)
        if self.safety_visit_margin < 0:
            raise ValueError("safety_visit_margin must be nonnegative")
        if not 0 <= self.selectable_initial_phase_count <= len(self.switch_cycle):
            raise ValueError(
                "selectable_initial_phase_count must lie between zero and the switch cycle length"
            )

        transitions = build_ring_switch_transitions(
            timings=timings,
            station_configs=config.station_configs,
            switch_cycle=self.switch_cycle,
        )
        transition_by_switch_id = transition_by_from_switch_id(transitions)

        visits: list[SwitchVisitDefinition] = []
        switch_index_by_id = {switch_id: index for index, switch_id in enumerate(self.switch_cycle)}
        cycle_min_seconds = sum(transition.min_seconds for transition in transitions)

        for start in cabin_starts:
            if start.first_switch_id not in switch_index_by_id:
                raise ValueError(f"cabin start references switch outside switch_cycle: {start.first_switch_id!r}")
            remaining_seconds = config.model_end_seconds - start.time_seconds
            if remaining_seconds < 0:
                raise ValueError(f"cabin {start.cabin_id!r} starts after model_end_seconds")

            start_index = switch_index_by_id[start.first_switch_id]
            if self.selectable_initial_phase_count:
                visit_count = max(
                    phase_index
                    + _visit_count_for_horizon(
                        start_index=(start_index + phase_index) % len(self.switch_cycle),
                        remaining_seconds=remaining_seconds,
                        cycle_min_seconds=cycle_min_seconds,
                        switch_cycle=self.switch_cycle,
                        transition_by_switch_id=transition_by_switch_id,
                        safety_visit_margin=self.safety_visit_margin,
                    )
                    for phase_index in range(self.selectable_initial_phase_count)
                )
            else:
                visit_count = _visit_count_for_horizon(
                    start_index=start_index,
                    remaining_seconds=remaining_seconds,
                    cycle_min_seconds=cycle_min_seconds,
                    switch_cycle=self.switch_cycle,
                    transition_by_switch_id=transition_by_switch_id,
                    safety_visit_margin=self.safety_visit_margin,
                )

            for visit_index in range(visit_count):
                switch_id = self.switch_cycle[(start_index + visit_index) % len(self.switch_cycle)]
                visits.append(
                    SwitchVisitDefinition(
                        cabin_id=start.cabin_id,
                        visit_index=visit_index,
                        switch_id=switch_id,
                    )
                )

        result = SwitchVisitBuildResult(visits=tuple(visits), transitions=transitions)
        result.validate()
        return result


def calculate_min_max_switch_to_next_seconds(
    timing: SkipStopTiming,
    station_config: StationEanConfig,
) -> tuple[float, float]:
    timing.validate()
    station_config.validate()
    if timing.station_id != station_config.station_id:
        raise ValueError("timing and station_config station ids must match")

    service_min_seconds = (
        timing.entry_to_platform_entry_seconds
        + timing.min_platform_entry_to_platform_exit_seconds
        + timing.platform_exit_to_exit_switch_seconds
    )
    if timing.skip_allowed:
        min_seconds = min(service_min_seconds, timing.skip_entry_to_exit_switch_seconds)
    else:
        min_seconds = service_min_seconds
    min_seconds += timing.rope_to_next_switch_seconds

    if station_config.waiting_mode is StationWaitingMode.NO_WAITING:
        service_max_seconds = service_min_seconds
    else:
        service_max_seconds = math.inf
    if timing.skip_allowed:
        max_seconds = max(service_max_seconds, timing.skip_entry_to_exit_switch_seconds)
    else:
        max_seconds = service_max_seconds
    max_seconds += timing.rope_to_next_switch_seconds

    return min_seconds, max_seconds


def build_ring_switch_transitions(
    timings: tuple[SkipStopTiming, ...],
    station_configs: tuple[StationEanConfig, ...],
    switch_cycle: tuple[str, ...],
) -> tuple[SwitchTransition, ...]:
    _validate_switch_cycle(switch_cycle)
    timings_by_switch_id = _timings_by_switch_id(timings)
    station_configs_by_id = _station_configs_by_id(station_configs)

    transitions: list[SwitchTransition] = []
    for index, from_switch_id in enumerate(switch_cycle):
        if from_switch_id not in timings_by_switch_id:
            raise ValueError(f"switch_cycle references unknown timing switch_id: {from_switch_id!r}")
        timing = timings_by_switch_id[from_switch_id]
        if timing.station_id not in station_configs_by_id:
            raise ValueError(f"timing references station without EAN config: {timing.station_id!r}")
        to_switch_id = switch_cycle[(index + 1) % len(switch_cycle)]
        min_seconds, max_seconds = calculate_min_max_switch_to_next_seconds(
            timing=timing,
            station_config=station_configs_by_id[timing.station_id],
        )
        transition = SwitchTransition(
            from_switch_id=from_switch_id,
            to_switch_id=to_switch_id,
            min_seconds=min_seconds,
            max_seconds=max_seconds,
        )
        transition.validate()
        transitions.append(transition)

    return tuple(transitions)


def count_visits_by_cabin(visits: tuple[SwitchVisitDefinition, ...]) -> dict[int, int]:
    counts: dict[int, int] = {}
    for visit in visits:
        counts[visit.cabin_id] = counts.get(visit.cabin_id, 0) + 1
    return counts


def transition_by_from_switch_id(transitions: tuple[SwitchTransition, ...]) -> dict[str, SwitchTransition]:
    result: dict[str, SwitchTransition] = {}
    duplicates = set()
    for transition in transitions:
        transition.validate()
        if transition.from_switch_id in result:
            duplicates.add(transition.from_switch_id)
        result[transition.from_switch_id] = transition
    if duplicates:
        raise ValueError(f"duplicate switch transition from_switch_id values: {duplicates}")
    return result


def _count_partial_rotation_visits(
    start_index: int,
    partial_remaining: float,
    switch_cycle: tuple[str, ...],
    transition_by_switch_id: dict[str, SwitchTransition],
) -> int:
    count = 0
    elapsed = 0.0
    tolerance = 1e-9
    while count < len(switch_cycle) and elapsed <= partial_remaining + tolerance:
        current_switch_id = switch_cycle[(start_index + count) % len(switch_cycle)]
        count += 1
        elapsed += transition_by_switch_id[current_switch_id].min_seconds
    return count


def _visit_count_for_horizon(
    *,
    start_index: int,
    remaining_seconds: float,
    cycle_min_seconds: float,
    switch_cycle: tuple[str, ...],
    transition_by_switch_id: dict[str, SwitchTransition],
    safety_visit_margin: int,
) -> int:
    full_rotations = math.floor(remaining_seconds / cycle_min_seconds)
    partial_remaining = remaining_seconds - full_rotations * cycle_min_seconds
    partial_visits = _count_partial_rotation_visits(
        start_index=start_index,
        partial_remaining=partial_remaining,
        switch_cycle=switch_cycle,
        transition_by_switch_id=transition_by_switch_id,
    )
    return (
        full_rotations * len(switch_cycle)
        + partial_visits
        + safety_visit_margin
    )


def _validate_cabin_starts(cabin_starts: tuple[EanCabinStart, ...]) -> None:
    if not cabin_starts:
        raise ValueError("ring switch visit builder needs at least one cabin start")
    cabin_ids = [start.cabin_id for start in cabin_starts]
    duplicate_cabin_ids = _duplicates(cabin_ids)
    if duplicate_cabin_ids:
        raise ValueError(f"duplicate cabin start ids: {duplicate_cabin_ids}")
    for start in cabin_starts:
        start.validate()


def _validate_switch_cycle(switch_cycle: tuple[str, ...]) -> None:
    if not switch_cycle:
        raise ValueError("switch_cycle must not be empty")
    duplicate_switch_ids = _duplicates(switch_cycle)
    if duplicate_switch_ids:
        raise ValueError(f"duplicate switch_cycle ids: {duplicate_switch_ids}")
    for switch_id in switch_cycle:
        if not switch_id:
            raise ValueError("switch_cycle ids must be nonempty")


def _timings_by_switch_id(timings: tuple[SkipStopTiming, ...]) -> dict[str, SkipStopTiming]:
    if not timings:
        raise ValueError("ring switch visit builder needs at least one skip/stop timing")
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


def _duplicates(values: tuple[str, ...] | list[int]) -> set:
    seen = set()
    duplicates = set()
    for value in values:
        if value in seen:
            duplicates.add(value)
        seen.add(value)
    return duplicates
