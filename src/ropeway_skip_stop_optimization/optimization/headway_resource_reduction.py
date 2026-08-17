from __future__ import annotations

from dataclasses import dataclass, replace
from enum import StrEnum
import math

from ropeway_skip_stop_optimization.models import (
    ConstantHeadwayRule,
    DerivedHeadwayPolicy,
    DerivedHeadwayResource,
    DerivedHeadwayResourceKind,
    EffectiveHeadwayPolicy,
    HeadwayDominanceProofKind,
    HeadwayResourceDominanceCertificate,
    HeadwayRouteBehavior,
    LeaderBehaviorHeadwayRule,
)
from ropeway_skip_stop_optimization.optimization.ean.models import (
    SkipStopTiming,
    StationEanConfig,
    StationWaitingMode,
)
from ropeway_skip_stop_optimization.optimization.ean.network import (
    EanMovementNetwork,
    EanPassengerBehavior,
)


class HeadwayResourceReductionMode(StrEnum):
    EXACT = "exact"
    DISABLED = "disabled"


@dataclass(frozen=True)
class HeadwayResourceReduction:
    """Remove or coalesce resources only through explicit local proofs.

    Version 1 deliberately recognizes a small set of templates.  A resource
    remains present whenever the timing, activation, routing, or shared-resource
    provenance falls outside those templates.
    """

    tolerance_seconds: float = 1e-9

    def reduce(
        self,
        *,
        policy: DerivedHeadwayPolicy,
        network: EanMovementNetwork,
        timings: tuple[SkipStopTiming, ...],
        station_configs: tuple[StationEanConfig, ...],
        mode: HeadwayResourceReductionMode = HeadwayResourceReductionMode.EXACT,
    ) -> EffectiveHeadwayPolicy:
        policy.validate()
        network.validate()
        if self.tolerance_seconds < 0:
            raise ValueError("headway dominance tolerance must be nonnegative")
        if not isinstance(mode, HeadwayResourceReductionMode):
            raise ValueError("invalid headway resource reduction mode")
        if mode is HeadwayResourceReductionMode.DISABLED or policy.legacy:
            return _identity_policy(policy)

        timing_by_state = {timing.switch_id: timing for timing in timings}
        config_by_station = {
            config.station_id: config for config in station_configs
        }
        if len(timing_by_state) != len(timings):
            raise ValueError("headway reduction timings must have unique state ids")
        if len(config_by_station) != len(station_configs):
            raise ValueError("headway reduction station configs must be unique")
        physical_resource_counts: dict[str, int] = {}
        for resource in policy.resource_requirements:
            if resource.physical_resource_id is not None:
                physical_resource_counts[resource.physical_resource_id] = (
                    physical_resource_counts.get(resource.physical_resource_id, 0)
                    + 1
                )

        resources_by_state_kind = {
            (resource.state_id, resource.kind): resource
            for resource in policy.resource_requirements
        }
        certificates: list[HeadwayResourceDominanceCertificate] = []
        dominated_ids: set[str] = set()
        for target in policy.resource_requirements:
            if target.kind is not DerivedHeadwayResourceKind.SERVICE_MECHANISM:
                continue
            if not _is_local_service_resource(
                target, physical_resource_counts=physical_resource_counts
            ):
                continue
            timing = timing_by_state.get(target.state_id)
            station_config = config_by_station.get(target.station_id)
            if timing is None or station_config is None:
                continue
            if not _has_one_deterministic_service_path(network, target.state_id):
                continue
            proof = _dominating_platform_resource(
                target=target,
                station_config=station_config,
                resources_by_state_kind=resources_by_state_kind,
            )
            if proof is None:
                continue
            dominator, proof_kind = proof
            # The recognized templates have rho=0.  NO_WAITING has identical
            # fixed offsets for both service routes.  END_OF_PLATFORM_WAIT uses
            # leader-clear/follower-enter occupancy; follower waiting can only
            # increase the later exit-switch gap.
            implied = policy.rule(dominator.rule_id).required_seconds(
                HeadwayRouteBehavior.SERVICE,
                HeadwayRouteBehavior.SERVICE,
            )
            required = policy.rule(target.rule_id).required_seconds(
                HeadwayRouteBehavior.SERVICE,
                HeadwayRouteBehavior.SERVICE,
            )
            if implied + self.tolerance_seconds < required:
                continue
            certificate = HeadwayResourceDominanceCertificate(
                dominated_resource_id=target.id,
                dominating_resource_id=dominator.id,
                behavior_pairs=((
                    HeadwayRouteBehavior.SERVICE,
                    HeadwayRouteBehavior.SERVICE,
                ),),
                minimum_implied_headway_seconds=implied,
                required_headway_seconds=required,
                proof_kind=proof_kind,
                retain_at_initial_boundary=True,
            )
            certificate.validate()
            certificates.append(certificate)
            dominated_ids.add(target.id)

        retained = tuple(
            resource
            for resource in policy.resource_requirements
            if resource.id not in dominated_ids
        )
        effective_resources, component_map, added_rules = _coalesce_resources(
            retained,
            policy,
            physical_resource_counts=physical_resource_counts,
            tolerance_seconds=self.tolerance_seconds,
        )
        referenced_rule_ids = {resource.rule_id for resource in effective_resources}
        effective = EffectiveHeadwayPolicy(
            rules=tuple(
                rule
                for rule in (*policy.rules, *added_rules)
                if rule.id in referenced_rule_ids
            ),
            resource_requirements=effective_resources,
            dominance_certificates=tuple(
                sorted(certificates, key=lambda item: item.dominated_resource_id)
            ),
            component_resource_ids_by_effective_id=component_map,
        )
        effective.validate()
        return effective


def _identity_policy(policy: DerivedHeadwayPolicy) -> EffectiveHeadwayPolicy:
    effective = EffectiveHeadwayPolicy(
        rules=policy.rules,
        resource_requirements=policy.resource_requirements,
        dominance_certificates=(),
        component_resource_ids_by_effective_id={
            resource.id: (resource.id,)
            for resource in policy.resource_requirements
        },
    )
    effective.validate()
    return effective


def _is_local_service_resource(
    resource: DerivedHeadwayResource,
    *,
    physical_resource_counts: dict[str, int],
) -> bool:
    return (
        resource.applies_to_service
        and not resource.applies_to_bypass
        and resource.physical_resource_id is not None
        and physical_resource_counts[resource.physical_resource_id] == 1
    )


def _has_one_deterministic_service_path(
    network: EanMovementNetwork,
    state_id: str,
) -> bool:
    service_options = tuple(
        option
        for option in network.route_options
        if option.from_state_id == state_id
        and option.passenger_behavior is EanPassengerBehavior.SERVICE
    )
    bypass_options = tuple(
        option
        for option in network.route_options
        if option.from_state_id == state_id
        and option.passenger_behavior is EanPassengerBehavior.SKIP
    )
    return (
        len(service_options) == 1
        and len(bypass_options) == 1
        and math.isclose(
            service_options[0].minimum_seconds,
            service_options[0].maximum_seconds,
            rel_tol=0.0,
            abs_tol=1e-9,
        )
    )


def _dominating_platform_resource(
    *,
    target: DerivedHeadwayResource,
    station_config: StationEanConfig,
    resources_by_state_kind: dict[
        tuple[str, DerivedHeadwayResourceKind], DerivedHeadwayResource
    ],
) -> tuple[DerivedHeadwayResource, HeadwayDominanceProofKind] | None:
    if station_config.waiting_mode is StationWaitingMode.NO_WAITING:
        kind = DerivedHeadwayResourceKind.PLATFORM_ENTRY
        proof_kind = HeadwayDominanceProofKind.FIXED_OFFSET
    elif station_config.waiting_mode is StationWaitingMode.END_OF_PLATFORM_WAIT:
        kind = DerivedHeadwayResourceKind.PLATFORM_EXIT
        proof_kind = HeadwayDominanceProofKind.WAIT_OCCUPANCY_FIXED_SUFFIX
    else:
        return None
    dominator = resources_by_state_kind.get((target.state_id, kind))
    if (
        dominator is None
        or not dominator.applies_to_service
        or dominator.applies_to_bypass
    ):
        return None
    return dominator, proof_kind


def _coalesce_resources(
    resources: tuple[DerivedHeadwayResource, ...],
    policy: DerivedHeadwayPolicy,
    *,
    physical_resource_counts: dict[str, int],
    tolerance_seconds: float,
) -> tuple[
    tuple[DerivedHeadwayResource, ...],
    dict[str, tuple[str, ...]],
    tuple[ConstantHeadwayRule | LeaderBehaviorHeadwayRule, ...],
]:
    groups: dict[tuple[object, ...], list[DerivedHeadwayResource]] = {}
    for resource in resources:
        groups.setdefault(_coalescing_signature(resource), []).append(resource)

    result: list[DerivedHeadwayResource] = []
    component_map: dict[str, tuple[str, ...]] = {}
    added_rules: list[ConstantHeadwayRule | LeaderBehaviorHeadwayRule] = []
    for group in groups.values():
        ordered = sorted(group, key=lambda item: (_representative_rank(item), item.id))
        if len(ordered) == 1 or not _group_is_local(ordered, physical_resource_counts):
            for resource in ordered:
                result.append(resource)
                component_map[resource.id] = (resource.id,)
            continue
        representative = ordered[0]
        components = tuple(sorted(resource.id for resource in ordered))
        merged_rule = _maximum_rule(
            tuple(policy.rule(resource.rule_id) for resource in ordered),
            rule_id=f"effective_rule::max::{'+'.join(components)}",
            tolerance_seconds=tolerance_seconds,
        )
        existing = next(
            (
                rule
                for rule in (policy.rule(resource.rule_id) for resource in ordered)
                if _rules_equal(rule, merged_rule, tolerance_seconds)
            ),
            None,
        )
        if existing is None:
            added_rules.append(merged_rule)
            rule_id = merged_rule.id
        else:
            rule_id = existing.id
        effective_resource = replace(representative, rule_id=rule_id)
        result.append(effective_resource)
        component_map[effective_resource.id] = components
    return tuple(result), component_map, tuple(added_rules)


def _coalescing_signature(resource: DerivedHeadwayResource) -> tuple[object, ...]:
    time_expression = (
        "exit_switch_time"
        if resource.kind
        in {
            DerivedHeadwayResourceKind.EXIT_SWITCH,
            DerivedHeadwayResourceKind.SERVICE_MECHANISM,
        }
        else resource.kind.value
    )
    return (
        resource.state_id,
        time_expression,
        resource.applies_to_service,
        resource.applies_to_bypass,
    )


def _group_is_local(
    resources: list[DerivedHeadwayResource],
    physical_resource_counts: dict[str, int],
) -> bool:
    return all(
        resource.physical_resource_id is None
        or physical_resource_counts[resource.physical_resource_id] == 1
        for resource in resources
    )


def _representative_rank(resource: DerivedHeadwayResource) -> int:
    return 0 if resource.kind is DerivedHeadwayResourceKind.EXIT_SWITCH else 1


def _maximum_rule(
    rules: tuple[ConstantHeadwayRule | LeaderBehaviorHeadwayRule, ...],
    *,
    rule_id: str,
    tolerance_seconds: float,
) -> ConstantHeadwayRule | LeaderBehaviorHeadwayRule:
    bypass = max(
        rule.required_seconds(
            HeadwayRouteBehavior.BYPASS, HeadwayRouteBehavior.BYPASS
        )
        for rule in rules
    )
    service = max(
        rule.required_seconds(
            HeadwayRouteBehavior.SERVICE, HeadwayRouteBehavior.BYPASS
        )
        for rule in rules
    )
    if math.isclose(
        bypass,
        service,
        rel_tol=0.0,
        abs_tol=tolerance_seconds,
    ):
        return ConstantHeadwayRule(rule_id, max(bypass, service))
    return LeaderBehaviorHeadwayRule(rule_id, bypass, service)


def _rules_equal(
    first: ConstantHeadwayRule | LeaderBehaviorHeadwayRule,
    second: ConstantHeadwayRule | LeaderBehaviorHeadwayRule,
    tolerance_seconds: float,
) -> bool:
    return all(
        math.isclose(
            first.required_seconds(leader, HeadwayRouteBehavior.BYPASS),
            second.required_seconds(leader, HeadwayRouteBehavior.BYPASS),
            rel_tol=0.0,
            abs_tol=tolerance_seconds,
        )
        for leader in HeadwayRouteBehavior
    )
