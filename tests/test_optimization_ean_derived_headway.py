from __future__ import annotations

from dataclasses import replace

import pytest

from ropeway_skip_stop_optimization.examples.artificial_headway_cases import (
    ArtificialHeadwayArchitecture,
    build_six_station_ring_headway_scenario,
)
from ropeway_skip_stop_optimization.examples.circular_skip_stop import (
    build_circular_skip_stop_ean_config,
    build_circular_skip_stop_ean_pattern_definition,
)
from ropeway_skip_stop_optimization.models import (
    LeaderBehaviorHeadwayRule,
)
from ropeway_skip_stop_optimization.optimization.ean import (
    AllPairsHeadwayPairBuilder,
    EanCabinStart,
    EanCabinStartBuilder,
    EanCabinStartKind,
    EanFleetConfig,
    EanFleetMode,
    EanHeadwayOrderFamilyIndex,
    EanHorizonFormulation,
    EanInitialPlacementStateKind,
    HeadwayCheckpointKind,
    StationWaitingMode,
    network_ean_builder_for_pattern,
    SparseHeadwayPairBuilder,
    validate_ean_initial_boundary_against_artifact,
)
from ropeway_skip_stop_optimization.optimization.ean.optimizers.all_stop_mip_start import (
    EanAllStopMipStartSeedBuilder,
)
from ropeway_skip_stop_optimization.optimization.ean.headway_rule_evaluation import (
    evaluate_headway_pair,
)
from ropeway_skip_stop_optimization.optimization.headway_resource_reduction import (
    HeadwayResourceReductionMode,
)


@pytest.mark.parametrize(
    ("first_service", "second_service", "forward_required", "reverse_required"),
    (
        (False, False, 0.916821, 0.916821),
        (False, True, 0.916821, 4.845393),
        (True, False, 4.845393, 0.916821),
        (True, True, 4.845393, 4.845393),
    ),
)
def test_architecture_b_evaluates_all_directed_route_combinations(
    first_service: bool,
    second_service: bool,
    forward_required: float,
    reverse_required: float,
) -> None:
    artifact = _two_cabin_architecture_b_artifact()
    checkpoint = next(
        checkpoint
        for checkpoint in artifact.headway_checkpoints
        if checkpoint.id == "exit_switch::S0_entry_cw"
    )
    rule = artifact.headway_rule_for_checkpoint(checkpoint)

    result = evaluate_headway_pair(
        rule=rule,
        first_is_service=first_service,
        second_is_service=second_service,
        forward_gap_seconds=0.0,
        reverse_gap_seconds=0.0,
    )

    assert result.forward_required_seconds == pytest.approx(forward_required)
    assert result.reverse_required_seconds == pytest.approx(reverse_required)


def test_service_mechanism_reuses_exit_order_family() -> None:
    artifact = _two_cabin_architecture_b_artifact(
        reduction_mode=HeadwayResourceReductionMode.DISABLED
    )
    index = EanHeadwayOrderFamilyIndex.build(artifact)
    checkpoints = {
        checkpoint.id: checkpoint for checkpoint in artifact.headway_checkpoints
    }
    exit_pair = next(
        pair
        for pair in artifact.headway_pairs
        if checkpoints[pair.checkpoint_id].kind is HeadwayCheckpointKind.EXIT_SWITCH
    )
    service_pair = next(
        pair
        for pair in artifact.headway_pairs
        if checkpoints[pair.checkpoint_id].kind
        is HeadwayCheckpointKind.SERVICE_MECHANISM
    )

    assert (
        index.reference_for_pair(exit_pair.id).family_id
        == index.reference_for_pair(service_pair.id).family_id
    )
    assert isinstance(
        artifact.headway_rule_for_pair(exit_pair), LeaderBehaviorHeadwayRule
    )


def test_bypass_leader_can_be_feasible_when_service_leader_is_not() -> None:
    artifact = _two_cabin_architecture_b_artifact()
    checkpoint = next(
        checkpoint
        for checkpoint in artifact.headway_checkpoints
        if checkpoint.id == "exit_switch::S0_entry_cw"
    )
    rule = artifact.headway_rule_for_checkpoint(checkpoint)

    bypass_leader = evaluate_headway_pair(
        rule=rule,
        first_is_service=False,
        second_is_service=True,
        forward_gap_seconds=2.0,
        reverse_gap_seconds=-2.0,
    )
    service_leader = evaluate_headway_pair(
        rule=rule,
        first_is_service=True,
        second_is_service=False,
        forward_gap_seconds=2.0,
        reverse_gap_seconds=-2.0,
    )

    assert not bypass_leader.is_violated(tolerance_seconds=1e-5)
    assert service_leader.is_violated(tolerance_seconds=1e-5)


def test_architecture_b_oip_seed_exports_virtual_previous_service() -> None:
    scenario = build_six_station_ring_headway_scenario(
        ArtificialHeadwayArchitecture.B,
        direction="cw",
        scenario_id="derived_headway_oip_test",
    )
    config = replace(
        build_circular_skip_stop_ean_config(
            scenario,
            waiting_mode=StationWaitingMode.NO_WAITING,
        ),
        horizon_seconds=20.0,
    )
    artifact = network_ean_builder_for_pattern(
        pattern_definition=build_circular_skip_stop_ean_pattern_definition(
            scenario, direction="cw"
        ),
        fleet_config=EanFleetConfig(
            mode=EanFleetMode.OPTIMIZED_INITIAL_PLACEMENT,
            available_fleet_count=12,
        ),
        headway_pair_builder=SparseHeadwayPairBuilder(),
    ).build(scenario, config)

    seed = EanAllStopMipStartSeedBuilder().build(
        artifact,
        EanHorizonFormulation.EXACT_TIME_ACTIVATION,
    )

    assert seed.fleet_plan is not None
    rope_states = tuple(
        state
        for state in seed.fleet_plan.initial_states
        if state.kind is EanInitialPlacementStateKind.ROPE
    )
    assert rope_states
    assert all(state.previous_service is True for state in rope_states)
    validate_ean_initial_boundary_against_artifact(
        artifact,
        seed.movement_plan,
        seed.fleet_plan,
        tolerance_seconds=1e-5,
    ).raise_for_errors()

    first_rope = rope_states[0]
    invalid = replace(
        seed.fleet_plan,
        initial_states=tuple(
            replace(state, previous_service=None)
            if state.cabin_id == first_rope.cabin_id
            else state
            for state in seed.fleet_plan.initial_states
        ),
    )
    report = validate_ean_initial_boundary_against_artifact(
        artifact,
        seed.movement_plan,
        invalid,
        tolerance_seconds=1e-5,
    )
    assert any(
        issue.code == "EAN_INITIAL_PREVIOUS_BEHAVIOR_MISSING"
        for issue in report.errors
    )


class _TwoCabinStartBuilder(EanCabinStartBuilder):
    def build(self, scenario, config, network, pattern, headway_policy=None):
        del scenario, config, network, headway_policy
        return tuple(
            EanCabinStart(
                cabin_id=cabin_id,
                first_switch_id=pattern.state_ids[0],
                kind=EanCabinStartKind.FIXED,
                time_seconds=float(cabin_id * 5),
            )
            for cabin_id in range(2)
        )


def _two_cabin_architecture_b_artifact(
    *,
    reduction_mode: HeadwayResourceReductionMode = HeadwayResourceReductionMode.EXACT,
):
    scenario = build_six_station_ring_headway_scenario(
        ArtificialHeadwayArchitecture.B,
        direction="cw",
        scenario_id="derived_headway_two_cabin_test",
    )
    config = replace(
        build_circular_skip_stop_ean_config(
            scenario,
            waiting_mode=StationWaitingMode.NO_WAITING,
        ),
        horizon_seconds=20.0,
    )
    return network_ean_builder_for_pattern(
        pattern_definition=build_circular_skip_stop_ean_pattern_definition(
            scenario, direction="cw"
        ),
        start_builder=_TwoCabinStartBuilder(),
        headway_pair_builder=AllPairsHeadwayPairBuilder(),
        headway_resource_reduction_mode=reduction_mode,
    ).build(scenario, config)
