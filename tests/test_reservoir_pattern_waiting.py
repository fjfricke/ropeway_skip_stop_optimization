from dataclasses import replace
from itertools import product
from types import SimpleNamespace

import pytest
from ortools.sat.python import cp_model

from test_reservoir_line_evolution import _prepared
from ropeway_skip_stop_optimization.optimization.ddd.reservoir_lines.evolution.pattern_waiting import (
    with_pattern_waiting, build_pattern_waiting, solve_pattern_waiting,
)
from ropeway_skip_stop_optimization.optimization.ddd.reservoir_cp_sat import _extract
from ropeway_skip_stop_optimization.optimization.ddd.reservoir_cp_sat_certificate import (
    DddReservoirCpPlan, DddReservoirCpTrip, validate_reservoir_cp_plan,
)
from ropeway_skip_stop_optimization.optimization.ddd.reservoir_lines.evolution.passengers import optimize_waiting_timetable_passengers

T = 1_000_000


def solve(built):
    s = cp_model.CpSolver()
    s.parameters.num_search_workers = 1
    s.parameters.max_time_in_seconds = 3
    return s, s.solve(built.movement.model)


def test_waiting_changes_number_of_laps_and_dispatch_is_free():
    p,_ = _prepared(fleet=1)
    p = with_pattern_waiting(p,60,earliest_seconds=0)
    b = build_pattern_waiting(p,('all_stop',),dispatch_end_tick=3*T)
    b.movement.model.add(b.movement.time_by_cabin[0][0] == 2*T)
    b.movement.model.add(b.movement.wait_steps_by_key[0,0] == 9*T)
    s,status = solve(b)
    assert status == cp_model.OPTIMAL
    plan = _extract(p,b,s.value)
    assert len(plan.trips[0].route_option_ids) == 2  # old No-Wait needs four laps
    assert plan.trips[0].return_tick == 15*T
    validate_reservoir_cp_plan(p,plan)


@pytest.mark.parametrize('offset,feasible',[(0,True),(1,False)])
def test_cannot_continue_at_or_after_service_deadline(offset,feasible):
    p,_ = _prepared(fleet=1)
    p = with_pattern_waiting(p,60,earliest_seconds=0)
    b=build_pattern_waiting(p,('all_stop',),dispatch_end_tick=3*T)
    b.movement.model.add(b.movement.active_by_cabin[0][2] == 1)
    b.movement.model.add(b.movement.time_by_cabin[0][2] == 15*T-1+offset)
    _,status=solve(b)
    assert (status == cp_model.OPTIMAL) == feasible


@pytest.mark.parametrize('wait,expected',[(60*T,cp_model.OPTIMAL),(60*T+1,cp_model.INFEASIBLE)])
def test_exact_sixty_second_cap(wait,expected):
    p,_=_prepared(fleet=1)
    p=replace(p,movement_core=replace(p.movement_core,
              passenger_service_end_seconds=65,operational_end_seconds=75))
    p=with_pattern_waiting(p,60,earliest_seconds=0)
    b=build_pattern_waiting(p,('all_stop',),dispatch_end_tick=3*T)
    b.movement.model.add(b.movement.wait_steps_by_key[0,0] == wait)
    _,status=solve(b)
    assert status==expected


def test_warmup_waiting_release_is_not_ignored():
    p,_=_prepared(fleet=1)
    p=with_pattern_waiting(p,60,earliest_seconds=5)
    b=build_pattern_waiting(p,('all_stop',),dispatch_end_tick=3*T)
    b.movement.model.add(b.movement.time_by_cabin[0][0] == 0)
    b.movement.model.add(b.movement.wait_steps_by_key[0,0] == 1)
    _,status=solve(b)
    assert status==cp_model.INFEASIBLE


def test_fixed_fleet_cannot_drop_cabin_and_dispatch_order_is_enforced():
    p,_=_prepared(fleet=2)
    p=with_pattern_waiting(p,60,earliest_seconds=0)
    for drop in (True,False):
        b=build_pattern_waiting(p,('all_stop','all_stop'),dispatch_end_tick=3*T)
        if drop:
            b.movement.model.add(b.movement.active_by_cabin[1][0] == 0)
        else:
            b.movement.model.add(b.movement.time_by_cabin[1][0] < b.movement.time_by_cabin[0][0])
        _,status=solve(b)
        assert status==cp_model.INFEASIBLE


def test_small_joint_optimum_and_timings_match_independent_enumeration():
    p,_=_prepared(fleet=1,dispatch_end=1)
    p=replace(p,movement_core=replace(p.movement_core,passenger_service_end_seconds=5,
                    operational_end_seconds=9),
              demand_groups=tuple(replace(g,release_time_seconds=0) for g in p.demand_groups))
    p=with_pattern_waiting(p,1,earliest_seconds=0)
    p=replace(p,waiting_policy=replace(p.waiting_policy,step_seconds=1))
    best=0;valid=0
    for dispatch,n in product(range(2),(2,4)):
        for waits in product(range(2),repeat=n):
            times=[];t=dispatch*T
            for w in waits:
                times.append(t);t+=(2+w)*T
            plan=DddReservoirCpPlan((DddReservoirCpTrip(0,('A_stop','B_stop')*(n//2),
                  tuple(times),tuple(w*T for w in waits),t),),{})
            allowed=t>=5*T and (n==2 or times[n-2]<5*T)
            try:validate_reservoir_cp_plan(p,plan)
            except ValueError:allowed=False
            b=build_pattern_waiting(p,('all_stop',),dispatch_end_tick=T)
            for i,a in enumerate(b.movement.active_by_cabin[0]):
                b.movement.model.add(a == int(i<n))
            b.movement.model.add(b.movement.time_by_cabin[0][0] == dispatch*T)
            for i,w in enumerate(waits):b.movement.model.add(b.movement.wait_steps_by_key[0,i] == w)
            _,status=solve(b)
            assert (status==cp_model.OPTIMAL)==allowed
            if allowed:
                valid+=1
                best=max(best,optimize_waiting_timetable_passengers(p,plan).served)
    assert valid>0
    r=solve_pattern_waiting(p,('all_stop',),dispatch_end_tick=T,joint=True,seconds=3,workers=1)
    assert r['solver_status']=='OPTIMAL' and r['passengers'].served==best>0


def test_expired_budget_never_claims_infeasibility():
    p,_=_prepared(fleet=1)
    p=with_pattern_waiting(p,60,earliest_seconds=0)
    r=solve_pattern_waiting(p,('all_stop',),dispatch_end_tick=3*T,deadline=0)
    assert r['solver_status']=='BUILD_TIMEOUT' and r['plan'] is None
