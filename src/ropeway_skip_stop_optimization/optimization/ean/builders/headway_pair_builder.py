from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from itertools import combinations

from ropeway_skip_stop_optimization.optimization.ean.models import (
    HeadwayCandidate,
    HeadwayCheckpointDefinition,
    HeadwayPair,
)


class HeadwayPairBuilder(ABC):
    @abstractmethod
    def build(
        self,
        candidates: tuple[HeadwayCandidate, ...],
        checkpoints: tuple[HeadwayCheckpointDefinition, ...],
    ) -> tuple[HeadwayPair, ...]:
        """Build candidate conflict pairs for headway ordering."""


@dataclass(frozen=True)
class AllPairsHeadwayPairBuilder(HeadwayPairBuilder):
    def build(
        self,
        candidates: tuple[HeadwayCandidate, ...],
        checkpoints: tuple[HeadwayCheckpointDefinition, ...],
    ) -> tuple[HeadwayPair, ...]:
        candidates_by_id = _candidates_by_id(candidates)
        checkpoints_by_id = _checkpoints_by_id(checkpoints)
        candidates_by_checkpoint_id = _candidates_by_checkpoint_id(tuple(candidates_by_id.values()), checkpoints_by_id)

        pairs: list[HeadwayPair] = []
        for checkpoint_id, checkpoint_candidates in candidates_by_checkpoint_id.items():
            checkpoint = checkpoints_by_id[checkpoint_id]
            sorted_candidates = tuple(sorted(checkpoint_candidates, key=lambda candidate: candidate.id))
            _validate_no_duplicate_visit_at_checkpoint(sorted_candidates, checkpoint_id)
            for first_candidate, second_candidate in combinations(sorted_candidates, 2):
                pair = HeadwayPair(
                    id=_pair_id(checkpoint_id, first_candidate.id, second_candidate.id),
                    checkpoint_id=checkpoint_id,
                    first_candidate_id=first_candidate.id,
                    second_candidate_id=second_candidate.id,
                    headway_seconds=checkpoint.headway_seconds,
                )
                pair.validate()
                pairs.append(pair)

        pair_ids = [pair.id for pair in pairs]
        duplicate_pair_ids = _duplicates(pair_ids)
        if duplicate_pair_ids:
            raise ValueError(f"duplicate headway pair ids: {duplicate_pair_ids}")
        return tuple(pairs)


def _pair_id(checkpoint_id: str, first_candidate_id: str, second_candidate_id: str) -> str:
    return f"pair::{checkpoint_id}::{first_candidate_id}::{second_candidate_id}"


def _candidates_by_id(candidates: tuple[HeadwayCandidate, ...]) -> dict[str, HeadwayCandidate]:
    if not candidates:
        raise ValueError("headway pair builder needs at least one candidate")
    result: dict[str, HeadwayCandidate] = {}
    duplicates = set()
    for candidate in candidates:
        candidate.validate()
        if candidate.id in result:
            duplicates.add(candidate.id)
        result[candidate.id] = candidate
    if duplicates:
        raise ValueError(f"duplicate headway candidate ids: {duplicates}")
    return result


def _checkpoints_by_id(
    checkpoints: tuple[HeadwayCheckpointDefinition, ...],
) -> dict[str, HeadwayCheckpointDefinition]:
    if not checkpoints:
        raise ValueError("headway pair builder needs at least one checkpoint")
    result: dict[str, HeadwayCheckpointDefinition] = {}
    duplicates = set()
    for checkpoint in checkpoints:
        checkpoint.validate()
        if checkpoint.id in result:
            duplicates.add(checkpoint.id)
        result[checkpoint.id] = checkpoint
    if duplicates:
        raise ValueError(f"duplicate headway checkpoint ids: {duplicates}")
    return result


def _candidates_by_checkpoint_id(
    candidates: tuple[HeadwayCandidate, ...],
    checkpoints_by_id: dict[str, HeadwayCheckpointDefinition],
) -> dict[str, list[HeadwayCandidate]]:
    result: dict[str, list[HeadwayCandidate]] = {}
    for candidate in candidates:
        if candidate.checkpoint_id not in checkpoints_by_id:
            raise ValueError(f"headway candidate references unknown checkpoint_id: {candidate.checkpoint_id!r}")
        result.setdefault(candidate.checkpoint_id, []).append(candidate)
    return result


def _validate_no_duplicate_visit_at_checkpoint(
    candidates: tuple[HeadwayCandidate, ...],
    checkpoint_id: str,
) -> None:
    seen = set()
    duplicates = set()
    for candidate in candidates:
        key = (candidate.cabin_id, candidate.visit_index)
        if key in seen:
            duplicates.add(key)
        seen.add(key)
    if duplicates:
        raise ValueError(f"duplicate candidate visits for checkpoint {checkpoint_id!r}: {duplicates}")


def _duplicates(values: list[str]) -> set[str]:
    seen = set()
    duplicates = set()
    for value in values:
        if value in seen:
            duplicates.add(value)
        seen.add(value)
    return duplicates
