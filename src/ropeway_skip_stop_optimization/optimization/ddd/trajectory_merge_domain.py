from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256
import json

from ropeway_skip_stop_optimization.optimization.ddd.models import (
    DddMovementCore,
    DddRouteDecision,
    DddRouteOption,
)
from ropeway_skip_stop_optimization.optimization.ddd.reference import (
    DddReferenceTrajectory,
)
from ropeway_skip_stop_optimization.optimization.ddd.time_ticks import (
    DddTimeTick,
    ddd_seconds_to_tick,
)


@dataclass(frozen=True, slots=True)
class DddTrajectoryMergeProvenance:
    service_fifo: bool
    skip_fifo: bool
    outgoing_corridor_fifo: bool
    service_skip_reconverges: bool
    reasons: tuple[str, ...]

    def validate(self) -> None:
        if not all(
            (
                self.service_fifo,
                self.skip_fifo,
                self.outgoing_corridor_fifo,
                self.service_skip_reconverges,
            )
        ):
            raise ValueError("DDD merge provenance is not complete")
        if not self.reasons or tuple(sorted(set(self.reasons))) != self.reasons:
            raise ValueError("DDD merge provenance reasons must be sorted and unique")


@dataclass(frozen=True, slots=True)
class DddTrajectoryMergeFamily:
    id: str
    state_id: str
    station_id: str
    target_state_id: str
    service_route_option_id: str
    skip_route_option_id: str
    service_only_resource_ids: tuple[str, ...]
    skip_only_resource_ids: tuple[str, ...]
    shared_merge_resource_ids: tuple[str, ...]
    outgoing_common_resource_ids: tuple[str, ...]
    provenance: DddTrajectoryMergeProvenance

    @property
    def protected_resource_ids(self) -> tuple[str, ...]:
        return tuple(
            sorted(
                {
                    *self.shared_merge_resource_ids,
                    *self.outgoing_common_resource_ids,
                }
            )
        )

    def validate(self) -> None:
        if not all(
            (
                self.id,
                self.state_id,
                self.station_id,
                self.target_state_id,
                self.service_route_option_id,
                self.skip_route_option_id,
            )
        ):
            raise ValueError("DDD merge family identifiers are required")
        if self.service_route_option_id == self.skip_route_option_id:
            raise ValueError("DDD merge family routes must differ")
        for values in (
            self.service_only_resource_ids,
            self.skip_only_resource_ids,
            self.shared_merge_resource_ids,
            self.outgoing_common_resource_ids,
        ):
            if tuple(sorted(set(values))) != values:
                raise ValueError("DDD merge resource IDs must be sorted and unique")
        branch_only = set(self.service_only_resource_ids) | set(
            self.skip_only_resource_ids
        )
        if branch_only & set(self.shared_merge_resource_ids):
            raise ValueError("DDD branch-only and shared merge resources overlap")
        self.provenance.validate()


@dataclass(frozen=True, order=True, slots=True)
class DddTrajectoryMergeOccurrence:
    family_id: str
    cabin_id: int
    visit_index: int
    decision: DddRouteDecision
    switch_tick: DddTimeTick
    next_switch_tick: DddTimeTick
    merge_entry_tick: DddTimeTick
    protected_resource_ids: tuple[str, ...]

    def validate(self) -> None:
        if not self.family_id:
            raise ValueError("DDD merge occurrence family ID is required")
        if self.cabin_id < 0 or self.visit_index < 0:
            raise ValueError("DDD merge occurrence indices are invalid")
        if not isinstance(self.decision, DddRouteDecision):
            raise ValueError("DDD merge occurrence decision is invalid")
        if (
            self.switch_tick < 0
            or self.next_switch_tick <= self.switch_tick
            or self.merge_entry_tick < self.switch_tick
        ):
            raise ValueError("DDD merge occurrence time interval is invalid")
        if tuple(sorted(set(self.protected_resource_ids))) != (
            self.protected_resource_ids
        ):
            raise ValueError("DDD merge occurrence resources are not normalized")


@dataclass(frozen=True, slots=True)
class DddTrajectoryMergeDomain:
    families: tuple[DddTrajectoryMergeFamily, ...]

    def validate(self) -> None:
        family_ids = tuple(family.id for family in self.families)
        if tuple(sorted(set(family_ids))) != family_ids:
            raise ValueError("DDD merge families must have sorted unique IDs")
        route_ids: set[str] = set()
        for family in self.families:
            family.validate()
            current = {
                family.service_route_option_id,
                family.skip_route_option_id,
            }
            if route_ids & current:
                raise ValueError("DDD route option belongs to multiple merge families")
            route_ids |= current

    @property
    def by_route_option_id(self) -> dict[str, DddTrajectoryMergeFamily]:
        return {
            route_id: family
            for family in self.families
            for route_id in (
                family.service_route_option_id,
                family.skip_route_option_id,
            )
        }

    @property
    def protected_resource_ids(self) -> tuple[str, ...]:
        return tuple(
            sorted(
                {
                    resource_id
                    for family in self.families
                    for resource_id in family.protected_resource_ids
                }
            )
        )

    @property
    def fingerprint(self) -> str:
        self.validate()
        payload = [
            {
                "id": family.id,
                "state": family.state_id,
                "station": family.station_id,
                "target": family.target_state_id,
                "service": family.service_route_option_id,
                "skip": family.skip_route_option_id,
                "service_only": family.service_only_resource_ids,
                "skip_only": family.skip_only_resource_ids,
                "shared": family.shared_merge_resource_ids,
                "outgoing": family.outgoing_common_resource_ids,
                "reasons": family.provenance.reasons,
            }
            for family in self.families
        ]
        return sha256(
            json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
        ).hexdigest()

    def occurrences(
        self,
        trajectory: DddReferenceTrajectory,
    ) -> tuple[DddTrajectoryMergeOccurrence, ...]:
        by_route = self.by_route_option_id
        visit_by_index = {visit.visit_index: visit for visit in trajectory.visits}
        occurrences = []
        for visit in trajectory.visits:
            family = by_route.get(visit.route_option_id)
            if family is None:
                continue
            next_visit = visit_by_index.get(visit.visit_index + 1)
            protected_occurrences = visit.resource_occurrences
            if next_visit is not None and next_visit.state_id == family.target_state_id:
                protected_occurrences = (
                    *protected_occurrences,
                    *next_visit.resource_occurrences,
                )
            occurrence = DddTrajectoryMergeOccurrence(
                family_id=family.id,
                cabin_id=trajectory.cabin_id,
                visit_index=visit.visit_index,
                decision=visit.decision,
                switch_tick=ddd_seconds_to_tick(visit.switch_time_seconds),
                next_switch_tick=ddd_seconds_to_tick(visit.next_switch_time_seconds),
                merge_entry_tick=min(
                    (
                        ddd_seconds_to_tick(item.follower_enter_time_seconds)
                        for item in protected_occurrences
                        if item.resource_id in family.protected_resource_ids
                    ),
                    default=ddd_seconds_to_tick(visit.next_switch_time_seconds),
                ),
                protected_resource_ids=tuple(
                    sorted(
                        {
                            item.resource_id
                            for item in protected_occurrences
                            if item.resource_id in family.protected_resource_ids
                        }
                    )
                ),
            )
            occurrence.validate()
            occurrences.append(occurrence)
        return tuple(occurrences)


@dataclass(frozen=True, slots=True)
class DddTrajectoryMergeDomainBuilder:
    """Derive exact current Stop/Skip reconvergence families from the DDD core."""

    def build(self, core: DddMovementCore) -> DddTrajectoryMergeDomain:
        core.validate()
        families: list[DddTrajectoryMergeFamily] = []
        for state_id, options in sorted(core.route_options_by_state_id.items()):
            stop_options = tuple(
                option for option in options if option.decision is DddRouteDecision.STOP
            )
            skip_options = tuple(
                option for option in options if option.decision is DddRouteDecision.SKIP
            )
            if not stop_options or not skip_options:
                continue
            if len(stop_options) != 1 or len(skip_options) != 1:
                raise NotImplementedError(
                    "merge-aware DDD currently requires one Stop and one Skip "
                    f"route at state {state_id!r}"
                )
            service = stop_options[0]
            skip = skip_options[0]
            if (
                service.to_state_id != skip.to_state_id
                or service.station_id != skip.station_id
            ):
                raise NotImplementedError(
                    "dynamic non-reconverging DDD routing is not supported: "
                    f"state={state_id!r}"
                )
            service_resources = _resource_ids(service)
            skip_resources = _resource_ids(skip)
            shared = service_resources & skip_resources
            outgoing = core.route_options_by_state_id.get(service.to_state_id, ())
            outgoing_common = _common_resource_ids(outgoing)
            family_id = _merge_family_id(
                state_id=state_id,
                station_id=service.station_id,
                target_state_id=service.to_state_id,
                service_route_option_id=service.id,
                skip_route_option_id=skip.id,
            )
            family = DddTrajectoryMergeFamily(
                id=family_id,
                state_id=state_id,
                station_id=service.station_id,
                target_state_id=service.to_state_id,
                service_route_option_id=service.id,
                skip_route_option_id=skip.id,
                service_only_resource_ids=tuple(sorted(service_resources - shared)),
                skip_only_resource_ids=tuple(sorted(skip_resources - shared)),
                shared_merge_resource_ids=tuple(sorted(shared)),
                outgoing_common_resource_ids=tuple(sorted(outgoing_common)),
                provenance=DddTrajectoryMergeProvenance(
                    service_fifo=True,
                    skip_fifo=True,
                    outgoing_corridor_fifo=True,
                    service_skip_reconverges=True,
                    reasons=(
                        "deterministic_common_target_state",
                        "no_overtaking_within_physical_branch",
                        "shared_outgoing_corridor",
                    ),
                ),
            )
            family.validate()
            families.append(family)
        domain = DddTrajectoryMergeDomain(
            tuple(sorted(families, key=lambda family: family.id))
        )
        domain.validate()
        return domain


def _resource_ids(option: DddRouteOption) -> set[str]:
    return {usage.resource_id for usage in option.resource_usages}


def _common_resource_ids(options: tuple[DddRouteOption, ...]) -> set[str]:
    if not options:
        return set()
    common = _resource_ids(options[0])
    for option in options[1:]:
        common &= _resource_ids(option)
    return common


def _merge_family_id(
    *,
    state_id: str,
    station_id: str,
    target_state_id: str,
    service_route_option_id: str,
    skip_route_option_id: str,
) -> str:
    payload = (
        state_id,
        station_id,
        target_state_id,
        service_route_option_id,
        skip_route_option_id,
    )
    digest = sha256(
        json.dumps(payload, separators=(",", ":")).encode()
    ).hexdigest()
    return f"ddd_merge_family::{digest}"
