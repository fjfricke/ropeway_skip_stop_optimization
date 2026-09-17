from dataclasses import replace

import pytest
from ortools.sat.python import cp_model

from test_reservoir_line_evolution import _prepared
from ropeway_skip_stop_optimization.optimization.ddd.reservoir_lines import (
    ReservoirLineConfig, ReservoirLineVariant, ReservoirLinePreparation,
    ReservoirLineFormulation, ReservoirLineMode, ReservoirLineCatalogProfile, prepare_line_problem,
)
from ropeway_skip_stop_optimization.optimization.ddd.reservoir_lines.evolution import GenomeFactory, decode_no_wait
from ropeway_skip_stop_optimization.optimization.ddd.reservoir_lines.evolution.waiting_repair import (
    build_waiting_only_repair, solve_waiting_only_repair,
)
from ropeway_skip_stop_optimization.optimization.ddd.reservoir_lines.evolution.passengers import (
    optimize_waiting_timetable_passengers, optimize_fixed_movement_passengers,
)
from ropeway_skip_stop_optimization.optimization.ddd.reservoir_cp_sat_certificate import (
    DddReservoirCpPlan, DddReservoirCpTrip, validate_reservoir_cp_plan,
)
from ropeway_skip_stop_optimization.optimization.ddd.trajectory_column_generation import DddTrajectoryWaitingDomain
from ropeway_skip_stop_optimization.optimization.ddd.trajectory_problem import DddTrajectoryWaitingPolicy


def fixture(*, early_conflict=False, earliest_wait=0, wait_cap=2):
    p,_ = _prepared(fleet=2)
    core=replace(p.movement_core, resources=tuple(
        replace(r, headway_seconds=1.5 if early_conflict else 1.0, maximum_headway_seconds=1.5 if early_conflict else 1.0)
        if r.id=='rope_A' else replace(r, headway_seconds=2.0, maximum_headway_seconds=2.0)
        for r in p.movement_core.resources))
    p=replace(p, movement_core=core, waiting_policy=DddTrajectoryWaitingPolicy(
        domain=DddTrajectoryWaitingDomain.BOUNDED_WAIT, step_seconds=0.000001,
        maximum_wait_seconds_by_station_id=(('A',wait_cap),('B',wait_cap)),
        earliest_wait_time_seconds=earliest_wait))
    if wait_cap == 0:
        p=replace(p, waiting_policy=DddTrajectoryWaitingPolicy())
    c=ReservoirLineConfig(dispatch_window_end_seconds=3, maximum_cabins=2,
        variant=ReservoirLineVariant.INTERVALS,preparation=ReservoirLinePreparation.ENCODING_SPECIFIC,
        formulation=ReservoirLineFormulation.SHARED_ROUNDS,mode=ReservoirLineMode.EXACT_SERVICE,
        catalog_profile=ReservoirLineCatalogProfile.RELEVANT)
    prep=prepare_line_problem(p,c);f=GenomeFactory(p,prep)
    m=decode_no_wait(p,prep,f.from_dispatches(('all_stop','all_stop'),(0,1_000_000)))
    assert m.conflicts and m.relaxed_timetable is not None
    return p,m.relaxed_timetable


def test_waiting_can_repair_without_changing_any_dispatch_or_route():
    p,candidate=fixture()
    saved=[]
    r=solve_waiting_only_repair(p,candidate,dispatch_end_tick=3_000_000,
        time_limit_seconds=3,workers=1,checkpoint_callback=saved.append)
    assert r['status']=='REPAIRED'
    assert r['total_wait_tick']>0 and r['positive_wait_visits']>0
    assert r['metrics']['served']>0
    assert r['global_bound'] is None and not r['capacity_optimal']
    assert saved
    for a,b in zip(candidate.trips,r['plan'].trips,strict=True):
        assert a.cabin_id==b.cabin_id and a.switch_ticks[0]==b.switch_ticks[0]
        assert a.route_option_ids==b.route_option_ids
    validate_reservoir_cp_plan(p,r['plan'])


def test_conflict_at_fixed_dispatch_cannot_be_healed_by_later_waiting():
    p,candidate=fixture(early_conflict=True)
    r=solve_waiting_only_repair(p,candidate,dispatch_end_tick=3_000_000,time_limit_seconds=2,workers=1)
    assert r['status']=='INFEASIBLE_FIXED_CANDIDATE' and r['plan'] is None


def test_waiting_before_release_is_not_silently_allowed():
    p,candidate=fixture(earliest_wait=5)
    r=solve_waiting_only_repair(p,candidate,dispatch_end_tick=3_000_000,time_limit_seconds=2,workers=1)
    assert r['status']=='INFEASIBLE_FIXED_CANDIDATE'


def test_dispatch_equality_is_in_the_native_model():
    p,candidate=fixture();b=build_waiting_only_repair(p,candidate,dispatch_end_tick=3_000_000)
    b.model.add(b.time_by_cabin[1][0] != candidate.trips[1].switch_ticks[0])
    s=cp_model.CpSolver();s.parameters.num_search_workers=1
    assert s.solve(b.model)==cp_model.INFEASIBLE


def test_fixed_activity_prevents_dropping_a_cabin():
    p,candidate=fixture();b=build_waiting_only_repair(p,candidate,dispatch_end_tick=3_000_000)
    b.model.add(b.active_by_cabin[1][0] == 0)
    s=cp_model.CpSolver();s.parameters.num_search_workers=1
    assert s.solve(b.model)==cp_model.INFEASIBLE


def test_no_waiting_cap_makes_original_collisions_infeasible():
    p,candidate=fixture(wait_cap=0)
    r=solve_waiting_only_repair(p,candidate,dispatch_end_tick=3_000_000,time_limit_seconds=2,workers=1)
    assert r['status']=='INFEASIBLE_FIXED_CANDIDATE'


def test_waiting_passenger_assignment_counts_origin_wait_but_not_destination_wait():
    p,_=fixture()
    # A departure: 0 + 0.5 + 1 = 1.5; B arrival: 3 (before its 1s wait).
    p=replace(p, available_fleet_count=1,
        demand_groups=tuple(replace(g, release_time_seconds=1.5) for g in p.demand_groups))
    t=DddReservoirCpTrip(0,('A_stop','B_stop'),(0,3_000_000),(1_000_000,1_000_000),6_000_000)
    plan=DddReservoirCpPlan((t,),{})
    v=optimize_waiting_timetable_passengers(p,plan)
    assert v.served==1 and v.proven_optimal
    assert validate_reservoir_cp_plan(p,v.plan).journey_time_tick==1_500_000
    with pytest.raises(ValueError,match='no-wait'):
        optimize_fixed_movement_passengers(p,plan)
    late=replace(p,demand_groups=tuple(replace(g,release_time_seconds=1.500001) for g in p.demand_groups))
    assert optimize_waiting_timetable_passengers(late,plan).served==0


def test_build_timeout_is_not_an_infeasibility_proof():
    p,candidate=fixture()
    r=solve_waiting_only_repair(p,candidate,dispatch_end_tick=3_000_000,time_limit_seconds=1e-12,workers=1)
    assert r['status']=='BUILD_TIMEOUT' and r['plan'] is None


def test_waiting_release_override_changes_only_that_field_and_identity():
    import importlib.util
    from pathlib import Path
    spec=importlib.util.spec_from_file_location('waiting_probe_test',
        Path(__file__).resolve().parents[1]/'benchmarks/run_reservoir_line_waiting_probe.py')
    module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
    before,candidate=fixture(earliest_wait=5)
    after=module.with_waiting_release(before,0)
    assert after.waiting_policy.earliest_wait_time_seconds==0
    assert before.waiting_policy.earliest_wait_time_seconds==5
    assert replace(after,waiting_policy=before.waiting_policy)==before
    assert after.fingerprint!=before.fingerprint
    assert module.with_waiting_release(before,None) is before
    old=solve_waiting_only_repair(before,candidate,dispatch_end_tick=3_000_000,time_limit_seconds=2,workers=1)
    new=solve_waiting_only_repair(after,candidate,dispatch_end_tick=3_000_000,time_limit_seconds=2,workers=1)
    assert old['status']=='INFEASIBLE_FIXED_CANDIDATE'
    assert new['status']=='REPAIRED'
    assert [t.switch_ticks[0] for t in new['plan'].trips]==[t.switch_ticks[0] for t in candidate.trips]
    for bad in (-1,float('nan'),float('inf')):
        with pytest.raises(ValueError,match='finite and nonnegative'):
            module.with_waiting_release(before,bad)
