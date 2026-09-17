from dataclasses import replace

import pytest

from test_optimization_ddd_reservoir_cp_sat import T, problem, trip
from ropeway_skip_stop_optimization.benchmarking.reservoir_cp_fleet_continuation import (
    FleetContinuationBudget,
    FleetContinuationConfig,
    plan_diagnostics,
    stage_problem,
)
from ropeway_skip_stop_optimization.optimization.ddd.cp_sat_integrated import (
    DddIntegratedCpSatConfig,
)
from ropeway_skip_stop_optimization.optimization.ddd.reservoir_cp_sat import (
    DddReservoirCpObjective,
    DddReservoirCpSatOptimizer,
)
from ropeway_skip_stop_optimization.optimization.ddd.reservoir_cp_sat_certificate import (
    DddReservoirCpPlan,
    read_reservoir_cp_checkpoint_for_fleet_resize,
    validate_reservoir_cp_plan,
    write_reservoir_cp_checkpoint,
)
from ropeway_skip_stop_optimization.optimization.ean.models import EanDemandGroup


def test_budget_schedule_is_exact_and_leaves_five_minute_reserve(tmp_path):
    budget = FleetContinuationBudget()
    assert budget.seconds_for(1) == budget.seconds_for(10) == 30
    assert budget.seconds_for(11) == budget.seconds_for(25) == 90
    assert budget.seconds_for(26) == budget.seconds_for(50) == 210
    assert budget.scheduled_seconds == 6900
    case = tmp_path / "case.json"
    case.write_text("{}")
    FleetContinuationConfig(case, tmp_path / "out").validate()
    with pytest.raises(ValueError, match="five minutes"):
        FleetContinuationConfig(
            case, tmp_path / "out", total_time_limit_seconds=7199
        ).validate()


def test_fleet_expansion_preserves_plan_and_objective(tmp_path):
    source = problem(available_fleet_count=1)
    plan = DddReservoirCpPlan((trip(),), {})
    checkpoint = tmp_path / "seed.json"
    write_reservoir_cp_checkpoint(checkpoint, source, plan)
    expanded = replace(source, available_fleet_count=2)
    imported = read_reservoir_cp_checkpoint_for_fleet_resize(checkpoint, expanded)
    assert imported == plan
    assert validate_reservoir_cp_plan(source, plan).journey_time_tick == validate_reservoir_cp_plan(expanded, imported).journey_time_tick
    assert stage_problem(expanded, 1).available_fleet_count == 1


def test_seed_is_a_hint_and_old_decisions_remain_free():
    p = problem(
        dispatch_end_seconds=3,
        dispatch_step_seconds=1,
        movement_core=replace(
            problem().movement_core,
            passenger_service_end_seconds=3,
            operational_end_seconds=4,
        ),
        demand_groups=(EanDemandGroup("g", "A", "B", 0, 1),),
    )
    # Empty service is valid but suboptimal. A fixed seed would retain cost 3;
    # a genuine hint lets CP-SAT change the existing cabin and reach cost 2.
    seed = DddReservoirCpPlan((), {})
    result = DddReservoirCpSatOptimizer(
        DddIntegratedCpSatConfig(total_time_limit_seconds=5, num_workers=1),
        DddReservoirCpObjective.JOURNEY_TIME,
    ).solve(p, primal_seed=seed)
    assert result["proven_optimal"]
    assert result["validated_upper_bound"] == 2
    assert result["metrics"]["served"] == 1


def test_service_then_journey_is_exactly_lexicographic():
    p = problem(
        dispatch_end_seconds=3,
        dispatch_step_seconds=1,
        movement_core=replace(
            problem().movement_core,
            passenger_service_end_seconds=3,
            operational_end_seconds=4,
        ),
        demand_groups=(EanDemandGroup("g", "A", "B", 0, 1),),
    )
    result = DddReservoirCpSatOptimizer(
        DddIntegratedCpSatConfig(total_time_limit_seconds=5, num_workers=1),
        DddReservoirCpObjective.SERVICE_THEN_JOURNEY,
    ).solve(p, primal_seed=DddReservoirCpPlan((), {}))
    assert result["proven_optimal"]
    assert result["metrics"]["served"] == 1
    assert result["metrics"]["unserved"] == 0
    assert result["journey_time_seconds"] == 2
    assert result["validated_upper_bound"] == 2 * T
    assert result["cp_lower_bound"] == 2 * T


def test_diagnostics_separate_service_and_skip_information():
    p = problem(demand_groups=(EanDemandGroup("g", "A", "B", 0, 1),))
    candidate = next(q for q in p.passenger_build.ride_candidates if q.board_visit_index == 0)
    served = DddReservoirCpPlan((trip(),), {candidate.id: 1})
    diagnostics = plan_diagnostics(p, served)
    assert diagnostics["served"] == 1
    assert diagnostics["mean_served_journey_seconds"] == 2
    assert diagnostics["stop_count"] == 2
    assert diagnostics["skip_count"] == 0
    assert diagnostics["passenger_carrying_skip_count"] == 0


def test_nonfleet_domain_change_is_rejected(tmp_path):
    source = problem(available_fleet_count=1)
    checkpoint = tmp_path / "seed.json"
    write_reservoir_cp_checkpoint(checkpoint, source, DddReservoirCpPlan((), {}))
    incompatible = replace(
        source,
        available_fleet_count=2,
        dispatch_step_seconds=source.dispatch_step_seconds + 1 / T,
    )
    with pytest.raises(ValueError, match="more than the available-fleet cap"):
        read_reservoir_cp_checkpoint_for_fleet_resize(checkpoint, incompatible)
