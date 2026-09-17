from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass

from ropeway_skip_stop_optimization.optimization.ean.models import (
    EanActivationReference,
    EanTimeReference,
    HeadwayCandidate,
    HeadwayCheckpointDefinition,
    HeadwayCheckpointKind,
    SwitchVisitDefinition,
)


class HeadwayCandidateBuilder(ABC):
    @abstractmethod
    def build(
        self,
        visits: tuple[SwitchVisitDefinition, ...],
        checkpoints: tuple[HeadwayCheckpointDefinition, ...],
    ) -> tuple[HeadwayCandidate, ...]:
        """Build cabin-visit-specific headway candidates."""


@dataclass(frozen=True)
class SwitchVisitHeadwayCandidateBuilder(HeadwayCandidateBuilder):
    def build(
        self,
        visits: tuple[SwitchVisitDefinition, ...],
        checkpoints: tuple[HeadwayCheckpointDefinition, ...],
    ) -> tuple[HeadwayCandidate, ...]:
        _validate_visits(visits)
        checkpoints_by_id = _checkpoints_by_id(checkpoints)

        candidates: list[HeadwayCandidate] = []
        for visit in visits:
            for checkpoint in checkpoints_by_id.values():
                if visit.switch_id != checkpoint.switch_id:
                    continue
                candidate = HeadwayCandidate(
                    id=f"candidate::{checkpoint.id}::cabin_{visit.cabin_id}::visit_{visit.visit_index}",
                    checkpoint_id=checkpoint.id,
                    cabin_id=visit.cabin_id,
                    visit_index=visit.visit_index,
                    time_reference=time_reference_for_checkpoint_kind(checkpoint.kind),
                    activation_reference=activation_reference_for_checkpoint_kind(checkpoint.kind),
                )
                candidate.validate()
                candidates.append(candidate)

        candidate_ids = [candidate.id for candidate in candidates]
        duplicate_candidate_ids = _duplicates(candidate_ids)
        if duplicate_candidate_ids:
            raise ValueError(f"duplicate headway candidate ids: {duplicate_candidate_ids}")
        return tuple(candidates)


def time_reference_for_checkpoint_kind(kind: HeadwayCheckpointKind) -> EanTimeReference:
    if kind is HeadwayCheckpointKind.ENTRY_SWITCH:
        return EanTimeReference.ENTRY_TIME
    if kind is HeadwayCheckpointKind.PLATFORM_ENTRY:
        return EanTimeReference.PLATFORM_ENTRY_TIME
    if kind is HeadwayCheckpointKind.PLATFORM_EXIT:
        return EanTimeReference.PLATFORM_EXIT_TIME
    if kind in {
        HeadwayCheckpointKind.EXIT_SWITCH,
        HeadwayCheckpointKind.SERVICE_MECHANISM,
    }:
        return EanTimeReference.EXIT_SWITCH_TIME
    raise ValueError(f"unsupported headway checkpoint kind: {kind}")


def activation_reference_for_checkpoint_kind(kind: HeadwayCheckpointKind) -> EanActivationReference:
    if kind is HeadwayCheckpointKind.ENTRY_SWITCH:
        return EanActivationReference.ACTIVE
    if kind in {
        HeadwayCheckpointKind.PLATFORM_ENTRY,
        HeadwayCheckpointKind.PLATFORM_EXIT,
        HeadwayCheckpointKind.SERVICE_MECHANISM,
    }:
        return EanActivationReference.SERVE
    if kind is HeadwayCheckpointKind.EXIT_SWITCH:
        return EanActivationReference.ACTIVE
    raise ValueError(f"unsupported headway checkpoint kind: {kind}")


def _validate_visits(visits: tuple[SwitchVisitDefinition, ...]) -> None:
    if not visits:
        raise ValueError("headway candidate builder needs at least one switch visit")
    seen = set()
    duplicates = set()
    for visit in visits:
        visit.validate()
        key = (visit.cabin_id, visit.visit_index)
        if key in seen:
            duplicates.add(key)
        seen.add(key)
    if duplicates:
        raise ValueError(f"duplicate switch visit keys: {duplicates}")


def _checkpoints_by_id(
    checkpoints: tuple[HeadwayCheckpointDefinition, ...],
) -> dict[str, HeadwayCheckpointDefinition]:
    if not checkpoints:
        raise ValueError("headway candidate builder needs at least one checkpoint")
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


def _duplicates(values: list[str]) -> set[str]:
    seen = set()
    duplicates = set()
    for value in values:
        if value in seen:
            duplicates.add(value)
        seen.add(value)
    return duplicates
