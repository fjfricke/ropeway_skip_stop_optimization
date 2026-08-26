from __future__ import annotations

import itertools
from dataclasses import replace
import json

import pytest

from ropeway_skip_stop_optimization.optimization.ddd import (
    DddArcFlowPassengerCapacityRow,
    DddArcFlowPassengerDemandRow,
    DddArcFlowPassengerDomain,
    DddArcFlowPassengerModelBuilder,
    DddArcFlowPassengerVariable,
    DddArcFlowProblemPreparer,
    DddArcFlowRelaxationConfig,
    DddArcFlowRelaxationMethod,
    DddArcFlowRelaxationOptimizer,
    DddArcFlowRelaxationStatus,
    DddOuterLoopLpBendersConfig,
    DddOuterLoopLpBendersSolver,
    DddOuterLoopLpBendersStatus,
    DddFixedKArcFlowOptimizer,
    DddFixedKArcFlowSolveConfig,
    DddFixedKOperatingMode,
)
from ropeway_skip_stop_optimization.optimization.ean import (
    EanPassengerAssignmentDomain,
)


def _synthetic_domain() -> DddArcFlowPassengerDomain:
    variables = (
        DddArcFlowPassengerVariable(
            id="y[a]",
            candidate_id="ride",
            demand_group_id="d",
            cabin_id=0,
            board_visit_index=0,
            alight_visit_index=1,
            arc_id="a",
            visit_index=0,
            upper_bound=1.0,
            objective_coefficient=-6.0,
        ),
        DddArcFlowPassengerVariable(
            id="y[b]",
            candidate_id="ride",
            demand_group_id="d",
            cabin_id=0,
            board_visit_index=0,
            alight_visit_index=1,
            arc_id="b",
            visit_index=0,
            upper_bound=1.0,
            objective_coefficient=-5.0,
        ),
    )
    return DddArcFlowPassengerDomain(
        problem_fingerprint="synthetic",
        objective_constant=10.0,
        variables=variables,
        flows=(),
        equality_rows=(),
        demand_rows=(
            DddArcFlowPassengerDemandRow(
                id="demand[d]",
                demand_group_id="d",
                variable_ids=("y[a]", "y[b]"),
                right_hand_side=1.0,
            ),
        ),
        capacity_rows=(
            DddArcFlowPassengerCapacityRow(
                id="capacity[a_needs_b]",
                arc_id="b",
                variable_ids=("y[a]",),
                movement_coefficient=1.0,
            ),
        ),
        fingerprint="synthetic",
    )


def test_lp_dual_cuts_are_globally_valid_on_exhaustive_binary_domain() -> None:
    recourse = DddArcFlowPassengerModelBuilder().build_recourse(
        domain=_synthetic_domain(),
        assignment_domain=EanPassengerAssignmentDomain.LP_RELAXATION,
    )
    vectors = tuple(
        {"a": float(a), "b": float(b)}
        for a, b in itertools.product((0, 1), repeat=2)
    )
    evaluations = tuple(recourse.evaluate(vector) for vector in vectors)

    assert tuple(item.objective_value for item in evaluations) == pytest.approx(
        (10.0, 5.0, 10.0, 4.0)
    )
    for source_vector, source in zip(vectors, evaluations, strict=True):
        assert source.benders_cut is not None
        assert source.benders_cut.evaluate(source_vector) == pytest.approx(
            source.objective_value
        )
        for target_vector, target in zip(vectors, evaluations, strict=True):
            assert target.objective_value is not None
            assert source.benders_cut.evaluate(target_vector) <= (
                target.objective_value + 1e-8
            )


def test_recourse_model_reuses_rows_without_stale_rhs_values() -> None:
    recourse = DddArcFlowPassengerModelBuilder().build_recourse(
        domain=_synthetic_domain(),
        assignment_domain=EanPassengerAssignmentDomain.INTEGER,
    )

    first = recourse.evaluate({"a": 1.0, "b": 1.0})
    second = recourse.evaluate({"a": 0.0, "b": 0.0})
    third = recourse.evaluate({"a": 1.0, "b": 1.0})

    assert first.objective_value == pytest.approx(4.0)
    assert second.objective_value == pytest.approx(10.0)
    assert third.objective_value == pytest.approx(4.0)
    assert third.evaluation_index == 3
    assert not first.cache_hit
    assert third.cache_hit
    assert third.solve_seconds == 0.0


def test_passenger_domain_and_cut_survive_json_roundtrip() -> None:
    domain = _synthetic_domain()
    restored_domain = DddArcFlowPassengerDomain.from_payload(
        json.loads(json.dumps(domain.to_payload()))
    )
    recourse = DddArcFlowPassengerModelBuilder().build_recourse(
        domain=restored_domain,
        assignment_domain=EanPassengerAssignmentDomain.LP_RELAXATION,
    )
    evaluation = recourse.evaluate({"a": 1.0, "b": 1.0})
    assert evaluation.benders_cut is not None

    restored_cut = type(evaluation.benders_cut).from_payload(
        json.loads(json.dumps(evaluation.benders_cut.to_payload()))
    )

    assert restored_domain == domain
    assert restored_cut == evaluation.benders_cut


def test_outer_lp_benders_matches_monolithic_tiny_case() -> None:
    from test_optimization_ddd_arc_flow import _fixed_problem

    problem = replace(
        _fixed_problem(),
        operating_mode=DddFixedKOperatingMode.ALL_STOP,
    )
    monolithic = DddFixedKArcFlowOptimizer(
        DddFixedKArcFlowSolveConfig(time_limit_seconds=10.0)
    ).solve(problem)
    result = DddOuterLoopLpBendersSolver(
        DddOuterLoopLpBendersConfig(
            time_limit_seconds=10.0,
            max_iterations=5,
        )
    ).solve(DddArcFlowProblemPreparer().build(problem))

    assert result.status is DddOuterLoopLpBendersStatus.INTEGER_OPTIMAL
    assert result.projected_lp_certified
    assert result.cut_count > 0
    assert result.validated_upper_bound == pytest.approx(
        monolithic.objective_value
    )
    assert result.certified_lower_bound == pytest.approx(
        result.validated_upper_bound
    )
    assert all(
        current.certified_lower_bound
        >= previous.certified_lower_bound - 1e-6
        for previous, current in itertools.pairwise(result.iterations)
    )


def test_outer_lp_benders_improves_certified_bound_on_skip_stop_case() -> None:
    from test_optimization_ddd_arc_flow import _fixed_problem

    result = DddOuterLoopLpBendersSolver(
        DddOuterLoopLpBendersConfig(
            time_limit_seconds=10.0,
            max_iterations=5,
        )
    ).solve(DddArcFlowProblemPreparer().build(_fixed_problem()))

    assert result.status in {
        DddOuterLoopLpBendersStatus.INTEGER_OPTIMAL,
        DddOuterLoopLpBendersStatus.ITERATION_LIMIT_WITH_CERTIFIED_INTERVAL,
    }
    assert result.cut_count == 5 or result.status is (
        DddOuterLoopLpBendersStatus.INTEGER_OPTIMAL
    )
    assert result.certified_lower_bound > 0.0
    assert result.validated_upper_bound is not None
    assert result.certified_lower_bound <= result.validated_upper_bound


def test_complete_arc_flow_relaxation_matches_tiny_integer_optimum() -> None:
    from test_optimization_ddd_arc_flow import _fixed_problem

    problem = _fixed_problem()
    monolithic = DddFixedKArcFlowOptimizer(
        DddFixedKArcFlowSolveConfig(time_limit_seconds=10.0)
    ).solve(problem)
    relaxation = DddArcFlowRelaxationOptimizer(
        DddArcFlowRelaxationConfig(
            time_limit_seconds=10.0,
            method=DddArcFlowRelaxationMethod.DUAL_SIMPLEX,
        )
    ).solve(DddArcFlowProblemPreparer().build(problem))

    assert relaxation.status is DddArcFlowRelaxationStatus.OPTIMAL
    assert relaxation.certified_lower_bound == pytest.approx(
        monolithic.objective_value
    )
    assert relaxation.lp_primal_objective == pytest.approx(
        relaxation.certified_lower_bound
    )
    assert relaxation.movement_fractional_variable_count == 0
    assert relaxation.passenger_fractional_variable_count == 0
