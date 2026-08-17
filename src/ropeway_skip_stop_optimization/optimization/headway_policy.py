from __future__ import annotations

from dataclasses import dataclass
import math
from typing import Protocol

from ropeway_skip_stop_optimization.mapping.physical_to_discrete import (
    travel_seconds_for_segment,
)
from ropeway_skip_stop_optimization.models import (
    ConstantHeadwayRule,
    ConventionalQuickSwitchDesign,
    DefaultBypassStopOnFaultDesign,
    DerivedHeadwayPolicy,
    DerivedHeadwayResource,
    DerivedHeadwayResourceKind,
    DerivedQuantity,
    DerivedSpatialRole,
    DerivedSpatialSpacing,
    FailSafeDiversionDesign,
    HeadwayEvidenceKind,
    HeadwayRouteBehavior,
    LeaderBehaviorHeadwayRule,
    MandatoryServiceStationDesign,
    Scenario,
    SpeedProfile,
    SpeedProfileKind,
)
from ropeway_skip_stop_optimization.optimization.ean.models import SkipStopTiming
from ropeway_skip_stop_optimization.optimization.ean.builders.headway_duration_builder import (
    HeadwayDurationBuilder,
)
from ropeway_skip_stop_optimization.optimization.ean.network import (
    EanCirculationPattern,
    EanMovementNetwork,
    EanPassengerBehavior,
)


class HeadwayPolicyBuilder(Protocol):
    def build(
        self,
        scenario: Scenario,
        network: EanMovementNetwork,
        timings: tuple[SkipStopTiming, ...],
        pattern: EanCirculationPattern,
    ) -> DerivedHeadwayPolicy: ...


@dataclass(frozen=True)
class LegacyHeadwayPolicyAdapterBuilder:
    duration_builder: HeadwayDurationBuilder

    def build(
        self,
        scenario: Scenario,
        network: EanMovementNetwork,
        timings: tuple[SkipStopTiming, ...],
        pattern: EanCirculationPattern,
    ) -> DerivedHeadwayPolicy:
        del network, pattern
        if scenario.headway_design is not None:
            raise ValueError(
                "legacy headway durations cannot be combined with a derived "
                "A/B/C headway design"
            )
        durations = self.duration_builder.build(scenario, timings)
        return build_legacy_headway_policy(
            scenario,
            timings,
            station_headway_seconds_by_station_id=(
                durations.station_headway_seconds_by_station_id
            ),
            exit_switch_headway_seconds_by_switch_id=(
                durations.exit_switch_headway_seconds_by_switch_id
            ),
        )


@dataclass(frozen=True)
class PhysicalHeadwayPolicyBuilder:
    speed_tolerance_m_per_s: float = 1e-9

    def build(
        self,
        scenario: Scenario,
        network: EanMovementNetwork,
        timings: tuple[SkipStopTiming, ...],
        pattern: EanCirculationPattern,
    ) -> DerivedHeadwayPolicy:
        scenario.validate()
        network.validate()
        pattern.validate()
        if scenario.headway_design is None:
            return build_legacy_headway_policy(scenario, timings)
        if self.speed_tolerance_m_per_s < 0:
            raise ValueError("headway speed tolerance must be nonnegative")

        design = scenario.headway_design
        physical = design.physical
        segments_by_id = {segment.id: segment for segment in scenario.track_segments}
        options_by_id = {option.id: option for option in network.route_options}
        timing_by_state_id = {timing.switch_id: timing for timing in timings}
        if set(timing_by_state_id) != set(pattern.state_ids):
            raise ValueError("headway policy timings must match the selected pattern")

        rope_spacing = (
            scenario.operating.cabin_length_m
            + 2.0
            * physical.suspension_length_m
            * math.sin(physical.rope_sway_angle_rad)
            + physical.rope_clearance_m
        )
        service_spacing = (
            scenario.operating.cabin_length_m + physical.service_clearance_m
        )
        rope_headway = rope_spacing / scenario.operating.rope_speed_m_per_s
        service_headway = service_spacing / scenario.operating.station_speed_m_per_s

        rules: list[ConstantHeadwayRule | LeaderBehaviorHeadwayRule] = []
        resources: list[DerivedHeadwayResource] = []
        quantities: list[DerivedQuantity] = [
            _quantity(
                "rope_spacing_m",
                rope_spacing,
                "m",
                "L_C + 2*l_H*sin(theta_R) + c_R",
            ),
            _quantity(
                "service_spacing_m",
                service_spacing,
                "m",
                "L_C + c_S",
            ),
            _quantity("rope_headway_seconds", rope_headway, "s", "d_R / v_R"),
            _quantity("service_headway_seconds", service_headway, "s", "d_S / v_S"),
        ]

        for state_id, option_ids in zip(
            pattern.state_ids,
            pattern.route_option_ids_by_position,
            strict=True,
        ):
            timing = timing_by_state_id[state_id]
            if timing.exit_switch_id is None:
                raise ValueError(
                    f"headway design needs the physical exit switch for state {state_id!r}"
                )
            mechanism = design.mechanism_for_exit_switch(timing.exit_switch_id)
            options = tuple(options_by_id[option_id] for option_id in option_ids)
            service_options = tuple(
                option
                for option in options
                if option.passenger_behavior is EanPassengerBehavior.SERVICE
            )
            bypass_options = tuple(
                option
                for option in options
                if option.passenger_behavior is EanPassengerBehavior.SKIP
            )
            if len(service_options) != 1 or len(bypass_options) > 1:
                raise ValueError(
                    f"headway policy requires one service and at most one bypass "
                    f"option at {state_id!r}"
                )
            if (
                isinstance(
                    mechanism,
                    DefaultBypassStopOnFaultDesign | FailSafeDiversionDesign,
                )
                and len(bypass_options) != 1
            ):
                raise ValueError(
                    f"{type(mechanism).__name__} requires a bypass route at "
                    f"{timing.exit_switch_id!r}"
                )
            if isinstance(mechanism, MandatoryServiceStationDesign) and bypass_options:
                raise ValueError(
                    "MandatoryServiceStationDesign is only valid without a bypass route"
                )

            merge_speed = _merge_speed(
                service_options[0].station_segment_ids,
                segments_by_id,
            )
            if bypass_options:
                bypass_speed = _merge_speed(
                    bypass_options[0].station_segment_ids,
                    segments_by_id,
                )
                if not math.isclose(
                    merge_speed,
                    bypass_speed,
                    rel_tol=0.0,
                    abs_tol=self.speed_tolerance_m_per_s,
                ):
                    raise ValueError(
                        f"service and bypass merge speeds differ at "
                        f"{timing.exit_switch_id!r}: {merge_speed} vs {bypass_speed}"
                    )

            platform_rule_id = f"headway_rule::platform::{state_id}"
            rules.append(ConstantHeadwayRule(platform_rule_id, service_headway))
            resources.extend(
                _platform_resources(
                    state_id=state_id,
                    exit_switch_id=timing.exit_switch_id,
                    station_id=timing.station_id,
                    rule_id=platform_rule_id,
                )
            )

            exit_rule_id = f"headway_rule::exit_switch::{state_id}"
            service_resource_seconds: float | None = None
            service_resource_id: str | None = None
            if isinstance(mechanism, ConventionalQuickSwitchDesign):
                rules.append(
                    ConstantHeadwayRule(
                        exit_rule_id,
                        max(
                            rope_headway,
                            mechanism.manufacturer_vehicle_interval_seconds,
                        ),
                    )
                )
            elif isinstance(mechanism, DefaultBypassStopOnFaultDesign):
                merge_envelope_headway, stop_time, stop_headway = _stop_headway(
                    scenario=scenario,
                    merge_speed=merge_speed,
                )
                rules.append(
                    LeaderBehaviorHeadwayRule(
                        exit_rule_id,
                        bypass_leader_seconds=rope_headway,
                        service_leader_seconds=stop_headway,
                    )
                )
                service_resource_seconds = mechanism.mechanical_service_cycle_seconds
                service_resource_id = mechanism.service_resource_id
                quantities.extend(
                    _merge_quantities(
                        state_id,
                        merge_envelope_headway,
                        stop_time,
                        stop_headway,
                    )
                )
            elif isinstance(mechanism, FailSafeDiversionDesign):
                rules.append(ConstantHeadwayRule(exit_rule_id, rope_headway))
                path_seconds = _safety_path_seconds(
                    mechanism.safety_path_segment_ids,
                    segments_by_id,
                )
                clearing_seconds = (
                    mechanism.detection_seconds
                    + mechanism.diversion_seconds
                    + path_seconds
                )
                service_resource_seconds = max(
                    mechanism.mechanical_service_cycle_seconds,
                    clearing_seconds,
                )
                service_resource_id = mechanism.service_resource_id
                quantities.extend(
                    (
                        _quantity(
                            f"safety_path_seconds::{state_id}",
                            path_seconds,
                            "s",
                            "sum_e integral dx/v_e(x)",
                        ),
                        _quantity(
                            f"safety_clear_seconds::{state_id}",
                            clearing_seconds,
                            "s",
                            "tau_detect + tau_divert + T_path",
                        ),
                        _quantity(
                            f"service_recovery_seconds::{state_id}",
                            service_resource_seconds,
                            "s",
                            "max(h_mechanical, h_clear)",
                        ),
                    )
                )
            elif isinstance(mechanism, MandatoryServiceStationDesign):
                rules.append(ConstantHeadwayRule(exit_rule_id, rope_headway))
                service_resource_seconds = mechanism.guaranteed_vehicle_interval_seconds
                service_resource_id = mechanism.service_resource_id
            else:  # pragma: no cover - exhaustive tagged union guard
                raise TypeError(f"unsupported station mechanism: {mechanism!r}")

            resources.append(
                DerivedHeadwayResource(
                    id=f"exit_switch::{state_id}",
                    state_id=state_id,
                    exit_switch_id=timing.exit_switch_id,
                    station_id=timing.station_id,
                    kind=DerivedHeadwayResourceKind.EXIT_SWITCH,
                    rule_id=exit_rule_id,
                    applies_to_service=True,
                    applies_to_bypass=bool(bypass_options),
                )
            )
            if service_resource_seconds is not None:
                assert service_resource_id is not None
                service_rule_id = f"headway_rule::service_mechanism::{state_id}"
                rules.append(
                    ConstantHeadwayRule(service_rule_id, service_resource_seconds)
                )
                resources.append(
                    DerivedHeadwayResource(
                        id=f"service_mechanism::{state_id}",
                        state_id=state_id,
                        exit_switch_id=timing.exit_switch_id,
                        station_id=timing.station_id,
                        kind=DerivedHeadwayResourceKind.SERVICE_MECHANISM,
                        rule_id=service_rule_id,
                        applies_to_service=True,
                        applies_to_bypass=False,
                        physical_resource_id=service_resource_id,
                    )
                )

        policy = DerivedHeadwayPolicy(
            rules=tuple(rules),
            resource_requirements=tuple(resources),
            spatial_spacings=(
                DerivedSpatialSpacing(DerivedSpatialRole.ROPE, rope_spacing),
                DerivedSpatialSpacing(DerivedSpatialRole.SERVICE, service_spacing),
            ),
            derived_quantities=tuple(quantities),
            provenance=physical.provenance + design.provenance,
        )
        policy.validate()
        return policy


def build_legacy_headway_policy(
    scenario: Scenario,
    timings: tuple[SkipStopTiming, ...],
    *,
    station_headway_seconds_by_station_id: dict[str, float] | None = None,
    exit_switch_headway_seconds_by_switch_id: dict[str, float] | None = None,
) -> DerivedHeadwayPolicy:
    spacing = scenario.operating.required_cabin_spacing_m
    station_seconds = spacing / scenario.operating.station_speed_m_per_s
    rope_seconds = spacing / scenario.operating.rope_speed_m_per_s
    station_headways = station_headway_seconds_by_station_id or {
        timing.station_id: station_seconds for timing in timings
    }
    exit_headways = exit_switch_headway_seconds_by_switch_id or {
        timing.switch_id: rope_seconds for timing in timings
    }
    rules: list[ConstantHeadwayRule] = []
    resources: list[DerivedHeadwayResource] = []
    for timing in timings:
        exit_switch_id = timing.exit_switch_id or timing.switch_id
        platform_rule_id = f"headway_rule::platform::{timing.switch_id}"
        exit_rule_id = f"headway_rule::exit_switch::{timing.switch_id}"
        rules.extend(
            (
                ConstantHeadwayRule(
                    platform_rule_id, station_headways[timing.station_id]
                ),
                ConstantHeadwayRule(exit_rule_id, exit_headways[timing.switch_id]),
            )
        )
        resources.extend(
            _platform_resources(
                state_id=timing.switch_id,
                exit_switch_id=exit_switch_id,
                station_id=timing.station_id,
                rule_id=platform_rule_id,
            )
        )
        resources.append(
            DerivedHeadwayResource(
                id=f"exit_switch::{timing.switch_id}",
                state_id=timing.switch_id,
                exit_switch_id=exit_switch_id,
                station_id=timing.station_id,
                kind=DerivedHeadwayResourceKind.EXIT_SWITCH,
                rule_id=exit_rule_id,
                applies_to_service=True,
                applies_to_bypass=timing.skip_allowed,
            )
        )
    policy = DerivedHeadwayPolicy(
        rules=tuple(rules),
        resource_requirements=tuple(resources),
        spatial_spacings=(
            DerivedSpatialSpacing(DerivedSpatialRole.ROPE, spacing),
            DerivedSpatialSpacing(DerivedSpatialRole.SERVICE, spacing),
        ),
        derived_quantities=(
            _quantity("legacy_spacing_m", spacing, "m", "L_C + c_legacy"),
            _quantity(
                "legacy_rope_headway_seconds", rope_seconds, "s", "d_legacy / v_R"
            ),
            _quantity(
                "legacy_station_headway_seconds",
                station_seconds,
                "s",
                "d_legacy / v_S",
            ),
        ),
        provenance=(),
        legacy=True,
    )
    policy.validate()
    return policy


def behavior_from_service(*, service: bool) -> HeadwayRouteBehavior:
    return HeadwayRouteBehavior.SERVICE if service else HeadwayRouteBehavior.BYPASS


def _platform_resources(
    *,
    state_id: str,
    exit_switch_id: str,
    station_id: str,
    rule_id: str,
) -> tuple[DerivedHeadwayResource, DerivedHeadwayResource]:
    return (
        DerivedHeadwayResource(
            id=f"platform_entry::{state_id}",
            state_id=state_id,
            exit_switch_id=exit_switch_id,
            station_id=station_id,
            kind=DerivedHeadwayResourceKind.PLATFORM_ENTRY,
            rule_id=rule_id,
            applies_to_service=True,
            applies_to_bypass=False,
        ),
        DerivedHeadwayResource(
            id=f"platform_exit::{state_id}",
            state_id=state_id,
            exit_switch_id=exit_switch_id,
            station_id=station_id,
            kind=DerivedHeadwayResourceKind.PLATFORM_EXIT,
            rule_id=rule_id,
            applies_to_service=True,
            applies_to_bypass=False,
        ),
    )


def _merge_speed(
    segment_ids: tuple[str, ...],
    segments_by_id: dict[str, object],
) -> float:
    if not segment_ids:
        raise ValueError("station route needs a segment at the merge")
    segment = segments_by_id.get(segment_ids[-1])
    if segment is None:
        raise ValueError(f"unknown merge segment {segment_ids[-1]!r}")
    profile = segment.speed_profile  # type: ignore[attr-defined]
    if profile is None:
        raise ValueError(f"merge segment {segment.id!r} needs a speed profile")
    return _profile_end_speed(profile)


def _profile_end_speed(profile: SpeedProfile) -> float:
    profile.validate()
    if profile.kind is SpeedProfileKind.CONSTANT:
        assert profile.speed_m_per_s is not None
        return profile.speed_m_per_s
    assert profile.end_speed_m_per_s is not None
    return profile.end_speed_m_per_s


def _stop_headway(
    *, scenario: Scenario, merge_speed: float
) -> tuple[float, float, float]:
    assert scenario.headway_design is not None
    physical = scenario.headway_design.physical
    merge_spacing = (
        scenario.operating.cabin_length_m
        + 2.0
        * physical.suspension_length_m
        * math.sin(physical.emergency_merge_sway_angle_rad)
        + physical.merge_clearance_m
    )
    envelope = merge_spacing / merge_speed
    stop_time = (
        physical.control_delay_seconds
        + merge_speed / physical.emergency_deceleration_m_per_s2
    )
    rope_headway = (
        scenario.operating.cabin_length_m
        + 2.0 * physical.suspension_length_m * math.sin(physical.rope_sway_angle_rad)
        + physical.rope_clearance_m
    ) / scenario.operating.rope_speed_m_per_s
    return envelope, stop_time, max(rope_headway, envelope + stop_time)


def _merge_quantities(
    state_id: str,
    envelope: float,
    stop_time: float,
    stop_headway: float,
) -> tuple[DerivedQuantity, ...]:
    return (
        _quantity(
            f"merge_envelope_headway_seconds::{state_id}",
            envelope,
            "s",
            "d_M / v_M",
        ),
        _quantity(
            f"merge_stop_time_seconds::{state_id}",
            stop_time,
            "s",
            "tau_control + v_M/a_M",
        ),
        _quantity(
            f"merge_stop_headway_seconds::{state_id}",
            stop_headway,
            "s",
            "max(h_R, h_M_env + tau_M_stop)",
        ),
    )


def _safety_path_seconds(
    segment_ids: tuple[str, ...],
    segments_by_id: dict[str, object],
) -> float:
    segments = []
    previous_to_node: str | None = None
    for segment_id in segment_ids:
        segment = segments_by_id.get(segment_id)
        if segment is None:
            raise ValueError(f"unknown safety path segment {segment_id!r}")
        if previous_to_node is not None and segment.from_node_id != previous_to_node:  # type: ignore[attr-defined]
            raise ValueError("safety path segments must form a connected ordered path")
        previous_to_node = segment.to_node_id  # type: ignore[attr-defined]
        segments.append(segment)
    return sum(travel_seconds_for_segment(segment) for segment in segments)  # type: ignore[arg-type]


def _quantity(
    quantity_id: str,
    value: float,
    unit: str,
    formula: str,
) -> DerivedQuantity:
    return DerivedQuantity(
        id=quantity_id,
        value=value,
        unit=unit,
        formula=formula,
        evidence_kind=HeadwayEvidenceKind.EXPERIMENTAL,
    )
