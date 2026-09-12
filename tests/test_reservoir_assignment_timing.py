from dataclasses import replace

import pytest
from ortools.sat.python import cp_model

from test_optimization_ddd_reservoir_cp_sat import problem, trip
from ropeway_skip_stop_optimization.optimization.ddd.reservoir_assignment import (
    ReservoirAssignmentMasterConfig,
    ReservoirAssignmentConflict,
    ReservoirAssignmentPipelineConfig,
    ReservoirAssignmentTimingConfig,
    ReservoirConflictConfig,
    ReservoirPassengerFixing,
    ReservoirServiceAssignment,
    ReservoirServiceTrip,
    ReservoirTimingAssumption,
    assignment_from_payload,
    assignment_from_plan,
    assignment_to_payload,
    assignment_violates_conflict,
    canonicalize_reservoir_plan,
    build_assignment_timing_model,
    extract_assignment_conflict,
    replay_assignment_conflict,
    solve_assignment_master,
    solve_assignment_pipeline,
    solve_assignment_timing,
    validate_service_assignment,
)
from ropeway_skip_stop_optimization.optimization.ddd.reservoir_cp_sat_certificate import (
    DddReservoirCpPlan,
    validate_reservoir_cp_plan,
)
from ropeway_skip_stop_optimization.optimization.ean.models import EanDemandGroup

T = 1_000_000


def _ride(p, cabin):
    return next(
        q
        for q in p.passenger_build.ride_candidates
        if q.cabin_id == cabin
        and q.demand_group_id == "g"
        and q.board_visit_index == 0
        and q.alight_visit_index == 1
    )


def _service_trip(k, dispatch=0):
    t = trip(k=k, dispatch=dispatch)
    return ReservoirServiceTrip(
        t.cabin_id,
        t.route_option_ids,
        t.switch_ticks,
        t.wait_ticks,
        t.return_tick,
    )


def test_master_and_exact_timing_find_small_complete_plan():
    p = problem()
    master, assignment = solve_assignment_master(
        p,
        ReservoirAssignmentMasterConfig(
            target_served=1, time_limit_seconds=5, threads=1
        ),
    )
    assert master["status_name"] == "OPTIMAL"
    assert master["validation"]["served"] == 1
    timing, plan = solve_assignment_timing(
        p,
        assignment,
        ReservoirAssignmentTimingConfig(time_limit_seconds=5, workers=1),
    )
    assert timing["status"] == "OPTIMAL"
    assert timing["has_valid_plan"]
    assert validate_reservoir_cp_plan(p, plan).served == 1
    free, free_plan = solve_assignment_timing(
        p,
        assignment,
        ReservoirAssignmentTimingConfig(
            time_limit_seconds=5,
            workers=1,
            use_witness_hints=False,
            fix_routes=False,
        ),
    )
    assert free["status"] == "OPTIMAL" and free["fixed_routes"] is False
    assert validate_reservoir_cp_plan(p, free_plan).served == 1


def test_timing_can_fix_witness_waits_and_resource_order():
    p = problem(
        available_fleet_count=2,
        dispatch_end_seconds=10,
        demand_groups=(EanDemandGroup("g", "A", "B", 0, 2),),
    )
    _, assignment = solve_assignment_master(
        p,
        ReservoirAssignmentMasterConfig(
            target_served=2, time_limit_seconds=5, threads=1
        ),
    )
    result, plan = solve_assignment_timing(
        p,
        assignment,
        ReservoirAssignmentTimingConfig(
            time_limit_seconds=5,
            workers=1,
            use_witness_hints=False,
            fix_witness_waits=True,
            fix_witness_resource_order=True,
        ),
    )
    assert result["status"] == "OPTIMAL"
    assert result["fixed_witness_waits"]
    assert result["fixed_witness_resource_order"]
    assert result["fixed_resource_precedences"] > 0
    assert validate_reservoir_cp_plan(p, plan).served == 2


def test_passenger_fixing_modes_release_exact_ride_counts():
    p = problem(
        cabin_capacity=2,
        demand_groups=(EanDemandGroup("g", "A", "B", 0, 2),),
    )
    ride = _ride(p, 0)
    seed = DddReservoirCpPlan((trip(),), {ride.id: 1})
    assignment = assignment_from_plan(p, seed)

    def status(mode):
        built = build_assignment_timing_model(
            p,
            assignment,
            ReservoirAssignmentTimingConfig(
                time_limit_seconds=5,
                workers=1,
                use_witness_hints=False,
                passenger_fixing=mode,
            ),
        )
        built.built.movement.model.add(built.built.passengers.ride_count[ride.id] == 2)
        return cp_model.CpSolver().solve(built.built.movement.model)

    assert status(ReservoirPassengerFixing.EXACT) == cp_model.INFEASIBLE
    assert status(ReservoirPassengerFixing.COMMITMENTS) in (
        cp_model.FEASIBLE,
        cp_model.OPTIMAL,
    )
    assert status(ReservoirPassengerFixing.REASSIGN) in (
        cp_model.FEASIBLE,
        cp_model.OPTIMAL,
    )


def test_infeasible_assignment_core_replays_under_same_background():
    p = problem(
        available_fleet_count=2,
        dispatch_end_seconds=0,
        demand_groups=(EanDemandGroup("g", "A", "B", 0, 1),),
    )
    assignment = ReservoirServiceAssignment(
        p.fingerprint,
        0,
        (_service_trip(0), _service_trip(1)),
        {},
        "conflict_test",
    )
    timing = ReservoirAssignmentTimingConfig(
        time_limit_seconds=5, workers=1, use_witness_hints=False
    )
    result, conflict = extract_assignment_conflict(
        p,
        assignment,
        timing,
        ReservoirConflictConfig(
            time_limit_seconds=5,
            deletion_limit_seconds=5,
            replay_limit_seconds=5,
            deletion_slice_seconds=1,
        ),
    )
    assert result["proved_infeasible"] and conflict is not None
    assert result["core_size"] > 0
    replay = replay_assignment_conflict(p, assignment, timing, conflict, seconds=5)
    assert replay["proved_infeasible"]


def test_master_no_good_changes_the_named_integer_ride_decision():
    p = problem()
    _, original = solve_assignment_master(
        p,
        ReservoirAssignmentMasterConfig(
            target_served=1, time_limit_seconds=5, threads=1
        ),
    )
    rid, count = next(iter(original.ride_counts.items()))
    conflict = ReservoirAssignmentConflict(
        p.fingerprint,
        "exact",
        True,
        False,
        (ReservoirTimingAssumption("ride", "ride_eq", rid, count, 0),),
    )
    assert assignment_violates_conflict(p, original, conflict)
    result, replacement = solve_assignment_master(
        p,
        ReservoirAssignmentMasterConfig(
            target_served=1,
            time_limit_seconds=5,
            threads=1,
            conflict_cuts=(conflict,),
        ),
    )
    assert result["conflict_cut_count"] == 1
    if replacement is not None:
        assert not assignment_violates_conflict(p, replacement, conflict)


def test_resource_order_diagnostic_requires_fixed_routes():
    with pytest.raises(ValueError, match="requires fixed routes"):
        ReservoirAssignmentTimingConfig(
            fix_routes=False, fix_witness_resource_order=True
        ).validate()


def test_pipeline_improves_an_empty_reference_without_fallback():
    p = problem()
    result, assignment, plan = solve_assignment_pipeline(
        p,
        DddReservoirCpPlan((), {}),
        ReservoirAssignmentPipelineConfig(
            additional_served=1,
            master_seconds=5,
            timing_seconds=5,
            threads=1,
        ),
    )
    assert assignment is not None and plan is not None
    assert result["target_served"] == 1
    assert result["improvement_over_reference"] == 1


def test_assignment_serialization_and_unknown_positive_ride_are_strict():
    p = problem()
    q = _ride(p, 0)
    a = ReservoirServiceAssignment(
        p.fingerprint, 1, (_service_trip(0),), {q.id: 1}, "test"
    )
    assert assignment_from_payload(assignment_to_payload(a)) == a
    bad = replace(a, ride_counts={"missing": 1})
    with pytest.raises(ValueError, match="invalid service assignment ride"):
        validate_service_assignment(p, bad)


def test_individually_valid_assignment_can_be_globally_infeasible():
    base = problem()
    p = problem(
        available_fleet_count=2,
        dispatch_end_seconds=0,
        movement_core=replace(
            base.movement_core,
            passenger_service_end_seconds=3,
            operational_end_seconds=4,
        ),
        demand_groups=(EanDemandGroup("g", "A", "B", 0, 2),),
    )
    rides = {_ride(p, k).id: 1 for k in range(2)}
    assignment = ReservoirServiceAssignment(
        p.fingerprint,
        2,
        (_service_trip(0), _service_trip(1)),
        rides,
        "conflicting",
    )
    assert validate_service_assignment(p, assignment)["served"] == 2
    with pytest.raises(ValueError, match="state-time|headway|resource"):
        validate_reservoir_cp_plan(
            p,
            DddReservoirCpPlan((trip(0), trip(1)), rides),
        )
    timing, plan = solve_assignment_timing(
        p,
        assignment,
        ReservoirAssignmentTimingConfig(time_limit_seconds=5, workers=1),
    )
    assert timing["proved_infeasible"] and plan is None


def test_dispatch_relabeling_translates_canonical_ride_ids():
    p = problem(
        available_fleet_count=2,
        dispatch_end_seconds=10,
        demand_groups=(EanDemandGroup("g", "A", "B", 0, 2),),
    )
    rides = {_ride(p, k).id: 1 for k in range(2)}
    original = DddReservoirCpPlan((trip(0, 5), trip(1, 0)), rides)
    validate_reservoir_cp_plan(p, original)
    canonical, mapping = canonicalize_reservoir_plan(p, original)
    assert mapping == {1: 0, 0: 1}
    assert [t.cabin_id for t in canonical.trips] == [0, 1]
    assert [t.switch_ticks[0] for t in canonical.trips] == [0, 5 * T]
    assert validate_reservoir_cp_plan(p, canonical).served == 2
