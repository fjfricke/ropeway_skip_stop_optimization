from dataclasses import replace
from pathlib import Path
import pytest
from ortools.sat.python import cp_model
from test_optimization_ddd_reservoir_ibm_cp import short_problem
from test_optimization_ddd_cp_sat_integrated import tiny_problem
from ropeway_skip_stop_optimization.optimization.ddd.cp_formulation import (
    DddCpFormulationConfig,
    DddCpFormulationProfile,
    prepare_cp_structure,
)
from ropeway_skip_stop_optimization.optimization.ddd.cp_sat_integrated import (
    DddIntegratedCpSatConfig,
    DddIntegratedCpSatOptimizer,
)
from ropeway_skip_stop_optimization.optimization.ddd.reservoir_cp_sat import (
    DddReservoirCpSatOptimizer,
)
from ropeway_skip_stop_optimization.optimization.ddd.reservoir_cp_sat_certificate import (
    DddReservoirCpPlan,
    DddReservoirCpTrip,
)
from ropeway_skip_stop_optimization.optimization.ddd.reservoir_ibm_cp import (
    DddReservoirIbmCpOptimizer,
    DddReservoirIbmCpConfig,
)
from ropeway_skip_stop_optimization.optimization.ddd.cp_sat_capacity import (
    DddCpSatCapacityOptimizer,
)

ENGINE = Path(
    "/Users/felix/Applications/CPLEX_Studio222/cpoptimizer/bin/arm64_osx/cpoptimizer"
)


@pytest.mark.parametrize("profile", list(DddCpFormulationProfile))
def test_cp_profiles_same_small_optimum_and_seed(profile):
    p = short_problem()
    old = DddReservoirCpSatOptimizer().solve(p)
    trips = tuple(
        DddReservoirCpTrip(
            t["cabin_id"],
            tuple(t["route_option_ids"]),
            tuple(t["switch_ticks"]),
            tuple(t["wait_ticks"]),
            t["return_tick"],
        )
        for t in old["plan"]["trips"]
    )
    seed = DddReservoirCpPlan(trips, old["plan"]["ride_counts"])
    result = DddReservoirCpSatOptimizer(
        DddIntegratedCpSatConfig(formulation=DddCpFormulationConfig(profile=profile))
    ).solve(p, primal_seed=seed)
    assert result["proven_optimal"] and result["validated_upper_bound"] == 2
    assert result["problem_fingerprint"] == old["problem_fingerprint"]


@pytest.mark.parametrize("profile", list(DddCpFormulationProfile))
@pytest.mark.parametrize("encoding", ["legacy", "native_visits"])
def test_ibm_profiles_match_small_optimum(profile, encoding):
    if not ENGINE.exists():
        pytest.skip("unrestricted IBM not installed")
    result = DddReservoirIbmCpOptimizer(
        DddReservoirIbmCpConfig(
            executable=ENGINE,
            total_time_limit_seconds=10,
            log_search_progress=False,
            formulation=DddCpFormulationConfig(
                profile=profile, movement_encoding=encoding
            ),
        )
    ).solve(short_problem())
    assert result["error"] is None
    assert result["proven_optimal"] and result["validated_upper_bound"] == 2


@pytest.mark.parametrize("profile", list(DddCpFormulationProfile))
@pytest.mark.parametrize("encoding", ["legacy", "compact_fixed", "merged_exit"])
def test_fixed_profiles_keep_optimum_and_physics(profile, encoding):
    _, p = tiny_problem(horizon=80, starts=(0.0, 8.0))
    config = DddIntegratedCpSatConfig(
        formulation=DddCpFormulationConfig(profile=profile, resource_encoding=encoding)
    )
    baseline = DddIntegratedCpSatOptimizer().solve(p)
    result = DddIntegratedCpSatOptimizer(config).solve(
        p, primal_seed=baseline.incumbent
    )
    assert result.proven_optimal
    assert result.validated_upper_bound == baseline.validated_upper_bound
    capacity = DddCpSatCapacityOptimizer(config).solve(
        p, primal_seed=baseline.incumbent
    )
    old_capacity = DddCpSatCapacityOptimizer().solve(p, primal_seed=baseline.incumbent)
    assert (
        capacity["unserved_upper_bound"]
        == capacity["unserved_lower_bound"]
        == old_capacity["unserved_upper_bound"]
    )
    assert capacity["model_stats"]["cost_auxiliaries"] == 0


def test_backend_options_fail_before_build():
    with pytest.raises(ValueError):
        DddCpFormulationConfig(movement_encoding="native_visits").validate()
    with pytest.raises(ValueError):
        DddCpFormulationConfig(resource_encoding="merged_exit").validate("ibm")


@pytest.mark.parametrize("encoding", ["legacy", "compact_fixed", "merged_exit"])
def test_all_enumerated_waiting_movements_remain_feasible(encoding):
    from test_optimization_ddd_cp_sat_waiting import enumerate_waiting
    from test_optimization_ddd_cp_sat_integrated import fixed_ip
    from ropeway_skip_stop_optimization.optimization.ean.models import EanDemandGroup

    scenario, p = tiny_problem(
        horizon=75,
        maximum_wait=2,
        waiting_step=1,
        groups=(EanDemandGroup("late", "A", "B", 23, 2),),
    )
    opt = DddIntegratedCpSatOptimizer(
        DddIntegratedCpSatConfig(
            total_time_limit_seconds=5,
            formulation=DddCpFormulationConfig(
                profile="strengthened", resource_encoding=encoding
            ),
        )
    )
    values = []
    for sol in enumerate_waiting(p):
        expected = fixed_ip(scenario, p, sol)[0]
        result = opt.solve(p, fixed_movement=sol)
        assert result.proven_optimal and result.validated_upper_bound == pytest.approx(
            expected, abs=1e-6
        )
        values.append(expected)
    assert opt.solve(p).validated_upper_bound == pytest.approx(min(values), abs=1e-6)


@pytest.mark.parametrize("encoding", ["legacy", "compact_fixed", "merged_exit"])
@pytest.mark.parametrize("decision,feasible", [("stop", False), ("skip", True)])
def test_resource_variant_preserves_waiting_bypass(decision, feasible, encoding):
    from ropeway_skip_stop_optimization.optimization.ddd.cp_sat_integrated import (
        build_ddd_integrated_cp_sat,
    )

    _, p = tiny_problem(horizon=60, starts=(0, 15), maximum_wait=20, groups=())
    b = build_ddd_integrated_cp_sat(
        p,
        formulation=DddCpFormulationConfig(
            profile="strengthened", resource_encoding=encoding
        ),
    )
    options = {
        o.id: o
        for o in p.resolved_trajectory_problem.structural_movement_problem.route_options
    }
    for (k, i, oid), lit in b.movement.selection_by_key.items():
        if i == 0:
            b.movement.model.add(
                lit
                == int(options[oid].decision.value == ("stop" if k == 0 else decision))
            )
    b.movement.model.add(b.movement.wait_steps_by_key[0, 0] == 20)
    solver = cp_model.CpSolver()
    status = solver.solve(b.movement.model)
    assert (status == cp_model.OPTIMAL) == feasible


@pytest.mark.parametrize("native", ["legacy", "native_visits"])
def test_ibm_waiting_seed_native_intervals(native):
    from test_optimization_ddd_reservoir_arc_flow import _problem
    from test_optimization_ddd_reservoir_cp_sat import trip, T
    from ropeway_skip_stop_optimization.optimization.ddd.reservoir_cp_sat_problem import (
        DddReservoirCpSatProblem,
    )

    p = DddReservoirCpSatProblem.from_arc_flow(_problem(waiting=True, fleet=2))
    t = trip(dispatch=5)
    t = replace(t, wait_ticks=(T, 0), switch_ticks=(5 * T, 8 * T), return_tick=10 * T)
    plan = DddReservoirCpPlan((t,), {})
    result = DddReservoirIbmCpOptimizer(
        DddReservoirIbmCpConfig(
            executable=ENGINE,
            total_time_limit_seconds=5,
            log_search_progress=False,
            formulation=DddCpFormulationConfig(
                profile="strengthened", movement_encoding=native
            ),
        )
    ).solve(p, fixed_plan=plan, primal_seed=plan)
    baseline = DddReservoirCpSatOptimizer().solve(p, fixed_plan=plan)
    assert (
        result["proven_optimal"]
        and result["validated_upper_bound"] == baseline["validated_upper_bound"]
    )


@pytest.mark.parametrize("encoding", ["legacy", "compact_fixed", "merged_exit"])
def test_long_fixed_terminal_wait_not_pruned(encoding):
    from ropeway_skip_stop_optimization.optimization.ddd.reference import (
        DddReferenceSolution,
        DddReferenceTrajectory,
        build_ddd_reference_visit,
    )

    _, p = tiny_problem(horizon=80, maximum_wait=1200, waiting_step=1e-6)
    movement = p.resolved_trajectory_problem.structural_movement_problem
    start = movement.starts[0]
    stop = next(
        o
        for o in movement.route_options_by_state_id[start.state_id]
        if o.decision.value == "stop"
    )
    visit = build_ddd_reference_visit(
        start=start,
        visit_index=0,
        switch_time_seconds=0,
        option=stop,
        operational_end_seconds=80,
        wait_seconds=1200,
        tolerance_seconds=1e-9,
    )
    sol = DddReferenceSolution((DddReferenceTrajectory(0, (visit,)),))
    result = DddIntegratedCpSatOptimizer(
        DddIntegratedCpSatConfig(
            formulation=DddCpFormulationConfig(
                profile="strengthened", resource_encoding=encoding
            )
        )
    ).solve(p, fixed_movement=sol)
    assert result.proven_optimal
    assert (
        result.incumbent.solution.trajectories[0].visits[0].next_switch_time_seconds
        > 1200
    )


def test_reservoir_pruning_and_lower_bound_known_case():
    from ropeway_skip_stop_optimization.benchmarking.ddd_reservoir_arc_flow import (
        DddReservoirArcFlowRunConfig,
        prepare_ddd_reservoir_arc_flow_run,
    )
    from ropeway_skip_stop_optimization.optimization.ddd.reservoir_cp_sat_problem import (
        DddReservoirCpSatProblem,
    )

    p = DddReservoirCpSatProblem.from_arc_flow(
        prepare_ddd_reservoir_arc_flow_run(
            DddReservoirArcFlowRunConfig(
                example_id="five_station_circle_cw_half_skip_no_wait_headway_b_v0",
                available_fleet_count=50,
                waiting_max_seconds=1200,
                waiting_step_seconds=1e-6,
            )
        ).problem
    )
    prepared = prepare_cp_structure(
        p.movement,
        p.passenger_build,
        {k: p.visit_states for k in range(50)},
        reservoir=p,
    )
    assert len(prepared.rides) == 10100
    assert sum(r.exclusion is not None for r in prepared.rides) == 1800
    assert prepared.analytical_lower_bound == 109032727040
