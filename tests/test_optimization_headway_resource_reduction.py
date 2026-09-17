from __future__ import annotations

from dataclasses import replace
from datetime import time

import pytest

from ropeway_skip_stop_optimization.examples.artificial_headway_cases import (
    ArtificialHeadwayArchitecture,
    FiveStationCircleCwFullSkipNoWaitHeadwayBExample,
    build_six_station_line_headway_scenario,
    build_six_station_ring_headway_scenario,
)
from ropeway_skip_stop_optimization.examples.circular_skip_stop import (
    build_circular_skip_stop_ean_config,
    build_circular_skip_stop_ean_pattern_definition,
)
from ropeway_skip_stop_optimization.examples.linear_skip_stop import (
    build_linear_skip_stop_ean_config,
    build_linear_skip_stop_ean_pattern_definition,
)
from ropeway_skip_stop_optimization.models import (
    DefaultBypassStopOnFaultDesign,
    Demand,
    DerivedHeadwayResourceKind,
    HeadwayDominanceProofKind,
)
from ropeway_skip_stop_optimization.optimization.ean import (
    AllPairsHeadwayPairBuilder,
    EanCabinStart,
    EanCabinStartBuilder,
    EanCabinStartKind,
    EanFleetConfig,
    EanFleetMode,
    EanHorizonFormulation,
    EanOptimizer,
    EanPassengerObjective,
    EanPassengerServiceProblem,
    EanSolveConfig,
    SparseHeadwayPairBuilder,
    StationWaitingMode,
    network_ean_builder_for_pattern,
    validate_ean_initial_boundary_against_artifact,
    validate_ean_movement_plan_against_artifact,
)
from ropeway_skip_stop_optimization.optimization.ean.optimizers.all_stop_mip_start import (
    EanAllStopMipStartSeedBuilder,
)
from ropeway_skip_stop_optimization.optimization.ddd.trajectory_exhaustive_reference import (
    ddd_trajectory_instance_fingerprint,
)
from ropeway_skip_stop_optimization.optimization.ean.builders.network_timing_builder import (
    NetworkSkipStopTimingBuilder,
)
from ropeway_skip_stop_optimization.optimization.ean.builders.physical_network_builder import (
    PhysicalMovementNetworkBuilder,
)
from ropeway_skip_stop_optimization.optimization.headway_policy import (
    PhysicalHeadwayPolicyBuilder,
)
from ropeway_skip_stop_optimization.optimization.headway_resource_reduction import (
    HeadwayResourceReduction,
    HeadwayResourceReductionMode,
)


def test_five_station_b_exact_reduction_has_expected_artifact_counts() -> None:
    example = FiveStationCircleCwFullSkipNoWaitHeadwayBExample()
    scenario = example.build_scenario()
    config = example.build_ean_config(scenario)
    artifact = example.build_ean_artifact_builder(scenario, config).build(
        scenario, config
    )

    assert len(artifact.headway_checkpoints) == 15
    assert len(artifact.headway_candidates) == 4_107
    assert len(artifact.headway_pairs) == 560_199
    assert artifact.effective_headway_policy is not None
    assert len(artifact.effective_headway_policy.dominance_certificates) == 5
    assert artifact.build_metrics is not None
    assert artifact.build_metrics.original_checkpoint_count == 20
    assert artifact.build_metrics.original_candidate_count == 5_476
    assert artifact.build_metrics.original_pair_count == 746_932
    assert artifact.build_metrics.dominated_pair_count == 186_733
    assert all(
        certificate.slack_seconds == 1.0
        for certificate in artifact.effective_headway_policy.dominance_certificates
    )


def test_b_mechanical_headway_above_platform_headway_is_retained() -> None:
    scenario = _with_mechanical_seconds(
        FiveStationCircleCwFullSkipNoWaitHeadwayBExample().build_scenario(),
        8.0,
    )
    artifact = _sparse_ring_artifact(scenario, StationWaitingMode.NO_WAITING)

    assert artifact.effective_headway_policy is not None
    assert not artifact.effective_headway_policy.dominance_certificates
    assert sum(
        checkpoint.kind.value == "service_mechanism"
        for checkpoint in artifact.headway_checkpoints
    ) == 5


def test_end_of_platform_wait_uses_occupancy_dominance() -> None:
    scenario = build_six_station_ring_headway_scenario(
        ArtificialHeadwayArchitecture.B,
        direction="cw",
    )
    artifact = _sparse_ring_artifact(
        scenario, StationWaitingMode.END_OF_PLATFORM_WAIT
    )

    assert artifact.effective_headway_policy is not None
    certificates = artifact.effective_headway_policy.dominance_certificates
    assert len(certificates) == 6
    assert all(
        certificate.proof_kind
        is HeadwayDominanceProofKind.WAIT_OCCUPANCY_FIXED_SUFFIX
        for certificate in certificates
    )
    assert all(
        certificate.dominating_resource_id.startswith("platform_exit::")
        for certificate in certificates
    )


def test_variable_service_route_prevents_dominance() -> None:
    scenario = build_six_station_ring_headway_scenario(
        ArtificialHeadwayArchitecture.B,
        direction="cw",
    )
    definition = build_circular_skip_stop_ean_pattern_definition(
        scenario, direction="cw"
    )
    network = PhysicalMovementNetworkBuilder().build(scenario, definition)
    pattern = network.pattern(definition.id)
    timings = NetworkSkipStopTimingBuilder().build(scenario, network, pattern)
    policy = PhysicalHeadwayPolicyBuilder().build(
        scenario, network, timings, pattern
    )
    first_service = next(
        option
        for option in network.route_options
        if option.passenger_behavior.value == "service"
    )
    variable_network = replace(
        network,
        route_options=tuple(
            replace(option, maximum_seconds=option.maximum_seconds + 1.0)
            if option.id == first_service.id
            else option
            for option in network.route_options
        ),
    )
    config = build_circular_skip_stop_ean_config(
        scenario, waiting_mode=StationWaitingMode.NO_WAITING
    )

    effective = HeadwayResourceReduction().reduce(
        policy=policy,
        network=variable_network,
        timings=timings,
        station_configs=config.station_configs,
    )

    assert "service_mechanism::S0_entry_cw" in {
        resource.id for resource in effective.resource_requirements
    }


def test_service_resource_shared_between_states_is_never_locally_removed() -> None:
    scenario = build_six_station_ring_headway_scenario(
        ArtificialHeadwayArchitecture.B,
        direction="cw",
    )
    assert scenario.headway_design is not None
    scenario = replace(
        scenario,
        headway_design=replace(
            scenario.headway_design,
            station_mechanisms=tuple(
                replace(
                    assignment,
                    design=replace(
                        assignment.design,
                        service_resource_id="shared_service_mechanism",
                    ),
                )
                for assignment in scenario.headway_design.station_mechanisms
            ),
        ),
    )
    artifact = _sparse_ring_artifact(scenario, StationWaitingMode.NO_WAITING)

    assert artifact.effective_headway_policy is not None
    assert not artifact.effective_headway_policy.dominance_certificates
    assert sum(
        checkpoint.kind.value == "service_mechanism"
        for checkpoint in artifact.headway_checkpoints
    ) == 6


def test_c_recovery_resource_uses_the_same_exact_dominance_template() -> None:
    scenario = build_six_station_ring_headway_scenario(
        ArtificialHeadwayArchitecture.C,
        direction="cw",
    )
    artifact = _sparse_ring_artifact(scenario, StationWaitingMode.NO_WAITING)

    assert artifact.effective_headway_policy is not None
    assert len(artifact.effective_headway_policy.dominance_certificates) == 6
    assert all(
        resource.kind is not DerivedHeadwayResourceKind.SERVICE_MECHANISM
        for resource in artifact.effective_headway_policy.resource_requirements
    )


def test_a_is_structurally_unchanged() -> None:
    scenario = build_six_station_ring_headway_scenario(
        ArtificialHeadwayArchitecture.A,
        direction="cw",
    )
    artifact = _sparse_ring_artifact(scenario, StationWaitingMode.NO_WAITING)

    assert artifact.effective_headway_policy is not None
    assert not artifact.effective_headway_policy.dominance_certificates
    assert all(
        components == (resource_id,)
        for resource_id, components in artifact.effective_headway_policy.component_resource_ids_by_effective_id.items()
    )


def test_terminal_exit_and_mechanism_are_coalesced_by_maximum() -> None:
    scenario = build_six_station_line_headway_scenario(
        ArtificialHeadwayArchitecture.B
    )
    config = build_linear_skip_stop_ean_config(
        scenario,
        service_station_waiting_mode=StationWaitingMode.NO_WAITING,
    )
    artifact = network_ean_builder_for_pattern(
        pattern_definition=build_linear_skip_stop_ean_pattern_definition(scenario),
        headway_pair_builder=SparseHeadwayPairBuilder(),
    ).build(scenario, config)

    assert artifact.effective_headway_policy is not None
    terminal_components = tuple(
        components
        for components in artifact.effective_headway_policy.component_resource_ids_by_effective_id.values()
        if any("service_mechanism::T" in component for component in components)
    )
    assert len(terminal_components) == 2
    assert all(len(components) == 2 for components in terminal_components)
    for effective_id, components in (
        artifact.effective_headway_policy.component_resource_ids_by_effective_id.items()
    ):
        if any("service_mechanism::T" in component for component in components):
            resource = artifact.effective_headway_policy.resource(effective_id)
            assert (
                artifact.effective_headway_policy.rule(resource.rule_id).maximum_seconds
                == 9.0
            )


def test_reduction_can_be_disabled_for_ablation() -> None:
    scenario = build_six_station_ring_headway_scenario(
        ArtificialHeadwayArchitecture.B,
        direction="cw",
    )
    definition = build_circular_skip_stop_ean_pattern_definition(
        scenario, direction="cw"
    )
    config = build_circular_skip_stop_ean_config(
        scenario, waiting_mode=StationWaitingMode.NO_WAITING
    )
    artifact = network_ean_builder_for_pattern(
        pattern_definition=definition,
        headway_pair_builder=SparseHeadwayPairBuilder(),
        headway_resource_reduction_mode=HeadwayResourceReductionMode.DISABLED,
    ).build(scenario, config)

    assert artifact.effective_headway_policy is not None
    assert not artifact.effective_headway_policy.dominance_certificates
    assert sum(
        checkpoint.kind.value == "service_mechanism"
        for checkpoint in artifact.headway_checkpoints
    ) == 6
    reduced = network_ean_builder_for_pattern(
        pattern_definition=definition,
        headway_pair_builder=SparseHeadwayPairBuilder(),
    ).build(scenario, config)
    assert ddd_trajectory_instance_fingerprint(artifact) != (
        ddd_trajectory_instance_fingerprint(reduced)
    )


def test_c_dominated_resource_is_retained_at_oip_boundary() -> None:
    scenario = build_six_station_ring_headway_scenario(
        ArtificialHeadwayArchitecture.C,
        direction="cw",
    )
    config = build_circular_skip_stop_ean_config(
        scenario, waiting_mode=StationWaitingMode.NO_WAITING
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
    ).build(scenario, replace(config, horizon_seconds=20.0))

    assert artifact.initial_boundary_service_resource("S0_entry_cw") is not None
    seed = EanAllStopMipStartSeedBuilder().build(
        artifact,
        EanHorizonFormulation.EXACT_TIME_ACTIVATION,
    )
    assert seed.fleet_plan is not None
    validate_ean_initial_boundary_against_artifact(
        artifact,
        seed.movement_plan,
        seed.fleet_plan,
        tolerance_seconds=1e-5,
    ).raise_for_errors()


@pytest.mark.parametrize("architecture", tuple(ArtificialHeadwayArchitecture))
def test_reduced_and_unreduced_ean_have_same_passenger_optimum(
    architecture: ArtificialHeadwayArchitecture,
) -> None:
    pytest.importorskip("gurobipy")
    scenario = _small_passenger_scenario(architecture)
    reduced = _small_ring_artifact(
        scenario,
        waiting_mode=StationWaitingMode.NO_WAITING,
        reduction_mode=HeadwayResourceReductionMode.EXACT,
    )
    unreduced = _small_ring_artifact(
        scenario,
        waiting_mode=StationWaitingMode.NO_WAITING,
        reduction_mode=HeadwayResourceReductionMode.DISABLED,
    )

    reduced_result = _solve_passenger(scenario, reduced)
    unreduced_result = _solve_passenger(scenario, unreduced)

    assert reduced_result.metadata.status == unreduced_result.metadata.status == "optimal"
    assert reduced_result.metadata.objective_value_seconds == pytest.approx(
        unreduced_result.metadata.objective_value_seconds,
        abs=1e-6,
    )
    assert reduced_result.metadata.objective_value_seconds is not None
    assert reduced_result.metadata.objective_value_seconds > 0.0
    assert reduced_result.metadata.served_passenger_count == (
        unreduced_result.metadata.served_passenger_count
    ) == 2
    assert reduced_result.movement_plan is not None
    assert unreduced_result.movement_plan is not None
    validate_ean_movement_plan_against_artifact(
        reduced, reduced_result.movement_plan, tolerance_seconds=1e-5
    ).raise_for_errors()
    validate_ean_movement_plan_against_artifact(
        unreduced, unreduced_result.movement_plan, tolerance_seconds=1e-5
    ).raise_for_errors()


def test_b_waiting_occupancy_reduction_is_solver_equivalent_with_positive_wait() -> None:
    gp = pytest.importorskip("gurobipy")
    scenario = _small_passenger_scenario(ArtificialHeadwayArchitecture.B)
    reduced = _small_ring_artifact(
        scenario,
        waiting_mode=StationWaitingMode.END_OF_PLATFORM_WAIT,
        reduction_mode=HeadwayResourceReductionMode.EXACT,
    )
    unreduced = _small_ring_artifact(
        scenario,
        waiting_mode=StationWaitingMode.END_OF_PLATFORM_WAIT,
        reduction_mode=HeadwayResourceReductionMode.DISABLED,
    )

    assert reduced.effective_headway_policy is not None
    assert len(reduced.effective_headway_policy.dominance_certificates) == 6
    assert all(
        certificate.proof_kind
        is HeadwayDominanceProofKind.WAIT_OCCUPANCY_FIXED_SUFFIX
        for certificate in reduced.effective_headway_policy.dominance_certificates
    )
    assert not any(
        checkpoint.kind.value == "service_mechanism"
        for checkpoint in reduced.headway_checkpoints
    )
    assert sum(
        checkpoint.kind.value == "service_mechanism"
        for checkpoint in unreduced.headway_checkpoints
    ) == 6

    reduced_status, reduced_plan = _solve_with_positive_initial_wait(gp, reduced)
    unreduced_status, unreduced_plan = _solve_with_positive_initial_wait(
        gp, unreduced
    )

    assert reduced_status == unreduced_status == gp.GRB.OPTIMAL
    assert reduced_plan.trajectories[0].visits[0].wait_seconds == pytest.approx(1.0)
    assert unreduced_plan.trajectories[0].visits[0].wait_seconds == pytest.approx(1.0)
    validate_ean_movement_plan_against_artifact(
        reduced, reduced_plan, tolerance_seconds=1e-5
    ).raise_for_errors()
    validate_ean_movement_plan_against_artifact(
        unreduced, unreduced_plan, tolerance_seconds=1e-5
    ).raise_for_errors()


def _with_mechanical_seconds(scenario, seconds: float):
    assert scenario.headway_design is not None
    return replace(
        scenario,
        headway_design=replace(
            scenario.headway_design,
            station_mechanisms=tuple(
                replace(
                    assignment,
                    design=replace(
                        assignment.design,
                        mechanical_service_cycle_seconds=seconds,
                    ),
                )
                if isinstance(
                    assignment.design, DefaultBypassStopOnFaultDesign
                )
                else assignment
                for assignment in scenario.headway_design.station_mechanisms
            ),
        ),
    )


def _sparse_ring_artifact(scenario, waiting_mode: StationWaitingMode):
    config = build_circular_skip_stop_ean_config(
        scenario, waiting_mode=waiting_mode
    )
    return network_ean_builder_for_pattern(
        pattern_definition=build_circular_skip_stop_ean_pattern_definition(
            scenario, direction="cw"
        ),
        headway_pair_builder=SparseHeadwayPairBuilder(),
    ).build(scenario, config)


class _TwoCabinStartBuilder(EanCabinStartBuilder):
    def build(self, scenario, config, network, pattern, headway_policy=None):
        del scenario, config, network, headway_policy
        return (
            EanCabinStart(
                cabin_id=0,
                first_switch_id=pattern.state_ids[0],
                kind=EanCabinStartKind.FIXED,
                time_seconds=0.0,
            ),
            EanCabinStart(
                cabin_id=1,
                first_switch_id=pattern.state_ids[0],
                kind=EanCabinStartKind.FIXED,
                time_seconds=13.0,
            ),
        )


def _small_passenger_scenario(architecture: ArtificialHeadwayArchitecture):
    scenario = build_six_station_ring_headway_scenario(
        architecture,
        direction="cw",
        scenario_id=f"headway_reduction_solver_{architecture.value}",
    )
    return replace(
        scenario,
        demands=(
            Demand(
                arrival_time=time(8, 0),
                origin="S0",
                destination="S1",
                count=2,
            ),
        ),
    )


def _small_ring_artifact(
    scenario,
    *,
    waiting_mode: StationWaitingMode,
    reduction_mode: HeadwayResourceReductionMode,
):
    config = replace(
        build_circular_skip_stop_ean_config(
            scenario,
            waiting_mode=waiting_mode,
        ),
        horizon_seconds=150.0,
    )
    return network_ean_builder_for_pattern(
        pattern_definition=build_circular_skip_stop_ean_pattern_definition(
            scenario, direction="cw"
        ),
        start_builder=_TwoCabinStartBuilder(),
        headway_pair_builder=AllPairsHeadwayPairBuilder(),
        headway_resource_reduction_mode=reduction_mode,
    ).build(scenario, config)


def _solve_passenger(scenario, artifact):
    return EanOptimizer(EanSolveConfig(log_to_console=False)).solve(
        EanPassengerServiceProblem(
            scenario=scenario,
            artifact=artifact,
            objective=EanPassengerObjective.JOURNEY_TIME,
        )
    )


def _solve_with_positive_initial_wait(gp, artifact):
    from ropeway_skip_stop_optimization.optimization.ean.optimization_config import (
        EanOptimizationConfig,
    )
    from ropeway_skip_stop_optimization.optimization.ean.optimizers.movement_model import (
        EanMovementModelBuilder,
    )

    model = gp.Model("headway_reduction_waiting_equivalence")
    model.Params.OutputFlag = 0
    movement = EanMovementModelBuilder().build(
        model=model,
        binary_vtype=gp.GRB.BINARY,
        artifact=artifact,
        optimization_config=EanOptimizationConfig(),
    )
    first_keys = ((0, 0), (1, 0))
    for key in first_keys:
        model.addConstr(movement.variables.stop[key] == 1)
    model.addConstr(movement.variables.wait_time[(0, 0)] == 1.0)
    model.addConstr(movement.variables.wait_time[(1, 0)] == 0.0)
    model.setObjective(0.0, gp.GRB.MINIMIZE)
    model.optimize()
    return model.Status, movement.extract_plan()
