from __future__ import annotations

from dataclasses import dataclass
from itertools import combinations

from ropeway_skip_stop_optimization.optimization.ean.artifact import EanBuildArtifact
from ropeway_skip_stop_optimization.optimization.ean.builders.headway_pair_builder import (
    build_headway_pair,
)
from ropeway_skip_stop_optimization.optimization.ean.formulation_config import (
    EanHorizonFormulation,
)
from ropeway_skip_stop_optimization.optimization.ean.horizon_contract import (
    is_within_closed_horizon,
)
from ropeway_skip_stop_optimization.optimization.ean.headway_semantics import (
    PLATFORM_EXIT_WAIT_OCCUPANCY_SEMANTICS,
    POINT_HEADWAY_SEMANTICS,
    uses_platform_exit_wait_occupancy,
)
from ropeway_skip_stop_optimization.optimization.ean.headway_rule_evaluation import (
    evaluate_headway_pair,
)
from ropeway_skip_stop_optimization.optimization.ean.models import (
    EanActivationReference,
    EanTimeReference,
    HeadwayCandidate,
    HeadwayCheckpointDefinition,
    HeadwayPair,
    SkipStopTiming,
    StationEanConfig,
)
from ropeway_skip_stop_optimization.optimization.ean.plan import (
    EanCabinVisit,
    EanMovementPlan,
    EanRouteDecision,
)


@dataclass(frozen=True)
class EanHeadwayViolation:
    pair: HeadwayPair
    forward_gap_seconds: float
    reverse_gap_seconds: float
    violation_seconds: float
    semantics_label: str
    forward_required_seconds: float | None = None
    reverse_required_seconds: float | None = None


@dataclass(frozen=True)
class _HeadwayTimes:
    leader_clear_time: float
    follower_enter_time: float
    semantics_label: str


def separate_all_headway_violations(
    artifact: EanBuildArtifact,
    plan: EanMovementPlan,
    *,
    tolerance_seconds: float = 1e-5,
    include_after_horizon: bool = False,
) -> tuple[EanHeadwayViolation, ...]:
    """Separate conflicts, retaining full clearance of resources entered by H.

    ``include_after_horizon`` is a diagnostic of all *exported* occurrences.
    Even a clean diagnostic does not certify unexported future visits.
    """

    if tolerance_seconds < 0:
        raise ValueError("tolerance_seconds must be nonnegative")
    checkpoint_by_id = {item.id: item for item in artifact.headway_checkpoints}
    station_by_id = {item.station_id: item for item in artifact.config.station_configs}
    timing_by_switch_id = {item.switch_id: item for item in artifact.timings}
    visit_by_key = {
        (visit.cabin_id, visit.visit_index): visit
        for trajectory in plan.trajectories
        for visit in trajectory.visits
    }
    candidates_by_checkpoint: dict[str, list[HeadwayCandidate]] = {}
    for candidate in artifact.headway_candidates:
        candidates_by_checkpoint.setdefault(candidate.checkpoint_id, []).append(candidate)

    violations: list[EanHeadwayViolation] = []
    for checkpoint_id in sorted(candidates_by_checkpoint):
        checkpoint = checkpoint_by_id[checkpoint_id]
        station = station_by_id.get(checkpoint.station_id)
        if station is not None and station.waiting_mode not in checkpoint.waiting_modes:
            continue
        active: list[tuple[HeadwayCandidate, _HeadwayTimes]] = []
        for candidate in sorted(candidates_by_checkpoint[checkpoint_id], key=lambda item: item.id):
            visit = visit_by_key.get((candidate.cabin_id, candidate.visit_index))
            if visit is None or not _candidate_is_active(candidate, checkpoint, visit):
                continue
            times = _candidate_times(candidate, checkpoint, station, visit, timing_by_switch_id)
            if times is None:
                continue
            if (
                plan.horizon_formulation is EanHorizonFormulation.EXACT_TIME_ACTIVATION
                and not include_after_horizon
                and not is_within_closed_horizon(
                    times.follower_enter_time, artifact.config.operational_end_seconds
                )
            ):
                continue
            active.append((candidate, times))
        for (first, first_times), (second, second_times) in combinations(active, 2):
            forward = second_times.follower_enter_time - first_times.leader_clear_time
            reverse = first_times.follower_enter_time - second_times.leader_clear_time
            first_visit = visit_by_key[(first.cabin_id, first.visit_index)]
            second_visit = visit_by_key[(second.cabin_id, second.visit_index)]
            evaluation = evaluate_headway_pair(
                rule=artifact.headway_rule_for_checkpoint(checkpoint),
                first_is_service=first_visit.decision is EanRouteDecision.STOP,
                second_is_service=second_visit.decision is EanRouteDecision.STOP,
                forward_gap_seconds=forward,
                reverse_gap_seconds=reverse,
            )
            if evaluation.is_violated(tolerance_seconds=tolerance_seconds):
                violations.append(
                    EanHeadwayViolation(
                        pair=build_headway_pair(checkpoint, first, second),
                        forward_gap_seconds=forward,
                        reverse_gap_seconds=reverse,
                        violation_seconds=evaluation.violation_seconds,
                        semantics_label=first_times.semantics_label,
                        forward_required_seconds=(
                            evaluation.forward_required_seconds
                        ),
                        reverse_required_seconds=(
                            evaluation.reverse_required_seconds
                        ),
                    )
                )
    return tuple(sorted(violations, key=lambda item: (-item.violation_seconds, item.pair.id)))


def select_headway_violation_batch(
    violations: tuple[EanHeadwayViolation, ...],
    *,
    limit: int,
    excluded_pair_ids: frozenset[str] = frozenset(),
) -> tuple[EanHeadwayViolation, ...]:
    if limit <= 0:
        raise ValueError("headway violation batch limit must be positive")
    eligible = (item for item in violations if item.pair.id not in excluded_pair_ids)
    return tuple(sorted(eligible, key=lambda item: (-item.violation_seconds, item.pair.id))[:limit])


def _candidate_is_active(
    candidate: HeadwayCandidate,
    checkpoint: HeadwayCheckpointDefinition,
    visit: EanCabinVisit,
) -> bool:
    if candidate.activation_reference is EanActivationReference.SERVE:
        return visit.decision is EanRouteDecision.STOP and checkpoint.applies_to_serve
    if candidate.activation_reference is EanActivationReference.SKIP:
        return visit.decision is EanRouteDecision.SKIP and checkpoint.applies_to_skip
    if candidate.activation_reference is EanActivationReference.ACTIVE:
        return (
            visit.decision is EanRouteDecision.STOP and checkpoint.applies_to_serve
        ) or (
            visit.decision is EanRouteDecision.SKIP and checkpoint.applies_to_skip
        )
    return False


def _candidate_times(
    candidate: HeadwayCandidate,
    checkpoint: HeadwayCheckpointDefinition,
    station: StationEanConfig | None,
    visit: EanCabinVisit,
    timing_by_switch_id: dict[str, SkipStopTiming],
) -> _HeadwayTimes | None:
    if uses_platform_exit_wait_occupancy(checkpoint, station):
        if visit.platform_exit_time_seconds is None:
            return None
        timing = timing_by_switch_id.get(visit.switch_id)
        if timing is None:
            return None
        return _HeadwayTimes(
            leader_clear_time=visit.platform_exit_time_seconds,
            follower_enter_time=(
                # Use the validated plan's event arithmetic. DDD exports
                # rounded offsets; recomputing raw EAN offsets can move an
                # exactly-on-H wait entry to the other side of H.
                visit.platform_exit_time_seconds - visit.wait_seconds
            ),
            semantics_label=PLATFORM_EXIT_WAIT_OCCUPANCY_SEMANTICS,
        )
    value: float | None
    if candidate.time_reference is EanTimeReference.ENTRY_TIME:
        value = visit.switch_time_seconds
    elif candidate.time_reference is EanTimeReference.PLATFORM_ENTRY_TIME:
        value = visit.platform_entry_time_seconds
    elif candidate.time_reference is EanTimeReference.PLATFORM_EXIT_TIME:
        value = visit.platform_exit_time_seconds
    elif candidate.time_reference is EanTimeReference.EXIT_SWITCH_TIME:
        value = visit.exit_switch_time_seconds
    else:
        value = None
    if value is None:
        return None
    return _HeadwayTimes(value, value, POINT_HEADWAY_SEMANTICS)
