from dataclasses import replace
from time import perf_counter

import pytest
from test_optimization_ddd_cp_sat_integrated import tiny_problem, fixed_ip
from test_optimization_ddd_reservation_insertion import skip_seed
from ropeway_skip_stop_optimization.benchmarking.ddd_scaling import (
    build_initial_ddd_network_problem,
)
from ropeway_skip_stop_optimization.optimization.ddd.primal_evaluation import (
    DddEanPassengerPrimalEvaluator,
)
from ropeway_skip_stop_optimization.optimization.ddd.reservation_refinement import (
    DddReservationAssignmentRefiner,
)
from ropeway_skip_stop_optimization.optimization.ddd.reservation_optimizer import (
    DddReservationInsertionOptimizer,
)
from ropeway_skip_stop_optimization.optimization.ddd.reservation_models import (
    DddReservationInsertionConfig,
)
from ropeway_skip_stop_optimization.optimization.ddd.reservation_passenger import (
    DddServiceInsertionCandidateBuilder,
)
from ropeway_skip_stop_optimization.optimization.ddd.fixed_k_certificate import (
    DddFixedKPrimalValidator,
)


def test_refiner_uses_canonical_custom_demand_and_matches_independent_ip():
    scenario, p = tiny_problem(horizon=130, maximum_wait=20)
    initial = skip_seed(p)
    best = (
        DddReservationInsertionOptimizer(
            DddReservationInsertionConfig(
                total_time_limit_seconds=10, attempt_time_limit_seconds=1
            )
        )
        .optimize(
            problem=p,
            initial_plan=initial,
            intents=DddServiceInsertionCandidateBuilder().build(p, initial, limit=4),
        )
        .best_plan
    )
    empty = DddFixedKPrimalValidator().validate(
        p, best.solution, {}, provenance="empty_assignment"
    )
    trajectory = p.resolved_trajectory_problem
    evaluator = DddEanPassengerPrimalEvaluator(
        scenario,
        p.artifact,
        waiting_policy=trajectory.waiting_policy,
        passenger_candidate_build=p.passenger_build,
    )
    refiner = DddReservationAssignmentRefiner(
        evaluator,
        build_initial_ddd_network_problem(
            trajectory.structural_movement_problem, trajectory.waiting_policy
        ),
    )
    refined = refiner.refine(
        p, empty, deadline=perf_counter() + 10, time_limit_seconds=2
    )
    assert refined.improved
    assert refined.plan.solution == empty.solution
    assert refined.plan.objective == pytest.approx(
        fixed_ip(scenario, p, empty.solution)[0], abs=1e-6
    )
    expired = refiner.refine(p, empty, deadline=0, time_limit_seconds=2)
    assert expired.plan is empty and expired.status == "BUDGET_EXHAUSTED"
    wrong = replace(
        refiner,
        evaluator=replace(
            evaluator,
            passenger_candidate_build=replace(p.passenger_build, ride_candidates=()),
        ),
    )
    with pytest.raises(ValueError, match="domain"):
        wrong.refine(p, empty, deadline=perf_counter() + 10, time_limit_seconds=2)
    again = refiner.refine(
        p, refined.plan, deadline=perf_counter() + 10, time_limit_seconds=2
    )
    assert not again.improved and again.plan is refined.plan
