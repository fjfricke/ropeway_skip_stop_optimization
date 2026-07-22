from __future__ import annotations

from dataclasses import dataclass

from ropeway_skip_stop_optimization.optimization.ean.artifact import EanBuildArtifact
from ropeway_skip_stop_optimization.optimization.ean.formulation_config import (
    HORIZON_ACTIVATION_EPSILON_SECONDS,
    EanTimeBoundFormulation,
)
from ropeway_skip_stop_optimization.optimization.ean.models import (
    EanCabinStartKind,
    EanFleetMode,
    SkipStopTiming,
    StationEanConfig,
    StationWaitingMode,
    SwitchVisitDefinition,
)


@dataclass(frozen=True)
class EanVisitTimeBounds:
    switch_lower: float
    switch_upper: float
    exit_lower: float
    exit_upper: float
    wait_upper: float


@dataclass(frozen=True)
class EanModelTimeBounds:
    by_visit: dict[tuple[int, int], EanVisitTimeBounds]
    global_upper: float


def build_ean_model_time_bounds(
    artifact: EanBuildArtifact,
    formulation: EanTimeBoundFormulation,
) -> EanModelTimeBounds:
    """Build the selected historical or visit-specific finite time domain."""
    if formulation is EanTimeBoundFormulation.LEGACY_PLUS_10:
        return _legacy_time_bounds(artifact)
    if formulation is EanTimeBoundFormulation.DERIVED_VISIT_BOUNDS:
        return _derived_time_bounds(artifact)
    if formulation is EanTimeBoundFormulation.INITIAL_PLACEMENT_SAFE:
        return _initial_placement_time_bounds(artifact)
    raise ValueError(f"unsupported EAN time-bound formulation: {formulation}")


def station_wait_upper_bound(
    station_config: StationEanConfig,
    operational_end_seconds: float,
) -> float:
    """Return a finite per-visit wait bound.

    An explicit station limit is preferred. Without one, allowing one complete
    operational horizon of waiting is sufficient to represent a cabin held
    through the finite boundary, while avoiding the historical implicit
    ten-second cumulative cap.
    """

    if station_config.waiting_mode is StationWaitingMode.NO_WAITING:
        return 0.0
    if station_config.waiting_mode is StationWaitingMode.END_OF_PLATFORM_WAIT:
        return (
            station_config.max_wait_seconds
            if station_config.max_wait_seconds is not None
            else operational_end_seconds
        )
    raise NotImplementedError(
        f"unsupported EAN time-bound waiting mode: {station_config.waiting_mode.value}"
    )


def _legacy_time_bounds(artifact: EanBuildArtifact) -> EanModelTimeBounds:
    global_upper = _legacy_time_upper_bound(artifact)
    by_visit = {
        (visit.cabin_id, visit.visit_index): EanVisitTimeBounds(
            switch_lower=0.0,
            switch_upper=global_upper,
            exit_lower=0.0,
            exit_upper=global_upper,
            wait_upper=global_upper,
        )
        for visit in artifact.switch_visits
    }
    return EanModelTimeBounds(by_visit=by_visit, global_upper=global_upper)


def _derived_time_bounds(artifact: EanBuildArtifact) -> EanModelTimeBounds:
    """Propagate conservative visit bounds along each fixed cabin sequence.

    Lower bounds use the faster feasible stop/skip transition. Upper bounds use
    the slower route plus the station wait cap. A fixed start remains fixed; an
    earliest start receives enough post-horizon domain to represent a cabin
    that never enters the active exact-horizon visit prefix.
    """
    starts_by_cabin_id = {start.cabin_id: start for start in artifact.cabin_starts}
    timings_by_switch_id = {timing.switch_id: timing for timing in artifact.timings}
    station_config_by_id = {
        station_config.station_id: station_config
        for station_config in artifact.config.station_configs
    }
    visits_by_cabin_id = _visits_by_cabin_id(artifact.switch_visits)
    by_visit: dict[tuple[int, int], EanVisitTimeBounds] = {}
    global_upper = artifact.config.operational_end_seconds

    for cabin_id, visits in visits_by_cabin_id.items():
        start = starts_by_cabin_id[cabin_id]
        switch_lower = start.time_seconds
        switch_upper = (
            start.time_seconds
            if start.kind is EanCabinStartKind.FIXED
            else max(
                artifact.config.operational_end_seconds
                + HORIZON_ACTIVATION_EPSILON_SECONDS,
                start.time_seconds + artifact.config.operational_end_seconds,
            )
        )
        for visit in visits:
            timing = timings_by_switch_id[visit.switch_id]
            station_config = station_config_by_id[timing.station_id]
            wait_upper = station_wait_upper_bound(
                station_config,
                artifact.config.operational_end_seconds,
            )
            exit_increment_lower = _minimum_entry_to_exit_seconds(timing)
            exit_increment_upper = _maximum_entry_to_exit_seconds(timing, wait_upper)
            bounds = EanVisitTimeBounds(
                switch_lower=switch_lower,
                switch_upper=switch_upper,
                exit_lower=switch_lower + exit_increment_lower,
                exit_upper=switch_upper + exit_increment_upper,
                wait_upper=wait_upper,
            )
            key = (visit.cabin_id, visit.visit_index)
            by_visit[key] = bounds
            global_upper = max(global_upper, bounds.exit_upper)
            switch_lower = bounds.exit_lower + timing.rope_to_next_switch_seconds
            switch_upper = bounds.exit_upper + timing.rope_to_next_switch_seconds
            global_upper = max(global_upper, switch_upper)

    return EanModelTimeBounds(by_visit=by_visit, global_upper=global_upper)


def _initial_placement_time_bounds(
    artifact: EanBuildArtifact,
) -> EanModelTimeBounds:
    """Build conservative finite bounds for selectable initial ring phases."""
    if artifact.fleet_mode is not EanFleetMode.OPTIMIZED_INITIAL_PLACEMENT:
        raise ValueError(
            "time_bounds_initial_placement_safe requires optimized_initial_placement"
        )
    if artifact.initial_placement_parameters is None:
        raise ValueError("initial placement time bounds need fleet parameters")

    timings_by_switch_id = {timing.switch_id: timing for timing in artifact.timings}
    station_config_by_id = {
        station_config.station_id: station_config
        for station_config in artifact.config.station_configs
    }
    visits_by_cabin_id = _visits_by_cabin_id(artifact.switch_visits)
    by_visit: dict[tuple[int, int], EanVisitTimeBounds] = {}
    maximum_chain_seconds = max(
        sum(
            _maximum_entry_to_exit_seconds(
                timings_by_switch_id[visit.switch_id],
                station_wait_upper_bound(
                    station_config_by_id[
                        timings_by_switch_id[visit.switch_id].station_id
                    ],
                    artifact.config.operational_end_seconds,
                ),
            )
            + timings_by_switch_id[visit.switch_id].rope_to_next_switch_seconds
            for visit in visits
        )
        for visits in visits_by_cabin_id.values()
    )
    switch_upper = (
        artifact.config.operational_end_seconds
        + HORIZON_ACTIVATION_EPSILON_SECONDS
        + maximum_chain_seconds
    )
    global_upper = switch_upper

    for visits in visits_by_cabin_id.values():
        for visit in visits:
            timing = timings_by_switch_id[visit.switch_id]
            station_config = station_config_by_id[timing.station_id]
            wait_upper = station_wait_upper_bound(
                station_config,
                artifact.config.operational_end_seconds,
            )
            exit_increment_lower = _minimum_entry_to_exit_seconds(timing)
            exit_increment_upper = _maximum_entry_to_exit_seconds(timing, wait_upper)
            switch_lower = -exit_increment_upper
            bounds = EanVisitTimeBounds(
                switch_lower=switch_lower,
                switch_upper=switch_upper,
                exit_lower=switch_lower + exit_increment_lower,
                exit_upper=switch_upper + exit_increment_upper,
                wait_upper=wait_upper,
            )
            key = (visit.cabin_id, visit.visit_index)
            by_visit[key] = bounds
            global_upper = max(global_upper, bounds.exit_upper)

    return EanModelTimeBounds(by_visit=by_visit, global_upper=global_upper)


def _legacy_time_upper_bound(artifact: EanBuildArtifact) -> float:
    starts_by_cabin_id = {start.cabin_id: start for start in artifact.cabin_starts}
    timings_by_switch_id = {timing.switch_id: timing for timing in artifact.timings}
    visits_by_cabin_id = _visits_by_cabin_id(artifact.switch_visits)
    max_time = artifact.config.operational_end_seconds
    for cabin_id, visits in visits_by_cabin_id.items():
        elapsed = starts_by_cabin_id[cabin_id].time_seconds
        for visit in visits:
            timing = timings_by_switch_id[visit.switch_id]
            elapsed += max(
                _service_entry_to_next_switch_seconds(timing),
                timing.skip_entry_to_exit_switch_seconds
                + timing.rope_to_next_switch_seconds,
            )
        max_time = max(max_time, elapsed)
    return max_time + 10.0


def _minimum_entry_to_exit_seconds(timing: SkipStopTiming) -> float:
    service_seconds = _service_entry_to_exit_switch_seconds(timing)
    if not timing.skip_allowed:
        return service_seconds
    return min(service_seconds, timing.skip_entry_to_exit_switch_seconds)


def _maximum_entry_to_exit_seconds(
    timing: SkipStopTiming,
    wait_upper: float,
) -> float:
    service_seconds = _service_entry_to_exit_switch_seconds(timing) + wait_upper
    if not timing.skip_allowed:
        return service_seconds
    return max(service_seconds, timing.skip_entry_to_exit_switch_seconds)


def _service_entry_to_exit_switch_seconds(timing: SkipStopTiming) -> float:
    return (
        timing.entry_to_platform_entry_seconds
        + timing.min_platform_entry_to_platform_exit_seconds
        + timing.platform_exit_to_exit_switch_seconds
    )


def _service_entry_to_next_switch_seconds(timing: SkipStopTiming) -> float:
    return (
        _service_entry_to_exit_switch_seconds(timing)
        + timing.rope_to_next_switch_seconds
    )


def _visits_by_cabin_id(
    visits: tuple[SwitchVisitDefinition, ...],
) -> dict[int, tuple[SwitchVisitDefinition, ...]]:
    grouped: dict[int, list[SwitchVisitDefinition]] = {}
    for visit in visits:
        grouped.setdefault(visit.cabin_id, []).append(visit)
    return {
        cabin_id: tuple(sorted(cabin_visits, key=lambda visit: visit.visit_index))
        for cabin_id, cabin_visits in grouped.items()
    }
