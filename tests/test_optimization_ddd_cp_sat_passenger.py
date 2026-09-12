from ropeway_skip_stop_optimization.optimization.ddd.cp_formulation import DddCpFormulationConfig, prepare_cp_structure
from dataclasses import replace
from itertools import product

import pytest
from ortools.sat.python import cp_model

from test_optimization_ddd_cp_sat_integrated import tiny_problem, fixed_ip
from ropeway_skip_stop_optimization.optimization.ddd.cp_sat_integrated import DddIntegratedCpSatOptimizer, DddIntegratedCpSatConfig, build_ddd_integrated_cp_sat
from ropeway_skip_stop_optimization.optimization.ddd.cp_sat_passenger import DddCpSatCostEncoding
from ropeway_skip_stop_optimization.optimization.ddd.cp_sat_certificate import validate_ddd_cp_sat_incumbent
from ropeway_skip_stop_optimization.optimization.ddd.cp_sat_movement import build_ddd_cp_sat_movement
from ropeway_skip_stop_optimization.optimization.ddd.reference import DddReferenceTrajectoryGenerator, DddReferenceSolution, validate_ddd_reference_solution, DddReferenceResourceOccurrence
from ropeway_skip_stop_optimization.optimization.ddd.models import DddMovementProblem, DddMovementState, DddFixedStart, DddResource, DddResourceUsage, DddRouteOption, DddRouteDecision
from ropeway_skip_stop_optimization.optimization.ean.models import EanDemandGroup


@pytest.mark.parametrize('encoding',list(DddCpSatCostEncoding))
def test_two_cabins_preserve_platform_overlap_and_bypass_overtaking(encoding):
    scenario,problem=tiny_problem(horizon=80,starts=(0.0,8.0))
    movement=problem.resolved_trajectory_problem.structural_movement_problem
    generated=DddReferenceTrajectoryGenerator().generate(movement)
    optima=[]
    all_stop_checked=overtake_checked=False
    for combo in product(*generated.by_cabin_id.values()):
        solution=DddReferenceSolution(combo)
        try:
            validate_ddd_reference_solution(movement,solution)
        except ValueError:
            continue
        all_stop=all(v.decision is DddRouteDecision.STOP for t in combo for v in t.visits)
        overtake=combo[0].visits[0].decision is DddRouteDecision.STOP and combo[1].visits[0].decision is DddRouteDecision.SKIP
        value,_=fixed_ip(scenario,problem,solution)
        optima.append(value)
        # Both directions: each independent physical trajectory combination
        # remains feasible when its movement is fixed in CP.
        result=DddIntegratedCpSatOptimizer(DddIntegratedCpSatConfig(cost_encoding=encoding)).solve(problem,fixed_movement=solution)
        assert result.proven_optimal
        assert result.validated_upper_bound==pytest.approx(value,abs=1e-6)
        all_stop_checked |= all_stop
        overtake_checked |= overtake
    assert all_stop_checked and overtake_checked
    result=DddIntegratedCpSatOptimizer(DddIntegratedCpSatConfig(cost_encoding=encoding)).solve(problem)
    assert result.validated_upper_bound==pytest.approx(min(optima),abs=1e-6)


@pytest.mark.parametrize('encoding',list(DddCpSatCostEncoding))
@pytest.mark.parametrize('horizon,expected_served',[(56.272727,1),(56.272726,0)])
@pytest.mark.parametrize('profile',['legacy','temporal','strengthened'])
def test_alighting_at_service_cutoff_and_one_tick_after(encoding,horizon,expected_served,profile):
    _,problem=tiny_problem(horizon=horizon,tail=70,groups=(EanDemandGroup('ab','A','B',0,1),))
    # Keep candidates even if canonical horizon pruning proves them impossible:
    # this exercises the CP guard itself, not just the upstream pruning.
    _,larger=tiny_problem(groups=(EanDemandGroup('ab','A','B',0,1),))
    problem=replace(problem,passenger_build=replace(problem.passenger_build,ride_candidates=larger.passenger_build.ride_candidates))
    built=build_ddd_integrated_cp_sat(problem,cost_encoding=encoding,formulation=DddCpFormulationConfig(profile=profile))
    if not built.passengers.ride_count:
        assert not expected_served and profile != "legacy"
        return
    q=next(iter(built.passengers.ride_count))
    built.movement.model.add(built.passengers.ride_count[q]==1)
    solver=cp_model.CpSolver()
    status=solver.solve(built.movement.model)
    assert (status==cp_model.OPTIMAL)==bool(expected_served)
    if not expected_served:
        assert status==cp_model.INFEASIBLE


def _horizon_movement(offset,headway=1.0):
    return DddMovementProblem(scenario_id='horizon_guard',passenger_service_end_seconds=2.0,operational_end_seconds=2.0,
        states=(DddMovementState('A'),),starts=(DddFixedStart(0,'A',0.0,2),),
        resources=(DddResource('r',headway),),route_options=(DddRouteOption(
            id='route',from_state_id='A',to_state_id='A',station_id='A',decision=DddRouteDecision.SKIP,
            duration_seconds=2.0,platform_entry_offset_seconds=None,platform_exit_offset_seconds=None,
            exit_switch_offset_seconds=offset,resource_usages=(DddResourceUsage('r',offset,offset),)),))


@pytest.mark.parametrize('offset,headway,boundary_start,expected',[
    (1.0,1.0,2.0,cp_model.OPTIMAL),  # entry at 3 > H disappears; [1,2) touches [2,4)
    (0.0,1.0,2.0,cp_model.INFEASIBLE), # visit at H still takes its route and resource
    (2.0,1.0,2.5,cp_model.INFEASIBLE), # entry exactly H is protected beyond H
    (1.0,3.0,2.5,cp_model.INFEASIBLE), # clearing beyond H is not clipped
])
@pytest.mark.parametrize('resource_encoding',['legacy','compact_fixed','merged_exit'])
def test_resource_horizon_and_half_open_touch(offset,headway,boundary_start,expected,resource_encoding):
    movement=_horizon_movement(offset,headway)
    occurrence=DddReferenceResourceOccurrence('r',99,0,3.0,boundary_start,1.0)
    built=build_ddd_cp_sat_movement(movement,boundary_occurrences=(occurrence,),resource_encoding=resource_encoding)
    solver=cp_model.CpSolver()
    status=solver.solve(built.model)
    assert status==expected
    if status==cp_model.OPTIMAL:
        assert solver.value(built.active_by_cabin[0][1])==1
        assert solver.value(built.time_by_cabin[0][2])==4_000_000


def test_independent_validator_rejects_fractional_and_overcapacity_assignment():
    _,problem=tiny_problem()
    result=DddIntegratedCpSatOptimizer().solve(problem)
    q=next(iter(result.incumbent.ride_counts))
    for count,match in ((0.5,'integer'),(99,'capacity')):
        with pytest.raises(ValueError,match=match):
            validate_ddd_cp_sat_incumbent(problem,result.incumbent.solution,{q:count},provenance='corrupt')


@pytest.mark.parametrize('encoding',list(DddCpSatCostEncoding))
@pytest.mark.parametrize('profile',['legacy','strengthened'])
def test_passenger_builder_on_existing_odd_cycle_fixture(encoding,profile):
    # The historical fixture is a legacy EAN artifact without network provenance.
    # Exercise the assignment builder on its fixed visits, not the integrated
    # domain adapter, which correctly requires the modern physical network.
    import gurobipy as gp
    from gurobipy import GRB
    from test_optimization_ean_passenger_service import _odd_cycle_fixed_movement_case
    from ropeway_skip_stop_optimization.optimization.ean import EanPassengerCandidateBuilder, EanPassengerObjective
    from ropeway_skip_stop_optimization.optimization.ean.optimizers.fixed_movement_passenger_model import EanFixedMovementPassengerModelBuilder,EanPassengerAssignmentDomain
    from ropeway_skip_stop_optimization.optimization.ddd.models import DddMovementCore
    from ropeway_skip_stop_optimization.optimization.ddd.trajectory_problem import DddTrajectoryProblem,DddFixedTrajectoryStartDomain
    from ropeway_skip_stop_optimization.optimization.ddd.fixed_k import DddFixedKTrajectoryProblem,DddFixedKOperatingMode,DddFixedKStartPolicy
    from ropeway_skip_stop_optimization.optimization.ddd.cp_sat_passenger import build_ddd_cp_sat_passengers
    scenario,artifact,plan=_odd_cycle_fixed_movement_case()
    states=artifact.state_ids
    routes=tuple(DddRouteOption(
        id=f'{state}:{decision.value}',from_state_id=state,to_state_id=states[(i+1)%3],station_id=str(i),
        decision=decision,duration_seconds=1.0,
        platform_entry_offset_seconds=0.2 if decision is DddRouteDecision.STOP else None,
        platform_exit_offset_seconds=0.5 if decision is DddRouteDecision.STOP else None,
        exit_switch_offset_seconds=0.7,resource_usages=(DddResourceUsage(state,0.0,0.0),),
    ) for i,state in enumerate(states) for decision in DddRouteDecision)
    core=DddMovementCore(scenario.id,5.0,5.0,tuple(DddMovementState(s) for s in states),routes,
        tuple(DddResource(s,0.1) for s in states))
    trajectory=DddTrajectoryProblem(core,DddFixedTrajectoryStartDomain(tuple(
        DddFixedStart(s.cabin_id,s.first_switch_id,0.0,6) for s in artifact.cabin_starts)))
    passengers=EanPassengerCandidateBuilder().build(scenario,artifact)
    problem=DddFixedKTrajectoryProblem(trajectory,artifact,passengers,EanPassengerObjective.JOURNEY_TIME,
        DddFixedKOperatingMode.SKIP_STOP,DddFixedKStartPolicy.LEGACY)
    built=build_ddd_cp_sat_movement(trajectory.structural_movement_problem)
    for t in plan.trajectories:
        for v in t.visits:
            for decision in DddRouteDecision:
                built.model.add(built.selection_by_key[t.cabin_id,v.visit_index,f'{v.switch_id}:{decision.value}']==int(v.decision.value==decision.value))
    prepared = prepare_cp_structure(trajectory.structural_movement_problem,passengers,built.states_by_cabin)
    assignment=build_ddd_cp_sat_passengers(problem,built,cost_encoding=encoding,formulation=DddCpFormulationConfig(profile=profile),prepared=prepared)
    solver=cp_model.CpSolver()
    assert solver.solve(built.model)==cp_model.OPTIMAL
    with gp.Model() as model:
        model.Params.OutputFlag=0
        model.Params.Threads=1
        passenger_ip=EanFixedMovementPassengerModelBuilder().build(model=model,scenario=scenario,artifact=artifact,
            movement_plan=plan,passenger_build=passengers,objective=EanPassengerObjective.JOURNEY_TIME,
            assignment_domain=EanPassengerAssignmentDomain.INTEGER,grb=GRB,gp=gp)
        model.optimize()
        assert model.Status==GRB.OPTIMAL
        assert solver.value(assignment.objective_expression)/1_000_000==pytest.approx(model.ObjVal,abs=1e-6)
    assert all(type(solver.value(y)) is int for y in assignment.ride_count.values())
