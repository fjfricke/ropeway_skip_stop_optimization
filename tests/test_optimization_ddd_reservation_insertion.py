from time import perf_counter

import pytest
from test_optimization_ddd_cp_sat_integrated import fixed_ip, tiny_problem

from ropeway_skip_stop_optimization.optimization.ddd.cp_sat_certificate import (
    read_ddd_cp_sat_checkpoint,
    validate_ddd_cp_sat_domain,
)
from ropeway_skip_stop_optimization.optimization.ddd.fixed_k_certificate import (
    DddFixedKPrimalValidator,
    build_ddd_fixed_k_domain_manifest,
)
from ropeway_skip_stop_optimization.optimization.ddd.reference import (
    DddReferenceSolution,
    DddReferenceTrajectory,
    build_ddd_reference_visit,
)
from ropeway_skip_stop_optimization.optimization.ddd.reservation_checkpoint import (
    DddReservationCheckpointAdapter,
)
from ropeway_skip_stop_optimization.optimization.ddd.reservation_models import (
    DddReservationInsertionConfig,
    DddServiceInsertionIntent,
)
from ropeway_skip_stop_optimization.optimization.ddd.reservation_optimizer import (
    DddReservationInsertionOptimizer,
)
from ropeway_skip_stop_optimization.optimization.ddd.reservation_passenger import (
    DddServiceInsertionCandidateBuilder,
)


def skip_seed(problem):
    movement = problem.resolved_trajectory_problem.structural_movement_problem
    trajectories = []
    for start in movement.starts:
        t, state = start.time_seconds, start.state_id
        visits = []
        while t <= movement.operational_end_seconds:
            option = next(
                o
                for o in movement.route_options_by_state_id[state]
                if o.decision.value == "skip"
            )
            v = build_ddd_reference_visit(
                start=start,
                visit_index=len(visits),
                switch_time_seconds=t,
                option=option,
                operational_end_seconds=movement.operational_end_seconds,
                tolerance_seconds=1e-9,
            )
            visits.append(v)
            t, state = v.next_switch_time_seconds, option.to_state_id
        trajectories.append(DddReferenceTrajectory(start.cabin_id, tuple(visits)))
    return DddFixedKPrimalValidator().validate(
        problem, DddReferenceSolution(tuple(trajectories)), {}, provenance="test"
    )


def test_coupled_service_improves_skip_seed_and_is_feasible_for_fixed_ip():
    scenario, p = tiny_problem(horizon=130, maximum_wait=20, waiting_step=1e-6)
    seed = skip_seed(p)
    intents = DddServiceInsertionCandidateBuilder().build(p, seed, limit=4)
    result = DddReservationInsertionOptimizer(
        DddReservationInsertionConfig(
            total_time_limit_seconds=5,
            attempt_time_limit_seconds=1,
            maximum_affected_cabins=1,
        )
    ).optimize(problem=p, initial_plan=seed, intents=intents)
    assert result.distinct_movements > 0
    assert 1 <= len(result.finalist_plans) <= 3
    assert result.best_plan in result.finalist_plans
    assert result.best_plan.objective < seed.objective
    assert (
        fixed_ip(scenario, p, result.best_plan.solution)[0]
        <= result.best_plan.objective + 1e-6
    )
    assert (
        sum(result.best_plan.ride_counts.values())
        + sum(result.best_plan.unserved_counts.values())
        == 7
    )
    assert seed.ride_counts == {}


def test_checkpoint_roundtrip_and_cp_compatibility(tmp_path):
    _, p = tiny_problem(maximum_wait=20, waiting_step=1e-6)
    seed = skip_seed(p)
    adapter = DddReservationCheckpointAdapter()
    path = tmp_path / "new.json"
    adapter.write(path, problem=p, plan=seed)
    restored = adapter.read(path, problem=p)
    assert restored.solution == seed.solution
    assert restored.objective_tick == seed.objective_tick
    assert build_ddd_fixed_k_domain_manifest(p) == validate_ddd_cp_sat_domain(p)
    cp = tmp_path / "cp.json"
    adapter.export_cp_seed(cp, problem=p, plan=restored)
    assert (
        read_ddd_cp_sat_checkpoint(
            cp, problem=p, manifest=validate_ddd_cp_sat_domain(p)
        ).solution
        == seed.solution
    )
    assert adapter.read(cp, problem=p).objective_tick == seed.objective_tick
    _, changed = tiny_problem(maximum_wait=21, waiting_step=1e-6)
    with pytest.raises(ValueError, match="domain"):
        adapter.read(path, problem=changed)


def test_expired_deadline_preserves_best_plan():
    _, p = tiny_problem()
    seed = skip_seed(p)
    result = DddReservationInsertionOptimizer().optimize(
        problem=p, initial_plan=seed, intents=(), deadline=perf_counter() - 1
    )
    assert result.termination_reason == "BUDGET_EXHAUSTED"
    assert result.best_plan.solution == seed.solution
    assert not result.attempts


def test_invalid_request_rejected():
    with pytest.raises(ValueError):
        DddServiceInsertionIntent("a", True)


def test_request_exceeding_shared_capacity_is_not_reported_as_feasible():
    _, p = tiny_problem(horizon=130, capacity=2, maximum_wait=20)
    seed = skip_seed(p)
    q = next(
        q
        for q in p.passenger_build.ride_candidates
        if q.demand_group_id == "ab" and q.board_visit_index == 0
    )
    result = DddReservationInsertionOptimizer(
        DddReservationInsertionConfig(
            total_time_limit_seconds=5, attempt_time_limit_seconds=1
        )
    ).optimize(
        problem=p, initial_plan=seed, intents=(DddServiceInsertionIntent(q.id, 3),)
    )
    assert result.attempts[0].status.value == "NO_CANDIDATE"
    assert result.best_plan.objective_tick == seed.objective_tick


def test_public_facade_exposes_the_composed_optimizer():
    from ropeway_skip_stop_optimization.optimization.ddd import (
        DddReservationInsertionOptimizer as PublicOptimizer,
        DddFixedKPrimalValidator as PublicValidator,
    )

    assert PublicOptimizer is DddReservationInsertionOptimizer
    assert PublicValidator is DddFixedKPrimalValidator
