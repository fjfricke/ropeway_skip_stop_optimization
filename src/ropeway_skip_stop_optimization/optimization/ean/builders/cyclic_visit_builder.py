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
from ropeway_skip_stop_optimization.optimization.ean.network import EanCirculationPattern


@dataclass(frozen=True)
class CyclicPatternVisitBuilder(SwitchVisitBuilder):
    """Build fixed visits for one deterministic circulation pattern."""

    pattern: EanCirculationPattern
    safety_visit_margin: int = 1
    selectable_initial_phase_count: int = 0

    def build(
        self,
        config: EanConfig,
        cabin_starts: tuple[EanCabinStart, ...],
        timings: tuple[SkipStopTiming, ...],
    ) -> SwitchVisitBuildResult:
        config.validate()
        self.pattern.validate()
        if self.safety_visit_margin < 0:
            raise ValueError("safety_visit_margin must be nonnegative")
        state_ids = self.pattern.state_ids
        if not 0 <= self.selectable_initial_phase_count <= len(state_ids):
            raise ValueError(
                "selectable_initial_phase_count must lie between zero and "
                "the circulation pattern length"
            )
        transitions = build_cyclic_switch_transitions(
            timings=timings,
            station_configs=config.station_configs,
            state_ids=state_ids,
        )
        transition_by_state_id = {
            transition.from_switch_id: transition for transition in transitions
        }
        state_index_by_id = {
            state_id: index for index, state_id in enumerate(state_ids)
        }
        cycle_min_seconds = sum(
            transition.min_seconds for transition in transitions
        )
        visits: list[SwitchVisitDefinition] = []
        seen_cabin_ids: set[int] = set()
        for start in cabin_starts:
            start.validate()
            if start.cabin_id in seen_cabin_ids:
                raise ValueError(f"duplicate cabin start id: {start.cabin_id}")
            seen_cabin_ids.add(start.cabin_id)
            if start.first_switch_id not in state_index_by_id:
                raise ValueError(
                    f"cabin start references state outside pattern: {start.first_switch_id!r}"
                )
            remaining_seconds = config.model_end_seconds - start.time_seconds
            if remaining_seconds < 0:
                raise ValueError(
                    f"cabin {start.cabin_id!r} starts after model_end_seconds"
                )
            start_index = state_index_by_id[start.first_switch_id]
            if self.selectable_initial_phase_count:
                visit_count = max(
                    phase_index
                    + _visit_count_for_horizon(
                        start_index=(start_index + phase_index) % len(state_ids),
                        remaining_seconds=remaining_seconds,
                        cycle_min_seconds=cycle_min_seconds,
                        state_ids=state_ids,
                        transition_by_state_id=transition_by_state_id,
                        safety_visit_margin=self.safety_visit_margin,
                    )
                    for phase_index in range(self.selectable_initial_phase_count)
                )
            else:
                visit_count = _visit_count_for_horizon(
                    start_index=start_index,
                    remaining_seconds=remaining_seconds,
                    cycle_min_seconds=cycle_min_seconds,
                    state_ids=state_ids,
                    transition_by_state_id=transition_by_state_id,
                    safety_visit_margin=self.safety_visit_margin,
                )
            visits.extend(
                SwitchVisitDefinition(
                    cabin_id=start.cabin_id,
                    visit_index=visit_index,
                    switch_id=state_ids[
                        (start_index + visit_index) % len(state_ids)
                    ],
                )
                for visit_index in range(visit_count)
            )
        result = SwitchVisitBuildResult(
            visits=tuple(visits),
            transitions=transitions,
        )
        result.validate()
        return result


def calculate_min_max_state_to_next_seconds(
    timing: SkipStopTiming,
    station_config: StationEanConfig,
) -> tuple[float, float]:
    timing.validate()
    station_config.validate()
    if timing.station_id != station_config.station_id:
        raise ValueError("timing and station config station ids must match")
    service_seconds = (
        timing.entry_to_platform_entry_seconds
        + timing.min_platform_entry_to_platform_exit_seconds
        + timing.platform_exit_to_exit_switch_seconds
    )
    minimum = (
        min(service_seconds, timing.skip_entry_to_exit_switch_seconds)
        if timing.skip_allowed
        else service_seconds
    )
    service_maximum = (
        service_seconds
        if station_config.waiting_mode is StationWaitingMode.NO_WAITING
        else math.inf
    )
    maximum = (
        max(service_maximum, timing.skip_entry_to_exit_switch_seconds)
        if timing.skip_allowed
        else service_maximum
    )
    return (
        minimum + timing.rope_to_next_switch_seconds,
        maximum + timing.rope_to_next_switch_seconds,
    )


def build_cyclic_switch_transitions(
    *,
    timings: tuple[SkipStopTiming, ...],
    station_configs: tuple[StationEanConfig, ...],
    state_ids: tuple[str, ...],
) -> tuple[SwitchTransition, ...]:
    timings_by_state_id = {timing.switch_id: timing for timing in timings}
    station_configs_by_id = {
        station.station_id: station for station in station_configs
    }
    if set(timings_by_state_id) != set(state_ids):
        raise ValueError("cyclic transition timings must exactly match pattern states")
    transitions: list[SwitchTransition] = []
    for index, state_id in enumerate(state_ids):
        timing = timings_by_state_id[state_id]
        station_config = station_configs_by_id.get(timing.station_id)
        if station_config is None:
            raise ValueError(
                f"timing references station without EAN config: {timing.station_id!r}"
            )
        minimum, maximum = calculate_min_max_state_to_next_seconds(
            timing,
            station_config,
        )
        transition = SwitchTransition(
            from_switch_id=state_id,
            to_switch_id=state_ids[(index + 1) % len(state_ids)],
            min_seconds=minimum,
            max_seconds=maximum,
        )
        transition.validate()
        transitions.append(transition)
    return tuple(transitions)


def count_visits_by_cabin(
    visits: tuple[SwitchVisitDefinition, ...],
) -> dict[int, int]:
    result: dict[int, int] = {}
    for visit in visits:
        result[visit.cabin_id] = result.get(visit.cabin_id, 0) + 1
    return result


def transition_by_from_switch_id(
    transitions: tuple[SwitchTransition, ...],
) -> dict[str, SwitchTransition]:
    result: dict[str, SwitchTransition] = {}
    duplicates: set[str] = set()
    for transition in transitions:
        transition.validate()
        if transition.from_switch_id in result:
            duplicates.add(transition.from_switch_id)
        result[transition.from_switch_id] = transition
    if duplicates:
        raise ValueError(
            f"duplicate transition from state ids: {sorted(duplicates)}"
        )
    return result


def _visit_count_for_horizon(
    *,
    start_index: int,
    remaining_seconds: float,
    cycle_min_seconds: float,
    state_ids: tuple[str, ...],
    transition_by_state_id: dict[str, SwitchTransition],
    safety_visit_margin: int,
) -> int:
    if cycle_min_seconds <= 0:
        raise ValueError("minimum circulation duration must be positive")
    full_rotations = math.floor(remaining_seconds / cycle_min_seconds)
    partial_remaining = remaining_seconds - full_rotations * cycle_min_seconds
    partial_visits = _count_partial_rotation_visits(
        start_index,
        partial_remaining,
        state_ids,
        transition_by_state_id,
    )
    return (
        full_rotations * len(state_ids)
        + partial_visits
        + safety_visit_margin
    )


def _count_partial_rotation_visits(
    start_index: int,
    partial_remaining: float,
    state_ids: tuple[str, ...],
    transition_by_state_id: dict[str, SwitchTransition],
) -> int:
    count = 0
    elapsed = 0.0
    while count < len(state_ids) and elapsed <= partial_remaining + 1e-9:
        state_id = state_ids[(start_index + count) % len(state_ids)]
        count += 1
        elapsed += transition_by_state_id[state_id].min_seconds
    return count
