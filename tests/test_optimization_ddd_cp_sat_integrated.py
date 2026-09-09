from dataclasses import replace
from itertools import product
import json

import gurobipy as gp
from gurobipy import GRB
import pytest

from ropeway_skip_stop_optimization.examples.registry import get_example
from ropeway_skip_stop_optimization.optimization.ean import (
    EanPassengerObjective, SparseHeadwayPairBuilder, EanPassengerCandidateBuilder,
)
from ropeway_skip_stop_optimization.optimization.ean.models import EanCabinStart, EanCabinStartKind, EanDemandGroup, StationWaitingMode
from ropeway_skip_stop_optimization.optimization.ean.builders.fixed_start_builder import ExplicitEanCabinStartBuilder
from ropeway_skip_stop_optimization.optimization.ean.builders.passenger_builder import EanPassengerCandidateBuildResult, build_ean_ride_candidates
from ropeway_skip_stop_optimization.optimization.ean.optimizers.fixed_movement_passenger_model import EanFixedMovementPassengerModelBuilder, EanPassengerAssignmentDomain
from ropeway_skip_stop_optimization.optimization.ddd.artifact_adapter import EanArtifactToDddMovementProblemAdapter
from ropeway_skip_stop_optimization.optimization.ddd.fixed_k import DddFixedKTrajectoryProblem, DddFixedKOperatingMode, DddFixedKStartPolicy, DddFixedKBoundaryContext
from ropeway_skip_stop_optimization.optimization.ddd.cp_sat_integrated import DddIntegratedCpSatOptimizer, DddIntegratedCpSatConfig, build_ddd_integrated_cp_sat
from ropeway_skip_stop_optimization.optimization.ddd.cp_sat_passenger import DddCpSatCostEncoding
from ropeway_skip_stop_optimization.optimization.ddd.cp_sat_certificate import (
    validate_ddd_cp_sat_domain, stable_fingerprint, validate_ddd_cp_sat_incumbent,
    write_ddd_cp_sat_checkpoint, read_ddd_cp_sat_checkpoint,
)
from ropeway_skip_stop_optimization.optimization.ddd.reference import (
    DddReferenceTrajectoryGenerator, DddReferenceSolution, validate_ddd_reference_solution,
    DddReferenceResourceOccurrence,
)
from ropeway_skip_stop_optimization.optimization.ddd.ean_plan_adapter import DddReferenceToEanMovementPlanAdapter
from ropeway_skip_stop_optimization.optimization.ddd.arc_flow import DddFixedKArcFlowOptimizer, DddFixedKArcFlowSolveConfig
from ropeway_skip_stop_optimization.optimization.ddd.trajectory_problem import DddTrajectoryWaitingPolicy
from ropeway_skip_stop_optimization.optimization.ddd.trajectory_column_generation import DddTrajectoryWaitingDomain


def tiny_problem(*, horizon=130.0, tail=0.0, capacity=2, starts=(0.0,), groups=None, maximum_wait=0.0, waiting_step=1.0):
    example = get_example('five_station_circle_cw_half_skip_no_wait_headway_b_v0')
    scenario = example.build_scenario()
    config = replace(example.build_ean_config(scenario), horizon_seconds=horizon, tail_seconds=tail, cabin_capacity=capacity)
    if maximum_wait:
        config = replace(config, station_configs=tuple(replace(s,
            waiting_mode=StationWaitingMode.END_OF_PLATFORM_WAIT, max_wait_seconds=maximum_wait, fifo_capacity=None)
            for s in config.station_configs))
    builder = replace(example.build_ean_artifact_builder(scenario, config),
        start_builder=ExplicitEanCabinStartBuilder(tuple(EanCabinStart(i, 'A_entry_cw', EanCabinStartKind.FIXED, t) for i,t in enumerate(starts))),
        headway_pair_builder=SparseHeadwayPairBuilder())
    artifact = builder.build(scenario, config)
    groups = groups if groups is not None else (
        EanDemandGroup('ab', 'A', 'B', 0.0, 3),
        EanDemandGroup('ac', 'A', 'C', 0.0, 2),
        EanDemandGroup('bc', 'B', 'C', 0.0, 2),
    )
    passengers = EanPassengerCandidateBuildResult(groups, build_ean_ride_candidates(groups, artifact))
    problem = DddFixedKTrajectoryProblem(
        EanArtifactToDddMovementProblemAdapter(waiting_step_seconds=waiting_step).build_trajectory_problem(artifact), artifact, passengers,
        EanPassengerObjective.JOURNEY_TIME, DddFixedKOperatingMode.SKIP_STOP, DddFixedKStartPolicy.LEGACY)
    return scenario, problem


def fixed_ip(scenario, problem, solution):
    movement = problem.resolved_trajectory_problem.structural_movement_problem
    plan = DddReferenceToEanMovementPlanAdapter(waiting_policy=problem.resolved_trajectory_problem.waiting_policy).build(problem=movement, solution=solution, artifact=problem.artifact)
    with gp.Model() as model:
        model.Params.OutputFlag=0
        model.Params.Threads=1
        passenger = EanFixedMovementPassengerModelBuilder().build(model=model, scenario=scenario,
            artifact=problem.artifact, movement_plan=plan, passenger_build=problem.passenger_build,
            objective=problem.objective, assignment_domain=EanPassengerAssignmentDomain.INTEGER, grb=GRB, gp=gp)
        model.optimize()
        assert model.Status == GRB.OPTIMAL
        return model.ObjVal, passenger.extract_assignment()


@pytest.mark.parametrize('encoding', list(DddCpSatCostEncoding))
def test_global_optimum_matches_exhaustive_movements_and_arc_flow(encoding):
    scenario, problem = tiny_problem()
    movement = problem.resolved_trajectory_problem.structural_movement_problem
    generated = DddReferenceTrajectoryGenerator().generate(movement)
    values=[]
    for combination in product(*generated.by_cabin_id.values()):
        solution=DddReferenceSolution(combination)
        try:
            validate_ddd_reference_solution(movement, solution)
        except ValueError:
            continue
        values.append(fixed_ip(scenario, problem, solution)[0])
    result = DddIntegratedCpSatOptimizer(DddIntegratedCpSatConfig(cost_encoding=encoding, total_time_limit_seconds=10)).solve(problem)
    assert result.proven_optimal
    assert result.validated_upper_bound == pytest.approx(min(values), abs=1e-6)
    assert result.cp_lower_bound == result.validated_upper_bound
    assert result.incumbent.ride_counts
    arc = DddFixedKArcFlowOptimizer(DddFixedKArcFlowSolveConfig(time_limit_seconds=10, threads=1)).solve(problem)
    assert result.validated_upper_bound == pytest.approx(arc.validated_upper_bound, abs=1e-6)


@pytest.mark.parametrize('encoding', list(DddCpSatCostEncoding))
def test_fixed_assignment_release_capacity_and_tail_match_integer_ip(encoding):
    groups=(EanDemandGroup('early','A','B',0,2), EanDemandGroup('at_board','A','B',22.090909,1),
            EanDemandGroup('late','A','B',22.090910,1), EanDemandGroup('bc','B','C',0,2),
            EanDemandGroup('after_service','A','B',131,1))
    scenario, problem=tiny_problem(tail=60,groups=groups)
    movement=problem.resolved_trajectory_problem.structural_movement_problem
    trajectories=DddReferenceTrajectoryGenerator().generate(movement).by_cabin_id[0]
    all_stop=next(t for t in trajectories if all(v.decision.value=='stop' for v in t.visits))
    solution=DddReferenceSolution((all_stop,))
    expected,_=fixed_ip(scenario,problem,solution)
    result=DddIntegratedCpSatOptimizer(DddIntegratedCpSatConfig(cost_encoding=encoding)).solve(problem,fixed_movement=solution)
    assert result.proven_optimal
    assert result.proof_scope=='FIXED_MOVEMENT'
    assert result.validated_upper_bound==pytest.approx(expected,abs=1e-6)
    assert result.incumbent.unserved_counts['late']==1
    assert result.incumbent.unserved_counts['after_service']==1
    assert sum(result.incumbent.ride_counts.values())==4  # seats reused at B


def test_manifest_detects_changes_omitted_from_historical_fingerprint():
    _,problem=tiny_problem()
    manifest=validate_ddd_cp_sat_domain(problem)
    other=replace(problem,artifact=replace(problem.artifact,config=replace(problem.artifact.config,cabin_capacity=3)))
    assert other.legacy_fingerprint==problem.legacy_fingerprint
    assert other.fingerprint!=problem.fingerprint
    assert stable_fingerprint(validate_ddd_cp_sat_domain(other))!=stable_fingerprint(manifest)
    other=replace(problem,passenger_build=replace(problem.passenger_build,ride_candidates=problem.passenger_build.ride_candidates[:-1]))
    assert other.legacy_fingerprint==problem.legacy_fingerprint
    assert other.fingerprint!=problem.fingerprint
    assert stable_fingerprint(validate_ddd_cp_sat_domain(other))!=stable_fingerprint(manifest)


def test_checkpoint_round_trip_rejects_wrong_capacity_and_tampered_counts(tmp_path):
    _,problem=tiny_problem()
    result=DddIntegratedCpSatOptimizer().solve(problem)
    path=tmp_path/'checkpoint.json'
    write_ddd_cp_sat_checkpoint(path,problem=problem,manifest=result.domain_manifest,incumbent=result.incumbent)
    loaded=read_ddd_cp_sat_checkpoint(path,problem=problem,manifest=result.domain_manifest)
    assert loaded.objective_tick==result.incumbent.objective_tick
    other=replace(problem,artifact=replace(problem.artifact,config=replace(problem.artifact.config,cabin_capacity=3)))
    with pytest.raises(ValueError,match='fingerprint'):
        read_ddd_cp_sat_checkpoint(path,problem=other,manifest=validate_ddd_cp_sat_domain(other))
    payload=json.loads(path.read_text())
    key=next(iter(payload['incumbent']['ride_counts']))
    payload['incumbent']['ride_counts'][key]=99
    path.write_text(json.dumps(payload))
    with pytest.raises(ValueError,match='capacity|demand'):
        read_ddd_cp_sat_checkpoint(path,problem=problem,manifest=result.domain_manifest)


def test_seed_survives_build_timeout_and_is_not_a_cp_solution():
    _,problem=tiny_problem()
    initial=DddIntegratedCpSatOptimizer().solve(problem)
    result=DddIntegratedCpSatOptimizer(DddIntegratedCpSatConfig(total_time_limit_seconds=1e-9)).solve(problem,primal_seed=initial.incumbent)
    assert result.solver_status=='UNKNOWN'
    assert result.incumbent is not None
    assert result.cp_objective_tick is None
    assert result.cp_lower_bound is None
    assert not result.proven_optimal


@pytest.mark.parametrize('encoding',list(DddCpSatCostEncoding))
def test_hints_do_not_fix_routes_or_assignment(encoding):
    _,problem=tiny_problem()
    movement=problem.resolved_trajectory_problem.structural_movement_problem
    trajectory=DddReferenceTrajectoryGenerator().generate(movement).by_cabin_id[0][0]
    seed=validate_ddd_cp_sat_incumbent(problem,DddReferenceSolution((trajectory,)),{},provenance='deliberately unserved seed')
    result=DddIntegratedCpSatOptimizer(DddIntegratedCpSatConfig(cost_encoding=encoding)).solve(problem,primal_seed=seed)
    assert result.proven_optimal
    assert result.incumbent.objective_tick < seed.objective_tick


def test_waiting_and_other_objectives_are_rejected():
    _,problem=tiny_problem()
    with pytest.raises(ValueError,match='Journey Time'):
        build_ddd_integrated_cp_sat(replace(problem,objective=EanPassengerObjective.WAITING_TIME))
    policy=DddTrajectoryWaitingPolicy(DddTrajectoryWaitingDomain.BOUNDED_WAIT,1.0,(('A',1.0),))
    with pytest.raises(ValueError,match='No-Wait'):
        build_ddd_integrated_cp_sat(replace(problem,trajectory_problem=replace(problem.trajectory_problem,waiting_policy=policy)))


@pytest.mark.parametrize('groups',[(),(EanDemandGroup('late','A','B',200,1),)])
def test_empty_and_unserviceable_demand_have_exact_zero_cost(groups):
    _,problem=tiny_problem(groups=groups)
    result=DddIntegratedCpSatOptimizer().solve(problem)
    assert result.proven_optimal
    assert result.validated_upper_bound==0
    assert result.cp_lower_bound==0
    assert result.relative_gap is None


def test_subtick_releases_cannot_silently_change_objective_constant():
    _,problem=tiny_problem(groups=(EanDemandGroup('ab','A','B',0.0000002,1),))
    with pytest.raises(ValueError,match='canonical tick grid'):
        build_ddd_integrated_cp_sat(problem)


def test_boundary_occupancy_cannot_be_omitted_from_seed_or_global_solve():
    _,problem=tiny_problem(horizon=80)
    movement=problem.resolved_trajectory_problem.structural_movement_problem
    generated=DddReferenceTrajectoryGenerator().generate(movement).by_cabin_id[0]
    skip=next(t for t in generated if t.visits[0].decision.value=='skip')
    boundary=DddReferenceResourceOccurrence('exit_switch::A_entry_cw',0,-1,4.0,0.0,4.620070)
    problem=replace(problem,boundary_context=DddFixedKBoundaryContext(resource_occurrences=(boundary,),source='regression'))
    with pytest.raises(ValueError,match='conflict'):
        validate_ddd_cp_sat_incumbent(problem,DddReferenceSolution((skip,)),{},provenance='missing boundary')
    result=DddIntegratedCpSatOptimizer().solve(problem)
    assert result.proven_optimal
    assert result.incumbent.solution.trajectories[0].visits[0].decision.value=='stop'


def test_shortened_visit_domain_is_rejected_before_solve():
    _,problem=tiny_problem()
    artifact=replace(problem.artifact,switch_visits=problem.artifact.switch_visits[:1],
        headway_candidates=tuple(c for c in problem.artifact.headway_candidates if c.visit_index == 0),
        headway_pairs=())
    artifact=replace(artifact,resource_conflict_index=type(artifact.resource_conflict_index).build(
        artifact.movement_network,artifact.headway_checkpoints,artifact.headway_candidates))
    trajectory=EanArtifactToDddMovementProblemAdapter().build_trajectory_problem(artifact)
    problem=replace(problem,artifact=artifact,trajectory_problem=trajectory,
        passenger_build=replace(problem.passenger_build,ride_candidates=()))
    with pytest.raises(ValueError,match='visit bound'):
        build_ddd_integrated_cp_sat(problem)
