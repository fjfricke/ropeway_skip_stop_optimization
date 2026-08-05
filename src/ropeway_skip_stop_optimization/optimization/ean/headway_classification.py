from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Protocol

from ropeway_skip_stop_optimization.optimization.ean.artifact import (
    EanBuildArtifact,
)
from ropeway_skip_stop_optimization.optimization.ean.formulation_config import (
    EanTimeBoundFormulation,
)
from ropeway_skip_stop_optimization.optimization.ean.headway_semantics import (
    uses_platform_exit_wait_occupancy,
)
from ropeway_skip_stop_optimization.optimization.ean.models import (
    EanFleetMode,
    EanTimeReference,
    HeadwayCandidate,
    HeadwayCheckpointKind,
    HeadwayPair,
)
from ropeway_skip_stop_optimization.optimization.ean.time_bounds import (
    build_ean_model_time_bounds,
)


class EanHeadwayPairClassification(StrEnum):
    REDUNDANT = "redundant"
    FIXED_FORWARD = "fixed_forward"
    FIXED_REVERSE = "fixed_reverse"
    DISJUNCTIVE = "disjunctive"


class EanHeadwayPairClassifier(Protocol):
    def classify(self, pair: HeadwayPair) -> EanHeadwayPairClassification:
        """Return an exact structural classification for one original pair."""


@dataclass(frozen=True)
class EanHeadwayCandidateTimeBounds:
    leader_clear_lower: float
    leader_clear_upper: float
    follower_enter_lower: float
    follower_enter_upper: float

    def validate(self) -> None:
        if self.leader_clear_lower > self.leader_clear_upper:
            raise ValueError("headway leader-clear bounds are inconsistent")
        if self.follower_enter_lower > self.follower_enter_upper:
            raise ValueError("headway follower-enter bounds are inconsistent")


@dataclass(frozen=True)
class EanFixedStartHeadwayClassifier:
    """Classify headway pairs from conservative fixed-start visit bounds."""

    candidate_bounds_by_id: dict[str, EanHeadwayCandidateTimeBounds]

    @classmethod
    def build(
        cls,
        artifact: EanBuildArtifact,
    ) -> EanFixedStartHeadwayClassifier | None:
        if artifact.fleet_mode is not EanFleetMode.FIXED_STARTS:
            return None
        visit_bounds = build_ean_model_time_bounds(
            artifact,
            EanTimeBoundFormulation.DERIVED_VISIT_BOUNDS,
        )
        timing_by_switch_id = {
            timing.switch_id: timing for timing in artifact.timings
        }
        visit_by_key = {
            (visit.cabin_id, visit.visit_index): visit
            for visit in artifact.switch_visits
        }
        checkpoint_by_id = {
            checkpoint.id: checkpoint for checkpoint in artifact.headway_checkpoints
        }
        station_by_id = {
            station.station_id: station for station in artifact.config.station_configs
        }
        bounds_by_id: dict[str, EanHeadwayCandidateTimeBounds] = {}
        for candidate in artifact.headway_candidates:
            key = (candidate.cabin_id, candidate.visit_index)
            visit = visit_by_key[key]
            timing = timing_by_switch_id[visit.switch_id]
            checkpoint = checkpoint_by_id[candidate.checkpoint_id]
            station = station_by_id.get(checkpoint.station_id)
            bounds = visit_bounds.by_visit[key]
            if uses_platform_exit_wait_occupancy(checkpoint, station):
                wait_entry_offset = (
                    timing.entry_to_platform_entry_seconds
                    + timing.min_platform_entry_to_platform_exit_seconds
                )
                candidate_bounds = EanHeadwayCandidateTimeBounds(
                    leader_clear_lower=bounds.switch_lower + wait_entry_offset,
                    leader_clear_upper=(
                        bounds.switch_upper
                        + wait_entry_offset
                        + bounds.wait_upper
                    ),
                    follower_enter_lower=bounds.switch_lower + wait_entry_offset,
                    follower_enter_upper=bounds.switch_upper + wait_entry_offset,
                )
            else:
                lower, upper = _point_candidate_bounds(
                    candidate,
                    bounds.switch_lower,
                    bounds.switch_upper,
                    bounds.exit_lower,
                    bounds.exit_upper,
                    bounds.wait_upper,
                    timing.entry_to_platform_entry_seconds,
                    timing.min_platform_entry_to_platform_exit_seconds,
                )
                candidate_bounds = EanHeadwayCandidateTimeBounds(
                    leader_clear_lower=lower,
                    leader_clear_upper=upper,
                    follower_enter_lower=lower,
                    follower_enter_upper=upper,
                )
            candidate_bounds.validate()
            bounds_by_id[candidate.id] = candidate_bounds
        return cls(candidate_bounds_by_id=bounds_by_id)

    def classify(self, pair: HeadwayPair) -> EanHeadwayPairClassification:
        first = self.candidate_bounds_by_id[pair.first_candidate_id]
        second = self.candidate_bounds_by_id[pair.second_candidate_id]
        if (
            first.leader_clear_upper + pair.headway_seconds
            <= second.follower_enter_lower
        ):
            return EanHeadwayPairClassification.FIXED_FORWARD
        if (
            second.leader_clear_upper + pair.headway_seconds
            <= first.follower_enter_lower
        ):
            return EanHeadwayPairClassification.FIXED_REVERSE
        return EanHeadwayPairClassification.DISJUNCTIVE


@dataclass(frozen=True)
class EanOipInitialHeadwayClassifier:
    """Remove visit-zero entry pairs implied by OIP boundary ordering.

    Visit zero is special: an active visit-zero route must have selected one
    of the two phase-zero boundary states. The fleet symmetry layer orders all
    serving phase-zero cabins at the shared platform-entry resource. For later
    visits, a cabin may have started in an earlier phase and may already have
    overtaken, so no cabin-ID direction is inferred.
    """

    candidate_by_id: dict[str, HeadwayCandidate]
    platform_entry_checkpoint_ids: frozenset[str]

    @classmethod
    def build(
        cls,
        artifact: EanBuildArtifact,
    ) -> EanOipInitialHeadwayClassifier | None:
        if artifact.fleet_mode is not EanFleetMode.OPTIMIZED_INITIAL_PLACEMENT:
            return None
        return cls(
            candidate_by_id={
                candidate.id: candidate for candidate in artifact.headway_candidates
            },
            platform_entry_checkpoint_ids=frozenset(
                checkpoint.id
                for checkpoint in artifact.headway_checkpoints
                if checkpoint.kind is HeadwayCheckpointKind.PLATFORM_ENTRY
            ),
        )

    def classify(self, pair: HeadwayPair) -> EanHeadwayPairClassification:
        if pair.checkpoint_id not in self.platform_entry_checkpoint_ids:
            return EanHeadwayPairClassification.DISJUNCTIVE
        first = self.candidate_by_id[pair.first_candidate_id]
        second = self.candidate_by_id[pair.second_candidate_id]
        if (
            first.visit_index == 0
            and second.visit_index == 0
            and first.cabin_id != second.cabin_id
        ):
            return EanHeadwayPairClassification.REDUNDANT
        return EanHeadwayPairClassification.DISJUNCTIVE


def _point_candidate_bounds(
    candidate: HeadwayCandidate,
    switch_lower: float,
    switch_upper: float,
    exit_lower: float,
    exit_upper: float,
    wait_upper: float,
    platform_entry_offset: float,
    platform_traversal: float,
) -> tuple[float, float]:
    if candidate.time_reference is EanTimeReference.ENTRY_TIME:
        return switch_lower, switch_upper
    if candidate.time_reference is EanTimeReference.PLATFORM_ENTRY_TIME:
        return (
            switch_lower + platform_entry_offset,
            switch_upper + platform_entry_offset,
        )
    if candidate.time_reference is EanTimeReference.PLATFORM_EXIT_TIME:
        offset = platform_entry_offset + platform_traversal
        return switch_lower + offset, switch_upper + offset + wait_upper
    if candidate.time_reference is EanTimeReference.EXIT_SWITCH_TIME:
        return exit_lower, exit_upper
    raise ValueError(
        f"unsupported candidate time reference: {candidate.time_reference.value}"
    )
