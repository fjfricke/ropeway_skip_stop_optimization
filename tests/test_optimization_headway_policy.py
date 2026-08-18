from __future__ import annotations

from dataclasses import replace

import pytest

from ropeway_skip_stop_optimization.examples.circular_skip_stop import (
    CircularSkipStopSpec,
    build_circular_skip_stop_ean_pattern_definition,
    build_circular_skip_stop_ean_config,
    build_circular_skip_stop_scenario,
)
from ropeway_skip_stop_optimization.models import (
    ConventionalQuickSwitchDesign,
    DefaultBypassStopOnFaultDesign,
    FailSafeDiversionDesign,
    HeadwayDesign,
    HeadwayPhysicalParameters,
    HeadwayRouteBehavior,
    LeaderBehaviorHeadwayRule,
    MandatoryServiceStationDesign,
    OperatingParameters,
    StationMechanismAssignment,
)
from ropeway_skip_stop_optimization.optimization.ean.builders.network_timing_builder import (
    NetworkSkipStopTimingBuilder,
)
from ropeway_skip_stop_optimization.optimization.ddd import (
    DddRouteDecision,
    EanArtifactToDddMovementProblemAdapter,
)
from ropeway_skip_stop_optimization.optimization.ean import (
    EanCabinStart,
    EanCabinStartBuilder,
    EanCabinStartKind,
    SparseHeadwayPairBuilder,
    StationWaitingMode,
    network_ean_builder_for_pattern,
)
from ropeway_skip_stop_optimization.optimization.ean.builders.physical_network_builder import (
    PhysicalMovementNetworkBuilder,
)
from ropeway_skip_stop_optimization.optimization.headway_policy import (
    PhysicalHeadwayPolicyBuilder,
)


def test_architecture_a_derives_manufacturer_headway() -> None:
    scenario, network, timings, pattern = _case(
        lambda station: ConventionalQuickSwitchDesign(9.0)
    )

    policy = PhysicalHeadwayPolicyBuilder().build(scenario, network, timings, pattern)

    assert _quantity(
        policy, "attachment_to_lowest_envelope_m"
    ) == pytest.approx(4.22)
    assert _quantity(policy, "rope_headway_seconds") == pytest.approx(1.052439)
    assert _quantity(policy, "service_headway_seconds") == pytest.approx(11.666667)
    for state_id in pattern.state_ids:
        rule = policy.rule(f"headway_rule::exit_switch::{state_id}")
        assert rule.minimum_seconds == pytest.approx(9.0)
        assert rule.maximum_seconds == pytest.approx(9.0)


@pytest.mark.parametrize(
    "field_name",
    ("cabin_height_m", "attachment_to_cabin_roof_m"),
)
def test_carrier_envelope_geometry_must_be_positive(field_name: str) -> None:
    scenario, _, _, _ = _case(
        lambda station: ConventionalQuickSwitchDesign(9.0)
    )
    assert scenario.headway_design is not None
    physical = scenario.headway_design.physical

    assert physical.attachment_to_lowest_envelope_m == pytest.approx(4.22)
    with pytest.raises(ValueError, match=field_name):
        replace(physical, **{field_name: 0.0}).validate()


def test_architecture_b_derives_directed_leader_rule_and_service_resource() -> None:
    scenario, network, timings, pattern = _case(
        lambda station: DefaultBypassStopOnFaultDesign(
            mechanical_service_cycle_seconds=6.0,
            service_resource_id=f"attachment::{station}",
        )
    )

    policy = PhysicalHeadwayPolicyBuilder().build(scenario, network, timings, pattern)

    rule = policy.rule(f"headway_rule::exit_switch::{pattern.state_ids[0]}")
    assert isinstance(rule, LeaderBehaviorHeadwayRule)
    bypass = HeadwayRouteBehavior.BYPASS
    service = HeadwayRouteBehavior.SERVICE
    assert rule.required_seconds(bypass, bypass) == pytest.approx(1.052439)
    assert rule.required_seconds(bypass, service) == pytest.approx(1.052439)
    assert rule.required_seconds(service, bypass) == pytest.approx(4.981010)
    assert rule.required_seconds(service, service) == pytest.approx(4.981010)
    assert (
        rule.required_seconds(bypass, service) + rule.required_seconds(service, bypass)
    ) == pytest.approx(6.033448)
    service_rule = policy.rule(
        f"headway_rule::service_mechanism::{pattern.state_ids[0]}"
    )
    assert service_rule.maximum_seconds == pytest.approx(6.0)


def test_architecture_c_derives_recovery_from_connected_safety_path() -> None:
    scenario, network, timings, pattern = _case(
        lambda station: FailSafeDiversionDesign(
            mechanical_service_cycle_seconds=1.0,
            detection_seconds=0.2,
            diversion_seconds=0.3,
            safety_path_segment_ids=(
                f"{station}_cw_approach_fast",
                f"{station}_cw_brake",
            ),
            service_resource_id=f"recovery::{station}",
        )
    )

    policy = PhysicalHeadwayPolicyBuilder().build(scenario, network, timings, pattern)

    state_id = pattern.state_ids[0]
    exit_rule = policy.rule(f"headway_rule::exit_switch::{state_id}")
    assert exit_rule.minimum_seconds == pytest.approx(1.052439)
    path_seconds = 5.0 / 6.0 + 3.0 / ((6.0 + 0.3) / 2.0)
    assert _quantity(policy, f"safety_path_seconds::{state_id}") == pytest.approx(
        path_seconds
    )
    recovery_rule = policy.rule(f"headway_rule::service_mechanism::{state_id}")
    assert recovery_rule.maximum_seconds == pytest.approx(0.5 + path_seconds)


def test_mandatory_service_design_rejects_a_bypass_state() -> None:
    scenario, network, timings, pattern = _case(
        lambda station: MandatoryServiceStationDesign(
            guaranteed_vehicle_interval_seconds=8.0,
            service_resource_id=f"terminal::{station}",
        )
    )

    with pytest.raises(ValueError, match="only valid without a bypass"):
        PhysicalHeadwayPolicyBuilder().build(scenario, network, timings, pattern)


def test_ddd_adapter_preserves_architecture_b_directed_usage_headways() -> None:
    scenario, _, _, _ = _case(
        lambda station: DefaultBypassStopOnFaultDesign(
            mechanical_service_cycle_seconds=6.0,
            service_resource_id=f"attachment::{station}",
        )
    )
    config = replace(
        build_circular_skip_stop_ean_config(
            scenario,
            waiting_mode=StationWaitingMode.NO_WAITING,
        ),
        horizon_seconds=100.0,
    )
    artifact = network_ean_builder_for_pattern(
        pattern_definition=build_circular_skip_stop_ean_pattern_definition(scenario),
        start_builder=_OneCabinStartBuilder(),
        headway_pair_builder=SparseHeadwayPairBuilder(),
    ).build(scenario, config)

    problem = EanArtifactToDddMovementProblemAdapter().build(artifact)
    exit_resource = problem.resources_by_id["exit_switch::A_entry_cw"]
    stop_option = next(
        option
        for option in problem.route_options
        if option.from_state_id == "A_entry_cw"
        and option.decision is DddRouteDecision.STOP
    )
    skip_option = next(
        option
        for option in problem.route_options
        if option.from_state_id == "A_entry_cw"
        and option.decision is DddRouteDecision.SKIP
    )
    stop_usage = next(
        usage
        for usage in stop_option.resource_usages
        if usage.resource_id == exit_resource.id
    )
    skip_usage = next(
        usage
        for usage in skip_option.resource_usages
        if usage.resource_id == exit_resource.id
    )

    assert exit_resource.minimum_headway_seconds == pytest.approx(1.052439)
    assert exit_resource.maximum_headway_seconds == pytest.approx(4.981010)
    assert stop_usage.separation_after_seconds == pytest.approx(4.981010)
    assert skip_usage.separation_after_seconds == pytest.approx(1.052439)


class _OneCabinStartBuilder(EanCabinStartBuilder):
    def build(self, scenario, config, network, pattern, headway_policy=None):
        del scenario, config, network, headway_policy
        return (
            EanCabinStart(
                cabin_id=0,
                first_switch_id=pattern.state_ids[0],
                kind=EanCabinStartKind.FIXED,
                time_seconds=0.0,
            ),
        )


def _case(mechanism_factory):
    spec = CircularSkipStopSpec(
        scenario_id="physical_headway_policy_test",
        station_ids=("A", "B", "C"),
        label="test",
        description="test",
        include_skip_routes=True,
        service_station_waiting_mode=StationWaitingMode.NO_WAITING,
        rope_speed_m_per_s=6.0,
        platform_speed_m_per_s=0.3,
        cabin_length_m=3.0,
        min_clearance_m=0.5,
        scenario_cabin_count=2,
    )
    scenario = build_circular_skip_stop_scenario(spec)
    physical = HeadwayPhysicalParameters(
        service_clearance_m=0.5,
        rope_clearance_m=0.5,
        merge_clearance_m=0.5,
        cabin_height_m=2.22,
        attachment_to_cabin_roof_m=2.0,
        rope_sway_angle_rad=0.34,
        emergency_merge_sway_angle_rad=0.34,
        control_delay_seconds=0.5,
        emergency_deceleration_m_per_s2=1.75,
    )
    scenario = replace(
        scenario,
        operating=OperatingParameters(
            rope_speed_m_per_s=6.0,
            station_speed_m_per_s=0.3,
            cabin_capacity=scenario.operating.cabin_capacity,
            cabin_length_m=3.0,
            min_clearance_m=0.5,
        ),
        headway_design=HeadwayDesign(
            physical=physical,
            station_mechanisms=tuple(
                StationMechanismAssignment(
                    exit_switch_id=f"{station}_exit_cw",
                    design=mechanism_factory(station),
                )
                for station in ("A", "B", "C")
            ),
        ),
    )
    pattern_definition = build_circular_skip_stop_ean_pattern_definition(scenario)
    network = PhysicalMovementNetworkBuilder().build(scenario, pattern_definition)
    pattern = network.pattern(pattern_definition.id)
    timings = NetworkSkipStopTimingBuilder().build(scenario, network, pattern)
    return scenario, network, timings, pattern


def _quantity(policy, quantity_id: str) -> float:
    return next(
        quantity.value
        for quantity in policy.derived_quantities
        if quantity.id == quantity_id
    )
