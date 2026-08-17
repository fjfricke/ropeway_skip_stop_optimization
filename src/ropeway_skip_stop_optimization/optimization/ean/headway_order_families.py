from __future__ import annotations

from dataclasses import dataclass

from ropeway_skip_stop_optimization.optimization.ean.artifact import (
    EanBuildArtifact,
)
from ropeway_skip_stop_optimization.optimization.ean.models import (
    EanFleetMode,
    EanHeadwayPairScope,
    HeadwayCandidate,
    HeadwayCheckpointKind,
    HeadwayPair,
)
VisitKey = tuple[int, int]
EventPair = tuple[VisitKey, VisitKey]


@dataclass(frozen=True)
class EanHeadwayOrderReference:
    family_id: str
    pair_forward_is_family_forward: bool


@dataclass(frozen=True)
class EanHeadwayOrderFamilyIndex:
    """Exact order-sharing index for one deterministic fixed-start pattern."""

    reference_by_pair_id: dict[str, EanHeadwayOrderReference]
    member_pair_ids_by_family_id: dict[str, tuple[str, ...]]

    @classmethod
    def build(cls, artifact: EanBuildArtifact) -> EanHeadwayOrderFamilyIndex:
        _require_supported_artifact(artifact)
        candidate_by_id = {
            candidate.id: candidate for candidate in artifact.headway_candidates
        }
        checkpoint_by_id = {
            checkpoint.id: checkpoint for checkpoint in artifact.headway_checkpoints
        }
        predecessor_by_visit_key = _predecessor_by_visit_key(artifact)
        switch_id_by_visit_key = {
            (visit.cabin_id, visit.visit_index): visit.switch_id
            for visit in artifact.switch_visits
        }
        order_boundary_state_ids = _order_boundary_state_ids(artifact)
        source_cache: dict[
            tuple[str, EventPair],
            tuple[str, str, EventPair],
        ] = {}
        member_pair_ids_by_family_id_mutable: dict[str, list[str]] = {}
        reference_by_pair_id: dict[str, EanHeadwayOrderReference] = {}
        for pair in artifact.headway_pairs:
            checkpoint = checkpoint_by_id[pair.checkpoint_id]
            endpoints = _pair_endpoints(pair, candidate_by_id)
            source_kind, source_switch_id, source_endpoints = _order_source(
                checkpoint_kind=checkpoint.kind,
                switch_id=checkpoint.switch_id,
                endpoints=endpoints,
                predecessor_by_visit_key=predecessor_by_visit_key,
                switch_id_by_visit_key=switch_id_by_visit_key,
                order_boundary_state_ids=order_boundary_state_ids,
                source_cache=source_cache,
            )
            canonical_source_endpoints = _unordered_event_pair(source_endpoints)
            family_id = _family_id(
                source_kind,
                source_switch_id,
                canonical_source_endpoints,
            )
            reference_by_pair_id[pair.id] = EanHeadwayOrderReference(
                family_id=family_id,
                pair_forward_is_family_forward=(
                    source_endpoints == canonical_source_endpoints
                ),
            )
            member_pair_ids_by_family_id_mutable.setdefault(
                family_id, []
            ).append(pair.id)

        member_pair_ids_by_family_id = {
            family_id: tuple(sorted(member_pair_ids))
            for family_id, member_pair_ids in sorted(
                member_pair_ids_by_family_id_mutable.items()
            )
        }
        return cls(
            reference_by_pair_id=dict(sorted(reference_by_pair_id.items())),
            member_pair_ids_by_family_id=member_pair_ids_by_family_id,
        )

    def reference_for_pair(self, pair_id: str) -> EanHeadwayOrderReference:
        try:
            return self.reference_by_pair_id[pair_id]
        except KeyError as error:
            raise ValueError(
                f"headway order family index has no pair {pair_id!r}"
            ) from error

    @property
    def family_count(self) -> int:
        return len(self.member_pair_ids_by_family_id)

    @property
    def singleton_family_count(self) -> int:
        return sum(
            len(member_pair_ids) == 1
            for member_pair_ids in self.member_pair_ids_by_family_id.values()
        )


def _require_supported_artifact(artifact: EanBuildArtifact) -> None:
    if artifact.fleet_mode is not EanFleetMode.FIXED_STARTS:
        raise NotImplementedError(
            "shared_merge_headway_order currently supports fixed starts only"
        )
    if artifact.headway_pair_scope is not EanHeadwayPairScope.COMPLETE:
        raise NotImplementedError(
            "shared_merge_headway_order requires complete eager headway pairs"
        )
    if artifact.movement_network is None or len(artifact.circulation_pattern_ids) != 1:
        raise NotImplementedError(
            "shared_merge_headway_order requires one canonical movement pattern"
        )


def _pair_endpoints(
    pair: HeadwayPair,
    candidate_by_id: dict[str, HeadwayCandidate],
) -> EventPair:
    first = candidate_by_id[pair.first_candidate_id]
    second = candidate_by_id[pair.second_candidate_id]
    return (
        (first.cabin_id, first.visit_index),
        (second.cabin_id, second.visit_index),
    )


def _unordered_event_pair(endpoints: EventPair) -> EventPair:
    first, second = sorted(endpoints)
    return first, second


def _predecessor_by_visit_key(
    artifact: EanBuildArtifact,
) -> dict[VisitKey, VisitKey]:
    visits_by_cabin_id: dict[int, list[VisitKey]] = {}
    for visit in artifact.switch_visits:
        visits_by_cabin_id.setdefault(visit.cabin_id, []).append(
            (visit.cabin_id, visit.visit_index)
        )
    result: dict[VisitKey, VisitKey] = {}
    for visit_keys in visits_by_cabin_id.values():
        ordered = sorted(visit_keys, key=lambda item: item[1])
        result.update(zip(ordered[1:], ordered, strict=False))
    return result


def _order_source(
    *,
    checkpoint_kind: HeadwayCheckpointKind,
    switch_id: str,
    endpoints: EventPair,
    predecessor_by_visit_key: dict[VisitKey, VisitKey],
    switch_id_by_visit_key: dict[VisitKey, str],
    order_boundary_state_ids: frozenset[str],
    source_cache: dict[
        tuple[str, EventPair],
        tuple[str, str, EventPair],
    ],
) -> tuple[str, str, EventPair]:
    current_switch_id = switch_id
    current_endpoints = endpoints
    current_kind = (
        HeadwayCheckpointKind.EXIT_SWITCH
        if checkpoint_kind is HeadwayCheckpointKind.SERVICE_MECHANISM
        else checkpoint_kind
    )
    traversed: list[tuple[str, EventPair]] = []
    while True:
        cache_key = current_switch_id, current_endpoints
        if current_kind is HeadwayCheckpointKind.EXIT_SWITCH:
            cached = source_cache.get(cache_key)
            if cached is not None:
                for traversed_key in traversed:
                    source_cache[traversed_key] = cached
                return cached
            traversed.append(cache_key)
        if (
            current_kind is HeadwayCheckpointKind.EXIT_SWITCH
            and current_switch_id in order_boundary_state_ids
        ):
            result = "merge", current_switch_id, current_endpoints
            for traversed_key in traversed:
                source_cache[traversed_key] = result
            return result
        first_predecessor = predecessor_by_visit_key.get(current_endpoints[0])
        second_predecessor = predecessor_by_visit_key.get(current_endpoints[1])
        if first_predecessor is None or second_predecessor is None:
            result = "boundary", current_switch_id, current_endpoints
            for traversed_key in traversed:
                source_cache[traversed_key] = result
            return result
        first_switch_id = switch_id_by_visit_key[first_predecessor]
        second_switch_id = switch_id_by_visit_key[second_predecessor]
        if first_switch_id != second_switch_id:
            result = "boundary", current_switch_id, current_endpoints
            for traversed_key in traversed:
                source_cache[traversed_key] = result
            return result
        current_switch_id = first_switch_id
        current_endpoints = first_predecessor, second_predecessor
        current_kind = HeadwayCheckpointKind.EXIT_SWITCH


def _order_boundary_state_ids(artifact: EanBuildArtifact) -> frozenset[str]:
    """Return every state at which trajectories may take different routes.

    Today's deterministic networks only expose service/skip alternatives here.
    Treating every future multi-option state as a boundary is deliberately
    conservative: an order is shared only after the alternatives reconverge.
    """
    network = artifact.movement_network
    if network is None:
        return frozenset()
    pattern = network.pattern(artifact.circulation_pattern_ids[0])
    result: set[str] = set()
    for state_id, option_ids in zip(
        pattern.state_ids,
        pattern.route_option_ids_by_position,
        strict=True,
    ):
        if len(option_ids) > 1:
            result.add(state_id)
    return frozenset(result)


def _family_id(
    source_kind: str,
    switch_id: str,
    endpoints: EventPair,
) -> str:
    first, second = endpoints
    return (
        f"order_family::{source_kind}::{switch_id}::"
        f"cabin_{first[0]}_visit_{first[1]}::"
        f"cabin_{second[0]}_visit_{second[1]}"
    )
