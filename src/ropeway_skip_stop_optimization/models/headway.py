from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
import math


class HeadwayEvidenceKind(StrEnum):
    LITERATURE = "literature"
    MANUFACTURER = "manufacturer"
    EXPERIMENTAL = "experimental"
    ENGINEERING_INPUT = "engineering_input"


@dataclass(frozen=True)
class HeadwayParameterProvenance:
    parameter_name: str
    source_id: str
    evidence_kind: HeadwayEvidenceKind
    note: str = ""

    def validate(self) -> None:
        if not self.parameter_name or not self.source_id:
            raise ValueError("headway parameter provenance needs nonempty names")
        if not isinstance(self.evidence_kind, HeadwayEvidenceKind):
            raise ValueError("headway parameter provenance needs a valid evidence kind")


@dataclass(frozen=True)
class HeadwayPhysicalParameters:
    service_clearance_m: float
    rope_clearance_m: float
    merge_clearance_m: float
    cabin_height_m: float
    attachment_to_cabin_roof_m: float
    rope_sway_angle_rad: float
    emergency_merge_sway_angle_rad: float
    control_delay_seconds: float
    emergency_deceleration_m_per_s2: float
    provenance: tuple[HeadwayParameterProvenance, ...] = ()

    def validate(self) -> None:
        for name in (
            "service_clearance_m",
            "rope_clearance_m",
            "merge_clearance_m",
            "control_delay_seconds",
        ):
            _require_finite_nonnegative(name, getattr(self, name))
        for name in (
            "cabin_height_m",
            "attachment_to_cabin_roof_m",
            "emergency_deceleration_m_per_s2",
        ):
            _require_finite_positive(name, getattr(self, name))
        for name in (
            "rope_sway_angle_rad",
            "emergency_merge_sway_angle_rad",
        ):
            value = getattr(self, name)
            if not math.isfinite(value) or not 0 <= value < math.pi / 2:
                raise ValueError(f"{name} must lie in [0, pi/2)")
        _validate_provenance(self.provenance)

    @property
    def attachment_to_lowest_envelope_m(self) -> float:
        """Vertical attachment-point distance used by the sway envelope.

        This geometric distance is deliberately distinct from the reduced
        pendulum length used by a carrier-dynamics model.
        """

        return self.attachment_to_cabin_roof_m + self.cabin_height_m


@dataclass(frozen=True)
class ConventionalQuickSwitchDesign:
    manufacturer_vehicle_interval_seconds: float

    def validate(self) -> None:
        _require_finite_positive(
            "manufacturer_vehicle_interval_seconds",
            self.manufacturer_vehicle_interval_seconds,
        )


@dataclass(frozen=True)
class DefaultBypassStopOnFaultDesign:
    mechanical_service_cycle_seconds: float
    service_resource_id: str

    def validate(self) -> None:
        _require_finite_positive(
            "mechanical_service_cycle_seconds",
            self.mechanical_service_cycle_seconds,
        )
        _require_id("service_resource_id", self.service_resource_id)


@dataclass(frozen=True)
class FailSafeDiversionDesign:
    mechanical_service_cycle_seconds: float
    detection_seconds: float
    diversion_seconds: float
    safety_path_segment_ids: tuple[str, ...]
    service_resource_id: str

    def validate(self) -> None:
        _require_finite_positive(
            "mechanical_service_cycle_seconds",
            self.mechanical_service_cycle_seconds,
        )
        _require_finite_nonnegative("detection_seconds", self.detection_seconds)
        _require_finite_nonnegative("diversion_seconds", self.diversion_seconds)
        if not self.safety_path_segment_ids:
            raise ValueError("fail-safe diversion needs a safety path")
        if len(set(self.safety_path_segment_ids)) != len(self.safety_path_segment_ids):
            raise ValueError("fail-safe safety path segment ids must be unique")
        for segment_id in self.safety_path_segment_ids:
            _require_id("safety path segment id", segment_id)
        _require_id("service_resource_id", self.service_resource_id)


@dataclass(frozen=True)
class MandatoryServiceStationDesign:
    guaranteed_vehicle_interval_seconds: float
    service_resource_id: str

    def validate(self) -> None:
        _require_finite_positive(
            "guaranteed_vehicle_interval_seconds",
            self.guaranteed_vehicle_interval_seconds,
        )
        _require_id("service_resource_id", self.service_resource_id)


type StationMechanismDesign = (
    ConventionalQuickSwitchDesign
    | DefaultBypassStopOnFaultDesign
    | FailSafeDiversionDesign
    | MandatoryServiceStationDesign
)


@dataclass(frozen=True)
class StationMechanismAssignment:
    exit_switch_id: str
    design: StationMechanismDesign

    def validate(self) -> None:
        _require_id("station mechanism exit_switch_id", self.exit_switch_id)
        self.design.validate()


@dataclass(frozen=True)
class HeadwayDesign:
    physical: HeadwayPhysicalParameters
    station_mechanisms: tuple[StationMechanismAssignment, ...]
    provenance: tuple[HeadwayParameterProvenance, ...] = ()

    def validate(self) -> None:
        self.physical.validate()
        if not self.station_mechanisms:
            raise ValueError("headway design needs station mechanism assignments")
        exit_ids = [item.exit_switch_id for item in self.station_mechanisms]
        if len(exit_ids) != len(set(exit_ids)):
            raise ValueError("headway design exit switch assignments must be unique")
        for assignment in self.station_mechanisms:
            assignment.validate()
        _validate_provenance(self.provenance)

    def mechanism_for_exit_switch(self, exit_switch_id: str) -> StationMechanismDesign:
        matches = tuple(
            item.design
            for item in self.station_mechanisms
            if item.exit_switch_id == exit_switch_id
        )
        if len(matches) != 1:
            raise ValueError(
                f"headway design has no unique mechanism for exit switch "
                f"{exit_switch_id!r}"
            )
        return matches[0]


class HeadwayRouteBehavior(StrEnum):
    BYPASS = "bypass"
    SERVICE = "service"


class HeadwayRuleKind(StrEnum):
    CONSTANT = "constant"
    LEADER_BEHAVIOR = "leader_behavior"


@dataclass(frozen=True)
class ConstantHeadwayRule:
    id: str
    seconds: float
    kind: HeadwayRuleKind = HeadwayRuleKind.CONSTANT

    @property
    def minimum_seconds(self) -> float:
        return self.seconds

    @property
    def maximum_seconds(self) -> float:
        return self.seconds

    def required_seconds(
        self,
        leader: HeadwayRouteBehavior,
        follower: HeadwayRouteBehavior,
    ) -> float:
        del leader, follower
        return self.seconds

    def validate(self) -> None:
        _require_id("headway rule id", self.id)
        _require_finite_positive("constant headway seconds", self.seconds)


@dataclass(frozen=True)
class LeaderBehaviorHeadwayRule:
    id: str
    bypass_leader_seconds: float
    service_leader_seconds: float
    kind: HeadwayRuleKind = HeadwayRuleKind.LEADER_BEHAVIOR

    @property
    def minimum_seconds(self) -> float:
        return min(self.bypass_leader_seconds, self.service_leader_seconds)

    @property
    def maximum_seconds(self) -> float:
        return max(self.bypass_leader_seconds, self.service_leader_seconds)

    def required_seconds(
        self,
        leader: HeadwayRouteBehavior,
        follower: HeadwayRouteBehavior,
    ) -> float:
        del follower
        return (
            self.service_leader_seconds
            if leader is HeadwayRouteBehavior.SERVICE
            else self.bypass_leader_seconds
        )

    def validate(self) -> None:
        _require_id("headway rule id", self.id)
        _require_finite_positive(
            "bypass leader headway seconds", self.bypass_leader_seconds
        )
        _require_finite_positive(
            "service leader headway seconds", self.service_leader_seconds
        )


type HeadwayRule = ConstantHeadwayRule | LeaderBehaviorHeadwayRule


class DerivedHeadwayResourceKind(StrEnum):
    PLATFORM_ENTRY = "platform_entry"
    PLATFORM_EXIT = "platform_exit"
    EXIT_SWITCH = "exit_switch"
    SERVICE_MECHANISM = "service_mechanism"


class HeadwayDominanceProofKind(StrEnum):
    """Machine-checkable proof templates used by the exact reducer."""

    FIXED_OFFSET = "fixed_offset"
    WAIT_OCCUPANCY_FIXED_SUFFIX = "wait_occupancy_fixed_suffix"


@dataclass(frozen=True)
class DerivedHeadwayResource:
    id: str
    state_id: str
    exit_switch_id: str
    station_id: str
    kind: DerivedHeadwayResourceKind
    rule_id: str
    applies_to_service: bool
    applies_to_bypass: bool
    physical_resource_id: str | None = None

    def validate(self) -> None:
        for label, value in (
            ("derived headway resource id", self.id),
            ("derived headway resource state_id", self.state_id),
            ("derived headway resource exit_switch_id", self.exit_switch_id),
            ("derived headway resource station_id", self.station_id),
            ("derived headway resource rule_id", self.rule_id),
        ):
            _require_id(label, value)
        if not self.applies_to_service and not self.applies_to_bypass:
            raise ValueError("derived resource must apply to a route behavior")
        if self.physical_resource_id is not None:
            _require_id("derived physical resource id", self.physical_resource_id)


@dataclass(frozen=True)
class HeadwayResourceDominanceCertificate:
    dominated_resource_id: str
    dominating_resource_id: str
    behavior_pairs: tuple[
        tuple[HeadwayRouteBehavior, HeadwayRouteBehavior], ...
    ]
    minimum_implied_headway_seconds: float
    required_headway_seconds: float
    proof_kind: HeadwayDominanceProofKind
    retain_at_initial_boundary: bool

    @property
    def slack_seconds(self) -> float:
        return (
            self.minimum_implied_headway_seconds
            - self.required_headway_seconds
        )

    def validate(self) -> None:
        _require_id("dominated resource id", self.dominated_resource_id)
        _require_id("dominating resource id", self.dominating_resource_id)
        if self.dominated_resource_id == self.dominating_resource_id:
            raise ValueError("a headway resource cannot dominate itself")
        if not self.behavior_pairs:
            raise ValueError("headway dominance needs at least one behavior pair")
        if len(self.behavior_pairs) != len(set(self.behavior_pairs)):
            raise ValueError("headway dominance behavior pairs must be unique")
        for leader, follower in self.behavior_pairs:
            if not isinstance(leader, HeadwayRouteBehavior) or not isinstance(
                follower, HeadwayRouteBehavior
            ):
                raise ValueError("headway dominance needs valid route behaviors")
        _require_finite_positive(
            "minimum implied headway", self.minimum_implied_headway_seconds
        )
        _require_finite_positive(
            "required dominated headway", self.required_headway_seconds
        )
        if self.slack_seconds < -1e-9:
            raise ValueError("headway dominance certificate has negative slack")
        if not isinstance(self.proof_kind, HeadwayDominanceProofKind):
            raise ValueError("headway dominance certificate needs a proof kind")


@dataclass(frozen=True)
class EffectiveHeadwayPolicy:
    """Exact solver view of a complete :class:`DerivedHeadwayPolicy`."""

    rules: tuple[HeadwayRule, ...]
    resource_requirements: tuple[DerivedHeadwayResource, ...]
    dominance_certificates: tuple[HeadwayResourceDominanceCertificate, ...]
    component_resource_ids_by_effective_id: dict[str, tuple[str, ...]]
    reduction_version: str = "headway_resource_reduction_v1"

    def validate(self) -> None:
        if not self.rules or not self.resource_requirements:
            raise ValueError("effective headway policy needs rules and resources")
        rule_ids = [rule.id for rule in self.rules]
        if len(rule_ids) != len(set(rule_ids)):
            raise ValueError("effective headway rule ids must be unique")
        for rule in self.rules:
            rule.validate()
        resource_ids = [resource.id for resource in self.resource_requirements]
        if len(resource_ids) != len(set(resource_ids)):
            raise ValueError("effective headway resource ids must be unique")
        known_rule_ids = set(rule_ids)
        for resource in self.resource_requirements:
            resource.validate()
            if resource.rule_id not in known_rule_ids:
                raise ValueError(
                    f"effective resource {resource.id!r} references unknown rule "
                    f"{resource.rule_id!r}"
                )
        if set(self.component_resource_ids_by_effective_id) != set(resource_ids):
            raise ValueError(
                "effective headway component mapping must cover every resource"
            )
        all_components: list[str] = []
        for effective_id, components in (
            self.component_resource_ids_by_effective_id.items()
        ):
            if not components or len(components) != len(set(components)):
                raise ValueError(
                    f"effective resource {effective_id!r} needs unique components"
                )
            all_components.extend(components)
        if len(all_components) != len(set(all_components)):
            raise ValueError("physical headway components may not be merged twice")
        dominated_ids = {
            certificate.dominated_resource_id
            for certificate in self.dominance_certificates
        }
        if len(dominated_ids) != len(self.dominance_certificates):
            raise ValueError("headway resources may only be dominated once")
        if dominated_ids & set(all_components):
            raise ValueError("dominated resources cannot remain effective components")
        for certificate in self.dominance_certificates:
            certificate.validate()
            if certificate.dominating_resource_id not in set(all_components):
                raise ValueError(
                    "dominance certificate must reference an effective component"
                )
        _require_id("headway reduction version", self.reduction_version)

    def rule(self, rule_id: str) -> HeadwayRule:
        matches = tuple(rule for rule in self.rules if rule.id == rule_id)
        if len(matches) != 1:
            raise ValueError(f"effective headway policy has no unique rule {rule_id!r}")
        return matches[0]

    def resource(self, resource_id: str) -> DerivedHeadwayResource:
        matches = tuple(
            resource
            for resource in self.resource_requirements
            if resource.id == resource_id
        )
        if len(matches) != 1:
            raise ValueError(
                f"effective headway policy has no unique resource {resource_id!r}"
            )
        return matches[0]


class DerivedSpatialRole(StrEnum):
    ROPE = "rope"
    SERVICE = "service"


@dataclass(frozen=True)
class DerivedSpatialSpacing:
    role: DerivedSpatialRole
    spacing_m: float

    def validate(self) -> None:
        _require_finite_positive("derived spatial spacing", self.spacing_m)


@dataclass(frozen=True)
class DerivedQuantity:
    id: str
    value: float
    unit: str
    formula: str
    evidence_kind: HeadwayEvidenceKind

    def validate(self) -> None:
        _require_id("derived quantity id", self.id)
        _require_id("derived quantity unit", self.unit)
        _require_id("derived quantity formula", self.formula)
        if not math.isfinite(self.value):
            raise ValueError("derived quantity value must be finite")


@dataclass(frozen=True)
class DerivedHeadwayPolicy:
    rules: tuple[HeadwayRule, ...]
    resource_requirements: tuple[DerivedHeadwayResource, ...]
    spatial_spacings: tuple[DerivedSpatialSpacing, ...]
    derived_quantities: tuple[DerivedQuantity, ...]
    provenance: tuple[HeadwayParameterProvenance, ...]
    legacy: bool = False

    def validate(self) -> None:
        if not self.rules or not self.resource_requirements:
            raise ValueError("derived headway policy needs rules and resources")
        rule_ids = [rule.id for rule in self.rules]
        if len(rule_ids) != len(set(rule_ids)):
            raise ValueError("derived headway rule ids must be unique")
        for rule in self.rules:
            rule.validate()
        resource_ids = [item.id for item in self.resource_requirements]
        if len(resource_ids) != len(set(resource_ids)):
            raise ValueError("derived headway resource ids must be unique")
        for resource in self.resource_requirements:
            resource.validate()
            if resource.rule_id not in set(rule_ids):
                raise ValueError(
                    f"derived resource {resource.id!r} references unknown rule "
                    f"{resource.rule_id!r}"
                )
        roles = [item.role for item in self.spatial_spacings]
        if len(roles) != len(set(roles)):
            raise ValueError("derived spatial spacing roles must be unique")
        for spacing in self.spatial_spacings:
            spacing.validate()
        quantity_ids = [item.id for item in self.derived_quantities]
        if len(quantity_ids) != len(set(quantity_ids)):
            raise ValueError("derived quantity ids must be unique")
        for quantity in self.derived_quantities:
            quantity.validate()
        _validate_provenance(self.provenance)

    def rule(self, rule_id: str) -> HeadwayRule:
        matches = tuple(rule for rule in self.rules if rule.id == rule_id)
        if len(matches) != 1:
            raise ValueError(f"headway policy has no unique rule {rule_id!r}")
        return matches[0]

    def resource(self, resource_id: str) -> DerivedHeadwayResource:
        matches = tuple(
            resource
            for resource in self.resource_requirements
            if resource.id == resource_id
        )
        if len(matches) != 1:
            raise ValueError(f"headway policy has no unique resource {resource_id!r}")
        return matches[0]

    def spatial_spacing(self, role: DerivedSpatialRole) -> float:
        matches = tuple(
            item.spacing_m for item in self.spatial_spacings if item.role is role
        )
        if len(matches) != 1:
            raise ValueError(f"headway policy has no unique spacing for {role.value}")
        return matches[0]

    @property
    def maximum_headway_seconds(self) -> float:
        return max(rule.maximum_seconds for rule in self.rules)

    @property
    def has_leader_behavior_rules(self) -> bool:
        return any(isinstance(rule, LeaderBehaviorHeadwayRule) for rule in self.rules)


def _validate_provenance(
    provenance: tuple[HeadwayParameterProvenance, ...],
) -> None:
    names = [item.parameter_name for item in provenance]
    if len(names) != len(set(names)):
        raise ValueError("headway provenance parameter names must be unique")
    for item in provenance:
        item.validate()


def _require_id(label: str, value: str) -> None:
    if not value:
        raise ValueError(f"{label} must be nonempty")


def _require_finite_positive(label: str, value: float) -> None:
    if not math.isfinite(value) or value <= 0:
        raise ValueError(f"{label} must be finite and positive")


def _require_finite_nonnegative(label: str, value: float) -> None:
    if not math.isfinite(value) or value < 0:
        raise ValueError(f"{label} must be finite and nonnegative")
