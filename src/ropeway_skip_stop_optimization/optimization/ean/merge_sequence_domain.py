from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
import hashlib
import json

from ropeway_skip_stop_optimization.optimization.ean.artifact import (
    EanBuildArtifact,
)
from ropeway_skip_stop_optimization.optimization.ean.models import (
    HeadwayCandidate,
    HeadwayCheckpointDefinition,
    HeadwayCheckpointKind,
    SwitchVisitDefinition,
)
from ropeway_skip_stop_optimization.optimization.ean.network import (
    EanMovementNetwork,
    EanPassengerBehavior,
    EanRouteOption,
)


class EanMergeHorizonRole(StrEnum):
    INTERIOR = "interior"
    INITIAL_BOUNDARY = "initial_boundary"
    TERMINAL_BOUNDARY = "terminal_boundary"
    INITIAL_AND_TERMINAL_BOUNDARY = "initial_and_terminal_boundary"


@dataclass(frozen=True)
class EanMergeOrderProof:
    service_fifo: bool
    skip_fifo: bool
    outgoing_corridor_fifo: bool
    predecessor_complete: bool
    horizon_complete: bool
    reasons: tuple[str, ...]

    @property
    def complete(self) -> bool:
        return all(
            (
                self.service_fifo,
                self.skip_fifo,
                self.outgoing_corridor_fifo,
                self.predecessor_complete,
                self.horizon_complete,
            )
        )

    def validate(self) -> None:
        if not self.reasons:
            raise ValueError("merge-order proof needs at least one reason")
        if any(not reason.strip() for reason in self.reasons):
            raise ValueError("merge-order proof reasons must be nonempty")


@dataclass(frozen=True)
class EanMergeSequenceBlockDefinition:
    id: str
    family_id: str
    candidate_ids: tuple[str, ...]
    visit_keys: tuple[tuple[int, int], ...]
    predecessor_by_candidate_id: tuple[tuple[str, str], ...]
    successor_by_candidate_id: tuple[tuple[str, str], ...]
    horizon_role_by_candidate_id: tuple[tuple[str, EanMergeHorizonRole], ...]

    def validate(self) -> None:
        _require_id("merge block id", self.id)
        _require_id("merge block family id", self.family_id)
        if not self.candidate_ids:
            raise ValueError("merge sequence block needs candidates")
        if len(self.candidate_ids) != len(set(self.candidate_ids)):
            raise ValueError("merge sequence block candidate ids must be unique")
        if len(self.candidate_ids) != len(self.visit_keys):
            raise ValueError("merge sequence block visits must match candidates")
        if len(self.visit_keys) != len(set(self.visit_keys)):
            raise ValueError("merge sequence block visit keys must be unique")
        predecessor_sources = [item[0] for item in self.predecessor_by_candidate_id]
        if len(predecessor_sources) != len(set(predecessor_sources)):
            raise ValueError("merge predecessor sources must be unique")
        predecessor_targets = [item[1] for item in self.predecessor_by_candidate_id]
        if len(predecessor_targets) != len(set(predecessor_targets)):
            raise ValueError("merge predecessor targets must be unique")
        unknown_sources = set(predecessor_sources) - set(self.candidate_ids)
        if unknown_sources:
            raise ValueError(
                f"merge predecessors reference unknown sources: {unknown_sources}"
            )
        successor_sources = [item[0] for item in self.successor_by_candidate_id]
        if len(successor_sources) != len(set(successor_sources)):
            raise ValueError("merge successor sources must be unique")
        successor_targets = [item[1] for item in self.successor_by_candidate_id]
        if len(successor_targets) != len(set(successor_targets)):
            raise ValueError("merge successor targets must be unique")
        unknown_successor_sources = set(successor_sources) - set(self.candidate_ids)
        if unknown_successor_sources:
            raise ValueError(
                "merge successors reference unknown sources: "
                f"{unknown_successor_sources}"
            )
        role_ids = [item[0] for item in self.horizon_role_by_candidate_id]
        if set(role_ids) != set(self.candidate_ids) or len(role_ids) != len(
            self.candidate_ids
        ):
            raise ValueError("every merge candidate needs one horizon role")
        for _, role in self.horizon_role_by_candidate_id:
            if not isinstance(role, EanMergeHorizonRole):
                raise ValueError("merge candidate needs a valid horizon role")


@dataclass(frozen=True)
class EanMergeFamily:
    id: str
    state_id: str
    station_id: str
    exit_checkpoint_id: str
    incoming_corridor_id: str
    outgoing_corridor_id: str
    service_option_id: str
    skip_option_id: str
    sequence_block_ids: tuple[str, ...]
    headway_rule_id: str
    proof: EanMergeOrderProof

    def validate(self) -> None:
        for label, value in (
            ("merge family id", self.id),
            ("merge state id", self.state_id),
            ("merge station id", self.station_id),
            ("merge exit checkpoint id", self.exit_checkpoint_id),
            ("merge incoming corridor id", self.incoming_corridor_id),
            ("merge outgoing corridor id", self.outgoing_corridor_id),
            ("merge service option id", self.service_option_id),
            ("merge skip option id", self.skip_option_id),
            ("merge headway rule id", self.headway_rule_id),
        ):
            _require_id(label, value)
        if not self.sequence_block_ids:
            raise ValueError("merge family needs a sequence block")
        self.proof.validate()


@dataclass(frozen=True)
class EanMergeSequenceDomain:
    families: tuple[EanMergeFamily, ...]
    sequence_blocks: tuple[EanMergeSequenceBlockDefinition, ...]
    covered_candidate_ids: tuple[str, ...]
    eager_fallback_candidate_ids: tuple[str, ...]

    @property
    def fingerprint(self) -> str:
        payload = {
            "families": [
                {
                    "id": family.id,
                    "state": family.state_id,
                    "checkpoint": family.exit_checkpoint_id,
                    "service": family.service_option_id,
                    "skip": family.skip_option_id,
                    "blocks": family.sequence_block_ids,
                    "rule": family.headway_rule_id,
                    "proof": family.proof.complete,
                }
                for family in self.families
            ],
            "blocks": [
                {
                    "id": block.id,
                    "candidates": block.candidate_ids,
                    "predecessors": block.predecessor_by_candidate_id,
                    "successors": block.successor_by_candidate_id,
                    "roles": tuple(
                        (candidate_id, role.value)
                        for candidate_id, role in block.horizon_role_by_candidate_id
                    ),
                }
                for block in self.sequence_blocks
            ],
            "covered": self.covered_candidate_ids,
            "fallback": self.eager_fallback_candidate_ids,
        }
        encoded = json.dumps(
            payload,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
        return hashlib.sha256(encoded).hexdigest()

    def validate(self) -> None:
        family_ids = [family.id for family in self.families]
        block_ids = [block.id for block in self.sequence_blocks]
        if len(family_ids) != len(set(family_ids)):
            raise ValueError("merge family ids must be unique")
        if len(block_ids) != len(set(block_ids)):
            raise ValueError("merge sequence block ids must be unique")
        for family in self.families:
            family.validate()
        for block in self.sequence_blocks:
            block.validate()
        if set(self.covered_candidate_ids) & set(self.eager_fallback_candidate_ids):
            raise ValueError("merge candidates cannot be covered and fallback")
        covered_from_blocks = {
            candidate_id
            for block in self.sequence_blocks
            for candidate_id in block.candidate_ids
        }
        if covered_from_blocks != set(self.covered_candidate_ids):
            raise ValueError("merge block candidates must equal covered candidates")


@dataclass(frozen=True)
class EanMergeSequenceDomainBuilder:
    """Derive exact two-branch reconvergence domains from canonical EAN data."""

    def build(self, artifact: EanBuildArtifact) -> EanMergeSequenceDomain:
        if artifact.movement_network is None:
            raise NotImplementedError("merge sequences require a movement network")
        if len(artifact.circulation_pattern_ids) != 1:
            raise NotImplementedError(
                "merge sequences require one canonical circulation pattern"
            )
        rule_id_by_checkpoint_id = {
            checkpoint.id: artifact.headway_rule_for_checkpoint(checkpoint).id
            for checkpoint in artifact.headway_checkpoints
        }
        return self.build_components(
            network=artifact.movement_network,
            pattern_id=artifact.circulation_pattern_ids[0],
            visits=artifact.switch_visits,
            checkpoints=artifact.headway_checkpoints,
            candidates=artifact.headway_candidates,
            rule_id_by_checkpoint_id=rule_id_by_checkpoint_id,
        )

    def build_components(
        self,
        *,
        network: EanMovementNetwork,
        pattern_id: str,
        visits: tuple[SwitchVisitDefinition, ...],
        checkpoints: tuple[HeadwayCheckpointDefinition, ...],
        candidates: tuple[HeadwayCandidate, ...],
        rule_id_by_checkpoint_id: dict[str, str],
    ) -> EanMergeSequenceDomain:
        network.validate()
        pattern = network.pattern(pattern_id)
        option_by_id = {option.id: option for option in network.route_options}
        checkpoint_by_state = _exit_checkpoint_by_state(checkpoints)
        checkpoint_by_id = {checkpoint.id: checkpoint for checkpoint in checkpoints}
        _validate_unique_count("headway checkpoint", checkpoint_by_id, checkpoints)
        candidate_by_visit_and_checkpoint = {
            ((candidate.cabin_id, candidate.visit_index), candidate.checkpoint_id): candidate
            for candidate in candidates
        }
        visit_by_key = {
            (visit.cabin_id, visit.visit_index): visit for visit in visits
        }
        _validate_unique_count("switch visit", visit_by_key, visits)
        _validate_unique_count(
            "candidate visit/checkpoint",
            candidate_by_visit_and_checkpoint,
            candidates,
        )

        families: list[EanMergeFamily] = []
        blocks: list[EanMergeSequenceBlockDefinition] = []
        covered: set[str] = set()
        all_exit_candidates = {
            candidate.id
            for candidate in candidates
            if _candidate_checkpoint_kind(candidate, checkpoint_by_id)
            is HeadwayCheckpointKind.EXIT_SWITCH
        }
        for position, state_id in enumerate(pattern.state_ids):
            options = tuple(
                option_by_id[option_id]
                for option_id in pattern.route_option_ids_by_position[position]
            )
            service = _unique_behavior_option(
                options,
                EanPassengerBehavior.SERVICE,
                state_id,
                required=True,
            )
            skip = _unique_behavior_option(
                options,
                EanPassengerBehavior.SKIP,
                state_id,
                required=False,
            )
            if skip is None:
                continue
            if service.to_state_id != skip.to_state_id:
                raise NotImplementedError(
                    f"dynamic routing not yet supported at {state_id!r}: "
                    "Service and Skip do not reconverge"
                )
            if service.continuation_segment_ids != skip.continuation_segment_ids:
                raise NotImplementedError(
                    f"dynamic routing not yet supported at {state_id!r}: "
                    "Service and Skip do not share one Rope continuation"
                )
            checkpoint = checkpoint_by_state.get(state_id)
            if checkpoint is None:
                raise ValueError(
                    f"merge state {state_id!r} has no EXIT_SWITCH checkpoint"
                )
            family_id = f"merge_family::{state_id}"
            block_id = f"merge_block::{state_id}"
            state_candidates = tuple(
                sorted(
                    (
                        candidate
                        for candidate in candidates
                        if candidate.checkpoint_id == checkpoint.id
                    ),
                    key=lambda item: (item.cabin_id, item.visit_index, item.id),
                )
            )
            if not state_candidates:
                continue
            predecessor_items: list[tuple[str, str]] = []
            successor_items: list[tuple[str, str]] = []
            role_items: list[tuple[str, EanMergeHorizonRole]] = []
            for candidate in state_candidates:
                key = (candidate.cabin_id, candidate.visit_index)
                predecessor_key = _predecessor_visit_key(key, visit_by_key)
                predecessor_candidate = None
                if predecessor_key is not None:
                    predecessor_visit = visit_by_key[predecessor_key]
                    predecessor_checkpoint = checkpoint_by_state.get(
                        predecessor_visit.switch_id
                    )
                    if predecessor_checkpoint is not None:
                        predecessor_candidate = candidate_by_visit_and_checkpoint.get(
                            (predecessor_key, predecessor_checkpoint.id)
                        )
                if predecessor_candidate is not None:
                    predecessor_items.append((candidate.id, predecessor_candidate.id))
                successor_key = _successor_visit_key(key, visit_by_key)
                successor_candidate = None
                if successor_key is not None:
                    successor_visit = visit_by_key[successor_key]
                    successor_checkpoint = checkpoint_by_state.get(
                        successor_visit.switch_id
                    )
                    if successor_checkpoint is not None:
                        successor_candidate = candidate_by_visit_and_checkpoint.get(
                            (successor_key, successor_checkpoint.id)
                        )
                if successor_candidate is not None:
                    successor_items.append((candidate.id, successor_candidate.id))
                role_items.append(
                    (
                        candidate.id,
                        _horizon_role(
                            has_predecessor=predecessor_candidate is not None,
                            has_successor=successor_candidate is not None,
                        ),
                    )
                )

            block = EanMergeSequenceBlockDefinition(
                id=block_id,
                family_id=family_id,
                candidate_ids=tuple(candidate.id for candidate in state_candidates),
                visit_keys=tuple(
                    (candidate.cabin_id, candidate.visit_index)
                    for candidate in state_candidates
                ),
                predecessor_by_candidate_id=tuple(sorted(predecessor_items)),
                successor_by_candidate_id=tuple(sorted(successor_items)),
                horizon_role_by_candidate_id=tuple(sorted(role_items)),
            )
            proof = EanMergeOrderProof(
                service_fifo=True,
                skip_fifo=True,
                outgoing_corridor_fifo=True,
                predecessor_complete=True,
                horizon_complete=True,
                reasons=(
                    "one Service and one Skip route reconverge at one Exit Switch",
                    "physical contract forbids overtaking on either branch",
                    "one deterministic Rope continuation transports output order",
                    "unmatched finite-horizon predecessors are explicit boundaries",
                ),
            )
            outgoing_corridor_id = _corridor_id(service)
            previous_position = (position - 1) % len(pattern.state_ids)
            previous_options = tuple(
                option_by_id[option_id]
                for option_id in pattern.route_option_ids_by_position[
                    previous_position
                ]
            )
            incoming_corridors = {_corridor_id(option) for option in previous_options}
            if len(incoming_corridors) != 1:
                raise NotImplementedError(
                    f"merge state {state_id!r} has no unique incoming corridor"
                )
            family = EanMergeFamily(
                id=family_id,
                state_id=state_id,
                station_id=service.station_id,
                exit_checkpoint_id=checkpoint.id,
                incoming_corridor_id=next(iter(incoming_corridors)),
                outgoing_corridor_id=outgoing_corridor_id,
                service_option_id=service.id,
                skip_option_id=skip.id,
                sequence_block_ids=(block_id,),
                headway_rule_id=rule_id_by_checkpoint_id[checkpoint.id],
                proof=proof,
            )
            family.validate()
            block.validate()
            families.append(family)
            blocks.append(block)
            covered.update(block.candidate_ids)

        domain = EanMergeSequenceDomain(
            families=tuple(sorted(families, key=lambda item: item.id)),
            sequence_blocks=tuple(sorted(blocks, key=lambda item: item.id)),
            covered_candidate_ids=tuple(sorted(covered)),
            eager_fallback_candidate_ids=tuple(sorted(all_exit_candidates - covered)),
        )
        domain.validate()
        return domain


def _exit_checkpoint_by_state(
    checkpoints: tuple[HeadwayCheckpointDefinition, ...],
) -> dict[str, HeadwayCheckpointDefinition]:
    result: dict[str, HeadwayCheckpointDefinition] = {}
    for checkpoint in checkpoints:
        if checkpoint.kind is not HeadwayCheckpointKind.EXIT_SWITCH:
            continue
        if checkpoint.switch_id in result:
            raise ValueError(
                f"state {checkpoint.switch_id!r} has multiple EXIT_SWITCH checkpoints"
            )
        result[checkpoint.switch_id] = checkpoint
    return result


def _candidate_checkpoint_kind(
    candidate: HeadwayCandidate,
    checkpoint_by_id: dict[str, HeadwayCheckpointDefinition],
) -> HeadwayCheckpointKind:
    checkpoint = checkpoint_by_id.get(candidate.checkpoint_id)
    if checkpoint is None:
        raise ValueError(
            f"candidate references unknown checkpoint {candidate.checkpoint_id!r}"
        )
    return checkpoint.kind


def _unique_behavior_option(
    options: tuple[EanRouteOption, ...],
    behavior: EanPassengerBehavior,
    state_id: str,
    *,
    required: bool,
) -> EanRouteOption | None:
    matches = tuple(
        option for option in options if option.passenger_behavior is behavior
    )
    if not matches and not required:
        return None
    if len(matches) != 1:
        raise NotImplementedError(
            f"merge sequences require one {behavior.value} option at {state_id!r}; "
            f"found {len(matches)}"
        )
    return matches[0]


def _corridor_id(option: EanRouteOption) -> str:
    if not option.continuation_segment_ids:
        raise ValueError(f"route option {option.id!r} has no continuation corridor")
    return "corridor::" + "::".join(option.continuation_segment_ids)


def _predecessor_visit_key(
    key: tuple[int, int],
    visit_by_key: dict[tuple[int, int], SwitchVisitDefinition],
) -> tuple[int, int] | None:
    cabin_id, visit_index = key
    if visit_index <= 0:
        return None
    predecessor = (cabin_id, visit_index - 1)
    return predecessor if predecessor in visit_by_key else None


def _successor_visit_key(
    key: tuple[int, int],
    visit_by_key: dict[tuple[int, int], SwitchVisitDefinition],
) -> tuple[int, int] | None:
    cabin_id, visit_index = key
    successor = (cabin_id, visit_index + 1)
    return successor if successor in visit_by_key else None


def _horizon_role(
    *,
    has_predecessor: bool,
    has_successor: bool,
) -> EanMergeHorizonRole:
    if has_predecessor and has_successor:
        return EanMergeHorizonRole.INTERIOR
    if not has_predecessor and not has_successor:
        return EanMergeHorizonRole.INITIAL_AND_TERMINAL_BOUNDARY
    if not has_predecessor:
        return EanMergeHorizonRole.INITIAL_BOUNDARY
    return EanMergeHorizonRole.TERMINAL_BOUNDARY


def _validate_unique_count(
    label: str,
    mapping: dict[object, object],
    values: tuple[object, ...],
) -> None:
    if len(mapping) != len(values):
        raise ValueError(f"duplicate {label} values")


def _require_id(label: str, value: str) -> None:
    if not value.strip():
        raise ValueError(f"{label} must be nonempty")
