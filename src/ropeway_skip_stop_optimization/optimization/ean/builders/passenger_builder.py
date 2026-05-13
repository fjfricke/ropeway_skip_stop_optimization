from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime

from ropeway_skip_stop_optimization.models import Demand, Scenario
from ropeway_skip_stop_optimization.optimization.ean.artifact import EanBuildArtifact
from ropeway_skip_stop_optimization.optimization.ean.models import (
    EanDemandGroup,
    EanRideCandidate,
    SkipStopTiming,
    SwitchTransition,
    SwitchVisitDefinition,
)


LOGGER = logging.getLogger(__name__)


@dataclass(frozen=True)
class EanPassengerCandidateBuildResult:
    demand_groups: tuple[EanDemandGroup, ...]
    ride_candidates: tuple[EanRideCandidate, ...]

    def validate(self) -> None:
        group_ids: set[str] = set()
        for group in self.demand_groups:
            group.validate()
            if group.id in group_ids:
                raise ValueError(f"duplicate EAN demand group id: {group.id!r}")
            group_ids.add(group.id)

        candidate_ids: set[str] = set()
        for candidate in self.ride_candidates:
            candidate.validate()
            if candidate.id in candidate_ids:
                raise ValueError(f"duplicate EAN ride candidate id: {candidate.id!r}")
            if candidate.demand_group_id not in group_ids:
                raise ValueError(
                    f"EAN ride candidate {candidate.id!r} references unknown demand group "
                    f"{candidate.demand_group_id!r}"
                )
            candidate_ids.add(candidate.id)


class EanPassengerCandidateBuilder:
    """Build grouped demand and feasible EAN ride candidates.

    Demand remains grouped by homogeneous OD/release-time batches. Candidate
    generation is intentionally structural: stop/skip choices are MILP
    decisions, so candidates are filtered only by cabin, station sequence, and
    visit order.

    For the current single directed ring EAN, ride candidates are additionally
    limited to less than one full switch cycle after boarding. This prevents
    passengers from riding one or more complete loops before alighting. If an
    artifact does not match the immutable directed-ring topology, this
    optimization is skipped with a warning; future branch or multi-cycle
    artifacts need an explicit graph/path-distance rule instead of visit-index
    span pruning.

    Candidate generation also applies conservative horizon pruning as an
    optimization: candidates are skipped only when their earliest possible
    boarding or alighting time is already after the passenger service horizon.
    The pruning must remain based on lower bounds so no potentially feasible
    integer solution is removed.
    """

    def build(self, scenario: Scenario, artifact: EanBuildArtifact) -> EanPassengerCandidateBuildResult:
        artifact.validate()
        demand_groups = expand_demands_to_ean_groups(scenario)
        ride_candidates = build_ean_ride_candidates(demand_groups, artifact)
        result = EanPassengerCandidateBuildResult(
            demand_groups=demand_groups,
            ride_candidates=ride_candidates,
        )
        result.validate()
        return result


def expand_demands_to_ean_groups(scenario: Scenario) -> tuple[EanDemandGroup, ...]:
    return tuple(
        EanDemandGroup(
            id=f"demand::{index}",
            origin_station_id=demand.origin,
            destination_station_id=demand.destination,
            release_time_seconds=release_seconds_for_demand(scenario, demand),
            count=demand.count,
        )
        for index, demand in enumerate(scenario.demands)
    )


def release_seconds_for_demand(scenario: Scenario, demand: Demand) -> float:
    service_start = datetime.combine(datetime.min.date(), scenario.service_start_time)
    arrival = datetime.combine(datetime.min.date(), demand.arrival_time)
    return (arrival - service_start).total_seconds()


def build_ean_ride_candidates(
    demand_groups: tuple[EanDemandGroup, ...],
    artifact: EanBuildArtifact,
) -> tuple[EanRideCandidate, ...]:
    timing_by_switch_id = {timing.switch_id: timing for timing in artifact.timings}
    visits_by_cabin_id = _visits_by_cabin_id(artifact.switch_visits)
    starts_by_cabin_id = {start.cabin_id: start for start in artifact.cabin_starts}
    ring_span_pruning_enabled = _is_single_directed_ring_artifact(artifact)
    if not ring_span_pruning_enabled:
        LOGGER.warning(
            "EAN passenger candidate ring-span pruning skipped: artifact %r does not match the single directed ring topology",
            artifact.scenario_id,
        )

    candidates: list[EanRideCandidate] = []
    for group in demand_groups:
        group.validate()
        for cabin_id, visits in visits_by_cabin_id.items():
            visits_by_key = {(visit.cabin_id, visit.visit_index): visit for visit in visits}
            for board_visit in visits:
                if _station_id_for_visit(board_visit, timing_by_switch_id) != group.origin_station_id:
                    continue
                for alight_visit in visits:
                    if alight_visit.visit_index <= board_visit.visit_index:
                        continue
                    if _station_id_for_visit(alight_visit, timing_by_switch_id) != group.destination_station_id:
                        continue
                    if ring_span_pruning_enabled and not _is_valid_single_ring_ride_span(
                        board_visit=board_visit,
                        alight_visit=alight_visit,
                        switch_cycle_length=len(artifact.switch_cycle),
                    ):
                        continue
                    if not _can_serve_within_horizon(
                        group=group,
                        cabin_id=cabin_id,
                        cabin_start_time_seconds=starts_by_cabin_id[cabin_id].time_seconds,
                        board_visit=board_visit,
                        alight_visit=alight_visit,
                        visits_by_key=visits_by_key,
                        timing_by_switch_id=timing_by_switch_id,
                        horizon_seconds=artifact.config.horizon_seconds,
                    ):
                        continue
                    candidate = EanRideCandidate(
                        id=(
                            f"ride::{group.id}::cabin_{cabin_id}::"
                            f"board_{board_visit.visit_index}::alight_{alight_visit.visit_index}"
                        ),
                        demand_group_id=group.id,
                        cabin_id=cabin_id,
                        board_visit_index=board_visit.visit_index,
                        alight_visit_index=alight_visit.visit_index,
                    )
                    candidate.validate()
                    candidates.append(candidate)

    return tuple(candidates)


def _station_id_for_visit(
    visit: SwitchVisitDefinition,
    timing_by_switch_id: dict[str, SkipStopTiming],
) -> str:
    return timing_by_switch_id[visit.switch_id].station_id


def _can_serve_within_horizon(
    group: EanDemandGroup,
    cabin_id: int,
    cabin_start_time_seconds: float,
    board_visit: SwitchVisitDefinition,
    alight_visit: SwitchVisitDefinition,
    visits_by_key: dict[tuple[int, int], SwitchVisitDefinition],
    timing_by_switch_id: dict[str, SkipStopTiming],
    horizon_seconds: float,
) -> bool:
    earliest_board_time = max(
        group.release_time_seconds,
        _earliest_platform_exit_time_seconds(
            cabin_id=cabin_id,
            visit_index=board_visit.visit_index,
            visits_by_key=visits_by_key,
            timing_by_switch_id=timing_by_switch_id,
            cabin_start_time_seconds=cabin_start_time_seconds,
        ),
    )
    if earliest_board_time > horizon_seconds:
        return False

    earliest_alight_time = earliest_board_time + _min_platform_exit_to_platform_entry_seconds(
        cabin_id=cabin_id,
        board_visit_index=board_visit.visit_index,
        alight_visit_index=alight_visit.visit_index,
        visits_by_key=visits_by_key,
        timing_by_switch_id=timing_by_switch_id,
    )
    return earliest_alight_time <= horizon_seconds


def _earliest_platform_exit_time_seconds(
    cabin_id: int,
    visit_index: int,
    visits_by_key: dict[tuple[int, int], SwitchVisitDefinition],
    timing_by_switch_id: dict[str, SkipStopTiming],
    cabin_start_time_seconds: float,
) -> float:
    elapsed = cabin_start_time_seconds
    for current_visit_index in range(visit_index):
        key = (cabin_id, current_visit_index)
        if key not in visits_by_key:
            raise ValueError(f"missing EAN visit while computing earliest platform exit: {key!r}")
        timing = timing_by_switch_id[visits_by_key[key].switch_id]
        elapsed += _min_entry_to_next_switch_seconds(timing)

    key = (cabin_id, visit_index)
    if key not in visits_by_key:
        raise ValueError(f"missing EAN board visit while computing earliest platform exit: {key!r}")
    timing = timing_by_switch_id[visits_by_key[key].switch_id]
    return (
        elapsed
        + timing.entry_to_platform_entry_seconds
        + timing.min_platform_entry_to_platform_exit_seconds
    )


def _min_platform_exit_to_platform_entry_seconds(
    cabin_id: int,
    board_visit_index: int,
    alight_visit_index: int,
    visits_by_key: dict[tuple[int, int], SwitchVisitDefinition],
    timing_by_switch_id: dict[str, SkipStopTiming],
) -> float:
    if alight_visit_index <= board_visit_index:
        raise ValueError("alight_visit_index must be after board_visit_index")

    board_key = (cabin_id, board_visit_index)
    if board_key not in visits_by_key:
        raise ValueError(f"missing EAN board visit while computing minimum trip time: {board_key!r}")
    board_timing = timing_by_switch_id[visits_by_key[board_key].switch_id]
    elapsed = board_timing.platform_exit_to_exit_switch_seconds + board_timing.rope_to_next_switch_seconds

    for current_visit_index in range(board_visit_index + 1, alight_visit_index):
        key = (cabin_id, current_visit_index)
        if key not in visits_by_key:
            raise ValueError(f"missing EAN intermediate visit while computing minimum trip time: {key!r}")
        timing = timing_by_switch_id[visits_by_key[key].switch_id]
        elapsed += _min_entry_to_next_switch_seconds(timing)

    alight_key = (cabin_id, alight_visit_index)
    if alight_key not in visits_by_key:
        raise ValueError(f"missing EAN alight visit while computing minimum trip time: {alight_key!r}")
    alight_timing = timing_by_switch_id[visits_by_key[alight_key].switch_id]
    return elapsed + alight_timing.entry_to_platform_entry_seconds


def _min_entry_to_next_switch_seconds(timing: SkipStopTiming) -> float:
    service_seconds = (
        timing.entry_to_platform_entry_seconds
        + timing.min_platform_entry_to_platform_exit_seconds
        + timing.platform_exit_to_exit_switch_seconds
        + timing.rope_to_next_switch_seconds
    )
    if not timing.skip_allowed:
        return service_seconds
    return min(service_seconds, timing.skip_entry_to_exit_switch_seconds + timing.rope_to_next_switch_seconds)


def _is_valid_single_ring_ride_span(
    board_visit: SwitchVisitDefinition,
    alight_visit: SwitchVisitDefinition,
    switch_cycle_length: int,
) -> bool:
    span = alight_visit.visit_index - board_visit.visit_index
    return 0 < span < switch_cycle_length


def _is_single_directed_ring_artifact(artifact: EanBuildArtifact) -> bool:
    expected_transition_by_from_switch_id = {
        switch_id: artifact.switch_cycle[(index + 1) % len(artifact.switch_cycle)]
        for index, switch_id in enumerate(artifact.switch_cycle)
    }
    transition_by_from_switch_id = _transition_by_from_switch_id(artifact.switch_transitions)
    return transition_by_from_switch_id == expected_transition_by_from_switch_id


def _transition_by_from_switch_id(transitions: tuple[SwitchTransition, ...]) -> dict[str, str]:
    return {
        transition.from_switch_id: transition.to_switch_id
        for transition in transitions
    }


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
