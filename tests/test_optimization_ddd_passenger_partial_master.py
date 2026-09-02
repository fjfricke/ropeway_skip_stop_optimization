from __future__ import annotations

from dataclasses import replace

import pytest

from ropeway_skip_stop_optimization.examples.registry import get_example
from ropeway_skip_stop_optimization.optimization.ddd import (
    DddArcFlowPassengerDomainBuilder,
    DddArcFlowPassengerModelBuilder,
    DddArcFlowProblemPreparer,
    DddArcFlowRelaxationConfig,
    DddArcFlowRelaxationOptimizer,
    DddFixedKMovementArcFlowConfig,
    DddFixedKMovementArcFlowOptimizer,
    DddMovementArcFlowObjectiveMode,
    DddFixedKOperatingMode,
    DddFixedKStartPolicy,
    DddFixedKTrajectoryProblem,
    DddPartialPassengerDomainBuilder,
    DddPartialPassengerModelBuilder,
    DddPartialPassengerRootConfig,
    DddPartialPassengerCutStrategy,
    DddPartialPassengerRootCutSolver,
    DddPartialPassengerRootStatus,
    DddParetoPassengerCutGenerator,
    DddPassengerCorePoint,
    DddPassengerCouplingComponentIndex,
    DddPassengerCoreConfig,
    DddPassengerCorePolicy,
    EanArtifactToDddMovementProblemAdapter,
    build_ddd_arc_flow_passenger_subdomain,
    build_ddd_arc_flow_movement_values,
)
from ropeway_skip_stop_optimization.optimization.ean import (
    CanonicalFixedKRopeCabinStartBuilder,
    EanPassengerCandidateBuilder,
    EanPassengerObjective,
    SparseHeadwayPairBuilder,
    EanPassengerAssignmentDomain,
)


EXAMPLE_ID = "five_station_circle_cw_half_skip_no_wait_v0"


def _prepared_problem():
    example = get_example(EXAMPLE_ID)
    scenario = example.build_scenario()
    config = example.build_ean_config(scenario)
    artifact = replace(
        example.build_ean_artifact_builder(scenario, config),
        start_builder=CanonicalFixedKRopeCabinStartBuilder(1),
        headway_pair_builder=SparseHeadwayPairBuilder(),
    ).build(scenario, config)
    problem = DddFixedKTrajectoryProblem(
        trajectory_problem=(
            EanArtifactToDddMovementProblemAdapter().build_trajectory_problem(
                artifact
            )
        ),
        artifact=artifact,
        passenger_build=EanPassengerCandidateBuilder().build(scenario, artifact),
        objective=EanPassengerObjective.JOURNEY_TIME,
        operating_mode=DddFixedKOperatingMode.SKIP_STOP,
        start_policy=DddFixedKStartPolicy.CANONICAL_ROPE,
    )
    return DddArcFlowProblemPreparer().build(problem)


def test_none_and_all_partitions_are_exact_domain_boundaries() -> None:
    prepared = _prepared_problem()
    domain = DddArcFlowPassengerDomainBuilder().build(prepared)
    builder = DddPartialPassengerDomainBuilder()

    none = builder.build(
        prepared,
        domain,
        DddPassengerCoreConfig(policy=DddPassengerCorePolicy.NONE),
    )
    all_groups = builder.build(
        prepared,
        domain,
        DddPassengerCoreConfig(policy=DddPassengerCorePolicy.ALL),
    )

    assert not none.core_domain.variables
    assert none.residual_domain.variables == domain.variables
    assert none.partition.residual_variable_count == len(domain.variables)
    assert all_groups.core_domain.variables == domain.variables
    assert not all_groups.residual_domain.variables
    assert all_groups.partition.core_variable_count == len(domain.variables)
    assert none.core_domain.objective_constant == pytest.approx(0.0)
    assert none.residual_domain.objective_constant == pytest.approx(
        domain.objective_constant
    )
    assert all_groups.core_domain.objective_constant == pytest.approx(
        domain.objective_constant
    )


def test_partial_domain_preserves_every_variable_and_capacity_incidence() -> None:
    prepared = _prepared_problem()
    domain = DddArcFlowPassengerDomainBuilder().build(prepared)
    variable_counts = {}
    nonzero_counts = {}
    for variable in domain.variables:
        variable_counts[variable.demand_group_id] = (
            variable_counts.get(variable.demand_group_id, 0) + 1
        )
    control = DddPartialPassengerDomainBuilder().selector.build_partition(
        prepared,
        domain,
        DddPassengerCoreConfig(policy=DddPassengerCorePolicy.ALL),
    )
    for item in control.statistics:
        nonzero_counts[item.demand_group_id] = item.passenger_nonzero_count
    maximum_variables = min(value for value in variable_counts.values() if value > 0)
    maximum_nonzeros = max(nonzero_counts.values())
    partial = DddPartialPassengerDomainBuilder().build(
        prepared,
        domain,
        DddPassengerCoreConfig(
            policy=DddPassengerCorePolicy.DEMAND_MASS,
            maximum_variable_count=maximum_variables,
            maximum_nonzero_count=maximum_nonzeros,
        ),
    )

    partial.validate(prepared, domain)
    assert partial.partition.core_variable_count <= maximum_variables
    assert partial.partition.core_nonzero_count <= maximum_nonzeros
    assert {
        variable.id for variable in partial.core_domain.variables
    } | {
        variable.id for variable in partial.residual_domain.variables
    } == {variable.id for variable in domain.variables}
    for row, coupling in zip(
        domain.capacity_rows,
        partial.capacity_couplings,
        strict=True,
    ):
        assert set(coupling.core_variable_ids) | set(
            coupling.residual_variable_ids
        ) == set(row.variable_ids)
        assert not set(coupling.core_variable_ids) & set(
            coupling.residual_variable_ids
        )
    component_index = DddPassengerCouplingComponentIndex.build(partial)
    component_index.validate(partial)
    assert sum(
        len(component.demand_group_ids)
        for component in component_index.components
    ) == len(partial.partition.residual_demand_group_ids)


def test_passenger_core_selection_is_deterministic_and_fingerprinted() -> None:
    prepared = _prepared_problem()
    domain = DddArcFlowPassengerDomainBuilder().build(prepared)
    config = DddPassengerCoreConfig(
        policy=DddPassengerCorePolicy.HYBRID,
        maximum_variable_count=max(1, len(domain.variables) // 3),
        maximum_nonzero_count=max(1, domain.constraint_count),
    )
    selector = DddPartialPassengerDomainBuilder().selector

    first = selector.build_partition(prepared, domain, config)
    second = selector.build_partition(prepared, domain, config)

    assert first == second
    assert first.fingerprint == second.fingerprint
    first.validate(domain)
    assert first.core_variable_count <= config.maximum_variable_count
    assert first.core_nonzero_count <= config.maximum_nonzero_count


def test_passenger_subdomain_rejects_unknown_demand_group() -> None:
    prepared = _prepared_problem()
    domain = DddArcFlowPassengerDomainBuilder().build(prepared)

    with pytest.raises(ValueError, match="unknown demand groups"):
        build_ddd_arc_flow_passenger_subdomain(
            domain,
            demand_group_ids=frozenset({"missing"}),
            objective_constant=0.0,
            prepared=prepared,
        )


def test_partial_recourse_subtracts_core_load_and_cut_is_tight() -> None:
    prepared = _prepared_problem()
    domain = DddArcFlowPassengerDomainBuilder().build(prepared)
    statistics = DddPartialPassengerDomainBuilder().selector.build_partition(
        prepared,
        domain,
        DddPassengerCoreConfig(policy=DddPassengerCorePolicy.ALL),
    ).statistics
    selected = max(
        (item for item in statistics if item.variable_count > 0),
        key=lambda item: (item.demand_count, item.demand_group_id),
    )
    partial = DddPartialPassengerDomainBuilder().build(
        prepared,
        domain,
        DddPassengerCoreConfig(
            policy=DddPassengerCorePolicy.DEMAND_MASS,
            maximum_variable_count=selected.variable_count,
            maximum_nonzero_count=max(
                item.passenger_nonzero_count for item in statistics
            ),
        ),
    )
    movement = DddFixedKMovementArcFlowOptimizer(
        DddFixedKMovementArcFlowConfig(time_limit_seconds=10.0)
    ).solve_prepared(prepared)
    assert movement.solution is not None
    movement_values = build_ddd_arc_flow_movement_values(
        prepared,
        movement.solution,
    )
    full_lp = DddArcFlowPassengerModelBuilder().build_recourse(
        domain=domain,
        assignment_domain=EanPassengerAssignmentDomain.LP_RELAXATION,
    ).evaluate(movement_values)
    assert full_lp.optimal
    assert full_lp.objective_value is not None
    full_values = dict(full_lp.variable_values)
    core_values = {
        variable.id: full_values[variable.id]
        for variable in partial.core_domain.variables
    }
    residual = DddPartialPassengerModelBuilder().build_residual_recourse(
        domain=partial
    ).evaluate(movement_values, core_values)

    assert residual.recourse.optimal
    assert residual.recourse.objective_value is not None
    assert residual.cut is not None
    core_objective = partial.core_domain.objective_constant + sum(
        variable.objective_coefficient * core_values[variable.id]
        for variable in partial.core_domain.variables
    )
    assert core_objective + residual.recourse.objective_value == pytest.approx(
        full_lp.objective_value
    )
    assert residual.cut.evaluate(movement_values, core_values) == pytest.approx(
        residual.recourse.objective_value
    )
    offsets = partial.capacity_offsets(core_values)
    assert all(value >= -1e-8 for value in offsets.values())


def test_all_core_root_model_matches_complete_monolithic_lp() -> None:
    prepared = _prepared_problem()
    complete = DddArcFlowRelaxationOptimizer(
        DddArcFlowRelaxationConfig(time_limit_seconds=10.0)
    ).solve(prepared)
    partial = DddPartialPassengerRootCutSolver(
        DddPartialPassengerRootConfig(
            core=DddPassengerCoreConfig(policy=DddPassengerCorePolicy.ALL),
            time_limit_seconds=10.0,
            max_iterations=2,
        )
    ).solve(prepared)

    assert partial.status is DddPartialPassengerRootStatus.PROJECTED_LP_OPTIMAL
    assert partial.projected_lp_certified
    assert partial.cut_count == 0
    assert partial.projected_lp_objective == pytest.approx(
        complete.lp_primal_objective
    )
    assert partial.certified_lower_bound == pytest.approx(
        complete.certified_lower_bound
    )


def test_partial_dual_cuts_are_valid_at_other_feasible_core_points() -> None:
    prepared = _prepared_problem()
    domain = DddArcFlowPassengerDomainBuilder().build(prepared)
    partial = DddPartialPassengerDomainBuilder().build(
        prepared,
        domain,
        DddPassengerCoreConfig(
            policy=DddPassengerCorePolicy.HYBRID,
            maximum_variable_count=max(1, len(domain.variables) // 4),
            maximum_nonzero_count=max(1, domain.constraint_count),
        ),
    )
    full_recourse = DddArcFlowPassengerModelBuilder().build_recourse(
        domain=domain,
        assignment_domain=EanPassengerAssignmentDomain.LP_RELAXATION,
    )
    partial_recourse = DddPartialPassengerModelBuilder().build_residual_recourse(
        domain=partial
    )
    points = []
    for seed in range(2):
        movement = DddFixedKMovementArcFlowOptimizer(
            DddFixedKMovementArcFlowConfig(
                time_limit_seconds=10.0,
                seed=seed,
                objective_mode=(
                    DddMovementArcFlowObjectiveMode.DETERMINISTIC_DIVERSIFICATION
                ),
            )
        ).solve_prepared(prepared)
        assert movement.solution is not None
        movement_values = build_ddd_arc_flow_movement_values(
            prepared,
            movement.solution,
        )
        full = full_recourse.evaluate(movement_values)
        assert full.optimal
        full_values = dict(full.variable_values)
        core_values = {
            variable.id: full_values[variable.id]
            for variable in partial.core_domain.variables
        }
        residual = partial_recourse.evaluate(movement_values, core_values)
        assert residual.cut is not None
        assert residual.recourse.objective_value is not None
        points.append((movement_values, core_values, residual))

    for _, _, source in points:
        assert source.cut is not None
        for movement_values, core_values, target in points:
            assert target.recourse.objective_value is not None
            assert source.cut.evaluate(movement_values, core_values) <= (
                target.recourse.objective_value + 1e-5
            )

    source_movement, source_core, source = points[0]
    target_movement, target_core, target = points[1]
    assert source.recourse.objective_value is not None
    pareto = DddParetoPassengerCutGenerator(partial).generate(
        source_movement_values=source_movement,
        source_core_values=source_core,
        source_objective=source.recourse.objective_value,
        core_point=DddPassengerCorePoint.from_point(
            target_movement,
            target_core,
        ),
        time_limit_seconds=10.0,
    )

    assert pareto.optimal
    assert pareto.cut is not None
    assert pareto.source_value == pytest.approx(source.recourse.objective_value)
    assert target.recourse.objective_value is not None
    assert pareto.cut.evaluate(target_movement, target_core) <= (
        target.recourse.objective_value + 1e-5
    )
    assert pareto.core_point_value is not None
    assert source.cut is not None
    assert pareto.core_point_value >= source.cut.evaluate(
        target_movement,
        target_core,
    ) - 1e-5


def test_core_point_root_strategy_adds_strengthened_cuts_after_first_round() -> None:
    prepared = _prepared_problem()
    domain = DddArcFlowPassengerDomainBuilder().build(prepared)
    result = DddPartialPassengerRootCutSolver(
        DddPartialPassengerRootConfig(
            core=DddPassengerCoreConfig(
                policy=DddPassengerCorePolicy.HYBRID,
                maximum_variable_count=max(1, len(domain.variables) // 5),
                maximum_nonzero_count=max(1, domain.constraint_count),
            ),
            cut_strategy=DddPartialPassengerCutStrategy.CORE_POINT,
            time_limit_seconds=10.0,
            pareto_time_limit_seconds=2.0,
            max_iterations=4,
        )
    ).solve(prepared, passenger_domain=domain)

    assert result.cut_count == 4
    assert result.iterations[0].cut_kind == "partial_lp_dual_optimality"
    assert any(
        item.cut_kind == "core_point_strengthened"
        for item in result.iterations[1:]
    )
    assert result.pareto_solve_seconds > 0
