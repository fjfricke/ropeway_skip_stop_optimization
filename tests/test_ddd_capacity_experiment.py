from dataclasses import replace
from test_optimization_ddd_cp_sat_integrated import tiny_problem
from ropeway_skip_stop_optimization.optimization.ddd.reference import (
    DddReferenceSolution,
    DddReferenceTrajectoryGenerator,
)
from ropeway_skip_stop_optimization.optimization.ddd.fixed_timetable_capacity import (
    NestedDemand,
    FixedTimetableCapacityProbe,
    find_fixed_timetable_capacity,
)
from ropeway_skip_stop_optimization.optimization.ean.models import EanDemandGroup


def fixture():
    _, p = tiny_problem(
        horizon=65, capacity=2, groups=(EanDemandGroup("ab", "A", "B", 0, 2),)
    )
    trajectories = (
        DddReferenceTrajectoryGenerator()
        .generate(p.resolved_trajectory_problem.structural_movement_problem)
        .by_cabin_id[0]
    )
    t = next(
        t for t in trajectories if all(v.decision.value == "stop" for v in t.visits)
    )
    return p, DddReferenceSolution((t,))


def test_weighted_prefix_is_nested_and_preserves_profile():
    d = NestedDemand(
        (EanDemandGroup("a", "A", "B", 0, 3), EanDemandGroup("b", "B", "C", 10, 1))
    )
    previous = [0, 0]
    for n in range(81):
        groups = d.groups(n)
        counts = [g.count for g in groups]
        assert sum(counts) == n and all(a <= b for a, b in zip(previous, counts))
        assert groups[1].release_time_seconds == 10
        previous = counts
    assert previous == [60, 20]


def test_fixed_capacity_has_adjacent_integer_certificates():
    p, s = fixture()
    d = NestedDemand(p.passenger_build.demand_groups)
    r = find_fixed_timetable_capacity(
        FixedTimetableCapacityProbe(5), p, s, d, initial=1
    )
    assert r["exact"] and r["kappa_lower"] == r["kappa_upper"] == 2
    assert any(v["total_demand"] == 2 and v["capacity_feasible"] for v in r["records"])
    assert any(
        v["total_demand"] == 3 and v["capacity_infeasible_proven"] for v in r["records"]
    )


def test_unknown_probe_does_not_establish_upper_capacity():
    p, s = fixture()
    d = NestedDemand(p.passenger_build.demand_groups)
    r = find_fixed_timetable_capacity(
        FixedTimetableCapacityProbe(1e-9), p, s, d, initial=3
    )
    assert not r["exact"] and r["kappa_upper"] is None
    assert r["records"][0]["solver_status"] == "UNKNOWN"


def test_release_after_departure_cannot_board_fixed_cabin():
    p, s = fixture()
    d = NestedDemand(
        (replace(p.passenger_build.demand_groups[0], release_time_seconds=30),)
    )
    r = FixedTimetableCapacityProbe(5).solve(d.apply(p, 1), s)
    assert r["capacity_infeasible_proven"]


def test_integrated_capacity_matches_fixed_probe_without_cost_products():
    from ropeway_skip_stop_optimization.optimization.ddd.cp_sat_capacity import (
        DddCpSatCapacityOptimizer,
    )
    from ropeway_skip_stop_optimization.optimization.ddd.cp_sat_integrated import (
        DddIntegratedCpSatConfig,
    )

    p, s = fixture()
    p = NestedDemand(p.passenger_build.demand_groups).apply(p, 3)
    result = DddCpSatCapacityOptimizer(
        DddIntegratedCpSatConfig(total_time_limit_seconds=5)
    ).solve(p, fixed_movement=s)
    assert result["unserved_upper_bound"] == result["unserved_lower_bound"] == 1
    assert (
        result["capacity_infeasible_proven"]
        and result["proof_scope"] == "FIXED_MOVEMENT"
    )
    assert result["model_stats"]["cost_auxiliaries"] == 0
    assert (
        result["incumbent"]["objective_tick"] != 1
    )  # separate Journey Time certificate


def test_capacity_seed_survives_timeout_and_does_not_import_journey_bound(tmp_path):
    from ropeway_skip_stop_optimization.optimization.ddd.cp_sat_capacity import (
        DddCpSatCapacityOptimizer,
    )
    from ropeway_skip_stop_optimization.optimization.ddd.cp_sat_integrated import (
        DddIntegratedCpSatConfig,
    )
    from ropeway_skip_stop_optimization.optimization.ddd.cp_sat_certificate import (
        validate_ddd_cp_sat_incumbent,
    )

    p, s = fixture()
    seed = validate_ddd_cp_sat_incumbent(p, s, {}, provenance="test")
    result = DddCpSatCapacityOptimizer(
        DddIntegratedCpSatConfig(
            total_time_limit_seconds=1e-9, checkpoint_path=tmp_path / "seed.json"
        )
    ).solve(p, primal_seed=seed)
    assert result["solver_status"] == "UNKNOWN" and result["unserved_upper_bound"] == 2
    assert (
        result["unserved_lower_bound"] is None
        and not result["capacity_infeasible_proven"]
    )


def test_capacity_global_serves_and_checkpoint_keeps_correct_costs(tmp_path):
    from ropeway_skip_stop_optimization.optimization.ddd.cp_sat_capacity import (
        DddCpSatCapacityOptimizer,
    )
    from ropeway_skip_stop_optimization.optimization.ddd.cp_sat_integrated import (
        DddIntegratedCpSatConfig,
    )
    from ropeway_skip_stop_optimization.optimization.ddd.cp_sat_certificate import (
        read_ddd_cp_sat_checkpoint,
        validate_ddd_cp_sat_domain,
    )

    p, s = fixture()
    path = tmp_path / "seed.json"
    result = DddCpSatCapacityOptimizer(
        DddIntegratedCpSatConfig(total_time_limit_seconds=5, checkpoint_path=path)
    ).solve(p)
    assert result["capacity_feasible"] and result["proven_optimal"]
    assert result["unserved_upper_bound"] == result["unserved_lower_bound"] == 0
    assert result["proof_scope"] == "FIXED_K_GLOBAL"
    seed = read_ddd_cp_sat_checkpoint(
        path, problem=p, manifest=validate_ddd_cp_sat_domain(p)
    )
    assert sum(seed.unserved_counts.values()) == 0


def test_global_capacity_hint_does_not_fix_empty_assignment():
    from ropeway_skip_stop_optimization.optimization.ddd.cp_sat_capacity import (
        DddCpSatCapacityOptimizer,
    )
    from ropeway_skip_stop_optimization.optimization.ddd.cp_sat_integrated import (
        DddIntegratedCpSatConfig,
    )
    from ropeway_skip_stop_optimization.optimization.ddd.cp_sat_certificate import (
        validate_ddd_cp_sat_incumbent,
    )

    p, s = fixture()
    seed = validate_ddd_cp_sat_incumbent(p, s, {}, provenance="empty_assignment")
    result = DddCpSatCapacityOptimizer(
        DddIntegratedCpSatConfig(total_time_limit_seconds=5)
    ).solve(p, primal_seed=seed)
    assert result["capacity_feasible"] and result["served"] == 2
